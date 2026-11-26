"""A card redo draws one keyframe and leaves the rest of the gallery alone."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))

from ai_film_editor_nodes.nodes.video.shot_keyframe_node import indexed_keyframe_shots, revision_clause
from ai_film_editor_nodes.webui import graphs
from ai_film_editor_nodes.webui.server import merge_kf_manifest, stage_part


SHOTS = [{"shot_id": f"shot_{n:03d}"} for n in range(1, 6)]


def test_full_step_still_honors_the_test_prefix():
    chosen = indexed_keyframe_shots(SHOTS, max_shots=2, only_listed=False)
    assert [shot["shot_id"] for _, shot in chosen] == ["shot_001", "shot_002"]
    assert [index for index, _ in chosen] == [0, 1]


def test_card_redo_keeps_a_later_shot_and_ignores_the_test_prefix():
    chosen = indexed_keyframe_shots(SHOTS, max_shots=2, only_listed=True, only_shot="shot_005")
    assert chosen == [(4, SHOTS[4])]


def test_card_redo_does_not_draw_shots_that_were_redone_earlier():
    chosen = indexed_keyframe_shots(SHOTS, max_shots=0, only_listed=True, only_shot="shot_003")
    assert [shot["shot_id"] for _, shot in chosen] == ["shot_003"]


def test_card_redo_without_a_shot_is_rejected():
    try:
        indexed_keyframe_shots(SHOTS, 0, True, "")
    except ValueError as exc:
        assert "没有指定" in str(exc)
    else:
        raise AssertionError("empty redo must fail")


def test_unknown_shot_is_rejected():
    try:
        indexed_keyframe_shots(SHOTS, 0, True, "shot_099")
    except ValueError as exc:
        assert "shot_099" in str(exc)
    else:
        raise AssertionError("missing shot must fail")


def test_kf_graph_names_only_the_clicked_shot():
    prompt, labels = graphs.build_prompt(
        3, "afe_project", {"kf_redo": "shot_002:1, shot_005:2", "test_mode": True, "test_shots": 2},
        "out", "kf", only_shot="shot_005",
    )
    node = prompt["11"]["inputs"]
    assert node["only_listed"] is True
    assert node["only_shot"] == "shot_005"
    assert node["max_shots"] == 0
    assert node["redo_shots"] == "shot_002:1, shot_005:2"
    assert labels["11"] == "只重画这一张首帧"


def test_full_keyframe_step_is_unchanged():
    prompt, labels = graphs.build_prompt(
        3, "afe_project", {"test_mode": True, "test_shots": 2}, "out",
    )
    node = prompt["11"]["inputs"]
    assert node["only_listed"] is False
    assert node["only_shot"] == ""
    assert node["max_shots"] == 2
    assert labels["11"] == "绘制每个分镜的首帧"


def test_part_kf_cannot_leak_into_another_step():
    assert stage_part(3, "kf") == "kf"
    assert stage_part(2, "kf") == "all"
    assert stage_part(4, "kf") == "all"
    assert stage_part(2, "cast") == "cast"
    assert stage_part(3, "cast") == "all"
    assert stage_part(2, "scene") == "scene"
    assert stage_part(3, "scene") == "all"


def test_revision_text_is_kept_and_a_blank_note_adds_nothing():
    clause = revision_clause("  茶杯换成白瓷杯，人物看向镜头  ")
    assert "茶杯换成白瓷杯，人物看向镜头" in clause
    assert "Director revision" in clause
    assert revision_clause("   ") == ""


def test_kf_graph_carries_the_revision_for_every_listed_shot():
    prompt, _labels = graphs.build_prompt(
        3, "afe_project", {"kf_notes": "shot_002: 茶杯换成白瓷杯"}, "out",
    )
    assert prompt["11"]["inputs"]["edit_notes"] == "shot_002: 茶杯换成白瓷杯"


def test_one_card_replaces_only_its_manifest_row():
    old = [
        {"shot": "shot_002", "variant": 1, "file": "keyframes/shot_002_old.png"},
        {"shot": "shot_005", "variant": 1, "file": "keyframes/shot_005_old.png"},
    ]
    new = [{"shot": "shot_005", "variant": 1, "file": "keyframes/shot_005_new.png"}]
    merged = merge_kf_manifest(old, new)
    by_shot = {item["shot"]: item["file"] for item in merged}
    assert by_shot == {
        "shot_002": "keyframes/shot_002_old.png",
        "shot_005": "keyframes/shot_005_new.png",
    }


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
