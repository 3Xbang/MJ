import random
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_VideoModelAdapter")

CAMERA_MOTION_DESCRIPTIONS = {
    "static": "camera static",
    "pan_left": "camera slowly panning left",
    "pan_right": "camera slowly panning right",
    "zoom_in": "camera gradually zooming in",
    "zoom_out": "camera gradually zooming out",
    "tilt_up": "camera tilting upward",
    "tilt_down": "camera tilting downward",
    "orbit": "camera orbiting around subject",
}


class AFE_VideoModelAdapter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character": ("CHARACTER_ASSET",),
                "scene": ("SCENE_ASSET",),
                "shot_prompt": ("STRING", {"multiline": True, "default": ""}),
                "camera_motion": (["static", "pan_left", "pan_right", "zoom_in", "zoom_out", "tilt_up", "tilt_down", "orbit"],),
                "target_model": (["wan_i2v", "wan_t2v", "kling_i2v", "generic"],),
                "width": ("INT", {"default": 640, "min": 64, "max": 2048, "step": 8}),
                "height": ("INT", {"default": 360, "min": 64, "max": 2048, "step": 8}),
            },
            "optional": {
                "outfit": ("OUTFIT_ASSET",),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2**31 - 1}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "seed", "width", "height")
    FUNCTION = "adapt_for_model"
    CATEGORY = "AI Film Editor/Adapters"

    def adapt_for_model(self, character, scene, shot_prompt, camera_motion, target_model,
                        width, height, outfit=None, seed=-1, negative_prompt=""):
        char_pos = character.get("positive_prompt", "")
        char_neg = character.get("negative_prompt", "")
        scene_bg = scene.get("background_prompt", "")
        scene_neg = scene.get("negative_prompt", "")
        outfit_pos = outfit.get("outfit_prompt", "") if outfit else ""
        outfit_neg = outfit.get("negative_prompt", "") if outfit else ""

        parts = [p for p in [char_pos, outfit_pos, scene_bg, shot_prompt] if p.strip()]
        cam_desc = CAMERA_MOTION_DESCRIPTIONS.get(camera_motion, "camera static")

        if target_model in ("wan_i2v", "wan_t2v"):
            positive = ", ".join(parts)
            if cam_desc:
                positive = f"{positive}, {cam_desc}"
        elif target_model == "kling_i2v":
            positive = ", ".join(parts)
            positive = f"{positive}, {cam_desc}, high quality, 4K, cinematic, smooth motion"
        else:  # generic
            positive = " ".join(parts)
            if cam_desc:
                positive = f"{positive}, {cam_desc}"

        neg_parts = [p for p in [char_neg, outfit_neg, scene_neg, negative_prompt] if p.strip()]
        combined_negative = ", ".join(neg_parts)

        if seed == -1:
            char_seed = character.get("seed", -1)
            seed = char_seed if char_seed != -1 else random.randint(0, 2**31 - 1)

        logger.info(f"Adapted prompt for {target_model}: {positive[:80]}...")
        return (positive, combined_negative, seed, width, height)
