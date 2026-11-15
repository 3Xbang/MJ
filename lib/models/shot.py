from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field

from ai_film_editor_nodes.lib.models.assets import Resolution
from ai_film_editor_nodes.lib.models.common import CameraAngle, CameraMotionEx, RenderStatus, RenderTier


class ShotDuration(BaseModel):
    """Duration specification for a shot expressed in frames and frames-per-second."""

    frames: int = 124
    fps: int = 24

    @computed_field  # type: ignore[misc]
    @property
    def seconds(self) -> float:
        """Return the duration in seconds derived from frames and fps."""
        return self.frames / self.fps

    def add_seconds(self, secs: float) -> ShotDuration:
        """Return a new ShotDuration extended by the given number of seconds."""
        return ShotDuration(frames=int((self.seconds + secs) * self.fps), fps=self.fps)


class ToneCompensation(BaseModel):
    """Parameters for colour and brightness normalisation between shots."""

    enabled: bool = True
    reference_frame_path: str | None = None
    brightness_offset: float = 0.0
    contrast_offset: float = 0.0
    color_temp_shift: float = 0.0


class ShotItem(BaseModel):
    """A single shot in the film sequence with all rendering parameters."""

    shot_id: str = Field(default_factory=lambda: str(uuid4()))
    sequence_index: int = 0
    label: str = ""
    duration: ShotDuration = Field(default_factory=ShotDuration)
    character_id: str | None = None
    outfit_id: str | None = None
    scene_id: str | None = None
    shot_prompt: str = ""
    negative_prompt: str = ""
    camera_motion: CameraMotionEx = CameraMotionEx.STATIC
    character_ids: list[str] = Field(default_factory=list)
    costume_per_character: dict[str, str] = Field(default_factory=dict)
    camera_angle: CameraAngle = CameraAngle.MEDIUM
    lighting_style: str = ""
    director_notes: str = ""
    shot_description: str = ""
    dialogue: str = ""
    seed: int = -1
    render_tier: RenderTier = RenderTier.FIRST_PASS
    resolution: Resolution = Field(default_factory=lambda: Resolution(width=640, height=360))
    tail_frame_input_path: str | None = None
    tail_frame_output_path: str | None = None
    tone_compensation: ToneCompensation = Field(default_factory=ToneCompensation)
    render_status: RenderStatus = RenderStatus.PENDING
    render_task_id: str | None = None
    output_video_path: str | None = None
    render_progress: float = 0.0
    error_message: str | None = None
    render_started_at: datetime | None = None
    render_finished_at: datetime | None = None
    extra: dict = Field(default_factory=dict)


class ShotSequence(BaseModel):
    """An ordered sequence of shots belonging to a project."""

    sequence_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    shots: list[ShotItem] = Field(default_factory=list)

    @computed_field  # type: ignore[misc]
    @property
    def total_frames(self) -> int:
        """Return the sum of all shot frame counts in the sequence."""
        return sum(s.duration.frames for s in self.shots)

    @computed_field  # type: ignore[misc]
    @property
    def total_seconds(self) -> float:
        """Return total duration in seconds across all shots."""
        fps = self.shots[0].duration.fps if self.shots else 24
        return self.total_frames / fps

    def get_shot_by_id(self, shot_id: str) -> ShotItem | None:
        """Return the ShotItem with the matching shot_id, or None."""
        for shot in self.shots:
            if shot.shot_id == shot_id:
                return shot
        return None

    def reindex(self) -> None:
        """Set each shot's sequence_index to its current position in the list."""
        for index, shot in enumerate(self.shots):
            shot.sequence_index = index
