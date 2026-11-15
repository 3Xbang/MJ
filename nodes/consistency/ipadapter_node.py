import torch
import numpy as np
from PIL import Image
import os
from ai_film_editor_nodes.lib.utils.model_checker import get_model_list

class AFE_IPAdapterConfig:
    DESCRIPTION = "需要在工作流中安装 ComfyUI-IPAdapter-plus 节点包。本节点为配置节点，实际注入由 IPAdapterAdvanced 节点完成（连接方式见工作流模板）。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character": ("CHARACTER_ASSET",),
                "ipadapter_model": (get_model_list("ipadapter", "(未安装，ComfyUI Manager 搜索 ip-adapter-plus)"),),
                "clip_vision": (get_model_list("clip_vision", "(未安装，ComfyUI Manager 搜索 clip vision h)"),),
                "weight": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.0, "step": 0.05}),
                "weight_type": (["original", "linear", "channel penalty"],),
            },
            "optional": {
                "reference_image": ("IMAGE",),
                "noise": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0}),
            },
        }

    RETURN_TYPES = ("AFE_IPADAPTER_CONFIG",)
    RETURN_NAMES = ("ipadapter_config",)
    FUNCTION = "build_config"
    CATEGORY = "AI Film Editor/Consistency"

    def build_config(self, character, ipadapter_model, clip_vision, weight, weight_type, reference_image=None, noise=0.0):
        ref_tensor = None
        if reference_image is not None:
            ref_tensor = reference_image
        else:
            views = character.get("views", []) if isinstance(character, dict) else []
            selected_view = None
            for v in views:
                if v.get("is_primary", False) and v.get("image_path"):
                    selected_view = v
                    break
            if selected_view is None:
                for v in views:
                    if v.get("image_path"):
                        selected_view = v
                        break
            if selected_view is not None:
                try:
                    img = Image.open(selected_view["image_path"]).convert("RGB")
                    arr = np.array(img).astype(np.float32) / 255.0
                    ref_tensor = torch.from_numpy(arr).unsqueeze(0)  # [1,H,W,3]
                except Exception as e:
                    print(f"[AFE_IPAdapterConfig] Warning: could not load image {selected_view['image_path']}: {e}")
            else:
                print("[AFE_IPAdapterConfig] Warning: character has no view images; returning empty config.")
        config = {
            "weight": weight,
            "weight_type": weight_type,
            "noise": noise,
            "reference_image_tensor": ref_tensor,
            "ipadapter_model": ipadapter_model,
            "clip_vision": clip_vision,
        }
        return (config,)
