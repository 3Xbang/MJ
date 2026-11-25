# Two-phase LLM parser replaces LLM_local chain in script pipeline

Replaces the LLM_local_loader → LLM_local → AFE_ScriptParser three-node chain with a single `AFE_ScriptFullParser` node that calls Qwen2.5-7B-Instruct directly via transformers. The motivation is the output-token ceiling on LLM_local: the old chain had to produce the full shot sequence in one call; now Phase 1 extracts a compact skeleton (~80 tokens/shot), and Phase 2 runs one dedicated call per shot to fill in cinematic detail with a 768-token budget each. The workflow drops from 16 to 15 links after a follow-up commit fixes a duplicate link ID, a missing `director_notes` field, and dead constants in the generator. Watch for: Phase 1's `max_new_tokens=2048` budget silently truncates scripts with more than ~20–25 shots, and no code path detects or logs how many shots were dropped.

**Verdict**: APPROVED

---

## High-level view

The two-phase split is well-suited to the stated constraint. Phase 1 produces a compact {cast, shots} skeleton with one LLM call; Phase 2 issues one call per shot for deep cinematographic analysis within a fixed 768-token budget. This directly solves the original user concern—each call is independently bounded, so longer scripts no longer hit a single output ceiling. The tradeoff is that Phase 1 itself can still truncate if the script has enough shots to fill the 2048-token budget; there is no detection path for this case.

The workflow wiring is complete: `AFE_ScriptFullParser`'s `shot_sequence` fans out to all five downstream SHOT_SEQUENCE consumers, and `cast_data` reaches the three nodes that need it (CastAnalyzer, CharacterTracker, ShotPromptBuilder). All 15 link IDs are consistent between `gen_afe_main_workflow.py` and the regenerated JSON. One gap: CastAnalyzer node 4 has no outgoing connections in the workflow—its `characters_json` and `characters_count` outputs are both `null`, and there is no display node for it. Whether this is intentional or an oversight is worth confirming.

`_parse_llm_json` handles the most common LLM output failures—markdown fences, partial JSON, malformed objects—through a three-tier fallback ending with `json_repair`. The gap is Phase 1 truncation: if the LLM hits its token limit mid-array, `json_repair` may reconstruct a partial shot list silently. The only user-visible effect is fewer shots than the script implies, with no warning distinguishing "short script" from "truncated output."

`trust_remote_code=True` is passed to both `AutoTokenizer` and `AutoModelForCausalLM`. This is standard for Qwen2.5-7B-Instruct, which requires custom tokenizer code, but it means the model repository code executes on load. Users should source the model from the official Qwen HuggingFace repository.

The class-level model cache (`_model`, `_tokenizer`, `_model_path_loaded`) loads the 7B model once per session and skips reloads when the path is unchanged. If `model_path` changes between runs, the old model and tokenizer are replaced in-place without an explicit CUDA memory release, which can cause OOM on VRAM-constrained hardware before the Python GC reclaims the old tensors.

---

<details>
<summary>Issues (5)</summary>

1. **Phase 1 silent truncation** — `max_new_tokens=2048` in Phase 1 fits roughly 20–25 shots in minimal form; scripts with more shots will produce a partial `shots` array after `json_repair` with no warning. Add a post-Phase-1 log comparing `len(minimal_shots)` against a rough estimate (e.g., script word count ÷ average shot length) to surface this.

2. **CastAnalyzer output disconnected** — Node 4 (`AFE_CastAnalyzer`) has no outgoing connections in `afe_script_pipeline.json` and no corresponding display node in `gen_afe_main_workflow.py`. Confirm whether this is intentional; if not, add a `show_text_party` for `characters_json` output at node 4 slot 0.

3. **Model hotswap VRAM leak** — `_ensure_model` overwrites `cls._model` and `cls._tokenizer` without calling `del` or clearing CUDA cache first. On VRAM-constrained hardware, the old model tensors may remain on the GPU until GC runs, causing an OOM before the new model loads. Add `del cls._model; del cls._tokenizer; torch.cuda.empty_cache()` before the new `from_pretrained` call.

4. **`trust_remote_code=True` without source verification** — both tokenizer and model load with `trust_remote_code=True`. This executes arbitrary Python from the model's repo on load. Document the expected model source (official Qwen HuggingFace repo) in a comment or README so users know what they're trusting.

5. **Docstring / code mismatch** — The class docstring says "Phase 1 (~750 tokens output)" but the call uses `max_new_tokens=2048`. The file-level docstring correctly says "~2048 tokens output." Fix the class docstring to avoid confusion about the actual budget.

</details>

---

<details>
<summary>Details</summary>

### Phase 1 budget and silent truncation

Phase 1 fires a single LLM call with `max_new_tokens=2048`. Each minimal shot entry has six fields with `raw_description` capped at 60 words (~90 tokens). At that rate, 20 shots consume roughly 1800 tokens of output, leaving ~200 tokens for cast and JSON framing. For scripts with 25+ shots the LLM hits the token ceiling mid-array. `_parse_llm_json` will attempt `json_repair`, which may recover a partial list, but the return value silently has fewer shots than the script contains. The `logger.warning` in `_parse_llm_json` fires only if all three repair strategies fail; a `json_repair` partial success produces no log at all.

A minimal mitigation is to log `len(minimal_shots)` prominently and compare it against a crude estimate (script character count or scene-break count) so users see the discrepancy immediately rather than discovering missing shots downstream.

### CastAnalyzer disconnect

Node 4 (`AFE_CastAnalyzer`) receives both `shot_sequence` and `cast_data` correctly, but its output slots—`characters_json` and `characters_count`—have `"links": null`. The generator's `display_configs` list in `gen_afe_main_workflow.py` has display nodes for SceneAnalyzer, PropsAnalyzer, CharacterTracker, ShotPromptBuilder, ShotList, and ScriptFullParser, but not CastAnalyzer. This means CastAnalyzer runs and produces data that goes nowhere visible in the pipeline. If CastAnalyzer's output is consumed by generation nodes not in this analysis workflow, the gap is intentional. If it was meant to have a display node, it was dropped during the topology rebuild.

### Full shot schema: Phase 2 fallback behavior

When Phase 2 fails for a shot (exception caught), `p2_data` is `{}`, so all Phase 2 fields fall back to their defaults: empty strings for text fields, `"medium"` for `camera_angle`, `"static"` for `camera_motion`, `"ugly, blurry, low quality, distorted"` for `negative_prompt`. Downstream nodes receive a structurally complete shot dict even on Phase 2 failure, but with no cinematic detail—`shot_description` falls back to `raw_desc` from Phase 1, so the prompt builder gets a 60-word plain description instead of a Wan2.1-optimized one.

### Model hotswap and VRAM

The hotswap path (`model_path` changes between runs) overwrites `cls._model` and `cls._tokenizer` without an explicit CUDA memory release before the new `from_pretrained` call. With a 7B float16 model occupying ~14 GB VRAM, this requires headroom for two models simultaneously during the transition. On cards with 16–24 GB VRAM this may OOM before the GC reclaims the old model.

### Trust boundary: `trust_remote_code=True`

The risk is that a tampered or spoofed model directory executes arbitrary code on load. The expected mitigation is sourcing from the official `Qwen/Qwen2.5-7B-Instruct` HuggingFace repository. Neither source verification nor hash checking is enforced in code, which is standard for local deployments, but users who point `model_path` at community fine-tunes should be warned explicitly.

### Test coverage

Not tested: `_parse_llm_json` behavior on truncated Phase 1 output, Phase 2 exception isolation (only the happy path and total-failure path were exercised by the live run), model hotswap memory behavior, and the `folder_paths` import fallback when running outside ComfyUI. `_parse_llm_json` is a pure function with multiple fallback paths and would be straightforward to cover with parametrized unit tests—it's the highest-value unverified component given that truncation is the primary production risk.

</details>

---

<details>
<summary>File map</summary>

| File | Change |
|---|---|
| `nodes/director/script_full_parser_node.py` | New node: two-phase LLM parser with class-level model cache, full 22-field shot schema, `_parse_llm_json` helper; fix commit adds `director_notes` to Phase 2 prompt and per-shot exception isolation |
| `__init__.py` | Part 14 import and registration of `AFE_ScriptFullParser` in both mappings |
| `gen_afe_main_workflow.py` | Replaced `build_workflow()`: removes LLM_local_loader + LLM_local + AFE_ScriptParser, inserts single `AFE_ScriptFullParser` node, adds show_text_party node 13 for the report output; fix commit removes dead `SYSTEM_PROMPT_EN`/`SCRIPT_PLACEHOLDER` constants and fixes orphaned `lnk_sp7` |
| `workflow_templates/afe_script_pipeline.json` | Regenerated: 13 nodes, 15 links, `last_link_id` corrected from 16 to 15, `shots_prompts_json` input on node 7 updated from link 16 to link 13 |

Full diff: `git -C e:/MJ/ai_film_editor_nodes diff origin/main HEAD`
</details>
