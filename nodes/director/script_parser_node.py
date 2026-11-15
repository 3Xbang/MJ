import json
import asyncio
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ScriptParser")

SYSTEM_PROMPT = (
    "You are a film production assistant. Parse the provided film script into a structured list of shots. "
    "Return a JSON array where each element has these fields: "
    "shot_id (string, sequential like 'shot_001'), label (string, short description), "
    "description (string, visual description of the shot), "
    "character_names (array of strings), scene_name (string), "
    "camera_motion (one of: static, pan_left, pan_right, zoom_in, zoom_out, tilt_up, tilt_down, orbit), "
    "duration_hint (float seconds, estimate). "
    "Return ONLY the JSON array, no markdown, no explanation."
)


class AFE_ScriptParser:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "script_text": ("STRING", {"multiline": True, "default": "在这里输入剧本..."}),
                "mode": (["api", "local_transformers"],),
            },
            "optional": {
                # API 模式
                "llm_api_key":  ("STRING", {"default": ""}),
                "llm_base_url": ("STRING", {"default": "https://api.deepseek.com/v1"}),
                "llm_model":    ("STRING", {"default": "deepseek-chat"}),
                # 本地模式
                "local_model_name": ("STRING", {"default": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"}),
                # 可选上下文
                "available_characters": ("STRING", {"default": ""}),
                "available_scenes":     ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("SHOT_SEQUENCE", "INT", "STRING")
    RETURN_NAMES = ("shot_sequence", "shot_count", "sequence_json")
    FUNCTION = "parse_script"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    # 缓存本地模型，避免重复加载
    _local_pipeline = None
    _loaded_model_name = None

    def parse_script(self, script_text, mode,
                     llm_api_key="", llm_base_url="https://api.deepseek.com/v1",
                     llm_model="deepseek-chat", local_model_name="deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
                     available_characters="", available_scenes=""):

        if not script_text.strip():
            raise ValueError("script_text 不能为空")

        chars_hint  = f" 可用角色：{available_characters}。" if available_characters.strip() else ""
        scenes_hint = f" 可用场景：{available_scenes}。" if available_scenes.strip() else ""
        system = SYSTEM_PROMPT + chars_hint + scenes_hint

        if mode == "api":
            raw = self._call_api(script_text, system, llm_api_key, llm_base_url, llm_model)
        else:
            raw = self._call_local(script_text, system, local_model_name)

        # 解析 JSON（兼容 LLM 返回 markdown 代码块的情况）
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        bracket = raw.find("[")
        if bracket > 0:
            raw = raw[bracket:]

        shots = json.loads(raw)
        if not isinstance(shots, list):
            raise ValueError(f"LLM 返回格式错误: {raw[:200]}")

        sequence_json = json.dumps(shots, ensure_ascii=False, indent=2)
        logger.info(f"解析完成：{len(shots)} 个分镜")
        return (shots, len(shots), sequence_json)

    # ── API 模式 ──────────────────────────────────────────
    def _call_api(self, script_text, system, api_key, base_url, model):
        if not api_key.strip():
            raise ValueError("API 模式需要填写 llm_api_key（DeepSeek / OpenAI 等）")

        async def _call():
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": script_text},
                ],
                temperature=0.3,
                timeout=60,
            )
            return resp.choices[0].message.content

        return asyncio.run(_call())

    # ── 本地 transformers 模式 ────────────────────────────
    def _call_local(self, script_text, system, model_name):
        """
        直接用 transformers pipeline 在本地 GPU 推理。
        第一次调用会从 HuggingFace 下载模型（约 15GB），之后缓存复用。
        """
        import torch
        from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM

        # 加载模型（缓存复用）
        if AFE_ScriptParser._loaded_model_name != model_name:
            logger.info(f"加载本地模型：{model_name}（首次加载需要下载，请耐心等待）")
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype=torch.float16,
                device_map="auto",
            )
            AFE_ScriptParser._local_pipeline = pipeline(
                "text-generation",
                model=model,
                tokenizer=tokenizer,
            )
            AFE_ScriptParser._loaded_model_name = model_name
            logger.info("本地模型加载完成")

        pipe = AFE_ScriptParser._local_pipeline
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": script_text},
        ]
        # 使用 chat template
        tokenizer = pipe.tokenizer
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        result = pipe(
            prompt,
            max_new_tokens=2048,
            temperature=0.3,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
        )
        generated = result[0]["generated_text"]
        # 只取新生成的部分
        if generated.startswith(prompt):
            generated = generated[len(prompt):]
        return generated
