"""🍪 Cookie manager (admins only).

Instagram (and often YouTube) refuse downloads from server IPs unless the
request comes from a logged-in account. The admin exports the cookies of an
account from a browser and sends the file here; no server access is needed."""
from __future__ import annotations

import html
import io
import time

from aiogram import Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..config import Config
from ..services.cookies import CookieError, parse_cookies
from .admin import admin_router, button
from .design import show

router = admin_router("cookies")

PLATFORMS = {"instagram": "📸 اینستاگرام", "youtube": "▶️ یوتیوب",
             "pinterest": "📌 پینترست", "soundcloud": "☁️ ساندکلود"}
NEEDED = {"instagram": "تقریبا همیشه لازم است", "youtube": "اگر یوتیوب خطا داد لازم است",
          "pinterest": "معمولا لازم نیست", "soundcloud": "معمولا لازم نیست"}

GUIDE = (
    "❓ <b>آموزش تهیه کوکی (فقط چند دقیقه)</b>\n\n"
    "کوکی یعنی «ورود به حساب». ربات با آن مثل یک کاربر واردشده دانلود می‌کند.\n"
    "⚠️ حتما از یک <b>حساب فرعی</b> استفاده کنید، نه حساب اصلی خودتان.\n\n"
    "💻 <b>با کامپیوتر (کروم یا فایرفاکس):</b>\n"
    "1️⃣ افزونه <b>Get cookies.txt LOCALLY</b> را نصب کنید.\n"
    "2️⃣ به instagram.com (یا youtube.com) بروید و وارد حساب شوید.\n"
    "3️⃣ روی آیکن افزونه بزنید و <b>Export</b> را بزنید.\n"
    "4️⃣ فایل دانلود شده را همینجا برای ربات بفرستید.\n\n"
    "📱 <b>با گوشی اندروید:</b>\n"
    "1️⃣ مرورگر <b>Firefox</b> را نصب کنید و از بخش Add-ons افزونه <b>Cookie-Editor</b> را اضافه کنید.\n"
    "2️⃣ در فایرفاکس وارد instagram.com شوید و وارد حساب شوید.\n"
    "3️⃣ از منوی فایرفاکس، Cookie-Editor را باز کنید ← <b>Export</b> ← <b>JSON</b> "
    "(در کلیپ‌بورد کپی می‌شود).\n"
    "4️⃣ متن کپی شده را همینجا برای ربات بفرستید (Paste).\n\n"
    "✅ ربات خودش فرمت را تشخیص می‌دهد و فقط کوکی‌های همان سایت را نگه می‌دارد.\n"
    "🔄 اگر بعدا دوباره خطا آمد، کوکی منقضی شده؛ همین کار را تکرار کنید. "
    "ربات خودش به ادمین‌ها خبر می‌دهد."
)


class CookieForm(StatesGroup):
    upload = State()


def status_view(config: Config) -> tuple[str, InlineKeyboardMarkup]:
    lines = ["🍪 <b>کوکی‌ها</b>\n",
             "برای دانلود از اینستاگرام (و گاهی یوتیوب) ربات باید با یک حساب وارد شود.\n"]
    rows = []
    for platform, name in PLATFORMS.items():
        path = config.cookies_for(platform)
        if path:
            age = int((time.time() - path.stat().st_mtime) / 86400)
            state = f"✅ تنظیم شده ({age} روز پیش)"
        else:
            state = "➖ ندارد"
        lines.append(f"{name}: {state}\n   <i>{NEEDED[platform]}</i>")
        row = [button(f"📤 ارسال کوکی {name.split(' ', 1)[1]}", f"ck|up|{platform}",
                      "success" if platform in ("instagram", "youtube") else None)]
        if path:
            row.append(button("🗑", f"ck|del|{platform}", "danger"))
        rows.append(row)
    rows.append([button("❓ آموزش تهیه کوکی", "ck|help", "primary")])
    rows.append([button("🔙 بازگشت", "admin|home")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("ck|"))
async def on_cookies(callback: CallbackQuery, config: Config, state: FSMContext) -> None:
    parts = (callback.data or "").split("|")
    action = parts[1]
    await callback.answer()
    if action == "home":
        await state.clear()
        await show(callback, *status_view(config))
    elif action == "help":
        await show(callback, GUIDE, InlineKeyboardMarkup(inline_keyboard=[
            [button("🔙 بازگشت", "ck|home")]]))
    elif action == "up" and parts[2] in PLATFORMS:
        await state.set_state(CookieForm.upload)
        await state.update_data(platform=parts[2])
        await callback.message.answer(
            f"📤 کوکی {PLATFORMS[parts[2]]} را بفرستید:\n"
            "• فایل cookies.txt یا فایل JSON\n"
            "• یا متن کپی شده از Cookie-Editor را Paste کنید\n\n"
            "آموزش: دکمه «❓ آموزش تهیه کوکی» در منوی کوکی‌ها.\n↩️ لغو: /cancel")
    elif action == "del" and parts[2] in PLATFORMS:
        if path := config.cookies_for(parts[2]):
            path.unlink(missing_ok=True)
        await show(callback, *status_view(config))


@router.message(CookieForm.upload)
async def got_cookies(message: Message, bot: Bot, config: Config, state: FSMContext) -> None:
    platform = (await state.get_data())["platform"]
    if message.document:
        if (message.document.file_size or 0) > 2 * 1024 * 1024:
            await message.answer("⚠️ فایل خیلی بزرگ است.")
            return
        buffer = io.BytesIO()
        await bot.download(message.document, destination=buffer)
        raw = buffer.getvalue().decode("utf-8", errors="replace")
    elif message.text:
        raw = message.text
    else:
        await message.answer("⚠️ فایل یا متن کوکی را بفرستید. لغو: /cancel")
        return
    try:
        parsed = parse_cookies(raw, platform)
    except CookieError as exc:
        await message.answer(f"❌ {html.escape(str(exc))}\nدوباره بفرستید یا /cancel")
        return
    config.cookies_dir.mkdir(parents=True, exist_ok=True)
    (config.cookies_dir / f"{platform}.txt").write_text(parsed.text, encoding="utf-8")
    await state.clear()
    # The pasted cookies are a login secret: remove them from the chat.
    if message.text:
        try:
            await message.delete()
        except Exception:
            pass
    note = ("✅ ورود به حساب پیدا شد." if parsed.has_session else
            "⚠️ کوکی ورود (session) پیدا نشد؛ احتمالا هنگام خروجی گرفتن وارد حساب نبودید.")
    await message.answer(f"✅ {parsed.count} کوکی {PLATFORMS[platform]} ذخیره شد.\n{note}\n\n"
                         "حالا یک لینک بفرستید تا تست کنید.")
    await show(message, *status_view(config))
