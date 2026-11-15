from __future__ import annotations
import random
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotUnit")


class AFE_ShotUnit:
    """
    单分镜控制器。将分镜数据与资产绑定，输出标准化的渲染配置。
    支持一采/二采/三采三个独立阶段。每个分镜独立运行，可单独重新生成。
    """

    PASS_CONFIG = {
        "first_pass_640x360":   {"width": 640,  "height": 360,  "frames": 124},
        "second_pass_1280x720": {"width": 1280, "height": 720,  "frames": 248},
        "third_pass_1920x1080": {"width": 1920, "height": 1080, "frames": 248},
    }
    PASS_LABELS = {
        "first_pass_640x360":   "一采",
        "second_pass_1280x720": "二采",
        "third_pass_1920x1080": "三采",
    }

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_id":       ("STRING", {"default": "shot_001"}),
                "shot_sequence": ("SHOT_SEQUENCE",),
                "render_pass":   (["first_pass_640x360", "second_pass_1280x720", "third_pass_1920x1080"],),
            },
            "optional": {
                "character":       ("CHARACTER_ASSET",),
                "scene":           ("SCENE_ASSET",),
                "outfit":          ("OUTFIT_ASSET",),
                "props":           ("PROPS_ASSET",),
                "tail_frame":      ("IMAGE",),
                "override_prompt": ("STRING", {"default": "", "tooltip": "留空=用分镜原始提示词，填写=覆盖"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "INT", "INT", "INT", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "seed", "width", "height", "frame_count", "shot_label")
    FUNCTION = "prepare_shot"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def prepare_shot(self, shot_id, shot_sequence, render_pass,
                     character=None, scene=None, outfit=None, props=None,
                     tail_frame=None, override_prompt=""):
        cfg = self.PASS_CONFIG[render_pass]
        pass_label = self.PASS_LABELS[render_pass]

        shot_data = {}
        if shot_sequence:
            for s in shot_sequence:
                sid = s.get("shot_id", "") if isinstance(s, dict) else getattr(s, "shot_id", "")
                if sid == shot_id:
                    shot_data = s
                    break
            else:
                logger.warning(f"ShotUnit: shot_id '{shot_id}' not found in sequence of {len(shot_sequence)} shots")

        def _get(d, key, default=""):
            return d.get(key, default) if isinstance(d, dict) else getattr(d, key, default)

        shot_description = _get(shot_data, "shot_description", "")
        shot_prompt_fb   = _get(shot_data, "shot_prompt", "")
        negative_prompt  = _get(shot_data, "negative_prompt", "ugly, blurry, low quality, watermark")
        camera_motion    = _get(shot_data, "camera_motion", "static")
        director_notes   = _get(shot_data, "director_notes", "")
        label            = _get(shot_data, "label", shot_id)
        duration_sec     = _get(shot_data, "duration_seconds", 5.0)

        base = shot_description or shot_prompt_fb or "cinematic shot"

        def _asset_prompt(asset, key):
            if asset is None:
                return ""
            return asset.get(key, "") if isinstance(asset, dict) else getattr(asset, key, "")

        asset_parts = [p for p in [
            _asset_prompt(character, "positive_prompt"),
            _asset_prompt(outfit, "outfit_prompt"),
            _asset_prompt(scene, "background_prompt"),
            _asset_prompt(props, "positive_prompt"),
        ] if p]

        if override_prompt.strip():
            positive_prompt = override_prompt.strip()
        else:
            parts = [base] + asset_parts
            if camera_motion and camera_motion != "static":
                parts.append(f"camera motion: {camera_motion}")
            if director_notes:
                parts.append(f"({director_notes})")
            positive_prompt = ", ".join(p for p in parts if p)

        seed = random.randint(0, 2**31 - 1)
        shot_label = f"{label} | {pass_label} | {cfg['width']}×{cfg['height']} | {duration_sec}秒"
        logger.info(f"ShotUnit: {shot_id} → {pass_label} {cfg['width']}×{cfg['height']}")
        return (
            positive_prompt,
            negative_prompt,
            seed,
            cfg["width"],
            cfg["height"],
            cfg["frames"],
            shot_label,
        )
