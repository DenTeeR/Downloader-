"""Sending designed screens: optional sticker, then the text with its keyboard."""
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, Message, ReplyParameters

from .design import Design

log = logging.getLogger(__name__)


async def send_screen(bot: Bot, chat_id: int, design: Design, key: str, /, *,
                      keyboard: InlineKeyboardMarkup | None = None,
                      reply_to: int | None = None, **params: Any) -> Message:
    reply = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) \
        if reply_to else None
    if sticker := design.sticker(key):
        try:
            await bot.send_sticker(chat_id, sticker, reply_parameters=reply)
            reply = None  # the text follows the sticker directly
        except TelegramAPIError as exc:
            log.warning("Sticker of screen %s could not be sent: %s", key, exc)
    return await bot.send_message(chat_id, design.text(key, **params),
                                  reply_markup=keyboard, reply_parameters=reply)


async def edit_screen(message: Message, design: Design, key: str, /, *,
                      keyboard: InlineKeyboardMarkup | None = None, sticker: bool = False,
                      **params: Any) -> None:
    """Show another screen in the same message (menu navigation). Stickers are
    skipped unless asked for, so going back and forth doesn't spam them."""
    text = design.text(key, **params)
    if sticker and (file_id := design.sticker(key)):
        try:
            await message.answer_sticker(file_id)
        except TelegramAPIError as exc:
            log.warning("Sticker of screen %s could not be sent: %s", key, exc)
    try:
        if message.text is not None:
            await message.edit_text(text, reply_markup=keyboard)
            return
    except TelegramAPIError:
        pass
    await message.answer(text, reply_markup=keyboard)
