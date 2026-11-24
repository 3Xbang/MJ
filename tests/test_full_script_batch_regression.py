"""CPU regression for the complete screenplay parser/session publish path."""
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))


def _load_module(name, path):
    module_spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


# Loading the repository package imports every optional ComfyUI node. Keep this
# regression CPU-only by exposing only the modules needed by the parser/session
# and WebUI validation path.
for package_name, package_path in (
    ("ai_film_editor_nodes", ROOT),
    ("ai_film_editor_nodes.lib", os.path.join(ROOT, "lib")),
    ("ai_film_editor_nodes.lib.utils", os.path.join(ROOT, "lib", "utils")),
    ("ai_film_editor_nodes.nodes", os.path.join(ROOT, "nodes")),
    ("ai_film_editor_nodes.nodes.director", os.path.join(ROOT, "nodes", "director")),
    ("ai_film_editor_nodes.nodes.video", os.path.join(ROOT, "nodes", "video")),
    ("ai_film_editor_nodes.webui", os.path.join(ROOT, "webui")),
):
    package = type(sys)(package_name)
    package.__path__ = [package_path]
    sys.modules[package_name] = package

_load_module("ai_film_editor_nodes.lib.utils.logger", os.path.join(ROOT, "lib", "utils", "logger.py"))
_load_module(
    "ai_film_editor_nodes.nodes.video.shot_prompt_contract",
    os.path.join(ROOT, "nodes", "video", "shot_prompt_contract.py"),
)
_load_module(
    "ai_film_editor_nodes.nodes.director.screenplay_source_units",
    os.path.join(ROOT, "nodes", "director", "screenplay_source_units.py"),
)
parser_mod = _load_module(
    "ai_film_editor_nodes.nodes.director.script_full_parser_node",
    os.path.join(ROOT, "nodes", "director", "script_full_parser_node.py"),
)
AnalysisSessionStore = _load_module(
    "ai_film_editor_nodes.nodes.director.script_analysis_session",
    os.path.join(ROOT, "nodes", "director", "script_analysis_session.py"),
).AnalysisSessionStore
_load_module("ai_film_editor_nodes.webui.graphs", os.path.join(ROOT, "webui", "graphs.py"))
server_mod = _load_module(
    "ai_film_editor_nodes.webui.server", os.path.join(ROOT, "webui", "server.py")
)
Api = server_mod.Api
_validate_analysis_payload = server_mod._validate_analysis_payload

SCRIPT_PATH = os.path.join(ROOT, "test_scripts", "san_yan_liang_yu_ep01_fidelity_test.md")
SECONDS_PER_SHOT = 5
BATCH_SIZE = 4


class CpuBatchParser(parser_mod.AFE_ScriptFullParser):
    """Return source-grounded structures without loading a model or GPU."""

    def __init__(self):
        self.phase2_prompts = []
        self.phase1_prompts = []

    def _call_llm(self, system_prompt, user_prompt, model_path, max_new_tokens=2048):
        if system_prompt == parser_mod.PHASE1_SYSTEM:
            self.phase1_prompts.append(user_prompt)
            marker = "Screenplay source for this batch:\n"
            source = user_prompt.split(marker, 1)[1]
            units = [
                unit for unit in parser_mod._source_units_with_offsets(source)
                if unit.get("is_explicit_shot")
            ]
            # Deliberately return no source metadata. FEAT-001 must bind each
            # item to the persisted batch unit by screenplay order.
            return json.dumps({
                "cast": [],
                "shots": [
                    {"shot_id": "model-local-id", "scene_index": 999,
                     "source_block_id": "model-invented-block",
                     "raw_description": unit["text"]}
                    for unit in units
                ],
            }, ensure_ascii=False)
        if system_prompt == parser_mod.SCENE_ENV_SYSTEM:
            return json.dumps({
                "scene_name_en": "Verified screenplay location",
                "environment_prompt_en": "screenplay location, empty set",
                "subject_scope": "place_only",
                "people": [], "props": [],
            })
        if system_prompt == parser_mod.PHASE2_SYSTEM:
            self.phase2_prompts.append(user_prompt)
            return json.dumps({"camera_motion": None, "action": None})
        if system_prompt == parser_mod.TO_ENGLISH_SYSTEM:
            return "verified source fragment"
        raise AssertionError(f"unexpected LLM phase: {system_prompt}")


def _ordered_units(scene_map):
    result = []
    for scene, block in parser_mod._ordered_scene_blocks(scene_map):
        for unit in parser_mod._source_units_with_offsets(block.get("source_text", "")):
            if unit.get("is_explicit_shot"):
                result.append((scene, block, unit))
    return result


def _batch_context(session, batch):
    """Build the same bounded scene context as the WebUI analysis route."""
    source_ranges = {
        str(item.get("source_block_id")): set(item.get("unit_ids", []))
        for item in batch.get("source_unit_ranges", [])
    }
    context_only_blocks = {
        str(item.get("source_block_id"))
        for item in session.get("source_manifest", [])
        if item.get("context_only")
    }
    scene_subset = []
    for scene in session.get("scene_map", []):
        environment_source_text = "\n".join(
            str(source_block.get("source_text", ""))
            for _, source_block in parser_mod._ordered_scene_blocks([scene])
            if str(source_block.get("source_text", "")).strip()
        ) or str(scene.get("source_text", ""))
        blocks = []
        for source_block in scene.get("source_blocks", []):
            block_id = str(source_block.get("source_block_id"))
            if block_id not in source_ranges and block_id not in context_only_blocks:
                continue
            block = dict(source_block)
            if block_id in context_only_blocks:
                block["batch_context_only"] = True
                units = parser_mod._source_units_with_offsets(block.get("source_text", ""))
                block["prompt_source_text"] = "\n".join(unit["text"] for unit in units)
                block["batch_unit_ids"] = []
            else:
                source_range = next(
                    (item for item in batch.get("source_unit_ranges", [])
                     if str(item.get("source_block_id")) == block_id), {}
                )
                block["batch_unit_ids"] = sorted(source_ranges[block_id])
                block["batch_units"] = [
                    dict(unit) for unit in source_range.get("units", [])
                    if str(unit.get("unit_id")) in source_ranges[block_id]
                ]
                units = [dict(unit) for unit in source_range.get("units", [])]
                if not units:
                    units = parser_mod._source_units_with_offsets(block.get("source_text", ""))
                block["prompt_source_text"] = "\n".join(
                    [unit["text"] for unit in units if unit.get("is_context")]
                    + [unit["text"] for unit in units
                       if unit["unit_id"] in source_ranges[block_id]]
                )
            blocks.append(block)
        if blocks:
            item = dict(scene)
            item["source_blocks"] = blocks
            item["source_text"] = "\n".join(
                block.get("prompt_source_text", "") for block in blocks
            )
            item["environment_source_text"] = environment_source_text
            scene_subset.append(item)

    ordered_blocks = parser_mod._ordered_scene_blocks(scene_subset)
    scene_order = {}
    for position, (scene, _block) in enumerate(ordered_blocks):
        scene_order.setdefault(id(scene), position)
    for scene in scene_subset:
        scene["source_blocks"] = sorted(
            scene.get("source_blocks", []),
            key=lambda block: (int(block.get("source_order", 10**9)),
                               str(block.get("source_block_id", ""))),
        )
        scene["source_text"] = "\n".join(
            block.get("prompt_source_text", block.get("source_text", ""))
            for block in scene["source_blocks"]
        )
    scene_subset.sort(key=lambda scene: scene_order.get(id(scene), 10**9))
    completed_before = sum(
        int(item.get("shot_end", 0)) - int(item.get("shot_start", 0)) + 1
        for item in session.get("batches", [])
        if item.get("status") == "completed"
    )
    return json.dumps({
        "scene_map": scene_subset,
        "batch_metadata": {
            "batch_index": int(batch["batch_index"]),
            "total_batches": int(session.get("total_batches", 0)),
            "completed_shot_count_before": completed_before,
            "target_shot_count": int(session.get("target_shot_count", 0)),
        },
    }, ensure_ascii=False)


def _parser_result(parsed):
    payload = json.loads(parsed["ui"]["afe_analysis"][0])
    return {
        "shots": payload["shots"],
        "cast": payload["cast"],
        "source_manifest": payload["source_manifest"],
    }


def _assert_phase2_isolated(prompts, current_units, adjacent_units=()):
    assert len(prompts) == len(current_units)
    for prompt, current in zip(prompts, current_units):
        assert current["text"] in prompt
        for sibling in current_units:
            if sibling is not current:
                assert sibling["text"] not in prompt
        for adjacent in adjacent_units:
            assert adjacent["text"] not in prompt


def test_complete_36_shot_screenplay_batches_bind_and_publish():
    with open(SCRIPT_PATH, encoding="utf-8") as handle:
        screenplay = handle.read()
    scene_map = parser_mod._build_scene_map(screenplay)
    explicit_units = _ordered_units(scene_map)
    assert len(explicit_units) == 36
    # Batch 2/3 split this source block, so the isolation check must cover
    # siblings on both sides of that persisted batch boundary.
    assert explicit_units[7][1]["source_block_id"] == explicit_units[8][1]["source_block_id"]

    with tempfile.TemporaryDirectory() as root:
        store = AnalysisSessionStore(root, batch_size=BATCH_SIZE)
        created = store.create(
            screenplay, len(explicit_units), SECONDS_PER_SHOT, scene_map, cast=[]
        )
        assert created["total_batches"] == 9
        assert all(
            batch["shot_end"] - batch["shot_start"] + 1 == BATCH_SIZE
            for batch in created["batches"]
        )
        parser = CpuBatchParser()
        source_by_key = {
            (str(block["source_block_id"]), str(unit["unit_id"])): (scene, block, unit)
            for scene, block, unit in explicit_units
        }
        all_results = []

        while True:
            session = store.status()
            batch = store.claim_next()
            if batch["status"] == "complete":
                break
            assert batch["claimed"] is True
            expected_pairs = [
                (str(item["source_block_id"]), str(unit_id))
                for item in batch["source_unit_ranges"]
                for unit_id in item["unit_ids"]
            ]
            assert len(expected_pairs) == BATCH_SIZE
            current_units = [source_by_key[pair][2] for pair in expected_pairs]
            context_json = _batch_context(session, batch)
            parsed = parser.parse_script(
                screenplay, target_duration_seconds=180,
                seconds_per_shot=SECONDS_PER_SHOT, model_path="cpu-stub",
                batch_start_shot=batch["shot_start"],
                batch_end_shot=batch["shot_end"],
                batch_context_json=context_json,
            )
            result = _parser_result(parsed)
            shots = result["shots"]
            assert [shot["shot_id"] for shot in shots] == [
                f"shot_{n:03d}" for n in range(batch["shot_start"], batch["shot_end"] + 1)
            ]
            for shot, (block_id, unit_id), unit in zip(shots, expected_pairs, current_units):
                assert shot["source_block_id"] == block_id
                assert shot["source_unit_ids"] == [unit_id]
                assert shot["source_text"] == unit["text"]
                assert shot["source_shot_text"] == unit["text"]
                assert shot["source_start"] == unit["start"]
                assert shot["source_end"] == unit["end"]
                assert shot["scene_occurrence_id"] == source_by_key[(block_id, unit_id)][1]["scene_occurrence_id"]
            adjacent_units = []
            first_index = batch["shot_start"] - 1
            if first_index > 0:
                adjacent_units.append(explicit_units[first_index - 1][2])
            after_batch = first_index + len(current_units)
            if after_batch < len(explicit_units):
                adjacent_units.append(explicit_units[after_batch][2])
            _assert_phase2_isolated(
                parser.phase2_prompts[-BATCH_SIZE:], current_units, adjacent_units
            )

            # Exercise cancellation/retry without changing the source contract.
            if batch["batch_index"] == 1 and not session.get("cancelled"):
                store.cancel(batch["batch_index"])
                retry_state = store.status()
                assert retry_state["batches"][0]["status"] == "pending"
                batch = store.claim_next()
                assert batch["batch_index"] == 1 and batch["claimed"] is True

            # Exercise durable result recovery after a restart for one batch.
            if batch["batch_index"] == 5:
                result.update({
                    "session_signature": session["script_signature"],
                    "source_manifest_hash": batch["source_manifest_hash"],
                    "batch_index": batch["batch_index"],
                })
                result_path = os.path.join(
                    root, "batches", session["script_signature"], "batch_005.json"
                )
                os.makedirs(os.path.dirname(result_path), exist_ok=True)
                with open(result_path, "w", encoding="utf-8") as handle:
                    json.dump(result, handle, ensure_ascii=False)
                recovered = AnalysisSessionStore(root, batch_size=BATCH_SIZE).recover_orphaned_running()
                assert recovered["batches"][4]["status"] == "completed"
            else:
                store.commit_batch(batch["batch_index"], result)
            all_results.append(result)

        final = store.status()
        assert final["analysis_status"] == "complete"
        assert final["completed_batches"] == list(range(1, 10))
        assert [shot["shot_id"] for shot in final["parsed_shots"]] == [
            f"shot_{n:03d}" for n in range(1, 37)
        ]
        assert len({
            (shot["source_block_id"], unit_id)
            for shot in final["parsed_shots"]
            for unit_id in shot["source_unit_ids"]
        }) == 36

        api = Api(root, "http://127.0.0.1:8188")
        analysis = api._assembled_analysis(final)
        _validate_analysis_payload(analysis)
        assert analysis["expected_shot_count"] == 36
        assert len(analysis["shots"]) == 36
        assert analysis["analysis_status"] == "complete"
        first = analysis["shots"][0]
        scene, block, unit = explicit_units[0]
        assert first["shot_id"] == "shot_001"
        assert first["source_text"] == unit["text"]
        assert first["source_shot_text"] == unit["text"]
        assert first["source_unit_ids"] == [unit["unit_id"]]
        assert first["source_start"] == unit["start"]
        assert first["source_end"] == unit["end"]
        assert first["source_block_id"] == block["source_block_id"]
        assert first["scene_occurrence_id"] == block["scene_occurrence_id"]


if __name__ == "__main__":
    test_complete_36_shot_screenplay_batches_bind_and_publish()
    print("PASS test_complete_36_shot_screenplay_batches_bind_and_publish")
