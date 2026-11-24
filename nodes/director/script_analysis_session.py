"""Persistent, atomic state for resumable screenplay batch analysis.

The store is deliberately independent of ComfyUI and the language model.  It
keeps a batch result before advancing the session cursor, so a process restart
cannot turn an unfinished batch into a complete analysis.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from copy import deepcopy

SCHEMA_VERSION = "afe-analysis-session-v1"
DEFAULT_BATCH_SIZE = 4


def script_signature(script: str, target_shot_count: int, seconds_per_shot: int,
                     episode_format: str = "", schema_version: str = SCHEMA_VERSION) -> str:
    payload = {
        "script": str(script or ""), "target_shot_count": int(target_shot_count),
        "seconds_per_shot": int(seconds_per_shot), "episode_format": str(episode_format or ""),
        "schema_version": schema_version,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _unit_manifest(scene_map: list[dict]) -> list[dict]:
    """Convert a parser scene map into an ordered, serialisable manifest."""
    manifest = []
    for scene in scene_map or []:
        for block in scene.get("source_blocks", []):
            text = str(block.get("source_text") or "")
            # Keep the same stable unit algorithm without importing the model
            # node. Newline and sentence boundaries are sufficient for planning.
            import re
            parts = [p.strip() for p in re.split(r"\n\s*\n+|(?<=[。！？!?])\s+|(?<=[。！？!?])(?=[\u4e00-\u9fff])|(?<=[.!?])\s+", text) if p.strip()]
            manifest.append({
                "order": len(manifest), "scene_id": scene.get("scene_id"),
                "scene_occurrence_id": block.get("scene_occurrence_id"),
                "source_block_id": block.get("source_block_id"),
                "section_type": block.get("section_type", scene.get("section_type")),
                "unit_ids": [f"unit_{i + 1:03d}" for i in range(len(parts))] or ["unit_001"],
                "source_text": text,
            })
    return manifest


class AnalysisSessionStore:
    """A small JSON repository with atomic session and batch-result writes."""

    def __init__(self, root: str, batch_size: int = DEFAULT_BATCH_SIZE):
        self.root = os.path.abspath(root)
        self.batch_size = max(1, int(batch_size))
        self.path = os.path.join(self.root, "session.json")
        self.results_dir = os.path.join(self.root, "batches")

    def load(self) -> dict | None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def save(self, state: dict) -> dict:
        os.makedirs(self.root, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="session-", suffix=".json", dir=self.root, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
                fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return state

    def create(self, script: str, target_shot_count: int, seconds_per_shot: int,
               scene_map: list[dict], episode_format: str = "", cast: list | None = None) -> dict:
        manifest = _unit_manifest(scene_map)
        total = int(target_shot_count)
        batches = []
        flat_units = [(item["source_block_id"], unit) for item in manifest for unit in item["unit_ids"]]
        for start in range(1, total + 1, self.batch_size):
            end = min(total, start + self.batch_size - 1)
            # Source ranges are ordered and deterministic. A unit is assigned to
            # one batch; no round-robin or synthetic shot is ever introduced.
            lo = (start - 1) * len(flat_units) // total if total else 0
            hi = end * len(flat_units) // total if total else len(flat_units)
            if end == total: hi = len(flat_units)
            selected_units = flat_units[lo:hi] or (flat_units[lo:lo + 1] if flat_units else [])
            ranges = []
            for block_id, unit_id in selected_units:
                item = next(x for x in manifest if x["source_block_id"] == block_id)
                current = next((x for x in ranges if x["source_block_id"] == block_id), None)
                if current is None:
                    current = {"source_block_id": block_id, "unit_ids": []}; ranges.append(current)
                current["unit_ids"].append(unit_id)
            batches.append({
                "batch_index": len(batches) + 1, "shot_start": start, "shot_end": end,
                "source_block_ids": [x["source_block_id"] for x in ranges],
                "source_unit_ranges": ranges,
                "status": "pending", "retry_count": 0, "error": None, "prompt_id": None,
            })
        state = {
            "schema_version": SCHEMA_VERSION, "created_at": time.time(), "updated_at": time.time(),
            "script": str(script or ""), "script_signature": script_signature(script, total, seconds_per_shot, episode_format),
            "target_shot_count": total, "seconds_per_shot": int(seconds_per_shot),
            "batch_size": self.batch_size, "total_batches": len(batches), "batches": batches,
            "completed_batches": [], "failed_batches": [], "parsed_shots": [],
            "cast": deepcopy(cast or []), "scene_map": deepcopy(scene_map or []),
            "source_manifest": manifest, "current_batch": None, "current_prompt_id": None,
            "cancelled": False, "analysis_status": "partial",
        }
        return self.save(state)

    def ensure(self, **kwargs) -> dict:
        state = self.load()
        signature = script_signature(kwargs["script"], kwargs["target_shot_count"], kwargs["seconds_per_shot"], kwargs.get("episode_format", ""))
        if state and state.get("script_signature") == signature:
            return state
        return self.create(**kwargs)

    def _touch(self, state):
        state["updated_at"] = time.time()
        return self.save(state)

    def claim_next(self, prompt_id: str | None = None) -> dict:
        state = self.load()
        if not state: raise ValueError("分析会话不存在")
        running = next((b for b in state["batches"] if b["status"] == "running"), None)
        if running:
            return deepcopy(running)
        batch = next((b for b in state["batches"] if b["status"] == "pending"), None)
        if not batch:
            return {"status": "complete", "batch_index": None}
        batch["status"] = "running"; batch["prompt_id"] = prompt_id
        state["current_batch"] = batch["batch_index"]; state["current_prompt_id"] = prompt_id
        self._touch(state)
        return deepcopy(batch)

    def set_prompt(self, batch_index: int, prompt_id: str) -> dict:
        state = self.load(); batch = state["batches"][int(batch_index) - 1]
        if batch["status"] != "running": raise ValueError("只能为运行中的批次保存 prompt")
        batch["prompt_id"] = prompt_id; state["current_prompt_id"] = prompt_id
        return self._touch(state)

    def commit_batch(self, batch_index: int, result: dict) -> dict:
        state = self.load(); index = int(batch_index)
        batch = next(b for b in state["batches"] if b["batch_index"] == index)
        if batch["status"] == "completed": return state
        shots = result.get("shots") if isinstance(result, dict) else None
        expected = batch["shot_end"] - batch["shot_start"] + 1
        if not isinstance(shots, list) or len(shots) != expected:
            raise ValueError(f"第{index}批分镜不完整：需要{expected}个，实际返回{len(shots) if isinstance(shots, list) else 0}个")
        ids = [str(s.get("shot_id") or "") for s in shots]
        wanted = [f"shot_{n:03d}" for n in range(batch["shot_start"], batch["shot_end"] + 1)]
        if ids != wanted:
            raise ValueError(f"第{index}批分镜编号或顺序错误：需要 {wanted[0]}-{wanted[-1]}")
        if not result.get("source_manifest"):
            raise ValueError(f"第{index}批缺少 source manifest，未保存不完整结果")
        expected_units = {(r["source_block_id"], unit) for r in batch.get("source_unit_ranges", []) for unit in r.get("unit_ids", [])}
        returned_units = set()
        for item in result.get("source_manifest", []):
            block_id = str(item.get("source_block_id") or "")
            for unit in item.get("unit_ids", []):
                key = (block_id, str(unit))
                if key in returned_units:
                    raise ValueError(f"第{index}批 source manifest 重复原文单元：{block_id}/{unit}")
                returned_units.add(key)
        if expected_units and returned_units != expected_units:
            missing = sorted(expected_units - returned_units)
            extra = sorted(returned_units - expected_units)
            raise ValueError(f"第{index}批 source manifest 覆盖错误：遗漏{missing[:5]}，多出{extra[:5]}")
        shot_units = []
        for shot in shots:
            block_id = str(shot.get("source_block_id") or "")
            for unit in shot.get("source_unit_ids") or []:
                shot_units.append((block_id, str(unit)))
        if len(shot_units) != len(set(shot_units)):
            raise ValueError(f"第{index}批分镜重复覆盖原文单元")
        if expected_units and set(shot_units) != expected_units:
            raise ValueError(f"第{index}批分镜 source_unit_ids 未完整覆盖批次原文")
        result_path = os.path.join(self.results_dir, f"batch_{index:03d}.json")
        os.makedirs(self.results_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f"batch-{index}-", suffix=".json", dir=self.results_dir, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2); fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp, result_path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        batch["status"] = "completed"; batch["error"] = None
        state["completed_batches"] = sorted(set(state["completed_batches"] + [index]))
        state["failed_batches"] = [x for x in state["failed_batches"] if x != index]
        state["parsed_shots"] = sorted(state.get("parsed_shots", []) + deepcopy(shots), key=lambda s: s.get("shot_id", ""))
        if result.get("cast"): state["cast"] = deepcopy(result["cast"])
        state["current_batch"] = None; state["current_prompt_id"] = None
        if len(state["completed_batches"]) == len(state["batches"]): state["analysis_status"] = "complete"
        return self._touch(state)

    def fail_batch(self, batch_index: int, error: str) -> dict:
        state = self.load(); batch = next(b for b in state["batches"] if b["batch_index"] == int(batch_index))
        batch["status"] = "failed"; batch["retry_count"] += 1; batch["error"] = str(error)[:2000]
        if batch["batch_index"] not in state["failed_batches"]: state["failed_batches"].append(batch["batch_index"])
        state["current_batch"] = None; state["current_prompt_id"] = None
        return self._touch(state)

    def retry(self, batch_index: int) -> dict:
        state = self.load(); batch = next(b for b in state["batches"] if b["batch_index"] == int(batch_index))
        if batch["status"] != "failed": raise ValueError("只能重试失败批次")
        batch["status"] = "pending"; batch["error"] = None
        state["failed_batches"] = [x for x in state["failed_batches"] if x != batch["batch_index"]]
        return self._touch(state)

    def cancel(self) -> dict:
        state = self.load();
        if not state: return {}
        for batch in state["batches"]:
            if batch["status"] == "running": batch["status"] = "pending"; batch["error"] = "已取消，可继续或重试"
        state["cancelled"] = True; state["current_batch"] = None; state["current_prompt_id"] = None
        return self._touch(state)

    def recover_orphaned_running(self) -> dict:
        state = self.load();
        if not state: return {}
        for batch in state["batches"]:
            if batch["status"] == "running":
                batch["status"] = "failed"; batch["error"] = "ComfyUI 重启后未找到该批次结果，可重试"; batch["retry_count"] += 1
                if batch["batch_index"] not in state["failed_batches"]: state["failed_batches"].append(batch["batch_index"])
        state["current_batch"] = None; state["current_prompt_id"] = None
        return self._touch(state)

    def status(self) -> dict:
        state = self.load() or {}
        state["completed_shot_count"] = sum(b["shot_end"] - b["shot_start"] + 1 for b in state.get("batches", []) if b.get("status") == "completed")
        return state
