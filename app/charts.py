"""Chart presets (matplotlib, Agg backend, in-memory PNG). The 'chart agent' is rule-based."""
from __future__ import annotations

import io
from collections import defaultdict
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BG, FG, ACCENT, ACCENT2 = "#14171c", "#e8eaed", "#fc4c02", "#4dabf7"
ZONE_COLORS = ["#6c8ebf", "#4dabf7", "#51cf66", "#fcc419", "#ff6b6b"]


def _fig(w=7, h=3.6):
    fig, ax = plt.subplots(figsize=(w, h), dpi=130)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#555b66")
    ax.tick_params(colors=FG, labelsize=8)
    ax.title.set_color(FG)
    ax.xaxis.label.set_color(FG)
    ax.yaxis.label.set_color(FG)
    return fig, ax


def _png(fig) -> bytes:
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def zone_distribution(facts, db):
    fig, ax = _fig(6, 3.2)
    zp = facts["zone_pct"]
    bars = ax.barh(list(zp.keys()), list(zp.values()), color=ZONE_COLORS)
    ax.invert_yaxis()
    ax.set_xlabel("% of time")
    ax.set_title("Time in heart-rate zones")
    for b, v in zip(bars, zp.values()):
        ax.text(b.get_width() + 0.8, b.get_y() + b.get_height() / 2, f"{v:.0f}%",
                va="center", color=FG, fontsize=8)
    return _png(fig)


def pace_hr(facts, db):
    s = facts["series"]
    fig, ax = _fig()
    ax.plot(s["t"], s["pace"], color=ACCENT, lw=1.4)
    ax.invert_yaxis()
    ax.set_xlabel("minutes")
    ax.set_ylabel("pace (sec/km)", color=ACCENT)
    ax2 = ax.twinx()
    ax2.plot(s["t"], s["hr"], color=ACCENT2, lw=1.2, alpha=0.9)
    ax2.set_ylabel("heart rate (bpm)", color=ACCENT2)
    ax2.tick_params(colors=FG, labelsize=8)
    ax2.spines["top"].set_visible(False)
    ax.set_title("Pace vs heart rate")
    return _png(fig)


def strength_volume(facts, db):
    ex = facts["exercises"][:8]
    fig, ax = _fig(7, 3.6)
    ax.barh([e["name"][:26] for e in ex], [e["volume_kg"] for e in ex], color=ACCENT)
    ax.invert_yaxis()
    ax.set_xlabel("volume (kg)")
    ax.set_title(f"Volume by exercise - total {facts['total_volume_kg']:g} kg")
    return _png(fig)


def e1rm_trend(facts, db):
    name = (facts.get("prs") or [{}])[0].get("exercise") or facts["exercises"][0]["name"]
    hist = db.e1rm_history(name)
    fig, ax = _fig()
    ax.plot([d[5:] for d, _ in hist], [m for _, m in hist], marker="o", color=ACCENT)
    ax.set_ylabel("estimated 1RM (kg)")
    ax.set_title(f"{name} - e1RM trend")
    return _png(fig)


def weekly_load(facts, db):
    daily = db.daily_loads(56)
    weeks: dict[int, float] = defaultdict(float)
    today = date.today()
    for d, v in daily.items():
        weeks[(today - d).days // 7] += v
    labels = [f"-{i}w" if i else "this wk" for i in range(7, -1, -1)]
    fig, ax = _fig()
    ax.bar(labels, [weeks.get(i, 0) for i in range(7, -1, -1)], color=ACCENT)
    ax.set_ylabel("TRIMP (endurance load)")
    ax.set_title("Weekly training load")
    return _png(fig)


REGISTRY = {
    "zones": (zone_distribution, "Heart-rate zone distribution"),
    "pace": (pace_hr, "Pace and heart rate"),
    "volume": (strength_volume, "Volume by exercise"),
    "e1rm": (e1rm_trend, "Estimated 1RM trend"),
    "weekly": (weekly_load, "Weekly training load"),
}


def choose_charts(facts: dict) -> list[str]:
    """Deterministic chart selection: show what's most informative for this session type."""
    if facts["kind"] == "run":
        return ["pace", "zones"]
    if facts["kind"] == "strength":
        return ["volume", "e1rm"] if facts.get("prs") else ["volume"]
    return []


def render(name: str, facts: dict, db) -> tuple[bytes, str]:
    fn, caption = REGISTRY[name]
    return fn(facts, db), caption
