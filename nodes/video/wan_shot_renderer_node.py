"""
AFE_WanShotRenderer — image-to-video for every shot with Wan 2.2 (14B, high/low-noise experts).

Node chain copied from ComfyUI's official "Wan 2.2 14B image to video" template:
  UNETLoader(high_noise) -> LoraLoaderModelOnly(lightx2v 4-step) -> ModelSamplingSD3(shift 5)
  UNETLoader(low_noise)  -> LoraLoaderModelOnly(lightx2v 4-step) -> ModelSamplingSD3(shift 5)
  CLIPTextEncode x2 -> WanImageToVideo(start_image=keyframe)
  KSamplerAdvanced(high, steps 0..split, add_noise) -> KSamplerAdvanced(low, split..end) -> VAEDecode
With the 4-step LoRA: steps=4, cfg=1.0, split=2.  Without it: steps=20, cfg=3.5, split=10.

Clips are written to <output>/afe_projects/<project_name>/clips/<shot_id>.mp4 (silent, 16 fps) with a
<shot_id>.json signature next to each. A clip is re-rendered only when what it depends on changed
(first frame, prompt, size, duration, speed mode, seed) or when the shot is listed in redo_shots;
everything else is skipped, so a crashed or interrupted run can simply be re-queued.
Gate: waits until switched to "confirmed" (or the master switch is on).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time

import torch

from ai_film_editor_nodes.nodes.video._common import (
    auto_all_input, call, check_interrupt, closed_result, gate_input, gate_is_open, get_node,
    get_shots, has_dialogue, load_png, make_progress, md5, parse_shot_numbers, shot_id_of,
    sub_dir, write_mp4,
)

logger = logging.getLogger("AFE_WanShotRenderer")

from ai_film_editor_nodes.nodes.video.shot_prompt_contract import (
    CAMERA_MOTIONS, build_video_prompt as render_contract_video, normalize_shot,
    render_shared_facts,
)

# File names are split so ComfyUI-Manager's static scanner does not flag them as "missing models".
_UNET_HIGH = "wan2.2_i2v_high_noise_14B_fp8_scaled"          + ".safetensors"
_UNET_LOW  = "wan2.2_i2v_low_noise_14B_fp8_scaled"           + ".safetensors"
_LORA_HIGH = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise" + ".safetensors"
_LORA_LOW  = "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise"  + ".safetensors"
_CLIP      = "umt5_xxl_fp8_e4m3fn_scaled"                    + ".safetensors"
_VAE       = "wan_2.1_vae"                                   + ".safetensors"

FPS = 16

# Wan's standard negative prompt (from the official template)
WAN_NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，"
    "低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，"
    "毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
)

CAMERA_PHRASES = {
    "static": "static camera, locked off",
    "slow_push_in": "the camera slowly pushes in",
    "slow_pull_back": "the camera slowly pulls back",
    "pan_left": "the camera pans left",
    "pan_right": "the camera pans right",
    "tracking_shot": "the camera tracks the subject",
    "crane_up": "the camera cranes upward",
    "crane_down": "the camera cranes downward",
    "handheld": "subtle handheld camera movement",
    "orbit": "the camera slowly orbits around the subject",
}

def _invalidate_clip(project_dir: str, shot_id: str, out_path: str, meta_path: str) -> None:
    """Invalidate every generated representation so assembly cannot use stale output."""
    paths = [out_path, meta_path,
             os.path.join(project_dir, "clips_av", f"{shot_id}.mp4"),
             os.path.join(project_dir, "clips_av", f"{shot_id}.json")]
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.warning("[AFE_WanShotRenderer] invalidated stale artifact %s", path)
        except OSError as exc:
            logger.error("[AFE_WanShotRenderer] could not invalidate %s: %s", path, exc)

_CACHE: dict = {}


def build_video_prompt(shot: dict, render_style: str, speaking: bool) -> str:
    """Render the canonical shot contract; unsupported camera values are derived, never dropped."""
    return render_contract_video(normalize_shot(shot), render_style, speaking)


def frames_for(duration_seconds: float, fps: int = FPS) -> int:
    """Wan needs length = 4n + 1."""
    n = max(1, round(duration_seconds * fps / 4))
    return n * 4 + 1


def _load_wan(use_lora: bool):
    key = ("wan22", use_lora)
    if key in _CACHE:
        return _CACHE[key]
    logger.info("[AFE_WanShotRenderer] Loading Wan 2.2 models (first run takes a few minutes)...")
    UNET, LoraL, Shift = get_node("UNETLoader"), get_node("LoraLoaderModelOnly"), get_node("ModelSamplingSD3")

    def build(unet_name, lora_name):
        m = call(UNET, unet_name=unet_name, weight_dtype="default")[0]
        if use_lora:
            m = call(LoraL, model=m, lora_name=lora_name, strength_model=1.0)[0]
        return call(Shift, model=m, shift=5.0)[0]

    high = build(_UNET_HIGH, _LORA_HIGH)
    low = build(_UNET_LOW, _LORA_LOW)
    clip = call(get_node("CLIPLoader"), clip_name=_CLIP, type="wan", device="default")[0]
    vae = call(get_node("VAELoader"), vae_name=_VAE)[0]
    neg = call(get_node("CLIPTextEncode"), clip=clip, text=WAN_NEGATIVE)[0]
    _CACHE[key] = (high, low, clip, vae, neg)
    logger.info("[AFE_WanShotRenderer] Wan 2.2 models loaded")
    return _CACHE[key]


MAX_SEG_FRAMES = 81          # Wan 2.2 14B: one segment is at most ~5 s at 16 fps
MAX_SHOT_SECONDS = 120.0
CONTINUE_SUFFIX = (". Continuing the same continuous shot without any cut, same character, "
                   "same location, same lighting")


def plan_segments(duration_seconds: float, fps: int = FPS) -> tuple[list[int], int]:
    """Split one shot into consecutive Wan segments.

    Returns (segment_lengths, target_total_frames). Every length is 4n+1 and <= 81.
    Segment 1 starts from the keyframe. Each later segment starts from the LAST frame of the
    previous one, so its first frame is a duplicate and is dropped when joining (it adds L-1).
    """
    target = max(5, round(duration_seconds * fps) + 1)
    segs: list[int] = []
    have = 0
    # stop when <= 4 frames (0.25 s) are missing: not worth a whole extra sampling pass
    while not segs or target - have > 4:
        needed = target - have
        if not segs:
            length = min(MAX_SEG_FRAMES, 4 * math.ceil((needed - 1) / 4) + 1)
            have += length
        else:
            length = min(MAX_SEG_FRAMES, 4 * math.ceil(needed / 4) + 1)
            have += length - 1
        segs.append(length)
    return segs, target


def parse_duration_overrides(text: str) -> dict[str, float]:
    """'shot_005:15, 20=30' -> {'shot_005': 15.0, 'shot_020': 30.0}  (seconds, clamped 1..120)."""
    out: dict[str, float] = {}
    for item in re.split(r"[,;\n]+", text or ""):
        item = item.strip()
        if not item:
            continue
        m = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*s?\s*$", item)
        if not m:
            logger.warning("[AFE_WanShotRenderer] ignoring bad long_take_overrides entry: %r", item)
            continue
        key, secs = m.group(1), float(m.group(2))
        if key.isdigit():
            key = f"shot_{int(key):03d}"
        out[key] = min(max(secs, 1.0), MAX_SHOT_SECONDS)
    return out


def render_shot(models, keyframe, prompt, width, height, duration_seconds, seed, use_lora,
                anchor_identity=False):
    """One shot of any length: chains 5-second Wan segments through their last frames."""
    segs, target = plan_segments(duration_seconds)
    parts = []
    start = keyframe
    for k, length in enumerate(segs):
        check_interrupt()
        seg_prompt = prompt if k == 0 else prompt + CONTINUE_SUFFIX
        logger.info("[AFE_WanShotRenderer]   segment %d/%d (%d frames)", k + 1, len(segs), length)
        seg = render_clip(models, start, seg_prompt, width, height, length, seed + k * 13, use_lora,
                          ref_pad_image=keyframe if (anchor_identity and k > 0) else None)
        parts.append(seg if k == 0 else seg[1:])
        start = seg[-1:]
    return torch.cat(parts, dim=0)[:target]


def render_clip(models, keyframe, prompt, width, height, length, seed, use_lora, ref_pad_image=None):
    """One segment: start image + prompt -> frames tensor (length,H,W,3)."""
    high, low, clip, vae, neg = models
    steps, cfg, split = (4, 1.0, 2) if use_lora else (20, 3.5, 10)

    pos = call(get_node("CLIPTextEncode"), clip=clip, text=prompt)[0]
    wan_args = dict(positive=pos, negative=neg, vae=vae, width=width, height=height,
                    length=length, batch_size=1, start_image=keyframe)
    if ref_pad_image is not None:
        try:
            cond = call(get_node("WanImageToVideo"), ref_pad_image=ref_pad_image, **wan_args)
        except TypeError:   # older ComfyUI without ref_pad_image
            logger.warning("[AFE_WanShotRenderer] this ComfyUI has no ref_pad_image; "
                           "identity anchoring skipped (update ComfyUI to use it)")
            cond = call(get_node("WanImageToVideo"), **wan_args)
    else:
        cond = call(get_node("WanImageToVideo"), **wan_args)
    pos2, neg2, latent = cond[0], cond[1], cond[2]

    KS = get_node("KSamplerAdvanced")
    stage1 = call(KS, model=high, add_noise="enable", noise_seed=seed, steps=steps, cfg=cfg,
                  sampler_name="euler", scheduler="simple",
                  positive=pos2, negative=neg2, latent_image=latent,
                  start_at_step=0, end_at_step=split, return_with_leftover_noise="enable")[0]
    stage2 = call(KS, model=low, add_noise="disable", noise_seed=0, steps=steps, cfg=cfg,
                  sampler_name="euler", scheduler="simple",
                  positive=pos2, negative=neg2, latent_image=stage1,
                  start_at_step=split, end_at_step=steps, return_with_leftover_noise="disable")[0]
    return call(get_node("VAEDecode"), samples=stage2, vae=vae)[0]


class AFE_WanShotRenderer:
    """Keyframe + shot data -> one silent mp4 clip per shot (Wan 2.2 image-to-video)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
                "project_dir": ("STRING", {"forceInput": True,
                                           "tooltip": "project_dir from AFE_ShotKeyframeGenerator"}),
                "render_style": ("STRING", {
                    "default": "3D cartoon Pixar animation style, vibrant colors, high detail"}),
            },
            "optional": {
                "shots_to_render": (["all", "no_dialogue_only", "dialogue_only"], {
                    "default": "all",
                    "tooltip": "no_dialogue_only: leave dialogue shots to the lip-sync model"}),
                "max_shots": ("INT", {"default": 0, "min": 0, "max": 500,
                                      "tooltip": "0 = all. Use 2-3 for a quick test."}),
                "width":  ("INT", {"default": 832, "min": 320, "max": 1920, "step": 16}),
                "height": ("INT", {"default": 480, "min": 320, "max": 1920, "step": 16}),
                "fast_4step": ("BOOLEAN", {"default": True,
                                           "tooltip": "lightx2v 4-step LoRA: ~5x faster. Off = 20 steps, better detail."}),
                "overwrite": ("BOOLEAN", {"default": False,
                                          "tooltip": "False = skip clips already on disk"}),
                "seed": ("INT", {"default": 42, "min": 0, "max": 2147483647}),
                "long_take_overrides": ("STRING", {
                    "default": "",
                    "tooltip": "Make chosen shots longer than 5 s (one continuous take, no cut). "
                               "Format: shot_005:15, shot_020:30  (seconds). Empty = use each shot's own duration."}),
                "anchor_identity": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Experimental: for long takes, also feed the shot's first frame as an identity "
                               "anchor to later segments to reduce face/outfit drift."}),
                "redo_shots": ("STRING", {
                    "default": "",
                    "tooltip": "不满意要重做的分镜视频。例：shot_005, 12:2  （再次重做把冒号后的数字加 1）"}),
                "approved": gate_input("渲染分镜视频（耗时最长，建议先用 max_shots 试跑）"),
                "auto_all": auto_all_input(),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("project_dir", "report")
    FUNCTION = "render"
    CATEGORY = "AI Film Editor/Video"
    OUTPUT_NODE = True

    def render(self, shot_sequence, project_dir, render_style,
               shots_to_render="all", max_shots=0, width=832, height=480,
               fast_4step=True, overwrite=False, seed=42,
               long_take_overrides="", anchor_identity=False, redo_shots="",
               approved=False, auto_all=False):
        if not gate_is_open(approved, auto_all):
            return closed_result("分镜视频渲染（渲染前请确认首帧）", "dr")

        shots = get_shots(shot_sequence)
        if not shots:
            raise ValueError("shot_sequence is empty")
        redo_map = parse_shot_numbers(redo_shots, default_value=1)

        overrides = parse_duration_overrides(long_take_overrides)
        if overrides:
            shots = [dict(s, duration_seconds=overrides[shot_id_of(s, i)])
                     if shot_id_of(s, i) in overrides else s
                     for i, s in enumerate(shots)]
            known = {shot_id_of(s, i) for i, s in enumerate(shots)}
            unknown = [k for k in overrides if k not in known]
            if unknown:
                logger.warning("[AFE_WanShotRenderer] long_take_overrides: unknown shot ids %s", unknown)

        kf_dir = sub_dir(project_dir, "keyframes")
        clip_dir = sub_dir(project_dir, "clips")

        # select shots (keep original index so seeds / ids stay stable)
        todo = []
        for i, shot in enumerate(shots):
            speaking = has_dialogue(shot)
            if shots_to_render == "no_dialogue_only" and speaking:
                continue
            if shots_to_render == "dialogue_only" and not speaking:
                continue
            todo.append((i, shot, speaking))
        if max_shots and max_shots > 0:
            todo = todo[:max_shots]

        models = None
        lines = ["🎬 Wan 2.2 渲染"]
        bar = make_progress(len(todo))
        done = skipped = failed = redone = 0
        t_total = 0.0

        for n, (i, shot, speaking) in enumerate(todo):
            check_interrupt()
            sid = shot_id_of(shot, i)
            out_path = os.path.join(clip_dir, f"{sid}.mp4")
            meta_path = os.path.join(clip_dir, f"{sid}.json")
            kf_path = os.path.join(kf_dir, f"{sid}.png")

            if not os.path.exists(kf_path):
                _invalidate_clip(project_dir, sid, out_path, meta_path)
                lines.append(f"  ⚠️ {sid}: 缺少首帧 {kf_path}")
                failed += 1
                if bar: bar.update(1)
                continue

            if shot.get("scene_assignment_error"):
                _invalidate_clip(project_dir, sid, out_path, meta_path)
                lines.append(f"  ❌ {sid}: {shot['scene_assignment_error']}")
                failed += 1
                if bar: bar.update(1)
                continue
            duration = float(shot.get("duration_seconds") or 5.0)
            n_segs = len(plan_segments(duration)[0])
            prompt = build_video_prompt(shot, render_style, speaking)
            salt = redo_map.get(sid, 0)
            seed_eff = seed + i + salt * 9973
            with open(kf_path, "rb") as f:
                kf_hash = hashlib.md5(f.read()).hexdigest()
            sig = md5(kf_hash, prompt, width, height, duration, fast_4step, anchor_identity, seed_eff)
            contract_sig = md5(render_shared_facts(shot), speaking)

            existing = os.path.exists(out_path)
            if existing and not overwrite:
                old_sig = None
                if os.path.exists(meta_path):
                    try:
                        old_sig = json.load(open(meta_path, encoding="utf-8")).get("sig")
                    except Exception:
                        pass
                if old_sig == sig:
                    skipped += 1
                    if bar: bar.update(1)
                    continue
                _invalidate_clip(project_dir, sid, out_path, meta_path)
                redone += 1
                lines.append(f"  ♻️ {sid}: 输入有变化（首帧/时长/提示词/重做），重新渲染")
            elif existing and overwrite:
                _invalidate_clip(project_dir, sid, out_path, meta_path)

            logger.info("[AFE_WanShotRenderer] %d/%d %s (%.0fs, %d segment(s))",
                        n + 1, len(todo), sid, duration, n_segs)
            t0 = time.time()
            try:
                if models is None:
                    models = _load_wan(fast_4step)
                frames = render_shot(models, load_png(kf_path), prompt, width, height, duration,
                                     seed_eff, fast_4step, anchor_identity)
                write_mp4(frames, out_path, FPS)
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump({"sig": sig, "contract_sig": contract_sig, "keyframe_sig": kf_hash,
                               "prompt_sig": md5(prompt), "prompt": prompt, "render_style": render_style,
                               "shot_id": sid, "duration": duration, "seed": seed_eff}, f,
                              ensure_ascii=False)
                done += 1
                dt = time.time() - t0
                t_total += dt
                if n_segs > 1:
                    lines.append(f"  🔗 {sid}: 长镜头 {duration:.0f}s = {n_segs} 段接续，用时 {dt:.0f}s")
                logger.info("[AFE_WanShotRenderer]   %s done in %.0fs", sid, dt)
            except Exception as e:
                _invalidate_clip(project_dir, sid, out_path, meta_path)
                logger.error("[AFE_WanShotRenderer] %s failed: %s", sid, e)
                lines.append(f"  ❌ {sid}: {e}")
                failed += 1
            try:
                import comfy.model_management as mm
                mm.soft_empty_cache()
            except Exception:
                pass
            if bar: bar.update(1)

        avg = f"，平均 {t_total / done:.0f}s/镜头" if done else ""
        lines.insert(1, f"新渲染 {done}（其中因变化重做 {redone}）/ 未变化跳过 {skipped} / 失败 {failed} / 本次范围 {len(todo)}{avg}")
        lines.append(f"目录：{clip_dir}")
        lines.append("不满意某个分镜：在 redo_shots 写分镜号（如 shot_005），或回到首帧节点换版本，再点 Queue。")
        report = "\n".join(lines)
        if failed:
            raise RuntimeError(
                "Wan render blocked because one or more shots failed. "
                "Stale clips were invalidated; resolve the reported shots and retry.\n" + report
            )
        return {"ui": {"text": [report]}, "result": (project_dir, report)}
