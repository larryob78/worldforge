"""
WorldForge — Natural language → explorable 3D Gaussian splat worlds.
No 3D modelling required.

Pipeline:
  TEXT PROMPT → Claude (scene manifest) → World Labs (SPZ splat + GLB mesh)
              → Blender (assembly + orbit render) → Topaz (4K upscale)
              → Luma Labs (cinematic video) + gaussian-splats-3d (web viewer)

Quickstart:
    from worldforge.pipeline import run_pipeline, PipelineConfig

    run_pipeline(
        scene="A misty ancient forest at dawn, towering oaks, golden light",
        config=PipelineConfig(fast_mode=True),
    )

Laurence O'Byrne Creative | Private Repository
"""

__version__ = "0.1.0"
__author__ = "Laurence O'Byrne Creative"

from .scene_decomposer import decompose_scene
from .worldlabs_api import (
    generate_world_from_text,
    generate_world_from_image,
    generate_world_from_multi_image,
    generate_world_from_video,
    download_world_assets,
)
from .luma_api import (
    generate_video_from_image,
    generate_orbit_flythrough,
)
from .topaz_upscale import upscale_render_for_pipeline
from .pipeline import run_pipeline, PipelineConfig

__all__ = [
    "decompose_scene",
    "generate_world_from_text",
    "generate_world_from_image",
    "generate_world_from_multi_image",
    "generate_world_from_video",
    "download_world_assets",
    "generate_video_from_image",
    "generate_orbit_flythrough",
    "upscale_render_for_pipeline",
    "run_pipeline",
    "PipelineConfig",
]
