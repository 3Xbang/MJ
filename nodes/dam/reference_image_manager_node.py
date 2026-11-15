from __future__ import annotations
import os
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ReferenceImageManager")


class AFE_ReferenceImageManager:
    """
    参考图管理节点。
    从各种资产中提取指定视角的参考图，
    统一输出为 IMAGE tensor。

    用于：
    - IP-Adapter（角色一致性）
    - WanImageToVideoLatent（I2V 初始帧）
    - AFE_ToneCompensation（色调参考）
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_type": (["character", "outfit", "scene", "props", "file_path"],),
            },
            "optional": {
                "character":    ("CHARACTER_ASSET",),
                "outfit":       ("OUTFIT_ASSET",),
                "scene":        ("SCENE_ASSET",),
                "props":        ("PROPS_ASSET",),
                "file_path":    ("STRING", {"default": ""}),
                "view_type":    (["primary", "front_full", "back_full", "left_side",
                                  "face_closeup", "half_body", "wide_shot", "medium_shot"],
                                {"default": "primary"}),
                "fallback_to_blank": ("BOOLEAN", {"default": True,
                                                  "tooltip": "True=图片不存在时返回空白图，False=报错"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "image_path")
    FUNCTION = "get_reference"
    CATEGORY = "AI Film Editor/Assets"

    def _resolve_path_from_asset(self, asset, view_type):
        """Return (path_str | None) from an asset dict's views list or primary_image_path."""
        if asset is None:
            return None
        a = asset if isinstance(asset, dict) else vars(asset)
        if view_type == "primary":
            p = a.get("primary_image_path", "")
            if p:
                return p
            # fall through to views list
        views = a.get("views", [])
        for v in views:
            vt = v.get("type", "") if isinstance(v, dict) else getattr(v, "type", "")
            vp = v.get("path", "") if isinstance(v, dict) else getattr(v, "path", "")
            if vt == view_type:
                return vp
        # fallback: first view or primary
        p = a.get("primary_image_path", "")
        if p:
            return p
        if views:
            first = views[0]
            return first.get("path", "") if isinstance(first, dict) else getattr(first, "path", "")
        return None

    def get_reference(self, source_type, character=None, outfit=None,
                      scene=None, props=None, file_path="",
                      view_type="primary", fallback_to_blank=True):
        import numpy as np
        import torch
        from PIL import Image

        # 1. Determine resolved path
        if source_type == "character":
            resolved = self._resolve_path_from_asset(character, view_type)
        elif source_type == "outfit":
            resolved = self._resolve_path_from_asset(outfit, view_type)
        elif source_type == "scene":
            resolved = self._resolve_path_from_asset(scene, view_type)
        elif source_type == "props":
            resolved = self._resolve_path_from_asset(props, view_type)
        else:  # file_path
            resolved = file_path.strip() or None

        # 2. Load image
        if resolved and os.path.isfile(resolved):
            try:
                img = Image.open(resolved).convert("RGB")
                arr = np.array(img).astype(np.float32) / 255.0
                tensor = torch.from_numpy(arr).unsqueeze(0)  # [1, H, W, 3]
                logger.info(f"ReferenceImageManager: loaded {resolved} shape={tensor.shape}")
                return (tensor, resolved)
            except Exception as e:
                logger.warning(f"ReferenceImageManager: failed to load '{resolved}': {e}")
                if not fallback_to_blank:
                    raise
                resolved = None
        else:
            if resolved:
                logger.warning(f"ReferenceImageManager: file not found: {resolved}")
            if not fallback_to_blank:
                raise FileNotFoundError(f"参考图不存在: {resolved}")

        # 3. Fallback blank
        blank = torch.zeros(1, 512, 512, 3, dtype=torch.float32)
        logger.info("ReferenceImageManager: returning blank 512x512 image")
        return (blank, "")
