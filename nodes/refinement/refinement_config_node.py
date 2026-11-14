from __future__ import annotations


class AFE_RefinementConfig:
    """Build a refinement configuration dict for second/third pass workflows."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pass_number": (["second_pass", "third_pass"],),
                "target_width": ("INT", {"default": 1280, "min": 64, "max": 8192, "step": 64}),
                "target_height": ("INT", {"default": 720, "min": 64, "max": 8192, "step": 64}),
                "denoise_strength": ("FLOAT", {"default": 0.55, "min": 0.1, "max": 1.0, "step": 0.05}),
                "steps": ("INT", {"default": 25, "min": 10, "max": 50}),
                "cfg_scale": ("FLOAT", {"default": 6.0, "min": 1.0, "max": 20.0, "step": 0.5}),
            }
        }

    RETURN_TYPES = ("REFINEMENT_CONFIG",)
    RETURN_NAMES = ("config",)
    FUNCTION = "build_config"
    CATEGORY = "AI Film Editor/Refinement"

    def build_config(self, pass_number, target_width, target_height, denoise_strength, steps, cfg_scale):
        config = {
            "pass_number": pass_number,
            "target_width": target_width,
            "target_height": target_height,
            "denoise_strength": denoise_strength,
            "steps": steps,
            "cfg_scale": cfg_scale,
        }
        return (config,)
