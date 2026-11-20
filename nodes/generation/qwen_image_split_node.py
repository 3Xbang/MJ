"""
AFE_QwenImageSplit — Qwen Image 2.1 输出切分器

Qwen Image 2.1 Prompt Enhancer 将9张图合并输出为1张网格图 (1440×2560)。
本节点将其按实际内容行高切分为9张独立图片。

实际行高（由内容分析确认，1440×2560 输出）：
  Row 0: y=0~900    (白背景: 三视图/全身图)       900px
  Row 1: y=900~1700 (蓝天背景: 面部特写)          800px
  Row 2: y=1700~H   (海滩背景: 坐姿场景)          860px
  Cols:  均等 3×480px

输出顺序（左→右，上→下）：
  view_1_三视图  view_2_正面    view_3_背面
  view_4_侧面    view_5_面部中性 view_6_面部微笑
  view_7_面部严肃 view_8_场景喝茶 view_9_场景坐姿
"""
from __future__ import annotations
import torch
import logging

logger = logging.getLogger("AFE_QwenImageSplit")


class AFE_QwenImageSplit:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
            },
            "optional": {
                "cols": ("INT", {
                    "default": 3, "min": 1, "max": 9, "step": 1,
                    "tooltip": "列数（Qwen默认3列）",
                }),
                "row_cut_1": ("INT", {
                    "default": 900, "min": 100, "max": 3000, "step": 10,
                    "tooltip": "Row 0/1 分割点（白背景行结束位置，默认900px）",
                }),
                "row_cut_2": ("INT", {
                    "default": 1700, "min": 200, "max": 3000, "step": 10,
                    "tooltip": "Row 1/2 分割点（蓝天行结束位置，默认1700px）",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE",) * 9
    RETURN_NAMES = (
        "view_1_三视图",
        "view_2_正面",
        "view_3_背面",
        "view_4_侧面",
        "view_5_面部中性",
        "view_6_面部微笑",
        "view_7_面部严肃",
        "view_8_场景喝茶",
        "view_9_场景坐姿",
    )
    FUNCTION = "split"
    CATEGORY = "AI Film Editor/Character Card"
    OUTPUT_NODE = False

    def split(self, image: torch.Tensor,
              cols: int = 3,
              row_cut_1: int = 900,
              row_cut_2: int = 1700):

        B, H, W, C = image.shape
        logger.info("QwenImageSplit: B=%d H=%d W=%d", B, H, W)

        # ── Batch 模式：直接按 index 拆分 ─────────────────────────────────
        if B > 1:
            logger.info("Batch mode: %d images", B)
            cells = [image[i:i+1] for i in range(B)]
            while len(cells) < 9:
                cells.append(cells[-1])
            return tuple(cells[:9])

        # ── 单张合并图：按非均等行高切分 ──────────────────────────────────
        # 按实际图片高度等比缩放分割点（基准：2560px）
        scale = H / 2560.0
        c1 = max(1,      min(int(row_cut_1 * scale), H - 2))
        c2 = max(c1 + 1, min(int(row_cut_2 * scale), H - 1))
        row_cuts = [0, c1, c2, H]
        cw = W // cols

        logger.info("Row cuts: [0, %d, %d, %d]  col_width=%d", c1, c2, H, cw)

        cells = []
        for ri in range(3):
            y0, y1 = row_cuts[ri], row_cuts[ri + 1]
            for ci in range(cols):
                x0, x1 = ci * cw, (ci + 1) * cw
                cells.append(image[:, y0:y1, x0:x1, :])

        while len(cells) < 9:
            cells.append(cells[-1])
        return tuple(cells[:9])
