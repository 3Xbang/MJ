"""AI Film Editor — ComfyUI custom node package."""
from __future__ import annotations
import sys, os

# 确保 custom_nodes 目录在 Python 路径中
_pkg_dir = os.path.dirname(os.path.abspath(__file__))
_custom_nodes_dir = os.path.dirname(_pkg_dir)
if _custom_nodes_dir not in sys.path:
    sys.path.insert(0, _custom_nodes_dir)

# Part 1 - Core DAM & Director
from ai_film_editor_nodes.nodes.dam.character_node import AFE_CharacterAsset
from ai_film_editor_nodes.nodes.dam.outfit_node import AFE_OutfitAsset
from ai_film_editor_nodes.nodes.dam.props_node import AFE_PropsAsset
from ai_film_editor_nodes.nodes.dam.scene_node import AFE_SceneAsset
from ai_film_editor_nodes.nodes.director.script_parser_node import AFE_ScriptParser
from ai_film_editor_nodes.nodes.director.shot_duration_node import AFE_ShotDuration
from ai_film_editor_nodes.nodes.director.shot_calculator_node import AFE_DirectorGroup, AFE_ShotCalculator
from ai_film_editor_nodes.nodes.director.tail_frame_node import AFE_TailFrameExtractor
from ai_film_editor_nodes.nodes.director.tone_comp_node import AFE_ToneCompensation
from ai_film_editor_nodes.nodes.adapters.video_adapter_node import AFE_VideoModelAdapter
from ai_film_editor_nodes.nodes.utils.prompt_preview_node import AFE_PromptPreview
from ai_film_editor_nodes.nodes.utils.model_checker_node import AFE_ModelChecker

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

# Part 5 - Consistency
from ai_film_editor_nodes.nodes.consistency.ipadapter_node import AFE_IPAdapterConfig
from ai_film_editor_nodes.nodes.consistency.controlnet_node import AFE_ControlNetPose

# Part 5 - Production
from ai_film_editor_nodes.nodes.production.transition_node import AFE_TransitionEffect
from ai_film_editor_nodes.nodes.production.subtitle_node import AFE_SubtitleOverlay
from ai_film_editor_nodes.nodes.production.colorgrade_node import AFE_ColorGrade
from ai_film_editor_nodes.nodes.production.quality_gate_node import AFE_QualityGate
from ai_film_editor_nodes.nodes.production.shot_report_node import AFE_ShotReport

# Part 6 - Cast & Shot Management
from ai_film_editor_nodes.nodes.dam.cast_manager_node import AFE_CastManager
from ai_film_editor_nodes.nodes.dam.expression_sheet_node import AFE_ExpressionSheet
from ai_film_editor_nodes.nodes.director.shot_unit_node import AFE_ShotUnit

# Part 7 - Director AI & Shot Chain
from ai_film_editor_nodes.nodes.director.shot_director_ai_node import AFE_ShotDirectorAI
from ai_film_editor_nodes.nodes.dam.character_view_prompt_node import AFE_CharacterViewPrompt
from ai_film_editor_nodes.nodes.director.shot_chain_node import AFE_ShotChain

# Part 8 - Production Bible, Auto Asset Pipeline, TTS, Shot Status
from ai_film_editor_nodes.nodes.director.production_bible_node import AFE_ProductionBible
from ai_film_editor_nodes.nodes.dam.auto_asset_pipeline_node import AFE_AutoAssetPipeline
from ai_film_editor_nodes.nodes.audio.tts_generator_node import AFE_TTSGenerator
from ai_film_editor_nodes.nodes.director.shot_status_node import AFE_ShotStatusBoard

# Part 9 - Character Consistency, Shot Batch Controller, Final Assembly, Project Manager
from ai_film_editor_nodes.nodes.consistency.character_consistency_node import AFE_CharacterConsistency
from ai_film_editor_nodes.nodes.director.shot_batch_controller_node import AFE_ShotBatchController
from ai_film_editor_nodes.nodes.export.final_assembly_node import AFE_FinalAssembly
from ai_film_editor_nodes.nodes.director.project_manager_node import AFE_ProjectManager

# Part 10 - Wan Optimizer, Shot Editor, Reference Image Manager, Shot Prompt Composer
from ai_film_editor_nodes.nodes.adapters.wan_prompt_optimizer_node import AFE_WanPromptOptimizer
from ai_film_editor_nodes.nodes.director.shot_editor_node import AFE_ShotEditor
from ai_film_editor_nodes.nodes.dam.reference_image_manager_node import AFE_ReferenceImageManager
from ai_film_editor_nodes.nodes.director.shot_prompt_composer_node import AFE_ShotPromptComposer

# Part 11 - Multi Character, Audio-Video Merge, Shot Preview
from ai_film_editor_nodes.nodes.consistency.multi_character_blend_node import AFE_MultiCharacterBlend
from ai_film_editor_nodes.nodes.export.shot_video_audio_merge_node import AFE_ShotVideoAudioMerge
from ai_film_editor_nodes.nodes.director.shot_preview_node import AFE_ShotPreview

# Part 12 - Analyzers
from ai_film_editor_nodes.nodes.analyzer.cast_analyzer_node import AFE_CastAnalyzer
from ai_film_editor_nodes.nodes.analyzer.costume_analyzer_node import AFE_CostumeAnalyzer
from ai_film_editor_nodes.nodes.analyzer.props_analyzer_node import AFE_PropsAnalyzer
from ai_film_editor_nodes.nodes.analyzer.scene_analyzer_node import AFE_SceneAnalyzer
from ai_film_editor_nodes.nodes.analyzer.shot_list_viewer_node import AFE_ShotListViewer
from ai_film_editor_nodes.nodes.analyzer.asset_selector_node import AFE_AssetSelector

# Part 13 - Batch Image Generation
from ai_film_editor_nodes.nodes.generation.batch_image_generator_node import AFE_BatchImageGenerator
from ai_film_editor_nodes.nodes.generation.single_asset_generator_node import AFE_SingleAssetGenerator

NODE_CLASS_MAPPINGS = {
    # Part 1
    "AFE_CharacterAsset": AFE_CharacterAsset,
    "AFE_OutfitAsset": AFE_OutfitAsset,
    "AFE_PropsAsset": AFE_PropsAsset,
    "AFE_SceneAsset": AFE_SceneAsset,
    "AFE_DirectorGroup": AFE_DirectorGroup,
    "AFE_ShotCalculator": AFE_DirectorGroup,  # 向后兼容
    "AFE_ScriptParser": AFE_ScriptParser,
    "AFE_ShotDuration": AFE_ShotDuration,
    "AFE_TailFrameExtractor": AFE_TailFrameExtractor,
    "AFE_ToneCompensation": AFE_ToneCompensation,
    "AFE_VideoModelAdapter": AFE_VideoModelAdapter,
    "AFE_PromptPreview": AFE_PromptPreview,
    "AFE_ModelChecker": AFE_ModelChecker,
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
    # Part 5
    "AFE_IPAdapterConfig": AFE_IPAdapterConfig,
    "AFE_ControlNetPose": AFE_ControlNetPose,
    "AFE_TransitionEffect": AFE_TransitionEffect,
    "AFE_SubtitleOverlay": AFE_SubtitleOverlay,
    "AFE_ColorGrade": AFE_ColorGrade,
    "AFE_QualityGate": AFE_QualityGate,
    "AFE_ShotReport": AFE_ShotReport,
    # Part 6 - Cast & Shot Management
    "AFE_CastManager": AFE_CastManager,
    "AFE_ExpressionSheet": AFE_ExpressionSheet,
    "AFE_ShotUnit": AFE_ShotUnit,
    # Part 7 - Director AI & Shot Chain
    "AFE_ShotDirectorAI": AFE_ShotDirectorAI,
    "AFE_CharacterViewPrompt": AFE_CharacterViewPrompt,
    "AFE_ShotChain": AFE_ShotChain,
    # Part 8 - Production Bible, Auto Asset Pipeline, TTS, Shot Status
    "AFE_ProductionBible": AFE_ProductionBible,
    "AFE_AutoAssetPipeline": AFE_AutoAssetPipeline,
    "AFE_TTSGenerator": AFE_TTSGenerator,
    "AFE_ShotStatusBoard": AFE_ShotStatusBoard,
    # Part 9
    "AFE_CharacterConsistency": AFE_CharacterConsistency,
    "AFE_ShotBatchController":  AFE_ShotBatchController,
    "AFE_FinalAssembly":        AFE_FinalAssembly,
    "AFE_ProjectManager":       AFE_ProjectManager,
    # Part 10 - Wan Optimizer, Shot Editor, Reference Image Manager, Shot Prompt Composer
    "AFE_WanPromptOptimizer":    AFE_WanPromptOptimizer,
    "AFE_ShotEditor":            AFE_ShotEditor,
    "AFE_ReferenceImageManager": AFE_ReferenceImageManager,
    "AFE_ShotPromptComposer":    AFE_ShotPromptComposer,
    # Part 11
    "AFE_MultiCharacterBlend":    AFE_MultiCharacterBlend,
    "AFE_ShotVideoAudioMerge":    AFE_ShotVideoAudioMerge,
    "AFE_ShotPreview":            AFE_ShotPreview,
    # Part 12 - Analyzers
    "AFE_CastAnalyzer":           AFE_CastAnalyzer,
    "AFE_CostumeAnalyzer":        AFE_CostumeAnalyzer,
    "AFE_PropsAnalyzer":          AFE_PropsAnalyzer,
    "AFE_SceneAnalyzer":          AFE_SceneAnalyzer,
    "AFE_ShotListViewer":         AFE_ShotListViewer,
    "AFE_AssetSelector":          AFE_AssetSelector,
    # Part 13 - Batch Generation
    "AFE_BatchImageGenerator":    AFE_BatchImageGenerator,
    "AFE_SingleAssetGenerator":   AFE_SingleAssetGenerator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # Part 1
    "AFE_CharacterAsset": "AFE Character Asset",
    "AFE_OutfitAsset": "AFE Outfit Asset",
    "AFE_PropsAsset": "🔧 Props Asset",
    "AFE_SceneAsset": "AFE Scene Asset",
    "AFE_DirectorGroup": "🎬 Director Group (导演组)",
    "AFE_ShotCalculator": "🎬 Director Group (导演组)",  # 向后兼容
    "AFE_ScriptParser": "AFE Script Parser",
    "AFE_ShotDuration": "AFE Shot Duration",
    "AFE_TailFrameExtractor": "AFE Tail Frame Extractor",
    "AFE_ToneCompensation": "AFE Tone Compensation",
    "AFE_VideoModelAdapter": "AFE Video Model Adapter",
    "AFE_PromptPreview": "AFE Prompt Preview",
    "AFE_ModelChecker": "🔍 Model Checker",
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
    # Part 5
    "AFE_IPAdapterConfig": "🎭 IP-Adapter Config (Character Consistency)",
    "AFE_ControlNetPose": "🦾 ControlNet Pose Control",
    "AFE_TransitionEffect": "✂️ Transition Effect",
    "AFE_SubtitleOverlay": "💬 Subtitle Overlay",
    "AFE_ColorGrade": "🎨 Color Grade",
    "AFE_QualityGate": "✅ Quality Gate",
    "AFE_ShotReport": "📋 Shot Report",
    # Part 6 - Cast & Shot Management
    "AFE_CastManager": "🎭 Cast Manager (演员表)",
    "AFE_ExpressionSheet": "😊 Expression Sheet (表情包)",
    "AFE_ShotUnit": "🎬 Shot Unit (单分镜控制器)",
    # Part 7 - Director AI & Shot Chain
    "AFE_ShotDirectorAI": "🎬 Shot Director AI (专业导演建议)",
    "AFE_CharacterViewPrompt": "👁️ Character View Prompt (角色视图提示词)",
    "AFE_ShotChain": "🔗 Shot Chain (尾帧接力)",
    # Part 8 - Production Bible, Auto Asset Pipeline, TTS, Shot Status
    "AFE_ProductionBible": "📋 Production Bible (制作手册)",
    "AFE_AutoAssetPipeline": "🏭 Auto Asset Pipeline (自动资产管线)",
    "AFE_TTSGenerator": "🎙️ TTS Generator (语音合成)",
    "AFE_ShotStatusBoard": "📊 Shot Status Board (分镜状态板)",
    "AFE_CharacterConsistency": "🎭 Character Consistency (角色一致性)",
    "AFE_ShotBatchController":  "🔄 Shot Batch Controller (分镜批控)",
    "AFE_FinalAssembly":        "🎞️ Final Assembly (最终合成)",
    "AFE_ProjectManager":       "📁 Project Manager (项目管理)",
    # Part 10
    "AFE_WanPromptOptimizer":    "⚡ Wan Prompt Optimizer (Wan提示词优化)",
    "AFE_ShotEditor":            "✏️ Shot Editor (分镜编辑器)",
    "AFE_ReferenceImageManager": "🖼️ Reference Image Manager (参考图管理)",
    "AFE_ShotPromptComposer":    "📝 Shot Prompt Composer (提示词合成器)",
    # Part 11
    "AFE_MultiCharacterBlend": "\U0001f465 Multi Character Blend (多角色混合)",
    "AFE_ShotVideoAudioMerge": "\U0001f3ac Shot Video Audio Merge (音视频合并)",
    "AFE_ShotPreview":         "\U0001f441\ufe0f Shot Preview (分镜预览)",
    # Part 12 - Analyzers
    "AFE_CastAnalyzer":        "👥 Cast Analyzer (人物分析器)",
    "AFE_CostumeAnalyzer":     "👗 Costume Analyzer (服装分析器)",
    "AFE_PropsAnalyzer":       "🔧 Props Analyzer (道具分析器)",
    "AFE_SceneAnalyzer":       "🌄 Scene Analyzer (场景分析器)",
    "AFE_ShotListViewer":      "🎬 Shot List Viewer (分镜列表)",
    "AFE_AssetSelector":       "🎯 Asset Selector (资产选择器)",
    # Part 13 - Batch Generation
    "AFE_BatchImageGenerator": "🖼️ Batch Image Generator (批量图像生成)",
    "AFE_SingleAssetGenerator": "🎯 Single Asset Generator (单图重生成)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
