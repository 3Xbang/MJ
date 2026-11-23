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

logger = logging.getLogger("AFE_WebUI")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MIME_NO_CACHE = {"Cache-Control": "no-store"}
# settings that decide what a step produced; the UI compares them with the current choices
USED_KEYS = ("cast_picks", "cast_redo", "scene_view_picks", "kf_picks", "kf_redo", "kf_variants",
             "video_redo", "long_takes", "skip_shots")


# ── project files ─────────────────────────────────────────────────────────────

REF_KINDS = ("cast", "scene", "prop")


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


def extract_results(stage: int, outputs: dict, part: str = "all") -> dict:
    """outputs = history[prompt_id]["outputs"]  ->  dict of what the UI should remember."""
    res: dict = {}
    if stage == 1:
        o1, o2, o3 = outputs.get("1", {}), outputs.get("2", {}), outputs.get("3", {})
        analysis = _first_json(o1, "afe_analysis")
        if not analysis or not analysis.get("shots"):
            raise ValueError("剧本分析没有返回分镜，请检查剧本内容是否完整。")
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

    # views
    def project_view(self, name: str) -> dict:
        pp = self.project_path(name)
        pname = safe_project_name(name)
        st = self.state(pp)
        analysis = read_json(os.path.join(pp, "analysis.json"))
        assets = st.get("assets")
        if assets:
            assets = {"scene_images": {k: [file_url(pname, f, pp) for f in files]
                                       for k, files in assets.get("scene_files", {}).items()},
                      "props_images": [{"url": file_url(pname, p["file"], pp), "name": p.get("name", "")}
                                       for p in assets.get("props_files", [])]}
        view = {"project": pname, "settings": graphs.merged(st.get("settings")), "done": st.get("done", {}),
                "has_analysis": bool(analysis), "analysis": None, "assets": assets,
                "kf_manifest": st.get("kf_manifest", []), "reports": st.get("reports", {}),
                "used": st.get("used", {}),
                "keyframes": {}, "clips": {}, "movie": None}
        if analysis:
            view["analysis"] = {
                "shots": [{"id": s.get("shot_id"), "scene": s.get("scene_name"),
                           "chars": s.get("character_names", []), "dialogue": s.get("dialogue"),
                           "duration": s.get("duration_seconds"), "type": s.get("shot_type"),
                           "desc": s.get("shot_description") or s.get("action") or ""}
                          for s in analysis.get("shots", [])],
                "cast": [{"name": c.get("name"), "role": c.get("role_type"), "gender": c.get("gender"),
                          "look": c.get("appearance_en")} for c in analysis.get("cast", [])],
                "scenes": st.get("scenes", []), "props": st.get("props", []),
            }
        view["refs"] = self.refs_view(pname, pp, analysis, st.get("scenes", []), st.get("props", []))
        view["ref_sig"] = self.ref_sig(pp)
        kd = os.path.join(pp, "keyframes")
        if os.path.isdir(kd):
            for f in os.listdir(kd):
                if f.endswith(".png") and not re.search(r"_v\d+_[0-9a-f]{8}\.png$", f):
                    view["keyframes"][f[:-4]] = file_url(pname, f"keyframes/{f}", pp)
        cd = os.path.join(pp, "clips")
        if os.path.isdir(cd):
            for f in os.listdir(cd):
                if f.endswith(".mp4"):
                    view["clips"][f[:-4]] = file_url(pname, f"clips/{f}", pp)
        if st.get("movie") and os.path.exists(os.path.join(pp, st["movie"])):
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
        items = sorted((f, int(os.path.getmtime(os.path.join(d, f)))) for f in os.listdir(d) if f.endswith(".png"))
        return hashlib.md5(json.dumps(items).encode()).hexdigest()[:10] if items else ""

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
        data = await request.read()
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data))
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
        view["cast_images"] = self.cast_images(view["project"], st.get("cast_manifest", []))
        view["kf_images"] = self.cast_images(view["project"], st.get("kf_manifest", []))
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
        if stage >= 2 and not os.path.exists(os.path.join(pp, "analysis.json")):
            return web.json_response({"error": "请先完成第 ① 步「分析剧本」。"}, status=400)
        os.makedirs(pp, exist_ok=True)
        st.setdefault("run_settings", {})[str(stage)] = {**{k: s.get(k, "") for k in USED_KEYS},
                                                         "refs": self.ref_sig(pp)}
        self.save_state(pp, st)

        part = "cast" if body.get("part") == "cast" and stage == 2 else "all"
        prompt, labels = graphs.build_prompt(stage, project, s, pp, part)
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
        return web.json_response({"prompt_id": data.get("prompt_id"), "labels": labels})

    async def collect(self, request):
        body = await request.json()
        stage = int(body["stage"])
        part = "cast" if body.get("part") == "cast" and stage == 2 else "all"
        project = safe_project_name(body.get("project", "afe_project"))
        pp = self.project_path(project)
        pid = body["prompt_id"]
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
            return web.json_response({"ok": False, "cancelled": True, "error": "已取消。已完成的部分都保留着，重新点击按钮会接着做。"})
        if status.get("status_str") == "error":
            err = next((m[1] for m in status.get("messages", []) if m and m[0] == "execution_error"), {})
            return web.json_response({"ok": False, "error": friendly_error(
                err.get("exception_message", ""), err.get("node_type", "")), "details": err.get("exception_message", "")[:800]})
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

    async def cancel(self, request):
        try:
            async with ClientSession(timeout=ClientTimeout(total=10)) as sess:
                await sess.post(f"{self.comfy()}/interrupt")
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=502)
        return web.json_response({"ok": True})

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
