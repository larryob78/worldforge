"""
WorldForge -- SetControl
Named lighting and atmosphere presets for the WorldForge pipeline.

Presets override specific fields in the world manifest, letting you
quickly swap the look of a scene without regenerating from scratch.

All presets include cinematically correct depth-of-field settings.
This counteracts Gaussian splat softness -- intentional shallow DoF
makes the inherent density falloff feel like a creative choice, not a flaw.

Usage:
    from worldforge.set_control import apply_preset, list_presets
    manifest = apply_preset(manifest, "golden_dawn")
    manifest = apply_preset(manifest, "blue_hour")
"""

import json
import copy
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SetControlPreset:
    name: str
    description: str
    manifest_overrides: dict
    tags: list = field(default_factory=list)


BUILT_IN_PRESETS = [
    SetControlPreset(
        name="golden_dawn",
        description="Warm golden sunrise, shallow DoF, cinematic",
        tags=["warm", "sunrise", "cinematic", "golden"],
        manifest_overrides={
            "lighting": {
                "mood": "golden_hour",
                "sun_elevation_deg": 8,
                "color_temperature": 3200,
                "fog_color": [0.9, 0.75, 0.5],
            },
            "atmosphere": {"mist": True, "wind_strength": 0.2},
            "camera": {"dof": {"enabled": True, "aperture_fstop": 1.8, "focus_distance_m": 3.0}},
        },
    ),
    SetControlPreset(
        name="golden_hour_dusk",
        description="Last light before sunset, warmer and lower than dawn",
        tags=["warm", "dusk", "sunset", "golden"],
        manifest_overrides={
            "lighting": {
                "mood": "golden_hour",
                "sun_elevation_deg": 5,
                "color_temperature": 2800,
                "fog_color": [0.95, 0.65, 0.4],
            },
            "atmosphere": {"mist": False, "particle_type": "dust", "wind_strength": 0.1},
            "camera": {"dof": {"enabled": True, "aperture_fstop": 1.6, "focus_distance_m": 3.5}},
        },
    ),
    SetControlPreset(
        name="foggy_dawn",
        description="Epic misty morning, mysterious atmosphere",
        tags=["fog", "mystery", "epic", "dawn"],
        manifest_overrides={
            "lighting": {
                "mood": "foggy_dawn",
                "sun_elevation_deg": 15,
                "color_temperature": 5500,
                "fog_color": [0.75, 0.8, 0.85],
            },
            "environment": {"fog_density": 0.4},
            "atmosphere": {"mist": True, "particle_type": "pollen", "wind_strength": 0.15},
            "camera": {"dof": {"enabled": True, "aperture_fstop": 2.8, "focus_distance_m": 5.0}},
        },
    ),
    SetControlPreset(
        name="blue_hour",
        description="Cool twilight, melancholic, cinematic colour grade",
        tags=["cool", "twilight", "moody", "blue"],
        manifest_overrides={
            "lighting": {
                "mood": "blue_hour",
                "sun_elevation_deg": -2,
                "color_temperature": 8000,
                "fog_color": [0.4, 0.5, 0.7],
            },
            "atmosphere": {"mist": True, "particle_type": "none", "wind_strength": 0.05},
            "camera": {"dof": {"enabled": True, "aperture_fstop": 2.0, "focus_distance_m": 4.0}},
        },
    ),
    SetControlPreset(
        name="midday_clear",
        description="Bright clean midday, high contrast, naturalistic",
        tags=["bright", "clean", "midday", "natural"],
        manifest_overrides={
            "lighting": {
                "mood": "midday",
                "sun_elevation_deg": 70,
                "color_temperature": 5800,
                "fog_color": [0.85, 0.9, 0.95],
            },
            "environment": {"fog_density": 0.0},
            "atmosphere": {"mist": False, "particle_type": "none", "wind_strength": 0.3},
            "camera": {"dof": {"enabled": True, "aperture_fstop": 4.0, "focus_distance_m": 6.0}},
        },
    ),
    SetControlPreset(
        name="storm_approaching",
        description="Dark dramatic stormlight, tension building",
        tags=["drama", "storm", "tension", "dark"],
        manifest_overrides={
            "lighting": {
                "mood": "overcast",
                "sun_elevation_deg": 20,
                "color_temperature": 6000,
                "fog_color": [0.4, 0.4, 0.45],
            },
            "environment": {"fog_density": 0.2},
            "atmosphere": {"mist": True, "particle_type": "dust", "wind_strength": 0.8},
            "camera": {"dof": {"enabled": True, "aperture_fstop": 2.8, "focus_distance_m": 5.0}},
        },
    ),
    SetControlPreset(
        name="heavy_fog",
        description="Dense atmospheric fog, dreamlike and immersive",
        tags=["fog", "dream", "immersive", "atmosphere"],
        manifest_overrides={
            "lighting": {
                "mood": "foggy_dawn",
                "sun_elevation_deg": 25,
                "color_temperature": 5800,
                "fog_color": [0.85, 0.85, 0.9],
            },
            "environment": {"fog_density": 0.7},
            "atmosphere": {"mist": True, "particle_type": "none", "wind_strength": 0.05},
            "camera": {"dof": {"enabled": True, "aperture_fstop": 2.8, "focus_distance_m": 5.0}},
        },
    ),
    SetControlPreset(
        name="clear_night",
        description="Dark night, dramatic shadows, wide aperture",
        tags=["night", "dark", "dramatic", "noir"],
        manifest_overrides={
            "lighting": {
                "mood": "night",
                "sun_elevation_deg": -10,
                "color_temperature": 6500,
                "fog_color": [0.05, 0.05, 0.1],
            },
            "atmosphere": {"mist": False, "particle_type": "none", "wind_strength": 0.1},
            "camera": {"dof": {"enabled": True, "aperture_fstop": 1.4, "focus_distance_m": 2.5}},
        },
    ),
    SetControlPreset(
        name="overcast_flat",
        description="Diffuse flat light, clean neutral, documentary look",
        tags=["flat", "neutral", "documentary", "clean"],
        manifest_overrides={
            "lighting": {
                "mood": "overcast",
                "sun_elevation_deg": 45,
                "color_temperature": 6500,
                "fog_color": [0.75, 0.75, 0.75],
            },
            "environment": {"fog_density": 0.05},
            "atmosphere": {"mist": False, "particle_type": "none", "wind_strength": 0.2},
            "camera": {"dof": {"enabled": True, "aperture_fstop": 4.0, "focus_distance_m": 6.0}},
        },
    ),
]

_PRESET_MAP = {p.name: p for p in BUILT_IN_PRESETS}


def list_presets() -> list:
    """Return all available preset names."""
    return [p.name for p in BUILT_IN_PRESETS]


def get_preset(name: str) -> Optional[SetControlPreset]:
    """Get a preset by name. Returns None if not found."""
    return _PRESET_MAP.get(name)


def apply_preset(manifest: dict, preset_name: str, deep_merge: bool = True) -> dict:
    """
    Apply a named preset to a world manifest.
    Returns a new manifest with preset overrides applied.

    deep_merge=True: merges nested dicts (preserves non-overridden fields)
    deep_merge=False: replaces top-level keys entirely
    """
    preset = _PRESET_MAP.get(preset_name)
    if not preset:
        available = ", ".join(list_presets())
        raise ValueError(f"Unknown preset: {preset_name}. Available: {available}")

    result = copy.deepcopy(manifest)

    if deep_merge:
        result = _deep_merge(result, preset.manifest_overrides)
    else:
        result.update(preset.manifest_overrides)

    print(f"   SetControl: applied preset [{preset_name}] -- {preset.description}")
    return result


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge overrides into base dict."""
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


if __name__ == "__main__":
    print("Available presets:")
    for name in list_presets():
        p = get_preset(name)
        print(f"  {name:20s} -- {p.description}")
