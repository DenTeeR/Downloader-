FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Deno: the JavaScript runtime yt-dlp needs for YouTube
COPY --from=denoland/deno:bin-2.9.4 /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

ENV PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/bot.db \
    DOWNLOAD_DIR=/app/downloads \
    COOKIES_DIR=/app/cookies

CMD ["python", "-m", "bot"]
