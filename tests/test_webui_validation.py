import asyncio
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))

from ai_film_editor_nodes.webui.server import (
    _validate_analysis_payload, Api, MAX_REF_UPLOAD_BYTES,
)
from ai_film_editor_nodes.nodes.video.analysis_loader_node import AFE_AnalysisLoader
import ai_film_editor_nodes.nodes.video.analysis_loader_node as analysis_loader_module


from ai_film_editor_nodes.webui import graphs
from ai_film_editor_nodes.nodes.video.cast_ref_generator_node import AFE_CastRefGenerator
from ai_film_editor_nodes.nodes.analyzer.props_image_generator_node import AFE_PropsImageGenerator


def test_valid_no_character_no_prop_analysis_keeps_asset_skip_paths():
    payload = _complete_analysis()
    payload["cast"] = []
    _validate_analysis_payload(payload)
    prompt, _ = graphs.build_prompt(2, "empty-cast-props", graphs.DEFAULTS, "test-output")
    assert prompt["6"]["class_type"] == "AFE_CastRefGenerator"
    assert prompt["5"]["class_type"] == "AFE_PropsImageGenerator"
    cast = AFE_CastRefGenerator().generate([], "style", approved=True)
    props = AFE_PropsImageGenerator().generate("", "[]", approved=True)
    assert "跳过角色参考图" in cast["ui"]["text"][0]
    assert "跳过道具参考图" in props["ui"]["text"][0]


def test_webui_rejects_truncated_structured_analysis():
    try:
        _validate_analysis_payload({"shots": [{"shot_id": "shot_001"}]})
    except ValueError as exc:
        assert "当前版本" in str(exc)
    else:
        raise AssertionError("web UI accepted an analysis without source identity")


def _complete_analysis(unit_ids=("unit_001",)):
    return {
        "schema_version": "afe-analysis-v1", "analysis_status": "complete", "expected_shot_count": 1,
        "source_manifest": [{"order": 0, "source_block_id": "block_001", "unit_ids": list(unit_ids)}],
        "shots": [{"shot_id": "shot_001", "scene_id": "scene_001",
                   "scene_occurrence_id": "occurrence_001", "source_block_id": "block_001",
                   "source_unit_ids": list(unit_ids), "section_type": "location_scene"}],
    }


def test_webui_accepts_complete_structured_analysis():
    _validate_analysis_payload(_complete_analysis())


def test_explicit_context_is_retained_while_36_shot_publication_passes():
    import tempfile
    from ai_film_editor_nodes.nodes.director.script_analysis_session import AnalysisSessionStore
    with tempfile.TemporaryDirectory() as root:
        script = "环境设定：伦敦超市外，夜雨。\n\n" + "\n\n".join(
            f"### 镜头{i:03d}（5秒）\n动作{i}。" for i in range(1, 37)
        )
        scene_map = [{"scene_id": "scene_001", "source_blocks": [{
            "source_block_id": "block_001", "scene_occurrence_id": "occurrence_001",
            "section_type": "location_scene", "source_text": script,
        }]}]
        store = AnalysisSessionStore(os.path.join(root, "session"), 4)
        store.create(script, 36, 5, scene_map)
        while True:
            batch = store.claim_next()
            if batch["status"] == "complete":
                break
            expected = [(item["source_block_id"], unit_id)
                        for item in batch["source_unit_ranges"]
                        for unit_id in item["unit_ids"]]
            shots = [{"shot_id": f"shot_{number:03d}", "scene_id": "scene_001",
                      "scene_occurrence_id": "occurrence_001", "source_block_id": block_id,
                      "source_unit_ids": [unit_id], "section_type": "location_scene"}
                     for number, (block_id, unit_id) in zip(
                         range(batch["shot_start"], batch["shot_end"] + 1), expected)]
            manifest = [{"source_block_id": batch["source_unit_ranges"][0]["source_block_id"],
                         "unit_ids": [unit_id for _, unit_id in expected]}]
            store.commit_batch(batch["batch_index"], {"shots": shots, "cast": [],
                                                        "source_manifest": manifest})
        analysis = Api(root, "http://127.0.0.1:8188")._assembled_analysis(store.status())
        assert len(analysis["shots"]) == 36
        assert analysis["source_manifest"][0]["unit_ids"] == [f"unit_{i:03d}" for i in range(1, 37)]
        assert analysis["source_manifest"][0]["context_units"][0]["text"].startswith("环境设定")


def test_downstream_loader_rejects_partial_or_orphan_analysis():
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "analysis.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": "afe-analysis-v1", "analysis_status": "partial",
                       "session_signature": "orphan", "expected_shot_count": 0,
                       "shots": [], "source_manifest": []}, fh)
        original = analysis_loader_module.analysis_path
        analysis_loader_module.analysis_path = lambda _project: path
        try:
            try:
                AFE_AnalysisLoader().load("orphan")
            except ValueError as exc:
                assert "尚未完成" in str(exc)
            else:
                raise AssertionError("downstream loader accepted partial analysis")
        finally:
            analysis_loader_module.analysis_path = original


def test_stage_two_rejects_orphan_analysis_without_session():
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        api = Api(root, "http://127.0.0.1:8188")
        project = api.project_path("orphan")
        os.makedirs(project, exist_ok=True)
        with open(os.path.join(project, "ui_state.json"), "w", encoding="utf-8") as fh:
            json.dump({"settings": {"script": "script", "duration": 5, "seconds_per_shot": 5}}, fh)
        with open(os.path.join(project, "analysis.json"), "w", encoding="utf-8") as fh:
            json.dump(_complete_analysis(), fh)

        class Request:
            async def json(self):
                return {"project": "orphan", "stage": 2}

        response = asyncio.run(api.run(Request()))
        assert response.status == 400


def test_webui_rejects_missing_manifest_even_with_identity_fields():
    payload = _complete_analysis()
    payload.pop("source_manifest")
    try:
        _validate_analysis_payload(payload)
    except ValueError as exc:
        assert "来源清单" in str(exc)
    else:
        raise AssertionError("web UI accepted analysis without source manifest")


def test_webui_rejects_incomplete_source_unit_coverage():
    payload = _complete_analysis(("unit_001", "unit_002"))
    payload["shots"][0]["source_unit_ids"] = ["unit_001"]
    try:
        _validate_analysis_payload(payload)
    except ValueError as exc:
        assert "遗漏原文单元" in str(exc)
    else:
        raise AssertionError("web UI accepted incomplete source-unit coverage")



def test_webui_rejects_source_order_error():
    payload = _complete_analysis()
    payload["source_manifest"][0]["order"] = 1
    try:
        _validate_analysis_payload(payload)
    except ValueError as exc:
        assert "顺序" in str(exc)
    else:
        raise AssertionError("web UI accepted reordered source manifest")


    import tempfile
    from ai_film_editor_nodes.webui.server import Api
    with tempfile.TemporaryDirectory() as root:
        refs = os.path.join(root, "refs")
        os.makedirs(refs)
        path = os.path.join(refs, "cast_asset.png")
        with open(path, "wb") as handle:
            handle.write(b"first")
        api = Api(root, "http://127.0.0.1:8188")
        first = api.ref_sig(root)
        with open(path, "wb") as handle:
            handle.write(b"second")
        second = api.ref_sig(root)
        assert first != second


def test_project_view_hides_stale_analysis_and_dependent_references():
    import tempfile
    from ai_film_editor_nodes.nodes.director.script_analysis_session import AnalysisSessionStore
    with tempfile.TemporaryDirectory() as root:
        api = Api(root, "http://127.0.0.1:8188")
        project = api.project_path("stale")
        os.makedirs(project, exist_ok=True)
        old_script = "【场景 A：旧地点】旧镜头。"
        store = AnalysisSessionStore(os.path.join(project, "analysis_session"), 4)
        session = store.create(old_script, 1, 5, [{"scene_id": "scene_old", "source_blocks": [{
            "source_block_id": "block_old", "source_text": old_script,
        }]}], cast=[])
        session["analysis_status"] = "complete"
        store.save(session)
        analysis = _complete_analysis()
        analysis["session_signature"] = session["script_signature"]
        with open(os.path.join(project, "analysis.json"), "w", encoding="utf-8") as fh:
            json.dump(analysis, fh)
        with open(os.path.join(project, "ui_state.json"), "w", encoding="utf-8") as fh:
            json.dump({"settings": {"script": "【场景 B：新地点】新镜头。", "duration": 5,
                                     "seconds_per_shot": 5}}, fh)
        view = api.project_view("stale")
        assert view["stale_analysis"] is True
        assert view["has_analysis"] is False
        assert view["analysis"] is None
        assert view["refs"] == {"cast": {}, "scene": {}, "prop": {}}


def test_project_view_allows_matching_completed_analysis():
    import tempfile
    from ai_film_editor_nodes.nodes.director.script_analysis_session import AnalysisSessionStore
    with tempfile.TemporaryDirectory() as root:
        api = Api(root, "http://127.0.0.1:8188")
        project = api.project_path("current")
        os.makedirs(project, exist_ok=True)
        script = "【场景 A：地点】镜头。"
        store = AnalysisSessionStore(os.path.join(project, "analysis_session"), 4)
        session = store.create(script, 1, 5, [{"scene_id": "scene_current", "source_blocks": [{
            "source_block_id": "block_current", "source_text": script,
        }]}], cast=[])
        session["analysis_status"] = "complete"
        store.save(session)
        analysis = _complete_analysis()
        analysis["session_signature"] = session["script_signature"]
        with open(os.path.join(project, "analysis.json"), "w", encoding="utf-8") as fh:
            json.dump(analysis, fh)
        with open(os.path.join(project, "ui_state.json"), "w", encoding="utf-8") as fh:
            json.dump({"settings": {"script": script, "duration": 5,
                                     "seconds_per_shot": 5}}, fh)
        view = api.project_view("current")
        assert view["stale_analysis"] is False
        assert view["has_analysis"] is True


def test_collect_rejects_delayed_prompt_without_mutating_current_batch():
    import tempfile
    from ai_film_editor_nodes.nodes.director.script_analysis_session import AnalysisSessionStore
    with tempfile.TemporaryDirectory() as root:
        api = Api(root, "http://127.0.0.1:8188")
        project = api.project_path("collect-stale")
        store = AnalysisSessionStore(os.path.join(project, "analysis_session"), 4)
        store.create("script", 1, 5, [{"scene_id": "scene_1", "source_blocks": [{
            "source_block_id": "block_1", "source_text": "A room with light."
        }]}])
        store.claim_next("current-prompt")

        class Request:
            async def json(self):
                return {"project": "collect-stale", "stage": 1, "prompt_id": "old-prompt"}

        response = asyncio.run(api.collect(Request()))
        assert response.status == 409
        assert store.status()["batches"][0]["status"] == "running"
        assert store.status()["batches"][0]["prompt_id"] == "current-prompt"


def test_cancel_releases_submission_pending_claim_without_prompt_id():
    import tempfile
    from ai_film_editor_nodes.nodes.director.script_analysis_session import AnalysisSessionStore
    with tempfile.TemporaryDirectory() as root:
        api = Api(root, "http://127.0.0.1:8188")
        project = api.project_path("pending-cancel")
        store = AnalysisSessionStore(os.path.join(project, "analysis_session"), 4)
        store.create("script", 1, 5, [{"scene_id": "scene_1", "source_blocks": [{
            "source_block_id": "block_1", "source_text": "A room with light."
        }]}], cast=[])
        claimed = store.claim_next()

        class Request:
            can_read_body = True
            async def json(self):
                return {"project": "pending-cancel", "stage": 1}

        response = asyncio.run(api.cancel(Request()))
        assert response.status == 200
        assert store.status()["batches"][0]["status"] == "pending"
        assert store.status()["current_batch"] is None
        try:
            store.set_prompt(claimed["batch_index"], "late-prompt", claimed["claim_token"])
        except ValueError as exc:
            assert "运行中" in str(exc)
        else:
            raise AssertionError("late /prompt response rebound a cancelled claim")


def test_reference_upload_rejects_oversized_body_before_reading():
    class NeverRead:
        async def read(self, size=-1):
            raise AssertionError("oversized request was read")

    class Request:
        query = {"kind": "cast", "name": "Mina", "project": "afe_project"}
        content_length = MAX_REF_UPLOAD_BYTES + 1
        content = NeverRead()

    api = Api("test-output", "http://127.0.0.1:8188")
    response = asyncio.run(api.upload_ref(Request()))
    assert response.status == 413


def test_completed_session_republishes_missing_analysis_file():
    import tempfile
    from ai_film_editor_nodes.nodes.director.script_analysis_session import AnalysisSessionStore
    with tempfile.TemporaryDirectory() as root:
        api = Api(root, "http://127.0.0.1:8188")
        project = api.project_path("republish")
        scene_map = [{"scene_id": "scene_1", "source_blocks": [{
            "source_block_id": "block_1", "scene_occurrence_id": "occ_1",
            "section_type": "location_scene", "source_text": "A room with light."
        }]}]
        store = AnalysisSessionStore(os.path.join(project, "analysis_session"), 4)
        state = store.create("script", 1, 5, scene_map, cast=[])
        shot = {"shot_id": "shot_001", "scene_id": "scene_1", "scene_occurrence_id": "occ_1",
                "source_block_id": "block_1", "source_unit_ids": ["unit_001"],
                "section_type": "location_scene"}
        state["batches"][0]["status"] = "completed"
        state["completed_batches"] = [1]
        state["parsed_shots"] = [shot]
        state["analysis_status"] = "complete"
        store.save(state)
        assert not os.path.exists(os.path.join(project, "analysis.json"))
        status = api.analysis_status(project)
        published = json.load(open(os.path.join(project, "analysis.json"), encoding="utf-8"))
        assert status["analysis_status"] == "complete"
        assert published["session_signature"] == state["script_signature"]
        assert published["expected_shot_count"] == 1


def test_recover_analysis_releases_only_missing_persisted_prompt():
    import tempfile
    from ai_film_editor_nodes.nodes.director.script_analysis_session import AnalysisSessionStore
    with tempfile.TemporaryDirectory() as root:
        api = Api(root, "http://127.0.0.1:8188")
        project = api.project_path("recover")
        scene_map = [{"scene_id": "scene_1", "source_blocks": [
            {"source_block_id": "block_1", "scene_occurrence_id": "occ_1",
             "section_type": "location_scene", "source_text": "A room with light."},
            {"source_block_id": "block_2", "scene_occurrence_id": "occ_2",
             "section_type": "location_scene", "source_text": "A garden with shade."},
        ]}]
        store = AnalysisSessionStore(os.path.join(project, "analysis_session"), 1)
        store.create("script", 2, 5, scene_map, cast=[])
        first = store.claim_next("first-prompt")
        store.commit_batch(first["batch_index"], {
            "shots": [{"shot_id": "shot_001", "scene_id": "scene_1",
                       "scene_occurrence_id": "occ_1", "source_block_id": "block_1",
                       "source_unit_ids": ["unit_001"], "section_type": "location_scene"}],
            "cast": [], "source_manifest": first["source_unit_ranges"],
        })
        store.claim_next("lost-prompt")
        async def missing(_prompt):
            return False
        api.prompt_is_known = missing

        class Request:
            async def json(self):
                return {"project": "recover", "prompt_id": "lost-prompt"}

        response = asyncio.run(api.recover_analysis(Request()))
        assert response.status == 200
        state = store.status()
        assert state["batches"][1]["status"] == "failed"
        assert "重启" in state["batches"][1]["error"]
        assert state["completed_batches"] == [1]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
