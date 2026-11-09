"""The status message of a job, edited in place while it runs.

Every state is a designable screen (text + optional sticker). When a screen
has a sticker, it is shown under the status message and swapped/removed as
the state changes (e.g. an animated "loading" sticker while downloading).

yt-dlp reports progress from a worker thread; `report()` only stores the
latest text and a small async loop pushes it to Telegram every few seconds
(editing faster would hit Telegram's flood limits)."""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, ReplyParameters

from .ui import Design
from .utils import format_size, progress_bar


class StatusMessage:
    def __init__(self, bot: Bot, design: Design, chat_id: int, message_id: int, *,
                 is_caption: bool = False, interval: float = 3.0) -> None:
        self.bot = bot
        self.design = design
        self.chat_id = chat_id
        self.message_id = message_id
        self.is_caption = is_caption
        self.interval = interval
        self.prefix = ""   # e.g. "🎵 2 از 10 — " for playlist items (HTML)
        self.banner = ""   # fixed text above everything (playlist title, HTML)
        self._header = ""
        self._pending: str | None = None
        self._shown: str | None = None
        self._task: asyncio.Task | None = None
        self._sticker_file: str | None = None
        self._sticker_msg: int | None = None

    @classmethod
    async def create(cls, bot: Bot, design: Design, chat_id: int, reply_to: int | None,
                     key: str, /, **params: Any) -> "StatusMessage":
        text = design.text(key, **params)
        reply = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) \
            if reply_to else None
        msg = await bot.send_message(chat_id, text, reply_parameters=reply)
        status = cls(bot, design, chat_id, msg.message_id)
        status._shown = text
        await status._swap_sticker(key)
        return status

    # ---- screens -----------------------------------------------------------

    async def show(self, key: str, markup: InlineKeyboardMarkup | None = None, /,
                   *, suffix: str = "", **params: Any) -> None:
        """Switch to a screen: its text (with prefix/banner) and its sticker."""
        await self.set(self.prefix + self.design.text(key, **params) + suffix, markup)
        await self._swap_sticker(key)

    async def set(self, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        """Edit the message right away."""
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
        except TelegramRetryAfter:
            pass
        except TelegramAPIError:  # "message is not modified", deleted message, ...
            pass

    async def _swap_sticker(self, key: str) -> None:
        wanted = self.design.sticker(key)
        if wanted == self._sticker_file:
            return
        await self._delete_sticker()
        if wanted:
            try:
                msg = await self.bot.send_sticker(self.chat_id, wanted)
                self._sticker_file, self._sticker_msg = wanted, msg.message_id
            except TelegramAPIError:
                pass

    async def _delete_sticker(self) -> None:
        if self._sticker_msg:
            with contextlib.suppress(TelegramAPIError):
                await self.bot.delete_message(self.chat_id, self._sticker_msg)
        self._sticker_file = self._sticker_msg = None

    # ---- progress ----------------------------------------------------------

    async def start_progress(self, key: str = "downloading") -> None:
        self._header = self.prefix + self.design.text(key)
        await self.show(key)
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    def report(self, downloaded: int, total: int | None, speed: float | None) -> None:
        """Thread-safe: called from yt-dlp's progress hook."""
        speed_text = f"{format_size(speed)}/s" if speed else "—"
        if total:
            frac = min(downloaded / total, 1.0)
            body = self.design.text("progress", bar=progress_bar(frac),
                                    percent=f"{frac * 100:.0f}", done=format_size(downloaded),
                                    total=format_size(total), speed=speed_text)
        else:
            body = self.design.text("progress_unknown", done=format_size(downloaded),
                                    speed=speed_text)
        self._pending = f"{self._header}\n{body}"

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            if self._pending:
                await self.set(self._pending)  # no-op when unchanged

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._pending = None

    async def delete(self) -> None:
        await self.stop()
        await self._delete_sticker()
        with contextlib.suppress(TelegramAPIError):
            await self.bot.delete_message(self.chat_id, self.message_id)
