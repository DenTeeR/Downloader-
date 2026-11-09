from aiogram import Bot
from aiogram.types import BotCommand

from .ui import Design


async def set_commands(bot: Bot, design: Design) -> None:
    """The /start and /help entries of Telegram's command menu (designable texts)."""
    await bot.set_my_commands([
        BotCommand(command="start", description=design.text("cmd_start")[:256] or "start"),
        BotCommand(command="help", description=design.text("cmd_help")[:256] or "help"),
    ])
