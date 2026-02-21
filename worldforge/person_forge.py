"""
WorldForge — PersonForge
Real-person Gaussian splat capture and composition for WorldForge.

The "Superman Move": capture a real person with iPhone, place them into an AI-generated world.

Pipeline:
1. Capture with Polycam (iOS) -> export .ply Gaussian splat
2. Extract reference frame from capture
3. Composite person into World Labs panorama (PIL/Pillow)
4. Two-keyframe Luma Dream Machine technique -> person entrance video

iPhone recommendation: Polycam (photogrammetry mode) or Luma AI app
HUGS (Apple research): github.com/apple/ml-hugs — requires desktop GPU
"""

import os
import json
import subprocess
import base64
import logging
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import requests
from PIL import Image
import numpy as np

LUMA_API_KEY = os.environ.get("LUMA_API_KEY", "")
LUMA_BASE_URL = "https://api.lumalabs.ai/dream-machine/v1"

logger = logging.getLogger("worldforge.personforge")


@dataclass
class PersonForgeConfig:
    project_name: str
    subject_name: str
    world_id: str
    environment_description: str
    world_panorama_path: str
    output_dir: str = "outputs/personforge/"
    capture_method: str = "polycam"   # polycam | luma_app | manual_hugs
    entrance_style: str = "walking"   # walking | running | appearing | turning
    luma_api_key: str = field(default_factory=lambda: os.environ.get("LUMA_API_KEY", ""))
    runpod_api_key: Optional[str] = None
    gpu_available: bool = False


def capture_guide_for_ios(subject_name: str = "You", environment: str = "AI-generated world") -> str:
    """
    Returns step-by-step guide for iPhone 16 Plus Gaussian splat capture.
    Three paths: Polycam (recommended), Luma AI app (free), Manual HUGS (power user).
    """
    guide = f"""
=== PersonForge iPhone Capture Guide ===
Subject: {subject_name} | Environment: {environment}

PATH 1: POLYCAM (Recommended - Best Quality)
App: Polycam (App Store, Pro ~$18/month for PLY export)
1. Open Polycam -> tap + -> Photogrammetry
2. Subject stands still in neutral pose (arms slightly away from body)
3. Walk around subject at 0.8-1.2m distance:
   - Low angle pass (waist height): 30 photos
   - Eye level pass: 30 photos
   - High angle pass (above head): 20 photos
4. Extra orbits around subject's head (5-10)
5. Process -> High Quality -> Export 3D -> PLY (Gaussian Splat)
Output: person_capture.ply (~50-200MB)

PATH 2: LUMA AI APP (Free - Good Quality)
App: Luma AI (App Store, free)
1. Open Luma AI -> Capture -> Object/Person
2. Follow on-screen orbit guide
3. Upload -> Generate 3D -> Export -> Gaussian Splat (.ply)

PATH 3: MANUAL HUGS (Power User - Best Animatable Result)
GitHub: https://github.com/apple/ml-hugs
Requires: Desktop GPU (RTX 3090+)
1. Film 360 video at 4K30fps (rotate subject or walk around them)
2. AirDrop to Mac -> run COLMAP + HUGS training

NEXT STEP after capture:
    from worldforge.person_forge import PersonForgeSession, PersonForgeConfig
    config = PersonForgeConfig(
        project_name="laurence_on_mars",
        subject_name="{subject_name}",
        world_id="8740d813-5ed7-43b1-a5a2-092830af053f",
        environment_description="futuristic Mars colony at dawn",
        world_panorama_path="outputs/mars_colony/world_pano.jpg",
    )
    session = PersonForgeSession(config)
    session.run_full_pipeline("person_capture.ply", world_panorama_url="https://...")
"""
    return guide


def process_hugs_capture(
    video_path: str,
    output_dir: str,
    subject_name: str = "person",
    gpu_available: bool = False,
    runpod_api_key: Optional[str] = None,
) -> Dict:
    """
    Process a monocular iPhone video through the HUGS pipeline.
    Routes to: local GPU / RunPod cloud / frame extraction fallback.
    Returns dict with paths to outputs.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"PersonForge: Processing capture for '{subject_name}' from {video_path}")

    if gpu_available:
        return _hugs_local_gpu(video_path, str(output_path), subject_name)
    elif runpod_api_key:
        return _hugs_runpod(video_path, str(output_path), subject_name, runpod_api_key)
    else:
        return _hugs_fallback_frames(video_path, str(output_path), subject_name)


def _hugs_local_gpu(video_path: str, output_dir: str, subject_name: str) -> Dict:
    """Run HUGS locally with GPU."""
    frames_dir = Path(output_dir) / "frames"
    frames_dir.mkdir(exist_ok=True)
    frame_paths = _extract_frames(video_path, str(frames_dir), fps=2)
    logger.info(f"  Extracted {len(frame_paths)} frames")

    colmap_dir = Path(output_dir) / "colmap"
    hugs_output = Path(output_dir) / "human_splat"

    try:
        subprocess.run([
            "python", "-m", "hugs.extract",
            "--images", str(frames_dir),
            "--output", str(colmap_dir),
        ], check=True)
        subprocess.run([
            "python", "-m", "hugs.train",
            "--colmap", str(colmap_dir),
            "--output", str(hugs_output),
            "--subject_name", subject_name,
        ], check=True)
        return {
            "method": "hugs_local",
            "splat_ply": str(hugs_output / f"{subject_name}.ply"),
            "reference_frame": frame_paths[len(frame_paths) // 2] if frame_paths else None,
            "success": True,
        }
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning(f"  HUGS local failed: {e}. Falling back.")
        return _hugs_fallback_frames(video_path, output_dir, subject_name)


def _hugs_runpod(video_path: str, output_dir: str, subject_name: str, runpod_api_key: str) -> Dict:
    """Submit to RunPod cloud GPU for HUGS processing."""
    logger.info("  Submitting to RunPod for cloud GPU processing...")
    with open(video_path, "rb") as f:
        video_b64 = base64.b64encode(f.read()).decode()

    headers = {"Authorization": f"Bearer {runpod_api_key}", "Content-Type": "application/json"}
    try:
        response = requests.post(
            "https://api.runpod.ai/v2/hugs-worldforge/run",
            json={"input": {"video_base64": video_b64, "subject_name": subject_name, "fps": 2}},
            headers=headers,
        )
        response.raise_for_status()
        job_id = response.json().get("id")
        logger.info(f"  RunPod job: {job_id} — polling (~10-15 min)...")

        import time
        while True:
            time.sleep(30)
            status = requests.get(
                f"https://api.runpod.ai/v2/hugs-worldforge/status/{job_id}",
                headers=headers
            ).json()
            if status.get("status") == "COMPLETED":
                ply_url = status.get("output", {}).get("splat_url")
                if ply_url:
                    ply_path = Path(output_dir) / f"{subject_name}.ply"
                    ply_path.write_bytes(requests.get(ply_url).content)
                    return {"method": "hugs_runpod", "splat_ply": str(ply_path), "job_id": job_id, "success": True}
                break
            elif status.get("status") == "FAILED":
                raise RuntimeError(f"RunPod job failed: {status.get('error')}")
    except Exception as e:
        logger.warning(f"  RunPod failed: {e}. Falling back.")
        return _hugs_fallback_frames(video_path, output_dir, subject_name)


def _hugs_fallback_frames(video_path: str, output_dir: str, subject_name: str) -> Dict:
    """Fallback: extract reference frame for 2D compositing (no GPU needed)."""
    frames_dir = Path(output_dir) / "frames"
    frames_dir.mkdir(exist_ok=True)
    frame_paths = _extract_frames(video_path, str(frames_dir), fps=1)
    reference_frame = frame_paths[len(frame_paths) // 2] if frame_paths else None
    logger.info(f"  Fallback 2D compositing: {len(frame_paths)} frames, best: {reference_frame}")
    return {
        "method": "fallback_frames",
        "splat_ply": None,
        "reference_frame": reference_frame,
        "frames_dir": str(frames_dir),
        "success": reference_frame is not None,
        "note": "No GPU — using 2D compositing from reference frame.",
    }


def _extract_frames(video_path: str, output_dir: str, fps: int = 2) -> List[str]:
    """Extract frames from video using ffmpeg."""
    output_pattern = str(Path(output_dir) / "frame_%04d.jpg")
    try:
        subprocess.run([
            "ffmpeg", "-i", video_path, "-vf", f"fps={fps}", "-q:v", "2", output_pattern, "-y",
        ], check=True, capture_output=True)
        return [str(f) for f in sorted(Path(output_dir).glob("frame_*.jpg"))]
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.warning("  ffmpeg not available")
        return []


def composite_person_into_panorama(
    panorama_path: str,
    person_image_path: str,
    position_x: float = 0.5,
    position_y: float = 0.6,
    scale: float = 1.0,
    lighting_match: bool = True,
    output_path: Optional[str] = None,
) -> str:
    """
    Composite a person cutout into a World Labs panorama.

    Creates the Frame1 image for the Luma two-keyframe technique:
    - Frame0 = panorama URL (empty world)
    - Frame1 = this composite (person present)
    Luma generates smooth entrance motion between them.

    position_x: 0=left, 0.5=centre, 1=right
    position_y: 0=top, 0.6=ground level, 1=bottom
    scale: 1.0=natural standing, 1.2=prominent foreground
    """
    panorama = Image.open(panorama_path).convert("RGBA")
    person = Image.open(person_image_path).convert("RGBA")
    pano_w, pano_h = panorama.size
    person_w, person_h = person.size

    target_height = int(pano_h * 0.30 * scale)
    target_width = int(target_height * (person_w / person_h))
    person_resized = person.resize((target_width, target_height), Image.LANCZOS)

    if lighting_match:
        person_resized = _match_lighting(person_resized, panorama, position_x, position_y)

    paste_x = max(0, min(int(pano_w * position_x - target_width / 2), pano_w - target_width))
    paste_y = max(0, min(int(pano_h * position_y - target_height), pano_h - target_height))

    result = panorama.copy()
    result.paste(person_resized, (paste_x, paste_y), person_resized.split()[3])

    if not output_path:
        output_path = str(Path(panorama_path).parent / "person_composite.jpg")
    result.convert("RGB").save(output_path, quality=95)
    logger.info(f"  Composite saved: {output_path} ({target_width}x{target_height}px at {paste_x},{paste_y})")
    return output_path


def _match_lighting(person: Image.Image, environment: Image.Image, env_x: float, env_y: float) -> Image.Image:
    """Colour-correct person to match environmental lighting at placement point."""
    env_w, env_h = environment.size
    sx = max(0, min(int(env_w * env_x) - 50, env_w - 100))
    sy = max(0, min(int(env_h * env_y) - 50, env_h - 100))
    env_patch = environment.crop((sx, sy, sx + 100, sy + 100))

    avg_env = np.array(env_patch.convert("RGB"), dtype=np.float32).mean(axis=(0, 1))
    avg_person = np.array(person.convert("RGB"), dtype=np.float32).mean(axis=(0, 1))
    correction = np.clip(avg_env / (avg_person + 1e-6), 0.7, 1.4)

    person_rgba = np.array(person, dtype=np.float32)
    person_rgba[:, :, :3] = np.clip(person_rgba[:, :, :3] * correction, 0, 255)
    return Image.fromarray(person_rgba.astype(np.uint8), "RGBA")


def generate_person_entrance_video(
    world_panorama_url: str,
    person_composite_path: str,
    luma_api_key: str = "",
    entrance_style: str = "walking",
    output_dir: str = "outputs/person_videos/",
) -> Dict:
    """
    Generate person entrance video using Luma Dream Machine two-keyframe technique.

    Frame0 = empty world panorama URL (World Labs CDN)
    Frame1 = composite image with person placed in world (base64)
    Luma generates smooth cinematic motion between the two frames.

    entrance_style: walking | appearing | turning | arriving
    """
    api_key = luma_api_key or LUMA_API_KEY
    if not api_key:
        raise ValueError("LUMA_API_KEY required.")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    with open(person_composite_path, "rb") as f:
        frame1_b64 = base64.b64encode(f.read()).decode()

    entrance_prompts = {
        "walking":   "Person walks confidently into the scene from the left, natural stride, photorealistic",
        "appearing": "Person gradually materialises in the environment, mysterious appearance, cinematic",
        "turning":   "Camera slowly reveals person already present, turns naturally to face camera",
        "arriving":  "Person steps forward into the scene, looks around, takes in the environment",
    }
    prompt = (
        f"Cinematic wide shot. {entrance_prompts.get(entrance_style, entrance_prompts['walking'])}. "
        "Photorealistic. Natural lighting. Smooth camera. High production value."
    )

    payload = {
        "prompt": prompt,
        "aspect_ratio": "16:9",
        "loop": False,
        "keyframes": {
            "frame0": {"type": "image", "url": world_panorama_url},
            "frame1": {"type": "image", "url": f"data:image/jpeg;base64,{frame1_b64}"},
        },
    }

    logger.info(f"PersonForge: Generating entrance video (style={entrance_style})")
    response = requests.post(f"{LUMA_BASE_URL}/generations", headers=headers, json=payload)
    response.raise_for_status()
    generation_id = response.json()["id"]
    logger.info(f"  Generation ID: {generation_id}")

    import time
    while True:
        gen = requests.get(f"{LUMA_BASE_URL}/generations/{generation_id}", headers=headers).json()
        state = gen.get("state", "")
        if state == "completed":
            video_url = gen.get("assets", {}).get("video")
            if video_url:
                output_path = Path(output_dir)
                output_path.mkdir(parents=True, exist_ok=True)
                out_file = output_path / f"person_entrance_{entrance_style}.mp4"
                video_data = requests.get(video_url, stream=True)
                video_data.raise_for_status()
                with open(out_file, "wb") as f:
                    for chunk in video_data.iter_content(chunk_size=8192):
                        f.write(chunk)
                logger.info(f"Video saved: {out_file}")
                return {"video_path": str(out_file), "generation_id": generation_id, "entrance_style": entrance_style, "success": True}
        elif state == "failed":
            raise RuntimeError(f"Luma failed: {gen.get('failure_reason', 'Unknown')}")
        else:
            time.sleep(10)


class PersonForgeSession:
    """
    Manages a complete PersonForge session — iPhone capture to world entrance video.
    Tracks state in personforge_state.json for resumable sessions.
    """

    def __init__(self, config: PersonForgeConfig):
        self.config = config
        self.output_dir = Path(config.output_dir) / config.project_name
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.output_dir / "personforge_state.json"
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        if self.state_path.exists():
            with open(self.state_path) as f:
                return json.load(f)
        return {
            "project_name": self.config.project_name,
            "subject_name": self.config.subject_name,
            "world_id": self.config.world_id,
            "created_at": datetime.now().isoformat(),
            "stages": {},
        }

    def _save_state(self):
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def print_capture_guide(self):
        print(capture_guide_for_ios(self.config.subject_name, self.config.environment_description))

    def from_capture(self, video_or_ply_path: str) -> "PersonForgeSession":
        """Process capture (video or pre-exported PLY) into session assets."""
        if video_or_ply_path.endswith(".ply"):
            self.state["stages"]["capture"] = {
                "method": "polycam_ply", "splat_ply": video_or_ply_path,
                "reference_frame": None, "success": True,
            }
        else:
            result = process_hugs_capture(
                video_path=video_or_ply_path,
                output_dir=str(self.output_dir / "capture"),
                subject_name=self.config.subject_name,
                gpu_available=self.config.gpu_available,
                runpod_api_key=self.config.runpod_api_key,
            )
            self.state["stages"]["capture"] = result
        self._save_state()
        return self

    def place_in_world(
        self,
        person_image_path: Optional[str] = None,
        position_x: float = 0.5,
        position_y: float = 0.6,
        scale: float = 1.0,
    ) -> "PersonForgeSession":
        """Composite person into the world panorama."""
        if not person_image_path:
            person_image_path = self.state.get("stages", {}).get("capture", {}).get("reference_frame")
            if not person_image_path:
                raise ValueError("No person image. Run from_capture() first.")

        composite_dir = self.output_dir / "composite"
        composite_dir.mkdir(exist_ok=True)
        composite_path = composite_dir / f"{self.config.subject_name}_in_world.jpg"

        result_path = composite_person_into_panorama(
            panorama_path=self.config.world_panorama_path,
            person_image_path=person_image_path,
            position_x=position_x, position_y=position_y, scale=scale,
            output_path=str(composite_path),
        )
        self.state["stages"]["placement"] = {
            "composite_path": result_path,
            "position": {"x": position_x, "y": position_y, "scale": scale},
            "success": True,
        }
        self._save_state()
        logger.info(f"Placed {self.config.subject_name} in {self.config.environment_description}")
        return self

    def generate_entrance_video(
        self,
        world_panorama_url: Optional[str] = None,
        entrance_style: Optional[str] = None,
    ) -> "PersonForgeSession":
        """Generate entrance video using Luma two-keyframe technique."""
        composite_path = self.state.get("stages", {}).get("placement", {}).get("composite_path")
        if not composite_path:
            raise ValueError("Run place_in_world() before generating entrance video.")
        if not world_panorama_url:
            raise ValueError(
                "world_panorama_url required. "
                "Get from world['assets']['imagery']['pano_url'] in World Labs API response."
            )
        result = generate_person_entrance_video(
            world_panorama_url=world_panorama_url,
            person_composite_path=composite_path,
            luma_api_key=self.config.luma_api_key,
            entrance_style=entrance_style or self.config.entrance_style,
            output_dir=str(self.output_dir / "videos"),
        )
        self.state["stages"]["entrance_video"] = result
        self._save_state()
        return self

    def run_full_pipeline(
        self,
        video_or_ply_path: str,
        world_panorama_url: str,
        person_image_path: Optional[str] = None,
        position_x: float = 0.5,
        position_y: float = 0.6,
        scale: float = 1.0,
    ) -> str:
        """Run complete pipeline: capture -> composite -> entrance video. Returns video path."""
        self.from_capture(video_or_ply_path)
        self.place_in_world(person_image_path=person_image_path, position_x=position_x, position_y=position_y, scale=scale)
        self.generate_entrance_video(world_panorama_url=world_panorama_url)
        return self.get_summary()

    def get_summary(self) -> str:
        stages = self.state.get("stages", {})
        video_path = stages.get("entrance_video", {}).get("video_path", "Not generated yet")
        print(f"""
=== PersonForge Session: {self.config.project_name} ===
Subject:     {self.config.subject_name}
World ID:    {self.config.world_id}
Environment: {self.config.environment_description}

Capture:  {'OK' if stages.get('capture', {}).get('success') else 'pending'}  [{stages.get('capture', {}).get('method', '-')}]
Composite: {'OK' if stages.get('placement', {}).get('success') else 'pending'}
Video:     {'OK' if stages.get('entrance_video', {}).get('success') else 'pending'}

Output: {video_path}
State:  {self.state_path}
""")
        return video_path


if __name__ == "__main__":
    print(capture_guide_for_ios(
        subject_name="Laurence",
        environment="Olympus Station - Futuristic Mars Colony at Dawn",
    ))
