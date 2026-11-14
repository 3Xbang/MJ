import torch
import numpy as np


class AFE_ToneCompensation:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "current_image": ("IMAGE",),
                "strength": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05}),
            },
            "optional": {
                "reference_frame": ("IMAGE",),
                "enable": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("compensated_image",)
    FUNCTION = "apply_tone_compensation"
    CATEGORY = "AI Film Editor/Director"

    def apply_tone_compensation(self, current_image, strength, enable=True, reference_frame=None):
        if reference_frame is None or not enable:
            return (current_image,)
        # Both are (N, H, W, C) float32 tensors in [0, 1]
        ref_np = reference_frame.numpy()  # (N, H, W, C)
        cur_np = current_image.numpy()
        # Compute per-channel mean for the first (reference) frame
        ref_mean = ref_np[0].mean(axis=(0, 1))  # (C,)
        cur_mean = cur_np[0].mean(axis=(0, 1))  # (C,)
        delta = (ref_mean - cur_mean) * strength  # (C,)
        compensated = cur_np + delta[np.newaxis, np.newaxis, np.newaxis, :]  # broadcast
        compensated = np.clip(compensated, 0.0, 1.0)
        return (torch.from_numpy(compensated).to(current_image.dtype),)
