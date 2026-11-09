"""Bot configuration, loaded from environment variables (or a .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MB = 1024 * 1024


@dataclass(frozen=True)
class Channel:
    """A channel users must join. `chat_id` is @username or -100... id."""

    chat_id: str
    link: str


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    force_join_channels: tuple[Channel, ...]
    bot_api_server: str | None
    max_file_size: int
    max_concurrent_downloads: int
    max_playlist_items: int
    download_dir: Path
    database_path: Path
    cookies_dir: Path
    proxy: str | None
    js_runtime: str
    youtube_pot_url: str | None
    cache_enabled: bool

    def cookies_for(self, platform: str) -> Path | None:
        """Return cookies/<platform>.txt if it exists (Netscape format)."""
        path = self.cookies_dir / f"{platform}.txt"
        return path if path.is_file() else None


def _parse_channels(raw: str) -> tuple[Channel, ...]:
    """Parse "@ch1, -1001234|https://t.me/+invite" into Channel objects."""
    channels = []
    for item in filter(None, (part.strip() for part in raw.split(","))):
        if "|" in item:
            chat_id, link = (s.strip() for s in item.split("|", 1))
        else:
            chat_id = item if item.startswith(("@", "-")) else f"@{item}"
            link = f"https://t.me/{chat_id.lstrip('@')}"
        channels.append(Channel(chat_id=chat_id, link=link))
    return tuple(channels)


def _bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    api_server = os.getenv("BOT_API_SERVER", "").strip() or None
    # The public Bot API accepts uploads up to 50 MB; a local Bot API server up to 2000 MB.
    default_limit = 2000 if api_server else 50
    max_mb = int(os.getenv("MAX_FILE_SIZE_MB", "").strip() or default_limit)

    return Config(
        bot_token=token,
        admin_ids=frozenset(
            int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
        ),
        force_join_channels=_parse_channels(os.getenv("FORCE_JOIN_CHANNELS", "")),
        bot_api_server=api_server,
        max_file_size=max_mb * MB,
        max_concurrent_downloads=int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3")),
        max_playlist_items=int(os.getenv("MAX_PLAYLIST_ITEMS", "10")),
        download_dir=Path(os.getenv("DOWNLOAD_DIR", "downloads")).resolve(),
        database_path=Path(os.getenv("DATABASE_PATH", "data/bot.db")).resolve(),
        cookies_dir=Path(os.getenv("COOKIES_DIR", "cookies")).resolve(),
        proxy=os.getenv("PROXY", "").strip() or None,
        js_runtime=os.getenv("JS_RUNTIME", "deno").strip().lower() or "deno",
        youtube_pot_url=os.getenv("YOUTUBE_POT_URL", "").strip() or None,
        cache_enabled=_bool(os.getenv("CACHE_ENABLED"), True),
    )
