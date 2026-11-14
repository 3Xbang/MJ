from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ProjectExport")

# Resolution presets
_RESOLUTION_MAP = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "4k": (3840, 2160),
    "source": None,
}


class AFE_ProjectExport:
    """Generate an export configuration JSON. Actual rendering is done by VHS_VideoCombine."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "sequence_manifest_path": ("STRING", {"default": ""}),
                "output_format": (["mp4_h264", "mp4_h265", "webm_vp9", "gif"],),
                "output_resolution": (["480p", "720p", "1080p", "4k", "source"],),
                "quality": (["low", "medium", "high", "lossless"],),
                "frame_rate": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 0.1}),
            },
            "optional": {
                "add_metadata": ("BOOLEAN", {"default": True}),
                "project_title": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("export_config_json",)
    FUNCTION = "build_export_config"
    CATEGORY = "AI Film Editor/Export"
    OUTPUT_NODE = True

    def build_export_config(
        self,
        sequence_manifest_path,
        output_format,
        output_resolution,
        quality,
        frame_rate=24.0,
        add_metadata=True,
        project_title="",
    ):
        resolution = _RESOLUTION_MAP.get(output_resolution)
        config = {
            "sequence_manifest_path": sequence_manifest_path,
            "output_format": output_format,
            "output_resolution": output_resolution,
            "resolution_pixels": resolution,
            "quality": quality,
            "frame_rate": frame_rate,
            "add_metadata": add_metadata,
            "project_title": project_title,
        }
        config_json = json.dumps(config, ensure_ascii=False, indent=2)
        logger.info(f"Export config built for '{project_title}' ({output_format}, {output_resolution}, {quality})")
        return (config_json,)
