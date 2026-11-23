"""
AFE_CastRefGenerator — one clean full-body reference image per cast member.

Reads cast_data (from AFE_ScriptFullParser: appearance_en, default_costume_en, gender,
age_range) and renders each character on a white background with Krea 2 Turbo.
These images are the identity references used by AFE_ShotKeyframeGenerator, so every
shot of the film can show the same character. Works for any script, no manual photo needed.
If you already have your own character images, skip this node and feed your own
IMAGE batch (same order as cast_data) into AFE_ShotKeyframeGenerator.
"""
from __future__ import annotations

import json
import logging

import torch

from ai_film_editor_nodes.nodes.analyzer.scene_image_generator_node import (
    _generate_scene_image, _load_models,
)
from ai_film_editor_nodes.nodes.video._common import check_interrupt, make_progress

logger = logging.getLogger("AFE_CastRefGenerator")

CAST_NEGATIVE = (
    "multiple people, crowd, group, text, watermark, logo, cropped, cut off, "
    "ugly, deformed, blurry, low quality, extra limbs, bad hands"
)


def build_cast_prompt(member: dict, render_style: str) -> str:
    appearance = (member.get("appearance_en") or "").strip()
    costume = (member.get("default_costume_en") or "").strip()
    gender = (member.get("gender") or "").strip()
    age = (member.get("age_range") or "").strip()
    who = ", ".join(x for x in [gender, f"age {age}" if age else ""] if x)
    parts = [
        "Character design reference, ONE single character, full body from head to feet, "
        "front view, standing relaxed with arms at sides, plain solid white background, "
        "even studio lighting, no props, no other objects",
        who,
        appearance,
        f"wearing {costume}" if costume else "",
        render_style,
    ]
    return ". ".join(p for p in parts if p)


class AFE_CastRefGenerator:
    """cast_data -> one full-body reference image per character (batch, cast order)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "cast_data": ("CAST_DATA",),
                "render_style": ("STRING", {
                    "default": "3D cartoon Pixar animation style, vibrant colors, 8k, highly detailed",
                }),
            },
            "optional": {
                "width":  ("INT", {"default": 768,  "min": 512, "max": 2048, "step": 64}),
                "height": ("INT", {"default": 1152, "min": 512, "max": 2048, "step": 64}),
                "steps":  ("INT", {"default": 8, "min": 4, "max": 50,
                                   "tooltip": "Krea 2 Turbo is distilled for 8 steps"}),
                "seed":   ("INT", {"default": 42, "min": 0, "max": 2147483647}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("character_refs", "report")
    FUNCTION = "generate"
    CATEGORY = "AI Film Editor/Video"
    OUTPUT_NODE = True

    def generate(self, cast_data, render_style, width=768, height=1152, steps=8, seed=42):
        cast = [c for c in (cast_data or []) if isinstance(c, dict) and c.get("name")]
        if not cast:
            raise ValueError("cast_data is empty. Connect cast_data from AFE_ScriptFullParser.")

        model, clip, vae = _load_models()
        images, lines = [], ["🎭 角色参考图生成完成"]
        bar = make_progress(len(cast))

        for i, member in enumerate(cast):
            check_interrupt()
            name = member["name"]
            prompt = build_cast_prompt(member, render_style)
            logger.info("[AFE_CastRefGenerator] %d/%d %s", i + 1, len(cast), name)
            try:
                img = _generate_scene_image(
                    clip=clip, vae=vae, base_model=model, prompt=prompt,
                    seed=seed + i * 101, width=width, height=height,
                    steps=steps, cfg=1.0, negative=CAST_NEGATIVE,
                )
                images.append(img)
                lines.append(f"  ✅ {name}")
            except Exception as e:  # keep batch aligned with cast order
                logger.error("[AFE_CastRefGenerator] %s failed: %s", name, e)
                images.append(torch.ones(1, height, width, 3))
                lines.append(f"  ❌ {name}: {e}")
            if bar:
                bar.update(1)

        lines.append("顺序：" + json.dumps([c["name"] for c in cast], ensure_ascii=False))
        report = "\n".join(lines)
        return {"ui": {"text": [report]}, "result": (torch.cat(images, dim=0), report)}
