from __future__ import annotations
import torch
from PIL import Image
import numpy as np


class AFE_SecondPassAdapter:
    """Rescale a frame batch and unpack refinement config parameters for KSamplerAdvanced."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "config": ("REFINEMENT_CONFIG",),
            },
            "optional": {
                "positive_prompt": ("STRING", {"default": "", "multiline": True}),
                "negative_prompt": ("STRING", {"default": "", "multiline": True}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT", "FLOAT", "INT", "FLOAT", "STRING", "STRING")
    RETURN_NAMES = ("images_scaled", "width", "height", "denoise", "steps", "cfg", "positive", "negative")
    FUNCTION = "prepare_second_pass"
    CATEGORY = "AI Film Editor/Refinement"

    def prepare_second_pass(self, images, config, positive_prompt="", negative_prompt=""):
        target_w = config["target_width"]
        target_h = config["target_height"]

        # images: (B, H, W, C) float32 tensor in [0, 1]
        scaled_frames = []
        for i in range(images.shape[0]):
            frame_np = (images[i].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
            pil_img = Image.fromarray(frame_np)
            pil_resized = pil_img.resize((target_w, target_h), Image.LANCZOS)
            scaled_frames.append(torch.from_numpy(np.array(pil_resized).astype(np.float32) / 255.0))

        scaled_tensor = torch.stack(scaled_frames)  # (B, target_h, target_w, C)

        return (
            scaled_tensor,
            target_w,
            target_h,
            config["denoise_strength"],
            config["steps"],
            config["cfg_scale"],
            positive_prompt,
            negative_prompt,
        )
