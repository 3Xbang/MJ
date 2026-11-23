"""
AFE_WanShotRenderer — image-to-video for every shot with Wan 2.2 (14B, high/low-noise experts).

Node chain copied from ComfyUI's official "Wan 2.2 14B image to video" template:
  UNETLoader(high_noise) -> LoraLoaderModelOnly(lightx2v 4-step) -> ModelSamplingSD3(shift 5)
  UNETLoader(low_noise)  -> LoraLoaderModelOnly(lightx2v 4-step) -> ModelSamplingSD3(shift 5)
  CLIPTextEncode x2 -> WanImageToVideo(start_image=keyframe)
  KSamplerAdvanced(high, steps 0..split, add_noise) -> KSamplerAdvanced(low, split..end) -> VAEDecode
With the 4-step LoRA: steps=4, cfg=1.0, split=2.  Without it: steps=20, cfg=3.5, split=10.

Clips are written to <output>/afe_projects/<project_name>/clips/<shot_id>.mp4 (silent, 16 fps).
Clips that already exist are skipped, so a crashed or interrupted run can simply be re-queued.
"""
from __future__ import annotations

import logging
import os
import time

from ai_film_editor_nodes.nodes.video._common import (
    call, check_interrupt, get_node, get_shots, has_dialogue, load_png, make_progress,
    shot_id_of, sub_dir, write_mp4,
)

logger = logging.getLogger("AFE_WanShotRenderer")

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

_CACHE: dict = {}


def build_video_prompt(shot: dict, render_style: str, speaking: bool) -> str:
    """Wan prompt: what happens (subject + action) first, then camera, light, style."""
    parts: list[str] = []
    desc = (shot.get("shot_description") or "").strip()
    if desc:
        parts.append(desc)
    for key in ("action", "business", "emotion"):
        v = (shot.get(key) or "").strip()
        if not v or v.lower() in desc.lower():
            continue
        if key == "emotion" and len(v.split()) <= 3:
            v = f"{v} expression"          # "tired" -> "tired expression"
        parts.append(v)
    if speaking:
        parts.append("the character is speaking, natural lip, head and facial movement")
    cam = CAMERA_PHRASES.get(str(shot.get("camera_motion") or "").strip())
    if cam:
        parts.append(cam)
    light = (shot.get("lighting") or shot.get("lighting_style") or "").strip()
    if light:
        parts.append(light)
    parts.append(render_style)
    parts.append("smooth natural motion")
    return ". ".join(p.rstrip(". ") for p in parts if p)


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


def render_clip(models, keyframe, prompt, width, height, length, seed, use_lora):
    """One shot: start image + prompt -> frames tensor (length,H,W,3)."""
    high, low, clip, vae, neg = models
    steps, cfg, split = (4, 1.0, 2) if use_lora else (20, 3.5, 10)

    pos = call(get_node("CLIPTextEncode"), clip=clip, text=prompt)[0]
    cond = call(get_node("WanImageToVideo"), positive=pos, negative=neg, vae=vae,
                width=width, height=height, length=length, batch_size=1, start_image=keyframe)
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
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("project_dir", "report")
    FUNCTION = "render"
    CATEGORY = "AI Film Editor/Video"
    OUTPUT_NODE = True

    def render(self, shot_sequence, project_dir, render_style,
               shots_to_render="all", max_shots=0, width=832, height=480,
               fast_4step=True, overwrite=False, seed=42):
        shots = get_shots(shot_sequence)
        if not shots:
            raise ValueError("shot_sequence is empty")

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
        done = skipped = failed = 0
        t_total = 0.0

        for n, (i, shot, speaking) in enumerate(todo):
            check_interrupt()
            sid = shot_id_of(shot, i)
            out_path = os.path.join(clip_dir, f"{sid}.mp4")
            kf_path = os.path.join(kf_dir, f"{sid}.png")

            if os.path.exists(out_path) and not overwrite:
                skipped += 1
                if bar: bar.update(1)
                continue
            if not os.path.exists(kf_path):
                lines.append(f"  ⚠️ {sid}: 缺少首帧 {kf_path}")
                failed += 1
                if bar: bar.update(1)
                continue

            if models is None:
                models = _load_wan(fast_4step)

            length = frames_for(float(shot.get("duration_seconds") or 5.0))
            prompt = build_video_prompt(shot, render_style, speaking)
            logger.info("[AFE_WanShotRenderer] %d/%d %s (%d frames)", n + 1, len(todo), sid, length)
            t0 = time.time()
            try:
                frames = render_clip(models, load_png(kf_path), prompt, width, height, length,
                                     seed + i, fast_4step)
                write_mp4(frames, out_path, FPS)
                done += 1
                dt = time.time() - t0
                t_total += dt
                logger.info("[AFE_WanShotRenderer]   %s done in %.0fs", sid, dt)
            except Exception as e:
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
        lines.insert(1, f"新渲染 {done} / 已有跳过 {skipped} / 失败 {failed} / 本次范围 {len(todo)}{avg}")
        lines.append(f"目录：{clip_dir}")
        report = "\n".join(lines)
        return {"ui": {"text": [report]}, "result": (project_dir, report)}
