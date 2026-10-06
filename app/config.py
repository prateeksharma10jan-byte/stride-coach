"""The ONLY module that reads environment variables. Fails fast on missing ones."""
import os
from dataclasses import dataclass


def _req(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    telegram_secret: str
    strava_client_id: str
    strava_client_secret: str
    strava_verify_token: str
    strava_subscription_id: int | None
    openai_model: str
    llm_daily_cap: int          # per user, per day
    default_max_hr: int
    default_rest_hr: int
    db_path: str
    app_url: str
    app_secret: str             # signs OAuth state + dashboard links
    encryption_key: str         # Fernet key for Strava tokens at rest
    max_users: int              # hard cap on signups (cost control)
    metrics_token: str          # bearer token for /metrics ('' = endpoint disabled)
    sentry_dsn: str
    run_worker: bool            # run the job worker inside the web process
    log_json: bool


def load_settings() -> Settings:
    sub = os.environ.get("STRAVA_SUBSCRIPTION_ID", "")
    return Settings(
        telegram_token=_req("TELEGRAM_BOT_TOKEN"),
        telegram_secret=_req("TELEGRAM_WEBHOOK_SECRET"),
        strava_client_id=_req("STRAVA_CLIENT_ID"),
        strava_client_secret=_req("STRAVA_CLIENT_SECRET"),
        strava_verify_token=_req("STRAVA_VERIFY_TOKEN"),
        strava_subscription_id=int(sub) if sub else None,
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        llm_daily_cap=int(os.environ.get("LLM_DAILY_CALL_CAP", "40")),
        default_max_hr=int(os.environ.get("MAX_HR", "190")),
        default_rest_hr=int(os.environ.get("REST_HR", "55")),
        db_path=os.environ.get("DB_PATH", "stride.db"),
        app_url=_req("APP_URL").rstrip("/"),
        app_secret=_req("APP_SECRET"),
        encryption_key=_req("ENCRYPTION_KEY"),
        max_users=int(os.environ.get("MAX_USERS", "20")),
        metrics_token=os.environ.get("METRICS_TOKEN", ""),
        sentry_dsn=os.environ.get("SENTRY_DSN", ""),
        run_worker=os.environ.get("RUN_WORKER", "1") == "1",
        log_json=os.environ.get("LOG_JSON", "1") == "1",
    )
