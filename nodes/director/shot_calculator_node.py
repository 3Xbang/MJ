from __future__ import annotations
from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger("AFE_DirectorGroup")

# ── Style mapping tables ──────────────────────────────────────────────────────

VISUAL_MAP = {
    "写实 Photorealistic": "photorealistic, hyper-realistic, film photography",
    "3D Animation": "3D animation, CGI rendered, Pixar style",
    "2D Animation / Anime": "2D animation, anime style, hand-drawn",
    "国风水墨 Chinese Ink": "Chinese ink painting style, traditional art",
    "赛博朋克 Cyberpunk": "cyberpunk style, neon lights, futuristic",
    "漫画 Comic / Manga": "comic book style, manga illustration",
    "油画 Oil Painting": "oil painting style, brushstroke texture",
    "简约扩散 Minimal": "minimalist style, clean composition",
}

PRODUCTION_MAP = {
    "电影 Movie": "movie cinematic style",
    "短视频 Short Video": "short video style",
    "广告片 Commercial": "commercial advertisement style",
    "动画片 Animation Film": "animation film style",
    "纪录片 Documentary": "documentary style",
    "MV 音乐视频": "music video style",
    "剧情短片 Drama": "drama short film style",
}

TIME_MAP = {
    "现代都市 Modern Urban": "modern urban setting, contemporary",
    "古代古装 Ancient Period": "ancient Chinese setting, period drama",
    "民国民初 Republican Era": "1930s China, Republican era",
    "未来科幻 Sci-Fi Future": "futuristic sci-fi setting",
    "年代感 Retro 70s-90s": "retro aesthetic, 1980s vibe",
    "战争年代 War Era": "wartime setting, historical drama",
    "当代校园 Campus": "modern campus, youth lifestyle",
    "古代仙侠 Wuxia Fantasy": "wuxia fantasy, martial arts world",
}

COLOR_MAP = {
    "自然 Natural": "natural color grading",
    "暖色调 Warm Tone": "warm color grading, golden tones",
    "冷色调 Cold Tone": "cold color grading, blue tones",
    "电影感 Cinematic Teal&Orange": "cinematic teal and orange color grading",
    "黑白 Film Noir": "black and white, film noir",
    "清新淡雅 Fresh & Clean": "fresh and clean, bright colors",
    "高富辉贵感 Luxury": "luxury aesthetic, rich colors",
}


class AFE_DirectorGroup:
    """
    导演组节点：分镜计算 + 制作风格设置。
    1. 输入总时长和每段时长，自动计算分镜总数
    2. 在 disabled_shots 填写要跳过的分镜编号
    3. 选择制作风格，输出 style_prompt 供提示词节点使用

    例：总180秒 ÷ 5秒 = 36个分镜
        disabled_shots = "3, 7, 15" → 跳过第3、7、15个
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "total_seconds": ("INT", {
                    "default": 180,
                    "min": 5,
                    "max": 7200,
                    "step": 5,
                    "tooltip": "视频总时长（秒）"
                }),
                "seconds_per_shot": ("INT", {
                    "default": 5,
                    "min": 1,
                    "max": 60,
                    "step": 1,
                    "tooltip": "每个分镜时长（秒），默认5秒"
                }),
                "visual_mode": (
                    [
                        "写实 Photorealistic", "3D Animation", "2D Animation / Anime",
                        "国风水墨 Chinese Ink", "赛博朋克 Cyberpunk",
                        "漫画 Comic / Manga", "油画 Oil Painting", "简约扩散 Minimal",
                    ],
                    {"default": "写实 Photorealistic"}
                ),
                "production_type": (
                    [
                        "电影 Movie", "短视频 Short Video", "广告片 Commercial",
                        "动画片 Animation Film", "纪录片 Documentary",
                        "MV 音乐视频", "剧情短片 Drama",
                    ],
                    {"default": "短视频 Short Video"}
                ),
                "time_period": (
                    [
                        "现代都市 Modern Urban", "古代古装 Ancient Period",
                        "民国民初 Republican Era", "未来科幻 Sci-Fi Future",
                        "年代感 Retro 70s-90s", "战争年代 War Era",
                        "当代校园 Campus", "古代仙侠 Wuxia Fantasy",
                    ],
                    {"default": "现代都市 Modern Urban"}
                ),
                "color_grading": (
                    [
                        "自然 Natural", "暖色调 Warm Tone", "冷色调 Cold Tone",
                        "电影感 Cinematic Teal&Orange", "黑白 Film Noir",
                        "清新淡雅 Fresh & Clean", "高富辉贵感 Luxury",
                    ],
                    {"default": "自然 Natural"}
                ),
                "art_quality": (
                    ["8K ultra detailed", "4K cinematic", "HD standard", "stylized artistic"],
                    {"default": "8K ultra detailed"}
                ),
            },
            "optional": {
                "disabled_shots": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "要跳过的分镜编号，逗号分隔。例：3, 7, 15"
                }),
                "start_from": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 500,
                    "tooltip": "从第几个分镜开始生成（续拍时用）"
                }),
            }
        }

    RETURN_TYPES = ("INT", "INT", "STRING", "STRING")
    RETURN_NAMES = ("shot_count", "seconds_per_shot", "instruction_text", "style_prompt")
    FUNCTION = "calculate"
    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    def calculate(
        self,
        total_seconds: int,
        seconds_per_shot: int,
        visual_mode: str = "写实 Photorealistic",
        production_type: str = "短视频 Short Video",
        time_period: str = "现代都市 Modern Urban",
        color_grading: str = "自然 Natural",
        art_quality: str = "8K ultra detailed",
        disabled_shots: str = "",
        start_from: int = 1,
    ) -> tuple:

        shot_count = total_seconds // seconds_per_shot
        remainder  = total_seconds % seconds_per_shot

        # ── Disabled shots ────────────────────────────────────────────────────
        disabled_set: set[int] = set()
        if disabled_shots.strip():
            for part in disabled_shots.split(","):
                part = part.strip()
                if part.isdigit():
                    disabled_set.add(int(part))

        # ── Shot grid display ─────────────────────────────────────────────────
        enabled_ids: list[int] = []
        rows: list[str] = []
        row: list[str] = []
        for i in range(1, shot_count + 1):
            if i in disabled_set:
                row.append(f"❌{i:02d}")
            elif i < start_from:
                row.append(f"⏭️{i:02d}")
            else:
                row.append(f"✅{i:02d}")
                enabled_ids.append(i)
            if len(row) == 8:
                rows.append("  ".join(row))
                row = []
        if row:
            rows.append("  ".join(row))

        # ── instruction_text for LLM ──────────────────────────────────────────
        instruction_text = (
            f"【分镜要求】请将以下剧本精确拆分为 {shot_count} 个分镜，"
            f"每个分镜时长固定为 {seconds_per_shot} 秒"
            f"（duration_seconds={seconds_per_shot}.0）。\n\n"
            f"以下是剧本内容：\n"
        )

        # ── style_prompt composition ──────────────────────────────────────────
        parts: list[str] = []
        if visual_mode in VISUAL_MAP:
            parts.append(VISUAL_MAP[visual_mode])
        if production_type in PRODUCTION_MAP:
            parts.append(PRODUCTION_MAP[production_type])
        if time_period in TIME_MAP:
            parts.append(TIME_MAP[time_period])
        if color_grading in COLOR_MAP:
            parts.append(COLOR_MAP[color_grading])
        parts.append(art_quality)
        style_prompt = ", ".join(parts)

        # ── Console output ────────────────────────────────────────────────────
        lines = [
            "🎬 导演组",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"总时长：{total_seconds}秒  每段：{seconds_per_shot}秒",
            f"分镜总数：{shot_count} 个",
        ]
        if remainder > 0:
            lines.append(f"剩余：{remainder}秒")
        lines.append(f"启用：{len(enabled_ids)} 个  跳过：{len(disabled_set)} 个")
        lines.append(f"风格提示词：{style_prompt}")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.extend(rows)
        print("\n".join(lines))

        logger.info(
            f"导演组：{total_seconds}s ÷ {seconds_per_shot}s = {shot_count}个 | 风格: {style_prompt}"
        )
        return (shot_count, seconds_per_shot, instruction_text, style_prompt)


# Backward-compatibility alias — existing workflows referencing AFE_ShotCalculator keep working
AFE_ShotCalculator = AFE_DirectorGroup
