"""Decide which shots continue the previous camera, using only the screenplay text.

The same setup continues from the previous shot's last moment. A new place, a new
framing, or a conflicting camera angle opens on this shot's own first frame.
"""
from __future__ import annotations

import re

_FIELD_SPLIT = re.compile(r"\s+-\s+|\n+")
_FIELD = re.compile(r"^(地点|入画|镜头)\s*[:：]\s*(.+)$")
_SAME_PLACE = re.compile(r"^(?:同上一镜|接上一镜|同上)(?!\s*\d)")
_SAME_SHOT = re.compile(r"^同镜头\s*0*(\d+)")
_STILL_OPENING = re.compile(r"^(?:仍|依旧|还是|同样|继续)")
_SHOT_NUMBER = re.compile(r"(\d+)")
_ANGLE_GROUPS = (
    ("side", ("侧面", "侧拍")),
    ("front", ("正面", "平视")),
    ("high", ("俯拍", "俯视", "略高", "高机位", "微俯")),
    ("low", ("略低", "低机位", "仰拍", "仰视")),
    ("behind", ("从身后", "背后", "背影")),
)


def screenplay_text(shot: dict) -> str:
    for key in ("source_shot_text", "source_text", "raw_description", "shot_description"):
        value = shot.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def screenplay_field(text: str, name: str) -> str:
    for part in _FIELD_SPLIT.split(text or ""):
        match = _FIELD.match(part.strip())
        if match and match.group(1) == name:
            return match.group(2).strip().rstrip("。.")
    return ""


def _core(line: str) -> str:
    compact = re.sub(r"\s+", "", (line or "").strip()).strip("。.")
    return re.split(r"[，,；;]", compact, maxsplit=1)[0]


def _shot_number(shot: dict, index: int) -> int:
    for key in ("shot_id", "id"):
        match = _SHOT_NUMBER.search(str(shot.get(key) or ""))
        if match:
            return int(match.group(1))
    heading = _SHOT_NUMBER.search(screenplay_text(shot))
    return int(heading.group(1)) if heading else index + 1


def _angles(line: str) -> set[str]:
    compact = re.sub(r"\s+", "", line or "")
    found = set()
    for name, words in _ANGLE_GROUPS:
        if any(word in compact for word in words):
            found.add(name)
    return found


def _empty_frame(line: str) -> bool:
    compact = re.sub(r"\s+", "", line or "")
    return "无人物" in compact or compact.startswith("无人")


def _place(line: str, prev_number: int, prev_place: str) -> str:
    compact = re.sub(r"\s+", "", line or "")
    if _SAME_PLACE.match(compact) and prev_place:
        return prev_place
    named = _SAME_SHOT.match(compact)
    if named and int(named.group(1)) == prev_number and prev_place:
        return prev_place
    return _core(line)


def _same_opening(prev_line: str, line: str) -> bool:
    if _empty_frame(prev_line) != _empty_frame(line):
        return False
    if _STILL_OPENING.match(_core(line)):
        return True
    prev_core = _core(prev_line)
    cur_core = _core(line)
    return bool(prev_core) and prev_core == cur_core


def _same_camera(prev: dict, shot: dict) -> bool:
    prev_text = screenplay_text(prev)
    text = screenplay_text(shot)
    prev_frame = screenplay_field(prev_text, "镜头")
    frame = screenplay_field(text, "镜头")
    if not prev_frame or not frame or _core(prev_frame) != _core(frame):
        return False
    prev_angles = _angles(prev_frame)
    angles = _angles(frame)
    if prev_angles and angles and prev_angles != angles:
        return False
    if shot.get("continuity_place") != prev.get("continuity_place"):
        return False
    if not shot.get("continuity_place"):
        return False
    return _same_opening(screenplay_field(prev_text, "入画"), screenplay_field(text, "入画"))


def link_shots(shots: list[dict]) -> list[dict]:
    """Return copies tagged ``continue`` or ``new_camera``.

    ``continue`` means this shot keeps the previous shot's camera, so the video
    starts from that shot's last frame. The first shot and every camera change
    open on their own first frame.
    """
    linked = []
    prev = None
    prev_place = ""
    prev_number = 0
    for index, shot in enumerate(shots or []):
        item = dict(shot)
        text = screenplay_text(item)
        number = _shot_number(item, index)
        place = _place(screenplay_field(text, "地点"), prev_number, prev_place)
        item["continuity_place"] = place
        item["continuity_end"] = screenplay_field(text, "动作结束")
        if prev is not None and _same_camera(prev, item):
            source = str(prev.get("shot_id") or f"shot_{index:03d}")
            item["continues_previous"] = True
            item["continuity"] = "continue"
            item["continuity_from"] = source
            item["continuity_note"] = f"接上 {source} 的最后一秒"
        else:
            item["continues_previous"] = False
            item["continuity"] = "new_camera"
            item["continuity_from"] = ""
            item["continuity_note"] = "新机位，从这一镜首帧开口"
        linked.append(item)
        prev = item
        prev_place = place
        prev_number = number
    return linked
