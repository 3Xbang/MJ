"""
AFE_NineViewPromptBuilder — 九视图提示词自动生成器

用户只需填写一段角色描述，节点自动生成
符合 Qwen Image 2.1 [Image_1]~[Image_9] 格式的完整提示词。

关键：每个 [Image_N] 都包含完整角色描述 + 对应角度描述。
（原版 10张.json 的正确格式，经测试可生成9个不同角度）

9个固定视角：
  1. 三视图（正面/背面/侧面合一）
  2. 正面全身
  3. 背面全身
  4. 侧面全身（90度）
  5. 面部特写 · 中性表情
  6. 面部特写 · 开心微笑
  7. 面部特写 · 严肃表情
  8. 场景动作 · 坐着喝茶
  9. 场景动作 · 交叉双臂自信坐姿
"""
from __future__ import annotations
import logging

logger = logging.getLogger("AFE_NineViewPromptBuilder")

# ── 9 个固定视角模板 ─────────────────────────────────────────
# {char}  = 角色外貌描述（每个 slot 都要有）
# {style} = 风格描述
VIEW_TEMPLATES = [
    # 1. 三视图合一
    "A high-quality 3D character design sheet showing THREE VIEWS side by side: "
    "front view on the left, back view in the center, right side profile on the right. "
    "{char}. White background. {style}.",

    # 2. 正面全身
    "Full body shot, FRONT VIEW, standing straight, arms relaxed at sides. "
    "{char}. White background. {style}.",

    # 3. 背面全身
    "Full body shot, BACK VIEW, standing, seen from directly behind, same outfit visible. "
    "{char}. White background. {style}.",

    # 4. 侧面全身（90度）
    "Full body shot, SIDE PROFILE VIEW, 90 degrees, standing, facing right. "
    "{char}. White background. {style}.",

    # 5. 面部特写 · 中性
    "FACE CLOSE-UP portrait, head and shoulders. "
    "Neutral calm expression, looking directly at camera. "
    "{char}. Blue sky background. {style}.",

    # 6. 面部特写 · 微笑
    "FACE CLOSE-UP portrait, head and shoulders. "
    "Big warm happy smile, eyes crinkling with joy, teeth showing. "
    "{char}. Blue sky background. {style}.",

    # 7. 面部特写 · 严肃
    "FACE CLOSE-UP portrait, head and shoulders. "
    "Serious sharp authoritative expression, eyebrows slightly furrowed, direct eye contact. "
    "{char}. Blue sky background. {style}.",

    # 8. 场景 · 坐着喝茶
    "MEDIUM SHOT. Sitting comfortably on wooden chair, sunny beach terrace, "
    "holding a glass of tea with both hands and blowing on it gently. "
    "{char}. Palm trees and ocean in background. {style}.",

    # 9. 场景 · 自信坐姿
    "MEDIUM SHOT. Sitting at a wooden table, "
    "arms crossed over chest, leaning back confidently, relaxed wise smile. "
    "{char}. Sunny beach background. {style}.",
]

DEFAULT_STYLE = "3D cartoon style, Pixar animation, vibrant colors, 8k, highly detailed"


class AFE_NineViewPromptBuilder:
    """
    九视图提示词自动生成器。

    只填写一段角色描述，自动生成9个固定视角的提示词，
    输出 [Image_1]~[Image_9] 格式，直接接 Qwen Image 2.1 节点。

    用户不需要写9段提示词，只需描述角色即可。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character_description": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": (
                        "填写角色外貌描述（一段即可，自动生成9张图的提示词）\n"
                        "例：50-year-old chubby Asian man, shoulder-length wavy "
                        "silver-grey hair, handlebar mustache, white T-shirt, "
                        "thick gold chain necklace, beige GG-pattern shorts, "
                        "brown wooden bead bracelets, brown sandals"
                    ),
                }),
            },
            "optional": {
                "style_suffix": ("STRING", {
                    "default": DEFAULT_STYLE,
                    "tooltip": "风格描述，默认 Pixar 3D 卡通风格",
                }),
                "negative_prompt": ("STRING", {
                    "default": (
                        "photorealistic, real person, ugly, deformed, "
                        "blurry, bad anatomy, watermark, text, 2d, sketch"
                    ),
                    "tooltip": "负向提示词",
                }),
            },
        }

    RETURN_TYPES = ("STRING",) * 9 + ("STRING", "STRING")
    RETURN_NAMES = (
        "prompt_1_设计参考图",
        "prompt_2_正面全身",
        "prompt_3_侧面全身",
        "prompt_4_面部中性",
        "prompt_5_面部微笑",
        "prompt_6_面部严肃",
        "prompt_7_场景喝茶",
        "prompt_8_场景指向",
        "prompt_9_场景自信坐",
        "negative_prompt",
        "prompt_preview",
    )
    FUNCTION = "build_prompts"
    CATEGORY = "AI Film Editor/Character Card"
    OUTPUT_NODE = True

    def build_prompts(
        self,
        character_description: str,
        style_suffix: str = DEFAULT_STYLE,
        negative_prompt: str = "",
    ):
        char = character_description.strip()
        style = style_suffix.strip() or DEFAULT_STYLE

        if not char:
            msg = "⚠️ 请填写角色描述"
            empty = ("",) * 9
            return {"ui": {"text": [msg]}, "result": empty + (negative_prompt, msg)}

        # 生成 9 个独立提示词，每个包含完整角色描述 + 对应视角描述
        view_names = [
            "角色设计参考图", "正面全身", "侧面全身",
            "面部·中性", "面部·微笑", "面部·严肃",
            "场景·喝茶", "场景·指向", "场景·自信坐",
        ]
        prompts = []
        for template in VIEW_TEMPLATES:
            filled = "[Image_1] " + template.replace("{char}", char).replace("{style}", style)
            prompts.append(filled)

        neg = negative_prompt.strip() or (
            "photorealistic, real person, ugly, deformed, "
            "blurry, bad anatomy, watermark, text, 2d, sketch"
        )

        # 预览
        lines = ["🎭 九视图提示词已生成（9个独立输出）", "━" * 40]
        lines.append(f"角色描述: {char[:60]}{'...' if len(char)>60 else ''}")
        lines.append(f"风格: {style[:40]}")
        lines.append("━" * 40)
        lines.append("输出接口:")
        for i, name in enumerate(view_names):
            lines.append(f"  prompt_{i+1} → Qwen节点_{i+1} ({name})")
        lines.append("━" * 40)
        lines.append("✅ 每个 prompt_N 直接接对应 Qwen 节点的 prompt 输入")
        lines.append("⚠️  视角描述已写死，只需修改 character_description")

        preview = "\n".join(lines)
        logger.info("NineViewPromptBuilder: 9 prompts for: %s...", char[:40])

        return {
            "ui": {"text": [preview]},
            "result": tuple(prompts) + (neg, preview),
        }

