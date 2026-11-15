# Review: consistency-production-nodes (7 new ComfyUI nodes)

## Evidence gathered
- Read all 7 node source files directly (consistency/ipadapter_node.py, consistency/controlnet_node.py, production/transition_node.py, production/subtitle_node.py, production/colorgrade_node.py, production/quality_gate_node.py, production/shot_report_node.py).
- Read `__init__.py`; AST-counted NODE_CLASS_MAPPINGS.
- Validated both workflow JSONs with Python `json.load`.
- Coder's test results (all 7 passed) accepted per instructions.
- No staged diff (files already committed / working-tree state read directly).

---

## Checklist results

### 1. ComfyUI required attributes on each node
All 7 nodes have `INPUT_TYPES` as a `@classmethod`, `RETURN_TYPES` and `RETURN_NAMES` as tuples, `FUNCTION` and `CATEGORY` as strings. `AFE_QualityGate` and `AFE_ShotReport` additionally carry `OUTPUT_NODE = True`. ✅

### 2. AFE_IPAdapterConfig
- Checks `reference_image` first; if absent, iterates `character["views"]` selecting `is_primary + image_path` before falling back to first view with any `image_path`. ✅
- Graceful fallback when no image: warning printed, `reference_image_tensor` is `None` in returned dict. ✅
- Returns `("AFE_IPADAPTER_CONFIG",)` dict with `weight`, `weight_type`, `noise`, `reference_image_tensor`. ✅

### 3. AFE_ControlNetPose
- `PRESETS` dict contains all 5 keys: `standing`, `walking`, `sitting`, `running`, `talking`; each with 18 normalized (x,y) keypoints. Skeleton drawn with NumPy, returned as `[1,H,W,3]` float32 tensor. ✅
- `flip_pose=True` → `torch.flip(tensor, dims=[2])` (width axis of `[N,H,W,C]`). ✅
- Returns `AFE_POSE_CONFIG` dict with `pose_image_tensor`, `control_strength`, `start_percent`, `end_percent`. ✅

### 4. AFE_TransitionEffect
- All 5 `transition_type` branches present: `cut`, `fade`, `dissolve`, `fade_to_black`, `fade_from_black`. ✅
- `dissolve` builds `a_slice` and `b_slice` each of exactly length `n`, outputs `torch.cat(frames)` of shape `[n,H,W,3]`. ✅
- Easing applied via `_get_alpha` for all 4 options. ✅
- `fade` = `torch.cat([to_black_frames, from_black_frames])` via recursive calls. ✅

### 5. AFE_SubtitleOverlay
- PIL `ImageFont.truetype` with Windows system font chain (`simhei.ttf → msyh.ttf → arial.ttf`) plus Linux glob fallback; `load_default()` last resort. ✅
- All 4 `position` options handled: `bottom_center`, `bottom_left`, `top_center`, `middle_center`. ✅
- Semi-transparent background rect: RGBA overlay `alpha_composite` before text draw. ✅
- `enable=False` → returns `(images,)` unchanged. ✅
- Handles both Pillow `textbbox` (≥9.2) and deprecated `textsize` via try/except. ✅

### 6. AFE_ColorGrade
- `PRESETS` dict: `none`, `cinematic_cool`, `cinematic_warm`, `noir_bw`, `golden_hour`, `neon_night`, `vintage`, `clean_bright` — exactly 8. ✅
- Saturation: luminance-preserving formula `gray + (1+fs) * (rgb - gray)`. ✅
- Vignette: `sqrt((x/0.7)² + (y/0.7)²)` → elliptical falloff. ✅
- `enable=False` → returns `(images,)` unchanged. ✅

### 7. AFE_QualityGate
- `OUTPUT_NODE = True`. ✅
- Blur: Laplacian variance of gray frame; scipy fallback to manual np.roll implementation. ✅
- Black frames: mean < 5.0. ✅
- Artifacts: variance > 0.4. ✅
- Input `images` always returned as first output element regardless of findings. ✅
- `fail_on_error=True` → raises `ValueError(quality_report)`. ✅

### 8. AFE_ShotReport
- `OUTPUT_NODE = True`. ✅
- Report includes: project name, timestamp, shot count, total duration, per-shot label/duration/frame_count/character/scene/camera_motion, optional prompt. ✅
- Writes to `output_path` with `makedirs`; write failure caught and printed as warning (non-fatal). ✅

### 9. NODE_CLASS_MAPPINGS count
AST parse confirms **27 entries**: 20 existing + 7 new. ✅

### 10. Workflow JSON files
Both `character_consistency_workflow.json` and `full_production_workflow.json` parse cleanly with `json.load` and contain top-level keys `nodes`, `links`, `version` (plus `last_node_id`, `last_link_id`, `groups`, `config`, `extra`). ✅

### 11. Coder's validation tests
All 7 tests reported passed. ✅

---

## Findings

No blockers found.
