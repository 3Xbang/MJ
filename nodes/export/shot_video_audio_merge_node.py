"""分镜音视频合并节点—用 FFmpeg 将视频和音频合并。"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess



def _file_sig(path):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_render_metadata(video_path):
    metadata_path = os.path.splitext(video_path)[0] + ".json"
    try:
        with open(metadata_path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


class AFE_ShotVideoAudioMerge:
    """
    分镜音视频合并节点。
    将视频文件和音频文件用 FFmpeg 合并。
    若无音频，直接输出原始视频路径。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_id":    ("STRING", {"default": "shot_001"}),
                "output_dir": ("STRING", {"default": "./projects/output/pass3"}),
            },
            "optional": {
                "audio_path": ("STRING", {"default": "",
                                          "tooltip": "来自 AFE_TTSGenerator 的音频文件路径"}),
                "video_filename_pattern": ("STRING", {"default": "{shot_id}_pass3.mp4",
                                                       "tooltip": "视频文件名模式，{shot_id}会被替换"}),
                "merge_output_dir": ("STRING", {"default": "./projects/output/merged"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("merged_video_path", "merge_status")
    FUNCTION = "merge_video_audio"
    CATEGORY = "AI Film Editor/Export"
    OUTPUT_NODE = True

    def merge_video_audio(self, shot_id, output_dir, audio_path="",
                          video_filename_pattern="{shot_id}_pass3.mp4",
                          merge_output_dir="./projects/output/merged"):
        video_filename = video_filename_pattern.format(shot_id=shot_id)
        video_path = os.path.join(output_dir, video_filename)

        if not os.path.exists(video_path):
            return ("", f"❌ 视频文件不存在：{video_path}")

        if not audio_path or not os.path.exists(audio_path):
            return (video_path, f"⚠️ 无音频文件，输出原始视频")

        os.makedirs(merge_output_dir, exist_ok=True)
        output_path = os.path.join(merge_output_dir, f"{shot_id}_merged.mp4")

        cmd = ["ffmpeg", "-y", "-i", video_path, "-i", audio_path,
               "-c:v", "copy", "-c:a", "aac", "-shortest", output_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                return (video_path, f"❌ FFmpeg 失败：{result.stderr[:200]}")
            source_meta = _load_render_metadata(video_path)
            merged_meta = dict(source_meta)
            merged_meta.update({
                "shot_id": shot_id,
                "merged_with_audio": True,
                "source_video": video_path,
                "source_render_sig": source_meta.get("sig"),
                "source_metadata_sig": _file_sig(os.path.splitext(video_path)[0] + ".json")
                    if os.path.exists(os.path.splitext(video_path)[0] + ".json") else "",
                "audio_sig": _file_sig(audio_path),
            })
            with open(os.path.splitext(output_path)[0] + ".json", "w", encoding="utf-8") as handle:
                json.dump(merged_meta, handle, ensure_ascii=False)
            try:
                def probe_dur(p):
                    r = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", p],
                        capture_output=True, text=True, timeout=10)
                    return float(r.stdout.strip()) if r.stdout.strip() else 0.0
                v_dur, a_dur = probe_dur(video_path), probe_dur(audio_path)
                status = f"✅ 合并完成：{shot_id}_merged.mp4 | 视频：{v_dur:.1f}s | 音频：{a_dur:.1f}s"
            except Exception:
                status = f"✅ 合并完成：{shot_id}_merged.mp4"
            return (output_path, status)
        except subprocess.TimeoutExpired:
            return (video_path, "❌ FFmpeg 超时")
        except FileNotFoundError:
            return (video_path, "❌ FFmpeg 未找到，请确保 FFmpeg 已安装并在 PATH 中")
        except Exception as e:
            return (video_path, f"❌ 异常：{e}")
