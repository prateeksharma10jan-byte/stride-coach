"""Dashboard data (pure function over UserDB -> JSON-able dict)."""
from __future__ import annotations

from datetime import date

from app.metrics import endurance as endu
from app.metrics import muscles


def build(udb, today: date | None = None) -> dict:
    today = today or date.today()
    acts = [a for a in udb.recent_activities(56) if a["kind"] in ("run", "strength")]
    weeks = [{"label": f"-{i}w" if i else "this wk", "trimp": 0.0, "km": 0.0, "volume_kg": 0.0}
             for i in range(7, -1, -1)]
    for a in acts:
        i = (today - date.fromisoformat(a["start_date"][:10])).days // 7
        if 0 <= i <= 7:
            w = weeks[7 - i]
            w["trimp"] += a["load"] or 0
            w["km"] += a["facts"].get("distance_km", 0)
            w["volume_kg"] += a["facts"].get("total_volume_kg", 0)
    for w in weeks:
        for k in ("trimp", "km", "volume_kg"):
            w[k] = round(w[k], 1)
    runs = [a for a in acts if a["kind"] == "run"][-10:]
    best = udb.best_e1rms()
    top = sorted(best.items(), key=lambda kv: -kv[1])
    val = endu.acwr(udb.daily_loads(60), today)
    return {
        "weekly": weeks,
        "recent": [{"date": a["start_date"][:10], "kind": a["kind"], "name": a["name"]}
                   for a in reversed(acts[-10:])],
        "prs": [{"exercise": k, "e1rm_kg": v} for k, v in top[:8]],
        "e1rm_series": {k: [{"day": d, "e1rm": m} for d, m in udb.e1rm_history(k)]
                        for k, _ in top[:3]},
        "zone_trend": [{"date": a["start_date"][:10], **a["facts"]["zone_pct"]} for a in runs],
        "muscle_sets": muscles.weekly_sets(udb.recent_sets(7)),
        "acwr": val, "acwr_label": endu.acwr_label(val),
    }
