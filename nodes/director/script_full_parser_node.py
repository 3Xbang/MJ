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
DEFAULT_DIRECT_BATCH_SIZE = 4


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
    # Cue prefixes and a physical INT/EXT heading may share one line. Keep the
    # cue in the source block, but classify the embedded place as a location.
    r'^[ \t]*(?:(?:OPEN\s+ON|OPENING\s+IMAGE|SMASH\s+CUT\s+TO|MATCH\s+CUT\s+TO|'
    r'JUMP\s+CUT\s+TO|CUT\s+TO|INTERCUT(?:\s+WITH)?|FLASHBACK|FLASHFORWARD|'
    r'DISSOLVE\s+TO|WIPE\s+TO)[ \t]*(?:[:\-—])?[ \t]*(?:INT|EXT|INT/EXT)[./][ \t]*[^\n]{0,100})$',
    r'^[ \t]*(?:(?:OPEN\s+ON|SMASH\s+CUT\s+TO|CUT\s+TO)[ \t]*:[ \t]*)?(?:INT|EXT|INT/EXT)[./][ \t]*[^\n]{0,100}$',
    r'^[ \t]*(?:INT|EXT|INT/EXT)[./][ \t]*[^\n]{0,100}$',           # INT. XXX - DAY
    r'Scene\s*[A-Za-z0-9]+[：:.][^\n]{0,40}',    # Scene 1: XXX
    # Common screenplay headings/cues are often unbracketed and line-anchored.
    # Treat them as semantic blocks before a following location heading.
    r'^[ \t]*(?:TITLE\s+SEQUENCE|TITLE\s+CARD|OPENING\s+TITLES?|END\s+CREDITS?|CREDITS|'
    r'MONTAGE|QUICK\s+FLASH(?:ES)?|FLASH\s+CUT|BLACK\s+SCREEN|HALF\s+SILHOUETTE|'
    r'SILHOUETTE|FADE\s+(?:IN|OUT)|CUT\s+TO|TRANSITION)\b[^\n]*',
    # ASCII bracketed screenplay labels are common in customer scripts. Keep
    # them as standalone semantic blocks instead of attaching their title or
    # transition facts to the next physical location.
    r'^[ \t]*\[(?:TITLE(?:\s+SEQUENCE)?|TITLE\s+CARD|OPENING\s+TITLES?|END\s+CREDITS?|'
    r'CREDITS|PROLOGUE|OPENING|TEASER|EPILOGUE|ENDING|MONTAGE|QUICK\s+FLASH(?:ES)?|'
    r'FLASH\s+CUT|BLACK\s+SCREEN|HALF\s+SILHOUETTE|SILHOUETTE|FADE\s+(?:IN|OUT)|'
    r'CUT\s+TO|TRANSITION)\b[^\]\n]*\][ \t]*$',
    r'^[ \t]*\[(?:片头|序幕|序章|序言|引子|开场|开篇|尾声|片尾|结尾|彩蛋|预告|'
    r'快速闪切|蒙太奇|黑屏|半剪影|淡出|转场)(?:[ \t]*[：:-][^\]\n]*)?\][ \t]*$',
    r'^[ \t]*\[(?:场景\s*[A-Za-z0-9一二三四五六七八九十\d]+(?:[：:][^\]\n]{0,80})?|'
    r'Scene\s*[A-Za-z0-9]+(?:[：:.][^\]\n]{0,80})?|(?:INT|EXT)[./]\s*[^\]\n]{0,80})\][ \t]*$',
    # Chinese screenplay labels are also valid boundaries when written as a
    # standalone line.  Requiring a line start plus a label delimiter (or the
    # label alone) avoids treating ordinary prose such as "开场很安静" as a
    # new section.
    r'^[ \t]*(?:片头|序幕|序章|序言|引子|开场|开篇|尾声|片尾|结尾|彩蛋|预告|'
    r'快速闪切|蒙太奇|黑屏|半剪影|淡出|转场)(?:[ \t]*(?:[：:]|[-—])[^\n]*)?[ \t]*$',
    # Customer scripts also use plain, line-anchored headings without a colon,
    # or wrap the same heading in Markdown.  Keep the match line-scoped so a
    # word such as "scene" inside ordinary prose cannot split the screenplay.
    r'^[ \t]*#{1,6}[ \t]*(?:SCENE|场景)[ \t]*[A-Za-z0-9一二三四五六七八九十\d]+'
    r'(?:[ \t]*(?:[：:.-]|[-—])[ \t]*[^\n]*)?[ \t]*$',
    r'^[ \t]*(?:SCENE|场景)[ \t]*[A-Za-z0-9一二三四五六七八九十\d]+'
    r'(?:[ \t]*(?:[：:.-]|[-—])[ \t]*[^\n]*)?[ \t]*$',
]
_HEADER_RE = re.compile('|'.join(f'(?:{p})' for p in _SCENE_HEADER_PATTERNS),
                         re.IGNORECASE | re.MULTILINE)

_SCENE_SOURCE_MAX_CHARS = 2500
# Bracketed screenplay cues are semantic boundaries even when they are not headings.
# Interior/exterior and continuity annotations remain attached to their location block.
_SEMANTIC_CUE_RE = re.compile(
    r'(?:\[|【)(black\s*screen|quick\s*flash(?:es)?|flash\s*cut|silhouette|half\s*silhouette|'
    r'fade(?:\s*out)?|transition|montage|黑屏|快速闪切|半剪影|淡出|转场|蒙太奇)[^\]】]*(?:\]|】)',
    re.IGNORECASE,
)
_SCREENPLAY_CUE_LINE_RE = re.compile(
    r'^[ \t]*(?:SMASH\s+CUT\s+TO|INTERCUT(?:\s+WITH)?|MATCH\s+CUT\s+TO|JUMP\s+CUT\s+TO|'
    r'CUT\s+TO|FADE\s+(?:IN|OUT)|DISSOLVE\s+TO|WIPE\s+TO)\b[^\n]*$',
    re.IGNORECASE | re.MULTILINE,
)
# Generic line-scoped screenplay cue grammar. Only validated section/transition
# labels may use this fallback. In particular, an all-caps ``NAME: dialogue``
# line is character dialogue, not a scene boundary. Physical INT/EXT headings
# remain handled by _HEADER_RE and are deduplicated by source range below.
_GENERIC_SCREENPLAY_CUE_LINE_RE = re.compile(
    r'^[ \t]*(?P<cue>[A-Z][A-Z0-9]*(?:[ \t]+[A-Z][A-Z0-9]*){0,7}'
    r'(?:[ \t]*(?::|[-—])[ \t]*[^\n]*)?)$',
    re.MULTILINE,
)
_GENERIC_VALIDATED_CUE_RE = re.compile(
    r'^(?:OPEN(?:ING)?(?:[ \t]+IMAGE)?|FLASHBACK|FLASHFORWARD|'
    r'FADE(?:[ \t]+(?:IN|OUT|TO(?:[ \t]+BLACK)?)?)?|DISSOLVE(?:[ \t]+TO)?|'
    r'WIPE(?:[ \t]+TO)?|SMASH[ \t]+CUT(?:[ \t]+TO)?|MATCH[ \t]+CUT(?:[ \t]+TO)?|'
    r'JUMP[ \t]+CUT(?:[ \t]+TO)?|INTERCUT(?:[ \t]+WITH)?|CUT(?:[ \t]+TO)?|'
    r'TITLE(?:[ \t]+(?:SEQUENCE|CARD))?|OPENING[ \t]+TITLES?|'
    r'(?:END[ \t]+)?CREDITS?|BLACK[ \t]+SCREEN|HALF[ \t]+SILHOUETTE|SILHOUETTE|'
    r'MONTAGE|QUICK[ \t]+FLASH(?:ES)?|FLASH[ \t]+CUT|TRANSITION|BEGIN|END)'
    r'(?:[ \t]*(?::|[-—])[ \t]*.*)?$',
    re.IGNORECASE,
)
# A montage may contain several inserts before the next screenplay heading.
# Split only explicit location-bearing insert lines, never arbitrary prose. This
# keeps each empty-scene asset tied to one place without hard-coding customer
# names such as A/B or London/Thailand.
_FLASH_LOCATION_LINE_RE = re.compile(
    r'^[ \t]*(?:#{1,6}[ \t]*)?(?:INT|EXT|INT/EXT)[./][^\n]+$|'
    r'^[ \t]*(?:LOCATION|地点|场景)[ \t]*[:：-][^\n]+$|'
    r'^[ \t]*\[[^\]\n]+\][ \t]*$|'
    r'^[ \t]*[^\n]{2,80}[ \t]+[-—][ \t]+(?:DAY|NIGHT|MORNING|EVENING|AFTERNOON|白天|夜|晚上|清晨|黄昏)[^\n]*$',
    re.IGNORECASE | re.MULTILINE,
)


def _split_montage_candidates(raw_script: str, candidates: list[tuple]) -> list[tuple]:
    """Split a multi-location flash-cut into independently scoped blocks."""
    expanded = []
    for candidate in candidates:
        start, end, header, section, key, is_location_header = candidate
        if section != "montage":
            expanded.append(candidate)
            continue
        next_start = min((item[0] for item in candidates if item[0] > start), default=len(raw_script))
        body = raw_script[end:next_start]
        markers = list(_FLASH_LOCATION_LINE_RE.finditer(body))
        if len(markers) < 2:
            expanded.append(candidate)
            continue
        # The cue remains part of the first insert. Later inserts begin at
        # their own explicit location marker and receive distinct occurrences.
        for index, marker in enumerate(markers):
            marker_start = start if index == 0 else end + marker.start()
            marker_end = end + marker.end()
            marker_header = header if index == 0 else marker.group().strip()
            expanded.append((marker_start, marker_end, marker_header, section,
                             f"semantic_{section}_{start}_{index + 1:03d}", False))
    return expanded

SCENE_ENV_SYSTEM = """You are a film production designer. You receive the screenplay text of ONE scene.
Write the visual description of the PLACE ONLY, so an image model can paint the empty set.

Rules:
- Use only what the text says or clearly implies about the place: layout, materials, furniture,
  fixtures, signage, colors, lighting sources, time of day, weather, atmosphere.
- Ignore people, dialogue, actions, emotions and story. Never mention any person.
- Translate everything into English. Keep concrete details (materials, colors, light color/temperature).
- environment_prompt_en: one paragraph, 40-70 words, comma-separated visual phrases, no sentences about events.
- subject_scope MUST be exactly "place_only".
- people and props MUST both be empty arrays. If the source does not prove a place-only
  description, return "subject_scope":"rejected" instead of guessing.

Return ONLY JSON, no markdown:
{"scene_name_en": "<place name>", "environment_prompt_en": "<visual description of the empty set>", "subject_scope": "place_only", "people": [], "props": []}
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
    # Fallback: reuse the same cue-stripping routine used for source metadata.
    # The separator is part of the cue in forms such as
    # ``FLASHBACK - INT. WAREHOUSE - DAY``; removing only whitespace/colon
    # leaves a leading hyphen and creates a second physical-scene key.
    # OPEN ON: EXT. HARBOR - NIGHT, INTERCUT WITH EXT. HARBOR - CONTINUOUS,
    # and EXT. HARBOR - NIGHT must share one scene asset while occurrences
    # remain separate.
    cleaned = _physical_location_header(header)
    cleaned = re.sub(r'^(?:INT|EXT|INT/EXT)\.?\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r'\s*[-—]\s*(?:DAY|NIGHT|MORNING|EVENING|AFTERNOON|DAWN|DUSK|CONTINUOUS|LATER|'
        r'白天|夜|晚上|清晨|黄昏|连续|稍后|此时).*$','', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'^[：:.-]+|[：:.-]+$', '', cleaned).strip()
    cleaned = re.sub(r'[【】:：.]', '', cleaned).strip()
    return cleaned or header.strip()


def _section_type(header: str) -> str:
    text = (header or "").lower()
    # A cue prefix can carry a real physical heading on the same line, for
    # example ``INTERCUT WITH EXT. HARBOR - NIGHT`` or ``FLASHBACK - INT.
    # WAREHOUSE - DAY``. The cue is retained separately in the source block,
    # while the physical place remains a location scene.
    if re.search(r'\b(?:int|ext|int/ext)(?:\.|\s)', text):
        return "location_scene"
    if re.search(r"片头|片尾|opening|title|credits", text):
        return "title_sequence"
    if re.search(r"序幕|序章|引子|prologue|teaser", text):
        return "prologue"
    if re.search(r"尾声|结尾|epilogue|ending", text):
        return "epilogue"
    if re.search(r"闪回|flashback|闪进|flashforward", text):
        return "transition"
    if re.search(r"黑屏|black\s*screen|转场|transition|淡出|fade|cut\s+to|smash\s+cut|intercut|match\s+cut|jump\s+cut|dissolve|wipe", text):
        return "transition"
    if re.search(r"快速闪切|montage|闪切|quick\s+flash|flash\s*cut", text):
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
                           _normalize_scene_key(header), _section_type(header) == "location_scene"))
    for match in cues:
        if any(start <= match.start() < end for start, end in header_ranges):
            continue
        cue = match.group().strip()
        section = _section_type(cue)
        # [内景 - 日], [外景 - 日] and [连续] are annotations, not boundaries.
        candidates.append((match.start(), match.end(), cue, section,
                           f"semantic_{section}_{len(candidates) + 1:03d}", False))
    for match in _SCREENPLAY_CUE_LINE_RE.finditer(raw_script):
        if any(start <= match.start() < end for start, end in header_ranges):
            continue
        cue = match.group().strip()
        section = _section_type(cue)
        candidates.append((match.start(), match.end(), cue, section,
                           f"semantic_{section}_{len(candidates) + 1:03d}", False))
    for match in _GENERIC_SCREENPLAY_CUE_LINE_RE.finditer(raw_script):
        if any(start <= match.start() < end for start, end in header_ranges):
            continue
        cue = match.group().strip()
        # Only validated section/transition labels may use the generic
        # fallback. An all-caps ``JOHN: Hello`` or ``MARY - Run!`` line is
        # ordinary dialogue and must stay inside the surrounding location.
        if not _GENERIC_VALIDATED_CUE_RE.match(cue):
            continue
        section = _section_type(cue)
        candidates.append((match.start(), match.end(), cue, section,
                           f"semantic_{section}_{len(candidates) + 1:03d}", False))
    candidates = _split_montage_candidates(raw_script, candidates)
    candidates.sort(key=lambda item: item[0])
    # The generic location grammar intentionally overlaps the legacy INT/EXT
    # rule. Keep one boundary for each exact source range.
    deduped = []
    seen_ranges = set()
    for candidate in candidates:
        marker = (candidate[0], candidate[1])
        if marker not in seen_ranges:
            deduped.append(candidate)
            seen_ranges.add(marker)
    candidates = deduped

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
                                    "source_order": i, "scene_occurrence_id": occurrence_id, "header": header,
                                    "cue_prefix": _extract_cue_prefix(header),
                                    "physical_header": _physical_location_header(header),
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
    # Display and downstream asset identity use the physical heading, not the
    # cue prefix, while the source block retains the cue for editing/order.
    cleaned = _physical_location_header(header)
    cleaned = re.sub(r'[\[\]【】]', '', cleaned).strip()
    cleaned = re.sub(r'^[# \t]+', '', cleaned).strip()
    # Drop leading "场景 X" / "Scene X" prefixes, with either a colon,
    # dash, dot, or no delimiter (all are common customer heading forms).
    cleaned = re.sub(r'^(场景\s*[A-Za-z0-9一二三四五六七八九十\d]+|Scene\s*[A-Za-z0-9]+)\s*(?:[：:.-]|[-—])?\s*', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or header.strip()


def _extract_cue_prefix(header: str) -> str:
    """Return a screenplay cue that prefixes an embedded physical heading."""
    cleaned = re.sub(r'[【】\[\]]', '', str(header or '')).strip()
    match = re.match(
        r'^(?P<cue>(?:OPEN\s+ON|OPENING\s+IMAGE|SMASH\s+CUT\s+TO|MATCH\s+CUT\s+TO|'
        r'JUMP\s+CUT\s+TO|CUT\s+TO|INTERCUT(?:\s+WITH)?|FLASHBACK|FLASHFORWARD|'
        r'DISSOLVE\s+TO|WIPE\s+TO))\s*(?:[:\-—])?[ \t]*(?=(?:INT|EXT|INT/EXT)\.)',
        cleaned, re.IGNORECASE,
    )
    return match.group('cue') if match else ''


def _physical_location_header(header: str) -> str:
    """Remove a cue prefix while retaining the embedded INT/EXT heading."""
    cleaned = re.sub(r'[【】\[\]]', '', str(header or '')).strip()
    return re.sub(
        r'^(?:OPEN\s+ON|OPENING\s+IMAGE|SMASH\s+CUT\s+TO|MATCH\s+CUT\s+TO|'
        r'JUMP\s+CUT\s+TO|CUT\s+TO|INTERCUT(?:\s+WITH)?|FLASHBACK|FLASHFORWARD|'
        r'DISSOLVE\s+TO|WIPE\s+TO)[ \t]*(?:[:\-—])?[ \t]*(?=(?:INT|EXT|INT/EXT)\.)',
        '', cleaned, flags=re.IGNORECASE,
    ).strip()


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
            prompt_text = block.get("prompt_source_text", block.get("source_text", ""))
            lines.append(
                f"    source_block_id={block['source_block_id']} "
                f"scene_occurrence_id={block['scene_occurrence_id']} "
                f"section_type={block['section_type']}: {prompt_text[:120]}..."
            )
            for unit in _source_units_with_offsets(block.get("source_text", "")):
                allowed = block.get("batch_unit_ids")
                if allowed and unit["unit_id"] not in allowed:
                    continue
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


def _source_tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{2,}", _compact_source(value).lower())}


_FACT_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "to", "of", "for", "from", "with", "in", "on", "at",
    "as", "by", "into", "then", "while", "her", "his", "their", "he", "she", "they", "it", "this",
    "that", "is", "are", "was", "were", "be", "being", "very", "slightly", "slowly", "quickly",
    "camera", "shot", "frame", "view", "null", "none",
}


def _fact_tokens(value: str) -> set[str]:
    tokens = _source_tokens(value)
    result = set()
    for token in tokens:
        if token in _FACT_STOPWORDS:
            continue
        # Small normalization catches reaches/reached/reaching without making
        # unrelated verbs such as reaches and runs interchangeable.
        stem = token
        for suffix in ("ing", "ed", "es", "s"):
            if len(stem) > 4 and stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        result.add(stem)
    return result


def _fact_is_supported(value: object, source_text: str) -> bool:
    """Require a fact to occur in one local source span.

    Exact prose is preferred. A short structured paraphrase may omit a source
    adjective or inflect a verb, but words may not be gathered from distant
    actions or subjects.
    """
    text = _compact_source(str(value or ""))
    if not text:
        return True
    source = _compact_source(source_text).lower()
    if text.lower() in source:
        return True
    def token_key(token: str) -> str:
        stem = token
        for suffix in ("ing", "ed", "es", "s"):
            if len(stem) > 4 and stem.endswith(suffix):
                return stem[:-len(suffix)]
        return stem

    fact_tokens = [token_key(token) for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower())]
    source_tokens = [token_key(token) for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", source)]
    if not fact_tokens or not source_tokens:
        return False
    for start, token in enumerate(source_tokens):
        if token != fact_tokens[0]:
            continue
        position = start
        matched = True
        for wanted in fact_tokens[1:]:
            next_positions = [
                index for index in range(position + 1, min(len(source_tokens), position + 4))
                if source_tokens[index] == wanted
            ]
            if not next_positions:
                matched = False
                break
            position = next_positions[0]
        if matched and position - start <= len(fact_tokens) + 2:
            return True
    return False


# These are screenplay facts, not free-form visual decoration.  A missing
# Phase-1 value may only be filled by Phase 2 when the exact source fragment
# supports it. Camera framing remains a deterministic production direction;
# camera motion is validated separately from the preserved source text.
_FACT_FIELDS = (
    "action", "business", "emotion", "facial_expression", "micro_expression", "micro_emotion",
    "gaze", "body_language", "action_start", "action_process", "action_end", "props_list",
    "prop_interactions", "dialogue", "location", "time_of_day", "weather", "lighting",
    "color_temperature", "camera_path", "costume_en", "costume_description",
)

# These fields are production directions. The phase-2 prompt is explicitly
# allowed to derive them from the shot semantics, so they must not be treated
# as screenplay quotations. Keep their provenance separately instead.
_DIRECTION_FIELDS = ("shot_type", "camera_angle", "pace", "lighting_style", "director_notes")
_DIRECTION_ALIASES = {
    "shot_type": {
        "wide shot": "wide", "wide_shot": "wide", "establishing shot": "wide",
        "full shot": "full_body", "full body": "full_body", "full_body shot": "full_body",
        "medium shot": "medium", "medium close-up": "medium_close_up",
        "medium close up": "medium_close_up", "medium_close_up shot": "medium_close_up",
        "close-up": "close_up", "close up": "close_up", "close_up shot": "close_up",
        "extreme close-up": "extreme_close_up", "extreme close up": "extreme_close_up",
    },
    "camera_angle": {
        "eye level": "eye_level", "eye-level": "eye_level", "low angle": "low_angle",
        "low-angle": "low_angle", "high angle": "high_angle", "high-angle": "high_angle",
        "dutch angle": "dutch", "dutch tilt": "dutch",
    },
}


def _canonical_direction(field: str, value):
    """Canonicalize enum-like directions while preserving free-form direction text."""
    if not _present(value):
        return value
    if isinstance(value, (list, tuple, dict)):
        return value
    text = str(value).strip()
    key = re.sub(r"\s+", " ", text.lower().replace("_", " ").replace("–", "-")).strip()
    return _DIRECTION_ALIASES.get(field, {}).get(key, text)


def _direction_provenance(field: str, value, source_fragment: str) -> str:
    """Mark exact screenplay directions as script facts and all others derived."""
    return "script" if _present(value) and _fact_is_supported(value, source_fragment) else "derived"



def _fact_validation_errors(data: dict, source_fragment: str, source_block_text: str,
                            phase: str = "structured") -> list[str]:
    errors = []
    source = str(source_fragment or "")
    block = str(source_block_text or "")
    for field in _FACT_FIELDS:
        value = data.get(field)
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if not _present(item):
                continue
            evidence = block if field == "location" and not source else source
            if not _fact_is_supported(item, evidence):
                errors.append(f"{phase} {field} fact is not supported by the exact source: {item}")
    for field in ("character_names",):
        for item in data.get(field) or []:
            if _present(item) and not _fact_is_supported(item, source):
                errors.append(f"{phase} character fact is not supported by the exact source: {item}")
    return errors


def _phase1_fact_validation_errors(shot: dict, source_fragment: str, source_block_text: str) -> list[str]:
    """Reject every Phase-1 fact that is not grounded in its verified span."""
    return _fact_validation_errors(shot, source_fragment, source_block_text, "Phase 1")


def _validate_cast_against_script(cast_list: list, raw_script: str) -> None:
    source = _source_tokens(raw_script)
    unknown = []
    for entry in cast_list or []:
        if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
            unknown.append("<missing name>")
            continue
        name = str(entry["name"]).strip()
        if not _source_tokens(name).intersection(source):
            unknown.append(name)
    if unknown:
        raise ValueError("剧本分镜解析被阻止：角色清单包含原文未出现的人物：" + ", ".join(unknown))


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
        declared_fragment = _first_present(shot.get("source_shot_text"), default="")
        if declared_fragment and str(declared_fragment) != fragment:
            return "", "source_shot_text does not match source_unit_ids verbatim"
        return fragment, ""

    start = shot.get("source_start")
    end = shot.get("source_end")
    has_offsets = start is not None or end is not None
    if has_offsets:
        if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(source)):
            return "", "source offsets are outside this source block"
        fragment = source[start:end]
        if not fragment.strip():
            return "", "source offsets point to empty text"
        declared_fragment = _first_present(shot.get("source_shot_text"), default="")
        if declared_fragment:
            if str(declared_fragment) != fragment:
                return "", "source offsets do not match source_shot_text verbatim"
            return fragment, ""
        # Without verbatim evidence, offsets must cover one or more complete,
        # adjacent source units. Arbitrary in-bounds slices can point at a
        # sibling action and are therefore unsafe to send to phase 2.
        starts = {unit["start"] for unit in units}
        ends = {unit["end"] for unit in units}
        if start not in starts or end not in ends:
            return "", "source offsets do not align with source-unit boundaries"
        selected = [unit for unit in units if start <= unit["start"] and unit["end"] <= end]
        if not selected or selected[0]["start"] != start or selected[-1]["end"] != end:
            return "", "source offsets do not cover adjacent source units"
        return fragment, ""

    model_fragment = _first_present(shot.get("source_shot_text"), raw_desc, default="")
    if model_fragment:
        model_fragment = str(model_fragment)
        exact_matches = [match.start() for match in re.finditer(re.escape(model_fragment), source)]
        if len(exact_matches) == 1:
            exact_start = exact_matches[0]
            return source[exact_start:exact_start + len(model_fragment)], ""
        if len(exact_matches) > 1:
            return "", "source_shot_text matches multiple source spans; provide unique source_unit_ids or offsets"
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


def _phase1_source_coverage_errors(shots: list, scene_map: list[dict], target_count: int) -> list[str]:
    """Validate that phase 1 did not silently omit or duplicate screenplay spans.

    Phase 2 is deliberately not allowed to enrich a truncated or reordered shot
    list.  Source-unit evidence is local to each source block, while block order
    is global screenplay order.  This permits several shots from one block but
    rejects the common failure where the model repeats its first valid block and
    never covers a later location/occurrence.
    """
    errors: list[str] = []
    if len(shots) != target_count:
        errors.append(f"分镜数量不完整：需要 {target_count} 个，模型返回 {len(shots)} 个")

    blocks_by_id = {}
    block_order = {}
    all_units = {}
    for scene in scene_map:
        for block in scene.get("source_blocks", []):
            block_id = str(block.get("source_block_id") or "")
            if not block_id:
                continue
            units = _source_units_with_offsets(block.get("source_text", ""))
            allowed_ids = {str(value) for value in (block.get("batch_unit_ids") or [])}
            if allowed_ids:
                units = [unit for unit in units if unit["unit_id"] in allowed_ids]
            blocks_by_id[block_id] = block
            all_units[block_id] = units
    ordered_block_ids = sorted(
        blocks_by_id,
        key=lambda value: (int(re.search(r"(\d+)$", value).group(1))
                           if re.search(r"(\d+)$", value) else 10**9, value),
    )
    block_order.update({block_id: position for position, block_id in enumerate(ordered_block_ids)})

    covered: dict[str, set[str]] = {key: set() for key in blocks_by_id}
    evidence_positions: list[tuple[int, int, str, str]] = []
    for index, shot in enumerate(shots):
        sid = str(shot.get("shot_id") or f"shot_{index + 1:03d}")
        block_id = str(shot.get("source_block_id") or "").strip()
        if block_id not in blocks_by_id:
            errors.append(f"{sid}: 缺少或无效 source_block_id={block_id or '<empty>'}")
            continue
        block = blocks_by_id[block_id]
        units = all_units[block_id]
        by_id = {unit["unit_id"]: unit for unit in units}
        selected = []
        requested_ids = shot.get("source_unit_ids")
        if isinstance(requested_ids, str):
            requested_ids = [requested_ids]
        if requested_ids:
            ids = [str(value).strip() for value in requested_ids if str(value).strip()]
            if any(unit_id not in by_id for unit_id in ids):
                errors.append(f"{sid}: source_unit_ids 不属于 {block_id}")
                continue
            if ids != sorted(ids, key=lambda unit_id: by_id[unit_id]["start"]):
                errors.append(f"{sid}: source_unit_ids 未按原文顺序排列")
                continue
            selected = [by_id[unit_id] for unit_id in ids]
        else:
            start, end = shot.get("source_start"), shot.get("source_end")
            if isinstance(start, int) and isinstance(end, int):
                selected = [unit for unit in units if start <= unit["start"] and unit["end"] <= end]
                if not selected or selected[0]["start"] != start or selected[-1]["end"] != end:
                    errors.append(f"{sid}: source offsets 未覆盖 {block_id} 的完整原文单元")
                    continue
            else:
                declared = _first_present(shot.get("source_shot_text"), shot.get("raw_description"), default="")
                matches = [match.start() for match in re.finditer(re.escape(str(declared)), block.get("source_text", ""))] if declared else []
                if len(units) == 1:
                    # A block containing one source unit has one deterministic
                    # span. The later exact-fragment validator still protects
                    # multi-unit blocks from sibling leakage.
                    selected = units
                else:
                    errors.append(f"{sid}: 缺少可验证的原文片段，无法确认 {block_id} 的来源")
                    continue
        if not selected:
            errors.append(f"{sid}: 没有覆盖 {block_id} 的原文单元")
            continue
        selected_ids = [unit["unit_id"] for unit in selected]
        duplicate = [unit_id for unit_id in selected_ids if unit_id in covered[block_id]]
        if duplicate:
            errors.append(f"{sid}: 重复覆盖 {block_id} 的原文单元 {', '.join(duplicate)}")
        covered[block_id].update(selected_ids)
        evidence_positions.append((block_order[block_id], selected[0]["start"], block_id, sid))

    covered_blocks = {item[2] for item in evidence_positions}
    missing_blocks = [block_id for block_id in all_units if block_id not in covered_blocks]
    for block_id in missing_blocks:
        block = blocks_by_id[block_id]
        errors.append(f"遗漏原文段 {block_id}（{_compact_source(block.get('source_text', ''))[:160]}）")
    for block_id, units in all_units.items():
        missing = [unit["text"] for unit in units if unit["unit_id"] not in covered[block_id]]
        if missing:
            spans = " | ".join(_compact_source(text)[:120] for text in missing)
            errors.append(f"{block_id} 遗漏原文单元：{spans}")

    ordered = [(block, start) for block, start, _, _ in evidence_positions]
    if ordered != sorted(ordered):
        errors.append("分镜来源顺序与剧本顺序不一致，存在跨场景或跨段落错序")
    return errors


_CAMERA_STATIC_CUE_RE = re.compile(
    # Do not treat an ordinary action such as "hold the cup" as a locked shot.
    r"\b(?:static|fixed|still)\s+(?:camera|shot|frame|view)\b|"
    r"\b(?:locked(?:[- ]off)?|fixed|still)\s+(?:camera|shot|frame|view)\b|"
    r"\b(?:camera|shot|frame|view)\s+(?:is\s+)?(?:static|fixed|still|locked(?:[- ]off)?)\b|"
    r"\bhold\s+(?:on\s+)?(?:the\s+)?(?:camera|shot|frame|view)\b|"
    # Reaction/subject holds are director camera cues; ordinary object actions
    # such as "hold the cup" remain outside this expression.
    r"\bhold\s+(?:on\s+)?(?:the\s+)?(?:reaction|subject|expression|face|response)\b|"
    r"\bhold\s+on\s+(?:his|her|their)\s+(?:reaction|expression|face)\b|"
    r"(?:固定机位|固定镜头|定机位|镜头停留|画面停留|"
    r"(?:镜头|机位|画面)(?:保持不动|静止|固定)|"
    r"(?:保持不动|静止|固定)(?:镜头|机位|画面))", re.IGNORECASE,
)
_CAMERA_MOTION_CUE_RE = re.compile(
    r"\b(?:camera|shot|frame)\s+(?:slowly\s+)?(?:push(?:es)? in|dolly|pull(?:s)? back|zoom(?:s)?|pan(?:s)?|"
    r"track(?:s)?|crane|handheld|orbit(?:s)?)\b|"
    r"\b(?:push(?:es)? in|dolly|pull(?:s)? back|zoom(?:s)?|pan(?:s)?|tracking|track(?:s)?|"
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
    if re.search(r"(?:横移|平移|horizontal\s+pan)", text, re.IGNORECASE):
        return "pan_horizontal"
    if re.search(r"(?:zoom|dolly)[^.!?\n]{0,16}(?:out|back)|(?:zoom|dolly)\s+out", low):
        return "slow_pull_back"
    if re.search(r"(?:zoom|dolly)[^.!?\n]{0,16}(?:in|closer)|(?:zoom|dolly)\s+in", low):
        return "slow_push_in"
    if re.search(r"(?:pull(?:s)? back|dolly out|拉远|拉镜)", low if not any(ord(c) > 127 for c in text) else text):
        return "slow_pull_back"
    if re.search(r"(?:push(?:es)? in|dolly in|推进|推近)", low if not any(ord(c) > 127 for c in text) else text):
        return "slow_push_in"
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


def _select_batch_scene_map(scene_map: list[dict], total_shots: int,
                            shot_start: int, shot_end: int) -> list[dict]:
    """Keep only the exact ordered source units assigned to this batch."""
    flat = []
    for scene in scene_map:
        for block in scene.get("source_blocks", []):
            for unit in _source_units_with_offsets(block.get("source_text", "")):
                flat.append((scene, block, unit))
    def source_order(item):
        block = item[1]
        if block.get("source_order") is not None:
            return int(block["source_order"])
        match = re.search(r"(\d+)$", str(block.get("source_block_id") or ""))
        return int(match.group(1)) if match else len(flat)
    flat.sort(key=source_order)
    if len(flat) < total_shots:
        raise ValueError(
            f"原文只有 {len(flat)} 个可验证 source unit，无法安全生成 {total_shots} 个镜头；"
            "不会复制原文或静默填充镜头。"
        )
    lo = (shot_start - 1) * len(flat) // total_shots
    hi = shot_end * len(flat) // total_shots
    if shot_end == total_shots:
        hi = len(flat)
    selected = {(id(scene), block.get("source_block_id")): set()
                for scene, block, _ in flat[lo:hi]}
    for scene, block, unit in flat[lo:hi]:
        selected[(id(scene), block.get("source_block_id"))].add(unit["unit_id"])
    result = []
    for scene in scene_map:
        blocks = []
        for block in scene.get("source_blocks", []):
            ids = selected.get((id(scene), block.get("source_block_id")))
            if not ids:
                continue
            copy = dict(block)
            copy["batch_unit_ids"] = sorted(ids, key=lambda value: int(value.rsplit("_", 1)[-1]))
            copy["prompt_source_text"] = "\n".join(
                unit["text"] for unit in _source_units_with_offsets(block.get("source_text", ""))
                if unit["unit_id"] in ids
            )
            blocks.append(copy)
        if blocks:
            copy = dict(scene)
            copy["source_blocks"] = blocks
            copy["source_text"] = "\n".join(block.get("prompt_source_text", "") for block in blocks)
            result.append(copy)
    return result


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
                "batch_start_shot": ("INT", {"default": 1, "min": 1, "max": 100000}),
                "batch_end_shot": ("INT", {"default": 0, "min": 0, "max": 100000}),
                "batch_context_json": ("STRING", {"default": "", "multiline": True}),
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
                     model_path: str = "LLM/Qwen2.5-7B-Instruct",
                     batch_start_shot: int = 1,
                     batch_end_shot: int = 0,
                     batch_context_json: str = ""):

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

        # Every parser invocation is a bounded batch. The WebUI supplies the
        # persisted session context; direct/manual node calls also return a
        # partial batch and can never publish a complete screenplay analysis.
        requested_end = int(batch_end_shot or 0)
        batch_mode = True
        if requested_end > 0:
            batch_start_shot = max(1, int(batch_start_shot))
            batch_end_shot = requested_end
        else:
            batch_start_shot = 1
            batch_end_shot = min(DEFAULT_DIRECT_BATCH_SIZE, target_shot_count)
        total_shot_count = target_shot_count
        target_batch_count = batch_end_shot - batch_start_shot + 1
        target_shot_count = target_batch_count
        if batch_end_shot > total_shot_count:
            raise ValueError("批次镜头范围超过剧本目标镜头数")

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
        if batch_mode and batch_context_json.strip():
            try:
                context = json.loads(batch_context_json)
                supplied = context.get("scene_map", context) if isinstance(context, dict) else context
                if isinstance(supplied, list) and supplied:
                    scene_map = supplied
                else:
                    raise ValueError("批次上下文缺少精确 scene_map")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"批次上下文不是有效 JSON：{exc}") from exc
        else:
            scene_map = _select_batch_scene_map(
                scene_map, total_shot_count, batch_start_shot, batch_end_shot
            )
        scene_map_text = _scene_map_to_prompt_text(scene_map)
        logger.info("[AFE_ScriptFullParser] Pre-segmented %d unique scene(s) from screenplay",
                    len(scene_map))
        for s in scene_map:
            logger.info("  scene_index=%d: %s", s["scene_index"], s["sample_header"][:60])

        # 2. Phase 1: single LLM call → cast + minimal shots
        logger.info("[AFE_ScriptFullParser] Phase 1: parsing script (target %d shots × %ds = %ds)...",
                    target_shot_count, seconds_per_shot, target_duration_seconds)
        phase1_user = (
            f"Generate EXACTLY {target_shot_count} shots for global shot IDs "
            f"shot_{batch_start_shot:03d} through shot_{batch_end_shot:03d} "
            f"(total {target_shot_count * seconds_per_shot}s at {seconds_per_shot}s each). "
            f"This is one contiguous batch; do not describe shots outside this range. "
            f"Episode format: {episode_format}. "
            f"Break scenes and dialogue into individual {seconds_per_shot}-second moments.\n\n"
            f"{scene_map_text}\n\n"
            f"Screenplay source for this batch:\n"
            f"{raw_script if not batch_mode else chr(10).join(s.get('source_text', '') for s in scene_map)}"
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
        # Models often restart numbering inside a small request. Canonicalise
        # only the requested contiguous range, never inventing missing shots.
        for local_index, item in enumerate(minimal_shots):
            if isinstance(item, dict):
                item["shot_id"] = f"shot_{batch_start_shot + local_index:03d}"
        _validate_cast_against_script(cast_list, raw_script)
        batch_duration = target_shot_count * seconds_per_shot if batch_mode else target_duration_seconds
        minimal_shots = _normalize_durations(minimal_shots, batch_duration, seconds_per_shot)
        logger.info(f"[AFE_ScriptFullParser] Phase 1 done: {len(cast_list)} cast, {len(minimal_shots)} shots")

        # Do not let Phase 2 make a truncated or reordered Phase 1 result look
        # complete. Every source block/unit must be represented exactly once
        # and the model must honor the requested shot count before enrichment.
        coverage_errors = _phase1_source_coverage_errors(
            minimal_shots, scene_map, target_shot_count
        )
        if coverage_errors:
            detail = "\n".join(f"  - {error}" for error in coverage_errors[:40])
            raise ValueError(
                "剧本分镜解析被阻止：Phase 1 没有完整覆盖原文。请重试；"
                "系统未继续生成可能遗漏场景、动作或对白的分镜。\n" + detail
            )

        # 3a. Build scene_index → scene_name lookup (code-level, guaranteed consistent).
        # scene_name is derived directly from the regex-detected header text, NOT
        # regenerated by the LLM each time — this is what prevents scene collapse/drift.
        scene_index_to_name = {
            s["scene_index"]: _header_to_scene_name(s["sample_header"])
            for s in scene_map
        }

        # 3a-2. One LLM call per scene: screenplay text -> English environment prompt
        # (place only, no people). A missing environment is a hard analysis error:
        # a generic name/location fallback would silently lose set facts.
        scene_env: dict[int, dict] = {}
        for s in scene_map:
            idx = s["scene_index"]
            src = s.get("source_text", "")
            if not src.strip():
                raise ValueError(f"场景 {idx}（{s.get('sample_header', '')}）没有可用的原文环境")
            try:
                env_raw = self._call_llm(
                    SCENE_ENV_SYSTEM,
                    f"Scene header: {s['sample_header']}\n\nScene screenplay text:\n{src}",
                    model_path, max_new_tokens=400,
                )
                env_data = self._parse_llm_json(env_raw)
                environment_prompt = (env_data.get("environment_prompt_en", "")
                                      if isinstance(env_data, dict) else "")
                scene_name_en = (env_data.get("scene_name_en", "")
                                 if isinstance(env_data, dict) else "")
                scope = env_data.get("subject_scope") if isinstance(env_data, dict) else None
                people_present = isinstance(env_data, dict) and "people" in env_data
                props_present = isinstance(env_data, dict) and "props" in env_data
                people = env_data.get("people") if people_present else None
                props = env_data.get("props") if props_present else None
                if (not str(environment_prompt).strip() or not str(scene_name_en).strip()
                        or scope != "place_only" or not people_present or not props_present
                        or not isinstance(people, list) or not isinstance(props, list)
                        or people != [] or props != []):
                    raise ValueError(
                        "返回内容不是可证明的 place-only 结构化环境（必须 subject_scope=place_only 且 people/props 必须存在并且是空数组）"
                    )
                scene_env[idx] = {
                    "scene_name_en": str(scene_name_en).strip(),
                    "environment_prompt_en": str(environment_prompt).strip(),
                    "subject_scope": "place_only",
                    "people": [],
                    "props": [],
                }
                logger.info("[AFE_ScriptFullParser] Scene %d env: %s", idx,
                            scene_env[idx]["environment_prompt_en"][:100])
            except Exception as exc:
                raise ValueError(
                    f"场景 {idx}（{s.get('sample_header', '')}）的空场景环境分析失败：{exc}。"
                    "未使用降级地点提示词，请重试或检查语言模型。"
                ) from exc

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
            fact_validation_errors = _phase1_fact_validation_errors(
                shot, source_shot_text, source_block_text
            ) if not source_validation_error else []
            invalid_phase1_fields = set()
            if fact_validation_errors:
                assignment_errors.extend(
                    f"{shot_id}: {error}" for error in fact_validation_errors
                )
                # Invalid Phase-1 values must not reach either renderer, and
                # must not be used as a fallback when Phase 2 omits a field.
                for field in _FACT_FIELDS:
                    if any(f" {field} fact " in error for error in fact_validation_errors):
                        invalid_phase1_fields.add(field)
                        shot[field] = [] if isinstance(shot.get(field), list) else None
            if source_validation_error:
                assignment_errors.append(f"{shot_id}: {source_validation_error}")
            dialogue   = _first_present(shot.get("dialogue"), default="")
            props_list = _clean_semantic(shot.get("props_list")) or []

            fact_validation_error = "; ".join(fact_validation_errors)

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
                p2_raw = self._call_llm(PHASE2_SYSTEM, p2_user, model_path, max_new_tokens=768)
                p2_data = self._parse_llm_json(p2_raw)
                if not isinstance(p2_data, dict) or not p2_data:
                    raise ValueError("Phase 2 返回为空或不是 JSON 对象")
            except Exception as exc:
                logger.error("[AFE_ScriptFullParser] Phase 2 failed for %s: %s", shot_id, exc)
                raise ValueError(
                    f"分镜 {shot_id} 的 Phase 2 深度解析失败：{exc}。"
                    "已阻止保存不完整分析，请重试剧本分析。"
                ) from exc

            # Phase 2 is also untrusted. Keep only values whose words are
            # supported by this exact source fragment. This prevents a missing
            # Phase-1 field from becoming a hallucinated action, person,
            # location, prop, expression, dialogue, light, or weather cue.
            phase2_fact_errors = _fact_validation_errors(
                p2_data, source_shot_text, source_block_text, "Phase 2"
            )
            if phase2_fact_errors:
                assignment_errors.extend(f"{shot_id}: {error}" for error in phase2_fact_errors)
                for field in _FACT_FIELDS:
                    if field in invalid_phase1_fields or (not _present(shot.get(field)) and field in p2_data):
                        p2_data[field] = [] if isinstance(p2_data.get(field), list) else None

            # Keep the verified Phase 1/source description canonical. Phase 2
            # may populate structured fields, but its prose cannot introduce a
            # second location or contradictory action into either renderer.
            sd = _first_present(source_shot_text, default="")
            if not sd:
                raise ValueError(
                    f"分镜 {shot_id} 缺少可验证的原文描述，已阻止生成。"
                )
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
            # Phase 1 is the structured extraction of the exact source moment.
            # Phase 2 may enrich missing fields, but it must never replace a
            # source/Phase-1 fact with a contradictory model guess.
            get_fact = lambda key, *fallbacks: _first_present(
                shot.get(key), *(shot.get(k) for k in fallbacks), p2_data.get(key)
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
            prop_interactions = _first_present(
                shot.get("prop_interactions"), p2_data.get("prop_interactions"), default=[]
            )
            camera_angle = _canonical_direction(
                "camera_angle", get_fact("camera_angle")
            )
            shot_type = _canonical_direction(
                "shot_type", get_fact("shot_type")
            )
            lighting_style = get_fact("lighting_style")
            director_notes = get_fact("director_notes")
            direction_provenance = {
                field: _direction_provenance(field, value, source_shot_text)
                for field, value in (("shot_type", shot_type), ("camera_angle", camera_angle),
                                     ("pace", get_fact("pace", "rhythm")),
                                     ("lighting_style", lighting_style),
                                     ("director_notes", director_notes))
            }
            location = _first_present(
                shot.get("location"), shot.get("scene_name"), default=scene_name
            )
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
                "source_validation_error": "; ".join(filter(None, [source_validation_error, fact_validation_error])),
                "raw_description":   raw_desc,
                "scene_assignment_error": shot.get("scene_assignment_error") or source_validation_error or fact_validation_error,
                "environment": {
                    "description": scene_env.get(scene_idx, {}).get("environment_prompt_en", ""),
                    "scope": scene_env.get(scene_idx, {}).get("subject_scope", ""),
                    "people": scene_env.get(scene_idx, {}).get("people", []),
                    "props": scene_env.get(scene_idx, {}).get("props", []),
                    "location": location,
                    "time_of_day": time_of_day,
                    "weather": weather,
                    "lighting": lighting,
                    "color_temperature": color_temperature,
                },
                "character_names":  char_names,
                "costume_description": _first_present(shot.get("costume_description"), p2_data.get("costume_description")),
                "costume_en":          _first_present(shot.get("costume_en"), p2_data.get("costume_en")),
                "props_list":          props_list,
                "scene_name":          scene_name,
                "scene_name_en":       scene_env.get(scene_idx, {}).get("scene_name_en", ""),
                "scene_environment_en": scene_env.get(scene_idx, {}).get("environment_prompt_en", ""),
                "shot_type":           shot_type,
                "shot_type_source":    direction_provenance["shot_type"],
                "camera_angle":        camera_angle,
                "camera_angle_source": direction_provenance["camera_angle"],
                "camera_motion":       camera_motion,
                "camera_motion_source": camera_motion_source,
                "camera_motion_explicit": camera_motion_explicit,
                "lighting_style":      lighting_style,
                "lighting_style_source": direction_provenance["lighting_style"],
                "director_notes":      director_notes,
                "director_notes_source": direction_provenance["director_notes"],
                "shot_description":    sd,
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
                "pace_source":         direction_provenance["pace"],
                "direction_provenance": direction_provenance,
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
        source_manifest = []
        for scene in scene_map:
            for block in scene.get("source_blocks", []):
                units = _source_units_with_offsets(block.get("source_text", ""))
                allowed = {str(value) for value in (block.get("batch_unit_ids") or [])}
                if allowed:
                    units = [unit for unit in units if unit["unit_id"] in allowed]
                source_manifest.append({
                    "scene_id": scene.get("scene_id"),
                    "scene_occurrence_id": block.get("scene_occurrence_id"),
                    "source_block_id": block.get("source_block_id"),
                    "section_type": block.get("section_type", scene.get("section_type")),
                    "unit_ids": [unit["unit_id"] for unit in units],
                })
        source_manifest.sort(key=lambda item: int(re.search(r"(\d+)$", item["source_block_id"]).group(1)))
        for order, item in enumerate(source_manifest):
            item["order"] = order
        analysis_payload = {
            "schema_version": "afe-analysis-v1",
            "analysis_status": "partial" if batch_mode else "complete",
            "expected_shot_count": target_shot_count,
            "batch_start_shot": batch_start_shot,
            "batch_end_shot": batch_end_shot,
            "source_manifest": source_manifest,
            "shots": full_shots,
            "cast": cast_list,
        }
        shots_json = json.dumps(full_shots, ensure_ascii=False, indent=2)
        cast_json  = json.dumps(cast_list,  ensure_ascii=False, indent=2)

        return {
            "ui": {"text": [report],
                   "afe_analysis": [json.dumps(analysis_payload, ensure_ascii=False)]},
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
