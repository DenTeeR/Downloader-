"""Spotify metadata without API keys, read from the public embed pages.

Spotify streams are DRM protected, so the bot (like every Spotify downloader)
reads the track name/artist/cover from Spotify, finds the same song on
YouTube and tags the resulting MP3 with Spotify's metadata."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from ..platforms import USER_AGENT
from .media import DownloadError

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


@dataclass
class SpotifyTrack:
    id: str
    title: str
    artists: str
    duration: int | None = None  # seconds
    album: str | None = None
    cover_url: str | None = None

    @property
    def search_query(self) -> str:
        return f"{self.artists} - {self.title}"


@dataclass
class SpotifyCollection:
    kind: str  # track | album | playlist
    title: str
    tracks: list[SpotifyTrack]


def _best_image(entity: dict) -> str | None:
    images = (entity.get("visualIdentity") or {}).get("image") or []
    if not images:
        images = (entity.get("coverArt") or {}).get("sources") or []
    images = [i for i in images if isinstance(i, dict) and i.get("url")]
    if not images:
        return None
    return max(images, key=lambda i: i.get("maxWidth") or i.get("width") or 0)["url"]


def _seconds(ms: int | None) -> int | None:
    return int(ms / 1000) if ms else None


async def fetch_spotify(kind: str, item_id: str, proxy: str | None = None) -> SpotifyCollection:
    url = f"https://open.spotify.com/embed/{kind}/{item_id}"
    try:
        async with httpx.AsyncClient(
            timeout=20, proxy=proxy, follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise DownloadError("❌ اطلاعات این لینک از اسپاتیفای دریافت نشد.", detail=str(exc)) from exc

    match = _NEXT_DATA_RE.search(resp.text)
    try:
        data = json.loads(match.group(1)) if match else {}
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise DownloadError("❌ این لینک اسپاتیفای قابل خواندن نیست.", detail=str(exc)) from exc

    title = entity.get("name") or entity.get("title") or "Spotify"
    cover = _best_image(entity)

    if kind == "track":
        artists = ", ".join(a["name"] for a in entity.get("artists") or [] if a.get("name"))
        track = SpotifyTrack(
            id=item_id, title=title, artists=artists or entity.get("subtitle", ""),
            duration=_seconds(entity.get("duration")), cover_url=cover,
        )
        return SpotifyCollection(kind, title, [track])

    tracks = []
    for item in entity.get("trackList") or []:
        uri = item.get("uri") or ""
        if not uri.startswith("spotify:track:") or not item.get("title"):
            continue
        tracks.append(SpotifyTrack(
            id=uri.rsplit(":", 1)[-1],
            title=item["title"],
            artists=(item.get("subtitle") or "").replace("\xa0", " "),
            duration=_seconds(item.get("duration")),
            album=title if kind == "album" else None,
            # Album tracks share the album cover; playlist tracks are looked up later.
            cover_url=cover if kind == "album" else None,
        ))
    if not tracks:
        raise DownloadError("❌ آهنگی در این لینک اسپاتیفای پیدا نشد.")
    return SpotifyCollection(kind, title, tracks)


async def download_bytes(url: str, proxy: str | None = None) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=20, proxy=proxy, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError:
        return None
