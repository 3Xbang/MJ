from __future__ import annotations

from enum import StrEnum


class RenderTier(StrEnum):
    """Defines the rendering quality tier for a shot."""

    FIRST_PASS = "first_pass"
    SECOND_PASS = "second_pass"
    THIRD_PASS = "third_pass"
    FINAL = "final"


class RenderStatus(StrEnum):
    """Lifecycle status of a render task."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CameraMotion(StrEnum):
    """Describes the camera movement style for a shot."""

    STATIC = "static"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    TILT_UP = "tilt_up"
    TILT_DOWN = "tilt_down"
    ORBIT = "orbit"


class SceneType(StrEnum):
    """Classification of a scene environment."""

    INTERIOR = "interior"
    EXTERIOR = "exterior"
    ABSTRACT = "abstract"


class AssetStatus(StrEnum):
    """Lifecycle status of a managed asset."""

    DRAFT = "draft"
    GENERATING = "generating"
    READY = "ready"
    ARCHIVED = "archived"


class ViewType(StrEnum):
    """Describes the perspective or framing of a generated asset view."""

    FRONT = "front"
    BACK = "back"
    LEFT_SIDE = "left_side"
    RIGHT_SIDE = "right_side"
    FACE_CLOSEUP = "face_closeup"
    FULLBODY = "fullbody"
    HALF_BODY = "half_body"
    DETAIL_CLOSEUP = "detail_closeup"
    FABRIC_TEXTURE = "fabric_texture"
    WIDE_SHOT = "wide_shot"
    MEDIUM_SHOT = "medium_shot"
    SCENE_DETAIL = "scene_detail"
    USAGE_STATE = "usage_state"
    CUSTOM = "custom"


class ModelType(StrEnum):
    """Type classification for a ComfyUI model file."""

    CHECKPOINT = "checkpoint"
    LORA = "lora"
    VAE = "vae"
    CLIP = "clip"
    CONTROLNET = "controlnet"
    UPSCALER = "upscaler"


class RoleType(StrEnum):
    """Character role hierarchy in a film production."""
    LEAD         = "lead"
    SUPPORTING   = "supporting"
    EXTRA_A      = "extra_a"
    EXTRA_B      = "extra_b"
    EXTRA_OTHER  = "extra_other"


class CameraAngle(StrEnum):
    """Camera angle classification for a shot."""
    CLOSE_UP     = "close_up"
    MEDIUM       = "medium"
    WIDE         = "wide"
    LOW_ANGLE    = "low_angle"
    HIGH_ANGLE   = "high_angle"
    EYE_LEVEL    = "eye_level"
    DUTCH        = "dutch"


class CameraMotionEx(StrEnum):
    """Extended camera motion types including cinematic moves."""
    STATIC        = "static"
    PAN_LEFT      = "pan_left"
    PAN_RIGHT     = "pan_right"
    ZOOM_IN       = "zoom_in"
    ZOOM_OUT      = "zoom_out"
    TILT_UP       = "tilt_up"
    TILT_DOWN     = "tilt_down"
    SLOW_PUSH_IN  = "slow_push_in"
    SLOW_PULL_BACK = "slow_pull_back"
    TRACKING_SHOT = "tracking_shot"
    CRANE_UP      = "crane_up"
    CRANE_DOWN    = "crane_down"
    ORBIT         = "orbit"
    HANDHELD      = "handheld"
