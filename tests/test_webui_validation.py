import os
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))

from ai_film_editor_nodes.webui.server import _validate_analysis_payload


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
