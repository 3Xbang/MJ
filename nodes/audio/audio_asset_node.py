from __future__ import annotations
from ai_film_editor_nodes.lib.models.audio import AudioAsset, AudioType
from ai_film_editor_nodes.lib.persistence.repositories.audio_repository import AudioRepository
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_AudioAsset")


class AFE_AudioAsset:
    """Create or load an AudioAsset and persist it to SQLite."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "asset_name": ("STRING", {"default": ""}),
                "audio_type": (["dialogue", "music", "sound_effect"],),
                "language": ("STRING", {"default": "zh"}),
            },
            "optional": {
                "audio_file": ("STRING", {"default": ""}),
                "transcript": ("STRING", {"default": "", "multiline": True}),
                "character": ("CHARACTER_ASSET",),
                "shot_id": ("STRING", {"default": ""}),
                "load_existing": ("BOOLEAN", {"default": False}),
                "asset_id": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("AUDIO_ASSET", "STRING", "STRING")
    RETURN_NAMES = ("audio", "asset_id", "transcript")
    FUNCTION = "create_or_load_audio"
    CATEGORY = "AI Film Editor/Audio"

    def create_or_load_audio(
        self,
        asset_name,
        audio_type,
        language="zh",
        audio_file="",
        transcript="",
        character=None,
        shot_id="",
        load_existing=False,
        asset_id="",
    ):
        repo = AudioRepository()

        if load_existing and asset_id:
            existing = repo.get(asset_id)
            if existing is not None:
                logger.info(f"Loaded audio asset: {existing.name} ({existing.asset_id})")
                return (existing.model_dump(mode="json"), existing.asset_id, existing.transcript or "")
            logger.warning(f"Audio asset '{asset_id}' not found; creating new one.")

        character_id = character.get("asset_id") if character else None

        audio = AudioAsset(
            name=asset_name,
            audio_type=AudioType(audio_type),
            language=language,
            file_path=audio_file if audio_file else None,
            transcript=transcript if transcript else None,
            shot_id=shot_id if shot_id else None,
            character_id=character_id,
        )
        repo.create(audio)
        logger.info(f"Created audio asset: {audio.name} ({audio.asset_id})")
        return (audio.model_dump(mode="json"), audio.asset_id, audio.transcript or "")
