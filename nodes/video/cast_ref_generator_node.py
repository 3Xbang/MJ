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

import json
import logging
import os

import torch

from ai_film_editor_nodes.nodes.analyzer.scene_image_generator_node import (
    _generate_scene_image, _load_models,
)
from ai_film_editor_nodes.nodes.video import user_refs
from ai_film_editor_nodes.nodes.video._common import (
    auto_all_input, check_interrupt, clamp, closed_result, fit_to_canvas, gate_input, gate_is_open,
    label_image, load_png, make_progress, md5, parse_index_numbers, project_dir, save_png, sub_dir,
    align_batch, tensor_sig,
)

logger = logging.getLogger("AFE_CastRefGenerator")

CAST_NEGATIVE = (
    "multiple people, crowd, group, text, watermark, logo, cropped, cut off, "
    "ugly, deformed, blurry, low quality, extra limbs, bad hands"
)


_GENDER_WORDS = {
    "female": "female", "woman": "female", "girl": "female", "女": "female", "女性": "female",
    "male": "male", "man": "male", "boy": "male", "男": "male", "男性": "male",
}


def parse_gender_choices(text: str) -> dict[str, str]:
    """'小舟:female, 小宇:男' -> {'小舟': 'female', '小宇': 'male'}."""
    from ai_film_editor_nodes.nodes.video._common import split_items, split_pair
    out = {}
    for item in split_items(text or ""):
        key, val = split_pair(item)
        kind = _GENDER_WORDS.get(str(val or "").strip().lower())
        if key and kind:
            out[key] = kind
    return out


def apply_gender_choice(member: dict, choices: dict[str, str]) -> dict:
    """The choice on the character card overrides the gender written during analysis."""
    chosen = choices.get(str(member.get("name") or "").strip())
    if not chosen:
        return member
    updated = dict(member)
    updated["gender"] = chosen
    return updated


def parse_cast_notes(text: str) -> dict[str, str]:
    """One correction per line: '小舟: 成年女人，黑发，米色开衫，卡其百褶裙'."""
    import re
    out = {}
    for line in re.split(r"\n+", text or ""):
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(.+?)\s*[:=：]\s*(.+)$", line)
        if not match:
            continue
        name = match.group(1).strip()
        note = " ".join(match.group(2).split())
        if name and note:
            out[name] = note
    return out


def apply_revision_note(member: dict, notes: dict[str, str]) -> dict:
    """A written correction replaces the analyzed look for this redraw."""
    note = notes.get(str(member.get("name") or "").strip())
    if not note:
        return member
    updated = dict(member)
    updated["revision_note"] = note
    return updated


def gender_clause(member: dict) -> str:
    raw = str(member.get("gender") or "").strip().lower()
    kind = _GENDER_WORDS.get(raw) or _GENDER_WORDS.get(raw.split()[0].strip(",，") if raw else "")
    if kind == "female":
        return "adult woman, female"
    if kind == "male":
        return "adult man, male"
    return ""


def gender_negative(member: dict) -> str:
    clause = gender_clause(member)
    if "woman" in clause:
        return "man, male, boy, masculine"
    if "man" in clause:
        return "woman, female, girl"
    return ""


def _revision_clause(note: str) -> str:
    return (
        "Follow this correction exactly, and ignore any earlier description that conflicts with it: "
        + note
    )


def build_cast_prompt(member: dict, render_style: str) -> str:
    appearance = (member.get("appearance_en") or "").strip()
    costume = (member.get("default_costume_en") or "").strip()
    age = (member.get("age_range") or "").strip()
    note = (member.get("revision_note") or "").strip()
    parts = [
        "Character design reference, ONE single character, full body from head to feet, "
        "front view, standing relaxed with arms at sides, plain solid white background, "
        "even studio lighting, no props, no other objects",
        gender_clause(member),
        f"age {age}" if age else "",
        _revision_clause(note) if note else appearance,
        "" if note else (f"wearing {costume}" if costume else ""),
        render_style,
    ]
    return ". ".join(p for p in parts if p)


def build_cast_edit_prompt(member: dict, render_style: str) -> str:
    """Edit an uploaded reference without changing the chosen gender."""
    appearance = (member.get("appearance_en") or "").strip()
    costume = (member.get("default_costume_en") or "").strip()
    note = (member.get("revision_note") or "").strip()
    look = _revision_clause(note) if note else ", ".join(
        x for x in [appearance, f"wearing {costume}" if costume else ""] if x)
    identity = gender_clause(member)
    forbid = gender_negative(member)
    bits = [identity, look, "White background", render_style]
    body = ". ".join(bit.strip(" .") for bit in bits if bit and bit.strip(" ."))
    banned = f" Do not draw: {forbid}." if forbid else ""
    return (
        "[Image_1] Full body FRONT VIEW, standing straight, arms relaxed at sides. "
        f"Keep this exact person and this exact gender. {body}.{banned}"
    )


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
                "genders": ("STRING", {"default": "",
                                       "tooltip": "每个角色的性别。例：小舟:female, 小宇:male。页面上的选择优先于分析里写的性别"}),
                "revision_notes": ("STRING", {"default": "", "multiline": True,
                                              "tooltip": "每个角色一条修改意见。例：小舟: 成年女人，黑发，米色开衫，卡其百褶裙。这句话替换分析写错的外貌"}),
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
                 candidates_per_character=3, picks="", redo_characters="", genders="",
                 project_name="afe_project", approved=False, auto_all=False, revision_notes=""):
        if not gate_is_open(approved, auto_all):
            return closed_result("角色参考图（生成前请确认剧本解析里的角色外貌描述是否正确）", "drd")

        cast = [c for c in (cast_data or []) if isinstance(c, dict) and c.get("name")]
        if not cast:
            report = "🎭 没有检测到角色：跳过角色参考图，首帧将使用无人物路径。"
            empty = torch.empty(0, 1, 1, 3)
            return {"ui": {"text": [report], "afe_manifest": ["[]"]},
                    "result": (empty, report, empty)}
        names = [c["name"] for c in cast]
        gender_choices = parse_gender_choices(genders)
        note_map = parse_cast_notes(revision_notes)
        K = clamp(int(candidates_per_character), 1, 6)
        pick_map = parse_index_numbers(picks, names, default_value=1)
        redo_map = parse_index_numbers(redo_characters, names, default_value=1)

        out_dir = sub_dir(project_dir(project_name), "cast_refs")
        model = clip = vae = None
        bar = make_progress(len(cast) * K)
        selected, preview, lines = [], [], ["🎭 角色参考图（选用的版本带 * 号）"]
        manifest = []
        failures = []
        made = reused = 0

        for ci, member in enumerate(cast):
            member = apply_revision_note(apply_gender_choice(member, gender_choices), note_map)
            prompt = build_cast_prompt(member, render_style)
            mine = user_refs.load_user_ref(project_name, "cast", member["name"])
            mine_sig = tensor_sig(mine) if mine is not None else ""
            qwen_prompt = build_cast_edit_prompt(member, render_style)
            forbid = gender_negative(member)
            if mine is not None:
                lines.append(f"  📎 {member['name']}：使用你上传的参考图")
            salt = redo_map.get(ci, 0)
            chosen = clamp(pick_map.get(ci, 1), 1, K)
            versions = []
            for k in range(1, K + 1):
                check_interrupt()
                seed_k = seed + ci * 101 + (k - 1) * 17 + salt * 9973
                is_original = mine is not None and k == 1          # v1 = the user's own picture
                how = "orig" if is_original else ("qwen" if mine is not None else "krea")
                sig = md5(prompt, qwen_prompt, width, height, steps, seed_k, how, mine_sig)[:8]
                path = os.path.join(out_dir, f"C{ci + 1}_v{k}_{sig}.png")
                if os.path.exists(path):
                    img = load_png(path); reused += 1
                else:
                    logger.info("[AFE_CastRefGenerator] %s version %d/%d (%s)", member["name"], k, K, how)
                    try:
                        if is_original:
                            img = fit_to_canvas(mine, width, height, "pad")
                        elif mine is not None:
                            img = user_refs.qwen_variant(fit_to_canvas(mine, width, height, "pad"),
                                                         qwen_prompt, seed_k)
                        else:
                            if model is None:
                                model, clip, vae = _load_models()
                            img = _generate_scene_image(
                                clip=clip, vae=vae, base_model=model, prompt=prompt, seed=seed_k,
                                width=width, height=height, steps=steps, cfg=1.0,
                                negative=", ".join(x for x in (CAST_NEGATIVE, forbid) if x))
                        save_png(img, path); made += 1
                    except Exception as e:
                        logger.error("[AFE_CastRefGenerator] %s v%d failed: %s", member["name"], k, e)
                        detail = {"asset_id": f"character:{member['name']}", "character": member["name"],
                                  "variant": k, "stage": "cast_reference", "error": str(e),
                                  "remediation": "retry character generation or upload a character reference"}
                        failures.append(detail)
                        lines.append(f"  ❌ C{ci + 1} {member['name']} v{k}: {e}")
                        img = None
                versions.append(img)
                if os.path.exists(path):
                    manifest.append({"char": ci + 1, "name": member["name"], "variant": k,
                                     "file": f"cast_refs/{os.path.basename(path)}", "chosen": k == chosen,
                                     "source": "upload" if is_original else "ai"})
                if img is not None:
                    preview.append(label_image(img, f"C{ci + 1} v{k}" + (" mine" if is_original else "")
                                               + (" *" if k == chosen else ""), 512))
                if bar:
                    bar.update(1)
            selected.append(versions[chosen - 1])
            lines.append(f"  C{ci + 1} = {member['name']}：共 {K} 个版本，选用 v{chosen}"
                         + (f"（第 {salt} 次重画）" if salt else ""))

        if failures:
            raise RuntimeError("Character reference generation failed: " + json.dumps(failures, ensure_ascii=False))
        lines.insert(1, f"新画 {made} / 复用 {reused}")
        lines.append("挑选方法：在 picks 里写「角色序号:版本号」，如 1:2, 2:3，然后再点 Queue。")
        report = "\n".join(lines)
        return {"ui": {"text": [report], "afe_manifest": [json.dumps(manifest, ensure_ascii=False)]},
                "result": (align_batch(selected), report, align_batch(preview))}
