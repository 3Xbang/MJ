"""
AFE_SingleAssetGenerator
单资产图像生成节点。

从任意 Analyzer 的 JSON 中选取指定编号的资产，
生成单张图像。每次运行使用不同 seed，
客户不满意直接再次运行直到满意为止。

用法：
  - assets_json ← Cast/Scene/Costume/Props Analyzer 的 JSON 输出
  - asset_index ← 选第几号资产（1开始）
  - seed_mode   ← fixed（固定seed）/ random（每次自动随机）
  - model/clip/vae ← 标准模型加载器
  - 点运行 → 出图；不满意直接再点运行
"""
from __future__ import annotations
import json
import random
import torch
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_SingleAssetGenerator")


def _encode_text(clip, text: str):
    tokens = clip.tokenize(text)
    out = clip.encode_from_tokens(tokens, return_pooled=True, return_dict=True)
    cond = out.pop("cond")
    return [[cond, out]]


def _make_latent(height: int, width: int, latent_channels: int = 16):
    return {"samples": torch.zeros([1, latent_channels, height // 8, width // 8])}


class AFE_SingleAssetGenerator:
    """
    单资产图像生成器（客户审批专用）。

    选定一个资产编号，每次运行生成一张新图。
    seed_mode=random 时每次自动换 seed，给客户多个方案直到选定。
    确认后记下 seed 编号，下次可用 fixed 模式复现同一张图。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "assets_json": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "tooltip": "来自任意 Analyzer 的 JSON 输出",
                }),
                "asset_index": ("INT", {
                    "default": 1, "min": 1, "max": 500,
                    "tooltip": "选第几号资产（从1开始）",
                }),
                "model": ("MODEL",),
                "clip":  ("CLIP",),
                "vae":   ("VAE",),
            },
            "optional": {
                "seed": ("INT", {
                    "default": 42, "min": 0, "max": 2**31 - 1,
                    "tooltip": "固定seed时使用；random模式下此值被忽略",
                }),
                "seed_mode": (["random", "fixed"], {
                    "default": "random",
                    "tooltip": "random=每次自动换seed（给客户多个方案）；fixed=复现指定seed的图",
                }),
                "width":  ("INT", {"default": 1024, "min": 64, "max": 4096, "step": 8}),
                "height": ("INT", {"default": 1024, "min": 64, "max": 4096, "step": 8}),
                "steps":  ("INT", {"default": 4,    "min": 1,  "max": 100}),
                "cfg":    ("FLOAT", {"default": 1.0, "min": 0.0, "max": 20.0, "step": 0.1}),
                "sampler_name": (
                    ["euler", "euler_cfg_pp", "dpm_2", "dpmpp_2m", "dpmpp_3m_sde"],
                    {"default": "euler"}
                ),
                "scheduler": (
                    ["simple", "normal", "karras", "exponential"],
                    {"default": "simple"}
                ),
                "latent_channels": ("INT", {
                    "default": 16, "min": 4, "max": 64, "step": 4,
                    "tooltip": "Flux/SD3=16, SD/SDXL=4",
                }),
                "output_prefix": ("STRING", {"default": "AFE_Single"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "INT")
    RETURN_NAMES = (
        "image",           # 生成的图像
        "positive_prompt", # 使用的正向提示词
        "asset_name",      # 资产名称
        "used_seed",       # 本次使用的 seed（方便客户确认后记录）
    )
    FUNCTION = "generate_single"
    CATEGORY = "AI Film Editor/Generation"
    OUTPUT_NODE = True

    def generate_single(
        self,
        assets_json: str,
        asset_index: int,
        model,
        clip,
        vae,
        seed: int = 42,
        seed_mode: str = "random",
        width: int = 1024,
        height: int = 1024,
        steps: int = 4,
        cfg: float = 1.0,
        sampler_name: str = "euler",
        scheduler: str = "simple",
        latent_channels: int = 16,
        output_prefix: str = "AFE_Single",
    ):
        # ── 解析资产列表 ──────────────────────────────────────────────────────
        try:
            assets = json.loads(assets_json)
        except Exception as exc:
            msg = f"❌ JSON 解析失败：{exc}"
            blank = torch.zeros([1, height, width, 3])
            return {"ui": {"text": [msg]}, "result": (blank, "", "", 0)}

        if not isinstance(assets, list) or not assets:
            msg = "⚠️ 资产列表为空，请先连接分析器节点"
            blank = torch.zeros([1, height, width, 3])
            return {"ui": {"text": [msg]}, "result": (blank, "", "", 0)}

        # ── 选取资产 ──────────────────────────────────────────────────────────
        idx = max(1, min(asset_index, len(assets)))
        asset = assets[idx - 1]

        pos_text = str(asset.get("positive_prompt", "")).strip()
        neg_text = str(asset.get("negative_prompt", "ugly, blurry, low quality")).strip()
        name = (
            asset.get("name")
            or asset.get("character_name")
            or asset.get("description", "")[:30]
            or f"asset_{idx:02d}"
        )

        # 角色额外信息
        role_type = asset.get("role_type", "")
        role_label = {"lead": "主角", "supporting": "配角",
                      "extra_a": "路人甲", "extra_b": "路人乙"}.get(role_type, role_type)

        if not pos_text:
            msg = f"⚠️ 资产 {idx} ({name}) 没有 positive_prompt"
            blank = torch.zeros([1, height, width, 3])
            return {"ui": {"text": [msg]}, "result": (blank, "", name, 0)}

        # ── 确定 seed ─────────────────────────────────────────────────────────
        actual_seed = random.randint(0, 2**31 - 1) if seed_mode == "random" else seed
        logger.info(f"SingleGen: [{idx}/{len(assets)}] {name}  seed={actual_seed}  mode={seed_mode}")

        # ── 生成图像 ──────────────────────────────────────────────────────────
        try:
            positive = _encode_text(clip, pos_text)
            negative = _encode_text(clip, neg_text)
            latent   = _make_latent(height, width, latent_channels)

            try:
                from nodes import common_ksampler  # type: ignore
                latent_out     = common_ksampler(
                    model, actual_seed, steps, cfg,
                    sampler_name, scheduler,
                    positive, negative, latent,
                )
                latent_samples = latent_out[0]["samples"]
            except ImportError:
                latent_samples = self._fallback_sample(
                    model, positive, negative, latent,
                    actual_seed, steps, cfg, sampler_name, scheduler,
                )

            img = vae.decode(latent_samples)

        except Exception as exc:
            msg = f"❌ 生成失败：{exc}"
            logger.error(msg)
            blank = torch.zeros([1, height, width, 3])
            return {"ui": {"text": [msg]}, "result": (blank, pos_text, name, actual_seed)}

        # ── 保存 ──────────────────────────────────────────────────────────────
        self._save(img, output_prefix, idx, name, actual_seed)

        # ── 报告 ──────────────────────────────────────────────────────────────
        lines = [
            f"✅ {name}" + (f"（{role_label}）" if role_label else ""),
            f"   资产编号：{idx} / {len(assets)}",
            f"   Seed：{actual_seed}  模式：{seed_mode}",
            f"   提示词：{pos_text[:100]}{'...' if len(pos_text) > 100 else ''}",
            "",
            "💡 不满意？直接再次运行（random模式自动换seed）",
            "   满意后记下上方 Seed 编号，切换 fixed 模式可复现此图",
        ]
        report = "\n".join(lines)

        return {
            "ui": {"text": [report]},
            "result": (img, pos_text, name, actual_seed),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _fallback_sample(self, model, positive, negative, latent,
                         seed, steps, cfg, sampler_name, scheduler):
        import comfy.sample   # type: ignore
        latent_img = latent["samples"]
        noise = comfy.sample.prepare_noise(latent_img, seed, None)
        return comfy.sample.sample(
            model, noise, steps, cfg, sampler_name, scheduler,
            positive, negative, latent_img,
            denoise=1.0, disable_noise=False,
            start_step=None, last_step=None,
            force_full_denoise=True, noise_mask=None,
            callback=None, disable_pbar=True, seed=seed,
        )

    def _save(self, img_tensor: torch.Tensor, prefix: str,
              idx: int, name: str, seed: int):
        try:
            import folder_paths  # type: ignore
            import numpy as np
            from PIL import Image  # type: ignore
            import os, re

            safe = re.sub(r'[\\/:*?"<>|]', "_", name)[:30]
            fname = f"{prefix}_{idx:02d}_{safe}_seed{seed}.png"
            path  = os.path.join(folder_paths.get_output_directory(), fname)
            arr   = (img_tensor[0].cpu().numpy() * 255).clip(0, 255).astype("uint8")
            Image.fromarray(arr).save(path)
            logger.info(f"Saved: {fname}")
        except Exception as exc:
            logger.warning(f"Save failed: {exc}")
