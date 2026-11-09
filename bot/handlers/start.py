"""/start, /help, menu navigation (help and custom pages) and the join check."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from ..config import Config
from ..middlewares import ForceJoinMiddleware
from ..ui import Design
from ..ui.menus import help_keyboard, page_keyboard, start_keyboard
from ..ui.screens import edit_screen, send_screen
from ..utils import fa, format_size

router = Router(name="start")


def _help_params(config: Config) -> dict[str, str]:
    return {"max_size": format_size(config.max_file_size),
            "max_items": fa(config.max_playlist_items)}


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, design: Design, bot_username: str) -> None:
    name = message.from_user.first_name if message.from_user else ""
    await send_screen(bot, message.chat.id, design, "start",
                      keyboard=start_keyboard(design, bot_username), name=name, bot=bot_username)


@router.message(Command("help"))
async def cmd_help(message: Message, bot: Bot, config: Config, design: Design) -> None:
    await send_screen(bot, message.chat.id, design, "help",
                      keyboard=help_keyboard(design), **_help_params(config))


@router.callback_query(F.data.startswith("pg|"))
async def navigate(callback: CallbackQuery, config: Config, design: Design,
                   bot_username: str) -> None:
    """Buttons that open another screen inside the same message."""
    target = (callback.data or "").split("|", 1)[1]
    await callback.answer()
    message = callback.message
    if not isinstance(message, Message):
        return
    name = callback.from_user.first_name
    if target == "start":
        await edit_screen(message, design, "start", keyboard=start_keyboard(design, bot_username),
                          name=name, bot=bot_username)
    elif target == "help":
        await edit_screen(message, design, "help", keyboard=help_keyboard(design),
                          **_help_params(config))
    elif target in design.pages():
        await edit_screen(message, design, f"page:{target}",
                          keyboard=page_keyboard(design, target), name=name)


@router.callback_query(F.data.startswith("noop"))
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "check_join")
async def check_join(callback: CallbackQuery, bot: Bot, design: Design,
                     force_join: ForceJoinMiddleware) -> None:
    if await force_join.is_member(bot, callback.from_user.id, use_cache=False):
        await callback.answer("✅")
        if isinstance(callback.message, Message):
            await edit_screen(callback.message, design, "join_ok", sticker=True)
    else:
        await callback.answer(design.text("join_not_yet"), show_alert=True)
