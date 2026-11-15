"""多角色 IP-Adapter 混合节点—将多个角色参考图合并。"""
from __future__ import annotations
import os
import torch
import numpy as np
from PIL import Image

class AFE_MultiCharacterBlend:
    """
    多角色 IP-Adapter 混合节点。
    将多个角色参考图合并，输出给 IPAdapterAdvanced 使用。
    支持最多 3 个角色同时出现在一个分镜中。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence":  ("SHOT_SEQUENCE",),
                "shot_id":        ("STRING", {"default": "shot_001"}),
            },
            "optional": {
                "character_1":    ("CHARACTER_ASSET",),
                "character_2":    ("CHARACTER_ASSET",),
                "character_3":    ("CHARACTER_ASSET",),
                "blend_mode":     (["stack_vertical", "stack_horizontal", "primary_only"],
                                  {"default": "primary_only",
                                   "tooltip": "primary_only=只用第一个角色，stack=将多角色参考图拼接"}),
                "enable_blend":   ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("blended_reference", "blend_status")
    FUNCTION = "blend_characters"
    CATEGORY = "AI Film Editor/Consistency"
    OUTPUT_NODE = True

    def blend_characters(self, shot_sequence, shot_id,
                         character_1=None, character_2=None, character_3=None,
                         blend_mode="primary_only", enable_blend=True):
        # 1. If enable_blend=False, return blank + status
        if not enable_blend:
            blank = torch.zeros((1, 512, 512, 3), dtype=torch.float32)
            return (blank, "⚠️ 混合已禁用，返回空白图")

        # 2. Collect character assets in order
        chars = [c for c in [character_1, character_2, character_3] if c is not None]

        if not chars:
            blank = torch.zeros((1, 512, 512, 3), dtype=torch.float32)
            return (blank, f"⚠️ 分镜 {shot_id} 未提供角色资产")

        # 3. Load reference images from CHARACTER_ASSET dicts
        ref_images, char_names = [], []
        for c in chars:
            name, img = "角色", None
            if isinstance(c, dict):
                name = c.get("name", "角色")
                ref_path = c.get("primary_view") or c.get("reference_image")
                if ref_path and os.path.exists(ref_path):
                    try:
                        img = Image.open(ref_path).convert("RGB").resize((512, 512))
                    except Exception:
                        pass
            if img is None:
                img = Image.new("RGB", (512, 512), (200, 200, 200))
            ref_images.append(img)
            char_names.append(name)

        # 4. Blend
        if blend_mode == "primary_only" or len(ref_images) == 1:
            final_img = ref_images[0]
            status = (
                "⚠️ 分镜只有1个角色，直接使用单角色参考图"
                if len(ref_images) == 1
                else f"✅ 主角色：{char_names[0]} | 模式：仅主角色"
            )
        elif blend_mode == "stack_vertical":
            w = max(i.size[0] for i in ref_images)
            canvas = Image.new("RGB", (w, sum(i.size[1] for i in ref_images)), (255, 255, 255))
            y = 0
            for i in ref_images:
                canvas.paste(i.resize((w, i.size[1])), (0, y))
                y += i.size[1]
            final_img = canvas
            status = f"✅ 多角色混合：{'  + '.join(char_names)} | 模式：垂直拼接 | 输出尺寸：{canvas.size[0]}×{canvas.size[1]}"
        else:  # stack_horizontal
            h = max(i.size[1] for i in ref_images)
            canvas = Image.new("RGB", (sum(i.size[0] for i in ref_images), h), (255, 255, 255))
            x = 0
            for i in ref_images:
                canvas.paste(i.resize((i.size[0], h)), (x, 0))
                x += i.size[0]
            final_img = canvas
            status = f"✅ 多角色混合：{' + '.join(char_names)} | 模式：水平拼接 | 输出尺寸：{canvas.size[0]}×{canvas.size[1]}"

        arr = np.array(final_img).astype(np.float32) / 255.0
        return (torch.from_numpy(arr).unsqueeze(0), status)
