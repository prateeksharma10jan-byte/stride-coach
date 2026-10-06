"""Stateless signed tokens (HMAC-SHA256, expiring). Used for OAuth state and dashboard links."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(payload: dict, secret: str, ttl: int, now: float | None = None) -> str:
    body = dict(payload, exp=int((now or time.time()) + ttl))
    raw = _b64(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{sig}"


def verify(token: str, secret: str, now: float | None = None) -> dict | None:
    """Returns the payload, or None if malformed / tampered / expired."""
    try:
        raw, sig = token.split(".", 1)
        good = _b64(hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        body = json.loads(_unb64(raw))
        if body.get("exp", 0) < (now or time.time()):
            return None
        return body
    except Exception:
        return None
