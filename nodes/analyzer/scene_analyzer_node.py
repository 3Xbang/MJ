from __future__ import annotations
import json
import re
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_SceneAnalyzer")

DEFAULT_NEGATIVE = "dark, dirty, crowded, blurry, low quality, people, person, human, character, man, woman, figure"
DEFAULT_STYLE = "3D CG animation, CGI rendering, cinematic"
SCENE_PREFIX = "empty scene, no people, no characters, no humans, background only"
# Empty-set validation is structural rather than an occupation/verb/prop
# blacklist. A free-form phrase that asserts a subject/action or a subject/
# object relation cannot be proven to be place-only, regardless of the words it
# uses. "with" is allowed for set dressing ("a box with water"). People holding,
# carrying, using, gripping, or wearing something still fail. The structured
# fields below provide the stronger boundary for node use.
_ENV_UNPROVEN_RELATION_RE = re.compile(
    r"\b(?:a|an|the)\s+(?:[a-z][a-z-]*\s+){0,3}[a-z][a-z-]*\s+"
    r"(?:holding|carrying|using|gripping|wearing)\s+"
    r"(?:(?:a|an|the)\s+)?[a-z][a-z-]*\b",
    re.IGNORECASE,
)
_ENV_SUBJECT_ACTION_RE = re.compile(
    r"\b(?:a|an|the)\s+(?:[a-z][a-z-]*\s+){0,3}(?P<head>[a-z][a-z-]*)\s+"
    r"(?P<act>[a-z][a-z-]*(?:ing|ed|s)|is\s+[a-z][a-z-]*ing)\b",
    re.IGNORECASE,
)
# Place prose uses participles ("a taillight reflection crossing"). Only a
# person-shaped head noun makes that pattern an action.
_ENV_ROLE_HEAD_RE = re.compile(
    r"(?:smith|person|keeper|officer|worker|operator|inspector|guard|driver|"
    r"chef|clerk|agent|boy|girl|man|woman|guy|stranger|figure|customer|assistant)$",
    re.IGNORECASE,
)
_ENV_EXPLICIT_HUMAN_RE = re.compile(
    r"\b(?:person|people|human|character|man|woman|boy|girl|someone|somebody|figure|silhouette|"
    r"he|she|him|his|her|hers|they|them|their)\b|"
    r"人物|男人|女人|男孩|女孩|他|她|他们|人影",
    re.IGNORECASE,
)
_ENV_HUMAN_ROLE_RE = re.compile(
    r"\b(?:technician|security\s+officer|officer|worker|mechanic|engineer|"
    r"guard|driver|chef|cook|waiter|nurse|doctor|police|soldier|operator|"
    r"inspector|janitor|customer|shopkeeper|clerk|assistant|agent)\b",
    re.IGNORECASE,
)
# A place-only description may use a structural relation ("windows overlook
# the courtyard") or a noun compound ("steel counters"). An article-free
# token ending in ``s`` is therefore ambiguous: distinguish the final token
# from a known structural noun before treating it as a predicate. A structural
# noun may use a small, source-grounded relation vocabulary. An unlisted
# plural ("prayer beads") is place wording. Listed third-person verbs still
# fail closed so "Machinery hums" and "Equipment vibrates" cannot pass.
_ENV_ARTICLE_FREE_SUBJECT_ACTION_RE = re.compile(
    r"(?=(?<![A-Za-z])(?P<subject>[A-Za-z][A-Za-z-]*)\s+"
    r"(?P<verb>[A-Za-z][A-Za-z-]*)\b)",
    re.IGNORECASE,
)
_ENV_STRUCTURAL_SUBJECTS = {
    "wall", "walls", "window", "windows", "door", "doors", "ceiling", "floor",
    "floors", "beam", "beams", "pillar", "pillars", "counter", "counters",
    "shelf", "shelves", "railing", "railings", "roof", "roofs", "stair", "stairs",
    "lamp", "lamps", "light", "lights", "sign", "signs", "table", "tables",
    "chair", "chairs", "sofa", "sofas", "curtain", "curtains", "building", "buildings",
    "room", "rooms", "hall", "halls", "corridor", "corridors", "street", "streets",
    "garden", "gardens", "sky", "sea", "water", "mist", "fog", "rain", "sunlight",
}
_ENV_STRUCTURAL_RELATION_VERBS = {
    "support", "overlook", "contain", "reveal", "connect", "lead",
}
_ENV_PREDICATE_WORDS = {
    "does", "do", "will",
    *_ENV_STRUCTURAL_RELATION_VERBS,
}
_ENV_FUNCTION_WORDS = {
    "of", "in", "on", "with", "and", "or", "for", "to", "from", "by", "at",
    "into", "over", "under", "near", "beside", "across", "through", "without",
    "within", "between", "along", "around", "behind", "above", "below",
}
# A trailing s is usually a plural noun ("prayer beads", "steel counters"), not an
# action. Only listed third-person verbs still count as an action in that slot.
_ENV_THIRD_PERSON_VERBS = {
    "hums", "vibrates", "inspects", "stands", "sits", "holds", "walks", "runs",
    "looks", "turns", "opens", "closes", "glows", "flickers", "waits", "moves",
    "reaches", "grips", "wears", "carries", "uses", "manipulates", "calibrates",
    "leans", "watches", "smiles", "nods", "points", "lifts", "pulls", "pushes",
    "drops", "places", "picks", "grabs", "touches", "stares", "breathes",
}


def validate_empty_scene_prompt(prompt: str, characters=(), forbidden_facts=(), *,
                                environment_scope=None, environment_people=None,
                                environment_props=None) -> str:
    """Return a reason when an environment response is not provably place-only.

    The structured ``subject_scope``/people/props contract is enforced by
    ``analyze_scenes``. This text guard is an additional conservative boundary
    for direct node callers; it rejects grammatical subject/object relations
    instead of trying to maintain a finite list of occupations and props.
    """
    text = str(prompt or "").strip()
    if not text:
        return "environment prompt is empty"
    if environment_scope is not None and environment_scope != "place_only":
        return "environment scope is not place_only"
    if environment_scope is not None and environment_people != []:
        return "place_only environment must contain an explicit empty people array"
    if environment_scope is not None and environment_props != []:
        return "place_only environment must contain an explicit empty props array"
    lowered = text.lower()
    for character in characters or ():
        name = str(character or "").strip()
        if name and name.lower() in lowered:
            return f"contains character name: {name}"
    for fact in forbidden_facts or ():
        fact_text = str(fact or "").strip()
        if fact_text and fact_text.lower() in lowered:
            return f"contains screenplay fact: {fact_text}"
    for match in _ENV_EXPLICIT_HUMAN_RE.finditer(text):
        word = match.group(0).lower()
        prefix = text[max(0, match.start() - 16):match.start()].lower()
        # "no people" / "without people" is the empty-set instruction, not a person.
        if word in {"people", "person", "human", "humans", "人物"} and re.search(
                r"(?:no|without|zero|not any|没有|无)\s*$", prefix):
            continue
        return f"contains an unverified human fact: {match.group(0)}"
    match = _ENV_HUMAN_ROLE_RE.search(text)
    if match:
        return f"contains an unverified human occupation: {match.group(0)}"
    for match in _ENV_ARTICLE_FREE_SUBJECT_ACTION_RE.finditer(text):
        subject = match.group("subject").lower()
        verb = match.group("verb").lower()
        # Inspect overlapping word pairs. This keeps "steel counters" and
        # "glass roofs" as noun compounds instead of mistaking their plural
        # head for a verb, while still checking the next pair in a sentence.
        if subject in {"a", "an", "the"} or subject in _ENV_FUNCTION_WORDS or verb in _ENV_STRUCTURAL_SUBJECTS:
            continue
        # A structural noun may use an explicitly structural relation, but
        # never an unlisted action.
        if subject in _ENV_STRUCTURAL_SUBJECTS and verb in _ENV_STRUCTURAL_RELATION_VERBS:
            continue
        # "the scene is dark" and "the left side has a window" describe the set.
        # Copulas and possession are not actions. "he has a bag" still fails
        # earlier, because pronouns are human facts.
        if verb in {"is", "are", "was", "were", "has", "have", "had"}:
            continue
        if verb not in _ENV_PREDICATE_WORDS and verb not in _ENV_THIRD_PERSON_VERBS:
            continue
        return ("contains an unverified subject/action relation: "
                f"{subject} {verb}")
    match = _ENV_UNPROVEN_RELATION_RE.search(text)
    if match:
        return f"contains an unverified subject/object relation: {match.group(0)}"
    match = _ENV_SUBJECT_ACTION_RE.search(text)
    if match and _ENV_ROLE_HEAD_RE.search(match.group("head")):
        return f"contains an unverified subject/action relation: {match.group(0)}"
    return ""


def _place_only_name_list(value) -> tuple[bool, list]:
    """Accept only an explicit empty name list.

    Older saved analyses stringified ``[]`` to ``""`` while keeping
    ``scope=place_only``. A blank value is that empty list. Any name still fails.
    """
    if isinstance(value, (list, tuple)):
        names = [str(item).strip() for item in value if str(item).strip()]
        return names == [], names
    if isinstance(value, str) and not value.strip():
        return True, []
    return False, [str(value).strip()] if str(value or "").strip() else []


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
            env_payload = shot.get("environment") if isinstance(shot.get("environment"), dict) else {}
            env_scope = (shot.get("environment_scope") if "environment_scope" in shot
                         else env_payload.get("scope", env_payload.get("subject_scope")))
            people_present = "environment_people" in shot or "people" in env_payload
            props_present = "environment_props" in shot or "props" in env_payload
            env_people = (shot.get("environment_people") if "environment_people" in shot
                          else env_payload.get("people"))
            env_props = (shot.get("environment_props") if "environment_props" in shot
                         else env_payload.get("props"))
            people_ok, env_people = _place_only_name_list(env_people)
            props_ok, env_props = _place_only_name_list(env_props)
            if env_scope == "place_only" and (
                    not people_present or not props_present or not people_ok or not props_ok):
                raise ValueError(
                    f"scene {shot_id or scene_name or 'unknown'} place_only requires people and props fields as empty arrays"
                )
            scene_id = str(shot.get("scene_id") or scene_name or "scene_unknown")
            scene_occurrence_id = str(shot.get("scene_occurrence_id") or "")
            section_type = shot.get("section_type") or "location_scene"
            if not scene_name:
                continue

            key = scene_id
            if key not in scene_map:
                seen_order.append(key)
                scene_map[key] = {
                    "scene_id": key,
                    "section_type": section_type,
                    "scene_occurrences": [],
                    "shots": [],
                    "lighting_style": lighting,
                    "time_of_day": time_of_day,
                    "weather": weather,
                    "location": location,
                    "scene_name_en": name_en,
                    "scene_environment_en": env_en,
                    "environment_scope": env_scope,
                    "environment_people": list(env_people) if isinstance(env_people, (list, tuple)) else [env_people],
                    "environment_props": list(env_props) if isinstance(env_props, (list, tuple)) else [env_props],
                    "forbidden_facts": [],
                }
            scene_map[key]["shots"].append(shot_id)
            if scene_occurrence_id and scene_occurrence_id not in scene_map[key]["scene_occurrences"]:
                scene_map[key]["scene_occurrences"].append(scene_occurrence_id)
            info = scene_map[key]
            info.setdefault("characters", [])
            for character in shot.get("character_names") or []:
                if character and character not in info["characters"]:
                    info["characters"].append(str(character))
            for fact in list(shot.get("props_list") or []) + [shot.get("action"), shot.get("business")]:
                fact_text = str(fact or "").strip()
                if fact_text and fact_text not in info["forbidden_facts"]:
                    info["forbidden_facts"].append(fact_text)
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
            if not info.get("environment_scope") and env_scope:
                info["environment_scope"] = env_scope
            if env_people:
                info["environment_people"].extend(x for x in env_people if x not in info["environment_people"])
            if env_props:
                info["environment_props"].extend(x for x in env_props if x not in info["environment_props"])

        scenes: list[dict] = []
        suffix = style_suffix.strip() or DEFAULT_STYLE

        for idx, key in enumerate(seen_order):
            info = scene_map[key]
            name = next((s.get("scene_name", "") for s in shots if str(s.get("scene_id") or s.get("scene_name")) == key), key)
            lighting = info["lighting_style"]
            time_of_day = info["time_of_day"]
            weather = info["weather"]
            location = info["location"]

            base_en = _scene_to_english(name, lighting)

            # A generic name/location prompt is unsafe here: it drops layout,
            # materials, props, weather and light-source facts from the empty
            # set. The parser normally guarantees this field, but direct node
            # use must fail visibly rather than silently degrade.
            if not info["scene_environment_en"].strip():
                raise ValueError(
                    f"场景 {info.get('scene_id', key)} 缺少空场景环境提示词，"
                    "已阻止生成，重试剧本分析或补充环境描述后再继续。"
                )

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
            # The environment model is an untrusted summarizer. Do not strip
            # tokens from a contaminated answer, because that can leave an
            # action or a different person in the empty-scene asset.
            if info.get("environment_scope") != "place_only":
                raise ValueError(
                    f"场景 {info.get('scene_id', key)} 缺少可证明的 place-only 环境结构，"
                    "已阻止生成空场景参考图。请重新分析剧本。"
                )
            if info.get("environment_people") or info.get("environment_props"):
                raise ValueError(
                    f"场景 {info.get('scene_id', key)} 的环境结构包含人物或道具，已阻止空场景生成。"
                )
            contamination = validate_empty_scene_prompt(
                environment_prompt_en, info.get("characters", []), info.get("forbidden_facts", []),
                environment_scope=info.get("environment_scope"),
                environment_people=info.get("environment_people"),
                environment_props=info.get("environment_props"),
            )
            if contamination:
                raise ValueError(
                    f"场景 {info.get('scene_id', key)} 的空场景提示词未通过隔离校验：{contamination}"
                )

            # Use the validated environment text, never the character/action-bearing shot text.
            positive_prompt = f"{SCENE_PREFIX}, {environment_prompt_en}, {suffix}"

            # Build environment_3view_prompt
            env_desc = environment_description_en
            environment_3view_prompt = (
                f"empty scene no people, {env_desc}, front view, eye level, {suffix} | "
                f"empty scene no people, {env_desc}, side angle, {suffix} | "
                f"empty scene no people, {env_desc}, overhead bird eye view, {suffix}"
            )

            scenes.append({
                "scene_id": info.get("scene_id", f"scene_{idx + 1:03d}"),
                "section_type": info.get("section_type", "location_scene"),
                "scene_occurrences": info.get("scene_occurrences", []),
                "asset_id": f"scene:{info.get('scene_id', f'scene_{idx + 1:03d}')}",
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
                "environment_scope": info.get("environment_scope"),
                "environment_people": info.get("environment_people", []),
                "environment_props": info.get("environment_props", []),
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
        return {"ui": {"text": [scene_report], "afe_scenes": [scenes_json]},
                "result": (scenes_json, len(scenes), scene_report)}
