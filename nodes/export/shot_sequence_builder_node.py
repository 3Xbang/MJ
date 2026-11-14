from __future__ import annotations
import json
import os
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotSequenceBuilder")


class AFE_ShotSequenceBuilder:
    """Build a shot sequence manifest JSON from a SHOT_SEQUENCE."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
            },
            "optional": {
                "output_directory": ("STRING", {"default": "./output/final"}),
                "project_name": ("STRING", {"default": "AFE_Project"}),
                "add_slate": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "FLOAT")
    RETURN_NAMES = ("sequence_manifest_path", "total_shots", "total_duration_seconds")
    FUNCTION = "build_sequence"
    CATEGORY = "AI Film Editor/Export"
    OUTPUT_NODE = True

    def build_sequence(self, shot_sequence, output_directory="./output/final", project_name="AFE_Project", add_slate=False):
        shots = []
        if isinstance(shot_sequence, dict):
            shots = shot_sequence.get("shots", [])
        elif hasattr(shot_sequence, "shots"):
            shots = shot_sequence.shots

        manifest = []
        for i, s in enumerate(shots):
            if isinstance(s, dict):
                entry = {
                    "index": i,
                    "shot_id": s.get("shot_id", s.get("id", f"shot_{i}")),
                    "label": s.get("label", f"Shot {i + 1}"),
                    "video_path": s.get("video_path", ""),
                    "duration": s.get("duration", 5.0),
                }
            else:
                entry = {
                    "index": i,
                    "shot_id": getattr(s, "shot_id", getattr(s, "id", f"shot_{i}")),
                    "label": getattr(s, "label", f"Shot {i + 1}"),
                    "video_path": getattr(s, "video_path", ""),
                    "duration": getattr(s, "duration", 5.0),
                }
            manifest.append(entry)

        os.makedirs(output_directory, exist_ok=True)
        manifest_path = os.path.join(output_directory, f"{project_name}_sequence_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        total_duration = sum(e["duration"] for e in manifest)
        logger.info(f"Sequence manifest written to {manifest_path} ({len(manifest)} shots)")
        return (manifest_path, len(manifest), total_duration)
