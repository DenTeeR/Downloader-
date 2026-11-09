"""If Telegram refuses premium emoji (the bot owner has no Telegram Premium and
the bot has no Fragment username), retry the same request with normal emoji
instead of failing. Installed as a request middleware on the bot session."""
from __future__ import annotations

import logging
import time
from typing import Any

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo

from .design import strip_premium

log = logging.getLogger(__name__)
RECHECK_SECONDS = 1800


def _has_premium(method: Any) -> bool:
    for name in ("text", "caption"):
        value = getattr(method, name, None)
        if isinstance(value, str) and "<tg-emoji" in value:
            return True
    markup = getattr(method, "reply_markup", None)
    if isinstance(markup, InlineKeyboardMarkup):
        if any(b.icon_custom_emoji_id for row in markup.inline_keyboard for b in row):
            return True
    for media in getattr(method, "media", None) or []:
        if isinstance(getattr(media, "caption", None), str) and "<tg-emoji" in media.caption:
            return True
    return False


def _without_premium(method: Any) -> Any:
    update: dict[str, Any] = {}
    for name in ("text", "caption"):
        value = getattr(method, name, None)
        if isinstance(value, str):
            update[name] = strip_premium(value)
    markup = getattr(method, "reply_markup", None)
    if isinstance(markup, InlineKeyboardMarkup):
        update["reply_markup"] = InlineKeyboardMarkup(inline_keyboard=[
            [b.model_copy(update={"icon_custom_emoji_id": None}) for b in row]
            for row in markup.inline_keyboard
        ])
    media = getattr(method, "media", None)
    if isinstance(media, list):
        update["media"] = [
            m.model_copy(update={"caption": strip_premium(m.caption)})
            if isinstance(m, (InputMediaPhoto, InputMediaVideo)) and m.caption else m
            for m in media
        ]
    return method.model_copy(update=update)


class PremiumEmojiFallback(BaseRequestMiddleware):
    def __init__(self) -> None:
        self._blocked_until = 0.0

    async def __call__(self, make_request, bot, method):  # type: ignore[override]
        if not _has_premium(method):
            return await make_request(bot, method)
        if self._blocked_until > time.monotonic():
            return await make_request(bot, _without_premium(method))
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as exc:
            plain = _without_premium(method)
            result = await make_request(bot, plain)  # raises again if unrelated
            self._blocked_until = time.monotonic() + RECHECK_SECONDS
            log.warning("Telegram rejected premium emoji (%s); sending normal emoji instead. "
                        "The bot owner needs Telegram Premium to use them.", exc.message)
            return result
