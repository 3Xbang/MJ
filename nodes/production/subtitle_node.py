import torch
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import os
import glob
import platform

class AFE_SubtitleOverlay:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "subtitle_text": ("STRING", {"multiline": True}),
                "font_size": ("INT", {"default": 32, "min": 12, "max": 72}),
                "position": (["bottom_center", "bottom_left", "top_center", "middle_center"],),
                "text_color": ("STRING", {"default": "#FFFFFF"}),
                "background_opacity": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.0}),
            },
            "optional": {
                "font_path": ("STRING", {"default": ""}),
                "margin": ("INT", {"default": 20}),
                "line_spacing": ("INT", {"default": 8}),
                "enable": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "overlay_subtitles"
    CATEGORY = "AI Film Editor/Production"

    def _load_font(self, font_path, font_size):
        # Try provided path first
        if font_path:
            try:
                return ImageFont.truetype(font_path, font_size)
            except Exception:
                pass
        # Platform-specific system fonts
        candidates = []
        if platform.system() == "Windows":
            candidates = [
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/msyh.ttf",
                "C:/Windows/Fonts/arial.ttf",
            ]
        else:
            ttfs = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
            candidates = ttfs[:3]
        for path in candidates:
            try:
                return ImageFont.truetype(path, font_size)
            except Exception:
                continue
        print("[AFE_SubtitleOverlay] Warning: no TrueType font found, using default font (no Chinese support).")
        return ImageFont.load_default()

    def overlay_subtitles(self, images, subtitle_text, font_size, position, text_color,
                          background_opacity, font_path="", margin=20, line_spacing=8, enable=True):
        if not enable:
            return (images,)
        lines = [l.strip() for l in subtitle_text.split("\n") if l.strip()]
        if not lines:
            return (images,)

        font = self._load_font(font_path, font_size)
        num_frames = images.shape[0]
        num_lines = len(lines)
        frames_per_line = max(1, num_frames // num_lines)

        # Parse color
        tc = text_color.lstrip("#")
        try:
            r, g, b = int(tc[0:2],16), int(tc[2:4],16), int(tc[4:6],16)
        except Exception:
            r, g, b = 255, 255, 255

        result_frames = []
        for i in range(num_frames):
            line_idx = min(i // frames_per_line, num_lines - 1)
            text = lines[line_idx]

            frame_np = (images[i].numpy() * 255).astype(np.uint8)
            img_pil = Image.fromarray(frame_np, "RGB")
            W, H = img_pil.size

            # Measure text
            tmp_draw = ImageDraw.Draw(img_pil)
            try:
                bbox = tmp_draw.textbbox((0, 0), text, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            except AttributeError:
                tw, th = tmp_draw.textsize(text, font=font)

            # Compute position
            if position == "bottom_center":
                x, y = (W - tw) // 2, H - th - margin
            elif position == "bottom_left":
                x, y = margin, H - th - margin
            elif position == "top_center":
                x, y = (W - tw) // 2, margin
            else:  # middle_center
                x, y = (W - tw) // 2, (H - th) // 2

            # Draw background rect
            if background_opacity > 0:
                overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                od = ImageDraw.Draw(overlay)
                bg_alpha = int(background_opacity * 255)
                pad = 6
                od.rectangle([x - pad, y - pad, x + tw + pad, y + th + pad],
                             fill=(0, 0, 0, bg_alpha))
                img_rgba = img_pil.convert("RGBA")
                img_pil = Image.alpha_composite(img_rgba, overlay).convert("RGB")

            draw = ImageDraw.Draw(img_pil)
            draw.text((x, y), text, font=font, fill=(r, g, b))

            result_frames.append(torch.from_numpy(np.array(img_pil).astype(np.float32) / 255.0))

        return (torch.stack(result_frames, dim=0),)
