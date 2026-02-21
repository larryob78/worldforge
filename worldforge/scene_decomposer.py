"""
WorldForge -- Scene Decomposer
Uses Claude API to convert a natural language scene description
into a structured world manifest JSON.
"""

import os
import json
import re
from typing import Optional
import anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SYSTEM_PROMPT = """You are a world-building assistant for the WorldForge pipeline.
Your job is to decompose a natural language scene description into a structured
JSON world manifest that drives Gaussian splat world generation.
Always return valid JSON only. No markdown, no explanation -- just the JSON object."""

MANIFEST_SCHEMA_PROMPT = """Generate a world manifest JSON with this exact schema:
{
  "world_title": "Short descriptive title (3-6 words)",
  "world_prompt": "Rich text prompt for World Labs Marble. Use the formula: [time of day] + [weather/atmosphere] + [primary biome/setting] + [hero objects] + [mood adjective]. 50-100 words.",
  "environment": {"ground_type": "grass|sand|rock|snow|mud|concrete|water|dirt", "fog_density": 0.0, "ambient_occlusion": true},
  "objects": [{"name": "object_name", "trellis_prompt": "5-part: [type], [material], [age/condition], [scale], [render style]", "position": [0,0,0], "scale": 1.0, "is_hero": true}],
  "lighting": {"mood": "golden_hour|foggy_dawn|blue_hour|night|overcast|midday", "sun_elevation_deg": 8, "color_temperature": 3200, "fog_color": [0.8, 0.7, 0.6]},
  "camera": {"position": [0, 1.7, -5], "target": [0, 1, 0], "lens_mm": 35, "f_stop": 2.8, "path": "slow_arc_360|dolly_forward|crane_up|push_in_hold", "dof": {"enabled": true, "aperture_fstop": 2.8, "focus_distance_m": 5.0}},
  "atmosphere": {"mist": true, "particle_type": "dust|pollen|snow|rain|embers|none", "wind_strength": 0.3}
}
Rules:
- objects: 5-8 max. 2-3 TRELLIS heroes (is_hero: true) + 3-5 World Labs fills.
- lighting.mood must match camera.dof.aperture_fstop: golden_hour->f/1.8, foggy_dawn->f/2.8, blue_hour->f/2.0, night->f/1.4, overcast->f/4.0, midday->f/4.0
- position: [x, y, z] Blender coordinates (y=forward, z=up)
- scale: relative to 1.8m human (1.0=normal, 2.0=double)"""


def decompose_scene(
    scene_description: str,
    client: Optional[anthropic.Anthropic] = None,
    model: str = "claude-sonnet-4-6",
) -> dict:
    """
    Decompose a natural language scene description into a world manifest.

    Args:
        scene_description: Plain English description of the desired world
        client: Anthropic client (created from env var if not provided)
        model: Claude model to use

    Returns:
        dict: Validated world manifest JSON

    Example:
        manifest = decompose_scene(
            "A futuristic Mars colony at dawn, habitat domes, red dust plains"
        )
    """
    if not client:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print(f"\nScene Decomposer -- Generating world manifest")
    print(f"   Scene: {scene_description[:80]}...")

    user_message = f"{MANIFEST_SCHEMA_PROMPT}\n\nScene description:\n{scene_description}"

    message = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()

    # Extract JSON: find first { and last }
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned invalid JSON: {e}\nRaw: {raw[:200]}")

    manifest = _validate_and_fill_defaults(manifest, scene_description)

    print(f"   World: {manifest.get('world_title', 'Untitled')}")
    print(f"   Objects: {len(manifest.get('objects', []))}")
    print(f"   Mood: {manifest.get('lighting', {}).get('mood', 'unknown')}")

    return manifest


def _validate_and_fill_defaults(manifest: dict, scene_description: str) -> dict:
    """Fill missing fields with sensible defaults."""
    if "world_title" not in manifest:
        manifest["world_title"] = scene_description[:40].title()
    if "world_prompt" not in manifest:
        manifest["world_prompt"] = scene_description
    if "environment" not in manifest:
        manifest["environment"] = {"ground_type": "grass", "fog_density": 0.1, "ambient_occlusion": True}
    if "objects" not in manifest:
        manifest["objects"] = []
    if "lighting" not in manifest:
        manifest["lighting"] = {"mood": "golden_hour", "sun_elevation_deg": 8, "color_temperature": 3200, "fog_color": [0.8, 0.7, 0.6]}

    # Ensure camera DoF
    if "camera" not in manifest:
        manifest["camera"] = {}
    cam = manifest["camera"]
    if "dof" not in cam:
        mood = manifest.get("lighting", {}).get("mood", "golden_hour")
        dof_defaults = {
            "golden_hour": {"aperture_fstop": 1.8, "focus_distance_m": 3.0},
            "foggy_dawn":  {"aperture_fstop": 2.8, "focus_distance_m": 5.0},
            "blue_hour":   {"aperture_fstop": 2.0, "focus_distance_m": 4.0},
            "night":       {"aperture_fstop": 1.4, "focus_distance_m": 2.5},
            "overcast":    {"aperture_fstop": 4.0, "focus_distance_m": 6.0},
            "midday":      {"aperture_fstop": 4.0, "focus_distance_m": 6.0},
        }
        dof = dof_defaults.get(mood, {"aperture_fstop": 2.8, "focus_distance_m": 5.0})
        cam["dof"] = {"enabled": True, **dof}

    if "atmosphere" not in manifest:
        manifest["atmosphere"] = {"mist": False, "particle_type": "none", "wind_strength": 0.1}

    if len(manifest["objects"]) > 8:
        manifest["objects"] = manifest["objects"][:8]

    return manifest


def save_manifest(manifest: dict, output_path: str) -> str:
    """Save world manifest to a JSON file."""
    import os
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"   Manifest saved: {output_path}")
    return output_path


def load_manifest(manifest_path: str) -> dict:
    """Load a world manifest from a JSON file."""
    with open(manifest_path) as f:
        return json.load(f)


if __name__ == "__main__":
    test_scene = (
        "Olympus Station -- a futuristic Mars colony at dawn. "
        "Habitat domes cluster on red dust plains, a pressurised greenhouse glows warm amber, "
        "solar panel arrays catch the first light. Olympus Mons silhouette on the horizon. "
        "Thin atmosphere, dust haze, epic and lonely."
    )
    manifest = decompose_scene(test_scene)
    print("\n" + "="*60)
    print(json.dumps(manifest, indent=2))
    save_manifest(manifest, "outputs/worldforge-tests/mars_colony/world_manifest.json")
