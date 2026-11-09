"""Turn whatever cookie export an admin sends (cookies.txt, Cookie-Editor JSON,
or a raw "name=value; ..." header) into the Netscape file yt-dlp/gallery-dl use.
Only cookies of the chosen site are kept."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

DOMAINS = {
    "instagram": "instagram.com",
    "youtube": "youtube.com",
    "pinterest": "pinterest.",
    "soundcloud": "soundcloud.com",
}
SITE = {"instagram": "instagram.com", "youtube": "youtube.com",
        "pinterest": "pinterest.com", "soundcloud": "soundcloud.com"}
SESSION_COOKIES = {
    "instagram": {"sessionid"},
    "youtube": {"SID", "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO"},
    "pinterest": {"_pinterest_sess"},
    "soundcloud": {"oauth_token"},
}
HEADER = "# Netscape HTTP Cookie File\n# Saved by the downloader bot\n\n"


class CookieError(ValueError):
    pass


@dataclass
class ParsedCookies:
    text: str
    count: int
    has_session: bool


def _matches(domain: str, platform: str) -> bool:
    return DOMAINS[platform] in domain.lower()


def _line(domain: str, subdomains: bool, path: str, secure: bool, expires: int,
          name: str, value: str) -> str:
    return "\t".join([domain, "TRUE" if subdomains else "FALSE", path or "/",
                      "TRUE" if secure else "FALSE", str(expires), name, value])


def _from_json(raw: str, platform: str) -> list[tuple[str, str]]:
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("cookies", [])
    if not isinstance(data, list):
        raise CookieError("ساختار JSON شناخته نشد.")
    lines = []
    for c in data:
        if not isinstance(c, dict) or "name" not in c or "domain" not in c:
            continue
        domain = str(c["domain"])
        if not _matches(domain, platform):
            continue
        host_only = bool(c.get("hostOnly", False))
        if not host_only and not domain.startswith("."):
            domain = "." + domain
        expires = int(float(c.get("expirationDate") or c.get("expires") or 0))
        lines.append((c["name"], _line(domain, not host_only, c.get("path", "/"),
                                       bool(c.get("secure", True)), max(expires, 0),
                                       str(c["name"]), str(c.get("value", "")))))
    return lines


def _from_netscape(raw: str, platform: str) -> list[tuple[str, str]]:
    lines = []
    for line in raw.splitlines():
        line = line.strip("\r")
        bare = line[len("#HttpOnly_"):] if line.startswith("#HttpOnly_") else line
        if not bare or bare.startswith("#"):
            continue
        parts = bare.split("\t")
        if len(parts) != 7:
            continue
        if _matches(parts[0], platform):
            lines.append((parts[5], line))
    return lines


def _from_header(raw: str, platform: str) -> list[tuple[str, str]]:
    domain = "." + SITE[platform]
    expires = int(time.time()) + 365 * 86400
    lines = []
    for part in raw.replace("\n", ";").split(";"):
        if "=" not in part:
            continue
        name, value = (s.strip() for s in part.split("=", 1))
        if name:
            lines.append((name, _line(domain, True, "/", True, expires, name, value)))
    return lines


def parse_cookies(raw: str, platform: str) -> ParsedCookies:
    raw = raw.strip().lstrip("﻿")
    if not raw:
        raise CookieError("فایل خالی است.")
    if raw.startswith(("[", "{")):
        try:
            lines = _from_json(raw, platform)
        except json.JSONDecodeError as exc:
            raise CookieError("فایل JSON قابل خواندن نیست.") from exc
    elif "\t" in raw:
        lines = _from_netscape(raw, platform)
    else:
        lines = _from_header(raw, platform)
    if not lines:
        raise CookieError(f"هیچ کوکی‌ای برای {SITE[platform]} در این فایل پیدا نشد.")
    names = {name for name, _ in lines}
    return ParsedCookies(
        text=HEADER + "\n".join(line for _, line in lines) + "\n",
        count=len(lines),
        has_session=bool(names & SESSION_COOKIES[platform]),
    )
