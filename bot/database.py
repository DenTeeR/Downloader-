"""SQLite storage: users, download log, and a file_id cache."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    joined_at   INTEGER NOT NULL,
    last_seen   INTEGER NOT NULL,
    is_banned   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    platform    TEXT NOT NULL,
    url         TEXT NOT NULL,
    success     INTEGER NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_downloads_created ON downloads(created_at);
CREATE TABLE IF NOT EXISTS cache (
    key         TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
"""


def _today_start() -> int:
    now = time.localtime()
    return int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1)))


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database.connect() was not called"
        return self._db

    # ---- users -------------------------------------------------------------

    async def touch_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        now = int(time.time())
        await self.db.execute(
            """INSERT INTO users (id, username, first_name, joined_at, last_seen)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 username=excluded.username, first_name=excluded.first_name,
                 last_seen=excluded.last_seen""",
            (user_id, username, first_name, now, now),
        )
        await self.db.commit()

    async def is_banned(self, user_id: int) -> bool:
        async with self.db.execute("SELECT is_banned FROM users WHERE id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        return bool(row and row[0])

    async def set_banned(self, user_id: int, banned: bool) -> bool:
        cur = await self.db.execute(
            "UPDATE users SET is_banned=? WHERE id=?", (int(banned), user_id)
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def all_user_ids(self) -> list[int]:
        async with self.db.execute("SELECT id FROM users WHERE is_banned=0") as cur:
            return [row[0] for row in await cur.fetchall()]

    # ---- downloads ---------------------------------------------------------

    async def log_download(self, user_id: int, platform: str, url: str, success: bool) -> None:
        await self.db.execute(
            "INSERT INTO downloads (user_id, platform, url, success, created_at) VALUES (?,?,?,?,?)",
            (user_id, platform, url, int(success), int(time.time())),
        )
        await self.db.commit()

    async def stats(self) -> dict[str, Any]:
        today = _today_start()

        async def scalar(sql: str, *args: Any) -> int:
            async with self.db.execute(sql, args) as cur:
                row = await cur.fetchone()
            return int(row[0] or 0) if row else 0

        async with self.db.execute(
            "SELECT platform, COUNT(*) FROM downloads WHERE success=1 GROUP BY platform "
            "ORDER BY COUNT(*) DESC"
        ) as cur:
            per_platform = [(row[0], row[1]) for row in await cur.fetchall()]

        return {
            "users": await scalar("SELECT COUNT(*) FROM users"),
            "users_today": await scalar("SELECT COUNT(*) FROM users WHERE joined_at>=?", today),
            "active_today": await scalar("SELECT COUNT(*) FROM users WHERE last_seen>=?", today),
            "banned": await scalar("SELECT COUNT(*) FROM users WHERE is_banned=1"),
            "downloads": await scalar("SELECT COUNT(*) FROM downloads WHERE success=1"),
            "downloads_today": await scalar(
                "SELECT COUNT(*) FROM downloads WHERE success=1 AND created_at>=?", today
            ),
            "failed": await scalar("SELECT COUNT(*) FROM downloads WHERE success=0"),
            "per_platform": per_platform,
        }

    # ---- file_id cache -----------------------------------------------------

    async def cache_get(self, key: str) -> dict[str, Any] | None:
        async with self.db.execute("SELECT payload FROM cache WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    async def cache_set(self, key: str, payload: dict[str, Any]) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO cache (key, payload, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload, ensure_ascii=False), int(time.time())),
        )
        await self.db.commit()

    async def cache_delete(self, key: str) -> None:
        await self.db.execute("DELETE FROM cache WHERE key=?", (key,))
        await self.db.commit()
