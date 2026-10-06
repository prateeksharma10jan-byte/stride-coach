from __future__ import annotations


from app.render import chunk_markdown, to_telegram_html


def _client(timeout: float):
    import httpx  # imported lazily: tests inject fakes and don't need it
    return httpx.Client(timeout=timeout)


class TelegramClient:
    def __init__(self, token: str, http=None):
        self.base = f"https://api.telegram.org/bot{token}"
        self.http = http or _client(30)

    def send_markdown(self, chat_id: int, text: str) -> None:
        for chunk in chunk_markdown(text):
            r = self.http.post(f"{self.base}/sendMessage", json={
                "chat_id": chat_id, "text": to_telegram_html(chunk), "parse_mode": "HTML"})
            r.raise_for_status()

    def send_photo(self, chat_id: int, png: bytes, caption: str = "") -> None:
        r = self.http.post(f"{self.base}/sendPhoto",
                           data={"chat_id": chat_id, "caption": caption[:1000]},
                           files={"photo": ("chart.png", png, "image/png")})
        r.raise_for_status()

    def send_document(self, chat_id: int, filename: str, data: bytes, caption: str = "") -> None:
        r = self.http.post(f"{self.base}/sendDocument",
                           data={"chat_id": chat_id, "caption": caption[:1000]},
                           files={"document": (filename, data, "application/json")})
        r.raise_for_status()

    def set_webhook(self, url: str, secret: str) -> dict:
        r = self.http.post(f"{self.base}/setWebhook",
                           json={"url": url, "secret_token": secret})
        r.raise_for_status()
        return r.json()
