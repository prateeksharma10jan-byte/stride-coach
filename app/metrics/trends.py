"""Compare today's run with similar recent runs (pure Python)."""
from __future__ import annotations

from statistics import median


def compare_to_recent(current: dict, history: list[dict], n: int = 5, tol: float = 0.25):
    """history: prior run facts, newest first. 'Similar' = distance within +/-25%."""
    d = current.get("distance_km") or 0
    cur_speed, cur_hr = current.get("avg_speed_ms") or 0, current.get("avg_hr") or 0
    if not (d and cur_speed and cur_hr):
        return None
    sim = [h for h in history
           if h.get("avg_speed_ms") and h.get("avg_hr")
           and abs(h["distance_km"] - d) <= tol * d][:n]
    if len(sim) < 2:
        return None
    med_speed = median(h["avg_speed_ms"] for h in sim)
    med_hr = median(h["avg_hr"] for h in sim)
    eff_now, eff_med = cur_speed / cur_hr, med_speed / med_hr
    return {
        "compared_runs": len(sim),
        "pace_vs_median_sec_per_km": round(1000 / cur_speed - 1000 / med_speed),  # negative = faster
        "avg_hr_vs_median_bpm": round(cur_hr - med_hr),
        "efficiency_change_pct": round((eff_now - eff_med) / eff_med * 100, 1),
    }
