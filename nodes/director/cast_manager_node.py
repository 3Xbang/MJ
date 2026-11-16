"""
AFE_CastManager — 演员表管理器（独立节点）

像导演组一样完全独立，不需要连接任何节点。
手动填写演员表，指定主角/配角/路人，
输出 CAST_DATA 供 Cast Analyzer 使用。

用法：
  · 把角色名填入对应的文本框
  · 每行一个角色名
  · 输出接到 Cast Analyzer 的 cast_data 输入
"""
from __future__ import annotations
import json
import logging

logger = logging.getLogger("AFE_CastManager")


def _parse_names(text: str) -> list[str]:
    """每行一个名字，去除空行和空白。"""
    return [line.strip() for line in text.splitlines() if line.strip()]


class AFE_CastManager:
    """
    演员表管理器 — 独立节点。

    手动填写剧本演员表：
      · 主角名单（lead）
      · 配角名单（supporting）
      · 路人名单（extra）

    输出标准 CAST_DATA，直接接 Cast Analyzer 的 cast_data 输入。
    不依赖 Script Parser 或 LLM，可在任意流程中独立使用。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lead_names": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "每行填一个主角名\n例：\n小宇",
                    "tooltip": "【主角】每行一个角色名",
                }),
                "supporting_names": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "每行填一个配角名\n例：\n小舟\n胖叔",
                    "tooltip": "【配角】每行一个角色名",
                }),
            },
            "optional": {
                "extra_a_names": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "【路人甲】每行一个角色名",
                }),
                "extra_b_names": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "【路人乙】每行一个角色名",
                }),
                "notes": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "备注（不影响输出，仅供记录）",
                }),
            },
        }

    RETURN_TYPES = ("CAST_DATA", "STRING")
    RETURN_NAMES = ("cast_data", "cast_report")
    FUNCTION = "manage_cast"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def manage_cast(
        self,
        lead_names: str = "",
        supporting_names: str = "",
        extra_a_names: str = "",
        extra_b_names: str = "",
        notes: str = "",
    ):
        # ── 解析各角色名单 ────────────────────────────────────────────────
        leads      = _parse_names(lead_names)
        supporting = _parse_names(supporting_names)
        extras_a   = _parse_names(extra_a_names)
        extras_b   = _parse_names(extra_b_names)

        cast_data: list[dict] = []
        idx = 1

        for name in leads:
            cast_data.append(_entry(idx, name, "lead"))
            idx += 1
        for name in supporting:
            cast_data.append(_entry(idx, name, "supporting"))
            idx += 1
        for name in extras_a:
            cast_data.append(_entry(idx, name, "extra_a"))
            idx += 1
        for name in extras_b:
            cast_data.append(_entry(idx, name, "extra_b"))
            idx += 1

        # ── 生成报告 ──────────────────────────────────────────────────────
        lines = [
            "🎭 演员表",
            "━" * 24,
            f"主角  {len(leads)} 人：{' / '.join(leads) if leads else '（未填）'}",
            f"配角  {len(supporting)} 人：{' / '.join(supporting) if supporting else '（未填）'}",
        ]
        if extras_a:
            lines.append(f"路人甲 {len(extras_a)} 人：{' / '.join(extras_a)}")
        if extras_b:
            lines.append(f"路人乙 {len(extras_b)} 人：{' / '.join(extras_b)}")
        lines.append("━" * 24)
        lines.append(f"共 {len(cast_data)} 人")

        if notes.strip():
            lines.append(f"\n📝 备注：{notes.strip()}")

        cast_report = "\n".join(lines)

        logger.info(
            "CastManager: lead=%d supporting=%d extra=%d",
            len(leads), len(supporting), len(extras_a) + len(extras_b),
        )

        return {
            "ui":    {"text": [cast_report]},
            "result": (cast_data, cast_report),
        }


def _entry(idx: int, name: str, role_type: str) -> dict:
    return {
        "character_id":       f"char_{idx:03d}",
        "name":               name,
        "role_type":          role_type,
        "gender":             "unknown",
        "age_range":          "",
        "appearance_en":      "",
        "default_costume_en": "",
        "costume_default":    "",
        "appearance":         "",
        "personality":        "",
        "shot_count":         0,
        "appearances":        [],
        "_source":            "manual",
    }
