"""Screenplay shots that share a camera continue; a new setup opens on its own frame."""
import os
import re
import tempfile
from unittest.mock import patch

import torch

from ai_film_editor_nodes.nodes.video._common import save_png
from ai_film_editor_nodes.nodes.video.shot_continuity import link_shots
from ai_film_editor_nodes.nodes.video.wan_shot_renderer_node import (
    PREVIOUS_SHOT_SUFFIX, AFE_WanShotRenderer,
)

_LECTURE = os.path.join(os.path.dirname(__file__), "..", "test_scripts", "san_yan_liang_yu_ep01_lecture.md")


def _shots(text: str) -> list[dict]:
    shots = []
    for part in re.split(r"(?=^### 镜头)", text, flags=re.M):
        match = re.match(r"### 镜头\s*(\d+)", part)
        if not match:
            continue
        number = int(match.group(1))
        shots.append({"shot_id": f"shot_{number:03d}", "source_shot_text": part.strip()})
    return shots


def _continued(shots: list[dict]) -> dict[str, str]:
    return {shot["shot_id"]: shot["continuity_from"]
            for shot in link_shots(shots) if shot["continues_previous"]}


def test_analysis_writes_the_link_sentence_from_the_screenplay():
    with open(_LECTURE, encoding="utf-8") as handle:
        linked = {shot["shot_id"]: shot for shot in link_shots(_shots(handle.read()))}
    continued = linked["shot_002"]["continuity_prompt"]
    assert continued.startswith("接上 shot_001 的最后一秒")
    assert "仍只有双手" in continued
    assert "左手把佛珠托稳" in continued
    opening = linked["shot_037"]["continuity_prompt"]
    assert opening.startswith("新机位，从这一镜首帧开口")
    assert "小宇和小舟的背影" in opening
    assert "中远景，从身后看" in opening
    assert "小宇拿起罐头" in opening


def test_lecture_keeps_the_same_camera_and_opens_a_new_one():
    with open(_LECTURE, encoding="utf-8") as handle:
        linked = _continued(_shots(handle.read()))
    assert linked["shot_002"] == "shot_001"
    assert "shot_003" not in linked
    assert "shot_006" not in linked
    assert linked["shot_025"] == "shot_024"
    assert linked["shot_026"] == "shot_025"
    assert "shot_027" not in linked
    assert "shot_028" not in linked


def test_same_place_with_a_new_angle_opens_on_its_own_frame():
    previous = {"shot_id": "shot_008", "source_shot_text": "地点：打包台前。\n入画：小宇腰部以上。\n镜头：中景，平视。"}
    side = {"shot_id": "shot_009", "source_shot_text": "地点：打包台前。\n入画：小宇腰部以上。\n镜头：中景，侧面。"}
    linked = link_shots([previous, side])
    assert linked[1]["continuity"] == "new_camera"


def test_missing_screenplay_text_opens_on_its_own_frame():
    linked = link_shots([
        {"shot_id": "shot_001", "shot_description": "a man talks"},
        {"shot_id": "shot_002", "shot_description": "a man talks"},
    ])
    assert linked[0]["continuity"] == "new_camera"
    assert linked[1]["continuity"] == "new_camera"


def test_same_camera_video_starts_from_the_previous_last_frame():
    seen = []

    def fake_render(models, image, prompt, *args, **kwargs):
        seen.append((round(float(image.mean()), 2), prompt))
        return torch.ones(4, 8, 8, 3)

    shots = [
        {"shot_id": "shot_001", "duration_seconds": 1,
         "source_shot_text": "地点：藤椅。\n入画：胖叔胸口以上。\n镜头：胸口以上。"},
        {"shot_id": "shot_002", "duration_seconds": 1,
         "source_shot_text": "地点：藤椅。\n入画：胖叔胸口以上。\n镜头：胸口以上。"},
    ]
    with tempfile.TemporaryDirectory() as project:
        os.makedirs(os.path.join(project, "keyframes"))
        save_png(torch.zeros(1, 8, 8, 3), os.path.join(project, "keyframes", "shot_001.png"))
        save_png(torch.zeros(1, 8, 8, 3), os.path.join(project, "keyframes", "shot_002.png"))
        with patch("ai_film_editor_nodes.nodes.video.wan_shot_renderer_node._load_wan", return_value=object()), \
             patch("ai_film_editor_nodes.nodes.video.wan_shot_renderer_node.write_mp4"), \
             patch("ai_film_editor_nodes.nodes.video.wan_shot_renderer_node.render_shot", side_effect=fake_render):
            result = AFE_WanShotRenderer().render([dict(s) for s in shots], project, "style", approved=True)
    assert seen[0][0] == 0.0
    assert PREVIOUS_SHOT_SUFFIX not in seen[0][1]
    assert seen[1][0] == 1.0
    assert PREVIOUS_SHOT_SUFFIX in seen[1][1]
    assert "shot_001→shot_002" in result["result"][1]


def test_linking_twice_keeps_the_same_decision():
    shots = [
        {"shot_id": "shot_001", "source_shot_text": "地点：藤椅。\n入画：胖叔胸口以上。\n镜头：胸口以上。"},
        {"shot_id": "shot_002", "source_shot_text": "地点：藤椅。\n入画：胖叔胸口以上。\n镜头：胸口以上。"},
    ]
    once = link_shots(shots)
    twice = link_shots(once)
    assert twice[1]["continues_previous"] is True
    assert twice[1]["continuity_from"] == "shot_001"
