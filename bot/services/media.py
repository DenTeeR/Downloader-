"""Downloaded-file model and ffmpeg/mutagen helpers."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
AUDIO_EXT = {".mp3", ".m4a", ".opus", ".ogg", ".flac", ".wav", ".aac"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ANIMATION_EXT = {".gif"}
IGNORED_EXT = {".part", ".ytdl", ".json", ".txt", ".temp", ".tmp"}


class DownloadError(Exception):
    """A failure whose message can be shown to the user as is."""

    def __init__(self, user_message: str, *, detail: str | None = None) -> None:
        super().__init__(detail or user_message)
        self.user_message = user_message


@dataclass
class MediaFile:
    path: Path
    kind: str  # video | audio | photo | animation | document
    title: str | None = None
    performer: str | None = None
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    thumbnail: Path | None = None

    @property
    def size(self) -> int:
        return self.path.stat().st_size


def kind_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in PHOTO_EXT:
        return "photo"
    if ext in ANIMATION_EXT:
        return "animation"
    return "document"


def media_files_in(directory: Path, exclude: set[Path] | None = None) -> list[Path]:
    """Files in download order (gallery-dl runs with --no-mtime)."""
    exclude = exclude or set()
    files = [
        p for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() not in IGNORED_EXT and p not in exclude
        and not p.name.startswith("tg_thumb_")
    ]
    return sorted(files, key=lambda p: (p.stat().st_mtime, p.name))


async def _run(*cmd: str, timeout: float = 120) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, b"", b"timeout"
    return proc.returncode or 0, out, err


async def probe(path: Path) -> dict:
    """Width, height and duration of a media file via ffprobe."""
    code, out, _ = await _run(
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_entries", "stream=codec_type,width,height:format=duration", str(path),
    )
    if code != 0:
        return {}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {}
    result: dict = {}
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and stream.get("width"):
            result["width"], result["height"] = stream["width"], stream["height"]
            break
    try:
        result["duration"] = int(float(data.get("format", {}).get("duration", 0))) or None
    except (TypeError, ValueError):
        pass
    return result


async def make_thumbnail(source: Path, dest: Path, *, from_video: bool) -> Path | None:
    """A JPEG of at most 320px per side, as Telegram requires for thumbnails."""
    scale = "scale=320:320:force_original_aspect_ratio=decrease"
    attempts = (["-ss", "1"], []) if from_video else ([],)
    for seek in attempts:
        code, _, _ = await _run(
            "ffmpeg", "-y", "-loglevel", "error", *seek, "-i", str(source),
            "-frames:v", "1", "-vf", scale, "-q:v", "4", str(dest),
        )
        if code == 0 and dest.exists() and dest.stat().st_size > 0:
            return dest
    return None


async def to_jpeg(path: Path) -> Path:
    """Convert webp/other images to JPEG so Telegram shows them as photos."""
    if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        return path
    dest = path.with_suffix(".jpg")
    code, _, _ = await _run("ffmpeg", "-y", "-loglevel", "error", "-i", str(path), str(dest))
    if code == 0 and dest.exists():
        path.unlink(missing_ok=True)
        return dest
    return path


async def finalize(files: list[MediaFile]) -> list[MediaFile]:
    """Fill in missing dimensions/durations and build Telegram thumbnails."""
    for index, media in enumerate(files):
        if media.kind == "photo":
            media.path = await to_jpeg(media.path)
            if media.path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                media.kind = "document"
            continue
        if media.kind not in {"video", "audio"}:
            continue
        if media.kind == "video" and not (media.width and media.duration):
            info = await probe(media.path)
            media.width = media.width or info.get("width")
            media.height = media.height or info.get("height")
            media.duration = media.duration or info.get("duration")
        elif media.kind == "audio" and not media.duration:
            media.duration = (await probe(media.path)).get("duration")

        thumb_dest = media.path.parent / f"tg_thumb_{index}.jpg"
        if media.thumbnail and media.thumbnail.exists():
            media.thumbnail = await make_thumbnail(media.thumbnail, thumb_dest, from_video=False)
        elif media.kind == "video":
            media.thumbnail = await make_thumbnail(media.path, thumb_dest, from_video=True)
        else:
            media.thumbnail = None
    return files


def tag_mp3(path: Path, *, title: str, artist: str, album: str | None,
            cover: bytes | None) -> None:
    """Write ID3 tags (and cover art) so music players show the right info."""
    try:
        from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, ID3NoHeaderError
    except ImportError:  # mutagen is optional
        return
    try:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        for frame in ("TIT2", "TPE1", "TALB"):
            tags.delall(frame)
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TPE1(encoding=3, text=artist))
        if album:
            tags.add(TALB(encoding=3, text=album))
        if cover:
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
        tags.save(path)
    except Exception:  # never fail a download because of tags
        log.exception("Could not write ID3 tags to %s", path)
