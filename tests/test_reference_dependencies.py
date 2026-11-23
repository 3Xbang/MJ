"""CPU reference identity and scoped dependency regressions."""
import json
import os
import sys
import tempfile
from unittest.mock import patch

import torch
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
from ai_film_editor_nodes.nodes.video.shot_prompt_contract import dependencies_for_shot
from ai_film_editor_nodes.nodes.video.shot_keyframe_node import pick_scene_image
from ai_film_editor_nodes.nodes.video import shot_keyframe_node, wan_shot_renderer_node
from ai_film_editor_nodes.nodes.analyzer import scene_image_generator_node, props_image_generator_node
from ai_film_editor_nodes.nodes.video import cast_ref_generator_node
from ai_film_editor_nodes.nodes.video._common import save_png


def test_dependency_scope_is_entity_specific():
    a = dependencies_for_shot({"shot_id": "shot_1", "scene_id": "scene_a", "character_names": ["Mina"], "props_list": ["key"]})
    b = dependencies_for_shot({"shot_id": "shot_2", "scene_id": "scene_b", "character_names": ["Bo"], "props_list": []})
    assert a["scene"] == ["scene_a"] and b["scene"] == ["scene_b"]
    assert a["characters"] == ["Mina"] and b["characters"] == ["Bo"]
    assert a["props"] == ["key"] and b["props"] == []
    assert set(a["characters"]).isdisjoint(b["characters"])


def test_reference_slot_identity_does_not_use_a_different_scene_or_person():
    # The keyframe node's stable contract is intentionally represented as IDs, not positions.
    shot = {"shot_id": "shot_3", "scene_id": "scene_custom", "character_names": ["OnlyPerson"], "props_list": ["OnlyProp"]}
    deps = dependencies_for_shot(shot)
    assert deps == {"scene": ["scene_custom"], "characters": ["OnlyPerson"],
                    "props": ["OnlyProp"], "shot": ["shot_3"]}


import tempfile

from ai_film_editor_nodes.nodes.video.movie_assembler_node import AFE_MovieAssembler


def test_assembler_does_not_hide_unskipped_missing_clip():
    with tempfile.TemporaryDirectory() as project:
        try:
            AFE_MovieAssembler().assemble(
                [{"shot_id": "shot_001"}, {"shot_id": "shot_002"}],
                project, skip_shots="shot_001", approved=True,
            )
        except RuntimeError as exc:
            assert "shot_002" in str(exc)
            assert "unskipped" in str(exc)
        else:
            raise AssertionError("missing unskipped clip was silently accepted")


def test_keyframe_rejects_missing_scene_identity_instead_of_using_scene_one():
    views = [torch.zeros(1, 8, 8, 3), None, None]
    try:
        pick_scene_image(views, {"shot_id": "shot_007", "scene_id": "scene_missing"},
                         ["displayed_scene"], {})
    except ValueError as exc:
        assert "No matching scene reference" in str(exc)
    else:
        raise AssertionError("missing scene identity silently selected another scene")


def test_keyframe_all_generation_failures_are_reported_and_blocked():
    shot = {"shot_id": "shot_001", "scene_id": "scene_001", "scene_name": "Scene",
            "character_names": [], "props_list": [], "duration_seconds": 5}
    with tempfile.TemporaryDirectory() as project:
        scene = torch.zeros(1, 8, 8, 3)
        with patch.object(shot_keyframe_node, "project_dir", return_value=project), \
             patch.object(shot_keyframe_node, "_load_models", return_value=(object(), object(), object())), \
             patch.object(shot_keyframe_node, "get_node", return_value=object()), \
             patch.object(shot_keyframe_node, "call", return_value=[object()]), \
             patch.object(shot_keyframe_node, "_generate_frame", side_effect=RuntimeError("mock qwen failure")):
            try:
                shot_keyframe_node.AFE_ShotKeyframeGenerator().generate(
                    [shot], [], scene, torch.zeros(0, 8, 8, 3), "project", "style",
                    approved=True, auto_all=False)
            except RuntimeError as exc:
                assert "shot_001" in str(exc)
                assert "blocked" in str(exc)
            else:
                raise AssertionError("all failed keyframes were reported as successful")


def test_uploaded_scene_reference_is_processed_as_an_empty_scene_for_every_view():
    source = torch.zeros(1, 8, 8, 3)
    edit_prompts = []
    with tempfile.TemporaryDirectory() as project:
        with patch.object(scene_image_generator_node, "project_dir", return_value=project), \
             patch.object(scene_image_generator_node, "gate_is_open", return_value=True), \
             patch.object(scene_image_generator_node.user_refs, "load_user_ref", return_value=source), \
             patch.object(scene_image_generator_node.user_refs, "qwen_variant",
                          side_effect=lambda image, prompt, seed: edit_prompts.append(prompt) or image):
            result = scene_image_generator_node.AFE_SceneImageGenerator().generate(
                "", scenes_json=json.dumps([{"scene_id": "scene_001", "name": "Room"}]),
                width=8, height=8, steps=8, approved=True, project_name="project")
    assert len(edit_prompts) == 3
    assert all("Remove every person" in prompt and "EMPTY set" in prompt for prompt in edit_prompts)
    manifest = json.loads(result["ui"]["afe_manifest"][0])
    assert len(manifest) == 3 and all(item["source"] == "uploaded" for item in manifest)


def test_wan_failure_invalidates_existing_clip_and_blocks_completion():
    with tempfile.TemporaryDirectory() as project:
        os.makedirs(os.path.join(project, "keyframes"), exist_ok=True)
        os.makedirs(os.path.join(project, "clips"), exist_ok=True)
        os.makedirs(os.path.join(project, "clips_av"), exist_ok=True)
        save_png(torch.zeros(1, 8, 8, 3), os.path.join(project, "keyframes", "shot_001.png"))
        for path in (os.path.join(project, "clips", "shot_001.mp4"),
                     os.path.join(project, "clips", "shot_001.json"),
                     os.path.join(project, "clips_av", "shot_001.mp4")):
            open(path, "wb").write(b"stale")
        shot = {"shot_id": "shot_001", "scene_id": "scene_001", "character_names": [],
                "props_list": [], "action": "waits", "duration_seconds": 1}
        with patch.object(wan_shot_renderer_node, "_load_wan", return_value=object()), \
             patch.object(wan_shot_renderer_node, "render_shot", side_effect=RuntimeError("mock wan failure")):
            try:
                wan_shot_renderer_node.AFE_WanShotRenderer().render(
                    [shot], project, "style", max_shots=1, approved=True, auto_all=False)
            except RuntimeError as exc:
                assert "blocked" in str(exc) and "shot_001" in str(exc)
            else:
                raise AssertionError("Wan failure was reported as a completed render")
        assert not os.path.exists(os.path.join(project, "clips", "shot_001.mp4"))
        assert not os.path.exists(os.path.join(project, "clips", "shot_001.json"))
        assert not os.path.exists(os.path.join(project, "clips_av", "shot_001.mp4"))


def test_empty_cast_and_props_are_valid_no_reference_paths():
    cast_result = cast_ref_generator_node.AFE_CastRefGenerator().generate(
        [], "style", approved=True, project_name="empty_cast")
    assert cast_result["result"][0].shape[0] == 0
    props_result = props_image_generator_node.AFE_PropsImageGenerator().generate(
        "", props_json="[]", approved=True, project_name="empty_props")
    assert props_result["result"][0].shape[0] == 0
    assert json.loads(props_result["result"][2]) == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
