"""The design store: admin overrides for texts, stickers, buttons and layouts.

Everything is kept in one JSON document (saved in SQLite) and cached in memory,
so rendering is just a dictionary lookup.

JSON shape::

    {
      "texts":    {text_key: html},
      "stickers": {text_key: sticker_file_id},
      "buttons":  {kb: {button: {"text": str, "style": str, "icon": custom_emoji_id}}},
      "layouts":  {kb: [[button, ...], ...]},
      "custom":   {kb: {cid: {"text", "style", "icon", "url" | "page"}}},
      "pages":    {pid: {"title": str}}
    }
"""
from __future__ import annotations

import html
import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..database import Database
from .keyboards import KEYBOARDS, PAGE_BUTTONS
from .specs import STYLES, ButtonSpec, KeyboardSpec, TextSpec
from .texts import TEXTS

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_TG_EMOJI_RE = re.compile(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", re.S)
MAX_ROW = 8          # Telegram allows at most 8 buttons per row
SETTING_KEY = "design"


class Raw(str):
    """A placeholder value that is already HTML and must not be escaped."""


@dataclass
class Btn:
    """What a handler provides for one button: its action and label values."""

    callback: str | None = None
    url: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


class DesignError(ValueError):
    """Invalid admin input (shown to the admin)."""


def strip_premium(text: str) -> str:
    """Replace premium emoji with their normal fallback emoji."""
    return _TG_EMOJI_RE.sub(r"\1", text)


def _fill(template: str, params: dict[str, Any], escape: bool) -> str:
    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name not in params:
            return match.group(0)
        value = params[name]
        if value is None:
            return ""
        if escape and not isinstance(value, Raw):
            return html.escape(str(value), quote=False)
        return str(value)
    return _PLACEHOLDER_RE.sub(repl, template)


def _new_id(prefix: str, taken: set[str] | dict) -> str:
    while True:
        candidate = prefix + secrets.token_hex(2)
        if candidate not in taken:
            return candidate


class Design:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.data: dict[str, Any] = self._empty()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"texts": {}, "stickers": {}, "buttons": {}, "layouts": {}, "custom": {},
                "pages": {}}

    # ---- persistence -------------------------------------------------------

    async def load(self) -> None:
        raw = await self.db.get_setting(SETTING_KEY)
        if raw:
            self.data = self._normalize(json.loads(raw))

    async def save(self) -> None:
        await self.db.set_setting(SETTING_KEY, json.dumps(self.data, ensure_ascii=False))

    def _normalize(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise DesignError("فایل طراحی معتبر نیست.")
        result = self._empty()
        for section in result:
            value = data.get(section, {})
            if not isinstance(value, dict):
                raise DesignError(f"بخش «{section}» در فایل طراحی معتبر نیست.")
            result[section] = value
        return result

    def export(self) -> str:
        return json.dumps({"version": 1, **self.data}, ensure_ascii=False, indent=2)

    async def import_json(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DesignError("فایل JSON قابل خواندن نیست.") from exc
        data.pop("version", None)
        self.data = self._normalize(data)
        await self.save()

    async def reset_all(self) -> None:
        self.data = self._empty()
        await self.save()

    # ---- texts -------------------------------------------------------------

    def text_spec(self, key: str) -> TextSpec:
        if key in TEXTS:
            return TEXTS[key]
        if key.startswith("page:") and (page := self.data["pages"].get(key[5:])):
            return TextSpec(key, page.get("title", "صفحه"), category="pages",
                            default=f"📄 <b>{html.escape(page.get('title', ''))}</b>\n\n"
                                    "متن این صفحه را از پنل طراحی تنظیم کنید.",
                            placeholders=("name",), sample={"name": "علی"})
        raise KeyError(key)

    def template(self, key: str) -> str:
        return self.data["texts"].get(key) or self.text_spec(key).default

    def is_custom_text(self, key: str) -> bool:
        return key in self.data["texts"]

    def text(self, key: str, /, **params: Any) -> str:
        spec = self.text_spec(key)
        return _fill(self.template(key), params, escape=not spec.plain)

    def render_sample(self, key: str, template: str) -> str:
        """Render an unsaved template with sample values (to validate/preview it)."""
        spec = self.text_spec(key)
        return _fill(template, dict(spec.sample), escape=not spec.plain)

    def sample_text(self, key: str) -> str:
        spec = self.text_spec(key)
        return _fill(self.template(key), dict(spec.sample), escape=not spec.plain)

    async def set_text(self, key: str, value: str) -> None:
        self.text_spec(key)  # validates the key
        self.data["texts"][key] = value
        await self.save()

    async def reset_text(self, key: str) -> None:
        self.data["texts"].pop(key, None)
        await self.save()

    # ---- stickers ----------------------------------------------------------

    def sticker(self, key: str) -> str | None:
        return self.data["stickers"].get(key)

    async def set_sticker(self, key: str, file_id: str | None) -> None:
        if file_id:
            self.data["stickers"][key] = file_id
        else:
            self.data["stickers"].pop(key, None)
        await self.save()

    # ---- pages -------------------------------------------------------------

    def pages(self) -> dict[str, dict[str, Any]]:
        return self.data["pages"]

    async def add_page(self, title: str) -> str:
        pid = _new_id("p", self.data["pages"])
        self.data["pages"][pid] = {"title": title[:60]}
        await self.save()
        return pid

    async def delete_page(self, pid: str) -> None:
        self.data["pages"].pop(pid, None)
        kb = f"page:{pid}"
        for section in ("buttons", "layouts", "custom"):
            self.data[section].pop(kb, None)
        self.data["texts"].pop(kb, None)
        self.data["stickers"].pop(kb, None)
        # Remove buttons elsewhere that opened this page.
        for kb_key, customs in list(self.data["custom"].items()):
            for cid, conf in list(customs.items()):
                if conf.get("page") == pid:
                    await self.delete_custom(kb_key, cid, save=False)
        await self.save()

    # ---- keyboards: specs and configuration --------------------------------

    def keyboard_spec(self, kb: str) -> KeyboardSpec:
        if kb in KEYBOARDS:
            return KEYBOARDS[kb]
        if kb.startswith("page:") and (page := self.data["pages"].get(kb[5:])):
            return KeyboardSpec(kb, f"دکمه‌های صفحه «{page.get('title', '')}»",
                                buttons=PAGE_BUTTONS, layout=(("back",),), screen=kb)
        raise KeyError(kb)

    def keyboards(self) -> list[KeyboardSpec]:
        return [*KEYBOARDS.values(), *(self.keyboard_spec(f"page:{pid}") for pid in self.pages())]

    def customs(self, kb: str) -> dict[str, dict[str, Any]]:
        return self.data["custom"].get(kb, {})

    def all_buttons(self, kb: str) -> list[str]:
        return [*self.keyboard_spec(kb).buttons, *self.customs(kb)]

    def button_title(self, kb: str, btn: str) -> str:
        spec = self.keyboard_spec(kb)
        if btn in spec.buttons:
            return spec.buttons[btn].title
        conf = self.customs(kb).get(btn, {})
        kind = "لینک" if conf.get("url") else "صفحه"
        return f"دکمه {kind}: {conf.get('text', btn)}"

    def button_conf(self, kb: str, btn: str) -> dict[str, Any]:
        """Effective label template, style and icon of a button."""
        spec = self.keyboard_spec(kb)
        if btn in spec.buttons:
            bspec: ButtonSpec = spec.buttons[btn]
            override = self.data["buttons"].get(kb, {}).get(btn, {})
            return {
                "text": override.get("text") or bspec.default,
                "style": override["style"] if "style" in override else bspec.style,
                "icon": override.get("icon"),
                "custom": False,
            }
        conf = self.customs(kb).get(btn)
        if conf is None:
            raise KeyError(btn)
        return {**conf, "custom": True}

    async def set_button(self, kb: str, btn: str, **fields: Any) -> None:
        """Update text / style / icon / url of a button."""
        spec = self.keyboard_spec(kb)
        if btn in spec.buttons:
            target = self.data["buttons"].setdefault(kb, {}).setdefault(btn, {})
        elif btn in self.customs(kb):
            target = self.data["custom"][kb][btn]
        else:
            raise KeyError(btn)
        for name, value in fields.items():
            if name == "style" and value not in (None, "primary", "success", "danger"):
                raise DesignError("رنگ نامعتبر است.")
            if value is None and name in ("icon", "text"):
                target.pop(name, None)
            else:
                target[name] = value
        await self.save()

    async def reset_keyboard(self, kb: str) -> None:
        self.data["buttons"].pop(kb, None)
        self.data["layouts"].pop(kb, None)
        if self.customs(kb):  # keep custom buttons, but put them back on their own rows
            self.data["layouts"][kb] = [list(r) for r in self.keyboard_spec(kb).layout] + \
                [[cid] for cid in self.customs(kb)]
        await self.save()

    async def add_custom(self, kb: str, text: str, *, url: str | None = None,
                         page: str | None = None) -> str:
        self.keyboard_spec(kb)
        if not url and not page:
            raise DesignError("دکمه باید لینک یا صفحه داشته باشد.")
        customs = self.data["custom"].setdefault(kb, {})
        cid = _new_id("c", customs)
        customs[cid] = {"text": text[:64], "style": None, "icon": None,
                        **({"url": url} if url else {"page": page})}
        layout = self.layout(kb)
        layout.append([cid])
        self.data["layouts"][kb] = layout
        await self.save()
        return cid

    async def delete_custom(self, kb: str, cid: str, *, save: bool = True) -> None:
        self.data["custom"].get(kb, {}).pop(cid, None)
        layout = [[b for b in row if b != cid] for row in self.layout(kb)]
        self.data["layouts"][kb] = [row for row in layout if row]
        if save:
            await self.save()

    # ---- layouts -----------------------------------------------------------

    def layout(self, kb: str) -> list[list[str]]:
        stored = self.data["layouts"].get(kb)
        if stored is not None:
            return [list(row) for row in stored]
        return [list(row) for row in self.keyboard_spec(kb).layout]

    @staticmethod
    def _base(token: str) -> str:
        return token.split(":", 1)[0]

    def parse_layout(self, kb: str, text: str) -> list[list[str]]:
        """Parse a layout typed by an admin: one line per row, keys separated by spaces."""
        valid = set(self.all_buttons(kb))
        multi = set(self.keyboard_spec(kb).multi)
        rows: list[list[str]] = []
        seen: set[str] = set()
        for line in text.strip().splitlines():
            row = line.replace(",", " ").split()
            if not row:
                continue
            for token in row:
                base = self._base(token)
                if base not in valid:
                    raise DesignError(f"«{token}» یک دکمه معتبر نیست.")
                if ":" in token and (base not in multi or not token.split(":", 1)[1].isdigit()):
                    raise DesignError(f"«{token}» نامعتبر است. «:عدد» فقط برای {', '.join(multi) or '—'} مجاز است.")
                if base in seen:
                    raise DesignError(f"دکمه «{base}» دو بار آمده است.")
                seen.add(base)
            if len(row) > MAX_ROW:
                raise DesignError(f"حداکثر {MAX_ROW} دکمه در هر ردیف مجاز است.")
            rows.append(row)
        return rows

    async def set_layout(self, kb: str, rows: list[list[str]]) -> None:
        self.data["layouts"][kb] = rows
        await self.save()

    def is_visible(self, kb: str, btn: str) -> bool:
        return any(self._base(t) == btn for row in self.layout(kb) for t in row)

    def _locate(self, layout: list[list[str]], btn: str) -> tuple[int, int] | None:
        for r, row in enumerate(layout):
            for c, token in enumerate(row):
                if self._base(token) == btn:
                    return r, c
        return None

    async def toggle_visible(self, kb: str, btn: str) -> bool:
        layout = self.layout(kb)
        pos = self._locate(layout, btn)
        if pos:
            layout[pos[0]].pop(pos[1])
            visible = False
        else:
            layout.append([btn])
            visible = True
        self.data["layouts"][kb] = [row for row in layout if row]
        await self.save()
        return visible

    async def move(self, kb: str, btn: str, direction: str) -> None:
        """up / down: move to the previous / next row; left / right: swap within the row;
        alone: put the button on its own (full-width) row; join: merge into the row above."""
        layout = self.layout(kb)
        pos = self._locate(layout, btn)
        if pos is None:
            layout.append([btn])
            pos = (len(layout) - 1, 0)
        r, c = pos
        row = layout[r]
        if direction in ("left", "right"):
            other = c - 1 if direction == "left" else c + 1
            if 0 <= other < len(row):
                row[c], row[other] = row[other], row[c]
        elif direction == "up":
            token = row.pop(c)
            if r == 0:
                layout.insert(0, [token])
            elif len(layout[r - 1]) >= MAX_ROW:
                raise DesignError("ردیف بالا پر است.")
            else:
                layout[r - 1].append(token)
        elif direction == "down":
            token = row.pop(c)
            if r == len(layout) - 1:
                layout.append([token])
            elif len(layout[r + 1]) >= MAX_ROW:
                raise DesignError("ردیف پایین پر است.")
            else:
                layout[r + 1].insert(0, token)
        elif direction == "alone":
            if len(row) > 1:
                token = row.pop(c)
                layout.insert(r + 1, [token])
        elif direction == "join":
            if r > 0 and len(row) == 1:
                if len(layout[r - 1]) >= MAX_ROW:
                    raise DesignError("ردیف بالا پر است.")
                layout[r - 1].append(row.pop(c))
        self.data["layouts"][kb] = [row for row in layout if row]
        await self.save()

    # ---- rendering ---------------------------------------------------------

    def _make_button(self, conf: dict[str, Any], btn: Btn) -> InlineKeyboardButton:
        label = _fill(conf["text"], btn.params, escape=False).strip() or "•"
        kwargs: dict[str, Any] = {"text": label[:64]}
        if btn.url:
            kwargs["url"] = btn.url
        else:
            kwargs["callback_data"] = btn.callback or "noop"
        if conf.get("style"):
            kwargs["style"] = conf["style"]
        if conf.get("icon"):
            kwargs["icon_custom_emoji_id"] = conf["icon"]
        return InlineKeyboardButton(**kwargs)

    def _custom_action(self, conf: dict[str, Any]) -> Btn:
        if conf.get("url"):
            return Btn(url=conf["url"])
        return Btn(callback=f"pg|{conf.get('page')}")

    def keyboard(self, kb: str, buttons: dict[str, Btn] | None = None,
                 multi: dict[str, list[Btn]] | None = None,
                 extra_rows: list[list[InlineKeyboardButton]] | None = None,
                 ) -> InlineKeyboardMarkup | None:
        """Build a keyboard. Buttons the handler did not provide (e.g. a quality
        that this video doesn't have) are skipped; empty rows disappear."""
        buttons = buttons or {}
        multi = multi or {}
        spec = self.keyboard_spec(kb)
        customs = self.customs(kb)
        rows: list[list[InlineKeyboardButton]] = []
        for layout_row in self.layout(kb):
            row: list[InlineKeyboardButton] = []
            for token in layout_row:
                base, _, per_row = token.partition(":")
                if base in spec.multi:
                    items = multi.get(base, [])
                    if not items:
                        continue
                    if row:
                        rows.append(row)
                        row = []
                    size = max(1, min(MAX_ROW, int(per_row) if per_row.isdigit() else 1))
                    conf = self.button_conf(kb, base)
                    made = [self._make_button(conf, item) for item in items]
                    rows.extend(made[i:i + size] for i in range(0, len(made), size))
                elif base in buttons:  # checked first so previews can override customs
                    row.append(self._make_button(self.button_conf(kb, base), buttons[base]))
                elif base in customs:
                    row.append(self._make_button(customs[base], self._custom_action(customs[base])))
            if row:
                rows.append(row)
        rows = [r[i:i + MAX_ROW] for r in rows for i in range(0, len(r), MAX_ROW)]
        rows += extra_rows or []
        return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None

    def preview_keyboard(self, kb: str, pick_prefix: str,
                         extra_rows: list[list[InlineKeyboardButton]] | None = None,
                         ) -> InlineKeyboardMarkup | None:
        """The keyboard as users see it, where every button opens its own settings."""
        spec = self.keyboard_spec(kb)
        buttons = {key: Btn(callback=f"{pick_prefix}|{key}", params=spec.sample.get(key, {}))
                   for key in [*spec.buttons, *self.customs(kb)] if key not in spec.multi}
        multi = {key: [Btn(callback=f"{pick_prefix}|{key}",
                           params={**spec.sample.get(key, {}), "n": str(i)}) for i in (1, 2)]
                 for key in spec.multi}
        return self.keyboard(kb, buttons, multi, extra_rows=extra_rows)

    @staticmethod
    def style_name(style: str | None) -> str:
        for key, (name, value) in STYLES.items():
            if value == style:
                return name
        return STYLES["default"][0]
