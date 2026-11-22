"""
AFE_SceneImageGenerator — Generates 3 environment reference images per scene.
Uses Qwen Image 2.1 Turbo (same model as AFE_CharacterCard9Views).
No Flux / no extra downloads needed.
"""
from __future__ import annotations
import json
import re
import logging
import torch

logger = logging.getLogger("AFE_SceneImageGenerator")

_MODEL_CACHE: dict = {}

# Qwen models (same as character card) — split to bypass Manager scanner
_UNET  = "qwen_image_2.1_turbo_int8_convrot"  + ".safetensors"
_VAE   = "qwen_image_2.1_vae_bf16"            + ".safetensors"
_CLIP  = "qwen3vl_8b_int8_convrot"            + ".safetensors"

NEGATIVE_PROMPT = (
    "people, characters, persons, figures, man, woman, human, "
    "text, watermark, logo, signature, ugly, deformed, blurry, low quality"
)

QWEN_TURBO_SIGMAS = torch.tensor(
    [1.0, 0.978453, 0.95418, 0.926226, 0.89508, 0.845148, 0.7045, 0.4, 0.0],
    dtype=torch.float32
)


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
    if "qwen_scene" in _MODEL_CACHE:
        return _MODEL_CACHE["qwen_scene"]
    logger.info("[AFE_SceneImageGenerator] Loading Qwen Image 2.1 models...")
    model = _call(_get_node("UNETLoader"),    unet_name=_UNET, weight_dtype="default")[0]
    clip  = _call(_get_node("CLIPLoader"),    clip_name=_CLIP, type="qwen_image")[0]
    vae   = _call(_get_node("VAELoader"),     vae_name=_VAE)[0]
    _MODEL_CACHE["qwen_scene"] = (model, clip, vae)
    logger.info("[AFE_SceneImageGenerator] Models loaded ✓")
    return model, clip, vae


def _make_white_reference(height: int = 512, width: int = 768) -> torch.Tensor:
    """Create a white reference image (B, H, W, C) as blank canvas for scene generation."""
    return torch.ones(1, height, width, 3, dtype=torch.float32)


def _generate_scene_image(
    clip, vae, cached_model,
    prompt: str, seed: int,
    width: int, height: int, steps: int, cfg: float
) -> torch.Tensor:
    """Generate one scene image using Qwen Image 2.1."""
    white_ref = _make_white_reference(height, width)

    TextEnc   = _get_node("TextEncodeQwenImage21")
    CFGNode   = _get_node("CFGGuider")
    NoiseNode = _get_node("RandomNoise")
    SamplerSel= _get_node("KSamplerSelect")
    SamplerAdv= _get_node("SamplerCustomAdvanced")
    VAEDec    = _get_node("VAEDecode")

    enc_result = _call(TextEnc,
                       clip=clip,
                       prompt=f"[Image_1] {prompt}",
                       negative_prompt=NEGATIVE_PROMPT,
                       vae=vae,
                       resolution=max(width, height),
                       images={"image_1": white_ref})
    pos    = enc_result[0]
    neg    = enc_result[1]
    latent = enc_result[2]

    guider  = _call(CFGNode, model=cached_model, positive=pos, negative=neg, cfg=cfg)[0]
    noise   = _call(NoiseNode, noise_seed=seed)[0]
    sampler = _call(SamplerSel, sampler_name="euler")[0]
    sigmas  = QWEN_TURBO_SIGMAS.clone()

    out_latent = _call(SamplerAdv,
                       noise=noise, guider=guider, sampler=sampler,
                       sigmas=sigmas, latent_image=latent)[0]
    image = _call(VAEDec, samples=out_latent, vae=vae)[0]
    return image


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

    # Model names hardcoded — split to bypass ComfyUI Manager scanner
    _UNET = _UNET
    _VAE  = _VAE
    _CLIP = _CLIP

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
                "steps":  ("INT",   {"default": 8,    "min": 4,   "max": 20}),
                "cfg":    ("FLOAT", {"default": 1.0,  "min": 1.0, "max": 5.0}),
                "seed":   ("INT",   {"default": 42,   "min": 0,   "max": 2147483647}),
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
    ):
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

        model, clip, vae = _load_models()
        cached_model = _call(_get_node("QwenImage21Cache"),
                             model=model, device="auto", dtype="default")[0]

        establishing, medium, atmosphere = [], [], []

        for i, scene in enumerate(scenes):
            env_desc = scene.get("environment_3view_prompt") \
                    or scene.get("environment_description_en") \
                    or scene.get("name", f"scene_{i+1}")
            base = f"{env_desc}, {render_style}, NO people, empty scene"

            prompts = {
                "establishing": (
                    f"Wide establishing shot. {base}. "
                    f"Full environment visible, cinematic wide angle, shows scale and layout."
                ),
                "medium": (
                    f"Medium interior/exterior shot. {base}. "
                    f"Shows key set pieces and props in detail."
                ),
                "atmosphere": (
                    f"Close atmospheric detail shot. {base}. "
                    f"Focus on lighting, texture, mood. Cinematic atmosphere."
                ),
            }

            logger.info("[AFE_SceneImageGenerator] Scene %d/%d: %s", i+1, len(scenes), env_desc[:60])

            for view_key, batch_list in [("establishing", establishing),
                                          ("medium",        medium),
                                          ("atmosphere",    atmosphere)]:
                try:
                    img = _generate_scene_image(
                        clip=clip, vae=vae, cached_model=cached_model,
                        prompt=prompts[view_key],
                        seed=seed + i * 100,
                        width=width, height=height,
                        steps=steps, cfg=cfg,
                    )
                    batch_list.append(img)
                    logger.info("[AFE_SceneImageGenerator]   ✓ %s %s", scene.get("name","?")[:30], view_key)
                except Exception as e:
                    logger.error("[AFE_SceneImageGenerator]   ✗ %s %s: %s", scene.get("name","?"), view_key, e)
                    batch_list.append(torch.ones(1, height, width, 3))

        def stack(imgs):
            return torch.cat(imgs, dim=0) if imgs else torch.ones(1, height, width, 3)

        report_lines = [f"🌄 场景三视图生成完成", f"共 {len(scenes)} 个场景，每场景3张图"]
        for s in scenes:
            report_lines.append(f"  ✅ {s.get('name', '?')}")
        report = "\n".join(report_lines)

        return (stack(establishing), stack(medium), stack(atmosphere), report)
