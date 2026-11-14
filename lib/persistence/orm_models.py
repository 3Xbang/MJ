from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_film_editor_nodes.lib.persistence.database import Base


class CharacterORM(Base):
    """SQLAlchemy ORM model for CharacterAsset persistence."""

    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    positive_prompt: Mapped[str | None] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    base_model_logical_name: Mapped[str | None] = mapped_column(Text)
    seed: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(Text, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    # Full Pydantic model_dump() stored for complete round-trip reconstruction
    data: Mapped[dict] = mapped_column(JSON, nullable=False)

    outfits: Mapped[list[OutfitORM]] = relationship(
        "OutfitORM", back_populates="character", lazy="select"
    )


class OutfitORM(Base):
    """SQLAlchemy ORM model for OutfitAsset persistence."""

    __tablename__ = "outfits"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    character_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("characters.id", ondelete="CASCADE"), nullable=True
    )
    tags: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(Text, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False)

    character: Mapped[CharacterORM | None] = relationship(
        "CharacterORM",
        back_populates="outfits",
    )


class SceneORM(Base):
    """SQLAlchemy ORM model for SceneAsset persistence."""

    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    scene_type: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(Text, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class PropsORM(Base):
    """SQLAlchemy ORM model for PropsAsset persistence."""

    __tablename__ = "props"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prop_type: Mapped[str | None] = mapped_column(Text)
    character_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(Text, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class ProjectORM(Base):
    """SQLAlchemy ORM model for ProjectState persistence."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    schema_version: Mapped[str] = mapped_column(Text, nullable=False, default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False)

    shots: Mapped[list[ShotORM]] = relationship(
        "ShotORM", back_populates="project", lazy="select"
    )


class ShotORM(Base):
    """SQLAlchemy ORM model for ShotItem persistence."""

    __tablename__ = "shots"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    render_status: Mapped[str] = mapped_column(Text, default="pending")
    render_tier: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)

    project: Mapped[ProjectORM | None] = relationship(
        "ProjectORM",
        back_populates="shots",
    )


class AudioORM(Base):
    """SQLAlchemy ORM model for AudioAsset persistence."""

    __tablename__ = "audio_assets"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    audio_type: Mapped[str] = mapped_column(Text, default="dialogue")
    file_path: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float] = mapped_column(default=0.0)
    transcript: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, default="zh")
    shot_id: Mapped[str | None] = mapped_column(Text)
    character_id: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
