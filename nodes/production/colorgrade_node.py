import torch
import numpy as np

class AFE_ColorGrade:
    PRESETS = {
        "none":           (0.0,   0.0,  0.0,  0.0,  [1.0,  1.0,  1.0]),
        "cinematic_cool": (-0.05, 0.1, -0.2, -0.05, [0.9,  0.95, 1.1]),
        "cinematic_warm": (0.05, 0.05,  0.1,  0.05, [1.1,  1.0,  0.9]),
        "noir_bw":        (0.0,   0.2, -1.0,  0.0,  [1.0,  1.0,  1.0]),
        "golden_hour":    (0.1,  0.05,  0.3,  0.08, [1.15, 1.05, 0.85]),
        "neon_night":     (-0.1,  0.1,  0.4, -0.1,  [0.9,  1.0,  1.1]),
        "vintage":        (-0.05,-0.1, -0.3,  0.05, [1.05, 0.95, 0.85]),
        "clean_bright":   (0.1,   0.0,  0.1,  0.0,  [1.0,  1.0,  1.0]),
    }

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "preset": (["none","cinematic_cool","cinematic_warm","noir_bw",
                            "golden_hour","neon_night","vintage","clean_bright"],),
            },
            "optional": {
                "brightness": ("FLOAT", {"default": 0.0, "min": -0.5, "max": 0.5, "step": 0.01}),
                "contrast":   ("FLOAT", {"default": 0.0, "min": -0.5, "max": 0.5, "step": 0.01}),
                "saturation": ("FLOAT", {"default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01}),
                "hue_shift":  ("FLOAT", {"default": 0.0, "min": -0.5, "max": 0.5, "step": 0.01}),
                "vignette":   ("FLOAT", {"default": 0.0, "min": 0.0,  "max": 1.0}),
                "enable":     ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("graded_images",)
    FUNCTION = "apply_color_grade"
    CATEGORY = "AI Film Editor/Production"

    def apply_color_grade(self, images, preset, brightness=0.0, contrast=0.0,
                          saturation=0.0, hue_shift=0.0, vignette=0.0, enable=True):
        if not enable:
            return (images,)

        pb, pc, ps, ph, tint = self.PRESETS[preset]
        fb = pb + brightness
        fc = pc + contrast
        fs = ps + saturation
        fh = ph + hue_shift

        result = images.clone().float()

        # Apply color tint
        result[..., 0] = (result[..., 0] * tint[0]).clamp(0, 1)
        result[..., 1] = (result[..., 1] * tint[1]).clamp(0, 1)
        result[..., 2] = (result[..., 2] * tint[2]).clamp(0, 1)

        # Brightness
        result = (result + fb).clamp(0, 1)

        # Contrast
        result = ((result - 0.5) * (1.0 + fc * 2.0) + 0.5).clamp(0, 1)

        # Saturation
        if abs(fs) > 1e-6:
            gray = (0.299 * result[..., 0] + 0.587 * result[..., 1] + 0.114 * result[..., 2]).unsqueeze(-1)
            factor = 1.0 + fs
            result = (gray + factor * (result - gray)).clamp(0, 1)

        # Hue shift (via numpy colorsys per-pixel)
        if abs(fh) > 1e-6:
            import colorsys
            arr = result.numpy()  # [N,H,W,3]
            shape = arr.shape
            flat = arr.reshape(-1, 3)
            out = np.zeros_like(flat)
            for idx in range(len(flat)):
                rr, gg, bb = float(flat[idx,0]), float(flat[idx,1]), float(flat[idx,2])
                h, s, v = colorsys.rgb_to_hsv(rr, gg, bb)
                h = (h + fh) % 1.0
                nr, ng, nb = colorsys.hsv_to_rgb(h, s, v)
                out[idx] = [nr, ng, nb]
            result = torch.from_numpy(out.reshape(shape).astype(np.float32))

        # Vignette
        if vignette > 1e-6:
            N, H, W, C = result.shape
            y_coords = torch.linspace(-1, 1, H).view(H, 1).expand(H, W)
            x_coords = torch.linspace(-1, 1, W).view(1, W).expand(H, W)
            dist = torch.sqrt((x_coords / 0.7) ** 2 + (y_coords / 0.7) ** 2)
            mask = (1.0 - dist * vignette).clamp(0, 1).view(1, H, W, 1)
            result = result * mask

        return (result,)
