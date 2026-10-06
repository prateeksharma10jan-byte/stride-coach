# Architecture

```mermaid
flowchart LR
  S[Strava] -- webhook --> W[/api/webhook/strava/]
  T[Telegram] -- webhook --> W2[/api/webhook/telegram/]
  W & W2 -- validate, de-dupe, enqueue --> Q[(jobs table)]
  Q --> K[Worker: retries, backoff, dead-letter]
  K --> SV[Service] --> B[Bot per user]
  B --> M[Pure-Python metrics]
  M --> F[FACTS]
  F --> L[OpenAI]
  L --> G{Number guard}
  G -- grounded --> R[Telegram text + charts]
  G -- fabricated --> L2[retry once] --> G
  G -- still bad --> FB[Deterministic summary]
  B <--> DB[(SQLite: users, activities, sets, sessions)]
  D[Dashboard /dashboard] -- signed 24h token --> API[/api/dashboard/] --> DB
```

**Request path vs work path.** Webhook handlers do three cheap things (authenticate, de-duplicate, enqueue) and return. All Strava/LLM/Telegram I/O happens in the worker, so a slow LLM never causes Strava to retry.

**Trust boundaries.** Strava and Telegram webhooks are authenticated by verify-token / secret header; the dashboard by an HMAC-signed expiring token; OAuth `state` is signed so a callback can't be forged to link someone else's chat.

**Data isolation.** Workout data is reachable only through `UserDB`, which is constructed with one `user_id` and puts it in every query.

**LLM contract.** The model sees only computed FACTS and may not introduce numbers. `guard.py` enforces this at runtime; `evals/` measures it across prompt/model changes.
