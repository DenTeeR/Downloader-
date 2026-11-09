"""Default text of every screen. Admins can override each one from the bot
(/admin → 🎨 طراحی) with formatting, premium emoji and a sticker."""
from __future__ import annotations

from .specs import TextSpec

CATEGORIES = {
    "general": "🏠 عمومی",
    "join": "🔒 عضویت اجباری",
    "progress": "⏳ مراحل دانلود",
    "youtube": "▶️ یوتیوب",
    "errors": "❌ خطاها",
    "commands": "⌨️ منوی دستورات",
}

_SIZE = {"size": "25.3 MB", "limit": "50.0 MB"}

_SPECS = [
    # ---- general ---------------------------------------------------------
    TextSpec(
        "start", "صفحه شروع (/start)", category="general", placeholders=("name", "bot"),
        sample={"name": "علی", "bot": "MyBot"},
        default=(
            "سلام {name} 👋\n\n"
            "به ربات دانلودر خوش اومدی! 🎉\n"
            "کافیه لینک محتوای مورد نظرت رو برام بفرستی تا دانلودش کنم و برات بفرستم.\n\n"
            "📥 <b>پلتفرم‌های پشتیبانی شده:</b>\n"
            "▫️ <b>اینستاگرام</b> — پست، ریلز، کاروسل، استوری\n"
            "▫️ <b>یوتیوب</b> — ویدیو و شورتس با انتخاب کیفیت، یا فقط صدا (MP3)\n"
            "▫️ <b>پینترست</b> — عکس و ویدیو\n"
            "▫️ <b>اسپاتیفای</b> — آهنگ، آلبوم و پلی‌لیست (MP3 با کاور)\n"
            "▫️ <b>ساندکلود</b> — آهنگ و پلی‌لیست (MP3)\n\n"
            "🔗 همین الان یه لینک بفرست!"
        ),
    ),
    TextSpec(
        "help", "راهنما (/help)", category="general", placeholders=("max_size", "max_items"),
        sample={"max_size": "50.0 MB", "max_items": "۱۰"},
        default=(
            "📖 <b>راهنمای ربات</b>\n\n"
            "1️⃣ لینک را از برنامه (اینستاگرام، یوتیوب، ...) کپی کنید.\n"
            "2️⃣ لینک را همینجا برای ربات بفرستید.\n"
            "3️⃣ برای یوتیوب کیفیت دلخواه را انتخاب کنید؛ بقیه موارد خودکار دانلود می‌شوند.\n\n"
            "📌 <b>نمونه لینک‌ها:</b>\n"
            "<code>https://www.instagram.com/reel/...</code>\n"
            "<code>https://youtu.be/...</code>\n"
            "<code>https://pin.it/...</code>\n"
            "<code>https://open.spotify.com/track/...</code>\n"
            "<code>https://soundcloud.com/artist/track</code>\n\n"
            "⚠️ حداکثر حجم هر فایل: <b>{max_size}</b>\n"
            "⚠️ برای آلبوم و پلی‌لیست حداکثر <b>{max_items}</b> مورد دانلود می‌شود."
        ),
    ),
    TextSpec("send_link", "پیام بدون لینک", category="general",
             default="🔗 لطفا یک لینک بفرستید. برای راهنما /help را بزنید."),
    TextSpec("unsupported", "لینک پشتیبانی‌نشده", category="general", default=(
        "❌ این لینک پشتیبانی نمی‌شود.\n\n"
        "فقط لینک‌های <b>اینستاگرام، یوتیوب، پینترست، اسپاتیفای و ساندکلود</b> را بفرستید."
    )),
    TextSpec("busy", "دانلود قبلی در جریان است", category="general",
             default="⏳ یک دانلود دیگر برای شما در حال انجام است. لطفا تا پایان آن صبر کنید."),
    TextSpec("busy_alert", "دانلود قبلی در جریان است (پیام پاپ‌آپ)", category="general",
             plain=True, default="⏳ یک دانلود دیگر برای شما در حال انجام است."),
    TextSpec("banned", "کاربر مسدود", category="general",
             default="⛔️ دسترسی شما به ربات مسدود شده است."),
    TextSpec("cancelled", "لغو شد", category="general", plain=True, default="❌ لغو شد."),
    TextSpec("media_caption", "کپشن فایل ارسالی (با عنوان)", category="general",
             placeholders=("title", "bot"), sample={"title": "Never Gonna Give You Up", "bot": "MyBot"},
             default="<b>{title}</b>\n\n📥 @{bot}"),
    TextSpec("media_caption_notitle", "کپشن فایل ارسالی (بدون عنوان)", category="general",
             placeholders=("bot",), sample={"bot": "MyBot"}, default="📥 @{bot}"),

    # ---- force join --------------------------------------------------------
    TextSpec("join_required", "درخواست عضویت در کانال", category="join", default=(
        "🔒 برای استفاده از ربات ابتدا در کانال‌های زیر عضو شوید، "
        "سپس روی «✅ عضو شدم» بزنید."
    )),
    TextSpec("join_ok", "عضویت تایید شد", category="join",
             default="✅ عضویت شما تایید شد! حالا لینک مورد نظر را بفرستید."),
    TextSpec("join_not_yet", "هنوز عضو نشده (پاپ‌آپ)", category="join", plain=True,
             default="❌ هنوز در همه کانال‌ها عضو نشده‌اید."),

    # ---- progress ----------------------------------------------------------
    TextSpec("checking", "در حال بررسی لینک", category="progress",
             default="🔎 در حال بررسی لینک..."),
    TextSpec("queued", "در صف دانلود", category="progress",
             default="🕒 در صف دانلود... (سرور شلوغ است)"),
    TextSpec("downloading", "در حال دانلود", category="progress", default="⏳ در حال دانلود..."),
    TextSpec("progress", "نوار پیشرفت (حجم مشخص)", category="progress",
             placeholders=("bar", "percent", "done", "total", "speed"),
             sample={"bar": "▰▰▰▰▰▱▱▱▱▱▱▱", "percent": "42", "done": "10.5 MB",
                     "total": "25.0 MB", "speed": "3.1 MB/s"},
             default="{bar} {percent}%\n📦 {done} / {total}\n🚀 {speed}"),
    TextSpec("progress_unknown", "نوار پیشرفت (حجم نامشخص)", category="progress",
             placeholders=("done", "speed"), sample={"done": "10.5 MB", "speed": "3.1 MB/s"},
             default="📦 {done}\n🚀 {speed}"),
    TextSpec("uploading", "در حال ارسال", category="progress",
             default="📤 در حال ارسال به تلگرام..."),
    TextSpec("from_cache", "ارسال سریع (از کش)", category="progress", default="⚡️ ارسال سریع..."),
    TextSpec("item_label", "شماره آهنگ در پلی‌لیست", category="progress",
             placeholders=("index", "total"), sample={"index": "۲", "total": "۱۰"},
             default="🎵 {index} از {total} — "),
    TextSpec("playlist_header", "شروع پلی‌لیست/آلبوم", category="progress",
             placeholders=("title", "count"), sample={"title": "Global Warming", "count": "۱۰"},
             default="📃 <b>{title}</b>\n🎵 {count} مورد در حال دانلود..."),
    TextSpec("playlist_truncated", "هشدار محدودیت تعداد پلی‌لیست", category="progress",
             placeholders=("total", "count"), sample={"total": "۵۰", "count": "۱۰"},
             default="\n⚠️ از {total} مورد، فقط {count} مورد اول دانلود می‌شود."),
    TextSpec("playlist_done", "پایان پلی‌لیست", category="progress",
             placeholders=("ok", "total"), sample={"ok": "۹", "total": "۱۰"},
             default="✅ دانلود تمام شد: {ok} از {total} مورد ارسال شد."),
    TextSpec("playlist_item_failed", "خطای یک آهنگ از پلی‌لیست", category="progress",
             placeholders=("error", "item"),
             sample={"error": "❌ آهنگ پیدا نشد.", "item": "Artist - Song"},
             default="{error}\n<code>{item}</code>"),

    # ---- youtube -----------------------------------------------------------
    TextSpec("yt_menu", "منوی انتخاب کیفیت", category="youtube",
             placeholders=("title", "channel", "duration"),
             sample={"title": "Me at the zoo", "channel": "jawed", "duration": "0:19"},
             default=("🎬 <b>{title}</b>\n👤 {channel}\n⏱ {duration}\n\n"
                      "👇 کیفیت مورد نظر را انتخاب کنید:")),
    TextSpec("yt_chosen", "شروع دانلود کیفیت انتخابی", category="youtube",
             placeholders=("quality", "title"), sample={"quality": "720p HD", "title": "Me at the zoo"},
             default="⏳ در حال دانلود <b>{quality}</b>...\n🎬 {title}"),
    TextSpec("yt_thumb_caption", "کپشن کاور ویدیو", category="youtube",
             placeholders=("title", "bot"), sample={"title": "Me at the zoo", "bot": "MyBot"},
             default="🖼 کاور: {title}\n\n📥 @{bot}"),
    TextSpec("yt_playlist", "لینک پلی‌لیست یوتیوب", category="youtube",
             default="❌ لینک پلی‌لیست یوتیوب پشتیبانی نمی‌شود. لطفا لینک یک ویدیو را بفرستید."),
    TextSpec("yt_live", "پخش زنده", category="youtube",
             default="❌ دانلود پخش زنده امکان‌پذیر نیست."),
    TextSpec("yt_expired", "منوی منقضی (پاپ‌آپ)", category="youtube", plain=True,
             default="⌛️ این منو منقضی شده. لطفا لینک را دوباره بفرستید."),
    TextSpec("yt_not_yours", "منوی شخص دیگر (پاپ‌آپ)", category="youtube", plain=True,
             default="این منو مال شما نیست."),
    TextSpec("yt_too_big", "کیفیت با حجم زیاد (پاپ‌آپ)", category="youtube", plain=True,
             placeholders=("size", "limit"), sample=_SIZE,
             default="⚠️ حجم این کیفیت حدود {size} است و از حد مجاز ربات ({limit}) بیشتر است. "
                     "کیفیت پایین‌تری انتخاب کنید."),

    # ---- errors ------------------------------------------------------------
    TextSpec("error_generic", "خطای ناشناخته", category="errors",
             default="❌ مشکلی پیش آمد. لطفا بعدا دوباره امتحان کنید."),
    TextSpec("err_download", "خطای کلی دانلود", category="errors",
             default="❌ دانلود با خطا مواجه شد. لطفا بعدا دوباره امتحان کنید."),
    TextSpec("too_large", "حجم بیش از حد", category="errors", placeholders=("size", "limit"),
             sample=_SIZE, default="⚠️ حجم فایل ({size}) بیشتر از حد مجاز ربات ({limit}) است."),
    TextSpec("err_too_large_or_empty", "فایل خیلی بزرگ / دریافت نشد", category="errors",
             default="⚠️ حجم فایل بیشتر از حد مجاز ربات است یا فایلی دریافت نشد."),
    TextSpec("some_skipped", "چند فایل به‌خاطر حجم ارسال نشد", category="errors",
             placeholders=("count", "limit"), sample={"count": "۲", "limit": "50.0 MB"},
             default="⚠️ {count} فایل به‌خاطر حجم زیاد (بیشتر از {limit}) ارسال نشد."),
    TextSpec("err_ig_login", "اینستاگرام: نیاز به ورود", category="errors", default=(
        "🔒 اینستاگرام اجازه دسترسی نداد. این پست خصوصی است یا اتصال ربات به اینستاگرام "
        "نیاز به تمدید دارد. لطفا کمی بعد دوباره امتحان کنید."
    )),
    TextSpec("err_ig_profile", "اینستاگرام: لینک پروفایل", category="errors",
             default="❌ لطفا لینک پست، ریلز یا استوری اینستاگرام را بفرستید (نه لینک پروفایل)."),
    TextSpec("err_yt_login", "یوتیوب: نیاز به ورود", category="errors", default=(
        "🔒 یوتیوب برای این ویدیو ورود به حساب می‌خواهد (محدودیت سنی/خصوصی) "
        "یا اتصال ربات به یوتیوب نیاز به تمدید دارد."
    )),
    TextSpec("err_yt_blocked", "یوتیوب: دسترسی سرور محدود شد", category="errors",
             default="🚫 یوتیوب دسترسی ربات را موقتا محدود کرده است. لطفا کمی بعد امتحان کنید."),
    TextSpec("err_login", "محتوای خصوصی", category="errors",
             default="🔒 این محتوا خصوصی است یا نیاز به ورود به حساب دارد."),
    TextSpec("err_unavailable", "محتوا در دسترس نیست", category="errors",
             default="❌ این محتوا در دسترس نیست یا حذف شده است."),
    TextSpec("err_unsupported_link", "نوع لینک پشتیبانی نمی‌شود", category="errors",
             default="❌ این نوع لینک پشتیبانی نمی‌شود."),
    TextSpec("err_no_media", "فایلی پیدا نشد", category="errors",
             default="❌ فایلی برای دانلود در این لینک پیدا نشد."),
    TextSpec("err_drm", "محتوای DRM", category="errors",
             default="❌ این محتوا با DRM محافظت شده و قابل دانلود نیست."),
    TextSpec("err_timeout", "زمان دانلود طولانی", category="errors",
             default="⏱ زمان دانلود بیش از حد طول کشید."),
    TextSpec("err_spotify_link", "اسپاتیفای: لینک نامعتبر", category="errors",
             default="❌ فقط لینک آهنگ، آلبوم یا پلی‌لیست اسپاتیفای پشتیبانی می‌شود."),
    TextSpec("err_spotify_fetch", "اسپاتیفای: اطلاعات دریافت نشد", category="errors",
             default="❌ اطلاعات این لینک از اسپاتیفای دریافت نشد."),
    TextSpec("err_playlist_empty", "پلی‌لیست خالی", category="errors",
             default="❌ آهنگی در این لینک پیدا نشد."),
    TextSpec("err_song_not_found", "آهنگ پیدا نشد", category="errors", placeholders=("title",),
             sample={"title": "Song"}, default="❌ آهنگ «{title}» پیدا نشد."),

    # ---- bot command menu ----------------------------------------------------
    TextSpec("cmd_start", "توضیح دستور /start در منو", category="commands", plain=True,
             default="شروع"),
    TextSpec("cmd_help", "توضیح دستور /help در منو", category="commands", plain=True,
             default="راهنما"),
]

TEXTS: dict[str, TextSpec] = {spec.key: spec for spec in _SPECS}
