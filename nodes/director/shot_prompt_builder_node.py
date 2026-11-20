"""
AFE_ShotPromptBuilder - Shot Prompt Builder

For each shot in shot_sequence, builds a complete video generation prompt
by combining:
  - Shot action/description/business/emotion (from Script Parser)
  - Approved character appearance + costume (from Cast Analyzer / cast_data)
  - Scene, location, time_of_day, weather, lighting, camera info
  - Style prompt (from Director Group)

Output is a JSON list of per-shot prompts compatible with
Wan2.1 / CogVideo / standard KSampler workflows.
"""
from __future__ import annotations
import json
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotPromptBuilder")

# English translations for English camera_motion keys (original)
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

# English translations for English camera_angle keys (original)
CAMERA_ANGLE_EN = {
    "close_up":   "close-up",
    "medium":     "medium shot",
    "wide":       "wide shot",
    "low_angle":  "low angle",
    "high_angle": "high angle",
    "eye_level":  "eye level",
    "dutch":      "dutch angle",
}

# Shot type map — covers both Chinese and English input variations
SHOT_TYPE_MAP = {
    "特写":       "close-up",
    "近景":       "medium close-up",
    "中景":       "medium shot",
    "全景":       "full shot",
    "远景":       "wide shot",
    "close_up":   "close-up",
    "medium":     "medium shot",
    "wide":       "wide shot",
    "low_angle":  "low-angle shot",
    "high_angle": "high-angle shot",
    "eye_level":  "eye-level shot",
    "dutch":      "dutch angle",
}

# Chinese camera movement → English
CAM_MOVEMENT_CN = {
    "静止": "static",
    "推进": "push-in",
    "拉出": "pull-out",
    "横移": "pan",
    "跟随": "follow",
    "升":   "crane-up",
    "降":   "crane-down",
}

# Chinese camera angle → English
CAM_ANGLE_CN = {
    "平视": "eye-level",
    "俯拍": "top-down",
    "仰拍": "low-angle",
}

DEFAULT_NEGATIVE = (
    "blurry, distorted, low quality, watermark, text, bad anatomy, extra limbs, "
    "cropped, worst quality, static image, no motion, duplicate, deformed face, disfigured"
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


def _resolve_cam_motion(raw: str) -> str:
    """Resolve camera motion from Chinese or English key."""
    if not raw:
        return ""
    # Chinese → English first
    resolved = CAM_MOVEMENT_CN.get(raw, raw)
    # Then look up in English map (which adds descriptive suffix like "shot")
    return CAMERA_MOTION_EN.get(resolved, resolved)


def _resolve_cam_angle(raw: str) -> str:
    """Resolve camera angle from Chinese or English key."""
    if not raw:
        return ""
    # Chinese → English first
    resolved = CAM_ANGLE_CN.get(raw, raw)
    # Then look up shot type map or angle map
    return SHOT_TYPE_MAP.get(resolved, CAMERA_ANGLE_EN.get(resolved, resolved))


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
    """Build prompt_en + prompt_cn + negative for one shot."""
    shot_id    = shot.get("shot_id", "shot_000")
    label      = shot.get("label", "")
    scene      = shot.get("scene_name", "").strip()
    location   = shot.get("location", "").strip()
    time_of_day = shot.get("time_of_day", "").strip()
    weather    = shot.get("weather", "").strip()
    lighting   = shot.get("lighting", "").strip() or shot.get("lighting_style", "").strip()
    action     = shot.get("action", "").strip()
    business   = shot.get("business", "").strip()
    emotion    = shot.get("emotion", "").strip()
    cam_angle_raw  = shot.get("camera_angle", "")
    cam_motion_raw = shot.get("camera_motion", "")
    cam_angle  = _resolve_cam_angle(cam_angle_raw)
    cam_motion = _resolve_cam_motion(cam_motion_raw)
    costume_en = shot.get("costume_en", "").strip()
    names      = shot.get("character_names", [])
    if not isinstance(names, list):
        names = [names] if names else []
    duration   = shot.get("duration_seconds", 5.0)
    dialogue   = shot.get("dialogue", "（无）")

    # ── Build English prompt ──────────────────────────────────
    parts: list[str] = []

    # 1. Camera line
    cam_line = ", ".join(filter(None, [cam_motion, cam_angle]))
    if cam_line:
        parts.append(cam_line)

    # 2. Scene + location + time_of_day + weather
    scene_parts = [p for p in [scene, location, time_of_day, weather] if p]
    if scene_parts:
        parts.append(", ".join(scene_parts))

    # 3. Lighting
    if lighting:
        parts.append(lighting)

    # 4. Characters with appearance + costume
    char_descs = []
    for name in names:
        name = str(name).strip()
        if name:
            d = _char_description(name, cast_map, costume_en)
            char_descs.append(d)
    if char_descs:
        parts.append(", ".join(char_descs))

    # 5. Action
    if action:
        parts.append(action)

    # 6. Business (subtle physical detail)
    if business:
        parts.append(business)

    # 7. Emotion
    if emotion:
        parts.append(emotion)

    # 8. Dialogue (only if not empty / "（无）" / "none")
    _no_dialogue = {"（无）", "none", "(无)", ""}
    has_dialogue = dialogue.strip().lower() not in _no_dialogue
    if has_dialogue:
        parts.append(f'says: "{dialogue}"')

    # 9. Duration
    parts.append(f"{duration:.1f}s")

    # 10. Style suffix
    if style_suffix.strip():
        parts.append(style_suffix.strip())

    prompt_en = ". ".join(parts) if parts else "cinematic shot"

    # ── Build Chinese summary prompt ─────────────────────────
    char_names_cn = ", ".join(str(n) for n in names if n)
    cn_parts = [scene, char_names_cn, action, emotion]
    cn_base = "，".join(p for p in cn_parts if p)
    if has_dialogue:
        cn_base += f"，台词：{dialogue}"
    prompt_cn = cn_base if cn_base else label

    negative = shot.get("negative_prompt", DEFAULT_NEGATIVE)
    if not negative.strip():
        negative = DEFAULT_NEGATIVE

    return {
        "shot_id":          shot_id,
        "label":            label,
        "duration_seconds": duration,
        "prompt_en":        prompt_en,
        "prompt_cn":        prompt_cn,
        "negative_prompt":  negative,
        "camera_angle":     cam_angle,
        "camera_motion":    cam_motion,
        "scene":            scene,
        "characters":       names,
        "dialogue":         dialogue,
    }


class AFE_ShotPromptBuilder:
    """
    Shot Prompt Builder - assembles per-shot video prompts for Wan2.1.

    For each shot in shot_sequence:
      - Combines shot description, action, business, emotion, character appearance/costume,
        scene, location, time_of_day, weather, lighting, camera
      - Outputs a JSON list of shot prompts for Wan / video generation
      - Also outputs the first shot's EN + CN prompts for quick testing

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

    RETURN_TYPES = ("STRING", "INT", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "shots_prompts_json",   # All shots as JSON array
        "shot_count",           # Number of shots
        "first_prompt_en",      # Shot 1 English prompt (quick test)
        "first_prompt_cn",      # Shot 1 Chinese summary
        "first_negative",       # Shot 1 negative prompt
        "report",               # Text summary
    )
    FUNCTION = "build_prompts"
    CATEGORY = "AI Film Editor/Shot"
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
                    "result": ("[]", 0, "", "", DEFAULT_NEGATIVE, msg)}

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
        first_en    = result_shots[0]["prompt_en"] if result_shots else ""
        first_cn    = result_shots[0]["prompt_cn"] if result_shots else ""
        first_neg   = result_shots[0]["negative_prompt"] if result_shots else DEFAULT_NEGATIVE

        # Build report
        lines = [
            "Shot Prompt Builder",
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
                f"  EN: {sp['prompt_en'][:80]}...\n"
                f"  CN: {sp['prompt_cn'][:60]}"
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
            "result": (shots_json, len(result_shots), first_en, first_cn, first_neg, report),
        }
