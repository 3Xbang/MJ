"""CPU prompt-fidelity regression tests. Run with: python tests/test_prompt_fidelity.py"""
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
from ai_film_editor_nodes.nodes.analyzer.scene_analyzer_node import validate_empty_scene_prompt
from ai_film_editor_nodes.nodes.video.shot_prompt_contract import build_keyframe_prompt, build_video_prompt, normalize_shot


def _shot():
    return normalize_shot({
        "shot_id": "shot_009", "scene_id": "scene_custom", "scene_occurrence_id": "occ_003",
        "source_block_id": "block_007", "section_type": "location_scene",
        "environment": {"description": "empty observatory with steel railing", "time_of_day": "night",
                        "weather": "clear", "color_temperature": "4200K"},
        "character_names": ["Rin"], "shot_description": "Rin's red wool coat catches the observatory light",
        "costume_en": "red wool coat with brass buttons", "action_start": "Rin reaches for the brass lever",
        "action_process": "her thumb rubs the lever while her shoulders tense",
        "action_end": "she pulls it down and looks toward the window",
        "facial_expression": "fear held behind a tight smile", "micro_expression": "left eyelid trembles",
        "gaze": "toward the window", "body_language": "shoulders tense", "props_list": ["brass lever"],
        "prop_interactions": ["grips and pulls the brass lever"], "dialogue": "Wait for me.",
        "lighting": "single cool overhead lamp", "camera_angle": "low_angle", "shot_type": "medium",
        "camera_motion": "tracking_shot", "camera_path": "from lever to face", "pace": "slow then sharp",
        "source_text": "The brass lever is beside the red wool coat; the overhead lamp flickers.",
    })


def test_every_required_fact_is_in_both_prompts():
    shot = _shot()
    key = build_keyframe_prompt(shot, "cinematic")
    video = build_video_prompt(shot, "cinematic", True)
    for fact in ("observatory", "night", "clear", "4200K", "Rin", "red wool coat catches",
                 "red wool coat with brass buttons", "fear held behind a tight smile",
                 "left eyelid trembles", "brass lever", "grips and pulls", "low_angle", "medium",
                 "tracking", "slow then sharp", "reaches for", "pulls it down", "flickers"):
        assert fact in key, fact + " missing from keyframe"
        assert fact in video, fact + " missing from video"
    assert "Wait for me." in key and "Wait for me." in video
    assert "do not render subtitles" in key.lower()


def test_contaminated_empty_scene_response_is_rejected():
    reason = validate_empty_scene_prompt("Mina reaches for the cup in the kitchen", ["Mina"])
    assert "character name" in reason or "human/action" in reason
    assert not validate_empty_scene_prompt("empty kitchen, steel counters, cool overhead light", ["Mina"])

    shot = normalize_shot({"shot_id": "s", "camera_motion": "static", "camera_motion_source": "derived",
                           "dialogue": "", "character_names": []})
    assert shot["time_of_day"] == ""
    assert shot["weather"] == ""
    assert shot["camera_motion"] != "static"
    held = normalize_shot({"shot_id": "held", "camera_motion": "static", "locked_camera": True})
    assert held["camera_motion"] == "static"


def test_camera_provenance_covers_explicit_static_script_motion_and_dialogue_rule():
    held = normalize_shot({"shot_id": "held", "camera_motion": "static",
                           "camera_motion_source": "script", "source_text": "Hold the camera locked off.",
                           "dialogue": "Wait."})
    assert held["camera_motion"] == "static"
    scripted = normalize_shot({"shot_id": "move", "camera_motion": "tracking_shot",
                               "camera_motion_source": "script", "source_text": "The camera tracks Mina.",
                               "dialogue": "Follow me."})
    assert scripted["camera_motion"] == "tracking_shot"
    ordinary_dialogue = normalize_shot({"shot_id": "dialogue", "camera_motion": "static",
                                        "camera_motion_source": "script", "source_text": "Mina holds the cup and speaks.",
                                        "dialogue": "Hello."})
    assert ordinary_dialogue["camera_motion"] != "static"
    assert ordinary_dialogue["camera_motion_source"] == "derived"


def test_nonempty_phase_two_summary_keeps_canonical_screenplay_text():
    shot = normalize_shot({
        "shot_description": "A person reaches toward a lever.",
        "raw_description": "The red coat catches a flickering lamp; she grips the brass lever.",
        "source_text": "The red coat catches a flickering lamp; she grips the brass lever.",
    })
    key = build_keyframe_prompt(shot)
    video = build_video_prompt(shot)
    for prompt in (key, video):
        assert "red coat catches a flickering lamp" in prompt
        assert "brass lever" in prompt
        assert "A person reaches toward a lever" in prompt


def test_camera_cues_are_scoped_to_the_shot_and_preserve_direction():
    import importlib.util
    path = os.path.join(ROOT, "nodes", "director", "script_full_parser_node.py")
    spec = importlib.util.spec_from_file_location("full_parser_for_camera", path)
    parser = importlib.util.module_from_spec(spec); spec.loader.exec_module(parser)
    sibling = parser._camera_motion_from_phases(
        {"camera_motion": "static", "camera_motion_source": "script"}, {},
        "The camera pans left, then Mina waits.", "Mina waits.")
    assert sibling[0] != "static"
    exact = parser._camera_motion_from_phases(
        {}, {"camera_motion": "static", "camera_motion_source": "model"},
        "The camera pans left.", "The camera pans left.")
    assert exact == ("pan_left", "script", True)
    person_still = parser._camera_motion_from_phases(
        {"camera_motion": "static", "camera_motion_source": "script"}, {},
        "Mina keeps still while holding a cup.", "Mina keeps still while holding a cup.")
    assert person_still[0] != "static"


def test_chinese_camera_direction_is_preserved_from_source_text():
    import importlib.util
    path = os.path.join(ROOT, "nodes", "director", "script_full_parser_node.py")
    spec = importlib.util.spec_from_file_location("full_parser_for_cn_camera", path)
    parser = importlib.util.module_from_spec(spec); spec.loader.exec_module(parser)
    assert parser._camera_motion_from_phases(
        {}, {}, "镜头向左移动，带过人物。", "人物抬头。"
    ) == ("pan_left", "script", True)
    assert parser._camera_motion_from_phases(
        {}, {}, "镜头向右横移，停在门口。", "人物看向门。"
    ) == ("pan_right", "script", True)
    assert parser._camera_motion_from_phases(
        {}, {}, "镜头跟拍人物向左移动。", "人物走向左侧。"
    ) == ("tracking_shot", "script", True)


def test_exact_source_fragment_excludes_sibling_screenplay_moments():
    import importlib.util
    path = os.path.join(ROOT, "nodes", "director", "script_full_parser_node.py")
    spec = importlib.util.spec_from_file_location("full_parser_for_source", path)
    parser = importlib.util.module_from_spec(spec); spec.loader.exec_module(parser)
    block = ("Scene: Workshop\nMina grips the red cup and narrows her eyes.\n\n"
             "Bo opens the brass drawer and shouts across the room.")
    fragment = parser._source_fragment_for_shot(
        block, "Mina grips the red cup and narrows her eyes.",
        {"source_shot_text": "Mina grips the red cup and narrows her eyes.",
         "character_names": ["Mina"], "props_list": ["red cup"]})
    assert fragment == "Mina grips the red cup and narrows her eyes."
    assert "Bo" not in fragment and "brass drawer" not in fragment


def test_shared_prompts_do_not_receive_sibling_character_or_prop_facts():
    shot = normalize_shot({
        "character_names": ["Mina"], "props_list": ["red cup"],
        "source_text": "Mina grips the red cup and narrows her eyes.",
        "source_block_text": "Mina grips the red cup. Bo opens the brass drawer.",
        "action_start": "Mina reaches for the red cup",
    })
    for prompt in (build_keyframe_prompt(shot), build_video_prompt(shot)):
        assert "Mina" in prompt and "red cup" in prompt
        assert "Bo" not in prompt and "brass drawer" not in prompt


def test_camera_uses_exact_source_when_phase_summary_omits_pan():
    import importlib.util
    path = os.path.join(ROOT, "nodes", "director", "script_full_parser_node.py")
    spec = importlib.util.spec_from_file_location("full_parser_for_source_camera", path)
    parser = importlib.util.module_from_spec(spec); spec.loader.exec_module(parser)
    result = parser._camera_motion_from_phases(
        {}, {}, "The camera pans left as Mina looks up.", "Mina looks up.")
    assert result == ("pan_left", "script", True)


def test_chinese_person_stillness_does_not_lock_camera():
    shot = normalize_shot({"camera_motion": "static", "camera_motion_source": "script",
                           "source_text": "人物静止不动地看向门。", "action": "看向门"})
    assert shot["camera_motion"] != "static"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
