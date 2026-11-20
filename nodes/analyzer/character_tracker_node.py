from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_CharacterTracker")


def _get_shots(shot_sequence) -> list:
    if isinstance(shot_sequence, list):
        return shot_sequence
    if isinstance(shot_sequence, dict):
        return shot_sequence.get("shots", [])
    if hasattr(shot_sequence, "shots"):
        return list(shot_sequence.shots)
    return []


class AFE_CharacterTracker:
    """
    Character Tracker (角色追踪器).
    Walks shot_sequence to collect every character's shot appearances,
    merges with cast_data for appearance/costume details, and
    outputs a per-character tracking report.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
            },
            "optional": {
                "cast_data": ("CAST_DATA",),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("tracking_json", "tracking_report", "character_count")
    FUNCTION = "track_characters"
    CATEGORY = "AI Film Editor/Script"
    OUTPUT_NODE = True

    def track_characters(self, shot_sequence, cast_data=None):
        shots = _get_shots(shot_sequence)

        # Build cast lookup from cast_data
        cast_lookup: dict[str, dict] = {}
        if cast_data:
            for char in cast_data:
                name = char.get("name", "").strip()
                if name:
                    cast_lookup[name] = char

        # Walk shots — collect per-character appearances in order
        char_order: list[str] = []
        char_shots: dict[str, list[str]] = {}

        for shot in shots:
            shot_id = shot.get("shot_id") or shot.get("label", "")
            names = shot.get("character_names", [])
            if not isinstance(names, list):
                names = [names] if names else []
            for name in names:
                name = str(name).strip()
                if not name:
                    continue
                if name not in char_shots:
                    char_order.append(name)
                    char_shots[name] = []
                if shot_id not in char_shots[name]:
                    char_shots[name].append(shot_id)

        # Build per-character dicts
        tracking: list[dict] = []
        for name in char_order:
            appearances = char_shots[name]
            cast_info = cast_lookup.get(name, {})
            appearance_en = cast_info.get("appearance_en", "").strip()
            default_costume_en = cast_info.get("default_costume_en", "").strip()

            tracking.append({
                "name":               name,
                "appearance_en":      appearance_en,
                "default_costume_en": default_costume_en,
                "shot_appearances":   appearances,
                "first_appearance":   appearances[0] if appearances else "",
                "last_appearance":    appearances[-1] if appearances else "",
                "total_appearances":  len(appearances),
            })

        # Build report
        lines = [
            "👥 角色追踪报告 Character Tracking Report",
            "━" * 50,
            f"共 {len(tracking)} 个角色：",
        ]
        for t in tracking:
            shots_str = ", ".join(t["shot_appearances"])
            lines.append(f"\n角色：{t['name']}")
            if t["appearance_en"]:
                lines.append(f"  外貌：{t['appearance_en']}")
            if t["default_costume_en"]:
                lines.append(f"  服装：{t['default_costume_en']}")
            lines.append(f"  出现次数：{t['total_appearances']}")
            lines.append(f"  首次出现：{t['first_appearance']}")
            lines.append(f"  最后出现：{t['last_appearance']}")
            lines.append(f"  出现分镜：{shots_str}")

        tracking_report = "\n".join(lines)
        tracking_json = json.dumps(tracking, ensure_ascii=False)

        logger.info(f"CharacterTracker: {len(tracking)} characters tracked across {len(shots)} shots")
        return {
            "ui": {"text": [tracking_report]},
            "result": (tracking_json, tracking_report, len(tracking)),
        }
