# AFE Node Migration Guide

## v2 Output Slot Changes

Two nodes changed their output slot count and ordering in this release. ComfyUI
resolves wired connections by **slot index**, not by name, so any workflow saved
against the previous version must be **manually rewired** after updating.

Both nodes are now labelled **"v2"** in the node picker so you can spot them
after a reload.

---

### AFE_ScriptParser — 5 → 9 outputs

| Slot | Old (v1) | New (v2) |
|------|----------|----------|
| 0 | shot_sequence (SHOT_SEQUENCE) | shot_sequence (SHOT_SEQUENCE) ✅ unchanged |
| 1 | cast_data (CAST_DATA) | cast_data (CAST_DATA) ✅ unchanged |
| 2 | shot_count (INT) | unique_scenes_json (STRING) ⚠️ changed |
| 3 | sequence_json (STRING) | props_list_json (STRING) ⚠️ changed |
| 4 | prompt_for_llm (STRING) | shot_count (INT) ⚠️ changed |
| 5 | — | scene_count (INT) 🆕 |
| 6 | — | props_count (INT) 🆕 |
| 7 | — | sequence_json (STRING) ⚠️ moved from slot 3 |
| 8 | — | prompt_for_llm (STRING) ⚠️ moved from slot 4 |

**Action required:** Delete and re-add `AFE_ScriptParser` in existing workflows,
then rewire slots 2–4 to their new indices.

---

### AFE_ShotPromptBuilder — 5 → 6 outputs

| Slot | Old (v1) | New (v2) |
|------|----------|----------|
| 0 | shots_prompts_json (STRING) | shots_prompts_json (STRING) ✅ unchanged |
| 1 | shot_count (INT) | shot_count (INT) ✅ unchanged |
| 2 | first_positive (STRING) | first_prompt_en (STRING) ⚠️ renamed |
| 3 | first_negative (STRING) | first_prompt_cn (STRING) ⚠️ changed |
| 4 | report (STRING) | first_negative (STRING) ⚠️ moved from slot 3 |
| 5 | — | report (STRING) ⚠️ moved from slot 4 |

**Action required:** Any node wired to slot 3 (old `first_negative`) now receives
`first_prompt_cn`. Any node wired to slot 4 (old `report`) now receives
`first_negative`. Re-add the node and rewire slots 2–5.

---

### Category changes

Both nodes moved to new categories in the ComfyUI node picker:

| Node | Old category | New category |
|------|-------------|--------------|
| AFE_ScriptParser | AI Film Editor/Director | AI Film Editor/Script |
| AFE_ShotPromptBuilder | AI Film Editor/Director | AI Film Editor/Shot |

If you used the old category path to find these nodes, look under the new
category after updating.

---

## LLM Party requirement

The `afe_script_pipeline.json` workflow template requires
[comfyui_LLM_party](https://github.com/heshengtao/comfyui_LLM_party) for nodes
1–2 (`LLM_local_loader`, `LLM_local`) and nodes 10–14 (`show_text_party`). The
AFE analysis nodes (3–9) work without it, but the full pipeline will not load in
ComfyUI until LLM Party is installed.

See **REQUIRED_NODES.md → Section 5** for install instructions.
