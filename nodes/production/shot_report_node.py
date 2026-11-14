import os
from datetime import datetime

class AFE_ShotReport:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
            },
            "optional": {
                "project_name": ("STRING", {"default": "AI Film Project"}),
                "output_path": ("STRING", {"default": "./output/shot_report.txt"}),
                "include_prompts": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("report",)
    FUNCTION = "generate_report"
    CATEGORY = "AI Film Editor/Production"
    OUTPUT_NODE = True

    def generate_report(self, shot_sequence, project_name="AI Film Project",
                        output_path="./output/shot_report.txt", include_prompts=True):
        total_duration = sum(s.get("duration", 0) for s in shot_sequence)
        lines = [
            f"项目：{project_name}",
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"总分镜数：{len(shot_sequence)}",
            f"总时长：{total_duration:.1f}秒",
            "",
            "━━━ 分镜列表 ━━━",
        ]
        for idx, shot in enumerate(shot_sequence):
            label = shot.get("label", f"Shot {idx+1}")
            duration = shot.get("duration", 0)
            frame_count = shot.get("frame_count", int(duration * 24))
            character = shot.get("character", {})
            character_name = character.get("name", "未指定") if isinstance(character, dict) else str(character)
            scene = shot.get("scene", {})
            scene_name = scene.get("name", "未指定") if isinstance(scene, dict) else str(scene)
            camera_motion = shot.get("camera_motion", "未指定")
            shot_prompt = shot.get("shot_prompt", shot.get("prompt", ""))

            lines.append(f"[{idx+1:02d}] {label}")
            lines.append(f"     时长：{duration:.1f}s / {frame_count}帧")
            lines.append(f"     角色：{character_name}")
            lines.append(f"     场景：{scene_name}")
            lines.append(f"     摄像机：{camera_motion}")
            if include_prompts and shot_prompt:
                lines.append(f"     提示词：{shot_prompt}")
            lines.append("")

        report = "\n".join(lines)

        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)
        except Exception as e:
            print(f"[AFE_ShotReport] Warning: could not save report to {output_path}: {e}")

        return (report,)
