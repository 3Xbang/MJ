import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ScriptParser")

SYSTEM_PROMPT_TEMPLATE = """你是一位专业影视分镜师。请将以下剧本解析为结构化分镜列表。

要求：
- 返回 JSON 数组格式
- 每个分镜包含：shot_id, label, description, character_names, scene_name, camera_motion, duration_hint
- camera_motion 只能是：static, pan_left, pan_right, zoom_in, zoom_out, tilt_up, tilt_down, orbit
- duration_hint 单位为秒
- 只返回 JSON，不要有其他文字

剧本内容：
{script_text}
{chars_hint}{scenes_hint}"""


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
                    "default": "在这里输入剧本内容..."
                }),
            },
            "optional": {
                # ── 用法1：接收外部 LLM 节点的输出 ──
                "llm_response": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "连接 ComfyUI-LLM-Party 等 LLM 节点的输出"
                }),

                # ── 用法2：直接调用 API（不连接 LLM 节点时使用）──
                "llm_api_key":  ("STRING", {"default": ""}),
                "llm_base_url": ("STRING", {"default": "https://api.deepseek.com/v1"}),
                "llm_model":    ("STRING", {"default": "deepseek-chat"}),

                # ── 上下文提示 ──
                "available_characters": ("STRING", {"default": ""}),
                "available_scenes":     ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("SHOT_SEQUENCE", "INT", "STRING", "STRING")
    RETURN_NAMES = ("shot_sequence", "shot_count", "sequence_json", "prompt_for_llm")
    FUNCTION = "parse_script"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def parse_script(self, script_text,
                     llm_response="", llm_api_key="",
                     llm_base_url="https://api.deepseek.com/v1",
                     llm_model="deepseek-chat",
                     available_characters="", available_scenes=""):

        if not script_text.strip():
            raise ValueError("script_text 不能为空")

        chars_hint  = f"\n可用角色：{available_characters}" if available_characters.strip() else ""
        scenes_hint = f"\n可用场景：{available_scenes}"   if available_scenes.strip()     else ""

        # 生成给 LLM 的提示词（无论哪种模式都输出，方便用户连接外部 LLM 节点）
        prompt_for_llm = SYSTEM_PROMPT_TEMPLATE.format(
            script_text=script_text,
            chars_hint=chars_hint,
            scenes_hint=scenes_hint,
        )

        # ── 决定使用哪个 LLM 响应 ──────────────────────────
        if llm_response.strip():
            # 用法1：使用外部 LLM 节点传入的响应
            raw = llm_response
            logger.info("使用外部 LLM 节点的响应")

        elif llm_api_key.strip():
            # 用法2：直接调用 API
            raw = self._call_api(prompt_for_llm, llm_api_key, llm_base_url, llm_model)
            logger.info(f"使用 API 模式：{llm_base_url}")

        else:
            # 两种都没有：输出提示词供用户复制到 LLM 节点
            hint = (
                "⚠️ 请选择以下任一方式：\n"
                "方式1：安装 ComfyUI-LLM-Party，把 LLM 节点的输出连接到 llm_response 输入\n"
                "方式2：在 llm_api_key 填入 DeepSeek API Key\n\n"
                "下方是给 LLM 的提示词（可手动复制使用）：\n\n"
                + prompt_for_llm
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
