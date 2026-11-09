import asyncio
import json

import pytest
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database import Database
from bot.services.cookies import CookieError, parse_cookies
from bot.ui import Btn, Design, Raw
from bot.ui.design import DesignError, strip_premium
from bot.ui.fallback import _has_premium, _without_premium
from bot.ui.keyboards import KEYBOARDS
from bot.ui.texts import TEXTS


_loop = asyncio.new_event_loop()


def run(coro):
    return _loop.run_until_complete(coro)


@pytest.fixture
def design(tmp_path):
    async def make():
        db = Database(tmp_path / "t.db")
        await db.connect()
        d = Design(db)
        await d.load()
        return d
    d = run(make())
    yield d
    run(d.db.close())


def rows(markup):
    return [[(b.text, b.callback_data or b.url, b.style, b.icon_custom_emoji_id) for b in r]
            for r in markup.inline_keyboard]


def test_every_text_has_valid_placeholders():
    import re
    for key, spec in TEXTS.items():
        used = set(re.findall(r"\{(\w+)\}", spec.default))
        assert used <= set(spec.placeholders), (key, used - set(spec.placeholders))
        assert set(spec.sample) <= set(spec.placeholders), key


def test_text_render_escapes_values_but_not_raw(design):
    assert design.text("start", name="<b>x</b>", bot="B").startswith("سلام &lt;b&gt;x&lt;/b&gt;")
    out = design.text("playlist_item_failed", error=Raw("<b>e</b>"), item="<i>")
    assert out == "<b>e</b>\n<code>&lt;i&gt;</code>"
    # plain texts (alerts) are not escaped
    assert design.text("yt_too_big", size="<1>", limit="2").startswith("⚠️ حجم این کیفیت حدود <1>")


def test_custom_text_with_premium_emoji_persists(design, tmp_path):
    html = '<tg-emoji emoji-id="5368324170671202286">👍</tg-emoji> سلام <b>{name}</b> {unknown}'
    run(design.set_text("start", html))
    assert design.text("start", name="Ali") == \
        '<tg-emoji emoji-id="5368324170671202286">👍</tg-emoji> سلام <b>Ali</b> {unknown}'

    async def reload():
        d2 = Design(design.db)
        await d2.load()
        return d2
    assert run(reload()).template("start") == html
    assert strip_premium(html).startswith("👍 سلام")
    run(design.reset_text("start"))
    assert design.template("start") == TEXTS["start"].default


def test_youtube_keyboard_skips_missing_qualities_and_keeps_styles(design):
    markup = design.keyboard("youtube", {
        "q360": Btn(callback="v360", params={"quality": "360p", "size": "5 MB", "warn": ""}),
        "q240": Btn(callback="v240", params={"quality": "240p", "size": "3 MB", "warn": ""}),
        "audio": Btn(callback="a", params={"size": "1 MB"}),
        "cancel": Btn(callback="x"),
    })
    assert rows(markup) == [
        [("🎬 360p • 5 MB", "v360", None, None)],
        [("🎬 240p • 3 MB", "v240", None, None)],
        [("🎵 فقط صدا (MP3) • 1 MB", "a", "primary", None)],
        [("❌ لغو", "x", "danger", None)],
    ]


def test_button_text_color_icon_and_moves(design):
    btns = {"help": Btn(callback="h"), "add_group": Btn(url="https://t.me/x?startgroup=true")}
    run(design.set_button("start", "help", text="📚 Help", style="success", icon="123"))
    run(design.move("start", "add_group", "up"))       # next to help
    assert rows(design.keyboard("start", btns)) == [
        [("📚 Help", "h", "success", "123"),
         ("➕ افزودن ربات به گروه", "https://t.me/x?startgroup=true", None, None)]]
    run(design.move("start", "add_group", "left"))     # swap inside the row
    assert design.layout("start") == [["add_group", "help"]]
    run(design.move("start", "help", "alone"))          # full width on its own row
    assert design.layout("start") == [["add_group"], ["help"]]
    run(design.move("start", "help", "join"))
    assert design.layout("start") == [["add_group", "help"]]
    assert run(design.toggle_visible("start", "add_group")) is False
    assert design.layout("start") == [["help"]]
    run(design.set_button("start", "help", style=None, icon=None))
    assert design.button_conf("start", "help")["style"] is None
    with pytest.raises(DesignError):
        run(design.set_button("start", "help", style="pink"))


def test_custom_link_and_page_buttons(design):
    cid = run(design.add_custom("media", "📢 Channel", url="https://t.me/ch"))
    assert rows(design.keyboard("media")) == [[("📢 Channel", "https://t.me/ch", None, None)]]
    pid = run(design.add_page("About"))
    pcid = run(design.add_custom("start", "ℹ️ About", page=pid))
    markup = design.keyboard("start", {"help": Btn(callback="h")})
    assert ("ℹ️ About", f"pg|{pid}", None, None) in [b for r in rows(markup) for b in r]
    assert design.text_spec(f"page:{pid}").title == "About"
    assert rows(design.keyboard(f"page:{pid}", {"back": Btn(callback="b")})) == \
        [[("🔙 بازگشت", "b", None, None)]]
    run(design.delete_page(pid))  # also removes the button that opened it
    assert pcid not in design.customs("start")
    run(design.delete_custom("media", cid))
    assert design.keyboard("media") is None


def test_layout_parsing_and_multi_buttons(design):
    rows_ = design.parse_layout("join", "check\nchannels:2")
    run(design.set_layout("join", rows_))
    markup = design.keyboard("join", {"check": Btn(callback="c")}, multi={
        "channels": [Btn(url=f"https://t.me/c{i}", params={"n": str(i)}) for i in (1, 2, 3)]})
    assert [len(r) for r in markup.inline_keyboard] == [1, 2, 1]
    assert markup.inline_keyboard[1][1].text == "📢 عضویت در کانال 2"
    for bad in ("nope", "check check", "check:2", " ".join(["check"] * 9)):
        with pytest.raises(DesignError):
            design.parse_layout("join", bad)


def test_preview_keyboard_opens_settings(design):
    markup = design.preview_keyboard("youtube", "ds|b|youtube")
    datas = [b.callback_data for r in markup.inline_keyboard for b in r]
    assert "ds|b|youtube|q1080" in datas and "ds|b|youtube|cancel" in datas
    for spec in KEYBOARDS.values():  # every built-in keyboard can be previewed
        design.preview_keyboard(spec.key, "noop")


def test_export_import_and_reset(design):
    run(design.set_text("help", "<b>H</b>"))
    run(design.set_sticker("start", "STICKER"))
    dumped = design.export()
    run(design.reset_all())
    assert design.sticker("start") is None
    run(design.import_json(dumped))
    assert design.sticker("start") == "STICKER" and design.template("help") == "<b>H</b>"
    with pytest.raises(DesignError):
        run(design.import_json("not json"))
    with pytest.raises(DesignError):
        run(design.import_json(json.dumps({"texts": []})))


def test_premium_fallback_strips_emoji_and_icons():
    method = SendMessage(
        chat_id=1, text='<tg-emoji emoji-id="1">🔥</tg-emoji> hi',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="b", callback_data="c", style="success", icon_custom_emoji_id="9")]]))
    assert _has_premium(method)
    plain = _without_premium(method)
    assert plain.text == "🔥 hi"
    button = plain.reply_markup.inline_keyboard[0][0]
    assert button.icon_custom_emoji_id is None and button.style == "success"
    assert not _has_premium(plain)


def test_cookie_formats():
    netscape = ("# Netscape HTTP Cookie File\n"
                ".instagram.com\tTRUE\t/\tTRUE\t1999999999\tsessionid\tabc\n"
                "#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t1999999999\tcsrftoken\tx\n"
                ".google.com\tTRUE\t/\tTRUE\t1999999999\tNID\tother\n")
    parsed = parse_cookies(netscape, "instagram")
    assert parsed.count == 2 and parsed.has_session and "google" not in parsed.text

    as_json = json.dumps([
        {"domain": ".youtube.com", "hostOnly": False, "path": "/", "secure": True,
         "expirationDate": 1999999999.5, "name": "SID", "value": "v"},
        {"domain": "www.youtube.com", "hostOnly": True, "path": "/", "secure": False,
         "name": "PREF", "value": "p"},
    ])
    parsed = parse_cookies(as_json, "youtube")
    lines = parsed.text.strip().splitlines()[-2:]
    assert lines[0].split("\t") == [".youtube.com", "TRUE", "/", "TRUE", "1999999999", "SID", "v"]
    assert lines[1].split("\t")[:2] == ["www.youtube.com", "FALSE"] and parsed.has_session

    parsed = parse_cookies("sessionid=abc; csrftoken=x", "instagram")
    assert parsed.count == 2 and parsed.text.splitlines()[-1].startswith(".instagram.com\t")
    with pytest.raises(CookieError):
        parse_cookies(netscape, "soundcloud")
