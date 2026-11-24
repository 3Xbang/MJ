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
                               "environment_prompt_en": "empty workshop, steel bench, cool overhead light",
                               "subject_scope": "place_only", "people": [], "props": []})
        if system_prompt == parser_mod.PHASE2_SYSTEM:
            return json.dumps(self.phase2)
        return "Mina reaches the lever in the workshop."


def _phase1(camera_motion=None, camera_source=None):
    return {
        "shot_id": "shot_001", "scene_index": 1, "source_block_id": "block_001",
        "scene_occurrence_id": "occurrence_001", "section_type": "location_scene",
        "character_names": ["Mina"], "dialogue": "Wait for me.", "props_list": ["brass lever"],
        "costume_en": "red wool coat", "raw_description": "The camera tracks Mina as she reaches for the brass lever, her anxious smile tight and her eyelid trembling.",
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
                  "script" if key == "camera_motion_source" and camera_motion else
                  ["null"] if key == "prop_interactions" else
                  "null" if key in {"shot_description", "costume_en"} else None)
            for key in (
                "camera_angle", "camera_motion", "camera_motion_source", "camera_path", "shot_type",
                "lighting_style", "location", "time_of_day", "weather", "lighting", "color_temperature",
                "action", "business", "emotion", "facial_expression", "micro_expression", "gaze",
                "body_language", "action_start", "action_process", "action_end", "prop_interactions",
                "pace", "shot_description", "costume_description", "costume_en", "director_notes")}


def _parse(phase1, phase2, screenplay=None):
    return StubParser(phase1, phase2).parse_script(
        screenplay or ("【场景一：Workshop】\nMina in a red wool coat reaches for the brass lever, anxious smile tight, "
                       "left eyelid trembling, gaze toward the window, shoulders tense; "
                       "hand approaches the lever, grips the brass lever, thumb rubs the label, she pulls the lever; "
                       "the camera is framed under cool LEDs."
                       ),
        target_duration_seconds=5, seconds_per_shot=5, model_path="stub") ["result"][0][0]


def test_phase2_nulls_preserve_phase1_facts_in_both_prompts():
    shot = _parse(_phase1("tracking_shot", "script"), _null_phase2(),
                  "【场景一：Workshop】\nMina in a red wool coat reaches for the brass lever, anxious smile tight, left eyelid trembling, gaze toward the window, shoulders tense; hand approaches the lever, grips the brass lever, thumb rubs the label, she pulls the lever; under cool LEDs.")
    assert shot["action"] == "reaches for the lever"
    assert shot["business"] == "thumb rubs the brass label"
    # The parser's phase-1 fields remain available to the canonical renderer.
    assert shot["facial_expression"] == "anxious smile"
    assert shot["micro_expression"] == "left eyelid trembles"
    assert shot["action_start"] == "hand approaches the lever"
    assert shot["action_process"] == "thumb rubs the label"
    assert shot["action_end"] == "she pulls the lever"
    assert shot["prop_interactions"] == ["grips the brass lever"]
    assert shot["shot_description"] == shot["source_shot_text"]
    assert shot["costume_en"] == "red wool coat"
    assert shot["camera_motion"] == "tracking_shot"
    key = build_keyframe_prompt(shot)
    video = build_video_prompt(shot, speaking=True)
    for value in ("anxious smile", "left eyelid trembles", "thumb rubs", "pulls the lever", "tracking", "brass lever", "red wool coat"):
        assert value in key and value in video, value


def test_conflicting_phase2_facts_do_not_replace_phase1_source_facts():
    phase2 = _null_phase2()
    phase2.update({
        "action": "runs away from the workshop",
        "business": "throws the brass lever across the room",
        "emotion": "joyful grin",
        "facial_expression": "joyful grin",
        "micro_expression": "right eyebrow jumps",
        "location": "a city street",
        "lighting": "red neon light",
        "shot_description": "A woman runs away on a city street.",
    })
    shot = _parse(_phase1(), phase2,
                  "【场景一：Workshop】\nMina in a red wool coat reaches for the brass lever, anxious smile tight, left eyelid trembling, gaze toward the window, shoulders tense; hand approaches the lever, grips the brass lever, thumb rubs the label, she pulls the lever; under cool LEDs.")
    assert shot["action"] == "reaches for the lever"
    assert shot["business"] == "thumb rubs the brass label"
    assert shot["facial_expression"] == "anxious smile"
    assert shot["micro_expression"] == "left eyelid trembles"
    assert shot["location"] == "Workshop"
    assert shot["lighting"] == "cool LEDs"
    assert "city street" not in build_keyframe_prompt(shot)
    assert "city street" not in build_video_prompt(shot)

def test_phase2_failure_blocks_nominal_analysis():
    class Phase2FailureParser(StubParser):
        def _call_llm(self, system_prompt, user_prompt, model_path, max_new_tokens=2048):
            if system_prompt == parser_mod.PHASE2_SYSTEM:
                raise RuntimeError("phase2 service unavailable")
            return super()._call_llm(system_prompt, user_prompt, model_path, max_new_tokens)

    try:
        Phase2FailureParser(_phase1(), _null_phase2()).parse_script(
            "【场景一：Workshop】\nMina reaches for the brass lever.",
            target_duration_seconds=5, seconds_per_shot=5, model_path="stub")
    except ValueError as exc:
        assert "Phase 2" in str(exc) and "已阻止保存" in str(exc)
    else:
        raise AssertionError("Phase 2 failure returned a complete analysis")


def test_parser_preserves_explicit_locked_camera_cue():
    shot = _parse(_phase1("static", "script"), _null_phase2(),
                  "【场景一：Workshop】\nHold the camera locked off while Mina holds the brass lever.")
    assert shot["camera_motion"] == "static"


def test_phase2_static_for_ordinary_dialogue_is_derived_motion():
    shot = _parse(_phase1(), _null_phase2("static"))
    assert shot["camera_motion"] != "static"
    assert shot["camera_motion_source"] == "derived"


def test_missing_source_evidence_blocks_ambiguous_shot_without_sibling_fallback():
    block = "Scene: Workshop\nMina grips the red cup.\n\nBo opens the brass drawer.\n\nCia leaves the room."
    fragment, error = parser_mod._validated_source_fragment(
        block, "A person reaches toward an object.", {}
    )
    assert fragment == ""
    assert "missing verified" in error
    units = parser_mod._source_units_with_offsets(block)
    fragment, error = parser_mod._validated_source_fragment(
        block, "ignored", {"source_unit_ids": [units[0]["unit_id"]]}
    )
    assert not error and "Mina" in fragment and "Bo" not in fragment
    fragment, error = parser_mod._validated_source_fragment(
        block, "ignored", {"source_unit_ids": [units[0]["unit_id"], units[-1]["unit_id"]]}
    )
    assert fragment == "" and "not adjacent" in error


def test_phase1_coverage_rejects_truncated_or_repeated_source_blocks():
    scene_map = parser_mod._build_scene_map(
        "【场景 A：Kitchen】\nMina opens the drawer.\n"
        "【场景 B：Garden】\nBo looks up."
    )
    errors = parser_mod._phase1_source_coverage_errors([
        {"shot_id": "shot_001", "scene_index": 1, "source_block_id": "block_001",
         "source_unit_ids": ["unit_001"]},
        {"shot_id": "shot_002", "scene_index": 1, "source_block_id": "block_001",
         "source_unit_ids": ["unit_001"]},
    ], scene_map, target_count=2)
    assert any("重复覆盖" in error for error in errors), errors
    assert any("block_002" in error and "遗漏" in error for error in errors), errors


    ordered_map = parser_mod._build_scene_map(
        "【场景 A：Kitchen】\nMina opens the drawer.\n"
        "【场景 B：Garden】\nBo looks up.\n"
        "【场景 A：Kitchen】\nMina closes the drawer."
    )
    ordered_errors = parser_mod._phase1_source_coverage_errors([
        {"shot_id": "shot_001", "source_block_id": "block_001", "source_unit_ids": ["unit_001"]},
        {"shot_id": "shot_002", "source_block_id": "block_003", "source_unit_ids": ["unit_001"]},
        {"shot_id": "shot_003", "source_block_id": "block_002", "source_unit_ids": ["unit_001"]},
    ], ordered_map, target_count=3)
    assert any("顺序" in error for error in ordered_errors), ordered_errors


def test_environment_prompt_failure_blocks_analysis_instead_of_fallback():
    class EnvFailureParser(StubParser):
        def _call_llm(self, system_prompt, user_prompt, model_path, max_new_tokens=2048):
            if system_prompt == parser_mod.SCENE_ENV_SYSTEM:
                raise RuntimeError("environment model unavailable")
            return super()._call_llm(system_prompt, user_prompt, model_path, max_new_tokens)

    parser = EnvFailureParser(_phase1(), _null_phase2())
    try:
        parser.parse_script("【场景一：Workshop】\nMina reaches for the brass lever.",
                            target_duration_seconds=5, seconds_per_shot=5, model_path="stub")
    except ValueError as exc:
        message = str(exc)
        assert "空场景环境分析失败" in message and "降级" in message
    else:
        raise AssertionError("environment failure silently used a generic fallback")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
