"""
WorldForge -- Topaz Labs Upscale Integration
Uses Topaz Video AI CLI to upscale Blender render frames to 4K.
Best CGI model: prob-4 (Proteus)
Install: https://www.topazlabs.com/topaz-video-ai

In the WorldForge pipeline:
  Stage 4: Blender renders PNG frames at 1080p
  Stage 5: Topaz upscales to 4K
  Stage 6: 4K frames -> PostShot -> unified world splat
  Stage 7: Best frame -> Luma Labs cinematic video
"""

import os
import subprocess
import shutil
from pathlib import Path
from typing import Optional

TOPAZ_CLI_PATHS = [
    "/Applications/Topaz Video AI.app/Contents/MacOS/ffmpeg",
    "C:/Program Files/Topaz Labs/Topaz Video AI/ffmpeg.exe",
    "ffmpeg",
]


def find_topaz_cli() -> Optional[str]:
    """Find the Topaz Video AI ffmpeg binary."""
    for path in TOPAZ_CLI_PATHS:
        if shutil.which(path) or Path(path).exists():
            return path
    return None


def upscale_render_for_pipeline(
    render_dir: str,
    output_dir: Optional[str] = None,
    scale_factor: int = 4,
    model: str = "prob-4",
    input_pattern: str = "frame_*.png",
    fps: float = 24.0,
) -> dict:
    """
    Upscale Blender render frames using Topaz Video AI.

    Args:
        render_dir: Directory containing PNG frames from Blender
        output_dir: Output directory (default: render_dir + "_4k")
        scale_factor: 2 or 4
        model: prob-4 (Proteus) best for CGI, ahq-13 (Artemis HQ) for live action
        fps: Frame rate for video assembly

    Returns dict with:
        upscaled_frames_dir, first_frame, last_frame, hero_frame, frame_count, success
    """
    render_path = Path(render_dir)
    if not output_dir:
        output_dir = str(render_path.parent / (render_path.name + "_4k"))
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    frames = sorted(render_path.glob(input_pattern))
    if not frames:
        frames = sorted(render_path.glob("*.png")) + sorted(render_path.glob("*.jpg"))

    if not frames:
        return {"success": False, "error": "No frames found in " + render_dir}

    print(f"Topaz Upscale -- {len(frames)} frames x{scale_factor} ({model})")

    topaz_cli = find_topaz_cli()
    if topaz_cli:
        result = _upscale_with_topaz(frames, output_path, scale_factor, model, fps, topaz_cli)
    else:
        print("   Topaz not found -- passthrough (no upscale)")
        result = _passthrough_copy(frames, output_path)

    if result["success"]:
        upscaled = sorted(output_path.glob("*.png")) + sorted(output_path.glob("*.jpg"))
        if upscaled:
            result["upscaled_frames_dir"] = str(output_path)
            result["first_frame"] = str(upscaled[0])
            result["last_frame"] = str(upscaled[-1])
            result["hero_frame"] = str(upscaled[len(upscaled) // 2])
            result["frame_count"] = len(upscaled)
            print(f"   Done: {len(upscaled)} frames -> {output_dir}")

    return result


def _upscale_with_topaz(frames, output_path, scale_factor, model, fps, topaz_cli) -> dict:
    """Run Topaz Video AI upscale via ffmpeg CLI."""
    input_dir = frames[0].parent
    input_pat = str(input_dir / "frame_%04d.png")
    output_pat = str(output_path / "frame_%04d.png")

    tvai_filter = (
        f"tvai_up=model={model}:scale={scale_factor}:"
        "w=0:h=0:preblur=0:noise=0:details=0:halo=0:blur=0:compression=0:estimate=20"
    )

    cmd = [topaz_cli, "-i", input_pat, "-vf", tvai_filter,
           "-r", str(fps), "-start_number", "1", output_pat, "-y"]

    print(f"   Running Topaz {model} x{scale_factor}...")
    try:
        subprocess.run(cmd, check=True)
        return {"success": True, "method": "topaz_video_ai", "model": model, "scale": scale_factor}
    except subprocess.CalledProcessError as e:
        print(f"   Topaz failed: {e} -- falling back to passthrough")
        return _passthrough_copy(frames, output_path)


def _passthrough_copy(frames, output_path) -> dict:
    """Copy frames without upscaling (fallback when Topaz not installed)."""
    for i, frame in enumerate(frames):
        shutil.copy2(frame, output_path / f"frame_{i+1:04d}{frame.suffix}")
    return {"success": True, "method": "passthrough", "scale": 1}


if __name__ == "__main__":
    import sys
    render_dir = sys.argv[1] if len(sys.argv) > 1 else "renders/test"
    result = upscale_render_for_pipeline(render_dir)
    print(result)
