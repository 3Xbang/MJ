"""最终合成节点 — 检查所有分镜的视频文件并生成 FFmpeg 合并命令。

工作流末尾使用，输出可直接在终端执行的 ffmpeg 命令。
支持三采/二采/一采降级回退，自动生成分镜状态报告。
"""
from __future__ import annotations

import json
import os

from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger(__name__)


class AFE_FinalAssembly:
    """最终合成节点。

    检查所有分镜的视频文件是否就绪（三采→二采→一采 降级），
    生成 FFmpeg 合并命令，输出合成报告。
    """

    CATEGORY = "AI Film Editor/Export"
    OUTPUT_NODE = True

    PASS_SUFFIXES = {
        "third_pass": "_pass3.mp4",
        "second_pass": "_pass2.mp4",
        "first_pass": "_pass1.mp4",
    }
    PASS_FALLBACK_ORDER = ["third_pass", "second_pass", "first_pass"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
                "output_dir": ("STRING", {"default": "./projects/output"}),
                "pass_to_use": (
                    ["third_pass", "second_pass", "first_pass"],
                    {
                        "default": "third_pass",
                        "tooltip": "优先使用哪个采集的结果（若三采不存在则自动降级）",
                    },
                ),
            },
            "optional": {
                "project_name": ("STRING", {"default": "final_movie"}),
                "include_audio": ("BOOLEAN", {"default": True}),
                "audio_dir": ("STRING", {"default": "./projects/audio"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("assembly_report", "ffmpeg_command", "ready_shots_count")
    FUNCTION = "assemble"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_id(shot) -> str:
        if isinstance(shot, dict):
            return shot.get("shot_id", shot.get("id", ""))
        return getattr(shot, "shot_id", getattr(shot, "id", ""))

    @staticmethod
    def _get_duration(shot) -> float:
        if isinstance(shot, dict):
            return float(shot.get("duration", shot.get("duration_sec", 5.0)))
        return float(getattr(shot, "duration", getattr(shot, "duration_sec", 5.0)))

    # ------------------------------------------------------------------
    # main
    # ------------------------------------------------------------------

    def assemble(
        self,
        shot_sequence,
        output_dir: str = "./projects/output",
        pass_to_use: str = "third_pass",
        project_name: str = "final_movie",
        include_audio: bool = True,
        audio_dir: str = "./projects/audio",
    ):
        shots = list(shot_sequence)
        total = len(shots)

        # Build fallback priority starting from pass_to_use
        try:
            start_idx = self.PASS_FALLBACK_ORDER.index(pass_to_use)
        except ValueError:
            start_idx = 0
        priority_passes = self.PASS_FALLBACK_ORDER[start_idx:]

        pass_labels = {
            "third_pass": "三采",
            "second_pass": "二采",
            "first_pass": "一采",
        }

        found_shots: list[dict] = []   # {shot_id, file_path, used_pass, duration}
        missing_shots: list[str] = []

        for shot in shots:
            shot_id = self._get_id(shot)
            duration = self._get_duration(shot)
            located = False
            for pass_name in priority_passes:
                suffix = self.PASS_SUFFIXES[pass_name]
                candidate = os.path.join(output_dir, f"{shot_id}{suffix}")
                if os.path.exists(candidate):
                    found_shots.append(
                        {
                            "shot_id": shot_id,
                            "file_path": candidate,
                            "used_pass": pass_name,
                            "duration": duration,
                        }
                    )
                    located = True
                    break
            if not located:
                missing_shots.append(shot_id)

        ready_count = len(found_shots)

        # ---- Build assembly_report ----
        sep = "━" * 24
        lines = ["📊 合成报告", sep]
        for item in found_shots:
            sid = item["shot_id"]
            used = item["used_pass"]
            dur = item["duration"]
            label = pass_labels.get(used, used)
            if used != pass_to_use and pass_to_use == "third_pass":
                icon = "⚠️"
                suffix_note = " (三采未完成)"
            else:
                icon = "✅"
                suffix_note = ""
            lines.append(f"{icon} {sid} → {label}{suffix_note}| {dur}秒")
        for sid in missing_shots:
            lines.append(f"❌ {sid} → 未找到任何版本")
        lines.append(sep)
        lines.append(
            f"可合成 {ready_count}/{total} 个分镜（{len(missing_shots)}个缺失）"
        )
        assembly_report = "\n".join(lines)

        # ---- Build ffmpeg_command ----
        filelist_path = os.path.join(output_dir, "filelist.txt")
        output_path = os.path.join(output_dir, f"{project_name}.mp4")

        if found_shots:
            # Show what filelist.txt would contain
            filelist_lines = [
                f"# filelist.txt 内容 (共{ready_count}个文件):"
            ]
            for item in found_shots:
                filelist_lines.append(f"# file '{item['file_path']}'")

            filelist_comment = "\n".join(filelist_lines)

            cmd = (
                f"{filelist_comment}\n\n"
                f'ffmpeg -f concat -safe 0 -i "{filelist_path}" -c copy "{output_path}"'
            )

            # Audio note
            if include_audio and os.path.isdir(audio_dir):
                audio_files = [
                    f for f in os.listdir(audio_dir)
                    if f.lower().endswith((".mp3", ".wav", ".aac", ".m4a"))
                ]
                if audio_files:
                    audio_path = os.path.join(audio_dir, audio_files[0])
                    cmd += (
                        f'\n\n# 合并音频（可选）:\n'
                        f'# ffmpeg -i "{output_path}" -i "{audio_path}" '
                        f'-filter_complex "[0:a][1:a]amix=inputs=2:duration=first" '
                        f'-c:v copy "{output_path.replace(".mp4", "_with_audio.mp4")}"'
                    )

            ffmpeg_command = cmd
        else:
            ffmpeg_command = "# ❌ 没有找到任何视频文件，无法生成合并命令"

        return (assembly_report, ffmpeg_command, ready_count)
