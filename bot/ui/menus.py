"""Builders for the keyboards of built-in screens."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from ..config import Channel
from .design import Btn, Design


def start_keyboard(design: Design, bot_username: str) -> InlineKeyboardMarkup | None:
    return design.keyboard("start", {
        "help": Btn(callback="pg|help"),
        "add_group": Btn(url=f"https://t.me/{bot_username}?startgroup=true"),
    })


def help_keyboard(design: Design) -> InlineKeyboardMarkup | None:
    return design.keyboard("help", {"back": Btn(callback="pg|start")})


def page_keyboard(design: Design, pid: str) -> InlineKeyboardMarkup | None:
    return design.keyboard(f"page:{pid}", {"back": Btn(callback="pg|start")})


def join_keyboard(design: Design, channels: tuple[Channel, ...]) -> InlineKeyboardMarkup | None:
    return design.keyboard(
        "join", {"check": Btn(callback="check_join")},
        multi={"channels": [Btn(url=c.link, params={"n": str(i)})
                            for i, c in enumerate(channels, 1)]},
    )


def media_keyboard(design: Design) -> InlineKeyboardMarkup | None:
    return design.keyboard("media")
