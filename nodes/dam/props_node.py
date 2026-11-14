from __future__ import annotations

from datetime import datetime, timezone

from ai_film_editor_nodes.lib.models.assets import PropsAsset, PropType
from ai_film_editor_nodes.lib.models.common import AssetStatus
from ai_film_editor_nodes.lib.persistence.database import init_db, get_session
from ai_film_editor_nodes.lib.persistence.orm_models import PropsORM
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_PropsAsset")

# Prompt prefixes that describe each prop category for the generation model
_PROP_TYPE_PREFIXES: dict[str, str] = {
    "weapon": "detailed weapon prop, metallic finish, sharp edges, ",
    "vehicle": "detailed vehicle prop, transportation, ",
    "furniture": "detailed furniture prop, interior object, ",
    "accessory": "detailed accessory prop, wearable item, ",
    "food": "detailed food prop, cuisine, ",
    "electronic": "electronic device prop, tech gadget, ",
    "other": "detailed prop, ",
}


class AFE_PropsAsset:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prop_name": ("STRING", {"default": ""}),
                "prop_prompt": ("STRING", {"multiline": True, "default": ""}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                "prop_type": (["weapon", "vehicle", "furniture", "accessory", "food", "electronic", "other"],),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2**31 - 1}),
            },
            "optional": {
                "character": ("CHARACTER_ASSET",),
                "scene": ("SCENE_ASSET",),
                "load_existing": ("BOOLEAN", {"default": False}),
                "prop_id": ("STRING", {"default": ""}),
            },
        }

    RETURN_TYPES = ("PROPS_ASSET", "STRING")
    RETURN_NAMES = ("props", "prop_id")
    FUNCTION = "create_or_load_props"
    CATEGORY = "AI Film Editor/Assets"

    def create_or_load_props(
        self,
        prop_name: str,
        prop_prompt: str,
        negative_prompt: str,
        prop_type: str,
        seed: int = -1,
        character=None,
        scene=None,
        load_existing: bool = False,
        prop_id: str = "",
    ):
        init_db()

        if load_existing:
            if not prop_id:
                raise ValueError("AFE_PropsAsset: prop_id is required when load_existing=True")
            with get_session() as session:
                row = session.get(PropsORM, prop_id)
            if row is None:
                raise ValueError(f"AFE_PropsAsset: prop_id '{prop_id}' not found in database")
            asset = PropsAsset.model_validate(row.data)
            logger.info(f"Loaded prop: {asset.name} ({asset.asset_id})")
            return (asset.model_dump(), asset.asset_id)

        # Apply category-specific prompt prefix
        prefix = _PROP_TYPE_PREFIXES.get(prop_type, "detailed prop, ")
        full_prompt = prefix + prop_prompt if prop_prompt.strip() else prefix.rstrip(", ")

        character_id = character.get("asset_id") if character else None
        scene_id = scene.get("asset_id") if scene else None

        asset = PropsAsset(
            name=prop_name,
            prop_type=PropType(prop_type),
            positive_prompt=full_prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            character_id=character_id,
            scene_id=scene_id,
            status=AssetStatus.DRAFT,
        )

        row = PropsORM(
            id=asset.asset_id,
            name=asset.name,
            prop_type=asset.prop_type,
            character_id=asset.character_id,
            scene_id=asset.scene_id,
            tags=asset.tags,
            status=asset.status,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            data=asset.model_dump(mode="json"),
        )

        with get_session() as session:
            session.merge(row)

        logger.info(f"Created prop: {asset.name} ({asset.asset_id})")
        return (asset.model_dump(), asset.asset_id)
