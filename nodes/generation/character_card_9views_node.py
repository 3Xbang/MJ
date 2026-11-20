"""
AFE_CharacterCard9Views — 单节点，1张参考图 → 9张独立视角图

内部调用 Qwen Image 2.1 Turbo 节点9次，每次1个视角。
9个固定视角模板写死，只有角色描述是动态输入。

输入:
  reference_image       — 角色参考照片
  character_description — 角色外貌描述（动态）

输出:
  view_1 ~ view_9       — 9张独立 IMAGE，每张对应1个视角
"""
from __future__ import annotations
import torch
import logging
import inspect

logger = logging.getLogger("AFE_CharacterCard9Views")

QWEN_NODE_TYPE = "bc1c967a-7f6a-4be9-a372-dad16e4f28e3"

# ─── 9个固定视角模板（写死，永不改变）────────────────────────────────────────
# {char} = 角色描述（动态），{style} = 风格（动态）
# 每个都放在 [Image_1] 里，因为每次只有一个输入槽
VIEW_TEMPLATES = [
    # 1. 角色设计参考图（综合）
    "[Image_1] Professional character design reference sheet on grey background. "
    "Left side: 3 full-body standing poses side by side — front view, back view, side profile. "
    "Top right: 4 face close-up portraits with different expressions — neutral, happy, serious, surprised. "
    "Middle right: 2 action medium shots — sitting drinking tea, sitting arms crossed. "
    "Bottom: running pose, silhouette, accessories. "
    "{char}. {style}.",

    # 2. 正面全身
    "[Image_1] Full body FRONT VIEW, standing straight, arms relaxed at sides. "
    "{char}. White background. {style}.",

    # 3. 侧面全身
    "[Image_1] Full body SIDE PROFILE VIEW, 90 degrees, standing, facing right. "
    "{char}. White background. {style}.",

    # 4. 面部·中性
    "[Image_1] FACE CLOSE-UP portrait, head and shoulders. "
    "Neutral calm expression, looking directly at camera. "
    "{char}. Blue sky soft background. {style}.",

    # 5. 面部·微笑
    "[Image_1] FACE CLOSE-UP portrait, head and shoulders. "
    "Big warm happy smile, eyes crinkling with joy, teeth showing. "
    "{char}. Blue sky soft background. {style}.",

    # 6. 面部·严肃
    "[Image_1] FACE CLOSE-UP portrait, head and shoulders. "
    "Serious sharp authoritative expression, eyebrows slightly furrowed. "
    "{char}. Blue sky soft background. {style}.",

    # 7. 场景·喝茶
    "[Image_1] MEDIUM SHOT. Sitting comfortably on wooden chair on sunny beach terrace, "
    "holding a glass of tea, blowing on it gently. Palm trees and ocean in background. "
    "{char}. {style}.",

    # 8. 场景·指向
    "[Image_1] MEDIUM SHOT, upper body. Sitting at table, raising right hand, "
    "pointing index finger forward assertively. Beach background. "
    "{char}. {style}.",

    # 9. 场景·自信坐
    "[Image_1] MEDIUM SHOT. Sitting at wooden table on beach, arms crossed over chest, "
    "leaning back confidently, smiling wisely. Sunny beach background. "
    "{char}. {style}.",
]

VIEW_NAMES = [
    "view_1_设计参考图",
    "view_2_正面全身",
    "view_3_侧面全身",
    "view_4_面部中性",
    "view_5_面部微笑",
    "view_6_面部严肃",
    "view_7_场景喝茶",
    "view_8_场景指向",
    "view_9_场景自信坐",
]

DEFAULT_STYLE = "3D cartoon Pixar animation style, vibrant colors, 8k, highly detailed"
DEFAULT_NEG   = (
    "photorealistic, real person, ugly, deformed, noisy, blurry, distorted, "
    "bad anatomy, bad hands, missing fingers, text, watermark, 2d, sketch, anime"
)

# ─── 默认 Qwen 模型文件 ────────────────────────────────────────────────────
DEFAULT_UNET   = "qwen_image_2.1_turbo_int8_convrot.safetensors"
DEFAULT_VAE    = "qwen_image_2.1_vae_bf16.safetensors"
DEFAULT_CLIP   = "qwen3vl_8b_int8_convrot.safetensors"
DEFAULT_PE     = "qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors"


def _get_qwen_class():
    """Find the Qwen Image 2.1 node class in ComfyUI's registry."""
    try:
        from nodes import NODE_CLASS_MAPPINGS
        cls = NODE_CLASS_MAPPINGS.get(QWEN_NODE_TYPE)
        if cls is not None:
            logger.info("[AFE] Qwen node found: %s, FUNCTION=%s",
                        cls.__name__, getattr(cls, "FUNCTION", "?"))
        return cls
    except Exception as e:
        logger.error("[AFE] Cannot access NODE_CLASS_MAPPINGS: %s", e)
        return None


def _call_qwen(qwen_cls, prompt: str, image: torch.Tensor,
               negative: str, seed: int,
               unet: str, vae: str, clip: str, pe: str) -> torch.Tensor:
    """
    Call the Qwen Image 2.1 Turbo node's execute function.
    Handles both old and new ComfyUI calling conventions.
    """
    func_name = getattr(qwen_cls, "FUNCTION", "execute")
    instance  = qwen_cls()
    func      = getattr(instance, func_name)

    # Discover actual parameter names
    sig    = inspect.signature(func)
    params = list(sig.parameters.keys())
    logger.debug("[AFE] Qwen params: %s", params)

    # Base kwargs (widget-based, always present)
    base_kwargs = dict(
        prompt           = prompt,
        switch_1         = False,   # refine_prompt
        thinking         = False,
        max_length       = 4096,
        negative_prompt  = negative,
        cfg              = 1.0,
        switch           = False,   # custom_size
        width            = 1024,
        height           = 1024,
        scheduler        = "euler",
        seed             = seed,
        unet_name        = unet,
        clip_name        = clip,
        vae_name         = vae,
        device           = "auto",
        dtype            = "default",
        clip_name_1      = pe,
    )

    # Try different conventions for the image_1 input
    # ComfyUI may use the full dotted name or just the last segment
    image_kwargs_options = [
        {"images.image_1": image},          # full dotted name via **
        {"image_1": image},                  # last segment only
        {"image": image},                    # simplified
    ]

    for img_kwargs in image_kwargs_options:
        try:
            result = func(**base_kwargs, **img_kwargs)
            # Extract IMAGE tensor from result
            if isinstance(result, (list, tuple)):
                out = result[0]
            elif isinstance(result, dict):
                out = result.get("result", [image])[0]
            else:
                out = result
            logger.info("[AFE] Qwen call succeeded with kwargs: %s",
                        list(img_kwargs.keys()))
            return out
        except TypeError as e:
            logger.warning("[AFE] Qwen call failed with %s: %s",
                           list(img_kwargs.keys()), e)
            continue

    raise RuntimeError(
        "Could not call Qwen node. Check /tmp/comfyui.log for details.\n"
        f"Function signature: {params}"
    )


class AFE_CharacterCard9Views:
    """
    一个节点，1张参考图 + 角色描述 → 9张独立视角图。
    内部调用 Qwen Image 2.1 Turbo 9次，每次1个视角。
    9个视角模板写死；只有 character_description 是动态输入。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reference_image": ("IMAGE", {
                    "tooltip": "角色参考照片（正面，白背景最佳）",
                }),
                "character_description": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": (
                        "角色外貌描述（来自 Cast Analyzer 的 appearance_en）\n"
                        "例: 50-year-old chubby Asian man, shoulder-length wavy "
                        "silver-grey hair, handlebar mustache..."
                    ),
                }),
            },
            "optional": {
                "style": ("STRING", {
                    "default": DEFAULT_STYLE,
                    "tooltip": "渲染风格（影响所有9张图）",
                }),
                "negative_prompt": ("STRING", {
                    "default": DEFAULT_NEG,
                }),
                "seed": ("INT", {
                    "default": 42, "min": 0, "max": 2 ** 31 - 1,
                    "tooltip": "每张图的 seed = seed + view_index * 1000",
                }),
            },
        }

    RETURN_TYPES  = ("IMAGE",) * 9
    RETURN_NAMES  = tuple(VIEW_NAMES)
    FUNCTION      = "generate"
    CATEGORY      = "AI Film Editor/Character Card"
    OUTPUT_NODE   = False

    def generate(
        self,
        reference_image: torch.Tensor,
        character_description: str,
        style: str = DEFAULT_STYLE,
        negative_prompt: str = DEFAULT_NEG,
        seed: int = 42,
        unet_name: str = DEFAULT_UNET,
        vae_name:  str = DEFAULT_VAE,
        clip_name: str = DEFAULT_CLIP,
        pe_model:  str = DEFAULT_PE,
    ):
        char = character_description.strip()
        if not char:
            raise ValueError("character_description 不能为空，请填写角色描述")

        qwen_cls = _get_qwen_class()
        if qwen_cls is None:
            raise RuntimeError(
                f"未找到 Qwen Image 2.1 Turbo 节点 (type={QWEN_NODE_TYPE})。\n"
                "请确认 ComfyUI 已安装 Qwen Image 2.1 插件，并重启 ComfyUI。"
            )

        results = []
        for i, (template, name) in enumerate(zip(VIEW_TEMPLATES, VIEW_NAMES)):
            prompt = template.replace("{char}", char).replace("{style}", style)
            logger.info("[AFE] 生成视角 %d/9: %s", i + 1, name)

            try:
                img = _call_qwen(
                    qwen_cls  = qwen_cls,
                    prompt    = prompt,
                    image     = reference_image,
                    negative  = negative_prompt,
                    seed      = seed + i * 1000,
                    unet      = unet_name,
                    vae       = vae_name,
                    clip      = clip_name,
                    pe        = pe_model,
                )
                results.append(img)
                logger.info("[AFE]   ✓ view %d shape=%s", i + 1, img.shape)

            except Exception as e:
                logger.error("[AFE]   ✗ view %d failed: %s", i + 1, e)
                # 失败时用参考图占位，不中断整个流程
                results.append(reference_image)

        return tuple(results)
