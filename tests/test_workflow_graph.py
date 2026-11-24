import json
import os

ROOT = os.path.dirname(os.path.dirname(__file__))


def check_safe_parser_graph(path):
    data = json.load(open(path, encoding="utf-8"))
    nodes = {node["id"]: node for node in data["nodes"]}
    links = data["links"]
    assert len(nodes) == len(data["nodes"])
    assert data["last_node_id"] == max(nodes)
    assert data["last_link_id"] == max(link[0] for link in links)
    for link_id, src, src_slot, dst, dst_slot, _link_type in links:
        assert src in nodes and dst in nodes, (link_id, src, dst)
        assert src_slot < len(nodes[src].get("outputs", [])), (link_id, src, src_slot)
        assert dst_slot < len(nodes[dst].get("inputs", [])), (link_id, dst, dst_slot)

    types = {node["type"] for node in nodes.values()}
    assert types == {"AFE_ScriptFullParser", "show_text_party"}
    parser = next(node for node in nodes.values()
                  if node["type"] == "AFE_ScriptFullParser")
    named = parser.get("widgets_values_named", {})
    values = parser.get("widgets_values", [])
    batch_end = named.get("batch_end_shot")
    if batch_end is None and len(values) > 9:
        batch_end = values[9]
    assert batch_end == 4


if __name__ == "__main__":
    check_safe_parser_graph(os.path.join(ROOT, "workflow_templates", "afe_full_pipeline.json"))
    check_safe_parser_graph(os.path.join(ROOT, "workflow_templates", "afe_script_pipeline.json"))
    print("PASS workflow graph")
