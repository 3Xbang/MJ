"""
AFE Character Card System
角色多视图编辑卡 — 12 槽位角色卡生成器

12个标准槽位：
  全身视角 × 4：正面/背面/左侧/右侧
  表情特写 × 4：温柔微笑/惊讶/闭眼/嗔怒
  头部特写 × 3：正面/侧面/斜侧
  细节     × 1：服装细节
"""
from __future__ import annotations
import json
import random
import logging
import torch

logger = logging.getLogger("AFE_CharacterCard")

# ── 12 个标准槽位配置 ─────────────────────────────────────────
SLOT_CONFIGS = {
    "front_full":    {"name":"正面全身",   "category":"全身", "angle":"front view, standing pose, full body, arms relaxed at sides"},
    "back_full":     {"name":"背面全身",   "category":"全身", "angle":"back view, standing pose, full body, hair visible"},
    "left_full":     {"name":"左侧面全身", "category":"全身", "angle":"left side profile view, standing pose, full body"},
    "right_full":    {"name":"右侧面全身", "category":"全身", "angle":"right side profile view, standing pose, full body"},
    "smile":         {"name":"温柔微笑",   "category":"表情", "angle":"head and shoulders, gentle warm smile, looking forward"},
    "surprised":     {"name":"惊讶张嘴",   "category":"表情", "angle":"head and shoulders, surprised expression, mouth slightly open, wide eyes"},
    "contemplating": {"name":"闭眼沉思",   "category":"表情", "angle":"head and shoulders, eyes closed, serene contemplating expression"},
    "angry":         {"name":"嗔怒",       "category":"表情", "angle":"head and shoulders, annoyed expression, furrowed brows"},
    "front_closeup": {"name":"正面特写",   "category":"特写", "angle":"face close-up portrait, front view, looking directly at camera"},
    "side_closeup":  {"name":"侧面特写",   "category":"特写", "angle":"face close-up portrait, side profile view"},
    "diag_closeup":  {"name":"斜侧特写",   "category":"特写", "angle":"face close-up portrait, three-quarter diagonal view"},
    "costume_detail":{"name":"服装细节",   "category":"细节", "angle":"upper body close-up, costume and accessories detail, fabric texture visible"},
}

SLOT_KEYS = list(SLOT_CONFIGS.keys())
SLOT_NAMES = [v["name"] for v in SLOT_CONFIGS.values()]

BASE_STYLE = "clean white background, studio lighting, high detail, sharp focus"
BASE_NEGATIVE = "ugly, deformed, blurry, low quality, extra limbs, bad anatomy, watermark"

_SAMPLER   = "euler"
_SCHEDULER = "simple"
_LATENT_CH = 16


def _encode(clip, text: str):
    tokens = clip.tokenize(text)
    out = clip.encode_from_tokens(tokens, return_pooled=True, return_dict=True)
    cond = out.pop("cond")
    return [[cond, out]]


def _latent(h: int, w: int):
    return {"samples": torch.zeros([1, _LATENT_CH, h // 8, w // 8])}


class AFE_CharacterCardSetup:
    """
    角色卡设置节点。
    输入角色基本描述，为所有12个槽位生成提示词配置。
    输出 card_config JSON 供生成节点使用。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character_description": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "角色外貌描述（从 Cast Analyzer 或手动填写）\n例：25-year-old Chinese male, messy dark hair, white T-shirt, gold necklace",
                }),
                "style_suffix": ("STRING", {
                    "default": "3D CG animation, Pixar style",
                    "tooltip": "风格后缀，接 Director Group 的 style_prompt",
                }),
            },
            "optional": {
                "slot_1_desc":  ("STRING", {"default": "", "tooltip": "正面全身 修改备注"}),
                "slot_2_desc":  ("STRING", {"default": "", "tooltip": "背面全身 修改备注"}),
                "slot_3_desc":  ("STRING", {"default": "", "tooltip": "左侧面全身 修改备注"}),
                "slot_4_desc":  ("STRING", {"default": "", "tooltip": "右侧面全身 修改备注"}),
                "slot_5_desc":  ("STRING", {"default": "", "tooltip": "温柔微笑 修改备注"}),
                "slot_6_desc":  ("STRING", {"default": "", "tooltip": "惊讶张嘴 修改备注"}),
                "slot_7_desc":  ("STRING", {"default": "", "tooltip": "闭眼沉思 修改备注"}),
                "slot_8_desc":  ("STRING", {"default": "", "tooltip": "嗔怒 修改备注"}),
                "slot_9_desc":  ("STRING", {"default": "", "tooltip": "正面特写 修改备注"}),
                "slot_10_desc": ("STRING", {"default": "", "tooltip": "侧面特写 修改备注"}),
                "slot_11_desc": ("STRING", {"default": "", "tooltip": "斜侧特写 修改备注"}),
                "slot_12_desc": ("STRING", {"default": "", "tooltip": "服装细节 修改备注"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("card_config_json", "card_report")
    FUNCTION = "setup_card"
    CATEGORY = "AI Film Editor/Character Card"
    OUTPUT_NODE = True

    def setup_card(self, character_description, style_suffix="3D CG animation, Pixar style",
                   slot_1_desc="", slot_2_desc="", slot_3_desc="", slot_4_desc="",
                   slot_5_desc="", slot_6_desc="", slot_7_desc="", slot_8_desc="",
                   slot_9_desc="", slot_10_desc="", slot_11_desc="", slot_12_desc=""):

        slot_descs = [slot_1_desc, slot_2_desc, slot_3_desc, slot_4_desc,
                      slot_5_desc, slot_6_desc, slot_7_desc, slot_8_desc,
                      slot_9_desc, slot_10_desc, slot_11_desc, slot_12_desc]

        card = {"character_description": character_description,
                "style_suffix": style_suffix, "slots": []}

        style = style_suffix.strip() or BASE_STYLE

        for i, (key, cfg) in enumerate(SLOT_CONFIGS.items()):
            extra = slot_descs[i].strip()
            parts = [cfg["angle"]]
            if character_description.strip():
                parts.append(character_description.strip())
            if extra:
                parts.append(extra)
            parts.append(style)
            positive = ", ".join(parts)

            card["slots"].append({
                "index":       i + 1,
                "key":         key,
                "name":        cfg["name"],
                "category":    cfg["category"],
                "angle":       cfg["angle"],
                "slot_desc":   extra,
                "positive":    positive,
                "negative":    BASE_NEGATIVE,
                "generated":   False,
                "image_path":  "",
                "seed":        0,
            })

        config_json = json.dumps(card, ensure_ascii=False, indent=2)

        lines = ["🎭 角色卡配置完成", "━" * 30]
        for s in card["slots"]:
            mark = "✏️ " if s["slot_desc"] else "   "
            lines.append(f"{mark}{s['index']:02d}. {s['name']}（{s['category']}）")
            if s["slot_desc"]:
                lines.append(f"      └─ 修改：{s['slot_desc']}")

        report = "\n".join(lines)
        return {"ui": {"text": [report]}, "result": (config_json, report)}


class AFE_CharacterSlotGenerate:
    """
    角色卡单槽生成器。
    从 card_config_json 中按 slot_index 生成对应视角的图片。
    客户不满意可修改 slot_desc 后重新生成该槽。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "card_config_json": ("STRING", {
                    "multiline": True, "default": "{}",
                    "tooltip": "来自 AFE_CharacterCardSetup 的配置 JSON",
                }),
                "slot_index": ("INT", {
                    "default": 1, "min": 1, "max": 12,
                    "tooltip": "生成第几号槽位（1-12）",
                }),
                "model": ("MODEL",),
                "clip":  ("CLIP",),
                "vae":   ("VAE",),
            },
            "optional": {
                "width":  ("INT", {"default": 1024, "min": 64, "max": 4096, "step": 8}),
                "height": ("INT", {"default": 1024, "min": 64, "max": 4096, "step": 8}),
                "steps":  ("INT", {"default": 20,   "min": 1,  "max": 100}),
                "cfg":    ("FLOAT", {"default": 3.5, "min": 0.0, "max": 20.0}),
                "seed":   ("INT", {"default": 0,    "min": 0,  "max": 2**31 - 1,
                                   "tooltip": "0=每次随机，>0=固定复现"}),
                "override_positive": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "覆盖正向提示词（留空=使用配置中的）",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "INT")
    RETURN_NAMES = ("image", "slot_name", "positive_used", "used_seed")
    FUNCTION = "generate_slot"
    CATEGORY = "AI Film Editor/Character Card"
    OUTPUT_NODE = True

    def generate_slot(self, card_config_json, slot_index, model, clip, vae,
                      width=1024, height=1024, steps=20, cfg=3.5, seed=0,
                      override_positive=""):
        try:
            card = json.loads(card_config_json)
        except Exception as e:
            msg = f"❌ JSON 解析失败：{e}"
            return {"ui": {"text": [msg]},
                    "result": (torch.zeros([1, height, width, 3]), "error", "", 0)}

        slots = card.get("slots", [])
        if not slots or slot_index < 1 or slot_index > len(slots):
            msg = f"⚠️ 槽位 {slot_index} 不存在（共{len(slots)}个）"
            return {"ui": {"text": [msg]},
                    "result": (torch.zeros([1, height, width, 3]), "error", "", 0)}

        slot = slots[slot_index - 1]
        slot_name = slot["name"]
        positive = override_positive.strip() or slot["positive"]
        negative = slot.get("negative", BASE_NEGATIVE)
        actual_seed = random.randint(1, 2**31 - 1) if seed == 0 else seed

        logger.info(f"CharacterCard slot {slot_index} ({slot_name}) seed={actual_seed}")

        try:
            pos = _encode(clip, positive)
            neg = _encode(clip, negative)
            lat = _latent(height, width)

            try:
                from nodes import common_ksampler
                out = common_ksampler(model, actual_seed, steps, cfg,
                                      _SAMPLER, _SCHEDULER, pos, neg, lat)
                samples = out[0]["samples"]
            except ImportError:
                import comfy.sample
                noise = comfy.sample.prepare_noise(lat["samples"], actual_seed, None)
                samples = comfy.sample.sample(
                    model, noise, steps, cfg, _SAMPLER, _SCHEDULER,
                    pos, neg, lat["samples"],
                    denoise=1.0, disable_noise=False,
                    force_full_denoise=True, seed=actual_seed,
                )

            img = vae.decode(samples)

        except Exception as e:
            msg = f"❌ 生成失败：{e}"
            logger.error(msg)
            return {"ui": {"text": [msg]},
                    "result": (torch.zeros([1, height, width, 3]), slot_name, positive, actual_seed)}

        lines = [
            f"✅ 槽位 {slot_index} — {slot_name}",
            f"   类别：{slot['category']}",
            f"   Seed：{actual_seed}（{'随机' if seed == 0 else '固定'}）",
            f"   提示词：{positive[:80]}...",
            "",
            "💡 不满意？再次运行换新图；满意后记下 Seed 填入固定",
        ]
        report = "\n".join(lines)

        return {"ui": {"text": [report]},
                "result": (img, slot_name, positive, actual_seed)}


class AFE_CharacterCardBatch:
    """
    角色卡批量生成器。
    一键生成所有12个槽位（或指定范围）。
    每个槽位用不同 seed，seed=0 时全部随机。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "card_config_json": ("STRING", {"multiline": True, "default": "{}"}),
                "model": ("MODEL",),
                "clip":  ("CLIP",),
                "vae":   ("VAE",),
            },
            "optional": {
                "width":      ("INT",   {"default": 1024, "min": 64,  "max": 4096, "step": 8}),
                "height":     ("INT",   {"default": 1024, "min": 64,  "max": 4096, "step": 8}),
                "steps":      ("INT",   {"default": 20,   "min": 1,   "max": 100}),
                "cfg":        ("FLOAT", {"default": 3.5,  "min": 0.0, "max": 20.0}),
                "base_seed":  ("INT",   {"default": 0,    "min": 0,   "max": 2**31 - 1,
                                         "tooltip": "0=每张随机；>0=以此为基础分配各槽seed"}),
                "start_slot": ("INT",   {"default": 1,    "min": 1,   "max": 12}),
                "end_slot":   ("INT",   {"default": 12,   "min": 1,   "max": 12}),
                "output_prefix": ("STRING", {"default": "AFE_CharCard"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "STRING")
    RETURN_NAMES = ("images", "count", "report")
    FUNCTION = "generate_batch"
    CATEGORY = "AI Film Editor/Character Card"
    OUTPUT_NODE = True

    def generate_batch(self, card_config_json, model, clip, vae,
                       width=1024, height=1024, steps=20, cfg=3.5,
                       base_seed=0, start_slot=1, end_slot=12,
                       output_prefix="AFE_CharCard"):
        try:
            card = json.loads(card_config_json)
        except Exception as e:
            msg = f"❌ JSON 解析失败：{e}"
            return {"ui": {"text": [msg]},
                    "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        slots = card.get("slots", [])
        if not slots:
            msg = "⚠️ 配置为空，请先连接 CharacterCardSetup 节点"
            return {"ui": {"text": [msg]},
                    "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        target_slots = [s for s in slots
                        if start_slot <= s["index"] <= end_slot]
        actual_base = random.randint(1, 2**31 - 1) if base_seed == 0 else base_seed
        all_images, names, errors = [], [], []

        try:
            from nodes import common_ksampler
            _ks = common_ksampler
        except ImportError:
            _ks = None

        for slot in target_slots:
            slot_seed = actual_base + (slot["index"] - 1) * 137
            positive = slot["positive"]
            negative = slot.get("negative", BASE_NEGATIVE)

            try:
                pos = _encode(clip, positive)
                neg = _encode(clip, negative)
                lat = _latent(height, width)

                if _ks:
                    out = _ks(model, slot_seed, steps, cfg,
                              _SAMPLER, _SCHEDULER, pos, neg, lat)
                    samples = out[0]["samples"]
                else:
                    import comfy.sample
                    noise = comfy.sample.prepare_noise(lat["samples"], slot_seed, None)
                    samples = comfy.sample.sample(
                        model, noise, steps, cfg, _SAMPLER, _SCHEDULER,
                        pos, neg, lat["samples"],
                        denoise=1.0, disable_noise=False,
                        force_full_denoise=True, seed=slot_seed,
                    )

                img = vae.decode(samples)
                all_images.append(img)
                names.append(f"{slot['index']:02d}_{slot['name']}")
                self._save(img, output_prefix, slot["index"], slot["name"], slot_seed)

            except Exception as e:
                errors.append(f"槽位{slot['index']}({slot['name']})失败：{e}")
                logger.error(errors[-1])

        if not all_images:
            msg = "❌ 全部失败\n" + "\n".join(errors)
            return {"ui": {"text": [msg]},
                    "result": (torch.zeros([1, height, width, 3]), 0, msg)}

        batch = torch.cat(all_images, dim=0)
        lines = [
            f"✅ 角色卡生成完成：{len(all_images)}/{len(target_slots)} 张",
            f"   base_seed={actual_base}  steps={steps}  cfg={cfg}",
            "━" * 30,
        ] + [f"  {n}" for n in names]
        if errors:
            lines += ["━" * 30] + errors

        report = "\n".join(lines)
        return {"ui": {"text": [report]},
                "result": (batch, len(all_images), report)}

    def _save(self, img, prefix, idx, name, seed):
        import os, re
        try:
            import folder_paths
            import numpy as np
            from PIL import Image
            safe = re.sub(r'[\\/:*?"<>|]', "_", name)[:20]
            path = os.path.join(folder_paths.get_output_directory(),
                                f"{prefix}_{idx:02d}_{safe}_s{seed}.png")
            Image.fromarray(
                (img[0].cpu().numpy() * 255).clip(0, 255).astype("uint8")
            ).save(path)
        except Exception as e:
            logger.warning(f"Save failed: {e}")
