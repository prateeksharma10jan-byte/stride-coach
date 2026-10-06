"""Durable job queue on the database: retries with exponential backoff, a dead-letter state,
and recovery of jobs abandoned by a crashed worker. Webhooks enqueue and return instantly;
a worker executes. Swap for SQS/Redis later without touching handlers."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

log = logging.getLogger("stride.jobs")


class JobQueue:
    def __init__(self, db, max_attempts: int = 5, visibility_timeout: float = 600,
                 clock=time.time):
        self.db, self.max_attempts, self.vis, self.now = db, max_attempts, visibility_timeout, clock

    def _raw(self):
        c = sqlite3.connect(self.db.path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        return c

    def enqueue(self, kind: str, payload: dict, delay: float = 0) -> int:
        with self.db._conn() as c:
            cur = c.execute("INSERT INTO jobs(kind,payload,run_after,created_at) VALUES(?,?,?,?)",
                            (kind, json.dumps(payload), self.now() + delay, self.now()))
            return cur.lastrowid

    def claim(self):
        """Atomically take the next due job (BEGIN IMMEDIATE = write lock => no double-claim)."""
        c = self._raw()
        try:
            c.execute("BEGIN IMMEDIATE")
            t = self.now()
            c.execute("UPDATE jobs SET status='pending' WHERE status='running' AND claimed_at<?",
                      (t - self.vis,))  # crashed worker: make the job claimable again
            r = c.execute("SELECT * FROM jobs WHERE status='pending' AND run_after<=?"
                          " ORDER BY id LIMIT 1", (t,)).fetchone()
            if not r:
                c.execute("COMMIT")
                return None
            c.execute("UPDATE jobs SET status='running', attempts=attempts+1, claimed_at=?"
                      " WHERE id=?", (t, r["id"]))
            c.execute("COMMIT")
            d = dict(r)
            d["attempts"] += 1
            d["payload"] = json.loads(d["payload"])
            return d
        except Exception:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def complete(self, job_id: int):
        with self.db._conn() as c:
            c.execute("UPDATE jobs SET status='done' WHERE id=?", (job_id,))

    def fail(self, job: dict, error: str):
        dead = job["attempts"] >= self.max_attempts
        backoff = min(5 * 2 ** job["attempts"], 600)
        with self.db._conn() as c:
            c.execute("UPDATE jobs SET status=?, last_error=?, run_after=? WHERE id=?",
                      ("dead" if dead else "pending", error[:500], self.now() + backoff, job["id"]))
        return dead

    def counts(self) -> dict[str, int]:
        with self.db._conn() as c:
            rows = c.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
        out = {"pending": 0, "running": 0, "done": 0, "dead": 0}
        out.update({r["status"]: r["n"] for r in rows})
        return out

    def requeue_dead(self) -> int:
        with self.db._conn() as c:
            return c.execute("UPDATE jobs SET status='pending', attempts=0, run_after=?"
                             " WHERE status='dead'", (self.now(),)).rowcount


class Worker:
    def __init__(self, queue: JobQueue, handlers: dict):
        self.q, self.handlers = queue, handlers

    def run_once(self) -> bool:
        job = self.q.claim()
        if not job:
            return False
        try:
            self.handlers[job["kind"]](job["payload"])
            self.q.complete(job["id"])
        except Exception as e:
            dead = self.q.fail(job, f"{type(e).__name__}: {e}")
            log.error("job %s failed (%s)%s", job["id"], e, " -> DEAD" if dead else " -> retry",
                      exc_info=True)
        return True

    def run_forever(self, stop: threading.Event, poll: float = 1.0):
        while not stop.is_set():
            try:
                if not self.run_once():
                    stop.wait(poll)
            except Exception:
                log.exception("worker loop error")
                stop.wait(poll)
