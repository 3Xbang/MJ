"""
AFE_MovieAssembler — joins the per-shot clips into one finished film.

Looks for <project_dir>/clips_av/<shot_id>.mp4 first (clips that already carry the dialogue
audio track), then <project_dir>/clips/<shot_id>.mp4 (silent Wan clips). All clips are written
by the same ffmpeg settings, so they are joined with the concat demuxer without re-encoding.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

from ai_film_editor_nodes.nodes.video._common import (
    auto_all_input, closed_result, concat_mp4, gate_input, gate_is_open, get_shots, has_dialogue,
    md5, shot_id_of,
    split_items, norm_shot_key,
)
from ai_film_editor_nodes.nodes.video.shot_prompt_contract import build_video_prompt, render_shared_facts

logger = logging.getLogger("AFE_MovieAssembler")


def _clip_candidates(project: str, sid: str) -> list[str]:
    return [os.path.join(project, folder, f"{sid}.mp4")
            for folder in ("clips_av", "clips")
            if os.path.exists(os.path.join(project, folder, f"{sid}.mp4"))]


def find_clip(project: str, sid: str) -> str | None:
    candidates = _clip_candidates(project, sid)
    return candidates[0] if candidates else None


def _keyframe_hash(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def _file_hash(path: str) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_audio_manifest(project: str, value="") -> tuple[dict, bool]:
    """Load the current TTS/audio manifest and report whether one was supplied."""
    candidates = []
    if isinstance(value, dict):
        return value, True
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if os.path.isfile(text):
            if not text.lower().endswith(".json"):
                return {"__audio_path__": text}, True
            candidates.append(text)
        else:
            try:
                parsed = json.loads(text)
                return (parsed if isinstance(parsed, (dict, list)) else {}), True
            except (TypeError, ValueError):
                return {}, True
    else:
        candidates.extend((
            os.path.join(project, "audio_manifest.json"),
            os.path.join(project, "audio", "manifest.json"),
            os.path.join(project, "audio", "tts_manifest.json"),
            os.path.join(project, "clips_av", "audio_manifest.json"),
        ))
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as handle:
                parsed = json.load(handle)
            if isinstance(parsed, (dict, list)):
                return parsed, True
        except (OSError, ValueError):
            continue
    return {}, bool(value and str(value).strip())


def _audio_entry(manifest, sid: str):
    entries = manifest.get("shots", manifest) if isinstance(manifest, dict) else manifest
    if isinstance(entries, dict):
        return entries.get(sid)
    if isinstance(entries, list):
        return next((item for item in entries if isinstance(item, dict) and
                     str(item.get("shot_id") or item.get("id")) == sid), None)
    return None


def _expected_audio_signature(project: str, sid: str, manifest) -> str:
    if isinstance(manifest, dict) and manifest.get("__audio_path__"):
        path = str(manifest["__audio_path__"])
        path = path if os.path.isabs(path) else os.path.join(project, path)
        return _file_hash(path) if os.path.exists(path) else ""
    entry = _audio_entry(manifest, sid)
    if isinstance(entry, str):
        path = entry
        return _file_hash(path if os.path.isabs(path) else os.path.join(project, path)) \
            if os.path.exists(path if os.path.isabs(path) else os.path.join(project, path)) else ""
    if not isinstance(entry, dict):
        return ""
    signature = entry.get("audio_sig") or entry.get("signature") or entry.get("sig")
    if signature:
        return str(signature)
    path = entry.get("audio_path") or entry.get("path") or entry.get("file")
    if not path:
        return ""
    path = path if os.path.isabs(str(path)) else os.path.join(project, str(path))
    return _file_hash(path) if os.path.exists(path) else ""


def _clip_current(project: str, shot: dict, sid: str, path: str, render_style: str = "",
                  audio_manifest="") -> tuple[bool, str]:
    keyframe = os.path.join(project, "keyframes", f"{sid}.png")
    meta_path = os.path.splitext(path)[0] + ".json"
    if not os.path.exists(keyframe):
        return False, f"missing current keyframe {keyframe}"
    if not os.path.exists(meta_path):
        return False, f"missing render metadata {meta_path}"
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError) as exc:
        return False, f"invalid render metadata: {exc}"
    is_audio_copy = os.path.basename(os.path.dirname(path)) == "clips_av"
    if is_audio_copy:
        # Audio copies must identify the exact silent render they wrap. This
        # prevents an old clips_av file from masking a current clips file.
        source_meta_path = os.path.join(project, "clips", f"{sid}.json")
        source_sig = meta.get("source_render_sig")
        if not meta.get("audio_sig") or not source_sig:
            return False, "audio copy lacks source render/audio signatures"
        try:
            with open(source_meta_path, encoding="utf-8") as f:
                source_meta = json.load(f)
        except (OSError, ValueError) as exc:
            return False, f"audio copy source metadata unavailable: {exc}"
        if source_meta.get("sig") != source_sig:
            return False, "audio copy wraps a stale render"
        manifest, manifest_present = _load_audio_manifest(project, audio_manifest)
        if not manifest_present:
            return False, "current audio manifest is unavailable; use the current silent clip"
        expected_audio_sig = _expected_audio_signature(project, sid, manifest)
        if not expected_audio_sig:
            return False, "current audio signature is unavailable"
        if meta.get("audio_sig") != expected_audio_sig:
            return False, "audio copy uses a stale audio signature"
    if meta.get("keyframe_sig") != _keyframe_hash(keyframe):
        return False, "clip keyframe signature is stale"
    expected_contract = md5(render_shared_facts(shot), has_dialogue(shot))
    if meta.get("contract_sig") != expected_contract:
        return False, "clip screenplay contract signature is stale"
    if render_style and meta.get("prompt_sig") != md5(build_video_prompt(shot, render_style, has_dialogue(shot))):
        return False, "clip prompt signature is stale"
    return True, ""


class AFE_MovieAssembler:
    """All shot clips, in script order -> <project_dir>/<output_name>.mp4"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
                "project_dir": ("STRING", {"forceInput": True,
                                           "tooltip": "project_dir from AFE_WanShotRenderer"}),
                "output_name": ("STRING", {"default": "final_movie"}),
            },
            "optional": {
                "render_style": ("STRING", {"default": "",
                                               "tooltip": "与 Wan 渲染相同的风格，用于合成前提示词签名校验"}),
                "audio_manifest": ("STRING", {"default": "",
                                                 "tooltip": "当前 TTS 音频 manifest JSON 或路径；用于拒绝旧对白"}),
                "skip_shots": ("STRING", {"default": "",
                                          "tooltip": "成片里不要的分镜。例：shot_007, 12"}),
                "approved": gate_input("把所有分镜视频合成成片"),
                "auto_all": auto_all_input(),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("movie_path", "report")
    FUNCTION = "assemble"
    CATEGORY = "AI Film Editor/Video"
    OUTPUT_NODE = True

    def assemble(self, shot_sequence, project_dir, output_name="final_movie", skip_shots="",
                 render_style="", audio_manifest="", approved=False, auto_all=False):
        if not gate_is_open(approved, auto_all):
            return closed_result("成片合成（合成前请确认各分镜视频）", "dr")
        skip = {norm_shot_key(t) for t in split_items(skip_shots)}
        shots = get_shots(shot_sequence)
        found, missing, invalid, total_s = [], [], [], 0.0
        for i, shot in enumerate(shots):
            sid = shot_id_of(shot, i)
            if sid in skip:
                continue
            candidates = _clip_candidates(project_dir, sid)
            if not candidates:
                missing.append(sid)
                continue
            reasons = []
            selected = None
            for candidate in candidates:
                current, reason = _clip_current(project_dir, shot, sid, candidate, render_style,
                                                audio_manifest)
                if current:
                    selected = candidate
                    break
                reasons.append(f"{os.path.basename(os.path.dirname(candidate))}: {reason}")
            if selected:
                found.append(selected)
                total_s += float(shot.get("duration_seconds") or 5.0)
            else:
                invalid.append(f"{sid} ({'; '.join(reasons)})")
                missing.append(sid)

        if missing:
            details = ", ".join(invalid) if invalid else "none"
            raise RuntimeError(
                "Cannot assemble film because clips are missing or stale for unskipped shots: "
                + ", ".join(missing) + f". Invalid details: {details}. "
                "Render those shots or add their shot IDs to skip_shots."
            )
        if not found:
            raise ValueError(f"No clips found in {project_dir}/clips. Run AFE_WanShotRenderer first.")

        safe = "".join(c for c in output_name if c.isalnum() or c in "-_ ").strip() or "final_movie"
        out_path = os.path.join(project_dir, f"{safe}.mp4")
        concat_mp4(found, out_path, os.path.join(project_dir, "concat_list.txt"))

        lines = [
            "🎞 成片合成完成",
            f"镜头 {len(found)} / {len(shots)}，约 {total_s:.0f} 秒" + (f"（按你的设置排除 {len(skip)} 个）" if skip else ""),
            f"文件：{out_path}",
        ]
        if missing:
            lines.append(f"⚠️ 缺少 {len(missing)} 个镜头（已跳过）：{', '.join(missing[:12])}"
                         + (" ..." if len(missing) > 12 else ""))
        report = "\n".join(lines)
        logger.info(report)
        return {"ui": {"text": [report], "afe_movie": [os.path.basename(out_path)]},
                "result": (out_path, report)}
