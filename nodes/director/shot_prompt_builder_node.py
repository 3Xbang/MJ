"""
AFE_ShotPromptBuilder - Shot Prompt Builder

For each shot in shot_sequence, builds a complete video generation prompt
by combining:
  - Shot action/description (from Script Parser)
  - Approved character appearance + costume (from Cast Analyzer / cast_data)
  - Scene, lighting, camera info
  - Style prompt (from Director Group)

Output is a JSON list of per-shot prompts compatible with
Wan / CogVideo / standard KSampler workflows.
"""
from __future__ import annotations
import json
import logging

logger = logging.getLogger("AFE_ShotPromptBuilder")

CAMERA_MOTION_EN = {
    "static":          "static shot",
    "pan_left":        "pan left",
    "pan_right":       "pan right",
    "zoom_in":         "zoom in",
    "zoom_out":        "zoom out",
    "tilt_up":         "tilt up",
    "tilt_down":       "tilt down",
    "orbit":           "orbit shot",
    "slow_push_in":    "slow push in",
    "slow_pull_back":  "slow pull back",
    "tracking_shot":   "tracking shot",
    "handheld":        "handheld",
}

CAMERA_ANGLE_EN = {
    "close_up":   "close-up",
    "medium":     "medium shot",
    "wide":       "wide shot",
    "low_angle":  "low angle",
    "high_angle": "high angle",
    "eye_level":  "eye level",
    "dutch":      "dutch angle",
}

DEFAULT_NEGATIVE = (
    "ugly, deformed, blurry, distorted, low quality, "
    "watermark, text, bad anatomy, extra limbs, "
    "cropped, worst quality, static image, no motion"
)


def _get_shots(shot_sequence) -> list:
    if isinstance(shot_sequence, list):
        return shot_sequence
    if isinstance(shot_sequence, dict):
        return shot_sequence.get("shots", [])
    if hasattr(shot_sequence, "shots"):
        return list(shot_sequence.shots)
    return []


def _build_cast_map(cast_data) -> dict:
    """name -> character dict"""
    result = {}
    if not cast_data:
        return result
    for char in cast_data:
        name = char.get("name", "").strip()
        if name:
            result[name] = char
    return result


def _char_description(name: str, cast_map: dict, shot_costume_en: str) -> str:
    """
    Build English character description for a shot.
    Priority: cast_data appearance_en > shot costume_en > generic
    """
    char = cast_map.get(name, {})
    appearance = char.get("appearance_en", "").strip()
    # Use shot-specific costume if available, else default from cast_data
    costume = shot_costume_en.strip() or char.get("default_costume_en", "").strip()

    if appearance and costume:
        return f"{appearance}, wearing {costume}"
    elif appearance:
        return appearance
    elif costume:
        return f"person wearing {costume}"
    else:
        return name


def _build_shot_prompt(shot: dict, cast_map: dict, style_suffix: str) -> dict:
    """Build positive + negative prompt for one shot."""
    shot_id    = shot.get("shot_id", "shot_000")
    label      = shot.get("label", "")
    desc       = shot.get("shot_description", "").strip()
    scene      = shot.get("scene_name", "").strip()
    lighting   = shot.get("lighting_style", "").strip()
    cam_angle  = CAMERA_ANGLE_EN.get(shot.get("camera_angle", ""), shot.get("camera_angle", ""))
    cam_motion = CAMERA_MOTION_EN.get(shot.get("camera_motion", ""), shot.get("camera_motion", ""))
    costume_en = shot.get("costume_en", "").strip()
    names      = shot.get("character_names", [])
    if not isinstance(names, list):
        names = [names] if names else []
    duration   = shot.get("duration_seconds", 5.0)
    dialogue   = shot.get("dialogue", "（无）")

    # Camera line
    cam_line = ", ".join(filter(None, [cam_motion, cam_angle]))

    # Character descriptions
    char_descs = []
    for name in names:
        name = str(name).strip()
        if name:
            d = _char_description(name, cast_map, costume_en)
            char_descs.append(d)

    # Assemble positive prompt
    parts = []
    if cam_line:
        parts.append(cam_line)
    if desc:
        parts.append(desc)
    elif scene:
        parts.append(scene)
    if char_descs:
        parts.append(", ".join(char_descs))
    if lighting:
        parts.append(lighting)
    if style_suffix.strip():
        parts.append(style_suffix.strip())

    positive = ". ".join(parts) if parts else "cinematic shot"
    negative = shot.get("negative_prompt", DEFAULT_NEGATIVE)
    if not negative.strip():
        negative = DEFAULT_NEGATIVE

    return {
        "shot_id":          shot_id,
        "label":            label,
        "duration_seconds": duration,
        "positive_prompt":  positive,
        "negative_prompt":  negative,
        "camera_angle":     cam_angle,
        "camera_motion":    cam_motion,
        "scene":            scene,
        "characters":       names,
        "dialogue":         dialogue,
    }


class AFE_ShotPromptBuilder:
    """
    Shot Prompt Builder - assembles per-shot video prompts.

    For each shot in shot_sequence:
      - Combines shot description, character appearance/costume, scene, lighting
      - Outputs a JSON list of shot prompts for Wan / video generation
      - Also outputs the first shot's prompt for quick testing

    Connect:
      shot_sequence <- Script Parser
      cast_data     <- Cast Analyzer (approved character data)
      style_suffix  <- Director Group style_prompt
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
            },
            "optional": {
                "cast_data": ("CAST_DATA",),
                "style_suffix": ("STRING", {
                    "default": "",
                    "tooltip": "Connect Director Group style_prompt here",
                }),
                "start_shot": ("INT", {
                    "default": 1, "min": 1, "max": 500,
                    "tooltip": "Start from shot number N (useful for resuming)",
                }),
                "end_shot": ("INT", {
                    "default": 0, "min": 0, "max": 500,
                    "tooltip": "End at shot number N (0 = all shots)",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "shots_prompts_json",   # All shots as JSON array
        "shot_count",           # Number of shots
        "first_positive",       # Shot 1 positive prompt (quick test)
        "first_negative",       # Shot 1 negative prompt
        "report",               # Text summary
    )
    FUNCTION = "build_prompts"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def build_prompts(
        self,
        shot_sequence,
        cast_data=None,
        style_suffix: str = "",
        start_shot: int = 1,
        end_shot: int = 0,
    ):
        shots    = _get_shots(shot_sequence)
        cast_map = _build_cast_map(cast_data)

        if not shots:
            msg = "No shots found in shot_sequence"
            return {"ui": {"text": [msg]},
                    "result": ("[]", 0, "", DEFAULT_NEGATIVE, msg)}

        # Slice shots by range
        s = max(0, start_shot - 1)
        e = end_shot if end_shot > 0 else len(shots)
        shots_slice = shots[s:e]

        # Build prompts
        result_shots = []
        for shot in shots_slice:
            sp = _build_shot_prompt(shot, cast_map, style_suffix)
            result_shots.append(sp)

        shots_json  = json.dumps(result_shots, ensure_ascii=False, indent=2)
        first_pos   = result_shots[0]["positive_prompt"] if result_shots else ""
        first_neg   = result_shots[0]["negative_prompt"] if result_shots else DEFAULT_NEGATIVE

        # Build report
        lines = [
            f"Shot Prompt Builder",
            f"Total: {len(result_shots)} shots  |  "
            f"Characters: {len(cast_map)}  |  "
            f"Style: {style_suffix[:40] + '...' if len(style_suffix) > 40 else style_suffix}",
            "=" * 50,
        ]
        for sp in result_shots[:5]:   # preview first 5
            chars = ", ".join(sp["characters"]) if sp["characters"] else "none"
            lines.append(
                f"[{sp['shot_id']}] {sp['label']}\n"
                f"  Chars: {chars}\n"
                f"  Prompt: {sp['positive_prompt'][:80]}..."
            )
        if len(result_shots) > 5:
            lines.append(f"  ... and {len(result_shots)-5} more shots")

        report = "\n".join(lines)

        logger.info(
            "ShotPromptBuilder: %d shots, %d chars in cast_map",
            len(result_shots), len(cast_map)
        )

        return {
            "ui":    {"text": [report]},
            "result": (shots_json, len(result_shots), first_pos, first_neg, report),
        }
