"""Static workflow invariants. Run with: python tests/test_workflow_graph.py"""
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
    kf = next(n for n in data["nodes"] if n["type"] == "AFE_ShotKeyframeGenerator")
    assert any(i["name"] == "props_images" and i.get("link") for i in kf["inputs"])
    assert any(n["type"] == "show_text_party" for n in data["nodes"])


if __name__ == "__main__":
    check(os.path.join(ROOT, "workflow_templates", "afe_full_pipeline.json"))
    print("PASS workflow graph")
