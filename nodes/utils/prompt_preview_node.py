from __future__ import annotations
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_PromptPreview")


class AFE_PromptPreview:
    """Displays the assembled prompt for debugging; passes all values through unchanged."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("STRING", {"forceInput": True}),
                "negative": ("STRING", {"forceInput": True}),
                "seed": ("INT", {"forceInput": True}),
                "width": ("INT", {"forceInput": True}),
                "height": ("INT", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("positive", "negative", "seed", "width", "height")
    OUTPUT_NODE = True
    FUNCTION = "preview_and_passthrough"
    CATEGORY = "AI Film Editor/Utils"

    def preview_and_passthrough(self, positive, negative, seed, width, height):
        display = (
            f"[Positive]\n{positive}\n\n"
            f"[Negative]\n{negative}\n\n"
            f"Seed: {seed} | {width}x{height}"
        )
        logger.info("AFE_PromptPreview: seed=%d  %dx%d", seed, width, height)
        return {"ui": {"text": [display]}, "result": (positive, negative, seed, width, height)}
