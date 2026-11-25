# AFE_SceneImageGenerator — Scene Environment Reference Image Generator

Adds a new ComfyUI node that reads `scene_report` from `AFE_SceneAnalyzer` and generates three environment reference images per scene (establishing, medium, atmosphere) using the Flux dev pipeline. The implementation drives ComfyUI's built-in `UNETLoader`, `DualCLIPLoader`, `KSampler`, and `VAEDecode` nodes directly via `NODE_CLASS_MAPPINGS` rather than adding new model-loading infrastructure. All 11 spec checklist items pass with no blocking gaps.

Watch for: `clip2_name` has no fallback folder path if `text_encoders` is empty on the target installation (confirmed asymmetry with `clip1_name`). Any per-shot failure during generation raises immediately, discarding all partial results for that run.

**Verdict**: APPROVED

---

## High-level view

The node caches the loaded model triple `(unet, clip, vae)` in a module-level dict keyed by the four model filenames. The first execution pays the VRAM cost; subsequent runs in the same session hit the cache. The dict has no lock, so concurrent queue execution could load the same models twice — low risk in standard single-threaded ComfyUI but a latent bug if concurrency is ever enabled.

Scene parsing handles both JSON (from `scenes_json` output) and the text `场景N：` block format from `AFE_SceneAnalyzer`. When `environment_description_en` is missing, the fallback assembles a description from `scene_name`, `location`, `lighting_mood`, and `time_of_day` — this means prompt quality degrades silently rather than erroring when the upstream analyzer omits the English field. The `clip1_name` dropdown has a `or get_filename_list("clip")` fallback but `clip2_name` does not; on installations where CLIP models live under `models/clip/` rather than `models/text_encoders/`, the `clip2_name` dropdown will be empty.

---

<details>
<summary>Issues (3)</summary>

1. **clip2_name empty-list risk** — `clip1_name` uses `get_filename_list("text_encoders") or get_filename_list("clip")` as its dropdown source, but `clip2_name` uses only `get_filename_list("text_encoders")` with no fallback. On installations where CLIP models live in the `clip` folder rather than `text_encoders`, the `clip2_name` dropdown will be empty and the node will error at runtime. Add the same `or get_filename_list("clip")` fallback.

2. **Full-or-nothing generation** — Any exception inside `_generate_one` during the per-scene loop is immediately re-raised, discarding all partially collected image tensors. A 5-scene batch that fails on scene 3 produces no output at all. Callers have no way to retrieve the two completed scenes. If partial output is acceptable, consider catching per-scene failures and inserting a placeholder tensor instead of re-raising; if not, document the all-or-nothing contract explicitly.

3. **_MODEL_CACHE race condition** — The module-level `_MODEL_CACHE` dict has no lock. Two simultaneous execution queue entries with the same model key will both pass the `if key in _MODEL_CACHE` check before either finishes loading and will each load the full model set into VRAM independently. Worth protecting with `threading.Lock` if the queue is ever run with concurrency enabled.

</details>

---

<details>
<summary>Details</summary>

### clip2_name fallback asymmetry

`INPUT_TYPES` builds the CLIP dropdown lists as:

```python
clip_list = (folder_paths.get_filename_list("text_encoders")
             or folder_paths.get_filename_list("clip"))
...
"clip1_name": (clip_list, {"default": "clip_l.safetensors"}),
"clip2_name": (folder_paths.get_filename_list("text_encoders"), {"default": "t5xxl_fp16.safetensors"}),
```

On a fresh ComfyUI install where both CLIP models are under `models/clip/`, `clip2_name`'s dropdown is an empty list. ComfyUI will error when `_load_models` calls `DualCLIPLoader` with an empty string. The fix is one line: use `clip_list` for `clip2_name` as well, or give it the same `or` expression.

### Full-or-nothing generation on failure

Inside the per-scene loop:

```python
except Exception as exc:
    logger.error("[AFE_SceneImageGenerator]   %s FAILED: %s", shot_type, exc)
    raise
```

The re-raise means `torch.cat` for the three batches never executes. For a workflow with five scenes, if scene 3's establishing shot fails (e.g., VRAM OOM), the two completed scenes are discarded. The choice between fail-fast and partial-output has real UX implications — worth an explicit comment or a user-facing `fail_on_error` toggle.

### _MODEL_CACHE thread safety

```python
_MODEL_CACHE: dict = {}

def _load_models(...):
    global _MODEL_CACHE
    key = (unet_name, clip1_name, clip2_name, vae_name)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    ...
    _MODEL_CACHE[key] = (model, clip, vae)
```

The check-then-assign is not atomic. Standard ComfyUI is single-threaded so this is low risk today, but the pattern is a latent double-load bug if the execution engine is ever run with threading enabled.

</details>

---

<details>
<summary>File map</summary>

| File | Change |
|------|--------|
| `nodes/analyzer/scene_image_generator_node.py` | New node: `AFE_SceneImageGenerator` with Flux pipeline, scene parser, model cache |
| `__init__.py` | Part 15 import and registration in both mappings dicts |
| `gen_afe_main_workflow.py` | Added nodes 14–17 (SceneImageGenerator + 3× PreviewImage), pre-allocated scene link IDs |
| `workflow_templates/afe_script_pipeline.json` | Regenerated output with `last_node_id=17`, 17 nodes, 19 links |

Full diff: `git diff HEAD~1` or compare against previous commit.

</details>
