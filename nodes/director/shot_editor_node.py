from __future__ import annotations
import copy
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ShotEditor")


class AFE_ShotEditor:
    """
    单分镜编辑器。
    允许用户修改任意分镜的参数，
    返回更新后的 shot_sequence。

    常见用途：
    - 修改时长（5秒 → 10秒）
    - 修改提示词描述
    - 更换运镜手法
    - 添加/移除道具
    - 调整角色服装描述
    """

    _NO_CHANGE_MOTION = "（不修改）"
    _NO_CHANGE_ANGLE  = "（不修改）"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
                "shot_id":       ("STRING", {"default": "shot_001"}),
            },
            "optional": {
                "new_duration_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 60.0,
                                                  "tooltip": "0=不修改，其他值=设置新时长"}),
                "new_shot_description": ("STRING", {"multiline": True, "default": "",
                                                   "tooltip": "留空=不修改"}),
                "new_negative_prompt":  ("STRING", {"default": ""}),
                "new_camera_motion":    (["（不修改）", "static", "pan_left", "pan_right",
                                         "zoom_in", "zoom_out", "slow_push_in",
                                         "slow_pull_back", "tracking_shot", "orbit",
                                         "crane_up", "crane_down", "handheld"],
                                        {"default": "（不修改）"}),
                "new_camera_angle":     (["（不修改）", "close_up", "medium", "wide",
                                         "low_angle", "high_angle", "eye_level", "dutch"],
                                        {"default": "（不修改）"}),
                "new_scene_name":       ("STRING", {"default": ""}),
                "new_director_notes":   ("STRING", {"multiline": True, "default": ""}),
                "new_seed":             ("INT", {"default": -1, "min": -1,
                                                "tooltip": "-1=不修改种子"}),
            }
        }

    RETURN_TYPES = ("SHOT_SEQUENCE", "STRING")
    RETURN_NAMES = ("updated_sequence", "edit_report")
    FUNCTION = "edit_shot"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def edit_shot(self, shot_sequence, shot_id, new_duration_seconds=0.0,
                  new_shot_description="", new_negative_prompt="",
                  new_camera_motion="（不修改）", new_camera_angle="（不修改）",
                  new_scene_name="", new_director_notes="", new_seed=-1):
        # 1. Deep copy to avoid mutating the original
        updated = copy.deepcopy(shot_sequence) if shot_sequence else []

        # 2. Find the target shot
        shot_data = None
        shot_index = -1
        for i, s in enumerate(updated):
            sid = s.get("shot_id", "") if isinstance(s, dict) else getattr(s, "shot_id", "")
            if sid == shot_id:
                shot_data = s
                shot_index = i
                break

        if shot_data is None:
            raise ValueError(f"AFE_ShotEditor: shot_id '{shot_id}' not found in sequence of {len(updated)} shots")

        def _get(d, key, default=""):
            return d.get(key, default) if isinstance(d, dict) else getattr(d, key, default)

        changes = []

        # 3. Apply only non-default values
        if new_duration_seconds != 0.0:
            old = _get(shot_data, "duration_seconds", "(未设置)")
            shot_data["duration_seconds"] = new_duration_seconds
            changes.append(f"- 时长: {old}秒 → {new_duration_seconds}秒")

        if new_shot_description.strip():
            old = _get(shot_data, "shot_description", "(空)")
            shot_data["shot_description"] = new_shot_description.strip()
            changes.append(f"- 描述: 已更新 ({len(old)} chars → {len(new_shot_description.strip())} chars)")

        if new_negative_prompt.strip():
            old = _get(shot_data, "negative_prompt", "(空)")
            shot_data["negative_prompt"] = new_negative_prompt.strip()
            changes.append(f"- 负面提示词: 已更新")

        if new_camera_motion != self._NO_CHANGE_MOTION:
            old = _get(shot_data, "camera_motion", "(未设置)")
            shot_data["camera_motion"] = new_camera_motion
            changes.append(f"- 运镜: {old} → {new_camera_motion}")

        if new_camera_angle != self._NO_CHANGE_ANGLE:
            old = _get(shot_data, "camera_angle", "(未设置)")
            shot_data["camera_angle"] = new_camera_angle
            changes.append(f"- 机位角度: {old} → {new_camera_angle}")

        if new_scene_name.strip():
            old = _get(shot_data, "scene_name", "(未设置)")
            shot_data["scene_name"] = new_scene_name.strip()
            changes.append(f"- 场景: {old} → {new_scene_name.strip()}")

        if new_director_notes.strip():
            shot_data["director_notes"] = new_director_notes.strip()
            changes.append(f"- 导演备注: 已更新")

        if new_seed != -1:
            old = _get(shot_data, "seed", -1)
            shot_data["seed"] = new_seed
            changes.append(f"- 种子: {old} → {new_seed}")

        if changes:
            edit_report = f"✏️ 已编辑分镜 {shot_id}:\n" + "\n".join(changes)
        else:
            edit_report = f"ℹ️ 分镜 {shot_id}：未修改任何字段（所有输入均为默认值）"

        logger.info(f"ShotEditor: {shot_id} — {len(changes)} field(s) changed")
        return (updated, edit_report)
