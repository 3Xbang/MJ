from __future__ import annotations

VIEW_PROMPTS = {
    "front_full":   "front view, full body, standing pose, character sheet",
    "back_full":    "back view, full body, standing pose, character sheet",
    "left_side":    "left side view, full body, standing pose, character sheet",
    "right_side":   "right side view, full body, standing pose, character sheet",
    "face_closeup": "close-up portrait, face detail, expression neutral, high detail",
    "half_body":    "medium shot, upper body, three-quarter view",
    "action_pose":  "dynamic action pose, full body, motion blur",
}

STANDARD_NEGATIVE = (
    "deformed, blurry, bad anatomy, disfigured, poorly drawn face, mutation, mutated, "
    "extra limb, ugly, poorly drawn hands, missing limb, floating limbs, disconnected limbs, "
    "malformed hands, out of focus, long neck, long body"
)


class AFE_CharacterViewPrompt:
    """
    角色视图提示词生成节点。根据角色资产和视图类型生成标准化的生成提示词。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character": ("CHARACTER_ASSET",),
                "view_type": (list(VIEW_PROMPTS.keys()),),
            },
            "optional": {
                "outfit": ("OUTFIT_ASSET",),
                "custom_pose": ("STRING", {
                    "default": "",
                    "tooltip": "自定义动作描述（英文）",
                }),
                "style_suffix": ("STRING", {
                    "default": "photorealistic, 8K, studio lighting, white background",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt")
    FUNCTION = "build_view_prompt"
    CATEGORY = "AI Film Editor/Assets"

    def build_view_prompt(self, character, view_type, outfit=None, custom_pose="",
                          style_suffix="photorealistic, 8K, studio lighting, white background"):

        def _get(d, key, default=""):
            return d.get(key, default) if isinstance(d, dict) else getattr(d, key, default)

        char_appearance = (
            _get(character, "appearance_description_en", "")
            or _get(character, "positive_prompt", "")
        )

        outfit_desc = ""
        if outfit is not None:
            outfit_desc = _get(outfit, "outfit_prompt", "")

        view_prefix = VIEW_PROMPTS.get(view_type, "")
        parts = [p for p in [char_appearance, outfit_desc, view_prefix, custom_pose, style_suffix] if p]
        positive_prompt = ", ".join(parts)

        return (positive_prompt, STANDARD_NEGATIVE)
