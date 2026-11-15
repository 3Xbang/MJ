"""分镜批量控制节点 — 管理多分镜顺序生成流程，支持尾帧接力。

用法：
  将 ShotSequenceBuilder 输出的 SHOT_SEQUENCE 连接到本节点，
  通过手动修改 current_index 逐个处理每个分镜，实现批量生成。
"""
from __future__ import annotations

import os

import numpy as np
import torch
from PIL import Image

from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger(__name__)


class AFE_ShotBatchController:
    """分镜批量控制器。

    管理多分镜顺序生成流程，每次处理一个分镜，自动加载上一分镜的尾帧，
    实现流畅的镜头接力效果。适合像拍电影一样逐个分镜单独生成视频。
    """

    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
                "current_index": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 999,
                        "tooltip": "当前要处理的分镜序号（从0开始）",
                    },
                ),
            },
            "optional": {
                "tail_frame_dir": ("STRING", {"default": "./projects/tail_frames"}),
                "output_dir": ("STRING", {"default": "./projects/output"}),
            },
        }

    RETURN_TYPES = ("SHOT_SEQUENCE", "STRING", "IMAGE", "STRING", "INT", "INT")
    RETURN_NAMES = (
        "shot_sequence",
        "current_shot_id",
        "tail_frame",
        "batch_status",
        "current_index",
        "total_shots",
    )
    FUNCTION = "control_batch"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _blank_image() -> torch.Tensor:
        arr = np.zeros((1, 1, 3), dtype=np.float32)
        return torch.from_numpy(arr).unsqueeze(0)  # [1, 1, 1, 3]

    @staticmethod
    def _get_id(shot) -> str:
        if isinstance(shot, dict):
            return shot.get("shot_id", shot.get("id", ""))
        return getattr(shot, "shot_id", getattr(shot, "id", ""))

    # ------------------------------------------------------------------
    # main
    # ------------------------------------------------------------------

    def control_batch(
        self,
        shot_sequence,
        current_index: int = 0,
        tail_frame_dir: str = "./projects/tail_frames",
        output_dir: str = "./projects/output",
    ):
        blank = self._blank_image

        shots = list(shot_sequence)
        total = len(shots)

        # All shots processed
        if current_index >= total:
            return (
                shot_sequence,
                "",
                blank(),
                f"✅ 所有分镜已完成！共{total}个分镜已处理完毕。",
                current_index,
                total,
            )

        current_shot = shots[current_index]
        current_shot_id = self._get_id(current_shot)

        # Load tail frame from previous shot
        if current_index == 0:
            tail_frame = blank()
            tail_status = "⏭️ 首个分镜，无尾帧"
        else:
            prev_shot_id = self._get_id(shots[current_index - 1])
            tail_path = os.path.join(tail_frame_dir, f"{prev_shot_id}_tail.png")
            if os.path.exists(tail_path):
                try:
                    pil_img = Image.open(tail_path).convert("RGB")
                    arr = np.array(pil_img, dtype=np.float32) / 255.0
                    tail_frame = torch.from_numpy(arr).unsqueeze(0)  # [1, H, W, 3]
                    tail_status = f"✅ 上一帧：已加载 {prev_shot_id}_tail.png"
                except Exception as exc:
                    logger.warning("无法加载尾帧 %s — %s", tail_path, exc)
                    tail_frame = blank()
                    tail_status = f"⚠️ 尾帧加载失败：{prev_shot_id}_tail.png"
            else:
                tail_frame = blank()
                tail_status = f"⚠️ 尾帧文件不存在：{prev_shot_id}_tail.png"

        next_index = current_index + 1
        if next_index < total:
            next_info = f"下一步：生成视频后修改 current_index 为 {next_index}"
        else:
            next_info = "这是最后一个分镜"

        batch_status = (
            f"🎬 当前：{current_shot_id} ({current_index + 1}/{total}) | {next_info}\n"
            f"{tail_status}\n"
            f"⏳ 总进度：已完成{current_index}个，待生成{total - current_index}个"
        )

        return (
            shot_sequence,
            current_shot_id,
            tail_frame,
            batch_status,
            current_index,
            total,
        )
