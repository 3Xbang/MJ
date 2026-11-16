"""
AFE_CastListBuilder — 演员表构建器

解决 LLM 有时漏报角色的问题。

工作原理：
1. 从 shot_sequence 的每一个分镜里提取所有 character_names（完整来源）
2. 与 LLM 生成的 cast_data 进行合并
3. LLM 有数据的角色：保留完整的 appearance_en / role_type
4. LLM 漏掉的角色：按出镜次数自动推断 role_type，标记为待完善
5. 输出完整的 CAST_DATA，不遗漏任何出场角色

放置位置：Script Parser → CastListBuilder → Cast Analyzer
"""
from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_CastListBuilder")

ROLE_LABELS = {
    "lead":        "主角",
    "supporting":  "配角",
    "extra_a":     "路人甲",
    "extra_b":     "路人乙",
    "extra_other": "其他路人",
}


def _get_shots(shot_sequence) -> list:
    if isinstance(shot_sequence, list):
        return shot_sequence
    if isinstance(shot_sequence, dict):
        return shot_sequence.get("shots", [])
    if hasattr(shot_sequence, "shots"):
        return list(shot_sequence.shots)
    return []


class AFE_CastListBuilder:
    """
    演员表构建器。

    从 shot_sequence 中提取全部角色，与 LLM 的 cast_data 合并，
    按出镜次数自动推断主配角，确保演员表完整无遗漏。
    输出的 CAST_DATA 直接接 Cast Analyzer。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
            },
            "optional": {
                "cast_data": ("CAST_DATA", {
                    "tooltip": "来自 Script Parser 的 LLM 角色数据（可选，补充外貌描述）",
                }),
                "lead_names": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "主角名单，逗号分隔。例：小宇,张三  （空=自动按出镜次数判断）",
                }),
                "supporting_names": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "配角名单，逗号分隔。例：小舟,胖叔  （空=自动）",
                }),
                "lead_count": ("INT", {
                    "default": 1, "min": 1, "max": 10,
                    "tooltip": "未指定名单时：出镜最多的前 N 人为主角（lead_names 有值时此项被忽略）",
                }),
            },
        }

    RETURN_TYPES = ("CAST_DATA", "STRING")
    RETURN_NAMES = ("cast_data", "cast_report")
    FUNCTION = "build_cast_list"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def build_cast_list(
        self,
        shot_sequence,
        cast_data=None,
        lead_names: str = "",
        supporting_names: str = "",
        lead_count: int = 1,
    ):
        shots = _get_shots(shot_sequence)

        # ── 1. 从所有分镜提取角色名 + 出镜次数 + 首次服装 ───────────────────
        name_shots:   dict[str, list] = {}   # name → [shot_id, ...]
        name_costume: dict[str, str]  = {}   # name → first costume
        name_costume_en: dict[str, str] = {} # name → first costume_en

        for shot in shots:
            shot_id    = shot.get("shot_id") or shot.get("label", "")
            costume    = shot.get("costume_description", "").strip()
            costume_en = shot.get("costume_en", "").strip()
            names      = shot.get("character_names", [])
            if not isinstance(names, list):
                names = [names] if names else []

            for raw in names:
                name = str(raw).strip()
                if not name:
                    continue
                if name not in name_shots:
                    name_shots[name]      = []
                    name_costume[name]    = costume
                    name_costume_en[name] = costume_en
                name_shots[name].append(shot_id)
                if not name_costume[name]    and costume:
                    name_costume[name]    = costume
                if not name_costume_en[name] and costume_en:
                    name_costume_en[name] = costume_en

        if not name_shots:
            msg = "⚠️ 分镜中未找到任何角色名"
            logger.warning(msg)
            return {"ui": {"text": [msg]}, "result": ([], msg)}

        # ── 2. 解析导演指定的主配角名单 ───────────────────────────────────
        def _parse_names(s: str) -> set:
            return {n.strip() for n in s.split(",") if n.strip()}

        designated_leads       = _parse_names(lead_names)
        designated_supporting  = _parse_names(supporting_names)
        use_manual             = bool(designated_leads or designated_supporting)

        # ── 3. 按出镜次数排序（作为自动分配的依据）────────────────────────
        sorted_names = sorted(name_shots.keys(),
                               key=lambda n: len(name_shots[n]), reverse=True)

        # ── 3. 建立 LLM cast_data 的查找表 ────────────────────────────────
        llm_map: dict[str, dict] = {}
        if cast_data:
            for char in cast_data:
                n = char.get("name", "").strip()
                if n:
                    llm_map[n] = char

        # ── 4. 合并构建完整角色表 ──────────────────────────────────────────
        merged: list[dict] = []

        for idx, name in enumerate(sorted_names):
            llm = llm_map.get(name, {})
            shot_list = name_shots[name]

            # role_type 优先级：
            # 1. 导演手动指定（lead_names / supporting_names）
            # 2. LLM 给的 role_type
            # 3. 按出镜排名自动推断
            if use_manual:
                if name in designated_leads:
                    role_type = "lead"
                elif name in designated_supporting:
                    role_type = "supporting"
                elif llm.get("role_type"):
                    role_type = llm["role_type"]
                else:
                    # 未在名单里的：按出镜量推断
                    role_type = "extra_a" if idx >= lead_count + 3 else "supporting"
            elif llm.get("role_type"):
                role_type = llm["role_type"]
            elif idx < lead_count:
                role_type = "lead"
            elif idx < lead_count + 3:
                role_type = "supporting"
            else:
                role_type = "extra_a" if idx == lead_count + 3 else "extra_b"

            merged.append({
                "character_id":    llm.get("character_id", f"char_{idx+1:03d}"),
                "name":            name,
                "role_type":       role_type,
                "gender":          llm.get("gender", "unknown"),
                "age_range":       llm.get("age_range", ""),
                "appearance_en":   llm.get("appearance_en", ""),
                "default_costume_en": llm.get("default_costume_en",
                                              name_costume_en.get(name, "")),
                "costume_default": name_costume.get(name, ""),
                "appearance":      llm.get("appearance", ""),
                "personality":     llm.get("personality", ""),
                "shot_count":      len(shot_list),
                "appearances":     shot_list,
                "_source":         "LLM+shots" if name in llm_map else "shots_only",
            })

        # ── 5. 生成报告 ────────────────────────────────────────────────────
        llm_names  = set(llm_map.keys())
        found_all  = set(name_shots.keys())
        auto_added = found_all - llm_names

        mode_str = "手动指定" if use_manual else f"自动（主角前{lead_count}名）"
        lines = [
            "🎭 演员表（构建完成）",
            f"   共 {len(merged)} 人  |  分配模式：{mode_str}",
            f"   LLM提供：{len(llm_names)} 人  |  自动补全：{len(auto_added)} 人",
            "━" * 24,
        ]

        if use_manual and (designated_leads or designated_supporting):
            if designated_leads:
                lines.append(f"   🎯 指定主角：{', '.join(sorted(designated_leads))}")
            if designated_supporting:
                lines.append(f"   🎯 指定配角：{', '.join(sorted(designated_supporting))}")
            lines.append("━" * 24)

        for c in merged:
            role   = ROLE_LABELS.get(c["role_type"], c["role_type"])
            source = "✓ LLM" if c["_source"] == "LLM+shots" else "⚠ 自动补全"
            appear = c.get("appearance_en", "")
            lines.append(
                f"{'★' if c['role_type']=='lead' else '·'} {c['name']}"
                f"（{role}）{source}  出镜 {c['shot_count']} 次"
            )
            if appear:
                lines.append(f"    外貌：{appear[:70]}")
            elif c["_source"] == "shots_only":
                lines.append(f"    外貌：（LLM未生成，Cast Analyzer 将用服装描述替代）")
            if c.get("default_costume_en"):
                lines.append(f"    服装：{c['default_costume_en'][:60]}")

        if auto_added:
            lines.append("━" * 20)
            lines.append(f"💡 以下角色为 LLM 遗漏，已从分镜自动补全：")
            for n in sorted(auto_added, key=lambda x: -len(name_shots[x])):
                lines.append(f"   · {n}（出镜 {len(name_shots[n])} 次）")

        cast_report = "\n".join(lines)

        logger.info(
            "CastListBuilder: total=%d  llm=%d  auto=%d",
            len(merged), len(llm_names), len(auto_added),
        )

        return {
            "ui":    {"text": [cast_report]},
            "result": (merged, cast_report),
        }
