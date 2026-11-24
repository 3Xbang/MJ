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
        message = str(exc)
        assert "scene_id" in message and "source_block_id" in message
    else:
        raise AssertionError("web UI accepted an analysis without source identity")


def test_webui_accepts_complete_structured_analysis():
    _validate_analysis_payload({"shots": [{
        "shot_id": "shot_001", "scene_id": "scene_001",
        "scene_occurrence_id": "occurrence_001", "source_block_id": "block_001",
        "section_type": "location_scene",
    }]})


def test_webui_rejects_complete_identity_but_truncated_source_manifest():
    try:
        _validate_analysis_payload({
            "analysis_status": "complete", "expected_shot_count": 2,
            "source_manifest": [
                {"order": 0, "source_block_id": "block_001"},
                {"order": 1, "source_block_id": "block_002"},
            ],
            "shots": [{"shot_id": "shot_001", "scene_id": "scene_001",
                       "scene_occurrence_id": "occurrence_001", "source_block_id": "block_001",
                       "section_type": "location_scene"}],
        })
    except ValueError as exc:
        assert "数量不完整" in str(exc)
    else:
        raise AssertionError("web UI accepted a truncated analysis manifest")


def test_webui_rejects_source_order_error():
    try:
        _validate_analysis_payload({
            "expected_shot_count": 2,
            "source_manifest": [
                {"order": 0, "source_block_id": "block_001"},
                {"order": 1, "source_block_id": "block_002"},
            ],
            "shots": [
                {"shot_id": "shot_001", "scene_id": "scene_001", "scene_occurrence_id": "o1",
                 "source_block_id": "block_002", "section_type": "location_scene"},
                {"shot_id": "shot_002", "scene_id": "scene_001", "scene_occurrence_id": "o2",
                 "source_block_id": "block_001", "section_type": "location_scene"},
            ],
        })
    except ValueError as exc:
        assert "顺序" in str(exc)
    else:
        raise AssertionError("web UI accepted reordered source blocks")


def test_webui_ref_signature_changes_when_content_changes_without_mtime_change():
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
