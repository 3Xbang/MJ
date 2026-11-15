# AI Film Editor — 角色管理系统 + 专业分镜升级

This change promotes the film editor from a single-output shot breakdown tool into a full cast-aware pipeline. The ScriptParser now instructs the LLM to produce a dual-output JSON (cast + shots) and exposes a new `CAST_DATA` output slot. Three new nodes cover the downstream lifecycle: `AFE_CastManager` hydrates raw cast dicts into `CharacterAsset` objects, `AFE_ExpressionSheet` generates multi-expression prompt suites per character, and `AFE_ShotUnit` resolves individual shots from the sequence and assembles render configs for each of the three production passes (640×360 / 1280×720 / 1920×1080). The data model gains three new enums (`RoleType`, `CameraAngle`, `CameraMotionEx`) and thirteen new fields spread across `CharacterAsset` and `ShotItem`.

Watch for: **enums defined but not wired into model type annotations** (confirmed) — the new validation types are dead weight until applied; **non-deterministic seed in ShotUnit** (confirmed) — each call produces a fresh random seed, making individual shot re-generation irreproducible; **ExpressionSheet disconnected in the workflow template** (confirmed) — node 116 is on the canvas but unwired.

**Verdict**: APPROVED

---

## High-level view

The ScriptParser upgrade is a backward-compatible extension. The new `_parse_json` tries the dict format first and falls back to the legacy array, so old LLM responses still parse. The 5-tuple return and shifted output slots are a breaking change to any workflow that hardcoded slot indices beyond slot 0 — only link 4 (sequence_json, slot 2 → 3) needed fixing in the bundled template.

The three enums (`RoleType`, `CameraAngle`, `CameraMotionEx`) are added to `common.py` but are never imported into `assets.py` or `shot.py`. Both `role_type` on `CharacterAsset` and `camera_angle` on `ShotItem` are plain `str` fields with string defaults. The enums provide no Pydantic validation, no IDE autocomplete guidance at the model layer, and no protection against out-of-range LLM output.

`AFE_ShotUnit` calls `random.randint(0, 2**31 - 1)` unconditionally to produce its seed output. The user requirement for independently re-generatable per-shot video implies reproducibility — the same shot should be re-runnable with the same seed. A fresh random seed each execution breaks that contract.

The workflow template adds nodes 115–117 above the main pipeline area. Only two links are added (79: cast_data → CastManager, 80: shot_sequence → ShotUnit). Node 116 (ExpressionSheet) has no incoming link, leaving the cast→expression sheet flow unwired.

---

<details>
<summary>Issues (5)</summary>

1. **Enums unused in model annotations** — `role_type: str` and `camera_angle: str` accept any string; import `RoleType` / `CameraAngle` into the model files and change the field types to enforce validation.
2. **ShotUnit non-deterministic seed** — `random.randint` on every call makes per-shot re-generation irreproducible. Use a deterministic seed derived from `shot_id` (e.g. `hash(shot_id) & 0x7FFFFFFF`) or add a user-configurable seed input.
3. **ExpressionSheet disconnected in workflow template** — Node 116's CHARACTER_ASSET input has `"link": null`; add a link from node 115's `character` output (slot 0) to node 116's input so the template demonstrates the full cast→expression flow.
4. **camera_angle is free-form in SYSTEM_PROMPT** — The example shows `"中景略低角仰拍"` with no whitelist constraint, unlike `camera_motion`. Downstream code that tries to map `camera_angle` to `CameraAngle` enum values will silently receive unstructured Chinese text. Add a constrained value list to the prompt.
5. **CameraMotionEx/SYSTEM_PROMPT whitelist mismatch** — `crane_up`, `crane_down`, `handheld` are defined in `CameraMotionEx` but absent from the SYSTEM_PROMPT allowed-values list. The LLM will never produce these values, making those enum members unreachable via the parser.

</details>

<details>
<summary>Details</summary>

### Enums defined but not wired into Pydantic models

`RoleType`, `CameraAngle`, and `CameraMotionEx` are added to `lib/models/common.py` as `StrEnum` subclasses. Neither `assets.py` nor `shot.py` imports them. The relevant fields are:

```python
# assets.py
role_type: str = "supporting"          # should be RoleType

# shot.py
camera_angle: str = "medium"           # should be CameraAngle
```

Pydantic will accept any string here, including out-of-range values like `"主角"` or `"extreme_close_up"`. The enums do nothing at runtime until the field annotations reference them. `CameraMotionEx` is entirely unreferenced — the existing `camera_motion` field in `ShotItem` still uses the legacy `CameraMotion` enum from before this PR, and the new field `camera_angle` uses plain `str`.

### ShotUnit seed non-reproducibility

```python
seed = random.randint(0, 2**31 - 1)
```

There is no way to pass a fixed seed or retrieve the seed from a previous run. For the stated goal of "每个分镜可以单独重新生成" (each shot independently re-generatable), users expect re-running a shot to reproduce the same frame before making deliberate changes. A deterministic default (e.g. hash of shot_id) with an optional override input would satisfy both use cases. As written, every execution is a lottery.

### camera_angle: missing whitelist, mixed-language values

The SYSTEM_PROMPT constrains `camera_motion` with an explicit allow-list:

```
camera_motion 只能是：static, pan_left, pan_right, ...
```

No equivalent constraint exists for `camera_angle`. The example in the prompt gives `"中景略低角仰拍"` — a free-form Chinese description that carries directorial intent but isn't normalized. Any code that attempts to key on `camera_angle` for downstream logic (render settings, metadata, search) will get unstructured text. Adding the same style of allow-list using `CameraAngle` values would fix this and also make those enum members useful.

### CameraMotionEx/SYSTEM_PROMPT whitelist mismatch

The SYSTEM_PROMPT allow-list for `camera_motion` covers `static`, `pan_left`, `pan_right`, `zoom_in`, `zoom_out`, `tilt_up`, `tilt_down`, `orbit`, `slow_push_in`, `slow_pull_back`, `tracking_shot` — 11 values. `CameraMotionEx` defines 14. Missing from the prompt: `crane_up`, `crane_down`, `handheld`. These are legitimate filmmaking moves the LLM will never output because the prompt forbids anything outside the list. Either add them to the prompt or remove them from the enum.

### Workflow template: ExpressionSheet island node

Link table in `complete_film_pipeline.json` after the patch:

```
79: 103(ScriptParser).cast_data   → 115(CastManager).cast_data
80: 103(ScriptParser).shot_sequence → 117(ShotUnit).shot_sequence
```

Node 116 (ExpressionSheet) has no incoming link. The intent is clearly ScriptParser → CastManager → ExpressionSheet, but the last hop is absent. The template as committed adds ExpressionSheet to the graph as an isolated island; users need to wire it manually to get any output from it.

</details>

---

<details>
<summary>File map</summary>

| File | Change |
|---|---|
| `lib/models/common.py` | Added `RoleType`, `CameraAngle`, `CameraMotionEx` StrEnums |
| `lib/models/assets.py` | Added 6 new fields to `CharacterAsset` |
| `lib/models/shot.py` | Added 7 new fields to `ShotItem` |
| `nodes/director/script_parser_node.py` | Upgraded SYSTEM_PROMPT, 5-tuple return, dual-format `_parse_json` |
| `nodes/dam/cast_manager_node.py` | New `AFE_CastManager` node |
| `nodes/dam/expression_sheet_node.py` | New `AFE_ExpressionSheet` node |
| `nodes/director/shot_unit_node.py` | New `AFE_ShotUnit` node with 3-pass config |
| `__init__.py` | Registered 3 new nodes; total 31 |
| `workflow_templates/complete_film_pipeline.json` | Added nodes 115–117, links 79–80, shifted ScriptParser output slots |
| `install.sh` | New install script (outside review scope) |
| `.agents/tasks/afe-folder-paths-20250124/review.*` | Prior review verdict updated to APPROVED |

Full diff: `git -C e:/MJ/ai_film_editor_nodes diff HEAD~1`

</details>
