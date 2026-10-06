"""Thin HTTP layer: validate -> hand to Service -> return fast. All logic lives in service.py."""
from __future__ import annotations

import hmac
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from app import dashboard
from app.config import load_settings
from app.jobs import JobQueue, Worker
from app.observability import init_sentry, metrics_text, setup_logging
from app.service import Service, SignupClosed

log = logging.getLogger("stride.http")
STATIC = Path(__file__).parent / "static"
SEC_HEADERS = {
    "Referrer-Policy": "no-referrer",  # dashboard token lives in the URL
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; "
                               "style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'",
}


def build_service(settings) -> Service:
    from app.clients.llm import LLM
    from app.clients.telegram import TelegramClient
    from app.crypto import TokenCipher
    from app.storage import Database
    db = Database(settings.db_path, TokenCipher(settings.encryption_key))
    return Service(settings, db, JobQueue(db), TelegramClient(settings.telegram_token),
                   LLM(settings.openai_model))


def create_app(service: Service | None = None) -> FastAPI:
    if service is None:
        settings = load_settings()
        setup_logging(settings.log_json)
        init_sentry(settings.sentry_dsn)
        service = build_service(settings)
    svc, cfg = service, service.s

    @asynccontextmanager
    async def lifespan(app):
        stop = threading.Event()
        if cfg.run_worker:
            threading.Thread(target=Worker(svc.queue, svc.handlers()).run_forever,
                             args=(stop,), daemon=True, name="worker").start()
        yield
        stop.set()

    app = FastAPI(title="stride-coach", lifespan=lifespan)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/readyz")
    def readyz():
        try:
            svc.db.user_count()
        except Exception as e:
            raise HTTPException(503, f"db unavailable: {type(e).__name__}")
        return {"ok": True, "jobs": svc.queue.counts()}

    @app.get("/metrics")
    def metrics(request: Request):
        tok = cfg.metrics_token
        if not tok or not hmac.compare_digest(request.headers.get("authorization", ""),
                                              f"Bearer {tok}"):
            raise HTTPException(404)
        return PlainTextResponse(metrics_text(svc.db, svc.queue))

    # ---- onboarding ----
    @app.get("/oauth/strava/start")
    def oauth_start(state: str):
        try:
            return RedirectResponse(svc.oauth_redirect(state))
        except PermissionError:
            raise HTTPException(400, "Link invalid or expired. Send /start to the bot again.")

    @app.get("/oauth/strava/callback")
    def oauth_cb(state: str, code: str = "", error: str = ""):
        if error or not code:
            return PlainTextResponse("Strava authorization was cancelled.", status_code=400)
        try:
            svc.complete_oauth(state, code)
        except PermissionError:
            raise HTTPException(400, "Link invalid or expired. Send /start to the bot again.")
        except SignupClosed:
            raise HTTPException(403, "This bot isn't accepting new users.")
        return PlainTextResponse("Strava connected. Head back to Telegram!")

    # ---- webhooks (ack fast; work happens in the worker) ----
    @app.get("/api/webhook/strava")
    def strava_verify(request: Request):
        q = request.query_params
        if not hmac.compare_digest(q.get("hub.verify_token", ""), cfg.strava_verify_token):
            raise HTTPException(403, "bad verify token")
        return {"hub.challenge": q.get("hub.challenge")}

    @app.post("/api/webhook/strava")
    async def strava_event(request: Request):
        status = svc.ingest_strava(await request.json())
        return {"status": status}

    @app.post("/api/webhook/telegram")
    async def telegram_event(request: Request):
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(got, cfg.telegram_secret):
            raise HTTPException(403, "bad secret")
        return {"status": svc.ingest_telegram(await request.json())}

    # ---- dashboard ----
    @app.get("/dashboard", response_class=HTMLResponse)
    def dash_page():
        return HTMLResponse((STATIC / "dashboard.html").read_text(), headers=SEC_HEADERS)

    @app.get("/api/dashboard")
    def dash_api(t: str = ""):
        user = svc.user_for_dashboard(t)
        if not user:
            return JSONResponse({"error": "invalid or expired"}, status_code=401,
                                headers=SEC_HEADERS)
        return JSONResponse(dashboard.build(svc.db.for_user(user["id"])), headers=SEC_HEADERS)

    return app


def app_factory() -> FastAPI:  # uvicorn app.server:app_factory --factory
    return create_app()
