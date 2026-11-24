"""
Local stand-in for ComfyUI, used to test the web UI end to end without a GPU.

* Serves the real /afe/* routes (webui/server.py) and the ComfyUI endpoints the UI relies on
  (/prompt, /history, /view, /interrupt, /ws).
* Executes the submitted API prompt node by node with the REAL node classes. Only the pieces that
  need a GPU are replaced: the LLM script parser, the image generators and the Wan renderer.
  File writing, signatures, picks/redo, manifests, ffmpeg joining are all the real code.

Run:  python tests/ui_mock_server.py [port]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import types
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))            # .../MJ  (package parent)
if os.environ.get("IOF_PATH"):
    sys.path.insert(0, os.environ["IOF_PATH"])                         # imageio-ffmpeg location

import torch
from aiohttp import web, WSMsgType

OUT = os.environ.get("AFE_MOCK_OUT") or tempfile.mkdtemp(prefix="afe_out_")
sys.modules["folder_paths"] = types.SimpleNamespace(get_output_directory=lambda: OUT)

import ai_film_editor_nodes as pkg  # noqa: E402
from ai_film_editor_nodes.nodes.video import (  # noqa: E402
    _common as cc, cast_ref_generator_node as cr, shot_keyframe_node as kf, wan_shot_renderer_node as wn,
)
from ai_film_editor_nodes.webui import server as ui  # noqa: E402

STEP_DELAY = float(os.environ.get("AFE_MOCK_DELAY", "0.4"))


# ── fakes for the GPU parts ──────────────────────────────────────────────────

def fake_img(h, w, seed):
    r, g, b = ((seed * 37) % 200 + 40) / 255, ((seed * 91) % 200 + 40) / 255, ((seed * 53) % 200 + 40) / 255
    img = torch.zeros(1, h, w, 3)
    img[..., 0], img[..., 1], img[..., 2] = r, g, b
    stripe = torch.linspace(0.2, 1.0, w).view(1, 1, w, 1)
    return (img * stripe).clamp(0, 1)


CALLS = {"scene": 0, "prop": 0, "cast": 0, "kf": 0, "qwen": 0, "kf_imgs": [], "keyframe_prompts": [], "video_prompts": []}


def _count(kind, img):
    CALLS[kind] += 1
    return img


cr._generate_scene_image = lambda **kw: _count("cast", fake_img(kw["height"], kw["width"], kw["seed"]))
cr._load_models = lambda: (None, None, None)
from ai_film_editor_nodes.nodes.analyzer import scene_image_generator_node as sg, props_image_generator_node as pg  # noqa: E402
sg._generate_scene_image = lambda **kw: _count("scene", fake_img(kw["height"], kw["width"], kw["seed"]))
sg._load_models = lambda: (None, None, None)
pg._generate_prop_image = lambda clip, vae, base_model, prop_prompt, seed, size, steps: _count("prop", fake_img(size, size, seed))
pg._load_models = lambda: (None, None, None)
kf._generate_frame = lambda cached, clip, vae, images, prompt, negative, seed, resolution: (
    CALLS["kf_imgs"].append(len(images)), CALLS["keyframe_prompts"].append(prompt), _count("kf", fake_img(288, 512, seed)))[2]
from ai_film_editor_nodes.nodes.video import user_refs as _user_refs  # noqa: E402
_user_refs.qwen_variant = lambda reference, prompt, seed: _count("qwen", fake_img(reference.shape[1], reference.shape[2], seed))
kf._load_models = lambda: (None, None, None)
kf.call = lambda cls, **k: (None,)
kf.get_node = lambda n: None
wn._load_wan = lambda fast: ("m",)


def _fake_render_shot(models, key, prompt, w, h, dur, seed, fast, anchor):
    CALLS["video_prompts"].append(prompt)
    n = min(int(dur * 16) + 1, 33)
    base = key[0] if key.shape[0] else fake_img(h, w, seed)[0]
    frames = []
    for i in range(n):
        f = torch.roll(base, shifts=i * 3, dims=1)
        f = torch.nn.functional.interpolate(f.permute(2, 0, 1)[None], size=(72, 128))[0].permute(1, 2, 0)
        frames.append(f)
    return torch.stack(frames)


wn.render_shot = _fake_render_shot


def fake_parser(raw_script, **kw):
    if "FAIL" in raw_script:
        raise RuntimeError("CUDA out of memory (mock)")
    batch_start = int(kw.get("batch_start_shot") or 1)
    batch_end = int(kw.get("batch_end_shot") or 0)
    total = batch_end - batch_start + 1 if batch_end >= batch_start else 6
    cast = [
        {"name": "阿明", "role_type": "lead", "gender": "male", "age_range": "25", "appearance_en": "short black hair, round glasses", "default_costume_en": "red apron"},
        {"name": "小红", "role_type": "supporting", "gender": "female", "age_range": "23", "appearance_en": "long brown hair", "default_costume_en": "blue dress"},
    ]
    shots = []
    for offset in range(total):
        i = batch_start - 1 + offset
        scene = "超市外卖厨房" if i < 4 else "公寓客厅"
        source_unit = i + 1 if i < 4 else i - 3
        shots.append({
            "shot_id": f"shot_{i + 1:03d}", "scene_id": "scene_001" if i < 4 else "scene_002",
            "scene_occurrence_id": "occurrence_001" if i < 4 else "occurrence_002",
            "source_block_id": "block_001" if i < 4 else "block_002", "source_unit_ids": [f"unit_{source_unit:03d}"], "section_type": "location_scene",
            "scene_name": scene, "scene_name_en": "Supermarket" if i < 4 else "Apartment",
            "scene_environment_en": "bright interior, steel counter" if i < 4 else "warm living room, sofa",
            "environment_scope": "place_only", "environment_people": [], "environment_props": [],
            "character_names": ["阿明"] if i % 2 == 0 else ["阿明", "小红"],
            "dialogue": "你好" if i == 1 else "（无）", "props_list": ["佛珠", "茶杯"][: 1 + i % 2],
            "shot_type": "medium close-up", "camera_angle": "medium", "camera_motion": "tracking_shot" if i % 2 == 0 else "slow_push_in", "camera_motion_source": "script",
            "shot_description": f"Shot {i + 1}: a person works at the counter", "action": "stacks boxes", "action_start": "reaches for a box", "action_process": "stacks boxes while rubbing the label", "action_end": "sets the box down", "business": "rubs the label", "emotion": "calm", "facial_expression": "calm focused face", "micro_expression": "lower eyelid tightens", "gaze": "toward the counter", "body_language": "shoulders forward", "prop_interactions": ["grips the prop"], "pace": "steady",
            "lighting": "cold white LED", "lighting_style": "cold white LED", "location": scene,
            "time_of_day": "afternoon", "weather": "indoor", "duration_seconds": 5.0, "costume_en": "red apron",
        })
    report = f"✅ 剧本解析完成（模拟）\n分镜 {len(shots)}"
    source_manifest = []
    if batch_start <= 4:
        source_manifest.append({"order": 0, "scene_id": "scene_001", "scene_occurrence_id": "occurrence_001",
                               "source_block_id": "block_001", "section_type": "location_scene",
                               "unit_ids": [f"unit_{i:03d}" for i in range(max(1, batch_start), min(4, batch_end) + 1)]})
    if batch_end > 4:
        source_manifest.append({"order": len(source_manifest), "scene_id": "scene_002", "scene_occurrence_id": "occurrence_002",
                               "source_block_id": "block_002", "section_type": "location_scene",
                               "unit_ids": [f"unit_{i - 4:03d}" for i in range(max(5, batch_start), batch_end + 1)]})
    if not source_manifest:
        source_manifest = [{"order": 0, "scene_id": "scene_001", "scene_occurrence_id": "occurrence_001",
                            "source_block_id": "block_001", "section_type": "location_scene", "unit_ids": ["unit_001"]}]
    analysis = {"schema_version": "afe-analysis-v1", "analysis_status": "partial",
                "expected_shot_count": total, "source_manifest": source_manifest,
                "shots": shots, "cast": cast}
    return {"ui": {"text": [report], "afe_analysis": [json.dumps(analysis, ensure_ascii=False)]},
            "result": (shots, cast, "", "", len(shots), 2, 3, report)}


def fake_scene_gen(**kw):
    n = len(json.loads(kw["scenes_json"]))
    return tuple(torch.cat([fake_img(576, 1024, 10 * i + v) for i in range(n)]) for v in range(3)) + ("ok",)


def fake_props_gen(**kw):
    props = json.loads(kw["props_json"])
    n = len(props)
    manifest = [{"asset_id": p.get("asset_id", f"prop:{i}"), "prop_id": p.get("prop_id", f"prop_{i + 1:03d}"), "index": i + 1, "name": p.get("name", f"prop_{i + 1}")} for i, p in enumerate(props)]
    return (torch.cat([fake_img(256, 256, 100 + i) for i in range(n)]), "ok", json.dumps(manifest, ensure_ascii=False))


FAKES = {"AFE_ScriptFullParser": fake_parser}


class SaveImage:                      # stand-in for ComfyUI's core node
    RETURN_TYPES = ()
    FUNCTION = "save"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "filename_prefix": ("STRING", {"default": "ComfyUI"})}}


CLASSES = dict(pkg.NODE_CLASS_MAPPINGS, SaveImage=SaveImage)


# ── mini ComfyUI ─────────────────────────────────────────────────────────────

class Mock:
    def __init__(self):
        self.history, self.clients, self.interrupt, self.counter = {}, {}, False, 0
        self.running = set()
        self.queue = asyncio.Queue()

    async def send(self, client, type_, data):
        ws = self.clients.get(client)
        if ws is not None and not ws.closed:
            await ws.send_json({"type": type_, "data": data})

    async def worker(self):
        while True:
            pid, prompt, client = await self.queue.get()
            try:
                await self.execute(pid, prompt, client)
            except Exception as e:           # never kill the worker
                print("mock worker error", e)

    def order(self, prompt):
        seen, out = set(), []

        def visit(n):
            if n in seen:
                return
            seen.add(n)
            for v in prompt[n]["inputs"].values():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] in prompt:
                    visit(v[0])
            out.append(n)
        for n in prompt:
            visit(n)
        return out

    async def execute(self, pid, prompt, client):
        outs, uis, messages = {}, {}, []
        status = "success"
        self.interrupt = False
        self.running.add(pid)
        try:
            for nid in self.order(prompt):
                if self.interrupt:
                    raise KeyboardInterrupt
                node = prompt[nid]
                ct = node["class_type"]
                await self.send(client, "executing", {"node": nid, "prompt_id": pid})
                kwargs = {k: (outs[v[0]][v[1]] if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) else v)
                          for k, v in node["inputs"].items()}
                for tick in range(4):
                    await self.send(client, "progress", {"value": tick + 1, "max": 4, "node": nid, "prompt_id": pid})
                    await asyncio.sleep(STEP_DELAY / 4)
                    if self.interrupt:
                        raise KeyboardInterrupt
                if ct == "SaveImage":
                    res = await asyncio.to_thread(self.save_image, **kwargs)
                elif ct in FAKES:
                    res = await asyncio.to_thread(FAKES[ct], **kwargs)
                else:
                    cls = CLASSES[ct]
                    res = await asyncio.to_thread(lambda: getattr(cls(), cls.FUNCTION)(**kwargs))
                if isinstance(res, dict):
                    outs[nid] = res["result"]
                    if res.get("ui"):
                        uis[nid] = res["ui"]
                else:
                    outs[nid] = res
        except KeyboardInterrupt:
            status = "error"
            messages = [["execution_interrupted", {"prompt_id": pid}]]
        except Exception as e:
            status = "error"
            messages = [["execution_error", {"prompt_id": pid, "node_type": ct, "exception_message": str(e)}]]
        uis.update(getattr(self, "_img_uis", {})); self._img_uis = {}
        self.history[pid] = {"outputs": uis, "status": {"status_str": status, "messages": messages}}
        self.running.discard(pid)
        await self.send(client, "executing", {"node": None, "prompt_id": pid})

    def save_image(self, images, filename_prefix):
        sub, base = os.path.split(filename_prefix)
        folder = os.path.join(OUT, sub)
        os.makedirs(folder, exist_ok=True)
        existing = [f for f in os.listdir(folder) if f.startswith(base + "_")]
        n0 = len(existing)
        files = []
        for i in range(images.shape[0]):
            name = f"{base}_{n0 + i + 1:05d}_.png"
            cc.save_png(images[i:i + 1], os.path.join(folder, name))
            files.append({"filename": name, "subfolder": sub.replace("\\", "/"), "type": "output"})
        return {"ui": {"images": files}, "result": ()}


def make_app(port: int):
    mock = Mock()
    routes = web.RouteTableDef()
    api = ui.Api(out_dir=lambda: OUT, comfy_base=f"http://127.0.0.1:{port}", node_classes=CLASSES,
                 options=lambda: {"styles": pkg.NODE_CLASS_MAPPINGS["AFE_ScriptFullParser"].RENDER_STYLES,
                                  "episodes": pkg.NODE_CLASS_MAPPINGS["AFE_ScriptFullParser"].EPISODE_FORMATS})
    api.attach(routes)

    @routes.post("/prompt")
    async def prompt(request):
        body = await request.json()
        p = body["prompt"]
        missing = [n["class_type"] for n in p.values() if n["class_type"] not in CLASSES]
        if missing:
            return web.json_response({"error": {"type": "invalid_prompt"}, "node_errors": {m: "missing" for m in missing}}, status=400)
        pid = str(uuid.uuid4())
        if getattr(mock, "lose_next", False):          # simulate ComfyUI restarting: job vanishes
            mock.lose_next = False
            return web.json_response({"prompt_id": pid, "number": 1})
        mock.queue.put_nowait((pid, p, body.get("client_id")))
        return web.json_response({"prompt_id": pid, "number": 1})

    @routes.get("/history/{pid}")
    async def history(request):
        pid = request.match_info["pid"]
        return web.json_response({pid: mock.history[pid]} if pid in mock.history else {})

    @routes.get("/view")
    async def view(request):
        q = request.query
        path = os.path.join(OUT, q.get("subfolder", ""), q["filename"])
        if not os.path.isfile(path):
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    @routes.get("/queue")
    async def queue(request):
        return web.json_response({"queue_running": [[0, pid, {}] for pid in mock.running],
                                  "queue_pending": [[1, item[0], {}] for item in list(mock.queue._queue)]})

    @routes.get("/mock/lose_next")
    async def lose_next(request):
        mock.lose_next = True
        return web.json_response({})

    @routes.get("/mock/stats")
    async def stats(request):
        return web.json_response(CALLS)

    @routes.post("/interrupt")
    async def interrupt(request):
        mock.interrupt = True
        return web.json_response({})

    @routes.get("/ws")
    async def ws(request):
        sock = web.WebSocketResponse()
        await sock.prepare(request)
        mock.clients[request.query.get("clientId")] = sock
        async for msg in sock:
            if msg.type == WSMsgType.ERROR:
                break
        return sock

    app = web.Application()
    app.add_routes(routes)

    async def start(app):
        app["worker"] = asyncio.create_task(mock.worker())
    app.on_startup.append(start)
    return app


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8199
    print(f"mock ComfyUI + AFE UI on http://127.0.0.1:{port}/afe/   (files in {OUT})", flush=True)
    web.run_app(make_app(port), host="127.0.0.1", port=port, print=None)
