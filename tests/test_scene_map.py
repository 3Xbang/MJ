"""Regression tests for script scene detection (no GPU needed).  python tests/test_scene_map.py"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
spec = importlib.util.spec_from_file_location(
    "parser_mod", os.path.join(os.path.dirname(HERE), "nodes", "director", "script_full_parser_node.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def names(text):
    return [m._header_to_scene_name(s["sample_header"]) for s in m._build_scene_map(text)]


def test_title_sequence_before_first_scene_is_its_own_scene():
    script = ("电影剧本：测试\n视觉风格：3D\n"
              "【片头：悬念与定调】\n[黑屏]\n黑暗中一束顶光照亮拨弄佛珠的手。\n"
              "【场景 A：伦敦社区超市 - 下午】\n[内景]\n小宇站在台前。\n"
              "【场景 B：泰国海边别墅 - 白天】\n[外景]\n胖叔喝茶。\n"
              "【场景 A：伦敦社区超市 - 连续】\n小舟走来。")
    sm = m._build_scene_map(script)
    assert len(sm) == 4, [s["sample_header"] for s in sm]
    assert "片头" in sm[0]["sample_header"]
    assert "佛珠" in sm[1]["source_text"] and "超市" not in sm[1]["source_text"]
    assert "小宇" in sm[2]["source_text"] and "小舟" in sm[2]["source_text"]     # A + A-continued merged
    assert "胖叔喝茶" in sm[3]["source_text"]


def test_prologue_and_epilogue_words():
    assert len(names("【序幕】\n夜。\n【场景一：街】\n人。\n【尾声】\n字幕。")) == 3
    assert len(names("【Prologue】\nNight.\nINT. KITCHEN - DAY\nBob.\n")) == 2


def test_existing_formats_unchanged():
    assert len(names("【场景 A：超市】\n甲。\n【场景 B：海边】\n乙。\n【场景 A：超市 - 连续】\n甲。")) == 2
    assert len(names("INT. KITCHEN - DAY\nBob.\nEXT. GARDEN - DAY\nAnn.")) == 2
    assert len(names("第一场：办公室\n开会。\n第二场：走廊\n对话。")) == 2
    assert names("他走进房间。") == ["Unnamed Location"]


def test_a_word_inside_a_sentence_is_not_a_header():
    assert len(names("【场景A：家】\n结尾的时候他笑了，开场很安静。\n【场景B：路】\n走。")) == 2


def test_line_anchored_and_markdown_scene_headings_preserve_locations():
    sm = m._build_scene_map(
        "### Scene A - Harbor\nA boat waits.\n"
        "SCENE 1\nA bell rings.\n"
        "场景 2 - Warehouse\nA door closes.\n")
    assert len(sm) == 3, [scene["sample_header"] for scene in sm]
    assert all(scene["section_type"] == "location_scene" for scene in sm)
    assert "Harbor" in names("### Scene A - Harbor\nA boat waits.")[0]


def test_multi_location_montage_gets_independent_source_blocks():
    sm = m._build_scene_map(
        "[QUICK FLASH]\n"
        "LOCATION: Harbor - NIGHT\nA wet crate.\n"
        "LOCATION: Rooftop - NIGHT\nA blinking sign.\n")
    assert len(sm) == 2, [scene["sample_header"] for scene in sm]
    assert all(scene["section_type"] == "montage" for scene in sm)
    assert "wet crate" in sm[0]["source_text"] and "blinking sign" not in sm[0]["source_text"]
    assert "blinking sign" in sm[1]["source_text"]


def test_semantic_cues_are_independent_blocks_and_keep_source_order():
    script = "【片头：定调】\\n[黑屏]\\nA hand turns a bead.\\n[快速闪切]\\nthree rapid inserts.\\n【场景 A：Workshop - Day】\\nA worker looks up.\\n【场景 B：Garden - Day】\\nA bird calls.\\n【场景 A：Workshop - Continuous】\\nThe worker moves.\\n[淡出]\\n"
    sm = m._build_scene_map(script)
    kinds = [s["section_type"] for s in sm]
    assert "transition" in kinds and "montage" in kinds, kinds
    block_ids = [b["source_block_id"] for s in sm for b in s["source_blocks"]]
    assert sorted(block_ids) == [
        f"block_{i:03d}" for i in range(1, len(block_ids) + 1)
    ]
    locations = [s for s in sm if s["section_type"] == "location_scene"]
    assert len(locations) == 2
    assert len(locations[0]["source_blocks"]) == 2


def test_source_block_text_is_not_truncated():
    body = "detail " * 700
    sm = m._build_scene_map("【场景 A：Room】\\n" + body)
    assert len(sm[0]["source_text"]) > 2500


def test_generic_screenplay_cues_are_semantic_blocks():
    script = ("TITLE SEQUENCE\nA title card appears.\n"
              "MONTAGE\nThree rapid inserts.\n"
              "INT. KITCHEN - DAY\nA cook turns.\n"
              "CUT TO:\nEXT. GARDEN - DAY\nA bird calls.\n"
              "FADE OUT\n")
    sm = m._build_scene_map(script)
    kinds = [scene["section_type"] for scene in sm]
    assert kinds[:2] == ["title_sequence", "montage"], kinds
    assert kinds.count("location_scene") == 2, kinds
    assert "transition" in kinds, kinds


def test_duplicate_verbatim_source_text_is_blocked():
    source = "She turns.\nShe turns."
    fragment, error = m._validated_source_fragment(
        source, "She turns.", {"source_shot_text": "She turns."})
    assert fragment == ""
    assert "multiple source spans" in error


def test_unbracketed_chinese_cues_and_alternating_locations_keep_order():
    script = ("片头\n标题卡出现。\n"
              "【场景 A：厨房】\n甲端起杯子。\n"
              "快速闪切\n雨夜街道。\n"
              "【场景 B：花园】\n乙抬头。\n"
              "【场景 A：厨房】\n甲放下杯子。\n"
              "尾声\n画面淡出。\n")
    sm = m._build_scene_map(script)
    assert [scene["section_type"] for scene in sm][:3] == [
        "title_sequence", "location_scene", "montage"
    ]
    assert any(scene["section_type"] == "epilogue" for scene in sm)
    locations = [scene for scene in sm if scene["section_type"] == "location_scene"]
    assert len(locations) == 2
    assert len(locations[0]["source_blocks"]) == 2
    ordered_blocks = [block for scene in sm for block in scene["source_blocks"]]
    assert sorted(block["source_block_id"] for block in ordered_blocks) == [
        f"block_{i:03d}" for i in range(1, len(ordered_blocks) + 1)
    ]
    assert [block["source_block_id"] for block in locations[0]["source_blocks"]] == [
        "block_002", "block_005"
    ]
    assert [block["source_block_id"] for block in locations[1]["source_blocks"]] == ["block_004"]
    assert "快速闪切" in next(scene for scene in sm if scene["section_type"] == "montage")["sample_header"]


def test_source_offsets_must_match_verbatim_evidence_or_unit_boundaries():
    source = "She turns.\nShe sits."
    fragment, error = m._validated_source_fragment(
        source, "", {"source_start": 3, "source_end": 12, "source_shot_text": "She turns."}
    )
    assert fragment == ""
    assert "do not match" in error

    fragment, error = m._validated_source_fragment(
        source, "", {"source_start": 1, "source_end": 12}
    )
    assert fragment == ""
    assert "boundaries" in error

    fragment, error = m._validated_source_fragment(
        source, "", {"source_start": 0, "source_end": 10}
    )
    assert fragment == "She turns."
    assert error == ""


def test_ascii_bracketed_title_sections_are_separate_blocks():
    script = ("[Title]\nA title card appears.\n"
              "[Prologue]\nA hand turns a bead.\n"
              "INT. HALL - DAY\nA door opens.\n"
              "[Epilogue]\nThe image fades out.\n")
    sm = m._build_scene_map(script)
    assert [scene["section_type"] for scene in sm] == [
        "title_sequence", "prologue", "location_scene", "epilogue"
    ], [scene["sample_header"] for scene in sm]
    assert "title card" in sm[0]["source_text"]
    assert "door opens" in sm[2]["source_text"]


def test_ascii_bracketed_title_sequence_does_not_swallow_location():
    sm = m._build_scene_map("[TITLE SEQUENCE]\nLogo.\n[场景 A：Harbor]\nA boat waits.")
    assert len(sm) == 2
    assert sm[0]["section_type"] == "title_sequence"
    assert sm[1]["section_type"] == "location_scene"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print("PASS", f.__name__)
    print(f"{len(fns)}/{len(fns)} passed")
