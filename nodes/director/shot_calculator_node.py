from __future__ import annotations
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotCalculator")


class AFE_ShotCalculator:
    """
    分镜计算器 + 开关管理器。
    1. 输入总时长和每段时长，自动计算分镜总数
    2. 在 disabled_shots 填写要跳过的分镜编号
    3. 显示所有分镜的启用/禁用状态
    
    例：总180秒 ÷ 5秒 = 36个分镜
        disabled_shots = "3, 7, 15" → 跳过第3、7、15个
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
            },
            "optional": {
                "disabled_shots": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "要跳过的分镜编号，逗号分隔。例：3, 7, 15"
                }),
                "start_from": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 500,
                    "tooltip": "从第几个分镜开始生成（续拍时用）"
                }),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("shot_count", "seconds_per_shot")
    FUNCTION = "calculate"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def calculate(self, total_seconds: int, seconds_per_shot: int,
                  disabled_shots: str = "", start_from: int = 1) -> tuple:

        shot_count = total_seconds // seconds_per_shot
        remainder  = total_seconds % seconds_per_shot

        # 解析要跳过的分镜编号
        disabled_set = set()
        if disabled_shots.strip():
            for part in disabled_shots.split(","):
                part = part.strip()
                if part.isdigit():
                    disabled_set.add(int(part))

        # 生成开关状态显示
        enabled_ids = []
        rows = []
        row  = []
        for i in range(1, shot_count + 1):
            if i in disabled_set:
                row.append(f"❌{i:02d}")
            elif i < start_from:
                row.append(f"⏭️{i:02d}")
            else:
                row.append(f"✅{i:02d}")
                enabled_ids.append(i)
            if len(row) == 8:
                rows.append("  ".join(row))
                row = []
        if row:
            rows.append("  ".join(row))

        lines = [
            "🧮 分镜计算结果",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"总时长：{total_seconds}秒  每段：{seconds_per_shot}秒",
            f"分镜总数：{shot_count} 个",
        ]
        if remainder > 0:
            lines.append(f"剩余：{remainder}秒")
        lines.append(f"启用：{len(enabled_ids)} 个  跳过：{len(disabled_set)} 个")
        if start_from > 1:
            lines.append(f"从第 {start_from} 个开始")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.extend(rows)

        # 在节点内部显示（不需要外部输出口）
        print("\n".join(lines))
        logger.info(f"分镜计算：{total_seconds}s ÷ {seconds_per_shot}s = {shot_count}个，启用{len(enabled_ids)}个")
        return (shot_count, seconds_per_shot)
