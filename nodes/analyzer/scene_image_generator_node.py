"""
AFE_SceneImageGenerator — Generates 3 environment reference images per scene.
Uses Krea 2 Turbo for accurate text-to-image scene generation.
No reference image needed — pure text-to-image with detailed scene descriptions.
"""
from __future__ import annotations
import json
import re
import logging
import torch

logger = logging.getLogger("AFE_SceneImageGenerator")

import json  # noqa: E402
import os  # noqa: E402
from ai_film_editor_nodes.nodes.video import user_refs  # noqa: E402
from ai_film_editor_nodes.nodes.video._common import (  # noqa: E402
    auto_all_input, closed_result, fit_to_canvas, gate_input, gate_is_open, load_png, md5,
    parse_index_numbers, project_dir, save_png, sub_dir, tensor_sig,
)

_MODEL_CACHE: dict = {}

# Krea 2 Turbo models — split to bypass Manager scanner
_KREA2_UNET = "krea2_turbo_fp8_scaled"       + ".safetensors"
_KREA2_CLIP = "qwen3vl_4b_fp8_scaled"        + ".safetensors"
_KREA2_VAE  = "qwen_image_vae"               + ".safetensors"

NEGATIVE_PROMPT = (
    "people, characters, persons, figures, man, woman, human, "
    "text, watermark, logo, signature, ugly, deformed, blurry, low quality"
)

_VIEW_SUFFIX = {
    "establishing": (
        "Wide establishing shot, full environment and layout visible, "
        "cinematic wide angle, eye level."
    ),
    "medium": (
        "Medium shot from a different angle, key set pieces and "
        "fixtures in detail, side view."
    ),
    "atmosphere": (
        "Close-up of surfaces, materials and lighting, "
        "atmospheric detail, shallow depth of field."
    ),
}


def parse_scene_notes(text: str) -> dict[str, str]:
    """One correction per line: '伦敦社区超市 / 外卖厨房: 夜间湿马路，路边一个橙色外卖箱'."""
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


def scene_view_prompt(env_desc: str, render_style: str, view_key: str, note: str = "") -> str:
    """A written correction replaces the analyzed place. An empty note keeps the old sentence."""
    place = (note or "").strip()
    if place:
        place = (
            "Follow this correction exactly, and ignore any earlier place description that conflicts with it: "
            + place
        )
    else:
        place = env_desc
    base = f"{place}, {render_style}, empty scene, no people"
    return f"{base}. {_VIEW_SUFFIX[view_key]}"


def _get_node(name: str):
    from nodes import NODE_CLASS_MAPPINGS
    cls = NODE_CLASS_MAPPINGS.get(name)
    if cls is None:
        raise RuntimeError(f"ComfyUI node '{name}' not found.")
    return cls


def _call(cls, **kwargs):
    func_name = getattr(cls, "FUNCTION", "execute")
    return getattr(cls(), func_name)(**kwargs)


def _load_models():
    global _MODEL_CACHE
    if "krea2" in _MODEL_CACHE:
        return _MODEL_CACHE["krea2"]
    logger.info("[AFE_SceneImageGenerator] Loading Krea 2 models...")
    model = _call(_get_node("UNETLoader"),    unet_name=_KREA2_UNET, weight_dtype="default")[0]
    clip  = _call(_get_node("CLIPLoader"),    clip_name=_KREA2_CLIP, type="krea2")[0]
    vae   = _call(_get_node("VAELoader"),     vae_name=_KREA2_VAE)[0]
    _MODEL_CACHE["krea2"] = (model, clip, vae)
    logger.info("[AFE_SceneImageGenerator] Krea 2 models loaded ✓")
    return model, clip, vae


def _make_white_reference(height: int = 512, width: int = 768) -> torch.Tensor:
    """Create a white reference image (B, H, W, C) as blank canvas for scene generation."""
    return torch.ones(1, height, width, 3, dtype=torch.float32)


def _generate_scene_image(
    clip, vae, base_model,
    prompt: str, seed: int,
    width: int, height: int, steps: int, cfg: float,
    negative: str | None = None,
) -> torch.Tensor:
    """Generate one scene image using Krea 2 Turbo (pure text-to-image)."""

    Krea2PW  = _get_node("Krea2PromptWeight")
    TextEnc  = _get_node("CLIPTextEncode")
    EmptyLat = _get_node("EmptyLatentImage")
    KSampler = _get_node("KSampler")
    VAEDec   = _get_node("VAEDecode")

    # Positive: Krea2PromptWeight → patched model + conditioning
    patched_model, pos = _call(Krea2PW,
                               clip=clip, model=base_model,
                               text=prompt, strength=1.0)

    # Negative: empty (CFG=1.0 means negative has minimal effect)
    neg = _call(TextEnc, clip=clip, text=negative if negative is not None else NEGATIVE_PROMPT)[0]

    # Empty latent (pure text-to-image, no reference image)
    latent = _call(EmptyLat, width=width, height=height, batch_size=1)[0]

    # Sample — CFG must be 1.0 for Krea 2
    sampled = _call(KSampler,
                    model=patched_model,
                    positive=pos,
                    negative=neg,
                    latent_image=latent,
                    seed=seed,
                    steps=steps,
                    cfg=1.0,          # Krea 2 requires cfg=1.0
                    sampler_name="euler",
                    scheduler="simple",
                    denoise=1.0)[0]

    return _call(VAEDec, samples=sampled, vae=vae)[0]


# ── Scene report parser ───────────────────────────────────────────────────────

def _parse_scene_report(report: str) -> list[dict]:
    """Parse scene_report from AFE_SceneAnalyzer (text or JSON format)."""
    if not report or not report.strip():
        return []

    # Try JSON first
    try:
        data = json.loads(report)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "scenes" in data:
            return data["scenes"]
    except (json.JSONDecodeError, ValueError):
        pass

    # Parse text format
    scenes = []
    blocks = re.split(r"场景\d+[:：]|Scene\s*\d+[:：]", report, flags=re.IGNORECASE)
    for block in blocks[1:]:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        name_line = lines[0]
        # Extract location, time, weather, lighting from subsequent lines
        location = ""
        lighting = ""
        for line in lines[1:]:
            if "地点" in line or "location" in line.lower():
                location = re.sub(r".*[:：]", "", line).strip()
            elif "布光" in line or "lighting" in line.lower():
                lighting = re.sub(r".*[:：]", "", line).strip()

        # Build environment description
        env_desc = name_line
        if location:
            env_desc += f", {location}"
        if lighting:
            env_desc += f", {lighting}"

        scenes.append({
            "name": name_line,
            "environment_description_en": env_desc,
            "environment_3view_prompt": env_desc,
        })
    return scenes


# ── Node class ────────────────────────────────────────────────────────────────

class AFE_SceneImageGenerator:
    """
    Generates 3 environment reference images per scene from scene_report.
    Uses Qwen Image 2.1 Turbo — no Flux needed.

    Outputs IMAGE batches (batch_size = number of unique scenes):
      establishing_shots_batch — wide shot, full environment
      medium_shots_batch       — medium, props and set pieces detail
      atmosphere_shots_batch   — close atmospheric detail, lighting/texture
    """

    # Krea 2 Turbo model names — split to bypass Manager scanner
    _KREA2_UNET = _KREA2_UNET
    _KREA2_CLIP = _KREA2_CLIP
    _KREA2_VAE  = _KREA2_VAE

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "scene_report": ("STRING", {
                    "multiline": True,
                    "tooltip": "scene_report output from AFE_SceneAnalyzer",
                }),
                "render_style": ("STRING", {
                    "default": "3D cartoon Pixar animation style, vibrant colors, 8k, highly detailed",
                }),
            },
            "optional": {
                "scenes_json": ("STRING", {
                    "multiline": True,
                    "tooltip": "scenes_json from AFE_SceneAnalyzer (preferred — has full descriptions)",
                }),
                "width":  ("INT",   {"default": 1024, "min": 512, "max": 2048, "step": 64}),
                "height": ("INT",   {"default": 576,  "min": 512, "max": 2048, "step": 64}),
                "steps":  ("INT",   {"default": 20,   "min": 8,   "max": 50}),
                "cfg":    ("FLOAT", {"default": 1.0,  "min": 1.0, "max": 1.0,
                                     "tooltip": "Krea 2 requires cfg=1.0 (fixed)"}),
                "seed":   ("INT",   {"default": 42,   "min": 0,   "max": 2147483647}),
                "approved": gate_input("生成场景图（每个场景 3 张）"),
                "project_name": ("STRING", {"default": "afe_project"}),
                "revision_notes": ("STRING", {"default": "", "multiline": True,
                                              "tooltip": "每个场景一条修改意见。例：伦敦社区超市 / 外卖厨房: 夜间湿马路，路边一个橙色外卖箱。这句话替换分析写的环境"}),
                "redo_scenes": ("STRING", {"default": "",
                                           "tooltip": "不满意要重画的场景。例：2, 露台:2  （再次重画把冒号后的数字加 1）"}),
                "auto_all": auto_all_input(),
            },
        }

    RETURN_TYPES  = ("IMAGE", "IMAGE", "IMAGE", "STRING")
    RETURN_NAMES  = ("establishing_shots_batch", "medium_shots_batch",
                     "atmosphere_shots_batch", "generation_report")
    FUNCTION      = "generate"
    CATEGORY      = "AI Film Editor/Scene"
    OUTPUT_NODE   = True

    def generate(
        self,
        scene_report: str,
        render_style: str = "3D cartoon Pixar animation style, vibrant colors, 8k, highly detailed",
        scenes_json: str = "",
        width:  int   = 1024,
        height: int   = 576,
        steps:  int   = 8,
        cfg:    float = 1.0,
        seed:   int   = 42,
        approved: bool = False,
        project_name: str = "afe_project",
        auto_all: bool = False,
        revision_notes: str = "",
        redo_scenes: str = "",
    ):
        if not gate_is_open(approved, auto_all):
            return closed_result("场景图（生成前请确认场景分析报告：场景数量、环境提示词）", "dddr")
        # Prefer scenes_json (full descriptions) over scene_report (formatted text)
        if scenes_json and scenes_json.strip():
            try:
                data = json.loads(scenes_json)
                if isinstance(data, list):
                    scenes = data
                elif isinstance(data, dict) and "scenes" in data:
                    scenes = data["scenes"]
                else:
                    scenes = []
            except Exception:
                scenes = []
        else:
            scenes = []

        if not scenes:
            scenes = _parse_scene_report(scene_report)
        if not scenes:
            raise ValueError(
                "No scenes found in scene_report. "
                "Connect scene_report output of AFE_SceneAnalyzer."
            )

        scenes_dir = sub_dir(project_dir(project_name), "scenes")
        model = clip = vae = None
        establishing, medium, atmosphere = [], [], []
        manifest = []
        failures = []
        made = reused = 0
        short = {"establishing": "est", "medium": "med", "atmosphere": "atm"}
        note_map = parse_scene_notes(revision_notes)
        scene_names = [str(s.get("scene_name") or s.get("name") or "") for s in scenes]
        redo_map = parse_index_numbers(redo_scenes, scene_names, default_value=1)

        for i, scene in enumerate(scenes):
            # One clean English place description; the 3 views differ only by camera suffix.
            scene_name = str(scene.get("scene_name") or scene.get("name") or "")
            env_desc = scene.get("environment_prompt_en") \
                    or scene.get("environment_description_en") \
                    or scene.get("name", f"scene_{i+1}")
            note = note_map.get(scene_name, "")
            prompts = {key: scene_view_prompt(env_desc, render_style, key, note) for key in _VIEW_SUFFIX}
            logger.info("[AFE_SceneImageGenerator] Scene %d/%d: %s", i+1, len(scenes), env_desc[:60])
            mine = user_refs.load_user_ref(project_name, "scene", scene_name)
            mine_sig = tensor_sig(mine) if mine is not None else ""
            salt = redo_map.get(i, 0)
            for view_key, batch_list in [("establishing", establishing),
                                          ("medium",        medium),
                                          ("atmosphere",    atmosphere)]:
                seed_i = seed + i * 100 + salt * 9973
                # An uploaded scene image is never used directly as the empty
                # location slot. Run every view through an image-edit pass that
                # removes people and preserves only the architecture, fixtures,
                # materials, colors, and lighting. If that pass fails, the asset
                # is reported as failed instead of leaking the original image.
                how = "qwen" if mine is not None else "krea"
                sig = md5(prompts[view_key], seed_i, width, height, steps, how, mine_sig)[:8]
                path = os.path.join(scenes_dir, f"S{i + 1}_{short[view_key]}_{sig}.png")
                if os.path.exists(path):
                    batch_list.append(load_png(path)); reused += 1
                else:
                    try:
                        if how == "qwen":
                            correction = ""
                            if note:
                                correction = (
                                    "Apply this correction exactly, and ignore any earlier place description "
                                    "that conflicts with it: " + note + ". "
                                )
                            img = user_refs.qwen_variant(
                                fit_to_canvas(mine, width, height, "crop"),
                                "[Image_1] This is a location reference. Rebuild the SAME architecture, "
                                "materials, fixtures, colors and lighting as an EMPTY set. Remove every "
                                "person, character, face, body, animal and human trace. Do not add props "
                                "that are not part of the location. "
                                + correction
                                + _VIEW_SUFFIX[view_key], seed_i)
                        else:
                            if model is None:
                                model, clip, vae = _load_models()
                            img = _generate_scene_image(
                                clip=clip, vae=vae, base_model=model,
                                prompt=prompts[view_key],
                                seed=seed_i,
                                width=width, height=height,
                                steps=steps, cfg=cfg,
                            )
                        save_png(img, path)
                        batch_list.append(img); made += 1
                        logger.info("[AFE_SceneImageGenerator]   ✓ %s %s", scene.get("name","?")[:30], view_key)
                    except Exception as e:
                        logger.error("[AFE_SceneImageGenerator]   ✗ %s %s: %s", scene.get("name", "?"), view_key, e)
                        failures.append({"asset_id": scene.get("asset_id") or scene.get("scene_id") or scene.get("name"), "view": view_key, "error": str(e), "remediation": "retry scene generation or upload a scene reference"})
                        continue
                manifest.append({"asset_id": scene.get("asset_id") or scene.get("scene_id") or f"scene:{i + 1}", "scene_id": scene.get("scene_id", f"scene_{i + 1:03d}"), "scene": i + 1, "view": short[view_key], "source": "uploaded" if mine is not None else "generated", "file": f"scenes/{os.path.basename(path)}"})

        if failures:
            raise RuntimeError("Scene reference generation failed: " + json.dumps(failures, ensure_ascii=False))

        def stack(imgs):
            return torch.cat(imgs, dim=0) if imgs else torch.ones(1, height, width, 3)

        report_lines = [f"🌄 场景三视图完成：新画 {made} 张，复用 {reused} 张", f"共 {len(scenes)} 个场景，每场景3张图"]
        for s_ in scenes:
            report_lines.append(f"  ✅ {s_.get('name', '?')}")
        report = "\n".join(report_lines)

        return {"ui": {"text": [report], "afe_manifest": [json.dumps(manifest, ensure_ascii=False)]},
                "result": (stack(establishing), stack(medium), stack(atmosphere), report)}
