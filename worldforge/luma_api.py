"""
WorldForge -- Luma Labs API Integration
Dream Machine -- cinematic video generation from images/frames

In WorldForge, Luma takes the Topaz-upscaled 4K render frames
from Blender and turns them into a cinematic flythrough video
for client delivery.

Docs: https://lumalabs.ai/dream-machine/api
Get API key: https://lumalabs.ai/dream-machine/api/keys
"""

import os
import time
import requests
import json
from pathlib import Path
from typing import Optional

LUMA_API_KEY = os.environ.get("LUMA_API_KEY", "")
BASE_URL = "https://api.lumalabs.ai/dream-machine/v1"

HEADERS = {
    "Authorization": f"Bearer {LUMA_API_KEY}",
    "Content-Type": "application/json",
}


def generate_video_from_image(
    prompt: str,
    image_path: str = None,
    image_url: str = None,
    end_image_path: str = None,
    end_image_url: str = None,
    aspect_ratio: str = "16:9",
    loop: bool = False,
    poll_interval: int = 10,
) -> dict:
    """
    Generate a cinematic video from a start (and optionally end) keyframe image.

    In WorldForge:
    - start image = first frame of Blender camera orbit (Topaz 4K upscaled)
    - end image   = last frame of orbit (optional, creates smooth loop)
    - prompt      = atmospheric description for motion and style

    Returns the completed generation with video download URL.
    """
    print(f"\nLuma Labs -- Generating video")
    print(f"   Prompt: {prompt[:80]}...")

    keyframes = {}

    if image_path:
        start_url = _upload_to_luma(image_path)
        keyframes["frame0"] = {"type": "image", "url": start_url}
    elif image_url:
        keyframes["frame0"] = {"type": "image", "url": image_url}

    if end_image_path:
        end_url = _upload_to_luma(end_image_path)
        keyframes["frame1"] = {"type": "image", "url": end_url}
    elif end_image_url:
        keyframes["frame1"] = {"type": "image", "url": end_image_url}

    payload = {"prompt": prompt, "aspect_ratio": aspect_ratio, "loop": loop}
    if keyframes:
        payload["keyframes"] = keyframes

    response = requests.post(f"{BASE_URL}/generations", headers=HEADERS, json=payload)
    response.raise_for_status()
    generation = response.json()
    print(f"   Generation ID: {generation['id']}")
    return _poll_generation(generation["id"], poll_interval)


def generate_video_from_text(
    prompt: str,
    aspect_ratio: str = "16:9",
    poll_interval: int = 10,
) -> dict:
    """
    Generate video from a text prompt only (no keyframe images).
    Faster but less controlled. Good for quick atmospheric tests.
    """
    print(f"\nLuma Labs -- Text-to-video: '{prompt[:60]}...'")
    response = requests.post(
        f"{BASE_URL}/generations",
        headers=HEADERS,
        json={"prompt": prompt, "aspect_ratio": aspect_ratio},
    )
    response.raise_for_status()
    return _poll_generation(response.json()["id"], poll_interval)


def extend_video(generation_id: str, prompt: str, poll_interval: int = 10) -> dict:
    """
    Extend an existing Luma generation to create longer footage.
    Use to build a longer cinematic sequence from multiple WorldForge shots.
    """
    print(f"\nLuma Labs -- Extending video {generation_id}")
    response = requests.post(
        f"{BASE_URL}/generations",
        headers=HEADERS,
        json={
            "prompt": prompt,
            "keyframes": {"frame0": {"type": "generation", "id": generation_id}}
        }
    )
    response.raise_for_status()
    return _poll_generation(response.json()["id"], poll_interval)


def download_video(generation: dict, output_dir: str, filename: str = None) -> str:
    """
    Download the completed video to a local file.
    Returns the local file path.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    video_url = generation.get("assets", {}).get("video")
    if not video_url:
        raise ValueError("No video URL in generation response")

    gen_id = generation.get("id", "video")
    out_file = output_path / (filename or f"worldforge_{gen_id}.mp4")

    print(f"Downloading video: {out_file.name}")
    response = requests.get(video_url, stream=True)
    response.raise_for_status()
    with open(out_file, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"Video saved: {out_file}")
    return str(out_file)


def generate_orbit_flythrough(
    world_title: str,
    mood: str,
    first_frame_path: str,
    last_frame_path: str,
    output_dir: str,
) -> str:
    """
    WorldForge-specific helper: generate a cinematic orbit flythrough video.

    Takes the first and last frames of a Blender orbit render
    (after Topaz 4K upscaling) and generates a smooth cinematic video.

    first_frame_path / last_frame_path: Topaz-upscaled 4K PNG files
    Returns: local path to downloaded .mp4 video
    """
    mood_prompts = {
        "golden_hour":  "Slow cinematic camera orbit, warm golden light, shallow depth of field, gentle lens flare, cinematic",
        "foggy_dawn":   "Slow ethereal camera arc through morning mist, cool blue-green light, atmospheric haze, cinematic",
        "blue_hour":    "Slow moody camera orbit, cool blue twilight, subtle lens bokeh, cinematic colour grade",
        "night":        "Slow mysterious camera sweep, deep shadows, dramatic point light sources, cinematic noir",
        "overcast":     "Slow methodical camera orbit, diffuse neutral light, clean cinematic look, documentary style",
        "midday":       "Slow confident camera arc, high contrast shadows, clear sky, cinematic naturalistic",
    }

    prompt = mood_prompts.get(mood, "Slow cinematic camera orbit, beautiful lighting, photorealistic, 8K cinematic")
    prompt = f"{prompt}. Scene: {world_title}."

    generation = generate_video_from_image(
        prompt=prompt,
        image_path=first_frame_path,
        end_image_path=last_frame_path,
        aspect_ratio="16:9",
        loop=False,
    )

    return download_video(
        generation,
        output_dir=output_dir,
        filename=f"{world_title.replace(' ', '_').lower()}_flythrough.mp4",
    )


def _upload_to_luma(image_path: str) -> str:
    """
    Upload a local image to a publicly accessible URL for Luma.
    Note: Luma requires public URLs.
    For production WorldForge, use S3/GCS/Cloudflare R2.
    For quick testing, use a public image URL directly.
    """
    raise NotImplementedError(
        f"To use local files with Luma, upload '{image_path}' to a public URL first.\n"
        "Options:\n"
        "  - AWS S3 presigned URL\n"
        "  - Cloudflare R2\n"
        "  - imgbb.com API (free, quick for testing)\n"
        "Then call generate_video_from_image(image_url='https://...')"
    )


def _poll_generation(generation_id: str, poll_interval: int = 10) -> dict:
    """Poll a Luma generation until complete."""
    print(f"Generating video... (typically 2-4 minutes)")

    while True:
        response = requests.get(f"{BASE_URL}/generations/{generation_id}", headers=HEADERS)
        response.raise_for_status()
        gen = response.json()
        state = gen.get("state", "")

        if state == "completed":
            print(f"Video ready!")
            return gen
        elif state == "failed":
            raise RuntimeError(f"Luma generation failed: {gen.get('failure_reason', 'Unknown error')}")
        else:
            print(f"   State: {state} -- waiting {poll_interval}s...")
            time.sleep(poll_interval)


if __name__ == "__main__":
    if not LUMA_API_KEY:
        print("Set LUMA_API_KEY environment variable")
        exit(1)

    gen = generate_video_from_text(
        prompt="Slow cinematic camera orbit through a misty ancient forest at dawn, golden light, photorealistic",
        aspect_ratio="16:9",
    )
    video_path = download_video(gen, output_dir="./luma_output")
    print(f"Video saved to: {video_path}")
