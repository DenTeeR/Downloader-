"""Turns a link into download jobs and runs them with the right tool."""
from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ..config import Config
from ..platforms import Platform, cache_key, spotify_parts
from .gallery import gallery_download
from .media import DownloadError, MediaFile, finalize, tag_mp3
from .spotify import SpotifyTrack, download_bytes, fetch_spotify
from .ytdlp import ProgressCallback, YtDlp

_INSTAGRAM_CONTENT = {"p", "reel", "reels", "tv", "stories", "share"}


@dataclass
class Job:
    """One item to download and send (a video, a post, a single track...)."""

    platform: Platform
    url: str
    key: str                       # cache key
    index: int = 0                 # position in a playlist (1-based), 0 = single item
    total: int = 0
    audio: bool = False
    height: int | None = None
    spotify: SpotifyTrack | None = field(default=None, repr=False)


@dataclass
class Plan:
    title: str | None
    jobs: list[Job]
    truncated_from: int | None = None  # original count when a list was cut


class Downloader:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.ytdlp = YtDlp(config)
        self.semaphore = asyncio.Semaphore(config.max_concurrent_downloads)
        config.download_dir.mkdir(parents=True, exist_ok=True)

    # ---- workdirs ----------------------------------------------------------

    def new_workdir(self) -> Path:
        path = self.config.download_dir / uuid.uuid4().hex
        path.mkdir(parents=True)
        return path

    @staticmethod
    def cleanup(path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)

    def cleanup_all(self) -> None:
        for child in self.config.download_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)

    # ---- planning ----------------------------------------------------------

    def _limit(self, jobs: list[Job]) -> tuple[list[Job], int | None]:
        limit = self.config.max_playlist_items
        if len(jobs) > limit:
            return jobs[:limit], len(jobs)
        return jobs, None

    async def plan(self, platform: Platform, url: str) -> Plan:
        """Resolve a (non-YouTube) link into one or more jobs."""
        if platform is Platform.SPOTIFY:
            parts = spotify_parts(url)
            if not parts:
                raise DownloadError("err_spotify_link")
            collection = await fetch_spotify(*parts, proxy=self.config.proxy)
            jobs = [
                Job(platform, f"https://open.spotify.com/track/{t.id}",
                    key=f"sp:track:{t.id}:mp3", audio=True, spotify=t)
                for t in collection.tracks
            ]
            jobs, total = self._limit(jobs)
            self._number(jobs)
            title = collection.title if collection.kind != "track" else None
            return Plan(title, jobs, total)

        if platform is Platform.SOUNDCLOUD:
            info = await self.ytdlp.extract(url, platform.value, flat=True)
            if info.get("_type") == "playlist":
                entries = [e for e in info.get("entries") or [] if e and e.get("url")]
                if not entries:
                    raise DownloadError("err_playlist_empty")
                jobs = [
                    Job(platform, e["url"], key=cache_key(platform, e["url"], "mp3"), audio=True)
                    for e in entries
                ]
                jobs, total = self._limit(jobs)
                self._number(jobs)
                return Plan(info.get("title"), jobs, total)
            return Plan(None, [Job(platform, url, cache_key(platform, url, "mp3"), audio=True)])

        if platform is Platform.INSTAGRAM:
            segments = [s for s in urlparse(url).path.split("/") if s]
            if not segments or not (_INSTAGRAM_CONTENT & set(segments)):
                raise DownloadError("err_ig_profile")

        return Plan(None, [Job(platform, url, cache_key(platform, url))])

    @staticmethod
    def _number(jobs: list[Job]) -> None:
        if len(jobs) > 1:
            for i, job in enumerate(jobs, 1):
                job.index, job.total = i, len(jobs)

    # ---- running -----------------------------------------------------------

    async def run(self, job: Job, workdir: Path,
                  progress: ProgressCallback | None = None) -> list[MediaFile]:
        if job.platform is Platform.SPOTIFY and job.spotify:
            files = await self._spotify(job.spotify, workdir, progress)
        elif job.platform is Platform.INSTAGRAM:
            files = await self._gallery_first(job, workdir, progress)
        elif job.platform is Platform.PINTEREST:
            if "/pin/" in job.url:
                files = await self._ytdlp_first(job, workdir, progress)
            else:  # boards and sections
                files = await gallery_download(
                    self.config, job.url, job.platform.value, workdir,
                    limit=self.config.max_playlist_items,
                )
        else:  # YouTube, SoundCloud
            files = await self.ytdlp.download(
                job.url, job.platform.value, workdir,
                audio=job.audio, height=job.height, progress=progress,
            )
        return await finalize(files)

    async def _gallery_first(self, job: Job, workdir: Path,
                             progress: ProgressCallback | None) -> list[MediaFile]:
        """Instagram: gallery-dl handles carousels of photos and videos."""
        try:
            # A carousel holds up to 20 items and is still a single post.
            return await gallery_download(
                self.config, job.url, job.platform.value, workdir,
                limit=max(20, self.config.max_playlist_items),
            )
        except DownloadError as first:
            try:
                return await self.ytdlp.download(job.url, job.platform.value, workdir,
                                                 progress=progress)
            except DownloadError:
                raise first

    async def _ytdlp_first(self, job: Job, workdir: Path,
                           progress: ProgressCallback | None) -> list[MediaFile]:
        """Pinterest pins: yt-dlp for videos, gallery-dl for image pins."""
        try:
            return await self.ytdlp.download(job.url, job.platform.value, workdir,
                                             progress=progress)
        except DownloadError:
            return await gallery_download(self.config, job.url, job.platform.value, workdir,
                                          limit=self.config.max_playlist_items)

    async def _spotify(self, track: SpotifyTrack, workdir: Path,
                       progress: ProgressCallback | None) -> list[MediaFile]:
        if not track.cover_url:  # playlist entries: look up the track page for its cover
            try:
                full = await fetch_spotify("track", track.id, proxy=self.config.proxy)
                track.cover_url = full.tracks[0].cover_url
            except DownloadError:
                pass

        files: list[MediaFile] = []
        error: DownloadError | None = None
        for site in ("youtube", "soundcloud"):  # SoundCloud if YouTube is blocked/missing
            for source in await self.ytdlp.search_songs(track.search_query, track.duration, site):
                try:
                    files = await self.ytdlp.download(source, site, workdir, audio=True,
                                                      progress=progress)
                    break
                except DownloadError as exc:
                    error = error or exc
            if files:
                break
        if not files:
            raise error or DownloadError("err_song_not_found", title=track.title)
        media = files[0]

        cover = await download_bytes(track.cover_url, self.config.proxy) if track.cover_url else None
        if cover:
            cover_path = workdir / "spotify_cover.jpg"
            cover_path.write_bytes(cover)
            media.thumbnail = cover_path
        await asyncio.to_thread(tag_mp3, media.path, title=track.title, artist=track.artists,
                                album=track.album, cover=cover)
        # Give the file a readable name, as shown in Telegram's music player.
        safe = "".join(c for c in f"{track.artists} - {track.title}" if c not in '\\/:*?"<>|')
        named = media.path.with_name(f"{safe[:120]}.mp3")
        media.path = media.path.rename(named)
        media.title, media.performer, media.duration = track.title, track.artists, \
            track.duration or media.duration
        return [media]
