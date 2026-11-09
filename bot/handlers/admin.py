"""Admin panel: statistics, broadcast, ban/unban. Only for ADMIN_IDS.
The design studio and the cookie manager live in design.py / cookies.py."""
from __future__ import annotations

import asyncio
import logging

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import Config
from ..database import Database
from ..platforms import PLATFORM_LABELS, Platform
from ..utils import fa

log = logging.getLogger(__name__)
router = Router(name="admin")


class AdminOnly(BaseMiddleware):
    """Silently ignore admin routes for everyone else."""

    async def __call__(self, handler, event, data):  # type: ignore[override]
        user = data.get("event_from_user")
        config: Config = data["config"]
        if user is None or user.id not in config.admin_ids:
            return None
        return await handler(event, data)


def admin_router(name: str) -> Router:
    r = Router(name=name)
    r.message.middleware(AdminOnly())
    r.callback_query.middleware(AdminOnly())
    return r


router = admin_router("admin")


class Broadcast(StatesGroup):
    waiting_message = State()


def button(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button("📊 آمار", "admin|stats"), button("📢 ارسال همگانی", "admin|broadcast")],
        [button("🎨 طراحی ربات (متن، استیکر، دکمه)", "ds|home", "primary")],
        [button("🍪 کوکی‌ها (اینستاگرام / یوتیوب)", "ck|home", "success")],
    ])


PANEL_TEXT = "👨‍💻 <b>پنل مدیریت</b>\nیکی از گزینه‌ها را انتخاب کنید:"
STATS_TEXT = (
    "📊 <b>آمار ربات</b>\n\n"
    "👥 کل کاربران: <b>{users}</b>\n"
    "🆕 کاربران جدید امروز: <b>{users_today}</b>\n"
    "🔥 کاربران فعال امروز: <b>{active_today}</b>\n"
    "⛔️ مسدود شده: <b>{banned}</b>\n\n"
    "📥 کل دانلودها: <b>{downloads}</b>\n"
    "📅 دانلودهای امروز: <b>{downloads_today}</b>\n"
    "❌ دانلودهای ناموفق: <b>{failed}</b>\n"
    "{per_platform}"
)


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(PANEL_TEXT, reply_markup=panel_keyboard())


@router.callback_query(F.data == "admin|home")
async def back_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(PANEL_TEXT, reply_markup=panel_keyboard())
        except TelegramAPIError:
            await callback.message.answer(PANEL_TEXT, reply_markup=panel_keyboard())


@router.callback_query(F.data == "admin|stats")
async def show_stats(callback: CallbackQuery, db: Database) -> None:
    stats = await db.stats()
    lines = []
    for platform, count in stats.pop("per_platform"):
        try:
            name = PLATFORM_LABELS[Platform(platform)]
        except ValueError:
            name = platform
        lines.append(f"▫️ {name}: <b>{fa(count)}</b>")
    per_platform = ("\n📈 <b>به تفکیک پلتفرم:</b>\n" + "\n".join(lines)) if lines else ""
    text = STATS_TEXT.format(**{k: fa(v) for k, v in stats.items()}, per_platform=per_platform)
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=panel_keyboard())


@router.callback_query(F.data == "admin|broadcast")
async def ask_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Broadcast.waiting_message)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "📢 پیام مورد نظر برای ارسال همگانی را بفرستید (متن، عکس، ویدیو و ...).\n"
            "برای لغو /cancel را بزنید.")


@router.message(Command("cancel"), StateFilter("*"))
async def cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is not None:
        await state.clear()
        await message.answer("❌ لغو شد.", reply_markup=panel_keyboard())


@router.message(Broadcast.waiting_message)
async def do_broadcast(message: Message, bot: Bot, db: Database, state: FSMContext) -> None:
    await state.clear()
    user_ids = await db.all_user_ids()
    status = await message.answer(f"📤 ارسال به {fa(len(user_ids))} کاربر شروع شد...")
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
        await status.edit_text(
            "✅ ارسال همگانی تمام شد.\n\n"
            f"✔️ موفق: <b>{fa(ok)}</b>\n"
            f"🚫 ربات را بلاک کرده‌اند: <b>{fa(blocked)}</b>\n"
            f"❌ خطا: <b>{fa(failed)}</b>")
    except TelegramAPIError:
        log.exception("Could not report broadcast result")


@router.message(Command("ban", "unban"))
async def ban_user(message: Message, command: CommandObject, db: Database) -> None:
    arg = (command.args or "").strip()
    if not arg.lstrip("-").isdigit():
        await message.answer("استفاده: <code>/ban 123456789</code> یا <code>/unban 123456789</code>")
        return
    user_id = int(arg)
    banned = command.command == "ban"
    if not await db.set_banned(user_id, banned):
        await message.answer("❌ کاربری با این شناسه پیدا نشد.")
        return
    await message.answer(f"✅ کاربر <code>{user_id}</code> {'مسدود' if banned else 'آزاد'} شد.")
