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
    # ``scene_map`` groups repeated physical locations for asset reuse.  That
    # grouping is not screenplay order: an A/B/A script has A's second
    # occurrence inside the first grouped scene.  Flatten by the parser's
    # source block position before assigning any batch ranges.
    blocks = []
    for scene in scene_map or []:
        for block in scene.get("source_blocks", []):
            blocks.append((block, scene))
    def source_order(item):
        block = item[0]
        if block.get("source_order") is not None:
            return int(block["source_order"])
        match = __import__("re").search(r"(\d+)$", str(block.get("source_block_id") or ""))
        return int(match.group(1)) if match else len(blocks)
    for block, scene in sorted(blocks, key=source_order):
        text = str(block.get("source_text") or "")
        # Keep the same stable unit algorithm without importing the model
        # node. Newline and sentence boundaries are sufficient for planning.
        import re
        parts = [p.strip() for p in re.split(r"\n\s*\n+|(?<=[。！？!?])\s+|(?<=[。！？!?])(?=[\u4e00-\u9fff])|(?<=[.!?])\s+", text) if p.strip()]
        units = []
        cursor = 0
        for index, part in enumerate(parts):
            start = text.find(part, cursor)
            end = start + len(part) if start >= 0 else cursor + len(part)
            units.append({"unit_id": f"unit_{index + 1:03d}", "start": start, "end": end, "text": part})
            cursor = max(end, cursor)
        manifest.append({
            "order": len(manifest), "scene_id": scene.get("scene_id"),
            "scene_occurrence_id": block.get("scene_occurrence_id"),
            "source_block_id": block.get("source_block_id"),
            "section_type": block.get("section_type", scene.get("section_type")),
            "unit_ids": [unit["unit_id"] for unit in units],
            "units": units,
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
        if total <= 0:
            raise ValueError("目标镜头数必须大于零")
        for start in range(1, total + 1, self.batch_size):
            end = min(total, start + self.batch_size - 1)
            # Source ranges are ordered and deterministic. A unit is assigned to
            # one batch; no round-robin or synthetic shot is ever introduced.
            if len(flat_units) < total:
                # Keep every real unit in screenplay order. Remaining batches
                # stay empty and will fail validation rather than reusing text.
                lo, hi = min(start - 1, len(flat_units)), min(end, len(flat_units))
            else:
                lo = (start - 1) * len(flat_units) // total
                hi = end * len(flat_units) // total
                if end == total:
                    hi = len(flat_units)
            selected_units = flat_units[lo:hi]
            ranges = []
            for block_id, unit_id in selected_units:
                item = next(x for x in manifest if x["source_block_id"] == block_id)
                current = next((x for x in ranges if x["source_block_id"] == block_id), None)
                if current is None:
                    current = {"source_block_id": block_id, "unit_ids": []}; ranges.append(current)
                current["unit_ids"].append(unit_id)
                manifest_item = next(x for x in manifest if x["source_block_id"] == block_id)
                unit_detail = next((item for item in manifest_item.get("units", [])
                                    if item["unit_id"] == unit_id), None)
                if unit_detail:
                    current.setdefault("units", []).append(deepcopy(unit_detail))
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
            # The caller must inspect the persisted prompt before queueing. This
            # method is intentionally idempotent and never creates a second claim.
            return deepcopy(running)
        first_unfinished = next((b for b in state["batches"] if b["status"] != "completed"), None)
        if first_unfinished and first_unfinished["status"] == "failed":
            return deepcopy(first_unfinished)
        batch = first_unfinished
        if not batch:
            return {"status": "complete", "batch_index": None}
        batch["status"] = "running"; batch["prompt_id"] = prompt_id
        state["current_batch"] = batch["batch_index"]; state["current_prompt_id"] = prompt_id
        state["cancelled"] = False
        self._touch(state)
        return deepcopy(batch)

    def set_prompt(self, batch_index: int, prompt_id: str) -> dict:
        state = self.load(); batch = state["batches"][int(batch_index) - 1]
        if batch["status"] != "running": raise ValueError("只能为运行中的批次保存 prompt")
        batch["prompt_id"] = prompt_id; state["current_prompt_id"] = prompt_id
        return self._touch(state)

    @staticmethod
    def _merge_cast(existing: list, incoming: list) -> list:
        """Merge batch cast records without losing characters from prior batches."""
        merged = []
        positions = {}
        for record in (existing or []) + (incoming or []):
            if not isinstance(record, dict) or not str(record.get("name") or "").strip():
                continue
            key = str(record["name"]).strip().casefold()
            if key not in positions:
                positions[key] = len(merged)
                merged.append(deepcopy(record))
            else:
                current = merged[positions[key]]
                for field, value in record.items():
                    if value not in (None, "", [], {}):
                        current[field] = deepcopy(value)
        return merged

    def commit_batch(self, batch_index: int, result: dict) -> dict:
        state = self.load(); index = int(batch_index)
        batch = next(b for b in state["batches"] if b["batch_index"] == index)
        if batch["status"] == "completed": return state
        if batch["status"] != "running":
            raise ValueError(f"第{index}批当前状态为 {batch['status']}，不能提交结果；请先继续或重试")
        def reject(message: str):
            batch["status"] = "failed"
            batch["retry_count"] += 1
            batch["error"] = str(message)[:2000]
            if index not in state["failed_batches"]:
                state["failed_batches"].append(index)
            state["current_batch"] = None
            state["current_prompt_id"] = None
            self._touch(state)
            raise ValueError(str(message))
        shots = result.get("shots") if isinstance(result, dict) else None
        expected = batch["shot_end"] - batch["shot_start"] + 1
        if not isinstance(shots, list) or len(shots) != expected:
            reject(f"第{index}批分镜不完整：需要{expected}个，实际返回{len(shots) if isinstance(shots, list) else 0}个")
        ids = [str(s.get("shot_id") or "") for s in shots]
        wanted = [f"shot_{n:03d}" for n in range(batch["shot_start"], batch["shot_end"] + 1)]
        if ids != wanted:
            reject(f"第{index}批分镜编号或顺序错误：需要 {wanted[0]}-{wanted[-1]}")
        unverified = []
        for shot in shots:
            for field in ("scene_assignment_error", "source_validation_error"):
                value = shot.get(field)
                if value not in (None, "", [], {}):
                    unverified.append(f"{shot.get('shot_id', '?')} {field}: {value}")
        if unverified:
            reason = "；".join(str(item) for item in unverified[:8])
            reject(f"第{index}批原文来源未验证，未保存结果：{reason}")
        if not result.get("source_manifest"):
            reject(f"第{index}批缺少 source manifest，未保存不完整结果")
        expected_units = [(r["source_block_id"], unit) for r in batch.get("source_unit_ranges", []) for unit in r.get("unit_ids", [])]
        expected_unit_set = set(expected_units)
        returned_units = set()
        returned_sequence = []
        for item in result.get("source_manifest", []):
            block_id = str(item.get("source_block_id") or "")
            for unit in item.get("unit_ids", []):
                key = (block_id, str(unit))
                if key in returned_units:
                    reject(f"第{index}批 source manifest 重复原文单元：{block_id}/{unit}")
                returned_units.add(key)
                returned_sequence.append(key)
        if expected_units and returned_sequence != expected_units:
            reject(f"第{index}批 source manifest 顺序错误")
        if expected_units and returned_units != expected_unit_set:
            missing = sorted(expected_units - returned_units)
            extra = sorted(returned_units - expected_units)
            reject(f"第{index}批 source manifest 覆盖错误：遗漏{missing[:5]}，多出{extra[:5]}")
        shot_units = []
        for shot in shots:
            block_id = str(shot.get("source_block_id") or "")
            for unit in shot.get("source_unit_ids") or []:
                shot_units.append((block_id, str(unit)))
        if len(shot_units) != len(set(shot_units)):
            reject(f"第{index}批分镜重复覆盖原文单元")
        if expected_units and set(shot_units) != expected_unit_set:
            missing = sorted(expected_unit_set - set(shot_units))
            extra = sorted(set(shot_units) - expected_unit_set)
            reject(f"第{index}批分镜 source_unit_ids 未完整覆盖批次原文：遗漏{missing[:5]}，多出{extra[:5]}")
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
        if result.get("cast"):
            state["cast"] = self._merge_cast(state.get("cast", []), result["cast"])
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
        state["cancelled"] = False
        state["failed_batches"] = [x for x in state["failed_batches"] if x != batch["batch_index"]]
        return self._touch(state)

    def cancel(self, batch_index: int | None = None, prompt_id: str | None = None) -> dict:
        state = self.load()
        if not state:
            return {}
        running = next((b for b in state["batches"] if b["status"] == "running"), None)
        if not running:
            raise ValueError("当前没有可取消的分析任务")
        if running and batch_index is not None and running["batch_index"] != int(batch_index):
            raise ValueError("当前运行批次已变化，未取消其他任务")
        if running and prompt_id and running.get("prompt_id") != prompt_id:
            raise ValueError("取消请求不是当前分析 prompt，未取消其他任务")
        if running:
            running["status"] = "pending"
            running["error"] = "已取消，可继续或重试"
            running["prompt_id"] = None
        state["cancelled"] = True
        state["current_batch"] = None
        state["current_prompt_id"] = None
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
