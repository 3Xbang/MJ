#!/usr/bin/env python3
"""
Build 10张_v5.json — Qwen PE + AFE_QwenImageSplit + 9× PreviewImage

Structure:
  LoadImage (character ref, node 470)
    └→ Qwen Prompt Enhancer (node 459)  ← prompt with 9 angle descriptions
         └→ AFE_QwenImageSplit (new)      ← splits 3×3 grid
              ├→ PreviewImage × 9          ← 9 individual view previews
              └→ SaveImage × 9            ← 9 individual saves (optional)

Removes: all original SaveImageAdvanced + ImageCompare nodes (they all showed the full grid)
"""

import json

# ─── 角色描述（每个 [Image_N] 都包含完整角色描述 + 角度，这是关键！）──────────
CHAR = (
    "A 50-year-old chubby Asian man with shoulder-length wavy silver-grey hair, "
    "handlebar mustache and goatee. Wearing white T-shirt, beige shorts with gold "
    "double-G pattern, thick gold chain necklace, brown wooden bead bracelets, "
    "brown sandals"
)
STYLE = "3D cartoon style, Pixar animation, vibrant colors, 8k, highly detailed"

PROMPT = f"""\
[Image_1] A high-quality 3D character design sheet showing THREE VIEWS side by side: front view on the left, back view in the center, right side profile on the right. {CHAR}. White background. {STYLE}.

[Image_2] Full body shot, FRONT VIEW, standing straight, arms relaxed at sides. {CHAR}. White background. {STYLE}.

[Image_3] Full body shot, BACK VIEW, standing, seen from directly behind, same outfit visible from behind. {CHAR}. White background. {STYLE}.

[Image_4] Full body shot, SIDE PROFILE VIEW, 90 degrees, standing, facing right. {CHAR}. White background. {STYLE}.

[Image_5] FACE CLOSE-UP portrait, head and shoulders. Neutral calm expression, looking directly at camera. {CHAR}. Blue sky background. {STYLE}.

[Image_6] FACE CLOSE-UP portrait, head and shoulders. Big warm happy smile, eyes crinkling with joy, teeth showing. {CHAR}. Blue sky background. {STYLE}.

[Image_7] FACE CLOSE-UP portrait, head and shoulders. Serious sharp authoritative expression, eyebrows slightly furrowed, direct eye contact. {CHAR}. Blue sky background. {STYLE}.

[Image_8] MEDIUM SHOT. Sitting comfortably on wooden chair, sunny beach terrace, holding a glass of tea with both hands and blowing on it gently. {CHAR}. Palm trees and ocean in background. {STYLE}.

[Image_9] MEDIUM SHOT. Sitting at a wooden table, arms crossed over chest, leaning back confidently, relaxed wise smile. {CHAR}. Sunny beach background. {STYLE}.\
"""

NEGATIVE = (
    "photorealistic, real person, ugly, deformed, noisy, blurry, distorted, "
    "bad anatomy, bad hands, missing fingers, extra fingers, text, watermark, "
    "logo, signature, low resolution, dark, gloomy, 2d, sketch, anime"
)

VIEW_NAMES = [
    "三视图合一", "正面全身", "背面全身", "侧面全身",
    "面部·中性", "面部·微笑", "面部·严肃",
    "场景·喝茶", "场景·自信坐"
]

# ─────────────────────────────────────────────────────────────────────────────
def patch(src_path: str, dst_path: str):
    with open(src_path, encoding="utf-8") as f:
        data = json.load(f)

    # ── 1. 找 Qwen PE 节点，更新 prompt ──────────────────────────────────────
    pe_node = next((n for n in data["nodes"] if "bc1c967a" in n.get("type", "")), None)
    if not pe_node:
        raise RuntimeError("Prompt Enhancer node not found")
    print(f"PE node id={pe_node['id']}")

    wv = pe_node.get("widgets_values", [])
    if len(wv) > 1:
        wv[1] = PROMPT
    if "prompt" in pe_node.get("widgets_values_named", {}):
        pe_node["widgets_values_named"]["prompt"] = PROMPT
    # 也更新负向提示词（通常在 widget index 4）
    if len(wv) > 4:
        wv[4] = NEGATIVE
    print("  Prompt updated ✓")

    # ── 2. 移除所有 SaveImageAdvanced 和 ImageCompare 节点及其关联 link ───────
    keep_types = {"bc1c967a-7f6a-4be9-a372-dad16e4f28e3", "LoadImage", "MarkdownNote"}
    nodes_to_remove = {
        n["id"] for n in data["nodes"]
        if n.get("type") not in keep_types
    }

    # 收集需要移除的 link id
    all_node_ids = {n["id"] for n in data["nodes"]}
    links_to_remove = set()
    for lnk in data.get("links", []):
        # lnk = [id, src_node, src_slot, dst_node, dst_slot, type]
        if lnk[1] in nodes_to_remove or lnk[3] in nodes_to_remove:
            links_to_remove.add(lnk[0])

    data["nodes"] = [n for n in data["nodes"] if n["id"] not in nodes_to_remove]
    data["links"] = [l for l in data.get("links", []) if l[0] not in links_to_remove]

    # 清理 PE 节点 outputs 里已经删掉的 link
    for n in data["nodes"]:
        if "bc1c967a" in n.get("type", ""):
            for out in n.get("outputs", []):
                out["links"] = [l for l in out.get("links", []) if l not in links_to_remove]

    print(f"  Removed {len(nodes_to_remove)} old nodes, {len(links_to_remove)} old links")

    # ── 3. 确定新节点/link 的起始 id ─────────────────────────────────────────
    next_node_id = max(n["id"] for n in data["nodes"]) + 1
    next_link_id = (max((l[0] for l in data.get("links", [])), default=0)) + 1

    # ── 4. 加入 AFE_QwenImageSplit 节点 ──────────────────────────────────────
    pe_x, pe_y = pe_node["pos"][0], pe_node["pos"][1]
    split_id = next_node_id; next_node_id += 1

    split_node = {
        "id": split_id,
        "type": "AFE_QwenImageSplit",
        "pos": [pe_x + 480, pe_y],
        "size": [280, 160],
        "flags": {},
        "order": 10,
        "mode": 0,
        "inputs": [
            {"name": "image", "type": "IMAGE", "link": None}
        ],
        "outputs": [
            {"name": f"view_{i+1}_{name}", "type": "IMAGE", "links": []}
            for i, name in enumerate(VIEW_NAMES)
        ],
        "properties": {},
        "widgets_values": [3, 3],   # cols=3, rows=3
        "widgets_values_named": {"cols": 3, "rows": 3},
    }
    data["nodes"].append(split_node)

    # link: PE → split
    pe_to_split_link = next_link_id; next_link_id += 1
    pe_node["outputs"][0]["links"].append(pe_to_split_link)
    split_node["inputs"][0]["link"] = pe_to_split_link
    data["links"].append([pe_to_split_link, pe_node["id"], 0, split_id, 0, "IMAGE"])
    print(f"  AFE_QwenImageSplit node id={split_id} ✓")

    # ── 5. 加入 9× PreviewImage 节点 ─────────────────────────────────────────
    COL = 3
    PREVIEW_W = 320
    PREVIEW_H = 380
    GAP = 20

    for i, name in enumerate(VIEW_NAMES):
        col = i % COL
        row = i // COL
        px = pe_x + 800 + col * (PREVIEW_W + GAP)
        py = pe_y + row * (PREVIEW_H + GAP)

        prev_id = next_node_id; next_node_id += 1
        link_id = next_link_id; next_link_id += 1

        prev_node = {
            "id": prev_id,
            "type": "PreviewImage",
            "title": f"🖼 {name}",
            "pos": [px, py],
            "size": [PREVIEW_W, PREVIEW_H],
            "flags": {},
            "order": 20 + i,
            "mode": 0,
            "inputs": [{"name": "images", "type": "IMAGE", "link": link_id}],
            "outputs": [],
            "properties": {},
            "widgets_values": [],
        }
        data["nodes"].append(prev_node)

        split_node["outputs"][i]["links"].append(link_id)
        data["links"].append([link_id, split_id, i, prev_id, 0, "IMAGE"])

    print(f"  Added 9× PreviewImage nodes ✓")

    # ── 6. 更新 metadata 并保存 ──────────────────────────────────────────────
    data["last_node_id"] = max(n["id"] for n in data["nodes"])
    data["last_link_id"] = max(l[0] for l in data["links"])

    with open(dst_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nSaved: {dst_path}")
    print(f"  Nodes: {len(data['nodes'])}, Links: {len(data['links'])}")


if __name__ == "__main__":
    src = "D:/下载/10张.json"      # 原版干净模板
    dst = "D:/下载/10张_v5.json"   # 输出
    print(f"Building: {src} → {dst}\n")
    patch(src, dst)
    print("""
Workflow layout:
  LoadImage (角色参考图, node 470)
    └→ Qwen Prompt Enhancer
         └→ AFE_QwenImageSplit (cols=3, rows=3)
              ├→ PreviewImage: 三视图合一
              ├→ PreviewImage: 正面全身
              ├→ PreviewImage: 背面全身
              ├→ PreviewImage: 侧面全身
              ├→ PreviewImage: 面部·中性
              ├→ PreviewImage: 面部·微笑
              ├→ PreviewImage: 面部·严肃
              ├→ PreviewImage: 场景·喝茶
              └→ PreviewImage: 场景·自信坐
""")
