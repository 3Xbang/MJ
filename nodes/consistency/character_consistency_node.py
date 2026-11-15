"""角色一致性节点 — 自动从角色资产库加载主视图参考图，输出 IP-Adapter 配置参数。

需要安装 ComfyUI-IPAdapter-plus。
工作流连接方式：AFE_CharacterConsistency → (image, weight) → IPAdapterAdvanced
"""
from __future__ import annotations

import os

import numpy as np
import torch
from PIL import Image

from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger(__name__)


class AFE_CharacterConsistency:
    """角色一致性节点。

    自动从角色资产库加载主视图参考图，输出 IP-Adapter 配置参数。
    需要安装 ComfyUI-IPAdapter-plus。
    工作流连接方式：AFE_CharacterConsistency → (image, weight) → IPAdapterAdvanced
    """

    CATEGORY = "AI Film Editor/Consistency"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character": ("CHARACTER_ASSET",),
                "consistency_strength": (
                    "FLOAT",
                    {
                        "default": 0.6,
                        "min": 0.0,
                        "max": 1.0,
                        "step": 0.05,
                        "tooltip": "0=完全不一致，1=完全复制外貌，0.6=推荐平衡值",
                    },
                ),
            },
            "optional": {
                "reference_image": (
                    "IMAGE",
                    {"tooltip": "留空=自动用角色正面参考图，提供=用此图覆盖"},
                ),
                "weight_type": (
                    ["original", "linear", "channel penalty"],
                    {"default": "original"},
                ),
                "enable": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("IMAGE", "FLOAT", "STRING", "STRING")
    RETURN_NAMES = ("reference_image", "weight", "weight_type", "consistency_status")
    FUNCTION = "setup_consistency"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _blank_image() -> torch.Tensor:
        """Return a minimal blank image tensor with shape [1, 1, 1, 3]."""
        arr = np.zeros((1, 1, 3), dtype=np.float32)
        return torch.from_numpy(arr).unsqueeze(0)  # [1, 1, 1, 3]

    # ------------------------------------------------------------------
    # main
    # ------------------------------------------------------------------

    def setup_consistency(
        self,
        character,
        consistency_strength: float = 0.6,
        reference_image=None,
        weight_type: str = "original",
        enable: bool = True,
    ):
        blank = self._blank_image

        if not enable:
            return (blank(), 0.0, weight_type, "⏸️ 角色一致性：已禁用")

        # Resolve character name (supports dict or object)
        if isinstance(character, dict):
            char_name = character.get("name", "未知角色")
        else:
            char_name = getattr(character, "name", "未知角色")

        # If a custom reference image was provided, use it directly
        if reference_image is not None:
            return (
                reference_image,
                consistency_strength,
                weight_type,
                f"✅ 角色一致性：{char_name} | 参考图：自定义输入 | 强度：{consistency_strength}",
            )

        # Resolve views list
        if isinstance(character, dict):
            views = character.get("views", [])
        else:
            views = getattr(character, "views", [])

        # Find primary view first, then any view with an image_path
        primary_view = None
        fallback_view = None
        for v in views:
            img_path = v.get("image_path") if isinstance(v, dict) else getattr(v, "image_path", None)
            if not img_path:
                continue
            is_primary = v.get("is_primary", False) if isinstance(v, dict) else getattr(v, "is_primary", False)
            if is_primary and primary_view is None:
                primary_view = v
            if fallback_view is None:
                fallback_view = v

        chosen_view = primary_view or fallback_view

        if chosen_view is not None:
            if isinstance(chosen_view, dict):
                image_path = chosen_view.get("image_path")
                view_name = chosen_view.get("view_name", "front_full" if chosen_view is primary_view else "unknown")
            else:
                image_path = getattr(chosen_view, "image_path", None)
                view_name = getattr(chosen_view, "view_name", "front_full" if chosen_view is primary_view else "unknown")

            try:
                pil_img = Image.open(image_path).convert("RGB")
                arr = np.array(pil_img, dtype=np.float32) / 255.0  # [H, W, 3]
                tensor = torch.from_numpy(arr).unsqueeze(0)         # [1, H, W, 3]
                return (
                    tensor,
                    consistency_strength,
                    weight_type,
                    f"✅ 角色一致性：{char_name} | 参考图：{view_name} | 强度：{consistency_strength}",
                )
            except Exception as exc:
                logger.warning("角色一致性：无法加载参考图 %s — %s", image_path, exc)
                # fall through to "no image" path

        return (
            blank(),
            consistency_strength,
            weight_type,
            f"⚠️ 角色无参考图，请先生成角色视图 ({char_name})",
        )
