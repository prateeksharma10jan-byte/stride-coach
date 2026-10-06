"""Hallucination guard: every number in an LLM reply must be traceable to the FACTS we gave it.

Policy (documented limitation): integers 0-10 are exempt - they're usually counts/ordinals
("3 sessions", "Z2") - and numbers the athlete wrote in their own goal are allowed.
Anything else must match a FACTS number within rounding tolerance.
"""
from __future__ import annotations

import re

NUM_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


def _numbers_in_text(s: str) -> list[float]:
    out = []
    for m in NUM_RE.findall(s):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def _flatten(obj, nums: set, strs: set):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        nums.add(float(obj))
    elif isinstance(obj, str):
        strs.add(obj)
        nums.update(_numbers_in_text(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(v, nums, strs)
            nums.update(_numbers_in_text(str(k)))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _flatten(v, nums, strs)


def _close(a: float, b: float) -> bool:
    diff = abs(a - b)
    if diff <= 0.051 or diff <= 0.01 * max(abs(a), abs(b)):
        return True
    return float(a).is_integer() and diff <= 0.5  # LLM rounded 62.3 -> 62


def ungrounded_numbers(text: str, facts: dict, extra_text: str = "") -> list[str]:
    """Returns the numbers in `text` that can't be found in `facts` (empty list = grounded)."""
    nums: set[float] = set()
    strs: set[str] = set()
    _flatten(facts, nums, strs)
    nums.update(_numbers_in_text(extra_text))
    blob = " ".join(strs)

    bad: list[str] = []
    for t in TIME_RE.findall(text):  # paces/durations like 5:12
        if t not in blob and not any(t in s for s in strs):
            bad.append(t)
    stripped = TIME_RE.sub(" ", text)
    for n in _numbers_in_text(stripped):
        if n == int(n) and 0 <= n <= 10:
            continue
        if any(_close(abs(n), x) for x in nums):
            continue
        bad.append(f"{n:g}")
    return sorted(set(bad))
