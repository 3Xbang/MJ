from __future__ import annotations
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_Watermark")


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return r, g, b


class AFE_Watermark:
    """Overlay a semi-transparent text watermark on every frame. Disabled by default."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "text": ("STRING", {"default": "AI Film Editor"}),
                "position": (["bottom_right", "bottom_left", "top_right", "top_left", "center"],),
                "opacity": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05}),
                "enable": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "font_size": ("INT", {"default": 24, "min": 12, "max": 72}),
                "text_color": ("STRING", {"default": "#FFFFFF"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "apply_watermark"
    CATEGORY = "AI Film Editor/Export"

    def apply_watermark(
        self, images, text="AI Film Editor", position="bottom_right",
        opacity=0.3, enable=False, font_size=24, text_color="#FFFFFF"
    ):
        if not enable:
            return (images,)

        try:
            r, g, b = _hex_to_rgb(text_color)
        except Exception:
            r, g, b = 255, 255, 255

        alpha = int(opacity * 255)
        fill_color = (r, g, b, alpha)

        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()

        result_frames = []
        for i in range(images.shape[0]):
            frame_np = (images[i].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
            pil_img = Image.fromarray(frame_np).convert("RGBA")
            w, h = pil_img.size

            overlay = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # Measure text
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            margin = 10

            if position == "bottom_right":
                xy = (w - tw - margin, h - th - margin)
            elif position == "bottom_left":
                xy = (margin, h - th - margin)
            elif position == "top_right":
                xy = (w - tw - margin, margin)
            elif position == "top_left":
                xy = (margin, margin)
            else:  # center
                xy = ((w - tw) // 2, (h - th) // 2)

            draw.text(xy, text, font=font, fill=fill_color)
            composited = Image.alpha_composite(pil_img, overlay).convert("RGB")
            result_frames.append(torch.from_numpy(np.array(composited).astype(np.float32) / 255.0))

        return (torch.stack(result_frames),)
