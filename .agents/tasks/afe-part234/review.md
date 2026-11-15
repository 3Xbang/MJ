# Part 2/3/4 nodes — Refinement, Audio, and Export

This commit adds 10 new ComfyUI custom nodes across three new sub-packages (`nodes/refinement/`, `nodes/audio/`, `nodes/export/`), bringing the total registered node count to 20. The refinement layer handles second-pass upscaling and face enhancement with graceful fallback for optional dependencies. The audio layer wires up asset management and lip-sync routing. The export layer assembles shot manifests, generates export configs, and optionally stamps watermarks. Supporting infrastructure includes a new `AudioAsset` Pydantic model, `AudioORM` table, an 8-method `AudioRepository`, and three workflow template JSONs (04–06).

Watch for: **workflow 06 ships with a confirmed type mismatch** (`VHS_FILENAMES` → `IMAGE`) that will prevent the template from validating in ComfyUI; **workflow 04 has a `last_link_id` undercount** that causes link ID collision on first edit; and **AFE_FaceEnhancer's CodeFormer dispatch is a guessed API** that silently falls through to passthrough even when CodeFormer is installed.

**Verdict**: NEEDS_CHANGES

---

## High-level view

One structural regression ships with this commit: `repositories/__init__.py` was emptied — the `PropsRepository` re-export was removed and `AudioRepository` was not added. The repositories package namespace now exposes nothing, breaking any import using the package path and leaving the new repository without a stable entry point.

Template 06 has a confirmed type mismatch: AFE_Watermark receives a `VHS_FILENAMES` wire where it expects `IMAGE`. ComfyUI validates connection types on load, so this template fails before execution. Template 04 has a `last_link_id` counter one short of the actual maximum link ID, causing a collision on the first user edit.

`AFE_FaceEnhancer` wraps CodeFormer behind `try/except (ImportError, ModuleNotFoundError, AttributeError)`. The concern is the assumed module path and class API — `custom_nodes.ComfyUI_CodeFormer.codeformer_node.CodeFormerEnhance().enhance(...)` is not a documented interface and will almost certainly raise `AttributeError` even when ComfyUI_CodeFormer is installed, silently degrading to passthrough with no behavioral difference from leaving `enable=False`.

`AFE_VideoUpscaler` permutes `(B,H,W,C) ↔ (B,C,H,W)` for `F.interpolate`. The `lanczos` option maps to `bilinear` (torch has no lanczos mode), documented in a code comment but not surfaced as a runtime warning to the user.

---

<details>
<summary>Issues (5)</summary>

1. **Workflow 06 VHS_FILENAMES→IMAGE type mismatch** — Link 5 in `06_final_export.json` connects VHS_VideoCombine's `VHS_FILENAMES` output to AFE_Watermark's `IMAGE` input. ComfyUI enforces type matching at load time; this template fails to validate. Rewire so watermark is applied upstream of VHS_VideoCombine: `VHS_LoadVideo → AFE_Watermark → VHS_VideoCombine`.

2. **Workflow 04 last_link_id undercount** — `"last_link_id": 18` but link ID 19 already exists in the links array. The first new link a user adds will be assigned ID 19, colliding with the existing upscaler→VHS connection. Set `"last_link_id": 19`.

3. **AFE_FaceEnhancer CodeFormer API is guessed** — The dispatch path `custom_nodes.ComfyUI_CodeFormer.codeformer_node.CodeFormerEnhance().enhance(...)` does not match the actual ComfyUI_CodeFormer node interface. The broad `except AttributeError` catch means enhancement silently falls through to passthrough whether CodeFormer is absent or the API is wrong. Verify the actual class and method name from the installed node pack and narrow the except clause, or log a distinguishable warning when CodeFormer is installed but the call fails.

4. **`lanczos` upscale option silently uses bilinear** — `_MODE_MAP["lanczos"] = "bilinear"` with no runtime log. Users selecting "lanczos" in ComfyUI receive bilinear upscaling with no indication. Add a `logger.warning()` on that code path.

5. **`repositories/__init__.py` now empty** — The `PropsRepository` re-export was removed and `AudioRepository` was not added. Add `AudioRepository` and restore `PropsRepository` to `__init__.py`.

</details>

<details>
<summary>Details</summary>

## Workflow 06: AFE_Watermark receives VHS_FILENAMES instead of IMAGE

In `06_final_export.json`, the intended pipeline is VHS_VideoCombine → AFE_Watermark → SaveImage. VHS_VideoCombine's output slot 0 is `VHS_FILENAMES` — a list of rendered file paths — not an `IMAGE` tensor. AFE_Watermark's `INPUT_TYPES` declares `images: ("IMAGE",)` and processes a 4D float tensor per frame. Connecting `VHS_FILENAMES` to that input is a type error ComfyUI catches at graph validation time, so the template fails on load.

The correct topology is `VHS_LoadVideo → AFE_Watermark → VHS_VideoCombine`. Watermarking must happen on raw frames before encoding.

## Workflow 04: last_link_id collision

`04_second_pass_refinement.json` declares `"last_link_id": 18` but the links array includes `[19, 11, 0, 12, 0, "IMAGE"]` — link ID 19. ComfyUI assigns `last_link_id + 1` to each new link, so the first user edit generates ID 19, silently overwriting the existing VideoUpscaler→VHS_VideoCombine connection. The field should read `"last_link_id": 19`.

## AFE_FaceEnhancer: guessed CodeFormer dispatch

```python
codeformer_mod = importlib.import_module("custom_nodes.ComfyUI_CodeFormer.codeformer_node")
enhancer = codeformer_mod.CodeFormerEnhance()
result = enhancer.enhance(images=images, fidelity_weight=fidelity_weight, only_center_face=only_center_face)
```

`ComfyUI_CodeFormer` does not expose a `CodeFormerEnhance` class with an `enhance()` method. The `except (ImportError, ModuleNotFoundError, AttributeError)` block catches the resulting `AttributeError` and logs "CodeFormer not found" even when it is installed. The node's output is indistinguishable from the `enable=False` passthrough. The fix requires inspecting the actual ComfyUI_CodeFormer node source to identify the correct class and call signature, then narrowing the except clause so an installed-but-failing CodeFormer surfaces as an error rather than silent passthrough.

## AFE_VideoUpscaler: lanczos silent substitution

```python
_MODE_MAP = {
    "lanczos": "bilinear",   # torch has no lanczos; bilinear is a reasonable proxy
}
```

The comment is accurate but no warning reaches the user at runtime. A `logger.warning("lanczos not available in torch; using bilinear")` before the `F.interpolate` call is sufficient.

</details>

---

<details>
<summary>File map</summary>

| File | Change |
|------|--------|
| `nodes/refinement/__init__.py` | New empty package marker |
| `nodes/refinement/refinement_config_node.py` | AFE_RefinementConfig — builds config dict for second-pass workflows |
| `nodes/refinement/second_pass_node.py` | AFE_SecondPassAdapter — PIL LANCZOS resize + config unpack, returns 8-tuple |
| `nodes/refinement/face_enhancer_node.py` | AFE_FaceEnhancer — CodeFormer dispatch with guessed API, ImportError/AttributeError passthrough fallback |
| `nodes/refinement/video_upscaler_node.py` | AFE_VideoUpscaler — torch.nn.functional.interpolate with (B,H,W,C)↔(B,C,H,W) permute |
| `nodes/audio/__init__.py` | New empty package marker |
| `nodes/audio/audio_asset_node.py` | AFE_AudioAsset — creates/loads AudioAsset, persists via AudioRepository |
| `nodes/audio/lip_sync_node.py` | AFE_LipSyncConfig — validates audio path, routes to lip-sync node packs |
| `nodes/audio/audio_video_sync_node.py` | AFE_AudioVideoSync — frame shift, trim-to-shortest, returns (IMAGE, FLOAT, STRING) |
| `nodes/export/__init__.py` | New empty package marker |
| `nodes/export/shot_sequence_builder_node.py` | AFE_ShotSequenceBuilder — writes JSON manifest, OUTPUT_NODE=True |
| `nodes/export/project_export_node.py` | AFE_ProjectExport — builds export config JSON, OUTPUT_NODE=True |
| `nodes/export/watermark_node.py` | AFE_Watermark — per-frame PIL RGBA composite watermark, enable=False passthrough default |
| `lib/models/audio.py` | New AudioType StrEnum + AudioAsset Pydantic model |
| `lib/persistence/orm_models.py` | AudioORM table appended with all required columns |
| `lib/persistence/repositories/audio_repository.py` | AudioRepository with 8 CRUD/query methods |
| `lib/persistence/repositories/__init__.py` | PropsRepository re-export removed; now empty (regression) |
| `__init__.py` | NODE_CLASS_MAPPINGS extended to 20 nodes; 10 new emoji display names added |
| `workflow_templates/04_second_pass_refinement.json` | New workflow: RefinementConfig → SecondPassAdapter → KSamplerAdvanced → FaceEnhancer → VideoUpscaler → VHS_VideoCombine |
| `workflow_templates/05_lip_sync_audio.json` | New workflow: AudioAsset → LipSyncConfig → [lip sync node] → AudioVideoSync → VHS_VideoCombine |
| `workflow_templates/06_final_export.json` | New workflow: ShotSequenceBuilder → ProjectExport + VHS_VideoCombine → Watermark → SaveImage (type mismatch present) |
| `REQUIRED_NODES.md` | Part 2/3/4 sections added with download requirements |

Full diff: `git -C e:/MJ/ai_film_editor_nodes diff HEAD~1..HEAD`

</details>
