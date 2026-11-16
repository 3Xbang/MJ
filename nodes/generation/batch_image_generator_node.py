"""
AFE_BatchImageGenerator — 固定 6 张输出模式

每次运行固定输出 6 张图片：
  - 1个资产  → 该资产的 6 个不同变体
  - 2个资产  → 每个资产 3 张
  - 3个资产  → 每个资产 2 张
  - 6+个资产 → 每个资产各取 1 张（前6个）

seed=0 时每次自动随机，确保重复运行出不同图。
seed>0 时固定复现同一组图。
"""
from __future__ import annotations
import json, os, re, random
import torch
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_BatchImageGenerator")

_SAMPLER   = "euler"
_SCHEDULER = "simple"
_LATENT_CH = 16
_TARGET    = 6   # 每次固定输出 6 张


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
    批量图像生成器 — 固定 6 张。
    每次运行为每个类别（主角/配角/场景/服装/道具）输出恰好 6 张图片。
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
                                            "tooltip": "0=每次自动随机；>0=固定复现该图"}),
                "output_prefix": ("STRING", {"default": "AFE"}),
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
    ):
        # 解析资产
        try:
            assets = json.loads(assets_json)
        except Exception as exc:
            msg = f"❌ JSON 解析失败：{exc}"
            return {"ui": {"text": [msg]}, "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        if not isinstance(assets, list) or not assets:
            msg = "⚠️ 资产列表为空，请先连接分析器节点"
            return {"ui": {"text": [msg]}, "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        total = len(assets)
        base_seed = random.randint(1, 2**31 - 1) if seed == 0 else seed
        logger.info(f"BatchGen: {total} 资产 → 固定 {_TARGET} 张  seed={base_seed}")

        try:
            from nodes import common_ksampler  # type: ignore
            _ks = common_ksampler
        except ImportError:
            _ks = None

        all_images, names, errors = [], [], []

        # 固定生成 _TARGET(6) 张，轮询资产
        for slot in range(_TARGET):
            asset = assets[slot % total]
            pos   = str(asset.get("positive_prompt", "")).strip()
            neg   = str(asset.get("negative_prompt", "ugly, blurry, low quality")).strip()
            name  = (asset.get("name") or asset.get("character_name")
                     or asset.get("description", "")[:20] or f"asset_{(slot % total)+1:02d}")

            if not pos:
                errors.append(f"槽位{slot+1}({name})：prompt为空，跳过")
                continue

            slot_seed = base_seed + slot * 137  # 质数步长保证每张不同

            try:
                positive = _encode(clip, pos)
                negative = _encode(clip, neg)
                lat = _latent(height, width)

                if _ks:
                    out     = _ks(model, slot_seed, steps, cfg,
                                  _SAMPLER, _SCHEDULER, positive, negative, lat)
                    samples = out[0]["samples"]
                else:
                    import comfy.sample  # type: ignore
                    noise   = comfy.sample.prepare_noise(lat["samples"], slot_seed, None)
                    samples = comfy.sample.sample(
                        model, noise, steps, cfg, _SAMPLER, _SCHEDULER,
                        positive, negative, lat["samples"],
                        denoise=1.0, disable_noise=False,
                        force_full_denoise=True, seed=slot_seed,
                    )

                img = vae.decode(samples)
                all_images.append(img)
                names.append(f"{name}_{slot+1}")
                self._save(img, output_prefix, slot + 1, name, slot_seed)

            except Exception as exc:
                errors.append(f"槽位{slot+1}({name}) 失败：{exc}")
                logger.error(f"Slot {slot+1} failed: {exc}")

        if not all_images:
            msg = "❌ 全部生成失败\n" + "\n".join(errors)
            return {"ui": {"text": [msg]}, "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        batch = torch.cat(all_images, dim=0)
        seed_tip = "🎲 随机seed，再次运行出新图" if seed == 0 else f"📌 固定seed={base_seed}"
        lines = [
            f"✅ 固定 {_TARGET} 张（来自 {total} 个资产，轮询分配）",
            f"   本次 seed：{base_seed}  |  {seed_tip}",
            f"   {width}×{height}  steps={steps}",
            "──────────────",
        ] + [f"  {j+1}. {n}" for j, n in enumerate(names)]
        if errors:
            lines += ["──────────────"] + errors

        report = "\n".join(lines)
        return {"ui": {"text": [report]}, "result": (batch, len(all_images), report)}

    def _save(self, img: torch.Tensor, prefix: str, slot: int, name: str, seed: int):
        try:
            import folder_paths  # type: ignore
            import numpy as np
            from PIL import Image  # type: ignore
            path = os.path.join(
                folder_paths.get_output_directory(),
                f"{prefix}_{slot:02d}_{_safe(name)}_s{seed}.png"
            )
            Image.fromarray(
                (img[0].cpu().numpy() * 255).clip(0, 255).astype("uint8")
            ).save(path)
            logger.info(f"Saved: {os.path.basename(path)}")
        except Exception as exc:
            logger.warning(f"Save failed: {exc}")
