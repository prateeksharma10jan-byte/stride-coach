"""Pure-Python endurance maths. No LLM, no I/O."""
from __future__ import annotations

import math
from datetime import date, timedelta

ZONE_BOUNDS = (0.60, 0.70, 0.80, 0.90)  # fractions of max HR -> Z1..Z5


def zone_index(hr: float, max_hr: float) -> int:
    f = hr / max_hr
    for i, bound in enumerate(ZONE_BOUNDS):
        if f < bound:
            return i
    return 4


def hr_zone_seconds(times, hrs, max_hr, max_gap: float = 30.0) -> list[float]:
    """Time in each zone, weighted by real elapsed seconds (dt), NOT sample count.

    Strava streams are unevenly spaced (smart recording), so counting samples
    would misreport zones. Gaps above `max_gap` (pauses) are capped.
    """
    secs = [0.0] * 5
    n = len(times)
    if n < 2 or n != len(hrs):
        return secs
    for i in range(n):
        dt = times[i + 1] - times[i] if i < n - 1 else times[i] - times[i - 1]
        secs[zone_index(hrs[i], max_hr)] += min(max(dt, 0.0), max_gap)
    return secs


def zone_percentages(secs: list[float]) -> list[float]:
    total = sum(secs)
    return [round(100 * s / total, 1) for s in secs] if total else [0.0] * 5


def decoupling_pct(times, hrs, speeds, min_speed: float = 0.5):
    """Aerobic decoupling (Pa:HR): efficiency = speed/HR, first half vs second half.

    Positive = efficiency dropped (cardiac drift). Under ~5% is 'well coupled'.
    """
    pts = [(t, h, v) for t, h, v in zip(times, hrs, speeds) if v >= min_speed and h > 0]
    if len(pts) < 20:
        return None
    mid = (pts[0][0] + pts[-1][0]) / 2
    a = [p for p in pts if p[0] < mid]
    b = [p for p in pts if p[0] >= mid]
    if not a or not b:
        return None

    def ef(g):
        return (sum(p[2] for p in g) / len(g)) / (sum(p[1] for p in g) / len(g))

    e1, e2 = ef(a), ef(b)
    return round((e1 - e2) / e1 * 100, 1)


def pace_str(speed_ms: float) -> str:
    """m/s -> 'm:ss' per km."""
    if speed_ms <= 0:
        return "-"
    total = round(1000 / speed_ms)
    return f"{total // 60}:{total % 60:02d}"


def trimp(duration_s: float, avg_hr: float, rest_hr: float, max_hr: float) -> float:
    """Banister TRIMP (male coefficients): minutes * HRR * 0.64 * e^(1.92 * HRR)."""
    hrr = (avg_hr - rest_hr) / (max_hr - rest_hr)
    hrr = min(max(hrr, 0.0), 1.0)
    return round(duration_s / 60 * hrr * 0.64 * math.exp(1.92 * hrr), 1)


def acwr(daily_load: dict[date, float], as_of: date):
    """Acute:chronic workload ratio = 7-day load / (28-day load / 4)."""
    acute = sum(daily_load.get(as_of - timedelta(days=i), 0.0) for i in range(7))
    chronic = sum(daily_load.get(as_of - timedelta(days=i), 0.0) for i in range(28)) / 4
    if chronic <= 0:
        return None
    return round(acute / chronic, 2)


def acwr_label(value) -> str:
    if value is None:
        return "not enough history"
    if value < 0.8:
        return "under-loaded"
    if value <= 1.3:
        return "sweet spot"
    if value <= 1.5:
        return "elevated"
    return "high injury-risk zone"


def downsample(seq, n: int = 200):
    if len(seq) <= n:
        return list(seq)
    step = len(seq) / n
    return [seq[int(i * step)] for i in range(n)]


def effective_max_hr(configured: int, observed_maxes: list[int]) -> int:
    """Personalised max HR: if enough runs show peaks above the configured (often formula-based)
    value, trust the data. Uses the 95th percentile of per-run peaks to ignore sensor spikes."""
    clean = sorted(h for h in observed_maxes if 120 <= h <= 230)
    if len(clean) < 5:
        return configured
    p95 = clean[min(len(clean) - 1, round(0.95 * (len(clean) - 1)))]
    return max(configured, p95)
