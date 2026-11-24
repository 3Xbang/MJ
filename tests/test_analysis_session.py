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
    state = store.load()
    ranges = batch["source_unit_ranges"]
    shots = [{"shot_id": f"shot_{n:03d}", "source_unit_ids": ["unit_001"],
              "source_block_id": ranges[min(n - batch["shot_start"], len(ranges) - 1)]["source_block_id"]}
             for n in range(batch["shot_start"], batch["shot_end"] + 1)]
    return {"shots": shots, "cast": [], "source_manifest": ranges}


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


def test_36_shots_make_nine_contiguous_batches_and_resume():
    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=4)
        store.create("script", 36, 5, scene_fixture())
        assert store.status()["total_batches"] == 9
        first = store.claim_next("p1")
        assert (first["shot_start"], first["shot_end"]) == (1, 4)
        store.commit_batch(1, result_for(store, first))
        again = store.claim_next("p2")
        assert again["batch_index"] == 2
        restored = AnalysisSessionStore(root, batch_size=4).status()
        assert restored["completed_batches"] == [1]
        assert restored["completed_shot_count"] == 4


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
