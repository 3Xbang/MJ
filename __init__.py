"""AI Film Editor — ComfyUI custom node package."""
from __future__ import annotations

from ai_film_editor_nodes.nodes.dam.character_node import AFE_CharacterAsset
from ai_film_editor_nodes.nodes.dam.outfit_node import AFE_OutfitAsset
from ai_film_editor_nodes.nodes.dam.props_node import AFE_PropsAsset
from ai_film_editor_nodes.nodes.dam.scene_node import AFE_SceneAsset
from ai_film_editor_nodes.nodes.director.script_parser_node import AFE_ScriptParser
from ai_film_editor_nodes.nodes.director.shot_duration_node import AFE_ShotDuration
from ai_film_editor_nodes.nodes.director.tail_frame_node import AFE_TailFrameExtractor
from ai_film_editor_nodes.nodes.director.tone_comp_node import AFE_ToneCompensation
from ai_film_editor_nodes.nodes.adapters.video_adapter_node import AFE_VideoModelAdapter
from ai_film_editor_nodes.nodes.utils.prompt_preview_node import AFE_PromptPreview

NODE_CLASS_MAPPINGS = {
    "AFE_CharacterAsset": AFE_CharacterAsset,
    "AFE_OutfitAsset": AFE_OutfitAsset,
    "AFE_PropsAsset": AFE_PropsAsset,
    "AFE_SceneAsset": AFE_SceneAsset,
    "AFE_ScriptParser": AFE_ScriptParser,
    "AFE_ShotDuration": AFE_ShotDuration,
    "AFE_TailFrameExtractor": AFE_TailFrameExtractor,
    "AFE_ToneCompensation": AFE_ToneCompensation,
    "AFE_VideoModelAdapter": AFE_VideoModelAdapter,
    "AFE_PromptPreview": AFE_PromptPreview,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AFE_CharacterAsset": "AFE Character Asset",
    "AFE_OutfitAsset": "AFE Outfit Asset",
    "AFE_PropsAsset": "🔧 Props Asset",
    "AFE_SceneAsset": "AFE Scene Asset",
    "AFE_ScriptParser": "AFE Script Parser",
    "AFE_ShotDuration": "AFE Shot Duration",
    "AFE_TailFrameExtractor": "AFE Tail Frame Extractor",
    "AFE_ToneCompensation": "AFE Tone Compensation",
    "AFE_VideoModelAdapter": "AFE Video Model Adapter",
    "AFE_PromptPreview": "AFE Prompt Preview",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
