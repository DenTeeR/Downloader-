import pytest

from bot.config import _parse_channels
from bot.platforms import (
    Platform, cache_key, detect_platform, extract_url, is_short_link,
    is_youtube_playlist_only, spotify_parts, youtube_id,
)
from bot.utils import TTLStore, format_size


@pytest.mark.parametrize("url,platform", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", Platform.YOUTUBE),
    ("https://youtu.be/dQw4w9WgXcQ?si=x", Platform.YOUTUBE),
    ("https://m.youtube.com/shorts/dQw4w9WgXcQ", Platform.YOUTUBE),
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", Platform.YOUTUBE),
    ("https://www.instagram.com/reel/C5Zvsk3o9Yq/?igsh=abc", Platform.INSTAGRAM),
    ("https://instagram.com/p/C5Zvsk3o9Yq/", Platform.INSTAGRAM),
    ("https://www.pinterest.com/pin/664281013778109217/", Platform.PINTEREST),
    ("https://ir.pinterest.com/pin/664281013778109217/", Platform.PINTEREST),
    ("https://www.pinterest.co.uk/pin/1/", Platform.PINTEREST),
    ("https://pin.it/4E7Ho7k", Platform.PINTEREST),
    ("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT", Platform.SPOTIFY),
    ("https://spotify.link/abc", Platform.SPOTIFY),
    ("https://soundcloud.com/forss/flickermood", Platform.SOUNDCLOUD),
    ("https://on.soundcloud.com/abc", Platform.SOUNDCLOUD),
    ("https://example.com/video.mp4", None),
    ("https://notyoutube.com/watch?v=dQw4w9WgXcQ", None),
])
def test_detect_platform(url, platform):
    assert detect_platform(url) is platform


def test_extract_url():
    assert extract_url("ببین این رو https://youtu.be/dQw4w9WgXcQ، عالیه") == \
        "https://youtu.be/dQw4w9WgXcQ"
    assert extract_url("(https://pin.it/abc).") == "https://pin.it/abc"
    assert extract_url("no link here") is None


def test_ids_and_keys():
    assert youtube_id("https://youtu.be/dQw4w9WgXcQ?t=3") == "dQw4w9WgXcQ"
    assert youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert is_youtube_playlist_only("https://www.youtube.com/playlist?list=PL123")
    assert not is_youtube_playlist_only("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1")
    assert spotify_parts("https://open.spotify.com/intl-de/track/4cOdK2wGLETKBW3PvgPWqT?si=1") \
        == ("track", "4cOdK2wGLETKBW3PvgPWqT")
    # Same content -> same key, regardless of tracking params / short domain.
    assert cache_key(Platform.YOUTUBE, "https://youtu.be/dQw4w9WgXcQ?si=1", "a") == \
        cache_key(Platform.YOUTUBE, "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "a")
    assert cache_key(Platform.INSTAGRAM, "https://www.instagram.com/reel/ABC/?igsh=1") == \
        cache_key(Platform.INSTAGRAM, "https://instagram.com/reel/ABC")


def test_short_links():
    assert is_short_link("https://pin.it/abc")
    assert is_short_link("https://www.instagram.com/share/reel/abc")
    assert not is_short_link("https://www.instagram.com/reel/abc")


def test_parse_channels():
    chans = _parse_channels("@one, two ,-1001|https://t.me/+xyz")
    assert [(c.chat_id, c.link) for c in chans] == [
        ("@one", "https://t.me/one"), ("@two", "https://t.me/two"),
        ("-1001", "https://t.me/+xyz"),
    ]


def test_utils():
    store: TTLStore[int] = TTLStore()
    key = store.put(5)
    assert len(key) <= 10 and store.get(key) == 5 and store.pop(key) == 5
    assert store.get(key) is None
    assert format_size(1536 * 1024) == "1.5 MB"
