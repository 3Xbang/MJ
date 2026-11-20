#!/usr/bin/env python3
"""生成 AFE_CharacterCard9Views 工作流 JSON"""
import json

VIEW_NAMES = [
    "🎨 设计参考图", "正面全身", "侧面全身",
    "面部·中性", "面部·微笑", "面部·严肃",
    "场景·喝茶", "场景·指向", "场景·自信坐",
]

def build():
    nodes, links = [], []
    nid = lid = 1

    # LoadImage
    li_id = nid; nid += 1
    nodes.append({
        "id": li_id, "type": "LoadImage",
        "title": "🎭 角色参考图",
        "pos": [50, 300], "size": [300, 420],
        "flags": {}, "order": 0, "mode": 0, "inputs": [],
        "outputs": [
            {"name": "IMAGE", "type": "IMAGE", "links": []},
            {"name": "MASK",  "type": "MASK",  "links": None},
        ],
        "properties": {"cnr_id": "comfy-core", "ver": "0.44.0",
                       "Node name for S&R": "LoadImage"},
        "widgets_values": ["reference.png", "image"],
    })

    # AFE_CharacterCard9Views
    cv_id = nid; nid += 1
    link_ref = lid; lid += 1
    nodes[li_id-1]["outputs"][0]["links"].append(link_ref)
    nodes.append({
        "id": cv_id, "type": "AFE_CharacterCard9Views",
        "title": "🎭 角色卡9视图生成器",
        "pos": [420, 50], "size": [520, 580],
        "flags": {}, "order": 1, "mode": 0,
        "inputs": [
            {"name": "reference_image",       "type": "IMAGE",  "link": link_ref},
            {"name": "character_description", "type": "STRING", "link": None,
             "widget": {"name": "character_description"}},
        ],
        "outputs": [
            {"name": f"view_{i+1}_{n}", "type": "IMAGE", "links": []}
            for i, n in enumerate(VIEW_NAMES)
        ],
        "properties": {},
        "widgets_values": [
            # character_description
            "A 50-year-old chubby Asian man with shoulder-length wavy silver-grey hair, "
            "handlebar mustache and goatee. Wearing white T-shirt, beige shorts with gold "
            "double-G pattern, thick gold chain necklace, brown wooden bead bracelets, brown sandals",
            # style
            "3D cartoon Pixar animation style, vibrant colors, 8k, highly detailed",
            # negative_prompt
            "photorealistic, real person, ugly, deformed, noisy, blurry, bad anatomy, "
            "watermark, text, 2d, sketch, anime",
            # seed
            42,
        ],
    })
    links.append([link_ref, li_id, 0, cv_id, 0, "IMAGE"])

    # 9x PreviewImage (3x3 grid layout)
    COL, PW, PH, GAP = 3, 420, 500, 20
    for i, name in enumerate(VIEW_NAMES):
        col, row = i % COL, i // COL
        px = 1000 + col * (PW + GAP)
        py = 50   + row * (PH + GAP)
        prev_id = nid; nid += 1
        lnk     = lid; lid += 1
        nodes[cv_id-1]["outputs"][i]["links"].append(lnk)
        links.append([lnk, cv_id, i, prev_id, 0, "IMAGE"])
        nodes.append({
            "id": prev_id, "type": "PreviewImage",
            "title": f"🖼 {name}",
            "pos": [px, py], "size": [PW, PH],
            "flags": {}, "order": 10+i, "mode": 0,
            "inputs": [{"name": "images", "type": "IMAGE", "link": lnk}],
            "outputs": [], "properties": {}, "widgets_values": [],
        })

    return {
        "id": "afe-character-card-9views-v1",
        "last_node_id": nid-1,
        "last_link_id": lid-1,
        "nodes": nodes, "links": links, "version": 0.4,
    }

if __name__ == "__main__":
    dst = "D:/下载/character_card_9views.json"
    wf = build()
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)
    print(f"Saved: {dst}  ({len(wf['nodes'])} nodes, {len(wf['links'])} links)")
    print("""
Structure:
  LoadImage (角色参考图)
    └→ AFE_CharacterCard9Views
         ├→ PreviewImage: 🎨 设计参考图
         ├→ PreviewImage: 正面全身
         ├→ PreviewImage: 侧面全身
         ├→ PreviewImage: 面部·中性
         ├→ PreviewImage: 面部·微笑
         ├→ PreviewImage: 面部·严肃
         ├→ PreviewImage: 场景·喝茶
         ├→ PreviewImage: 场景·指向
         └→ PreviewImage: 场景·自信坐
""")
