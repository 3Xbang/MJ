# Canonical source mapping for RunPod screenplay batches

FEAT-001 makes the persisted screenplay source catalog authoritative for explicit-shot batches instead of trusting model-supplied IDs, ranges, or fragments. It carries each indivisible heading-plus-body unit through Phase 1, Phase 2, and the returned analysis while limiting Phase 2 to the current shot and non-shot context. FEAT-002 adds a CPU-stub regression over the complete 36-shot screenplay, nine batches of four, session recovery, and final publish validation. The feature diff contains only the parser change and the new regression test; it does not change UI, workflow templates, session storage, or the pre-existing review, log, cache, and task artifacts.

Watch for: **confirmed** the target RunPod/Qwen/ComfyUI smoke remains unverified, so the original `shot_001` failure is not closed in the deployment where it occurred; **confirmed** the required compatibility evidence is incomplete because the UI E2E retry was interrupted and the explicit-boundary script was only module-loaded.

**Verdict**: NEEDS_CHANGES

## High-level view

Persisted `source_unit_ranges` now define the explicit batch contract. The parser canonicalizes each returned Phase 1 item from batch-local screenplay order before coverage and fact validation, preserving the heading and body as one source unit and rejecting a mismatch between persisted explicit units and the requested range.

Phase 2 receives the canonical fragment for the current shot and only non-shot context reconstructed from its source block. The resulting source text, IDs, occurrence identity, and offsets flow into the session manifest and its existing order, duplicate, and publish gates.

The regression exercises all 36 shots as nine four-shot batches, including shot_001 provenance, cross-boundary sibling exclusion, cancellation/reclaim, durable recovery, ordered completion, and final schema validation. **confirmed** its CPU stub deliberately omits model source metadata, so it tests canonical binding but does not substitute for an actual Qwen/ComfyUI RunPod execution.

<details>
<summary>Issues (2)</summary>

1. **RunPod model-path smoke** — **confirmed**: the evidence explicitly leaves Qwen, GPU, RunPod, and real ComfyUI unverified. Run the target screenplay-batch path and capture `shot_001` source text/IDs/offsets, sibling isolation, and strict blocking of invalid evidence before approval.
2. **Incomplete compatibility evidence** — **confirmed**: `tests/ui_e2e.py` was interrupted by the local Windows runner after retry, and `tests/test_explicit_shot_batch_boundaries.py` was only loaded because it has no executable runner. Complete the required compatibility checks in a supported environment, or record an accepted exception before approval.

</details>

<details>
<summary>Details</summary>

## Persisted explicit units and Phase 2 isolation

`_canonical_explicit_batch_catalog` walks the supplied scene map in screenplay order, filters to persisted `batch_unit_ids`, and rebuilds each fragment from persisted source offsets (`nodes/director/script_full_parser_node.py:1217-1259`). The parser applies that catalog before source coverage and fact validation (`:1504-1539`). The source-unit parser and session planner keep each explicit heading with its body and select units one-for-one, covering indivisibility, batch-local ranges, and ordered 9-by-4 partitioning.

For each explicit shot, `_explicit_source_context` rebuilds only `is_context` units from the complete source block, while the exact shot fragment is carried into the Phase 2 prompt and returned fields (`nodes/director/script_full_parser_node.py:1262-1267, 1651-1708, 1810-1818`). The regression checks both sides of the batch-2/batch-3 source-block boundary and asserts that adjacent shot text is absent from each prompt (`tests/test_full_script_batch_regression.py:224-294`).

## Strict blocking, recovery, and publication coverage

The parser raises when a shot lacks a validated source fragment (`nodes/director/script_full_parser_node.py:1743-1747`), and the session commit path rejects source errors, foreign or duplicate manifest units, wrong order, and incomplete batches (`nodes/director/script_analysis_session.py:358-375, 483-530`). The new regression returns invented model metadata, then verifies canonical source text, IDs, offsets, scene occurrence, contiguous shot IDs, cancellation/reclaim, batch-five durable recovery, complete session state, `_assembled_analysis`, and `_validate_analysis_payload` (`tests/test_full_script_batch_regression.py:65-104, 224-350`).

## RunPod and compatibility verification boundary

**confirmed**: the verification records in `E:\MJ\.agents\tasks\fix-runpod-screenplay-source-mapping\features\FEAT-001.json` and `FEAT-002.json` report CPU-stub and static/package checks, but explicitly say that real Qwen/Krea/Wan, ComfyUI, RunPod, and the new-Pod `shot_001` smoke were not run. **confirmed**: the CPU regression therefore cannot prove model loading, real Phase 1 output shape, ComfyUI node wiring, or the target deployment's original failure path.

**confirmed**: the same records say the UI E2E run was first affected by a local port conflict and then interrupted by the Windows runner. FEAT-001 also records that `tests/test_explicit_shot_batch_boundaries.py` only completed module loading because it has no `__main__` runner. The other listed CPU/session/parser/prompt/reference/shot/WebUI/graph and compile checks are reported passing, and the feature diff has no UI or workflow changes, but the requested compatibility evidence remains incomplete.

## File map

- `nodes/director/script_full_parser_node.py` — binds explicit batch shots to persisted source units and isolates Phase 2 context.
- `tests/test_full_script_batch_regression.py` — adds the 36-shot, nine-batch CPU/session/recovery/publication regression.

Full diff: `E:\MJ\ai_film_editor_nodes` (`git diff origin/main...HEAD`).
