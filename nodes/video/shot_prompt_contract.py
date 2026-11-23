"""Canonical, GPU-free shot facts and prompt rendering.

The parser may keep legacy flat fields, but every downstream prompt is built from
this contract.  Empty facts stay empty; this module never invents people or props.
"""
from __future__ import annotations

import re
from typing import Any

SCHEMA_VERSION = "afe-shot-v1"
CAMERA_MOTIONS = {
    "static": "static camera, locked off",
    "slow_push_in": "the camera slowly pushes in",
    "slow_pull_back": "the camera slowly pulls back",
    "pan_left": "the camera pans left",
    "pan_right": "the camera pans right",
    "tracking_shot": "the camera tracks the subject in a tracking shot",
    "crane_up": "the camera cranes upward",
    "crane_down": "the camera cranes downward",
    "handheld": "subtle handheld camera movement",
    "orbit": "the camera slowly orbits around the subject",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip()


def _list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [v for v in value if v not in (None, "")]
    return [value] if str(value).strip() else []


def camera_motion_for(shot: dict) -> tuple[str, str]:
    """Return a supported motion and whether it came from the screenplay/rule."""
    raw = _text(shot.get("camera_motion")).lower().replace(" ", "_")
    aliases = {"push_in": "slow_push_in", "pull_back": "slow_pull_back", "track": "tracking_shot",
               "pan": "pan_right", "locked": "static", "hold": "static", "locked_off": "static"}
    raw = aliases.get(raw, raw)
    if raw in CAMERA_MOTIONS and not (raw == "static" and _text(shot.get("camera_motion_source")).lower() in {"derived", "llm"}):
        return raw, _text(shot.get("camera_motion_source")) or "script"
    if shot.get("locked_camera") or re.search(r"\b(static|locked|hold|固定|静止)\b", _text(shot.get("director_notes") or shot.get("shot_description")), re.I):
        return "static", "script"
    text = " ".join(_text(shot.get(k)) for k in ("shot_type", "action", "business", "section_type", "director_notes")).lower()
    section = _text(shot.get("section_type")).lower()
    if section in {"epilogue", "ending", "transition"} or re.search(r"ending|resolution|fade|淡出|结尾", text):
        return "slow_pull_back", "derived"
    if section in {"title_sequence", "prologue", "opening"} or re.search(r"establish|opening|title|片头|序幕|开场", text):
        return "slow_push_in", "derived"
    if re.search(r"walk|run|move|turn|pick|put|grab|raise|grip|carry|place|open|close|走|跑|转身|拿起|放下|移动", text):
        return "tracking_shot", "derived"
    if _text(shot.get("dialogue")) or _text(shot.get("emotion")) or _text(shot.get("facial_expression")):
        return "slow_push_in", "derived"
    return "pan_right", "derived"


def normalize_shot(shot: dict, index: int = 0) -> dict:
    """Normalize legacy or new parser output into the versioned shot contract."""
    src = dict(shot or {})
    chars = _list(src.get("character_names") or src.get("characters"))
    props = _list(src.get("props_list") or src.get("props"))
    interactions = _list(src.get("prop_interactions") or src.get("props_interactions"))
    motion, motion_source = camera_motion_for(src)
    environment = src.get("environment") if isinstance(src.get("environment"), dict) else {}
    environment = dict(environment)
    for key, old in (("description", "scene_environment_en"), ("location", "location"),
                     ("time_of_day", "time_of_day"), ("weather", "weather"),
                     ("lighting", "lighting"), ("color_temperature", "color_temperature")):
        if not environment.get(key) and src.get(old):
            environment[key] = src[old]
    out = dict(src)
    out.update({
        "schema_version": src.get("schema_version") or SCHEMA_VERSION,
        "shot_id": src.get("shot_id") or f"shot_{index + 1:03d}",
        "section_type": src.get("section_type") or "location_scene",
        "scene_id": src.get("scene_id") or src.get("scene_name") or "scene_unknown",
        "scene_occurrence_id": src.get("scene_occurrence_id") or f"occurrence_{index + 1:03d}",
        "source_block_id": src.get("source_block_id") or f"block_{index + 1:03d}",
        "environment": environment,
        "time_of_day": src.get("time_of_day") or environment.get("time_of_day", ""),
        "weather": src.get("weather") or environment.get("weather", ""),
        "lighting": src.get("lighting") or environment.get("lighting", ""),
        "color_temperature": src.get("color_temperature") or environment.get("color_temperature", ""),
        "character_names": [str(x) for x in chars],
        "character_facts": src.get("character_facts") or {},
        "props_list": [str(x) for x in props],
        "props": [str(x) for x in props],
        "prop_interactions": [str(x) for x in interactions],
        "dialogue": src.get("dialogue") or "（无）",
        "facial_expression": src.get("facial_expression") or src.get("emotion", ""),
        "micro_expression": src.get("micro_expression") or src.get("micro_emotion", ""),
        "gaze": src.get("gaze", ""),
        "body_language": src.get("body_language", ""),
        "action_start": src.get("action_start") or src.get("action", ""),
        "action_process": src.get("action_process") or src.get("business", ""),
        "action_end": src.get("action_end", ""),
        "camera_angle": src.get("camera_angle", ""),
        "camera_motion": motion,
        "camera_motion_source": motion_source,
        "camera_path": src.get("camera_path", ""),
        "pace": src.get("pace") or src.get("rhythm") or "",
        "business": src.get("business", ""),
        "emotion": src.get("emotion") or src.get("facial_expression", ""),
    })
    return out


def required_facts(shot: dict) -> dict[str, str]:
    s = normalize_shot(shot)
    return {
        "environment": _text(s["environment"].get("description") or s.get("scene_environment_en") or s.get("location")),
        "time_of_day": _text(s.get("time_of_day") or s["environment"].get("time_of_day")),
        "weather": _text(s.get("weather") or s["environment"].get("weather")),
        "characters": _text(s.get("character_names")),
        "action_start": _text(s.get("action_start")),
        "action_process": _text(s.get("action_process")),
        "action_end": _text(s.get("action_end")),
        "expression": _text(s.get("facial_expression")),
        "micro_expression": _text(s.get("micro_expression")),
        "gaze": _text(s.get("gaze")),
        "body_language": _text(s.get("body_language")),
        "props": _text(s.get("props_list")),
        "prop_interactions": _text(s.get("prop_interactions")),
        "dialogue": _text(s.get("dialogue")),
        "lighting": _text(s.get("lighting") or s.get("lighting_style")),
        "color_temperature": _text(s.get("color_temperature") or s["environment"].get("color_temperature")),
        "shot_type": _text(s.get("shot_type")),
        "camera_angle": _text(s.get("camera_angle")),
        "camera": CAMERA_MOTIONS[s["camera_motion"]],
        "camera_path": _text(s.get("camera_path")),
        "pace": _text(s.get("pace")),
    }


def render_shared_facts(shot: dict, include_dialogue: bool = True) -> str:
    f = required_facts(shot)
    parts = []
    labels = (("Environment", "environment"), ("Time of day", "time_of_day"),
              ("Weather", "weather"), ("Characters", "characters"),
              ("Action start", "action_start"), ("Action process / business", "action_process"),
              ("Action end", "action_end"), ("Facial expression", "expression"),
              ("Micro-expression", "micro_expression"), ("Gaze", "gaze"),
              ("Body language", "body_language"), ("Props", "props"),
              ("Prop interaction", "prop_interactions"), ("Lighting", "lighting"),
              ("Color temperature", "color_temperature"), ("Shot type", "shot_type"),
              ("Camera angle", "camera_angle"), ("Camera motion", "camera"),
              ("Camera path", "camera_path"), ("Pace", "pace"))
    s = normalize_shot(shot)
    for label, key in labels:
        value = f.get(key, "") if key in f else _text(s.get(key))
        if key in {"action_start", "action_process", "action_end"} and not value:
            value = "not specified in screenplay"
        if value:
            parts.append(f"{label}: {value}")
    if include_dialogue and f["dialogue"] and f["dialogue"] not in {"（无）", "(无)", "none", "null"}:
        parts.append(f"Spoken dialogue context (do not render subtitles): {f['dialogue']}")
    return ". ".join(parts)


def build_keyframe_prompt(shot: dict, render_style: str = "") -> str:
    return ("Create one cinematic first frame from the exact screenplay facts below. "
            + render_shared_facts(shot) + ". Keep named characters and props only; no other people. "
            "Do not render dialogue as text or subtitles. " + _text(render_style)).strip()


def build_video_prompt(shot: dict, render_style: str = "", speaking: bool = False) -> str:
    text = ("Animate the exact screenplay facts below from start to finish. " + render_shared_facts(shot)
            + (". The character speaks with natural lip, head and facial movement" if speaking else "")
            + ". " + _text(render_style) + ". Smooth natural motion.")
    return text.strip()


def dependencies_for_shot(shot: dict) -> dict[str, list[str]]:
    s = normalize_shot(shot)
    return {"scene": [str(s.get("scene_id"))], "characters": list(s.get("character_names", [])),
            "props": list(s.get("props_list", [])), "shot": [str(s.get("shot_id"))]}
