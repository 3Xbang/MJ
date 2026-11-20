"""
AFE_NineViewPromptBuilder — 九视图提示词自动生成器

用户只需填写一段角色描述，节点自动生成
符合 Qwen Image 2.1 [Image_1]~[Image_9] 格式的完整提示词。

结构：
  [Image_1] = 角色描述（动态输入，来自 Cast Analyzer）
  [Image_2]~[Image_9] = 完全写死的角度描述（不含角色信息）

9个固定视角：
  1. 三视图（正面/背面/侧面合一）—— image_1 slot: 人物外貌描述
  2. 正面全身                     —— image_2 slot: pose_01_front_full.png
  3. 背面全身                     —— image_3 slot: pose_02_back_full.png
  4. 侧面全身（90度）              —— image_4 slot: pose_03_side_full.png
  5. 面部特写 · 中性表情            —— image_5 slot: pose_04_face_neutral.png
  6. 面部特写 · 开心微笑            —— image_6 slot: pose_05_face_smile.png
  7. 面部特写 · 严肃表情            —— image_7 slot: pose_06_face_serious.png
  8. 场景动作 · 坐着喝茶            —— image_8 slot: pose_07_sit_forward.png
  9. 场景动作 · 交叉双臂自信坐姿    —— image_9 slot: pose_08_sit_cross.png
"""
from __future__ import annotations
import logging

logger = logging.getLogger("AFE_NineViewPromptBuilder")

# ── [Image_1] 模板：只有这里含角色描述 {char} ─────────────────
# {char}  = 角色外貌描述（动态）
# {style} = 风格（动态）
IMAGE_1_TEMPLATE = (
    "{char}. "
    "Character design reference sheet. "
    "White background. {style}."
)

# ── [Image_2]~[Image_9]：完全写死，不含任何角色信息 ───────────
# 只描述角度/构图/表情，模型从 image_1 参考图 + [Image_1] 文本获取角色信息
# {style} 保留（让每张都维持相同渲染风格）
FIXED_VIEW_TEMPLATES = [
    # [Image_2] 正面全身
    "Same character as Image 1, full body FRONT VIEW. "
    "Standing straight, arms relaxed at sides. "
    "White background. {style}.",

    # [Image_3] 背面全身
    "Same character as Image 1, full body BACK VIEW. "
    "Standing, seen from directly behind, same outfit visible. "
    "White background. {style}.",

    # [Image_4] 侧面全身（90度）
    "Same character as Image 1, full body RIGHT SIDE PROFILE VIEW, 90 degrees. "
    "Standing, showing posture and silhouette from the side. "
    "White background. {style}.",

    # [Image_5] 面部特写 · 中性
    "Same character as Image 1, FACE CLOSE-UP portrait, head and shoulders only. "
    "Neutral calm expression, looking directly at camera. "
    "Blue sky soft background. {style}.",

    # [Image_6] 面部特写 · 微笑
    "Same character as Image 1, FACE CLOSE-UP portrait, head and shoulders only. "
    "Big warm happy smile, eyes crinkling with joy, teeth showing. "
    "Blue sky soft background. {style}.",

    # [Image_7] 面部特写 · 严肃
    "Same character as Image 1, FACE CLOSE-UP portrait, head and shoulders only. "
    "Serious sharp authoritative expression, eyebrows slightly furrowed, direct eye contact. "
    "Blue sky soft background. {style}.",

    # [Image_8] 场景 · 坐着喝茶
    "Same character as Image 1, MEDIUM SHOT. "
    "Sitting comfortably on a wooden chair on a sunny beach terrace, "
    "holding a glass of tea with both hands and blowing on it gently. "
    "Palm trees and ocean in background. {style}.",

    # [Image_9] 场景 · 自信坐姿
    "Same character as Image 1, MEDIUM SHOT. "
    "Sitting at a wooden table, arms crossed over chest, "
    "leaning back confidently, relaxed wise smile. "
    "Sunny beach background. {style}.",
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

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "nine_view_prompt",   # [Image_1]~[Image_9] 完整提示词 → 接 Qwen
        "negative_prompt",    # 负向提示词
        "prompt_preview",     # 文字预览
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
            return {"ui": {"text": [msg]}, "result": ("", negative_prompt, msg)}

        # ── [Image_1]：角色描述（动态）────────────────────────────
        image1 = IMAGE_1_TEMPLATE.replace("{char}", char).replace("{style}", style)
        parts = [f"[Image_1] {image1}"]

        # ── [Image_2]~[Image_9]：完全写死（不含角色信息）──────────
        view_names = [
            "三视图合一",    # [Image_1] ← 只有这里有角色描述
            "正面全身",      # [Image_2]
            "背面全身",      # [Image_3]
            "侧面全身",      # [Image_4]
            "面部·中性",    # [Image_5]
            "面部·微笑",    # [Image_6]
            "面部·严肃",    # [Image_7]
            "场景·喝茶",    # [Image_8]
            "场景·自信坐姿",# [Image_9]
        ]
        for i, template in enumerate(FIXED_VIEW_TEMPLATES):
            filled = template.replace("{style}", style)
            parts.append(f"[Image_{i+2}] {filled}")   # i+2: Image_2 ~ Image_9

        nine_view_prompt = "\n\n".join(parts)
        neg = negative_prompt.strip() or (
            "photorealistic, real person, ugly, deformed, "
            "blurry, bad anatomy, watermark, text, 2d, sketch"
        )

        # 预览
        lines = ["🎭 九视图提示词已生成", "━" * 40]
        lines.append(f"[Image_1] 角色描述（动态）：")
        lines.append(f"  {char[:80]}{'...' if len(char)>80 else ''}")
        lines.append(f"风格：{style[:50]}")
        lines.append("━" * 40)
        lines.append("[Image_2]~[Image_9] 固定写死（不含角色信息）：")
        for i, name in enumerate(view_names[1:], 2):
            lines.append(f"  [Image_{i}] {name}")
        lines.append("━" * 40)
        lines.append("✅ nine_view_prompt → Qwen PE 节点的 prompt 输入")
        lines.append("⚠️  image_1 slot = 上传角色参考照片")
        lines.append("⚠️  image_2~9 slots = 已连接姿势参考图（固定不变）")

        preview = "\n".join(lines)
        logger.info("NineViewPromptBuilder: char=%s... style=%s", char[:40], style[:20])

        return {
            "ui": {"text": [preview]},
            "result": (nine_view_prompt, neg, preview),
        }
