# Security notes

| Area | Control |
|---|---|
| Strava tokens | Fernet-encrypted at rest (`ENCRYPTION_KEY`); wrong key fails loudly |
| Webhooks | Strava: verify token + optional `subscription_id` check. Telegram: secret header (constant-time compare) |
| OAuth | Signed, 1-hour `state` binds the callback to the chat that started it |
| Dashboard | HMAC-signed 24h token, purpose-scoped (OAuth tokens can't open it); `Referrer-Policy: no-referrer`; CSP; DOM built with `textContent` (workout names are attacker-influenced) |
| Output | LLM text HTML-escaped before a whitelist of Telegram tags is applied |
| Abuse / cost | `MAX_USERS`, per-user daily LLM cap, per-chat message rate limit (in-process) |
| Privacy | `/export`, `/forget`, `/deleteaccount confirm` |
| Container | non-root user, minimal image |

## Rotating secrets
- **TELEGRAM_WEBHOOK_SECRET / STRAVA_VERIFY_TOKEN**: change env, redeploy, re-run `scripts/setup_webhooks.py`.
- **APP_SECRET**: change env, redeploy. Outstanding dashboard/OAuth links stop working (they're short-lived).
- **ENCRYPTION_KEY**: rotating requires re-encrypting `users.tokens_enc` (not automated; or have users reconnect via /start).
- **OPENAI_API_KEY**: change env, redeploy.

## Known limits
- Rate limiter and dashboard tokens-in-URL are simple; a shared limiter (Redis) is needed for multi-instance.
- No per-user encryption of workout data (only tokens). Disk encryption is the host's job.
- The Strava webhook has no signature; the origin check is the subscription id plus unguessable callback URL.
