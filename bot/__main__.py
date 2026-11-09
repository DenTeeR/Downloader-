"""Entry point: python -m bot"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import PRODUCTION, TelegramAPIServer
from aiogram.enums import ParseMode

from .commands import set_commands
from .config import load_config
from .database import Database
from .handlers import setup_routers
from .middlewares import ForceJoinMiddleware, UserMiddleware
from .services.downloader import Downloader
from .ui import Design
from .ui.fallback import PremiumEmojiFallback

log = logging.getLogger("bot")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()

    db = Database(config.database_path)
    await db.connect()
    design = Design(db)
    await design.load()

    downloader = Downloader(config)
    downloader.cleanup_all()  # leftovers from a previous run

    api = (TelegramAPIServer.from_base(config.bot_api_server, is_local=True)
           if config.bot_api_server else PRODUCTION)
    # Long timeout: uploading big videos can take minutes.
    session = AiohttpSession(api=api, proxy=config.proxy, timeout=900)
    session.middleware(PremiumEmojiFallback())
    bot = Bot(
        token=config.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    me = await bot.get_me()

    force_join = ForceJoinMiddleware(config)
    dp = Dispatcher(
        config=config, db=db, design=design, downloader=downloader,
        force_join=force_join, bot_username=me.username,
    )
    user_mw = UserMiddleware(db)
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(user_mw)
        observer.outer_middleware(force_join)
    dp.include_router(setup_routers())

    await set_commands(bot, design)

    log.info("Bot @%s started (max file size %d MB, API: %s)", me.username,
             config.max_file_size // (1024 * 1024), config.bot_api_server or "cloud")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code not in (None, 0):
            raise
