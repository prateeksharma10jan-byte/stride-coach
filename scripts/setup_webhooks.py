"""One-time: register Telegram + Strava webhooks (run where APP_URL is reachable)."""
import httpx

from app.clients.telegram import TelegramClient
from app.config import load_settings

s = load_settings()
print(TelegramClient(s.telegram_token).set_webhook(
    f"{s.app_url}/api/webhook/telegram", s.telegram_secret))
r = httpx.post("https://www.strava.com/api/v3/push_subscriptions", data={
    "client_id": s.strava_client_id, "client_secret": s.strava_client_secret,
    "callback_url": f"{s.app_url}/api/webhook/strava", "verify_token": s.strava_verify_token})
print(r.status_code, r.text, "\n-> put the returned id in STRAVA_SUBSCRIPTION_ID and redeploy")
