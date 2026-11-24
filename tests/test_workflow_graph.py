import json
import os

ROOT = os.path.dirname(os.path.dirname(__file__))


def check(path):
    data = json.load(open(path, encoding="utf-8"))
    nodes = {n["id"]: n for n in data["nodes"]}
    links = data["links"]
    assert len(nodes) == len(data["nodes"])
    assert data["last_node_id"] == max(nodes)
    assert data["last_link_id"] == max(x[0] for x in links)
    for lid, src, src_slot, dst, dst_slot, typ in links:
        assert src in nodes and dst in nodes, (lid, src, dst)
        assert src_slot < len(nodes[src].get("outputs", [])), (lid, src, src_slot)
        assert dst_slot < len(nodes[dst].get("inputs", [])), (lid, dst, dst_slot)
    types = {node["type"] for node in nodes.values()}
    assert types == {"AFE_ScriptFullParser", "show_text_party"}
    assert any(node["type"] == "show_text_party" for node in nodes.values())
    parser = next(node for node in nodes.values() if node["type"] == "AFE_ScriptFullParser")
    assert parser["outputs"][7]["links"]
    named = parser.get("widgets_values_named", {})
    batch_end = named.get("batch_end_shot")
    if batch_end is None:
        batch_end = parser.get("widgets_values", [None] * 10)[9]
    assert batch_end == 4


if __name__ == "__main__":
    check(os.path.join(ROOT, "workflow_templates", "afe_full_pipeline.json"))
    check(os.path.join(ROOT, "workflow_templates", "afe_script_pipeline.json"))
    print("PASS workflow graph")
