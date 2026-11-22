"""
AFE_SceneImageGenerator — Generates 3 environment reference images per scene.
Establishing shot, medium shot, and atmosphere shot per scene.
Uses Flux dev pipeline internally via ComfyUI NODE_CLASS_MAPPINGS.
"""
from __future__ import annotations
import json
import re
import logging
import torch

logger = logging.getLogger("AFE_SceneImageGenerator")

_MODEL_CACHE: dict = {}

NEGATIVE_PROMPT = (
    "people, characters, persons, figures, man, woman, human, "
    "text, watermark, logo, signature, ugly, deformed, blurry, low quality"
)


def _get_node(name: str):
    from nodes import NODE_CLASS_MAPPINGS
    cls = NODE_CLASS_MAPPINGS.get(name)
    if cls is None:
        raise RuntimeError(f"ComfyUI node '{name}' not found. Ensure ComfyUI is fully loaded.")
    return cls


def _call(cls, **kwargs):
    func_name = getattr(cls, "FUNCTION", "execute")
    return getattr(cls(), func_name)(**kwargs)


def _load_models(unet_name: str, clip1_name: str, clip2_name: str, vae_name: str):
    global _MODEL_CACHE
    key = (unet_name, clip1_name, clip2_name, vae_name)
    if key in _MODEL_CACHE:
        logger.debug("[AFE_SceneImageGenerator] Using cached Flux models")
        return _MODEL_CACHE[key]
    logger.info("[AFE_SceneImageGenerator] Loading Flux models (first run)...")
    model = _call(_get_node("UNETLoader"), unet_name=unet_name, weight_dtype="default")[0]
    clip  = _call(_get_node("DualCLIPLoader"), clip_name1=clip1_name, clip_name2=clip2_name, type="flux")[0]
    vae   = _call(_get_node("VAELoader"), vae_name=vae_name)[0]
    _MODEL_CACHE[key] = (model, clip, vae)
    logger.info("[AFE_SceneImageGenerator] Models loaded OK")
    return model, clip, vae


def _generate_one(
    model, clip, vae,
    prompt: str, negative: str,
    seed: int, width: int, height: int, steps: int, cfg: float
) -> torch.Tensor:
    """Run one full Flux KSampler pass and return an IMAGE tensor (B, H, W, C)."""
    pos    = _call(_get_node("CLIPTextEncode"), clip=clip, text=prompt)[0]
    neg    = _call(_get_node("CLIPTextEncode"), clip=clip, text=negative)[0]
    latent = _call(_get_node("EmptyLatentImage"), width=width, height=height, batch_size=1)[0]
    sampled = _call(
        _get_node("KSampler"),
        model=model, positive=pos, negative=neg,
        latent_image=latent, seed=seed, steps=steps, cfg=cfg,
        sampler_name="euler", scheduler="simple", denoise=1.0
    )[0]
    image = _call(_get_node("VAEDecode"), samples=sampled, vae=vae)[0]
    return image


def _parse_scene_report(scene_report: str) -> list[dict]:
    """
    Parse scene_report from AFE_SceneAnalyzer.
    Tries JSON first (scenes_json format), then falls back to text parsing.
    Returns list of dicts with keys:
      scene_name, location, time_of_day, weather, lighting_mood, environment_description_en
    """
    text = scene_report.strip()

    # 1. Try JSON parse (scenes_json output format)
    if text.startswith("[") or text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                scenes = []
                for item in data:
                    scenes.append({
                        "scene_name": item.get("scene_name") or item.get("name", ""),
                        "location": item.get("location", ""),
                        "time_of_day": item.get("time_of_day", ""),
                        "weather": item.get("weather", ""),
                        "lighting_mood": item.get("lighting_mood") or item.get("lighting_style", ""),
                        "environment_description_en": item.get("environment_description_en", ""),
                    })
                return scenes
        except json.JSONDecodeError:
            pass

    # 2. Text parsing — format produced by AFE_SceneAnalyzer.analyze_scenes()
    # Pattern: 场景N：name followed by optional indented fields
    scenes = []
    scene_blocks = re.split(r'(?=场景\d+[：:])', text)
    for block in scene_blocks:
        block = block.strip()
        if not block:
            continue
        m = re.match(r'场景\d+[：:](.+)', block)
        if not m:
            continue
        scene_name = m.group(1).strip()
        location     = ""
        time_weather = ""
        lighting     = ""
        env_desc     = ""
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("地点") and ("：" in line or ":" in line):
                location = re.split(r'[：:]', line, 1)[1].strip()
            elif line.startswith("时间") and ("：" in line or ":" in line):
                time_weather = re.split(r'[：:]', line, 1)[1].strip()
            elif line.startswith("布光") and ("：" in line or ":" in line):
                lighting = re.split(r'[：:]', line, 1)[1].strip()
            elif line.startswith("环境描述") and ("：" in line or ":" in line):
                env_desc = re.split(r'[：:]', line, 1)[1].strip()
        scenes.append({
            "scene_name": scene_name,
            "location": location,
            "time_of_day": time_weather,
            "weather": "",
            "lighting_mood": lighting,
            "environment_description_en": env_desc,
        })
    return scenes


class AFE_SceneImageGenerator:
    """
    场景三视图生成器。
    Reads scene_report from AFE_SceneAnalyzer and generates 3 environment
    reference images per scene using Flux dev:
      - Establishing shot (wide)
      - Medium shot (key props and set pieces)
      - Atmosphere shot (lighting and texture detail)
    Outputs IMAGE batches (batch_size = number of scenes).
    """

    @classmethod
    def INPUT_TYPES(cls):
        import folder_paths
        clip_list = (folder_paths.get_filename_list("text_encoders")
                     or folder_paths.get_filename_list("clip"))
        return {
            "required": {
                "scene_report": ("STRING", {
                    "multiline": True,
                    "tooltip": "scene_report from AFE_SceneAnalyzer",
                }),
                "render_style": ("STRING", {
                    "default": "3D cartoon Pixar animation style, vibrant colors, 8k, highly detailed",
                }),
            },
            "optional": {
                "unet_name":  (folder_paths.get_filename_list("unet"),  {"default": "flux1-dev.safetensors"}),
                "vae_name":   (folder_paths.get_filename_list("vae"),   {"default": "ae.safetensors"}),
                "clip1_name": (clip_list, {"default": "clip_l.safetensors"}),
                "clip2_name": (folder_paths.get_filename_list("text_encoders"), {"default": "t5xxl_fp16.safetensors"}),
                "width":  ("INT", {"default": 1024, "min": 512, "max": 2048, "step": 64}),
                "height": ("INT", {"default": 576,  "min": 512, "max": 2048, "step": 64}),
                "steps":  ("INT", {"default": 20, "min": 10, "max": 50}),
                "cfg":    ("FLOAT", {"default": 3.5, "min": 1.0, "max": 10.0}),
                "seed":   ("INT", {"default": 42, "min": 0, "max": 2147483647}),
            },
        }

    RETURN_TYPES  = ("IMAGE", "IMAGE", "IMAGE", "STRING")
    RETURN_NAMES  = ("establishing_shots_batch", "medium_shots_batch", "atmosphere_shots_batch", "generation_report")
    FUNCTION      = "generate"
    CATEGORY      = "AI Film Editor/Scene"
    OUTPUT_NODE   = True

    def generate(
        self,
        scene_report: str,
        render_style: str = "3D cartoon Pixar animation style, vibrant colors, 8k, highly detailed",
        unet_name:  str = "flux1-dev.safetensors",
        vae_name:   str = "ae.safetensors",
        clip1_name: str = "clip_l.safetensors",
        clip2_name: str = "t5xxl_fp16.safetensors",
        width:  int   = 1024,
        height: int   = 576,
        steps:  int   = 20,
        cfg:    float = 3.5,
        seed:   int   = 42,
    ):
        scenes = _parse_scene_report(scene_report)
        if not scenes:
            raise ValueError(
                "AFE_SceneImageGenerator: No scenes found in scene_report. "
                "Connect the scene_report output of AFE_SceneAnalyzer."
            )

        model, clip, vae = _load_models(unet_name, clip1_name, clip2_name, vae_name)

        establishing_imgs: list[torch.Tensor] = []
        medium_imgs:       list[torch.Tensor] = []
        atmosphere_imgs:   list[torch.Tensor] = []
        report_lines = ["🌄 Scene Image Generation Report", "=" * 42, f"{len(scenes)} scenes"]

        for i, scene in enumerate(scenes):
            scene_name = (scene.get("scene_name") or scene.get("name") or f"Scene_{i + 1}").strip()
            env_desc = scene.get("environment_description_en", "").strip()
            if not env_desc:
                parts = [scene_name]
                if scene.get("location"):
                    parts.append(scene["location"])
                if scene.get("lighting_mood"):
                    parts.append(scene["lighting_mood"])
                if scene.get("time_of_day"):
                    parts.append(scene["time_of_day"])
                env_desc = ", ".join(filter(None, parts))

            prompts = {
                "establishing": (
                    f"Wide establishing shot. {env_desc}. "
                    f"Empty scene with no people. {render_style}. Cinematic wide angle, 16:9."
                ),
                "medium": (
                    f"Medium interior/exterior shot showing key props and set pieces. {env_desc}. "
                    f"No people. {render_style}. Detailed environment."
                ),
                "atmosphere": (
                    f"Close atmospheric detail shot showing lighting and texture. {env_desc}. "
                    f"No people. {render_style}. Mood lighting, focus on atmosphere."
                ),
            }

            logger.info("[AFE_SceneImageGenerator] Scene %d/%d: %s", i + 1, len(scenes), scene_name)

            for j, (shot_type, prompt) in enumerate(prompts.items()):
                img_seed = seed + i * 100 + j * 10
                try:
                    img = _generate_one(
                        model=model, clip=clip, vae=vae,
                        prompt=prompt, negative=NEGATIVE_PROMPT,
                        seed=img_seed, width=width, height=height,
                        steps=steps, cfg=cfg,
                    )
                    if shot_type == "establishing":
                        establishing_imgs.append(img)
                    elif shot_type == "medium":
                        medium_imgs.append(img)
                    else:
                        atmosphere_imgs.append(img)
                    logger.info("[AFE_SceneImageGenerator]   %s OK shape=%s", shot_type, img.shape)
                except Exception as exc:
                    logger.error("[AFE_SceneImageGenerator]   %s FAILED: %s", shot_type, exc)
                    raise

            report_lines.append(f"  Scene {i + 1}: {scene_name} — 3 images OK")

        est_batch = torch.cat(establishing_imgs, dim=0)
        med_batch = torch.cat(medium_imgs,       dim=0)
        atm_batch = torch.cat(atmosphere_imgs,   dim=0)
        generation_report = "\n".join(report_lines)

        logger.info("[AFE_SceneImageGenerator] Done. Batches shape: %s", est_batch.shape)
        return {
            "ui": {"images": []},
            "result": (est_batch, med_batch, atm_batch, generation_report),
        }
