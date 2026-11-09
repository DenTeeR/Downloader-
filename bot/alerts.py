"""Tell admins when a site needs (new) cookies, at most once an hour per site."""
from __future__ import annotations

import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import Config

log = logging.getLogger(__name__)

COOKIE_ERRORS = {"err_ig_login": "instagram", "err_yt_login": "youtube",
                 "err_yt_blocked": "youtube"}
NAMES = {"instagram": "اینستاگرام", "youtube": "یوتیوب"}
_last_alert: dict[str, float] = {}


async def maybe_alert_cookies(bot: Bot, config: Config, error_key: str) -> None:
    platform = COOKIE_ERRORS.get(error_key)
    if not platform or not config.admin_ids:
        return
    if time.monotonic() - _last_alert.get(platform, -1e9) < 3600:
        return
    _last_alert[platform] = time.monotonic()
    has = config.cookies_for(platform) is not None
    name = NAMES[platform]
    text = (
        f"🔔 <b>هشدار {name}</b>\n\n"
        + (f"کوکی {name} احتمالا منقضی شده است. " if has else f"ربات هنوز کوکی {name} ندارد. ")
        + f"{name} اجازه دانلود از سرور را نمی‌دهد و کاربران خطا می‌گیرند.\n\n"
        "👇 برای رفع مشکل، فایل کوکی یک حساب را برای ربات بفرستید (آموزش داخل همین بخش است)."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"🍪 ارسال کوکی {name}", callback_data=f"ck|up|{platform}",
                             style="success"),
    ], [InlineKeyboardButton(text="❓ آموزش", callback_data="ck|help")]])
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=markup)
        except TelegramAPIError as exc:
            log.warning("Could not alert admin %s: %s", admin_id, exc)
