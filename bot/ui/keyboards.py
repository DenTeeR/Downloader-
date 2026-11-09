"""Default buttons and layouts of every keyboard. Admins can change each
button's label, color, premium-emoji icon, position and visibility, and add
their own link buttons or buttons that open custom pages."""
from __future__ import annotations

from .specs import ButtonSpec, KeyboardSpec

QUALITY_NAMES = {2160: "2160p 4K", 1440: "1440p 2K", 1080: "1080p FHD", 720: "720p HD",
                 480: "480p", 360: "360p", 240: "240p"}


def _quality_buttons() -> dict[str, ButtonSpec]:
    return {
        f"q{h}": ButtonSpec(f"q{h}", f"کیفیت {name}", "🎬 {quality} • {size}{warn}",
                            placeholders=("quality", "size", "warn"))
        for h, name in QUALITY_NAMES.items()
    }


_QUALITY_SAMPLE = {f"q{h}": {"quality": name, "size": f"{h // 20}.0 MB", "warn": ""}
                   for h, name in QUALITY_NAMES.items()}

_SPECS = [
    KeyboardSpec(
        "start", "دکمه‌های صفحه شروع", screen="start",
        buttons={
            "help": ButtonSpec("help", "راهنما", "📖 راهنما", style="primary"),
            "add_group": ButtonSpec("add_group", "افزودن به گروه", "➕ افزودن ربات به گروه"),
        },
        layout=(("help",), ("add_group",)),
    ),
    KeyboardSpec(
        "help", "دکمه‌های صفحه راهنما", screen="help",
        buttons={"back": ButtonSpec("back", "بازگشت", "🔙 بازگشت")},
        layout=(("back",),),
    ),
    KeyboardSpec(
        "join", "دکمه‌های عضویت اجباری", screen="join_required",
        buttons={
            "channels": ButtonSpec("channels", "دکمه کانال‌ها", "📢 عضویت در کانال {n}",
                                   placeholders=("n",)),
            "check": ButtonSpec("check", "عضو شدم", "✅ عضو شدم", style="success"),
        },
        multi=("channels",),
        layout=(("channels",), ("check",)),
        sample={"channels": {"n": "1"}},
    ),
    KeyboardSpec(
        "youtube", "دکمه‌های منوی یوتیوب", screen="yt_menu",
        buttons={
            **_quality_buttons(),
            "audio": ButtonSpec("audio", "فقط صدا (MP3)", "🎵 فقط صدا (MP3) • {size}",
                                style="primary", placeholders=("size",)),
            "thumb": ButtonSpec("thumb", "کاور ویدیو", "🖼 کاور ویدیو"),
            "cancel": ButtonSpec("cancel", "لغو", "❌ لغو", style="danger"),
        },
        layout=(("q2160", "q1440"), ("q1080", "q720"), ("q480", "q360"), ("q240",),
                ("audio",), ("thumb", "cancel")),
        sample={**_QUALITY_SAMPLE, "audio": {"size": "3.2 MB"}},
    ),
    KeyboardSpec(
        "media", "دکمه‌های زیر فایل‌های ارسالی", buttons={}, layout=(),
    ),
]

KEYBOARDS: dict[str, KeyboardSpec] = {spec.key: spec for spec in _SPECS}

# Buttons of custom pages (created by admins) — only a back button is built in.
PAGE_BUTTONS = {"back": ButtonSpec("back", "بازگشت", "🔙 بازگشت")}
