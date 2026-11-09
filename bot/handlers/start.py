from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..config import Config
from ..middlewares import ForceJoinMiddleware
from ..utils import esc, fa, format_size

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    name = esc(message.from_user.first_name if message.from_user else "")
    await message.answer(texts.START.format(name=name))


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config) -> None:
    await message.answer(texts.HELP.format(
        max_size=format_size(config.max_file_size), max_items=fa(config.max_playlist_items),
    ))


@router.callback_query(F.data == "check_join")
async def check_join(callback: CallbackQuery, bot: Bot,
                     force_join: ForceJoinMiddleware) -> None:
    if await force_join.is_member(bot, callback.from_user.id, use_cache=False):
        await callback.answer("✅")
        if callback.message:
            await callback.message.edit_text(texts.JOIN_OK)
    else:
        await callback.answer(texts.JOIN_NOT_YET, show_alert=True)
