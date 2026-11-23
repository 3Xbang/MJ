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

_STATIC_CAMERA_CUES = re.compile(
    # "hold" is a camera cue only when it names the shot/frame/camera. A
    # screenplay action such as "hold the cup" must not lock the camera.
    r"\b(?:static|fixed|still)\s+(?:camera|shot|frame|view)\b|"
    r"\b(?:locked(?:[- ]off)?|fixed|still)\s+(?:camera|shot|frame|view)\b|"
    r"\b(?:camera|shot|frame|view)\s+(?:is\s+)?(?:static|fixed|still|locked(?:[- ]off)?)\b|"
    r"\bhold\s+(?:on\s+)?(?:the\s+)?(?:camera|shot|frame|view)\b|"
    r"(?:静止|固定机位|固定镜头|定机位|镜头停留|画面停留|"
    r"(?:镜头|机位|画面)(?:保持不动|静止|固定)|"
    r"(?:保持不动|静止|固定)(?:镜头|机位|画面))", re.IGNORECASE,
)


def _clean(value: Any):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        cleaned = []
        for item in value:
            item = _clean(item)
            if item not in ("", None):
                cleaned.append(item)
        return cleaned
    if isinstance(value, str) and value.strip().lower() in {"", "null", "none", "n/a", "nil"}:
        return ""
    return value.strip() if isinstance(value, str) else value


def _text(value: Any) -> str:
    value = _clean(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip() if value not in (None, "") else ""


def _first_text(*values) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _list(value: Any) -> list:
    value = _clean(value)
    if isinstance(value, (list, tuple)):
        return [item for item in value if item not in (None, "")]
    return [value] if value not in (None, "") and str(value).strip() else []


def camera_motion_for(shot: dict) -> tuple[str, str]:
    """Return a supported motion and its provenance.

    A static camera is a screenplay fact, not a safe default.  A caller may mark
    it as ``script`` only after validating that provenance, or provide an explicit
    locked/hold cue in the source text.  Otherwise a missing or model-invented
    static value is replaced by a deterministic non-static rule.
    """
    raw = _text(shot.get("camera_motion")).lower().replace(" ", "_")
    aliases = {"push_in": "slow_push_in", "pull_back": "slow_pull_back", "track": "tracking_shot",
               "pan": "pan_right", "locked": "static", "hold": "static", "locked_off": "static"}
    raw = aliases.get(raw, raw)
    source = _text(shot.get("camera_motion_source")).lower()
    source_text = " ".join(_text(shot.get(k)) for k in (
        "source_shot_text", "raw_description", "source_text", "screenplay_source_text",
        "shot_description", "director_notes"
    ))
    # Only a validated contract flag or camera/shot wording in the preserved
    # screenplay text can authorize a locked camera. Model provenance alone is
    # deliberately insufficient, because the model may label ordinary dialogue
    # or an object action as ``static``.
    explicit_static = bool(shot.get("locked_camera"))
    explicit_static = explicit_static or bool(_STATIC_CAMERA_CUES.search(source_text))
    if raw in CAMERA_MOTIONS and raw != "static":
        return raw, source or "script"
    if raw == "static" and explicit_static:
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
    for env_key, env_value in list(environment.items()):
        environment[env_key] = _text(env_value)
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
        "source_description": _first_text(src.get("source_description"), src.get("source_shot_text"),
                                          src.get("raw_description"), src.get("shot_description"), src.get("source_text")),
        "shot_description": _first_text(src.get("shot_description"), src.get("raw_description")),
        "raw_description": _first_text(src.get("raw_description"), src.get("source_shot_text"),
                                       src.get("shot_description"), src.get("source_text")),
        "costume_en": _text(src.get("costume_en")),
        "costume_description": _text(src.get("costume_description")),
        "time_of_day": _first_text(src.get("time_of_day"), environment.get("time_of_day", "")),
        "weather": _first_text(src.get("weather"), environment.get("weather", "")),
        "lighting": _first_text(src.get("lighting"), environment.get("lighting", "")),
        "color_temperature": _first_text(src.get("color_temperature"), environment.get("color_temperature", "")),
        "character_names": [str(x) for x in chars],
        "character_facts": src.get("character_facts") or {},
        "props_list": [str(x) for x in (_list(src.get("props_list")) or _list(src.get("props")))],
        "props": [str(x) for x in (_list(src.get("props")) or _list(src.get("props_list")))],
        "prop_interactions": [str(x) for x in (_list(src.get("prop_interactions")) or _list(src.get("props_interactions")))],
        "dialogue": _first_text(src.get("dialogue")) or "（无）",
        "facial_expression": _first_text(src.get("facial_expression"), src.get("emotion")),
        "micro_expression": _first_text(src.get("micro_expression"), src.get("micro_emotion")),
        "gaze": _text(src.get("gaze")),
        "body_language": _text(src.get("body_language")),
        "action_start": _first_text(src.get("action_start"), src.get("action")),
        "action_process": _first_text(src.get("action_process"), src.get("business")),
        "action_end": _text(src.get("action_end")),
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
        "source_description": _text(s.get("source_description") or s.get("shot_description") or s.get("raw_description")),
        "shot_enhancement": _text(s.get("shot_description")),
        "source_text": _text(s.get("source_text")),
        "costume": _text(s.get("costume_en") or s.get("costume_description")),
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
    labels = (("Environment", "environment"), ("Source visual description", "source_description"),
              ("Phase 2 visual enhancement", "shot_enhancement"), ("Canonical screenplay source", "source_text"),
              ("Costume", "costume"), ("Time of day", "time_of_day"),
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
