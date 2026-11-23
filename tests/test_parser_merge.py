"""CPU parser merge and camera provenance regressions."""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
spec = importlib.util.spec_from_file_location(
    "parser_mod", os.path.join(ROOT, "nodes", "director", "script_full_parser_node.py"))
parser_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser_mod)

from ai_film_editor_nodes.nodes.video.shot_prompt_contract import build_keyframe_prompt, build_video_prompt


class StubParser(parser_mod.AFE_ScriptFullParser):
    def __init__(self, phase1_shot, phase2):
        self.phase1_shot = phase1_shot
        self.phase2 = phase2

    def _call_llm(self, system_prompt, user_prompt, model_path, max_new_tokens=2048):
        if system_prompt == parser_mod.PHASE1_SYSTEM:
            return json.dumps({"cast": [{"name": "Mina", "appearance_en": "short hair"}],
                               "shots": [self.phase1_shot]})
        if system_prompt == parser_mod.SCENE_ENV_SYSTEM:
            return json.dumps({"scene_name_en": "Quiet Workshop",
                               "environment_prompt_en": "empty workshop, steel bench, cool overhead light"})
        if system_prompt == parser_mod.PHASE2_SYSTEM:
            return json.dumps(self.phase2)
        return "Mina reaches the lever in the workshop."


def _phase1(camera_motion=None, camera_source=None):
    return {
        "shot_id": "shot_001", "scene_index": 1, "source_block_id": "block_001",
        "scene_occurrence_id": "occurrence_001", "section_type": "location_scene",
        "character_names": ["Mina"], "dialogue": "Wait for me.", "props_list": ["brass lever"],
        "raw_description": "Mina reaches for the brass lever, her anxious smile tight and her eyelid trembling.",
        "facial_expression": "anxious smile", "micro_expression": "left eyelid trembles",
        "gaze": "toward the window", "body_language": "shoulders tense",
        "action_start": "hand approaches the lever", "action_process": "thumb rubs the label",
        "action": "reaches for the lever", "business": "thumb rubs the brass label",
        "action_end": "she pulls the lever", "prop_interactions": ["grips the brass lever"],
        "camera_motion": camera_motion, "camera_motion_source": camera_source,
        "shot_type": "medium", "camera_angle": "low_angle", "lighting": "cool LEDs",
    }


def _null_phase2(camera_motion=None):
    return {key: (camera_motion if key == "camera_motion" else
                  "script" if key == "camera_motion_source" and camera_motion else None)
            for key in (
                "camera_angle", "camera_motion", "camera_motion_source", "camera_path", "shot_type",
                "lighting_style", "location", "time_of_day", "weather", "lighting", "color_temperature",
                "action", "business", "emotion", "facial_expression", "micro_expression", "gaze",
                "body_language", "action_start", "action_process", "action_end", "prop_interactions",
                "pace", "shot_description", "costume_description", "costume_en", "director_notes")}


def _parse(phase1, phase2):
    return StubParser(phase1, phase2).parse_script(
        "【场景一：Workshop】\nMina reaches for the brass lever and waits.",
        target_duration_seconds=5, seconds_per_shot=5, model_path="stub") ["result"][0][0]


def test_phase2_nulls_preserve_phase1_facts_in_both_prompts():
    shot = _parse(_phase1("tracking_shot", "script"), _null_phase2())
    assert shot["action"] == "reaches for the lever"
    assert shot["business"] == "thumb rubs the brass label"
    # The parser's phase-1 fields remain available to the canonical renderer.
    assert shot["facial_expression"] == "anxious smile"
    assert shot["micro_expression"] == "left eyelid trembles"
    assert shot["action_start"] == "hand approaches the lever"
    assert shot["action_process"] == "thumb rubs the label"
    assert shot["action_end"] == "she pulls the lever"
    assert shot["prop_interactions"] == ["grips the brass lever"]
    assert shot["camera_motion"] == "tracking_shot"
    key = build_keyframe_prompt(shot)
    video = build_video_prompt(shot, speaking=True)
    for value in ("anxious smile", "left eyelid trembles", "thumb rubs", "pulls the lever", "tracking"):
        assert value in key and value in video, value


def test_phase2_static_for_ordinary_dialogue_is_derived_motion():
    shot = _parse(_phase1(), _null_phase2("static"))
    assert shot["camera_motion"] != "static"
    assert shot["camera_motion_source"] == "derived"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
