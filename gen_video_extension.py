#!/usr/bin/env python3
"""
gen_video_extension.py
Appends the video-production chain to an existing integrated workflow JSON:

  ScriptFullParser.cast_data ──> CastRefGenerator ──> character_refs ─┐
  SceneImageGenerator.establishing ───────────────────────────────────┼─> ShotKeyframeGenerator
  ScriptFullParser.shot_sequence / cast_data ─────────────────────────┘        │ project_dir
                                                                                v
                                                          WanShotRenderer ──> MovieAssembler

Usage:  python gen_video_extension.py <source.json> <dest.json> [<dest2.json> ...]
Existing nodes, widget values and layout are left untouched.
"""
import copy
import json
import os
import sys

TEST_SHOTS = 2   # first run renders only this many shots (set max_shots to 0 for the full film)
TEST_LONG_TAKE = "shot_001:10"   # first run also tests a 10 s continuous take (2 chained segments); clear it for normal runs


def build(src_path: str) -> dict:
    wf = json.load(open(src_path, encoding="utf-8"))
    nodes = {n["id"]: n for n in wf["nodes"]}
    next_node = max(nodes) + 1
    next_link = max(l[0] for l in wf["links"]) + 1
    order = max(n.get("order", 0) for n in wf["nodes"]) + 1

    # keep the render style the user chose on the parser node
    style = "3D cartoon Pixar animation style, vibrant colors, 8k, highly detailed"
    parser = nodes[1]
    if parser["type"] == "AFE_ScriptFullParser" and len(parser.get("widgets_values", [])) > 1:
        style = str(parser["widgets_values"][1])

    new_nodes = []

    def add_node(ntype, pos, size, inputs, outputs, widgets, title=None):
        nonlocal next_node, order
        node = {
            "id": next_node, "type": ntype, "pos": list(pos), "size": list(size),
            "flags": {}, "order": order, "mode": 0,
            "inputs": inputs,
            "outputs": [{"name": n, "type": t, "links": None, "slot_index": i}
                        for i, (n, t) in enumerate(outputs)],
            "properties": {"Node name for S&R": ntype},
            "widgets_values": widgets,
        }
        if title:
            node["title"] = title
        next_node += 1
        order += 1
        nodes[node["id"]] = node
        new_nodes.append(node)
        return node["id"]

    def link(src, src_slot, dst, dst_slot, ltype):
        nonlocal next_link
        lid = next_link
        next_link += 1
        wf["links"].append([lid, src, src_slot, dst, dst_slot, ltype])
        out = nodes[src]["outputs"][src_slot]
        out["links"] = (out.get("links") or []) + [lid]
        inp = nodes[dst]["inputs"][dst_slot]
        inp["link"] = lid
        return lid

    def sock(name, t):
        return {"name": name, "type": t, "link": None}

    def show_text(title, pos):
        return add_node("show_text_party", pos, (380, 160),
                        [sock("text", "STRING")],
                        [("STRING", "STRING")], [""], title=title)

    def preview(title, pos, size=(420, 360)):
        return add_node("PreviewImage", pos, size, [sock("images", "IMAGE")], [], [], title=title)

    X0, Y0 = 50, 1350

    cast_ref = add_node(
        "AFE_CastRefGenerator", (X0, Y0), (400, 300),
        [sock("cast_data", "CAST_DATA")],
        [("character_refs", "IMAGE"), ("report", "STRING")],
        [style, 768, 1152, 8, 42, "fixed"],
        title="🎭 角色参考图 (Krea 2)")
    keyframe = add_node(
        "AFE_ShotKeyframeGenerator", (X0 + 480, Y0), (420, 420),
        [sock("shot_sequence", "SHOT_SEQUENCE"), sock("cast_data", "CAST_DATA"),
         sock("scene_images", "IMAGE"), sock("character_refs", "IMAGE")],
        [("keyframes", "IMAGE"), ("project_dir", "STRING"), ("report", "STRING")],
        ["afe_project", style, TEST_SHOTS, False, 1024, 42, "fixed"],
        title="🖼 分镜首帧 (Qwen Image 2.1)")
    wan = add_node(
        "AFE_WanShotRenderer", (X0 + 980, Y0), (420, 420),
        [sock("shot_sequence", "SHOT_SEQUENCE"), sock("project_dir", "STRING")],
        [("project_dir", "STRING"), ("report", "STRING")],
        [style, "all", TEST_SHOTS, 832, 480, True, False, 42, "fixed",
         TEST_LONG_TAKE, False],
        title="🎬 分镜视频渲染 (Wan 2.2)")
    assembler = add_node(
        "AFE_MovieAssembler", (X0 + 1480, Y0), (380, 200),
        [sock("shot_sequence", "SHOT_SEQUENCE"), sock("project_dir", "STRING")],
        [("movie_path", "STRING"), ("report", "STRING")],
        ["final_movie"],
        title="🎞 成片合成")

    prev_refs = preview("🎭 角色参考图", (X0, Y0 + 360), (400, 420))
    prev_kf = preview("🖼 分镜首帧", (X0 + 480, Y0 + 480), (420, 420))
    txt_cast = show_text("角色参考图报告", (X0, Y0 + 820))
    txt_kf = show_text("首帧报告", (X0 + 480, Y0 + 940))
    txt_wan = show_text("视频渲染报告", (X0 + 980, Y0 + 480))
    txt_asm = show_text("成片报告", (X0 + 1480, Y0 + 260))

    # data links
    link(1, 1, cast_ref, 0, "CAST_DATA")
    link(1, 0, keyframe, 0, "SHOT_SEQUENCE")
    link(1, 1, keyframe, 1, "CAST_DATA")
    link(14, 0, keyframe, 2, "IMAGE")              # establishing_shots_batch
    link(cast_ref, 0, keyframe, 3, "IMAGE")
    link(1, 0, wan, 0, "SHOT_SEQUENCE")
    link(keyframe, 1, wan, 1, "STRING")            # project_dir
    link(1, 0, assembler, 0, "SHOT_SEQUENCE")
    link(wan, 0, assembler, 1, "STRING")           # project_dir (after rendering finished)
    # previews + reports
    link(cast_ref, 0, prev_refs, 0, "IMAGE")
    link(keyframe, 0, prev_kf, 0, "IMAGE")
    link(cast_ref, 1, txt_cast, 0, "STRING")
    link(keyframe, 2, txt_kf, 0, "STRING")
    link(wan, 1, txt_wan, 0, "STRING")
    link(assembler, 1, txt_asm, 0, "STRING")

    wf["nodes"].extend(new_nodes)
    wf["last_node_id"] = next_node - 1
    wf["last_link_id"] = next_link - 1
    wf.setdefault("groups", []).append({
        "id": max([g.get("id", 0) for g in wf.get("groups", [])] + [0]) + 1,
        "title": "视频生产：角色参考图 → 首帧 → Wan 2.2 → 成片",
        "bounding": [X0 - 30, Y0 - 90, 2000, 1250],
        "color": "#a1309b", "flags": {},
    })
    return wf


# ── self-check: widgets_values must match each node's INPUT_TYPES widget order ──

def expected_widget_count(cls) -> int:
    spec = cls.INPUT_TYPES()
    n = 0
    for section in ("required", "optional"):
        for name, cfg in spec.get(section, {}).items():
            t = cfg[0]
            opts = cfg[1] if len(cfg) > 1 else {}
            if opts.get("forceInput"):
                continue
            if isinstance(t, list) or t in ("INT", "FLOAT", "STRING", "BOOLEAN"):
                n += 1
                if name == "seed":
                    n += 1            # frontend adds control_after_generate
    return n


def self_check(wf: dict) -> None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import ai_film_editor_nodes as pkg
    ids = {n["id"] for n in wf["nodes"]}
    assert len(ids) == len(wf["nodes"]), "duplicate node ids"
    lids = [l[0] for l in wf["links"]]
    assert len(set(lids)) == len(lids), "duplicate link ids"
    for l in wf["links"]:
        assert l[1] in ids and l[3] in ids, f"dangling link {l}"
    for n in wf["nodes"]:
        cls = pkg.NODE_CLASS_MAPPINGS.get(n["type"])
        if cls is None or not n["type"].startswith("AFE_"):
            continue
        exp = expected_widget_count(cls)
        got = len(n.get("widgets_values", []))
        flag = "OK " if exp == got else "BAD"
        if n["id"] >= 31 or exp != got:
            print(f"  [{flag}] {n['type']}: widgets expected {exp}, got {got}")
        if exp != got and n["id"] >= 31:
            raise SystemExit("widget mismatch")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    wf = build(sys.argv[1])
    self_check(wf)
    for dest in sys.argv[2:]:
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(wf, f, ensure_ascii=False, indent=2)
        print("written", dest)
    print(f"nodes={len(wf['nodes'])} links={len(wf['links'])}")
