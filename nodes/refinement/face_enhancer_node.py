from __future__ import annotations
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_FaceEnhancer")


class AFE_FaceEnhancer:
    """
    AI face enhancement using CodeFormer.
    Requires: ComfyUI_CodeFormer node pack (install via ComfyUI Manager).
    Falls back to passthrough if CodeFormer is not available.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "fidelity_weight": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
                "enable": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "only_center_face": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("enhanced_images",)
    FUNCTION = "enhance_faces"
    CATEGORY = "AI Film Editor/Refinement"
    OUTPUT_NODE = False
    DESCRIPTION = "AI face enhancement. Requires ComfyUI_CodeFormer. Passes through unchanged if not installed."

    def enhance_faces(self, images, fidelity_weight=0.5, enable=True, only_center_face=False):
        if not enable:
            return (images,)

        try:
            # CodeFormer is provided by the ComfyUI_CodeFormer node pack.
            # When installed, it registers its own restoration pipeline.
            # We attempt to invoke it; if unavailable we gracefully degrade.
            import importlib
            codeformer_mod = importlib.import_module("custom_nodes.ComfyUI_CodeFormer.codeformer_node")
            enhancer = codeformer_mod.CodeFormerEnhance()
            result = enhancer.enhance(
                images=images,
                fidelity_weight=fidelity_weight,
                only_center_face=only_center_face,
            )
            return (result[0],) if isinstance(result, (list, tuple)) else (result,)
        except (ImportError, ModuleNotFoundError, AttributeError):
            logger.warning(
                "CodeFormer not found. Install ComfyUI_CodeFormer for AI face enhancement. "
                "Passing images through unchanged."
            )
            return (images,)
