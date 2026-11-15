from __future__ import annotations
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotPromptComposer")


class AFE_ShotPromptComposer:
    """
    分镜提示词合成器。
    整合所有资产信息，生成完整的视频生成提示词。
    输出直接连接到 WanTextEncode 或 CLIPTextEncode。

    工作流中位置：
    ShotUnit + 资产节点 → ShotPromptComposer → WanPromptOptimizer → WanTextEncode
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
                "shot_id":       ("STRING", {"default": "shot_001"}),
            },
            "optional": {
                "character":     ("CHARACTER_ASSET",),
                "outfit":        ("OUTFIT_ASSET",),
                "scene":         ("SCENE_ASSET",),
                "props":         ("PROPS_ASSET",),
                "director_notes_override": ("STRING", {"default": "",
                                                       "tooltip": "留空=用分镜原始导演备注"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("composed_prompt", "negative_prompt", "composition_report")
    FUNCTION = "compose_prompt"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def compose_prompt(self, shot_sequence, shot_id, character=None,
                       outfit=None, scene=None, props=None,
                       director_notes_override=""):
        def _get(d, key, default=""):
            return d.get(key, default) if isinstance(d, dict) else getattr(d, key, default)

        def _asset(a, key):
            if a is None: return ""
            return a.get(key, "") if isinstance(a, dict) else getattr(a, key, "")

        # Find shot
        shot_data = {}
        if shot_sequence:
            for s in shot_sequence:
                if _get(s, "shot_id", "") == shot_id:
                    shot_data = s
                    break
            if not shot_data:
                logger.warning(f"ShotPromptComposer: shot_id '{shot_id}' not found")

        # 1-7: Composition order
        char_part    = _asset(character, "appearance_description_en")
        outfit_part  = f"wearing {_asset(outfit, 'outfit_prompt')}" if outfit and _asset(outfit, "outfit_prompt") else ""
        action_part  = _get(shot_data, "shot_description", "") or _get(shot_data, "shot_prompt", "")
        scene_part   = _asset(scene, "background_prompt") if scene else _get(shot_data, "scene_name", "")
        props_part   = f"with {_asset(props, 'positive_prompt')}" if props and _asset(props, "positive_prompt") else ""
        lighting_part = _get(shot_data, "lighting_style", "")
        notes_part   = director_notes_override.strip() or _get(shot_data, "director_notes", "")

        composed_parts = [p for p in [char_part, outfit_part, action_part, scene_part,
                                      props_part, lighting_part, notes_part] if p.strip()]
        composed_prompt = ", ".join(composed_parts)

        # negative: merge all sources
        neg_parts = [
            _get(shot_data, "negative_prompt", ""),
            _asset(character, "negative_prompt") if character else "",
            _asset(outfit, "negative_prompt") if outfit else "",
            _asset(scene, "negative_prompt") if scene else "",
            _asset(props, "negative_prompt") if props else "",
        ]
        negative_prompt = "; ".join(p for p in neg_parts if p.strip())

        # Report
        char_name  = _asset(character, "name") or _asset(character, "character_name") or "无"
        outfit_name = _asset(outfit, "name") or _asset(outfit, "outfit_name") or "无"
        scene_name  = _asset(scene, "name") or _asset(scene, "scene_name") or _get(shot_data, "scene_name", "无")
        props_name  = _asset(props, "name") or _asset(props, "prop_name") or "无"
        composition_report = (
            f"📝 分镜 {shot_id} 提示词合成报告:\n"
            f"- 角色: {char_name if character else '无 (使用分镜数据)'}\n"
            f"- 服装: {outfit_name if outfit else '无'}\n"
            f"- 动作: 来自分镜 shot_description\n"
            f"- 场景: {'资产' if scene else '分镜 scene_name'}={scene_name}\n"
            f"- 道具: {props_name if props else '无'}\n"
            f"- 光线: {lighting_part or '未设置'}\n"
            f"- 导演备注: {'override' if director_notes_override.strip() else '分镜原始'}\n"
            f"合成段落数: {len(composed_parts)}\n"
            f"最终长度: {len(composed_prompt.split())} tokens"
        )

        logger.info(f"ShotPromptComposer: {shot_id} → {len(composed_parts)} parts, {len(composed_prompt.split())} tokens")
        return (composed_prompt, negative_prompt, composition_report)
