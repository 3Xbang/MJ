"""
AFE_PropsImageGenerator — Generates white-background prop reference images.
Uses Krea 2 Turbo for accurate product-photography-style isolated prop images.
"""
from __future__ import annotations
import json
import re
import logging
import torch

logger = logging.getLogger("AFE_PropsImageGenerator")

import json  # noqa: E402
import os  # noqa: E402
from ai_film_editor_nodes.nodes.video import user_refs  # noqa: E402
from ai_film_editor_nodes.nodes.video._common import (  # noqa: E402
    auto_all_input, closed_result, fit_to_canvas, gate_input, gate_is_open, load_png, md5, project_dir,
    save_png, sub_dir, tensor_sig,
)

# Shared model cache with scene generator
_MODEL_CACHE: dict = {}

_KREA2_UNET = "krea2_turbo_fp8_scaled"   + ".safetensors"
_KREA2_CLIP = "qwen3vl_4b_fp8_scaled"    + ".safetensors"
_KREA2_VAE  = "qwen_image_vae"           + ".safetensors"


def _get_node(name):
    from nodes import NODE_CLASS_MAPPINGS
    cls = NODE_CLASS_MAPPINGS.get(name)
    if cls is None:
        raise RuntimeError(f"Node '{name}' not found in ComfyUI")
    return cls


def _call(cls, **kwargs):
    return getattr(cls(), getattr(cls, "FUNCTION", "execute"))(**kwargs)


def _load_models():
    global _MODEL_CACHE
    if "krea2" in _MODEL_CACHE:
        return _MODEL_CACHE["krea2"]
    logger.info("[AFE_PropsImageGenerator] Loading Krea 2 models...")
    model = _call(_get_node("UNETLoader"),  unet_name=_KREA2_UNET, weight_dtype="default")[0]
    clip  = _call(_get_node("CLIPLoader"),  clip_name=_KREA2_CLIP, type="krea2")[0]
    vae   = _call(_get_node("VAELoader"),   vae_name=_KREA2_VAE)[0]
    _MODEL_CACHE["krea2"] = (model, clip, vae)
    logger.info("[AFE_PropsImageGenerator] Models loaded ✓")
    return model, clip, vae


def _generate_prop_image(clip, vae, base_model, prop_prompt, seed, size, steps):
    """Generate one white-background prop image using Krea 2."""
    Krea2PW  = _get_node("Krea2PromptWeight")
    TextEnc  = _get_node("CLIPTextEncode")
    EmptyLat = _get_node("EmptyLatentImage")
    KSampler = _get_node("KSampler")
    VAEDec   = _get_node("VAEDecode")

    patched_model, pos = _call(Krea2PW,
                               clip=clip, model=base_model,
                               text=prop_prompt, strength=1.0)
    neg    = _call(TextEnc, clip=clip, text="people, humans, text, watermark, background, environment, shadow")[0]
    latent = _call(EmptyLat, width=size, height=size, batch_size=1)[0]
    sampled = _call(KSampler,
                    model=patched_model, positive=pos, negative=neg,
                    latent_image=latent, seed=seed, steps=steps,
                    cfg=1.0, sampler_name="euler", scheduler="simple", denoise=1.0)[0]
    return _call(VAEDec, samples=sampled, vae=vae)[0]


def _parse_props_report(report: str) -> list[dict]:
    """Parse props_report from AFE_PropsAnalyzer."""
    if not report or not report.strip():
        return []

    # Try JSON
    try:
        data = json.loads(report)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "props" in data:
            return data["props"]
    except Exception:
        pass

    # Parse text format
    props = []
    # Match lines like "道具1: desk (desk)" or "- prop: description"
    for line in report.splitlines():
        line = line.strip()
        if not line:
            continue
        # Try to extract prop name and AI prompt
        ai_match = re.search(r'AI提示词[：:]\s*(.+)', line)
        name_match = re.search(r'道具\d+[：:]\s*(.+?)(?:\s*\(|$)', line)
        if name_match:
            name = name_match.group(1).strip()
            props.append({"name": name, "ai_prompt": ""})
        elif ai_match and props:
            props[-1]["ai_prompt"] = ai_match.group(1).strip()

    return props


class AFE_PropsImageGenerator:
    """
    Generates white-background reference images for each prop.
    Uses Krea 2 Turbo — product photography style, clean isolated objects.

    Output: IMAGE batch (batch_size = number of unique props)
    """

    _KREA2_UNET = _KREA2_UNET
    _KREA2_CLIP = _KREA2_CLIP
    _KREA2_VAE  = _KREA2_VAE

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "props_report": ("STRING", {
                    "multiline": True,
                    "tooltip": "props_report output from AFE_PropsAnalyzer",
                }),
            },
            "optional": {
                "props_json": ("STRING", {
                    "multiline": True,
                    "tooltip": "props_json from AFE_PropsAnalyzer (preferred)",
                }),
                "size":  ("INT",   {"default": 1024, "min": 512, "max": 1024, "step": 64,
                                    "tooltip": "Square size for props (1:1 ratio)"}),
                "steps": ("INT",   {"default": 20,   "min": 8,   "max": 50}),
                "seed":  ("INT",   {"default": 42,   "min": 0,   "max": 2147483647}),
                "approved": gate_input("生成道具白底图"),
                "project_name": ("STRING", {"default": "afe_project"}),
                "auto_all": auto_all_input(),
            },
        }

    RETURN_TYPES  = ("IMAGE", "STRING")
    RETURN_NAMES  = ("props_images_batch", "generation_report")
    FUNCTION      = "generate"
    CATEGORY      = "AI Film Editor/Props"
    OUTPUT_NODE   = True

    def generate(
        self,
        props_report: str,
        props_json: str = "",
        size: int = 1024,
        steps: int = 20,
        seed: int = 42,
        approved: bool = False,
        project_name: str = "afe_project",
        auto_all: bool = False,
    ):
        if not gate_is_open(approved, auto_all):
            return closed_result("道具白底图（生成前请确认道具分析报告）", "dr")
        # Prefer props_json (richer data)
        props = []
        if props_json and props_json.strip():
            try:
                data = json.loads(props_json)
                props = data if isinstance(data, list) else data.get("props", [])
            except Exception:
                pass

        if not props:
            props = _parse_props_report(props_report)

        if not props:
            raise ValueError("No props found. Connect props_report from AFE_PropsAnalyzer.")

        props_dir = sub_dir(project_dir(project_name), "props")
        model = clip = vae = None
        images = []
        manifest = []
        failures = []
        made = reused = 0

        for i, prop in enumerate(props):
            name = prop.get("name", f"prop_{i+1}")
            # Use the AI prompt from PropsAnalyzer if available
            ai_prompt = prop.get("ai_prompt", "") or prop.get("prompt_en", "")

            if ai_prompt:
                prompt = f"Product photography, pure white studio background, clean isolated {ai_prompt}, " \
                         f"no shadows, no environment, no people, studio lighting, 8k"
            else:
                desc = prop.get("description_en", "") or prop.get("description", "")
                prompt = f"Product photography, pure white studio background, clean isolated {name}, " \
                         f"{desc}. No shadows, no environment, no people, studio lighting, 8k"

            seed_i = seed + i * 100
            mine = user_refs.load_user_ref(project_name, "prop", name)
            mine_sig = tensor_sig(mine) if mine is not None else ""
            sig = md5(prompt, seed_i, size, steps, "orig" if mine is not None else "krea", mine_sig)[:8]
            path = os.path.join(props_dir, f"P{i + 1}_{sig}.png")
            logger.info("[AFE_PropsImageGenerator] Prop %d/%d: %s", i+1, len(props), name[:50])

            if os.path.exists(path):
                images.append(load_png(path)); reused += 1
            else:
                try:
                    if mine is not None:                      # the user's own picture: use it as is
                        img = fit_to_canvas(mine, size, size, "pad")
                    else:
                        if model is None:
                            model, clip, vae = _load_models()
                        img = _generate_prop_image(
                            clip=clip, vae=vae, base_model=model,
                            prop_prompt=prompt,
                            seed=seed_i,
                            size=size, steps=steps,
                        )
                    save_png(img, path)
                    images.append(img); made += 1
                    logger.info("[AFE_PropsImageGenerator]   ✓ %s", name[:30])
                except Exception as e:
                    logger.error("[AFE_PropsImageGenerator]   ✗ %s: %s", name, e)
                    failures.append({"asset_id": prop.get("asset_id") or f"prop:{name}", "error": str(e), "remediation": "retry prop generation or upload a prop reference"})
                    continue
            manifest.append({"asset_id": prop.get("asset_id") or f"prop:{name}", "prop_id": prop.get("prop_id", f"prop_{i + 1:03d}"), "index": i + 1, "name": name, "source": "uploaded" if mine is not None else "generated", "file": f"props/{os.path.basename(path)}"})

        if failures:
            raise RuntimeError("Prop reference generation failed: " + json.dumps(failures, ensure_ascii=False))

        def stack(imgs):
            return torch.cat(imgs, dim=0) if imgs else torch.ones(1, size, size, 3)

        report = f"🔧 道具白底图完成：新画 {made} 张，复用 {reused} 张\n共 {len(props)} 个道具\n"
        report += "\n".join(f"  ✅ {p.get('name','?')}" for p in props)

        return {"ui": {"text": [report], "afe_manifest": [json.dumps(manifest, ensure_ascii=False)]},
                "result": (stack(images), report)}
