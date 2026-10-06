import unittest

from app.bot import fallback_summary
from tests.helpers import Env, FakeLLM, lift_act, run_act


class RunAndLift(unittest.TestCase):
    def test_run_flow(self):
        e = Env(); e.onboard()
        self.assertEqual(e.svc.ingest_strava(e.strava_ev(1)), "queued")
        e.drain()
        self.assertEqual(len(e.tg.photos), 2)
        self.assertEqual(e.tg.photos[0][1], b"\x89PNG")
        f = e.db.for_user(1).get_activity(1)["facts"]
        self.assertEqual(f["distance_km"], 10.0)
        self.assertIn("max_hr_used_for_zones", f)
        self.assertNotIn("series", e.llm.calls[0][1][0]["content"])

    def test_duplicate_unknown_and_rejected(self):
        e = Env(sub_id=5); e.onboard()
        self.assertEqual(e.svc.ingest_strava(e.strava_ev(1)), "rejected")        # wrong subscription
        self.assertEqual(e.svc.ingest_strava(e.strava_ev(1, subscription_id=5)), "queued")
        self.assertEqual(e.svc.ingest_strava(e.strava_ev(1, subscription_id=5)), "duplicate")
        self.assertEqual(e.svc.ingest_strava(e.strava_ev(1, athlete=999, subscription_id=5)),
                         "unknown_user")

    def test_strength_pr_and_late_hevy_sync(self):
        e = Env(acts={2: lift_act(desc="")}); u = e.onboard()
        udb = e.db.for_user(u["id"])
        udb.replace_sets(99, "2026-09-01", [("Bench", 70, 5, 81.7)])        # prior best
        e.svc.ingest_strava(e.strava_ev(2)); e.drain()
        self.assertIn("couldn't find sets", e.tg.to(42)[-1])
        n = len(e.tg.to(42))
        e.acts[2]["description"] = "Push\n\n1. Bench\nSet 1: 80 kg x 5\nSet 2: 80 kg x 5\n"
        e.svc.ingest_strava(e.strava_ev(2, aspect="update", t=2)); e.drain()   # Hevy synced late
        f = udb.get_activity(2)["facts"]
        self.assertEqual(f["total_volume_kg"], 800)
        self.assertEqual(f["prs"][0]["exercise"], "Bench")
        self.assertGreater(len(e.tg.to(42)), n)
        before = len(e.llm.calls)
        e.svc.ingest_strava(e.strava_ev(2, aspect="update", t=3)); e.drain()   # later edits ignored
        self.assertEqual(len(e.llm.calls), before)

    def test_llm_cap_fallback(self):
        e = Env(cap=0); e.onboard()
        e.svc.ingest_strava(e.strava_ev(1)); e.drain()
        self.assertEqual(e.llm.calls, [])
        self.assertIn("10.0 km", e.tg.to(42)[-1])


class GuardIntegration(unittest.TestCase):
    def test_hallucination_triggers_retry(self):
        llm = FakeLLM(["You ran 42 km at 3:33 pace.", "You ran **10 km**. Nice."])
        e = Env(llm=llm); e.onboard()
        e.svc.ingest_strava(e.strava_ev(1)); e.drain()
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("not in FACTS", llm.calls[1][1][-1]["content"])
        self.assertNotIn("42", e.tg.to(42)[-1])

    def test_persistent_hallucination_falls_back(self):
        llm = FakeLLM(["You ran 42 km.", "You ran 41 km."])
        e = Env(llm=llm); e.onboard()
        e.svc.ingest_strava(e.strava_ev(1)); e.drain()
        self.assertEqual(e.tg.to(42)[-1], fallback_summary(
            e.db.for_user(1).get_activity(1)["facts"]))


class Chat(unittest.TestCase):
    def test_window_and_expiry(self):
        t = [1_000_000.0]
        e = Env(clock=lambda: t[0]); e.onboard()
        e.svc.ingest_strava(e.strava_ev(1)); e.drain()
        n = len(e.llm.calls)
        e.say("was it too fast?")
        self.assertEqual(len(e.llm.calls), n + 1)
        t[0] += 31 * 60
        e.say("hello?")
        self.assertEqual(len(e.llm.calls), n + 1)
        self.assertIn("No active chat", e.tg.to(42)[-1])


class Commands(unittest.TestCase):
    def test_commands(self):
        e = Env(); e.onboard()
        e.svc.ingest_strava(e.strava_ev(1, t=1)); e.svc.ingest_strava(e.strava_ev(2, t=2)); e.drain()
        for c in ("/pr", "/week", "/plan 3", "/goal sub-4 marathon", "/hr 195 50",
                  "/chart volume", "/chart", "/dashboard", "/export"):
            e.say(c)
        out = "\n".join(e.tg.to(42))
        self.assertIn("Bench", out)
        self.assertIn("chest: 2", out)                       # muscle sets in /week
        self.assertIn("Next week", out)
        self.assertIn("max HR 195", out)
        self.assertIn("https://app.test/dashboard?t=", out)
        self.assertEqual(e.db.for_user(1).get_kv("goal"), "sub-4 marathon")
        self.assertEqual(e.tg.docs[0][1], "stride-export.json")
        self.assertEqual(e.db.get_user(1)["max_hr"], 195)

    def test_deleteaccount_requires_confirm(self):
        e = Env(); e.onboard()
        e.say("/deleteaccount")
        self.assertIsNotNone(e.db.user_by_chat(42))
        e.say("/deleteaccount confirm")
        self.assertIsNone(e.db.user_by_chat(42))


class Onboarding(unittest.TestCase):
    def test_start_gives_link_then_strangers_get_hint(self):
        e = Env()
        e.say("/start", chat_id=50)
        self.assertIn("/oauth/strava/start?state=", e.tg.to(50)[-1])
        e.say("/last", chat_id=51)
        self.assertIn("Send /start", e.tg.to(51)[-1])

    def test_bad_state_rejected(self):
        e = Env()
        with self.assertRaises(PermissionError):
            e.svc.complete_oauth("garbage.token", "1")

    def test_user_cap(self):
        from app.service import SignupClosed
        e = Env(max_users=1); e.onboard(chat_id=1, athlete=1)
        with self.assertRaises(SignupClosed):
            e.onboard(chat_id=2, athlete=2)

    def test_rate_limit(self):
        e = Env(); e.onboard()
        res = [e.svc.ingest_telegram({"update_id": i, "message": {"chat": {"id": 42}, "text": "hi"}})
               for i in range(25)]
        self.assertEqual(res.count("queued"), 20)
        self.assertEqual(res.count("rate_limited"), 5)


class Isolation(unittest.TestCase):
    def test_users_cannot_see_each_other(self):
        e = Env(acts={1: run_act(1), 2: lift_act(2)})
        a = e.onboard(chat_id=42, athlete=777)
        b = e.onboard(chat_id=43, athlete=888)
        e.svc.ingest_strava(e.strava_ev(2, athlete=777)); e.drain()
        ua, ub = e.db.for_user(a["id"]), e.db.for_user(b["id"])
        self.assertIsNotNone(ua.get_activity(2))
        self.assertIsNone(ub.get_activity(2))
        self.assertEqual(ub.best_e1rms(), {})
        self.assertEqual(ub.recent_activities(30), [])
        e.say("/pr", chat_id=43)
        self.assertIn("No lifting data", e.tg.to(43)[-1])
        e.say("/forget", chat_id=43)                                  # B wipes...
        self.assertIsNotNone(ua.get_activity(2))                      # ...A is untouched


if __name__ == "__main__":
    unittest.main()
