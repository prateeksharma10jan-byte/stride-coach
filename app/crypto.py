"""Token-at-rest encryption (Fernet: AES-128-CBC + HMAC). Key comes from ENCRYPTION_KEY."""
from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken


class TokenCipher:
    def __init__(self, key: str | bytes):
        self._f = Fernet(key)

    def encrypt(self, obj: dict) -> str:
        return self._f.encrypt(json.dumps(obj).encode()).decode()

    def decrypt(self, blob: str) -> dict:
        try:
            return json.loads(self._f.decrypt(blob.encode()))
        except InvalidToken as e:
            raise ValueError("token blob can't be decrypted (wrong ENCRYPTION_KEY?)") from e

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()
