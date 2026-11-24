import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
spec = importlib.util.spec_from_file_location(
    "parser_mod", os.path.join(ROOT, "nodes", "director", "script_full_parser_node.py"))
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


def test_supplied_36_shot_script_keeps_each_heading_and_body_together():
    path = os.path.join(ROOT, "test_scripts", "san_yan_liang_yu_ep01_fidelity_test.md")
    with open(path, encoding="utf-8") as handle:
        script = handle.read()
    scene_map = parser._build_scene_map(script)
    units = [
        unit
        for scene, block in parser._ordered_scene_blocks(scene_map)
        for unit in parser._source_units_with_offsets(block.get("source_text", ""))
        if unit.get("is_explicit_shot")
    ]
    assert len(units) == 36
    assert [unit["shot_number"] for unit in units] == list(range(1, 37))
    assert all(unit["text"].startswith("### 镜头") for unit in units)
    assert "右手拇指捏住第一颗佛珠" in units[0]["text"]
    assert "右手拇指捏住第一颗佛珠" not in units[1]["text"]


def test_explicit_shot_batches_follow_heading_order_not_sentence_ratios():
    script = (
        "### 场景A：厨房\n环境元数据。\n\n"
        "### 镜头001（5秒）\n动作开始：拿杯子。\n动作结束：停住。\n\n"
        "### 镜头002（5秒）\n表情：惊讶。\n动作开始：抬头。\n\n"
        "### 镜头003（5秒）\n对白：继续。\n动作结束：转身。\n"
    )
    scene_map = parser._build_scene_map(script)
    first = parser._select_batch_scene_map(scene_map, 3, 1, 1)
    second = parser._select_batch_scene_map(scene_map, 3, 2, 2)
    first_text = first[0]["source_blocks"][0]["prompt_source_text"]
    second_text = second[0]["source_blocks"][0]["prompt_source_text"]
    assert "镜头001" in first_text and "镜头002" not in first_text
    assert "动作结束：停住" in first_text
    assert "镜头002" in second_text and "镜头001" not in second_text
    assert "表情：惊讶" in second_text
