import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))

from ai_film_editor_nodes.webui.server import (
    _validate_analysis_payload, Api, MAX_REF_UPLOAD_BYTES,
)


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
