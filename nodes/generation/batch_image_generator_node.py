"""
AFE_BatchImageGenerator
批量图像生成节点。

每个资产固定生成 6 张不同方案（内部固定，不作为参数暴露）。
客户从 6 张中选择满意的方案。
采样参数（sampler/scheduler/latent_channels）内部固定为 Flux Schnell 最优设置。
"""
from __future__ import annotations
import json, os, re
import torch
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_BatchImageGenerator")

# 固定内部参数 — 不作为 widget 暴露，避免 ComfyUI 验证问题
_SAMPLER       = "euler"
_SCHEDULER     = "simple"
_LATENT_CH     = 16    # Flux 使用 16 通道
_VARIATIONS    = 6     # 每个资产固定生成 6 张方案


def _safe(text: str, maxlen: int = 40) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", text)[:maxlen]


def _encode(clip, text: str):
    tokens = clip.tokenize(text)
    out = clip.encode_from_tokens(tokens, return_pooled=True, return_dict=True)
    cond = out.pop("cond")
    return [[cond, out]]


def _latent(h: int, w: int):
    return {"samples": torch.zeros([1, _LATENT_CH, h // 8, w // 8])}


class AFE_BatchImageGenerator:
    """
    批量图像生成器。
    从任意 Analyzer 的 JSON 中读取所有资产，为每个资产生成 N 张图片，
    保存到 ComfyUI 输出目录，并返回批量 IMAGE 供预览。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "assets_json": ("STRING", {
                    "multiline": True, "default": "[]",
                    "tooltip": "来自 Cast/Scene/Costume/Props Analyzer 的 JSON 输出",
                }),
                "model": ("MODEL",),
                "clip":  ("CLIP",),
                "vae":   ("VAE",),
            },
            "optional": {
                "width":         ("INT",   {"default": 1024, "min": 64,  "max": 4096, "step": 8}),
                "height":        ("INT",   {"default": 1024, "min": 64,  "max": 4096, "step": 8}),
                "steps":         ("INT",   {"default": 4,    "min": 1,   "max": 100}),
                "cfg":           ("FLOAT", {"default": 1.0,  "min": 0.0, "max": 20.0, "step": 0.1}),
                "seed":          ("INT",   {"default": 42,   "min": 0,   "max": 2**31 - 1}),
                "output_prefix": ("STRING", {"default": "AFE"}),
                "max_assets":    ("INT",   {"default": 0,    "min": 0,   "max": 200,
                                            "tooltip": "0=生成全部资产"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "STRING")
    RETURN_NAMES = ("images", "count", "report")
    FUNCTION = "generate_batch"
    CATEGORY = "AI Film Editor/Generation"
    OUTPUT_NODE = True

    def generate_batch(
        self,
        assets_json: str,
        model, clip, vae,
        width: int = 1024, height: int = 1024,
        steps: int = 4,   cfg: float = 1.0,
        seed: int = 42,
        output_prefix: str = "AFE",
        max_assets: int = 0,
    ):
        try:
            assets = json.loads(assets_json)
        except Exception as exc:
            msg = f"❌ JSON 解析失败：{exc}"
            return {"ui": {"text": [msg]}, "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        if not isinstance(assets, list) or not assets:
            msg = "⚠️ 资产列表为空"
            return {"ui": {"text": [msg]}, "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        if max_assets > 0:
            assets = assets[:max_assets]

        total = len(assets)
        logger.info(f"BatchGen: {total} 资产 × {_VARIATIONS} 张 = {total * _VARIATIONS} 张")

        try:
            from nodes import common_ksampler  # type: ignore
            _ks = common_ksampler
        except ImportError:
            _ks = None

        all_images, names, errors = [], [], []

        for i, asset in enumerate(assets):
            pos = str(asset.get("positive_prompt", "")).strip()
            neg = str(asset.get("negative_prompt", "ugly, blurry, low quality")).strip()
            name = (asset.get("name") or asset.get("character_name")
                    or asset.get("description", "")[:20] or f"asset_{i+1:02d}")

            if not pos:
                errors.append(f"资产{i+1}({name})：prompt为空，跳过")
                continue

            try:
                positive = _encode(clip, pos)
                negative = _encode(clip, neg)
            except Exception as exc:
                errors.append(f"资产{i+1}({name}) 编码失败：{exc}")
                continue

            for v in range(_VARIATIONS):
                vseed = seed + i * 1000 + v * 137  # 质数步长确保每张都不同
                vlabel = f"v{v+1}" if variations_per_asset > 1 else ""
                try:
                    lat = _latent(height, width)
                    if _ks:
                        out = _ks(model, vseed, steps, cfg, _SAMPLER, _SCHEDULER, positive, negative, lat)
                        samples = out[0]["samples"]
                    else:
                        import comfy.sample  # type: ignore
                        noise = comfy.sample.prepare_noise(lat["samples"], vseed, None)
                        samples = comfy.sample.sample(
                            model, noise, steps, cfg, _SAMPLER, _SCHEDULER,
                            positive, negative, lat["samples"],
                            denoise=1.0, disable_noise=False,
                            force_full_denoise=True, seed=vseed,
                        )
                    img = vae.decode(samples)
                    all_images.append(img)
                    flabel = f"{name}_{vlabel}" if vlabel else name
                    names.append(flabel)
                    self._save(img, output_prefix, i + 1, flabel)
                except Exception as exc:
                    errors.append(f"资产{i+1}({name}){vlabel} 生成失败：{exc}")

        if not all_images:
            msg = "❌ 全部生成失败\n" + "\n".join(errors)
            return {"ui": {"text": [msg]}, "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        batch = torch.cat(all_images, dim=0)
        lines = [
            f"✅ 生成完成：{len(all_images)} 张（{total} 资产 × {_VARIATIONS} 方案）",
            f"   {width}×{height}  steps={steps}  cfg={cfg}",
            "──────────────",
        ] + [f"  {j+1:02d}. {n}" for j, n in enumerate(names)]
        if errors:
            lines += ["──────────────"] + errors
        report = "\n".join(lines)

        return {"ui": {"text": [report]}, "result": (batch, len(all_images), report)}

    def _save(self, img: torch.Tensor, prefix: str, idx: int, name: str):
        try:
            import folder_paths  # type: ignore
            import numpy as np
            from PIL import Image  # type: ignore
            path = os.path.join(
                folder_paths.get_output_directory(),
                f"{prefix}_{idx:02d}_{_safe(name)}.png"
            )
            Image.fromarray((img[0].cpu().numpy() * 255).clip(0, 255).astype("uint8")).save(path)
            logger.info(f"Saved: {os.path.basename(path)}")
        except Exception as exc:
            logger.warning(f"Save failed: {exc}")
