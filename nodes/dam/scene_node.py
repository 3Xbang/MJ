from __future__ import annotations
from ai_film_editor_nodes.lib.models.assets import SceneAsset
from ai_film_editor_nodes.lib.models.common import AssetStatus, SceneType
from ai_film_editor_nodes.lib.persistence.database import init_db, get_session
from ai_film_editor_nodes.lib.persistence.orm_models import SceneORM
from ai_film_editor_nodes.lib.utils.logger import get_logger
from datetime import datetime, timezone

logger = get_logger("AFE_SceneAsset")


class AFE_SceneAsset:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "scene_name": ("STRING", {"default": ""}),
                "background_prompt": ("STRING", {"multiline": True, "default": ""}),
                "scene_type": (["interior", "exterior", "abstract"],),
                "ambient_light": ("STRING", {"default": "natural"}),
            },
            "optional": {
                "seed": ("INT", {"default": -1, "min": -1, "max": 2**31 - 1}),
                "load_existing": ("BOOLEAN", {"default": False}),
                "scene_id": ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("SCENE_ASSET", "STRING")
    RETURN_NAMES = ("scene", "scene_id")
    FUNCTION = "create_or_load_scene"
    CATEGORY = "AI Film Editor/Assets"

    def create_or_load_scene(self, scene_name, background_prompt, scene_type, ambient_light,
                              seed=-1, load_existing=False, scene_id=""):
        init_db()
        if load_existing:
            if not scene_id:
                raise ValueError("AFE_SceneAsset: scene_id is required when load_existing=True")
            with get_session() as session:
                row = session.get(SceneORM, scene_id)
            if row is None:
                raise ValueError(f"AFE_SceneAsset: scene_id '{scene_id}' not found in database")
            asset = SceneAsset.model_validate(row.data)
            logger.info(f"Loaded scene: {asset.name} ({asset.asset_id})")
            return (asset.model_dump(), asset.asset_id)
        else:
            asset = SceneAsset(
                name=scene_name,
                scene_type=SceneType(scene_type),
                background_prompt=background_prompt,
                ambient_light=ambient_light,
                status=AssetStatus.DRAFT,
            )
            row = SceneORM(
                id=asset.asset_id,
                name=asset.name,
                scene_type=asset.scene_type,
                tags=asset.tags,
                status=asset.status,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                data=asset.model_dump(mode="json"),
            )
            with get_session() as session:
                session.merge(row)
            logger.info(f"Created scene: {asset.name} ({asset.asset_id})")
            return (asset.model_dump(), asset.asset_id)
