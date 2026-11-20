#!/usr/bin/env python3
"""
Build 10张_v4.json:
  - image_1 : character reference (stays as LoadImage node 470)
  - image_2~9: 8 pose reference images, each with its own LoadImage node
  - Per-slot [Image_N] prompts hardcoded for 9 different angles
  - image_10: disconnected (optional slot, unused)
"""

import json, copy

# ─────────────────────────────────────────────────────────────────────────────
# Per-slot prompts  (do NOT change [Image_N] tags – the model reads them)
# ─────────────────────────────────────────────────────────────────────────────
FIXED_PROMPT = """\
[Image_1] A high-quality 3D character design sheet showing THREE angles in one image: front view on the left, back view in the center, and right side profile on the right. Same character, same outfit. White background, Pixar/Disney 3D style.

[Image_2] Full body FRONT VIEW. Character standing straight, facing the camera, arms relaxed at sides. White background, 3D Pixar style, 8k.

[Image_3] Full body BACK VIEW. Character standing, seen from directly behind. White background, 3D Pixar style, 8k.

[Image_4] Full body SIDE PROFILE VIEW, 90 degrees to the right. White background, 3D Pixar style, 8k.

[Image_5] FACE CLOSE-UP, head and shoulders. Character looking directly at camera. Neutral, calm expression. Blue sky background, 3D Pixar style, 8k.

[Image_6] FACE CLOSE-UP, head and shoulders. Character showing a big warm happy smile, eyes crinkling with joy, teeth showing. Blue sky background, 3D Pixar style, 8k.

[Image_7] FACE CLOSE-UP, head and shoulders. Character with a serious, sharp, authoritative look. Eyebrows slightly furrowed, direct eye contact. Blue sky background, 3D Pixar style, 8k.

[Image_8] MEDIUM SHOT. Character sitting comfortably on a wooden chair on a sunny beach terrace. Leaning forward slightly, holding a glass of tea with both hands and blowing on it gently. Palm trees and ocean in background. 3D Pixar style, 8k.

[Image_9] MEDIUM SHOT. Character sitting at a wooden table on a beach. Arms crossed over chest, leaning back confidently. Relaxed, wise smile. Sunny beach background. 3D Pixar style, 8k.\
"""

# ─────────────────────────────────────────────────────────────────────────────
# Pose reference images for image_2~9
#   key   = slot label in the Prompt Enhancer node
#   value = filename inside ComfyUI's input/poses/ folder
# ─────────────────────────────────────────────────────────────────────────────
POSE_IMAGES = {
    "image_2": "poses/pose_01_front_full.png",
    "image_3": "poses/pose_02_back_full.png",
    "image_4": "poses/pose_03_side_full.png",
    "image_5": "poses/pose_04_face_neutral.png",
    "image_6": "poses/pose_05_face_smile.png",
    "image_7": "poses/pose_06_face_serious.png",
    "image_8": "poses/pose_07_sit_forward.png",
    "image_9": "poses/pose_08_sit_cross.png",
}

# ─────────────────────────────────────────────────────────────────────────────
# Node IDs to allocate (must not clash with existing IDs in the workflow)
# Original max id = 525; use 600+ for new LoadImage nodes
# ─────────────────────────────────────────────────────────────────────────────
NEW_NODE_ID_START = 600
NEW_LINK_ID_START = 1000

SLOT_ORDER = ["image_2","image_3","image_4","image_5",
              "image_6","image_7","image_8","image_9"]

# ─────────────────────────────────────────────────────────────────────────────
def make_loadimage_node(node_id, img_filename, x, y):
    """Return a minimal ComfyUI LoadImage node dict."""
    return {
        "id": node_id,
        "type": "LoadImage",
        "pos": [x, y],
        "size": [280, 380],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [
            {"name": "IMAGE", "type": "IMAGE", "links": []},
            {"name": "MASK",  "type": "MASK",  "links": None},
        ],
        "properties": {
            "cnr_id": "comfy-core",
            "ver": "0.44.0",
            "Node name for S&R": "LoadImage",
        },
        "widgets_values": [img_filename, "image"],
        "widgets_values_named": {"image": img_filename, "upload": "image"},
    }

def make_link(link_id, src_node, src_slot, dst_node, dst_slot, typ="IMAGE"):
    """Return a ComfyUI link array [id, src_node, src_slot, dst_node, dst_slot, type]."""
    return [link_id, src_node, src_slot, dst_node, dst_slot, typ]

# ─────────────────────────────────────────────────────────────────────────────
def patch_workflow(src_path, dst_path):
    with open(src_path, encoding="utf-8") as f:
        data = json.load(f)

    # ── 1. Find the Prompt Enhancer node ─────────────────────────────────────
    pe_node = None
    for n in data["nodes"]:
        if "bc1c967a" in n.get("type", ""):
            pe_node = n
            break
    if not pe_node:
        raise RuntimeError("Prompt Enhancer node not found")
    print(f"Found Prompt Enhancer node id={pe_node['id']}")

    # ── 2. Remove old links for image_2~9 (and image_10) ─────────────────────
    old_links_to_remove = set()
    disconnect_labels = set(SLOT_ORDER) | {"image_10"}
    for inp in pe_node.get("inputs", []):
        if inp.get("label") in disconnect_labels and inp.get("link") is not None:
            old_links_to_remove.add(inp["link"])
            inp["link"] = None
    print(f"Removed {len(old_links_to_remove)} old image_2~9/10 links")

    data["links"] = [l for l in data.get("links", [])
                     if l[0] not in old_links_to_remove]

    # ── 3. Update the prompt widget ──────────────────────────────────────────
    wv = pe_node.get("widgets_values", [])
    # widget index 1 is "prompt" (resolution=0 is index 0)
    if len(wv) > 1:
        wv[1] = FIXED_PROMPT
    if "prompt" in pe_node.get("widgets_values_named", {}):
        pe_node["widgets_values_named"]["prompt"] = FIXED_PROMPT
    print("Prompt updated")

    # ── 4. Add 8 new LoadImage nodes + links ─────────────────────────────────
    # Layout: stack them vertically to the left of the canvas
    base_x = pe_node["pos"][0] - 400
    base_y = pe_node["pos"][1]

    # Build a slot_label → input_index map for the PE node
    label_to_idx = {inp.get("label"): i
                    for i, inp in enumerate(pe_node.get("inputs", []))}

    new_nodes = []
    new_links = []
    next_node_id = NEW_NODE_ID_START
    next_link_id = NEW_LINK_ID_START

    for i, slot_label in enumerate(SLOT_ORDER):
        img_file = POSE_IMAGES[slot_label]
        node_x = base_x
        node_y = base_y + i * 420

        # New LoadImage node
        li_node = make_loadimage_node(next_node_id, img_file, node_x, node_y)
        new_nodes.append(li_node)

        # New link: LoadImage.IMAGE → PE.image_N
        dst_inp_idx = label_to_idx.get(slot_label)
        if dst_inp_idx is None:
            print(f"  WARNING: slot {slot_label} not found in PE inputs – skipping")
            next_node_id += 1
            next_link_id += 1
            continue

        link = make_link(next_link_id,
                         src_node=next_node_id, src_slot=0,
                         dst_node=pe_node["id"], dst_slot=dst_inp_idx)
        new_links.append(link)

        # Register the link on the LoadImage output
        li_node["outputs"][0]["links"].append(next_link_id)

        # Register the link on the PE input
        pe_node["inputs"][dst_inp_idx]["link"] = next_link_id

        print(f"  {slot_label} → LoadImage {next_node_id} ({img_file})")
        next_node_id += 1
        next_link_id += 1

    # ── 5. Append new nodes and links ────────────────────────────────────────
    data["nodes"].extend(new_nodes)
    data["links"].extend(new_links)

    # Update metadata
    data["last_node_id"] = max(n["id"] for n in data["nodes"])
    data["last_link_id"] = max(l[0] for l in data["links"])

    # ── 6. Save ───────────────────────────────────────────────────────────────
    with open(dst_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {dst_path}")
    print(f"  Nodes: {len(data['nodes'])}, Links: {len(data['links'])}")

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    src = "D:/下载/10张.json"          # original clean template
    dst = "D:/下载/10张_v4.json"       # output with pose refs wired in
    print(f"Patching: {src} → {dst}\n")
    patch_workflow(src, dst)
    print("\nDone!")
    print("\nWorkflow summary:")
    print("  image_1 : character reference (node 470 — upload your character ref here)")
    for i, (slot, fname) in enumerate(POSE_IMAGES.items(), 2):
        print(f"  {slot} : {fname}")
    print(f"\nRemember to upload pose PNGs to RunPod:")
    print("  /workspace/runpod-slim/ComfyUI/input/poses/*.png")
