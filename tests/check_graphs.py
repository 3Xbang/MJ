import sys, os
sys.path.insert(0, "tests")
import ui_mock_server as m
from ai_film_editor_nodes.webui import graphs
for st in range(1, 6):
    p, l = graphs.build_prompt(st, "afe_project", {"script": "x"}, m.OUT)
    print("stage", st, "nodes", sorted(p, key=int), "problems:", graphs.validate_prompt(p, m.CLASSES))
