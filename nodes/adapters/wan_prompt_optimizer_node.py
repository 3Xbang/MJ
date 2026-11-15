from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_WanPromptOptimizer")

WAN_SYSTEM_PROMPT = """You are an expert at writing prompts for Wan 2.1 video generation model.

Wan 2.1 prompt best practices:
1. Start with the SUBJECT and their ACTION (not camera)
2. Describe movement and motion explicitly
3. Include: character appearance + action + environment + lighting + mood
4. Keep under 150 tokens
5. Use simple, visual language
6. Good: "A young woman in a black suit walks slowly down a neon street at night, looking at her phone, worried expression, city lights reflecting on wet pavement"
7. Bad: "Medium shot, low angle, slow push in, cinematic depth of field..."

Format: single paragraph, no line breaks, English only.
Return ONLY the optimized prompt, no explanation."""


class AFE_WanPromptOptimizer:
    """
    Wan 2.1 专用提示词优化器。
    将通用的 shot_description 重新格式化为 Wan 最优格式。
    可选：通过 LLM API 进一步优化，或直接使用规则优化。
    """

    WAN_DEFAULT_NEGATIVE = "ugly, deformed, disfigured, blurry, low quality, watermark, text overlay, duplicate, extra limbs, bad anatomy, worst quality"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence":  ("SHOT_SEQUENCE",),
                "shot_id":        ("STRING", {"default": "shot_001"}),
                "optimization_mode": (["rule_based", "llm_enhanced"],
                                     {"default": "rule_based",
                                      "tooltip": "rule_based=快速规则优化（无需LLM），llm_enhanced=LLM深度优化"}),
            },
            "optional": {
                "character":      ("CHARACTER_ASSET",),
                "outfit":         ("OUTFIT_ASSET",),
                "scene":          ("SCENE_ASSET",),
                "llm_api_key":    ("STRING", {"default": ""}),
                "llm_base_url":   ("STRING", {"default": "https://api.deepseek.com/v1"}),
                "manual_override": ("STRING", {"multiline": True, "default": "",
                                              "tooltip": "留空=自动生成，填写=直接使用此提示词"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("wan_positive", "wan_negative", "optimization_report")
    FUNCTION = "optimize_prompt"
    CATEGORY = "AI Film Editor/Adapters"
    OUTPUT_NODE = True

    def optimize_prompt(self, shot_sequence, shot_id, optimization_mode="rule_based",
                        character=None, outfit=None, scene=None,
                        llm_api_key="", llm_base_url="", manual_override=""):
        # --- helpers ---
        def _get(d, key, default=""):
            return d.get(key, default) if isinstance(d, dict) else getattr(d, key, default)

        # 1. Find shot
        shot_data = {}
        if shot_sequence:
            for s in shot_sequence:
                if _get(s, "shot_id", "") == shot_id:
                    shot_data = s
                    break
            if not shot_data:
                logger.warning(f"WanPromptOptimizer: shot_id '{shot_id}' not found")

        original_desc = _get(shot_data, "shot_description", "") or _get(shot_data, "shot_prompt", "")
        wan_negative   = _get(shot_data, "negative_prompt", "") or self.WAN_DEFAULT_NEGATIVE

        # 2. manual_override takes priority
        if manual_override.strip():
            report = f"模式: manual_override\n输入: {original_desc}\n输出: {manual_override.strip()}"
            return (manual_override.strip(), wan_negative, report)

        # 3. rule_based
        def _asset(a, key):
            if a is None: return ""
            return a.get(key, "") if isinstance(a, dict) else getattr(a, key, "")

        char_desc    = _asset(character, "appearance_description_en")
        outfit_desc  = _asset(outfit, "outfit_prompt") or _get(shot_data, "costume_per_character", {}).get("default", "") if outfit else ""
        scene_desc   = _asset(scene, "background_prompt") or _get(shot_data, "scene_name", "")
        lighting     = _get(shot_data, "lighting_style", "")
        action_desc  = original_desc

        parts = []
        if char_desc: parts.append(char_desc)
        if outfit_desc: parts.append(f"wearing {outfit_desc}")
        if action_desc: parts.append(action_desc)
        if scene_desc: parts.append(scene_desc)
        if lighting: parts.append(lighting)

        rule_result = ", ".join(p for p in parts if p)
        # truncate to 150 tokens
        words = rule_result.split()
        if len(words) > 150:
            rule_result = " ".join(words[:150])

        if optimization_mode == "rule_based" or not llm_api_key.strip():
            report = (f"模式: rule_based\n"
                      f"原始描述: {original_desc}\n"
                      f"优化后: {rule_result}\n"
                      f"Tokens: {len(rule_result.split())}")
            return (rule_result, wan_negative, report)

        # 4. llm_enhanced
        try:
            import urllib.request
            payload = json.dumps({
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": WAN_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Original description: {original_desc}\nCharacter: {char_desc}\nOutfit: {outfit_desc}\nScene: {scene_desc}"}
                ],
                "max_tokens": 200,
                "temperature": 0.7,
            }).encode()
            req = urllib.request.Request(
                f"{llm_base_url.rstrip('/')}/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {llm_api_key}"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            llm_result = data["choices"][0]["message"]["content"].strip()
            report = (f"模式: llm_enhanced\n"
                      f"原始描述: {original_desc}\n"
                      f"优化后: {llm_result}\n"
                      f"Tokens: {len(llm_result.split())}")
            return (llm_result, wan_negative, report)
        except Exception as e:
            logger.warning(f"LLM API failed, falling back to rule_based: {e}")
            report = (f"模式: llm_enhanced→rule_based(fallback, {e})\n"
                      f"原始描述: {original_desc}\n"
                      f"优化后: {rule_result}\n"
                      f"Tokens: {len(rule_result.split())}")
            return (rule_result, wan_negative, report)
