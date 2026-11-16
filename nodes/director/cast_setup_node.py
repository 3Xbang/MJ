"""
AFE_CastSetup - Cast Setup Node (standalone, like Director Group)
No connection inputs. Fill in text boxes, outputs CAST_DATA.
"""
from __future__ import annotations
import logging

logger = logging.getLogger("AFE_CastSetup")


def _parse_names(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def _entry(idx, name, role_type):
    return {
        "character_id": f"char_{idx:03d}",
        "name": name,
        "role_type": role_type,
        "gender": "unknown",
        "age_range": "",
        "appearance_en": "",
        "default_costume_en": "",
        "costume_default": "",
        "appearance": "",
        "personality": "",
        "shot_count": 0,
        "appearances": [],
        "_source": "manual",
    }


class AFE_CastSetup:
    """
    Cast Setup - standalone cast builder, like Director Group.
    No connection inputs needed. Fill in names, get CAST_DATA out.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lead_names": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "Lead characters, one name per line",
                }),
                "supporting_names": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "Supporting characters, one name per line",
                }),
            },
            "optional": {
                "extra_a_names": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "Extra A, one name per line",
                }),
                "extra_b_names": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "Extra B, one name per line",
                }),
                "notes": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "Notes only, no effect on output",
                }),
            },
        }

    RETURN_TYPES = ("CAST_DATA", "STRING")
    RETURN_NAMES = ("cast_data", "cast_report")
    FUNCTION = "setup_cast"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def setup_cast(self, lead_names="", supporting_names="",
                   extra_a_names="", extra_b_names="", notes=""):
        leads      = _parse_names(lead_names)
        supporting = _parse_names(supporting_names)
        extras_a   = _parse_names(extra_a_names)
        extras_b   = _parse_names(extra_b_names)

        cast_data = []
        idx = 1
        for name in leads:
            cast_data.append(_entry(idx, name, "lead")); idx += 1
        for name in supporting:
            cast_data.append(_entry(idx, name, "supporting")); idx += 1
        for name in extras_a:
            cast_data.append(_entry(idx, name, "extra_a")); idx += 1
        for name in extras_b:
            cast_data.append(_entry(idx, name, "extra_b")); idx += 1

        lines = [
            "Cast List",
            "=" * 24,
            f"Lead:       {len(leads)} - {' / '.join(leads) if leads else '(none)'}",
            f"Supporting: {len(supporting)} - {' / '.join(supporting) if supporting else '(none)'}",
        ]
        if extras_a: lines.append(f"Extra A: {' / '.join(extras_a)}")
        if extras_b: lines.append(f"Extra B: {' / '.join(extras_b)}")
        lines += ["=" * 24, f"Total: {len(cast_data)} characters"]
        if notes.strip(): lines.append(f"Notes: {notes.strip()}")

        report = "\n".join(lines)
        logger.info("CastSetup: %d total", len(cast_data))
        return {"ui": {"text": [report]}, "result": (cast_data, report)}