"""Link parsing: find the URL in a message, tell which platform it belongs to,
expand short links, and build a stable cache key."""
from __future__ import annotations

import re
from enum import Enum
from urllib.parse import parse_qs, urlparse

import httpx

# Stops at whitespace, quotes and Persian/Arabic punctuation that often follows a link.
URL_RE = re.compile(r"https?://[^\s<>\"'«»،؛]+", re.IGNORECASE)


class Platform(str, Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    PINTEREST = "pinterest"
    SPOTIFY = "spotify"
    SOUNDCLOUD = "soundcloud"


PLATFORM_LABELS = {
    Platform.YOUTUBE: "یوتیوب",
    Platform.INSTAGRAM: "اینستاگرام",
    Platform.PINTEREST: "پینترست",
    Platform.SPOTIFY: "اسپاتیفای",
    Platform.SOUNDCLOUD: "ساندکلود",
}

_DOMAINS: dict[Platform, tuple[str, ...]] = {
    Platform.YOUTUBE: ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    Platform.INSTAGRAM: ("instagram.com", "instagr.am", "ddinstagram.com"),
    Platform.PINTEREST: ("pinterest.com", "pin.it"),
    Platform.SPOTIFY: ("spotify.com", "spotify.link", "spotify.app.link"),
    Platform.SOUNDCLOUD: ("soundcloud.com", "snd.sc", "soundcloud.app.goo.gl"),
}

# Short-link hosts that must be expanded before the URL can be processed.
_SHORT_HOSTS = ("pin.it", "spotify.link", "spotify.app.link", "on.soundcloud.com", "snd.sc",
                "soundcloud.app.goo.gl")

_SPOTIFY_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z]{2}(?:-[a-z]{2})?/|embed/)?"
    r"(track|album|playlist)/([A-Za-z0-9]{22})"
)
_YOUTUBE_ID_RE = re.compile(
    r"(?:v=|/shorts/|/live/|/embed/|youtu\.be/|/v/)([A-Za-z0-9_-]{11})"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


def extract_url(text: str | None) -> str | None:
    if not text:
        return None
    match = URL_RE.search(text)
    return match.group(0).rstrip(".,;!?)]}") if match else None


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def detect_platform(url: str) -> Platform | None:
    host = _host(url)
    for platform, domains in _DOMAINS.items():
        if any(_host_matches(host, d) for d in domains):
            return platform
    # Country domains such as pinterest.de, pinterest.co.uk, ir.pinterest.com
    if re.search(r"(^|\.)pinterest\.[a-z.]+$", host):
        return Platform.PINTEREST
    return None


def is_short_link(url: str) -> bool:
    host = _host(url)
    if _host_matches(host, "instagram.com") and urlparse(url).path.startswith("/share/"):
        return True  # instagram.com/share/... redirects to the real post
    return any(_host_matches(host, h) for h in _SHORT_HOSTS)


async def expand_short_link(url: str, proxy: str | None = None) -> str:
    """Follow redirects of short links (pin.it, spotify.link, on.soundcloud.com...)."""
    if not is_short_link(url):
        return url
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=20, proxy=proxy, headers={"User-Agent": USER_AGENT}
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError:
        return url
    final = str(resp.url)
    # Spotify app links sometimes land on an HTML page that holds the real link.
    if "spotify" in url and not _SPOTIFY_RE.search(final):
        match = _SPOTIFY_RE.search(resp.text)
        if match:
            return f"https://open.spotify.com/{match.group(1)}/{match.group(2)}"
    return final


def spotify_parts(url: str) -> tuple[str, str] | None:
    """Return (kind, id) for a Spotify track/album/playlist URL."""
    match = _SPOTIFY_RE.search(url)
    return (match.group(1), match.group(2)) if match else None


def youtube_id(url: str) -> str | None:
    match = _YOUTUBE_ID_RE.search(url)
    return match.group(1) if match else None


def is_youtube_playlist_only(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.path.rstrip("/") == "/playlist" and "list" in parse_qs(parsed.query)


def cache_key(platform: Platform, url: str, option: str = "") -> str:
    """A stable key for the same content, ignoring tracking query params."""
    if platform is Platform.YOUTUBE and (vid := youtube_id(url)):
        base = f"yt:{vid}"
    elif platform is Platform.SPOTIFY and (parts := spotify_parts(url)):
        base = f"sp:{parts[0]}:{parts[1]}"
    else:
        parsed = urlparse(url)
        base = f"{platform.value}:{_host(url)}{parsed.path.rstrip('/')}"
    return f"{base}:{option}" if option else base
