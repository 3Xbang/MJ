from __future__ import annotations
import torch
import torch.nn.functional as F
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_VideoUpscaler")


class AFE_VideoUpscaler:
    """
    Basic video upscaling via interpolation (no AI model required).
    For AI super-resolution, chain a Real-ESRGAN or BSRGAN node after this one.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "scale_factor": (["2x", "4x"],),
                "upscale_method": (["nearest-exact", "bilinear", "bicubic", "lanczos"],),
                "enable": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("upscaled_images",)
    FUNCTION = "upscale_video"
    CATEGORY = "AI Film Editor/Refinement"
    DESCRIPTION = (
        "Basic interpolation upscaling. Chain ComfyUI-Real-ESRGAN or ComfyUI-BSRGAN "
        "after this node for AI-based super-resolution."
    )

    # Map our labels to torch interpolation modes
    _MODE_MAP = {
        "nearest-exact": "nearest-exact",
        "bilinear": "bilinear",
        "bicubic": "bicubic",
        "lanczos": "bilinear",   # torch has no lanczos; bilinear is a reasonable proxy
    }

    def upscale_video(self, images, scale_factor="2x", upscale_method="bicubic", enable=True):
        if not enable:
            return (images,)

        scale = 2 if scale_factor == "2x" else 4
        mode = self._MODE_MAP.get(upscale_method, "bicubic")
        if upscale_method == "lanczos":
            logger.warning(
                "PyTorch does not support Lanczos interpolation; using bilinear as a proxy. "
                "For true Lanczos quality, use a PIL-based upscaler node instead."
            )
        align_corners = False if mode in ("bilinear", "bicubic") else None

        # images: (B, H, W, C) → permute to (B, C, H, W) for F.interpolate
        x = images.permute(0, 3, 1, 2).float()
        kwargs = {"scale_factor": float(scale), "mode": mode, "recompute_scale_factor": False}
        if align_corners is not None:
            kwargs["align_corners"] = align_corners
        upscaled = F.interpolate(x, **kwargs)
        # Back to (B, H, W, C)
        upscaled = upscaled.permute(0, 2, 3, 1).clamp(0.0, 1.0)
        return (upscaled,)
