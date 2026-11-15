import random
from ai_film_editor_nodes.lib.utils.logger import get_logger
from ai_film_editor_nodes.lib.utils.model_checker import get_model_list

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
                "shot_prompt": ("STRING", {"multiline": True, "default": ""}),
                "camera_motion": (["static", "pan_left", "pan_right", "zoom_in", "zoom_out", "tilt_up", "tilt_down", "orbit"],),
                "video_model": (get_model_list("diffusion_models", "(未安装视频模型，ComfyUI Manager 搜索 Wan2.1 I2V)"),),
                "width": ("INT", {"default": 640, "min": 64, "max": 2048, "step": 8}),
                "height": ("INT", {"default": 360, "min": 64, "max": 2048, "step": 8}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2**31 - 1}),
            },
            "optional": {
                "outfit": ("OUTFIT_ASSET",),
                "scene": ("SCENE_ASSET",),
                "props": ("PROPS_ASSET",),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "seed", "width", "height")
    FUNCTION = "adapt_for_model"
    CATEGORY = "AI Film Editor/Adapters"

    def _detect_model_type(self, model_filename: str) -> str:
        name = model_filename.lower()
        if "wan" in name and "i2v" in name:
            return "wan_i2v"
        if "wan" in name and "t2v" in name:
            return "wan_t2v"
        if "kling" in name:
            return "kling"
        return "generic"

    def adapt_for_model(self, character, shot_prompt, camera_motion, video_model,
                        width, height, seed, scene=None, outfit=None, props=None, negative_prompt=""):
        target_model = self._detect_model_type(video_model)
        char_pos = character.get("positive_prompt", "")
        char_neg = character.get("negative_prompt", "")
        outfit_pos = outfit.get("outfit_prompt", "") if outfit else ""
        outfit_neg = outfit.get("negative_prompt", "") if outfit else ""

        scene_bg = scene.get("background_prompt", "") if scene else ""
        scene_neg = scene.get("negative_prompt", "") if scene else ""

        props_pos = props.get("positive_prompt", "") if props else ""

        parts = [p for p in [char_pos, outfit_pos, scene_bg, props_pos, shot_prompt] if p.strip()]
        cam_desc = CAMERA_MOTION_DESCRIPTIONS.get(camera_motion, "camera static")

        if target_model in ("wan_i2v", "wan_t2v"):
            positive = ", ".join(parts)
            if cam_desc:
                positive = f"{positive}, {cam_desc}"
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
