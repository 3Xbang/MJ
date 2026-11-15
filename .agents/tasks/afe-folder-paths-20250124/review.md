# folder_paths-driven model dropdowns across AFE nodes

This change replaces every hardcoded STRING model input across the AFE node package with `folder_paths`-driven dropdowns backed by a new `get_model_list` utility. A companion `AFE_ModelChecker` node surfaces installation status per-mode with ✅/❌ reporting, pulling from an enumerated `MODEL_REQUIREMENTS` dict of nine model keys and their ComfyUI Manager search hints. The package now registers 28 nodes total. Watch for: `face_model` dropdown in `AFE_FaceEnhancer` is wired to the UI but not passed to the CodeFormer enhancer call — the selection has no effect on what model runs (confirmed); `image_checkpoint` is accepted but silently discarded in outfit, scene, and props nodes (confirmed).

**Verdict**: CHANGES_REQUESTED

## High-level view

`get_model_list` in `lib/utils/model_checker.py` wraps `folder_paths.get_filename_list()` with a guarded import and a placeholder fallback. All eight modified nodes call it inside their `INPUT_TYPES` classmethod, which ComfyUI invokes at startup to populate dropdowns. This means model lists reflect whatever is installed when ComfyUI starts; installing a new model requires a restart.

`AFE_ModelChecker` is a pure output utility: `OUTPUT_NODE=True`, no generation, formats a text report for the ComfyUI display area. The `check_mode` dropdown routes to one of four key subsets. The node calls `check_requirement` twice per key — once in the report loop, again in the installed-count sum — a minor confirmed inefficiency.

`AFE_VideoModelAdapter` replaces the old hardcoded type-selector with a live `diffusion_models` dropdown. `_detect_model_type` infers model family from the filename. When no diffusion model is installed, the placeholder string flows through `_detect_model_type`, matches nothing, and falls back to `"generic"` prompt formatting silently.

`AFE_FaceEnhancer` adds `face_model` to the dropdown but the CodeFormer `enhance()` call receives only `fidelity_weight` and `only_center_face`. The selected filename is never passed; the model CodeFormer loads is unaffected by the user's selection.

In the three DAM nodes that received `image_checkpoint` as an optional field — outfit, scene, props — the value arrives in the function signature and is immediately dropped. `character_node.py` correctly maps it to `base_model_logical_name`, establishing the right pattern that the other three don't follow.

<details>
<summary>Issues (5)</summary>

1. **face_model inert in AFE_FaceEnhancer** — `face_model` is received by `enhance_faces()` but never passed to `enhancer.enhance()`. The dropdown is misleading: the user's selection has zero effect on what CodeFormer loads. Pass the model filename to the enhancer call, or remove the dropdown until the integration is complete.

2. **image_checkpoint discarded in outfit/scene/props** — All three nodes accept `image_checkpoint` in their function signature but never store or forward it. Character node correctly stores it as `base_model_logical_name`. Apply the same pattern to outfit, scene, and props, or remove the parameter until it has a use.

3. **Placeholder stored as base_model_logical_name in DB** — When no checkpoints are installed, `get_model_list` returns the placeholder string as the first (and only) list entry. That string becomes the default selection and gets written to `CharacterORM.base_model_logical_name`. Add a guard in `create_or_load_character` to treat the placeholder as `None` before storing.

4. **Double check_requirement calls per key** — `check_models` calls `check_requirement(key)` once in the report loop and once in the installed-count `sum()`. Cache the results from the first pass rather than querying `folder_paths` twice per key.

5. **require_model defined but never called** — The `require_model` function in `model_checker.py` raises a `ValueError` with an install tip if a required model is missing, which would give fail-fast validation at execution time. No node currently calls it. Consider using it in nodes where the model is strictly required (e.g., `AFE_VideoModelAdapter`).

</details>

<details>
<summary>Details</summary>

### face_model selection has no effect on CodeFormer execution

`face_enhancer_node.py` adds `face_model` to `INPUT_TYPES` from `get_model_list("facerestore_models", ...)` and receives it in `enhance_faces(self, images, face_model, ...)`. The CodeFormer invocation:

```python
result = enhancer.enhance(
    images=images,
    fidelity_weight=fidelity_weight,
    only_center_face=only_center_face,
)
```

`face_model` is absent. Whatever ComfyUI_CodeFormer's default model loading behavior is, the user's dropdown selection doesn't influence it. A user selecting `codeformer.pth` over any other facerestore model in the list gets the same execution result regardless.

### image_checkpoint discarded in outfit, scene, and props

`character_node.py` stores the selection:

```python
asset = CharacterAsset(
    ...
    base_model_logical_name=image_checkpoint,
    ...
)
```

In `outfit_node.py`, `scene_node.py`, and `props_node.py`, the parameter appears in the signature (`image_checkpoint=None`) but no corresponding field on the ORM row or asset model is set. The OutfitAsset, SceneAsset, and PropsAsset data models may not have a `base_model_logical_name` equivalent, but if the intent is to record which checkpoint should be used for downstream generation of these assets, the value needs to be persisted somewhere.

### Placeholder value contaminating the database

`get_model_list` returns `["(未安装图片模型，ComfyUI Manager 搜索 flux1-dev)"]` when the `checkpoints` folder is empty. This string becomes the first entry in the dropdown and the ComfyUI default value for new nodes. In `character_node.py`, it flows directly into `CharacterORM.base_model_logical_name` without any sanitization. Any query later trying to map logical names to actual checkpoint files will encounter this garbage value.

### _detect_model_type silent fallback on placeholder

If a user has no models installed and executes `AFE_VideoModelAdapter`, `video_model` will be the placeholder string. `_detect_model_type` checks for `"wan"` and `"i2v"` substrings (case-folded), finds neither, and returns `"generic"`. Prompt formatting proceeds as if the model is some unknown generic video model. No warning is logged, no error is raised. This is a silent degradation.

### Double check_requirement calls

```python
# First pass: build the report
for key in keys:
    installed, msg = check_requirement(key)   # call #1

# Second pass: count installs
installed_count = sum(1 for k in keys if check_requirement(k)[0])  # call #2
```

Each `check_requirement` call invokes `folder_paths.get_filename_list(folder)`. For a 9-key full check, that's 18 calls instead of 9. The fix is to collect results in a dict during the first pass and reuse them for the count.

</details>

<details>
<summary>File map</summary>

| File | Change |
|------|--------|
| `lib/utils/model_checker.py` | New — `MODEL_REQUIREMENTS` (9 keys), `find_model`, `get_model_list`, `check_requirement`, `require_model`, `check_all_requirements`; guarded `folder_paths` import |
| `nodes/utils/model_checker_node.py` | New — `AFE_ModelChecker`, `OUTPUT_NODE=True`, check_mode dropdown, ✅/❌ report |
| `nodes/dam/character_node.py` | `base_model` STRING → `image_checkpoint` dropdown; `base_model_logical_name` wired correctly |
| `nodes/dam/outfit_node.py` | `image_checkpoint` optional dropdown added; value not stored |
| `nodes/dam/scene_node.py` | `image_checkpoint` optional dropdown added; value not stored |
| `nodes/dam/props_node.py` | `image_checkpoint` optional dropdown added; value not stored |
| `nodes/adapters/video_adapter_node.py` | `target_model` hardcoded → `video_model` dropdown from `diffusion_models`; `_detect_model_type` added |
| `nodes/refinement/face_enhancer_node.py` | `face_model` dropdown added; not passed to CodeFormer |
| `nodes/consistency/ipadapter_node.py` | `ipadapter_model` + `clip_vision` dropdowns added; both stored in config dict |
| `nodes/consistency/controlnet_node.py` | `controlnet_model` dropdown added; stored in config dict |
| `__init__.py` | `AFE_ModelChecker` imported and registered; 28 total entries |
| `workflow_templates/first_pass_video_workflow.json` | `AFE_ModelChecker` node id=18 added; all orders +1; `last_node_id=18` |
| `workflow_templates/asset_generation_workflow.json` | `AFE_ModelChecker` node id=14 added; all orders +1; `last_node_id=14` |

Full diff: `git -C e:\MJ\ai_film_editor_nodes diff HEAD~1 HEAD`

</details>
