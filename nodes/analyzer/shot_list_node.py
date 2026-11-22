from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotList")


class AFE_ShotList:
    """
    Shot List (分镜清单).
    Parses shots_prompts_json from ShotPromptBuilder and produces a
    formatted shot list report plus summary JSON for downstream nodes.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shots_prompts_json": ("STRING", {
                    "default": "[]",
                    "forceInput": True,
                    "tooltip": "Connect to AFE_ShotPromptBuilder shots_prompts_json output",
                }),
            },
            "optional": {
                "target_duration_seconds": ("INT", {
                    "default": 0, "min": 0, "max": 7200,
                    "tooltip": "目标总时长（秒），用于与实际总时长对比（0=不对比）",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("shot_list_report", "shot_count", "total_duration_seconds", "shot_summary_json")
    FUNCTION = "build_shot_list"
    CATEGORY = "AI Film Editor/Shot"
    OUTPUT_NODE = True

    def build_shot_list(self, shots_prompts_json: str, target_duration_seconds: int = 0):
        try:
            shots = json.loads(shots_prompts_json)
            if not isinstance(shots, list):
                shots = []
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"Failed to parse shots_prompts_json: {exc}")
            shots = []

        total_duration = 0.0
        summary_list: list[dict] = []
        report_lines = [
            "🎬 分镜清单 Shot List",
            "━" * 50,
        ]

        for idx, shot in enumerate(shots):
            shot_id    = shot.get("shot_id", f"shot_{idx+1:03d}")
            scene      = shot.get("scene", "")
            characters = shot.get("characters", [])
            if not isinstance(characters, list):
                characters = [characters] if characters else []
            duration   = float(shot.get("duration_seconds", 5.0))
            cam_angle  = shot.get("camera_angle", "")
            cam_motion = shot.get("camera_motion", "")

            total_duration += duration
            chars_str = ", ".join(str(c) for c in characters) if characters else "(none)"
            cam_str = " ".join(filter(None, [cam_angle, cam_motion]))

            line = (
                f"[{idx+1:02d}] {shot_id} | {scene} | "
                f"{chars_str} | {duration:.1f}s | {cam_str}"
            )
            report_lines.append(line)

            summary_list.append({
                "shot_id":       shot_id,
                "scene":         scene,
                "characters":    characters,
                "duration_seconds": duration,
                "camera_angle":  cam_angle,
                "camera_motion": cam_motion,
            })

        report_lines.append("━" * 50)
        report_lines.append(
            f"共 {len(shots)} 个分镜  |  总时长：{total_duration:.1f}s "
            f"({total_duration/60:.1f}min)"
        )
        if target_duration_seconds > 0:
            diff = abs(total_duration - target_duration_seconds)
            if diff > 5:
                report_lines.append(
                    f"⚠️ 总时长 {total_duration:.1f}s 与目标 {target_duration_seconds}s "
                    f"相差 {diff:.1f}s"
                )
            else:
                report_lines.append(f"✅ 总时长与目标一致 ({total_duration:.1f}s)")
        shot_list_report = "\n".join(report_lines)
        shot_summary_json = json.dumps(summary_list, ensure_ascii=False)

        logger.info(f"ShotList: {len(shots)} shots, total {total_duration:.1f}s")
        return {
            "ui": {"text": [shot_list_report]},
            "result": (shot_list_report, len(shots), total_duration, shot_summary_json),
        }
