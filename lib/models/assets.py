from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from ai_film_editor_nodes.lib.models.common import AssetStatus, RoleType, SceneType, ViewType


class PropType(StrEnum):
    """Classification of a prop asset by category."""

    WEAPON = "weapon"
    VEHICLE = "vehicle"
    FURNITURE = "furniture"
    ACCESSORY = "accessory"
    FOOD = "food"
    ELECTRONIC = "electronic"
    OTHER = "other"


class LoraConfig(BaseModel):
    """Configuration for a single LoRA model applied during generation."""

    model_logical_name: str
    strength_model: float = 0.8
    strength_clip: float = 0.8


class AssetVersion(BaseModel):
    """Snapshot of an asset at a specific point in its generation history."""

    version_id: str = Field(default_factory=lambda: str(uuid4()))
    version_tag: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    seed: int
    positive_prompt_snapshot: str
    output_image_path: str | None = None
    comfy_task_id: str | None = None
    extra_metadata: dict = Field(default_factory=dict)


class GeneratedView(BaseModel):
    """A single generated image representing a specific view of an asset."""

    view_id: str = Field(default_factory=lambda: str(uuid4()))
    view_type: ViewType
    custom_label: str | None = None
    image_path: str | None = None
    thumbnail_path: str | None = None
    seed: int = -1
    positive_prompt: str = ""
    negative_prompt: str = ""
    comfy_task_id: str | None = None
    model_logical_name: str = ""
    is_primary: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Resolution(BaseModel):
    """Width and height dimensions for a rendered frame or image."""

    width: int
    height: int

    def __str__(self) -> str:
        """Return a human-readable resolution string."""
        return f"{self.width}x{self.height}"


class CharacterAsset(BaseModel):
    """A managed character asset with views, versioning, and generation parameters."""

    asset_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    positive_prompt: str = ""
    negative_prompt: str = ""
    base_model_logical_name: str = "wan_i2v_14b_480p"
    lora_configs: list[LoraConfig] = Field(default_factory=list)
    seed: int = -1
    reference_image_path: str | None = None
    views: list[GeneratedView] = Field(default_factory=list)
    version_history: list[AssetVersion] = Field(default_factory=list)
    current_version_id: str | None = None
    role_type: RoleType = RoleType.SUPPORTING
    character_id_code: str = ""
    age_range: str = ""
    personality: str = ""
    appearance_description: str = ""
    appearance_description_en: str = ""
    tags: list[str] = Field(default_factory=list)
    status: AssetStatus = AssetStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def get_primary_view(self) -> GeneratedView | None:
        """Return the first view marked as primary, or None if none exists."""
        for view in self.views:
            if view.is_primary:
                return view
        return None

    def get_view(self, view_type: ViewType) -> GeneratedView | None:
        """Return the first view matching the given view_type, or None."""
        for view in self.views:
            if view.view_type == view_type:
                return view
        return None


class OutfitAsset(BaseModel):
    """A managed outfit asset associated with a character."""

    asset_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    character_id: str
    outfit_prompt: str = ""
    negative_prompt: str = ""
    base_model_logical_name: str = "wan_i2v_14b_480p"
    views: list[GeneratedView] = Field(default_factory=list)
    version_history: list[AssetVersion] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: AssetStatus = AssetStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SceneAsset(BaseModel):
    """A managed scene/background asset with environment metadata."""

    asset_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    scene_type: SceneType = SceneType.EXTERIOR
    background_prompt: str = ""
    negative_prompt: str = ""
    ambient_light: str = ""
    base_model_logical_name: str = "wan_i2v_14b_480p"
    views: list[GeneratedView] = Field(default_factory=list)
    version_history: list[AssetVersion] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: AssetStatus = AssetStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PropsAsset(BaseModel):
    """A managed prop asset with type classification and generation parameters."""

    asset_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    prop_type: PropType = PropType.OTHER
    positive_prompt: str = ""
    negative_prompt: str = ""
    seed: int = -1
    base_model_logical_name: str = "wan_i2v_14b_480p"
    character_id: str | None = None
    scene_id: str | None = None
    views: list[GeneratedView] = Field(default_factory=list)
    version_history: list[AssetVersion] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: AssetStatus = AssetStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
