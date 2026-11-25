# AFE Script Analysis Pipeline — ComfyUI custom nodes

This change adds the script-to-shot-prompt pipeline as a set of ComfyUI custom nodes. Starting from raw script text, it flows through ScriptParser → SceneAnalyzer / PropsAnalyzer / CharacterTracker → ShotPromptBuilder → ShotList, with every intermediate type encoded in JSON for downstream nodes. Two new nodes (AFE_ShotList, AFE_CharacterTracker) are added, four existing nodes are substantially expanded, `__init__.py` is updated, and a workflow generator script produces `afe_script_pipeline.json`. The fix commit addresses a slot-shift breaking change and a missing LLM Party dependency.

Watch for: (1) **asyncio.run() in API mode** — will raise if called from an existing event loop (confirmed); (2) **Chinese prop names** falling through to English image prompts when the lightweight translator can't reach ≥40 % ASCII (confirmed); (3) **json_repair** used as a fallback but absent from requirements.txt (confirmed).

**Verdict**: APPROVED

---

## High-level view

All nine checklist items pass on direct code inspection. ScriptParser now emits 9 outputs (slot indices shifted), ShotPromptBuilder emits 6 (also shifted), and the fix commit mitigated both with v2 display names and MIGRATION.md — users on old workflows need to rewire slots 2–8 and 2–5 respectively.

SceneAnalyzer, PropsAnalyzer, CharacterTracker, and ShotPromptBuilder each consume the new shot fields (location, time_of_day, weather, lighting, action, business, emotion) added to the SYSTEM_PROMPT. The fields flow end-to-end from parser through to the final per-shot English prompt, which is the core behavioral goal.

The two new nodes are thin aggregators: AFE_ShotList reformats ShotPromptBuilder output into a human-readable report and totals duration; AFE_CharacterTracker cross-references shot_sequence against cast_data to produce per-character appearance lists. Both sit at the end of the pipeline and don't affect upstream behavior.

The only runtime risk in the happy path is the LLM Party dependency — the template JSON references it in `_afe_meta.requires`, and REQUIRED_NODES.md documents the install steps, but ComfyUI itself won't surface that metadata before loading; missing nodes will produce load-time errors. The direct API fallback carries a secondary risk around asyncio, described below.

---

<details>
<summary>Issues (6)</summary>

1. **asyncio.run() in API mode** — `_call_api` wraps an async OpenAI call in `asyncio.run()`; this raises `RuntimeError` if the calling thread already owns an event loop (some ComfyUI async forks, middleware). Switch to `loop.run_until_complete()` with loop detection, or use the synchronous OpenAI client. The LLM Party path is unaffected.

2. **Chinese prop names in English prompts** — `_prop_to_english` returns the original Chinese string when ASCII ratio < 0.4. That string lands directly in an English image-generation prompt sent to Wan2.1 or Stable Diffusion. Add a user-visible warning or placeholder like `"prop: {name}"` for untranslatable entries.

3. **json_repair not in requirements.txt** — The import lives inside a try/except so failure is silent, but the dependency should be listed (even as optional). Add `json-repair` to requirements.txt with a comment that it improves handling of truncated LLM output.

4. **Slot-shift migration** — ScriptParser slots 2–8 and ShotPromptBuilder slots 2–5 changed. The fix commit adds MIGRATION.md and v2 display names. Any saved workflow JSON that hardcodes slot indices will silently wire wrong outputs without that documentation being noticed.

5. **environment_3view_prompt pipe format is an implicit contract** — The three-view prompt uses `" | "` as a separator. The downstream 3-view generator node needs to split on that separator; if it doesn't, all three views collapse into one prompt. Document this contract in the node's tooltip or docstring.

6. **API key stored in plaintext workflow JSON** — `llm_api_key` is a plain STRING widget; ComfyUI has no native sensitive/password flag, so saved workflows contain the key in plaintext JSON. Use `os.getenv("AFE_LLM_API_KEY", "")` as the default to keep keys out of saved files.

</details>

---

<details>
<summary>Details</summary>

## Checklist verification (confirmed)

All nine requirements pass on direct inspection:

- **ScriptParser**: `RETURN_TYPES` has 9 entries; `RETURN_NAMES` includes `unique_scenes_json`, `props_list_json`, `scene_count`, `props_count`; `SYSTEM_PROMPT` documents `location`, `time_of_day`, `weather`, `action`, `business`, `emotion` (plus `lighting`); `CATEGORY = "AI Film Editor/Script"`.
- **SceneAnalyzer**: reads `time_of_day`, `weather`, `location` per shot; builds `environment_3view_prompt` as three pipe-separated prompts; `CATEGORY = "AI Film Editor/Script"`.
- **PropsAnalyzer**: output dicts include `name_en`, `description_en`, `which_shots`; positive prompt starts with `PROPS_PREFIX` (single object on white background...); `CATEGORY = "AI Film Editor/Script"`.
- **ShotPromptBuilder**: 6-output `RETURN_TYPES`; `RETURN_NAMES` has `first_prompt_en`, `first_prompt_cn`; `action`, `business`, `emotion` are appended to `parts` in `_build_shot_prompt`; `CATEGORY = "AI Film Editor/Shot"`.
- **AFE_ShotList**: `STRING` input, `(STRING, INT, FLOAT, STRING)` outputs, `CATEGORY = "AI Film Editor/Shot"`.
- **AFE_CharacterTracker**: `SHOT_SEQUENCE` (required) + `CAST_DATA` (optional) inputs, `(STRING, STRING, INT)` outputs, `CATEGORY = "AI Film Editor/Script"`.
- **`__init__.py`**: both nodes imported from `nodes/analyzer/` and registered in `NODE_CLASS_MAPPINGS` and `NODE_DISPLAY_NAME_MAPPINGS`.
- **gen_afe_main_workflow.py**: file present (17 891 bytes); `py_compile` passed per commit message.
- **afe_script_pipeline.json**: file present (18 891 bytes); parses as valid JSON (UTF-8) with keys `_afe_meta`, `nodes`, `links`.

## asyncio.run() in direct API mode

`ScriptParser._call_api` creates an `AsyncOpenAI` client and runs it via `asyncio.run()`. In standard ComfyUI queue execution (threads, no existing event loop), this works. The risk is any environment that wraps node execution in an async loop — some LLM Party configurations or async ComfyUI forks do this — where `asyncio.run()` raises `RuntimeError: This event loop is already running`. The primary LLM Party path and the `llm_response` passthrough path bypass this entirely. For the API fallback, using `asyncio.get_event_loop().run_until_complete()` with a check for a running loop, or the synchronous `openai.OpenAI` client, would remove the risk.

## Chinese prop names in English prompts

`_prop_to_english` applies a 24-entry lookup table and returns the original name when it can't reach ≥40 % ASCII. The comment notes "selector/user can refine" but there is no user-visible signal. The returned Chinese string goes directly into the `positive_prompt` field that image generation nodes consume. A prop like `合同` (contract) would appear in a Wan2.1 prompt unchanged. The function should return a neutral placeholder (`"prop: {name}"`) or emit a logger.warning that lists untranslated props in the report.

## json_repair optional dependency

`_parse_json` tries three strategies for malformed LLM output: standard parse → json_repair → manual bracket extraction. The `json_repair` import is guarded by try/except so absent silently degrades to manual extraction. `requirements.txt` does not list it. For teams setting up fresh environments, adding `json-repair` as an optional dependency with a comment would make the behaviour explicit.

## Slot-shift migration and LLM Party dependency

Both ScriptParser (5 → 9 outputs) and ShotPromptBuilder (5 → 6 outputs) changed slot counts. The fix commit covers this with MIGRATION.md before/after tables and v2 suffixes in display names. `afe_script_pipeline.json` lists `comfyui_LLM_party` in `_afe_meta.requires` and REQUIRED_NODES.md now has an install section. ComfyUI doesn't natively surface `_afe_meta`, so a user opening the template without the package gets a node-not-found error at load time. The documentation is in place; the gap is that the warning only reaches users who read REQUIRED_NODES.md before importing the template.

## API key in plaintext workflow JSON

`llm_api_key` is a plain `STRING` widget. ComfyUI has no native sensitive/password flag for inputs, so any workflow that uses the direct API mode will store the key in plaintext JSON. This is an inherent ComfyUI platform limitation for now. Using environment variables (`os.getenv("AFE_LLM_API_KEY")` as the default) would keep keys out of saved workflows.

</details>

---

<details>
<summary>File map</summary>

| File | Change |
|---|---|
| `nodes/director/script_parser_node.py` | SYSTEM_PROMPT expanded with 6 new shot fields; RETURN_TYPES/NAMES expanded to 9 outputs; unique scene + prop deduplication added |
| `nodes/analyzer/scene_analyzer_node.py` | Reads time_of_day/weather/location per shot; builds environment_3view_prompt with pipe separator |
| `nodes/analyzer/props_analyzer_node.py` | Output dicts gain name_en, description_en, which_shots; white-bg PROPS_PREFIX prompt |
| `nodes/director/shot_prompt_builder_node.py` | SHOT_TYPE_MAP/CAM_MOVEMENT_CN/CAM_ANGLE_CN added; action/business/emotion woven into prompt; 6 outputs including first_prompt_en/cn |
| `nodes/analyzer/shot_list_node.py` | New AFE_ShotList node: reformats shots_prompts_json into report + total duration |
| `nodes/analyzer/character_tracker_node.py` | New AFE_CharacterTracker node: walks shot_sequence, cross-refs cast_data, per-character appearance lists |
| `__init__.py` | AFE_ShotList and AFE_CharacterTracker imported and registered |
| `gen_afe_main_workflow.py` | New script: programmatically builds afe_script_pipeline.json (14 nodes, 17 links) |
| `workflow_templates/afe_script_pipeline.json` | Generated 14-node pipeline workflow; includes _afe_meta dependency list |
| `MIGRATION.md` | New: before/after slot tables for ScriptParser and ShotPromptBuilder |
| `REQUIRED_NODES.md` | Section 5 added: comfyui_LLM_party install steps and model path |

Full diff: `git -C e:/MJ/ai_film_editor_nodes diff HEAD~2`

</details>
