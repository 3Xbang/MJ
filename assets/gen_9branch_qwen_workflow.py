#!/usr/bin/env python3
"""
9-branch Qwen Image 2.1 Character Card Workflow
================================================
每个分支独立运行一个 Qwen Image Edit 节点：
  - 只连接 image_1 槽（角色参考图）
  - 一个视角的提示词
  - 一张独立输出图

9个输入 → 9个独立 Qwen 节点 → 9张独立输出
不再需要合并图切分，彻底解决布局问题。

输出: D:/下载/character_card_9branch.json
"""

import json, copy

# ─── 角色描述 ──────────────────────────────────────────────────────────────
CHAR = (
    "A 50-year-old chubby Asian man with shoulder-length wavy silver-grey hair, "
    "handlebar mustache and goatee. Wearing white T-shirt, beige shorts with gold "
    "double-G pattern, thick gold chain necklace, brown wooden bead bracelets, "
    "brown sandals"
)
STYLE = "3D cartoon Pixar animation style, vibrant colors, 8k, highly detailed"

# ─── 9个视角提示词（每个节点只用这一段，放在 [Image_1] 里）────────────────
# 每个节点只有 image_1 连接，所以只有 [Image_1] 标签
VIEW_PROMPTS = [
    # 1. 角色设计参考图（综合）
    f"[Image_1] Professional character design reference sheet on light grey background. "
    f"Left side: 3 full-body standing poses side by side — front view, back view, side profile. "
    f"Top right: 4 face close-up portraits with different expressions — neutral, happy, serious, surprised. "
    f"Middle right: 2 action poses — sitting drinking tea on beach, sitting arms crossed. "
    f"Bottom: running silhouette, accessories. "
    f"{CHAR}. {STYLE}.",

    # 2. 正面全身
    f"[Image_1] Full body shot, FRONT VIEW, standing straight, arms relaxed at sides. "
    f"{CHAR}. White background. {STYLE}.",

    # 3. 侧面全身
    f"[Image_1] Full body shot, SIDE PROFILE VIEW, 90 degrees, standing, facing right. "
    f"{CHAR}. White background. {STYLE}.",

    # 4. 面部·中性
    f"[Image_1] FACE CLOSE-UP portrait, head and shoulders. "
    f"Neutral calm expression, looking directly at camera. "
    f"{CHAR}. Blue sky soft background. {STYLE}.",

    # 5. 面部·微笑
    f"[Image_1] FACE CLOSE-UP portrait, head and shoulders. "
    f"Big warm happy smile, eyes crinkling with joy, teeth showing. "
    f"{CHAR}. Blue sky soft background. {STYLE}.",

    # 6. 面部·严肃
    f"[Image_1] FACE CLOSE-UP portrait, head and shoulders. "
    f"Serious sharp authoritative expression, eyebrows slightly furrowed. "
    f"{CHAR}. Blue sky soft background. {STYLE}.",

    # 7. 场景·喝茶
    f"[Image_1] MEDIUM SHOT. Sitting comfortably on wooden chair on sunny beach terrace, "
    f"holding a glass of tea, blowing on it gently. "
    f"{CHAR}. Palm trees and ocean in background. {STYLE}.",

    # 8. 场景·指向
    f"[Image_1] MEDIUM SHOT, upper body. Sitting at table, raising right hand, "
    f"pointing index finger forward assertively. "
    f"{CHAR}. Beach background. {STYLE}.",

    # 9. 场景·自信坐
    f"[Image_1] MEDIUM SHOT. Sitting at wooden table on beach, "
    f"arms crossed over chest, leaning back confidently, smiling wisely. "
    f"{CHAR}. Sunny beach background. {STYLE}.",
]

VIEW_NAMES = [
    "🎨 角色设计参考图", "正面全身", "侧面全身",
    "面部·中性", "面部·微笑", "面部·严肃",
    "场景·喝茶", "场景·指向", "场景·自信坐",
]

NEGATIVE = (
    "photorealistic, real person, ugly, deformed, noisy, blurry, distorted, "
    "bad anatomy, bad hands, missing fingers, extra fingers, text, watermark, "
    "logo, signature, low resolution, dark, gloomy, 2d, sketch, anime"
)

# ─── 模型文件（从原版 10张.json 读取，确保一致）──────────────────────────────
QWEN_MODELS = {
    "unet_name":   "qwen_image_2.1_turbo_int8_convrot.safetensors",
    "clip_name":   "qwen3vl_8b_int8_convrot.safetensors",
    "vae_name":    "qwen_image_2.1_vae_bf16.safetensors",
    "clip_name_1": "qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors",
    "device":      "auto",
    "dtype":       "default",
    "scheduler":   "euler",
    "cfg":         1,
    "width":       1024,
    "height":      1024,
    "max_length":  4096,
}

QWEN_NODE_TYPE = "bc1c967a-7f6a-4be9-a372-dad16e4f28e3"


def make_qwen_node(node_id, prompt, pos_x, pos_y, link_image1, seed=None):
    """Create a Qwen Image Edit node with only image_1 connected."""
    import random
    _seed = seed if seed is not None else random.randint(0, 2**31)
    return {
        "id": node_id,
        "type": QWEN_NODE_TYPE,
        "pos": [pos_x, pos_y],
        "size": [420, 680],
        "flags": {},
        "order": 2,
        "mode": 0,
        "inputs": [
            # prompt widget (no link)
            {"label": "positive_prompt", "name": "prompt",     "type": "STRING",  "widget": {"name": "prompt"},     "link": None},
            {"label": "refine_prompt",   "name": "switch_1",   "type": "BOOLEAN", "widget": {"name": "switch_1"},   "link": None},
            {"label": "custom_size",     "name": "switch",     "type": "BOOLEAN", "widget": {"name": "switch"},     "link": None},
            {"label": "sampler",         "name": "scheduler",  "type": "COMBO",   "widget": {"name": "scheduler"},  "link": None},
            {"label": "cache_device",    "name": "device",     "type": "COMBO",   "widget": {"name": "device"},     "link": None},
            {"label": "dtype",           "name": "dtype",      "type": "COMBO",   "widget": {"name": "dtype"},      "link": None},
            {"label": "PE_model",        "name": "clip_name_1","type": "COMBO",   "widget": {"name": "clip_name_1"},"link": None},
            # image_1: connected to character reference
            {"label": "image_1",  "name": "images.image_1",  "type": "IMAGE", "link": link_image1},
            # image_2 ~ image_10: NOT connected (optional slots)
            {"label": "image_2",  "name": "images.image_2",  "shape": 7, "type": "IMAGE", "link": None},
            {"label": "image_3",  "name": "images.image_3",  "shape": 7, "type": "IMAGE", "link": None},
            {"label": "image_4",  "name": "images.image_4",  "shape": 7, "type": "IMAGE", "link": None},
            {"label": "image_5",  "name": "images.image_5_1","shape": 7, "type": "IMAGE", "link": None},
            {"label": "image_6",  "name": "images.image_6",  "shape": 7, "type": "IMAGE", "link": None},
            {"label": "image_7",  "name": "images.image_7",  "shape": 7, "type": "IMAGE", "link": None},
            {"label": "image_8",  "name": "images.image_8",  "shape": 7, "type": "IMAGE", "link": None},
            {"label": "image_9",  "name": "images.image_9",  "shape": 7, "type": "IMAGE", "link": None},
            {"label": "image_10", "name": "images.image_10", "shape": 7, "type": "IMAGE", "link": None},
        ],
        "outputs": [
            {"name": "IMAGE", "type": "IMAGE", "links": []}
        ],
        "properties": {"cnr_id": "comfy-core", "ver": "0.44.0"},
        "widgets_values": [
            0,                              # resolution
            prompt,                         # prompt (single [Image_1] view)
            False,                          # switch_1 (refine_prompt)
            False,                          # thinking
            QWEN_MODELS["max_length"],      # max_length = 4096
            NEGATIVE,                       # negative_prompt
            QWEN_MODELS["cfg"],             # cfg = 1
            False,                          # switch (custom_size)
            QWEN_MODELS["width"],           # width = 1024
            QWEN_MODELS["height"],          # height = 1024
            QWEN_MODELS["scheduler"],       # scheduler = euler
            _seed,                          # seed
            QWEN_MODELS["unet_name"],
            QWEN_MODELS["clip_name"],
            QWEN_MODELS["vae_name"],
            QWEN_MODELS["device"],
            QWEN_MODELS["dtype"],
            QWEN_MODELS["clip_name_1"],
        ],
        "widgets_values_named": {
            "resolution":  0,
            "prompt":      prompt,
            "switch_1":    False,
            "thinking":    False,
            "max_length":  QWEN_MODELS["max_length"],
            "negative_prompt": NEGATIVE,
            "cfg":         QWEN_MODELS["cfg"],
            "switch":      False,
            "width":       QWEN_MODELS["width"],
            "height":      QWEN_MODELS["height"],
            "scheduler":   QWEN_MODELS["scheduler"],
            "seed":        _seed,
            "unet_name":   QWEN_MODELS["unet_name"],
            "clip_name":   QWEN_MODELS["clip_name"],
            "vae_name":    QWEN_MODELS["vae_name"],
            "device":      QWEN_MODELS["device"],
            "dtype":       QWEN_MODELS["dtype"],
            "clip_name_1": QWEN_MODELS["clip_name_1"],
        },
    }


def build():
    # ── 读取原版 10张.json，克隆 Qwen PE 节点 ──────────────────────────────
    with open("D:/下载/10张.json", encoding="utf-8") as f:
        orig = json.load(f)

    orig_pe = next(n for n in orig["nodes"] if "bc1c967a" in n.get("type", ""))
    print(f"Cloning Qwen PE node from original (id={orig_pe['id']})")

    nodes = []
    links = []
    nid = 1
    lid = 1

    # ── LoadImage (角色参考图) ─────────────────────────────────────────────
    ref_id = nid; nid += 1
    nodes.append({
        "id": ref_id,
        "type": "LoadImage",
        "title": "🎭 角色参考图",
        "pos": [50, 300],
        "size": [300, 420],
        "flags": {}, "order": 0, "mode": 0,
        "inputs": [],
        "outputs": [
            {"name": "IMAGE", "type": "IMAGE", "links": []},
            {"name": "MASK",  "type": "MASK",  "links": None},
        ],
        "properties": {"cnr_id": "comfy-core", "ver": "0.44.0",
                       "Node name for S&R": "LoadImage"},
        "widgets_values": ["reference.png", "image"],
        "widgets_values_named": {"image": "reference.png", "upload": "image"},
    })

    # ── AFE_NineViewPromptBuilder（角色描述 → 9个独立提示词）────────────────
    builder_id = nid; nid += 1
    nodes.append({
        "id": builder_id,
        "type": "AFE_NineViewPromptBuilder",
        "title": "🎬 角色描述 → 9视角提示词",
        "pos": [50, 50],
        "size": [560, 300],
        "flags": {}, "order": 0, "mode": 0,
        "inputs": [],
        "outputs": [
            {"name": f"prompt_{i+1}_{name}", "type": "STRING", "links": []}
            for i, name in enumerate([
                "设计参考图","正面全身","侧面全身",
                "面部中性","面部微笑","面部严肃",
                "场景喝茶","场景指向","场景自信坐",
            ])
        ] + [
            {"name": "negative_prompt", "type": "STRING", "links": []},
            {"name": "prompt_preview",  "type": "STRING", "links": []},
        ],
        "properties": {},
        "widgets_values": [
            # character_description (multiline)
            f"{CHAR}",
            # style_suffix
            STYLE,
            # negative_prompt
            NEGATIVE,
        ],
        "widgets_values_named": {
            "character_description": CHAR,
            "style_suffix": STYLE,
            "negative_prompt": NEGATIVE,
        },
    })

    # 找到 image_1 在 Qwen inputs 数组中的位置
    image1_idx = next(
        i for i, inp in enumerate(orig_pe["inputs"])
        if inp.get("label") == "image_1"
    )
    # 找到 prompt 在 Qwen inputs 数组中的位置
    prompt_idx = next(
        i for i, inp in enumerate(orig_pe["inputs"])
        if inp.get("label") == "positive_prompt"
    )
    print(f"  image_1 idx={image1_idx}, prompt idx={prompt_idx}")

    # ── 9 个独立 Qwen 节点 + 对应 PreviewImage ────────────────────────────
    COL_W   = 560
    PREV_H  = 1120
    QX_BASE = 680
    QY_BASE = 50

    for i, name in enumerate(VIEW_NAMES):
        col = i % 3
        row = i // 3
        qx = QX_BASE + col * COL_W
        qy = QY_BASE + row * PREV_H

        qwen_id = nid; nid += 1

        # Deep clone from original
        qwen = copy.deepcopy(orig_pe)
        qwen["id"]  = qwen_id
        qwen["pos"] = [qx, qy]
        qwen["outputs"][0]["links"] = []

        # max_length fix
        wv  = qwen["widgets_values"]
        wvn = qwen.get("widgets_values_named", {})
        wv[4] = 4096
        if "max_length" in wvn:
            wvn["max_length"] = 4096
        # Different seed per branch
        for j, v in enumerate(wv):
            if isinstance(v, int) and v > 100000000:
                wv[j] = 42 + i * 1000
                break

        # Disconnect ALL image slots, reconnect only image_1
        for inp in qwen["inputs"]:
            inp["link"] = None

        # Link: LoadImage → Qwen image_1
        link_ref = lid; lid += 1
        qwen["inputs"][image1_idx]["link"] = link_ref
        nodes[ref_id - 1]["outputs"][0]["links"].append(link_ref)
        links.append([link_ref, ref_id, 0, qwen_id, image1_idx, "IMAGE"])

        # Link: NineViewPromptBuilder.prompt_N → Qwen.prompt
        # Convert prompt input from widget to connected input
        link_prompt = lid; lid += 1
        qwen["inputs"][prompt_idx]["link"] = link_prompt
        nodes[builder_id - 1]["outputs"][i]["links"].append(link_prompt)
        links.append([link_prompt, builder_id, i, qwen_id, prompt_idx, "STRING"])

        nodes.append(qwen)

        # PreviewImage
        link_prev = lid; lid += 1
        prev_id   = nid; nid += 1
        qwen["outputs"][0]["links"].append(link_prev)
        links.append([link_prev, qwen_id, 0, prev_id, 0, "IMAGE"])

        nodes.append({
            "id": prev_id,
            "type": "PreviewImage",
            "title": f"🖼 {name}",
            "pos": [qx, qy + 720],
            "size": [480, 580],
            "flags": {}, "order": 20 + i, "mode": 0,
            "inputs": [{"name": "images", "type": "IMAGE", "link": link_prev}],
            "outputs": [], "properties": {}, "widgets_values": [],
        })

        print(f"  Branch {i+1}: Builder[{i}]→prompt + LoadImage→image_1 → Qwen{qwen_id} → Preview{prev_id}  [{name}]")

    return {
        "id": "afe-character-card-9branch-v3",
        "last_node_id": nid - 1,
        "last_link_id": lid - 1,
        "nodes": nodes,
        "links": links,
        "version": 0.4,
    }


if __name__ == "__main__":
    dst = "D:/下载/character_card_9branch.json"
    print("Building 9-branch Qwen character card workflow...\n")
    wf = build()
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {dst}")
    print(f"Nodes: {wf['last_node_id']}, Links: {wf['last_link_id']}")
    print("""
Structure:
  LoadImage (角色参考图)
    ├→ Qwen_1 → PreviewImage_1  (🎨 角色设计参考图)
    ├→ Qwen_2 → PreviewImage_2  (正面全身)
    ├→ Qwen_3 → PreviewImage_3  (侧面全身)
    ├→ Qwen_4 → PreviewImage_4  (面部·中性)
    ├→ Qwen_5 → PreviewImage_5  (面部·微笑)
    ├→ Qwen_6 → PreviewImage_6  (面部·严肃)
    ├→ Qwen_7 → PreviewImage_7  (场景·喝茶)
    ├→ Qwen_8 → PreviewImage_8  (场景·指向)
    └→ Qwen_9 → PreviewImage_9  (场景·自信坐)

每个 Qwen 节点:
  - 只有 image_1 连接角色参考图
  - 自己独立的 [Image_1] 提示词
  - 独立输出1张图 → 总共9张独立图
""")
