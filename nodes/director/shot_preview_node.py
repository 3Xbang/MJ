"""分镜预览节点—加载已生成的分镜视频/图片，在 ComfyUI 中预览。"""
from __future__ import annotations
import os
import torch
import numpy as np
from PIL import Image

class AFE_ShotPreview:
    """
    分镜预览节点。
    从输出目录加载指定分镜的截图（第一帧/最后一帧/中间帧），
    在 ComfyUI 中显示为 IMAGE。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_id":       ("STRING", {"default": "shot_001"}),
                "output_dir":    ("STRING", {"default": "./projects/output"}),
                "pass_to_view": (["pass1", "pass2", "pass3", "tail_frame"], {"default": "pass3"}),
                "frame_to_show": (["first", "middle", "last"], {"default": "middle"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("preview_image", "preview_status")
    FUNCTION = "load_preview"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = False

    def load_preview(self, shot_id, output_dir, pass_to_view="pass3", frame_to_show="middle"):
        blank = torch.zeros((1, 512, 512, 3), dtype=torch.float32)

        if pass_to_view == "tail_frame":
            file_path = os.path.join(output_dir, "tail_frames", f"{shot_id}_tail.png")
        else:
            file_path = os.path.join(output_dir, pass_to_view, f"{shot_id}_{pass_to_view}.mp4")

        if not os.path.exists(file_path):
            return (blank, f"❌ 文件未找到：{file_path}")

        ext = os.path.splitext(file_path)[1].lower()

        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            try:
                pil_img = Image.open(file_path).convert("RGB")
                arr = np.array(pil_img).astype(np.float32) / 255.0
                w, h = pil_img.size
                return (torch.from_numpy(arr).unsqueeze(0),
                        f"✅ 预览加载：{shot_id} | {pass_to_view} | 图片 | {w}×{h}")
            except Exception as e:
                return (blank, f"❌ 图片加载失败：{e}")

        elif ext in (".mp4", ".avi", ".mov", ".webm"):
            try:
                import imageio
                reader = imageio.get_reader(file_path)
                n_frames = reader.count_frames()
                if n_frames <= 0:
                    n_frames = 1
                idx = {"first": 0, "last": max(0, n_frames - 1),
                       "middle": n_frames // 2}.get(frame_to_show, n_frames // 2)
                frame = reader.get_data(idx)
                reader.close()
                pil_img = Image.fromarray(frame).convert("RGB")
                arr = np.array(pil_img).astype(np.float32) / 255.0
                return (torch.from_numpy(arr).unsqueeze(0),
                        f"✅ 预览加载：{shot_id} | {pass_to_view} | {frame_to_show}帧 ({idx}/{n_frames})")
            except ImportError:
                return (blank, "⚠️ imageio 未安装，请 pip install imageio[ffmpeg]")
            except Exception as e:
                return (blank, f"❌ 视频帧提取失败：{e}")
        else:
            return (blank, f"❌ 不支持的文件格式：{ext}")
