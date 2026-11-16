"""
AFE_BatchImageGenerator
批量图像生成节点。

接受任意 Analyzer 输出的 JSON（characters_json / scenes_json /
costumes_json / props_json），为每个资产自动生成一张图片并保存，
最终返回批量 IMAGE 供 ComfyUI 预览。

使用 ComfyUI 内置的采样 API，无需额外依赖。
"""

from __future__ import annotations
import json
import os
import re
import torch
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_BatchImageGenerator")


def _safe_filename(text: str, maxlen: int = 40) -> str:
    """Convert any string to a filesystem-safe ASCII/Chinese name."""
    s = re.sub(r'[\\/:*?"<>|]', "_", text)
    return s[:maxlen]


def _encode_text(clip, text: str):
    """Encode a text prompt into CONDITIONING format."""
    tokens = clip.tokenize(text)
    out = clip.encode_from_tokens(tokens, return_pooled=True, return_dict=True)
    cond = out.pop("cond")
    return [[cond, out]]


def _make_latent(height: int, width: int, latent_channels: int = 16):
    """Create an empty latent tensor (16ch for Flux/SD3, 4ch for SD/SDXL)."""
    return {"samples": torch.zeros([1, latent_channels, height // 8, width // 8])}


class AFE_BatchImageGenerator:
    """
    批量图像生成器。

    从任意分析器的 JSON 输出（characters_json / scenes_json /
    costumes_json / props_json）中读取所有资产，
    依次为每个资产生成一张图片，保存到 ComfyUI 输出目录，
    并返回批量 IMAGE 供预览。

    使用方法：
    - assets_json ← 任意 Analyzer 的 JSON 输出
    - model / clip / vae ← 标准加载器
    - 调整 steps / cfg 适配不同模型（Flux schnell: steps=4, cfg=1）
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "assets_json": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "tooltip": "来自 Cast/Scene/Costume/Props Analyzer 的 JSON 字符串",
                }),
                "model":  ("MODEL",),
                "clip":   ("CLIP",),
                "vae":    ("VAE",),
            },
            "optional": {
                "width":  ("INT",   {"default": 1024, "min": 64, "max": 4096, "step": 8}),
                "height": ("INT",   {"default": 1024, "min": 64, "max": 4096, "step": 8}),
                "steps":  ("INT",   {"default": 4,    "min": 1,  "max": 100}),
                "cfg":    ("FLOAT", {"default": 1.0,  "min": 0.0,"max": 20.0, "step": 0.1}),
                "seed":   ("INT",   {"default": 42,   "min": 0,  "max": 2**31 - 1}),
                "sampler_name": (
                    ["euler", "euler_cfg_pp", "dpm_2", "dpmpp_2m",
                     "dpmpp_3m_sde", "dpmpp_2m_sde"],
                    {"default": "euler"}
                ),
                "scheduler": (
                    ["simple", "normal", "karras", "exponential", "sgm_uniform"],
                    {"default": "simple"}
                ),
                "latent_channels": ("INT", {
                    "default": 16, "min": 4, "max": 64, "step": 4,
                    "tooltip": "Flux/SD3=16, SD/SDXL=4",
                }),
                "variations_per_asset": ("INT", {
                    "default": 3, "min": 1, "max": 10,
                    "tooltip": "每个资产生成几张供选择（1=只生成1张，3=生成3个方案）",
                }),
                "output_prefix": ("STRING", {"default": "AFE"}),
                "max_assets": ("INT", {
                    "default": 0, "min": 0, "max": 200,
                    "tooltip": "最多生成几个资产（0=全部）",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "STRING")
    RETURN_NAMES = ("images", "count", "report")
    FUNCTION = "generate_batch"
    CATEGORY = "AI Film Editor/Generation"
    OUTPUT_NODE = True

    # ── Main entry ────────────────────────────────────────────────────────────
    def generate_batch(
        self,
        assets_json: str,
        model,
        clip,
        vae,
        width: int = 1024,
        height: int = 1024,
        steps: int = 4,
        cfg: float = 1.0,
        seed: int = 42,
        sampler_name: str = "euler",
        scheduler: str = "simple",
        latent_channels: int = 16,
        variations_per_asset: int = 3,
        output_prefix: str = "AFE",
        max_assets: int = 0,
    ):
        # ── Parse assets ──────────────────────────────────────────────────────
        try:
            assets = json.loads(assets_json)
        except Exception as exc:
            msg = f"❌ JSON 解析失败：{exc}"
            logger.error(msg)
            blank = torch.zeros([1, height, width, 3])
            return {"ui": {"text": [msg]}, "result": (blank, 0, msg)}

        if not isinstance(assets, list) or not assets:
            msg = "⚠️ 资产列表为空，请先连接分析器节点并运行"
            logger.warning(msg)
            blank = torch.zeros([1, height, width, 3])
            return {"ui": {"text": [msg]}, "result": (blank, 0, msg)}

        if max_assets > 0:
            assets = assets[:max_assets]

        total = len(assets)
        logger.info(
            f"BatchGenerator: {total} 个资产 × {variations_per_asset} 张 "
            f"= {total * variations_per_asset} 张图，{width}×{height}"
        )

        # ── Import ComfyUI KSampler internals ─────────────────────────────────
        try:
            from nodes import common_ksampler  # type: ignore
        except ImportError:
            # Fallback: use comfy.sample directly
            common_ksampler = None

        # ── Generation loop ───────────────────────────────────────────────────
        all_images: list[torch.Tensor] = []
        success_names: list[str] = []
        errors: list[str] = []

        for i, asset in enumerate(assets):
            idx = i + 1
            pos_text = str(asset.get("positive_prompt", "")).strip()
            neg_text = str(asset.get("negative_prompt", "")).strip() or "ugly, blurry, low quality"
            name = (
                asset.get("name")
                or asset.get("character_name")
                or asset.get("description", "")[:20]
                or f"asset_{idx:02d}"
            )

            if not pos_text:
                errors.append(f"资产{idx} ({name})：positive_prompt 为空，跳过")
                continue

            # Encode prompts once per asset, reuse across variations
            try:
                positive = _encode_text(clip, pos_text)
                negative = _encode_text(clip, neg_text)
            except Exception as exc:
                errors.append(f"资产{idx} ({name}) 编码失败：{exc}")
                continue

            # Generate N variations with different seeds
            for v in range(variations_per_asset):
                var_seed = seed + i * 1000 + v * 100
                var_label = f"v{v + 1}" if variations_per_asset > 1 else ""
                logger.info(f"  [{idx}/{total}] {name} {var_label}  seed={var_seed}")

                try:
                    latent = _make_latent(height, width, latent_channels)

                    if common_ksampler is not None:
                        latent_out = common_ksampler(
                            model, var_seed, steps, cfg,
                            sampler_name, scheduler,
                            positive, negative, latent,
                        )
                        latent_samples = latent_out[0]["samples"]
                    else:
                        latent_samples = self._fallback_sample(
                            model, positive, negative, latent,
                            var_seed, steps, cfg, sampler_name, scheduler,
                        )

                    img = vae.decode(latent_samples)
                    all_images.append(img)
                    file_label = f"{name}_{var_label}" if var_label else name
                    success_names.append(file_label)
                    self._save(img, output_prefix, idx, file_label)

                except Exception as exc:
                    err = f"资产{idx} ({name}) {var_label} 生成失败：{exc}"
                    logger.error(err)
                    errors.append(err)

        # ── Assemble result ───────────────────────────────────────────────────
        if not all_images:
            msg = "❌ 所有资产生成均失败\n" + "\n".join(errors)
            blank = torch.zeros([1, height, width, 3])
            return {"ui": {"text": [msg]}, "result": (blank, 0, msg)}

        batch = torch.cat(all_images, dim=0)   # [N, H, W, 3]

        lines = [
            f"✅ 批量生成完成：{len(all_images)} 张（{total} 个资产 × {variations_per_asset} 方案）",
            f"   尺寸：{width}×{height}  步数：{steps}  CFG：{cfg}",
            "──────────────",
        ]
        for j, n in enumerate(success_names):
            lines.append(f"  {j+1:02d}. {n}")
        if errors:
            lines.append("──────────────")
            lines.extend(errors)

        report = "\n".join(lines)
        logger.info(f"BatchGenerator done: {len(all_images)} images generated")

        return {
            "ui": {"text": [report]},
            "result": (batch, len(all_images), report),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _fallback_sample(self, model, positive, negative, latent,
                         seed, steps, cfg, sampler_name, scheduler):
        """Direct comfy.sample call when common_ksampler is unavailable."""
        import comfy.sample     # type: ignore
        import comfy.samplers   # type: ignore

        latent_img = latent["samples"]
        noise = comfy.sample.prepare_noise(latent_img, seed, None)
        samples = comfy.sample.sample(
            model, noise, steps, cfg, sampler_name, scheduler,
            positive, negative, latent_img,
            denoise=1.0, disable_noise=False,
            start_step=None, last_step=None,
            force_full_denoise=True, noise_mask=None,
            callback=None, disable_pbar=True, seed=seed,
        )
        return samples

    def _save(self, img_tensor: torch.Tensor, prefix: str, idx: int, name: str):
        """Save a single image tensor to ComfyUI's output directory."""
        try:
            import folder_paths   # type: ignore
            import numpy as np
            from PIL import Image  # type: ignore

            out_dir = folder_paths.get_output_directory()
            safe_name = _safe_filename(name)
            filename = f"{prefix}_{idx:02d}_{safe_name}.png"
            path = os.path.join(out_dir, filename)

            # img_tensor shape: [1, H, W, 3], float 0-1
            arr = (img_tensor[0].cpu().numpy() * 255).clip(0, 255).astype("uint8")
            Image.fromarray(arr).save(path)
            logger.info(f"    → 已保存：{filename}")
        except Exception as exc:
            logger.warning(f"    ⚠️ 保存失败：{exc}")
