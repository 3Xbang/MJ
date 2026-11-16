from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_CastAnalyzer")

ROLE_TYPE_LABELS = {
    "lead": "主角",
    "supporting": "配角",
    "extra_a": "路人甲",
    "extra_b": "路人乙",
    "extra_other": "其他路人",
}

DEFAULT_NEGATIVE = "ugly, deformed, blurry, low quality, distorted"
DEFAULT_STYLE = "photorealistic, 8K, studio lighting, white background"

EXTRA_TYPES = {"extra_a", "extra_b", "extra_other"}


def _get_shots(shot_sequence) -> list:
    """Normalize shot_sequence to a plain list of shot dicts."""
    if isinstance(shot_sequence, list):
        return shot_sequence
    if isinstance(shot_sequence, dict):
        return shot_sequence.get("shots", [])
    if hasattr(shot_sequence, "shots"):
        return list(shot_sequence.shots)
    return []


def _build_prompts(char: dict, style_suffix: str) -> tuple[str, str]:
    """
    Generate (positive_prompt, negative_prompt) for a character dict.

    Priority:
      1. appearance_en from cast_data (already embedded in char["positive_prompt"])
      2. fallback: "person, {costume_description}, {style_suffix}"
    """
    # positive_prompt is already built during the main loop with appearance_en / costume
    positive = char.get("positive_prompt", "")
    if not positive:
        # Last-resort fallback
        name = char.get("name", "person")
        costume = char.get("costume_description", "")
        base = f"person, {costume}" if costume else f"person named {name}"
        suffix = style_suffix.strip()
        positive = f"{base}, {suffix}" if suffix else base
    return positive, DEFAULT_NEGATIVE


class AFE_CastAnalyzer:
    """
    人物分析器。
    从 shot_sequence 中汇总所有出场角色，可结合 cast_data 补充角色信息，
    为每个角色生成 AI 提示词，并按角色类型输出独立提示词口（主角/配角/路人）。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
            },
            "optional": {
                "cast_data": ("CAST_DATA",),
                "style_suffix": ("STRING", {
                    "default": DEFAULT_STYLE,
                    "tooltip": "追加到每个人物正面提示词末尾的风格描述",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "characters_json",      # 全部角色 JSON
        "characters_count",     # 角色数量
        "lead_positive",        # 主角正向提示词
        "lead_negative",        # 主角负面提示词
        "supporting_positive",  # 第一配角正向提示词
        "supporting_negative",  # 第一配角负面提示词
        "extra_positive",       # 路人甲正向提示词（第一个路人）
        "extra_negative",       # 路人甲负面提示词
    )
    FUNCTION = "analyze_cast"
    CATEGORY = "AI Film Editor/Analyzers"
    OUTPUT_NODE = True

    def analyze_cast(
        self,
        shot_sequence,
        cast_data=None,
        style_suffix: str = DEFAULT_STYLE,
    ):
        shots = _get_shots(shot_sequence)

        # Build name → cast_data mapping for quick lookup
        cast_map: dict[str, dict] = {}
        if cast_data:
            for char in cast_data:
                name = char.get("name", "")
                if name:
                    cast_map[name] = char

        # Traverse all shots to collect appearances and first costume per character
        seen_order: list[str] = []
        name_info: dict[str, dict] = {}  # name → {shots, costume}

        for shot in shots:
            shot_id = shot.get("shot_id") or shot.get("label", "")
            costume = shot.get("costume_description", "")
            costume_en = shot.get("costume_en", "").strip()
            names = shot.get("character_names", [])
            if not isinstance(names, list):
                names = [names] if names else []
            for name in names:
                name = str(name).strip()
                if not name:
                    continue
                if name not in name_info:
                    seen_order.append(name)
                    name_info[name] = {"shots": [], "costume": costume, "costume_en": costume_en}
                name_info[name]["shots"].append(shot_id)
                # Keep first non-empty values
                if not name_info[name]["costume"] and costume:
                    name_info[name]["costume"] = costume
                if not name_info[name]["costume_en"] and costume_en:
                    name_info[name]["costume_en"] = costume_en

        # Build character list
        characters: list[dict] = []
        for idx, name in enumerate(seen_order):
            info = name_info[name]
            char_data = cast_map.get(name, {})

            # ── Positive prompt: layer appearance + costume ──────────────────
            # appearance_en  = physical description from cast_data (new format)
            # default_costume_en = representative outfit from cast_data (new format)
            # costume_en     = outfit from shot data (fallback when cast_data absent)
            appearance_en      = char_data.get("appearance_en", "").strip()
            default_costume_en = char_data.get("default_costume_en", "").strip()
            costume_en         = info.get("costume_en", "").strip()

            # Determine the best outfit descriptor (English only)
            outfit = default_costume_en or costume_en

            if appearance_en and outfit:
                base = f"{appearance_en}, {outfit}"
            elif appearance_en:
                base = appearance_en
            elif outfit:
                base = f"person, {outfit}"
            else:
                # Last resort: no English data at all — generic person
                base = "person"

            suffix = style_suffix.strip()
            positive_prompt = f"{base}, {suffix}" if suffix else base

            # Role type: lead for first, supporting for rest (cast_data overrides)
            role_type = char_data.get("role_type", "lead" if idx == 0 else "supporting")

            characters.append({
                "index": idx + 1,
                "name": name,
                "role_type": role_type,
                "appearances": info["shots"],
                "positive_prompt": positive_prompt,
                "negative_prompt": DEFAULT_NEGATIVE,
                "costume_description": info["costume"],
                "costume_en": info.get("costume_en", ""),
            })

        # ── Filter by role type ───────────────────────────────────────────────
        leads       = [c for c in characters if c["role_type"] == "lead"]
        supportings = [c for c in characters if c["role_type"] == "supporting"]
        extras      = [c for c in characters if c["role_type"] in EXTRA_TYPES]

        lead_char  = leads[0]       if leads       else None
        sup_char   = supportings[0] if supportings else None
        extra_char = extras[0]      if extras       else None

        lead_positive,       lead_negative       = _build_prompts(lead_char,  style_suffix) if lead_char  else ("", "")
        supporting_positive, supporting_negative = _build_prompts(sup_char,   style_suffix) if sup_char   else ("", "")
        extra_positive,      extra_negative      = _build_prompts(extra_char, style_suffix) if extra_char else ("", "")

        # ── Build report ─────────────────────────────────────────────────────
        lead_name  = lead_char["name"]  if lead_char  else "无"
        sup_name   = sup_char["name"]   if sup_char   else "无"
        extra_name = extra_char["name"] if extra_char else "无"

        summary_line = f"🎭 主角：{lead_name} | 配角：{sup_name} | 路人：{extra_name}"

        lines = [
            "👥 人物分析报告",
            "━" * 10,
            summary_line,
            f"共 {len(characters)} 个人物：",
        ]
        for c in characters:
            label = ROLE_TYPE_LABELS.get(c["role_type"], c["role_type"])
            shot_ids = ", ".join(c["appearances"])
            prompt_preview = c["positive_prompt"][:80]
            if len(c["positive_prompt"]) > 80:
                prompt_preview += "..."
            lines.append(f"人物{c['index']}：{c['name']}（{label}）")
            lines.append(f"  出现分镜：{shot_ids}")
            lines.append(f"  AI提示词：{prompt_preview}")

        cast_report = "\n".join(lines)
        characters_json = json.dumps(characters, ensure_ascii=False)

        logger.info(
            "CastAnalyzer: found %d characters (%d lead, %d supporting, %d extra) in %d shots",
            len(characters), len(leads), len(supportings), len(extras), len(shots),
        )

        return {
            "ui": {"text": [cast_report]},
            "result": (
                characters_json,
                len(characters),
                lead_positive,
                lead_negative,
                supporting_positive,
                supporting_negative,
                extra_positive,
                extra_negative,
            ),
        }
