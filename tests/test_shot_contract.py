"""CPU regression tests for the canonical shot contract."""
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))

from ai_film_editor_nodes.nodes.video.shot_prompt_contract import (
    build_keyframe_prompt, build_video_prompt, normalize_shot, dependencies_for_shot,
)


def test_structured_facts_and_non_static_camera_are_preserved():
    shot = normalize_shot({
        "shot_id": "shot_001", "scene_id": "scene_warehouse", "character_names": ["Mina"],
        "scene_environment_en": "empty warehouse, steel shelves", "action": "raises the box",
        "business": "thumb rubs the torn label", "emotion": "anxious",
        "micro_expression": "lower eyelid twitches", "gaze": "toward the exit",
        "props_list": ["box"], "prop_interactions": ["grips the box with both hands"],
        "dialogue": "We should leave", "lighting": "cool overhead LEDs",
    })
    assert shot["camera_motion"] == "tracking_shot"
    assert shot["duration_seconds"] if "duration_seconds" in shot else True
    key = build_keyframe_prompt(shot, "cinematic")
    video = build_video_prompt(shot, "cinematic", True)
    for value in ("Mina", "box", "anxious", "lower eyelid twitches", "tracks", "cool overhead LEDs"):
        assert value in key and value in video, value
    assert "We should leave" in key and "do not render dialogue as text" in key.lower()
    assert all(x in video for x in ("Action start", "Action process", "Action end"))


def test_explicit_locked_hold_stays_static_and_dependencies_are_entity_scoped():
    shot = normalize_shot({"shot_id": "shot_7", "scene_id": "scene_a", "camera_motion": "static",
                           "locked_camera": True, "character_names": ["A"], "props_list": ["key"]})
    assert shot["camera_motion"] == "static"
    deps = dependencies_for_shot(shot)
    assert deps == {"scene": ["scene_a"], "characters": ["A"], "props": ["key"], "shot": ["shot_7"]}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
