from __future__ import annotations
from ai_film_editor_nodes.lib.utils.logger import get_logger
from ai_film_editor_nodes.lib.utils.model_checker import get_model_list

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
                "face_model": (get_model_list("facerestore_models", "(未安装，ComfyUI Manager 搜索 codeformer)"),),
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

    def enhance_faces(self, images, face_model, fidelity_weight=0.5, enable=True, only_center_face=False):
        if not enable:
            return (images,)

        # Step 1: check whether the CodeFormer pack is importable at all.
        try:
            import importlib
            codeformer_mod = importlib.import_module("custom_nodes.ComfyUI_CodeFormer.codeformer_node")
        except (ImportError, ModuleNotFoundError):
            logger.warning(
                "CodeFormer not found. Install ComfyUI_CodeFormer via ComfyUI Manager "
                "for AI face enhancement. Passing images through unchanged."
            )
            return (images,)

        # Step 2: attempt the actual enhancement.  If CodeFormer is installed but its
        # API differs from what we expect, surface a distinguishable error rather than
        # silently falling through to passthrough.
        try:
            enhancer = codeformer_mod.CodeFormerEnhance()
            result = enhancer.enhance(
                images=images,
                face_model=face_model,
                fidelity_weight=fidelity_weight,
                only_center_face=only_center_face,
            )
            return (result[0],) if isinstance(result, (list, tuple)) else (result,)
        except Exception as exc:
            logger.warning(
                f"CodeFormer is installed but enhancement failed: {exc}. "
                "Check that ComfyUI_CodeFormer is up to date and compatible. "
                "Passing images through unchanged."
            )
            return (images,)
