from __future__ import annotations
from ai_film_editor_nodes.lib.models.assets import CharacterAsset
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_AutoAssetPipeline")

ROLE_TYPE_ORDER = ["lead", "supporting", "extra_a", "extra_b", "extra_other"]
ROLE_TYPE_LABELS = {
    "lead": "主角",
    "supporting": "配角",
    "extra_a": "路人甲",
    "extra_b": "路人乙",
    "extra_other": "其他路人",
}

VIEW_PROMPTS = {
    "front_full":   "front view, full body, standing pose, character sheet",
    "back_full":    "back view, full body, standing pose, character sheet",
    "left_side":    "left side view, full body, standing pose, character sheet",
    "face_closeup": "close-up portrait, face detail, expression neutral, high detail",
    "half_body":    "medium shot, upper body, three-quarter view",
}


class AFE_AutoAssetPipeline:
    """
    自动资产管线节点。按角色序号自动选取角色，生成标准化角色资产和视图提示词。
    配合循环节点可批量生成所有角色的视图。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "cast_data": ("CAST_DATA",),
                "character_index": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 100,
                    "tooltip": "要处理的角色序号（0=第一个，通常是主角）",
                }),
            },
            "optional": {
                "view_type": (list(VIEW_PROMPTS.keys()), {"default": "front_full"}),
                "process_lead_only": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "True=只处理主角，False=处理所有角色",
                }),
            },
        }

    RETURN_TYPES = ("CHARACTER_ASSET", "STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("character", "character_id", "generation_prompt", "current_index", "total_count")
    FUNCTION = "auto_pipeline"
    CATEGORY = "AI Film Editor/Assets"
    OUTPUT_NODE = True

    def auto_pipeline(self, cast_data, character_index,
                      view_type="front_full", process_lead_only=False):
        def _empty_result(msg, idx=0, total=0):
            empty = CharacterAsset(name="unknown").model_dump()
            return (empty, "", msg, idx, total)

        if not cast_data:
            logger.warning("AutoAssetPipeline: cast_data 为空")
            return _empty_result("⚠️ cast_data 为空，请先连接 AFE_ScriptParser")

        # 1) Filter by lead if requested
        working = (
            [c for c in cast_data if c.get("role_type") == "lead"]
            if process_lead_only
            else list(cast_data)
        )

        if not working:
            logger.warning("AutoAssetPipeline: 筛选后无角色")
            return _empty_result("⚠️ 筛选后没有可处理的角色")

        # 2) Sort by ROLE_TYPE_ORDER
        def _sort_key(c):
            rt = c.get("role_type", "extra_other")
            return ROLE_TYPE_ORDER.index(rt) if rt in ROLE_TYPE_ORDER else 99

        sorted_cast = sorted(working, key=_sort_key)
        total_count = len(sorted_cast)

        # 3) Check index bounds
        if character_index >= total_count:
            status = f"⚠️ 角色序号 {character_index} 超出范围（共 {total_count} 个角色）"
            logger.warning(status)
            return _empty_result(status, character_index, total_count)

        # 4) Create CharacterAsset same way as cast_manager_node.py
        c = sorted_cast[character_index]
        asset = CharacterAsset(
            name=c.get("name", "unknown"),
            positive_prompt=c.get("appearance_en", ""),
            role_type=c.get("role_type", "supporting"),
            character_id_code=c.get("character_id", ""),
            age_range=c.get("age_range", ""),
            personality=c.get("personality", ""),
            appearance_description=c.get("appearance", ""),
            appearance_description_en=c.get("appearance_en", ""),
        )

        # 5) Build generation_prompt
        appearance_en = c.get("appearance_en", "")
        view_p = VIEW_PROMPTS.get(view_type, VIEW_PROMPTS["front_full"])
        generation_prompt = ", ".join(
            p for p in [appearance_en, view_p, "photorealistic, 8K, studio lighting, white background"]
            if p
        )

        # 6) Log progress
        rt = c.get("role_type", "extra_other")
        role_label = ROLE_TYPE_LABELS.get(rt, rt)
        name = c.get("name", "未知")
        logger.info(f"正在处理第 {character_index + 1}/{total_count} 个角色：{name}（{role_label}）")

        character_id = c.get("character_id", "")
        return (asset.model_dump(), character_id, generation_prompt, character_index, total_count)
