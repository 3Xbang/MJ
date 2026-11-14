from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ai_film_editor_nodes.lib.models.assets import PropsAsset
from ai_film_editor_nodes.lib.models.common import AssetStatus
from ai_film_editor_nodes.lib.persistence.database import get_session, init_db
from ai_film_editor_nodes.lib.persistence.orm_models import PropsORM


class PropsRepository:
    """CRUD and query operations for PropsAsset persistence."""

    def __init__(self) -> None:
        init_db()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create(self, asset: PropsAsset) -> PropsAsset:
        """Persist a new PropsAsset and return it."""
        row = self._to_orm(asset)
        with get_session() as session:
            session.merge(row)
        return asset

    def update(self, asset: PropsAsset) -> PropsAsset:
        """Overwrite an existing PropsAsset record."""
        asset.updated_at = datetime.now(timezone.utc)
        row = self._to_orm(asset)
        with get_session() as session:
            session.merge(row)
        return asset

    def delete(self, asset_id: str) -> bool:
        """Delete a PropsAsset by ID. Returns True if the record existed."""
        with get_session() as session:
            row = session.get(PropsORM, asset_id)
            if row is None:
                return False
            session.delete(row)
        return True

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, asset_id: str) -> PropsAsset | None:
        """Return a PropsAsset by ID, or None if not found."""
        with get_session() as session:
            row = session.get(PropsORM, asset_id)
        if row is None:
            return None
        return PropsAsset.model_validate(row.data)

    def list_all(self) -> list[PropsAsset]:
        """Return all stored PropsAssets."""
        with get_session() as session:
            rows = session.execute(select(PropsORM)).scalars().all()
        return [PropsAsset.model_validate(r.data) for r in rows]

    def list_by_character(self, character_id: str) -> list[PropsAsset]:
        """Return all props associated with a given character ID."""
        with get_session() as session:
            rows = session.execute(
                select(PropsORM).where(PropsORM.character_id == character_id)
            ).scalars().all()
        return [PropsAsset.model_validate(r.data) for r in rows]

    def list_by_scene(self, scene_id: str) -> list[PropsAsset]:
        """Return all props associated with a given scene ID."""
        with get_session() as session:
            rows = session.execute(
                select(PropsORM).where(PropsORM.scene_id == scene_id)
            ).scalars().all()
        return [PropsAsset.model_validate(r.data) for r in rows]

    def search(self, query: str) -> list[PropsAsset]:
        """Return props whose name contains the query string (case-insensitive)."""
        with get_session() as session:
            rows = session.execute(
                select(PropsORM).where(PropsORM.name.ilike(f"%{query}%"))
            ).scalars().all()
        return [PropsAsset.model_validate(r.data) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_orm(asset: PropsAsset) -> PropsORM:
        return PropsORM(
            id=asset.asset_id,
            name=asset.name,
            prop_type=asset.prop_type,
            character_id=asset.character_id,
            scene_id=asset.scene_id,
            tags=asset.tags,
            status=asset.status,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
            data=asset.model_dump(mode="json"),
        )
