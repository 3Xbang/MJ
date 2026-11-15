from __future__ import annotations
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_ProductionBible")

ROLE_TYPE_ORDER = ["lead", "supporting", "extra_a", "extra_b", "extra_other"]
ROLE_TYPE_LABELS = {
    "lead": "主角",
    "supporting": "配角",
    "extra_a": "路人甲",
    "extra_b": "路人乙",
    "extra_other": "其他路人",
}


class AFE_ProductionBible:
    """
    制作手册节点。汇总演员表和分镜表，输出完整的制作参考文档。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "cast_data": ("CAST_DATA",),
                "shot_sequence": ("SHOT_SEQUENCE",),
            },
            "optional": {
                "project_name": ("STRING", {"default": "我的影视项目"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("cast_summary", "shot_summary", "full_bible")
    FUNCTION = "generate_bible"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def generate_bible(self, cast_data, shot_sequence, project_name="我的影视项目"):
        def _get(d, k, default=""):
            return d.get(k, default) if isinstance(d, dict) else getattr(d, k, default)

        sep = "━" * 40

        # ── 演员表 ──────────────────────────────────────────
        cast_lines = [f"🎭 演员表 — {project_name}", sep]

        if cast_data:
            def _sort_key(c):
                rt = _get(c, "role_type", "extra_other")
                return ROLE_TYPE_ORDER.index(rt) if rt in ROLE_TYPE_ORDER else 99

            sorted_cast = sorted(cast_data, key=_sort_key)
            current_group = None
            for c in sorted_cast:
                rt = _get(c, "role_type", "extra_other")
                label = ROLE_TYPE_LABELS.get(rt, rt)
                if rt != current_group:
                    current_group = rt
                    cast_lines.append(f"\n【{label}】")

                name = _get(c, "name", "未知")
                cid = _get(c, "character_id", "")
                gender = _get(c, "gender", "unknown")
                age = _get(c, "age_range", "")
                appearance = _get(c, "appearance", "")
                costume = _get(c, "costume_default", "")
                cast_lines.append(f"  👤 {name} ({cid}) | {gender} {age}")
                desc = "     " + ("  ".join(p for p in [appearance, costume] if p))
                if desc.strip():
                    cast_lines.append(desc)

            total = len(cast_data)
            cast_lines.extend([
                sep,
                f"共 {total} 个角色 | 需生成视图约 {total * 5} 张",
            ])
        else:
            cast_lines.extend(["（无角色数据）", sep])

        cast_summary = "\n".join(cast_lines)

        # ── 分镜表 ──────────────────────────────────────────
        shot_lines = []
        if shot_sequence:
            total_duration = sum(_get(s, "duration_seconds", 5) for s in shot_sequence)
            shot_lines.append(
                f"🎬 分镜表 — 共 {len(shot_sequence)} 个分镜，总时长 {total_duration} 秒"
            )
            shot_lines.append(sep)
            for idx, shot in enumerate(shot_sequence):
                shot_id = _get(shot, "shot_id", f"shot_{idx + 1:03d}")
                label = _get(shot, "label", shot_id)
                duration = _get(shot, "duration_seconds", 5)
                camera_angle = _get(shot, "camera_angle", "")
                camera_motion = _get(shot, "camera_motion", "")
                shot_lines.append(
                    f"[{idx:02d}] {label:<18}| {duration}秒 | {camera_angle} | {camera_motion}"
                )
                chars = _get(shot, "character_ids", _get(shot, "characters", []))
                if chars:
                    char_str = ", ".join(chars) if isinstance(chars, list) else str(chars)
                    shot_lines.append(f"     角色：{char_str}")
                scene = _get(shot, "scene_name", _get(shot, "scene", ""))
                if scene:
                    shot_lines.append(f"     场景：{scene}")
                props = _get(shot, "props_list", _get(shot, "props", []))
                if props:
                    props_str = ", ".join(props) if isinstance(props, list) else str(props)
                    shot_lines.append(f"     道具：{props_str}")
                notes = _get(shot, "director_notes", "")
                if notes:
                    shot_lines.append(f"     导演备注：{notes}")
        else:
            shot_lines.append("（无分镜数据）")

        shot_summary = "\n".join(shot_lines)
        full_bible = cast_summary + "\n\n" + shot_summary

        logger.info(f"ProductionBible generated: {project_name}")
        return (cast_summary, shot_summary, full_bible)
