from __future__ import annotations
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ExpressionSheet")

VIEW_TYPE_MAP = {
    "面部特写": "face close-up portrait, upper face only",
    "半身": "half-body shot, from waist up",
    "全身": "full-body shot, standing",
}

EXPRESSION_MAP = {
    "喜悦": "joyful expression, bright smile, happy eyes, cheerful",
    "愤怒": "angry expression, furrowed brows, intense gaze, furious",
    "悲伤": "sad expression, downcast eyes, melancholy, sorrowful",
    "平静": "neutral expression, calm face, composed, serene",
    "惊讶": "surprised expression, wide eyes, open mouth, astonished",
    "恐惧": "fearful expression, wide frightened eyes, pale, terrified",
    "思考": "thoughtful expression, slightly furrowed brows, contemplative",
}

ALL_EXPRESSIONS = ["喜悦", "愤怒", "悲伤", "平静", "惊讶", "恐惧", "思考"]


class AFE_ExpressionSheet:
    """
    角色表情包生成配置节点。
    为指定角色生成多种表情的提示词组合，
    输出提示词供 KSampler 批量生成表情图。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character": ("CHARACTER_ASSET",),
                "expressions": (
                    ["全套(喜怒哀乐惊恐)", "喜悦", "愤怒", "悲伤", "平静", "惊讶", "恐惧", "思考", "自定义"],
                ),
            },
            "optional": {
                "custom_expression": ("STRING", {
                    "default": "",
                    "tooltip": "选择'自定义'时在此填写表情描述"
                }),
                "view_type": (["面部特写", "半身", "全身"],),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "expression_count")
    FUNCTION = "build_expression_prompts"
    CATEGORY = "AI Film Editor/Cast"

    def build_expression_prompts(self, character, expressions, custom_expression="", view_type="面部特写"):
        if isinstance(character, dict):
            appearance_en = character.get("appearance_description_en") or character.get("positive_prompt", "")
            char_name = character.get("name", "character")
        else:
            appearance_en = getattr(character, "appearance_description_en", "") or getattr(character, "positive_prompt", "")
            char_name = getattr(character, "name", "character")

        view_desc = VIEW_TYPE_MAP.get(view_type, "face close-up portrait")
        base = f"{appearance_en}, {view_desc}" if appearance_en else view_desc
        negative = "ugly, blurry, low quality, watermark, deformed, mutation, bad anatomy"

        if expressions == "全套(喜怒哀乐惊恐)":
            prompts = [f"{base}, {EXPRESSION_MAP[e]}" for e in ALL_EXPRESSIONS]
            combined = " | ".join(prompts)
            count = len(ALL_EXPRESSIONS)
        elif expressions == "自定义":
            expr_desc = custom_expression.strip() if custom_expression.strip() else "neutral expression"
            combined = f"{base}, {expr_desc}"
            count = 1
        else:
            expr_desc = EXPRESSION_MAP.get(expressions, "neutral expression")
            combined = f"{base}, {expr_desc}"
            count = 1

        logger.info(f"ExpressionSheet: {char_name}, {expressions}, {count} prompts")
        return (combined, negative, count)
