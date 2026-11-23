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
    assert len(sm) == 3, [s["sample_header"] for s in sm]
    assert "片头" in sm[0]["sample_header"]
    assert "佛珠" in sm[0]["source_text"] and "超市" not in sm[0]["source_text"]
    assert "小宇" in sm[1]["source_text"] and "小舟" in sm[1]["source_text"]     # A + A-continued merged
    assert "胖叔喝茶" in sm[2]["source_text"]


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


def test_cjk_detection_for_english_rewrite():
    assert m._mostly_cjk("在昏暗的超市内部，一束强烈的顶光")
    assert not m._mostly_cjk("A man stands in a dim supermarket")
    assert not m._mostly_cjk("")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print("PASS", f.__name__)
    print(f"{len(fns)}/{len(fns)} passed")
