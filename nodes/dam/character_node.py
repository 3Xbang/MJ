from __future__ import annotations
import uuid
from ai_film_editor_nodes.lib.models.assets import CharacterAsset
from ai_film_editor_nodes.lib.models.common import AssetStatus
from ai_film_editor_nodes.lib.persistence.database import init_db, get_session
from ai_film_editor_nodes.lib.persistence.orm_models import CharacterORM
from ai_film_editor_nodes.lib.utils.logger import get_logger
from ai_film_editor_nodes.lib.utils.model_checker import get_model_list
from datetime import datetime, timezone

logger = get_logger("AFE_CharacterAsset")


class AFE_CharacterAsset:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "character_name": ("STRING", {"default": ""}),
                "positive_prompt": ("STRING", {"multiline": True, "default": ""}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2**31 - 1}),
                "image_checkpoint": (get_model_list("checkpoints", "(未安装图片模型，ComfyUI Manager 搜索 flux1-dev)"),),
            },
            "optional": {
                "reference_image": ("IMAGE",),
                "load_existing": ("BOOLEAN", {"default": False}),
                "character_id": ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("CHARACTER_ASSET", "STRING")
    RETURN_NAMES = ("character", "character_id")
    FUNCTION = "create_or_load_character"
    CATEGORY = "AI Film Editor/Assets"

    def create_or_load_character(self, character_name, positive_prompt, negative_prompt,
                                  seed, image_checkpoint, reference_image=None,
                                  load_existing=False, character_id=""):
        init_db()
        if load_existing:
            if not character_id:
                raise ValueError("AFE_CharacterAsset: character_id is required when load_existing=True")
            with get_session() as session:
                row = session.get(CharacterORM, character_id)
            if row is None:
                raise ValueError(f"AFE_CharacterAsset: character_id '{character_id}' not found in database")
            asset = CharacterAsset.model_validate(row.data)
            logger.info(f"Loaded character: {asset.name} ({asset.asset_id})")
            return (asset.model_dump(), asset.asset_id)
        else:
            asset = CharacterAsset(
                name=character_name,
                positive_prompt=positive_prompt,
                negative_prompt=negative_prompt,
                seed=seed,
                base_model_logical_name=image_checkpoint,
                status=AssetStatus.DRAFT,
            )
            row = CharacterORM(
                id=asset.asset_id,
                name=asset.name,
                positive_prompt=asset.positive_prompt,
                negative_prompt=asset.negative_prompt,
                base_model_logical_name=asset.base_model_logical_name,
                seed=asset.seed,
                tags=asset.tags,
                status=asset.status,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                data=asset.model_dump(mode="json"),
            )
            with get_session() as session:
                session.merge(row)
            logger.info(f"Created character: {asset.name} ({asset.asset_id})")
            return (asset.model_dump(), asset.asset_id)
