from __future__ import annotations
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_LipSyncConfig")


class AFE_LipSyncConfig:
    """
    Prepare image frames and audio for lip sync.
    Requires one of: ComfyUI-LatentSync, ComfyUI-Wav2Lip, or ComfyUI-SadTalker.
    Connect outputs to your chosen lip sync node.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "audio": ("AUDIO_ASSET",),
                "sync_model": (["LatentSync", "Wav2Lip", "SadTalker"],),
                "face_detect_confidence": ("FLOAT", {"default": 0.9, "min": 0.5, "max": 1.0, "step": 0.05}),
            },
            "optional": {
                "enhance_face": ("BOOLEAN", {"default": True}),
                "smooth_transition": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("images", "audio_path", "sync_model")
    FUNCTION = "prepare_lip_sync"
    CATEGORY = "AI Film Editor/Audio"
    DESCRIPTION = (
        "Validates and routes inputs for lip sync. "
        "Install ComfyUI-LatentSync, ComfyUI-Wav2Lip, or ComfyUI-SadTalker "
        "and connect this node's outputs to your chosen lip sync node."
    )

    def prepare_lip_sync(
        self, images, audio, sync_model, face_detect_confidence=0.9,
        enhance_face=True, smooth_transition=True
    ):
        file_path = audio.get("file_path") if isinstance(audio, dict) else getattr(audio, "file_path", None)
        if not file_path:
            logger.warning(
                "AFE_LipSyncConfig: audio.file_path is empty. "
                "Set the audio_file field in AFE_AudioAsset before connecting to lip sync."
            )
        return (images, file_path or "", sync_model)
