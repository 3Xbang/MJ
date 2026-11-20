#!/usr/bin/env python3
"""
Build 10x_v4.json:
  - image_1 : character reference photo (stays as LoadImage node 470, user uploads here)
  - image_2~9: 8 pose reference images, each with its own LoadImage node (fixed assets)
  - [Image_1] prompt  = character description (the only dynamic part)
  - [Image_2]~[Image_9] prompts = hardcoded angle descriptions (never change)
  - image_10: disconnected (unused)

Usage:
  python fix_qwen_workflow.py
  Outputs: D:/xia/10x_v4.json
  Upload pose PNGs: /workspace/runpod-slim/ComfyUI/input/poses/*.png
"""

import json

# =============================================================================
# PROMPT STRUCTURE
#   [Image_1] = character description  ← only this changes per character
#   [Image_2]~[Image_9] = hardcoded angle descriptions (never change)
# =============================================================================

# Example character (replace with real Cast Analyzer output in production)
CHAR_DESCRIPTION = (
    "A 50-year-old chubby Asian man with shoulder-length wavy silver-grey hair, "
    "handlebar mustache and goatee. Wearing white T-shirt, beige shorts with gold "
    "double-G pattern, thick gold chain necklace, brown wooden bead bracelets, "
    "brown sandals."
)
STYLE = "3D cartoon style, Pixar animation, vibrant colors, 8k, highly detailed"

# [Image_2]~[Image_9]: completely hardcoded, NO character info repeated
_FIXED_ANGLE_SLOTS = [
    # [Image_2] front full body
    "Same character as Image 1, full body FRONT VIEW. "
    "Standing straight, arms relaxed at sides. "
    "White background. " + STYLE + ".",

    # [Image_3] back full body
    "Same character as Image 1, full body BACK VIEW. "
    "Standing, seen from directly behind, same outfit visible. "
    "White background. " + STYLE + ".",

    # [Image_4] side profile
    "Same character as Image 1, full body RIGHT SIDE PROFILE VIEW, 90 degrees. "
    "Standing, showing posture and silhouette from the side. "
    "White background. " + STYLE + ".",

    # [Image_5] face neutral
    "Same character as Image 1, FACE CLOSE-UP portrait, head and shoulders only. "
    "Neutral calm expression, looking directly at camera. "
    "Blue sky soft background. " + STYLE + ".",

    # [Image_6] face smile
    "Same character as Image 1, FACE CLOSE-UP portrait, head and shoulders only. "
    "Big warm happy smile, eyes crinkling with joy, teeth showing. "
    "Blue sky soft background. " + STYLE + ".",

    # [Image_7] face serious
    "Same character as Image 1, FACE CLOSE-UP portrait, head and shoulders only. "
    "Serious sharp authoritative expression, eyebrows slightly furrowed, direct eye contact. "
    "Blue sky soft background. " + STYLE + ".",

    # [Image_8] sitting with tea
    "Same character as Image 1, MEDIUM SHOT. "
    "Sitting comfortably on a wooden chair on a sunny beach terrace, "
    "holding a glass of tea with both hands and blowing on it gently. "
    "Palm trees and ocean in background. " + STYLE + ".",

    # [Image_9] sitting arms crossed
    "Same character as Image 1, MEDIUM SHOT. "
    "Sitting at a wooden table, arms crossed over chest, "
    "leaning back confidently, relaxed wise smile. "
    "Sunny beach background. " + STYLE + ".",
]


def build_prompt(char_description: str = CHAR_DESCRIPTION) -> str:
    """
    Build the full [Image_1]~[Image_9] prompt string.
    Only [Image_1] uses char_description; the rest are hardcoded.
    """
    image1 = (
        f"{char_description} "
        f"Character design reference sheet. White background. {STYLE}."
    )
    parts = [f"[Image_1] {image1}"]
    for i, slot in enumerate(_FIXED_ANGLE_SLOTS):
        parts.append(f"[Image_{i+2}] {slot}")
    return "\n\n".join(parts)


# =============================================================================
# POSE IMAGES  (image_2~9 slots)
# =============================================================================
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

SLOT_ORDER = ["image_2", "image_3", "image_4", "image_5",
              "image_6", "image_7", "image_8", "image_9"]

NEW_NODE_ID_START = 600
NEW_LINK_ID_START = 1000


# =============================================================================
# WORKFLOW PATCHING
# =============================================================================

def make_loadimage_node(node_id, img_filename, x, y):
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


def patch_workflow(src_path, dst_path, char_description=CHAR_DESCRIPTION):
    with open(src_path, encoding="utf-8") as f:
        data = json.load(f)

    # Find the Prompt Enhancer node
    pe_node = next(
        (n for n in data["nodes"] if "bc1c967a" in n.get("type", "")), None
    )
    if not pe_node:
        raise RuntimeError("Prompt Enhancer node not found")
    print(f"Found Prompt Enhancer node id={pe_node['id']}")

    # Remove old links for image_2~9 and image_10
    old_links_to_remove = set()
    disconnect_labels = set(SLOT_ORDER) | {"image_10"}
    for inp in pe_node.get("inputs", []):
        if inp.get("label") in disconnect_labels and inp.get("link") is not None:
            old_links_to_remove.add(inp["link"])
            inp["link"] = None
    print(f"Removed {len(old_links_to_remove)} old links")

    data["links"] = [l for l in data.get("links", [])
                     if l[0] not in old_links_to_remove]

    # Update the prompt widget
    full_prompt = build_prompt(char_description)
    wv = pe_node.get("widgets_values", [])
    if len(wv) > 1:
        wv[1] = full_prompt
    if "prompt" in pe_node.get("widgets_values_named", {}):
        pe_node["widgets_values_named"]["prompt"] = full_prompt
    print("Prompt updated ([Image_1]=char desc, [Image_2~9]=hardcoded angles)")

    # Add 8 new LoadImage nodes for pose references
    label_to_idx = {inp.get("label"): i
                    for i, inp in enumerate(pe_node.get("inputs", []))}

    base_x = pe_node["pos"][0] - 420
    base_y = pe_node["pos"][1]
    next_node_id = NEW_NODE_ID_START
    next_link_id = NEW_LINK_ID_START

    for i, slot_label in enumerate(SLOT_ORDER):
        img_file = POSE_IMAGES[slot_label]
        li_node = make_loadimage_node(next_node_id, img_file,
                                      base_x, base_y + i * 420)
        data["nodes"].append(li_node)

        dst_inp_idx = label_to_idx.get(slot_label)
        if dst_inp_idx is None:
            print(f"  WARNING: slot {slot_label} not found, skipping")
            next_node_id += 1
            next_link_id += 1
            continue

        link = [next_link_id, next_node_id, 0, pe_node["id"], dst_inp_idx, "IMAGE"]
        data["links"].append(link)
        li_node["outputs"][0]["links"].append(next_link_id)
        pe_node["inputs"][dst_inp_idx]["link"] = next_link_id
        print(f"  {slot_label} → LoadImage {next_node_id} ({img_file})")
        next_node_id += 1
        next_link_id += 1

    data["last_node_id"] = max(n["id"] for n in data["nodes"])
    data["last_link_id"] = max(l[0] for l in data["links"])

    with open(dst_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {dst_path}")
    print(f"  Nodes: {len(data['nodes'])}, Links: {len(data['links'])}")


if __name__ == "__main__":
    src = "D:/下载/10张.json"
    dst = "D:/下载/10张_v4.json"
    print(f"Patching: {src} -> {dst}\n")
    patch_workflow(src, dst)
    print("\nWorkflow slot summary:")
    print("  image_1  : character reference photo  (node 470, user uploads)")
    for slot, fname in POSE_IMAGES.items():
        print(f"  {slot} : {fname}")
    print("\nRunPod upload:")
    print("  cp assets/poses/*.png /workspace/runpod-slim/ComfyUI/input/poses/")
