from __future__ import annotations

import time
from urllib.parse import urlencode


BASE = "https://www.strava.com/api/v3"


def _client(timeout: float):
    import httpx  # imported lazily: tests inject fakes and don't need it
    return httpx.Client(timeout=timeout)


class UserTokenStore:
    """Per-user token persistence (encrypted at rest by the Database)."""

    def __init__(self, db, user_id: int):
        self.db, self.uid = db, user_id

    def get(self):
        return self.db.get_tokens(self.uid)

    def set(self, tokens: dict):
        self.db.set_tokens(self.uid, tokens)


class StravaClient:
    def __init__(self, client_id, client_secret, store=None, http=None):
        self.cid, self.secret, self.store = client_id, client_secret, store
        self.http = http or _client(20)

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        q = urlencode({"client_id": self.cid, "redirect_uri": redirect_uri, "state": state,
                       "response_type": "code", "approval_prompt": "auto",
                       "scope": "read,activity:read_all"})
        return f"https://www.strava.com/oauth/authorize?{q}"

    def exchange_code(self, code: str) -> dict:
        """Returns Strava's token payload, including `athlete.id`."""
        r = self.http.post("https://www.strava.com/oauth/token", data={
            "client_id": self.cid, "client_secret": self.secret,
            "code": code, "grant_type": "authorization_code"})
        r.raise_for_status()
        return r.json()

    def _access_token(self) -> str:
        tok = self.store.get()
        if not tok:
            raise RuntimeError("Strava not connected for this user")
        if tok["expires_at"] - 60 < time.time():
            r = self.http.post("https://www.strava.com/oauth/token", data={
                "client_id": self.cid, "client_secret": self.secret,
                "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
            r.raise_for_status()
            j = r.json()
            tok = {k: j[k] for k in ("access_token", "refresh_token", "expires_at")}
            self.store.set(tok)
        return tok["access_token"]

    def _get(self, path: str, **params):
        r = self.http.get(f"{BASE}{path}", params=params,
                          headers={"Authorization": f"Bearer {self._access_token()}"})
        r.raise_for_status()
        return r.json()

    def get_activity(self, activity_id: int) -> dict:
        return self._get(f"/activities/{activity_id}")

    def get_laps(self, activity_id: int) -> list[dict]:
        return self._get(f"/activities/{activity_id}/laps")

    def get_streams(self, activity_id: int) -> dict[str, list]:
        raw = self._get(f"/activities/{activity_id}/streams",
                        keys="time,heartrate,velocity_smooth,distance", key_by_type="true")
        return {k: v["data"] for k, v in raw.items()}
