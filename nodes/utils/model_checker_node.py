"""AFE_ModelChecker node — displays model installation status in ComfyUI."""
from __future__ import annotations

from ai_film_editor_nodes.lib.utils.model_checker import check_requirement, MODEL_REQUIREMENTS
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ModelChecker")

VIDEO_KEYS = ["wan_i2v_model", "wan_t5_encoder", "wan_vae", "wan_clip_vision"]
IMAGE_KEYS = ["flux_checkpoint", "flux_t5"]
REFINE_KEYS = ["codeformer", "ipadapter_plus", "controlnet_openpose"]
MODE_KEYS: dict[str, list[str]] = {
    "全部检查": list(MODEL_REQUIREMENTS.keys()),
    "仅视频生成": VIDEO_KEYS,
    "仅图片生成": IMAGE_KEYS,
    "仅精修增强": REFINE_KEYS,
}


class AFE_ModelChecker:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "check_mode": (["全部检查", "仅视频生成", "仅图片生成", "仅精修增强"],),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status_report",)
    FUNCTION = "check_models"
    CATEGORY = "AI Film Editor/Utils"
    OUTPUT_NODE = True

    def check_models(self, check_mode: str):
        keys = MODE_KEYS.get(check_mode, list(MODEL_REQUIREMENTS.keys()))
        lines = [f"=== AFE 模型检查报告 [{check_mode}] ===\n"]
        for key in keys:
            req = MODEL_REQUIREMENTS[key]
            installed, msg = check_requirement(key)
            if installed:
                lines.append(f"✅ {req['description']}\n   文件: {msg}")
            else:
                lines.append(
                    f"❌ {req['description']}\n"
                    f"   ComfyUI Manager 搜索: \"{req['manager_search']}\""
                )
        installed_count = sum(1 for k in keys if check_requirement(k)[0])
        lines.append(f"\n已安装: {installed_count}/{len(keys)}")
        report = "\n".join(lines)
        logger.info(f"Model check [{check_mode}]: {installed_count}/{len(keys)} installed")
        return {"ui": {"text": [report]}, "result": (report,)}
