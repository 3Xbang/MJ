"""
Web UI backend. Registers /afe/* routes on ComfyUI's own web server, so the UI is reachable at the
same address as ComfyUI (no extra port):    http://<pod>:8188/afe/

The browser talks to these routes; the routes queue ComfyUI API prompts built by graphs.py through
ComfyUI's normal /prompt endpoint, then read the results back from /history and save a compact
project state next to the generated files:
    <output>/afe_projects/<project>/ui_state.json   settings + results shown by the UI
    <output>/afe_projects/<project>/analysis.json   shots + cast (read by AFE_AnalysisLoader)
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import time
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout, web

from ai_film_editor_nodes.webui import graphs
from ai_film_editor_nodes.nodes.director.script_analysis_session import (
    AnalysisSessionStore, DEFAULT_BATCH_SIZE, script_signature,
)
from ai_film_editor_nodes.nodes.director.script_full_parser_node import _build_scene_map, _source_units_with_offsets

logger = logging.getLogger("AFE_WebUI")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MIME_NO_CACHE = {"Cache-Control": "no-store"}
# settings that decide what a step produced; the UI compares them with the current choices
USED_KEYS = ("cast_picks", "cast_redo", "scene_view_picks", "kf_picks", "kf_redo", "kf_variants",
             "video_redo", "long_takes", "skip_shots")


# ── project files ─────────────────────────────────────────────────────────────

REF_KINDS = ("cast", "scene", "prop")
MAX_REF_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_REF_PIXELS = 25_000_000
MAX_REF_DIMENSION = 8192


def ref_filename(kind: str, name: str) -> str:
    """Must stay identical to nodes.video._common.ref_filename()."""
    return f"{kind}_{hashlib.md5((name or '').strip().lower().encode('utf-8')).hexdigest()[:10]}.png"


def safe_project_name(name: str) -> str:
    """Must stay identical to nodes.video._common.project_dir()'s sanitising."""
    return "".join(c for c in (name or "").strip() if c.isalnum() or c in "-_ ").strip() or "afe_project"


def read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def file_url(project: str, rel: str, project_path: str) -> str:
    full = os.path.join(project_path, rel)
    mtime = int(os.path.getmtime(full)) if os.path.exists(full) else 0
    return f"/afe/api/file?project={quote(project)}&path={quote(rel)}&t={mtime}"


def view_urls(entry: dict) -> list[str]:
    return [f"/view?filename={quote(i['filename'])}&subfolder={quote(i.get('subfolder', ''))}"
            f"&type={i.get('type', 'output')}" for i in entry.get("images", [])]


# ── turning ComfyUI history into UI state ────────────────────────────────────

def _first_json(entry: dict, key: str, default=None):
    vals = entry.get(key) or []
    if not vals:
        return default
    try:
        return json.loads(vals[0])
    except Exception:
        return default


def _text(entry: dict) -> str:
    return "\n".join(str(t) for t in (entry.get("text") or []))


def _validate_analysis_payload(analysis: dict) -> None:
    """Reject incomplete, duplicated, or reordered current-schema parser results."""
    if not isinstance(analysis, dict) or analysis.get("schema_version") != "afe-analysis-v1":
        raise ValueError("剧本分析缺少当前版本的结构化来源清单，请重新运行分析。")
    shots = analysis.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("剧本分析没有返回分镜，请检查剧本内容是否完整。")
    if analysis.get("analysis_status") != "complete":
        raise ValueError("剧本分析尚未完成，已阻止保存，请重新运行分析。")
    expected_count = analysis.get("expected_shot_count")
    if not isinstance(expected_count, int) or expected_count <= 0 or expected_count != len(shots):
        raise ValueError(
            f"剧本分析分镜数量不完整：清单要求 {expected_count} 个，实际返回 {len(shots)} 个。"
        )

    manifest = analysis.get("source_manifest")
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("剧本分析缺少有效的原文来源清单。")
    manifest_ids = {}
    manifest_units = {}
    all_units = set()
    for position, item in enumerate(manifest):
        if not isinstance(item, dict) or not str(item.get("source_block_id") or "").strip():
            raise ValueError(f"原文来源清单第 {position + 1} 项无效。")
        block_id = str(item["source_block_id"])
        if block_id in manifest_ids:
            raise ValueError(f"原文来源清单重复：{block_id}")
        if item.get("order") != position:
            raise ValueError(f"原文来源清单顺序错误：{block_id}")
        unit_ids = item.get("unit_ids")
        if not isinstance(unit_ids, list) or not unit_ids or any(not str(unit).strip() for unit in unit_ids):
            raise ValueError(f"原文来源清单 {block_id} 缺少完整原文单元。")
        normalized_units = [str(unit).strip() for unit in unit_ids]
        if len(set(normalized_units)) != len(normalized_units):
            raise ValueError(f"原文来源清单重复原文单元：{block_id}")
        overlap = {(block_id, unit) for unit in normalized_units}.intersection(all_units)
        if overlap:
            raise ValueError(f"原文来源清单重复原文单元：{block_id}")
        manifest_ids[block_id] = position
        manifest_units[block_id] = normalized_units
        all_units.update((block_id, unit) for unit in normalized_units)

    errors = []
    seen = set()
    covered_units = set()
    evidence_positions = []
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            errors.append(f"shot_{index + 1:03d}: 分镜不是结构化对象")
            continue
        shot_id = str(shot.get("shot_id") or f"shot_{index + 1:03d}")
        if shot_id in seen:
            errors.append(f"{shot_id}: 分镜编号重复")
        seen.add(shot_id)
        required = ("scene_id", "scene_occurrence_id", "source_block_id", "section_type")
        missing = [key for key in required if not str(shot.get(key) or "").strip()]
        if missing:
            errors.append(f"{shot_id}: 缺少 {', '.join(missing)}")
        if shot.get("scene_assignment_error") or shot.get("source_validation_error"):
            errors.append(f"{shot_id}: 原文来源未验证")
        block_id = str(shot.get("source_block_id") or "")
        if block_id not in manifest_ids:
            errors.append(f"{shot_id}: source_block_id 不在原文来源清单中")
            continue
        unit_ids = shot.get("source_unit_ids")
        if not isinstance(unit_ids, list) or not unit_ids:
            errors.append(f"{shot_id}: 缺少可验证的 source_unit_ids")
            continue
        normalized_units = [str(unit).strip() for unit in unit_ids]
        if len(set(normalized_units)) != len(normalized_units):
            errors.append(f"{shot_id}: source_unit_ids 重复")
            continue
        unknown = [unit for unit in normalized_units if unit not in manifest_units[block_id]]
        if unknown:
            errors.append(f"{shot_id}: source_unit_ids 不属于 {block_id}")
            continue
        unit_positions = [manifest_units[block_id].index(unit) for unit in normalized_units]
        if unit_positions != sorted(unit_positions):
            errors.append(f"{shot_id}: source_unit_ids 未按原文顺序排列")
            continue
        duplicate = [(block_id, unit) for unit in normalized_units if (block_id, unit) in covered_units]
        if duplicate:
            errors.append(f"{shot_id}: 重复覆盖原文单元 {', '.join(unit for _, unit in duplicate)}")
        covered_units.update((block_id, unit) for unit in normalized_units)
        evidence_positions.append((manifest_ids[block_id], manifest_units[block_id].index(normalized_units[0]), shot_id))

    missing_units = sorted(all_units - covered_units)
    if missing_units:
        errors.append("遗漏原文单元：" + ", ".join(f"{block}:{unit}" for block, unit in missing_units[:20]))
    if covered_units - all_units:
        errors.append("出现清单外原文单元：" + ", ".join(f"{block}:{unit}" for block, unit in sorted(covered_units - all_units)[:20]))
    if evidence_positions != sorted(evidence_positions):
        errors.append("分镜来源顺序与原文来源清单不一致")
    if errors:
        raise ValueError(
            "剧本分析被阻止：返回的分镜未通过来源完整性检查。\n"
            + "\n".join(f"  - {error}" for error in errors[:40])
        )


def extract_results(stage: int, outputs: dict, part: str = "all") -> dict:
    """outputs = history[prompt_id]["outputs"]  ->  dict of what the UI should remember."""
    res: dict = {}
    if stage == 1:
        o1, o2, o3 = outputs.get("1", {}), outputs.get("2", {}), outputs.get("3", {})
        analysis = _first_json(o1, "afe_analysis")
        _validate_analysis_payload(analysis or {})
        res["analysis"] = analysis
        res["scenes"] = _first_json(o2, "afe_scenes", [])
        res["props"] = _first_json(o3, "afe_props", [])
        res["reports"] = {"parse": _text(o1), "scenes": _text(o2), "props": _text(o3)}
    elif stage == 2:
        res["cast_manifest"] = _first_json(outputs.get("6", {}), "afe_manifest", [])
        res["report"] = _text(outputs.get("6", {}))
        if part != "cast":
            sm = sorted(_first_json(outputs.get("4", {}), "afe_manifest", []), key=lambda m: m["scene"])
            res["scene_files"] = {k: [m["file"] for m in sm if m["view"] == k] for k in ("est", "med", "atm")}
            res["props_files"] = [{"name": m.get("name", ""), "file": m["file"]}
                                for m in sorted(_first_json(outputs.get("5", {}), "afe_manifest", []), key=lambda m: m["index"])]
    elif stage == 3:
        o = outputs.get("11", {})
        res["kf_manifest"] = _first_json(o, "afe_manifest", [])
        res["report"] = _text(o)
    elif stage == 4:
        res["report"] = _text(outputs.get("12", {}))
    elif stage == 5:
        o = outputs.get("13", {})
        movie = (o.get("afe_movie") or [""])[0]
        if not movie:
            raise ValueError("没有可合成的分镜视频，请先完成第④步。")
        res["movie"] = movie
        res["report"] = _text(o)
    return res


def friendly_error(message: str, node_type: str = "") -> str:
    m = (message or "").strip()
    low = m.lower()
    if "out of memory" in low or "oom" in low:
        return "显存不足。请把「视频分辨率」调低一档，或等其他任务结束后重试。"
    if "not found" in low and "node" in low:
        return "缺少节点或模型文件。请在 RunPod 终端重新运行部署命令，然后刷新页面。"
    if "no such file" in low or "value_not_in_list" in low:
        return "缺少模型文件。请在 RunPod 终端重新运行部署命令。"
    return (f"{node_type}：" if node_type else "") + (m.splitlines()[0][:300] if m else "未知错误")


# ── API ───────────────────────────────────────────────────────────────────────

_VERSION = None


def code_version() -> str:
    """Short git commit of the installed code, shown in the page header so support can tell at a glance
    whether the Pod runs the latest version."""
    global _VERSION
    if _VERSION is None:
        try:
            import subprocess
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            _VERSION = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"], capture_output=True,
                                      text=True, timeout=5).stdout.strip() or "未知"
        except Exception:
            _VERSION = "未知"
    return _VERSION


class Api:
    def __init__(self, out_dir, comfy_base, node_classes=None, options=None):
        """out_dir/comfy_base/node_classes: values or zero-arg callables (lazy, ComfyUI starts later)."""
        self._out_dir, self._comfy_base = out_dir, comfy_base
        self._node_classes, self._options = node_classes, options

    # helpers
    def out_dir(self):
        return self._out_dir() if callable(self._out_dir) else self._out_dir

    def comfy(self):
        return self._comfy_base() if callable(self._comfy_base) else self._comfy_base

    def projects_root(self):
        return os.path.join(self.out_dir(), "afe_projects")

    def project_path(self, name: str) -> str:
        return os.path.join(self.projects_root(), safe_project_name(name))

    def state(self, project_path: str) -> dict:
        return read_json(os.path.join(project_path, "ui_state.json"), {}) or {}

    def save_state(self, project_path: str, st: dict) -> None:
        write_json(os.path.join(project_path, "ui_state.json"), st)

    def session_store(self, project_path: str) -> AnalysisSessionStore:
        return AnalysisSessionStore(os.path.join(project_path, "analysis_session"), DEFAULT_BATCH_SIZE)

    def analysis_status(self, project_path: str) -> dict:
        store = self.session_store(project_path)
        state = store.status()
        if not state:
            return {"analysis_status": "none", "completed_shot_count": 0}
        return {
            "analysis_status": state.get("analysis_status", "partial"),
            "target_shot_count": state.get("target_shot_count", 0),
            "script_signature": state.get("script_signature"),
            "batch_size": state.get("batch_size", DEFAULT_BATCH_SIZE),
            "total_batches": state.get("total_batches", 0),
            "current_batch": state.get("current_batch"),
            "completed_batches": state.get("completed_batches", []),
            "failed_batches": state.get("failed_batches", []),
            "batches": state.get("batches", []),
            "completed_shot_count": state.get("completed_shot_count", 0),
            "error": next((b.get("error") for b in state.get("batches", []) if b.get("status") == "failed"), None),
        }

    async def prompt_is_known(self, prompt_id: str) -> bool:
        """Check history and queue before re-submitting a persisted batch."""
        if not prompt_id:
            return False
        try:
            async with ClientSession(timeout=ClientTimeout(total=5)) as sess:
                async with sess.get(f"{self.comfy()}/history/{quote(str(prompt_id))}") as response:
                    history = await response.json(content_type=None)
                if isinstance(history, dict) and prompt_id in history:
                    return True
                async with sess.get(f"{self.comfy()}/queue") as response:
                    queue = await response.json(content_type=None)
                return prompt_id in json.dumps(queue, ensure_ascii=False)
        except Exception:
            return False

    async def cancel_prompt(self, prompt_id: str) -> None:
        """Cancel only the persisted analysis prompt, never another project job."""
        if not prompt_id:
            return
        async with ClientSession(timeout=ClientTimeout(total=10)) as sess:
            async with sess.get(f"{self.comfy()}/queue") as response:
                queue = await response.json(content_type=None)
            pending = {str(item[1]) for item in (queue.get("queue_pending") or [])
                       if isinstance(item, (list, tuple)) and len(item) > 1}
            running = {str(item[1]) for item in (queue.get("queue_running") or [])
                       if isinstance(item, (list, tuple)) and len(item) > 1}
            if str(prompt_id) in pending:
                async with sess.post(f"{self.comfy()}/queue", json={"delete": [prompt_id]}) as response:
                    if response.status >= 400:
                        raise RuntimeError(f"删除排队任务失败（HTTP {response.status}）")
            elif str(prompt_id) in running:
                async with sess.post(f"{self.comfy()}/interrupt", json={"prompt_id": prompt_id}) as response:
                    if response.status >= 400:
                        raise RuntimeError(f"中断当前分析任务失败（HTTP {response.status}）")

    def project_view(self, name: str) -> dict:
        pp = self.project_path(name)
        pname = safe_project_name(name)
        st = self.state(pp)
        analysis = read_json(os.path.join(pp, "analysis.json"))
        session = self.session_store(pp).load()
        settings = st.get("settings") or {}
        target_count = max(1, round(int(settings.get("duration", 180)) /
                                int(settings.get("seconds_per_shot", 5))))
        expected_signature = script_signature(
            settings.get("script", ""), target_count,
            int(settings.get("seconds_per_shot", 5)), settings.get("episode", "")
        )
        # A previous analysis file is retained on purpose, but it must never be
        # presented as the current script while a resumable session is partial
        # or its signature differs from the current settings.
        analysis_current = bool(analysis)
        if session:
            analysis_current = bool(
                analysis and session.get("analysis_status") == "complete"
                and analysis.get("session_signature") == session.get("script_signature")
                and session.get("script_signature") == expected_signature
            )
        elif analysis and analysis.get("session_signature"):
            analysis_current = analysis.get("session_signature") == expected_signature
        current_analysis = analysis if analysis_current else None
        stale_analysis = bool(analysis) and not analysis_current
        scenes = st.get("scenes", []) if analysis_current else []
        props = st.get("props", []) if analysis_current else []
        assets = st.get("assets") if analysis_current else None
        if assets:
            assets = {"scene_images": {k: [file_url(pname, f, pp) for f in files]
                                       for k, files in assets.get("scene_files", {}).items()},
                      "props_images": [{"url": file_url(pname, p["file"], pp), "name": p.get("name", "")}
                                       for p in assets.get("props_files", [])]}
        view = {"project": pname, "settings": graphs.merged(st.get("settings")),
                "done": st.get("done", {}) if analysis_current else {},
                "has_analysis": bool(current_analysis), "analysis": None, "assets": assets,
                "stale_analysis": stale_analysis,
                "stale_analysis_message": "检测到旧剧本分析，已隐藏；请继续当前剧本的分批分析。" if stale_analysis else "",
                "analysis_progress": self.analysis_status(pp),
                "kf_manifest": st.get("kf_manifest", []) if analysis_current else [],
                "reports": st.get("reports", {}) if analysis_current else {},
                "used": st.get("used", {}),
                "keyframes": {}, "clips": {}, "movie": None}
        if current_analysis:
            view["analysis"] = {
                "shots": [{"id": s.get("shot_id"), "scene": s.get("scene_name"),
                           "scene_id": s.get("scene_id"), "section_type": s.get("section_type"),
                           "scene_occurrence_id": s.get("scene_occurrence_id"),
                           "chars": s.get("character_names", []), "dialogue": s.get("dialogue"),
                           "duration": s.get("duration_seconds"), "type": s.get("shot_type"),
                           "camera_motion": s.get("camera_motion"), "camera_angle": s.get("camera_angle"),
                           "pace": s.get("pace"), "expression": s.get("facial_expression") or s.get("emotion"),
                           "micro_expression": s.get("micro_expression"), "action_start": s.get("action_start"),
                           "action_process": s.get("action_process") or s.get("business"), "action_end": s.get("action_end"),
                           "props": s.get("props_list", []), "prop_interactions": s.get("prop_interactions", []),
                           "environment": s.get("environment") or s.get("scene_environment_en"),
                           "lighting": s.get("lighting"), "time_of_day": s.get("time_of_day", ""),
                           "weather": s.get("weather", ""),
                           "desc": s.get("shot_description") or s.get("action") or ""}
                          for s in current_analysis.get("shots", [])],
                "cast": [{"name": c.get("name"), "role": c.get("role_type"), "gender": c.get("gender"),
                          "look": c.get("appearance_en")} for c in current_analysis.get("cast", [])],
                "scenes": scenes, "props": props,
            }
        view["refs"] = self.refs_view(pname, pp, current_analysis, scenes, props)
        view["ref_sig"] = self.ref_sig(pp) if analysis_current else ""
        view["ref_entities"] = self.ref_entity_sigs(pp, current_analysis, scenes, props)
        kd = os.path.join(pp, "keyframes")
        if analysis_current and os.path.isdir(kd):
            for f in os.listdir(kd):
                if f.endswith(".png") and not re.search(r"_v\d+_[0-9a-f]{8}\.png$", f):
                    view["keyframes"][f[:-4]] = file_url(pname, f"keyframes/{f}", pp)
        cd = os.path.join(pp, "clips")
        if analysis_current and os.path.isdir(cd):
            for f in os.listdir(cd):
                if f.endswith(".mp4"):
                    view["clips"][f[:-4]] = file_url(pname, f"clips/{f}", pp)
        if analysis_current and st.get("movie") and os.path.exists(os.path.join(pp, st["movie"])):
            view["movie"] = {"file": st["movie"], "url": file_url(pname, st["movie"], pp)}
        return view

    def cast_images(self, name: str, manifest: list) -> list:
        pp, pname = self.project_path(name), safe_project_name(name)
        return [dict(m, url=file_url(pname, m["file"], pp)) for m in manifest
                if os.path.exists(os.path.join(pp, m["file"]))]

    # reference pictures uploaded by the user ------------------------------------------------
    def ref_sig(self, pp: str) -> str:
        d = os.path.join(pp, "refs")
        if not os.path.isdir(d):
            return ""
        items = []
        for name in sorted(f for f in os.listdir(d) if f.endswith(".png")):
            path = os.path.join(d, name)
            try:
                with open(path, "rb") as handle:
                    digest = hashlib.sha256(handle.read()).hexdigest()
            except OSError:
                continue
            items.append((name, digest))
        return hashlib.sha256(json.dumps(items, separators=(",", ":")).encode()).hexdigest()[:10] if items else ""

    def ref_entity_sigs(self, pp: str, analysis: dict | None, scenes: list, props: list) -> dict:
        """Return stable per-asset signatures so callers can invalidate only dependent shots."""
        names = {
            "cast": [c.get("name") for c in (analysis or {}).get("cast", [])],
            "scene": [s.get("scene_name") for s in scenes or []],
            "prop": [p.get("name") for p in props or []],
        }
        result = {}
        for kind, entities in names.items():
            for name in entities:
                if not name:
                    continue
                path = os.path.join(pp, "refs", ref_filename(kind, name))
                key = f"{kind}:{name}"
                if os.path.isfile(path):
                    with open(path, "rb") as fh:
                        result[key] = hashlib.md5(fh.read()).hexdigest()[:12]
                else:
                    result[key] = ""
        return result

    def refs_view(self, pname: str, pp: str, analysis: dict | None, scenes: list, props: list) -> dict:
        out = {"cast": {}, "scene": {}, "prop": {}}
        names = {"cast": [c.get("name") for c in (analysis or {}).get("cast", [])],
                 "scene": [s.get("scene_name") for s in scenes or []],
                 "prop": [p.get("name") for p in props or []]}
        for kind, lst in names.items():
            for name in lst:
                if name and os.path.exists(os.path.join(pp, "refs", ref_filename(kind, name))):
                    out[kind][name] = file_url(pname, f"refs/{ref_filename(kind, name)}", pp)
        return out

    async def upload_ref(self, request):
        q = request.query
        kind, name = q.get("kind", ""), (q.get("name") or "").strip()
        if kind not in REF_KINDS or not name:
            return web.json_response({"error": "缺少参数。"}, status=400)
        content_length = request.content_length
        if content_length is not None and content_length > MAX_REF_UPLOAD_BYTES:
            return web.json_response({"error": "图片文件过大，最大支持 20 MB。"}, status=413)
        chunks = []
        total = 0
        while True:
            chunk = await request.content.read(min(64 * 1024, MAX_REF_UPLOAD_BYTES - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_REF_UPLOAD_BYTES:
                return web.json_response({"error": "图片文件过大，最大支持 20 MB。"}, status=413)
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data:
            return web.json_response({"error": "上传文件为空。"}, status=400)
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data))
            if (im.width > MAX_REF_DIMENSION or im.height > MAX_REF_DIMENSION
                    or im.width * im.height > MAX_REF_PIXELS):
                return web.json_response({"error": "图片尺寸过大，最大支持 8192 像素边长和 2500 万像素。"}, status=413)
            im.load()
            im = im.convert("RGB")
            im.thumbnail((2048, 2048))
        except Exception:
            return web.json_response({"error": "这个文件不是可用的图片，请换成 JPG 或 PNG。"}, status=400)
        pp = self.project_path(q.get("project", "afe_project"))
        os.makedirs(os.path.join(pp, "refs"), exist_ok=True)
        im.save(os.path.join(pp, "refs", ref_filename(kind, name)), "PNG")
        return web.json_response({"ok": True})

    async def delete_ref(self, request):
        body = await request.json()
        kind, name = body.get("kind", ""), (body.get("name") or "").strip()
        if kind not in REF_KINDS or not name:
            return web.json_response({"error": "缺少参数。"}, status=400)
        path = os.path.join(self.project_path(body.get("project", "afe_project")), "refs", ref_filename(kind, name))
        if os.path.exists(path):
            os.remove(path)
        return web.json_response({"ok": True})

    # handlers
    async def index(self, request):
        return web.FileResponse(os.path.join(STATIC_DIR, "index.html"), headers=MIME_NO_CACHE)

    async def static(self, request):
        name = request.match_info["name"]
        path = os.path.join(STATIC_DIR, name)
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name) or not os.path.isfile(path):
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers=MIME_NO_CACHE)

    async def options(self, request):
        opts = self._options() if callable(self._options) else (self._options or {})
        root = self.projects_root()
        projects = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))) if os.path.isdir(root) else []
        return web.json_response({**opts, "projects": projects, "defaults": graphs.DEFAULTS,
                                  "stage_names": graphs.STAGE_NAMES, "version": code_version()})

    async def get_project(self, request):
        view = self.project_view(request.query.get("name", "afe_project"))
        st = self.state(self.project_path(view["project"]))
        if view.get("has_analysis"):
            view["cast_images"] = self.cast_images(view["project"], st.get("cast_manifest", []))
            view["kf_images"] = self.cast_images(view["project"], st.get("kf_manifest", []))
        else:
            view["cast_images"], view["kf_images"] = [], []
        return web.json_response(view)

    async def save_settings(self, request):
        body = await request.json()
        pp = self.project_path(body.get("project", "afe_project"))
        st = self.state(pp)
        st["settings"] = graphs.merged({**(st.get("settings") or {}), **(body.get("settings") or {})})
        self.save_state(pp, st)
        return web.json_response({"ok": True})

    async def run(self, request):
        body = await request.json()
        stage = int(body.get("stage", 0))
        project = safe_project_name(body.get("project", "afe_project"))
        pp = self.project_path(project)
        st = self.state(pp)
        st["settings"] = graphs.merged({**(st.get("settings") or {}), **(body.get("settings") or {})})
        s = st["settings"]
        if stage == 1 and not str(s.get("script", "")).strip():
            return web.json_response({"error": "请先在上面粘贴剧本。"}, status=400)
        batch = None
        session_store = None
        target_count = max(1, round(int(s.get("duration", 180)) / int(s.get("seconds_per_shot", 5))))
        if stage == 1:
            session_store = self.session_store(pp)
            try:
                session = session_store.ensure(
                    script=s["script"], target_shot_count=target_count,
                    seconds_per_shot=int(s["seconds_per_shot"]),
                    episode_format=s.get("episode", ""), scene_map=_build_scene_map(s["script"]),
                )
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=400)
            existing = next((item for item in session.get("batches", [])
                             if item.get("status") == "running"), None)
            if existing:
                if await self.prompt_is_known(existing.get("prompt_id", "")):
                    return web.json_response({"prompt_id": existing.get("prompt_id"),
                                              "batch": existing, "session": self.analysis_status(pp),
                                              "labels": {"1": f"分析剧本第{existing['batch_index']}批"}})
                # A running prompt that is absent from both history and queue is
                # conservatively retryable after a ComfyUI/browser restart.
                session_store.recover_orphaned_running()
                session = session_store.load()
            batch = session_store.claim_next()
            if batch.get("status") == "complete":
                return web.json_response({"ok": True, "complete": True,
                                          "session": self.analysis_status(pp)})
            if batch.get("status") == "failed":
                return web.json_response({"error": f"第{batch['batch_index']}批失败，请先重试该批次。",
                                          "session": self.analysis_status(pp)}, status=409)
            source_ranges = {
                str(item.get("source_block_id")): set(item.get("unit_ids", []))
                for item in batch.get("source_unit_ranges", [])
            }
            scene_subset = []
            for scene in session.get("scene_map", []):
                blocks = []
                for source_block in scene.get("source_blocks", []):
                    block_id = str(source_block.get("source_block_id"))
                    if block_id not in source_ranges:
                        continue
                    block = dict(source_block)
                    block["batch_unit_ids"] = sorted(source_ranges[block_id])
                    units = _source_units_with_offsets(block.get("source_text", ""))
                    block["prompt_source_text"] = "\n".join(
                        unit["text"] for unit in units if unit["unit_id"] in source_ranges[block_id]
                    )
                    blocks.append(block)
                if blocks:
                    item = dict(scene); item["source_blocks"] = blocks
                    item["source_text"] = "\n".join(b.get("prompt_source_text", "") for b in blocks)
                    scene_subset.append(item)
            batch["context_json"] = json.dumps({"scene_map": scene_subset}, ensure_ascii=False)
        if stage >= 2:
            current_session = self.session_store(pp).load()
            if current_session:
                expected_signature = script_signature(
                    s.get("script", ""), target_count,
                    int(s.get("seconds_per_shot", 5)), s.get("episode", "")
                )
                if current_session.get("script_signature") != expected_signature:
                    return web.json_response({"error": "剧本已改变，请先完成当前剧本的分批分析。"}, status=400)
                if current_session.get("analysis_status") != "complete":
                    return web.json_response({"error": "请先完成第 ① 步「分析剧本」的全部批次。"}, status=400)
                published = read_json(os.path.join(pp, "analysis.json"), {}) or {}
                if published.get("session_signature") != current_session.get("script_signature"):
                    return web.json_response({"error": "当前剧本尚未发布匹配的完整分析结果。"}, status=400)
            elif not os.path.exists(os.path.join(pp, "analysis.json")):
                return web.json_response({"error": "请先完成第 ① 步「分析剧本」。"}, status=400)
        os.makedirs(pp, exist_ok=True)
        st.setdefault("run_settings", {})[str(stage)] = {**{k: s.get(k, "") for k in USED_KEYS},
                                                         "refs": self.ref_sig(pp),
                                                         "ref_entities": self.ref_entity_sigs(pp, read_json(os.path.join(pp, "analysis.json"), {}),
                                                                                               st.get("scenes", []), st.get("props", []))}
        self.save_state(pp, st)

        part = "cast" if body.get("part") == "cast" and stage == 2 else "all"
        prompt, labels = graphs.build_prompt(stage, project, s, pp, part, batch=batch)
        classes = self._node_classes() if callable(self._node_classes) else self._node_classes
        if classes:
            problems = graphs.validate_prompt(prompt, classes)
            if problems:
                logger.error("AFE UI prompt invalid: %s", problems)
                return web.json_response({"error": "内部流程配置有误，请把下面的信息发给技术支持：\n" + "\n".join(problems[:6])}, status=500)
        payload = {"prompt": prompt, "client_id": body.get("client_id", "afe-ui")}
        try:
            async with ClientSession(timeout=ClientTimeout(total=30)) as sess:
                async with sess.post(f"{self.comfy()}/prompt", json=payload) as r:
                    data = await r.json(content_type=None)
                    if r.status != 200:
                        detail = json.dumps(data, ensure_ascii=False)[:600]
                        return web.json_response({"error": friendly_error(detail), "details": detail}, status=400)
        except Exception as e:
            return web.json_response({"error": f"无法连接 ComfyUI：{e}"}, status=502)
        if stage == 1 and session_store and batch:
            session_store.set_prompt(batch["batch_index"], data.get("prompt_id", ""))
            st["analysis_run"] = {"batch_index": batch["batch_index"], "prompt_id": data.get("prompt_id", "")}
            self.save_state(pp, st)
        return web.json_response({"prompt_id": data.get("prompt_id"), "labels": labels,
                                  "batch": batch, "session": self.analysis_status(pp)})

    async def collect(self, request):
        body = await request.json()
        stage = int(body["stage"])
        part = "cast" if body.get("part") == "cast" and stage == 2 else "all"
        project = safe_project_name(body.get("project", "afe_project"))
        pp = self.project_path(project)
        pid = body["prompt_id"]
        session_store = self.session_store(pp) if stage == 1 else None
        session = session_store.load() if session_store else None
        if stage == 1 and session:
            current_batch = next((item for item in session.get("batches", [])
                                  if item.get("status") == "running"), None)
            if not current_batch or current_batch.get("prompt_id") != pid:
                return web.json_response({"ok": False,
                                          "error": "该分析任务已过期或已被取消，未修改当前批次。",
                                          "expired_task": True,
                                          "session": self.analysis_status(pp)}, status=409)
        entry = None
        async with ClientSession(timeout=ClientTimeout(total=30)) as sess:
            for _ in range(20):
                async with sess.get(f"{self.comfy()}/history/{pid}") as r:
                    hist = await r.json(content_type=None)
                if pid in hist:
                    entry = hist[pid]
                    break
                await asyncio.sleep(0.5)
        if entry is None:
            return web.json_response({"ok": False, "error": "没有找到运行结果，请重试。"}, status=404)

        status = entry.get("status", {})
        if any(m and m[0] == "execution_interrupted" for m in status.get("messages", [])):
            if stage == 1 and session_store and session:
                current_batch = next((item for item in session.get("batches", [])
                                      if item.get("status") == "running" and item.get("prompt_id") == pid), None)
                if current_batch:
                    session_store.cancel(batch_index=current_batch["batch_index"], prompt_id=pid)
            return web.json_response({"ok": False, "cancelled": True, "error": "已取消。已完成的批次都保留着，继续分析会从未完成批次开始。",
                                      "session": self.analysis_status(pp)})
        if status.get("status_str") == "error":
            err = next((m[1] for m in status.get("messages", []) if m and m[0] == "execution_error"), {})
            message = friendly_error(err.get("exception_message", ""), err.get("node_type", ""))
            if stage == 1:
                session = self.session_store(pp).load()
                if session and session.get("current_batch"):
                    current_batch = next((item for item in session.get("batches", [])
                                          if item.get("batch_index") == session.get("current_batch")), None)
                    if current_batch and current_batch.get("prompt_id") == pid:
                        self.session_store(pp).fail_batch(session["current_batch"], message)
            return web.json_response({"ok": False, "error": message, "details": err.get("exception_message", "")[:800],
                                      "session": self.analysis_status(pp)})
        outputs = entry.get("outputs", {})
        if stage == 1:
            try:
                raw_analysis = _first_json(outputs.get("1", {}), "afe_analysis") or {}
                if raw_analysis.get("analysis_status") == "complete" and not self.session_store(pp).load():
                    # Compatibility for direct legacy parser calls.
                    _validate_analysis_payload(raw_analysis)
                    res = {"analysis": raw_analysis, "scenes": [], "props": [], "reports": {"parse": _text(outputs.get("1", {}))}}
                else:
                    store = self.session_store(pp)
                    session = store.load()
                    if not session:
                        raise ValueError("分析会话不存在，请重新开始分析。")
                    batch_index = (self.state(pp).get("analysis_run") or {}).get("batch_index") or session.get("current_batch")
                    if not batch_index:
                        raise ValueError("没有可提交的当前分析批次。")
                    current_batch = next((item for item in session.get("batches", [])
                                          if item.get("batch_index") == int(batch_index)), None)
                    if not current_batch or current_batch.get("prompt_id") != pid:
                        raise ValueError("该分析任务已过期或已被取消，未保存其结果。")
                    store.commit_batch(int(batch_index), raw_analysis)
                    session = store.status()
                    if session.get("analysis_status") != "complete":
                        self.save_state(pp, {**self.state(pp), "analysis_progress": session})
                        return web.json_response({"ok": True, "partial": True,
                                                  "session": self.analysis_status(pp)})
                    analysis = {"schema_version": "afe-analysis-v1", "analysis_status": "complete",
                                "session_signature": session["script_signature"],
                                "expected_shot_count": session["target_shot_count"],
                                "source_manifest": [{k: v for k, v in item.items() if k != "source_text"}
                                                     for item in session["source_manifest"]],
                                "shots": session["parsed_shots"], "cast": session.get("cast", [])}
                    _validate_analysis_payload(analysis)
                    scenes = []
                    for shot in session.get("parsed_shots", []):
                        scene_id = shot.get("scene_id")
                        if scene_id and not any(item.get("scene_id") == scene_id for item in scenes):
                            scenes.append({"scene_id": scene_id,
                                           "scene_name": shot.get("scene_name", scene_id),
                                           "scene_name_en": shot.get("scene_name_en", ""),
                                           "shot_appearances": [],
                                           "environment_prompt_en": shot.get("scene_environment_en", "")})
                    if not scenes:
                        scenes = [{"scene_id": scene.get("scene_id"),
                                   "scene_name": scene.get("sample_header", scene.get("scene_id", "")),
                                   "scene_name_en": scene.get("sample_header", ""),
                                   "shot_appearances": [], "environment_prompt_en": ""}
                                  for scene in session.get("scene_map", [])]
                    props = []
                    for shot in session.get("parsed_shots", []):
                        for name in shot.get("props_list", []) or []:
                            if name and not any(p.get("name") == name for p in props):
                                props.append({"name": name, "shot_appearances": []})
                    res = {"analysis": analysis, "scenes": scenes, "props": props,
                           "reports": {"parse": "✅ 所有分析批次已完成"}}
            except (ValueError, KeyError, TypeError) as exc:
                session = self.session_store(pp).load()
                batch_index = (self.state(pp).get("analysis_run") or {}).get("batch_index") or (session or {}).get("current_batch")
                if session and batch_index:
                    current_batch = next((item for item in session.get("batches", [])
                                          if item.get("batch_index") == int(batch_index)), None)
                    if current_batch and current_batch.get("status") == "running" and current_batch.get("prompt_id") == pid:
                        self.session_store(pp).fail_batch(int(batch_index), str(exc))
                return web.json_response({"ok": False, "error": str(exc),
                                          "session": self.analysis_status(pp)})
        else:
            try:
                res = extract_results(stage, entry.get("outputs", {}), part)
            except ValueError as e:
                return web.json_response({"ok": False, "error": str(e)})

        st = self.state(pp)
        st.setdefault("done", {})[str(stage)] = int(time.time())
        if part != "cast":
            st.setdefault("used", {})[str(stage)] = (st.get("run_settings") or {}).get(str(stage), {})
        if stage == 1:
            write_json(os.path.join(pp, "analysis.json"), res["analysis"])
            st["scenes"], st["props"], st["reports"] = res["scenes"], res["props"], res["reports"]
            for k in ("2", "3", "4", "5"):          # a new analysis invalidates everything after it
                st["done"].pop(k, None)
            st.pop("assets", None); st.pop("cast_manifest", None); st.pop("kf_manifest", None); st.pop("movie", None)
        elif stage == 2:
            if part != "cast":
                st["assets"] = {"scene_files": res["scene_files"], "props_files": res["props_files"]}
            st["cast_manifest"] = res["cast_manifest"]
        elif stage == 3:
            st["kf_manifest"] = res["kf_manifest"]
            st.setdefault("reports", {})["keyframes"] = res["report"]
        elif stage == 4:
            st.setdefault("reports", {})["video"] = res["report"]
        elif stage == 5:
            st["movie"] = res["movie"]
            st.setdefault("reports", {})["movie"] = res["report"]
        self.save_state(pp, st)
        return web.json_response({"ok": True})

    async def analysis_status_api(self, request):
        project = safe_project_name(request.query.get("name", "afe_project"))
        return web.json_response(self.analysis_status(self.project_path(project)))

    async def retry_analysis_batch(self, request):
        body = await request.json()
        project = safe_project_name(body.get("project", "afe_project"))
        try:
            state = self.session_store(self.project_path(project)).retry(int(body.get("batch_index")))
            return web.json_response({"ok": True, "session": self.analysis_status(self.project_path(project))})
        except (ValueError, TypeError, KeyError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def cancel(self, request):
        body = await request.json() if request.can_read_body else {}
        project = safe_project_name(body.get("project", "afe_project"))
        store = self.session_store(self.project_path(project))
        state = store.load()
        active = next((b for b in (state or {}).get("batches", []) if b.get("status") == "running"), None)
        stage = int(body.get("stage") or 1)
        if not active:
            if stage == 1 or not body.get("prompt_id"):
                return web.json_response({"ok": False, "error": "当前没有可取消的分析任务。",
                                          "session": self.analysis_status(self.project_path(project))}, status=409)
            try:
                await self.cancel_prompt(str(body["prompt_id"]))
            except Exception as exc:
                return web.json_response({"ok": False, "error": f"取消任务失败：{exc}"}, status=502)
            return web.json_response({"ok": True, "session": self.analysis_status(self.project_path(project))})
        prompt_id = str(body.get("prompt_id") or active.get("prompt_id") or "")
        if not prompt_id or prompt_id != str(active.get("prompt_id") or ""):
            return web.json_response({"ok": False, "error": "当前分析任务已变化，未取消其他任务。",
                                      "session": self.analysis_status(self.project_path(project))}, status=409)
        try:
            await self.cancel_prompt(prompt_id)
            if state:
                store.cancel(batch_index=active.get("batch_index") if active else None,
                             prompt_id=prompt_id or None)
        except (ValueError, RuntimeError) as exc:
            return web.json_response({"ok": False, "error": str(exc),
                                      "session": self.analysis_status(self.project_path(project))}, status=409)
        except Exception as exc:
            return web.json_response({"ok": False, "error": f"取消任务失败：{exc}"}, status=502)
        return web.json_response({"ok": True, "session": self.analysis_status(self.project_path(project))})

    async def file(self, request):
        pp = os.path.realpath(self.project_path(request.query.get("project", "")))
        full = os.path.realpath(os.path.join(pp, request.query.get("path", "")))
        if not (full == pp or full.startswith(pp + os.sep)) or not os.path.isfile(full):
            raise web.HTTPNotFound()
        return web.FileResponse(full)

    def attach(self, routes: web.RouteTableDef) -> None:
        routes.get("/afe")(self.index_redirect)
        routes.get("/afe/")(self.index)
        routes.get("/afe/static/{name}")(self.static)
        routes.get("/afe/api/options")(self.options)
        routes.get("/afe/api/project")(self.get_project)
        routes.get("/afe/api/analysis/status")(self.analysis_status_api)
        routes.post("/afe/api/analysis/retry")(self.retry_analysis_batch)
        routes.post("/afe/api/settings")(self.save_settings)
        routes.post("/afe/api/run")(self.run)
        routes.post("/afe/api/collect")(self.collect)
        routes.post("/afe/api/cancel")(self.cancel)
        routes.get("/afe/api/file")(self.file)
        routes.post("/afe/api/upload")(self.upload_ref)
        routes.post("/afe/api/ref/delete")(self.delete_ref)

    async def index_redirect(self, request):
        raise web.HTTPFound("/afe/")


def register() -> None:
    """Called once from the package __init__ when running inside ComfyUI."""
    from server import PromptServer
    import folder_paths

    def classes():
        import nodes
        return nodes.NODE_CLASS_MAPPINGS

    def options():
        from ai_film_editor_nodes.nodes.director.script_full_parser_node import AFE_ScriptFullParser as P
        return {"styles": P.RENDER_STYLES, "episodes": P.EPISODE_FORMATS}

    api = Api(out_dir=folder_paths.get_output_directory,
              comfy_base=lambda: f"http://127.0.0.1:{getattr(PromptServer.instance, 'port', 8188)}",
              node_classes=classes, options=options)
    api.attach(PromptServer.instance.routes)
    logger.info("AFE web UI available at /afe/")
