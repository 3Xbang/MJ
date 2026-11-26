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
from ai_film_editor_nodes.nodes.video import user_refs
from ai_film_editor_nodes.nodes.video._common import (
    align_batch, auto_all_input, call, check_interrupt, clamp, closed_result, files_differ,
    fit_to_canvas, gate_input, gate_is_open, get_node, get_shots, label_image, load_png, make_progress, md5,
    parse_link_prompts, parse_shot_numbers, project_dir, save_png, scene_names_in_order, shot_id_of, split_items,
    split_pair, sub_dir, tensor_sig,
)

logger = logging.getLogger("AFE_ShotKeyframeGenerator")

from ai_film_editor_nodes.nodes.video.shot_prompt_contract import (
    build_keyframe_prompt as render_contract_keyframe, normalize_shot,
)

def indexed_keyframe_shots(all_shots, max_shots, only_listed, only_shot=""):
    """Shots to draw, with their original index so the seed stays stable.

    A per-card redo draws only the shot named for this click. Earlier redo
    counts stay in the seed map and are not drawn again. A full step still
    walks the test-mode prefix, or every shot when max_shots is 0.
    """
    indexed = [(i, shot) for i, shot in enumerate(all_shots)]
    if only_listed:
        target = str(only_shot or "").strip()
        if not target:
            raise ValueError("没有指定要重画的分镜。请在某一张首帧上点「重画」。")
        chosen = [(i, shot) for i, shot in indexed if shot_id_of(shot, i) == target]
        if not chosen:
            raise ValueError("要重画的分镜不在当前剧本里：" + target)
        return chosen
    if max_shots and max_shots > 0:
        return indexed[:max_shots]
    return indexed


KEYFRAME_NEGATIVE = (
    "ugly, deformed, blurry, bad anatomy, extra fingers, extra limbs, duplicate characters, "
    "text, watermark, logo, subtitles, low quality"
)
MAX_CHARS_PER_SHOT = 3
MAX_PROPS_PER_SHOT = 2
VIEW_BY_NAME = {"1": 0, "establishing": 0, "wide": 0, "2": 1, "medium": 1, "3": 2, "atmosphere": 2}
VIEW_LABEL = ["establishing", "medium", "atmosphere"]


def revision_clause(note: str) -> str:
    """User wording for one frame. Empty notes add nothing to the prompt."""
    note = " ".join(str(note or "").split())
    if not note:
        return ""
    return (
        " Director revision for this one frame. Apply this change exactly. "
        "Keep the same people, faces, outfits, and location unless the revision explicitly changes them. "
        "Revision: " + note
    )


def cast_names(cast_data) -> list[str]:
    """Cast names in the same order AFE_CastRefGenerator uses."""
    return [c["name"] for c in (cast_data or []) if isinstance(c, dict) and c.get("name")]


def build_keyframe_prompt(shot: dict, char_names: list[str], render_style: str,
                          prop_names: list[str] | tuple = ()) -> str:
    """Prompt for Qwen Image 2.1. [Image_1] = set, then the characters, then the props the user
    uploaded pictures for (same [Image_n] convention as AFE_CharacterCard9Views)."""
    shot = normalize_shot(shot)
    lines = [
        "[Image_1] is the EMPTY location reference only. No people, character faces, or props are supplied by this slot."
    ]
    for k, name in enumerate(char_names):
        lines.append(
            f"[Image_{k + 2}] is the character {name}. Keep the face, hairstyle, body shape "
            f"and outfit exactly as shown."
        )
    for k, name in enumerate(prop_names):
        lines.append(
            f"[Image_{len(char_names) + k + 2}] is the prop {name}. Keep its exact shape, color and "
            f"details, and show it in the frame where the action uses it."
        )
    lines.append("Create ONE new cinematic film frame inside this location.")

    framing = " ".join(x for x in [
        str(shot.get("shot_type") or "").replace("_", " "),
        f"camera angle: {str(shot.get('camera_angle')).replace('_', ' ')}" if shot.get("camera_angle") else "",
    ] if x)
    if framing:
        lines.append(f"Framing: {framing}.")

    facts = render_contract_keyframe(shot, render_style)
    lines.append(facts)
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
    scene_id = str(shot.get("scene_id") or "")
    ids = [str(s.get("scene_id")) for s in (shot.get("scene_manifest") or []) if isinstance(s, dict)]
    if scene_id and scene_id in ids:
        sidx = ids.index(scene_id)
    elif name in scene_order:
        sidx = scene_order.index(name)
    else:
        raise ValueError(f"No matching scene reference for shot {shot.get('shot_id', '?')}: {name or scene_id}")
    want = view_picks.get(sidx, 0)
    available = [i for i, view in enumerate(views) if view is not None and view.shape[0] > sidx]
    if not available:
        raise ValueError(f"No scene image batch contains scene {scene_id or name}")
    if want not in available:
        raise ValueError(f"Requested scene view {want + 1} is unavailable for scene {scene_id or name}")
    vidx = want
    batch = views[vidx]
    return batch[sidx:sidx + 1], sidx, vidx


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
                "link_prompts": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "每镜一条衔接提示词。例：shot_002: 接上一镜的手部特写，镜头继续缓慢推近"}),
                "redo_shots": ("STRING", {"default": "",
                                          "tooltip": "不满意要重画的分镜。例：shot_007, 12:2  （再次重画把冒号后的数字加 1）"}),
                "only_listed": ("BOOLEAN", {"default": False,
                                            "tooltip": "True = draw only the shot named in only_shot"}),
                "only_shot": ("STRING", {"default": "",
                                         "tooltip": "The one shot id to redraw when only_listed is on"}),
                "edit_notes": ("STRING", {"default": "", "multiline": True,
                                          "tooltip": "每镜一条修改意见。例：shot_002: 茶杯换成白瓷杯，人物看向镜头"}),
                "scene_view_picks": ("STRING", {"default": "",
                                                "tooltip": "每个场景用哪张场景图当地点参考。例：1:2, 2:3  （场景号:视角，1全景 2中景 3氛围）"}),
                "approved": gate_input("生成分镜首帧"),
                "scene_images_medium": ("IMAGE",),
                "scene_images_atmosphere": ("IMAGE",),
                "props_images": ("IMAGE", {
                    "tooltip": "Generated prop references in stable props_list order; uploads override them."}),
                "props_manifest": ("STRING", {
                    "multiline": True,
                    "tooltip": "Stable prop asset manifest from AFE_PropsImageGenerator."}),
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
                 variants_per_shot=1, picks="", link_prompts="", redo_shots="", scene_view_picks="", approved=False,
                 scene_images_medium=None, scene_images_atmosphere=None, props_images=None,
                 props_manifest="", auto_all=False, only_listed=False, only_shot="", edit_notes=""):
        if not gate_is_open(approved, auto_all):
            return closed_result("分镜首帧（生成前请确认场景图和角色参考图）", "ddrd")

        all_shots = get_shots(shot_sequence)
        if not all_shots:
            raise ValueError("shot_sequence is empty")
        redo_map = parse_shot_numbers(redo_shots, default_value=1)
        indexed = indexed_keyframe_shots(all_shots, max_shots, only_listed, only_shot)

        names = cast_names(cast_data)
        ref_by_name = {n: character_refs[i:i + 1] for i, n in enumerate(names) if i < character_refs.shape[0]}
        scene_order = scene_names_in_order(all_shots)
        views = [scene_images, scene_images_medium, scene_images_atmosphere]
        view_picks = parse_scene_view_picks(scene_view_picks)
        pick_map = parse_shot_numbers(picks, default_value=1)
        link_map = parse_link_prompts(link_prompts)
        edit_map = parse_link_prompts(edit_notes)
        K = clamp(int(variants_per_shot), 1, 4)

        proj = project_dir(project_name)
        kf_dir = sub_dir(proj, "keyframes")

        # Uploaded references override generated references. Generated batch is in the
        # stable props_list order emitted by PropsAnalyzer.
        all_prop_names = []
        prop_manifest_by_name = {}
        if props_manifest:
            try:
                manifest_data = json.loads(props_manifest)
                if isinstance(manifest_data, dict):
                    manifest_data = manifest_data.get("assets", manifest_data.get("props", []))
                for item in manifest_data or []:
                    if isinstance(item, dict) and item.get("name"):
                        prop_manifest_by_name[str(item["name"])] = item
            except (TypeError, json.JSONDecodeError) as exc:
                lines = [f"❌ invalid props_manifest: {exc}"]
        for candidate in all_shots:
            for prop in candidate.get("props_list") or []:
                prop = str(prop).strip()
                if prop and prop not in all_prop_names:
                    all_prop_names.append(prop)
        prop_refs = {}
        for p in all_prop_names:
            img = user_refs.load_user_ref(project_name, "prop", p)
            if img is not None:
                prop_refs[p] = fit_to_canvas(img, 768, 768, "pad")
        if props_images is not None:
            for pidx, p in enumerate(all_prop_names):
                if p in prop_refs:
                    continue
                item = prop_manifest_by_name.get(p, {})
                index = int(item.get("index", pidx + 1)) - 1
                if 0 <= index < props_images.shape[0]:
                    prop_refs[p] = fit_to_canvas(props_images[index:index + 1], 768, 768, "pad")

        model = clip = vae = cached = None
        chosen_frames, preview, lines = [], [], ["🖼 首帧（选用的版本带 * 号）"]
        manifest = []
        blocked_shots = []
        bar = make_progress(len(indexed) * K)
        made = reused = failed = 0

        for n, (i, shot) in enumerate(indexed, start=1):
            sid = shot_id_of(shot, i)
            requested_chars = list(dict.fromkeys(shot.get("character_names") or []))
            if shot.get("scene_assignment_error"):
                lines.append(f"  ❌ {sid}: {shot['scene_assignment_error']}")
                failed += 1
                blocked_shots.append(sid)
                continue
            in_shot = [n for n in requested_chars if n in ref_by_name]
            if len(in_shot) != len(requested_chars):
                missing_names = [n for n in requested_chars if n not in ref_by_name]
                lines.append(f"  ❌ {sid}: missing character reference(s) {', '.join(missing_names)}; upload or regenerate them")
                failed += 1
                blocked_shots.append(sid)
                continue
            try:
                scene_img, sidx, vidx = pick_scene_image(views, shot, scene_order, view_picks)
            except Exception as exc:
                lines.append(f"  ❌ {sid}: scene reference unavailable: {exc}")
                failed += 1
                blocked_shots.append(sid)
                continue
            images = {"image_1": scene_img}
            for k, n in enumerate(in_shot):
                images[f"image_{k + 2}"] = ref_by_name[n]
            in_props = [p for p in dict.fromkeys(str(x).strip() for x in (shot.get("props_list") or []))
                        if p in prop_refs]
            for k, p in enumerate(in_props):
                images[f"image_{len(in_shot) + k + 2}"] = prop_refs[p]
            prompt = build_keyframe_prompt(shot, in_shot, render_style, in_props)
            if link_map.get(sid):
                prompt += " Continuity direction: " + link_map[sid]
            prompt += revision_clause(edit_map.get(sid, ""))
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
                                n, len(indexed), sid, k, in_shot, VIEW_LABEL[vidx])
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
                blocked_shots.append(sid)
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

        scope = "指定分镜" if only_listed else "分镜"
        lines.insert(1, f"新画 {made} / 复用 {reused} / 失败 {failed} / 共 {len(indexed)} 个{scope}")
        lines.append(f"目录：{kf_dir}")
        lines.append("挑选：在 picks 写「分镜号:版本号」；不满意：在 redo_shots 写分镜号；改完再点 Queue。")
        report = "\n".join(lines)
        if blocked_shots:
            raise RuntimeError(
                "Keyframe generation blocked for shots: " + ", ".join(dict.fromkeys(blocked_shots)) +
                ". Resolve the reported reference or generation errors and retry."
            )
        kf_batch = align_batch(chosen_frames)
        prev_batch = align_batch(preview) if preview else kf_batch
        return {"ui": {"text": [report], "afe_manifest": [json.dumps(manifest, ensure_ascii=False)]},
                "result": (kf_batch, proj, report, prev_batch)}
