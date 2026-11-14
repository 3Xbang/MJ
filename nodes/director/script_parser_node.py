import json
import asyncio
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ScriptParser")


class AFE_ScriptParser:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "script_text": ("STRING", {"multiline": True, "default": ""}),
                "llm_api_key": ("STRING", {"default": ""}),
                "llm_base_url": ("STRING", {"default": "https://api.openai.com/v1"}),
                "llm_model": ("STRING", {"default": "gpt-4o-mini"}),
            },
            "optional": {
                "available_characters": ("STRING", {"default": ""}),
                "available_scenes": ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("SHOT_SEQUENCE", "INT", "STRING")
    RETURN_NAMES = ("shot_sequence", "shot_count", "sequence_json")
    FUNCTION = "parse_script"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def parse_script(self, script_text, llm_api_key, llm_base_url, llm_model,
                     available_characters="", available_scenes=""):
        if not llm_api_key.strip():
            raise ValueError("AFE_ScriptParser: llm_api_key is required")
        if not script_text.strip():
            raise ValueError("AFE_ScriptParser: script_text cannot be empty")

        chars_hint = f" Available characters: {available_characters}." if available_characters else ""
        scenes_hint = f" Available scenes: {available_scenes}." if available_scenes else ""

        system_prompt = (
            "You are a film production assistant. Parse the provided film script into a structured list of shots. "
            "Return a JSON array where each element has these fields: "
            "shot_id (string, sequential like 'shot_001'), label (string, short description), "
            "description (string, visual description of the shot), "
            "character_names (array of strings), scene_name (string), "
            "camera_motion (one of: static, pan_left, pan_right, zoom_in, zoom_out, tilt_up, tilt_down, orbit), "
            "duration_hint (float seconds, estimate). "
            f"{chars_hint}{scenes_hint}"
            " Return ONLY the JSON array, no markdown, no explanation."
        )

        async def _call_llm():
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=llm_api_key, base_url=llm_base_url)
            response = await client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": script_text},
                ],
                temperature=0.3,
            )
            return response.choices[0].message.content

        raw = asyncio.run(_call_llm())
        shots = json.loads(raw)
        if not isinstance(shots, list):
            raise ValueError(f"AFE_ScriptParser: LLM returned unexpected format: {raw[:200]}")
        sequence_json = json.dumps(shots, ensure_ascii=False, indent=2)
        logger.info(f"Parsed {len(shots)} shots from script")
        return (shots, len(shots), sequence_json)
