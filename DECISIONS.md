# Decisions & known gaps

| Decision | Why | Trade-off |
|---|---|---|
| LLM never does arithmetic; runtime number guard | No hallucinated stats; failures degrade to a plain summary | Ints 0-10 are exempt from the guard (counts/ordinals); goal numbers allowed |
| HR zones weighted by elapsed seconds | Streams are unevenly spaced; sample-counting skews zones (tested) | Pauses capped at 30s |
| Personalised max HR = max(configured, p95 of past run peaks) | Formula max HR is often wrong | Needs 5+ runs; sensor spikes filtered to 120-230 bpm |
| Lifting from Strava description | Hevy API needs Pro | **Parser is provisional**, validate on your own data |
| Late-synced lifts via `update` events | Hevy may write the description after creation | Updates for runs ignored |
| **SQLite-backed job queue** (not Redis/SQS) | Durable, transactional, zero extra infra; retries/backoff/DLQ/crash recovery implemented and tested | Single-host. For scale: swap `JobQueue` for SQS/Celery (handlers unchanged) |
| **SQLite, not Postgres** | Tested here end-to-end; one file to back up | Needs a persistent disk; no horizontal scaling. `UserDB` is the seam for a Postgres port |
| Signed stateless tokens (dashboard, OAuth state) | No sessions table, no login UI | Token in URL (mitigated: 24h TTL, no-referrer); not revocable before expiry |
| Dashboard in vanilla JS/SVG | No build step, no CDN, CSP-friendly | Not a React app; fewer interactions |
| Rule-based `/plan` | Safe, explainable, testable | Doesn't adapt to goal text/race dates |
| ACWR from running TRIMP only | Lifting has no HR load here | Understates load for mixed athletes |
| Rate limiter is in-process | Simple | Per-instance only |

## Open items
- Validate the Hevy parser against real descriptions; add fixtures from them.
- Live end-to-end run on real accounts (Strava -> worker -> OpenAI -> Telegram) is **untested in the dev sandbox**; do this before relying on it.
- Port `storage.py` to Postgres + Alembic if you need >1 instance.
- Re-encrypt tooling for `ENCRYPTION_KEY` rotation.
- Grow `evals/fixtures.py` from real bad replies; run evals in CI on prompt changes (needs an API key secret).
