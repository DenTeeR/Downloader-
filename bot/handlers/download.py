"""The main flow: user sends a link -> bot downloads -> bot sends the files."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from .. import keyboards, texts
from ..config import Config
from ..database import Database
from ..platforms import (
    Platform, cache_key, detect_platform, expand_short_link, extract_url,
    is_youtube_playlist_only, youtube_id,
)
from ..progress import StatusMessage
from ..sender import from_cache, from_files, send_items
from ..services.downloader import Downloader, Job, Plan
from ..services.media import DownloadError
from ..services.ytdlp import YtDlp
from ..utils import TTLStore, esc, fa, format_duration, format_size, truncate

log = logging.getLogger(__name__)
router = Router(name="download")

# Users with a download in progress (one job per user at a time).
active_users: set[int] = set()


@dataclass
class YoutubeRequest:
    user_id: int
    chat_id: int
    reply_to: int
    url: str
    video_id: str
    title: str
    qualities: dict[int, int | None] = field(default_factory=dict)
    audio_size: int | None = None


youtube_requests: TTLStore[YoutubeRequest] = TTLStore(ttl=3600)


def build_caption(title: str | None, bot_username: str) -> str:
    parts = []
    if title:
        parts.append(f"<b>{esc(truncate(title.strip(), 300))}</b>")
    parts.append(f"📥 @{bot_username}")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
#  Incoming links                                                              #
# --------------------------------------------------------------------------- #

@router.message(F.text | F.caption)
async def on_message(message: Message, bot: Bot, config: Config, db: Database,
                     downloader: Downloader, bot_username: str) -> None:
    private = message.chat.type == ChatType.PRIVATE
    url = extract_url(message.text or message.caption)
    if not url:
        if private:
            await message.answer(texts.SEND_LINK)
        return
    platform = detect_platform(url)
    if platform is None:
        if private:
            await message.reply(texts.UNSUPPORTED)
        return

    user_id = message.from_user.id if message.from_user else message.chat.id
    if user_id in active_users:
        await message.reply(texts.BUSY)
        return

    active_users.add(user_id)
    status: StatusMessage | None = None
    try:
        status_msg = await message.reply(texts.CHECKING)
        status = StatusMessage(bot, message.chat.id, status_msg.message_id)
        url = await expand_short_link(url, config.proxy)
        platform = detect_platform(url) or platform
        if platform is Platform.YOUTUBE:
            await show_youtube_menu(message, status, url, config, downloader)
            return
        plan = await downloader.plan(platform, url)
        await run_plan(plan, status, bot, message.chat.id, message.message_id, user_id,
                       config, db, downloader, bot_username)
    except DownloadError as exc:
        log.info("Download failed for %s: %s", url, exc)
        if status:
            await status.set(exc.user_message)
    except Exception:
        log.exception("Unexpected error for %s", url)
        if status:
            await status.set(texts.ERROR_GENERIC)
    finally:
        if status:
            await status.stop()
        active_users.discard(user_id)


async def run_plan(plan: Plan, status: StatusMessage, bot: Bot, chat_id: int, reply_to: int,
                   user_id: int, config: Config, db: Database, downloader: Downloader,
                   bot_username: str) -> None:
    if len(plan.jobs) == 1:
        await run_job(plan.jobs[0], status, bot, chat_id, reply_to, user_id,
                      config, db, downloader, bot_username)
        await status.delete()
        return

    header = texts.PLAYLIST_HEADER.format(title=esc(plan.title or "Playlist"),
                                          count=fa(len(plan.jobs)))
    if plan.truncated_from:
        header += texts.PLAYLIST_TRUNCATED.format(total=fa(plan.truncated_from),
                                                  count=fa(len(plan.jobs)))
    status.banner = header
    ok = 0
    for job in plan.jobs:
        try:
            await run_job(job, status, bot, chat_id, None, user_id,
                          config, db, downloader, bot_username)
            ok += 1
        except DownloadError as exc:
            log.info("Playlist item failed %s: %s", job.url, exc)
            title = job.spotify.search_query if job.spotify else job.url
            await bot.send_message(chat_id, f"{exc.user_message}\n<code>{esc(title)}</code>")
        except Exception:
            log.exception("Playlist item crashed %s", job.url)
    await status.set(texts.PLAYLIST_DONE.format(ok=fa(ok), total=fa(len(plan.jobs))))


async def run_job(job: Job, status: StatusMessage, bot: Bot, chat_id: int,
                  reply_to: int | None, user_id: int, config: Config, db: Database,
                  downloader: Downloader, bot_username: str,
                  title_hint: str | None = None) -> None:
    """Download one job and send it; raises DownloadError on failure."""
    prefix = f"[{job.label}] " if job.label else ""

    # 1) Already sent before? Re-send by file_id, no download needed.
    if config.cache_enabled and (cached := await db.cache_get(job.key)):
        try:
            await status.set(prefix + texts.FROM_CACHE)
            await send_items(bot, chat_id, from_cache(cached["items"]),
                             build_caption(cached.get("title"), bot_username), reply_to)
            await db.log_download(user_id, job.platform.value, job.url, True)
            return
        except TelegramBadRequest:
            await db.cache_delete(job.key)  # stale file_id (e.g. bot token changed)

    # 2) Download.
    workdir = downloader.new_workdir()
    try:
        if downloader.semaphore.locked():
            await status.set(prefix + texts.QUEUED)
        async with downloader.semaphore:
            status.header = prefix + texts.DOWNLOADING
            await status.set(status.header)
            status.start()
            files = await downloader.run(job, workdir, progress=status.report)
            await status.stop()

        sendable = [f for f in files if f.size <= config.max_file_size]
        if not sendable:
            raise DownloadError(texts.TOO_LARGE.format(
                size=format_size(max(f.size for f in files)),
                limit=format_size(config.max_file_size)))

        # 3) Upload.
        await status.set(prefix + texts.UPLOADING)
        if job.spotify:
            title = job.spotify.search_query
        else:
            title = title_hint or (sendable[0].title if len(sendable) == 1 else None)
        action = {"video": ChatAction.UPLOAD_VIDEO, "audio": ChatAction.UPLOAD_VOICE,
                  "photo": ChatAction.UPLOAD_PHOTO}.get(sendable[0].kind,
                                                        ChatAction.UPLOAD_DOCUMENT)
        async with ChatActionSender(bot=bot, chat_id=chat_id, action=action):
            items = await send_items(bot, chat_id, from_files(sendable),
                                     build_caption(title, bot_username), reply_to)

        skipped = len(files) - len(sendable)
        if skipped:
            await bot.send_message(chat_id, texts.SOME_SKIPPED.format(
                count=fa(skipped), limit=format_size(config.max_file_size)))
        elif config.cache_enabled and items:
            await db.cache_set(job.key, {"title": title, "items": items})
        await db.log_download(user_id, job.platform.value, job.url, True)
    except DownloadError:
        await db.log_download(user_id, job.platform.value, job.url, False)
        raise
    finally:
        await status.stop()
        downloader.cleanup(workdir)


# --------------------------------------------------------------------------- #
#  YouTube: quality menu                                                       #
# --------------------------------------------------------------------------- #

def _thumb(video_id: str, size: str = "hqdefault") -> str:
    return f"https://i.ytimg.com/vi/{video_id}/{size}.jpg"


async def show_youtube_menu(message: Message, status: StatusMessage, url: str,
                            config: Config, downloader: Downloader) -> None:
    if is_youtube_playlist_only(url) or not youtube_id(url):
        raise DownloadError(texts.YT_PLAYLIST)
    info = await downloader.ytdlp.extract(url, Platform.YOUTUBE.value)
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise DownloadError(texts.YT_LIVE)

    qualities = YtDlp.youtube_qualities(info)
    audio_size = YtDlp.audio_size(info)
    request = YoutubeRequest(
        user_id=message.from_user.id if message.from_user else message.chat.id,
        chat_id=message.chat.id,
        reply_to=message.message_id,
        url=info.get("webpage_url") or url,
        video_id=info["id"],
        title=info.get("title") or "YouTube",
        qualities=dict(qualities),
        audio_size=audio_size,
    )
    token = youtube_requests.put(request)
    caption = texts.YT_MENU.format(
        title=esc(truncate(request.title, 200)),
        channel=esc(info.get("channel") or info.get("uploader") or "—"),
        duration=format_duration(info.get("duration")),
    )
    markup = keyboards.youtube_menu(token, qualities, audio_size, config.max_file_size)
    try:
        await message.reply_photo(_thumb(request.video_id), caption=caption, reply_markup=markup)
        await status.delete()
    except TelegramAPIError:
        await status.set(caption, markup)


@router.callback_query(F.data.startswith("yt|"))
async def on_youtube_choice(callback: CallbackQuery, bot: Bot, config: Config, db: Database,
                            downloader: Downloader, bot_username: str) -> None:
    _, token, option = (callback.data or "").split("|", 2)
    request = youtube_requests.get(token)
    msg = callback.message
    if request is None or msg is None:
        await callback.answer(texts.YT_EXPIRED, show_alert=True)
        return
    if request.user_id != callback.from_user.id:
        await callback.answer(texts.YT_NOT_YOURS, show_alert=True)
        return

    if option == "x":
        youtube_requests.pop(token)
        await callback.answer(texts.CANCELLED)
        try:
            await msg.delete()
        except TelegramAPIError:
            pass
        return

    if option == "t":
        await callback.answer()
        caption = texts.YT_THUMB_CAPTION.format(title=esc(truncate(request.title, 200)))
        for size in ("maxresdefault", "hqdefault"):
            try:
                await bot.send_photo(request.chat_id, _thumb(request.video_id, size),
                                     caption=f"{caption}\n\n📥 @{bot_username}")
                break
            except TelegramAPIError:
                continue
        return

    audio = option == "a"
    height = int(option[1:]) if option.startswith("v") and option[1:].isdigit() else None
    if not audio and height is None:
        await callback.answer()
        return
    estimate = request.audio_size if audio else request.qualities.get(height or 0)
    if estimate and estimate > config.max_file_size * 1.05:
        await callback.answer(texts.YT_TOO_BIG_ALERT.format(
            size=format_size(estimate), limit=format_size(config.max_file_size)),
            show_alert=True)
        return
    if request.user_id in active_users:
        await callback.answer(texts.BUSY, show_alert=True)
        return

    await callback.answer()
    active_users.add(request.user_id)
    quality = "MP3" if audio else keyboards.QUALITY_NAMES.get(height, f"{height}p")
    status = StatusMessage(bot, msg.chat.id, msg.message_id, is_caption=bool(msg.photo))
    menu_caption = msg.caption or msg.text or ""
    job = Job(
        platform=Platform.YOUTUBE, url=request.url,
        key=cache_key(Platform.YOUTUBE, request.url, "a" if audio else f"v{height}"),
        audio=audio, height=height,
    )
    try:
        await status.set(texts.YT_CHOSEN.format(quality=quality,
                                                title=esc(truncate(request.title, 150))))
        await run_job(job, status, bot, request.chat_id, request.reply_to, request.user_id,
                      config, db, downloader, bot_username, title_hint=request.title)
        youtube_requests.pop(token)
        await status.delete()
    except DownloadError as exc:
        log.info("YouTube download failed %s: %s", request.url, exc)
        # Show the error and keep the menu so another quality can be picked.
        markup = keyboards.youtube_menu(token, list(request.qualities.items()),
                                        request.audio_size, config.max_file_size)
        await status.set(f"{exc.user_message}\n\n{esc(menu_caption)}", markup)
    except Exception:
        log.exception("Unexpected YouTube error %s", request.url)
        await status.set(texts.ERROR_GENERIC)
    finally:
        active_users.discard(request.user_id)
