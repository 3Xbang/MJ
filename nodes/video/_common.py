"""
Shared helpers for the video-production nodes (cast refs, keyframes, Wan render, assembly).

Everything here is plain Python + torch so it can be unit-tested without ComfyUI.
ComfyUI-only imports (folder_paths, comfy.*) are done lazily inside functions.
"""
from __future__ import annotations

import filecmp
import hashlib
import logging
import os
import re
import shutil
import subprocess

import numpy as np
import torch

logger = logging.getLogger("AFE_Video")

NO_DIALOGUE_MARKERS = {"", "（无）", "(无)", "无", "none", "null", "n/a"}

try:  # present in current ComfyUI; lets a closed gate skip downstream nodes silently
    from comfy_execution.graph import ExecutionBlocker
except Exception:  # pragma: no cover - older ComfyUI / unit tests
    ExecutionBlocker = None


# ── Approval gates ────────────────────────────────────────────────────────────
# Every expensive stage has a "confirm to continue" switch (default: waiting) and an optional
# master switch `auto_all`. A closed gate does no work and blocks everything downstream of its
# data outputs; its report output still carries the waiting message so the text boxes show it.

def gate_input(what: str):
    """The per-node 'confirm to continue' switch (default: waiting)."""
    return ("BOOLEAN", {"default": False, "label_on": "▶ 已确认，开始", "label_off": "⏸ 等待确认",
                        "tooltip": f"检查上一步结果后切到「已确认」再 Queue。本节点将：{what}"})


def auto_all_input():
    """Optional socket for the master switch (core PrimitiveBoolean). ON = never wait."""
    return ("BOOLEAN", {"forceInput": True, "tooltip": "接「全自动模式」总开关。打开=所有关口都不停顿"})


def gate_is_open(approved: bool, auto_all: bool = False) -> bool:
    return bool(approved) or bool(auto_all)


def waiting_message(stage: str) -> str:
    return (f"⏸ 等待确认：{stage}\n"
            f"请先检查上一步的结果，然后在本节点把开关切到「已确认」"
            f"（或打开总开关「全自动模式」），再点 Queue。")


def closed_result(stage: str, layout: str):
    """Result for a closed gate. layout: one char per output, 'd' = data (blocked), 'r' = report."""
    msg = waiting_message(stage)
    if ExecutionBlocker is None:
        raise RuntimeError(msg)
    outs = tuple(msg if ch == "r" else ExecutionBlocker(None) for ch in layout)
    return {"ui": {"text": [msg]}, "result": outs}


# ── Pick / redo syntax ("shot_005:2, 7:3") ────────────────────────────────────

def split_items(text: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,;，；\n]+", text or "") if t.strip()]


def split_pair(item: str) -> tuple[str, str | None]:
    m = re.match(r"^(.*?)\s*[:=：]\s*([^:=：]+?)\s*$", item)
    return (m.group(1).strip(), m.group(2).strip()) if m else (item.strip(), None)


def norm_shot_key(tok: str) -> str:
    tok = tok.strip()
    return f"shot_{int(tok):03d}" if tok.isdigit() else tok


def parse_shot_numbers(text: str, default_value: int = 1) -> dict[str, int]:
    """'shot_005:2, 7:3, shot_009' -> {'shot_005': 2, 'shot_007': 3, 'shot_009': default_value}"""
    out: dict[str, int] = {}
    for item in split_items(text):
        key, val = split_pair(item)
        if not key:
            continue
        try:
            n = int(val) if val is not None else default_value
        except ValueError:
            logger.warning("ignoring bad entry %r", item)
            continue
        out[norm_shot_key(key)] = n
    return out


def parse_index_numbers(text: str, names: list[str] | None = None, default_value: int = 1) -> dict[int, int]:
    """For items addressed by 1-based number OR name: 'Ann:2, 3:1, Bo' -> {0: 2, 2: 1, 1: default}"""
    out: dict[int, int] = {}
    low = [n.lower() for n in (names or [])]
    for item in split_items(text):
        key, val = split_pair(item)
        if key.isdigit():
            idx = int(key) - 1
        elif key.lower() in low:
            idx = low.index(key.lower())
        else:
            logger.warning("ignoring unknown name/number %r", item)
            continue
        try:
            n = int(val) if val is not None else default_value
        except ValueError:
            logger.warning("ignoring bad entry %r", item)
            continue
        out[idx] = n
    return out


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


# ── Signatures: an artifact is rebuilt only when what it depends on changed ──

def md5(*parts) -> str:
    h = hashlib.md5()
    for p in parts:
        h.update(str(p).encode("utf-8", errors="replace"))
        h.update(b"|")
    return h.hexdigest()


def tensor_sig(t: torch.Tensor) -> str:
    """Cheap content fingerprint of an image tensor."""
    small = t[:, ::16, ::16, :3].detach().cpu().contiguous().numpy()
    return hashlib.md5(small.tobytes()).hexdigest()[:10]


def files_differ(a: str, b: str) -> bool:
    if not os.path.exists(b):
        return True
    return not filecmp.cmp(a, b, shallow=False)


# ── Preview helpers ───────────────────────────────────────────────────────────

def label_image(image: torch.Tensor, text: str, max_width: int = 640) -> torch.Tensor:
    """Down-size to max_width and stamp an ASCII label on a dark banner. (1,H,W,3) -> (1,h,w,3)."""
    from PIL import Image, ImageDraw, ImageFont
    arr = (image[0].clamp(0, 1).cpu().numpy() * 255.0).astype(np.uint8)[:, :, :3]
    img = Image.fromarray(arr)
    if img.width > max_width:
        img = img.resize((max_width, max(1, round(img.height * max_width / img.width))), Image.LANCZOS)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=max(14, img.width // 22))
    except TypeError:                       # old Pillow: fixed-size bitmap font
        font = ImageFont.load_default()
    pad = 4
    box = draw.textbbox((0, 0), text, font=font)
    draw.rectangle([0, 0, box[2] - box[0] + pad * 2, box[3] - box[1] + pad * 2], fill=(0, 0, 0))
    draw.text((pad, pad - box[1]), text, fill=(255, 255, 0), font=font)
    return torch.from_numpy(np.asarray(img).astype(np.float32) / 255.0).unsqueeze(0)


def align_batch(images: list[torch.Tensor]) -> torch.Tensor:
    """Stack images of possibly different sizes by resizing to the first one."""
    h, w = images[0].shape[1], images[0].shape[2]
    out = []
    for f in images:
        if f.shape[1] != h or f.shape[2] != w:
            f = torch.nn.functional.interpolate(f.movedim(-1, 1), size=(h, w), mode="bilinear").movedim(1, -1)
        out.append(f)
    return torch.cat(out, dim=0)


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

def safe_project_name(name: str) -> str:
    return "".join(c for c in (name or "").strip() if c.isalnum() or c in "-_ ").strip() or "afe_project"


def project_dir(project_name: str) -> str:
    """<ComfyUI output>/afe_projects/<project_name>  (created if missing)."""
    safe = safe_project_name(project_name)
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
