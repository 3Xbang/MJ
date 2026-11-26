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
import uuid
from contextlib import contextmanager
from copy import deepcopy

from ai_film_editor_nodes.nodes.director.screenplay_source_units import (
    refine_source_units,
    source_units_with_offsets,
)

SCHEMA_VERSION = "afe-analysis-session-v1"
DEFAULT_BATCH_SIZE = 1


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

    ordered_blocks = sorted(blocks, key=source_order)
    parsed = []
    explicit_mode = False
    for block, scene in ordered_blocks:
        text = str(block.get("source_text") or "")
        units = source_units_with_offsets(text)
        explicit_mode = explicit_mode or any(unit.get("is_explicit_shot") for unit in units)
        parsed.append((block, scene, text, units))
    for block, scene, text, units in parsed:
        has_explicit_shot = any(unit.get("is_explicit_shot") for unit in units)
        # In a mixed script, a title card, environment paragraph, or ordinary
        # structure block without an explicit shot heading is context-only.
        # Preserve it verbatim and in screenplay order, but never require a
        # fabricated shot to cover it at publication time.
        context_only = explicit_mode and not has_explicit_shot
        consumable = [unit for unit in units
                      if not unit.get("is_context") and not context_only]
        context_units = [unit for unit in units
                         if unit.get("is_context") or context_only]
        manifest.append({
            "order": len(manifest), "scene_id": scene.get("scene_id"),
            "scene_occurrence_id": block.get("scene_occurrence_id"),
            "source_block_id": block.get("source_block_id"),
            "section_type": block.get("section_type", scene.get("section_type")),
            "unit_ids": [unit["unit_id"] for unit in consumable],
            "context_only": context_only,
            "context_units": context_units,
            "units": units,
            "source_text": text,
        })
    return manifest


def _source_manifest_hash(items: list[dict]) -> str:
    payload = [{
        "source_block_id": item.get("source_block_id"),
        "unit_ids": list(item.get("unit_ids") or []),
        "context_only": bool(item.get("context_only")),
    } for item in items]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _batch_source_hash(ranges: list[dict]) -> str:
    return _source_manifest_hash(ranges)


class AnalysisSessionStore:
    """A small JSON repository with atomic session and batch-result writes."""

    def __init__(self, root: str, batch_size: int = DEFAULT_BATCH_SIZE):
        self.root = os.path.abspath(root)
        self.batch_size = max(1, int(batch_size))
        self.path = os.path.join(self.root, "session.json")
        # Keep legacy batches/ untouched, but never use its index-only files as
        # recovery markers for a new script session.
        self.results_dir = os.path.join(self.root, "batches")

    def _results_dir(self, state: dict) -> str:
        signature = str(state.get("script_signature") or "").strip()
        if not signature:
            raise ValueError("分析会话缺少脚本签名，拒绝恢复批次结果")
        return os.path.join(self.root, "batches", signature)

    @staticmethod
    def _batch_metadata(state: dict, batch: dict) -> dict:
        return {
            "session_signature": state.get("script_signature"),
            "source_manifest_hash": batch.get("source_manifest_hash"),
            "batch_index": int(batch.get("batch_index")),
        }

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
        if total <= 0:
            raise ValueError("目标镜头数必须大于零")
        session_script_signature = script_signature(script, total, seconds_per_shot, episode_format)
        batches = []
        all_units = [
            (item["source_block_id"], unit)
            for item in manifest
            for unit in item.get("units", [])
            if unit.get("unit_id") in set(item.get("unit_ids") or [])
        ]
        explicit_units = [entry for entry in all_units if entry[1].get("is_explicit_shot")]
        if not explicit_units and len(all_units) < total:
            # Ordinary scripts often use action lines or clause fragments rather
            # than numbered shot headings. Refine only at exact punctuation
            # boundaries and persist those offsets as the batch contract.
            for item in manifest:
                refined = refine_source_units(item.get("source_text", ""), total)
                if len(refined) > len(item.get("units", [])):
                    item["units"] = refined
                    item["unit_ids"] = [unit["unit_id"] for unit in refined]
            all_units = [
                (item["source_block_id"], unit)
                for item in manifest
                for unit in item.get("units", [])
                if unit.get("unit_id") in set(item.get("unit_ids") or [])
            ]
            if len(all_units) < total:
                raise ValueError(
                    f"原文只有 {len(all_units)} 个可验证 source unit，无法建立 {total} 个有效镜头边界；"
                    "拒绝文本切分或静默复制。"
                )
        if explicit_units:
            if len(explicit_units) != total:
                raise ValueError(
                    f"原文包含 {len(explicit_units)} 个显式镜头边界，但目标为 {total} 个镜头；"
                    "不会跨镜头拆分或静默填充镜头。"
                )
            flat_units = explicit_units
        else:
            flat_units = all_units
        for start in range(1, total + 1, self.batch_size):
            end = min(total, start + self.batch_size - 1)
            # Source ranges are ordered and deterministic. Explicit shot units
            # are selected one-for-one; generic scripts retain proportional
            # planning because they have no declared shot boundaries.
            if explicit_units:
                selected_units = flat_units[start - 1:end]
            elif len(flat_units) < total:
                # Keep every real unit in screenplay order. Remaining batches
                # stay empty and will fail validation rather than reusing text.
                lo, hi = min(start - 1, len(flat_units)), min(end, len(flat_units))
                selected_units = flat_units[lo:hi]
            else:
                lo = (start - 1) * len(flat_units) // total
                hi = end * len(flat_units) // total
                if end == total:
                    hi = len(flat_units)
                selected_units = flat_units[lo:hi]
            ranges = []
            for block_id, unit in selected_units:
                current = next((x for x in ranges if x["source_block_id"] == block_id), None)
                if current is None:
                    current = {"source_block_id": block_id, "unit_ids": []}; ranges.append(current)
                current["unit_ids"].append(unit["unit_id"])
                current.setdefault("units", []).append(deepcopy(unit))
            source_hash = _batch_source_hash(ranges)
            has_source = bool(ranges and any(item.get("unit_ids") for item in ranges))
            batches.append({
                "batch_index": len(batches) + 1, "shot_start": start, "shot_end": end,
                "source_block_ids": [x["source_block_id"] for x in ranges],
                "source_unit_ranges": ranges,
                "source_manifest_hash": source_hash,
                "status": "pending" if has_source else "failed", "retry_count": 0,
                "error": None if has_source else "该批次没有可验证的原文 source unit，拒绝生成或发布镜头",
                "prompt_id": None,
            })
        failed_batches = [b["batch_index"] for b in batches if b["status"] == "failed"]
        state = {
            "schema_version": SCHEMA_VERSION, "created_at": time.time(), "updated_at": time.time(),
            "script": str(script or ""), "script_signature": session_script_signature,
            "source_manifest_hash": _source_manifest_hash(manifest),
            "target_shot_count": total, "seconds_per_shot": int(seconds_per_shot),
            "batch_size": self.batch_size, "total_batches": len(batches), "batches": batches,
            "completed_batches": [], "failed_batches": failed_batches, "parsed_shots": [],
            "cast": deepcopy(cast or []), "scene_map": deepcopy(scene_map or []),
            "source_manifest": manifest, "current_batch": None, "current_prompt_id": None,
            "cancelled": False, "analysis_status": "partial",
        }
        return self.save(state)

    def ensure(self, **kwargs) -> dict:
        state = self.load()
        signature = script_signature(kwargs["script"], kwargs["target_shot_count"], kwargs["seconds_per_shot"], kwargs.get("episode_format", ""))
        if state and state.get("script_signature") == signature:
            # An unfinished 4-shot batch session is rebuilt as one shot per call.
            # A finished analysis is left as-is.
            stored = int(state.get("batch_size") or self.batch_size)
            if state.get("analysis_status") != "complete" and stored != int(self.batch_size):
                return self.create(**kwargs)
            return state
        return self.create(**kwargs)

    def _touch(self, state):
        state["updated_at"] = time.time()
        return self.save(state)

    @contextmanager
    def _claim_lock(self):
        """Serialize claim and prompt ownership across WebUI worker processes."""
        os.makedirs(self.root, exist_ok=True)
        lock_path = os.path.join(self.root, ".claim.lock")
        deadline = time.time() + 15
        handle = None
        while handle is None:
            try:
                handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(lock_path) > 60:
                        os.unlink(lock_path)
                        continue
                except FileNotFoundError:
                    continue
                except OSError:
                    pass
                if time.time() >= deadline:
                    raise TimeoutError("分析批次锁定超时，请稍后重试")
                time.sleep(0.02)
        try:
            os.write(handle, str(os.getpid()).encode("ascii", errors="ignore"))
            os.close(handle)
            handle = None
            yield
        finally:
            if handle is not None:
                os.close(handle)
            try:
                os.unlink(lock_path)
            except FileNotFoundError:
                pass

    def _claim_locked(self, state: dict, prompt_id: str | None = None) -> dict:
        running = next((b for b in state["batches"] if b["status"] == "running"), None)
        if running:
            result = deepcopy(running)
            result["claimed"] = False
            result["submission_pending"] = not bool(running.get("prompt_id"))
            return result
        first_unfinished = next((b for b in state["batches"] if b["status"] != "completed"), None)
        if first_unfinished and first_unfinished["status"] == "failed":
            result = deepcopy(first_unfinished)
            result["claimed"] = False
            return result
        if not first_unfinished:
            return {"status": "complete", "batch_index": None, "claimed": False}
        if not any(item.get("unit_ids") for item in first_unfinished.get("source_unit_ranges", [])):
            first_unfinished["status"] = "failed"
            first_unfinished["error"] = "该批次没有可验证的原文 source unit，拒绝生成或发布镜头"
            if first_unfinished["batch_index"] not in state["failed_batches"]:
                state["failed_batches"].append(first_unfinished["batch_index"])
            self._touch(state)
            result = deepcopy(first_unfinished)
            result["claimed"] = False
            return result
        first_unfinished["status"] = "running"
        first_unfinished["prompt_id"] = prompt_id
        first_unfinished["claim_token"] = uuid.uuid4().hex
        state["current_batch"] = first_unfinished["batch_index"]
        state["current_prompt_id"] = None
        state["cancelled"] = False
        self._touch(state)
        result = deepcopy(first_unfinished)
        result["claimed"] = True
        return result

    def claim_next(self, prompt_id: str | None = None) -> dict:
        with self._claim_lock():
            state = self.load()
            if not state:
                raise ValueError("分析会话不存在")
            return self._claim_locked(state, prompt_id)

    def set_prompt(self, batch_index: int, prompt_id: str, claim_token: str | None = None) -> dict:
        with self._claim_lock():
            state = self.load()
            batch = state["batches"][int(batch_index) - 1]
            if batch["status"] != "running":
                raise ValueError("只能为运行中的批次保存 prompt")
            if claim_token and batch.get("claim_token") != claim_token:
                raise ValueError("该分析批次已被其他请求接管")
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

    def _validate_batch_result(self, batch: dict, result: dict, state: dict | None = None) -> list[dict]:
        """Validate one persisted batch without changing session state."""
        if state is not None:
            expected_meta = self._batch_metadata(state, batch)
            for key, expected_value in expected_meta.items():
                if result.get(key) != expected_value:
                    raise ValueError(f"第{batch['batch_index']}批结果不属于当前分析会话（{key} 不匹配）")
        expected_units = [(r["source_block_id"], unit) for r in batch.get("source_unit_ranges", []) for unit in r.get("unit_ids", [])]
        if not expected_units:
            raise ValueError(f"第{batch['batch_index']}批没有可验证的原文 source unit，拒绝发布")
        shots = result.get("shots") if isinstance(result, dict) else None
        expected = batch["shot_end"] - batch["shot_start"] + 1
        if not isinstance(shots, list) or len(shots) != expected:
            raise ValueError(f"第{batch['batch_index']}批分镜不完整：需要{expected}个，实际返回{len(shots) if isinstance(shots, list) else 0}个")
        ids = [str(s.get("shot_id") or "") for s in shots]
        wanted = [f"shot_{n:03d}" for n in range(batch["shot_start"], batch["shot_end"] + 1)]
        if ids != wanted:
            raise ValueError(f"第{batch['batch_index']}批分镜编号或顺序错误：需要 {wanted[0]}-{wanted[-1]}")
        unverified = []
        for shot in shots:
            for field in ("scene_assignment_error", "source_validation_error"):
                value = shot.get(field)
                if value not in (None, "", [], {}):
                    unverified.append(f"{shot.get('shot_id', '?')} {field}: {value}")
        if unverified:
            raise ValueError("第%d批原文来源未验证，未保存结果：%s" % (batch["batch_index"], "；".join(str(item) for item in unverified[:8])))
        if not result.get("source_manifest"):
            raise ValueError(f"第{batch['batch_index']}批缺少 source manifest，未保存不完整结果")
        expected_units = [(r["source_block_id"], unit) for r in batch.get("source_unit_ranges", []) for unit in r.get("unit_ids", [])]
        expected_unit_set = set(expected_units)
        returned_units = set()
        returned_sequence = []
        for item in result.get("source_manifest", []):
            block_id = str(item.get("source_block_id") or "")
            for unit in item.get("unit_ids", []):
                key = (block_id, str(unit))
                if key in returned_units:
                    raise ValueError(f"第{batch['batch_index']}批 source manifest 重复原文单元：{block_id}/{unit}")
                returned_units.add(key)
                returned_sequence.append(key)
        if expected_units and returned_sequence != expected_units:
            raise ValueError(f"第{batch['batch_index']}批 source manifest 顺序错误")
        if expected_units and returned_units != expected_unit_set:
            missing = sorted(expected_unit_set - returned_units)
            extra = sorted(returned_units - expected_unit_set)
            raise ValueError(f"第{batch['batch_index']}批 source manifest 覆盖错误：遗漏{missing[:5]}，多出{extra[:5]}")
        shot_units = []
        for shot in shots:
            block_id = str(shot.get("source_block_id") or "")
            for unit in shot.get("source_unit_ids") or []:
                shot_units.append((block_id, str(unit)))
        if len(shot_units) != len(set(shot_units)):
            raise ValueError(f"第{batch['batch_index']}批分镜重复覆盖原文单元")
        if expected_units and set(shot_units) != expected_unit_set:
            missing = sorted(expected_unit_set - set(shot_units))
            extra = sorted(set(shot_units) - expected_unit_set)
            raise ValueError(f"第{batch['batch_index']}批分镜 source_unit_ids 未完整覆盖批次原文：遗漏{missing[:5]}，多出{extra[:5]}")
        return shots

    def _publish_batch_state(self, state: dict, batch: dict, result: dict, shots: list[dict]) -> dict:
        index = int(batch["batch_index"])
        result_path = os.path.join(self._results_dir(state), f"batch_{index:03d}.json")
        result_dir = os.path.dirname(result_path)
        os.makedirs(result_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f"batch-{index}-", suffix=".json", dir=result_dir, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2); fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp, result_path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        batch["status"] = "completed"; batch["error"] = None
        state["completed_batches"] = sorted(set(state["completed_batches"] + [index]))
        state["failed_batches"] = [x for x in state["failed_batches"] if x != index]
        known = {str(item.get("shot_id")) for item in state.get("parsed_shots", [])}
        state["parsed_shots"] = sorted(
            state.get("parsed_shots", []) + [deepcopy(shot) for shot in shots if str(shot.get("shot_id")) not in known],
            key=lambda s: s.get("shot_id", ""))
        if result.get("cast"):
            state["cast"] = self._merge_cast(state.get("cast", []), result["cast"])
        state["current_batch"] = None; state["current_prompt_id"] = None
        if len(state["completed_batches"]) == len(state["batches"]): state["analysis_status"] = "complete"
        return self._touch(state)

    @staticmethod
    def _claim_matches(batch: dict, claim_token: str | None = None,
                       prompt_id: str | None = None) -> bool:
        if claim_token is not None and str(batch.get("claim_token") or "") != str(claim_token):
            return False
        if prompt_id is not None and str(batch.get("prompt_id") or "") != str(prompt_id):
            return False
        return True

    def commit_batch(self, batch_index: int, result: dict, claim_token: str | None = None,
                     prompt_id: str | None = None) -> dict:
        """Validate and publish one batch as one serialized transaction.

        Collection requests can arrive twice after a browser retry.  Keep the
        lock around loading, validation, the durable batch file, and the
        session update so the second request observes ``completed`` and
        returns the already-published state without appending its shots.
        """
        with self._claim_lock():
            return self._commit_batch_locked(batch_index, result, claim_token, prompt_id)

    def _commit_batch_locked(self, batch_index: int, result: dict,
                             claim_token: str | None = None,
                             prompt_id: str | None = None) -> dict:
        state = self.load(); index = int(batch_index)
        batch = next(b for b in state["batches"] if b["batch_index"] == index)
        if batch["status"] == "completed": return state
        if batch["status"] != "running":
            raise ValueError(f"第{index}批当前状态为 {batch['status']}，不能提交结果；请先继续或重试")
        if not self._claim_matches(batch, claim_token, prompt_id):
            raise ValueError(f"第{index}批分析请求已过期，未保存其结果")
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
        if not isinstance(result, dict):
            reject(f"第{index}批结果不是结构化对象，未保存不完整结果")
        result = deepcopy(result)
        expected_meta = self._batch_metadata(state, batch)
        for key, expected_value in expected_meta.items():
            actual = result.get(key)
            if actual is None:
                result[key] = expected_value
            elif actual != expected_value:
                reject(f"第{index}批结果不属于当前分析会话（{key} 不匹配）")
        expected_units = [(r["source_block_id"], unit) for r in batch.get("source_unit_ranges", []) for unit in r.get("unit_ids", [])]
        if not expected_units:
            reject(f"第{index}批没有可验证的原文 source unit，拒绝发布")
        shots = result.get("shots")
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
        result_path = os.path.join(self._results_dir(state), f"batch_{index:03d}.json")
        result_dir = os.path.dirname(result_path)
        os.makedirs(result_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f"batch-{index}-", suffix=".json", dir=result_dir, text=True)
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

    def fail_batch(self, batch_index: int, error: str, claim_token: str | None = None,
                   prompt_id: str | None = None) -> dict:
        """Fail only the still-running claim that reported the error.

        A cancelled request can finish after a retry has claimed the same
        batch.  The ownership check prevents that stale request from marking
        the new claim failed.
        """
        with self._claim_lock():
            state = self.load()
            batch = next(b for b in state["batches"] if b["batch_index"] == int(batch_index))
            if batch["status"] != "running" or not self._claim_matches(batch, claim_token, prompt_id):
                return state
            batch["status"] = "failed"; batch["retry_count"] += 1; batch["error"] = str(error)[:2000]
            if batch["batch_index"] not in state["failed_batches"]:
                state["failed_batches"].append(batch["batch_index"])
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
        with self._claim_lock():
            state = self.load()
            if not state:
                return {}
            running = next((b for b in state["batches"] if b["status"] == "running"), None)
            if not running:
                raise ValueError("当前没有可取消的分析任务")
            if batch_index is not None and running["batch_index"] != int(batch_index):
                raise ValueError("当前运行批次已变化，未取消其他任务")
            if prompt_id and running.get("prompt_id") != prompt_id:
                raise ValueError("取消请求不是当前分析 prompt，未取消其他任务")
            running["status"] = "pending"
            running["error"] = "已取消，可继续或重试"
            running["prompt_id"] = None
            state["cancelled"] = True
            state["current_batch"] = None
            state["current_prompt_id"] = None
            return self._touch(state)

    def recover_orphaned_running(self) -> dict:
        """Reconcile a crash between batch-result and session writes.

        A valid result file is a durable commit marker.  Publish it idempotently
        instead of turning the batch into a retryable failure; only an absent or
        invalid result is marked failed.
        """
        with self._claim_lock():
            state = self.load()
            if not state:
                return {}
            changed = False
            for batch in state["batches"]:
                if batch["status"] != "running":
                    continue
                result_path = os.path.join(self._results_dir(state), f"batch_{batch['batch_index']:03d}.json")
                result = None
                try:
                    with open(result_path, encoding="utf-8") as fh:
                        result = json.load(fh)
                    shots = self._validate_batch_result(batch, result, state)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    shots = None
                if shots is not None:
                    self._publish_batch_state(state, batch, result, shots)
                    state = self.load() or state
                    changed = False
                    continue
                batch["status"] = "failed"
                batch["error"] = "ComfyUI 重启后未找到有效的该批次结果，可重试"
                batch["retry_count"] += 1
                if batch["batch_index"] not in state["failed_batches"]:
                    state["failed_batches"].append(batch["batch_index"])
                state["current_batch"] = None
                state["current_prompt_id"] = None
                changed = True
            if changed:
                self._touch(state)
            return state

    def status(self) -> dict:
        state = self.load() or {}
        state["completed_shot_count"] = sum(b["shot_end"] - b["shot_start"] + 1 for b in state.get("batches", []) if b.get("status") == "completed")
        return state
