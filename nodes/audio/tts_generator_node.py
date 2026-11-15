from __future__ import annotations
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

import asyncio
import os
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_TTSGenerator")


class AFE_TTSGenerator:
    """
    TTS 语音合成节点。从分镜对白或自定义文本生成语音文件（MP3）。
    依赖 edge-tts 库（pip install edge-tts>=6.1.0）。
    """

    VOICES_ZH = {
        "晓晓(女)": "zh-CN-XiaoxiaoNeural",
        "云希(男)": "zh-CN-YunxiNeural",
        "云扬(男,沉稳)": "zh-CN-YunjianNeural",
        "晓伊(女)": "zh-CN-XiaoyiNeural",
        "晓涵(女)": "zh-CN-XiaohanNeural",
    }

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_sequence": ("SHOT_SEQUENCE",),
                "shot_id": ("STRING", {"default": "shot_001"}),
                "voice": (list(cls.VOICES_ZH.keys()), {"default": "晓晓(女)"}),
            },
            "optional": {
                "speed_rate": ("FLOAT", {
                    "default": -0.1,
                    "min": -0.5,
                    "max": 0.5,
                    "step": 0.05,
                }),
                "output_dir": ("STRING", {"default": "./projects/audio"}),
                "custom_text": ("STRING", {"default": "", "multiline": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("audio_path", "tts_status")
    FUNCTION = "generate_tts"
    CATEGORY = "AI Film Editor/Audio"
    OUTPUT_NODE = True

    def generate_tts(self, shot_sequence, shot_id, voice,
                     speed_rate=-0.1, output_dir="./projects/audio", custom_text=""):
        # 1) Find dialogue from shot_sequence by shot_id
        text = ""
        if shot_sequence:
            for shot in shot_sequence:
                if shot.get("shot_id") == shot_id or shot.get("label") == shot_id:
                    text = shot.get("dialogue", shot.get("narration", ""))
                    break

        # 2) Use custom_text if not empty
        if custom_text and custom_text.strip():
            text = custom_text.strip()

        # 3) Return warning if no text or placeholder
        if not text or text in ("（无）", "(无)"):
            warning = f"⚠️ 分镜 {shot_id} 没有对白/旁白文本，跳过 TTS 生成"
            logger.warning(warning)
            return ("", warning)

        # 4) Return error if edge_tts not available
        if not EDGE_TTS_AVAILABLE:
            error = "❌ edge-tts 未安装，请运行: pip install edge-tts>=6.1.0"
            logger.error(error)
            return ("", error)

        # 5) Build rate_str
        pct = int(speed_rate * 100)
        rate_str = f"+{pct}%" if pct >= 0 else f"{pct}%"

        # 6) Create output directory
        os.makedirs(output_dir, exist_ok=True)

        # 7) Build output path with sanitized voice name
        voice_key = voice.replace("(", "").replace(")", "").replace(",", "_")
        output_path = os.path.join(output_dir, f"{shot_id}_{voice_key}.mp3")

        # 8) Define async TTS generate function
        voice_id = self.VOICES_ZH.get(voice, "zh-CN-XiaoxiaoNeural")

        async def _generate(tts_text, tts_voice_id, tts_rate, tts_path):
            communicate = edge_tts.Communicate(tts_text, tts_voice_id, rate=tts_rate)
            await communicate.save(tts_path)

        # 9) Run TTS (wrapped in try/except per spec)
        try:
            asyncio.run(_generate(text, voice_id, rate_str, output_path))
        except Exception as e:
            error = f"❌ TTS 生成失败：{e}"
            logger.error(error)
            return ("", error)

        # 10) Return result
        status = (
            f"✅ 分镜{shot_id}语音已生成 | {voice} | 语速{rate_str} | 文件：{output_path}"
        )
        logger.info(status)
        return (output_path, status)
