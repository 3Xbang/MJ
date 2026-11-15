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


def _get_shots(shot_sequence) -> list:
    """Normalize shot_sequence to a plain list of shot dicts."""
    if isinstance(shot_sequence, list):
        return shot_sequence
    if isinstance(shot_sequence, dict):
        return shot_sequence.get("shots", [])
    if hasattr(shot_sequence, "shots"):
        return list(shot_sequence.shots)
    return []


class AFE_CastAnalyzer:
    """
    人物分析器。
    从 shot_sequence 中汇总所有出场角色，可结合 cast_data 补充角色信息，
    为每个角色生成 AI 提示词，并输出格式化分析报告。
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

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("characters_json", "characters_count", "cast_report")
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
            names = shot.get("character_names", [])
            if not isinstance(names, list):
                names = [names] if names else []
            for name in names:
                name = str(name).strip()
                if not name:
                    continue
                if name not in name_info:
                    seen_order.append(name)
                    name_info[name] = {"shots": [], "costume": costume}
                name_info[name]["shots"].append(shot_id)
                # Keep first non-empty costume
                if not name_info[name]["costume"] and costume:
                    name_info[name]["costume"] = costume

        # Build character list
        characters: list[dict] = []
        for idx, name in enumerate(seen_order):
            info = name_info[name]
            char_data = cast_map.get(name, {})

            # Positive prompt: prefer appearance_en from cast_data
            appearance_en = char_data.get("appearance_en", "").strip()
            if appearance_en:
                base = appearance_en
            elif info["costume"]:
                base = f"{name}, {info['costume']}"
            else:
                base = f"person named {name}"

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
            })

        # Build report
        lines = [
            "👥 人物分析报告",
            "━" * 10,
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

        logger.info(f"CastAnalyzer: found {len(characters)} characters in {len(shots)} shots")
        return (characters_json, len(characters), cast_report)
