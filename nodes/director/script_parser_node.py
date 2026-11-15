import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ScriptParser")

SYSTEM_PROMPT = """你是一位专业影视导演和分镜师。请将以下剧本精确解析为结构化分镜列表。

每个分镜必须包含以下字段：
- shot_id: 顺序编号（shot_001, shot_002...）
- label: 简短场景标签（如"第01场-街道追逐"）
- duration_seconds: 精确时长（秒，如 5.0 表示5秒）
- character_names: 该镜头出现的角色名字列表
- costume_description: 角色服装描述（中文）
- props_list: 该镜头使用的道具列表
- scene_name: 场景名称（如"夜晚城市街道-室外"）
- camera_motion: 镜头运动（只能是：static, pan_left, pan_right, zoom_in, zoom_out, tilt_up, tilt_down, orbit）
- shot_description: 详细画面英文描述，用于AI图像生成（如 "Medium shot. Character walks down a neon-lit street at night. Cinematic lighting."）
- negative_prompt: 该镜头应避免的元素（英文，如 "ugly, blurry, watermark"）
- dialogue: 台词（无台词填空字符串）

重要规则：
1. duration_seconds 必须是明确数字（5秒=5.0，10秒=10.0）
2. shot_description 必须用英文写，详细描述构图、光线、人物动作
3. 每个分镜独立完整，不依赖上下文
4. 只返回 JSON 数组，不要其他任何文字

You are a professional film director and storyboard artist. Parse the script into structured shots.
Return ONLY a JSON array. Each shot must have: shot_id, label, duration_seconds, character_names, costume_description, props_list, scene_name, camera_motion, shot_description (English), negative_prompt (English), dialogue."""


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

    RETURN_TYPES = ("SHOT_SEQUENCE", "INT", "STRING", "STRING")
    RETURN_NAMES = ("shot_sequence", "shot_count", "sequence_json", "prompt_for_llm")
    FUNCTION = "parse_script"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def parse_script(self, script_text, custom_system_prompt="",
                     llm_response="", llm_api_key="",
                     llm_base_url="https://api.deepseek.com/v1",
                     llm_model="deepseek-chat"):

        if not script_text.strip():
            raise ValueError("script_text 不能为空")

        # 使用自定义提示词或默认专业提示词
        system = custom_system_prompt.strip() if custom_system_prompt.strip() else SYSTEM_PROMPT

        # 生成给 LLM 的完整提示词（无论哪种模式都输出，方便用户连接外部 LLM 节点）
        prompt_for_llm = f"{system}\n\n剧本内容：\n{script_text}"

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
            return ([], 0, hint, prompt_for_llm)

        # ── 解析 JSON ────────────────────────────────────────
        shots = self._parse_json(raw)
        sequence_json = json.dumps(shots, ensure_ascii=False, indent=2)
        logger.info(f"解析完成：{len(shots)} 个分镜")
        return (shots, len(shots), sequence_json, prompt_for_llm)

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

    def _parse_json(self, raw: str) -> list:
        raw = raw.strip()
        # 去掉 markdown 代码块
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                if "[" in part:
                    raw = part
                    if raw.startswith("json"):
                        raw = raw[4:]
                    break
        # 找到 JSON 数组起始位置
        start = raw.find("[")
        end   = raw.rfind("]")
        if start == -1 or end == -1:
            raise ValueError(f"LLM 响应中未找到 JSON 数组，响应内容：{raw[:300]}")
        raw = raw[start:end+1]
        shots = json.loads(raw)
        if not isinstance(shots, list):
            raise ValueError("解析结果不是列表格式")
        return shots
