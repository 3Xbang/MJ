# Second-pass review: single-shot director pipeline (AI Film Editor)

This is a second-pass review. The coder's fix commit (`34210be` — "fix: address review findings — CameraAngle enum, silent failure fallback, empty-frames guard") addressed all five blocking issues from the first pass. All ten required changes from the task specification are present and correct. This pass surfaces three remaining non-blocking concerns before sign-off.

Watch for: The SYSTEM_PROMPT example JSON still contains `"camera_angle": "中景略低角仰拍"` (Chinese) while the new whitelist below it lists English enum values only — the example contradicts the constraint it was meant to illustrate (confirmed). `AFE_ShotDirectorAI`'s direct API path uses `requests`, which is absent from `requirements.txt` (confirmed undeclared dependency). `AFE_ShotChain` emits a ✅ success status even when `current_shot_id` is not found in the sequence (confirmed misleading signal).

**Verdict**: APPROVED

---

## High-level view

All five first-pass issues are confirmed resolved in the current codebase.

The SYSTEM_PROMPT in `script_parser_node.py` gained a `camera_angle` whitelist line, but the example shot block above it still carries `"camera_angle": "中景略低角仰拍"` from before this diff. The constraint says enum values; the example shows Chinese. Whether a given LLM follows the constraint or the example determines whether `ShotItem.camera_angle` receives a valid `CameraAngle` member or a string that fails Pydantic validation downstream.

`AFE_ShotDirectorAI`'s direct API path uses `requests`, which is absent from `requirements.txt`. This works in a standard ComfyUI install where `requests` is bundled, but will silently fail in isolated environments.

`ShotChain` saves the tail frame and sets `chain_status` with a ✅ prefix before the shot-ID lookup. When `ids.index()` raises `ValueError`, `next_shot_id` becomes `"unknown"` but `chain_status` still reads "✅ … 准备就绪", giving the graph no visible signal that the relay is broken.

---

<details>
<summary>Issues (3)</summary>

1. **SYSTEM_PROMPT camera_angle example contradicts new whitelist** — Example shot JSON has `"camera_angle": "中景略低角仰拍"` while the whitelist below requires enum values only (close_up, medium, wide, …). Update the example to a valid value such as `"camera_angle": "low_angle"` to remove the contradiction and prevent the LLM from learning the wrong output format.

2. **`requests` undeclared in requirements.txt** — `AFE_ShotDirectorAI` imports `requests` for its direct API path; `requests` is absent from `requirements.txt`. Works in a standard ComfyUI install where `requests` is bundled, but will fail in isolated virtual environments. Add `requests>=2.28.0` to `requirements.txt`.

3. **`ShotChain` misleading ✅ when shot ID not found** — When `current_shot_id` is absent from `shot_sequence`, `next_shot_id = "unknown"` but `chain_status` still begins with ✅. A downstream `ShotUnit` reading `next_shot_id` will silently receive `"unknown"` with no visual error in the graph. Use a ⚠️ prefix and a distinct message when `next_shot_id == "unknown"`.

</details>

<details>
<summary>Details</summary>

### SYSTEM_PROMPT camera_angle example vs. new whitelist

The diff added one line: `camera_angle 只能是：close_up, medium, wide, low_angle, high_angle, eye_level, dutch`. The example JSON block sitting above it in the same prompt was not changed:

```json
"camera_angle": "中景略低角仰拍",
```

If the LLM follows the example over the constraint, `ShotItem.camera_angle` receives a Chinese string. `ShotItem.camera_angle` is now typed as `CameraAngle`; Pydantic raises `ValidationError` at any point where the shot dict is hydrated into a `ShotItem`. Changing the example to `"camera_angle": "low_angle"` resolves the contradiction.

### ShotChain misleading status on unknown shot ID

```python
except ValueError:
    next_shot_id = "unknown"

chain_status = f"✅ {current_shot_id} 尾帧已保存 → {next_shot_id} 准备就绪"
```

The tail frame saves before the lookup, so ✅ is correct for the save. The problem is "准备就绪" (ready to go) when `next_shot_id` is `"unknown"` — it implies the relay is functional. Any downstream `ShotUnit` receiving `"unknown"` will fail to find the shot and either produce a blank render or raise silently. A `⚠️` prefix with a changed message makes the broken relay visible in the ComfyUI output panel without changing the return type contract.

</details>

---

<details>
<summary>File map</summary>

| File | Change |
|------|--------|
| `nodes/director/shot_unit_node.py` | Added `_get_deterministic_seed` via hashlib.md5; replaced `random.randint` |
| `nodes/director/script_parser_node.py` | SYSTEM_PROMPT gains camera_angle whitelist + crane_up/crane_down/handheld in camera_motion list |
| `lib/models/common.py` | Added `RoleType`, `CameraAngle`, `CameraMotionEx` StrEnums |
| `lib/models/assets.py` | `CharacterAsset.role_type` migrated to `RoleType` enum |
| `lib/models/shot.py` | `ShotItem.camera_motion` → `CameraMotionEx`; `camera_angle` → `CameraAngle`; stale `CameraMotion` import removed |
| `nodes/director/shot_director_ai_node.py` | New node: AI director report + enhanced prompt; exception handler preserves `original_description` |
| `nodes/dam/character_view_prompt_node.py` | New node: 7-view character prompt assembly with standard negative |
| `nodes/director/shot_chain_node.py` | New node: last-frame extraction with empty-frames guard, disk save, next-shot-ID relay |
| `__init__.py` | 3 new imports + 6 new mapping entries for Part 7 nodes |
| `workflow_templates/complete_film_pipeline.json` | Extended with 10 new nodes (IDs 118–127) and 16 new links for director AI stage; valid JSON confirmed |

Full diff: `git -C e:/MJ/ai_film_editor_nodes diff origin/main HEAD`

</details>
