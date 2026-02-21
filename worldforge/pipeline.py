"""
WorldForge — Pipeline Orchestrator

Runs the full WorldForge pipeline:
  Stage 1: Scene Decomposition (Claude)
  Stage 2: World Labs Marble (Gaussian splat environment)
  Stage 3: Blender Assembly (DoF + lighting + camera orbit)
  Stage 4: Topaz 4K Upscale
  Stage 5: Luma Labs Cinematic Video
  Stage 6: PersonForge (optional — composite person into world)

Usage:
  python -m worldforge.pipeline --scene "A misty forest at dawn" --fast
  python -m worldforge.pipeline --scene "..." --preset golden_dawn
"""

import os
import json
import argparse
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from worldforge.scene_decomposer import decompose_scene, save_manifest
from worldforge.worldlabs_api import (
    generate_world_from_text,
    generate_world_from_image,
    generate_world_from_multi_image,
    download_world_assets,
    MODEL_FAST,
    MODEL_QUALITY,
)
from worldforge.luma_api import generate_orbit_flythrough
from worldforge.topaz_upscale import upscale_render_for_pipeline
from worldforge.set_control import apply_preset, list_presets


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
@dataclass
class PipelineConfig:
    """Configuration for a WorldForge pipeline run."""
    scene: str                              # Natural language scene description
    output_dir: str = "outputs/worldforge"  # Base output directory
    fast_mode: bool = False                 # Use Marble mini (~45s) vs plus (~5 min)
    preset: Optional[str] = None           # SetControl preset name
    skip_blender: bool = False             # Skip Blender stage (just get World Labs output)
    skip_topaz: bool = False               # Skip Topaz upscale
    skip_luma: bool = False                # Skip Luma video generation
    person_capture_dir: Optional[str] = None  # PersonForge: dir of PLY/images
    world_manifest_path: Optional[str] = None # Load existing manifest (skip Stage 1)
    world_id: Optional[str] = None          # Resume from existing World Labs world


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────
def run_pipeline(config: PipelineConfig) -> dict:
    """
    Run the full WorldForge pipeline.
    Returns a dict of all output paths and metadata.
    """
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "scene": config.scene,
        "output_dir": str(output_dir),
    }

    print("\n" + "=" * 60)
    print("  WORLDFORGE PIPELINE")
    print("=" * 60)

    # ── Stage 1: Scene Decomposition ──────────────────────────────
    print("\n[Stage 1] Scene Decomposition")

    if config.world_manifest_path:
        print(f"  Loading manifest: {config.world_manifest_path}")
        with open(config.world_manifest_path) as f:
            manifest = json.load(f)
    else:
        manifest = decompose_scene(config.scene)

    # Apply SetControl preset if specified
    if config.preset:
        print(f"  Applying preset: {config.preset}")
        manifest = apply_preset(manifest, config.preset)

    manifest_path = output_dir / "world_manifest.json"
    save_manifest(manifest, str(manifest_path))
    results["manifest"] = str(manifest_path)
    results["manifest_data"] = manifest

    world_title = manifest.get("world_title", "WorldForge Scene")
    print(f"  World: {world_title}")

    # ── Stage 2: World Labs Marble ─────────────────────────────────
    print("\n[Stage 2] World Labs Marble")

    if config.world_id:
        print(f"  Resuming from world ID: {config.world_id}")
        # Load world from ID — just download assets
        world = {"id": config.world_id}
    else:
        model = MODEL_FAST if config.fast_mode else MODEL_QUALITY
        text_prompt = manifest.get("world_prompt", manifest.get("environment", {}).get("description", config.scene))

        world = generate_world_from_text(
            display_name=world_title,
            text_prompt=text_prompt,
            model=model,
        )

    world_dir = output_dir / "world_assets"
    quality = "500k" if config.fast_mode else "full_res"
    downloaded = download_world_assets(world, str(world_dir), quality=quality)

    results["world"] = world
    results["world_assets"] = downloaded
    results["world_id"] = world.get("id", "")

    if config.skip_blender:
        print("  [skip_blender=True] Stopping after World Labs.")
        return results

    # ── Stage 3: Blender Assembly ──────────────────────────────────
    print("\n[Stage 3] Blender Assembly")

    glb_path = downloaded.get("collider_glb")
    if not glb_path:
        print("  WARNING: No GLB mesh from World Labs. Skipping Blender stage.")
        config.skip_blender = True
    else:
        render_dir = output_dir / "renders"
        render_dir.mkdir(exist_ok=True)

        blender_script = _generate_blender_script(manifest, glb_path, str(render_dir), config.fast_mode)
        script_path = output_dir / "blender_assembly.py"
        with open(script_path, "w") as f:
            f.write(blender_script)

        print(f"  Running Blender script: {script_path}")
        blender_result = _run_blender(str(script_path))

        results["blender_script"] = str(script_path)
        results["render_dir"] = str(render_dir)

    if config.skip_topaz:
        print("  [skip_topaz=True] Skipping Topaz upscale.")
        results["upscale"] = {"upscaled_frames_dir": str(render_dir), "success": False}
        first_frame = str(sorted(render_dir.glob("*.png"))[0]) if list(render_dir.glob("*.png")) else None
        last_frame = str(sorted(render_dir.glob("*.png"))[-1]) if list(render_dir.glob("*.png")) else None
        results["first_frame"] = first_frame
        results["last_frame"] = last_frame
    else:
        # ── Stage 4: Topaz 4K Upscale ─────────────────────────────
        print("\n[Stage 4] Topaz 4K Upscale")
        upscale_result = upscale_render_for_pipeline(
            render_dir=str(render_dir),
            scale_factor=2 if config.fast_mode else 4,
            model="prob-4",
        )
        results["upscale"] = upscale_result
        results["first_frame"] = upscale_result.get("first_frame")
        results["last_frame"] = upscale_result.get("last_frame")

    if config.skip_luma:
        print("  [skip_luma=True] Skipping Luma video generation.")
        return results

    # ── Stage 5: Luma Labs Cinematic Video ────────────────────────
    print("\n[Stage 5] Luma Labs Cinematic Video")

    first_frame = results.get("first_frame")
    last_frame = results.get("last_frame")

    if not first_frame or not last_frame:
        print("  WARNING: No render frames found. Skipping Luma stage.")
        return results

    mood = manifest.get("lighting", {}).get("mood", "golden_hour")
    video_dir = output_dir / "videos"
    video_dir.mkdir(exist_ok=True)

    video_path = generate_orbit_flythrough(
        world_title=world_title,
        mood=mood,
        first_frame_path=first_frame,
        last_frame_path=last_frame,
        output_dir=str(video_dir),
    )

    results["video"] = video_path
    print(f"\n  Video: {video_path}")

    # ── Stage 6: PersonForge (optional) ──────────────────────────
    if config.person_capture_dir:
        print("\n[Stage 6] PersonForge — Compositing person into world")
        try:
            from worldforge.person_forge import PersonForgeSession
            pano_url = world.get("assets", {}).get("imagery", {}).get("pano_url", "")
            session = PersonForgeSession(
                capture_dir=config.person_capture_dir,
                world_panorama_url=pano_url,
                world_title=world_title,
                output_dir=str(output_dir / "person_forge"),
            )
            person_result = session.run()
            results["person_forge"] = person_result
        except Exception as e:
            print(f"  PersonForge error: {e}")

    print("\n" + "=" * 60)
    print("  WORLDFORGE COMPLETE")
    print("=" * 60)
    _print_summary(results)

    return results


# ─────────────────────────────────────────────
# BLENDER SCRIPT GENERATOR
# ─────────────────────────────────────────────
def _generate_blender_script(manifest: dict, glb_path: str, render_dir: str, fast_mode: bool = False) -> str:
    """Generate a Blender Python script for scene assembly and camera orbit render."""

    lighting = manifest.get("lighting", {})
    camera = manifest.get("camera", {})
    objects = manifest.get("objects", [])

    mood = lighting.get("mood", "golden_hour")
    sun_elevation = lighting.get("sun_elevation_deg", 8)
    sun_azimuth = lighting.get("sun_azimuth_deg", 210)
    color_temp = lighting.get("color_temperature", 3200)
    fog_color = lighting.get("fog_color", [0.8, 0.7, 0.5])

    cam_pos = camera.get("position", [0, -8, 3])
    cam_target = camera.get("target", [0, 0, 1])
    lens_mm = camera.get("lens_mm", 50)
    f_stop = camera.get("f_stop", 2.8)
    focus_distance = camera.get("focus_distance", 5.0)

    # Find hero object for DoF focus target
    hero_objects = [o for o in objects if o.get("is_hero", False)]
    hero_pos = hero_objects[0].get("position", cam_target) if hero_objects else cam_target

    frame_count = 60 if fast_mode else 180
    render_samples = 32 if fast_mode else 128

    # Convert colour temperature to approximate RGB
    def kelvin_to_rgb(k):
        if k <= 3200:   return [1.0, 0.75, 0.45]
        elif k <= 5500: return [1.0, 0.95, 0.85]
        elif k <= 6500: return [0.95, 0.97, 1.0]
        else:           return [0.85, 0.90, 1.0]

    sun_color = kelvin_to_rgb(color_temp)

    script = f"""import bpy
import math
import os

# ── Setup ─────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = {render_samples}
scene.cycles.use_denoising = True
scene.cycles.denoiser = "OPENIMAGEDENOISE"

# ── Import World Labs GLB ─────────────────────
bpy.ops.import_scene.gltf(filepath=r"{glb_path}")

# ── World / Environment ──────────────────────
world = bpy.data.worlds.new("WorldForge_World")
scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = ({fog_color[0]}, {fog_color[1]}, {fog_color[2]}, 1.0)
bg.inputs[1].default_value = 0.3

# ── Sun Light ────────────────────────────────
bpy.ops.object.light_add(type="SUN", location=(0, 0, 10))
sun = bpy.context.active_object
sun.name = "WorldForge_Sun"
sun.data.energy = 5.0
sun.data.color = ({sun_color[0]}, {sun_color[1]}, {sun_color[2]})
sun.rotation_euler = (
    math.radians(90 - {sun_elevation}),
    0,
    math.radians({sun_azimuth})
)

# ── Camera ───────────────────────────────────
bpy.ops.object.camera_add(location=({cam_pos[0]}, {cam_pos[1]}, {cam_pos[2]}))
cam_obj = bpy.context.active_object
cam_obj.name = "WorldForge_Camera"
cam_data = cam_obj.data
cam_data.lens = {lens_mm}

# ── Depth of Field ───────────────────────────
cam_data.dof.use_dof = True
cam_data.dof.aperture_fstop = {f_stop}

# Focus empty at hero object position
bpy.ops.object.empty_add(type="PLAIN_AXES", location=({hero_pos[0]}, {hero_pos[1]}, {hero_pos[2]}))
focus_empty = bpy.context.active_object
focus_empty.name = "WorldForge_FocusTarget"
cam_data.dof.focus_object = focus_empty
cam_data.dof.focus_distance = {focus_distance}

# ── Camera Orbit Path ────────────────────────
bpy.ops.curve.primitive_bezier_circle_add(
    radius=8.0,
    location=({cam_target[0]}, {cam_target[1]}, {cam_pos[2]})
)
orbit_curve = bpy.context.active_object
orbit_curve.name = "WorldForge_OrbitPath"

# Constrain camera to orbit path
follow = cam_obj.constraints.new("FOLLOW_PATH")
follow.target = orbit_curve
follow.use_curve_follow = True

# Track to scene centre
track = cam_obj.constraints.new("TRACK_TO")
bpy.ops.object.empty_add(type="PLAIN_AXES", location=({cam_target[0]}, {cam_target[1]}, {cam_target[2]}))
target_empty = bpy.context.active_object
target_empty.name = "WorldForge_CameraTarget"
track.target = target_empty
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"

# Animate orbit over {frame_count} frames
scene.frame_start = 1
scene.frame_end = {frame_count}
orbit_curve.data.path_duration = {frame_count}
cam_obj.constraints["Follow Path"].offset = 0
cam_obj.constraints["Follow Path"].keyframe_insert("offset", frame=1)
cam_obj.constraints["Follow Path"].offset = -100
cam_obj.constraints["Follow Path"].keyframe_insert("offset", frame={frame_count})

# ── Render Settings ──────────────────────────
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = r"{render_dir}/frame_"

# ── Set Active Camera ────────────────────────
scene.camera = cam_obj

# ── Render Animation ─────────────────────────
print("Rendering {frame_count} frames to: {render_dir}")
bpy.ops.render.render(animation=True)
print("Render complete.")
"""
    return script


def _run_blender(script_path: str) -> subprocess.CompletedProcess:
    """Execute a Blender Python script headlessly."""
    blender_cmd = os.environ.get("BLENDER_PATH", "blender")
    result = subprocess.run(
        [blender_cmd, "--background", "--python", script_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  Blender stderr: {result.stderr[-500:]}")
    return result


def _print_summary(results: dict):
    """Print a summary of pipeline outputs."""
    print(f"  Scene:     {results.get('scene', ''[:60])}")
    print(f"  World ID:  {results.get('world_id', 'N/A')}")
    print(f"  Manifest:  {results.get('manifest', 'N/A')}")
    print(f"  Renders:   {results.get('render_dir', 'N/A')}")
    print(f"  Video:     {results.get('video', 'N/A')}")
    if results.get("world", {}).get("world_marble_url"):",
        print(f"  Marble:    {results['world']['world_marble_url']}")


# ─────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="WorldForge — Natural language to walkable 3D world",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m worldforge.pipeline --scene "A misty Japanese garden at dawn" --fast
  python -m worldforge.pipeline --scene "Futuristic Mars colony" --preset golden_dawn
  python -m worldforge.pipeline --scene "Ancient forest" --skip-luma
  python -m worldforge.pipeline --list-presets
        """
    )
    parser.add_argument("--scene", type=str, help="Natural language scene description")
    parser.add_argument("--fast", action="store_true", help="Fast mode (Marble mini, ~45s, fewer frames)")
    parser.add_argument("--preset", type=str, help="SetControl preset name")
    parser.add_argument("--output-dir", type=str, default="outputs/worldforge", help="Output directory")
    parser.add_argument("--skip-blender", action="store_true", help="Stop after World Labs")
    parser.add_argument("--skip-topaz", action="store_true", help="Skip Topaz upscale")
    parser.add_argument("--skip-luma", action="store_true", help="Skip Luma video")
    parser.add_argument("--manifest", type=str, help="Load existing world manifest JSON")
    parser.add_argument("--world-id", type=str, help="Resume from existing World Labs world ID")
    parser.add_argument("--person-dir", type=str, help="PersonForge: directory of iPhone capture files")
    parser.add_argument("--list-presets", action="store_true", help="List all SetControl presets")
    args = parser.parse_args()

    if args.list_presets:
        print("\nAvailable SetControl presets:")
        for p in list_presets():
            print(f"  {p['name']:25} {p['description']}")
        return

    if not args.scene and not args.manifest:
        parser.error("Provide --scene or --manifest")

    config = PipelineConfig(
        scene=args.scene or "",
        output_dir=args.output_dir,
        fast_mode=args.fast,
        preset=args.preset,
        skip_blender=args.skip_blender,
        skip_topaz=args.skip_topaz,
        skip_luma=args.skip_luma,
        world_manifest_path=args.manifest,
        world_id=args.world_id,
        person_capture_dir=args.person_dir,
    )

    results = run_pipeline(config)
    output_json = Path(config.output_dir) / "pipeline_results.json"
    with open(output_json, "w") as f:
        # Serialize only serialisable parts
        serialisable = {k: v for k, v in results.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
        json.dump(serialisable, f, indent=2)
    print(f"\nResults saved: {output_json}")


if __name__ == "__main__":
    main()
