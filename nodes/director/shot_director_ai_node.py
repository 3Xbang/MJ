from __future__ import annotations
import copy
import json
import requests
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotDirectorAI")

DIRECTOR_SYSTEM_PROMPT = '''
你是一位获奖电影摄影师和导演，精通好莱坞电影制作技巧。
对于给定的分镜描述，请提供专业的导演指导意见。

返回 JSON 格式：
{
  "shot_id": "原始shot_id",
  "refined_shot_description": "优化后的英文画面描述（更专业的摄影语言）",
  "camera_setup": "具体摄像机设置（镜头焦距建议，如 85mm portrait lens）",
  "lighting_setup": "具体布光方案（3点布光/自然光/伦勃朗光等）",
  "color_grade_style": "调色风格（Teal and Orange / Film Noir / Golden Hour等）",
  "composition_notes": "构图要点（三分法/对称/引导线等）",
  "emotional_tone": "情绪基调和视觉传达目标",
  "technical_tips": "技术提示（景深、运动模糊、等）",
  "enhanced_prompt_en": "最终优化的英文生成提示词（直接给 Wan/Flux 用）",
  "enhanced_negative_en": "优化的负面提示词"
}

You are an award-winning cinematographer. Enhance the shot description with professional filmmaking guidance.
Return ONLY valid JSON.
'''


class AFE_ShotDirectorAI:
    """
    专业导演 AI 节点。对单个分镜提供专业摄影指导，输出优化提示词和导演报告。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
                "shot_id":       ("STRING", {"default": "shot_001"}),
                "llm_response":  ("STRING", {"default": ""}),
            },
            "optional": {
                "custom_director_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "留空=用专业导演提示词，填写=覆盖",
                }),
                "llm_api_key":  ("STRING", {"default": ""}),
                "llm_base_url": ("STRING", {"default": "https://api.deepseek.com/v1"}),
                "llm_model":    ("STRING", {"default": "deepseek-chat"}),
            },
        }

    RETURN_TYPES = ("SHOT_SEQUENCE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("enhanced_sequence", "enhanced_prompt", "enhanced_negative", "director_report")
    FUNCTION = "enhance_shot"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def enhance_shot(self, shot_sequence, shot_id, llm_response,
                     custom_director_prompt="", llm_api_key="",
                     llm_base_url="https://api.deepseek.com/v1",
                     llm_model="deepseek-chat"):

        def _get(d, key, default=""):
            return d.get(key, default) if isinstance(d, dict) else getattr(d, key, default)

        try:
            # 1. Find shot_data for given shot_id
            shot_data = None
            for s in shot_sequence:
                if _get(s, "shot_id", "") == shot_id:
                    shot_data = s
                    break

            if shot_data is None:
                raise ValueError(f"shot_id '{shot_id}' not found in sequence")

            # 2. Build user message dict
            user_message = {
                "shot_id":          shot_id,
                "shot_description": _get(shot_data, "shot_description", ""),
                "camera_motion":    str(_get(shot_data, "camera_motion", "static")),
                "scene_name":       _get(shot_data, "scene_name", ""),
                "director_notes":   _get(shot_data, "director_notes", ""),
            }

            # 3. Get result from LLM response or API call
            if llm_response.strip():
                raw = llm_response.strip()
                # Strip markdown code fences
                if "```" in raw:
                    for part in raw.split("```"):
                        if "{" in part:
                            raw = part
                            if raw.startswith("json"):
                                raw = raw[4:]
                            break
                result = json.loads(raw.strip())
            else:
                system_prompt = custom_director_prompt.strip() if custom_director_prompt.strip() else DIRECTOR_SYSTEM_PROMPT
                headers = {
                    "Authorization": f"Bearer {llm_api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": llm_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(user_message, ensure_ascii=False)},
                    ],
                    "temperature": 0.3,
                }
                resp = requests.post(
                    llm_base_url.rstrip("/") + "/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                # Strip markdown code fences
                if "```" in content:
                    for part in content.split("```"):
                        if "{" in part:
                            content = part
                            if content.startswith("json"):
                                content = content[4:]
                            break
                result = json.loads(content.strip())

            # 4. Extract key fields
            enhanced_prompt_en = result.get("enhanced_prompt_en", "")
            enhanced_negative_en = result.get("enhanced_negative_en", "")

            # 5. Deep copy sequence and update matching shot
            enhanced_sequence = copy.deepcopy(shot_sequence)
            for s in enhanced_sequence:
                if _get(s, "shot_id", "") == shot_id:
                    if isinstance(s, dict):
                        s["shot_description"] = enhanced_prompt_en
                        s["negative_prompt"] = enhanced_negative_en
                    else:
                        s.shot_description = enhanced_prompt_en
                        if hasattr(s, "negative_prompt"):
                            s.negative_prompt = enhanced_negative_en
                    break

            # 6. Format director report
            director_report = (
                f"=== Director Report: {shot_id} ===\n"
                f"📷 Camera: {result.get('camera_setup', '')}\n"
                f"💡 Lighting: {result.get('lighting_setup', '')}\n"
                f"🎨 Color Grade: {result.get('color_grade_style', '')}\n"
                f"📐 Composition: {result.get('composition_notes', '')}\n"
                f"🎭 Emotional Tone: {result.get('emotional_tone', '')}\n"
                f"⚙️ Technical Tips: {result.get('technical_tips', '')}\n"
                f"✅ Enhanced Prompt:\n{enhanced_prompt_en}"
            )

            logger.info(f"ShotDirectorAI: {shot_id} enhanced successfully")
            return (enhanced_sequence, enhanced_prompt_en, enhanced_negative_en, director_report)

        except Exception as e:
            logger.error(f"ShotDirectorAI error: {e}")
            return (shot_sequence, "", "", f"Error: {e}")
