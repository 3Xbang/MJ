from __future__ import annotations
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotCalculator")


class AFE_ShotCalculator:
    """
    分镜计算器。
    输入总时长和每段时长，计算需要多少个分镜。
    例：180秒 ÷ 5秒 = 36个分镜
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "total_seconds": ("INT", {
                    "default": 180,
                    "min": 5,
                    "max": 7200,
                    "step": 5,
                    "tooltip": "视频总时长（秒）"
                }),
                "seconds_per_shot": ("INT", {
                    "default": 5,
                    "min": 1,
                    "max": 60,
                    "step": 1,
                    "tooltip": "每个分镜时长（秒），默认5秒"
                }),
            }
        }

    RETURN_TYPES = ("INT", "INT", "STRING")
    RETURN_NAMES = ("shot_count", "seconds_per_shot", "summary")
    FUNCTION = "calculate"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def calculate(self, total_seconds: int, seconds_per_shot: int) -> tuple:
        shot_count = total_seconds // seconds_per_shot
        remainder = total_seconds % seconds_per_shot

        lines = [
            "🎬 分镜计算结果",
            "━━━━━━━━━━━━━━━━━━",
            f"总时长：{total_seconds} 秒",
            f"每段时长：{seconds_per_shot} 秒",
            f"分镜总数：{shot_count} 个",
        ]
        if remainder > 0:
            lines.append(f"剩余：{remainder} 秒（最后一段可设为 {remainder} 秒）")
        lines.append("━━━━━━━━━━━━━━━━━━")

        summary = "\n".join(lines)
        logger.info(f"分镜计算：{total_seconds}秒 ÷ {seconds_per_shot}秒 = {shot_count}个分镜")

        return (shot_count, seconds_per_shot, summary)
