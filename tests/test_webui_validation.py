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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
