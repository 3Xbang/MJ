"""
script_full_parser_node.py
AFE_ScriptFullParser — Two-phase LLM script parser using transformers directly.

Phase 1 (1 call): Quick parse → cast + shot list with minimal fields (~2048 tokens output).
Phase 2 (1 call per shot): Deep analysis → camera, lighting, action, etc. (~768 tokens each).

Avoids the LLM_local output-token limit by calling Qwen2.5-7B-Instruct directly
via transformers, keeping each phase's output budget well under the model limit.
"""

import json
import os
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ScriptFullParser")

# ── Phase 1 system prompt ─────────────────────────────────────────────────────
PHASE1_SYSTEM = """You are a professional film storyboard artist. Break the screenplay into individual shots for video production.
Return ONLY the JSON object, no explanation, no markdown.

IMPORTANT: Each shot = ONE specific 5-second moment. Break scenes into small shots:
- One line of dialogue = one shot
- One physical action = one shot  
- Reaction / pause / expression change = one shot
- Scene transition = one shot
You MUST generate EXACTLY the number of shots specified in the user message.

CRITICAL — scene_name RULE:
The screenplay marks real locations with headers like "【场景 A：伦敦社区超市/外卖厨房 - 下午】"
or "【场景 B：泰国海边别墅露台 - 白天】". scene_name MUST be copied from the NEAREST such
header above each shot (translate to concise English, e.g. "London Supermarket Kitchen"
or "Thai Beach Villa Terrace"). Every shot belonging to the same screenplay scene header
MUST use the IDENTICAL scene_name string — this groups shots into the same physical set.
NEVER use a transition/camera direction tag such as [黑屏], [半剪影], [快速闪切], [内景-日],
[外景-日] as scene_name — those are shot direction notes, not locations. If a shot has no
scene header yet (e.g. cold open before the first 【场景 X】), reuse the nearest following
header's scene_name.

raw_description MUST include concrete set/location details copied from the screenplay's
scene description paragraph (materials, furniture, lighting fixtures, weather) — not just
the character action — so a cinematographer can recreate the actual place later.

Format:
{
  "cast": [
    {
      "name": "CharacterName",
      "role_type": "lead",
      "gender": "male",
      "age_range": "24-26",
      "appearance_en": "English physical description",
      "default_costume_en": "English default outfit description"
    }
  ],
  "shots": [
    {
      "shot_id": "shot_001",
      "scene_name": "<English translation of the nearest 【场景 X：...】 header, identical across all shots in that scene>",
      "character_names": ["name"],
      "dialogue": "one line of quoted dialogue or null",
      "props_list": ["prop1"],
      "raw_description": "max 40 words: concrete set details + who does what + emotion, single moment only"
    }
  ]
}

Rules:
- role_type: lead | supporting | extra_a | extra_b | extra_other
- Each shot covers ONLY one specific moment, not an entire scene
- Split long dialogue into separate shots (one line per shot)
- Split long action sequences into separate shots
- Return ONLY the JSON object."""

# ── Phase 2 system prompt ─────────────────────────────────────────────────────
PHASE2_SYSTEM = """You are a professional cinematographer. Given a shot description and context, generate detailed cinematic directions.

CRITICAL RULE: The "Description" field in the user message contains the ACTUAL scene content
(location, set pieces, props, action) taken directly from the real screenplay. You MUST extract
"location", "lighting", "action", "business", "emotion" etc. FROM THAT DESCRIPTION TEXT.
NEVER invent a generic location like "apartment living room" — that is a placeholder format example only,
not a real answer. If the Description mentions a supermarket, kitchen, beach villa, office etc.,
your location field MUST reflect that same real place, in English, with specific set details
(materials, furniture, lighting fixtures) carried over from the Description.

Return ONLY a JSON object with these exact fields (field names fixed, VALUES must be derived
from the actual Description — the strings below are FORMAT HINTS, not real answers to copy):

{
  "camera_angle": "<pick one from camera_angle options below>",
  "camera_motion": "<pick one from camera_motion options below>",
  "shot_type": "<camera_angle and camera_motion combined in natural language, e.g. 'close-up slow push in' or 'wide shot tracking'>",
  "lighting_style": "<derived from Description, e.g. 'cold white LED panel lights, overcast London afternoon'>",
  "location": "<the REAL location from Description, e.g. 'London community supermarket interior, stainless steel takeaway counter' — DO NOT default to a generic living room>",
  "time_of_day": "<morning|afternoon|evening|night, from Description>",
  "weather": "<sunny|cloudy|rainy|snowy|foggy|indoor|clear, from Description>",
  "lighting": "<detailed English lighting description matching Description's actual light sources>",
  "action": "<main character action in English, from Description>",
  "business": "<subtle physical detail from Description, e.g. 'fingers the rim of the cup'>",
  "emotion": "<character emotion/expression in English, from Description>",
  "shot_description": "<Wan2.1 optimized English description max 80 words, grounded in Description's real setting>",
  "costume_description": "<Chinese costume description>",
  "costume_en": "<English costume description>",
  "negative_prompt": "ugly, blurry, low quality, distorted",
  "director_notes": "<brief director instruction for this shot, e.g. 'pace is slow, hold on her face'>"
}

camera_angle options: close_up | medium_close_up | medium | full_body | wide | extreme_close_up | low_angle | high_angle | dutch
camera_motion options: static | slow_push_in | slow_pull_back | pan_left | pan_right | tracking_shot | crane_up | crane_down | handheld | orbit
time_of_day options: morning, afternoon, evening, night
weather options: sunny, cloudy, rainy, snowy, foggy, indoor, clear

CAMERA SELECTION RULES (must follow these):
- Opening scene / establishing shot → wide shot (wide_shot), camera: slow_push_in
- Character introduced for first time → medium shot, camera: static
- Dialogue (one person speaking) → medium close-up, camera: static or slow_push_in
- Two people talking (shot/reverse) → medium shot, alternating eye-level
- Emotional climax / reaction → close_up, camera: static (hold)
- Action / movement → medium or wide, camera: tracking_shot or pan
- Object / prop detail → close_up or extreme close-up, camera: static
- Ending / resolution → wide shot, camera: slow_pull_back
- Character thinking / internal moment → close_up, camera: slow_push_in
- Scene transition → wide shot, camera: static or pan

Return ONLY the JSON object."""


def _normalize_durations(shots: list, target_seconds: int, default_secs: int) -> list:
    """
    Redistribute durations so total ≈ target_seconds.
    Weights: shots with dialogue get 2x weight vs shots without.
    """
    if not shots:
        return shots
    weights = []
    for shot in shots:
        dialogue = shot.get("dialogue")
        has_dialogue = dialogue and dialogue not in ("null", "(无)", "none", "")
        desc_words = len(shot.get("raw_description", "").split())
        weight = 2.0 if has_dialogue else 1.0
        weight += desc_words / 50.0
        weights.append(weight)
    total_weight = sum(weights)
    for i, shot in enumerate(shots):
        shot["duration_seconds"] = round(
            max(default_secs, (weights[i] / total_weight) * target_seconds), 1
        )
    return shots


class AFE_ScriptFullParser:
    """
    全剧本深度解析器 — Two-phase LLM approach.
    Phase 1 (1 call): Quick parse → shot list with minimal fields + cast (~750 tokens output).
    Phase 2 (1 call per shot): Deep analysis → camera, lighting, action, etc. (~250 tokens each).
    Uses transformers directly to call Qwen2.5-7B-Instruct; avoids LLM_local token-limit issues.
    Model is cached at class level and loaded once per model_path.
    """

    _model = None
    _tokenizer = None
    _model_path_loaded = None

    @classmethod
    def _ensure_model(cls, model_path: str):
        if cls._model is not None and cls._model_path_loaded == model_path:
            return
        logger.info(f"[AFE_ScriptFullParser] Loading model from: {model_path}")
        logger.info("[AFE_ScriptFullParser] First load may take several minutes...")
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        cls._tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        cls._model = AutoModelForCausalLM.from_pretrained(
            model_path, device_map="auto", torch_dtype=torch.float16, trust_remote_code=True
        )
        cls._model.eval()
        cls._model_path_loaded = model_path
        logger.info("[AFE_ScriptFullParser] Model loaded.")

    def _call_llm(self, system_prompt: str, user_prompt: str, model_path: str,
                  max_new_tokens: int = 2048) -> str:
        self._ensure_model(model_path)
        import torch
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ]
        text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer([text], return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=0.3,
                do_sample=True,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        generated = output_ids[0][inputs.input_ids.shape[1]:]
        return self._tokenizer.decode(generated, skip_special_tokens=True)

    # ── ComfyUI interface ─────────────────────────────────────────────────────

    RENDER_STYLES = [
        "3D cartoon Pixar animation style, vibrant colors, 8k",
        "3D cartoon Disney animation style, warm tones, 8k",
        "3D realistic CGI, photorealistic, cinematic lighting, 8k",
        "2.5D flat illustration, clean lines, vibrant palette",
        "Anime / cel-shading style, bold outlines, vivid colors",
        "Watercolor animation, soft brushstrokes, pastel tones",
        "Stop-motion clay animation, tactile textures, warm light",
        "Comic-book / graphic-novel style, bold lines, high contrast",
        "High-key 3D cartoon, super-bright lighting, no shadows",
        "Low-key 3D cinematic, moody, dramatic shadows",
    ]

    EPISODE_FORMATS = [
        "短片 Short Film (1-3 min)",
        "竖版短剧 Vertical Short Drama (3-5 min)",
        "迷你剧集 Mini Episode (5-10 min)",
        "标准剧集 Standard Episode (20-30 min)",
        "电影 Feature Film (90-120 min)",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "raw_script": ("STRING", {
                    "multiline": True,
                    "default": "在这里输入剧本...",
                    "tooltip": "粘贴完整剧本文本",
                }),
                "render_style": (cls.RENDER_STYLES, {
                    "default": cls.RENDER_STYLES[0],
                    "tooltip": "整体渲染风格，影响所有分镜提示词",
                }),
                "episode_format": (cls.EPISODE_FORMATS, {
                    "default": cls.EPISODE_FORMATS[2],
                    "tooltip": "集数格式，决定总时长预期",
                }),
            },
            "optional": {
                "target_duration_seconds": ("INT", {
                    "default": 180, "min": 30, "max": 7200,
                    "tooltip": "目标总时长（秒）。180=3分钟。LLM 会据此决定镜头数量",
                }),
                "seconds_per_shot": ("INT", {
                    "default": 5, "min": 3, "max": 15,
                    "tooltip": "每个分镜的默认时长（秒）",
                }),
                "lighting_mood": (["auto (from script)", "High-key bright", "Low-key moody",
                                   "Golden hour warm", "Cool blue night", "Neon cyberpunk",
                                   "Natural daylight", "Studio flat light"], {
                    "default": "auto (from script)",
                    "tooltip": "整体光线风格（auto = 由剧本场景决定）",
                }),
                "color_palette": (["auto (from style)", "Vibrant saturated",
                                   "Pastel soft", "Warm amber", "Cool desaturated",
                                   "High contrast B&W", "Earthy natural"], {
                    "default": "auto (from style)",
                }),
                "model_path": ("STRING", {
                    "default": "LLM/Qwen2.5-7B-Instruct",
                    "tooltip": "Qwen LLM 模型路径（相对于 models/ 目录）",
                }),
            },
        }

    RETURN_TYPES  = ("SHOT_SEQUENCE", "CAST_DATA", "STRING", "STRING", "INT", "INT", "INT", "STRING")
    RETURN_NAMES  = ("shot_sequence", "cast_data", "shots_json", "cast_json",
                     "shot_count", "scene_count", "props_count", "report")
    FUNCTION      = "parse_script"
    CATEGORY      = "AI Film Editor/Script"
    OUTPUT_NODE   = True

    # ── Main entry point ──────────────────────────────────────────────────────

    def parse_script(self, raw_script: str,
                     render_style: str = "3D cartoon Pixar animation style, vibrant colors, 8k",
                     episode_format: str = "迷你剧集 Mini Episode (5-10 min)",
                     target_duration_seconds: int = 180,
                     seconds_per_shot: int = 5,
                     lighting_mood: str = "auto (from script)",
                     color_palette: str = "auto (from style)",
                     model_path: str = "LLM/Qwen2.5-7B-Instruct"):

        if not raw_script.strip():
            raise ValueError("raw_script 不能为空")

        # 组合风格参数
        style_full = render_style
        if lighting_mood != "auto (from script)":
            style_full += f", {lighting_mood}"
        if color_palette != "auto (from style)":
            style_full += f", {color_palette} color palette"

        # 目标镜头数 = 总时长 / 每镜时长
        target_shot_count = max(1, round(target_duration_seconds / seconds_per_shot))

        # 1. Resolve model_path to absolute
        if not os.path.isabs(model_path):
            try:
                import folder_paths
                model_path = os.path.join(folder_paths.models_dir, model_path)
            except ImportError:
                pass
        logger.info(f"[AFE_ScriptFullParser] Using model: {model_path}")

        # 2. Phase 1: single LLM call → cast + minimal shots
        logger.info("[AFE_ScriptFullParser] Phase 1: parsing script (target %d shots × %ds = %ds)...",
                    target_shot_count, seconds_per_shot, target_duration_seconds)
        phase1_user = (
            f"Generate EXACTLY {target_shot_count} shots "
            f"(total {target_duration_seconds}s at {seconds_per_shot}s each). "
            f"Episode format: {episode_format}. "
            f"Break scenes and dialogue into individual {seconds_per_shot}-second moments.\n"
            f"Screenplay:\n{raw_script}"
        )
        phase1_raw = self._call_llm(
            PHASE1_SYSTEM,
            phase1_user,
            model_path,
            max_new_tokens=8192,  # 36 shots × ~100 tokens = ~3600, need headroom
        )
        phase1_data = self._parse_llm_json(phase1_raw)
        if not isinstance(phase1_data, dict):
            phase1_data = {}

        cast_list    = phase1_data.get("cast", [])
        minimal_shots = phase1_data.get("shots", [])
        minimal_shots = _normalize_durations(minimal_shots, target_duration_seconds, seconds_per_shot)
        logger.info(f"[AFE_ScriptFullParser] Phase 1 done: {len(cast_list)} cast, {len(minimal_shots)} shots")

        # 3. Build cast lookup by name
        cast_lookup = {c["name"]: c for c in cast_list if isinstance(c, dict) and "name" in c}

        # 4. Phase 2: deep analysis per shot
        full_shots = []
        total = len(minimal_shots)

        for i, shot in enumerate(minimal_shots):
            shot_id    = shot.get("shot_id", f"shot_{i + 1:03d}")
            scene_name = shot.get("scene_name", "")
            char_names = shot.get("character_names", [])
            raw_desc   = shot.get("raw_description", "")
            dialogue   = shot.get("dialogue", None)
            props_list = shot.get("props_list", [])

            logger.info(f"[AFE_ScriptFullParser] Phase 2: shot {i + 1}/{total} ({shot_id})")

            # Build character appearance context for Phase 2
            char_lines = []
            for name in char_names:
                char = cast_lookup.get(name, {})
                appearance = char.get("appearance_en", "")
                if appearance:
                    char_lines.append(f"- {name}: {appearance}")
            char_context = "\n".join(char_lines) if char_lines else "none"

            p2_user = (
                f"Shot ID: {shot_id}\n"
                f"Scene: {scene_name}\n"
                f"Characters: {', '.join(char_names) if char_names else 'none'}\n"
                f"Character Appearance:\n{char_context}\n"
                f"Description: {raw_desc}\n"
                f"Render Style: {style_full}\nShot duration: {seconds_per_shot}s"
            )

            try:
                p2_raw  = self._call_llm(PHASE2_SYSTEM, p2_user, model_path, max_new_tokens=768)
                p2_data = self._parse_llm_json(p2_raw)
                if not isinstance(p2_data, dict):
                    p2_data = {}
            except Exception as exc:
                logger.warning(f"[AFE_ScriptFullParser] Phase 2 failed for {shot_id}: {exc}")
                p2_data = {}

            # 5. Merge minimal + phase2 into full shot dict
            full_shot = {
                "shot_id":          shot_id,
                "label":            f"第{i + 1:02d}场-{scene_name}",
                "duration_seconds": float(seconds_per_shot),
                "character_names":  char_names,
                "costume_description": p2_data.get("costume_description", ""),
                "costume_en":          p2_data.get("costume_en", ""),
                "props_list":          props_list,
                "scene_name":          scene_name,
                "camera_angle":        p2_data.get("camera_angle", "medium"),
                "camera_motion":       p2_data.get("camera_motion", "static"),
                "shot_type":           p2_data.get("shot_type", ""),
                "lighting_style":      p2_data.get("lighting_style", ""),
                "director_notes":      p2_data.get("director_notes", ""),
                "shot_description":    p2_data.get("shot_description", raw_desc),
                "negative_prompt":     p2_data.get("negative_prompt", "ugly, blurry, low quality, distorted"),
                "dialogue":            dialogue if dialogue else "（无）",
                "location":            p2_data.get("location", scene_name),
                "time_of_day":         p2_data.get("time_of_day", "afternoon"),
                "weather":             p2_data.get("weather", "indoor"),
                "lighting":            p2_data.get("lighting", ""),
                "action":              p2_data.get("action", ""),
                "business":            p2_data.get("business", ""),
                "emotion":             p2_data.get("emotion", ""),
            }
            full_shots.append(full_shot)

        # 6. Compute deduplicated ordered scenes and props
        seen_scenes: list[str] = []
        for shot in full_shots:
            sn = shot.get("scene_name", "").strip()
            if sn and sn not in seen_scenes:
                seen_scenes.append(sn)

        seen_props: list[str] = []
        for shot in full_shots:
            for p in shot.get("props_list", []):
                p = str(p).strip()
                if p and p not in seen_props:
                    seen_props.append(p)

        shot_count  = len(full_shots)
        scene_count = len(seen_scenes)
        props_count = len(seen_props)

        # 7. Build human-readable Chinese report
        scene_lines = "\n".join(f"  - {s}" for s in seen_scenes) if seen_scenes else "  （无）"
        cast_lines  = "\n".join(
            f"  - {c.get('name', '?')} ({c.get('role_type', '')})"
            for c in cast_list
        ) if cast_list else "  （无）"

        report = (
            f"✅ 剧本解析完成\n"
            f"📽️ 分镜数量：{shot_count}\n"
            f"🎬 场景数量：{scene_count}\n"
            f"🔧 道具数量：{props_count}\n"
            f"👥 角色数量：{len(cast_list)}\n\n"
            f"📋 场景列表：\n{scene_lines}\n\n"
            f"🎭 角色列表：\n{cast_lines}"
        )

        logger.info(f"[AFE_ScriptFullParser] Done: {shot_count} shots, {scene_count} scenes, "
                    f"{props_count} props, {len(cast_list)} cast")

        # 8. Return
        shots_json = json.dumps(full_shots, ensure_ascii=False, indent=2)
        cast_json  = json.dumps(cast_list,  ensure_ascii=False, indent=2)

        return {
            "ui": {"text": [report]},
            "result": (
                full_shots, cast_list,
                shots_json, cast_json,
                shot_count, scene_count, props_count,
                report,
            ),
        }

    # ── JSON parsing helper ───────────────────────────────────────────────────

    def _parse_llm_json(self, raw: str):
        """Strip markdown code fences, try json.loads, then substring extraction,
        then json_repair. Returns {} if all attempts fail."""
        raw = raw.strip()

        # Strip markdown code fences
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                if "{" in part or "[" in part:
                    raw = part.strip()
                    if raw.startswith("json"):
                        raw = raw[4:].strip()
                    break

        # 1. Try direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 2. Find first { or [ and last matching } or ]
        obj_start = raw.find("{")
        arr_start = raw.find("[")

        if obj_start == -1 and arr_start == -1:
            pass
        else:
            if obj_start == -1:
                start, end_char = arr_start, "]"
            elif arr_start == -1:
                start, end_char = obj_start, "}"
            elif obj_start < arr_start:
                start, end_char = obj_start, "}"
            else:
                start, end_char = arr_start, "]"

            end = raw.rfind(end_char)
            if end != -1 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    pass

        # 3. Try json_repair if available
        try:
            from json_repair import repair_json
            repaired = repair_json(raw)
            return json.loads(repaired)
        except Exception:
            pass

        logger.warning(f"[AFE_ScriptFullParser] _parse_llm_json failed. Raw[:200]: {raw[:200]}")
        return {}
