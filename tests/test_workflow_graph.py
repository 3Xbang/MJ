"""Workflow template invariants. Run with: python tests/test_workflow_graph.py"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(__file__))


def _load(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    nodes = {node["id"]: node for node in data["nodes"]}
    links = data["links"]
    assert len(nodes) == len(data["nodes"])
    assert data["last_node_id"] == max(nodes)
    assert data["last_link_id"] == max(link[0] for link in links)
    assert len({link[0] for link in links}) == len(links)
    for link_id, src, src_slot, dst, dst_slot, _link_type in links:
        assert src in nodes and dst in nodes, (link_id, src, dst)
        assert src_slot < len(nodes[src].get("outputs", [])), (link_id, src, src_slot)
        assert dst_slot < len(nodes[dst].get("inputs", [])), (link_id, dst, dst_slot)
    return data, nodes, links


def check_full_graph(path):
    data, nodes, links = _load(path)
    types = {node["type"] for node in nodes.values()}
    for required in {
        "AFE_AnalysisLoader", "AFE_SceneImageGenerator", "AFE_PropsImageGenerator",
        "AFE_ShotKeyframeGenerator", "AFE_WanShotRenderer", "AFE_MovieAssembler",
        "show_text_party",
    }:
        assert required in types, required
    parser_id = next(node_id for node_id, node in nodes.items()
                     if node["type"] == "AFE_ScriptFullParser")
    loader_id = next(node_id for node_id, node in nodes.items()
                     if node["type"] == "AFE_AnalysisLoader")
    assert any(link[1] == loader_id and link[2] in (0, 1) for link in links)
    assert not any(link[1] == parser_id and link[2] in (0, 1) for link in links)
    keyframe = next(node for node in nodes.values() if node["type"] == "AFE_ShotKeyframeGenerator")
    assert any(item["name"] == "props_images" and item.get("link") for item in keyframe["inputs"])
    assert any(item["name"] == "props_manifest" and item.get("link") for item in keyframe["inputs"])
    assert any(node["type"] == "show_text_party" for node in nodes.values())


def check_batch_graph(path):
    _data, nodes, links = _load(path)
    assert {node["type"] for node in nodes.values()} == {"AFE_ScriptFullParser", "show_text_party"}
    parser = next(node for node in nodes.values() if node["type"] == "AFE_ScriptFullParser")
    show = next(node_id for node_id, node in nodes.items() if node["type"] == "show_text_party")
    assert any(link[1] == parser["id"] and link[2] == 7 and link[3] == show and link[4] == 0
               for link in links), "batch report must reach show_text_party"
    values = parser.get("widgets_values", [])
    assert values[9] == 4


if __name__ == "__main__":
    check_full_graph(os.path.join(ROOT, "workflow_templates", "afe_full_pipeline.json"))
    check_batch_graph(os.path.join(ROOT, "workflow_templates", "afe_script_pipeline.json"))
    print("PASS workflow graph")
