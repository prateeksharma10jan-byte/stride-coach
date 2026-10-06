import unittest
from datetime import date, timedelta

from app.metrics import endurance as e
from app.metrics import strength as s


class Endurance(unittest.TestCase):
    def test_zones_weighted_by_seconds_not_samples(self):
        # 1 sample in Z1 lasting 90s (capped to 30), 3 dense samples in Z5 (1s each)
        times = [0, 90, 91, 92, 93]
        hrs = [100, 185, 185, 185, 185]
        secs = e.hr_zone_seconds(times, hrs, 190, max_gap=30)
        self.assertEqual(secs[0], 30)           # gap capped
        self.assertEqual(secs[4], 4)            # 1+1+1 + last sample reuses prev dt (1)
        # sample-counting would have said 80% Z5; time-weighting says ~12%
        self.assertLess(e.zone_percentages(secs)[4], 15)

    def test_zone_boundaries(self):
        self.assertEqual(e.zone_index(100, 190), 0)
        self.assertEqual(e.zone_index(125, 190), 1)
        self.assertEqual(e.zone_index(180, 190), 4)

    def test_decoupling_detects_drift(self):
        t = list(range(0, 2400, 10))
        v = [3.0] * len(t)
        hr = [140 + (i * 20 / len(t)) for i in range(len(t))]  # HR drifts up at same speed
        d = e.decoupling_pct(t, hr, v)
        self.assertGreater(d, 5)

    def test_decoupling_flat_is_near_zero(self):
        t = list(range(0, 2400, 10))
        self.assertAlmostEqual(e.decoupling_pct(t, [150] * len(t), [3.0] * len(t)), 0, places=1)

    def test_decoupling_too_short(self):
        self.assertIsNone(e.decoupling_pct([0, 1], [140, 140], [3, 3]))

    def test_pace(self):
        self.assertEqual(e.pace_str(3.333), "5:00")
        self.assertEqual(e.pace_str(0), "-")

    def test_trimp_increases_with_intensity(self):
        self.assertGreater(e.trimp(3600, 170, 55, 190), e.trimp(3600, 130, 55, 190))

    def test_acwr(self):
        today = date(2026, 1, 28)
        daily = {today - timedelta(days=i): 100.0 for i in range(28)}
        self.assertEqual(e.acwr(daily, today), 1.0)
        self.assertEqual(e.acwr_label(1.0), "sweet spot")
        self.assertIsNone(e.acwr({}, today))
        self.assertEqual(e.acwr_label(1.8), "high injury-risk zone")


class Strength(unittest.TestCase):
    def test_e1rm(self):
        self.assertEqual(s.e1rm(100, 1), 100)
        self.assertEqual(s.e1rm(100, 5), 116.7)
        self.assertEqual(s.e1rm(0, 5), 0)

    def test_summary_and_volume(self):
        sets = [s.SetEntry("Bench", 80, 5), s.SetEntry("Bench", 80, 5), s.SetEntry("Row", 60, 10)]
        out = s.summarize(sets)
        self.assertEqual(out["total_volume_kg"], 1400)
        self.assertEqual(out["exercises"][0]["name"], "Bench")

    def test_pr_needs_history(self):
        ex = s.summarize([s.SetEntry("Bench", 100, 5)])["exercises"]
        self.assertEqual(s.detect_prs(ex, {}), [])            # first time != PR
        self.assertEqual(s.detect_prs(ex, {"Bench": 120}), [])
        prs = s.detect_prs(ex, {"Bench": 100})
        self.assertEqual(prs[0]["improvement_kg"], 16.7)


if __name__ == "__main__":
    unittest.main()
