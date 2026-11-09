"""Admin panel: statistics, broadcast, ban/unban. Only for ADMIN_IDS."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramAPIError
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards, texts
from ..config import Config
from ..database import Database
from ..platforms import PLATFORM_LABELS, Platform
from ..utils import esc, fa

log = logging.getLogger(__name__)
router = Router(name="admin")


class Broadcast(StatesGroup):
    waiting_message = State()


def is_admin(config: Config, user_id: int | None) -> bool:
    return user_id is not None and user_id in config.admin_ids


@router.message(Command("admin"))
async def cmd_admin(message: Message, config: Config) -> None:
    if not is_admin(config, message.from_user and message.from_user.id):
        return
    await message.answer(texts.ADMIN_PANEL, reply_markup=keyboards.admin_panel())


@router.callback_query(F.data == "admin|stats")
async def show_stats(callback: CallbackQuery, config: Config, db: Database) -> None:
    if not is_admin(config, callback.from_user.id):
        return
    stats = await db.stats()
    lines = []
    for platform, count in stats.pop("per_platform"):
        try:
            name = PLATFORM_LABELS[Platform(platform)]
        except ValueError:
            name = platform
        lines.append(f"▫️ {name}: <b>{fa(count)}</b>")
    per_platform = ("\n📈 <b>به تفکیک پلتفرم:</b>\n" + "\n".join(lines)) if lines else ""
    text = texts.ADMIN_STATS.format(**{k: fa(v) for k, v in stats.items()},
                                    per_platform=per_platform)
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(text, reply_markup=keyboards.admin_panel())


@router.callback_query(F.data == "admin|broadcast")
async def ask_broadcast(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    if not is_admin(config, callback.from_user.id):
        return
    await state.set_state(Broadcast.waiting_message)
    await callback.answer()
    if callback.message:
        await callback.message.answer(texts.BROADCAST_ASK)


@router.message(Command("cancel"), StateFilter("*"))
async def cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is not None:
        await state.clear()
        await message.answer(texts.CANCELLED)


@router.message(Broadcast.waiting_message)
async def do_broadcast(message: Message, bot: Bot, config: Config, db: Database,
                       state: FSMContext) -> None:
    if not is_admin(config, message.from_user and message.from_user.id):
        return
    await state.clear()
    user_ids = await db.all_user_ids()
    status = await message.answer(texts.BROADCAST_START.format(count=fa(len(user_ids))))
    # Run in the background so the bot keeps answering other users meanwhile.
    asyncio.create_task(_broadcast(bot, message, user_ids, status))


async def _broadcast(bot: Bot, source: Message, user_ids: list[int], status: Message) -> None:
    ok = blocked = failed = 0
    for user_id in user_ids:
        for _ in range(2):
            try:
                await bot.copy_message(user_id, source.chat.id, source.message_id)
                ok += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
                continue
            except TelegramForbiddenError:
                blocked += 1
            except TelegramAPIError:
                failed += 1
            break
        await asyncio.sleep(0.05)  # stay under ~20 messages/second
    try:
        await status.edit_text(texts.BROADCAST_DONE.format(
            ok=fa(ok), blocked=fa(blocked), failed=fa(failed)))
    except TelegramAPIError:
        log.exception("Could not report broadcast result")


@router.message(Command("ban", "unban"))
async def ban_user(message: Message, command: CommandObject, config: Config,
                   db: Database) -> None:
    if not is_admin(config, message.from_user and message.from_user.id):
        return
    arg = (command.args or "").strip()
    if not arg.lstrip("-").isdigit():
        await message.answer(texts.BAN_USAGE)
        return
    user_id = int(arg)
    banned = command.command == "ban"
    if not await db.set_banned(user_id, banned):
        await message.answer(texts.USER_NOT_FOUND)
        return
    template = texts.BAN_OK if banned else texts.UNBAN_OK
    await message.answer(template.format(user_id=esc(user_id)))
