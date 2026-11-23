"""
Helpers for pictures the user uploaded as references (characters, scenes, props).

load_user_ref()   -> the uploaded picture as a (1,H,W,3) tensor, or None
qwen_variant()    -> a new picture "in the manner of" a reference, made with Qwen Image 2.1
                     (the same model and call pattern AFE_CharacterCard9Views already uses)
"""
from __future__ import annotations

import os

import torch

from ai_film_editor_nodes.nodes.video._common import load_png, user_ref_file

QWEN_NEGATIVE = (
    "ugly, deformed, noisy, blurry, bad anatomy, bad hands, extra limbs, text, watermark, "
    "duplicate characters"
)


def load_user_ref(project_name: str, kind: str, name: str) -> torch.Tensor | None:
    """kind: 'cast' | 'scene' | 'prop'. Returns None when nothing was uploaded for that name."""
    if not name:
        return None
    path = user_ref_file(project_name, kind, name)
    return load_png(path) if os.path.exists(path) else None


def qwen_variant(reference: torch.Tensor, prompt: str, seed: int) -> torch.Tensor:
    """One Qwen Image 2.1 edit pass. `prompt` must refer to the reference as [Image_1]."""
    from ai_film_editor_nodes.nodes.generation.character_card_9views_node import (
        _generate_one, _load_models,
    )
    from ai_film_editor_nodes.nodes.video._common import call, get_node

    model, clip, vae = _load_models()
    cached = call(get_node("QwenImage21Cache"), model=model, device="auto", dtype="default")[0]
    return _generate_one(reference_image=reference, clip=clip, vae=vae, cached_model=cached,
                         prompt=prompt, negative=QWEN_NEGATIVE, seed=seed)
