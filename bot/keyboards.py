"""Inline keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import Channel
from .utils import format_size

QUALITY_NAMES = {144: "144p", 240: "240p", 360: "360p", 480: "480p", 720: "720p HD",
                 1080: "1080p FHD", 1440: "1440p 2K", 2160: "2160p 4K"}


def join_channels(channels: tuple[Channel, ...]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, channel in enumerate(channels, 1):
        kb.row(InlineKeyboardButton(text=f"📢 عضویت در کانال {i}", url=channel.link))
    kb.row(InlineKeyboardButton(text="✅ عضو شدم", callback_data="check_join"))
    return kb.as_markup()


def youtube_menu(token: str, qualities: list[tuple[int, int | None]],
                 audio_size: int | None, limit: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for height, size in qualities:
        if height < 240:
            continue
        mark = " ⛔️" if size and size > limit else ""
        label = f"🎬 {QUALITY_NAMES.get(height, f'{height}p')} • {format_size(size)}{mark}"
        kb.button(text=label, callback_data=f"yt|{token}|v{height}")
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text=f"🎵 فقط صدا (MP3) • {format_size(audio_size)}",
                                callback_data=f"yt|{token}|a"))
    kb.row(
        InlineKeyboardButton(text="🖼 کاور ویدیو", callback_data=f"yt|{token}|t"),
        InlineKeyboardButton(text="❌ لغو", callback_data=f"yt|{token}|x"),
    )
    return kb.as_markup()


def admin_panel() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📊 آمار", callback_data="admin|stats"))
    kb.row(InlineKeyboardButton(text="📢 ارسال همگانی", callback_data="admin|broadcast"))
    return kb.as_markup()
