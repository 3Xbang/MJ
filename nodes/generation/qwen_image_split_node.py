"""
AFE_QwenImageSplit — Qwen Image 2.1 输出切分器

Qwen Image 2.1 Prompt Enhancer 将9张图合并输出为1张网格图。
本节点将其按 3×3 网格切分为9张独立图片，每张对应一个视角。

输出顺序（左到右、上到下）：
  view_1: [Image_1] 三视图合一
  view_2: [Image_2] 正面全身
  view_3: [Image_3] 侧面全身（或背面）
  view_4: [Image_4] 面部特写1
  view_5: [Image_5] 面部特写2
  view_6: [Image_6] 面部特写3
  view_7: [Image_7] 面部特写4
  view_8: [Image_8] 场景坐姿1
  view_9: [Image_9] 场景坐姿2
"""
from __future__ import annotations
import torch
import logging

logger = logging.getLogger("AFE_QwenImageSplit")


class AFE_QwenImageSplit:
    """
    将 Qwen Image 2.1 Prompt Enhancer 输出的合并网格图
    切分为 9 张独立图片。

    默认按 3×3 网格均分。如果宽高无法整除，会自动截断到最近的整数。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
            },
            "optional": {
                "cols": ("INT", {
                    "default": 3, "min": 1, "max": 9, "step": 1,
                    "tooltip": "网格列数（Qwen默认3列）",
                }),
                "rows": ("INT", {
                    "default": 3, "min": 1, "max": 9, "step": 1,
                    "tooltip": "网格行数（Qwen默认3行）",
                }),
            },
        }

    # 9 个独立 IMAGE 输出
    RETURN_TYPES  = ("IMAGE",) * 9
    RETURN_NAMES  = (
        "view_1_三视图",
        "view_2_正面",
        "view_3_侧面",
        "view_4_面部1",
        "view_5_面部2",
        "view_6_面部3",
        "view_7_面部4",
        "view_8_场景1",
        "view_9_场景2",
    )
    FUNCTION  = "split"
    CATEGORY  = "AI Film Editor/Character Card"
    OUTPUT_NODE = False

    def split(self, image: torch.Tensor, cols: int = 3, rows: int = 3):
        """
        image: 两种可能的输入格式：
          A) [1, H, W, C]  — Qwen 输出的单张合并网格图（例如 1440×2560）
          B) [9, H, W, C]  — Qwen 输出的 batch（9张独立图，每张 1024×1024）

        对应处理：
          A → 按 rows×cols 裁剪成 9 个小图
          B → 直接按 batch index 拆开成 9 张
        """
        B, H, W, C = image.shape
        logger.info("QwenImageSplit input: B=%d H=%d W=%d C=%d", B, H, W, C)

        # ── 情况 B：已经是 batch，直接按 index 拆分 ───────────────────────────
        if B > 1:
            logger.info("Batch mode: splitting %d images by index", B)
            cells = [image[i:i+1] for i in range(B)]
            # 补齐到 9
            while len(cells) < 9:
                cells.append(cells[-1])
            return tuple(cells[:9])

        # ── 情况 A：单张合并图，按网格裁剪 ───────────────────────────────────
        img = image  # [1, H, W, C]
        cell_h = H // rows
        cell_w = W // cols
        logger.info("Grid crop mode: %dx%d cells (%dx%d each)", cols, rows, cell_w, cell_h)

        cells = []
        for r in range(rows):
            for c in range(cols):
                y0 = r * cell_h
                x0 = c * cell_w
                cell = img[:, y0:y0 + cell_h, x0:x0 + cell_w, :]
                cells.append(cell)

        while len(cells) < 9:
            cells.append(cells[-1])
        return tuple(cells[:9])
