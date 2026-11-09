"""Send downloaded files (or cached file_ids) to a chat, and collect the
file_ids Telegram returns so the same link can be re-sent instantly later."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import (
    FSInputFile, InputFile, InputMediaPhoto, InputMediaVideo, Message, ReplyParameters,
)

from .services.media import MediaFile

T = TypeVar("T")


@dataclass
class Outgoing:
    kind: str                       # video | audio | photo | animation | document
    media: InputFile | str          # a local file or a Telegram file_id
    title: str | None = None
    performer: str | None = None
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    thumbnail: InputFile | None = None


def from_files(files: list[MediaFile]) -> list[Outgoing]:
    return [
        Outgoing(
            kind=f.kind,
            media=FSInputFile(f.path, filename=f.path.name),
            title=f.title, performer=f.performer, duration=f.duration,
            width=f.width, height=f.height,
            thumbnail=FSInputFile(f.thumbnail) if f.thumbnail else None,
        )
        for f in files
    ]


def from_cache(payload: list[dict[str, Any]]) -> list[Outgoing]:
    return [
        Outgoing(kind=item["kind"], media=item["file_id"],
                 title=item.get("title"), performer=item.get("performer"))
        for item in payload
    ]


def _entry(message: Message) -> dict[str, Any] | None:
    if message.video:
        return {"kind": "video", "file_id": message.video.file_id}
    if message.photo:
        return {"kind": "photo", "file_id": message.photo[-1].file_id}
    if message.audio:
        return {"kind": "audio", "file_id": message.audio.file_id,
                "title": message.audio.title, "performer": message.audio.performer}
    if message.animation:
        return {"kind": "animation", "file_id": message.animation.file_id}
    if message.document:
        return {"kind": "document", "file_id": message.document.file_id}
    return None


async def _retry(call: Callable[[], Awaitable[T]]) -> T:
    for _ in range(3):
        try:
            return await call()
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
    return await call()


async def send_items(bot: Bot, chat_id: int, items: list[Outgoing], caption: str,
                     reply_to: int | None = None) -> list[dict[str, Any]]:
    """Send everything; returns cache entries (kind + file_id) in order."""
    reply = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) \
        if reply_to else None
    sent: list[Message] = []
    visual = [i for i in items if i.kind in ("photo", "video")]
    others = [i for i in items if i.kind not in ("photo", "video")]

    if len(visual) > 1:
        for start in range(0, len(visual), 10):
            group = []
            for n, item in enumerate(visual[start:start + 10]):
                cap = caption if start == 0 and n == 0 else None
                if item.kind == "photo":
                    group.append(InputMediaPhoto(media=item.media, caption=cap))
                else:
                    group.append(InputMediaVideo(
                        media=item.media, caption=cap, thumbnail=item.thumbnail,
                        width=item.width, height=item.height, duration=item.duration,
                        supports_streaming=True,
                    ))
            sent += await _retry(lambda g=group: bot.send_media_group(
                chat_id, media=g, reply_parameters=reply))
    elif visual:
        others.insert(0, visual[0])

    for item in others:
        sent.append(await _retry(lambda i=item: _send_single(bot, chat_id, i, caption, reply)))

    return [e for e in (_entry(m) for m in sent) if e]


async def _send_single(bot: Bot, chat_id: int, item: Outgoing, caption: str,
                       reply: ReplyParameters | None) -> Message:
    common: dict[str, Any] = {"caption": caption, "reply_parameters": reply}
    if item.kind == "video":
        return await bot.send_video(
            chat_id, video=item.media, thumbnail=item.thumbnail, width=item.width,
            height=item.height, duration=item.duration, supports_streaming=True, **common,
        )
    if item.kind == "photo":
        return await bot.send_photo(chat_id, photo=item.media, **common)
    if item.kind == "audio":
        return await bot.send_audio(
            chat_id, audio=item.media, thumbnail=item.thumbnail, title=item.title,
            performer=item.performer, duration=item.duration, **common,
        )
    if item.kind == "animation":
        return await bot.send_animation(chat_id, animation=item.media, **common)
    return await bot.send_document(chat_id, document=item.media, thumbnail=item.thumbnail,
                                   **common)
