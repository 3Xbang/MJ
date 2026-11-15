from __future__ import annotations
from ai_film_editor_nodes.lib.models.assets import OutfitAsset
from ai_film_editor_nodes.lib.models.common import AssetStatus
from ai_film_editor_nodes.lib.persistence.database import init_db, get_session
from ai_film_editor_nodes.lib.persistence.orm_models import OutfitORM
from ai_film_editor_nodes.lib.utils.logger import get_logger
from ai_film_editor_nodes.lib.utils.model_checker import get_model_list
from datetime import datetime, timezone

logger = get_logger("AFE_OutfitAsset")


class AFE_OutfitAsset:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character": ("CHARACTER_ASSET",),
                "outfit_name": ("STRING", {"default": ""}),
                "outfit_prompt": ("STRING", {"multiline": True, "default": ""}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
            },
            "optional": {
                "seed": ("INT", {"default": -1, "min": -1, "max": 2**31 - 1}),
                "load_existing": ("BOOLEAN", {"default": False}),
                "outfit_id": ("STRING", {"default": ""}),
                "image_checkpoint": (get_model_list("checkpoints", "(未安装图片模型，ComfyUI Manager 搜索 flux1-dev)"),),
            }
        }

    RETURN_TYPES = ("OUTFIT_ASSET", "STRING")
    RETURN_NAMES = ("outfit", "outfit_id")
    FUNCTION = "create_or_load_outfit"
    CATEGORY = "AI Film Editor/Assets"

    def create_or_load_outfit(self, character, outfit_name, outfit_prompt, negative_prompt,
                               seed=-1, load_existing=False, outfit_id="", image_checkpoint=None):
        init_db()
        character_id = character["asset_id"]
        if load_existing:
            if not outfit_id:
                raise ValueError("AFE_OutfitAsset: outfit_id is required when load_existing=True")
            with get_session() as session:
                row = session.get(OutfitORM, outfit_id)
            if row is None:
                raise ValueError(f"AFE_OutfitAsset: outfit_id '{outfit_id}' not found in database")
            asset = OutfitAsset.model_validate(row.data)
            logger.info(f"Loaded outfit: {asset.name} ({asset.asset_id})")
            return (asset.model_dump(), asset.asset_id)
        else:
            asset = OutfitAsset(
                name=outfit_name,
                character_id=character_id,
                outfit_prompt=outfit_prompt,
                negative_prompt=negative_prompt,
                status=AssetStatus.DRAFT,
            )
            row = OutfitORM(
                id=asset.asset_id,
                name=asset.name,
                character_id=asset.character_id,
                tags=asset.tags,
                status=asset.status,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                data=asset.model_dump(mode="json"),
            )
            with get_session() as session:
                session.merge(row)
            logger.info(f"Created outfit: {asset.name} ({asset.asset_id})")
            return (asset.model_dump(), asset.asset_id)
