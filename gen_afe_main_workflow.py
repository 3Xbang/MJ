#!/usr/bin/env python3
"""Generate the checked-in AFE workflow templates.

The full artifact keeps the original downstream graph, but its consumers read
only from AFE_AnalysisLoader. The loader rejects partial analysis.json files,
so a parser batch can never start asset or video generation. The WebUI uses the
small batch graph for step 1 and builds stages 2-5 after the session is complete.
"""
import json
import os


ROOT = os.path.dirname(__file__)
FULL_TEMPLATE = os.path.join(ROOT, "workflow_templates", "afe_full_pipeline.json")


def build_workflow() -> dict:
    """Load the gated full graph without reconnecting partial parser output."""
    with open(FULL_TEMPLATE, encoding="utf-8") as handle:
        workflow = json.load(handle)
    types = {node.get("type") for node in workflow.get("nodes", [])}
    if "AFE_AnalysisLoader" not in types:
        raise ValueError("full workflow must use AFE_AnalysisLoader as its durable gate")
    parser = next(node for node in workflow["nodes"] if node.get("type") == "AFE_ScriptFullParser")
    if any(link for link in workflow.get("links", []) if link[1] == parser["id"] and link[2] in (0, 1)):
        raise ValueError("partial parser output is connected to the full workflow")
    return workflow


def build_batch_workflow() -> dict:
    """Build the bounded parser graph used for one persisted session batch."""
    parser = {
        "id": 1, "type": "AFE_ScriptFullParser", "pos": [50, 300],
        "size": {"0": 400, "1": 220}, "flags": {}, "order": 0, "mode": 0,
        "inputs": [],
        "outputs": [
            {"name": "shot_sequence", "type": "SHOT_SEQUENCE", "links": None, "slot_index": 0},
            {"name": "cast_data", "type": "CAST_DATA", "links": None, "slot_index": 1},
            {"name": "shots_json", "type": "STRING", "links": None, "slot_index": 2},
            {"name": "cast_json", "type": "STRING", "links": None, "slot_index": 3},
            {"name": "shot_count", "type": "INT", "links": None, "slot_index": 4},
            {"name": "scene_count", "type": "INT", "links": None, "slot_index": 5},
            {"name": "props_count", "type": "INT", "links": None, "slot_index": 6},
            {"name": "report", "type": "STRING", "links": [1], "slot_index": 7},
        ],
        "properties": {"Node name for S&R": "AFE_ScriptFullParser"},
        "widgets_values": [
            "在这里输入剧本...", "3D cartoon Pixar animation style, vibrant colors, 8k",
            "迷你剧集 Mini Episode (5-10 min)", 180, 5, "auto (from script)",
            "auto (from style)", "LLM/Qwen2.5-7B-Instruct", 1, 4, "",
        ],
    }
    display = {
        "id": 2, "type": "show_text_party", "pos": [520, 300],
        "size": {"0": 380, "1": 140}, "flags": {}, "order": 1, "mode": 0,
        "inputs": [{"name": "text", "type": "STRING", "link": 1}], "outputs": [],
        "title": "report from AFE_ScriptFullParser",
        "properties": {"Node name for S&R": "show_text_party"}, "widgets_values": [""],
    }
    return {
        "last_node_id": 2, "last_link_id": 1, "nodes": [parser, display],
        "links": [[1, 1, 7, 2, 0, "STRING"]], "groups": [], "config": {},
        "extra": {"ds": {"scale": 0.6, "offset": [0, 0]}}, "version": 0.4,
    }


def main():
    out_dir = os.path.join(ROOT, "workflow_templates")
    os.makedirs(out_dir, exist_ok=True)
    full_path = os.path.join(out_dir, "afe_full_pipeline.json")
    batch_path = os.path.join(out_dir, "afe_script_pipeline.json")
    full_workflow = build_workflow()
    batch_workflow = build_batch_workflow()
    with open(full_path, "w", encoding="utf-8") as handle:
        json.dump(full_workflow, handle, ensure_ascii=False, indent=2)
    with open(batch_path, "w", encoding="utf-8") as handle:
        json.dump(batch_workflow, handle, ensure_ascii=False, indent=2)
    print(f"✅ Full workflow saved to: {full_path}")
    print(f"✅ Batch workflow saved to: {batch_path}")
    print(f"   Full nodes: {len(full_workflow['nodes'])}, links: {len(full_workflow['links'])}")
    print(f"   Batch nodes: {len(batch_workflow['nodes'])}, links: {len(batch_workflow['links'])}")


if __name__ == "__main__":
    main()
