"""
script_full_parser_node.py
AFE_ScriptFullParser — Two-phase LLM script parser using transformers directly.

Phase 1 (1 call): Quick parse → cast + shot list with minimal fields (~2048 tokens output).
Phase 2 (1 call per shot): Deep analysis → camera, lighting, action, etc. (~768 tokens each).

Avoids the LLM_local output-token limit by calling Qwen2.5-7B-Instruct directly
via transformers, keeping each phase's output budget well under the model limit.
"""

import json
import os
import re
from ai_film_editor_nodes.lib.utils.logger import get_logger
from ai_film_editor_nodes.nodes.video.shot_prompt_contract import normalize_shot

logger = get_logger("AFE_ScriptFullParser")


# ── Scene pre-segmentation (code-level, NOT LLM-dependent) ───────────────────
#
# Qwen2.5-7B cannot reliably track scene boundaries across a long script with
# many scene switches (e.g. Scene A / Scene B alternating 10+ times) — it
# tends to collapse everything into one scene or invent generic names.
# So we pre-segment the script with regex BEFORE calling the LLM, build a
# numbered "scene map", and ask the LLM to only pick a scene_index per shot
# (a classification task) instead of generating/repeating a scene_name string
# from memory (an unreliable generation task).

_SCENE_HEADER_PATTERNS = [
    # non-location sections: title sequence / prologue / epilogue ... get their own scene,
    # otherwise their text is swallowed by the next real scene and the shots get the wrong set
    r'【(?:片头|序幕|序章|序言|引子|开场|开篇|尾声|片尾|结尾|彩蛋|预告|Prologue|Opening|Teaser|Epilogue|Ending|Credits)[^】\n]{0,40}】',
    r'(?<![^\n])(?:片头|序幕|序章|序言|引子|开场|开篇|尾声|片尾|结尾|彩蛋|预告|Prologue|Opening|Teaser|Epilogue|Ending|Credits)[：:][^\n]{0,40}',
    r'【场景\s*[A-Za-z0-9]+[：:].*?】',          # 【场景 A：XXX - YYY】
    r'场景[一二三四五六七八九十\d]+[：:][^\n]{0,40}',  # 场景一：XXX
    r'第[一二三四五六七八九十\d]+场[：:]?[^\n]{0,40}', # 第一场：XXX
    r'(?:INT|EXT)[./]\s*[^\n]{0,60}',           # INT. XXX - DAY
    r'Scene\s*[A-Za-z0-9]+[：:.][^\n]{0,40}',    # Scene 1: XXX
]
_HEADER_RE = re.compile('|'.join(f'(?:{p})' for p in _SCENE_HEADER_PATTERNS))

_SCENE_SOURCE_MAX_CHARS = 2500
# Bracketed screenplay cues are semantic boundaries even when they are not headings.
# Interior/exterior and continuity annotations remain attached to their location block.
_SEMANTIC_CUE_RE = re.compile(
    r'(?:\[|【)(black\s*screen|quick\s*flash(?:es)?|flash\s*cut|silhouette|half\s*silhouette|'
    r'fade(?:\s*out)?|transition|montage|黑屏|快速闪切|半剪影|淡出|转场|蒙太奇)[^\]】]*(?:\]|】)',
    re.IGNORECASE,
)

SCENE_ENV_SYSTEM = """You are a film production designer. You receive the screenplay text of ONE scene.
Write the visual description of the PLACE ONLY, so an image model can paint the empty set.

Rules:
- Use only what the text says or clearly implies about the place: layout, materials, furniture,
  fixtures, signage, colors, lighting sources, time of day, weather, atmosphere.
- Ignore people, dialogue, actions, emotions and story. Never mention any person.
- Translate everything into English. Keep concrete details (materials, colors, light color/temperature).
- environment_prompt_en: one paragraph, 40-70 words, comma-separated visual phrases, no sentences about events.
- scene_name_en: 2-5 words naming the place in English.

Return ONLY JSON, no markdown:
{"scene_name_en": "<place name>", "environment_prompt_en": "<visual description of the empty set>"}
"""


def _normalize_scene_key(header: str) -> str:
    """Extract a stable grouping key from a scene header, e.g. 'A' from
    '【场景 A：伦敦超市 - 下午】' so repeated appearances of the same physical
    scene (场景A, 场景A-连续, 场景A-续) group together."""
    m = re.search(r'场景\s*([A-Za-z0-9]+)', header)
    if m:
        return f"scene_{m.group(1).upper()}"
    m = re.search(r'Scene\s*([A-Za-z0-9]+)', header, re.IGNORECASE)
    if m:
        return f"scene_{m.group(1).upper()}"
    m = re.search(r'第([一二三四五六七八九十\d]+)场', header)
    if m:
        return f"scene_{m.group(1)}"
    # Fallback: location text with trailing time/status stripped
    cleaned = re.sub(r'[-－—][^】\n]*$', '', header)
    cleaned = re.sub(r'[【】:：.]', '', cleaned).strip()
    return cleaned or header.strip()


def _section_type(header: str) -> str:
    text = (header or "").lower()
    if re.search(r"片头|片尾|opening|title|credits", text):
        return "title_sequence"
    if re.search(r"序幕|序章|引子|prologue|teaser", text):
        return "prologue"
    if re.search(r"尾声|结尾|epilogue|ending", text):
        return "epilogue"
    if re.search(r"黑屏|black\s*screen|转场|transition|淡出|fade", text):
        return "transition"
    if re.search(r"快速闪切|montage|闪切|quick\s*flash|flash\s*cut", text):
        return "montage"
    if re.search(r"半剪影|silhouette", text):
        return "transition"
    return "location_scene"


def _build_scene_map(raw_script: str) -> list[dict]:
    """Build an ordered semantic map without losing repeated-location occurrences.

    Location headers are grouped by their physical key, while each source block keeps its
    original position. Bracketed montage/transition cues get their own semantic group so a
    cue in the middle of a location cannot inherit the wrong environment.
    """
    headers = list(_HEADER_RE.finditer(raw_script))
    cues = list(_SEMANTIC_CUE_RE.finditer(raw_script))
    candidates = []
    header_ranges = [(m.start(), m.end()) for m in headers]
    for match in headers:
        header = match.group().strip()
        candidates.append((match.start(), match.end(), header, _section_type(header),
                           _normalize_scene_key(header), True))
    for match in cues:
        if any(start <= match.start() < end for start, end in header_ranges):
            continue
        cue = match.group().strip()
        section = _section_type(cue)
        # [内景 - 日], [外景 - 日] and [连续] are annotations, not boundaries.
        candidates.append((match.start(), match.end(), cue, section,
                           f"semantic_{section}_{len(candidates) + 1:03d}", False))
    candidates.sort(key=lambda item: item[0])

    if not candidates:
        return [{"scene_index": 1, "scene_id": "scene_001", "sample_header": "Unnamed Location",
                 "section_type": "location_scene", "preview": raw_script[:200],
                 "source_text": raw_script, "source_block_ids": ["block_001"],
                 "occurrences": ["occurrence_001"],
                 "source_blocks": [{"source_block_id": "block_001", "scene_occurrence_id": "occurrence_001",
                                    "header": "Unnamed Location", "section_type": "location_scene",
                                    "source_text": raw_script}] }]

    grouped: dict[str, dict] = {}
    order: list[str] = []
    for i, (start, end, header, section, key, is_location_header) in enumerate(candidates):
        next_start = candidates[i + 1][0] if i + 1 < len(candidates) else len(raw_script)
        # Include the cue/header in the source block. Phase 2 must see the complete original text.
        block_text = raw_script[start:next_start].strip()
        source_block_id = f"block_{i + 1:03d}"
        occurrence_id = f"occurrence_{i + 1:03d}"
        if not is_location_header:
            key = f"{key}_{i + 1:03d}"
        if key not in grouped:
            order.append(key)
            grouped[key] = {"headers": [], "preview": block_text[:300], "blocks": [],
                            "source_block_ids": [], "occurrences": [], "source_blocks": [],
                            "section_type": section}
        g = grouped[key]
        g["headers"].append(header)
        g["blocks"].append(block_text)
        g["source_block_ids"].append(source_block_id)
        g["occurrences"].append(occurrence_id)
        g["source_blocks"].append({"source_block_id": source_block_id,
                                    "scene_occurrence_id": occurrence_id, "header": header,
                                    "section_type": section, "source_text": block_text})

    scene_map = []
    for idx, key in enumerate(order):
        g = grouped[key]
        scene_map.append({
            "scene_index": idx + 1,
            "scene_id": f"scene_{idx + 1:03d}",
            "sample_header": g["headers"][0],
            "section_type": g["section_type"],
            "preview": g["preview"],
            "source_text": "\n".join(g["blocks"]),
            "source_block_ids": g["source_block_ids"],
            "occurrences": g["occurrences"],
            "source_blocks": g["source_blocks"],
        })
    return scene_map


def _header_to_scene_name(header: str) -> str:
    """
    Convert a raw scene header into a readable scene_name for grouping/display.
    Keeps original text (Chinese or English) — downstream SceneAnalyzer already
    has keyword-based CN→EN translation for display; what matters here is that
    the SAME header always produces the SAME scene_name (code-guaranteed).
    """
    # Strip bracket/punctuation wrapper, keep the descriptive text
    cleaned = re.sub(r'[【】]', '', header).strip()
    # Drop leading "场景 X：" / "Scene X:" prefix, keep the location + time part
    cleaned = re.sub(r'^(场景\s*[A-Za-z0-9]+[：:]|Scene\s*[A-Za-z0-9]+[：:.])\s*', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or header.strip()


def _scene_map_to_prompt_text(scene_map: list[dict]) -> str:
    """Format the scene map as text for the LLM prompt."""
    lines = ["PRE-SEGMENTED SCENE MAP (use these EXACT scene_index values, "
             "do not invent new ones):"]
    for s in scene_map:
        lines.append(
            f"  scene_index={s['scene_index']}: \"{s['sample_header']}\" "
            f"— starts with: {s['preview'][:80]}..."
        )
        for block in s.get("source_blocks", []):
            lines.append(
                f"    source_block_id={block['source_block_id']} "
                f"scene_occurrence_id={block['scene_occurrence_id']} "
                f"section_type={block['section_type']}: {block['source_text'][:120]}..."
            )
            for unit in _source_units_with_offsets(block.get("source_text", "")):
                lines.append(
                    f"      source_unit_id={unit['unit_id']} "
                    f"source_start={unit['start']} source_end={unit['end']}: "
                    f"{unit['text']}"
                )
    return "\n".join(lines)

# ── Phase 1 system prompt ─────────────────────────────────────────────────────
PHASE1_SYSTEM = """You are a professional film storyboard artist. Break the screenplay into individual shots for video production.
Return ONLY the JSON object, no explanation, no markdown.

IMPORTANT: Each shot = ONE specific 5-second moment. Break scenes into small shots:
- One line of dialogue = one shot
- One physical action = one shot  
- Reaction / pause / expression change = one shot
- Scene transition = one shot
You MUST generate EXACTLY the number of shots specified in the user message.

CRITICAL — scene_index RULE:
The user message includes a PRE-SEGMENTED SCENE MAP listing every distinct physical scene
in this screenplay, each with a scene_index number. For EVERY shot, you MUST set
"scene_index" to the number from that map matching where the shot's text falls.
DO NOT invent scene_index values outside the given map. DO NOT merge different
scene_index values together — if the map lists 2 scenes, shots alternate between
scene_index 1 and 2 exactly as the screenplay text alternates between them; re-read
the screenplay text near each shot to determine which scene block it falls in.

raw_description MUST preserve the complete relevant screenplay moment and its concrete set/location details. Do not summarize away facial expression, micro-expression, gaze, business motion, prop interaction, dialogue, lighting, or action phases. Do not impose a word limit.
The shot must also include source_block_id, scene_occurrence_id, section_type, facial_expression, micro_expression, gaze, body_language, action_start, action_process, action_end, prop_interactions, camera_motion and pace.

Format:
{
  "cast": [
    {
      "name": "CharacterName",
      "role_type": "lead",
      "gender": "male",
      "age_range": "24-26",
      "appearance_en": "English physical description",
      "default_costume_en": "English default outfit description"
    }
  ],
  "shots": [
    {
      "shot_id": "shot_001",
      "scene_index": 1,
      "source_block_id": "block_001",
      "scene_occurrence_id": "occurrence_001",
      "section_type": "location_scene",
      "character_names": ["name"],
      "dialogue": "one line of quoted dialogue or null",
      "props_list": ["prop1"],
      "raw_description": "the complete original screenplay moment: set, subject, expression, micro-action, props, dialogue and lighting",
      "source_shot_text": "verbatim source text for this shot, copied exactly",
      "source_unit_ids": ["unit_001"],
      "source_start": 0,
      "source_end": 120,
      "facial_expression": "explicit facial expression or null",
      "micro_expression": "explicit micro-expression or null",
      "gaze": "gaze direction or null",
      "body_language": "body language or null",
      "action_start": "starting state or null",
      "action_process": "action process and business motion or null",
      "action_end": "ending state or null",
      "prop_interactions": ["exact interaction or null"],
      "camera_motion": "explicit motion or null",
      "camera_motion_source": "script only when the screenplay explicitly specifies camera motion or a locked/hold shot, otherwise null",
      "camera_path": "path or null",
      "pace": "rhythm or null"
    }
  ]
}

Rules:
- source_shot_text MUST be copied verbatim from the listed source block when it is used.
- Prefer source_unit_ids from the source-unit catalog; otherwise return source_start/source_end offsets relative to that source block. Never paraphrase the only source evidence.
- A shot may span adjacent source units, but the IDs must be in source order. If the source moment cannot be uniquely mapped, still return the shot with source evidence empty; the parser will block generation and report it.
- raw_description is descriptive enrichment, not proof of source provenance.
- role_type: lead | supporting | extra_a | extra_b | extra_other
- Each shot covers ONLY one specific moment, not an entire scene
- Split long dialogue into separate shots (one line per shot)
- Split long action sequences into separate shots
- Return ONLY the JSON object."""

# ── Phase 2 system prompt ─────────────────────────────────────────────────────
PHASE2_SYSTEM = """You are a professional cinematographer. Given a shot description and context, generate detailed cinematic directions.

CRITICAL RULE: The "Description" field in the user message contains the ACTUAL scene content
(location, set pieces, props, action) taken directly from the real screenplay. You MUST extract
"location", "lighting", "action", "business", "emotion" etc. FROM THAT DESCRIPTION TEXT.
NEVER invent a generic location like "apartment living room" — that is a placeholder format example only,
not a real answer. If the Description mentions a supermarket, kitchen, beach villa, office etc.,
your location field MUST reflect that same real place, in English, with specific set details
(materials, furniture, lighting fixtures) carried over from the Description.

Return ONLY a JSON object with these exact fields (field names fixed, VALUES must be derived
from the actual Description — the strings below are FORMAT HINTS, not real answers to copy):

{
  "camera_angle": "<camera position/angle or null>",
  "camera_motion": "<explicit screenplay motion or null>",
  "camera_motion_source": "<script|derived>",
  "camera_path": "<path or null>",
  "shot_type": "<shot size/type or null>",
  "lighting_style": "<derived from the actual Description or null>",
  "location": "<the real location from the actual Description or null>",
  "time_of_day": "<only if stated, otherwise null>",
  "weather": "<only if stated, otherwise null>",
  "lighting": "<actual light sources or null>",
  "color_temperature": "<only if stated, otherwise null>",
  "action": "<main action or null>",
  "business": "<subtle physical business motion or null>",
  "emotion": "<emotion or null>",
  "facial_expression": "<face expression or null>",
  "micro_expression": "<micro-expression or null>",
  "gaze": "<gaze direction or null>",
  "body_language": "<body language or null>",
  "action_start": "<starting state or null>",
  "action_process": "<process state or null>",
  "action_end": "<ending state or null>",
  "prop_interactions": ["<exact prop interaction or null>"],
  "pace": "<rhythm or null>",
  "shot_description": "<complete visual description grounded in Description>",
  "costume_description": "<Chinese costume description or null>",
  "costume_en": "<English costume description or null>",
  "negative_prompt": "ugly, blurry, low quality, distorted",
  "director_notes": "<brief direction or null>"
}

camera_angle options: close_up | medium_close_up | medium | full_body | wide | extreme_close_up | low_angle | high_angle | dutch
camera_motion options: static | slow_push_in | slow_pull_back | pan_left | pan_right | tracking_shot | crane_up | crane_down | handheld | orbit
time_of_day options: morning, afternoon, evening, night, or null when absent
weather options: sunny, cloudy, rainy, snowy, foggy, indoor, clear, or null when absent

CAMERA SELECTION RULES (must follow these):
- Opening scene / establishing shot → wide shot (wide_shot), camera: slow_push_in
- Character introduced for first time → medium shot, camera: static
- Dialogue (one person speaking) → medium close-up, camera: static or slow_push_in
- Two people talking (shot/reverse) → medium shot, alternating eye-level
- Emotional climax / reaction → close_up, camera: static (hold)
- Action / movement → medium or wide, camera: tracking_shot or pan
- Object / prop detail → close_up or extreme close-up, camera: static
- Ending / resolution → wide shot, camera: slow_pull_back
- Character thinking / internal moment → close_up, camera: slow_push_in
- Scene transition → wide shot, camera: static or pan

Return ONLY the JSON object."""


def _normalize_durations(shots: list, target_seconds: int, default_secs: int) -> list:
    """
    Redistribute durations so total ≈ target_seconds.
    Weights: shots with dialogue get 2x weight vs shots without.
    """
    if not shots:
        return shots
    weights = []
    for shot in shots:
        dialogue = shot.get("dialogue")
        has_dialogue = dialogue and dialogue not in ("null", "(无)", "none", "")
        desc_words = len(shot.get("raw_description", "").split())
        weight = 2.0 if has_dialogue else 1.0
        weight += desc_words / 50.0
        weights.append(weight)
    total_weight = sum(weights)
    for i, shot in enumerate(shots):
        shot["duration_seconds"] = round(
            max(default_secs, (weights[i] / total_weight) * target_seconds), 1
        )
    return shots


def _mostly_cjk(text: str, threshold: float = 0.2) -> bool:
    t = text or ""
    return bool(t) and sum(1 for c in t if "\u4e00" <= c <= "\u9fff") / len(t) > threshold


_NULL_WORDS = {"", "null", "none", "n/a", "nil"}


def _clean_semantic(value):
    """Remove JSON null markers recursively without turning them into prompt facts."""
    if value is None:
        return None
    if isinstance(value, list):
        cleaned = [_clean_semantic(item) for item in value]
        return [item for item in cleaned if item is not None]
    if isinstance(value, tuple):
        cleaned = [_clean_semantic(item) for item in value]
        return [item for item in cleaned if item is not None]
    if isinstance(value, dict):
        return {key: cleaned for key, item in value.items()
                if (cleaned := _clean_semantic(item)) is not None}
    if isinstance(value, str):
        return None if value.strip().lower() in _NULL_WORDS else value.strip()
    return value


def _present(value) -> bool:
    value = _clean_semantic(value)
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def _first_present(*values, default=""):
    for value in values:
        cleaned = _clean_semantic(value)
        if _present(cleaned):
            return cleaned
    return default


def _source_units_with_offsets(source_text: str) -> list[dict]:
    """Return stable, verifiable units from one source block.

    Offsets are relative to the unmodified block text.  The phase-1 model can
    identify one or more of these units instead of paraphrasing a moment.  The
    parser then joins the original span, preserving every screenplay fact and
    the separators between adjacent units.
    """
    source = str(source_text or "")
    boundary = re.compile(
        r"\n\s*\n+|(?<=[。！？!?])\s+|(?<=[。！？!?])(?=[\u4e00-\u9fff])|(?<=[.!?])\s+"
    )
    units = []
    start = 0
    for match in boundary.finditer(source):
        end = match.start()
        raw = source[start:end]
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        if left < right:
            units.append({"unit_id": f"unit_{len(units) + 1:03d}",
                          "start": start + left, "end": start + right,
                          "text": source[start + left:start + right]})
        start = match.end()
    raw = source[start:]
    left = len(raw) - len(raw.lstrip())
    right = len(raw.rstrip())
    if left < right:
        units.append({"unit_id": f"unit_{len(units) + 1:03d}",
                      "start": start + left, "end": start + right,
                      "text": source[start + left:start + right]})
    return units


def _source_units(source_text: str) -> list[str]:
    return [unit["text"] for unit in _source_units_with_offsets(source_text)]


def _compact_source(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _validated_source_fragment(source_block_text: str, raw_desc: str, shot: dict) -> tuple[str, str]:
    """Resolve a shot to a verified original span, or return an error.

    A model summary is never used as a substitute for source text.  Accepted
    evidence is an exact returned fragment, source-unit IDs, or character
    offsets that point into the source block.  Ambiguous clue matching is
    intentionally rejected so sibling actions cannot leak into this shot.
    """
    source = str(source_block_text or "")
    units = _source_units_with_offsets(source)
    by_id = {unit["unit_id"]: unit for unit in units}
    requested_ids = shot.get("source_unit_ids")
    if isinstance(requested_ids, str):
        requested_ids = [requested_ids]
    if requested_ids:
        ids = [str(value).strip() for value in requested_ids if str(value).strip()]
        selected = [by_id.get(value) for value in ids]
        if len(selected) != len(ids) or any(unit is None for unit in selected):
            return "", "source_unit_ids do not identify this source block"
        selected = sorted(selected, key=lambda unit: unit["start"])
        if [unit["unit_id"] for unit in selected] != ids:
            return "", "source_unit_ids are out of source order"
        positions = [units.index(unit) for unit in selected]
        if positions != list(range(positions[0], positions[-1] + 1)):
            return "", "source_unit_ids are not adjacent"
        if any(left["end"] > right["start"] for left, right in zip(selected, selected[1:])):
            return "", "source_unit_ids overlap"
        fragment = source[selected[0]["start"]:selected[-1]["end"]]
        return fragment, ""

    start = shot.get("source_start")
    end = shot.get("source_end")
    if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(source):
        fragment = source[start:end]
        if fragment.strip():
            return fragment, ""
        return "", "source offsets point to empty text"

    model_fragment = _first_present(shot.get("source_shot_text"), raw_desc, default="")
    if model_fragment:
        exact_start = source.find(str(model_fragment))
        if exact_start >= 0:
            return source[exact_start:exact_start + len(str(model_fragment))], ""
        compact_model = _compact_source(model_fragment)
        if compact_model:
            compact_match = re.search(re.escape(compact_model), _compact_source(source))
            if compact_match:
                return "", "source_shot_text is not a verbatim source span"
    if len(units) == 1:
        # A source block with one unit has only one possible shot span. This is
        # deterministic, unlike selecting one unit from a multi-moment block.
        return units[0]["text"], ""
    return "", "missing verified source_unit_ids, source offsets, or verbatim source_shot_text"


def _source_fragment_for_shot(source_block_text: str, raw_desc: str, shot: dict) -> str:
    """Return only a verified original screenplay fragment.

    This compatibility helper deliberately returns an empty string when the
    model did not provide verifiable source evidence.  It never picks a sibling
    source unit by fuzzy clue overlap.
    """
    fragment, _ = _validated_source_fragment(source_block_text, raw_desc, shot)
    return fragment


_CAMERA_STATIC_CUE_RE = re.compile(
    # Do not treat an ordinary action such as "hold the cup" as a locked shot.
    r"\b(?:static|fixed|still)\s+(?:camera|shot|frame|view)\b|"
    r"\b(?:locked(?:[- ]off)?|fixed|still)\s+(?:camera|shot|frame|view)\b|"
    r"\b(?:camera|shot|frame|view)\s+(?:is\s+)?(?:static|fixed|still|locked(?:[- ]off)?)\b|"
    r"\bhold\s+(?:on\s+)?(?:the\s+)?(?:camera|shot|frame|view)\b|"
    r"(?:固定机位|固定镜头|定机位|镜头停留|画面停留|"
    r"(?:镜头|机位|画面)(?:保持不动|静止|固定)|"
    r"(?:保持不动|静止|固定)(?:镜头|机位|画面))", re.IGNORECASE,
)
_CAMERA_MOTION_CUE_RE = re.compile(
    r"\b(?:camera|shot|frame)\s+(?:slowly\s+)?(?:push(?:es)? in|dolly|pull(?:s)? back|zoom|pan(?:s)?|"
    r"track(?:s)?|crane|handheld|orbit(?:s)?)\b|"
    r"\b(?:push(?:es)? in|dolly|pull(?:s)? back|zoom|pan(?:s)?|tracking|track(?:s)?|"
    r"crane|handheld|orbit(?:s)?|camera movement|camera moves?)\b|"
    r"(?:镜头|机位|运镜).{0,16}(?:推近|推进|拉远|拉镜|变焦|摇镜|跟拍|升镜|降镜|手持|环绕|"
    r"向左(?:移动|横移|平移)?|向右(?:移动|横移|平移)?|左移|右移|横移|平移)|"
    r"(?:推近|推进|拉远|拉镜|变焦|摇镜|跟拍|升镜|降镜|手持|环绕|横移|平移|"
    r"向左(?:移动|横移|平移)?|向右(?:移动|横移|平移)?|左移|右移).{0,16}(?:镜头|机位|运镜)", re.IGNORECASE,
)


def _camera_motion_from_text(text: str) -> str:
    """Infer the direction from the exact shot text, never from model provenance."""
    low = text.lower()
    if re.search(r"(?:track|tracking).{0,12}(?:left|right)", low) or re.search(
            r"(?:跟拍|追踪).{0,12}(?:向左|向右|左移|右移)", text):
        return "tracking_shot"
    if re.search(r"(?:pan|摇镜).{0,12}(?:left|左)", low) or re.search(
            r"(?:镜头|机位|运镜)?(?:向左(?:移动|横移|平移)?|左移|左横移|左平移)", text):
        return "pan_left"
    if re.search(r"(?:pan|摇镜).{0,12}(?:right|右)", low) or re.search(
            r"(?:镜头|机位|运镜)?(?:向右(?:移动|横移|平移)?|右移|右横移|右平移)", text):
        return "pan_right"
    if re.search(r"(?:push(?:es)? in|dolly in|推进|推近)", low if not any(ord(c) > 127 for c in text) else text):
        return "slow_push_in"
    if re.search(r"(?:pull(?:s)? back|dolly out|拉远|拉镜)", low if not any(ord(c) > 127 for c in text) else text):
        return "slow_pull_back"
    if re.search(r"(?:track(?:s)?|tracking|跟拍)", low if not any(ord(c) > 127 for c in text) else text):
        return "tracking_shot"
    if re.search(r"(?:crane).{0,8}(?:up|升)|升镜", low if not any(ord(c) > 127 for c in text) else text):
        return "crane_up"
    if re.search(r"(?:crane).{0,8}(?:down|降)|降镜", low if not any(ord(c) > 127 for c in text) else text):
        return "crane_down"
    if re.search(r"handheld|手持", low if not any(ord(c) > 127 for c in text) else text):
        return "handheld"
    if re.search(r"orbit|环绕", low if not any(ord(c) > 127 for c in text) else text):
        return "orbit"
    return ""


def _camera_motion_from_phases(phase1: dict, phase2: dict, source_text: str, raw_desc: str) -> tuple[str, str, bool]:
    """Validate camera cues against this shot's exact source fragment."""
    cue_text = str(source_text or raw_desc or "").strip()
    static_cue = bool(_CAMERA_STATIC_CUE_RE.search(cue_text))
    motion_cue = bool(_CAMERA_MOTION_CUE_RE.search(cue_text))
    # The phase dictionaries are enrichment only. A camera value is a script
    # fact only when the exact source fragment contains the corresponding cue.
    text_motion = _camera_motion_from_text(cue_text) if motion_cue else ""

    if text_motion:
        return text_motion, "script", True
    if static_cue:
        return "static", "script", True
    return "", "derived", False


TO_ENGLISH_SYSTEM = (
    "You write prompts for an image / video model. Rewrite the shot description as ONE English "
    "paragraph of at most 60 words, purely visual: subject, action, setting, lighting, mood. "
    "No quotes of dialogue, no JSON, no explanation. Output only the paragraph."
)


class AFE_ScriptFullParser:
    """
    全剧本深度解析器 — Two-phase LLM approach.
    Phase 1 (1 call): Quick parse → shot list with minimal fields + cast (~750 tokens output).
    Phase 2 (1 call per shot): Deep analysis → camera, lighting, action, etc. (~250 tokens each).
    Uses transformers directly to call Qwen2.5-7B-Instruct; avoids LLM_local token-limit issues.
    Model is cached at class level and loaded once per model_path.
    """

    _model = None
    _tokenizer = None
    _model_path_loaded = None

    @classmethod
    def _ensure_model(cls, model_path: str):
        if cls._model is not None and cls._model_path_loaded == model_path:
            return
        logger.info(f"[AFE_ScriptFullParser] Loading model from: {model_path}")
        logger.info("[AFE_ScriptFullParser] First load may take several minutes...")
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        cls._tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        cls._model = AutoModelForCausalLM.from_pretrained(
            model_path, device_map="auto", torch_dtype=torch.float16, trust_remote_code=True
        )
        cls._model.eval()
        cls._model_path_loaded = model_path
        logger.info("[AFE_ScriptFullParser] Model loaded.")

    def _call_llm(self, system_prompt: str, user_prompt: str, model_path: str,
                  max_new_tokens: int = 2048) -> str:
        self._ensure_model(model_path)
        import torch
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ]
        text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer([text], return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=0.3,
                do_sample=True,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        generated = output_ids[0][inputs.input_ids.shape[1]:]
        return self._tokenizer.decode(generated, skip_special_tokens=True)

    # ── ComfyUI interface ─────────────────────────────────────────────────────

    RENDER_STYLES = [
        "3D cartoon Pixar animation style, vibrant colors, 8k",
        "3D cartoon Disney animation style, warm tones, 8k",
        "3D realistic CGI, photorealistic, cinematic lighting, 8k",
        "2.5D flat illustration, clean lines, vibrant palette",
        "Anime / cel-shading style, bold outlines, vivid colors",
        "Watercolor animation, soft brushstrokes, pastel tones",
        "Stop-motion clay animation, tactile textures, warm light",
        "Comic-book / graphic-novel style, bold lines, high contrast",
        "High-key 3D cartoon, super-bright lighting, no shadows",
        "Low-key 3D cinematic, moody, dramatic shadows",
    ]

    EPISODE_FORMATS = [
        "短片 Short Film (1-3 min)",
        "竖版短剧 Vertical Short Drama (3-5 min)",
        "迷你剧集 Mini Episode (5-10 min)",
        "标准剧集 Standard Episode (20-30 min)",
        "电影 Feature Film (90-120 min)",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "raw_script": ("STRING", {
                    "multiline": True,
                    "default": "在这里输入剧本...",
                    "tooltip": "粘贴完整剧本文本",
                }),
                "render_style": (cls.RENDER_STYLES, {
                    "default": cls.RENDER_STYLES[0],
                    "tooltip": "整体渲染风格，影响所有分镜提示词",
                }),
                "episode_format": (cls.EPISODE_FORMATS, {
                    "default": cls.EPISODE_FORMATS[2],
                    "tooltip": "集数格式，决定总时长预期",
                }),
            },
            "optional": {
                "target_duration_seconds": ("INT", {
                    "default": 180, "min": 30, "max": 7200,
                    "tooltip": "目标总时长（秒）。180=3分钟。LLM 会据此决定镜头数量",
                }),
                "seconds_per_shot": ("INT", {
                    "default": 5, "min": 3, "max": 15,
                    "tooltip": "每个分镜的默认时长（秒）",
                }),
                "lighting_mood": (["auto (from script)", "High-key bright", "Low-key moody",
                                   "Golden hour warm", "Cool blue night", "Neon cyberpunk",
                                   "Natural daylight", "Studio flat light"], {
                    "default": "auto (from script)",
                    "tooltip": "整体光线风格（auto = 由剧本场景决定）",
                }),
                "color_palette": (["auto (from style)", "Vibrant saturated",
                                   "Pastel soft", "Warm amber", "Cool desaturated",
                                   "High contrast B&W", "Earthy natural"], {
                    "default": "auto (from style)",
                }),
                "model_path": ("STRING", {
                    "default": "LLM/Qwen2.5-7B-Instruct",
                    "tooltip": "Qwen LLM 模型路径（相对于 models/ 目录）",
                }),
            },
        }

    RETURN_TYPES  = ("SHOT_SEQUENCE", "CAST_DATA", "STRING", "STRING", "INT", "INT", "INT", "STRING")
    RETURN_NAMES  = ("shot_sequence", "cast_data", "shots_json", "cast_json",
                     "shot_count", "scene_count", "props_count", "report")
    FUNCTION      = "parse_script"
    CATEGORY      = "AI Film Editor/Script"
    OUTPUT_NODE   = True

    # ── Main entry point ──────────────────────────────────────────────────────

    def parse_script(self, raw_script: str,
                     render_style: str = "3D cartoon Pixar animation style, vibrant colors, 8k",
                     episode_format: str = "迷你剧集 Mini Episode (5-10 min)",
                     target_duration_seconds: int = 180,
                     seconds_per_shot: int = 5,
                     lighting_mood: str = "auto (from script)",
                     color_palette: str = "auto (from style)",
                     model_path: str = "LLM/Qwen2.5-7B-Instruct"):

        if not raw_script.strip():
            raise ValueError("raw_script 不能为空")

        # 组合风格参数
        style_full = render_style
        if lighting_mood != "auto (from script)":
            style_full += f", {lighting_mood}"
        if color_palette != "auto (from style)":
            style_full += f", {color_palette} color palette"

        # 目标镜头数 = 总时长 / 每镜时长
        target_shot_count = max(1, round(target_duration_seconds / seconds_per_shot))

        # 1. Resolve model_path to absolute
        if not os.path.isabs(model_path):
            try:
                import folder_paths
                model_path = os.path.join(folder_paths.models_dir, model_path)
            except ImportError:
                pass
        logger.info(f"[AFE_ScriptFullParser] Using model: {model_path}")

        # 1b. Pre-segment scenes by regex (code-level, not LLM memory)
        scene_map = _build_scene_map(raw_script)
        scene_map_text = _scene_map_to_prompt_text(scene_map)
        logger.info("[AFE_ScriptFullParser] Pre-segmented %d unique scene(s) from screenplay",
                    len(scene_map))
        for s in scene_map:
            logger.info("  scene_index=%d: %s", s["scene_index"], s["sample_header"][:60])

        # 2. Phase 1: single LLM call → cast + minimal shots
        logger.info("[AFE_ScriptFullParser] Phase 1: parsing script (target %d shots × %ds = %ds)...",
                    target_shot_count, seconds_per_shot, target_duration_seconds)
        phase1_user = (
            f"Generate EXACTLY {target_shot_count} shots "
            f"(total {target_duration_seconds}s at {seconds_per_shot}s each). "
            f"Episode format: {episode_format}. "
            f"Break scenes and dialogue into individual {seconds_per_shot}-second moments.\n\n"
            f"{scene_map_text}\n\n"
            f"Screenplay:\n{raw_script}"
        )
        phase1_raw = self._call_llm(
            PHASE1_SYSTEM,
            phase1_user,
            model_path,
            max_new_tokens=8192,  # 36 shots × ~100 tokens = ~3600, need headroom
        )
        phase1_data = self._parse_llm_json(phase1_raw)
        if not isinstance(phase1_data, dict):
            phase1_data = {}

        cast_list    = phase1_data.get("cast", [])
        minimal_shots = phase1_data.get("shots", [])
        minimal_shots = _normalize_durations(minimal_shots, target_duration_seconds, seconds_per_shot)
        logger.info(f"[AFE_ScriptFullParser] Phase 1 done: {len(cast_list)} cast, {len(minimal_shots)} shots")

        # 3a. Build scene_index → scene_name lookup (code-level, guaranteed consistent).
        # scene_name is derived directly from the regex-detected header text, NOT
        # regenerated by the LLM each time — this is what prevents scene collapse/drift.
        scene_index_to_name = {
            s["scene_index"]: _header_to_scene_name(s["sample_header"])
            for s in scene_map
        }

        # 3a-2. One LLM call per scene: screenplay text -> English environment prompt
        # (place only, no people). Falls back to empty; SceneAnalyzer then uses old logic.
        scene_env: dict[int, dict] = {}
        for s in scene_map:
            idx = s["scene_index"]
            src = s.get("source_text", "")
            if not src.strip():
                continue
            try:
                env_raw = self._call_llm(
                    SCENE_ENV_SYSTEM,
                    f"Scene header: {s['sample_header']}\n\nScene screenplay text:\n{src}",
                    model_path, max_new_tokens=400,
                )
                env_data = self._parse_llm_json(env_raw)
                if isinstance(env_data, dict):
                    scene_env[idx] = {
                        "scene_name_en": str(env_data.get("scene_name_en", "")).strip(),
                        "environment_prompt_en": str(env_data.get("environment_prompt_en", "")).strip(),
                    }
                    logger.info("[AFE_ScriptFullParser] Scene %d env: %s", idx,
                                scene_env[idx]["environment_prompt_en"][:100])
            except Exception as exc:
                logger.warning("[AFE_ScriptFullParser] Scene env prompt failed for scene %d: %s", idx, exc)

        # Validate the LLM assignment. Never round-robin a shot into another place.
        valid_indices = {s["scene_index"] for s in scene_map}
        scene_blocks = {
            s["scene_index"]: {b["source_block_id"]: b for b in s.get("source_blocks", [])}
            for s in scene_map
        }
        assignment_errors = []
        for i, shot in enumerate(minimal_shots):
            idx = shot.get("scene_index")
            sid = shot.get("shot_id", f"shot_{i + 1:03d}")
            if idx not in valid_indices:
                assignment_errors.append(f"{sid}: invalid scene_index={idx}")
                shot["scene_index"] = None
                shot["scene_assignment_error"] = "Scene source could not be verified; generation is blocked."
                continue
            requested_block = str(shot.get("source_block_id") or "").strip()
            blocks = scene_blocks[idx]
            if requested_block and requested_block in blocks:
                continue
            if requested_block and requested_block not in blocks:
                assignment_errors.append(f"{sid}: source_block_id={requested_block} is not in scene_index={idx}")
                shot["scene_assignment_error"] = "Shot source block does not belong to its scene; generation is blocked."
            elif len(blocks) == 1:
                # A single source block is deterministic; repeated locations remain ambiguous.
                shot["source_block_id"] = next(iter(blocks))
                shot["scene_occurrence_id"] = blocks[shot["source_block_id"]]["scene_occurrence_id"]
            else:
                assignment_errors.append(f"{sid}: missing source_block_id for repeated scene_index={idx}")
                shot["scene_assignment_error"] = "Repeated scene needs an explicit source_block_id; generation is blocked."
        if assignment_errors:
            logger.error("[AFE_ScriptFullParser] %s", "; ".join(assignment_errors))

        # 3b. Build cast lookup by name
        cast_lookup = {c["name"]: c for c in cast_list if isinstance(c, dict) and "name" in c}

        # 4. Phase 2: deep analysis per shot
        full_shots = []
        total = len(minimal_shots)

        for i, shot in enumerate(minimal_shots):
            shot_id    = shot.get("shot_id", f"shot_{i + 1:03d}")
            scene_idx  = shot.get("scene_index")
            scene_info = next((s for s in scene_map if s["scene_index"] == scene_idx), None)
            scene_name = scene_index_to_name.get(scene_idx, "Unverified scene")
            scene_id = scene_info.get("scene_id") if scene_info else "scene_unverified"
            source_blocks = scene_info.get("source_blocks", []) if scene_info else []
            source_by_id = {b.get("source_block_id"): b for b in source_blocks}
            source_block_id = str(shot.get("source_block_id") or "").strip()
            source_block = source_by_id.get(source_block_id)
            if source_block is None and len(source_blocks) == 1:
                source_block = source_blocks[0]
                source_block_id = source_block.get("source_block_id", "")
            occurrence_id = str(shot.get("scene_occurrence_id") or "").strip()
            if source_block is not None:
                occurrence_id = source_block.get("scene_occurrence_id", occurrence_id)
            source_block_text = source_block.get("source_text", "") if source_block else ""
            if not source_block_text:
                source_block_text = scene_info.get("source_text", "") if scene_info else ""
            char_names = _clean_semantic(shot.get("character_names")) or []
            raw_desc   = _first_present(shot.get("raw_description"), default="")
            source_shot_text, source_validation_error = _validated_source_fragment(
                source_block_text, raw_desc, shot
            )
            if source_validation_error:
                assignment_errors.append(f"{shot_id}: {source_validation_error}")
            dialogue   = _first_present(shot.get("dialogue"), default="")
            props_list = _clean_semantic(shot.get("props_list")) or []

            logger.info(f"[AFE_ScriptFullParser] Phase 2: shot {i + 1}/{total} ({shot_id})")

            # Build character appearance context for Phase 2
            char_lines = []
            for name in char_names:
                char = cast_lookup.get(name, {})
                appearance = char.get("appearance_en", "")
                if appearance:
                    char_lines.append(f"- {name}: {appearance}")
            char_context = "\n".join(char_lines) if char_lines else "none"

            p2_user = (
                f"Shot ID: {shot_id}\n"
                f"Scene: {scene_name}\n"
                f"Characters: {', '.join(char_names) if char_names else 'none'}\n"
                f"Character Appearance:\n{char_context}\n"
                f"Source block ID: {source_block_id or 'unverified'}; occurrence: {occurrence_id or 'unverified'}\n"
                f"Exact source fragment for THIS shot (canonical visual facts; do not add sibling moments):\n{source_shot_text or 'unverified'}\n"
                f"Scene block context (environment only; do not copy its other actions, characters, props, or dialogue):\n{source_block_text}\n"
                f"Phase 1 shot description (use only to enrich the exact fragment): {raw_desc}\n"
                f"Dialogue fact: {dialogue or 'null'}; Props fact: {json.dumps(props_list, ensure_ascii=False)}\n"
                f"Requested structured facts: expression={shot.get('facial_expression','')}; micro_expression={shot.get('micro_expression','')}; gaze={shot.get('gaze','')}; body_language={shot.get('body_language','')}; action_start={shot.get('action_start','')}; action_process={shot.get('action_process','')}; action_end={shot.get('action_end','')}; prop_interactions={shot.get('prop_interactions','')}\n"
                f"Render Style: {style_full}\nShot duration: {shot.get('duration_seconds', seconds_per_shot)}s"
            )

            try:
                p2_raw  = self._call_llm(PHASE2_SYSTEM, p2_user, model_path, max_new_tokens=768)
                p2_data = self._parse_llm_json(p2_raw)
                if not isinstance(p2_data, dict):
                    p2_data = {}
            except Exception as exc:
                logger.warning(f"[AFE_ScriptFullParser] Phase 2 failed for {shot_id}: {exc}")
                p2_data = {}

            # A phase-2 literal "null" is semantically absent. Keep the full
            # phase-1/source description so no prop, action, or costume detail
            # disappears before the shared prompt contract is built.
            sd = _first_present(p2_data.get("shot_description"), raw_desc, default="")
            if _mostly_cjk(sd):
                try:
                    eng = self._call_llm(TO_ENGLISH_SYSTEM, sd, model_path, max_new_tokens=160).strip()
                    if eng and not _mostly_cjk(eng):
                        sd = eng
                except Exception as exc:
                    logger.warning("[AFE_ScriptFullParser] English rewrite failed for %s: %s", shot_id, exc)
            p2_data["shot_description"] = sd

            camera_motion, camera_motion_source, camera_motion_explicit = _camera_motion_from_phases(
                shot, p2_data, source_shot_text, raw_desc
            )
            # Phase 2 is an enrichment pass. JSON null/empty values must never
            # erase a fact already extracted by Phase 1.
            get_fact = lambda key, *fallbacks: _first_present(
                p2_data.get(key), *(shot.get(k) for k in (key,) + fallbacks)
            )
            action = get_fact("action")
            business = get_fact("business")
            facial_expression = get_fact("facial_expression", "emotion")
            micro_expression = get_fact("micro_expression", "micro_emotion")
            gaze = get_fact("gaze")
            body_language = get_fact("body_language")
            action_start = get_fact("action_start", "action")
            action_process = get_fact("action_process", "business")
            action_end = get_fact("action_end")
            prop_interactions = _first_present(p2_data.get("prop_interactions"), shot.get("prop_interactions"), default=[])
            camera_angle = get_fact("camera_angle")
            shot_type = get_fact("shot_type")
            lighting_style = get_fact("lighting_style")
            director_notes = get_fact("director_notes")
            location = get_fact("location", "scene_name")
            time_of_day = get_fact("time_of_day")
            weather = get_fact("weather")
            lighting = get_fact("lighting")
            color_temperature = get_fact("color_temperature")
            camera_path = get_fact("camera_path")
            pace = get_fact("pace", "rhythm")

            # 5. Merge minimal + phase2 into full shot dict
            full_shot = {
                "shot_id":          shot_id,
                "schema_version":   "afe-shot-v1",
                "label":            f"第{i + 1:02d}场-{scene_name}",
                "duration_seconds": float(shot.get("duration_seconds") or seconds_per_shot),
                "section_type":     shot.get("section_type") or (scene_info or {}).get("section_type", "location_scene"),
                "scene_id":          scene_id,
                "scene_occurrence_id": occurrence_id,
                "source_block_id":   source_block_id or None,
                "source_text":       source_shot_text,
                "source_shot_text":  source_shot_text,
                "source_block_text": source_block_text,
                "source_unit_ids":   _clean_semantic(shot.get("source_unit_ids")) or [],
                "source_start":      shot.get("source_start"),
                "source_end":        shot.get("source_end"),
                "source_validation_error": source_validation_error,
                "raw_description":   raw_desc,
                "scene_assignment_error": shot.get("scene_assignment_error") or source_validation_error,
                "environment": {
                    "description": scene_env.get(scene_idx, {}).get("environment_prompt_en", ""),
                    "location": location,
                    "time_of_day": time_of_day,
                    "weather": weather,
                    "lighting": lighting,
                    "color_temperature": color_temperature,
                },
                "character_names":  char_names,
                "costume_description": _first_present(p2_data.get("costume_description"), shot.get("costume_description")),
                "costume_en":          _first_present(p2_data.get("costume_en"), shot.get("costume_en")),
                "props_list":          props_list,
                "scene_name":          scene_name,
                "scene_name_en":       scene_env.get(scene_idx, {}).get("scene_name_en", ""),
                "scene_environment_en": scene_env.get(scene_idx, {}).get("environment_prompt_en", ""),
                "camera_angle":        camera_angle,
                "camera_motion":       camera_motion,
                "camera_motion_source": camera_motion_source,
                "camera_motion_explicit": camera_motion_explicit,
                "shot_type":           shot_type,
                "lighting_style":      lighting_style,
                "director_notes":      director_notes,
                "shot_description":    p2_data.get("shot_description") or raw_desc,
                "negative_prompt":     _first_present(p2_data.get("negative_prompt"), shot.get("negative_prompt"), default="ugly, blurry, low quality, distorted"),
                "dialogue":            dialogue if dialogue else "（无）",
                "location":            location or scene_name,
                "time_of_day":         time_of_day,
                "weather":             weather,
                "lighting":            lighting,
                "action":              action,
                "business":            business,
                "facial_expression":   facial_expression,
                "micro_expression":    micro_expression,
                "gaze":                gaze,
                "body_language":       body_language,
                "action_start":        action_start,
                "action_process":      action_process,
                "action_end":          action_end,
                "prop_interactions":   prop_interactions,
                "camera_path":         camera_path,
                "pace":                pace,
                "color_temperature":   color_temperature,
            }
            full_shots.append(normalize_shot(full_shot, i))

        # 6. Compute deduplicated ordered scenes and props
        seen_scenes: list[str] = []
        for shot in full_shots:
            sn = shot.get("scene_name", "").strip()
            if sn and sn not in seen_scenes:
                seen_scenes.append(sn)

        seen_props: list[str] = []
        for shot in full_shots:
            for p in shot.get("props_list", []):
                p = str(p).strip()
                if p and p not in seen_props:
                    seen_props.append(p)

        shot_count  = len(full_shots)
        scene_count = len(seen_scenes)
        props_count = len(seen_props)

        # 7. Build human-readable Chinese report
        scene_lines = "\n".join(f"  - {s}" for s in seen_scenes) if seen_scenes else "  （无）"
        cast_lines  = "\n".join(
            f"  - {c.get('name', '?')} ({c.get('role_type', '')})"
            for c in cast_list
        ) if cast_list else "  （无）"

        blocked_shots = [shot for shot in full_shots if shot.get("scene_assignment_error")]
        blocked_line = ""
        if blocked_shots:
            blocked_line = "\n\n❌ 已阻止生成的分镜：" + ", ".join(
                shot.get("shot_id", "?") for shot in blocked_shots
            ) + "（原文片段无法验证或场景来源不明确）"

        report = (
            f"✅ 剧本解析完成\n"
            f"📽️ 分镜数量：{shot_count}\n"
            f"🎬 场景数量：{scene_count}\n"
            f"🔧 道具数量：{props_count}\n"
            f"👥 角色数量：{len(cast_list)}\n\n"
            f"📋 场景列表：\n{scene_lines}\n\n"
            f"🎭 角色列表：\n{cast_lines}"
            f"{blocked_line}"
        )

        logger.info(f"[AFE_ScriptFullParser] Done: {shot_count} shots, {scene_count} scenes, "
                    f"{props_count} props, {len(cast_list)} cast")

        # 8. Return
        shots_json = json.dumps(full_shots, ensure_ascii=False, indent=2)
        cast_json  = json.dumps(cast_list,  ensure_ascii=False, indent=2)

        return {
            "ui": {"text": [report],
                   "afe_analysis": [json.dumps({"shots": full_shots, "cast": cast_list}, ensure_ascii=False)]},
            "result": (
                full_shots, cast_list,
                shots_json, cast_json,
                shot_count, scene_count, props_count,
                report,
            ),
        }

    # ── JSON parsing helper ───────────────────────────────────────────────────

    def _parse_llm_json(self, raw: str):
        """Strip markdown code fences, try json.loads, then substring extraction,
        then json_repair. Returns {} if all attempts fail."""
        raw = raw.strip()

        # Strip markdown code fences
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                if "{" in part or "[" in part:
                    raw = part.strip()
                    if raw.startswith("json"):
                        raw = raw[4:].strip()
                    break

        # 1. Try direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 2. Find first { or [ and last matching } or ]
        obj_start = raw.find("{")
        arr_start = raw.find("[")

        if obj_start == -1 and arr_start == -1:
            pass
        else:
            if obj_start == -1:
                start, end_char = arr_start, "]"
            elif arr_start == -1:
                start, end_char = obj_start, "}"
            elif obj_start < arr_start:
                start, end_char = obj_start, "}"
            else:
                start, end_char = arr_start, "]"

            end = raw.rfind(end_char)
            if end != -1 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    pass

        # 3. Try json_repair if available
        try:
            from json_repair import repair_json
            repaired = repair_json(raw)
            return json.loads(repaired)
        except Exception:
            pass

        logger.warning(f"[AFE_ScriptFullParser] _parse_llm_json failed. Raw[:200]: {raw[:200]}")
        return {}
