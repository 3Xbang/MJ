from __future__ import annotations
import torch
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_AudioVideoSync")


class AFE_AudioVideoSync:
    """
    Align video frames to audio timing.
    Connect outputs (images, frame_rate, audio_path) directly to VHS_VideoCombine.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "audio": ("AUDIO_ASSET",),
                "frame_rate": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 0.1}),
                "sync_offset_seconds": ("FLOAT", {"default": 0.0, "min": -5.0, "max": 5.0, "step": 0.1}),
            },
            "optional": {
                "trim_to_shortest": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("IMAGE", "FLOAT", "STRING")
    RETURN_NAMES = ("images", "frame_rate", "audio_path")
    FUNCTION = "sync_audio_video"
    CATEGORY = "AI Film Editor/Audio"

    def sync_audio_video(self, images, audio, frame_rate=24.0, sync_offset_seconds=0.0, trim_to_shortest=True):
        file_path = audio.get("file_path") if isinstance(audio, dict) else getattr(audio, "file_path", None)
        duration = audio.get("duration_seconds", 0.0) if isinstance(audio, dict) else getattr(audio, "duration_seconds", 0.0)

        offset_frames = int(sync_offset_seconds * frame_rate)
        result = images

        if offset_frames > 0:
            # Drop the first N frames (video starts later relative to audio)
            result = images[offset_frames:] if images.shape[0] > offset_frames else images[-1:]
        elif offset_frames < 0:
            # Pad: repeat the first frame to shift video earlier
            pad_count = min(abs(offset_frames), 60)  # cap at 60 frames to avoid memory issues
            padding = images[:1].expand(pad_count, -1, -1, -1)
            result = torch.cat([padding, images], dim=0)

        if trim_to_shortest and duration > 0:
            max_frames = int(duration * frame_rate)
            if result.shape[0] > max_frames:
                result = result[:max_frames]

        return (result, frame_rate, file_path or "")
