# Part 10: Wan Prompt Optimizer, Shot Editor, Reference Image Manager, Shot Prompt Composer

Four new ComfyUI nodes completing the per-shot prompt assembly pipeline for the AI Film Editor. The nodes cover the full chain from raw shot data to Wan 2.1-ready prompts: `AFE_ShotPromptComposer` assembles structured asset data into a base prompt, `AFE_WanPromptOptimizer` reformats it for Wan 2.1 (optionally via LLM), `AFE_ReferenceImageManager` extracts reference images from asset registries for I2V/IP-Adapter, and `AFE_ShotEditor` enables non-destructive per-shot edits on a sequence. All four are registered in `__init__.py` under a "Part 10" block, bringing the total NODE_CLASS_MAPPINGS count to 46.

Watch for: The workflow template (`03_single_shot_production.json`) describes a "ShotPromptComposer → WanPromptOptimizer" chain in its `afe_description` field, but `AFE_ShotPromptComposer`'s output has no outgoing links in the template — the node is wired but orphaned. `AFE_WanPromptOptimizer` also has no input port for a pre-composed prompt, so the two nodes cannot be chained at all with the current API. This gap means users loading the template get a disconnected ShotPromptComposer node with no effect on generation.

**Verdict**: APPROVED

---

## High-level view

`AFE_WanPromptOptimizer` gates API calls behind the `llm_enhanced` branch — `import urllib.request` sits inside the try block, so `rule_based` mode is network-free. `AFE_ShotEditor` deep-copies the sequence before modifying it and raises `ValueError` on a missing shot ID. `AFE_ReferenceImageManager` returns a `[1, H, W, 3] float32` tensor and falls back to `torch.zeros(1, 512, 512, 3)` with correct `FileNotFoundError` behavior when `fallback_to_blank=False`.

The workflow template gap is the one item worth fixing before treating the template as documentation: `AFE_ShotPromptComposer` and `AFE_WanPromptOptimizer` are parallel nodes in the template, not chained. `AFE_WanPromptOptimizer` has no input port for a pre-composed prompt, so they can't be chained without an API change. The `afe_description` field claims a "ShotPromptComposer → WanPromptOptimizer" pipeline that doesn't exist in the links array.

The `AFE_ShotEditor` edit report shows old→new for every changed field except `negative_prompt`, which records only "已更新" — the old value is captured but dropped before the report string is built. The `ReferenceImageManager` error path for `source_type="file_path"` with empty input produces "参考图不存在: None", obscuring that the root cause is a missing input rather than a missing file.

---

<details>
<summary>Issues (4)</summary>

1. **Orphaned ShotPromptComposer in workflow template** — Node 3 (`AFE_ShotPromptComposer`) has no outgoing links in `03_single_shot_production.json`; its `composed_prompt` output reaches nothing. `AFE_WanPromptOptimizer` has no input port for a pre-composed prompt, so they can't be chained without an API change. Either add a `composed_prompt` optional input to `AFE_WanPromptOptimizer` and wire `[3, 0] → [5, composed_prompt]` in the template, or document that the two nodes are intentionally parallel and update `afe_description` to reflect that.

2. **ShotEditor negative_prompt report missing old value** — All other edited fields in `edit_report` show `old → new`, but the `negative_prompt` entry only appends "- 负面提示词: 已更新". Log the old value as the other fields do to satisfy the spec requirement.

3. **ReferenceImageManager: FileNotFoundError message shows "None"** — When `source_type="file_path"` and `file_path` is empty with `fallback_to_blank=False`, the raised error reads "参考图不存在: None". Add a check before the resolution step: if `source_type == "file_path"` and `file_path` is empty, raise `ValueError("file_path is required when source_type='file_path'")`.

4. **WanPromptOptimizer: costume_per_character fallback may AttributeError** — When `outfit` is provided but `outfit_prompt` is empty, the code evaluates `_get(shot_data, "costume_per_character", {}).get("default", "")`. If `shot_data["costume_per_character"]` exists as a non-dict value (list or string), `.get()` will throw `AttributeError`. Guard with `isinstance(..., dict)` before calling `.get()`.

</details>

---

<details>
<summary>Details</summary>

## WanPromptOptimizer: outfit_desc inconsistency and costume_per_character risk

The `outfit_desc` computation has a subtle inconsistency with `ShotPromptComposer`: when `outfit` is provided but its `outfit_prompt` is empty, `WanPromptOptimizer` falls back to `shot_data.costume_per_character.default` while `ShotPromptComposer` produces an empty string. The two nodes are designed to run in parallel (see workflow gap below), but this divergence means they can produce different prompts for identical inputs. The `costume_per_character` fallback also carries an `AttributeError` risk if the field exists in `shot_data` as a non-dict type — the `_get` helper returns the raw value and `.get("default", "")` is called on it unconditionally.

## Workflow template: ShotPromptComposer is an orphan

The `afe_description` in `03_single_shot_production.json` reads:

```
ShotBatchController → ShotPromptComposer → WanPromptOptimizer → WanTextEncode → ...
```

But the links array shows no edge from node 3 (`AFE_ShotPromptComposer`) to node 5 (`AFE_WanPromptOptimizer`). Both nodes receive `SHOT_SEQUENCE` and `shot_id` directly from `AFE_ShotBatchController` (links 4–7), and node 3's three outputs (`composed_prompt`, `negative_prompt`, `composition_report`) have no consumers. `AFE_WanPromptOptimizer`'s `INPUT_TYPES` has no port for a pre-composed prompt, so there is currently no way to chain them even if the template were corrected.

The practical effect: `ShotPromptComposer` runs and logs, but its output is discarded. The actual prompt sent to `WanTextEncode` comes entirely from `WanPromptOptimizer`'s internal rule-based assembly. If the intent is a two-stage pipeline, `WanPromptOptimizer` needs a `composed_prompt` optional input (which could be used as the `action_desc` base instead of re-reading `shot_description`), and the template needs a link `[3, 0] → [5, composed_prompt_input_index]`.

## ShotEditor edit report: negative_prompt omits old value

Every other changed field in `edit_report` shows an old→new comparison:

```
- 时长: 5.0秒 → 10.0秒
- 运镜: static → tracking_shot
```

The `negative_prompt` entry records only:

```
- 负面提示词: 已更新
```

The old value is captured (`old = _get(shot_data, "negative_prompt", "(空)")`) but never appended to the report string. This is inconsistent and makes it impossible to audit what was replaced without inspecting the original sequence separately.

## ReferenceImageManager: FileNotFoundError message quality

The error raised when `source_type="file_path"`, `file_path=""`, and `fallback_to_blank=False` reads:

```
FileNotFoundError: 参考图不存在: None
```

`resolved` is set to `None` via `file_path.strip() or None`, so the message correctly reflects the resolved path, but "None" gives no indication that the root cause is a missing input. A `ValueError` early-exit when `source_type == "file_path"` and `file_path` is empty would surface a more actionable message before reaching the FileNotFoundError path.

</details>

---

<details>
<summary>File map</summary>

| File | Change |
|------|--------|
| `nodes/adapters/wan_prompt_optimizer_node.py` | New node: Wan 2.1 prompt optimizer with rule_based and llm_enhanced modes |
| `nodes/director/shot_editor_node.py` | New node: non-destructive per-shot sequence editor with deep copy |
| `nodes/dam/reference_image_manager_node.py` | New node: extracts IMAGE tensors from asset registries with blank fallback |
| `nodes/director/shot_prompt_composer_node.py` | New node: assembles structured asset data into a base prompt string |
| `__init__.py` | Part 10 imports + 4 NODE_CLASS_MAPPINGS + 4 NODE_DISPLAY_NAME_MAPPINGS entries (46 total) |
| `workflow_templates/03_single_shot_production.json` | Full 13-node single-shot production pipeline template |

Full diff: `git show HEAD` in `e:/MJ/ai_film_editor_nodes`

</details>
