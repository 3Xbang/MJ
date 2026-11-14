import torch


class AFE_TailFrameExtractor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "extract_mode": (["last_frame", "first_frame"],),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("frame",)
    FUNCTION = "extract_frame"
    CATEGORY = "AI Film Editor/Director"

    def extract_frame(self, images, extract_mode):
        # images shape: (N, H, W, C) — ComfyUI IMAGE batch
        if extract_mode == "last_frame":
            return (images[-1:],)
        else:  # first_frame
            return (images[:1],)
