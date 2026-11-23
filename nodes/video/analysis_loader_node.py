"""
AFE_AnalysisLoader — loads the script analysis (shots + cast) saved by the web UI.

The LLM script parser is slow and not deterministic. The web UI therefore runs it once, saves the
result to <output>/afe_projects/<project>/analysis.json, and every later step reads it from here.
That keeps shot ids and descriptions identical between runs (so first frames and clips are reused
instead of redrawn) and survives a ComfyUI restart.
"""
from __future__ import annotations

import json
import os

from ai_film_editor_nodes.nodes.video._common import project_dir


def analysis_path(project_name: str) -> str:
    return os.path.join(project_dir(project_name), "analysis.json")


class AFE_AnalysisLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project_name": ("STRING", {"default": "afe_project"})}}

    RETURN_TYPES = ("SHOT_SEQUENCE", "CAST_DATA", "STRING")
    RETURN_NAMES = ("shot_sequence", "cast_data", "report")
    FUNCTION = "load"
    CATEGORY = "AI Film Editor/Video"

    @classmethod
    def IS_CHANGED(cls, project_name):
        p = analysis_path(project_name)
        return os.path.getmtime(p) if os.path.exists(p) else float("nan")

    def load(self, project_name):
        p = analysis_path(project_name)
        if not os.path.exists(p):
            raise ValueError(f"项目「{project_name}」还没有剧本分析结果，请先完成第 ① 步「分析剧本」。")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        shots, cast = data.get("shots", []), data.get("cast", [])
        return (shots, cast, f"已载入分析结果：{len(shots)} 个分镜，{len(cast)} 个角色")
