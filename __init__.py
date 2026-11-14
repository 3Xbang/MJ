"""AI Film Editor — ComfyUI custom node package."""
from __future__ import annotations

# Part 1 - Core DAM & Director
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

# Part 2 - Refinement
from ai_film_editor_nodes.nodes.refinement.refinement_config_node import AFE_RefinementConfig
from ai_film_editor_nodes.nodes.refinement.second_pass_node import AFE_SecondPassAdapter
from ai_film_editor_nodes.nodes.refinement.face_enhancer_node import AFE_FaceEnhancer
from ai_film_editor_nodes.nodes.refinement.video_upscaler_node import AFE_VideoUpscaler

# Part 3 - Audio
from ai_film_editor_nodes.nodes.audio.audio_asset_node import AFE_AudioAsset
from ai_film_editor_nodes.nodes.audio.lip_sync_node import AFE_LipSyncConfig
from ai_film_editor_nodes.nodes.audio.audio_video_sync_node import AFE_AudioVideoSync

# Part 4 - Export
from ai_film_editor_nodes.nodes.export.shot_sequence_builder_node import AFE_ShotSequenceBuilder
from ai_film_editor_nodes.nodes.export.project_export_node import AFE_ProjectExport
from ai_film_editor_nodes.nodes.export.watermark_node import AFE_Watermark

NODE_CLASS_MAPPINGS = {
    # Part 1
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
    # Part 2
    "AFE_RefinementConfig": AFE_RefinementConfig,
    "AFE_SecondPassAdapter": AFE_SecondPassAdapter,
    "AFE_FaceEnhancer": AFE_FaceEnhancer,
    "AFE_VideoUpscaler": AFE_VideoUpscaler,
    # Part 3
    "AFE_AudioAsset": AFE_AudioAsset,
    "AFE_LipSyncConfig": AFE_LipSyncConfig,
    "AFE_AudioVideoSync": AFE_AudioVideoSync,
    # Part 4
    "AFE_ShotSequenceBuilder": AFE_ShotSequenceBuilder,
    "AFE_ProjectExport": AFE_ProjectExport,
    "AFE_Watermark": AFE_Watermark,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # Part 1
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
    # Part 2
    "AFE_RefinementConfig": "🎯 Refinement Config",
    "AFE_SecondPassAdapter": "🔄 Second Pass Adapter",
    "AFE_FaceEnhancer": "👤 Face Enhancer",
    "AFE_VideoUpscaler": "⬆️ Video Upscaler",
    # Part 3
    "AFE_AudioAsset": "🎵 Audio Asset",
    "AFE_LipSyncConfig": "👄 Lip Sync Config",
    "AFE_AudioVideoSync": "🔊 Audio Video Sync",
    # Part 4
    "AFE_ShotSequenceBuilder": "🎬 Shot Sequence Builder",
    "AFE_ProjectExport": "📤 Project Export",
    "AFE_Watermark": "💧 Watermark",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
