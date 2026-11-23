from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_SceneAnalyzer")

DEFAULT_NEGATIVE = "dark, dirty, crowded, blurry, low quality, people, person, human, character, man, woman, figure"
DEFAULT_STYLE = "3D CG animation, CGI rendering, cinematic"

# 场景固定词 — 明确排除人物，只拍空场景
SCENE_PREFIX = "empty scene, no people, no characters, no humans, background only"


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
    包含 environment_3view_prompt 供三视图背景生成使用。
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
                    "tooltip": "追加到每个场景提示词末尾，接 Director Group 的 style_prompt",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("scenes_json", "scenes_count", "scene_report")
    FUNCTION = "analyze_scenes"
    CATEGORY = "AI Film Editor/Script"
    OUTPUT_NODE = True

    def analyze_scenes(self, shot_sequence, style_suffix: str = DEFAULT_STYLE):
        shots = _get_shots(shot_sequence)

        # scene_name → {shots, lighting_style, time_of_day, weather, location}
        scene_map: dict[str, dict] = {}
        seen_order: list[str] = []

        for shot in shots:
            shot_id = shot.get("shot_id") or shot.get("label", "")
            scene_name = shot.get("scene_name", "").strip()
            lighting = shot.get("lighting_style", "").strip()
            time_of_day = shot.get("time_of_day", "").strip()
            weather = shot.get("weather", "").strip()
            location = shot.get("location", "").strip()
            name_en = (shot.get("scene_name_en") or "").strip()
            env_en = (shot.get("scene_environment_en") or "").strip()
            if not scene_name:
                continue

            if scene_name not in scene_map:
                seen_order.append(scene_name)
                scene_map[scene_name] = {
                    "shots": [],
                    "lighting_style": lighting,
                    "time_of_day": time_of_day,
                    "weather": weather,
                    "location": location,
                    "scene_name_en": name_en,
                    "scene_environment_en": env_en,
                }
            scene_map[scene_name]["shots"].append(shot_id)
            info = scene_map[scene_name]
            # Keep first non-empty value per field
            if not info["lighting_style"] and lighting:
                info["lighting_style"] = lighting
            if not info["time_of_day"] and time_of_day:
                info["time_of_day"] = time_of_day
            if not info["weather"] and weather:
                info["weather"] = weather
            if not info["location"] and location:
                info["location"] = location
            if not info["scene_name_en"] and name_en:
                info["scene_name_en"] = name_en
            if not info["scene_environment_en"] and env_en:
                info["scene_environment_en"] = env_en

        scenes: list[dict] = []
        suffix = style_suffix.strip() or DEFAULT_STYLE

        for idx, name in enumerate(seen_order):
            info = scene_map[name]
            lighting = info["lighting_style"]
            time_of_day = info["time_of_day"]
            weather = info["weather"]
            location = info["location"]

            base_en = _scene_to_english(name, lighting)

            # Build environment_description_en
            tod_weather = " ".join(filter(None, [time_of_day, weather]))
            atm_part = f"{tod_weather} atmosphere" if tod_weather else ""
            env_parts = [name]
            if location:
                env_parts.append(location)
            if atm_part:
                env_parts.append(atm_part)
            if lighting:
                env_parts.append(lighting)
            environment_description_en = ", ".join(filter(None, env_parts))

            # Single clean English environment prompt (place only).
            # Preferred: LLM-written from the screenplay's own scene text.
            # Fallback: keyword translation of name + per-shot location.
            scene_name_en = info["scene_name_en"] or base_en
            environment_prompt_en = info["scene_environment_en"] or environment_description_en

            # Build positive_prompt (uses translated base_en)
            positive_prompt = f"{SCENE_PREFIX}, {base_en}, {suffix}"

            # Build environment_3view_prompt
            env_desc = environment_description_en
            environment_3view_prompt = (
                f"empty scene no people, {env_desc}, front view, eye level, {suffix} | "
                f"empty scene no people, {env_desc}, side angle, {suffix} | "
                f"empty scene no people, {env_desc}, overhead bird eye view, {suffix}"
            )

            scenes.append({
                "index": idx + 1,
                "scene_name": name,
                "name": name,                                # compat alias
                "location": location,
                "time_of_day": time_of_day,
                "weather": weather,
                "lighting_mood": lighting,
                "lighting_style": lighting,                  # compat alias
                "shot_appearances": info["shots"],
                "appears_in_shots": info["shots"],           # compat alias
                "scene_name_en": scene_name_en,
                "environment_prompt_en": environment_prompt_en,
                "environment_description_en": environment_description_en,
                "environment_3view_prompt": environment_3view_prompt,
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
            shot_ids = ", ".join(s["shot_appearances"])
            lines.append(f"场景{s['index']}：{s['scene_name']}")
            if s["location"]:
                lines.append(f"  地点：{s['location']}")
            if s["time_of_day"] or s["weather"]:
                lines.append(f"  时间/天气：{s['time_of_day']} {s['weather']}".strip())
            if s["lighting_mood"]:
                lines.append(f"  布光：{s['lighting_mood']}")
            lines.append(f"  出现分镜：{shot_ids}")
            lines.append(f"  英文名：{s['scene_name_en']}")
            lines.append(f"  环境提示词：{s['environment_prompt_en']}")

        scene_report = "\n".join(lines)
        scenes_json = json.dumps(scenes, ensure_ascii=False)

        logger.info(f"SceneAnalyzer: found {len(scenes)} unique scenes in {len(shots)} shots")
        return {"ui": {"text": [scene_report]}, "result": (scenes_json, len(scenes), scene_report)}
