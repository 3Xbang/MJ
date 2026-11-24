"""Deterministic source spans used to plan and validate screenplay batches."""
from __future__ import annotations

import re

# A line-scoped explicit shot heading is a hard source boundary.  The heading
# stays in the same unit as its body so an action, expression, or dialogue
# cannot be split between parser batches.
EXPLICIT_SHOT_HEADER_RE = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:镜头|shots?)[ \t]*(?:[_#.\-—:：]?[ \t]*)?"
    r"(?P<number>\d{1,4})"
    r"(?:[ \t]*(?:[（(][^)）\n]{0,40}[)）]|[-—:：][^\n]{0,80}))?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def _trimmed_unit(source: str, start: int, end: int, unit_id: str, **metadata) -> dict:
    raw = source[start:end]
    left = len(raw) - len(raw.lstrip())
    right = len(raw.rstrip())
    if left >= right:
        return {}
    return {
        "unit_id": unit_id,
        "start": start + left,
        "end": start + right,
        "text": source[start + left:start + right],
        **metadata,
    }


def _explicit_units(source: str, markers: list[re.Match]) -> list[dict]:
    units: list[dict] = []
    preamble = _trimmed_unit(source, 0, markers[0].start(), "context_001",
                              is_context=True, is_explicit_shot=False)
    if preamble:
        units.append(preamble)
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(source)
        unit = _trimmed_unit(
            source, marker.start(), end, f"unit_{index + 1:03d}",
            is_context=False, is_explicit_shot=True,
            shot_number=int(marker.group("number")),
        )
        if unit:
            units.append(unit)
    return units


def source_units_with_offsets(source_text: str) -> list[dict]:
    """Return ordered, non-overlapping source units with stable offsets.

    Explicit shot headings take precedence over sentence/paragraph splitting.
    A pre-heading context unit is retained for prompts but is marked as context
    and is never assigned to a shot range.  Scripts without explicit headings
    retain the existing sentence/paragraph behavior.
    """
    source = str(source_text or "")
    markers = list(EXPLICIT_SHOT_HEADER_RE.finditer(source))
    if markers:
        return _explicit_units(source, markers)

    boundary = re.compile(
        r"\n\s*\n+|(?<=[。！？!?])\s+|(?<=[。！？!?])(?=[\u4e00-\u9fff])|(?<=[.!?])\s+"
    )
    units = []
    start = 0
    for match in boundary.finditer(source):
        unit = _trimmed_unit(source, start, match.start(), f"unit_{len(units) + 1:03d}",
                              is_context=False, is_explicit_shot=False)
        if unit:
            units.append(unit)
        start = match.end()
    unit = _trimmed_unit(source, start, len(source), f"unit_{len(units) + 1:03d}",
                         is_context=False, is_explicit_shot=False)
    if unit:
        units.append(unit)
    return units


def explicit_shot_units(units: list[dict]) -> list[dict]:
    """Return only explicit shot units, preserving screenplay order."""
    return [unit for unit in units if unit.get("is_explicit_shot")]
