"""Static descriptions of the screens and keyboards that admins can redesign."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TextSpec:
    key: str
    title: str                      # shown to admins in the design menu
    default: str                    # HTML (or plain text when plain=True)
    category: str
    placeholders: tuple[str, ...] = ()
    plain: bool = False             # alerts / commands: no HTML, no premium emoji
    sample: dict[str, str] = field(default_factory=dict)  # values for previews


@dataclass(frozen=True)
class ButtonSpec:
    key: str
    title: str                      # shown to admins
    default: str                    # label template
    style: str | None = None        # default color: primary | success | danger
    placeholders: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeyboardSpec:
    key: str
    title: str
    buttons: dict[str, ButtonSpec]
    layout: tuple[tuple[str, ...], ...]   # default rows of button keys
    multi: tuple[str, ...] = ()           # keys that expand into several buttons
    screen: str | None = None             # text key this keyboard belongs to
    sample: dict[str, dict[str, str]] = field(default_factory=dict)


STYLES = {
    "default": ("⚪️ پیش‌فرض", None),
    "primary": ("🔵 آبی", "primary"),
    "success": ("🟢 سبز", "success"),
    "danger": ("🔴 قرمز", "danger"),
}
