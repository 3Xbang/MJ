"""
AFE_BatchImageGenerator
批量图像生成节点。

每次运行为每个资产生成【1张】图片。
需要多个方案时，重复点运行即可——每次 seed 自动变化，保证不同。
这样与 ComfyUI 的执行模型完全一致：每个步数跑一次，出一组图。

用法：
  1. 点运行 → 每个资产出1张图
  2. 不满意某张 → 再点运行 → 自动出新图
  3. 记录满意那次的 seed → 下次用 fixed seed 复现
"""
from __future__ import annotations
import json, os, re, random, time
import torch
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_BatchImageGenerator")

# 内部固定的采样参数（Flux Schnell 最优设置）
_SAMPLER   = "euler"
_SCHEDULER = "simple"
_LATENT_CH = 16


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
    批量图像生成器（每步出图模式）。

    每次运行为每个资产各生成 1 张图片。
    seed=0 时每次自动随机（不同方案）；seed>0 时固定复现同一张图。
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
                "seed":          ("INT",   {"default": 0,    "min": 0,   "max": 2**31 - 1,
                                            "tooltip": "0=每次自动随机（出不同图）；>0=固定复现该图"}),
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
        steps: int = 4, cfg: float = 1.0,
        seed: int = 0,
        output_prefix: str = "AFE",
        max_assets: int = 0,
    ):
        # ── 解析资产 ──────────────────────────────────────────────────────────
        try:
            assets = json.loads(assets_json)
        except Exception as exc:
            msg = f"❌ JSON 解析失败：{exc}"
            return {"ui": {"text": [msg]}, "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        if not isinstance(assets, list) or not assets:
            msg = "⚠️ 资产列表为空，请先连接分析器节点"
            return {"ui": {"text": [msg]}, "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        if max_assets > 0:
            assets = assets[:max_assets]

        total = len(assets)

        # ── 确定本次 seed ─────────────────────────────────────────────────────
        # seed=0 → 每次自动随机，确保每次运行出不同图
        # seed>0 → 固定 seed，可复现同一张图
        base_seed = random.randint(1, 2**31 - 1) if seed == 0 else seed
        logger.info(f"BatchGen: {total} 资产，base_seed={base_seed}  {'(随机)' if seed == 0 else '(固定)'}")

        # ── 加载 KSampler ─────────────────────────────────────────────────────
        try:
            from nodes import common_ksampler  # type: ignore
            _ks = common_ksampler
        except ImportError:
            _ks = None

        all_images, names, errors = [], [], []

        # ── 每个资产生成 1 张 ──────────────────────────────────────────────────
        for i, asset in enumerate(assets):
            pos = str(asset.get("positive_prompt", "")).strip()
            neg = str(asset.get("negative_prompt", "ugly, blurry, low quality")).strip()
            name = (asset.get("name") or asset.get("character_name")
                    or asset.get("description", "")[:20] or f"asset_{i+1:02d}")

            if not pos:
                errors.append(f"资产{i+1}({name})：prompt为空，跳过")
                continue

            asset_seed = base_seed + i * 137  # 每个资产不同 seed，同一次运行内各资产图片也不同

            try:
                positive = _encode(clip, pos)
                negative = _encode(clip, neg)
                lat = _latent(height, width)

                if _ks:
                    out = _ks(model, asset_seed, steps, cfg,
                              _SAMPLER, _SCHEDULER, positive, negative, lat)
                    samples = out[0]["samples"]
                else:
                    import comfy.sample  # type: ignore
                    noise = comfy.sample.prepare_noise(lat["samples"], asset_seed, None)
                    samples = comfy.sample.sample(
                        model, noise, steps, cfg, _SAMPLER, _SCHEDULER,
                        positive, negative, lat["samples"],
                        denoise=1.0, disable_noise=False,
                        force_full_denoise=True, seed=asset_seed,
                    )

                img = vae.decode(samples)
                all_images.append(img)
                names.append(name)
                self._save(img, output_prefix, i + 1, name, base_seed)

            except Exception as exc:
                errors.append(f"资产{i+1}({name}) 生成失败：{exc}")
                logger.error(f"Asset {i+1} failed: {exc}")

        # ── 汇报 ──────────────────────────────────────────────────────────────
        if not all_images:
            msg = "❌ 全部生成失败\n" + "\n".join(errors)
            return {"ui": {"text": [msg]}, "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        batch = torch.cat(all_images, dim=0)

        seed_tip = "🎲 随机seed，再次运行出新图" if seed == 0 else f"📌 固定seed={base_seed}"
        lines = [
            f"✅ {len(all_images)} 张图已生成（{total} 个资产）",
            f"   本次 seed：{base_seed}  |  {seed_tip}",
            f"   {width}×{height}  steps={steps}  cfg={cfg}",
            "──────────────",
        ] + [f"  {j+1:02d}. {n}" for j, n in enumerate(names)]
        if errors:
            lines += ["──────────────"] + errors
        report = "\n".join(lines)

        logger.info(f"BatchGen done: {len(all_images)}/{total}  seed={base_seed}")
        return {"ui": {"text": [report]}, "result": (batch, len(all_images), report)}

    def _save(self, img: torch.Tensor, prefix: str, idx: int, name: str, seed: int):
        try:
            import folder_paths  # type: ignore
            import numpy as np
            from PIL import Image  # type: ignore
            path = os.path.join(
                folder_paths.get_output_directory(),
                f"{prefix}_{idx:02d}_{_safe(name)}_s{seed}.png"
            )
            Image.fromarray(
                (img[0].cpu().numpy() * 255).clip(0, 255).astype("uint8")
            ).save(path)
            logger.info(f"Saved: {os.path.basename(path)}")
        except Exception as exc:
            logger.warning(f"Save failed: {exc}")
