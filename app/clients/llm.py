from __future__ import annotations


class LLM:
    """Thin OpenAI wrapper. The model INTERPRETS pre-computed numbers; it never computes them."""

    def __init__(self, model: str, client=None):
        if client is None:
            from openai import OpenAI  # imported lazily so tests need no SDK
            client = OpenAI()  # reads OPENAI_API_KEY
        self.client, self.model = client, model

    def complete(self, system: str, messages: list[dict], max_tokens: int = 700) -> str:
        resp = self.client.chat.completions.create(
            model=self.model, temperature=0.4, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, *messages])
        return (resp.choices[0].message.content or "").strip()
