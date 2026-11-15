from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_AssetSelector")


def _asset_name(asset: dict) -> str:
    """Extract the best human-readable name from any analyzer asset dict."""
    for key in ("name", "character_name", "description"):
        val = asset.get(key, "")
        if val:
            return str(val)
    return f"资产{asset.get('index', '?')}"


class AFE_AssetSelector:
    """
    资产选择器。
    接受任意分析器（人物/服装/道具/场景）输出的 JSON 字符串，
    按编号选取单个资产，输出其 AI 提示词供生成节点直接使用。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "assets_json": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "tooltip": "来自任意 Analyzer 的 JSON 输出（characters_json / costumes_json / props_json / scenes_json）",
                }),
                "asset_index": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 200,
                    "tooltip": "选择第几个资产（从1开始）",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "asset_name", "asset_info")
    FUNCTION = "select_asset"
    CATEGORY = "AI Film Editor/Analyzers"
    OUTPUT_NODE = True

    def select_asset(self, assets_json: str, asset_index: int = 1):
        # Parse JSON
        try:
            assets = json.loads(assets_json)
        except (json.JSONDecodeError, ValueError) as exc:
            msg = f"❌ JSON 解析失败：{exc}"
            logger.error(msg)
            return ("", "", "", msg)

        if not isinstance(assets, list):
            msg = "❌ 输入必须是 JSON 数组（来自分析器的输出）"
            logger.error(msg)
            return ("", "", "", msg)

        if len(assets) == 0:
            msg = "⚠️ 资产列表为空，请先连接分析器节点"
            logger.warning(msg)
            return ("", "", "", msg)

        # Convert 1-based index to 0-based
        zero_idx = asset_index - 1
        if zero_idx < 0 or zero_idx >= len(assets):
            msg = (
                f"⚠️ 编号 {asset_index} 超出范围（共 {len(assets)} 个资产，"
                f"有效范围：1–{len(assets)}）"
            )
            logger.warning(msg)
            return ("", "", "", msg)

        asset = assets[zero_idx]

        positive_prompt = str(asset.get("positive_prompt", ""))
        negative_prompt = str(asset.get("negative_prompt", ""))
        name = _asset_name(asset)

        # Format detail info
        shots = asset.get("appears_in_shots", asset.get("appearances", []))
        shots_str = ", ".join(shots) if shots else "（无）"
        detail_lines = [
            f"✅ 已选：资产{asset_index} - {name}",
            f"  正面提示词：{positive_prompt}",
            f"  负面提示词：{negative_prompt}",
            f"  出现分镜：{shots_str}",
        ]
        # Include extra fields if present
        for field in ("role_type", "description", "lighting_style", "costume_description"):
            val = asset.get(field, "")
            if val:
                detail_lines.append(f"  {field}：{val}")
        asset_info = "\n".join(detail_lines)

        logger.info(f"AssetSelector: selected index={asset_index} name={name}")
        return (positive_prompt, negative_prompt, name, asset_info)
