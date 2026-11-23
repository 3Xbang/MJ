"""
Shared helpers for the video-production nodes (cast refs, keyframes, Wan render, assembly).

Everything here is plain Python + torch so it can be unit-tested without ComfyUI.
ComfyUI-only imports (folder_paths, comfy.*) are done lazily inside functions.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

import numpy as np
import torch

logger = logging.getLogger("AFE_Video")

NO_DIALOGUE_MARKERS = {"", "（无）", "(无)", "无", "none", "null", "n/a"}


# ── ComfyUI node access (same pattern as the existing image-generation nodes) ──

def get_node(name: str):
    from nodes import NODE_CLASS_MAPPINGS
    cls = NODE_CLASS_MAPPINGS.get(name)
    if cls is None:
        raise RuntimeError(
            f"ComfyUI node '{name}' not found. Update ComfyUI to the latest version "
            f"(cd ComfyUI && git pull) and restart."
        )
    return cls


def call(cls, **kwargs):
    func_name = getattr(cls, "FUNCTION", "execute")
    return getattr(cls(), func_name)(**kwargs)


def check_interrupt():
    """Raise ComfyUI's interrupt exception if the user pressed Cancel."""
    try:
        import comfy.model_management as mm
        mm.throw_exception_if_processing_interrupted()
    except ImportError:
        pass


def make_progress(total: int):
    try:
        import comfy.utils
        return comfy.utils.ProgressBar(total)
    except ImportError:
        return None


# ── Paths ─────────────────────────────────────────────────────────────────────

def project_dir(project_name: str) -> str:
    """<ComfyUI output>/afe_projects/<project_name>  (created if missing)."""
    safe = "".join(c for c in project_name.strip() if c.isalnum() or c in "-_ ").strip() or "afe_project"
    try:
        import folder_paths
        base = folder_paths.get_output_directory()
    except ImportError:
        base = os.path.abspath("./output")
    path = os.path.join(base, "afe_projects", safe)
    os.makedirs(path, exist_ok=True)
    return path


def sub_dir(project: str, name: str) -> str:
    path = os.path.join(project, name)
    os.makedirs(path, exist_ok=True)
    return path


# ── Shot helpers ──────────────────────────────────────────────────────────────

def get_shots(shot_sequence) -> list:
    if isinstance(shot_sequence, list):
        return shot_sequence
    if isinstance(shot_sequence, dict):
        return shot_sequence.get("shots", [])
    if hasattr(shot_sequence, "shots"):
        return list(shot_sequence.shots)
    return []


def has_dialogue(shot: dict) -> bool:
    d = shot.get("dialogue")
    if d is None:
        return False
    return str(d).strip().lower() not in NO_DIALOGUE_MARKERS


def scene_names_in_order(shots: list) -> list[str]:
    """Unique scene_name values in first-appearance order.
    MUST match AFE_SceneAnalyzer's ordering so scene image i belongs to scene i."""
    seen: list[str] = []
    for shot in shots:
        name = (shot.get("scene_name") or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def shot_id_of(shot: dict, index: int) -> str:
    return str(shot.get("shot_id") or f"shot_{index + 1:03d}")


# ── Image / video IO ──────────────────────────────────────────────────────────

def save_png(image: torch.Tensor, path: str) -> None:
    """image: (1,H,W,3) or (H,W,3) float 0..1."""
    from PIL import Image
    arr = image[0] if image.dim() == 4 else image
    arr = (arr.clamp(0, 1).cpu().numpy() * 255.0).astype(np.uint8)
    Image.fromarray(arr[:, :, :3]).save(path)


def load_png(path: str) -> torch.Tensor:
    """-> (1,H,W,3) float 0..1."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    arr = np.asarray(img).astype(np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError(
            "ffmpeg not found. Run: pip install imageio-ffmpeg  (or apt-get install -y ffmpeg)"
        )


def write_mp4(frames: torch.Tensor, path: str, fps: float) -> None:
    """frames: (N,H,W,3) float 0..1  ->  H.264 mp4 (yuv420p) via ffmpeg pipe."""
    n, h, w, _ = frames.shape
    h2, w2 = h - (h % 2), w - (w % 2)      # yuv420p needs even dimensions
    arr = (frames[:, :h2, :w2, :3].clamp(0, 1).cpu().numpy() * 255.0).astype(np.uint8)
    cmd = [
        ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w2}x{h2}", "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-preset", "medium",
        "-movflags", "+faststart", path,
    ]
    proc = subprocess.run(cmd, input=arr.tobytes(), capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed writing {path}: {proc.stderr.decode(errors='replace')[:400]}")


def concat_mp4(clip_paths: list[str], out_path: str, list_file: str) -> None:
    """Join clips that share codec/size/fps with the concat demuxer (no re-encode)."""
    with open(list_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write("file '" + os.path.abspath(p).replace("\\", "/").replace("'", "'\\''") + "'\n")
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
           "-i", list_file, "-c", "copy", "-movflags", "+faststart", out_path]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {proc.stderr.decode(errors='replace')[:400]}")
