import sqlite3
import unittest

from app import auth
from app.crypto import TokenCipher
from app.jobs import JobQueue, Worker
from app.observability import metrics_text
from app.storage import Database
from tests.helpers import SECRET_TOKEN, Env, run_act


class Storage(unittest.TestCase):
    def test_migrations_idempotent(self):
        e = Env()
        self.assertEqual(e.db.migrate(), 2)
        self.assertEqual(e.db.migrate(), 2)
        with sqlite3.connect(e.path) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 2)

    def test_tokens_encrypted_at_rest(self):
        e = Env(); e.onboard()
        with sqlite3.connect(e.path) as c:
            raw = c.execute("SELECT tokens_enc FROM users").fetchone()[0]
        self.assertNotIn(SECRET_TOKEN, raw)
        self.assertEqual(e.db.get_tokens(1)["access_token"], SECRET_TOKEN)

    def test_wrong_key_fails_loudly(self):
        e = Env(); e.onboard()
        other = Database(e.path, TokenCipher(TokenCipher.generate_key()))
        with self.assertRaises(ValueError):
            other.get_tokens(1)


class Auth(unittest.TestCase):
    def test_roundtrip_tamper_expiry(self):
        t = auth.sign({"uid": 1}, "k", 60, now=1000)
        self.assertEqual(auth.verify(t, "k", now=1010)["uid"], 1)
        self.assertIsNone(auth.verify(t, "other-key", now=1010))
        self.assertIsNone(auth.verify(t, "k", now=2000))                  # expired
        raw, sig = t.split(".")
        self.assertIsNone(auth.verify(raw[:-2] + "xx." + sig, "k", now=1010))
        self.assertIsNone(auth.verify("nonsense", "k"))

    def test_dashboard_token_only_for_dash_purpose(self):
        e = Env(); u = e.onboard()
        good = e.svc.dashboard_url(u["id"]).split("t=")[1]
        self.assertEqual(e.svc.user_for_dashboard(good)["id"], u["id"])
        oauth_state = auth.sign({"p": "oauth", "chat": 42}, "s3cret", 60)
        self.assertIsNone(e.svc.user_for_dashboard(oauth_state))        # can't reuse other tokens


class Jobs(unittest.TestCase):
    def setUp(self):
        self.t = [1000.0]
        self.e = Env(clock=lambda: self.t[0])
        self.q = JobQueue(self.e.db, max_attempts=3, visibility_timeout=100, clock=lambda: self.t[0])

    def test_success(self):
        seen = []
        self.q.enqueue("k", {"a": 1})
        self.assertTrue(Worker(self.q, {"k": seen.append}).run_once())
        self.assertEqual(seen, [{"a": 1}])
        self.assertEqual(self.q.counts()["done"], 1)

    def test_retry_with_backoff_then_dead_letter_then_requeue(self):
        def boom(_): raise RuntimeError("x")
        w = Worker(self.q, {"k": boom})
        self.q.enqueue("k", {})
        self.assertTrue(w.run_once())                      # attempt 1 -> pending, backoff
        self.assertFalse(w.run_once())                     # not due yet
        self.t[0] += 11; self.assertTrue(w.run_once())     # attempt 2
        self.t[0] += 25; self.assertTrue(w.run_once())     # attempt 3 -> dead
        self.assertEqual(self.q.counts()["dead"], 1)
        self.t[0] += 10_000
        self.assertFalse(w.run_once())
        self.assertEqual(self.q.requeue_dead(), 1)
        self.assertTrue(w.run_once())

    def test_no_double_claim_and_stale_recovery(self):
        self.q.enqueue("k", {})
        first = self.q.claim()
        self.assertIsNotNone(first)
        self.assertIsNone(self.q.claim())                  # already running
        self.t[0] += 101                                   # worker "crashed"
        again = self.q.claim()
        self.assertEqual(again["id"], first["id"])

    def test_handler_failure_in_real_flow_retries(self):
        e = Env(clock=lambda: self.t[0]); e.onboard()
        e.acts[1] = run_act(1)
        calls = {"n": 0}
        orig = e.svc.handle_strava_event
        def flaky(p):
            calls["n"] += 1
            if calls["n"] == 1: raise RuntimeError("strava 500")
            orig(p)
        e.worker = Worker(e.queue, {"strava_event": flaky, "telegram_update": e.svc.handle_telegram_update})
        e.svc.ingest_strava(e.strava_ev(1)); e.worker.run_once()
        self.assertEqual(len(e.tg.photos), 0)
        self.t[0] += 11; e.worker.run_once()
        self.assertEqual(len(e.tg.photos), 2)


class Observability(unittest.TestCase):
    def test_metrics_text(self):
        e = Env(); e.onboard()
        out = metrics_text(e.db, e.queue)
        self.assertIn("stride_users 1", out)
        self.assertIn('stride_jobs{status="dead"} 0', out)


if __name__ == "__main__":
    unittest.main()
