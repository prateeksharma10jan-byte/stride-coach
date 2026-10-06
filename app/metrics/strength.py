"""Pure-Python strength maths."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SetEntry:
    exercise: str
    weight_kg: float
    reps: int


def e1rm(weight: float, reps: int) -> float:
    """Epley estimated 1RM. Unreliable above ~12 reps (documented, not hidden)."""
    if weight <= 0 or reps <= 0:
        return 0.0
    if reps == 1:
        return round(weight, 1)
    return round(weight * (1 + reps / 30), 1)


def summarize(sets: list[SetEntry]) -> dict:
    by_ex: dict[str, list[SetEntry]] = {}
    for s in sets:
        by_ex.setdefault(s.exercise, []).append(s)
    exercises = []
    for name, ss in by_ex.items():
        best = max(ss, key=lambda s: e1rm(s.weight_kg, s.reps))
        exercises.append({
            "name": name,
            "sets": len(ss),
            "reps": sum(s.reps for s in ss),
            "volume_kg": round(sum(s.weight_kg * s.reps for s in ss), 1),
            "top_e1rm_kg": e1rm(best.weight_kg, best.reps),
            "best_set": f"{best.weight_kg:g}kg x {best.reps}",
        })
    exercises.sort(key=lambda e: e["volume_kg"], reverse=True)
    return {
        "total_volume_kg": round(sum(e["volume_kg"] for e in exercises), 1),
        "total_sets": sum(e["sets"] for e in exercises),
        "exercises": exercises,
    }


def detect_prs(exercises: list[dict], history_best: dict[str, float]) -> list[dict]:
    """A PR = beating the best prior e1RM. The first time a lift appears is NOT a PR."""
    prs = []
    for ex in exercises:
        prev = history_best.get(ex["name"])
        if prev is not None and ex["top_e1rm_kg"] > prev:
            prs.append({
                "exercise": ex["name"],
                "new_e1rm_kg": ex["top_e1rm_kg"],
                "previous_e1rm_kg": prev,
                "improvement_kg": round(ex["top_e1rm_kg"] - prev, 1),
                "set": ex["best_set"],
            })
    return prs


def lift_plateau(history: list[tuple[str, float]], window: int = 4) -> bool:
    """Plateau = none of the last `window` sessions beat the best of everything before them."""
    if len(history) < window + 1:
        return False
    recent = [m for _, m in history[-window:]]
    earlier = [m for _, m in history[:-window]]
    return max(recent) <= max(earlier)
