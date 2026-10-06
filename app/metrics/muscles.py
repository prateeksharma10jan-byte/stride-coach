"""Exercise -> primary muscle group (first matching rule wins; order matters)."""
from __future__ import annotations

RULES = [
    ("quads", ["squat", "leg press", "leg extension", "lunge", "hack "]),
    ("hamstrings/glutes", ["romanian", "rdl", "deadlift", "hamstring", "leg curl",
                           "hip thrust", "glute"]),
    ("calves", ["calf"]),
    ("back", [" row", "pull up", "pull-up", "pullup", "chin up", "chin-up", " lat ",
              "pulldown", "pull down"]),
    ("chest", ["bench", "incline", "decline", "chest", " fly", "push up", "push-up", " pec ",
               "dip"]),
    ("triceps", ["tricep", "pushdown", "skull"]),
    ("shoulders", ["overhead", "shoulder", "lateral raise", "military", "press"]),
    ("biceps", ["curl"]),
    ("core", ["crunch", "plank", "sit up", "sit-up", " ab "]),
]


def muscle_for(exercise: str) -> str:
    name = f" {exercise.lower()} "
    for muscle, keys in RULES:
        if any(k in name for k in keys):
            return muscle
    return "other"


def weekly_sets(rows: list[tuple[str, int]]) -> dict[str, int]:
    """rows: (exercise, reps) per set -> sets per muscle group (primary mover only)."""
    out: dict[str, int] = {}
    for ex, _ in rows:
        m = muscle_for(ex)
        out[m] = out.get(m, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
