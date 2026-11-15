# Fix commit: folder_paths review findings resolved

This commit addresses all five findings from the initial review pass. `AFE_FaceEnhancer` now passes `face_model` to `CodeFormerEnhance.enhance()`; outfit, scene, and props nodes persist `image_checkpoint` as `base_model_logical_name` with a placeholder guard; `AFE_ModelChecker` caches `check_requirement` results in a single pass; `AFE_VideoModelAdapter` calls `require_model` to fail fast when no diffusion model is installed. All five prior blocking concerns are resolved.

Watch for: `CodeFormerEnhance.enhance()` accepting `face_model` as a kwarg cannot be verified without reading the ComfyUI_CodeFormer source — if the kwarg is unexpected, every CodeFormer call silently falls back to passthrough with a warning and the model selection has no effect (possible). `require_model("wan_i2v_model")` always references Wan2.1 I2V in its error message even when the user's diffusion_models folder is empty for non-Wan reasons (confirmed minor).

**Verdict**: APPROVED

## High-level view

The face_model fix is effective when the external CodeFormer API accepts the kwarg; a broad `except Exception` prevents crashes if it doesn't. If `CodeFormerEnhance.enhance()` rejects `face_model`, the user sees "CodeFormer is installed but enhancement failed" for every run — identifiable but potentially confusing until the ComfyUI_CodeFormer API is confirmed.

`require_model("wan_i2v_model")` is hardcoded, so a user with an empty `diffusion_models` folder who intended a Kling workflow gets an error message pointing them to Wan2.1 I2V. The message is technically inaccurate for non-Wan use cases, though it only fires when all diffusion models are absent.

<details>
<summary>Issues (2)</summary>

1. **`face_model` kwarg unverified against external CodeFormer API** (possible) — If `CodeFormerEnhance.enhance()` doesn't accept `face_model`, the broad `except Exception` block swallows the `TypeError` and returns passthrough with a warning. Users will see "CodeFormer is installed but enhancement failed" for every run, with no clear indication the kwarg was rejected. Verify the parameter name against the ComfyUI_CodeFormer source before shipping.

2. **`require_model("wan_i2v_model")` misleading message for non-Wan placeholder** (confirmed) — When `video_model.startswith("(")`, the error always tells the user to install Wan2.1 I2V regardless of what video model family they intended. A user building a Kling workflow gets incorrect guidance. Consider a generic message, or accept any valid model requirement key rather than hardcoding `wan_i2v_model`.

</details>

<details>
<summary>Details</summary>

### face_model kwarg to external CodeFormerEnhance API

```python
result = enhancer.enhance(
    images=images,
    face_model=face_model,
    fidelity_weight=fidelity_weight,
    only_center_face=only_center_face,
)
```

`CodeFormerEnhance` is loaded at runtime via `importlib.import_module("custom_nodes.ComfyUI_CodeFormer.codeformer_node")`. The parameter signature of its `enhance()` method is external and cannot be verified here. If `face_model` is not an accepted kwarg, Python raises `TypeError: enhance() got an unexpected keyword argument 'face_model'`; the `except Exception` block catches it and returns passthrough with a logger warning. The worst-case path is passthrough plus a confusing "enhancement failed" warning on every run rather than a crash.

### require_model key hardcoded to Wan I2V

```python
if video_model.startswith("("):
    require_model("wan_i2v_model")
```

`require_model("wan_i2v_model")` raises with the message:

```
❌ Wan 2.1 图生视频主模型 未安装。请在 ComfyUI Manager 中搜索 "Wan2.1 I2V" 下载。
（需要此模型的节点: AFE_VideoModelAdapter (wan_i2v 模式)）
```

The placeholder fires whenever `diffusion_models` is empty, regardless of the target model family. For a Kling or generic video workflow with no models installed, the message incorrectly prescribes Wan2.1 I2V. The simplest fix is replacing the hardcoded key with a broader message, or adding a `MODEL_REQUIREMENTS` entry for a generic video model requirement.

</details>

<details>
<summary>Prior review findings — resolution status</summary>

| Finding | Status |
|---------|--------|
| face_model inert in AFE_FaceEnhancer | ✅ Resolved — `face_model` now passed to `enhancer.enhance()` |
| image_checkpoint discarded in outfit/scene/props | ✅ Resolved — stored as `base_model_logical_name` with placeholder guard |
| Placeholder stored as base_model_logical_name in DB | ✅ Resolved — `startswith("(")` guard in all four DAM nodes |
| Double check_requirement calls per key | ✅ Resolved — single-pass dict cache in `AFE_ModelChecker.check_models` |
| require_model defined but never called | ✅ Resolved — called in `AFE_VideoModelAdapter.adapt_for_model` |

</details>

<details>
<summary>File map</summary>

| File | Change |
|------|--------|
| `nodes/refinement/face_enhancer_node.py` | `face_model` now passed to `enhancer.enhance()` |
| `nodes/dam/outfit_node.py` | `image_checkpoint` persisted as `base_model_logical_name`; placeholder guard |
| `nodes/dam/scene_node.py` | `image_checkpoint` persisted as `base_model_logical_name`; placeholder guard |
| `nodes/dam/props_node.py` | `image_checkpoint` persisted as `base_model_logical_name`; placeholder guard |
| `nodes/dam/character_node.py` | Placeholder guard tightened; fallback to `wan_i2v_14b_480p` explicit |
| `nodes/adapters/video_adapter_node.py` | `require_model` imported and called on placeholder detection |
| `nodes/utils/model_checker_node.py` | Single-pass `results` dict replaces double `check_requirement` calls |

Full diff: `git -C e:\MJ\ai_film_editor_nodes diff HEAD~1 HEAD`

</details>
