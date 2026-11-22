#!/usr/bin/env python3
"""
gen_afe_main_workflow.py
Generates the AFE Script Analysis Pipeline ComfyUI workflow JSON.
Run: python gen_afe_main_workflow.py
Output: workflow_templates/afe_script_pipeline.json
"""
import json
import os


def build_workflow() -> dict:
    """Build the ComfyUI workflow dict.

    New layout: single AFE_ScriptFullParser replaces the three-node
    LLM_local_loader → LLM_local → AFE_ScriptParser chain.
    """

    nodes = []
    links = []
    link_id = 0

    def next_link():
        nonlocal link_id
        link_id += 1
        return link_id

    # ── Node 1: AFE_ScriptFullParser ─────────────────────────────────────────
    # Outputs:
    #   [0] shot_sequence  (SHOT_SEQUENCE)
    #   [1] cast_data      (CAST_DATA)
    #   [2] shots_json     (STRING)
    #   [3] cast_json      (STRING)
    #   [4] shot_count     (INT)
    #   [5] scene_count    (INT)
    #   [6] props_count    (INT)
    #   [7] report         (STRING)  → node 13

    # Pre-allocate link IDs for node-1 outputs that fan out to downstream nodes
    lnk_ss2          = next_link()   #  1 shot_sequence → node 2
    lnk_ss3          = next_link()   #  2 shot_sequence → node 3
    lnk_ss4          = next_link()   #  3 shot_sequence → node 4
    lnk_cd4          = next_link()   #  4 cast_data     → node 4
    lnk_ss5          = next_link()   #  5 shot_sequence → node 5
    lnk_cd5          = next_link()   #  6 cast_data     → node 5
    lnk_ss6          = next_link()   #  7 shot_sequence → node 6
    lnk_cd6          = next_link()   #  8 cast_data     → node 6
    lnk_report13     = next_link()   #  9 report        → node 13
    lnk_scene_to_gen  = next_link()   # scene_report → AFE_SceneImageGenerator
    lnk_est_preview   = next_link()   # establishing_shots_batch → PreviewImage
    lnk_med_preview   = next_link()   # medium_shots_batch → PreviewImage
    lnk_atm_preview   = next_link()   # atmosphere_shots_batch → PreviewImage

    nodes.append({
        "id": 1,
        "type": "AFE_ScriptFullParser",
        "pos": [50, 300],
        "size": {"0": 400, "1": 220},
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "links": [lnk_ss2, lnk_ss3, lnk_ss4, lnk_ss5, lnk_ss6], "slot_index": 0},
            {"name": "cast_data",     "type": "CAST_DATA",     "links": [lnk_cd4, lnk_cd5, lnk_cd6],                   "slot_index": 1},
            {"name": "shots_json",    "type": "STRING",         "links": None,                                           "slot_index": 2},
            {"name": "cast_json",     "type": "STRING",         "links": None,                                           "slot_index": 3},
            {"name": "shot_count",    "type": "INT",            "links": None,                                           "slot_index": 4},
            {"name": "scene_count",   "type": "INT",            "links": None,                                           "slot_index": 5},
            {"name": "props_count",   "type": "INT",            "links": None,                                           "slot_index": 6},
            {"name": "report",        "type": "STRING",         "links": [lnk_report13],                                 "slot_index": 7},
        ],
        "properties": {"Node name for S&R": "AFE_ScriptFullParser"},
        "widgets_values": [
            "在这里输入剧本...",                             # raw_script
            "3D cartoon Pixar animation style, vibrant colors, 8k",  # render_style (COMBO)
            "迷你剧集 Mini Episode (5-10 min)",             # episode_format (COMBO)
            180,                                             # target_duration_seconds
            5,                                               # seconds_per_shot
            "auto (from script)",                            # lighting_mood (COMBO)
            "auto (from style)",                             # color_palette (COMBO)
            "LLM/Qwen2.5-7B-Instruct",                      # model_path
        ],
    })

    # ── Node 2: AFE_SceneAnalyzer ────────────────────────────────────────────
    # Outputs: [0]=scenes_json, [1]=scenes_count, [2]=scene_report
    lnk_scene_report = next_link()   # 10
    lnk_scenes_json_to_gen = next_link()   # scenes_json → SceneImageGenerator

    nodes.append({
        "id": 2,
        "type": "AFE_SceneAnalyzer",
        "pos": [520, 0],
        "size": {"0": 380, "1": 120},
        "flags": {},
        "order": 1,
        "mode": 0,
        "inputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "link": lnk_ss2},
        ],
        "outputs": [
            {"name": "scenes_json",  "type": "STRING", "links": [lnk_scenes_json_to_gen], "slot_index": 0},
            {"name": "scenes_count", "type": "INT",    "links": None,                      "slot_index": 1},
            {"name": "scene_report", "type": "STRING", "links": [lnk_scene_report],        "slot_index": 2},
        ],
        "properties": {"Node name for S&R": "AFE_SceneAnalyzer"},
        "widgets_values": ["3D CG animation, CGI rendering, cinematic"],
    })
    links.append([lnk_ss2, 1, 0, 2, 0, "SHOT_SEQUENCE"])

    # ── Node 14: AFE_SceneImageGenerator ────────────────────────────────────
    # Outputs: [0]=establishing_shots_batch, [1]=medium_shots_batch,
    #          [2]=atmosphere_shots_batch,   [3]=generation_report
    nodes.append({
        "id": 14,
        "type": "AFE_SceneImageGenerator",
        "pos": [960, -200],
        "size": {"0": 420, "1": 260},
        "flags": {},
        "order": 14,
        "mode": 0,
        "inputs": [
            {"name": "scene_report", "type": "STRING", "link": lnk_scene_to_gen},
            {"name": "scenes_json",  "type": "STRING", "link": lnk_scenes_json_to_gen},
        ],
        "outputs": [
            {"name": "establishing_shots_batch", "type": "IMAGE",  "links": [lnk_est_preview], "slot_index": 0},
            {"name": "medium_shots_batch",       "type": "IMAGE",  "links": [lnk_med_preview], "slot_index": 1},
            {"name": "atmosphere_shots_batch",   "type": "IMAGE",  "links": [lnk_atm_preview], "slot_index": 2},
            {"name": "generation_report",        "type": "STRING", "links": None,              "slot_index": 3},
        ],
        "properties": {"Node name for S&R": "AFE_SceneImageGenerator"},
        "widgets_values": [
            "",     # scene_report (connected via link, placeholder)
            "3D cartoon Pixar animation style, vibrant colors, 8k, highly detailed",  # render_style
            "",     # scenes_json (connected via link, placeholder)
            1024,   # width
            576,    # height
            8,      # steps
            1.0,    # cfg
            42,     # seed
        ],
    })
    links.append([lnk_scene_to_gen, 2, 2, 14, 0, "STRING"])

    # ── Nodes 15-17: PreviewImage for each batch output ──────────────────────
    preview_configs = [
        (15, lnk_est_preview, "establishing_shots_batch", [1400, -280], 14, 0),
        (16, lnk_med_preview, "medium_shots_batch",       [1400, -100], 14, 1),
        (17, lnk_atm_preview, "atmosphere_shots_batch",   [1400,  80],  14, 2),
    ]
    for node_id, lnk_in, title, pos, src_node, src_slot in preview_configs:
        nodes.append({
            "id": node_id,
            "type": "PreviewImage",
            "pos": pos,
            "size": {"0": 360, "1": 220},
            "flags": {},
            "order": node_id,
            "mode": 0,
            "inputs": [
                {"name": "images", "type": "IMAGE", "link": lnk_in},
            ],
            "outputs": [],
            "title": title,
            "properties": {"Node name for S&R": "PreviewImage"},
            "widgets_values": [],
        })
        links.append([lnk_in, src_node, src_slot, node_id, 0, "IMAGE"])

    # ── Node 3: AFE_PropsAnalyzer ────────────────────────────────────────────
    # Outputs: [0]=props_json, [1]=props_count, [2]=props_report
    lnk_props_report = next_link()   # 11
    nodes.append({
        "id": 3,
        "type": "AFE_PropsAnalyzer",
        "pos": [520, 180],
        "size": {"0": 380, "1": 120},
        "flags": {},
        "order": 2,
        "mode": 0,
        "inputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "link": lnk_ss3},
        ],
        "outputs": [
            {"name": "props_json",   "type": "STRING", "links": None,              "slot_index": 0},
            {"name": "props_count",  "type": "INT",    "links": None,              "slot_index": 1},
            {"name": "props_report", "type": "STRING", "links": [lnk_props_report],"slot_index": 2},
        ],
        "properties": {"Node name for S&R": "AFE_PropsAnalyzer"},
        "widgets_values": ["product photography style, studio lighting, clean white background, sharp focus"],
    })
    links.append([lnk_ss3, 1, 0, 3, 0, "SHOT_SEQUENCE"])

    # ── Node 4: AFE_CastAnalyzer ─────────────────────────────────────────────
    nodes.append({
        "id": 4,
        "type": "AFE_CastAnalyzer",
        "pos": [520, 360],
        "size": {"0": 380, "1": 140},
        "flags": {},
        "order": 3,
        "mode": 0,
        "inputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "link": lnk_ss4},
            {"name": "cast_data",     "type": "CAST_DATA",     "link": lnk_cd4},
        ],
        "outputs": [
            {"name": "characters_json",  "type": "STRING", "links": None, "slot_index": 0},
            {"name": "characters_count", "type": "INT",    "links": None, "slot_index": 1},
        ],
        "properties": {"Node name for S&R": "AFE_CastAnalyzer"},
        "widgets_values": ["photorealistic, studio lighting, white background"],
    })
    links.append([lnk_ss4, 1, 0, 4, 0, "SHOT_SEQUENCE"])
    links.append([lnk_cd4, 1, 1, 4, 1, "CAST_DATA"])

    # ── Node 5: AFE_CharacterTracker ─────────────────────────────────────────
    # Outputs: [0]=tracking_json, [1]=tracking_report, [2]=character_count
    lnk_tracking_report = next_link()   # 12
    nodes.append({
        "id": 5,
        "type": "AFE_CharacterTracker",
        "pos": [520, 540],
        "size": {"0": 380, "1": 120},
        "flags": {},
        "order": 4,
        "mode": 0,
        "inputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "link": lnk_ss5},
            {"name": "cast_data",     "type": "CAST_DATA",     "link": lnk_cd5},
        ],
        "outputs": [
            {"name": "tracking_json",   "type": "STRING", "links": None,                   "slot_index": 0},
            {"name": "tracking_report", "type": "STRING", "links": [lnk_tracking_report],  "slot_index": 1},
            {"name": "character_count", "type": "INT",    "links": None,                   "slot_index": 2},
        ],
        "properties": {"Node name for S&R": "AFE_CharacterTracker"},
        "widgets_values": [],
    })
    links.append([lnk_ss5, 1, 0, 5, 0, "SHOT_SEQUENCE"])
    links.append([lnk_cd5, 1, 1, 5, 1, "CAST_DATA"])

    # ── Node 6: AFE_ShotPromptBuilder ────────────────────────────────────────
    # Outputs: [0]=shots_prompts_json, [1]=shot_count, [2]=first_prompt_en,
    #          [3]=first_prompt_cn, [4]=first_negative, [5]=report
    lnk_shots_prompts = next_link()   # 13
    lnk_shot_report   = next_link()   # 14
    nodes.append({
        "id": 6,
        "type": "AFE_ShotPromptBuilder",
        "pos": [520, 720],
        "size": {"0": 380, "1": 160},
        "flags": {},
        "order": 5,
        "mode": 0,
        "inputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "link": lnk_ss6},
            {"name": "cast_data",     "type": "CAST_DATA",     "link": lnk_cd6},
        ],
        "outputs": [
            {"name": "shots_prompts_json", "type": "STRING", "links": [lnk_shots_prompts], "slot_index": 0},
            {"name": "shot_count",         "type": "INT",    "links": None,                "slot_index": 1},
            {"name": "first_prompt_en",    "type": "STRING", "links": None,                "slot_index": 2},
            {"name": "first_prompt_cn",    "type": "STRING", "links": None,                "slot_index": 3},
            {"name": "first_negative",     "type": "STRING", "links": None,                "slot_index": 4},
            {"name": "report",             "type": "STRING", "links": [lnk_shot_report],   "slot_index": 5},
        ],
        "properties": {"Node name for S&R": "AFE_ShotPromptBuilder"},
        "widgets_values": ["", 1, 0],
    })
    links.append([lnk_ss6, 1, 0, 6, 0, "SHOT_SEQUENCE"])
    links.append([lnk_cd6, 1, 1, 6, 1, "CAST_DATA"])

    # ── Node 7: AFE_ShotList ─────────────────────────────────────────────────
    # Outputs: [0]=shot_list_report, [1]=shot_count, [2]=total_duration_seconds, [3]=shot_summary_json
    lnk_shot_list_report = next_link()   # 15
    nodes.append({
        "id": 7,
        "type": "AFE_ShotList",
        "pos": [960, 720],
        "size": {"0": 380, "1": 120},
        "flags": {},
        "order": 6,
        "mode": 0,
        "inputs": [
            {"name": "shots_prompts_json", "type": "STRING", "link": lnk_shots_prompts},
        ],
        "outputs": [
            {"name": "shot_list_report",       "type": "STRING", "links": [lnk_shot_list_report], "slot_index": 0},
            {"name": "shot_count",             "type": "INT",    "links": None,                   "slot_index": 1},
            {"name": "total_duration_seconds", "type": "FLOAT",  "links": None,                   "slot_index": 2},
            {"name": "shot_summary_json",      "type": "STRING", "links": None,                   "slot_index": 3},
        ],
        "properties": {"Node name for S&R": "AFE_ShotList"},
        "widgets_values": [0],  # target_duration_seconds (0 = no comparison)
    })
    links.append([lnk_shots_prompts, 6, 0, 7, 0, "STRING"])

    # ── Nodes 8-13: show_text_party display nodes ─────────────────────────────
    # (node_id, incoming_link, title, pos, source_node, source_slot)
    display_configs = [
        (8,  lnk_scene_report,     "scene_report from SceneAnalyzer",        [960,   0],   2, 2),
        (9,  lnk_props_report,     "props_report from PropsAnalyzer",         [960, 180],   3, 2),
        (10, lnk_tracking_report,  "tracking_report from CharacterTracker",   [960, 360],   5, 1),
        (11, lnk_shot_report,      "report from ShotPromptBuilder",           [960, 540],   6, 5),
        (12, lnk_shot_list_report, "shot_list_report from ShotList",          [1360, 720],  7, 0),
        (13, lnk_report13,         "report from AFE_ScriptFullParser",        [520,  940],  1, 7),
    ]
    for node_id, lnk_in, title, pos, src_node, src_slot in display_configs:
        nodes.append({
            "id": node_id,
            "type": "show_text_party",
            "pos": pos,
            "size": {"0": 380, "1": 140},
            "flags": {},
            "order": node_id - 1,
            "mode": 0,
            "inputs": [
                {"name": "text", "type": "STRING", "link": lnk_in},
            ],
            "outputs": [
                {"name": "text", "type": "STRING", "links": None, "slot_index": 0},
            ],
            "title": title,
            "properties": {"Node name for S&R": "show_text_party"},
            "widgets_values": [""],
        })
        links.append([lnk_in, src_node, src_slot, node_id, 0, "STRING"])

    workflow = {
        "last_node_id": 17,
        "last_link_id": link_id,
        "nodes": nodes,
        "links": links,
        "groups": [],
        "config": {},
        "extra": {"ds": {"scale": 0.6, "offset": [0, 0]}},
        "version": 0.4,
    }
    return workflow


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "workflow_templates")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "afe_script_pipeline.json")

    workflow = build_workflow()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(workflow, f, ensure_ascii=False, indent=2)
    print(f"✅ Workflow saved to: {out_path}")

    # Also save to user's local downloads folder
    downloads_dir = "D:/下载"
    try:
        os.makedirs(downloads_dir, exist_ok=True)
        downloads_path = os.path.join(downloads_dir, "afe_script_pipeline.json")
        with open(downloads_path, "w", encoding="utf-8") as f:
            json.dump(workflow, f, ensure_ascii=False, indent=2)
        print(f"✅ Also saved to: {downloads_path}")
    except OSError as e:
        print(f"⚠️ Could not save to {downloads_dir}: {e}")
    print(f"   Nodes: {len(workflow['nodes'])}")
    print(f"   Links: {len(workflow['links'])}")


if __name__ == "__main__":
    main()
