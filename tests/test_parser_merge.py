"""CPU parser merge and camera provenance regressions."""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))
spec = importlib.util.spec_from_file_location(
    "parser_mod", os.path.join(ROOT, "nodes", "director", "script_full_parser_node.py"))
parser_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser_mod)

from ai_film_editor_nodes.nodes.video.shot_prompt_contract import build_keyframe_prompt, build_video_prompt


class StubParser(parser_mod.AFE_ScriptFullParser):
    def __init__(self, phase1_shot, phase2):
        self.phase1_shot = phase1_shot
        self.phase2 = phase2

    def _call_llm(self, system_prompt, user_prompt, model_path, max_new_tokens=2048):
        if system_prompt == parser_mod.PHASE1_SYSTEM:
            return json.dumps({"cast": [{"name": "Mina", "appearance_en": "short hair"}],
                               "shots": [self.phase1_shot]})
        if system_prompt == parser_mod.SCENE_ENV_SYSTEM:
            return json.dumps({"scene_name_en": "Quiet Workshop",
                               "environment_prompt_en": "empty workshop, steel bench, cool overhead light",
                               "subject_scope": "place_only", "people": [], "props": []})
        if system_prompt == parser_mod.PHASE2_SYSTEM:
            return json.dumps(self.phase2)
        return "Mina reaches the lever in the workshop."


def _phase1(camera_motion=None, camera_source=None):
    return {
        "shot_id": "shot_001", "scene_index": 1, "source_block_id": "block_001",
        "scene_occurrence_id": "occurrence_001", "section_type": "location_scene",
        "character_names": ["Mina"], "dialogue": "Wait for me.", "props_list": ["brass lever"],
        "costume_en": "red wool coat", "raw_description": "The camera tracks Mina as she reaches for the brass lever, her anxious smile tight and her eyelid trembling.",
        "facial_expression": "anxious smile", "micro_expression": "left eyelid trembles",
        "gaze": "toward the window", "body_language": "shoulders tense",
        "action_start": "hand approaches the lever", "action_process": "thumb rubs the label",
        "action": "reaches for the lever", "business": "thumb rubs the brass label",
        "action_end": "she pulls the lever", "prop_interactions": ["grips the brass lever"],
        "camera_motion": camera_motion, "camera_motion_source": camera_source,
        "shot_type": "medium", "camera_angle": "low_angle", "lighting": "cool LEDs",
    }


def _null_phase2(camera_motion=None):
    return {key: (camera_motion if key == "camera_motion" else
                  "script" if key == "camera_motion_source" and camera_motion else
                  ["null"] if key == "prop_interactions" else
                  "null" if key in {"shot_description", "costume_en"} else None)
            for key in (
                "camera_angle", "camera_motion", "camera_motion_source", "camera_path", "shot_type",
                "lighting_style", "location", "time_of_day", "weather", "lighting", "color_temperature",
                "action", "business", "emotion", "facial_expression", "micro_expression", "gaze",
                "body_language", "action_start", "action_process", "action_end", "prop_interactions",
                "pace", "shot_description", "costume_description", "costume_en", "director_notes")}


def _parse(phase1, phase2, screenplay=None):
    return StubParser(phase1, phase2).parse_script(
        screenplay or ("【场景一：Workshop】\nMina in a red wool coat reaches for the brass lever, anxious smile tight, "
                       "left eyelid trembling, gaze toward the window, shoulders tense; "
                       "hand approaches the lever, grips the brass lever, thumb rubs the brass label, she pulls the lever; "
                       "the camera is framed under cool LEDs."
                       ),
        target_duration_seconds=5, seconds_per_shot=5, model_path="stub") ["result"][0][0]


def test_single_character_chinese_cast_name_is_grounded_in_source():
    parser_mod._validate_cast_against_script([{"name": "李"}], "【场景】\n李走进厨房，停下。")


def test_placeholder_cast_name_is_not_a_character():
    kept = parser_mod._without_placeholder_cast([
        {"name": "小宇", "role_type": "lead"},
        {"name": "N/A"},
        {"name": "无"},
        {"name": ""},
    ])
    assert [item["name"] for item in kept] == ["小宇"]
    parser_mod._validate_cast_against_script(kept, "小宇站在打包台前。")


def test_invented_cast_name_is_still_blocked():
    try:
        parser_mod._validate_cast_against_script([{"name": "神秘法杖"}], "小宇站在打包台前。")
    except ValueError as exc:
        assert "神秘法杖" in str(exc)
    else:
        raise AssertionError("invented cast name must still fail")


def test_phase2_nulls_preserve_phase1_facts_in_both_prompts():
    shot = _parse(_phase1("tracking_shot", "script"), _null_phase2(),
                  "【场景一：Workshop】\nMina in a red wool coat reaches for the brass lever, anxious smile tight, left eyelid trembling, gaze toward the window, shoulders tense; hand approaches the lever, grips the brass lever, thumb rubs the brass label, she pulls the lever; under cool LEDs.")
    assert shot["action"] == "reaches for the lever"
    assert shot["business"] == "thumb rubs the brass label"
    # The parser's phase-1 fields remain available to the canonical renderer.
    assert shot["facial_expression"] == "anxious smile"
    assert shot["micro_expression"] == "left eyelid trembles"
    assert shot["action_start"] == "hand approaches the lever"
    assert shot["action_process"] == "thumb rubs the label"
    assert shot["action_end"] == "she pulls the lever"
    assert shot["prop_interactions"] == ["grips the brass lever"]
    assert shot["shot_description"] == shot["source_shot_text"]
    assert shot["costume_en"] == "red wool coat"
    assert shot["camera_motion"] == "tracking_shot"
    key = build_keyframe_prompt(shot)
    video = build_video_prompt(shot, speaking=True)
    for value in ("anxious smile", "left eyelid trembles", "thumb rubs", "pulls the lever", "tracking", "brass lever", "red wool coat"):
        assert value in key and value in video, value


def test_conflicting_phase2_facts_do_not_replace_phase1_source_facts():
    phase2 = _null_phase2()
    phase2.update({
        "action": "runs away from the workshop",
        "business": "throws the brass lever across the room",
        "emotion": "joyful grin",
        "facial_expression": "joyful grin",
        "micro_expression": "right eyebrow jumps",
        "location": "a city street",
        "lighting": "red neon light",
        "shot_description": "A woman runs away on a city street.",
    })
    shot = _parse(_phase1(), phase2,
                  "【场景一：Workshop】\nMina in a red wool coat reaches for the brass lever, anxious smile tight, left eyelid trembling, gaze toward the window, shoulders tense; hand approaches the lever, grips the brass lever, thumb rubs the brass label, she pulls the lever; under cool LEDs.")
    assert shot["action"] == "reaches for the lever"
    assert shot["business"] == "thumb rubs the brass label"
    assert shot["facial_expression"] == "anxious smile"
    assert shot["micro_expression"] == "left eyelid trembles"
    assert shot["location"] == "Workshop"
    assert shot["lighting"] == "cool LEDs"
    assert "city street" not in build_keyframe_prompt(shot)
    assert "city street" not in build_video_prompt(shot)

def test_phase2_failure_blocks_nominal_analysis():
    class Phase2FailureParser(StubParser):
        def _call_llm(self, system_prompt, user_prompt, model_path, max_new_tokens=2048):
            if system_prompt == parser_mod.PHASE2_SYSTEM:
                raise RuntimeError("phase2 service unavailable")
            return super()._call_llm(system_prompt, user_prompt, model_path, max_new_tokens)

    try:
        Phase2FailureParser(_phase1(), _null_phase2()).parse_script(
            "【场景一：Workshop】\nMina reaches for the brass lever.",
            target_duration_seconds=5, seconds_per_shot=5, model_path="stub")
    except ValueError as exc:
        assert "Phase 2" in str(exc) and "已阻止保存" in str(exc)
    else:
        raise AssertionError("Phase 2 failure returned a complete analysis")


def test_parser_preserves_explicit_locked_camera_cue():
    motion, source, explicit = parser_mod._camera_motion_from_phases(
        {}, {}, "Hold the camera locked off while Mina holds the brass lever.", ""
    )
    assert (motion, source, explicit) == ("static", "script", True)


def test_parser_preserves_reaction_hold_but_not_object_hold():
    reaction = parser_mod._camera_motion_from_phases(
        {}, {}, "Hold on reaction while Mina looks toward the door.", ""
    )
    assert reaction == ("static", "script", True)
    object_hold = parser_mod._camera_motion_from_phases(
        {}, {}, "Mina holds the cup while speaking.", ""
    )
    assert object_hold[0] != "static"


def test_phase2_static_for_ordinary_dialogue_is_derived_motion():
    shot = _parse(_phase1(), _null_phase2("static"))
    assert shot["camera_motion"] != "static"
    assert shot["camera_motion_source"] == "derived"


def test_missing_source_evidence_blocks_ambiguous_shot_without_sibling_fallback():
    block = "Scene: Workshop\nMina grips the red cup.\n\nBo opens the brass drawer.\n\nCia leaves the room."
    fragment, error = parser_mod._validated_source_fragment(
        block, "A person reaches toward an object.", {}
    )
    assert fragment == ""
    assert "missing verified" in error
    units = parser_mod._source_units_with_offsets(block)
    fragment, error = parser_mod._validated_source_fragment(
        block, "ignored", {"source_unit_ids": [units[0]["unit_id"]]}
    )
    assert not error and "Mina" in fragment and "Bo" not in fragment
    fragment, error = parser_mod._validated_source_fragment(
        block, "ignored", {"source_unit_ids": [units[0]["unit_id"], units[-1]["unit_id"]]}
    )
    assert fragment == "" and "not adjacent" in error


def test_phase1_coverage_rejects_truncated_or_repeated_source_blocks():
    scene_map = parser_mod._build_scene_map(
        "【场景 A：Kitchen】\nMina opens the drawer.\n"
        "【场景 B：Garden】\nBo looks up."
    )
    errors = parser_mod._phase1_source_coverage_errors([
        {"shot_id": "shot_001", "scene_index": 1, "source_block_id": "block_001",
         "source_unit_ids": ["unit_001"]},
        {"shot_id": "shot_002", "scene_index": 1, "source_block_id": "block_001",
         "source_unit_ids": ["unit_001"]},
    ], scene_map, target_count=2)
    assert any("重复覆盖" in error for error in errors), errors
    assert any("block_002" in error and "遗漏" in error for error in errors), errors


    ordered_map = parser_mod._build_scene_map(
        "【场景 A：Kitchen】\nMina opens the drawer.\n"
        "【场景 B：Garden】\nBo looks up.\n"
        "【场景 A：Kitchen】\nMina closes the drawer."
    )
    ordered_errors = parser_mod._phase1_source_coverage_errors([
        {"shot_id": "shot_001", "source_block_id": "block_001", "source_unit_ids": ["unit_001"]},
        {"shot_id": "shot_002", "source_block_id": "block_003", "source_unit_ids": ["unit_001"]},
        {"shot_id": "shot_003", "source_block_id": "block_002", "source_unit_ids": ["unit_001"]},
    ], ordered_map, target_count=3)
    assert any("顺序" in error for error in ordered_errors), ordered_errors


def test_batch_environment_analysis_keeps_full_repeated_scene_context():
    class EnvironmentContextParser(StubParser):
        def __init__(self):
            super().__init__(_phase1(), _null_phase2())
            self.environment_prompts = []

        def _call_llm(self, system_prompt, user_prompt, model_path, max_new_tokens=2048):
            if system_prompt == parser_mod.SCENE_ENV_SYSTEM:
                self.environment_prompts.append(user_prompt)
            return super()._call_llm(system_prompt, user_prompt, model_path, max_new_tokens)

    parser = EnvironmentContextParser()
    context = {
        "scene_map": [{
            "scene_index": 1,
            "scene_id": "scene_001",
            "sample_header": "INT. London supermarket - NIGHT",
            "preview": "The supermarket has 6000K fluorescent ceiling lights and wet floors.",
            "source_text": "Mina walks between the aisles.",
            "environment_source_text": (
                "INT. London supermarket - NIGHT\n"
                "The supermarket has 6000K fluorescent ceiling lights and wet floors.\n"
                "Mina walks between the aisles."
            ),
            "source_blocks": [{
                "source_block_id": "block_001",
                "scene_occurrence_id": "occurrence_002",
                "section_type": "location_scene",
                "source_text": "Mina walks between the aisles.",
                "batch_unit_ids": ["unit_001"],
            }],
        }]
    }
    parser.parse_script(
        "Mina walks between the aisles.", target_duration_seconds=5,
        seconds_per_shot=5, model_path="stub", batch_start_shot=1,
        batch_end_shot=1, batch_context_json=json.dumps(context),
    )
    assert len(parser.environment_prompts) == 1
    assert "6000K fluorescent ceiling lights" in parser.environment_prompts[0]
    assert "Mina walks between the aisles" in parser.environment_prompts[0]




def test_batch_report_marks_partial_progress_for_show_text_party():
    script = (
        "【场景一：Workshop】 "
        "Mina in a red wool coat reaches for the brass lever, anxious smile tight, "
        "left eyelid trembling, gaze toward the window, shoulders tense; hand approaches "
        "the lever, grips the brass lever, thumb rubs the brass label, she pulls the lever; "
        "under cool LEDs."
    )
    context = {
        "scene_map": parser_mod._build_scene_map(script),
        "batch_metadata": {
            "batch_index": 2,
            "total_batches": 9,
            "completed_shot_count_before": 4,
            "target_shot_count": 36,
        },
    }
    result = StubParser(_phase1(), _null_phase2()).parse_script(
        script, target_duration_seconds=180, seconds_per_shot=5, model_path="stub",
        batch_start_shot=1, batch_end_shot=1,
        batch_context_json=json.dumps(context, ensure_ascii=False),
    )
    report = result["result"][-1]
    assert "Batch 2/9 completed" in report
    assert "analysis_status=partial" in report
    assert "Overall progress: 5/36 shots completed" in report
    assert "Screenplay analysis complete" not in report

    class EnvFailureParser(StubParser):
        def _call_llm(self, system_prompt, user_prompt, model_path, max_new_tokens=2048):
            if system_prompt == parser_mod.SCENE_ENV_SYSTEM:
                raise RuntimeError("environment model unavailable")
            return super()._call_llm(system_prompt, user_prompt, model_path, max_new_tokens)

    parser = EnvFailureParser(_phase1(), _null_phase2())
    try:
        parser.parse_script("【场景一：Workshop】\nMina reaches for the brass lever.",
                            target_duration_seconds=5, seconds_per_shot=5, model_path="stub")
    except ValueError as exc:
        message = str(exc)
        assert "空场景环境分析失败" in message and "降级" in message
    else:
        raise AssertionError("environment failure silently used a generic fallback")


def test_explicit_zoom_out_is_preserved_as_pull_back():
    motion, source, explicit = parser_mod._camera_motion_from_phases(
        {}, {}, "The camera zooms out as Mina speaks.", ""
    )
    assert (motion, source, explicit) == ("slow_pull_back", "script", True)


def _context_scene_map(context_text, shot_text, sibling_shot_text=None):
    """Minimal scene map: one verified global/context-only block plus one
    ordinary shot block. ``sibling_shot_text`` is concatenated into the same
    shot block as a neighboring, non-context fragment so a test can prove it
    never becomes alias evidence."""
    shot_block_text = shot_text if not sibling_shot_text else f"{sibling_shot_text}\n{shot_text}"
    return [
        {"scene_index": 1, "scene_id": "scene_context", "source_blocks": [
            {"source_block_id": "block_context", "scene_occurrence_id": "occurrence_context",
             "section_type": "title_sequence", "source_text": context_text,
             "batch_context_only": True},
        ]},
        {"scene_index": 2, "scene_id": "scene_shot", "source_blocks": [
            {"source_block_id": "block_shot", "scene_occurrence_id": "occurrence_shot",
             "section_type": "location_scene", "source_text": shot_block_text},
        ]},
    ]


def test_verified_prop_registry_resolves_same_script_alias_without_sibling_shots():
    context_text = "- **胖叔**：纯白重磅棉T恤，粗金链，深棕色小叶紫檀佛珠。性格从容。"
    shot_text = "佛珠与金链在顶光下晃动。"
    # Only a neighboring shot states the finer measurement; it must stay
    # invisible to the registry so Phase 2 isolation guarantees still hold.
    sibling_text = "手腕戴着2厘米宽的实心粗金链，一颗佛珠停在指尖。"
    scene_map = _context_scene_map(context_text, shot_text, sibling_text)
    registry = parser_mod._build_verified_prop_registry(scene_map)

    assert parser_mod._prop_fact_is_supported("深棕色小叶紫檀佛珠", shot_text, registry)
    assert parser_mod._prop_fact_is_supported("粗金链", shot_text, registry)
    # A sibling shot's measurement names the same verified prop. Keep the
    # shot moving and store only the context declaration, not the measurement.
    assert parser_mod._prop_fact_is_supported("2厘米宽的实心粗金链", shot_text, registry)
    assert parser_mod._canonicalize_prop_value("2厘米宽的实心粗金链", shot_text, registry) == "粗金链"
    assert not parser_mod._prop_fact_is_supported("神秘法杖", shot_text, registry)
    assert not parser_mod._prop_fact_is_supported("神秘法杖和金链", shot_text, registry)

    assert parser_mod._canonicalize_prop_value("佛珠", shot_text, registry) == "深棕色小叶紫檀佛珠"
    assert parser_mod._canonicalize_prop_value("金链", shot_text, registry) == "粗金链"
    # A value with no verified alias in this shot's own fragment is untouched.
    assert parser_mod._canonicalize_prop_value("神秘法杖", shot_text, registry) == "神秘法杖"


def test_verified_prop_registry_generalizes_to_an_unrelated_screenplays_props():
    # No fixed noun vocabulary: any customer screenplay's own short/detailed
    # prop pair must resolve the same way without code changes.
    context_text = "- **老陈**：磨损的棕色皮革公文包，一把锈迹斑斑的黄铜怀表。"
    shot_text = "老陈打开公文包，怀表从里面滑出来。"
    scene_map = _context_scene_map(context_text, shot_text)
    registry = parser_mod._build_verified_prop_registry(scene_map)

    assert parser_mod._prop_fact_is_supported("磨损的棕色皮革公文包", shot_text, registry)
    assert parser_mod._prop_fact_is_supported("一把锈迹斑斑的黄铜怀表", shot_text, registry)
    assert not parser_mod._prop_fact_is_supported("祖传金怀表", shot_text, registry)


def test_prop_interaction_sentence_is_canonicalized_around_its_alias():
    context_text = "道具设定：深棕色小叶紫檀佛珠。"
    shot_text = "他用右手捏住佛珠，缓缓转动。"
    scene_map = _context_scene_map(context_text, shot_text)
    registry = parser_mod._build_verified_prop_registry(scene_map)

    assert parser_mod._prop_fact_is_supported("右手捏住深棕色小叶紫檀佛珠", shot_text, registry)
    assert parser_mod._canonicalize_prop_value(
        "右手捏住深棕色小叶紫檀佛珠", shot_text, registry
    ) == "右手捏住深棕色小叶紫檀佛珠"


def test_phase1_props_list_accepts_verified_alias_and_blocks_hallucinated_prop():
    context_text = "- **胖叔**：粗金链，深棕色小叶紫檀佛珠。"
    shot_text = "画面事实：佛珠与金链在顶光下晃动。"
    scene_map = _context_scene_map(context_text, shot_text)
    registry = parser_mod._build_verified_prop_registry(scene_map)

    accepted = parser_mod._phase1_fact_validation_errors(
        {"props_list": ["深棕色小叶紫檀佛珠", "粗金链"]}, shot_text, shot_text, registry
    )
    assert accepted == []

    blocked = parser_mod._phase1_fact_validation_errors(
        {"props_list": ["深棕色小叶紫檀佛珠", "神秘法杖"]}, shot_text, shot_text, registry
    )
    assert any("神秘法杖" in error for error in blocked)

    unsupported_action = parser_mod._phase1_fact_validation_errors(
        {"action": "他突然飞起来"}, shot_text, shot_text, registry
    )
    assert unsupported_action


def test_chinese_none_is_not_a_screenplay_fact():
    source = "胖叔举起玻璃杯，茶水轻轻晃动。"
    assert parser_mod._clean_semantic("无") is None
    assert parser_mod._clean_semantic("无。") is None
    assert parser_mod._clean_semantic("无人物") == "无人物"
    assert not parser_mod._phase1_fact_validation_errors(
        {"body_language": "无", "camera_path": "无。", "action": "胖叔举起玻璃杯"},
        source, source,
    )


def test_joined_shot_clauses_and_camera_restatement_are_grounded():
    source = (
        "画面事实：胖叔戴着墨镜的侧脸，墨镜镜片里反射出伦敦街景。\n"
        "动作开始：胖叔保持侧脸不动。\n"
        "动作过程：他缓慢转动眼睛，墨镜反光发生变化。\n"
        "运镜：半圆弧绕拍，从侧脸转到三分之二正面。\n"
    )
    assert parser_mod._fact_is_supported("保持侧脸不动，缓慢转动眼睛", source)
    assert parser_mod._camera_path_is_supported("半圆弧路径", source)
    assert parser_mod._camera_path_is_supported("半圆弧路径，从侧脸转到三分之二正面", source)
    assert not parser_mod._phase1_fact_validation_errors(
        {"body_language": "保持侧脸不动，缓慢转动眼睛", "camera_path": "半圆弧路径"},
        source, source,
    )
    blocked = parser_mod._phase1_fact_validation_errors(
        {"body_language": "突然跳起来挥剑", "camera_path": "穿过爆炸的墙",
         "action": "他抽出神秘法杖"},
        source, source,
    )
    assert any("body_language" in error for error in blocked)
    assert any("camera_path" in error for error in blocked)
    assert any("action" in error for error in blocked)
    assert not parser_mod._fact_is_supported("Mina runs away", "Mina reaches for the brass lever and smiles.")


def test_same_sentence_restatement_is_kept_and_invented_state_is_not():
    source = (
        "画面事实：空的超市外卖厨房，打包台、货架、热敏打印机、牛皮纸袋和落地窗全部可见。\n"
        "动作：热敏打印机吐出一条带黑色条形码的小票。\n"
        "运镜：从窗户缓慢向打包台推近。\n"
    )
    assert parser_mod._fact_is_supported("小票完全吐出", source)
    assert parser_mod._fact_is_supported("打印机吐出小票", source)
    assert not parser_mod._fact_is_supported("热敏打印机静止", source)
    assert not parser_mod._fact_is_supported("突然跳起来挥剑", source)
    assert not parser_mod._fact_is_supported("神秘法杖", source)
    assert not parser_mod._fact_is_supported(
        "Mina runs away", "Mina reaches for the brass lever and smiles."
    )


def test_rule_derived_directions_are_kept_with_provenance():
    source = "Mina reaches for the lever."
    assert not parser_mod._fact_validation_errors(
        {"shot_type": "low angle", "camera_angle": "low angle", "pace": "slow",
         "lighting_style": "dramatic", "director_notes": "hold the reaction"},
        source, source, "Phase 2"
    )


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
