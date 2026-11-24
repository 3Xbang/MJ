import json
import os

ROOT = os.path.dirname(os.path.dirname(__file__))


def check(path, expect_full):
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
    parser = next(node for node in nodes.values() if node["type"] == "AFE_ScriptFullParser")
    named = parser.get("widgets_values_named", {})
    values = parser.get("widgets_values", [])
    batch_end = named.get("batch_end_shot")
    if batch_end is None and len(values) > 9:
        batch_end = values[9]
    if not expect_full:
        assert batch_end == 4
    if expect_full:
        required = {
            "AFE_SceneAnalyzer", "AFE_PropsAnalyzer", "AFE_CastAnalyzer",
            "AFE_CharacterTracker", "AFE_ShotPromptBuilder", "AFE_ShotList",
            "AFE_SceneImageGenerator", "AFE_PropsImageGenerator",
            "AFE_CastRefGenerator", "AFE_ShotKeyframeGenerator",
            "AFE_WanShotRenderer", "AFE_MovieAssembler", "show_text_party",
        }
        assert required <= types
        assert any(n["type"] == "AFE_ShotKeyframeGenerator" for n in nodes.values())
        assert any(n["type"] == "AFE_WanShotRenderer" for n in nodes.values())
        keyframe = next(n for n in nodes.values() if n["type"] == "AFE_ShotKeyframeGenerator")
        assert any(i["name"] == "props_images" and i.get("link") for i in keyframe["inputs"])
    else:
        assert types == {"AFE_ScriptFullParser", "show_text_party"}
        assert len(nodes) == 2


if __name__ == "__main__":
    check(os.path.join(ROOT, "workflow_templates", "afe_full_pipeline.json"), True)
    check(os.path.join(ROOT, "workflow_templates", "afe_script_pipeline.json"), False)
    print("PASS workflow graph")
