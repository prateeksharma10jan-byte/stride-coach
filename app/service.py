"""Application service: onboarding, fast webhook ingestion, and the job handlers.

Ingestion methods only validate + de-dupe + enqueue (so webhooks ack in milliseconds);
handlers run later inside the worker, with retries."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from app import auth
from app.bot import Bot
from app.clients.strava import StravaClient, UserTokenStore

log = logging.getLogger("stride.service")
RATE_LIMIT, RATE_WINDOW = 20, 60  # messages per chat per minute (in-process limiter)


class SignupClosed(Exception):
    pass


class Service:
    def __init__(self, settings, db, queue, telegram, llm, strava_factory=None, clock=time.time):
        self.s, self.db, self.queue, self.tg, self.llm, self.now = (
            settings, db, queue, telegram, llm, clock)
        self.strava_factory = strava_factory or (
            lambda uid: StravaClient(settings.strava_client_id, settings.strava_client_secret,
                                     UserTokenStore(db, uid) if uid else None))
        self._hits: dict[int, deque] = defaultdict(deque)

    # ------------------------------------------------------------ users / bots
    def bot_for(self, user: dict) -> Bot:
        return Bot(self.s, self.db.for_user(user["id"]), self.strava_factory(user["id"]),
                   self.tg, self.llm, user,
                   dashboard_url=lambda: self.dashboard_url(user["id"]), clock=self.now)

    def dashboard_url(self, user_id: int) -> str:
        t = auth.sign({"p": "dash", "uid": user_id}, self.s.app_secret, 86400, self.now())
        return f"{self.s.app_url}/dashboard?t={t}"

    def user_for_dashboard(self, token: str) -> dict | None:
        body = auth.verify(token or "", self.s.app_secret, self.now())
        if not body or body.get("p") != "dash":
            return None
        return self.db.get_user(body["uid"])

    # ------------------------------------------------------------ onboarding
    def connect_url(self, chat_id: int) -> str:
        state = auth.sign({"p": "oauth", "chat": chat_id}, self.s.app_secret, 3600, self.now())
        return f"{self.s.app_url}/oauth/strava/start?state={state}"

    def oauth_redirect(self, state: str) -> str:
        if not auth.verify(state, self.s.app_secret, self.now()):
            raise PermissionError("invalid or expired link")
        return self.strava_factory(None).authorize_url(
            f"{self.s.app_url}/oauth/strava/callback", state)

    def complete_oauth(self, state: str, code: str) -> dict:
        body = auth.verify(state, self.s.app_secret, self.now())
        if not body or body.get("p") != "oauth":
            raise PermissionError("invalid or expired link")
        chat_id = body["chat"]
        if not self.db.user_by_chat(chat_id) and self.db.user_count() >= self.s.max_users:
            raise SignupClosed("user limit reached")
        tok = self.strava_factory(None).exchange_code(code)
        user = self.db.upsert_user(
            chat_id, tok["athlete"]["id"],
            {k: tok[k] for k in ("access_token", "refresh_token", "expires_at")},
            self.s.default_max_hr, self.s.default_rest_hr)
        self.tg.send_markdown(chat_id, "Strava connected! I'll message you after each workout.\n\n"
                                       "Send /help to see what I can do.")
        return user

    # ------------------------------------------------------------ ingestion (fast path)
    def ingest_strava(self, ev: dict) -> str:
        sub = self.s.strava_subscription_id
        if sub is not None and ev.get("subscription_id") != sub:
            return "rejected"
        user = self.db.user_by_athlete(ev.get("owner_id"))
        if not user:
            return "unknown_user"
        key = f"strava:{ev.get('object_id')}:{ev.get('aspect_type')}:{ev.get('event_time')}"
        if not self.db.mark_event(key):
            return "duplicate"
        self.queue.enqueue("strava_event", {"user_id": user["id"], "event": ev})
        return "queued"

    def _rate_limited(self, chat_id: int) -> bool:
        q, t = self._hits[chat_id], self.now()
        while q and q[0] < t - RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return True
        q.append(t)
        return False

    def ingest_telegram(self, update: dict) -> str:
        msg = update.get("message") or {}
        chat_id, text = (msg.get("chat") or {}).get("id"), (msg.get("text") or "")
        if chat_id is None or not text:
            return "ignored"
        if self._rate_limited(chat_id):
            return "rate_limited"
        if not self.db.mark_event(f"tg:{update.get('update_id')}"):
            return "duplicate"
        self.queue.enqueue("telegram_update", update)
        return "queued"

    # ------------------------------------------------------------ job handlers (worker)
    def handle_strava_event(self, payload: dict) -> None:
        user = self.db.get_user(payload["user_id"])
        if user:  # may have deleted their account since enqueue
            self.bot_for(user).handle_strava_event(payload["event"])

    def handle_telegram_update(self, update: dict) -> None:
        msg = update["message"]
        chat_id, text = msg["chat"]["id"], (msg.get("text") or "").strip()
        user = self.db.user_by_chat(chat_id)
        if user is None:
            if text.startswith("/start"):
                if self.db.user_count() >= self.s.max_users:
                    self.tg.send_markdown(chat_id, "Sorry, this bot isn't accepting new users.")
                else:
                    self.tg.send_markdown(
                        chat_id, "Welcome! Connect your Strava account to get started:\n"
                                 f"{self.connect_url(chat_id)}\n\n(link valid for 1 hour)")
            else:
                self.tg.send_markdown(chat_id, "Send /start to connect your Strava account.")
            return
        self.bot_for(user).handle_message(text)

    def handlers(self) -> dict:
        return {"strava_event": self.handle_strava_event,
                "telegram_update": self.handle_telegram_update}
