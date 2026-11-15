from __future__ import annotations
import json
from ai_film_editor_nodes.lib.models.assets import CharacterAsset
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_CastManager")

ROLE_TYPE_LABELS = {
    "lead": "主角",
    "supporting": "配角",
    "extra_a": "路人甲",
    "extra_b": "路人乙",
    "extra_other": "其他路人",
}
ROLE_TYPE_ORDER = ["lead", "supporting", "extra_a", "extra_b", "extra_other"]


class AFE_CastManager:
    """
    演员表管理节点。接收 ScriptParser 输出的 cast_data，
    显示完整演员表，允许用户查看和筛选角色。
    输出指定角色的详细信息供资产生成使用。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "cast_data": ("CAST_DATA",),
                "select_character_id": ("STRING", {
                    "default": "char_001",
                    "tooltip": "填入要处理的角色ID，如 char_001"
                }),
            },
            "optional": {
                "filter_role_type": (
                    ["all", "lead", "supporting", "extra_a", "extra_b", "extra_other"],
                    {"default": "all"}
                ),
            }
        }

    RETURN_TYPES = ("CHARACTER_ASSET", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("character", "character_id", "cast_summary", "character_json")
    FUNCTION = "manage_cast"
    CATEGORY = "AI Film Editor/Cast"
    OUTPUT_NODE = True

    def manage_cast(self, cast_data, select_character_id, filter_role_type="all"):
        if not cast_data:
            warning = "⚠️ cast_data 为空，请先连接 AFE_ScriptParser 的 cast_data 输出"
            logger.warning(warning)
            empty = CharacterAsset(name="unknown").model_dump()
            return (empty, "", warning, "{}")

        filtered = [
            c for c in cast_data
            if filter_role_type == "all" or c.get("role_type") == filter_role_type
        ]

        def sort_key(c):
            rt = c.get("role_type", "extra_other")
            return ROLE_TYPE_ORDER.index(rt) if rt in ROLE_TYPE_ORDER else 99

        sorted_cast = sorted(filtered, key=sort_key)
        lines = ["🎭 演员表", "━" * 20]
        for c in sorted_cast:
            rt = c.get("role_type", "extra_other")
            label = ROLE_TYPE_LABELS.get(rt, rt)
            name = c.get("name", "未知")
            cid = c.get("character_id", "")
            gender = c.get("gender", "unknown")
            age = c.get("age_range", "")
            lines.append(f"{label}：{name} ({cid}) - {gender}，{age}")
        lines.extend(["━" * 20, f"共 {len(sorted_cast)} 个角色（筛选：{filter_role_type}）"])
        cast_summary = "\n".join(lines)

        selected = next(
            (c for c in cast_data if c.get("character_id") == select_character_id), None
        )
        if selected is None:
            cast_summary += f"\n⚠️ 未找到角色 {select_character_id}"
            logger.warning(f"Character {select_character_id} not found")
            empty = CharacterAsset(name="unknown").model_dump()
            return (empty, select_character_id, cast_summary, "{}")

        asset = CharacterAsset(
            name=selected.get("name", "unknown"),
            positive_prompt=selected.get("appearance_en", ""),
            role_type=selected.get("role_type", "supporting"),
            character_id_code=selected.get("character_id", ""),
            age_range=selected.get("age_range", ""),
            personality=selected.get("personality", ""),
            appearance_description=selected.get("appearance", ""),
            appearance_description_en=selected.get("appearance_en", ""),
        )
        character_json = json.dumps(selected, ensure_ascii=False, indent=2)
        logger.info(f"CastManager: selected {selected.get('name')} ({select_character_id})")
        return (asset.model_dump(), select_character_id, cast_summary, character_json)
