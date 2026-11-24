import os
import os
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, os.path.dirname(ROOT))

from ai_film_editor_nodes.nodes.director.script_analysis_session import AnalysisSessionStore


def scene_fixture(count=36):
    return [{"scene_id": f"scene_{i:03d}", "section_type": "location_scene",
             "source_blocks": [{"source_block_id": f"block_{i:03d}",
                                 "scene_occurrence_id": f"occurrence_{i:03d}",
                                 "section_type": "location_scene",
                                 "source_text": f"Scene {i}: London market action {i}."}]}
            for i in range(1, count + 1)]


def result_for(store, batch):
    expected = [
        (item["source_block_id"], unit_id)
        for item in batch["source_unit_ranges"]
        for unit_id in item.get("unit_ids", [])
    ]
    if len(expected) != batch["shot_end"] - batch["shot_start"] + 1:
        raise AssertionError("fixture must provide one source unit per shot")
    shots = [{"shot_id": f"shot_{n:03d}", "source_unit_ids": [unit_id],
              "source_block_id": block_id}
             for n, (block_id, unit_id) in zip(
                 range(batch["shot_start"], batch["shot_end"] + 1), expected)]
    source_manifest = []
    for block_id, unit_id in expected:
        item = next((entry for entry in source_manifest
                     if entry["source_block_id"] == block_id), None)
        if item is None:
            item = {"source_block_id": block_id, "unit_ids": []}
            source_manifest.append(item)
        item["unit_ids"].append(unit_id)
    return {"shots": shots, "cast": [], "source_manifest": source_manifest}


def test_explicit_shot_headings_create_one_contiguous_source_shot_per_batch():
    with tempfile.TemporaryDirectory() as root:
        script = "\n\n".join(
            f"### 镜头{i:03d}（5秒）\n动作开始：动作{i}。\n动作结束：停住。"
            for i in range(1, 37)
        )
        scene_map = [{"scene_id": "scene_001", "source_blocks": [{
            "source_block_id": "block_001", "scene_occurrence_id": "occurrence_001",
            "section_type": "location_scene", "source_text": script,
        }]}]
        state = AnalysisSessionStore(root, batch_size=4).create(script, 36, 5, scene_map)
        assert state["total_batches"] == 9
        assert [batch["source_unit_ranges"][0]["unit_ids"] for batch in state["batches"]] == [
            [f"unit_{index:03d}" for index in range(start, start + 4)]
            for start in range(1, 37, 4)
        ]
        assert all(
            len(batch["source_unit_ranges"]) == 1
            and len(batch["source_unit_ranges"][0]["unit_ids"]) == 4
            for batch in state["batches"]
        )


def test_explicit_preamble_is_persisted_as_context_but_final_coverage_uses_36_shots():
    with tempfile.TemporaryDirectory() as root:
        script = "环境设定：伦敦超市外，夜雨。\n\n" + "\n\n".join(
            f"### 镜头{i:03d}（5秒）\n动作{i}。" for i in range(1, 37)
        )
        scene_map = [{"scene_id": "scene_001", "source_blocks": [{
            "source_block_id": "block_001", "scene_occurrence_id": "occurrence_001",
            "section_type": "location_scene", "source_text": script,
        }]}]
        store = AnalysisSessionStore(root, batch_size=4)
        state = store.create(script, 36, 5, scene_map)
        manifest = state["source_manifest"][0]
        assert manifest["context_units"][0]["text"].startswith("环境设定")
        assert manifest["unit_ids"] == [f"unit_{i:03d}" for i in range(1, 37)]
        while True:
            batch = store.claim_next()
            if batch["status"] == "complete":
                break
            store.commit_batch(batch["batch_index"], result_for(store, batch))
        final = store.status()
        assert final["analysis_status"] == "complete"
        assert len(final["parsed_shots"]) == 36
        assert final["source_manifest"][0]["context_units"][0]["text"].startswith("环境设定")


def test_ab_a_source_blocks_are_batched_in_screenplay_order():
    with tempfile.TemporaryDirectory() as root:
        scene_map = [{"scene_id": "scene_A", "source_blocks": [
            {"source_block_id": "block_001", "scene_occurrence_id": "a1", "source_text": "A first."},
            {"source_block_id": "block_003", "scene_occurrence_id": "a2", "source_text": "A again."},
        ]}, {"scene_id": "scene_B", "source_blocks": [
            {"source_block_id": "block_002", "scene_occurrence_id": "b1", "source_text": "B between."},
        ]}]
        state = AnalysisSessionStore(root, batch_size=1).create("A/B/A", 3, 5, scene_map)
        assert [b["source_block_ids"] for b in state["batches"]] == [["block_001"], ["block_002"], ["block_003"]]
        assert [m["source_block_id"] for m in state["source_manifest"]] == ["block_001", "block_002", "block_003"]


def test_unverified_batch_is_failed_and_retryable():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=4)
        store.create("script", 4, 5, scene_fixture(4))
        batch = store.claim_next()
        result = result_for(store, batch)
        result["shots"][0]["source_validation_error"] = "bad source"
        try:
            store.commit_batch(1, result)
        except ValueError as exc:
            assert "未验证" in str(exc)
        else:
            raise AssertionError("unverified source was accepted")
        assert store.status()["batches"][0]["status"] == "failed"
        store.retry(1)
        assert store.status()["batches"][0]["status"] == "pending"


def test_valid_script_without_characters_or_props_keeps_empty_paths():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=4)
        store.create("TITLE CARD\nA room with light.", 1, 5, scene_fixture(1), cast=[])
        batch = store.claim_next()
        result = result_for(store, batch)
        result["cast"] = []
        result["shots"][0].pop("source_unit_ids", None)
        result["shots"][0]["source_unit_ids"] = ["unit_001"]
        state = store.commit_batch(1, result)
        assert state["cast"] == [] and state["analysis_status"] == "complete"


def test_36_shots_persist_every_batch_and_resume_after_interruption():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=4)
        store.create("script", 36, 5, scene_fixture())
        completed = set()
        interrupted = False
        while True:
            reopened = AnalysisSessionStore(root, batch_size=4)
            batch = reopened.claim_next()
            if batch["status"] == "complete":
                break
            assert batch["batch_index"] not in completed
            if batch["batch_index"] == 5 and not interrupted:
                # Simulate a process/ComfyUI restart while the fifth claim is running.
                AnalysisSessionStore(root, batch_size=4).recover_orphaned_running()
                failed = AnalysisSessionStore(root, batch_size=4).status()
                assert failed["batches"][4]["status"] == "failed"
                AnalysisSessionStore(root, batch_size=4).retry(5)
                batch = AnalysisSessionStore(root, batch_size=4).claim_next()
                interrupted = True
            result = result_for(reopened, batch)
            state = AnalysisSessionStore(root, batch_size=4).commit_batch(
                batch["batch_index"], result
            )
            completed.add(batch["batch_index"])
            restored = AnalysisSessionStore(root, batch_size=4).status()
            assert restored["completed_batches"] == sorted(completed)
            assert len(restored["parsed_shots"]) == len(completed) * 4
            assert all(item["source_manifest"] for item in [result])
            assert state["analysis_status"] in {"partial", "complete"}
        final = AnalysisSessionStore(root, batch_size=4).status()
        assert interrupted
        assert final["analysis_status"] == "complete"
        assert final["completed_batches"] == list(range(1, 10))
        assert final["completed_shot_count"] == 36
        assert len(final["parsed_shots"]) == 36
        # A repeated continue after completion cannot claim or submit any batch.
        assert AnalysisSessionStore(root, batch_size=4).claim_next()["status"] == "complete"


def test_completed_batch_is_idempotent_and_failed_batch_only_retries_it():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=4)
        store.create("script", 8, 5, scene_fixture(8))
        batch = store.claim_next()
        result = result_for(store, batch)
        store.commit_batch(1, result)
        store.commit_batch(1, result)
        assert store.status()["completed_batches"] == [1]
        second = store.claim_next()
        store.fail_batch(second["batch_index"], "Qwen returned only 2 shots")
        assert store.status()["failed_batches"] == [2]
        assert store.claim_next()["status"] == "failed"
        store.retry(2)
        assert store.status()["batches"][1]["status"] == "pending"
        assert store.status()["completed_batches"] == [1]


def test_cancel_and_restart_recover_running_without_losing_completed_results():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=4)
        store.create("script", 8, 5, scene_fixture(8))
        first = store.claim_next("running-prompt")
        store.commit_batch(1, result_for(store, first))
        store.claim_next("lost-prompt")
        AnalysisSessionStore(root, batch_size=4).recover_orphaned_running()
        state = store.status()
        assert state["completed_batches"] == [1]
        assert state["batches"][1]["status"] == "failed"
        assert "重启" in state["batches"][1]["error"]


def test_recovery_publishes_durable_batch_result_after_session_write_gap():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=4)
        store.create("script", 4, 5, scene_fixture(4))
        batch = store.claim_next("lost-prompt")
        result = result_for(store, batch)
        result_path = os.path.join(root, "batches", "batch_001.json")
        os.makedirs(os.path.dirname(result_path), exist_ok=True)
        with open(result_path, "w", encoding="utf-8") as fh:
            import json
            json.dump(result, fh)
        recovered = AnalysisSessionStore(root, batch_size=4)
        recovered.recover_orphaned_running()
        state = recovered.status()
        assert state["completed_batches"] == [1]
        assert state["batches"][0]["status"] == "completed"
        assert state["parsed_shots"] == result["shots"]


def test_source_manifest_duplicate_is_rejected_and_empty_cast_props_are_valid():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=4)
        store.create("script", 4, 5, scene_fixture(4))
        batch = store.claim_next()
        result = result_for(store, batch)
        result["source_manifest"] = [{"source_block_id": "block_001", "unit_ids": ["unit_001", "unit_001"]}]
        try:
            store.commit_batch(1, result)
        except ValueError as exc:
            assert "重复" in str(exc) or "覆盖错误" in str(exc)
        else:
            raise AssertionError("duplicate source unit was accepted")
        assert store.status()["batches"][0]["status"] == "failed"
        assert store.status()["cast"] == []


def test_cast_from_earlier_batches_is_retained_and_source_units_are_not_reused():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=1)
        store.create("script", 2, 5, scene_fixture(2))
        first = store.claim_next()
        first_result = result_for(store, first)
        first_result["cast"] = [{"name": "Mina", "role_type": "lead"}]
        store.commit_batch(1, first_result)
        second = store.claim_next()
        second_result = result_for(store, second)
        second_result["cast"] = [{"name": "Bo", "role_type": "support"}]
        state = store.commit_batch(2, second_result)
        assert [item["name"] for item in state["cast"]] == ["Mina", "Bo"]
        assert state["analysis_status"] == "complete"


def test_create_keeps_unsafe_uncovered_batches_pending_without_reusing_source_units():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=1)
        state = store.create("script", 2, 5, scene_fixture(1))
        assert state["batches"][0]["source_unit_ranges"]
        assert state["batches"][1]["source_unit_ranges"] == []


def test_concurrent_claim_returns_existing_owner_without_second_claim():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=4)
        store.create("script", 4, 5, scene_fixture(4))
        owner = store.claim_next()
        contender = AnalysisSessionStore(root, batch_size=4).claim_next()
        assert owner["claimed"] is True
        assert contender["claimed"] is False
        assert contender["batch_index"] == owner["batch_index"]
        assert contender["submission_pending"] is True


def test_cancel_only_changes_matching_running_batch_and_preserves_completed_results():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=4)
        store.create("script", 8, 5, scene_fixture(8))
        first = store.claim_next("prompt-1")
        store.commit_batch(1, result_for(store, first))
        second = store.claim_next("prompt-2")
        try:
            store.cancel(batch_index=2, prompt_id="old-prompt")
        except ValueError as exc:
            assert "未取消" in str(exc)
        else:
            raise AssertionError("stale cancellation changed the active batch")
        state = store.status()
        assert state["completed_batches"] == [1]
        assert state["batches"][1]["status"] == "running"
        store.cancel(batch_index=second["batch_index"], prompt_id="prompt-2")
        assert store.status()["batches"][1]["status"] == "pending"


def test_cancel_without_active_batch_does_not_change_session():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=4)
        before = store.create("script", 4, 5, scene_fixture(4))
        try:
            store.cancel(prompt_id="not-running")
        except ValueError as exc:
            assert "没有可取消" in str(exc)
        else:
            raise AssertionError("cancellation without an active batch was accepted")
        state = store.status()
        assert state["batches"] == before["batches"]
        assert state["current_batch"] is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
