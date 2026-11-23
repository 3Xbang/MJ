"""
AFE_MovieAssembler — joins the per-shot clips into one finished film.

Looks for <project_dir>/clips_av/<shot_id>.mp4 first (clips that already carry the dialogue
audio track), then <project_dir>/clips/<shot_id>.mp4 (silent Wan clips). All clips are written
by the same ffmpeg settings, so they are joined with the concat demuxer without re-encoding.
"""
from __future__ import annotations

import logging
import os

from ai_film_editor_nodes.nodes.video._common import (
    auto_all_input, closed_result, concat_mp4, gate_input, gate_is_open, get_shots, shot_id_of,
    split_items, norm_shot_key,
)

logger = logging.getLogger("AFE_MovieAssembler")


def find_clip(project: str, sid: str) -> str | None:
    for folder in ("clips_av", "clips"):
        p = os.path.join(project, folder, f"{sid}.mp4")
        if os.path.exists(p):
            return p
    return None


class AFE_MovieAssembler:
    """All shot clips, in script order -> <project_dir>/<output_name>.mp4"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
                "project_dir": ("STRING", {"forceInput": True,
                                           "tooltip": "project_dir from AFE_WanShotRenderer"}),
                "output_name": ("STRING", {"default": "final_movie"}),
            },
            "optional": {
                "skip_shots": ("STRING", {"default": "",
                                          "tooltip": "成片里不要的分镜。例：shot_007, 12"}),
                "approved": gate_input("把所有分镜视频合成成片"),
                "auto_all": auto_all_input(),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("movie_path", "report")
    FUNCTION = "assemble"
    CATEGORY = "AI Film Editor/Video"
    OUTPUT_NODE = True

    def assemble(self, shot_sequence, project_dir, output_name="final_movie", skip_shots="",
                 approved=False, auto_all=False):
        if not gate_is_open(approved, auto_all):
            return closed_result("成片合成（合成前请确认各分镜视频）", "dr")
        skip = {norm_shot_key(t) for t in split_items(skip_shots)}
        shots = get_shots(shot_sequence)
        found, missing, total_s = [], [], 0.0
        for i, shot in enumerate(shots):
            sid = shot_id_of(shot, i)
            if sid in skip:
                continue
            path = find_clip(project_dir, sid)
            if path:
                found.append(path)
                total_s += float(shot.get("duration_seconds") or 5.0)
            else:
                missing.append(sid)

        if not found:
            raise ValueError(f"No clips found in {project_dir}/clips. Run AFE_WanShotRenderer first.")

        safe = "".join(c for c in output_name if c.isalnum() or c in "-_ ").strip() or "final_movie"
        out_path = os.path.join(project_dir, f"{safe}.mp4")
        concat_mp4(found, out_path, os.path.join(project_dir, "concat_list.txt"))

        lines = [
            "🎞 成片合成完成",
            f"镜头 {len(found)} / {len(shots)}，约 {total_s:.0f} 秒" + (f"（按你的设置排除 {len(skip)} 个）" if skip else ""),
            f"文件：{out_path}",
        ]
        if missing:
            lines.append(f"⚠️ 缺少 {len(missing)} 个镜头（已跳过）：{', '.join(missing[:12])}"
                         + (" ..." if len(missing) > 12 else ""))
        report = "\n".join(lines)
        logger.info(report)
        return {"ui": {"text": [report], "afe_movie": [os.path.basename(out_path)]},
                "result": (out_path, report)}
