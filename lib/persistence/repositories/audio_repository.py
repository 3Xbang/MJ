from __future__ import annotations
from datetime import datetime, timezone
from ai_film_editor_nodes.lib.models.audio import AudioAsset
from ai_film_editor_nodes.lib.persistence.database import get_session, init_db
from ai_film_editor_nodes.lib.persistence.orm_models import AudioORM
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AudioRepository")


class AudioRepository:
    def __init__(self):
        init_db()

    def create(self, audio: AudioAsset) -> AudioAsset:
        row = AudioORM(
            id=audio.asset_id,
            name=audio.name,
            audio_type=audio.audio_type,
            file_path=audio.file_path,
            duration_seconds=audio.duration_seconds,
            transcript=audio.transcript,
            language=audio.language,
            shot_id=audio.shot_id,
            character_id=audio.character_id,
            tags=audio.tags,
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            data=audio.model_dump(mode="json"),
        )
        with get_session() as session:
            session.merge(row)
        return audio

    def get(self, asset_id: str) -> AudioAsset | None:
        with get_session() as session:
            row = session.get(AudioORM, asset_id)
        if row is None:
            return None
        return AudioAsset.model_validate(row.data)

    def update(self, audio: AudioAsset) -> AudioAsset:
        with get_session() as session:
            row = session.get(AudioORM, audio.asset_id)
            if row is None:
                raise ValueError(f"AudioAsset '{audio.asset_id}' not found")
            row.name = audio.name
            row.audio_type = audio.audio_type
            row.file_path = audio.file_path
            row.duration_seconds = audio.duration_seconds
            row.transcript = audio.transcript
            row.language = audio.language
            row.shot_id = audio.shot_id
            row.character_id = audio.character_id
            row.tags = audio.tags
            row.updated_at = datetime.now(timezone.utc)
            row.data = audio.model_dump(mode="json")
            session.merge(row)
        return audio

    def delete(self, asset_id: str) -> bool:
        with get_session() as session:
            row = session.get(AudioORM, asset_id)
            if row is None:
                return False
            session.delete(row)
        return True

    def list_all(self) -> list[AudioAsset]:
        from sqlalchemy import select
        with get_session() as session:
            rows = session.execute(select(AudioORM)).scalars().all()
        return [AudioAsset.model_validate(r.data) for r in rows]

    def list_by_shot(self, shot_id: str) -> list[AudioAsset]:
        from sqlalchemy import select
        with get_session() as session:
            rows = session.execute(
                select(AudioORM).where(AudioORM.shot_id == shot_id)
            ).scalars().all()
        return [AudioAsset.model_validate(r.data) for r in rows]

    def list_by_character(self, character_id: str) -> list[AudioAsset]:
        from sqlalchemy import select
        with get_session() as session:
            rows = session.execute(
                select(AudioORM).where(AudioORM.character_id == character_id)
            ).scalars().all()
        return [AudioAsset.model_validate(r.data) for r in rows]

    def search(self, query: str) -> list[AudioAsset]:
        from sqlalchemy import select
        q = f"%{query}%"
        with get_session() as session:
            rows = session.execute(
                select(AudioORM).where(
                    AudioORM.name.like(q) | AudioORM.transcript.like(q)
                )
            ).scalars().all()
        return [AudioAsset.model_validate(r.data) for r in rows]
