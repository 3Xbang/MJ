"""CPU prompt-fidelity regression tests. Run with: python tests/test_prompt_fidelity.py"""
import os
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
from ai_film_editor_nodes.nodes.video.shot_prompt_contract import build_keyframe_prompt, build_video_prompt, normalize_shot


def _shot():
    return normalize_shot({
        "shot_id": "shot_009", "scene_id": "scene_custom", "scene_occurrence_id": "occ_003",
        "source_block_id": "block_007", "section_type": "location_scene",
        "environment": {"description": "empty observatory with steel railing", "time_of_day": "night",
                        "weather": "clear", "color_temperature": "4200K"},
        "character_names": ["Rin"], "action_start": "Rin reaches for the brass lever",
        "action_process": "her thumb rubs the lever while her shoulders tense",
        "action_end": "she pulls it down and looks toward the window",
        "facial_expression": "fear held behind a tight smile", "micro_expression": "left eyelid trembles",
        "gaze": "toward the window", "body_language": "shoulders tense", "props_list": ["brass lever"],
        "prop_interactions": ["grips and pulls the brass lever"], "dialogue": "Wait for me.",
        "lighting": "single cool overhead lamp", "camera_angle": "low_angle", "shot_type": "medium",
        "camera_motion": "tracking_shot", "camera_path": "from lever to face", "pace": "slow then sharp",
    })


def test_every_required_fact_is_in_both_prompts():
    shot = _shot()
    key = build_keyframe_prompt(shot, "cinematic")
    video = build_video_prompt(shot, "cinematic", True)
    for fact in ("observatory", "night", "clear", "4200K", "Rin", "fear held behind a tight smile",
                 "left eyelid trembles", "brass lever", "grips and pulls", "low_angle", "medium",
                 "tracking", "slow then sharp", "reaches for", "pulls it down"):
        assert fact in key, fact + " missing from keyframe"
        assert fact in video, fact + " missing from video"
    assert "Wait for me." in key and "Wait for me." in video
    assert "do not render subtitles" in key.lower()


def test_missing_time_weather_stay_empty_and_static_requires_explicit_hold():
    shot = normalize_shot({"shot_id": "s", "camera_motion": "static", "camera_motion_source": "derived",
                           "dialogue": "", "character_names": []})
    assert shot["time_of_day"] == ""
    assert shot["weather"] == ""
    assert shot["camera_motion"] != "static"
    held = normalize_shot({"shot_id": "held", "camera_motion": "static", "locked_camera": True})
    assert held["camera_motion"] == "static"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
