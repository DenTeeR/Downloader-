"""yt-dlp wrapper: info extraction, YouTube quality list, video/audio download."""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Callable

import yt_dlp
from yt_dlp.utils import DownloadError as YtDownloadError

from ..config import Config
from .media import DownloadError, MediaFile, kind_for, media_files_in

log = logging.getLogger(__name__)

# downloaded_bytes, total_bytes (may be None), speed in bytes/s (may be None)
ProgressCallback = Callable[[int, int | None, float | None], None]

YOUTUBE_HEIGHTS = (144, 240, 360, 480, 720, 1080, 1440, 2160)


def friendly_error(exc: Exception, platform: str) -> DownloadError:
    text = str(exc).lower()
    if "sign in" in text or "login" in text or "cookies" in text or "private" in text \
            or "empty media response" in text or "not granting access" in text:
        key = {"instagram": "err_ig_login", "youtube": "err_yt_login"}.get(platform, "err_login")
    elif platform == "youtube" and ("403" in text or "forbidden" in text):
        key = "err_yt_blocked"
    elif "unavailable" in text or "not available" in text or "404" in text or "removed" in text:
        key = "err_unavailable"
    elif "drm" in text:
        key = "err_drm"
    elif "unsupported url" in text:
        key = "err_unsupported_link"
    elif "no video formats" in text or "no video in this post" in text:
        key = "err_no_media"
    elif "live" in text and "stream" in text:
        key = "yt_live"
    else:
        key = "err_download"
    return DownloadError(key, detail=str(exc))


class _Logger:
    """Route yt-dlp output to logging instead of stderr (errors are raised anyway)."""

    def debug(self, msg: str) -> None:
        pass

    info = debug

    def warning(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    error = warning


class YtDlp:
    def __init__(self, config: Config) -> None:
        self.config = config

    # ---- options -----------------------------------------------------------

    def _opts(self, platform: str, workdir: Path | None = None,
              progress: ProgressCallback | None = None) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "logger": _Logger(),
            "noprogress": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 4,
            "js_runtimes": {self.config.js_runtime: {}},
            "max_filesize": self.config.max_file_size,
        }
        if workdir is not None:
            opts["outtmpl"] = str(workdir / "%(id).60B.%(ext)s")
            opts["paths"] = {"home": str(workdir), "temp": str(workdir)}
        if self.config.proxy:
            opts["proxy"] = self.config.proxy
        if self.config.youtube_pot_url:
            # bgutil PO-token provider: helps YouTube downloads from server IPs.
            opts["extractor_args"] = {
                "youtubepot-bgutilhttp": {"base_url": [self.config.youtube_pot_url]},
            }
        cookies = self.config.cookies_for(platform)
        if cookies:
            # yt-dlp writes cookies back on exit; use a private copy per job.
            if workdir is not None:
                private = workdir / "cookies.txt"
                shutil.copyfile(cookies, private)
                opts["cookiefile"] = str(private)
            else:
                opts["cookiefile"] = str(cookies)
        if progress is not None:
            opts["progress_hooks"] = [self._hook(progress)]
        return opts

    @staticmethod
    def _hook(callback: ProgressCallback) -> Callable[[dict], None]:
        def hook(d: dict) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                try:
                    callback(int(d.get("downloaded_bytes") or 0),
                             int(total) if total else None, d.get("speed"))
                except Exception:  # progress must never break a download
                    pass
        return hook

    # ---- info --------------------------------------------------------------

    def _extract_sync(self, url: str, platform: str, flat: bool) -> dict:
        opts = self._opts(platform)
        opts.pop("max_filesize")
        if flat:
            opts["extract_flat"] = "in_playlist"
            opts["noplaylist"] = False
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return ydl.sanitize_info(info)

    async def extract(self, url: str, platform: str, *, flat: bool = False) -> dict:
        try:
            return await asyncio.to_thread(self._extract_sync, url, platform, flat)
        except YtDownloadError as exc:
            raise friendly_error(exc, platform) from exc

    @staticmethod
    def youtube_qualities(info: dict) -> list[tuple[int, int | None]]:
        """(height, estimated size in bytes) for each standard resolution available."""
        formats = info.get("formats") or []
        duration = info.get("duration") or 0

        def size(fmt: dict) -> int | None:
            value = fmt.get("filesize") or fmt.get("filesize_approx")
            if not value and fmt.get("tbr") and duration:
                value = fmt["tbr"] * 1000 / 8 * duration
            return int(value) if value else None

        audio_sizes = [
            size(f) for f in formats
            if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")
            and f.get("ext") == "m4a"
        ]
        audio_size = max((s for s in audio_sizes if s), default=0)

        result = []
        for height in YOUTUBE_HEIGHTS:
            candidates = [
                f for f in formats
                if f.get("vcodec") not in (None, "none") and f.get("height") == height
                and f.get("protocol", "https").startswith("http")
            ]
            if not candidates:
                continue
            # Prefer h264 (what we ask yt-dlp for), otherwise the smallest estimate.
            h264 = [f for f in candidates if str(f.get("vcodec", "")).startswith("avc")]
            pool = h264 or candidates
            sizes = [s for s in (size(f) for f in pool) if s]
            video_size = max(sizes) if h264 and sizes else (min(sizes) if sizes else None)
            muxed = all(f.get("acodec") not in (None, "none") for f in pool)
            total = (video_size + (0 if muxed else audio_size)) if video_size else None
            result.append((height, total))
        return result

    @staticmethod
    def audio_size(info: dict) -> int | None:
        sizes = [
            f.get("filesize") or f.get("filesize_approx") for f in info.get("formats") or []
            if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")
        ]
        best = max((s for s in sizes if s), default=None)
        # mp3 at 192 kbps vs. source (~128-160 kbps): a rough estimate is enough.
        if best:
            return int(best * 1.3)
        duration = info.get("duration")
        return int(duration * 192_000 / 8) if duration else None

    # ---- download ----------------------------------------------------------

    def _download_sync(self, url: str, platform: str, workdir: Path, *, audio: bool,
                       height: int | None, progress: ProgressCallback | None) -> list[MediaFile]:
        opts = self._opts(platform, workdir, progress)
        opts["writethumbnail"] = True
        thumb_pp = {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}
        if audio:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [
                thumb_pp,
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "EmbedThumbnail", "already_have_thumbnail": True},
            ]
        else:
            if height:
                opts["format"] = f"bv*[height<={height}]+ba/b[height<={height}]/b"
            else:
                opts["format"] = "bv*+ba/b"
            # Telegram plays h264/aac in mp4 everywhere; prefer it at equal resolution.
            opts["format_sort"] = ["res", "vcodec:h264", "acodec:aac"]
            opts["merge_output_format"] = "mp4"
            opts["postprocessors"] = [thumb_pp]

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=True))

        entries = info.get("entries") or [info]
        files: list[MediaFile] = []
        seen: set[Path] = set()
        for entry in entries:
            if not entry:
                continue
            path = None
            for item in entry.get("requested_downloads") or []:
                candidate = item.get("filepath")
                if candidate and Path(candidate).exists():
                    path = Path(candidate)
            if path is None:
                continue
            thumb = next(
                (Path(t["filepath"]) for t in entry.get("thumbnails") or []
                 if t.get("filepath") and Path(t["filepath"]).exists()),
                None,
            )
            seen.update(p for p in (path, thumb) if p)
            files.append(MediaFile(
                path=path,
                kind="audio" if audio else kind_for(path),
                title=entry.get("track") or entry.get("title"),
                performer=entry.get("artist") or entry.get("uploader") or entry.get("channel"),
                duration=int(entry["duration"]) if entry.get("duration") else None,
                width=entry.get("width"),
                height=entry.get("height"),
                thumbnail=thumb,
            ))

        if not files:
            # Fall back to whatever landed in the folder.
            leftovers = [p for p in media_files_in(workdir, seen) if p.name != "cookies.txt"
                         and kind_for(p) in {"video", "audio"}]
            files = [MediaFile(path=p, kind=kind_for(p), title=info.get("title")) for p in leftovers]
        if not files:
            raise DownloadError("err_too_large_or_empty", detail=f"no output file for {url}")
        return files

    async def download(self, url: str, platform: str, workdir: Path, *, audio: bool = False,
                       height: int | None = None,
                       progress: ProgressCallback | None = None) -> list[MediaFile]:
        try:
            return await asyncio.to_thread(
                self._download_sync, url, platform, workdir,
                audio=audio, height=height, progress=progress,
            )
        except YtDownloadError as exc:
            raise friendly_error(exc, platform) from exc

    # ---- search (used for Spotify) ----------------------------------------

    async def search_songs(self, query: str, duration: int | None,
                           site: str = "youtube", limit: int = 3) -> list[str]:
        """Candidate URLs for a song on YouTube or SoundCloud, best first.
        Similar duration is preferred (this also skips 30-second previews)."""
        prefix = {"youtube": "ytsearch6", "soundcloud": "scsearch8"}[site]
        try:
            info = await self.extract(f"{prefix}:{query}", site, flat=True)
        except DownloadError:
            return []
        entries = [e for e in info.get("entries") or [] if e and (e.get("url") or e.get("id"))]
        if duration:
            close = sorted(
                (e for e in entries if e.get("duration") and abs(e["duration"] - duration) <= 15),
                key=lambda e: abs(e["duration"] - duration),
            )
            # SoundCloud results with a different length are rarely the right song.
            entries = close if site == "soundcloud" else close + [e for e in entries
                                                                  if e not in close]
        urls = []
        for entry in entries[:limit]:
            if site == "youtube":
                urls.append(f"https://www.youtube.com/watch?v={entry['id']}")
            elif entry.get("url"):
                urls.append(entry["url"])
        return urls
