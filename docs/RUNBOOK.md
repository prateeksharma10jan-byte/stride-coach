# Runbook

**Is it up?** `GET /healthz` (process) and `GET /readyz` (DB + queue counts).

**Metrics.** Set `METRICS_TOKEN`, scrape `GET /metrics` with `Authorization: Bearer ...`:
`stride_jobs{status=pending|running|done|dead}`, `stride_users`, `stride_llm_calls_today`.
Alert on `stride_jobs{status="dead"} > 0` and on pending staying > 0 for several minutes.

**Dead jobs.** Read `jobs.last_error`, fix the cause, then `python scripts/requeue_dead.py`.

**Bot silent after a workout.** (1) `/readyz` ok? (2) pending jobs piling up -> worker not running
(`RUN_WORKER=1` or run `scripts/run_worker.py`). (3) Strava webhook subscription alive? Re-run
`scripts/setup_webhooks.py`. (4) Token problems: user sends `/start` again to reconnect.

**Backups.** Copy the SQLite file (WAL mode: use `sqlite3 stride.db ".backup out.db"`).

**LLM regression check** before changing a prompt or model:
`python -m evals.run_evals --samples 5 --threshold 0.95`.
