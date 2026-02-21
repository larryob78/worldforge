# WorldForge

> *"Text prompt or 4 iPhone photos → walkable 3D Gaussian splat world → director approval in hours, not weeks. Nobody has assembled this pipeline."*

## What Is WorldForge?

WorldForge is the first pipeline to combine World Labs Marble (Gaussian splat environment generation), Microsoft TRELLIS (hero 3D object generation), Blender (scene assembly), Topaz Labs 4K (upscale), and Luma Labs Dream Machine (cinematic video) into a single, natural-language-driven workflow.

## Quick Start

```bash
export WORLDLABS_API_KEY=your_key_here
export LUMA_API_KEY=your_key_here
export ANTHROPIC_API_KEY=your_key_here

# Fast draft (~45 seconds)
python -m worldforge.pipeline --scene "A misty ancient forest at dawn" --fast

# Quality render (~5 minutes)
python -m worldforge.pipeline --scene "A misty ancient forest at dawn"
```

## Pipeline Stages

1. SCENE DECOMPOSER — Claude generates world manifest JSON
2. WORLD LABS MARBLE — Gaussian splat environment (SPZ) + GLB mesh
3. TRELLIS — Hero foreground objects
4. BLENDER ASSEMBLY — GLB + objects + lighting + camera orbit
5. TOPAZ 4K UPSCALE — Rendered frames to 4K
6. LUMA LABS — First/last frames to cinematic video
7. SPLAT TRAINING — PostShot/COLMAP unified world splat
8. WEB VIEWER — Three.js browser walkthrough

## VFX Production Context

- Previs-to-director approval: 4-8 weeks traditional → hours with WorldForge
- Digital environment cost: $10k-100k per shot
- Superman (2025, Framestore): 4D Gaussian splatting validated at major studio level
- glTF standardisation: August 2025 (Khronos KHR_gaussian_splatting)

## Test: Mars Colony

World generated: Olympus Station — Futuristic Mars Colony at Dawn
- World Labs Marble: https://marble.worldlabs.ai/world/8740d813-5ed7-43b1-a5a2-092830af053f

*Laurence O'Byrne Creative | laurenceobyrnecreative@gmail.com*
