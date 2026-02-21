# WorldForge — VFX Plate Quality Guide

> *How WorldForge produces production-grade Gaussian splat environments.*

---

## The Core Problem: Gaussian Splat Softness

World Labs Marble outputs are Gaussian splat environments. But Gaussian splats have a known
characteristic: **density falloff at edges**. Objects at the periphery appear soft — slightly
blurred, as if shot with a telephoto lens at wide aperture.

**In WorldForge, this is a cinematic choice, not a flaw.**

---

## The Depth-of-Field Solution

WorldForge treats Gaussian splat softness as motivated Depth of Field (DoF). By configuring
Blender camera with matching DoF parameters, the splat softness becomes designed bokeh —
indistinguishable from a high-end anamorphic lens wide open.

### How it works in the pipeline

In `pipeline.py`, `_generate_blender_script()` configures the camera:

```python
cam_data.dof.use_dof = True
cam_data.dof.aperture_fstop = f_stop  # from world manifest

# Place a Focus Empty at the hero object position
bpy.ops.object.empty_add(type="PLAIN_AXES", location=hero_pos)
focus_empty = bpy.context.active_object
cam_data.dof.focus_object = focus_empty
cam_data.dof.focus_distance = focus_distance
```

The `f_stop` comes from the world manifest, set by:
- `scene_decomposer.py` (auto-inferred from mood)
- A `set_control.py` named preset
- Manual override in the manifest

---

## DoF Settings by Mood

| Mood | f/stop | Focus Dist | Visual Feel |
|------|--------|------------|-------------|
| `golden_dawn` | f/1.8 | 3.0m | Warm, shallow, dreamy |
| `golden_hour_dusk` | f/1.6 | 3.5m | Ultra-shallow, romantic |
| `foggy_dawn` | f/2.8 | 5.0m | Atmospheric haze preserved |
| `blue_hour` | f/2.0 | 4.0m | Cool, moody, melancholic |
| `clear_night` | f/1.4 | 2.5m | Dark, dramatic, wide open |
| `midday_clear` | f/4.0 | 6.0m | Sharp, clean, documentary |
| `overcast_flat` | f/4.0 | 6.0m | Even, neutral, no bokeh |
| `storm_approaching` | f/2.8 | 5.0m | Ominous, atmospheric |

**Key insight:** f/1.4 to f/2.0 masks splat softness best. f/4.0+ only for high-density splats.

---

## World Labs Input Quality

The quality of the output splat is directly related to the quality of the input.

### Text-only input

- `Marble 0.1-plus` — 5 min, full_res splat, best for client delivery
- `Marble 0.1-mini` — 45s, 500k splat, use for iteration

**Best text prompt formula:**

```
[time of day] + [weather] + [biome] + [hero objects] + [mood]

Good: "misty dawn, ancient temperate forest, towering mossy oaks, golden shafts through fog, serene"
Weak: "a forest"
```

### Multi-image input (highest quality — real locations)

4 iPhone photos at 0/90/180/270 degrees azimuth gives World Labs enough angular coverage
to reconstruct reliable geometry from a real location.

**Capture protocol:**
1. Stand in the centre of the scene
2. Shoot at head height, level horizon
3. 0 deg = front (hero direction), 90 = right, 180 = back, 270 = left
4. Keep consistent exposure across all 4 shots
5. Avoid motion blur — use at least 1/250s shutter

```python
images = [
    {"azimuth": 0,   "path": "front.jpg"},
    {"azimuth": 90,  "path": "right.jpg"},
    {"azimuth": 180, "path": "back.jpg"},
    {"azimuth": 270, "path": "left.jpg"},
]
world = generate_world_from_multi_image(
    display_name="On-Location Capture",
    images=images,
)
```

---

## Topaz Upscale: CGI-Specific Settings

After Blender renders the orbit frames, Topaz upscales them to 4K before splat training.

**Best model for CGI renders: `prob-4` (Proteus)**

```python
result = upscale_render_for_pipeline(
    render_dir="renders/world_20260221/",
    scale_factor=4,
    model="prob-4",  # Proteus handles CGI geometry without halo artefacts
)
```

Default Topaz models (Artemis) are tuned for photographic content. On CG renders they
introduce edge halos. Proteus preserves CGI sharpness without ringing.

---

## Luma Labs: Cinematic Video from Orbit Frames

The Topaz-upscaled first and last frames drive Luma video generation.
The two-keyframe approach gives directional motion.

```python
video = generate_orbit_flythrough(
    world_title="Ancient Forest at Dawn",
    mood="foggy_dawn",
    first_frame_path=result["first_frame"],
    last_frame_path=result["last_frame"],
    output_dir="outputs/videos/",
)
```

**Mood to cinematic prompt mapping:**
- `golden_hour` - warm golden light, shallow depth of field, gentle lens flare
- `foggy_dawn` - ethereal arc through morning mist, cool blue-green, atmospheric haze
- `blue_hour` - cool blue twilight, subtle lens bokeh, cinematic colour grade
- `clear_night` - deep shadows, dramatic point light sources, cinematic noir

---

## PersonForge: Real People in the World

`person_forge.py` composites a real person (captured on iPhone via Polycam) into the environment.

### Two-keyframe Luma technique

Luma takes `frame0` (empty world panorama URL) and `frame1` (composite with person).
Luma generates a smooth entrance — the person walks into the world.

```python
keyframes = {
    "frame0": {"type": "image", "url": world_panorama_url},
    "frame1": {"type": "image", "url": f"data:image/jpeg;base64,{frame1_b64}"},
}
```

---

## Unreal Engine Integration

WorldForge Gaussian splat outputs are compatible with Unreal Engine 5.3+ via the
Gaussian Splatting plugin.

**Workflow:**
1. Download the `.spz` from World Labs (full_res quality)
2. Convert `.spz` to `.ply`:
   ```bash
   npx splat-convert input.spz output.ply
   ```
3. Import `.ply` into UE5 via the Gaussian Splatting plugin
4. The splat renders at 60fps on RTX 3080+

The `.glb` collider mesh can be imported separately for character collision geometry.

---

## Quality Benchmark

| Stage | Fast Mode | Quality Mode |
|-------|-----------|--------------|
| World Labs | Marble mini, ~45s, 500k | Marble plus, ~5 min, full_res |
| Blender | 60 frames, 32 samples | 180 frames, 128 samples |
| Topaz | 2x scale | 4x scale |
| Total | ~10-15 min | ~30-40 min |
| Use for | Director iteration | Client delivery |

---

## Key Production Numbers

- Previs to director approval: 4-8 weeks traditional vs hours with WorldForge
- Digital environment cost: $10k-$100k per shot (avg $62k on Avatar) vs fraction for non-hero envs
- Superman (2025, Framestore): ~40 shots used 4D Gaussian splatting — validated at top-tier VFX level
- glTF standardisation: August 2025 (Khronos KHR_gaussian_splatting) — format is now industry standard

---

*WorldForge — Laurence O'Byrne Creative | laurenceobyrnecreative@gmail.com*
