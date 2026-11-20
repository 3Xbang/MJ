#!/usr/bin/env python3
"""
gen_afe_main_workflow.py
Generates the AFE Script Analysis Pipeline ComfyUI workflow JSON.
Run: python gen_afe_main_workflow.py
Output: workflow_templates/afe_script_pipeline.json
"""
import json
import os

# ── English system prompt for LLM_local ──────────────────────────────────────
SYSTEM_PROMPT_EN = (
    "You are a professional film storyboard artist. Parse the script into a JSON object. "
    "Return ONLY the JSON object, no other text.\n\n"
    "OUTPUT FORMAT:\n"
    '{\n'
    '  "cast": [\n'
    '    {"name": "CharacterName", "role_type": "lead|supporting|extra_a|extra_b|extra_other",\n'
    '     "gender": "male|female|unknown", "age_range": "24-26",\n'
    '     "appearance_en": "English appearance description",\n'
    '     "default_costume_en": "English costume description"}\n'
    '  ],\n'
    '  "shots": [\n'
    '    {\n'
    '      "shot_id": "shot_001", "label": "Scene01-Location",\n'
    '      "duration_seconds": 5.0,\n'
    '      "character_names": ["name"],\n'
    '      "costume_description": "Chinese costume description",\n'
    '      "costume_en": "English costume description",\n'
    '      "props_list": ["prop1", "prop2"],\n'
    '      "scene_name": "Scene Name-Indoor/Outdoor",\n'
    '      "camera_angle": "medium",\n'
    '      "camera_motion": "static",\n'
    '      "lighting_style": "natural light, afternoon",\n'
    '      "director_notes": "...",\n'
    '      "shot_description": "English description max 80 words",\n'
    '      "negative_prompt": "ugly, blurry",\n'
    '      "dialogue": "dialogue text or \uff08\u65e0\uff09",\n'
    '      "location": "apartment living room, near window",\n'
    '      "time_of_day": "morning|afternoon|evening|night",\n'
    '      "weather": "sunny|cloudy|rainy|snowy|foggy|indoor|clear",\n'
    '      "lighting": "detailed English lighting description",\n'
    '      "action": "main character action in English",\n'
    '      "business": "subtle physical detail, e.g. fingers the rim of the cup",\n'
    '      "emotion": "character emotion/expression in English"\n'
    '    }\n'
    '  ]\n'
    '}\n\n'
    "RULES:\n"
    "- camera_angle: close_up | medium | wide | low_angle | high_angle | eye_level | dutch\n"
    "- camera_motion: static | pan_left | pan_right | zoom_in | zoom_out | tilt_up | tilt_down | "
    "orbit | slow_push_in | slow_pull_back | tracking_shot | handheld\n"
    "- role_type: lead | supporting | extra_a | extra_b | extra_other\n"
    "- time_of_day: morning | afternoon | evening | night\n"
    "- weather: sunny | cloudy | rainy | snowy | foggy | indoor | clear\n"
    "- Return ONLY the JSON object."
)

SCRIPT_PLACEHOLDER = "在这里输入剧本..."


def build_workflow() -> dict:
    """Build the ComfyUI workflow dict."""

    nodes = []
    links = []
    link_id = 0

    def next_link():
        nonlocal link_id
        link_id += 1
        return link_id

    # ── Node 1: LLM_local_loader ─────────────────────────────────────────────
    lnk_model     = next_link()   # 1
    lnk_tokenizer = next_link()   # 2
    nodes.append({
        "id": 1,
        "type": "LLM_local_loader",
        "pos": [50, 100],
        "size": {"0": 320, "1": 170},
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [
            {"name": "model",     "type": "CUSTOM", "links": [lnk_model],     "slot_index": 0},
            {"name": "tokenizer", "type": "CUSTOM", "links": [lnk_tokenizer], "slot_index": 1},
        ],
        "properties": {"Node name for S&R": "LLM_local_loader"},
        "widgets_values": ["models/LLM/Qwen2.5-7B-Instruct/", "cuda", "float16", False],
    })

    # ── Node 2: LLM_local ────────────────────────────────────────────────────
    lnk_llm_out = next_link()   # 3
    nodes.append({
        "id": 2,
        "type": "LLM_local",
        "pos": [430, 50],
        "size": {"0": 400, "1": 500},
        "flags": {},
        "order": 1,
        "mode": 0,
        "inputs": [
            {"name": "model",     "type": "CUSTOM", "link": lnk_model},
            {"name": "tokenizer", "type": "CUSTOM", "link": lnk_tokenizer},
        ],
        "outputs": [
            {"name": "assistant_response", "type": "STRING", "links": [lnk_llm_out], "slot_index": 0},
            {"name": "history",            "type": "STRING", "links": None,           "slot_index": 1},
        ],
        "properties": {"Node name for S&R": "LLM_local"},
        "widgets_values": [
            SYSTEM_PROMPT_EN,    # system_prompt (STRING)
            SCRIPT_PLACEHOLDER,  # user_prompt (STRING)
            "LLM",               # model_type (COMBO)
            0.3,                 # temperature (FLOAT)
            4096,                # max_length (INT)
            "disable",           # is_memory (COMBO)
            "disable",           # is_locked (COMBO)
            "enable",            # main_brain (COMBO)
            1,                   # conversation_rounds (INT)
            "",                  # historical_record (COMBO, '' = first/only option)
            True,                # is_enable (BOOLEAN)
            "enable",            # is_enable_system_role (COMBO)
        ],
    })
    links.append([lnk_model,     1, 0, 2, 0, "CUSTOM"])
    links.append([lnk_tokenizer, 1, 1, 2, 1, "CUSTOM"])

    # ── Node 3: AFE_ScriptParser ─────────────────────────────────────────────
    # Outputs: [0]=shot_sequence, [1]=cast_data, [2]=unique_scenes_json,
    #          [3]=props_list_json, [4]=shot_count, [5]=scene_count,
    #          [6]=props_count, [7]=sequence_json, [8]=prompt_for_llm
    lnk_shot_seq  = next_link()   # 4
    lnk_cast_data = next_link()   # 5
    nodes.append({
        "id": 3,
        "type": "AFE_ScriptParser",
        "pos": [900, 100],
        "size": {"0": 380, "1": 400},
        "flags": {},
        "order": 2,
        "mode": 0,
        "inputs": [
            {"name": "llm_response", "type": "STRING", "link": lnk_llm_out},
        ],
        "outputs": [
            {"name": "shot_sequence",     "type": "SHOT_SEQUENCE", "links": [], "slot_index": 0},
            {"name": "cast_data",         "type": "CAST_DATA",     "links": [], "slot_index": 1},
            {"name": "unique_scenes_json","type": "STRING",        "links": None, "slot_index": 2},
            {"name": "props_list_json",   "type": "STRING",        "links": None, "slot_index": 3},
            {"name": "shot_count",        "type": "INT",           "links": None, "slot_index": 4},
            {"name": "scene_count",       "type": "INT",           "links": None, "slot_index": 5},
            {"name": "props_count",       "type": "INT",           "links": None, "slot_index": 6},
            {"name": "sequence_json",     "type": "STRING",        "links": None, "slot_index": 7},
            {"name": "prompt_for_llm",    "type": "STRING",        "links": None, "slot_index": 8},
        ],
        "properties": {"Node name for S&R": "AFE_ScriptParser"},
        "widgets_values": [SCRIPT_PLACEHOLDER, 0, 5, "", "", "https://api.deepseek.com/v1", "deepseek-chat"],
    })
    links.append([lnk_llm_out, 2, 0, 3, 0, "STRING"])
    # We'll fill shot_sequence and cast_data links after creating downstream nodes

    # ── Node 4: AFE_SceneAnalyzer ────────────────────────────────────────────
    # Outputs: [0]=scenes_json, [1]=scenes_count, [2]=scene_report
    lnk_scene_report = next_link()   # 6
    lnk_ss4 = next_link()   # 7  shot_sequence → Node4
    nodes.append({
        "id": 4,
        "type": "AFE_SceneAnalyzer",
        "pos": [1360, 0],
        "size": {"0": 320, "1": 120},
        "flags": {},
        "order": 3,
        "mode": 0,
        "inputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "link": lnk_ss4},
        ],
        "outputs": [
            {"name": "scenes_json",   "type": "STRING", "links": None,              "slot_index": 0},
            {"name": "scenes_count",  "type": "INT",    "links": None,              "slot_index": 1},
            {"name": "scene_report",  "type": "STRING", "links": [lnk_scene_report],"slot_index": 2},
        ],
        "properties": {"Node name for S&R": "AFE_SceneAnalyzer"},
        "widgets_values": ["3D CG animation, CGI rendering, cinematic"],
    })
    links.append([lnk_ss4, 3, 0, 4, 0, "SHOT_SEQUENCE"])

    # ── Node 5: AFE_PropsAnalyzer ────────────────────────────────────────────
    # Outputs: [0]=props_json, [1]=props_count, [2]=props_report
    lnk_props_report = next_link()   # 8
    lnk_ss5 = next_link()   # 9
    nodes.append({
        "id": 5,
        "type": "AFE_PropsAnalyzer",
        "pos": [1360, 160],
        "size": {"0": 320, "1": 120},
        "flags": {},
        "order": 4,
        "mode": 0,
        "inputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "link": lnk_ss5},
        ],
        "outputs": [
            {"name": "props_json",   "type": "STRING", "links": None,              "slot_index": 0},
            {"name": "props_count",  "type": "INT",    "links": None,              "slot_index": 1},
            {"name": "props_report", "type": "STRING", "links": [lnk_props_report],"slot_index": 2},
        ],
        "properties": {"Node name for S&R": "AFE_PropsAnalyzer"},
        "widgets_values": ["product photography style, studio lighting, clean white background, sharp focus"],
    })
    links.append([lnk_ss5, 3, 0, 5, 0, "SHOT_SEQUENCE"])

    # ── Node 6: AFE_CastAnalyzer ─────────────────────────────────────────────
    lnk_ss6  = next_link()   # 10
    lnk_cd6  = next_link()   # 11
    nodes.append({
        "id": 6,
        "type": "AFE_CastAnalyzer",
        "pos": [1360, 320],
        "size": {"0": 320, "1": 140},
        "flags": {},
        "order": 5,
        "mode": 0,
        "inputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "link": lnk_ss6},
            {"name": "cast_data",     "type": "CAST_DATA",     "link": lnk_cd6},
        ],
        "outputs": [
            {"name": "characters_json",  "type": "STRING", "links": None, "slot_index": 0},
            {"name": "characters_count", "type": "INT",    "links": None, "slot_index": 1},
        ],
        "properties": {"Node name for S&R": "AFE_CastAnalyzer"},
        "widgets_values": ["photorealistic, studio lighting, white background"],
    })
    links.append([lnk_ss6, 3, 0, 6, 0, "SHOT_SEQUENCE"])
    links.append([lnk_cd6, 3, 1, 6, 1, "CAST_DATA"])

    # ── Node 7: AFE_CharacterTracker ─────────────────────────────────────────
    # Outputs: [0]=tracking_json, [1]=tracking_report, [2]=character_count
    lnk_tracking_report = next_link()   # 12
    lnk_ss7 = next_link()   # 13
    lnk_cd7 = next_link()   # 14
    nodes.append({
        "id": 7,
        "type": "AFE_CharacterTracker",
        "pos": [1360, 500],
        "size": {"0": 320, "1": 120},
        "flags": {},
        "order": 6,
        "mode": 0,
        "inputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "link": lnk_ss7},
            {"name": "cast_data",     "type": "CAST_DATA",     "link": lnk_cd7},
        ],
        "outputs": [
            {"name": "tracking_json",    "type": "STRING", "links": None,                    "slot_index": 0},
            {"name": "tracking_report",  "type": "STRING", "links": [lnk_tracking_report],   "slot_index": 1},
            {"name": "character_count",  "type": "INT",    "links": None,                    "slot_index": 2},
        ],
        "properties": {"Node name for S&R": "AFE_CharacterTracker"},
        "widgets_values": [],
    })
    links.append([lnk_ss7, 3, 0, 7, 0, "SHOT_SEQUENCE"])
    links.append([lnk_cd7, 3, 1, 7, 1, "CAST_DATA"])

    # ── Node 8: AFE_ShotPromptBuilder ────────────────────────────────────────
    # Outputs: [0]=shots_prompts_json, [1]=shot_count, [2]=first_prompt_en,
    #          [3]=first_prompt_cn, [4]=first_negative, [5]=report
    lnk_shots_prompts = next_link()   # 15
    lnk_shot_report   = next_link()   # 16
    lnk_ss8 = next_link()   # 17
    lnk_cd8 = next_link()   # 18
    nodes.append({
        "id": 8,
        "type": "AFE_ShotPromptBuilder",
        "pos": [1360, 660],
        "size": {"0": 320, "1": 160},
        "flags": {},
        "order": 7,
        "mode": 0,
        "inputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "link": lnk_ss8},
            {"name": "cast_data",     "type": "CAST_DATA",     "link": lnk_cd8},
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
    links.append([lnk_ss8, 3, 0, 8, 0, "SHOT_SEQUENCE"])
    links.append([lnk_cd8, 3, 1, 8, 1, "CAST_DATA"])

    # ── Node 9: AFE_ShotList ─────────────────────────────────────────────────
    # Outputs: [0]=shot_list_report, [1]=shot_count, [2]=total_duration_seconds, [3]=shot_summary_json
    lnk_shot_list_report = next_link()   # 19
    lnk_sp9 = next_link()   # 20  shots_prompts_json → Node9
    nodes.append({
        "id": 9,
        "type": "AFE_ShotList",
        "pos": [1740, 660],
        "size": {"0": 320, "1": 120},
        "flags": {},
        "order": 8,
        "mode": 0,
        "inputs": [
            {"name": "shots_prompts_json", "type": "STRING", "link": lnk_sp9},
        ],
        "outputs": [
            {"name": "shot_list_report",       "type": "STRING", "links": [lnk_shot_list_report], "slot_index": 0},
            {"name": "shot_count",             "type": "INT",    "links": None,                   "slot_index": 1},
            {"name": "total_duration_seconds", "type": "FLOAT",  "links": None,                   "slot_index": 2},
            {"name": "shot_summary_json",      "type": "STRING", "links": None,                   "slot_index": 3},
        ],
        "properties": {"Node name for S&R": "AFE_ShotList"},
        "widgets_values": [],
    })
    links.append([lnk_sp9, 8, 0, 9, 0, "STRING"])

    # ── Nodes 10-14: show_text_party display nodes ────────────────────────────
    display_configs = [
        (10, lnk_scene_report,    "scene_report from SceneAnalyzer",  [1740,  0]),
        (11, lnk_props_report,    "props_report from PropsAnalyzer",  [1740, 160]),
        (12, lnk_tracking_report, "tracking_report from CharTracker", [1740, 320]),
        (13, lnk_shot_list_report,"shot_list_report from ShotList",   [2120, 660]),
        (14, lnk_shot_report,     "shot_report from ShotPromptBuilder",[1740, 500]),
    ]
    for node_id, lnk_in, title, pos in display_configs:
        nodes.append({
            "id": node_id,
            "type": "show_text_party",
            "pos": pos,
            "size": {"0": 360, "1": 140},
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

    links.append([lnk_scene_report,     4, 2, 10, 0, "STRING"])
    links.append([lnk_props_report,     5, 2, 11, 0, "STRING"])
    links.append([lnk_tracking_report,  7, 1, 12, 0, "STRING"])
    links.append([lnk_shot_list_report, 9, 0, 13, 0, "STRING"])
    links.append([lnk_shot_report,      8, 5, 14, 0, "STRING"])

    # Patch shot_sequence and cast_data output links in Node 3
    ss_link_ids  = [lnk_ss4, lnk_ss5, lnk_ss6, lnk_ss7, lnk_ss8]
    cd_link_ids  = [lnk_cd6, lnk_cd7, lnk_cd8]
    for node in nodes:
        if node["id"] == 3:
            node["outputs"][0]["links"] = ss_link_ids   # shot_sequence
            node["outputs"][1]["links"] = cd_link_ids   # cast_data

    workflow = {
        "last_node_id": 14,
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
    print(f"   Nodes: {len(workflow['nodes'])}")
    print(f"   Links: {len(workflow['links'])}")


if __name__ == "__main__":
    main()
