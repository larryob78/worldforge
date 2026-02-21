"""
WorldForge -- World Labs API Integration
Marble 0.1 spatial intelligence model

Inputs:  text prompt / image / multi-image / video
Outputs: SPZ Gaussian splats (100k / 500k / full_res)
         GLB collider mesh (imports directly into Blender)
         Panorama image
         AI-generated scene caption

Docs: https://docs.worldlabs.ai/api
"""

import os
import time
import requests
import json
from pathlib import Path
from typing import Optional

WORLDLABS_API_KEY = os.environ.get("WORLDLABS_API_KEY", "")
BASE_URL = "https://api.worldlabs.ai/marble/v1"

HEADERS = {
    "Content-Type": "application/json",
    "WLT-Api-Key": WORLDLABS_API_KEY,
}

MODEL_QUALITY = "Marble 0.1-plus"   # ~5 min, best quality -- use for final delivery
MODEL_FAST    = "Marble 0.1-mini"   # ~30-45s -- use for iteration and testing


def generate_world_from_text(
    display_name: str,
    text_prompt: str,
    model: str = MODEL_QUALITY,
    poll_interval: int = 15,
) -> dict:
    """
    Generate a World Labs spatial world from a text description.
    Returns the completed world object with all asset URLs.
    Blocks until generation is complete (~5 min for plus, ~45s for mini).

    Usage:
        world = generate_world_from_text(
            display_name="Misty Ancient Forest",
            text_prompt="A primordial forest at dawn, ancient oaks, low mist...",
            model=MODEL_FAST
        )
        print(world["assets"]["splats"]["spz_urls"]["full_res"])
    """
    print(f"\nWorld Labs -- Generating world: '{display_name}'")
    print(f"   Model: {model}")
    print(f"   Prompt: {text_prompt[:80]}...")

    payload = {
        "display_name": display_name,
        "model": model,
        "world_prompt": {
            "type": "text",
            "text_prompt": text_prompt,
        }
    }

    response = requests.post(f"{BASE_URL}/worlds:generate", headers=HEADERS, json=payload)
    response.raise_for_status()
    operation = response.json()
    operation_id = operation["operation_id"]
    print(f"   Operation ID: {operation_id}")
    return _poll_operation(operation_id, poll_interval)


def generate_world_from_image(
    display_name: str,
    image_url: str = None,
    image_path: str = None,
    text_prompt: str = None,
    model: str = MODEL_QUALITY,
    is_pano: bool = False,
    poll_interval: int = 15,
) -> dict:
    """
    Generate a World Labs spatial world from a single image.
    Pass either image_url (public URL) or image_path (local file).
    text_prompt is optional -- World Labs will auto-caption if omitted.

    Key integration with WorldForge:
    - Generate a hero concept image with SANA or Flux
    - Feed that image here -> World Labs generates a navigable 3D world
    - Download the SPZ splat + GLB mesh for Blender assembly
    """
    print(f"\nWorld Labs -- Generating world from image: '{display_name}'")

    if image_path:
        print("   Uploading local image...")
        media_asset_id = _upload_media_asset(image_path, kind="image")
        image_prompt = {"source": "media_asset", "media_asset_id": media_asset_id, "is_pano": is_pano}
    elif image_url:
        image_prompt = {"source": "uri", "uri": image_url, "is_pano": is_pano}
    else:
        raise ValueError("Provide either image_url or image_path")

    world_prompt = {"type": "image", "image_prompt": image_prompt}
    if text_prompt:
        world_prompt["text_prompt"] = text_prompt

    payload = {"display_name": display_name, "model": model, "world_prompt": world_prompt}
    response = requests.post(f"{BASE_URL}/worlds:generate", headers=HEADERS, json=payload)
    response.raise_for_status()
    return _poll_operation(response.json()["operation_id"], poll_interval)


def generate_world_from_multi_image(
    display_name: str,
    images: list,
    text_prompt: str = None,
    model: str = MODEL_QUALITY,
    poll_interval: int = 15,
) -> dict:
    """
    Generate from multiple images of the same scene at different angles.

    images format:
        [
            {"azimuth": 0,   "url": "https://...front.jpg"},
            {"azimuth": 90,  "url": "https://...right.jpg"},
            {"azimuth": 180, "url": "https://...back.jpg"},
            {"azimuth": 270, "url": "https://...left.jpg"},
        ]

    azimuth: 0=front, 90=right, 180=back, 270=left

    Best input for photogrammetry-style world generation --
    4 iPhone photos of a real location gives a faithful Gaussian splat.
    """
    print(f"\nWorld Labs -- Generating world from {len(images)} images: '{display_name}'")

    multi_image_prompt = []
    for img in images:
        if "url" in img:
            content = {"source": "uri", "uri": img["url"]}
        elif "path" in img:
            asset_id = _upload_media_asset(img["path"], kind="image")
            content = {"source": "media_asset", "media_asset_id": asset_id}
        else:
            raise ValueError("Each image needs 'url' or 'path'")
        multi_image_prompt.append({"azimuth": img.get("azimuth", 0), "content": content})

    world_prompt = {"type": "multi-image", "multi_image_prompt": multi_image_prompt}
    if text_prompt:
        world_prompt["text_prompt"] = text_prompt

    payload = {"display_name": display_name, "model": model, "world_prompt": world_prompt}
    response = requests.post(f"{BASE_URL}/worlds:generate", headers=HEADERS, json=payload)
    response.raise_for_status()
    return _poll_operation(response.json()["operation_id"], poll_interval)


def generate_world_from_video(
    display_name: str,
    video_url: str = None,
    video_path: str = None,
    text_prompt: str = None,
    model: str = MODEL_QUALITY,
    poll_interval: int = 15,
) -> dict:
    """
    Generate a World Labs spatial world from a video.
    Walk through a real location with your phone -> navigable 3D splat.
    Supported formats: mp4, mov, mkv
    """
    print(f"\nWorld Labs -- Generating world from video: '{display_name}'")

    if video_path:
        print("   Uploading local video...")
        media_asset_id = _upload_media_asset(video_path, kind="video")
        video_prompt = {"source": "media_asset", "media_asset_id": media_asset_id}
    elif video_url:
        video_prompt = {"source": "uri", "uri": video_url}
    else:
        raise ValueError("Provide either video_url or video_path")

    world_prompt = {"type": "video", "video_prompt": video_prompt}
    if text_prompt:
        world_prompt["text_prompt"] = text_prompt

    payload = {"display_name": display_name, "model": model, "world_prompt": world_prompt}
    response = requests.post(f"{BASE_URL}/worlds:generate", headers=HEADERS, json=payload)
    response.raise_for_status()
    return _poll_operation(response.json()["operation_id"], poll_interval)


def download_world_assets(world: dict, output_dir: str, quality: str = "full_res") -> dict:
    """
    Download all assets from a completed World Labs world.
    quality: "100k" | "500k" | "full_res"
    - "100k"     -- smallest, fastest to view, use for quick browser tests
    - "500k"     -- balanced, good for client demos
    - "full_res" -- maximum quality, use for final delivery
    Returns dict of local file paths.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    assets = world.get("assets", {})
    world_id = world.get("id", "world")
    downloaded = {}

    print(f"\nDownloading world assets to: {output_dir}")

    splat_urls = assets.get("splats", {}).get("spz_urls", {})
    if quality in splat_urls:
        splat_path = output_path / f"{world_id}_{quality}.spz"
        _download_file(splat_urls[quality], str(splat_path))
        downloaded["splat_spz"] = str(splat_path)
        print(f"   Splat ({quality}): {splat_path.name}")

    mesh_url = assets.get("mesh", {}).get("collider_mesh_url")
    if mesh_url:
        mesh_path = output_path / f"{world_id}_collider.glb"
        _download_file(mesh_url, str(mesh_path))
        downloaded["collider_glb"] = str(mesh_path)
        print(f"   Mesh (GLB): {mesh_path.name}")

    pano_url = assets.get("imagery", {}).get("pano_url")
    if pano_url:
        pano_path = output_path / f"{world_id}_pano.jpg"
        _download_file(pano_url, str(pano_path))
        downloaded["panorama"] = str(pano_path)
        print(f"   Panorama: {pano_path.name}")

    thumb_url = assets.get("thumbnail_url")
    if thumb_url:
        thumb_path = output_path / f"{world_id}_thumbnail.jpg"
        _download_file(thumb_url, str(thumb_path))
        downloaded["thumbnail"] = str(thumb_path)

    caption = assets.get("caption", "")
    if caption:
        caption_path = output_path / f"{world_id}_caption.txt"
        caption_path.write_text(caption)
        downloaded["caption"] = str(caption_path)

    print(f"\n   Marble viewer: {world.get('world_marble_url', '')}")
    return downloaded


def _poll_operation(operation_id: str, poll_interval: int = 15) -> dict:
    """Poll an operation until complete. Returns the world object."""
    print(f"Polling operation {operation_id}...")
    print("   (~5 min for Marble 0.1-plus, ~45s for mini)")

    while True:
        response = requests.get(f"{BASE_URL}/operations/{operation_id}", headers=HEADERS)
        response.raise_for_status()
        op = response.json()

        if op.get("done"):
            if op.get("error"):
                raise RuntimeError(f"World generation failed: {op['error']}")
            world = op["response"]
            print(f"World generated: {world.get('display_name', 'Untitled')}")
            print(f"   ID: {world.get('id')}")
            print(f"   Marble URL: {world.get('world_marble_url')}")
            return world

        status = op.get("metadata", {}).get("progress", {}).get("status", "IN_PROGRESS")
        print(f"   Status: {status} -- waiting {poll_interval}s...")
        time.sleep(poll_interval)


def _upload_media_asset(file_path: str, kind: str = "image") -> str:
    """Upload a local file as a World Labs media asset. Returns asset ID."""
    path = Path(file_path)
    prep_response = requests.post(
        f"{BASE_URL}/media-assets:prepare_upload",
        headers=HEADERS,
        json={"file_name": path.name, "kind": kind, "extension": path.suffix.lstrip(".")},
    )
    prep_response.raise_for_status()
    prep = prep_response.json()
    asset_id = prep["media_asset"]["id"]
    upload_url = prep["upload_info"]["upload_url"]
    required_headers = prep["upload_info"].get("required_headers", {})

    with open(file_path, "rb") as f:
        requests.put(upload_url, headers=required_headers, data=f).raise_for_status()

    print(f"   Uploaded: {path.name} -> asset ID: {asset_id}")
    return asset_id


def _download_file(url: str, dest_path: str):
    """Download a file from URL to local path."""
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


if __name__ == "__main__":
    if not WORLDLABS_API_KEY:
        print("Set WORLDLABS_API_KEY environment variable")
        exit(1)

    world = generate_world_from_text(
        display_name="WorldForge Test -- Ancient Forest",
        text_prompt="A misty ancient forest at dawn, towering oaks, mossy boulders, golden light through canopy",
        model=MODEL_FAST,
    )
    files = download_world_assets(world, output_dir="./worldlabs_output", quality="500k")
    print(f"Downloaded: {json.dumps(files, indent=2)}")
