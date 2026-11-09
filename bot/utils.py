"""Small helpers: formatting and a TTL key/value store."""
from __future__ import annotations

import html
import secrets
import time
from typing import Generic, TypeVar

T = TypeVar("T")

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(value: object) -> str:
    """Render digits in Persian."""
    return str(value).translate(_FA_DIGITS)


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)


def format_size(size: float | None) -> str:
    if not size:
        return "نامشخص"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def format_duration(seconds: float | None) -> str:
    if not seconds:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def progress_bar(fraction: float, width: int = 12) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    return "▰" * filled + "▱" * (width - filled)


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class TTLStore(Generic[T]):
    """In-memory store with expiring entries and short random keys
    (Telegram callback_data is limited to 64 bytes, so URLs can't go there)."""

    def __init__(self, ttl: float = 3600) -> None:
        self.ttl = ttl
        self._items: dict[str, tuple[float, T]] = {}

    def put(self, value: T) -> str:
        self._purge()
        key = secrets.token_urlsafe(6)
        self._items[key] = (time.monotonic() + self.ttl, value)
        return key

    def get(self, key: str) -> T | None:
        item = self._items.get(key)
        if not item or item[0] < time.monotonic():
            self._items.pop(key, None)
            return None
        return item[1]

    def pop(self, key: str) -> T | None:
        value = self.get(key)
        self._items.pop(key, None)
        return value

    def _purge(self) -> None:
        now = time.monotonic()
        for key in [k for k, (exp, _) in self._items.items() if exp < now]:
            del self._items[key]
