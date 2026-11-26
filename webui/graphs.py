"""
Turns one step of the web UI into a ComfyUI API prompt (a node graph).

Pure Python, no ComfyUI imports, so it can be unit-tested. Steps:
  1 analyze    script -> shots / cast / scenes / props   (LLM, saved to analysis.json)
  2 assets     scene images (3 views each), props images, character reference candidates
  3 keyframes  first frame of every shot (several versions, picks, redo)
  4 video      Wan 2.2 image-to-video for every shot
  5 movie      join the clips into the final film

The UI itself is the approval gate (the user presses the step button), so every generating node is
sent with approved=True. Nodes whose inputs did not change are served from ComfyUI's cache, and
every artifact on disk is keyed by a signature, so re-running a step only redoes what changed.
"""
from __future__ import annotations

DEFAULTS = {
    "script": "",
    "style": "3D cartoon Pixar animation style, vibrant colors, 8k",
    "episode": "迷你剧集 Mini Episode (5-10 min)",
    "duration": 180,
    "seconds_per_shot": 15,
    "seed": 42,
    # test mode: only the first N shots go through keyframes / video
    "test_mode": True,
    "test_shots": 2,
    # step 2
    "make_props": True,
    "cast_candidates": 3,
    "cast_picks": "",
    "cast_redo": "",
    "scene_view_picks": "",
    # step 3
    "kf_variants": 1,
    "kf_picks": "",
    "kf_redo": "",
    # step 4
    "fast": True,
    "video_width": 832,
    "video_height": 480,
    "long_takes": "",
    "shot_links": "",
    "video_redo": "",
    # step 5
    "skip_shots": "",
    "output_name": "final_movie",
}

STAGE_NAMES = {1: "分析剧本", 2: "生成素材", 3: "生成首帧", 4: "渲染视频", 5: "合成成片"}


def merged(settings: dict | None) -> dict:
    s = dict(DEFAULTS)
    for k, v in (settings or {}).items():
        if k in DEFAULTS and v is not None:
            s[k] = v
    return s


def _n(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def _max_shots(s: dict) -> int:
    return int(s["test_shots"]) if s["test_mode"] else 0


def build_prompt(stage: int, project: str, settings: dict | None, project_path: str,
                 part: str = "all", batch: dict | None = None, only_shot: str = "") -> tuple[dict, dict]:
    """Returns (api_prompt, labels). labels maps node id -> text shown while that node runs.

    part "cast" redraws characters only. part "kf" redraws the one keyframe named
    by only_shot. "all" runs the whole step."""
    s = merged(settings)
    g: dict[str, dict] = {}
    labels: dict[str, str] = {}
    style = s["style"]

    def loader():
        g["1"] = _n("AFE_AnalysisLoader", project_name=project)
        labels["1"] = "载入剧本分析结果"

    def analyzers():
        g["2"] = _n("AFE_SceneAnalyzer", shot_sequence=["1", 0])
        g["3"] = _n("AFE_PropsAnalyzer", shot_sequence=["1", 0])
        labels["2"] = "整理场景"
        labels["3"] = "整理道具"

    def scene_images():
        g["4"] = _n("AFE_SceneImageGenerator", scene_report=["2", 2], render_style=style,
                    scenes_json=["2", 0], width=1024, height=576, steps=20, cfg=1.0,
                    seed=int(s["seed"]), approved=True, project_name=project)
        labels["4"] = "绘制场景图（每个场景 3 张）"

    def cast_refs():
        g["6"] = _n("AFE_CastRefGenerator", cast_data=["1", 1], render_style=style, width=768,
                    height=1152, steps=8, seed=int(s["seed"]),
                    candidates_per_character=int(s["cast_candidates"]), picks=s["cast_picks"],
                    redo_characters=s["cast_redo"], project_name=project, approved=True)
        labels["6"] = "绘制角色参考图"

    if stage == 1:
        inputs = dict(raw_script=s["script"], render_style=style,
                      episode_format=s["episode"], target_duration_seconds=int(s["duration"]),
                      seconds_per_shot=int(s["seconds_per_shot"]), lighting_mood="auto (from script)",
                      color_palette="auto (from style)", model_path="LLM/Qwen2.5-7B-Instruct")
        if batch:
            inputs.update(batch_start_shot=int(batch["shot_start"]),
                          batch_end_shot=int(batch["shot_end"]),
                          batch_context_json=batch.get("context_json", ""))
        g["1"] = _n("AFE_ScriptFullParser", **inputs)
        if batch and int(batch.get("shot_start") or 0) == int(batch.get("shot_end") or 0):
            labels["1"] = f"分析镜头 {int(batch['shot_start'])}"
        else:
            labels["1"] = (f"分析剧本第{batch['batch_index']}批（{batch['shot_start']}-{batch['shot_end']}镜头）"
                            if batch else "分析剧本（第一次要载入语言模型，需要几分钟）")

    elif stage == 2:
        loader()
        cast_refs()
        if part != "cast":
            analyzers(); scene_images()
            if s["make_props"]:
                g["5"] = _n("AFE_PropsImageGenerator", props_report=["3", 2], props_json=["3", 0],
                            size=1024, steps=20, seed=int(s["seed"]), approved=True, project_name=project)
                labels["5"] = "绘制道具图"

    elif stage == 3:
        one = part == "kf"
        loader(); analyzers(); scene_images(); cast_refs()
        if s["make_props"]:
            g["5"] = _n("AFE_PropsImageGenerator", props_report=["3", 2], props_json=["3", 0],
                         size=1024, steps=20, seed=int(s["seed"]), approved=True, project_name=project)
        g["11"] = _n("AFE_ShotKeyframeGenerator", shot_sequence=["1", 0], cast_data=["1", 1],
                     scene_images=["4", 0], character_refs=["6", 0], project_name=project,
                     render_style=style, max_shots=0 if one else _max_shots(s), overwrite=False, resolution=1024,
                     seed=int(s["seed"]), variants_per_shot=int(s["kf_variants"]),
                     picks=s["kf_picks"], link_prompts=s["shot_links"], redo_shots=s["kf_redo"],
                     only_listed=one, only_shot=only_shot if one else "",
                     scene_view_picks=s["scene_view_picks"], approved=True,
                     scene_images_medium=["4", 1], scene_images_atmosphere=["4", 2])
        if "5" in g:
            g["11"]["inputs"]["props_images"] = ["5", 0]
            g["11"]["inputs"]["props_manifest"] = ["5", 2]
        labels["11"] = "只重画这一张首帧" if one else "绘制每个分镜的首帧"

    elif stage == 4:
        loader()
        g["12"] = _n("AFE_WanShotRenderer", shot_sequence=["1", 0], project_dir=project_path,
                     render_style=style, shots_to_render="all", max_shots=_max_shots(s),
                     width=int(s["video_width"]), height=int(s["video_height"]),
                     fast_4step=bool(s["fast"]), overwrite=False, seed=int(s["seed"]),
                     long_take_overrides=s["long_takes"], link_prompts=s["shot_links"],
                     anchor_identity=False,
                     redo_shots=s["video_redo"], approved=True)
        labels["12"] = "渲染分镜视频（每个分镜约几分钟，请耐心等待）"

    elif stage == 5:
        loader()
        g["13"] = _n("AFE_MovieAssembler", shot_sequence=["1", 0], project_dir=project_path,
                     output_name=s["output_name"], render_style=style, skip_shots=s["skip_shots"], approved=True)
        labels["13"] = "合成成片"

    else:
        raise ValueError(f"unknown stage {stage}")
    return g, labels


# ── validation against the real node definitions (used by tests and by the server) ──

def validate_prompt(prompt: dict, node_classes: dict) -> list[str]:
    """Returns a list of problems (empty = ok)."""
    problems: list[str] = []
    for nid, node in prompt.items():
        ct = node["class_type"]
        cls = node_classes.get(ct)
        if cls is None:
            problems.append(f"{nid}: node type {ct} is not installed")
            continue
        spec = cls.INPUT_TYPES()
        allowed = {**spec.get("required", {}), **spec.get("optional", {})}
        for name, value in node["inputs"].items():
            if name not in allowed:
                problems.append(f"{nid} {ct}: unknown input '{name}'")
                continue
            t = allowed[name][0]
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                src = prompt.get(value[0])
                if src is None:
                    problems.append(f"{nid} {ct}.{name}: links to missing node {value[0]}")
                    continue
                src_cls = node_classes.get(src["class_type"])
                rtypes = getattr(src_cls, "RETURN_TYPES", ())
                if value[1] >= len(rtypes):
                    problems.append(f"{nid} {ct}.{name}: slot {value[1]} does not exist on {src['class_type']}")
                elif not isinstance(t, list) and rtypes[value[1]] != t and t != "*":
                    problems.append(f"{nid} {ct}.{name}: type {rtypes[value[1]]} -> {t}")
            elif isinstance(t, list) and value not in t:
                problems.append(f"{nid} {ct}.{name}: '{value}' is not one of the allowed options")
        for name in spec.get("required", {}):
            if name not in node["inputs"]:
                problems.append(f"{nid} {ct}: missing required input '{name}'")
    return problems
