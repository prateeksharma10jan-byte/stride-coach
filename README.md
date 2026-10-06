# stride-coach

![CI](https://github.com/prateeksharma10jan-byte/stride-coach/actions/workflows/ci.yml/badge.svg)

A multi-user Telegram bot (plus a small web dashboard) that reacts to finished **Strava** workouts, sends an AI analysis with charts, then keeps a **30-minute chat** open for follow-ups.

**Core rule:** every number is computed in plain Python and unit-tested. The LLM only *interprets* them, and a runtime **number guard** rejects any reply containing a figure that isn't in the computed facts (retry once, then fall back to a deterministic summary).

## Features
- **Runs:** time-in-zone (weighted by elapsed seconds), aerobic decoupling, Banister TRIMP, ACWR load ratio, lap splits, comparison with similar recent runs, personalised max HR from your own data
- **Lifting:** parsed from Hevy's Strava description. Volume, e1RM, PRs, plateau detection, sets per muscle group
- **Planning:** `/plan` builds next week's runs from your load (rule-based; never >10% jump)
- **Charts:** 5 matplotlib presets + a web dashboard (signed link, no login to manage)
- **Multi-user:** Strava OAuth onboarding via `/start`, strict per-user data scoping, signup cap, per-user LLM budget
- **Reliability:** durable job queue (retries, exponential backoff, dead-letter, crash recovery), idempotent webhooks, late-synced lifts handled via Strava `update` events
- **Privacy/security:** encrypted tokens, `/export`, `/forget`, `/deleteaccount`; see `docs/SECURITY.md`
- **Ops:** JSON logs, optional Sentry, `/healthz` `/readyz` `/metrics`, Dockerfile, CI, runbook

Commands: `/last /week /pr /plan /chart /dashboard /goal /hr /export /forget /deleteaccount /help`

## Quick start
```bash
cp .env.example .env            # fill in values (never commit it)
docker compose up --build       # or: pip install -r requirements.txt && uvicorn app.server:app_factory --factory
python scripts/setup_webhooks.py    # registers Telegram + Strava webhooks (needs public APP_URL)
```
Then message your bot `/start` and follow the Strava link.

## Develop
```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m unittest discover -s tests -t .     # 49+ offline tests, no credentials needed
ruff check .
OPENAI_API_KEY=... python -m evals.run_evals  # LLM grounding evals (real model)
```

## Layout
```
app/config.py        only place env vars are read
app/service.py       onboarding, webhook ingestion, job handlers
app/jobs.py          durable queue + worker
app/bot.py           per-user brain: facts -> guarded LLM -> Telegram
app/guard.py         number-grounding guard
app/metrics/         endurance, strength, trends, muscles, plan  (pure Python)
app/storage.py       SQLite + migrations + UserDB (per-user scoping)
app/dashboard.py     dashboard data; app/static/dashboard.html the page
app/server.py        thin FastAPI layer
evals/               LLM eval fixtures + runner
docs/                ARCHITECTURE, SECURITY, RUNBOOK
```
See `DECISIONS.md` for trade-offs and what's still open.
