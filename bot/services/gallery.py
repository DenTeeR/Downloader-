"""gallery-dl wrapper (images, carousels, boards). Runs as a subprocess so
each job gets its own isolated configuration."""
from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path

from ..config import Config
from .media import DownloadError, MediaFile, kind_for, media_files_in

log = logging.getLogger(__name__)


async def gallery_download(config: Config, url: str, platform: str, workdir: Path,
                           *, limit: int, timeout: float = 600) -> list[MediaFile]:
    out_dir = workdir / "gallery"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "gallery_dl",
        "--no-mtime",            # mtime = download order, used for sorting
        "--no-part",
        "-D", str(out_dir),
        "--range", f"1-{limit}",
        "--filesize-max", str(config.max_file_size),
    ]
    if config.proxy:
        cmd += ["--proxy", config.proxy]
    cookies = config.cookies_for(platform)
    if cookies:
        private = workdir / "gallery-cookies.txt"
        shutil.copyfile(cookies, private)
        cmd += ["--cookies", str(private)]
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise DownloadError("⏱ زمان دانلود بیش از حد طول کشید.", detail=f"gallery-dl timeout {url}")

    files = media_files_in(out_dir)
    if not files:
        err = stderr.decode(errors="replace")
        log.info("gallery-dl failed (%s) for %s: %s", proc.returncode, url, err[-500:])
        low = err.lower()
        if "login" in low or "authorization" in low or "401" in low or "403" in low:
            raise DownloadError(
                "🔒 این محتوا خصوصی است یا ربات برای دسترسی به آن به کوکی نیاز دارد.",
                detail=err,
            )
        raise DownloadError("❌ فایلی برای دانلود در این لینک پیدا نشد.", detail=err)
    return [MediaFile(path=p, kind=kind_for(p)) for p in files]
