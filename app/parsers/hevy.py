"""PROVISIONAL parser for the workout text Hevy writes into a Strava description.

Real Hevy output varies, so this is deliberately tolerant. A line is either a
set ("Set 2: 80 kg x 5", "80kg × 5", "12 reps") or a heading. A heading followed
by sets is an exercise; a leading heading with no sets is the workout title.
Validate against YOUR real descriptions before trusting it (see DECISIONS.md).
"""
from __future__ import annotations

import re

from app.metrics.strength import SetEntry

LB_TO_KG = 0.45359237
SET_RE = re.compile(
    r"^(?:set\s*\d+\s*[:\-]?\s*)?(\d+(?:[.,]\d+)?)\s*(kg|lbs?)?\s*[x×]\s*(\d+)\b", re.I)
BW_RE = re.compile(r"^(?:set\s*\d+\s*[:\-]?\s*)?(\d+)\s*reps?\b", re.I)
PREFIX_RE = re.compile(r"^\s*(?:\d+[.)]\s*|[-•*]\s*)")
NOISE_RE = re.compile(r"^(logged with|hevy\b|https?://)", re.I)


def _classify(line: str):
    m = SET_RE.match(line)
    if m:
        w = float(m.group(1).replace(",", "."))
        if (m.group(2) or "kg").lower().startswith("lb"):
            w *= LB_TO_KG
        return "set", (round(w, 2), int(m.group(3)))
    b = BW_RE.match(line)
    if b:
        return "set", (0.0, int(b.group(1)))
    heading = PREFIX_RE.sub("", line).strip(" :")
    return ("head", heading) if heading else (None, None)


def parse_description(text: str | None) -> tuple[str, list[SetEntry]]:
    """Returns (title, sets). Empty list if nothing parseable."""
    if not text:
        return "", []
    items = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or NOISE_RE.match(line):
            continue
        kind, val = _classify(line)
        if kind:
            items.append((kind, val))

    title, current, sets = "", None, []
    for i, (kind, val) in enumerate(items):
        if kind == "head":
            followed_by_set = i + 1 < len(items) and items[i + 1][0] == "set"
            if followed_by_set:
                current = val
            elif not title and not sets:
                title = val
            else:
                current = None
        elif current:
            sets.append(SetEntry(current, val[0], val[1]))
    return title, sets
