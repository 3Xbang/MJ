"""
AFE_ShotKeyframeGenerator — first frame for every shot (the start image for image-to-video).

For each shot it gives Qwen Image 2.1 the scene reference image plus the reference image of every
character who appears in that shot, and asks for ONE new cinematic frame. This keeps faces, outfits
and the set consistent across all shots.

Choosing (all optional):
  variants_per_shot   draw several versions of every first frame (1-4)
  picks               which version a shot uses:      "shot_005:2, 7:3"
  redo_shots          draw new versions of some shots: "shot_007, 12:2"  (higher number = another new set)
  scene_view_picks    which of the 3 scene images is the location reference: "1:2, 2:3"
                      (scene number : view, 1 = establishing, 2 = medium, 3 = atmosphere)
Gate: waits until switched to "confirmed" (or the master switch is on).

Files: <output>/afe_projects/<project>/keyframes/<shot>_v<k>_<signature>.png (all versions) and
<shot>.png (the version in use, read by the video renderer). The signature covers the prompt, the
reference images and the seed, so changing a character pick or a scene view automatically redraws
exactly the shots it affects and nothing else.
"""
from __future__ import annotations

import json
import logging
import os
import shutil

import torch

from ai_film_editor_nodes.nodes.generation.character_card_9views_node import (
    QWEN_TURBO_SIGMAS, _load_models,
)
from ai_film_editor_nodes.nodes.video._common import (
    align_batch, auto_all_input, call, check_interrupt, clamp, closed_result, files_differ,
    gate_input, gate_is_open, get_node, get_shots, label_image, load_png, make_progress, md5,
    parse_shot_numbers, project_dir, save_png, scene_names_in_order, shot_id_of, split_items,
    split_pair, sub_dir, tensor_sig,
)

logger = logging.getLogger("AFE_ShotKeyframeGenerator")

KEYFRAME_NEGATIVE = (
    "ugly, deformed, blurry, bad anatomy, extra fingers, extra limbs, duplicate characters, "
    "text, watermark, logo, subtitles, low quality"
)
MAX_CHARS_PER_SHOT = 3
VIEW_BY_NAME = {"1": 0, "establishing": 0, "wide": 0, "2": 1, "medium": 1, "3": 2, "atmosphere": 2}
VIEW_LABEL = ["establishing", "medium", "atmosphere"]


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


def parse_scene_view_picks(text: str) -> dict[int, int]:
    """'1:2, 2:atmosphere' -> {0: 1, 1: 2}   (0-based scene index -> 0-based view index)"""
    out: dict[int, int] = {}
    for item in split_items(text):
        key, val = split_pair(item)
        if not key.isdigit() or val is None or val.lower() not in VIEW_BY_NAME:
            logger.warning("ignoring bad scene_view_picks entry %r", item)
            continue
        out[int(key) - 1] = VIEW_BY_NAME[val.lower()]
    return out


def pick_scene_image(views: list, shot: dict, scene_order: list[str], view_picks: dict[int, int]):
    """views = [establishing, medium, atmosphere] (None where not connected).
    Returns (image (1,H,W,3), scene_index, view_index_used)."""
    name = (shot.get("scene_name") or "").strip()
    sidx = scene_order.index(name) if name in scene_order else 0
    want = view_picks.get(sidx, 0)
    vidx = want if views[want] is not None else 0
    batch = views[vidx]
    return batch[min(sidx, batch.shape[0] - 1):min(sidx, batch.shape[0] - 1) + 1], sidx, vidx


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
    """Scene image + character refs + shot description -> first frame per shot (with choices)."""

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
                "variants_per_shot": ("INT", {"default": 1, "min": 1, "max": 4,
                                              "tooltip": "每个分镜首帧画几个版本供挑选"}),
                "picks": ("STRING", {"default": "",
                                     "tooltip": "选用哪个版本。例：shot_005:2, 7:3  （分镜号:版本号）。不写=都用 1 号"}),
                "redo_shots": ("STRING", {"default": "",
                                          "tooltip": "不满意要重画的分镜。例：shot_007, 12:2  （再次重画把冒号后的数字加 1）"}),
                "scene_view_picks": ("STRING", {"default": "",
                                                "tooltip": "每个场景用哪张场景图当地点参考。例：1:2, 2:3  （场景号:视角，1全景 2中景 3氛围）"}),
                "approved": gate_input("生成分镜首帧"),
                "scene_images_medium": ("IMAGE",),
                "scene_images_atmosphere": ("IMAGE",),
                "auto_all": auto_all_input(),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "IMAGE")
    RETURN_NAMES = ("keyframes", "project_dir", "report", "candidates_preview")
    FUNCTION = "generate"
    CATEGORY = "AI Film Editor/Video"
    OUTPUT_NODE = True

    def generate(self, shot_sequence, cast_data, scene_images, character_refs, project_name,
                 render_style, max_shots=0, overwrite=False, resolution=1024, seed=42,
                 variants_per_shot=1, picks="", redo_shots="", scene_view_picks="", approved=False,
                 scene_images_medium=None, scene_images_atmosphere=None, auto_all=False):
        if not gate_is_open(approved, auto_all):
            return closed_result("分镜首帧（生成前请确认场景图和角色参考图）", "ddrd")

        all_shots = get_shots(shot_sequence)
        if not all_shots:
            raise ValueError("shot_sequence is empty")
        shots = all_shots[:max_shots] if max_shots and max_shots > 0 else all_shots

        names = cast_names(cast_data)
        ref_by_name = {n: character_refs[i:i + 1] for i, n in enumerate(names) if i < character_refs.shape[0]}
        scene_order = scene_names_in_order(all_shots)
        views = [scene_images, scene_images_medium, scene_images_atmosphere]
        view_picks = parse_scene_view_picks(scene_view_picks)
        pick_map = parse_shot_numbers(picks, default_value=1)
        redo_map = parse_shot_numbers(redo_shots, default_value=1)
        K = clamp(int(variants_per_shot), 1, 4)

        proj = project_dir(project_name)
        kf_dir = sub_dir(proj, "keyframes")

        model = clip = vae = cached = None
        chosen_frames, preview, lines = [], [], ["🖼 首帧（选用的版本带 * 号）"]
        manifest = []
        bar = make_progress(len(shots) * K)
        made = reused = failed = 0

        for i, shot in enumerate(shots):
            sid = shot_id_of(shot, i)
            in_shot = [n for n in (shot.get("character_names") or []) if n in ref_by_name][:MAX_CHARS_PER_SHOT]
            scene_img, sidx, vidx = pick_scene_image(views, shot, scene_order, view_picks)
            images = {"image_1": scene_img}
            for k, n in enumerate(in_shot):
                images[f"image_{k + 2}"] = ref_by_name[n]
            prompt = build_keyframe_prompt(shot, in_shot, render_style)
            base_sig = md5(prompt, resolution, KEYFRAME_NEGATIVE,
                           *[tensor_sig(t) for t in images.values()])
            salt = redo_map.get(sid, 0)
            chosen = clamp(pick_map.get(sid, 1), 1, K)

            versions, version_paths = [], []
            for k in range(1, K + 1):
                check_interrupt()
                seed_k = seed + i * 7 + (k - 1) * 101 + salt * 9973
                path = os.path.join(kf_dir, f"{sid}_v{k}_{md5(base_sig, seed_k)[:8]}.png")
                img = None
                if os.path.exists(path) and not overwrite:
                    img = load_png(path); reused += 1
                else:
                    if model is None:
                        model, clip, vae = _load_models()
                        cached = call(get_node("QwenImage21Cache"), model=model, device="auto", dtype="default")[0]
                    logger.info("[AFE_ShotKeyframeGenerator] %d/%d %s v%d chars=%s scene_view=%s",
                                i + 1, len(shots), sid, k, in_shot, VIEW_LABEL[vidx])
                    try:
                        img = _generate_frame(cached, clip, vae, images, prompt, KEYFRAME_NEGATIVE,
                                              seed_k, resolution)
                        save_png(img, path); made += 1
                    except Exception as e:
                        logger.error("[AFE_ShotKeyframeGenerator] %s v%d failed: %s", sid, k, e)
                        lines.append(f"  ❌ {sid} v{k}: {e}")
                        failed += 1
                        path = None
                versions.append(img)
                version_paths.append(path)
                if bar:
                    bar.update(1)

            use = chosen - 1
            if versions[use] is None:                        # chosen version failed -> any that worked
                use = next((j for j, v in enumerate(versions) if v is not None), None)
            current = os.path.join(kf_dir, f"{sid}.png")
            if use is None:
                if os.path.exists(current):
                    os.remove(current)                       # never leave a stale frame behind
                chosen_frames.append(label_image(scene_img, f"{sid} FAILED", 768))
                continue
            if files_differ(version_paths[use], current):
                shutil.copyfile(version_paths[use], current)
            chosen_frames.append(label_image(versions[use], f"{sid} v{use + 1}", 768))
            for j, v in enumerate(versions):
                if v is not None:
                    manifest.append({"shot": sid, "variant": j + 1,
                                     "file": f"keyframes/{os.path.basename(version_paths[j])}",
                                     "chosen": j == use})
                    preview.append(label_image(v, f"{sid} v{j + 1}" + (" *" if j == use else ""), 512))
            if K > 1 or salt or vidx:
                note = f"  {sid}：选用 v{use + 1}/{K}，地点图={VIEW_LABEL[vidx]}" + (f"，第{salt}次重画" if salt else "")
                lines.append(note)

        lines.insert(1, f"新画 {made} / 复用 {reused} / 失败 {failed} / 共 {len(shots)} 个分镜")
        lines.append(f"目录：{kf_dir}")
        lines.append("挑选：在 picks 写「分镜号:版本号」；不满意：在 redo_shots 写分镜号；改完再点 Queue。")
        report = "\n".join(lines)
        kf_batch = align_batch(chosen_frames)
        prev_batch = align_batch(preview) if preview else kf_batch
        return {"ui": {"text": [report], "afe_manifest": [json.dumps(manifest, ensure_ascii=False)]},
                "result": (kf_batch, proj, report, prev_batch)}
