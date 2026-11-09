"""Middlewares: user tracking/ban check and mandatory channel membership."""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from .config import Config
from .database import Database
from .ui import Design
from .ui.menus import join_keyboard
from .ui.screens import send_screen

log = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class UserMiddleware(BaseMiddleware):
    """Saves users to the database (at most once a minute each) and drops banned users."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._seen: dict[int, float] = {}

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)

        now = time.monotonic()
        if now - self._seen.get(user.id, 0) > 60:
            self._seen[user.id] = now
            await self.db.touch_user(user.id, user.username, user.first_name)

        if await self.db.is_banned(user.id):
            design: Design = data["design"]
            if isinstance(event, Message) and event.chat.type == ChatType.PRIVATE:
                await send_screen(data["bot"], event.chat.id, design, "banned")
            elif isinstance(event, CallbackQuery):
                await event.answer()
            return None
        return await handler(event, data)


class ForceJoinMiddleware(BaseMiddleware):
    """Blocks the bot until the user has joined every channel in FORCE_JOIN_CHANNELS."""

    OK_STATUSES = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
                   ChatMemberStatus.CREATOR}
    CACHE_SECONDS = 600

    def __init__(self, config: Config) -> None:
        self.config = config
        self._ok_until: dict[int, float] = {}

    async def is_member(self, bot: Bot, user_id: int, *, use_cache: bool = True) -> bool:
        if not self.config.force_join_channels or user_id in self.config.admin_ids:
            return True
        if use_cache and self._ok_until.get(user_id, 0) > time.monotonic():
            return True
        for channel in self.config.force_join_channels:
            try:
                member = await bot.get_chat_member(channel.chat_id, user_id)
            except TelegramAPIError as exc:
                # Usually: the bot is not an admin of that channel. Don't lock users out.
                log.warning("Cannot check membership in %s: %s", channel.chat_id, exc)
                continue
            joined = member.status in self.OK_STATUSES or (
                member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False)
            )
            if not joined:
                return False
        self._ok_until[user_id] = time.monotonic() + self.CACHE_SECONDS
        return True

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        bot: Bot = data["bot"]
        if user is None or not self.config.force_join_channels:
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data == "check_join":
            return await handler(event, data)
        # Only enforce in private chats; in groups just stay quiet.
        chat = data.get("event_chat")
        if chat is not None and chat.type != ChatType.PRIVATE:
            return await handler(event, data)

        if await self.is_member(bot, user.id):
            return await handler(event, data)

        design: Design = data["design"]
        markup = join_keyboard(design, self.config.force_join_channels)
        if isinstance(event, CallbackQuery):
            await event.answer(design.text("join_not_yet"), show_alert=True)
        target = event.chat.id if isinstance(event, Message) else user.id
        await send_screen(bot, target, design, "join_required", keyboard=markup)
        return None
