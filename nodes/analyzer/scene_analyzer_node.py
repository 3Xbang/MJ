from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_SceneAnalyzer")

DEFAULT_NEGATIVE = "dark, dirty, crowded, blurry, low quality"


def _get_shots(shot_sequence) -> list:
    if isinstance(shot_sequence, list):
        return shot_sequence
    if isinstance(shot_sequence, dict):
        return shot_sequence.get("shots", [])
    if hasattr(shot_sequence, "shots"):
        return list(shot_sequence.shots)
    return []


def _scene_to_english(name: str, lighting: str) -> str:
    """Generate a base English scene description from Chinese name + lighting."""
    _location_map = [
        ("超市", "supermarket"), ("商场", "shopping mall"), ("街道", "street"),
        ("公园", "park"), ("咖啡厅", "cafe"), ("餐厅", "restaurant"),
        ("办公室", "office"), ("学校", "school"), ("教室", "classroom"),
        ("家", "home"), ("客厅", "living room"), ("卧室", "bedroom"),
        ("厨房", "kitchen"), ("医院", "hospital"), ("车站", "train station"),
        ("地铁", "subway"), ("机场", "airport"), ("酒店", "hotel"),
        ("室内", "interior"), ("室外", "exterior"), ("户外", "outdoor"),
        ("夜晚", "night"), ("白天", "daytime"), ("清晨", "early morning"),
        ("黄昏", "dusk"), ("午后", "afternoon"),
        ("城市", "city"), ("社区", "community"), ("伦敦", "London"),
        ("上海", "Shanghai"), ("北京", "Beijing"),
    ]
    _light_map = [
        ("阳光", "sunlight"), ("霓虹灯", "neon lights"), ("灯光", "ambient lighting"),
        ("冷色调", "cool tones"), ("暖色调", "warm tones"), ("柔光", "soft light"),
        ("侧光", "side lighting"), ("背光", "backlight"), ("自然光", "natural light"),
        ("落地窗", "floor-to-ceiling windows"), ("透进", "streaming through"),
    ]

    en_name = name
    for zh, en in _location_map:
        en_name = en_name.replace(zh, en)

    en_light = lighting
    for zh, en in _light_map:
        en_light = en_light.replace(zh, en)

    # If still largely Chinese, use a generic wrapper
    def _ratio(s: str) -> float:
        return sum(1 for c in s if ord(c) < 128) / max(len(s), 1)

    base = en_name if _ratio(en_name) >= 0.4 else f"scene: {name}"
    light_part = en_light.strip() if _ratio(en_light) >= 0.4 else lighting.strip()

    prompt = base
    if light_part:
        prompt += f", {light_part}"
    return prompt


class AFE_SceneAnalyzer:
    """
    场景分析器。
    从所有分镜的 scene_name 字段提取所有场景，
    统计场景数量，生成每个场景的 AI 提示词（背景描述风格）。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("scenes_json", "scenes_count")
    FUNCTION = "analyze_scenes"
    CATEGORY = "AI Film Editor/Analyzers"
    OUTPUT_NODE = True

    def analyze_scenes(self, shot_sequence):
        shots = _get_shots(shot_sequence)

        # scene_name → {shots, lighting_style}
        scene_map: dict[str, dict] = {}
        seen_order: list[str] = []

        for shot in shots:
            shot_id = shot.get("shot_id") or shot.get("label", "")
            scene_name = shot.get("scene_name", "").strip()
            lighting = shot.get("lighting_style", "").strip()
            if not scene_name:
                continue

            if scene_name not in scene_map:
                seen_order.append(scene_name)
                scene_map[scene_name] = {"shots": [], "lighting_style": lighting}
            scene_map[scene_name]["shots"].append(shot_id)
            # Keep first non-empty lighting description
            if not scene_map[scene_name]["lighting_style"] and lighting:
                scene_map[scene_name]["lighting_style"] = lighting

        scenes: list[dict] = []
        for idx, name in enumerate(seen_order):
            info = scene_map[name]
            lighting = info["lighting_style"]
            base_en = _scene_to_english(name, lighting)
            positive_prompt = f"{base_en}, cinematic, high detail, 8K"

            scenes.append({
                "index": idx + 1,
                "name": name,
                "appears_in_shots": info["shots"],
                "lighting_style": lighting,
                "positive_prompt": positive_prompt,
                "negative_prompt": DEFAULT_NEGATIVE,
            })

        # Build report
        lines = [
            "🌄 场景分析报告",
            "━" * 10,
            f"共 {len(scenes)} 个场景：",
        ]
        for s in scenes:
            shot_ids = ", ".join(s["appears_in_shots"])
            lines.append(f"场景{s['index']}：{s['name']}")
            if s["lighting_style"]:
                lines.append(f"  布光：{s['lighting_style']}")
            lines.append(f"  出现分镜：{shot_ids}")
            lines.append(f"  AI提示词：{s['positive_prompt'][:80]}")

        scene_report = "\n".join(lines)
        scenes_json = json.dumps(scenes, ensure_ascii=False)

        logger.info(f"SceneAnalyzer: found {len(scenes)} unique scenes in {len(shots)} shots")
        return {"ui": {"text": [scene_report]}, "result": (scenes_json, len(scenes))}
