"""
AFE_CastRefGenerator — full-body reference image(s) for every cast member.

Reads cast_data (AFE_ScriptFullParser: appearance_en, default_costume_en, gender, age_range) and
renders each character on white with Krea 2 Turbo. These are the identity references used by
AFE_ShotKeyframeGenerator, so each character looks the same in every shot.

Choosing:
  candidates_per_character   how many versions to draw per character (1-6)
  picks                      which version to use:  "1:2, Ann:3"   (character number or name : version)
  redo_characters            draw new versions:     "2" or "Bo:2"  (the number is the attempt; use a
                             higher number to get yet another set)
Gate: the node waits until you switch it to "confirmed" (or the master switch is on).
Candidates are saved under <output>/afe_projects/<project>/cast_refs/. A file name contains a
signature of everything it depends on, so changed inputs are redrawn and unchanged ones are reused.
"""
from __future__ import annotations

import logging
import os

import torch

from ai_film_editor_nodes.nodes.analyzer.scene_image_generator_node import (
    _generate_scene_image, _load_models,
)
from ai_film_editor_nodes.nodes.video._common import (
    auto_all_input, check_interrupt, clamp, closed_result, gate_input, gate_is_open, label_image,
    load_png, make_progress, md5, parse_index_numbers, project_dir, save_png, sub_dir, align_batch,
)

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
    """cast_data -> reference image(s) per character; you choose which version is used."""

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
                "candidates_per_character": ("INT", {"default": 3, "min": 1, "max": 6,
                                                     "tooltip": "每个角色画几个版本供挑选"}),
                "picks": ("STRING", {"default": "",
                                     "tooltip": "选用哪个版本。例：1:2, Ann:3  （角色序号或名字:版本号）。不写=都用 1 号"}),
                "redo_characters": ("STRING", {"default": "",
                                               "tooltip": "不满意要重画的角色。例：2, Bo:2  （再次重画把冒号后的数字加 1）"}),
                "project_name": ("STRING", {"default": "afe_project"}),
                "approved": gate_input("生成角色参考图"),
                "auto_all": auto_all_input(),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "IMAGE")
    RETURN_NAMES = ("character_refs", "report", "candidates_preview")
    FUNCTION = "generate"
    CATEGORY = "AI Film Editor/Video"
    OUTPUT_NODE = True

    def generate(self, cast_data, render_style, width=768, height=1152, steps=8, seed=42,
                 candidates_per_character=3, picks="", redo_characters="",
                 project_name="afe_project", approved=False, auto_all=False):
        if not gate_is_open(approved, auto_all):
            return closed_result("角色参考图（生成前请确认剧本解析里的角色外貌描述是否正确）", "drd")

        cast = [c for c in (cast_data or []) if isinstance(c, dict) and c.get("name")]
        if not cast:
            raise ValueError("cast_data is empty. Connect cast_data from AFE_ScriptFullParser.")
        names = [c["name"] for c in cast]
        K = clamp(int(candidates_per_character), 1, 6)
        pick_map = parse_index_numbers(picks, names, default_value=1)
        redo_map = parse_index_numbers(redo_characters, names, default_value=1)

        out_dir = sub_dir(project_dir(project_name), "cast_refs")
        model = clip = vae = None
        bar = make_progress(len(cast) * K)
        selected, preview, lines = [], [], ["🎭 角色参考图（选用的版本带 * 号）"]
        made = reused = 0

        for ci, member in enumerate(cast):
            prompt = build_cast_prompt(member, render_style)
            salt = redo_map.get(ci, 0)
            chosen = clamp(pick_map.get(ci, 1), 1, K)
            versions = []
            for k in range(1, K + 1):
                check_interrupt()
                seed_k = seed + ci * 101 + (k - 1) * 17 + salt * 9973
                sig = md5(prompt, width, height, steps, seed_k)[:8]
                path = os.path.join(out_dir, f"C{ci + 1}_v{k}_{sig}.png")
                if os.path.exists(path):
                    img = load_png(path); reused += 1
                else:
                    if model is None:
                        model, clip, vae = _load_models()
                    logger.info("[AFE_CastRefGenerator] %s version %d/%d", member["name"], k, K)
                    try:
                        img = _generate_scene_image(
                            clip=clip, vae=vae, base_model=model, prompt=prompt, seed=seed_k,
                            width=width, height=height, steps=steps, cfg=1.0, negative=CAST_NEGATIVE)
                        save_png(img, path); made += 1
                    except Exception as e:
                        logger.error("[AFE_CastRefGenerator] %s v%d failed: %s", member["name"], k, e)
                        lines.append(f"  ❌ C{ci + 1} {member['name']} v{k}: {e}")
                        img = torch.ones(1, height, width, 3)
                versions.append(img)
                preview.append(label_image(img, f"C{ci + 1} v{k}" + (" *" if k == chosen else ""), 512))
                if bar:
                    bar.update(1)
            selected.append(versions[chosen - 1])
            lines.append(f"  C{ci + 1} = {member['name']}：共 {K} 个版本，选用 v{chosen}"
                         + (f"（第 {salt} 次重画）" if salt else ""))

        lines.insert(1, f"新画 {made} / 复用 {reused}")
        lines.append("挑选方法：在 picks 里写「角色序号:版本号」，如 1:2, 2:3，然后再点 Queue。")
        report = "\n".join(lines)
        return {"ui": {"text": [report]},
                "result": (align_batch(selected), report, align_batch(preview))}
