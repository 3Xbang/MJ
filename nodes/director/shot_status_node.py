from __future__ import annotations
import os
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotStatusBoard")


class AFE_ShotStatusBoard:
    """
    分镜状态看板节点。检查每个分镜的三采集文件是否存在，输出可读的状态报告。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
            },
            "optional": {
                "output_dir": ("STRING", {"default": "./projects/output"}),
                "check_files": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "INT")
    RETURN_NAMES = ("status_board", "completed_count", "pending_count")
    FUNCTION = "show_status"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def show_status(self, shot_sequence, output_dir="./projects/output", check_files=True):
        if not shot_sequence:
            warning = "⚠️ 没有分镜数据"
            logger.warning(warning)
            return (warning, 0, 0)

        sep = "━" * 55
        lines = ["📊 分镜状态看板", sep]

        completed = 0
        in_progress = 0
        pending = 0
        total_duration = 0.0

        for idx, shot in enumerate(shot_sequence):
            shot_id = shot.get("shot_id", shot.get("label", f"shot_{idx + 1:03d}"))
            label = shot.get("label", shot_id)
            duration = shot.get("duration_seconds", 5)
            total_duration += duration

            if check_files:
                p1 = os.path.exists(os.path.join(output_dir, f"{shot_id}_pass1.mp4"))
                p2 = os.path.exists(os.path.join(output_dir, f"{shot_id}_pass2.mp4"))
                p3 = os.path.exists(os.path.join(output_dir, f"{shot_id}_pass3.mp4"))
            else:
                p1, p2, p3 = False, False, False

            done_count = sum([p1, p2, p3])
            if done_count == 3:
                emoji = "✅"
                completed += 1
            elif done_count > 0:
                emoji = "🔄"
                in_progress += 1
            else:
                emoji = "⏳"
                pending += 1

            p1_mark = "✓" if p1 else "✗"
            p2_mark = "✓" if p2 else "✗"
            p3_mark = "✓" if p3 else "✗"

            lines.append(
                f"{emoji} [{idx:02d}] {label:<18}| {duration}秒 | 一采{p1_mark} | 二采{p2_mark} | 三采{p3_mark}"
            )

        total = len(shot_sequence)
        lines.extend([
            sep,
            f"完成 {completed}/{total} | 进行中 {in_progress} | 待生成 {pending}",
            f"预计总时长：{total_duration:.0f}秒",
        ])

        status_board = "\n".join(lines)
        logger.info(f"ShotStatusBoard: {completed}/{total} shots completed")
        return (status_board, completed, pending)
