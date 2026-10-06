"""Deterministic next-week running plan. Rules, not LLM: safe, explainable, testable."""
from __future__ import annotations

TEMPLATES = {
    2: ["Tue", "Sat"],
    3: ["Tue", "Thu", "Sat"],
    4: ["Tue", "Thu", "Sat", "Sun"],
    5: ["Mon", "Tue", "Thu", "Sat", "Sun"],
}


def load_factor(acwr) -> tuple[float, str]:
    if acwr is None:
        return 1.0, "not enough history yet - hold volume steady"
    if acwr > 1.5:
        return 0.7, "load ratio is in the high-risk zone - recovery week"
    if acwr > 1.3:
        return 0.9, "load ratio is elevated - trim volume slightly"
    if acwr >= 0.8:
        return 1.05, "load ratio is in the sweet spot - small progression"
    return 1.1, "you're under-loaded - rebuild gradually (10% cap)"


def _half(x: float) -> float:
    return round(x * 2) / 2


def weekly_plan(acwr, weekly_km: list[float], runs_per_week: int = 4) -> dict | None:
    """weekly_km: last few weeks of running km, most recent first (zeros allowed)."""
    base = [k for k in weekly_km[:4] if k > 0]
    if not base or runs_per_week not in TEMPLATES:
        return None
    factor, reason = load_factor(acwr)
    target = sum(base) / len(base) * factor
    days = TEMPLATES[runs_per_week]
    long_km = target * 0.35
    easy_km = (target - long_km) / (runs_per_week - 1)
    sessions = []
    long_day = "Sat" if "Sat" in days else days[-1]
    strides_done = False
    for day in days:
        if day == long_day:
            sessions.append({"day": day, "type": "long run (easy pace)", "km": _half(long_km)})
        elif factor >= 1.0 and not strides_done and day == days[1]:
            sessions.append({"day": day, "type": "easy + 6x20s strides", "km": _half(easy_km)})
            strides_done = True
        else:
            sessions.append({"day": day, "type": "easy run", "km": _half(easy_km)})
    return {"target_km": round(sum(s["km"] for s in sessions), 1), "baseline_km": round(
        sum(base) / len(base), 1), "reason": reason, "sessions": sessions}
