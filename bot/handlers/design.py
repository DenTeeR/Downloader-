"""🎨 Design studio (admins only): redesign every screen of the bot from Telegram.

* Texts: send a new message with any formatting and premium emoji; it is saved as is.
* Stickers: each screen can show a sticker (normal, animated or video).
* Buttons: label, color (blue / green / red), premium-emoji icon, position,
  width (alone on a row = full width), visibility, plus custom link buttons and
  buttons that open custom pages.
* Layout: also editable as text (one line per row).
* Export / import the whole design as a JSON file, or reset it.
"""
from __future__ import annotations

import html
import io
import logging

from aiogram import Bot, F
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from ..commands import set_commands
from ..ui import Design
from ..ui.design import MAX_ROW, DesignError
from ..ui.specs import STYLES
from ..ui.texts import CATEGORIES, TEXTS
from .admin import admin_router, button

log = logging.getLogger(__name__)
router = admin_router("design")

PLACEHOLDER_HELP = {
    "name": "نام کاربر", "bot": "یوزرنیم ربات", "max_size": "حداکثر حجم فایل",
    "max_items": "حداکثر تعداد پلی‌لیست", "bar": "نوار پیشرفت", "percent": "درصد",
    "done": "حجم دانلود شده", "total": "حجم کل", "speed": "سرعت", "index": "شماره",
    "title": "عنوان", "count": "تعداد", "ok": "تعداد موفق", "error": "متن خطا",
    "item": "نام آیتم", "channel": "نام کانال", "duration": "مدت زمان", "quality": "کیفیت",
    "size": "حجم", "limit": "حداکثر حجم مجاز", "warn": "علامت ⛔️ برای حجم زیاد",
    "n": "شماره کانال",
}
# Screens that are not a message of their own, so a sticker would never show.
NO_STICKER = {"media_caption", "media_caption_notitle", "progress", "progress_unknown",
              "item_label", "playlist_header", "playlist_truncated", "playlist_item_failed",
              "yt_thumb_caption"}
REQUIRED = {("join", "check"), ("join", "channels")}
CANCEL_HINT = "\n\n↩️ لغو: /cancel"


class DesignForm(StatesGroup):
    text = State()
    sticker = State()
    btn_text = State()
    btn_icon = State()
    btn_url = State()
    layout = State()
    link_text = State()
    link_url = State()
    page_btn_text = State()
    page_title = State()
    import_file = State()


# --------------------------------------------------------------------------- #
#  helpers                                                                     #
# --------------------------------------------------------------------------- #

def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def back(data: str, text: str = "🔙 بازگشت") -> list[InlineKeyboardButton]:
    return [button(text, data)]


async def show(target: CallbackQuery | Message, text: str,
               markup: InlineKeyboardMarkup | None, *, fallback: str | None = None) -> None:
    """Edit the admin's menu message (from a button) or send a new one."""
    message = target.message if isinstance(target, CallbackQuery) else None
    for body in (text, fallback):
        if body is None:
            continue
        try:
            if isinstance(message, Message):
                try:
                    await message.edit_text(body, reply_markup=markup)
                    return
                except TelegramBadRequest as exc:
                    if "not modified" in str(exc):
                        return
            chat = target.message.chat.id if isinstance(target, CallbackQuery) else target.chat.id
            await target.bot.send_message(chat, body, reply_markup=markup)
            return
        except TelegramBadRequest:
            continue  # broken preview HTML: retry with the escaped fallback


def has_sticker(design: Design, key: str) -> bool:
    spec = design.text_spec(key)
    return not spec.plain and key not in NO_STICKER and not key.startswith("page:")


def screen_keyboard(design: Design, key: str) -> str | None:
    if key.startswith("page:"):
        return key
    return next((k.key for k in design.keyboards() if k.screen == key), None)


def placeholders_text(names: tuple[str, ...]) -> str:
    if not names:
        return ""
    items = "، ".join(f"<code>{{{n}}}</code> {PLACEHOLDER_HELP.get(n, '')}" for n in names)
    return f"🧩 متغیرها: {items}\n"


# --------------------------------------------------------------------------- #
#  views                                                                       #
# --------------------------------------------------------------------------- #

def home_view() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "🎨 <b>استودیو طراحی ربات</b>\n\n"
        "همه چیزهایی که کاربر می‌بیند اینجا قابل تغییر است:\n"
        "📝 <b>متن‌ها</b> — با بولد، لینک، نقل‌قول و <b>ایموجی پرمیوم</b>\n"
        "🎭 <b>استیکر</b> — برای هر صفحه یک استیکر دلخواه (حتی متحرک)\n"
        "🔘 <b>دکمه‌ها</b> — متن، <b>رنگ</b> (آبی/سبز/قرمز)، ایموجی پرمیوم، <b>جا و اندازه</b>\n"
        "📄 <b>صفحه‌های سفارشی</b> — مثل «درباره ما» یا «پشتیبانی» با دکمه‌های خودشان\n\n"
        "💎 ایموجی پرمیوم فقط وقتی نمایش داده می‌شود که <b>صاحب ربات تلگرام پرمیوم</b> "
        "داشته باشد؛ در غیر این صورت ربات خودکار ایموجی معمولی می‌گذارد."
    )
    markup = kb(
        [button("📝 متن‌ها و استیکرها", "ds|tc", "primary")],
        [button("🔘 دکمه‌ها، رنگ و چیدمان", "ds|kl", "primary")],
        [button("📄 صفحه‌های سفارشی", "ds|pl")],
        [button("📤 خروجی گرفتن", "ds|ex"), button("📥 وارد کردن", "ds|im")],
        [button("♻️ بازگردانی همه به پیش‌فرض", "ds|ra", "danger")],
        back("admin|home"),
    )
    return text, markup


def categories_view() -> tuple[str, InlineKeyboardMarkup]:
    rows = [[button(title, f"ds|tl|{cat}")] for cat, title in CATEGORIES.items()]
    return "📝 <b>متن‌ها و استیکرها</b>\nیک دسته را انتخاب کنید:", kb(*rows, back("ds|home"))


def text_list_view(design: Design, cat: str) -> tuple[str, InlineKeyboardMarkup]:
    rows = []
    for key, spec in TEXTS.items():
        if spec.category != cat:
            continue
        marks = ("✏️" if design.is_custom_text(key) else "") + ("🎭" if design.sticker(key) else "")
        rows.append([button(f"{spec.title} {marks}".strip(), f"ds|t|{key}")])
    text = (f"{CATEGORIES.get(cat, cat)}\n\n"
            "✏️ = متن تغییر کرده    🎭 = استیکر دارد")
    return text, kb(*rows, back("ds|tc"))


def text_view(design: Design, key: str) -> tuple[str, str, InlineKeyboardMarkup]:
    spec = design.text_spec(key)
    sticker_ok = has_sticker(design, key)
    head = [f"📝 <b>{html.escape(spec.title)}</b>",
            f"وضعیت: {'✏️ تغییر یافته' if design.is_custom_text(key) else '⚪️ پیش‌فرض'}"]
    if sticker_ok:
        head.append(f"استیکر: {'✅ دارد' if design.sticker(key) else '➖ ندارد'}")
    if spec.plain:
        head.append("ℹ️ این متن به صورت پیام پاپ‌آپ/ساده نمایش داده می‌شود (بدون فرمت).")
    header = "\n".join(head) + "\n" + placeholders_text(spec.placeholders)
    preview = design.sample_text(key)
    if spec.plain:
        preview = html.escape(preview)
    text = f"{header}━━━━━━━━━━━━\n👁 <b>پیش‌نمایش:</b>\n\n{preview}"
    fallback = f"{header}━━━━━━━━━━━━\n👁 <b>پیش‌نمایش:</b>\n\n{html.escape(preview)}"

    rows = [[button("✏️ ویرایش متن", f"ds|te|{key}", "primary")]]
    if sticker_ok:
        sticker_row = [button("🎭 تنظیم استیکر", f"ds|ts|{key}")]
        if design.sticker(key):
            sticker_row.append(button("🗑 حذف استیکر", f"ds|tsd|{key}", "danger"))
        rows.append(sticker_row)
    rows.append([button("👁 پیش‌نمایش کامل (مثل کاربر)", f"ds|tp|{key}")])
    if kbd := screen_keyboard(design, key):
        rows.append([button("🔘 دکمه‌های این صفحه", f"ds|k|{kbd}")])
    if design.is_custom_text(key):
        rows.append([button("♻️ بازگردانی متن پیش‌فرض", f"ds|tr|{key}", "danger")])
    back_to = f"ds|p|{key[5:]}" if key.startswith("page:") else f"ds|tl|{spec.category}"
    rows.append(back(back_to))
    if len(text) > 4000:
        text = f"{header}\n⚠️ متن طولانی است؛ از «👁 پیش‌نمایش کامل» استفاده کنید."
        fallback = text
    return text, fallback, kb(*rows)


def keyboards_view(design: Design) -> tuple[str, InlineKeyboardMarkup]:
    rows = [[button(spec.title, f"ds|k|{spec.key}")] for spec in design.keyboards()]
    text = ("🔘 <b>دکمه‌ها و چیدمان</b>\n\n"
            "یک کیبورد را انتخاب کنید. در صفحه بعد پیش‌نمایش دکمه‌ها را می‌بینید و با زدن "
            "روی هر دکمه، تنظیماتش (متن، رنگ، ایموجی پرمیوم، جا و اندازه) باز می‌شود.")
    return text, kb(*rows, back("ds|home"))


def _hidden(design: Design, kbd: str) -> list[str]:
    return [b for b in design.all_buttons(kbd) if not design.is_visible(kbd, b)]


def keyboard_view(design: Design, kbd: str) -> tuple[str, InlineKeyboardMarkup]:
    spec = design.keyboard_spec(kbd)
    hidden = _hidden(design, kbd)
    lines = [f"🔘 <b>{html.escape(spec.title)}</b>", "",
             "👇 پیش‌نمایش دکمه‌ها دقیقا مثل چیزی که کاربر می‌بیند.",
             "روی هر دکمه بزنید تا تنظیماتش باز شود.",
             "📏 اندازه: دکمه‌ای که تنها در یک ردیف باشد تمام‌عرض است؛ "
             "هرچه دکمه‌های یک ردیف بیشتر باشند، باریک‌تر می‌شوند."]
    if not design.all_buttons(kbd):
        lines.append("\nℹ️ این بخش هنوز دکمه‌ای ندارد. با «➕ دکمه لینک» اضافه کنید.")
    if spec.key == "media":
        lines.append("\nℹ️ این دکمه‌ها زیر هر فایل ارسالی نمایش داده می‌شوند "
                     "(مثلا لینک کانال شما). آلبوم‌های چند عکسی دکمه نمی‌گیرند.")
    extra = [[button("━━━━━━ ⚙️ تنظیمات ━━━━━━", "noop")]]
    for b in hidden:
        extra.append([button(f"🙈 {design.button_title(kbd, b)} (مخفی)", f"ds|b|{kbd}|{b}")])
    extra.append([button("➕ دکمه لینک", f"ds|kal|{kbd}", "success"),
                  button("➕ دکمه صفحه", f"ds|kap|{kbd}", "success")])
    extra.append([button("📐 چیدمان متنی", f"ds|kly|{kbd}"),
                  button("♻️ پیش‌فرض", f"ds|kr|{kbd}", "danger")])
    extra.append(back(f"ds|p|{kbd[5:]}" if kbd.startswith("page:") else "ds|kl"))
    markup = design.preview_keyboard(kbd, f"ds|b|{kbd}", extra_rows=extra)
    return "\n".join(lines), markup or kb(*extra)


def button_view(design: Design, kbd: str, btn: str) -> tuple[str, InlineKeyboardMarkup]:
    spec = design.keyboard_spec(kbd)
    conf = design.button_conf(kbd, btn)
    visible = design.is_visible(kbd, btn)
    lines = [f"🔘 <b>{html.escape(design.button_title(kbd, btn))}</b>",
             f"📍 کیبورد: {html.escape(spec.title)}", "",
             f"✏️ متن: <code>{html.escape(conf['text'])}</code>",
             f"🎨 رنگ: {design.style_name(conf.get('style'))}",
             f"💎 ایموجی پرمیوم: {'✅ دارد' if conf.get('icon') else '➖ ندارد'}",
             f"👁 وضعیت: {'نمایش' if visible else '🙈 مخفی'}"]
    if conf.get("url"):
        lines.append(f"🔗 لینک: {html.escape(conf['url'])}")
    if conf.get("page"):
        title = design.pages().get(conf["page"], {}).get("title", "؟")
        lines.append(f"📄 باز کردن صفحه: {html.escape(title)}")
    if btn in spec.buttons and spec.buttons[btn].placeholders:
        lines.append(placeholders_text(spec.buttons[btn].placeholders).strip())
    lines.append("\n👇 بالا: پیش‌نمایش زنده | پایین: تنظیمات این دکمه")

    p = f"{kbd}|{btn}"
    controls: list[list[InlineKeyboardButton]] = [
        [button(f"━━ ⚙️ {design.button_title(kbd, btn)[:30]} ━━", "noop")],
        [button("✏️ متن دکمه", f"ds|bt|{p}"), button("💎 ایموجی پرمیوم", f"ds|bi|{p}")],
        [InlineKeyboardButton(text=name.split(" ", 1)[1] if value else name, style=value,
                              callback_data=f"ds|bc|{p}|{key}")
         for key, (name, value) in STYLES.items()],
    ]
    if visible:
        controls += [
            [button("⬆️ ردیف بالا", f"ds|bm|{p}|up"), button("⬇️ ردیف پایین", f"ds|bm|{p}|down")],
            [button("◀️ جابجایی با قبلی", f"ds|bm|{p}|left"),
             button("جابجایی با بعدی ▶️", f"ds|bm|{p}|right")],
            [button("⬜️ تمام‌عرض (ردیف جدا)", f"ds|bm|{p}|alone"),
             button("🔗 کنار دکمه‌های بالا", f"ds|bm|{p}|join")],
        ]
        if btn in spec.multi:
            controls.append([button(f"{n} کانال در هر ردیف", f"ds|bn|{p}|{n}")
                             for n in (1, 2, 3)])
    if conf.get("icon"):
        controls.append([button("🗑 حذف ایموجی پرمیوم", f"ds|bid|{p}", "danger")])
    if conf.get("custom"):
        row = [button("🗑 حذف دکمه", f"ds|bx|{p}", "danger")]
        if conf.get("url"):
            row.insert(0, button("🔗 تغییر لینک", f"ds|bu|{p}"))
        controls.append(row)
    elif (kbd, btn) not in REQUIRED:
        controls.append([button("🙈 مخفی کردن" if visible else "👁 نمایش دادن", f"ds|bv|{p}")])
    controls.append(back(f"ds|k|{kbd}"))
    markup = design.preview_keyboard(kbd, f"ds|b|{kbd}", extra_rows=controls)
    return "\n".join(lines), markup or kb(*controls)


def pages_view(design: Design) -> tuple[str, InlineKeyboardMarkup]:
    rows = [[button(f"📄 {p.get('title', pid)}", f"ds|p|{pid}")]
            for pid, p in design.pages().items()]
    text = ("📄 <b>صفحه‌های سفارشی</b>\n\n"
            "هر صفحه یک متن (با ایموجی پرمیوم) و دکمه‌های خودش را دارد؛ مثل «درباره ما»، "
            "«پشتیبانی» یا «تعرفه‌ها».\n"
            "بعد از ساخت صفحه، در هر کیبوردی (مثلا صفحه شروع) با «➕ دکمه صفحه» "
            "یک دکمه بسازید که این صفحه را باز کند.")
    return text, kb(*rows, [button("➕ ساخت صفحه جدید", "ds|pn", "success")], back("ds|home"))


def page_view(design: Design, pid: str) -> tuple[str, InlineKeyboardMarkup]:
    title = design.pages().get(pid, {}).get("title", pid)
    text = f"📄 <b>صفحه «{html.escape(title)}»</b>\n\nمتن و دکمه‌های این صفحه را تنظیم کنید."
    return text, kb(
        [button("✏️ متن صفحه", f"ds|t|page:{pid}", "primary"),
         button("🔘 دکمه‌های صفحه", f"ds|k|page:{pid}", "primary")],
        [button("🗑 حذف صفحه", f"ds|pd|{pid}", "danger")],
        back("ds|pl"),
    )


def layout_help(design: Design, kbd: str) -> str:
    spec = design.keyboard_spec(kbd)
    current = "\n".join(" ".join(row) for row in design.layout(kbd)) or "(خالی)"
    names = "\n".join(f"<code>{b}</code> — {html.escape(design.button_title(kbd, b))}"
                      for b in design.all_buttons(kbd))
    multi = (f"\n\n💡 <code>{spec.multi[0]}:2</code> یعنی دو کانال در هر ردیف."
             if spec.multi else "")
    return (f"📐 <b>چیدمان «{html.escape(spec.title)}»</b>\n\n"
            "هر خط = یک ردیف دکمه. نام دکمه‌ها را با فاصله جدا کنید "
            f"(حداکثر {MAX_ROW} دکمه در هر ردیف).\n"
            "دکمه‌ای که در چیدمان نیاید، مخفی می‌شود.\n\n"
            f"چیدمان فعلی (کپی و ویرایش کنید):\n<pre>{html.escape(current)}</pre>\n"
            f"نام دکمه‌ها:\n{names}{multi}{CANCEL_HINT}")


# --------------------------------------------------------------------------- #
#  button presses                                                              #
# --------------------------------------------------------------------------- #

@router.callback_query(F.data.startswith("ds|"))
async def on_design(callback: CallbackQuery, bot: Bot, design: Design,
                    state: FSMContext) -> None:
    parts = (callback.data or "").split("|")
    action, args = parts[1], parts[2:]
    try:
        await _dispatch(callback, bot, design, state, action, args)
    except DesignError as exc:
        await callback.answer(str(exc), show_alert=True)
    except KeyError:
        await callback.answer("⚠️ این مورد دیگر وجود ندارد.", show_alert=True)


async def _dispatch(callback: CallbackQuery, bot: Bot, design: Design, state: FSMContext,
                    action: str, args: list[str]) -> None:
    answer = callback.answer
    if action not in ("tp",):
        await state.clear()

    # ---- navigation -------------------------------------------------------
    if action == "home":
        await answer()
        await show(callback, *home_view())
    elif action == "tc":
        await answer()
        await show(callback, *categories_view())
    elif action == "tl":
        await answer()
        await show(callback, *text_list_view(design, args[0]))
    elif action == "t":
        await answer()
        text, fallback, markup = text_view(design, args[0])
        await show(callback, text, markup, fallback=fallback)
    elif action == "kl":
        await answer()
        await show(callback, *keyboards_view(design))
    elif action == "k":
        await answer()
        await show(callback, *keyboard_view(design, args[0]))
    elif action == "b":
        await answer()
        await show(callback, *button_view(design, args[0], args[1]))
    elif action == "pl":
        await answer()
        await show(callback, *pages_view(design))
    elif action == "p":
        await answer()
        await show(callback, *page_view(design, args[0]))

    # ---- texts & stickers ---------------------------------------------------
    elif action == "te":
        key = args[0]
        spec = design.text_spec(key)
        await state.set_state(DesignForm.text)
        await state.update_data(key=key)
        await answer()
        tips = ("فقط متن ساده (بدون فرمت و ایموجی پرمیوم)، حداکثر ۲۰۰ کاراکتر." if spec.plain else
                "می‌توانید از <b>بولد</b>، <i>ایتالیک</i>، لینک، اسپویلر، نقل‌قول و "
                "<b>ایموجی پرمیوم</b> استفاده کنید؛ همه دقیقا همان‌طور ذخیره می‌شوند.")
        await callback.message.answer(
            f"✏️ متن جدید «{html.escape(spec.title)}» را بفرستید.\n\n{tips}\n"
            f"{placeholders_text(spec.placeholders)}"
            "👇 متن فعلی را در پیام بعدی فرستادم؛ آن را کپی کنید، تغییر دهید و بفرستید."
            f"{CANCEL_HINT}")
        template = design.template(key)
        try:
            await callback.message.answer(template, parse_mode=None if spec.plain else "HTML")
        except TelegramAPIError:
            await callback.message.answer(template, parse_mode=None)
    elif action == "ts":
        await state.set_state(DesignForm.sticker)
        await state.update_data(key=args[0])
        await answer()
        await callback.message.answer(
            "🎭 استیکر این صفحه را بفرستید (معمولی، متحرک یا ویدیویی).\n"
            "از این به بعد هر بار این صفحه نمایش داده شود، استیکر هم همراهش می‌آید."
            f"{CANCEL_HINT}")
    elif action == "tsd":
        await design.set_sticker(args[0], None)
        await answer("🗑 استیکر حذف شد")
        text, fallback, markup = text_view(design, args[0])
        await show(callback, text, markup, fallback=fallback)
    elif action == "tr":
        await design.reset_text(args[0])
        if args[0].startswith("cmd_"):
            await set_commands(bot, design)
        await answer("♻️ متن پیش‌فرض برگشت")
        text, fallback, markup = text_view(design, args[0])
        await show(callback, text, markup, fallback=fallback)
    elif action == "tp":
        await _full_preview(callback, bot, design, args[0])

    # ---- buttons --------------------------------------------------------------
    elif action in ("bt", "bi", "bu"):
        kbd, btn = args
        form = {"bt": DesignForm.btn_text, "bi": DesignForm.btn_icon, "bu": DesignForm.btn_url}
        await state.set_state(form[action])
        await state.update_data(kb=kbd, btn=btn)
        await answer()
        conf = design.button_conf(kbd, btn)
        spec = design.keyboard_spec(kbd)
        if action == "bt":
            names = spec.buttons[btn].placeholders if btn in spec.buttons else ()
            await callback.message.answer(
                "✏️ متن جدید دکمه را بفرستید (ایموجی معمولی مجاز است).\n"
                f"متن فعلی: <code>{html.escape(conf['text'])}</code>\n"
                f"{placeholders_text(names)}"
                "💎 برای ایموجی پرمیوم کنار دکمه از گزینه «ایموجی پرمیوم» استفاده کنید."
                f"{CANCEL_HINT}")
        elif action == "bi":
            await callback.message.answer(
                "💎 یک <b>ایموجی پرمیوم</b> بفرستید (یا استیکر ایموجی، یا آیدی عددی آن).\n"
                "این ایموجی قبل از متن دکمه نمایش داده می‌شود." + CANCEL_HINT)
        else:
            await callback.message.answer("🔗 لینک جدید را بفرستید (https://... یا t.me/...)."
                                          + CANCEL_HINT)
    elif action == "bc":
        kbd, btn, style = args
        await design.set_button(kbd, btn, style=STYLES[style][1])
        await answer(f"🎨 رنگ: {STYLES[style][0]}")
        await show(callback, *button_view(design, kbd, btn))
    elif action == "bid":
        kbd, btn = args
        await design.set_button(kbd, btn, icon=None)
        await answer("🗑 ایموجی حذف شد")
        await show(callback, *button_view(design, kbd, btn))
    elif action == "bm":
        kbd, btn, direction = args
        await design.move(kbd, btn, direction)
        await answer("✅")
        await show(callback, *button_view(design, kbd, btn))
    elif action == "bn":
        kbd, btn, n = args
        rows = [[f"{btn}:{n}" if t.split(":")[0] == btn else t for t in row]
                for row in design.layout(kbd)]
        await design.set_layout(kbd, rows)
        await answer("✅")
        await show(callback, *button_view(design, kbd, btn))
    elif action == "bv":
        kbd, btn = args
        visible = await design.toggle_visible(kbd, btn)
        await answer("👁 نمایش داده می‌شود" if visible else "🙈 مخفی شد")
        await show(callback, *button_view(design, kbd, btn))
    elif action == "bx":
        kbd, btn = args
        await design.delete_custom(kbd, btn)
        await answer("🗑 دکمه حذف شد")
        await show(callback, *keyboard_view(design, kbd))

    # ---- keyboards -------------------------------------------------------------
    elif action == "kal":
        await state.set_state(DesignForm.link_text)
        await state.update_data(kb=args[0])
        await answer()
        await callback.message.answer("➕ متن دکمه لینک را بفرستید (مثلا: 📢 کانال ما)."
                                      + CANCEL_HINT)
    elif action == "kap":
        if not design.pages():
            await answer("اول از «📄 صفحه‌های سفارشی» یک صفحه بسازید.", show_alert=True)
            return
        await answer()
        rows = [[button(f"📄 {p.get('title', pid)}", f"ds|kapp|{args[0]}|{pid}")]
                for pid, p in design.pages().items() if f"page:{pid}" != args[0]]
        await show(callback, "کدام صفحه با این دکمه باز شود؟", kb(*rows, back(f"ds|k|{args[0]}")))
    elif action == "kapp":
        await state.set_state(DesignForm.page_btn_text)
        await state.update_data(kb=args[0], pid=args[1])
        await answer()
        await callback.message.answer("✏️ متن دکمه را بفرستید (مثلا: 💬 پشتیبانی)." + CANCEL_HINT)
    elif action == "kly":
        await state.set_state(DesignForm.layout)
        await state.update_data(kb=args[0])
        await answer()
        await callback.message.answer(layout_help(design, args[0]))
    elif action == "kr":
        await design.reset_keyboard(args[0])
        await answer("♻️ دکمه‌ها به حالت پیش‌فرض برگشتند")
        await show(callback, *keyboard_view(design, args[0]))

    # ---- pages -----------------------------------------------------------------
    elif action == "pn":
        await state.set_state(DesignForm.page_title)
        await answer()
        await callback.message.answer("📄 یک نام برای صفحه جدید بفرستید (مثلا: درباره ما)."
                                      + CANCEL_HINT)
    elif action == "pd":
        await design.delete_page(args[0])
        await answer("🗑 صفحه حذف شد")
        await show(callback, *pages_view(design))

    # ---- import / export / reset -----------------------------------------------
    elif action == "ex":
        await answer()
        await callback.message.answer_document(
            BufferedInputFile(design.export().encode(), filename="design.json"),
            caption="📤 فایل طراحی ربات. با «📥 وارد کردن» می‌توانید آن را برگردانید.")
    elif action == "im":
        await state.set_state(DesignForm.import_file)
        await answer()
        await callback.message.answer("📥 فایل design.json را بفرستید.\n"
                                      "⚠️ طراحی فعلی جایگزین می‌شود." + CANCEL_HINT)
    elif action == "ra":
        await answer()
        await show(callback, "⚠️ همه متن‌ها، استیکرها، دکمه‌ها و صفحه‌های سفارشی پاک شوند؟",
                   kb([button("✅ بله، همه پاک شود", "ds|rac", "danger"),
                       button("❌ خیر", "ds|home")]))
    elif action == "rac":
        await design.reset_all()
        await set_commands(bot, design)
        await answer("♻️ طراحی به پیش‌فرض برگشت", show_alert=True)
        await show(callback, *home_view())
    else:
        await answer()


async def _full_preview(callback: CallbackQuery, bot: Bot, design: Design, key: str) -> None:
    spec = design.text_spec(key)
    if spec.plain:
        await callback.answer(design.sample_text(key)[:200], show_alert=True)
        return
    await callback.answer()
    chat_id = callback.message.chat.id
    if has_sticker(design, key) and (sticker := design.sticker(key)):
        await bot.send_sticker(chat_id, sticker)
    kbd = screen_keyboard(design, key)
    markup = design.preview_keyboard(kbd, "noop") if kbd else None
    await bot.send_message(chat_id, design.sample_text(key), reply_markup=markup)


# --------------------------------------------------------------------------- #
#  admin replies while a design form is open                                   #
# --------------------------------------------------------------------------- #

@router.message(DesignForm.text)
async def got_text(message: Message, bot: Bot, design: Design, state: FSMContext) -> None:
    key = (await state.get_data())["key"]
    spec = design.text_spec(key)
    if not message.text:
        await message.answer("⚠️ لطفا متن بفرستید." + CANCEL_HINT)
        return
    value = message.text if spec.plain else message.html_text
    if spec.plain and len(value) > (256 if key.startswith("cmd_") else 200):
        await message.answer("⚠️ این متن باید کوتاه‌تر باشد (حداکثر ۲۰۰ کاراکتر).")
        return
    try:  # validate by actually sending it once
        await message.answer(design.render_sample(key, value),
                             parse_mode=None if spec.plain else "HTML")
    except TelegramBadRequest as exc:
        await message.answer(f"❌ تلگرام این متن را قبول نکرد: <code>{html.escape(exc.message)}</code>")
        return
    await design.set_text(key, value)
    await state.clear()
    if key.startswith("cmd_"):
        await set_commands(bot, design)
    text, fallback, markup = text_view(design, key)
    await message.answer("✅ ذخیره شد! (پیام بالا پیش‌نمایش است)")
    await show(message, text, markup, fallback=fallback)


@router.message(DesignForm.sticker)
async def got_sticker(message: Message, design: Design, state: FSMContext) -> None:
    if not message.sticker:
        await message.answer("⚠️ لطفا یک استیکر بفرستید." + CANCEL_HINT)
        return
    key = (await state.get_data())["key"]
    await design.set_sticker(key, message.sticker.file_id)
    await state.clear()
    await message.answer("✅ استیکر ذخیره شد.")
    text, fallback, markup = text_view(design, key)
    await show(message, text, markup, fallback=fallback)


@router.message(DesignForm.btn_text)
async def got_button_text(message: Message, design: Design, state: FSMContext) -> None:
    data = await state.get_data()
    if not message.text or len(message.text) > 64:
        await message.answer("⚠️ متن دکمه باید بین ۱ تا ۶۴ کاراکتر باشد." + CANCEL_HINT)
        return
    await design.set_button(data["kb"], data["btn"], text=message.text)
    await state.clear()
    await show(message, *button_view(design, data["kb"], data["btn"]))


def extract_custom_emoji(message: Message) -> str | None:
    for entity in message.entities or []:
        if entity.type == "custom_emoji" and entity.custom_emoji_id:
            return entity.custom_emoji_id
    if message.sticker and message.sticker.custom_emoji_id:
        return message.sticker.custom_emoji_id
    if message.text and message.text.strip().isdigit():
        return message.text.strip()
    return None


@router.message(DesignForm.btn_icon)
async def got_button_icon(message: Message, design: Design, state: FSMContext) -> None:
    icon = extract_custom_emoji(message)
    if not icon:
        await message.answer("⚠️ ایموجی پرمیوم پیدا نشد. یک ایموجی پرمیوم (نه معمولی) بفرستید."
                             + CANCEL_HINT)
        return
    data = await state.get_data()
    await design.set_button(data["kb"], data["btn"], icon=icon)
    await state.clear()
    await show(message, *button_view(design, data["kb"], data["btn"]))


def normalize_url(text: str | None) -> str | None:
    url = (text or "").strip()
    if url.startswith(("t.me/", "telegram.me/")):
        url = "https://" + url
    if url.startswith("@") and len(url) > 1:
        url = f"https://t.me/{url[1:]}"
    return url if url.startswith(("https://", "http://", "tg://")) and " " not in url else None


@router.message(DesignForm.btn_url)
async def got_button_url(message: Message, design: Design, state: FSMContext) -> None:
    url = normalize_url(message.text)
    if not url:
        await message.answer("⚠️ لینک معتبر نیست. نمونه: https://t.me/mychannel" + CANCEL_HINT)
        return
    data = await state.get_data()
    await design.set_button(data["kb"], data["btn"], url=url)
    await state.clear()
    await show(message, *button_view(design, data["kb"], data["btn"]))


@router.message(DesignForm.layout)
async def got_layout(message: Message, design: Design, state: FSMContext) -> None:
    kbd = (await state.get_data())["kb"]
    try:
        rows = design.parse_layout(kbd, message.text or "")
    except DesignError as exc:
        await message.answer(f"❌ {html.escape(str(exc))}" + CANCEL_HINT)
        return
    await design.set_layout(kbd, rows)
    await state.clear()
    await message.answer("✅ چیدمان ذخیره شد.")
    await show(message, *keyboard_view(design, kbd))


@router.message(DesignForm.link_text)
async def got_link_text(message: Message, state: FSMContext) -> None:
    if not message.text or len(message.text) > 64:
        await message.answer("⚠️ متن دکمه باید بین ۱ تا ۶۴ کاراکتر باشد." + CANCEL_HINT)
        return
    await state.update_data(text=message.text)
    await state.set_state(DesignForm.link_url)
    await message.answer("🔗 حالا لینک را بفرستید (https://... یا t.me/... یا @channel)."
                         + CANCEL_HINT)


@router.message(DesignForm.link_url)
async def got_link_url(message: Message, design: Design, state: FSMContext) -> None:
    url = normalize_url(message.text)
    if not url:
        await message.answer("⚠️ لینک معتبر نیست. نمونه: https://t.me/mychannel" + CANCEL_HINT)
        return
    data = await state.get_data()
    cid = await design.add_custom(data["kb"], data["text"], url=url)
    await state.clear()
    await message.answer("✅ دکمه اضافه شد. حالا می‌توانید رنگ، ایموجی و جای آن را تنظیم کنید.")
    await show(message, *button_view(design, data["kb"], cid))


@router.message(DesignForm.page_btn_text)
async def got_page_button(message: Message, design: Design, state: FSMContext) -> None:
    if not message.text or len(message.text) > 64:
        await message.answer("⚠️ متن دکمه باید بین ۱ تا ۶۴ کاراکتر باشد." + CANCEL_HINT)
        return
    data = await state.get_data()
    cid = await design.add_custom(data["kb"], message.text, page=data["pid"])
    await state.clear()
    await message.answer("✅ دکمه اضافه شد.")
    await show(message, *button_view(design, data["kb"], cid))


@router.message(DesignForm.page_title)
async def got_page_title(message: Message, design: Design, state: FSMContext) -> None:
    if not message.text or len(message.text) > 60:
        await message.answer("⚠️ نام صفحه باید بین ۱ تا ۶۰ کاراکتر باشد." + CANCEL_HINT)
        return
    pid = await design.add_page(message.text)
    await state.clear()
    await message.answer("✅ صفحه ساخته شد. حالا متن و دکمه‌هایش را تنظیم کنید.")
    await show(message, *page_view(design, pid))


@router.message(DesignForm.import_file)
async def got_import(message: Message, bot: Bot, design: Design, state: FSMContext) -> None:
    doc = message.document
    if not doc or (doc.file_size or 0) > 2 * 1024 * 1024:
        await message.answer("⚠️ لطفا فایل design.json را بفرستید (حداکثر ۲ مگابایت)."
                             + CANCEL_HINT)
        return
    buffer = io.BytesIO()
    await bot.download(doc, destination=buffer)
    try:
        await design.import_json(buffer.getvalue().decode("utf-8-sig"))
    except (DesignError, UnicodeDecodeError) as exc:
        await message.answer(f"❌ {html.escape(str(exc))}" + CANCEL_HINT)
        return
    await state.clear()
    await set_commands(bot, design)
    await message.answer("✅ طراحی وارد شد.")
    await show(message, *home_view())
