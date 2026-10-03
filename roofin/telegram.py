"""Telegram notifications to YOU (not to prospects), via your own bot. Free.

Setup: in Telegram, message @BotFather -> /newbot -> copy the token into ROOFIN_TELEGRAM_TOKEN.
Send your new bot any message, then run `roofin telegram-setup` to get ROOFIN_TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import html
import os
import time
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"
LIMIT = 4000  # Telegram's hard limit is 4096 characters per message


class TelegramError(RuntimeError):
    pass


def esc(text: str | None) -> str:
    return html.escape(text or "", quote=False)


def copyable(text: str) -> str:
    """A <pre> block: one tap copies the whole thing in Telegram."""
    return f"<pre>{esc(text)}</pre>"


class Telegram:
    def __init__(self, token: str, chat_id: str, session: requests.Session | None = None, pause: float = 1.0):
        self.token, self.chat_id = token, chat_id
        self.http = session or requests.Session()
        self.pause = pause  # Telegram asks bots to stay around 1 message/second per chat

    @classmethod
    def from_env(cls) -> "Telegram | None":
        token, chat = os.environ.get("ROOFIN_TELEGRAM_TOKEN"), os.environ.get("ROOFIN_TELEGRAM_CHAT_ID")
        return cls(token, chat) if token and chat else None

    def _call(self, method: str, **kw) -> dict:
        resp = self.http.post(API.format(token=self.token, method=method), timeout=60, **kw)
        data = resp.json() if resp.content else {}
        if not data.get("ok"):
            raise TelegramError(f"Telegram {method}: {data.get('description') or resp.status_code}")
        if self.pause:
            time.sleep(self.pause)
        return data["result"]

    def send(self, html_text: str) -> None:
        for chunk in split(html_text):
            self._call("sendMessage", data={"chat_id": self.chat_id, "text": chunk, "parse_mode": "HTML",
                                            "disable_web_page_preview": "true"})

    def send_file(self, path: str | Path, caption: str = "") -> None:
        with open(path, "rb") as fh:
            self._call("sendDocument", data={"chat_id": self.chat_id, "caption": caption[:1000]},
                       files={"document": (Path(path).name, fh)})


def split(text: str) -> list[str]:
    """Split on blank lines so <pre> blocks are never cut in half (each block we build is < LIMIT)."""
    if len(text) <= LIMIT:
        return [text]
    chunks, cur = [], ""
    for part in text.split("\n\n"):
        if cur and len(cur) + len(part) + 2 > LIMIT:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n\n{part}" if cur else part
    if cur:
        chunks.append(cur)
    return [c[:4096] for c in chunks]


def find_chat_id(token: str, session: requests.Session | None = None) -> list[tuple[str, str]]:
    http = session or requests.Session()
    data = http.get(API.format(token=token, method="getUpdates"), timeout=30).json()
    if not data.get("ok"):
        raise TelegramError(data.get("description", "bad token"))
    seen = {}
    for u in data["result"]:
        chat = (u.get("message") or u.get("edited_message") or {}).get("chat")
        if chat:
            seen[str(chat["id"])] = chat.get("username") or chat.get("first_name") or ""
    return list(seen.items())
