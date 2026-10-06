import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from app import dashboard, guard
from app.metrics import endurance as endu
from app.metrics import muscles, plan, strength, trends
from tests.helpers import Env


class Guard(unittest.TestCase):
    F = {"distance_km": 10.0, "avg_pace_per_km": "5:00", "zone_pct": {"Z2": 62.3},
         "decoupling_pct": 3.1, "total_volume_kg": 1400.0, "name": "Easy run"}

    def test_grounded_texts_pass(self):
        for t in ["Ran **10 km** at 5:00.", "62% in Z2, decoupling 3.1%.", "Volume was 1,400 kg.",
                  "About 62.3 percent easy.", "You did 3 hard sets."]:
            self.assertEqual(guard.ungrounded_numbers(t, self.F), [], t)

    def test_fabrications_caught(self):
        self.assertIn("12", guard.ungrounded_numbers("You ran 12 km.", self.F))
        self.assertIn("4:45", guard.ungrounded_numbers("Pace 4:45.", self.F))
        self.assertIn("80", guard.ungrounded_numbers("80% in Z2", self.F))
        self.assertIn("155", guard.ungrounded_numbers("avg HR 155", self.F))

    def test_goal_numbers_allowed(self):
        self.assertEqual(guard.ungrounded_numbers("Toward your 42 km goal", self.F, "run 42 km"), [])


class Pure(unittest.TestCase):
    def test_plan_scales_with_load(self):
        hi = plan.weekly_plan(1.8, [30, 30, 30, 30])
        ok = plan.weekly_plan(1.0, [30, 30, 30, 30])
        self.assertLess(hi["target_km"], 30)
        self.assertGreater(ok["target_km"], 30)
        self.assertLessEqual(ok["target_km"], 30 * 1.10)                 # never >10% jump
        self.assertEqual([s["day"] for s in ok["sessions"]][-2], "Sat")
        self.assertIsNone(plan.weekly_plan(1.0, [0, 0, 0, 0]))

    def test_muscles(self):
        m = muscles.muscle_for
        self.assertEqual(m("Leg Press"), "quads")
        self.assertEqual(m("Bench Press (Barbell)"), "chest")
        self.assertEqual(m("Overhead Triceps Extension"), "triceps")
        self.assertEqual(m("Romanian Deadlift"), "hamstrings/glutes")
        self.assertEqual(m("Lat Pulldown"), "back")
        self.assertEqual(m("Basket weaving"), "other")

    def test_trends(self):
        cur = {"distance_km": 10, "avg_speed_ms": 3.4, "avg_hr": 150}
        hist = [{"distance_km": 10, "avg_speed_ms": 3.2, "avg_hr": 150}] * 3 + \
               [{"distance_km": 3, "avg_speed_ms": 9, "avg_hr": 100}]       # dissimilar: ignored
        r = trends.compare_to_recent(cur, hist)
        self.assertEqual(r["compared_runs"], 3)
        self.assertLess(r["pace_vs_median_sec_per_km"], 0)                  # faster
        self.assertGreater(r["efficiency_change_pct"], 0)
        self.assertIsNone(trends.compare_to_recent(cur, hist[:1]))

    def test_plateau_and_effective_hr(self):
        up = [("d1", 100), ("d2", 105), ("d3", 110), ("d4", 112), ("d5", 115)]
        flat = [("d0", 100), ("d1", 120), ("d2", 115), ("d3", 118), ("d4", 119), ("d5", 120)]
        self.assertFalse(strength.lift_plateau(up))
        self.assertTrue(strength.lift_plateau(flat))
        self.assertEqual(endu.effective_max_hr(185, [180, 190]), 185)       # too little data
        self.assertEqual(endu.effective_max_hr(185, [192, 195, 196, 197, 198, 300]), 198)


class Dashboard(unittest.TestCase):
    def test_build_is_json_and_scoped(self):
        e = Env(); e.onboard(); e.onboard(chat_id=43, athlete=888)
        e.svc.ingest_strava(e.strava_ev(1, t=1)); e.svc.ingest_strava(e.strava_ev(2, t=2)); e.drain()
        d = dashboard.build(e.db.for_user(1))
        json.dumps(d)
        self.assertEqual(d["weekly"][-1]["km"], 10.0)
        self.assertEqual(d["weekly"][-1]["volume_kg"], 800.0)
        self.assertEqual(d["prs"][0]["exercise"], "Bench")
        self.assertEqual(len(d["zone_trend"]), 1)
        other = dashboard.build(e.db.for_user(2))
        self.assertEqual(other["prs"], [])
        self.assertEqual(other["recent"], [])

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_dashboard_js_parses_and_avoids_innerhtml(self):
        html = Path("app/static/dashboard.html").read_text()
        js = re.search(r"<script>(.*)</script>", html, re.S).group(1)
        self.assertNotIn("innerHTML", js)                                   # XSS: names come from Strava
        Path("/tmp/_d.js").write_text(js)
        r = subprocess.run(["node", "--check", "/tmp/_d.js"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
