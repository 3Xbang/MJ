from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_CostumeAnalyzer")

DEFAULT_NEGATIVE = "ugly, torn, dirty, damaged, low quality"
DEFAULT_STYLE = "fabric detail, product photography, studio lighting"


def _get_shots(shot_sequence) -> list:
    if isinstance(shot_sequence, list):
        return shot_sequence
    if isinstance(shot_sequence, dict):
        return shot_sequence.get("shots", [])
    if hasattr(shot_sequence, "shots"):
        return list(shot_sequence.shots)
    return []


def _translate_costume(description: str) -> str:
    """Produce a basic English prompt from a Chinese costume description.

    For now we output the description as-is so the user can refine it;
    a downstream LLM node can polish the English if needed.
    """
    if not description:
        return "casual outfit"
    # Very lightweight heuristic: common Chinese → English word substitutions
    _map = [
        ("衬衫", "shirt"), ("亚麻", "linen"), ("牛仔裤", "jeans"),
        ("西装", "suit"), ("领带", "tie"), ("裙子", "skirt"),
        ("T恤", "T-shirt"), ("外套", "jacket"), ("卫衣", "hoodie"),
        ("米色", "cream"), ("白色", "white"), ("黑色", "black"),
        ("蓝色", "blue"), ("红色", "red"), ("灰色", "grey"),
        ("袖口", "cuff"), ("卷到手肘", "rolled up to the elbow"),
        ("宽松", "loose-fit"), ("修身", "slim-fit"),
    ]
    result = description
    for zh, en in _map:
        result = result.replace(zh, en)
    # If still mostly Chinese (non-ASCII), wrap it descriptively
    ascii_ratio = sum(1 for c in result if ord(c) < 128) / max(len(result), 1)
    if ascii_ratio < 0.4:
        result = f"outfit described as: {description}"
    return result


class AFE_CostumeAnalyzer:
    """
    服装分析器。
    从所有分镜的 costume_description 字段提取不同服装，
    统计服装套数，生成每套服装的 AI 提示词。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
            },
            "optional": {
                "style_suffix": ("STRING", {
                    "default": DEFAULT_STYLE,
                    "tooltip": "追加到每套服装提示词末尾，接 Director Group 的 style_prompt",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("costumes_json", "costumes_count", "costume_report")
    FUNCTION = "analyze_costumes"
    CATEGORY = "AI Film Editor/Analyzers"
    OUTPUT_NODE = True

    def analyze_costumes(self, shot_sequence, style_suffix: str = DEFAULT_STYLE):
        shots = _get_shots(shot_sequence)

        # Key: (character_name_or_empty, costume_description) → entry dict
        costume_map: dict[tuple, dict] = {}
        seen_order: list[tuple] = []

        for shot in shots:
            shot_id = shot.get("shot_id") or shot.get("label", "")
            costume = shot.get("costume_description", "").strip()
            if not costume:
                continue

            names = shot.get("character_names", [])
            if not isinstance(names, list):
                names = [names] if names else []
            # Associate the costume with the first character (most specific)
            char_name = str(names[0]).strip() if names else ""

            key = (char_name, costume)
            if key not in costume_map:
                seen_order.append(key)
                costume_map[key] = {
                    "character_name": char_name,
                    "description": costume,
                    "appears_in_shots": [],
                }
            if shot_id not in costume_map[key]["appears_in_shots"]:
                costume_map[key]["appears_in_shots"].append(shot_id)

        # Build output list
        costumes: list[dict] = []
        for idx, key in enumerate(seen_order):
            entry = costume_map[key]
            suffix = style_suffix.strip() or DEFAULT_STYLE
            positive_prompt = (
                f"{_translate_costume(entry['description'])}, {suffix}"
            )
            costumes.append({
                "index": idx + 1,
                "character_name": entry["character_name"],
                "description": entry["description"],
                "appears_in_shots": entry["appears_in_shots"],
                "positive_prompt": positive_prompt,
                "negative_prompt": DEFAULT_NEGATIVE,
            })

        # Build report
        lines = [
            "👗 服装分析报告",
            "━" * 10,
            f"共 {len(costumes)} 套服装：",
        ]
        for c in costumes:
            char_label = f"（{c['character_name']}）" if c["character_name"] else ""
            shot_ids = ", ".join(c["appears_in_shots"])
            lines.append(f"服装{c['index']}{char_label}：{c['description']}")
            lines.append(f"  出现分镜：{shot_ids}")
            lines.append(f"  AI提示词：{c['positive_prompt'][:80]}")

        costume_report = "\n".join(lines)
        costumes_json = json.dumps(costumes, ensure_ascii=False)

        logger.info(f"CostumeAnalyzer: found {len(costumes)} unique costumes in {len(shots)} shots")
        return {"ui": {"text": [costume_report]}, "result": (costumes_json, len(costumes), costume_report)}
