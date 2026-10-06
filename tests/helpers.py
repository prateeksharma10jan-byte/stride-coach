import os
import tempfile
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from app.crypto import TokenCipher
from app.jobs import JobQueue, Worker
from app.service import Service
from app.storage import Database

NOW_ISO = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
SECRET_TOKEN = "SECRET_ACCESS_TOKEN"


class FakeTG:
    def __init__(self):
        self.texts, self.photos, self.docs = [], [], []

    def send_markdown(self, chat_id, text): self.texts.append((chat_id, text))
    def send_photo(self, chat_id, png, caption=""): self.photos.append((chat_id, png[:4], caption))
    def send_document(self, chat_id, name, data, caption=""): self.docs.append((chat_id, name, data))
    def to(self, chat_id): return [t for c, t in self.texts if c == chat_id]


class FakeLLM:
    def __init__(self, replies=None):
        self.calls, self.replies = [], list(replies or [])

    def complete(self, system, messages, max_tokens=700):
        self.calls.append((system, messages))
        return self.replies.pop(0) if self.replies else "Solid session. **Z2 dominant.**"


class FakeStrava:
    def __init__(self, acts): self.acts = acts
    def authorize_url(self, redirect_uri, state): return f"https://strava.test/authorize?state={state}"
    def exchange_code(self, code):
        return {"athlete": {"id": int(code)}, "access_token": SECRET_TOKEN,
                "refresh_token": "RT", "expires_at": 9999999999}
    def get_activity(self, i): return self.acts[i]
    def get_laps(self, i): return [{"distance": 1000, "average_speed": 3.3, "average_heartrate": 150}]
    def get_streams(self, i):
        n = 300
        return {"time": list(range(0, n * 10, 10)), "heartrate": [150] * n,
                "velocity_smooth": [3.3] * n, "distance": [k * 33 for k in range(n)]}


def run_act(i=1, name="Easy run"):
    return {"id": i, "name": name, "sport_type": "Run", "start_date": NOW_ISO,
            "distance": 10000, "moving_time": 3000, "average_heartrate": 150}


def lift_act(i=2, desc="Push\n\n1. Bench\nSet 1: 80 kg x 5\nSet 2: 80 kg x 5\n"):
    return {"id": i, "name": "Workout", "sport_type": "WeightTraining",
            "start_date": NOW_ISO, "description": desc}


class Env:
    def __init__(self, llm=None, cap=40, max_users=5, acts=None, sub_id=None, clock=time.time):
        self.acts = acts if acts is not None else {1: run_act(), 2: lift_act()}
        s = SimpleNamespace(app_url="https://app.test", app_secret="s3cret", max_users=max_users,
                            strava_subscription_id=sub_id, llm_daily_cap=cap,
                            default_max_hr=190, default_rest_hr=55)
        self.path = os.path.join(tempfile.mkdtemp(), "t.db")
        self.db = Database(self.path, TokenCipher(TokenCipher.generate_key()))
        self.queue = JobQueue(self.db, clock=clock)
        self.tg, self.llm = FakeTG(), llm or FakeLLM()
        self.svc = Service(s, self.db, self.queue, self.tg, self.llm,
                           strava_factory=lambda uid: FakeStrava(self.acts), clock=clock)
        self.worker = Worker(self.queue, self.svc.handlers())

    def onboard(self, chat_id=42, athlete=777):
        url = self.svc.connect_url(chat_id)
        state = parse_qs(urlparse(url).query)["state"][0]
        return self.svc.complete_oauth(state, str(athlete))

    def drain(self):
        while self.worker.run_once():
            pass

    def strava_ev(self, obj, athlete=777, aspect="create", t=1, **kw):
        return dict({"object_type": "activity", "aspect_type": aspect, "object_id": obj,
                     "owner_id": athlete, "event_time": t}, **kw)

    def say(self, text, chat_id=42, uid=1):
        r = self.svc.ingest_telegram({"update_id": hash((text, chat_id, time.time())),
                                      "message": {"chat": {"id": chat_id}, "text": text}})
        self.drain()
        return r
