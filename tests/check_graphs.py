import sys
sys.path.insert(0, "tests")
import ui_mock_server as m
from ai_film_editor_nodes.webui import graphs

for st in range(1, 6):
    p, l = graphs.build_prompt(st, "afe_project", {"script": "x"}, m.OUT)
    print("stage", st, "nodes", sorted(p, key=int), "problems:", graphs.validate_prompt(p, m.CLASSES))
    assert not graphs.validate_prompt(p, m.CLASSES)

stage1, _ = graphs.build_prompt(
    1, "afe_project", {"script": "x"}, m.OUT,
    batch={"batch_index": 1, "shot_start": 1, "shot_end": 4, "context_json": "{}"},
)
assert {node["class_type"] for node in stage1.values()} == {"AFE_ScriptFullParser"}
assert "batch_end_shot" in stage1["1"]["inputs"]
