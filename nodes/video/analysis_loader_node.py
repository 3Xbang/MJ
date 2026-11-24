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


def _validate_complete_analysis(data: dict) -> None:
    """Keep the downstream node behind the same durable complete-result contract."""
    if not isinstance(data, dict) or data.get("schema_version") != "afe-analysis-v1":
        raise ValueError("剧本分析缺少当前版本的结构化来源清单，请先完成第 ① 步。")
    if data.get("analysis_status") != "complete":
        raise ValueError("剧本分析尚未完成全部批次，不能进入后续阶段。")
    if not str(data.get("session_signature") or "").strip():
        raise ValueError("剧本分析缺少会话签名，不能作为当前项目结果使用。")
    shots = data.get("shots")
    expected = data.get("expected_shot_count")
    if not isinstance(shots, list) or not isinstance(expected, int) or expected <= 0 or len(shots) != expected:
        raise ValueError("剧本分析的分镜数量与完整结果清单不一致。")
    manifest = data.get("source_manifest")
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("剧本分析缺少原文来源清单。")
    manifest_units = set()
    by_block = {}
    block_positions = {}
    for position, item in enumerate(manifest):
        if not isinstance(item, dict):
            raise ValueError("剧本分析原文来源清单不完整或顺序错误。")
        block_id = str(item.get("source_block_id") or "")
        unit_ids = item.get("unit_ids")
        context_only = bool(item.get("context_only"))
        if (not block_id or item.get("order") != position
                or not isinstance(unit_ids, list)
                or (not unit_ids and not context_only)):
            raise ValueError("剧本分析原文来源清单不完整或顺序错误。")
        if block_id in by_block:
            raise ValueError("剧本分析原文来源清单包含重复来源块。")
        normalized = [str(unit).strip() for unit in unit_ids]
        if any(not unit for unit in normalized):
            raise ValueError("剧本分析原文来源清单不完整或顺序错误。")
        if len(set(normalized)) != len(normalized):
            raise ValueError("剧本分析原文来源清单包含重复单元。")
        by_block[block_id] = normalized
        block_positions[block_id] = position
        manifest_units.update((block_id, unit) for unit in normalized)
    if not manifest_units:
        raise ValueError("剧本分析原文来源清单没有可用于分镜的 source unit。")
    covered = set()
    previous_position = None
    for shot in shots:
        if not isinstance(shot, dict):
            raise ValueError("剧本分析包含无效分镜。")
        block_id = str(shot.get("source_block_id") or "")
        unit_ids = shot.get("source_unit_ids")
        if not block_id or block_id not in by_block or not isinstance(unit_ids, list) or not unit_ids:
            raise ValueError("剧本分析分镜缺少可验证的原文来源。")
        normalized = [str(unit).strip() for unit in unit_ids]
        if len(set(normalized)) != len(normalized) or any(unit not in by_block[block_id] for unit in normalized):
            raise ValueError("剧本分析分镜引用了无效或重复原文单元。")
        positions = [by_block[block_id].index(unit) for unit in normalized]
        if positions != sorted(positions):
            raise ValueError("剧本分析分镜原文来源顺序错误。")
        if any((block_id, unit) in covered for unit in normalized):
            raise ValueError("剧本分析分镜重复覆盖原文单元。")
        first_position = (block_positions[block_id], positions[0])
        if previous_position is not None and first_position < previous_position:
            raise ValueError("剧本分析分镜顺序与原文来源清单不一致。")
        previous_position = first_position
        covered.update((block_id, unit) for unit in normalized)
    if covered != manifest_units:
        raise ValueError("剧本分析未完整覆盖原文来源清单。")


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
        _validate_complete_analysis(data)
        shots, cast = data["shots"], data.get("cast", [])
        return (shots, cast, f"已载入分析结果：{len(shots)} 个分镜，{len(cast)} 个角色")
