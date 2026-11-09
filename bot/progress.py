"""A status message that is edited in place while a job runs.

yt-dlp reports progress from a worker thread; `report()` only stores the
latest text, and a small async loop pushes it to Telegram every few seconds
(editing faster would hit Telegram's flood limits)."""
from __future__ import annotations

import asyncio
import contextlib
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from . import texts
from .utils import format_size, progress_bar


class StatusMessage:
    def __init__(self, bot: Bot, chat_id: int, message_id: int, *,
                 is_caption: bool = False, interval: float = 3.0) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.is_caption = is_caption
        self.interval = interval
        self.header = ""   # first line of progress updates
        self.banner = ""   # fixed text shown above everything (playlist title)
        self._pending: str | None = None
        self._shown: str | None = None
        self._task: asyncio.Task | None = None
        self._last_edit = 0.0

    async def set(self, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        """Edit right away (used for state changes, not for progress ticks)."""
        if self.banner:
            text = f"{self.banner}\n\n{text}"
        if text == self._shown and markup is None:
            return
        try:
            if self.is_caption:
                await self.bot.edit_message_caption(
                    chat_id=self.chat_id, message_id=self.message_id,
                    caption=text, reply_markup=markup,
                )
            else:
                await self.bot.edit_message_text(
                    text=text, chat_id=self.chat_id, message_id=self.message_id,
                    reply_markup=markup,
                )
            self._shown = text
            self._last_edit = time.monotonic()
        except TelegramRetryAfter:
            pass
        except TelegramAPIError:  # "message is not modified", deleted message, ...
            pass

    def report(self, downloaded: int, total: int | None, speed: float | None) -> None:
        """Thread-safe: called from yt-dlp's progress hook."""
        lines = [self.header or texts.DOWNLOADING]
        if total:
            frac = downloaded / total
            lines.append(f"{progress_bar(frac)} {frac * 100:.0f}%")
            lines.append(f"📦 {format_size(downloaded)} / {format_size(total)}")
        else:
            lines.append(f"📦 {format_size(downloaded)}")
        if speed:
            lines.append(f"🚀 {format_size(speed)}/s")
        self._pending = "\n".join(lines)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            if self._pending:
                await self.set(self._pending)  # no-op when unchanged

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._pending = None

    async def delete(self) -> None:
        await self.stop()
        with contextlib.suppress(TelegramAPIError):
            await self.bot.delete_message(self.chat_id, self.message_id)
