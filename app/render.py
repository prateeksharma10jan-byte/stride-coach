"""LLM markdown -> Telegram-safe HTML. Escape first, then whitelist a tiny tag set."""
from __future__ import annotations

import html
import re

LIMIT = 3500  # Telegram max is 4096; leave headroom for escaping growth


def to_telegram_html(md: str) -> str:
    s = html.escape(md, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s, flags=re.S)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    s = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", s)
    s = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", s, flags=re.M)
    return s.replace("\n- ", "\n• ").replace("\n* ", "\n• ")


def chunk_markdown(md: str, limit: int = LIMIT) -> list[str]:
    """Split on paragraph boundaries BEFORE converting, so every chunk's tags balance."""
    chunks, cur = [], ""
    for para in md.strip().split("\n\n"):
        while len(para) > limit:  # pathological paragraph: hard-split
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(para[:limit])
            para = para[limit:]
        if len(cur) + len(para) + 2 > limit and cur:
            chunks.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        chunks.append(cur)
    return chunks or [""]
