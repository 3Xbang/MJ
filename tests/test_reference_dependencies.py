"""CPU reference identity and scoped dependency regressions."""
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
from ai_film_editor_nodes.nodes.video.shot_prompt_contract import dependencies_for_shot


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
