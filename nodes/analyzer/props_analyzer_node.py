from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_PropsAnalyzer")

DEFAULT_NEGATIVE = "blurry, damaged, low quality, distorted, person, human, hands, body, background, scene, room, table, surface"
DEFAULT_STYLE = "3D CG animation, CGI rendering, clean white background, studio lighting"

# 道具固定词 — 白底单品，无人无背景
PROPS_PREFIX = "single object on white background, pure white background, no person, no hands, no scene, isolated product shot, clean white backdrop"
DEFAULT_STYLE = "product photography style, studio lighting, clean white background, sharp focus"


def _get_shots(shot_sequence) -> list:
    if isinstance(shot_sequence, list):
        return shot_sequence
    if isinstance(shot_sequence, dict):
        return shot_sequence.get("shots", [])
    if hasattr(shot_sequence, "shots"):
        return list(shot_sequence.shots)
    return []


def _prop_to_english(name: str) -> str:
    """Very lightweight Chinese → English substitution for common props."""
    _map = [
        ("手机", "smartphone"), ("电话", "phone"), ("电脑", "laptop computer"),
        ("桌子", "table"), ("椅子", "chair"), ("书", "book"),
        ("包", "bag"), ("钱包", "wallet"), ("钥匙", "keys"),
        ("眼镜", "glasses"), ("帽子", "hat"), ("伞", "umbrella"),
        ("咖啡", "coffee cup"), ("水杯", "water glass"), ("茶杯", "tea cup"),
        ("相机", "camera"), ("报纸", "newspaper"), ("文件", "document"),
        ("花", "flowers"), ("蜡烛", "candle"), ("灯", "lamp"),
        ("钱", "money"), ("信封", "envelope"), ("信", "letter"),
    ]
    result = name
    for zh, en in _map:
        result = result.replace(zh, en)
    ascii_ratio = sum(1 for c in result if ord(c) < 128) / max(len(result), 1)
    if ascii_ratio < 0.4:
        result = name  # Return original; selector/user can refine
    return result


class AFE_PropsAnalyzer:
    """
    道具分析器。
    从所有分镜的 props_list 字段提取所有道具，
    统计道具数量，生成每件道具的 AI 提示词（产品图风格）。
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
                    "tooltip": "追加到每件道具提示词末尾，接 Director Group 的 style_prompt",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("props_json", "props_count", "props_report")
    FUNCTION = "analyze_props"
    CATEGORY = "AI Film Editor/Analyzers"
    OUTPUT_NODE = True

    def analyze_props(self, shot_sequence, style_suffix: str = DEFAULT_STYLE):
        shots = _get_shots(shot_sequence)

        # prop_name → {shots: [...]}
        prop_map: dict[str, dict] = {}
        seen_order: list[str] = []

        for shot in shots:
            shot_id = shot.get("shot_id") or shot.get("label", "")
            props = shot.get("props_list", [])
            if not isinstance(props, list):
                props = [props] if props else []
            for raw_prop in props:
                prop_name = str(raw_prop).strip()
                if not prop_name:
                    continue
                if prop_name not in prop_map:
                    seen_order.append(prop_name)
                    prop_map[prop_name] = {"shots": []}
                if shot_id not in prop_map[prop_name]["shots"]:
                    prop_map[prop_name]["shots"].append(shot_id)

        props_list: list[dict] = []
        for idx, name in enumerate(seen_order):
            info = prop_map[name]
            en_name = _prop_to_english(name)
            # 道具图：白底单品，风格跟 Director Group 统一
            suffix = style_suffix.strip() or DEFAULT_STYLE
            positive_prompt = f"{PROPS_PREFIX}, {en_name}, {suffix}"
            props_list.append({
                "index": idx + 1,
                "name": name,
                "appears_in_shots": info["shots"],
                "positive_prompt": positive_prompt,
                "negative_prompt": DEFAULT_NEGATIVE,
            })

        # Build report
        lines = [
            "🔧 道具分析报告",
            "━" * 10,
            f"共 {len(props_list)} 件道具：",
        ]
        for p in props_list:
            shot_ids = ", ".join(p["appears_in_shots"])
            lines.append(f"道具{p['index']}：{p['name']}")
            lines.append(f"  出现分镜：{shot_ids}")
            lines.append(f"  AI提示词：{p['positive_prompt'][:80]}")

        props_report = "\n".join(lines)
        props_json = json.dumps(props_list, ensure_ascii=False)

        logger.info(f"PropsAnalyzer: found {len(props_list)} unique props in {len(shots)} shots")
        return {"ui": {"text": [props_report]}, "result": (props_json, len(props_list), props_report)}
