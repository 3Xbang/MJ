from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pydantic import BaseModel, Field


class AudioType(StrEnum):
    DIALOGUE = "dialogue"
    MUSIC = "music"
    SFX = "sound_effect"


class AudioAsset(BaseModel):
    asset_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    audio_type: AudioType = AudioType.DIALOGUE
    file_path: str | None = None
    duration_seconds: float = 0.0
    transcript: str | None = None
    language: str = "zh"
    shot_id: str | None = None
    character_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
