"""SQLite storage with versioned migrations and strict per-user scoping.

Every query that touches workout data goes through `UserDB`, which is bound to one user_id,
so cross-user leaks are structurally hard (and covered by tests).
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from app.crypto import TokenCipher

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      telegram_chat_id INTEGER UNIQUE NOT NULL,
      strava_athlete_id INTEGER UNIQUE,
      tokens_enc TEXT,
      max_hr INTEGER NOT NULL DEFAULT 190,
      rest_hr INTEGER NOT NULL DEFAULT 55,
      created_at REAL NOT NULL);
    CREATE TABLE events(key TEXT PRIMARY KEY, ts REAL);
    CREATE TABLE user_kv(user_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(user_id, key));
    CREATE TABLE activities(
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, start_date TEXT, kind TEXT, name TEXT,
      load REAL DEFAULT 0, facts TEXT, analysis TEXT);
    CREATE INDEX idx_act_user ON activities(user_id, start_date);
    CREATE TABLE sets(
      user_id INTEGER NOT NULL, activity_id INTEGER, day TEXT, exercise TEXT,
      weight_kg REAL, reps INTEGER, e1rm REAL);
    CREATE INDEX idx_sets_user_ex ON sets(user_id, exercise, day);
    CREATE TABLE sessions(
      user_id INTEGER PRIMARY KEY, activity_id INTEGER, last_ts REAL, history TEXT);
    """),
    (2, """
    CREATE TABLE jobs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0, run_after REAL NOT NULL,
      claimed_at REAL, last_error TEXT, created_at REAL NOT NULL);
    CREATE INDEX idx_jobs_poll ON jobs(status, run_after);
    CREATE TABLE usage(user_id INTEGER, day TEXT, llm_calls INTEGER DEFAULT 0,
      PRIMARY KEY(user_id, day));
    """),
]


class Database:
    def __init__(self, path: str, cipher: TokenCipher):
        self.path, self.cipher = path, cipher
        self.migrate()

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def migrate(self) -> int:
        """Apply pending migrations in order. Safe to run on every boot."""
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY)")
            done = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
            for version, sql in MIGRATIONS:
                if version not in done:
                    c.executescript(sql)
                    c.execute("INSERT INTO schema_migrations VALUES(?)", (version,))
            return max(done | {v for v, _ in MIGRATIONS})

    # ---------------- users ----------------
    @staticmethod
    def _user(r):
        return dict(r) if r else None

    def user_count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def get_user(self, user_id: int):
        with self._conn() as c:
            return self._user(c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def user_by_chat(self, chat_id: int):
        with self._conn() as c:
            return self._user(c.execute("SELECT * FROM users WHERE telegram_chat_id=?",
                                        (chat_id,)).fetchone())

    def user_by_athlete(self, athlete_id: int):
        with self._conn() as c:
            return self._user(c.execute("SELECT * FROM users WHERE strava_athlete_id=?",
                                        (athlete_id,)).fetchone())

    def upsert_user(self, chat_id: int, athlete_id: int, tokens: dict,
                    max_hr: int = 190, rest_hr: int = 55) -> dict:
        enc = self.cipher.encrypt(tokens)
        with self._conn() as c:
            row = c.execute("SELECT id FROM users WHERE telegram_chat_id=?", (chat_id,)).fetchone()
            if row:
                c.execute("UPDATE users SET strava_athlete_id=?, tokens_enc=? WHERE id=?",
                          (athlete_id, enc, row["id"]))
            else:
                c.execute("INSERT INTO users(telegram_chat_id, strava_athlete_id, tokens_enc,"
                          " max_hr, rest_hr, created_at) VALUES(?,?,?,?,?,?)",
                          (chat_id, athlete_id, enc, max_hr, rest_hr, time.time()))
        return self.user_by_chat(chat_id)

    def get_tokens(self, user_id: int):
        with self._conn() as c:
            r = c.execute("SELECT tokens_enc FROM users WHERE id=?", (user_id,)).fetchone()
        return self.cipher.decrypt(r["tokens_enc"]) if r and r["tokens_enc"] else None

    def set_tokens(self, user_id: int, tokens: dict) -> None:
        with self._conn() as c:
            c.execute("UPDATE users SET tokens_enc=? WHERE id=?",
                      (self.cipher.encrypt(tokens), user_id))

    def set_hr(self, user_id: int, max_hr: int, rest_hr: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE users SET max_hr=?, rest_hr=? WHERE id=?", (max_hr, rest_hr, user_id))

    # ---------------- shared ----------------
    def mark_event(self, key: str) -> bool:
        """True the first time a webhook event is seen. Strava retries; we must be idempotent."""
        with self._conn() as c:
            return c.execute("INSERT OR IGNORE INTO events VALUES(?,?)",
                             (key, time.time())).rowcount == 1

    def total_llm_calls(self, day: str) -> int:
        with self._conn() as c:
            return c.execute("SELECT COALESCE(SUM(llm_calls),0) FROM usage WHERE day=?",
                             (day,)).fetchone()[0]

    def for_user(self, user_id: int) -> "UserDB":
        return UserDB(self, user_id)


class UserDB:
    """All workout data access, bound to exactly one user."""

    def __init__(self, db: Database, user_id: int):
        self.db, self.uid = db, user_id

    def _conn(self):
        return self.db._conn()

    # ---- per-user key/value ----
    def get_kv(self, key, default=None):
        with self._conn() as c:
            r = c.execute("SELECT value FROM user_kv WHERE user_id=? AND key=?",
                          (self.uid, key)).fetchone()
        return json.loads(r["value"]) if r else default

    def set_kv(self, key, value):
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO user_kv VALUES(?,?,?)",
                      (self.uid, key, json.dumps(value)))

    # ---- LLM usage / cost control ----
    def incr_llm_calls(self, day: str) -> int:
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO usage(user_id, day, llm_calls) VALUES(?,?,0)",
                      (self.uid, day))
            c.execute("UPDATE usage SET llm_calls=llm_calls+1 WHERE user_id=? AND day=?",
                      (self.uid, day))
            return c.execute("SELECT llm_calls FROM usage WHERE user_id=? AND day=?",
                             (self.uid, day)).fetchone()[0]

    # ---- activities ----
    def save_activity(self, id_, start_date, kind, name, load, facts, analysis=""):
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO activities VALUES(?,?,?,?,?,?,?,?)",
                      (id_, self.uid, start_date, kind, name, load, json.dumps(facts), analysis))

    @staticmethod
    def _act(r):
        if not r:
            return None
        d = dict(r)
        d["facts"] = json.loads(d["facts"])
        return d

    def get_activity(self, id_):
        with self._conn() as c:
            return self._act(c.execute("SELECT * FROM activities WHERE id=? AND user_id=?",
                                       (id_, self.uid)).fetchone())

    def last_activity(self):
        with self._conn() as c:
            return self._act(c.execute(
                "SELECT * FROM activities WHERE user_id=? ORDER BY start_date DESC LIMIT 1",
                (self.uid,)).fetchone())

    def recent_activities(self, days: int):
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._conn() as c:
            rows = c.execute("SELECT * FROM activities WHERE user_id=? AND start_date>=?"
                             " ORDER BY start_date", (self.uid, since)).fetchall()
        return [self._act(r) for r in rows]

    def run_history(self, exclude_id=None, limit: int = 40) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM activities WHERE user_id=? AND kind='run'"
                             " AND id IS NOT ? ORDER BY start_date DESC LIMIT ?",
                             (self.uid, exclude_id, limit)).fetchall()
        return [self._act(r)["facts"] for r in rows]

    def daily_loads(self, days: int = 56) -> dict[date, float]:
        since = (date.today() - timedelta(days=days)).isoformat()
        out: dict[date, float] = {}
        with self._conn() as c:
            for r in c.execute("SELECT start_date, load FROM activities"
                               " WHERE user_id=? AND start_date>=?", (self.uid, since)):
                d = date.fromisoformat(r["start_date"][:10])
                out[d] = out.get(d, 0.0) + (r["load"] or 0.0)
        return out

    # ---- sets ----
    def replace_sets(self, activity_id, day, rows):
        """rows: (exercise, weight_kg, reps, e1rm)"""
        with self._conn() as c:
            c.execute("DELETE FROM sets WHERE user_id=? AND activity_id=?",
                      (self.uid, activity_id))
            c.executemany("INSERT INTO sets VALUES(?,?,?,?,?,?,?)",
                          [(self.uid, activity_id, day, *r) for r in rows])

    def set_count(self, activity_id) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM sets WHERE user_id=? AND activity_id=?",
                             (self.uid, activity_id)).fetchone()[0]

    def best_e1rms(self, exclude_activity_id=None) -> dict[str, float]:
        with self._conn() as c:
            rows = c.execute("SELECT exercise, MAX(e1rm) m FROM sets WHERE user_id=?"
                             " AND activity_id IS NOT ? GROUP BY exercise",
                             (self.uid, exclude_activity_id)).fetchall()
        return {r["exercise"]: r["m"] for r in rows}

    def e1rm_history(self, exercise: str):
        with self._conn() as c:
            rows = c.execute("SELECT day, MAX(e1rm) m FROM sets WHERE user_id=? AND exercise=?"
                             " GROUP BY day ORDER BY day", (self.uid, exercise)).fetchall()
        return [(r["day"], r["m"]) for r in rows]

    def recent_sets(self, days: int):
        since = (date.today() - timedelta(days=days)).isoformat()
        with self._conn() as c:
            return [(r["exercise"], r["reps"]) for r in c.execute(
                "SELECT exercise, reps FROM sets WHERE user_id=? AND day>=?", (self.uid, since))]

    # ---- chat session (30-min sliding window) ----
    def get_session(self):
        with self._conn() as c:
            r = c.execute("SELECT * FROM sessions WHERE user_id=?", (self.uid,)).fetchone()
        if not r:
            return None
        return {"activity_id": r["activity_id"], "last_ts": r["last_ts"],
                "history": json.loads(r["history"])}

    def set_session(self, activity_id, history, now=None):
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)",
                      (self.uid, activity_id, now or time.time(), json.dumps(history)))

    # ---- privacy ----
    def export_all(self) -> dict:
        with self._conn() as c:
            acts = [self._act(r) for r in c.execute(
                "SELECT * FROM activities WHERE user_id=? ORDER BY start_date", (self.uid,))]
            sets = [dict(r) for r in c.execute("SELECT * FROM sets WHERE user_id=?", (self.uid,))]
        return {"activities": acts, "sets": sets, "goal": self.get_kv("goal")}

    def wipe_data(self):
        """Delete workouts, sets, chat and settings. Keeps the account + Strava link."""
        with self._conn() as c:
            for t in ("user_kv", "activities", "sets", "sessions", "usage"):
                c.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))

    def delete_account(self):
        self.wipe_data()
        with self._conn() as c:
            c.execute("DELETE FROM users WHERE id=?", (self.uid,))
