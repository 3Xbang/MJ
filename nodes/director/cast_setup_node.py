"""
AFE_CastSetup 鈥?婕斿憳琛ㄧ鐞嗗櫒锛堢嫭绔嬭妭鐐癸級

鍍忓婕旂粍涓€鏍峰畬鍏ㄧ嫭绔嬶紝涓嶉渶瑕佽繛鎺ヤ换浣曡妭鐐广€?鎵嬪姩濉啓婕斿憳琛紝鎸囧畾涓昏/閰嶈/璺汉锛?杈撳嚭 CAST_DATA 渚?Cast Analyzer 浣跨敤銆?
鐢ㄦ硶锛?  路 鎶婅鑹插悕濉叆瀵瑰簲鐨勬枃鏈
  路 姣忚涓€涓鑹插悕
  路 杈撳嚭鎺ュ埌 Cast Analyzer 鐨?cast_data 杈撳叆
"""
from __future__ import annotations
import json
import logging

logger = logging.getLogger("AFE_CastSetup")


def _parse_names(text: str) -> list[str]:
    """姣忚涓€涓悕瀛楋紝鍘婚櫎绌鸿鍜岀┖鐧姐€?""
    return [line.strip() for line in text.splitlines() if line.strip()]


class AFE_CastSetup:
    """
    婕斿憳琛ㄧ鐞嗗櫒 鈥?鐙珛鑺傜偣銆?
    鎵嬪姩濉啓鍓ф湰婕斿憳琛細
      路 涓昏鍚嶅崟锛坙ead锛?      路 閰嶈鍚嶅崟锛坰upporting锛?      路 璺汉鍚嶅崟锛坋xtra锛?
    杈撳嚭鏍囧噯 CAST_DATA锛岀洿鎺ユ帴 Cast Analyzer 鐨?cast_data 杈撳叆銆?    涓嶄緷璧?Script Parser 鎴?LLM锛屽彲鍦ㄤ换鎰忔祦绋嬩腑鐙珛浣跨敤銆?    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lead_names": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "姣忚濉竴涓富瑙掑悕\n渚嬶細\n灏忓畤",
                    "tooltip": "銆愪富瑙掋€戞瘡琛屼竴涓鑹插悕",
                }),
                "supporting_names": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "姣忚濉竴涓厤瑙掑悕\n渚嬶細\n灏忚垷\n鑳栧彅",
                    "tooltip": "銆愰厤瑙掋€戞瘡琛屼竴涓鑹插悕",
                }),
            },
            "optional": {
                "extra_a_names": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "銆愯矾浜虹敳銆戞瘡琛屼竴涓鑹插悕",
                }),
                "extra_b_names": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "銆愯矾浜轰箼銆戞瘡琛屼竴涓鑹插悕",
                }),
                "notes": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "澶囨敞锛堜笉褰卞搷杈撳嚭锛屼粎渚涜褰曪級",
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
        # 鈹€鈹€ 瑙ｆ瀽鍚勮鑹插悕鍗?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
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

        # 鈹€鈹€ 鐢熸垚鎶ュ憡 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        lines = [
            "馃幁 婕斿憳琛?,
            "鈹? * 24,
            f"涓昏  {len(leads)} 浜猴細{' / '.join(leads) if leads else '锛堟湭濉級'}",
            f"閰嶈  {len(supporting)} 浜猴細{' / '.join(supporting) if supporting else '锛堟湭濉級'}",
        ]
        if extras_a:
            lines.append(f"璺汉鐢?{len(extras_a)} 浜猴細{' / '.join(extras_a)}")
        if extras_b:
            lines.append(f"璺汉涔?{len(extras_b)} 浜猴細{' / '.join(extras_b)}")
        lines.append("鈹? * 24)
        lines.append(f"鍏?{len(cast_data)} 浜?)

        if notes.strip():
            lines.append(f"\n馃摑 澶囨敞锛歿notes.strip()}")

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

