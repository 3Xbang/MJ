import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ScriptParser")

# 简化版提示词——针对 7B 模型优化，只要求输出 shots 数组
# 角色表从 shots 数据中自动提取
SYSTEM_PROMPT = """你是一位专业影视分镜师。请将以下剧本解析为分镜列表，只返回 JSON 数组，不要其他任何文字。

格式：
[
  {
    "shot_id": "shot_001",
    "label": "第01场-开场",
    "duration_seconds": 5.0,
    "character_names": ["李明"],
    "costume_description": "黑色西装，领带松散",
    "props_list": ["手机"],
    "scene_name": "夜晚城市街道-室外",
    "camera_angle": "medium",
    "camera_motion": "slow_push_in",
    "lighting_style": "冷色调霓虹灯",
    "director_notes": "用冷色调表现孤独感",
    "shot_description": "Medium shot. Character walks alone on a neon-lit city street at night. Cold blue tones. Cinematic.",
    "negative_prompt": "ugly, blurry, low quality",
    "dialogue": "（无）"
  }
]

camera_angle 只能是：close_up, medium, wide, low_angle, high_angle, eye_level, dutch
camera_motion 只能是：static, pan_left, pan_right, zoom_in, zoom_out, tilt_up, tilt_down, orbit, slow_push_in, slow_pull_back, tracking_shot, handheld
duration_seconds 必须是数字（5秒=5.0，10秒=10.0）
shot_description 必须用英文
只返回 JSON 数组，不要解释。

You are a professional film storyboard artist. Parse the script into a JSON array of shots. Return ONLY the JSON array, no other text."""


class AFE_ScriptParser:
    """
    剧本解析节点。

    两种用法：
    1. 连接 LLM 节点输出（推荐）：llm_response 接收任意 LLM 节点的文本输出
    2. 独立模式：填写 llm_api_key 直接调用 DeepSeek/OpenAI API
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "script_text": ("STRING", {
                    "multiline": True,
                    "default": "在这里输入剧本..."
                }),
            },
            "optional": {
                # 来自 Shot Calculator 的分镜数量控制
                "requested_shot_count": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 500,
                    "tooltip": "连接 Shot Calculator 的 shot_count，告诉LLM生成几个分镜（0=自动判断）"
                }),
                "seconds_per_shot": ("INT", {
                    "default": 5,
                    "min": 1,
                    "max": 60,
                    "tooltip": "连接 Shot Calculator 的 seconds_per_shot，每个分镜几秒"
                }),
                "custom_system_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "留空使用默认专业提示词，填写则覆盖默认提示词"
                }),
                "llm_response": ("STRING", {
                    "default": ""
                }),
                "llm_api_key":  ("STRING", {"default": ""}),
                "llm_base_url": ("STRING", {"default": "https://api.deepseek.com/v1"}),
                "llm_model":    ("STRING", {"default": "deepseek-chat"}),
            }
        }

    RETURN_TYPES = ("SHOT_SEQUENCE", "CAST_DATA", "INT", "STRING", "STRING")
    RETURN_NAMES = ("shot_sequence", "cast_data", "shot_count", "sequence_json", "prompt_for_llm")
    FUNCTION = "parse_script"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def parse_script(self, script_text, custom_system_prompt="",
                     requested_shot_count: int = 0, seconds_per_shot: int = 5,
                     llm_response="", llm_api_key="",
                     llm_base_url="https://api.deepseek.com/v1",
                     llm_model="deepseek-chat"):

        if not script_text.strip():
            raise ValueError("script_text 不能为空")

        # 若连接了 Shot Calculator，把分镜要求写进提示词
        shot_requirement = ""
        if requested_shot_count > 0:
            shot_requirement = f"\n\n【分镜要求】请将剧本精确拆分为 {requested_shot_count} 个分镜，每个分镜时长 {seconds_per_shot} 秒（duration_seconds={seconds_per_shot}.0）。"
            logger.info(f"分镜要求：{requested_shot_count}个 × {seconds_per_shot}秒")

        # 使用自定义提示词或默认专业提示词
        system = custom_system_prompt.strip() if custom_system_prompt.strip() else SYSTEM_PROMPT

        # 生成给 LLM 的完整提示词（包含分镜数量要求）
        prompt_for_llm = f"{system}{shot_requirement}\n\n剧本内容：\n{script_text}"

        # ── 决定使用哪个 LLM 响应 ──────────────────────────
        def _looks_like_json(text: str) -> bool:
            t = text.strip()
            return t.startswith("[") or t.startswith("{")

        if llm_response.strip():
            # 用法1：llm_response 有真实内容
            raw = llm_response
            logger.info("使用 llm_response 输入的 LLM 响应")

        elif _looks_like_json(script_text):
            # 用法2：script_text 里直接传入了 JSON（LLM 输出接到了 script_text）
            raw = script_text
            logger.info("从 script_text 检测到 JSON，直接解析")

        elif llm_api_key.strip():
            # 用法3：调用远程 API
            raw = self._call_api(prompt_for_llm, llm_api_key, llm_base_url, llm_model)
            logger.info(f"使用 API 模式：{llm_base_url}")

        else:
            hint = (
                "⚠️ 请选择以下任一方式：\n"
                "方式1：把 LLM 节点的输出连接到 llm_response 输入\n"
                "方式2：在 llm_api_key 填入 DeepSeek API Key\n\n"
                "LLM 提示词：\n\n" + prompt_for_llm
            )
            logger.warning("未提供 LLM 响应或 API Key")
            return ([], [], 0, hint, prompt_for_llm)

        # ── 解析 JSON ────────────────────────────────────────
        cast_list, shots = self._parse_json(raw)
        sequence_json = json.dumps(shots, ensure_ascii=False, indent=2)
        logger.info(f"解析完成：{len(shots)} 个分镜，{len(cast_list)} 个角色")
        return (shots, cast_list, len(shots), sequence_json, prompt_for_llm)

    def _call_api(self, prompt, api_key, base_url, model):
        import asyncio
        async def _call():
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                timeout=60,
            )
            return resp.choices[0].message.content
        return asyncio.run(_call())

    def _parse_json(self, raw: str) -> tuple[list, list]:
        """Parse LLM response. Returns (cast_list, shots_list).
        New format: {"cast": [...], "shots": [...]}
        Old format: [...] (shots array only, cast=[])
        """
        raw = raw.strip()
        # Remove markdown code blocks
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                if "[" in part or "{" in part:
                    raw = part
                    if raw.startswith("json"):
                        raw = raw[4:]
                    break
        raw = raw.strip()
        # Try new dict format first
        obj_start = raw.find("{")
        arr_start = raw.find("[")
        if obj_start != -1 and (arr_start == -1 or obj_start < arr_start):
            end = raw.rfind("}")
            if end != -1:
                try:
                    data = json.loads(raw[obj_start:end + 1])
                    if isinstance(data, dict):
                        cast_list = data.get("cast", [])
                        shots_list = data.get("shots", [])
                        if isinstance(shots_list, list):
                            return (cast_list, shots_list)
                except json.JSONDecodeError:
                    pass
        # Fallback: array format (possibly truncated)
        start = raw.find("[")
        if start == -1:
            raise ValueError(f"LLM 响应中未找到 JSON 数组，响应内容：{raw[:300]}")

        # 1. 先尝试完整解析
        end = raw.rfind("]")
        if end != -1:
            try:
                shots = json.loads(raw[start:end + 1])
                if isinstance(shots, list):
                    cast_list = self._extract_cast_from_shots(shots)
                    return (cast_list, shots)
            except json.JSONDecodeError:
                pass

        # 2. JSON 被截断，用 json_repair 修复
        try:
            from json_repair import repair_json
            truncated = raw[start:]
            if not truncated.rstrip().endswith("]"):
                truncated = truncated.rstrip() + "]"
            repaired = repair_json(truncated)
            shots = json.loads(repaired)
            if isinstance(shots, list) and shots:
                logger.info(f"截断JSON修复成功：恢复 {len(shots)} 个分镜")
                cast_list = self._extract_cast_from_shots(shots)
                return (cast_list, shots)
        except Exception as e:
            logger.warning(f"json_repair 失败：{e}")

        # 3. 最后手段：手动提取完整对象
        shots = self._extract_complete_objects(raw[start:])
        if shots:
            logger.info(f"手动提取完整分镜：{len(shots)} 个")
            cast_list = self._extract_cast_from_shots(shots)
            return (cast_list, shots)

        raise ValueError(f"LLM 响应中未找到 JSON 数组，响应内容：{raw[:300]}")

    def _extract_complete_objects(self, raw: str) -> list:
        """从截断的 JSON 数组字符串中提取所有完整的 JSON 对象"""
        shots = []
        depth = 0
        obj_start = None
        for i, c in enumerate(raw):
            if c == '{':
                if depth == 0:
                    obj_start = i
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0 and obj_start is not None:
                    try:
                        obj = json.loads(raw[obj_start:i + 1])
                        if isinstance(obj, dict):
                            shots.append(obj)
                    except Exception:
                        pass
                    obj_start = None
        return shots

    def _extract_cast_from_shots(self, shots: list) -> list:
        """从分镜数据中提取角色名，自动生成基础角色表"""
        seen = {}
        for i, shot in enumerate(shots):
            names = shot.get("character_names", [])
            if isinstance(names, list):
                for name in names:
                    if name and name not in seen:
                        # 推断角色类型：第一个出现的通常是主角
                        role_type = "lead" if len(seen) == 0 else "supporting"
                        seen[name] = {
                            "character_id": f"char_{len(seen)+1:03d}",
                            "name": name,
                            "role_type": role_type,
                            "gender": "unknown",
                            "age_range": "",
                            "appearance": "",
                            "personality": "",
                            "costume_default": shot.get("costume_description", ""),
                            "appearance_en": f"person named {name}",
                        }
        return list(seen.values())
