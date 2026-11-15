from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotListViewer")


def _get_shots(shot_sequence) -> list:
    if isinstance(shot_sequence, list):
        return shot_sequence
    if isinstance(shot_sequence, dict):
        return shot_sequence.get("shots", [])
    if hasattr(shot_sequence, "shots"):
        return list(shot_sequence.shots)
    return []


class AFE_ShotListViewer:
    """
    分镜列表查看器。
    显示所有分镜的完整信息，支持简洁/详细两种模式。
    返回 shot_list_json 供下游节点使用；
    报告文本通过 ComfyUI UI dict 显示在节点卡上。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
            },
            "optional": {
                "show_details": (["简洁", "详细"], {"default": "简洁"}),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("shot_list_json", "total_shots")
    FUNCTION = "view_shots"
    CATEGORY = "AI Film Editor/Analyzers"
    OUTPUT_NODE = True

    def view_shots(self, shot_sequence, show_details: str = "简洁"):
        shots = _get_shots(shot_sequence)
        detailed = show_details == "详细"

        output_shots: list[dict] = []
        lines = [
            "🎬 分镜列表",
            "━" * 20,
        ]

        for idx, shot in enumerate(shots):
            shot_id = shot.get("shot_id") or shot.get("label", f"shot_{idx+1:03d}")
            label = shot.get("label", shot_id)
            duration = shot.get("duration_seconds", shot.get("duration", 0.0))
            scene = shot.get("scene_name", "")
            char_names = shot.get("character_names", [])
            if not isinstance(char_names, list):
                char_names = [char_names] if char_names else []
            chars_str = "、".join(char_names) if char_names else "（无）"

            # Concise line: index | label | duration | scene | characters
            lines.append(f"[{idx+1:02d}] {label} | {duration:.1f}s | {scene} | {chars_str}")

            if detailed:
                shot_desc = shot.get("shot_description", "")
                neg_prompt = shot.get("negative_prompt", "")
                props = shot.get("props_list", [])
                props_str = "、".join(props) if isinstance(props, list) and props else "（无）"
                camera_motion = shot.get("camera_motion", "")
                camera_angle = shot.get("camera_angle", "")
                lighting = shot.get("lighting_style", "")
                dialogue = shot.get("dialogue", "")
                if shot_desc:
                    lines.append(f"     提示词：{shot_desc}")
                if neg_prompt:
                    lines.append(f"     负面词：{neg_prompt}")
                if props_str != "（无）":
                    lines.append(f"     道具：{props_str}")
                if camera_motion or camera_angle:
                    lines.append(f"     运镜：{camera_angle} / {camera_motion}")
                if lighting:
                    lines.append(f"     布光：{lighting}")
                if dialogue and dialogue != "（无）":
                    lines.append(f"     台词：{dialogue}")
                lines.append("")

            # Collect full shot data for JSON output
            output_shots.append({
                "index": idx + 1,
                "shot_id": shot_id,
                "label": label,
                "duration_seconds": duration,
                "scene_name": scene,
                "character_names": char_names,
                "costume_description": shot.get("costume_description", ""),
                "props_list": shot.get("props_list", []),
                "camera_angle": shot.get("camera_angle", ""),
                "camera_motion": shot.get("camera_motion", ""),
                "lighting_style": shot.get("lighting_style", ""),
                "shot_description": shot.get("shot_description", ""),
                "negative_prompt": shot.get("negative_prompt", ""),
                "director_notes": shot.get("director_notes", ""),
                "dialogue": shot.get("dialogue", ""),
            })

        lines.append("━" * 20)
        lines.append(f"共 {len(shots)} 个分镜")

        shot_list_json = json.dumps(output_shots, ensure_ascii=False)
        report_text = "\n".join(lines)

        logger.info(f"ShotListViewer: {len(shots)} shots, mode={show_details}")
        # Return UI text for display on the node card, plus the downstream outputs
        return {"ui": {"text": [report_text]}, "result": (shot_list_json, len(shots))}
