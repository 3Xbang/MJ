"""
AFE_CastListBuilder — 演员表管理器

客户手动管理演员表：
  · lead_names       指定主角（谁是主角）
  · supporting_names 指定配角（谁是配角）
  · extra_names      指定路人（谁是路人）
  · exclude_names    排除角色（不需要生成图的角色）
  · extra_cast       手动追加角色（剧本里没有但要生成的）

工作原理：
  1. 从 shot_sequence 提取所有出场角色（不遗漏）
  2. 与 LLM cast_data 合并（补充外貌描述）
  3. 客户指定的角色优先，未指定的自动按出镜次数推断
  4. 排除指定角色，追加手动角色
  5. 输出完整 CAST_DATA 给 Cast Analyzer
"""
from __future__ import annotations
import json
import logging

logger = logging.getLogger("AFE_CastListBuilder")

ROLE_LABELS = {
    "lead":        "★ 主角",
    "supporting":  "· 配角",
    "extra_a":     "· 路人甲",
    "extra_b":     "· 路人乙",
    "extra_other": "· 其他路人",
}


def _get_shots(shot_sequence) -> list:
    if isinstance(shot_sequence, list):
        return shot_sequence
    if isinstance(shot_sequence, dict):
        return shot_sequence.get("shots", [])
    if hasattr(shot_sequence, "shots"):
        return list(shot_sequence.shots)
    return []


def _parse_names(s: str) -> list[str]:
    """Parse comma-separated or newline-separated names, return ordered list."""
    result = []
    for sep in (",", "\n"):
        s = s.replace(sep, "||")
    for part in s.split("||"):
        name = part.strip()
        if name:
            result.append(name)
    return result


class AFE_CastListBuilder:
    """
    演员表管理器（客户手动管理版）。

    【增】extra_cast      手动追加角色（格式：角色名:角色类型，一行一个）
    【删】exclude_names   排除不需要的角色
    【改】lead_names      指定主角名单
         supporting_names 指定配角名单
         extra_names      指定路人名单

    未指定的角色自动按出镜次数推断主配角。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},   # 全部可选，独立节点，不依赖其他节点
            "optional": {
                "shot_sequence": ("SHOT_SEQUENCE", {
                    "tooltip": "（可选）连接 Script Parser 自动提取分镜角色",
                }),
                "cast_data": ("CAST_DATA", {
                    "tooltip": "（可选）连接 Script Parser 补充 LLM 外貌描述",
                }),
                "lead_names": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "【主角名单】每行一个名字\n例：\n小宇",
                }),
                "supporting_names": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "【配角名单】每行一个名字\n例：\n小舟\n胖叔",
                }),
                "extra_names": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "【路人名单】每行一个名字",
                }),
                "exclude_names": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "【排除名单】不需要生成图的角色，每行一个",
                }),
                "extra_cast": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": (
                        "【手动追加】剧本外或后期新增角色\n"
                        "格式：角色名:角色类型  每行一个\n"
                        "类型：lead / supporting / extra_a\n"
                        "例：\n老板:supporting\n替身演员:extra_a"
                    ),
                }),
                "lead_count": ("INT", {
                    "default": 1, "min": 1, "max": 10,
                    "tooltip": "未填名单时：出镜最多的前 N 人自动设为主角",
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
        shot_sequence=None,   # 可选 — 不连接时纯手动模式
        cast_data=None,
        lead_names: str = "",
        supporting_names: str = "",
        extra_names: str = "",
        exclude_names: str = "",
        extra_cast: str = "",
        lead_count: int = 1,
    ):
        shots = _get_shots(shot_sequence) if shot_sequence is not None else []

        # ── 1. 从分镜提取全部角色 ─────────────────────────────────────────
        name_shots:      dict[str, list] = {}
        name_costume:    dict[str, str]  = {}
        name_costume_en: dict[str, str]  = {}

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
                if not name_costume[name]    and costume:    name_costume[name]    = costume
                if not name_costume_en[name] and costume_en: name_costume_en[name] = costume_en

        # ── 2. 解析客户指定的名单 ─────────────────────────────────────────
        designated_leads      = _parse_names(lead_names)
        designated_supporting = _parse_names(supporting_names)
        designated_extras     = _parse_names(extra_names)
        exclude_set           = set(_parse_names(exclude_names))

        # 建立角色→指定类型的映射（方便查找）
        manual_role: dict[str, str] = {}
        for n in designated_leads:      manual_role[n] = "lead"
        for n in designated_supporting: manual_role[n] = "supporting"
        for n in designated_extras:     manual_role[n] = "extra_a"

        # ── 3. 是否使用手动模式 ───────────────────────────────────────────
        has_manual = bool(manual_role)

        # ── 4. LLM cast_data 查找表 ──────────────────────────────────────
        llm_map: dict[str, dict] = {}
        if cast_data:
            for char in cast_data:
                n = char.get("name", "").strip()
                if n:
                    llm_map[n] = char

        # ── 5. 按出镜次数排序（自动模式依据） ────────────────────────────
        sorted_names = sorted(
            name_shots.keys(), key=lambda n: len(name_shots[n]), reverse=True
        )

        # ── 6. 合并构建角色表 ─────────────────────────────────────────────
        merged: list[dict] = []
        seen_names: set[str] = set()

        for idx, name in enumerate(sorted_names):
            if name in exclude_set:
                continue                     # 【删】排除指定角色

            llm = llm_map.get(name, {})

            # role_type 优先级: 客户手动 > LLM > 自动推断
            if name in manual_role:
                role_type = manual_role[name]
            elif llm.get("role_type"):
                role_type = llm["role_type"]
            elif idx < lead_count:
                role_type = "lead"
            elif idx < lead_count + 4:
                role_type = "supporting"
            else:
                role_type = "extra_a"

            merged.append(_build_entry(
                idx, name, role_type, llm,
                name_shots[name], name_costume.get(name, ""),
                name_costume_en.get(name, ""),
                source="LLM+shots" if name in llm_map else "shots_only",
            ))
            seen_names.add(name)

        # ── 7. 【增】手动追加额外角色 ─────────────────────────────────────
        extra_added = []
        for line in extra_cast.splitlines():
            line = line.strip()
            if not line:
                continue
            if ":" in line:
                parts = line.split(":", 1)
                ename, erole = parts[0].strip(), parts[1].strip()
            else:
                ename, erole = line, "supporting"

            if not ename or ename in seen_names or ename in exclude_set:
                continue

            valid_roles = {"lead","supporting","extra_a","extra_b","extra_other"}
            if erole not in valid_roles:
                erole = "supporting"

            merged.append(_build_entry(
                len(merged), ename, erole, {},
                [], "", "", source="manual_add",
            ))
            seen_names.add(ename)
            extra_added.append(ename)

        # ── 8. 生成报告 ───────────────────────────────────────────────────
        llm_names  = set(llm_map.keys())
        auto_added = set(name_shots.keys()) - llm_names - exclude_set

        mode = "手动指定" if has_manual else (
            f"自动（主角前{lead_count}名）" if shots else "纯手动模式"
        )
        lines = [
            "🎭 演员表（管理完成）",
            f"   共 {len(merged)} 人  ·  分配模式：{mode}",
            f"   LLM：{len(llm_names&seen_names)}人  "
            f"自动补全：{len(auto_added&seen_names)}人  "
            f"手动追加：{len(extra_added)}人  "
            f"已排除：{len(exclude_set)}人",
            "━" * 28,
        ]
        if has_manual:
            if designated_leads:
                lines.append(f"   🎯 主角：{' / '.join(designated_leads)}")
            if designated_supporting:
                lines.append(f"   🎯 配角：{' / '.join(designated_supporting)}")
            if designated_extras:
                lines.append(f"   🎯 路人：{' / '.join(designated_extras)}")
            lines.append("━" * 28)

        for c in merged:
            role   = ROLE_LABELS.get(c["role_type"], c["role_type"])
            src    = {"LLM+shots":"✓LLM","shots_only":"⚠自动","manual_add":"✚手动"}.get(c["_source"],"")
            appear = c.get("appearance_en", "")
            lines.append(f"{role}  {c['name']}  {src}  出镜{c['shot_count']}次")
            if appear:
                lines.append(f"      {appear[:70]}")

        if exclude_set:
            lines.append("━" * 28)
            lines.append(f"🚫 已排除：{', '.join(sorted(exclude_set))}")

        cast_report = "\n".join(lines)
        logger.info("CastListBuilder: total=%d  leads=%d  supp=%d  excl=%d",
                    len(merged),
                    sum(1 for c in merged if c["role_type"]=="lead"),
                    sum(1 for c in merged if c["role_type"]=="supporting"),
                    len(exclude_set))

        return {"ui": {"text": [cast_report]}, "result": (merged, cast_report)}


# ── Helpers ──────────────────────────────────────────────────────────────────
def _build_entry(idx, name, role_type, llm, shots, costume, costume_en, source):
    return {
        "character_id":       llm.get("character_id", f"char_{idx+1:03d}"),
        "name":               name,
        "role_type":          role_type,
        "gender":             llm.get("gender", "unknown"),
        "age_range":          llm.get("age_range", ""),
        "appearance_en":      llm.get("appearance_en", ""),
        "default_costume_en": llm.get("default_costume_en", costume_en),
        "costume_default":    costume,
        "appearance":         llm.get("appearance", ""),
        "personality":        llm.get("personality", ""),
        "shot_count":         len(shots),
        "appearances":        shots,
        "_source":            source,
    }
