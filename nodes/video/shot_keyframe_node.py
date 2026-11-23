"""
AFE_ShotKeyframeGenerator — first frame for every shot (the start image for image-to-video).

For each shot it gives Qwen Image 2.1 the scene reference image plus the reference image of
every character who appears in that shot, and asks for ONE new cinematic frame. This is what
keeps faces, outfits and the set consistent across all shots.

Frames are saved to <output>/afe_projects/<project_name>/keyframes/<shot_id>.png.
Existing files are reused (resume after a crash / partial re-run) unless overwrite=True.
"""
from __future__ import annotations

import logging
import os

import torch

from ai_film_editor_nodes.nodes.generation.character_card_9views_node import (
    QWEN_TURBO_SIGMAS, _load_models,
)
from ai_film_editor_nodes.nodes.video._common import (
    call, check_interrupt, get_node, get_shots, load_png, make_progress, project_dir,
    save_png, scene_names_in_order, shot_id_of, sub_dir,
)

logger = logging.getLogger("AFE_ShotKeyframeGenerator")

KEYFRAME_NEGATIVE = (
    "ugly, deformed, blurry, bad anatomy, extra fingers, extra limbs, duplicate characters, "
    "text, watermark, logo, subtitles, low quality"
)
MAX_CHARS_PER_SHOT = 3


def cast_names(cast_data) -> list[str]:
    """Cast names in the same order AFE_CastRefGenerator uses."""
    return [c["name"] for c in (cast_data or []) if isinstance(c, dict) and c.get("name")]


def build_keyframe_prompt(shot: dict, char_names: list[str], render_style: str) -> str:
    """Prompt for Qwen Image 2.1. [Image_1] = set, [Image_2..] = characters (same
    convention as AFE_CharacterCard9Views)."""
    lines = [
        "[Image_1] is the location reference. Keep its architecture, materials, colors and "
        "lighting exactly as shown."
    ]
    for k, name in enumerate(char_names):
        lines.append(
            f"[Image_{k + 2}] is the character {name}. Keep the face, hairstyle, body shape "
            f"and outfit exactly as shown."
        )
    lines.append("Create ONE new cinematic film frame inside this location.")

    framing = " ".join(x for x in [
        str(shot.get("shot_type") or "").replace("_", " "),
        f"camera angle: {str(shot.get('camera_angle')).replace('_', ' ')}" if shot.get("camera_angle") else "",
    ] if x)
    if framing:
        lines.append(f"Framing: {framing}.")

    desc = (shot.get("shot_description") or "").strip()
    if desc:
        lines.append(desc)
    for label, key in (("Action", "action"), ("Expression", "emotion"), ("Lighting", "lighting")):
        v = (shot.get(key) or "").strip()
        if v:
            lines.append(f"{label}: {v}.")
    costume = (shot.get("costume_en") or "").strip()
    if costume and char_names:
        lines.append(f"Outfit: {costume}.")
    if char_names:
        lines.append(f"Characters in frame: {', '.join(char_names)}. No other people.")
    else:
        lines.append("No people in frame.")
    lines.append(f"{render_style}. No text, no watermark.")
    return " ".join(lines)


def pick_scene_image(scene_images: torch.Tensor, shot: dict, scene_order: list[str]) -> torch.Tensor:
    name = (shot.get("scene_name") or "").strip()
    idx = scene_order.index(name) if name in scene_order else 0
    idx = min(idx, scene_images.shape[0] - 1)
    return scene_images[idx:idx + 1]


def _generate_frame(model_cached, clip, vae, images: dict, prompt: str, negative: str,
                    seed: int, resolution: int) -> torch.Tensor:
    enc = call(get_node("TextEncodeQwenImage21"),
               clip=clip, prompt=prompt, negative_prompt=negative, vae=vae,
               resolution=resolution, images=images)
    pos, neg, latent = enc[0], enc[1], enc[2]
    guider = call(get_node("CFGGuider"), model=model_cached, positive=pos, negative=neg, cfg=1.0)[0]
    noise = call(get_node("RandomNoise"), noise_seed=seed)[0]
    sampler = call(get_node("KSamplerSelect"), sampler_name="euler")[0]
    out = call(get_node("SamplerCustomAdvanced"),
               noise=noise, guider=guider, sampler=sampler,
               sigmas=QWEN_TURBO_SIGMAS.clone(), latent_image=latent)
    return call(get_node("VAEDecode"), samples=out[0], vae=vae)[0]


class AFE_ShotKeyframeGenerator:
    """Scene image + character refs + shot description -> first frame per shot."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
                "cast_data": ("CAST_DATA",),
                "scene_images": ("IMAGE", {
                    "tooltip": "establishing_shots_batch from AFE_SceneImageGenerator (one image per scene)"}),
                "character_refs": ("IMAGE", {
                    "tooltip": "character_refs from AFE_CastRefGenerator (one image per cast member, cast order)"}),
                "project_name": ("STRING", {"default": "afe_project"}),
                "render_style": ("STRING", {
                    "default": "3D cartoon Pixar animation style, vibrant colors, 8k, highly detailed"}),
            },
            "optional": {
                "max_shots": ("INT", {"default": 0, "min": 0, "max": 500,
                                      "tooltip": "0 = all shots. Use 2-3 for a quick test run."}),
                "overwrite": ("BOOLEAN", {"default": False,
                                          "tooltip": "False = reuse frames already on disk"}),
                "resolution": ("INT", {"default": 1024, "min": 512, "max": 2048, "step": 32}),
                "seed": ("INT", {"default": 42, "min": 0, "max": 2147483647}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("keyframes", "project_dir", "report")
    FUNCTION = "generate"
    CATEGORY = "AI Film Editor/Video"
    OUTPUT_NODE = True

    def generate(self, shot_sequence, cast_data, scene_images, character_refs, project_name,
                 render_style, max_shots=0, overwrite=False, resolution=1024, seed=42):
        shots = get_shots(shot_sequence)
        if not shots:
            raise ValueError("shot_sequence is empty")
        if max_shots and max_shots > 0:
            shots = shots[:max_shots]

        names = cast_names(cast_data)
        ref_by_name = {n: character_refs[i:i + 1] for i, n in enumerate(names) if i < character_refs.shape[0]}
        scene_order = scene_names_in_order(get_shots(shot_sequence))

        proj = project_dir(project_name)
        kf_dir = sub_dir(proj, "keyframes")

        model, clip, vae = _load_models()
        cached = call(get_node("QwenImage21Cache"), model=model, device="auto", dtype="default")[0]

        frames, lines = [], ["🖼 首帧生成"]
        bar = make_progress(len(shots))
        done = reused = failed = 0

        for i, shot in enumerate(shots):
            check_interrupt()
            sid = shot_id_of(shot, i)
            path = os.path.join(kf_dir, f"{sid}.png")

            if os.path.exists(path) and not overwrite:
                frames.append(load_png(path)); reused += 1
                if bar: bar.update(1)
                continue

            in_shot = [n for n in (shot.get("character_names") or []) if n in ref_by_name][:MAX_CHARS_PER_SHOT]
            images = {"image_1": pick_scene_image(scene_images, shot, scene_order)}
            for k, n in enumerate(in_shot):
                images[f"image_{k + 2}"] = ref_by_name[n]
            prompt = build_keyframe_prompt(shot, in_shot, render_style)
            logger.info("[AFE_ShotKeyframeGenerator] %d/%d %s chars=%s", i + 1, len(shots), sid, in_shot)

            try:
                img = _generate_frame(cached, clip, vae, images, prompt, KEYFRAME_NEGATIVE,
                                      seed + i * 7, resolution)
                save_png(img, path)
                frames.append(img); done += 1
            except Exception as e:
                logger.error("[AFE_ShotKeyframeGenerator] %s failed: %s", sid, e)
                lines.append(f"  ❌ {sid}: {e}")
                failed += 1
                frames.append(images["image_1"])   # fall back to the scene image so the batch stays aligned
            if bar: bar.update(1)

        # a batch needs identical sizes; align anything that differs to the first frame
        h, w = frames[0].shape[1], frames[0].shape[2]
        aligned = []
        for f in frames:
            if f.shape[1] != h or f.shape[2] != w:
                f = torch.nn.functional.interpolate(f.movedim(-1, 1), size=(h, w), mode="bilinear").movedim(1, -1)
            aligned.append(f)

        lines.insert(1, f"新生成 {done} / 复用 {reused} / 失败 {failed} / 共 {len(shots)}")
        lines.append(f"目录：{kf_dir}")
        report = "\n".join(lines)
        return {"ui": {"text": [report]}, "result": (torch.cat(aligned, dim=0), proj, report)}
