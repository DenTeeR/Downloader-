"""The main flow: user sends a link -> bot downloads -> bot sends the files.
Every message shown here is a designable screen (see bot/ui/texts.py)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from ..alerts import maybe_alert_cookies
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
from ..ui import Btn, Design, Raw
from ..ui.keyboards import QUALITY_NAMES
from ..ui.menus import media_keyboard
from ..ui.screens import send_screen
from ..utils import TTLStore, fa, format_duration, format_size, truncate

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
    channel: str
    duration: str
    qualities: dict[int, int | None] = field(default_factory=dict)
    audio_size: int | None = None


youtube_requests: TTLStore[YoutubeRequest] = TTLStore(ttl=3600)


def build_caption(design: Design, title: str | None, bot_username: str) -> str:
    if title and title.strip():
        return design.text("media_caption", title=truncate(title.strip(), 300), bot=bot_username)
    return design.text("media_caption_notitle", bot=bot_username)


async def report_error(bot: Bot, config: Config, status: StatusMessage | None,
                       exc: DownloadError, suffix: str = "", markup=None) -> None:
    await maybe_alert_cookies(bot, config, exc.key)
    if status:
        await status.show(exc.key, markup, suffix=suffix, **exc.params)


# --------------------------------------------------------------------------- #
#  Incoming links                                                              #
# --------------------------------------------------------------------------- #

@router.message(F.text | F.caption)
async def on_message(message: Message, bot: Bot, config: Config, db: Database,
                     design: Design, downloader: Downloader, bot_username: str) -> None:
    private = message.chat.type == ChatType.PRIVATE
    url = extract_url(message.text or message.caption)
    if not url:
        if private:
            await send_screen(bot, message.chat.id, design, "send_link")
        return
    platform = detect_platform(url)
    if platform is None:
        if private:
            await send_screen(bot, message.chat.id, design, "unsupported",
                              reply_to=message.message_id)
        return

    user_id = message.from_user.id if message.from_user else message.chat.id
    if user_id in active_users:
        await send_screen(bot, message.chat.id, design, "busy", reply_to=message.message_id)
        return

    active_users.add(user_id)
    status: StatusMessage | None = None
    try:
        status = await StatusMessage.create(bot, design, message.chat.id, message.message_id,
                                            "checking")
        url = await expand_short_link(url, config.proxy)
        platform = detect_platform(url) or platform
        if platform is Platform.YOUTUBE:
            await show_youtube_menu(message, bot, status, url, config, design, downloader)
            return
        plan = await downloader.plan(platform, url)
        await run_plan(plan, status, bot, message.chat.id, message.message_id, user_id,
                       config, db, design, downloader, bot_username)
    except DownloadError as exc:
        log.info("Download failed for %s: %s", url, exc)
        await report_error(bot, config, status, exc)
    except Exception:
        log.exception("Unexpected error for %s", url)
        if status:
            await status.show("error_generic")
    finally:
        if status:
            await status.stop()
        active_users.discard(user_id)


async def run_plan(plan: Plan, status: StatusMessage, bot: Bot, chat_id: int, reply_to: int,
                   user_id: int, config: Config, db: Database, design: Design,
                   downloader: Downloader, bot_username: str) -> None:
    if len(plan.jobs) == 1:
        await run_job(plan.jobs[0], status, bot, chat_id, reply_to, user_id,
                      config, db, design, downloader, bot_username)
        await status.delete()
        return

    banner = design.text("playlist_header", title=plan.title or "Playlist",
                         count=fa(len(plan.jobs)))
    if plan.truncated_from:
        banner += design.text("playlist_truncated", total=fa(plan.truncated_from),
                              count=fa(len(plan.jobs)))
    status.banner = banner
    ok = 0
    for job in plan.jobs:
        try:
            await run_job(job, status, bot, chat_id, None, user_id,
                          config, db, design, downloader, bot_username)
            ok += 1
        except DownloadError as exc:
            log.info("Playlist item failed %s: %s", job.url, exc)
            await maybe_alert_cookies(bot, config, exc.key)
            item = job.spotify.search_query if job.spotify else job.url
            await bot.send_message(chat_id, design.text(
                "playlist_item_failed", error=Raw(design.text(exc.key, **exc.params)), item=item))
        except Exception:
            log.exception("Playlist item crashed %s", job.url)
    status.prefix = ""
    await status.show("playlist_done", ok=fa(ok), total=fa(len(plan.jobs)))


async def run_job(job: Job, status: StatusMessage, bot: Bot, chat_id: int,
                  reply_to: int | None, user_id: int, config: Config, db: Database,
                  design: Design, downloader: Downloader, bot_username: str,
                  title_hint: str | None = None) -> None:
    """Download one job and send it; raises DownloadError on failure."""
    status.prefix = design.text("item_label", index=fa(job.index), total=fa(job.total)) \
        if job.total else ""
    keyboard = media_keyboard(design)

    # 1) Already sent before? Re-send by file_id, no download needed.
    if config.cache_enabled and (cached := await db.cache_get(job.key)):
        try:
            await status.show("from_cache")
            await send_items(bot, chat_id, from_cache(cached["items"]),
                             build_caption(design, cached.get("title"), bot_username),
                             reply_to, keyboard)
            await db.log_download(user_id, job.platform.value, job.url, True)
            return
        except TelegramBadRequest:
            await db.cache_delete(job.key)  # stale file_id (e.g. bot token changed)

    # 2) Download.
    workdir = downloader.new_workdir()
    try:
        if downloader.semaphore.locked():
            await status.show("queued")
        async with downloader.semaphore:
            await status.start_progress("downloading")
            files = await downloader.run(job, workdir, progress=status.report)
            await status.stop()

        sendable = [f for f in files if f.size <= config.max_file_size]
        if not sendable:
            raise DownloadError("too_large", size=format_size(max(f.size for f in files)),
                                limit=format_size(config.max_file_size))

        # 3) Upload.
        await status.show("uploading")
        if job.spotify:
            title = job.spotify.search_query
        else:
            title = title_hint or (sendable[0].title if len(sendable) == 1 else None)
        action = {"video": ChatAction.UPLOAD_VIDEO, "audio": ChatAction.UPLOAD_VOICE,
                  "photo": ChatAction.UPLOAD_PHOTO}.get(sendable[0].kind,
                                                        ChatAction.UPLOAD_DOCUMENT)
        async with ChatActionSender(bot=bot, chat_id=chat_id, action=action):
            items = await send_items(bot, chat_id, from_files(sendable),
                                     build_caption(design, title, bot_username),
                                     reply_to, keyboard)

        skipped = len(files) - len(sendable)
        if skipped:
            await send_screen(bot, chat_id, design, "some_skipped", count=fa(skipped),
                              limit=format_size(config.max_file_size))
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


def youtube_keyboard(design: Design, token: str, request: YoutubeRequest, limit: int):
    buttons: dict[str, Btn] = {}
    for height, size in request.qualities.items():
        if height in QUALITY_NAMES:
            buttons[f"q{height}"] = Btn(callback=f"yt|{token}|v{height}", params={
                "quality": QUALITY_NAMES[height], "size": format_size(size),
                "warn": " ⛔️" if size and size > limit else "",
            })
    buttons["audio"] = Btn(callback=f"yt|{token}|a",
                           params={"size": format_size(request.audio_size)})
    buttons["thumb"] = Btn(callback=f"yt|{token}|t")
    buttons["cancel"] = Btn(callback=f"yt|{token}|x")
    return design.keyboard("youtube", buttons)


async def show_youtube_menu(message: Message, bot: Bot, status: StatusMessage, url: str,
                            config: Config, design: Design, downloader: Downloader) -> None:
    if is_youtube_playlist_only(url) or not youtube_id(url):
        raise DownloadError("yt_playlist")
    info = await downloader.ytdlp.extract(url, Platform.YOUTUBE.value)
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        raise DownloadError("yt_live")

    request = YoutubeRequest(
        user_id=message.from_user.id if message.from_user else message.chat.id,
        chat_id=message.chat.id,
        reply_to=message.message_id,
        url=info.get("webpage_url") or url,
        video_id=info["id"],
        title=info.get("title") or "YouTube",
        channel=info.get("channel") or info.get("uploader") or "—",
        duration=format_duration(info.get("duration")),
        qualities=dict(YtDlp.youtube_qualities(info)),
        audio_size=YtDlp.audio_size(info),
    )
    token = youtube_requests.put(request)
    caption = design.text("yt_menu", title=truncate(request.title, 200),
                          channel=request.channel, duration=request.duration)
    markup = youtube_keyboard(design, token, request, config.max_file_size)
    await status.delete()
    if sticker := design.sticker("yt_menu"):
        try:
            await bot.send_sticker(message.chat.id, sticker)
        except TelegramAPIError:
            pass
    try:
        await message.reply_photo(_thumb(request.video_id), caption=caption, reply_markup=markup)
    except TelegramAPIError:
        await message.reply(caption, reply_markup=markup)


@router.callback_query(F.data.startswith("yt|"))
async def on_youtube_choice(callback: CallbackQuery, bot: Bot, config: Config, db: Database,
                            design: Design, downloader: Downloader, bot_username: str) -> None:
    _, token, option = (callback.data or "").split("|", 2)
    request = youtube_requests.get(token)
    msg = callback.message
    if request is None or not isinstance(msg, Message):
        await callback.answer(design.text("yt_expired"), show_alert=True)
        return
    if request.user_id != callback.from_user.id:
        await callback.answer(design.text("yt_not_yours"), show_alert=True)
        return

    if option == "x":
        youtube_requests.pop(token)
        await callback.answer(design.text("cancelled"))
        try:
            await msg.delete()
        except TelegramAPIError:
            pass
        return

    if option == "t":
        await callback.answer()
        caption = design.text("yt_thumb_caption", title=truncate(request.title, 200),
                              bot=bot_username)
        for size in ("maxresdefault", "hqdefault"):
            try:
                await bot.send_photo(request.chat_id, _thumb(request.video_id, size),
                                     caption=caption, reply_markup=media_keyboard(design))
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
        await callback.answer(design.text("yt_too_big", size=format_size(estimate),
                                          limit=format_size(config.max_file_size)),
                              show_alert=True)
        return
    if request.user_id in active_users:
        await callback.answer(design.text("busy_alert"), show_alert=True)
        return

    await callback.answer()
    active_users.add(request.user_id)
    quality = "MP3" if audio else QUALITY_NAMES.get(height or 0, f"{height}p")
    status = StatusMessage(bot, design, msg.chat.id, msg.message_id, is_caption=bool(msg.photo))
    job = Job(
        platform=Platform.YOUTUBE, url=request.url,
        key=cache_key(Platform.YOUTUBE, request.url, "a" if audio else f"v{height}"),
        audio=audio, height=height,
    )
    try:
        await status.show("yt_chosen", quality=quality, title=truncate(request.title, 150))
        await run_job(job, status, bot, request.chat_id, request.reply_to, request.user_id,
                      config, db, design, downloader, bot_username, title_hint=request.title)
        youtube_requests.pop(token)
        await status.delete()
    except DownloadError as exc:
        log.info("YouTube download failed %s: %s", request.url, exc)
        # Show the error and keep the menu so another quality can be picked.
        menu = design.text("yt_menu", title=truncate(request.title, 200),
                           channel=request.channel, duration=request.duration)
        await report_error(bot, config, status, exc, suffix=f"\n\n{menu}",
                           markup=youtube_keyboard(design, token, request, config.max_file_size))
    except Exception:
        log.exception("Unexpected YouTube error %s", request.url)
        await status.show("error_generic")
    finally:
        active_users.discard(request.user_id)
