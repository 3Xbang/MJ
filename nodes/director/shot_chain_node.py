from __future__ import annotations
import os
import numpy as np
import torch
from PIL import Image
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotChain")


class AFE_ShotChain:
    """
    尾帧接力节点。提取当前分镜渲染结果的最后一帧并保存，同时返回下一个分镜 ID。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "current_shot_id": ("STRING", {"default": "shot_001"}),
                "rendered_frames": ("IMAGE",),
                "shot_sequence":   ("SHOT_SEQUENCE",),
            },
            "optional": {
                "output_dir": ("STRING", {"default": "./projects/tail_frames"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("tail_frame", "next_shot_id", "chain_status")
    FUNCTION = "process_chain"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def process_chain(self, current_shot_id, rendered_frames, shot_sequence,
                      output_dir="./projects/tail_frames"):
        # rendered_frames is a [B,H,W,C] float32 torch tensor (values 0-1)
        tail_tensor = rendered_frames[-1:]  # shape [1,H,W,C]

        os.makedirs(output_dir, exist_ok=True)
        tail_path = os.path.join(output_dir, f"{current_shot_id}_tail.png")
        arr = (tail_tensor[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        Image.fromarray(arr).save(tail_path)

        def _get_id(s):
            return s.get("shot_id", "") if isinstance(s, dict) else getattr(s, "shot_id", "")

        ids = [_get_id(s) for s in shot_sequence]
        try:
            idx = ids.index(current_shot_id)
            next_shot_id = ids[idx + 1] if idx + 1 < len(ids) else "(END)"
        except ValueError:
            next_shot_id = "unknown"

        chain_status = f"✅ {current_shot_id} 尾帧已保存 → {next_shot_id} 准备就绪"
        logger.info(f"ShotChain: {current_shot_id} → {next_shot_id}, tail saved to {tail_path}")
        return (tail_tensor, next_shot_id, chain_status)
