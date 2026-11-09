#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Downloader bot installer (Ubuntu / Debian)
#
#  One-line install:
#    bash <(curl -fsSL https://raw.githubusercontent.com/DenTeeR/Downloader-/main/install.sh)
#
#  Non-interactive (all optional except the first two):
#    BOT_TOKEN=... ADMIN_IDS=123 INSTALL_MODE=docker|native FORCE_JOIN_CHANNELS=@ch \
#    PROXY=socks5://... bash install.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/DenTeeR/Downloader-.git}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-}"   # default: this checkout, or /opt/downloader-bot
SERVICE="downloader-bot"
TELEGRAM_API="${TELEGRAM_API:-https://api.telegram.org}"
CLI="/usr/local/bin/dlbot"

green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }
red() { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }
step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
die() { red "✖ $*"; exit 1; }

# A terminal we can actually read answers from (also works for `curl ... | bash`).
interactive() { [[ "${NONINTERACTIVE:-0}" != 1 ]] && { : </dev/tty; } 2>/dev/null; }
ask() {  # ask "question" default -> echoes answer
    local question="$1" default="${2:-}" answer=""
    if interactive; then
        read -r -p "$question ${default:+[$default] }" answer </dev/tty || true
    fi
    echo "${answer:-$default}"
}

# ── checks ──────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    [[ -f "$0" ]] && exec sudo -E bash "$0" "$@"
    die "لطفا با کاربر root اجرا کنید (sudo -i)."
fi
command -v apt-get >/dev/null || die "این اسکریپت فقط برای Ubuntu/Debian است (apt-get پیدا نشد)."

cat <<'EOF'

  ╔══════════════════════════════════════════════╗
  ║        📥  نصب ربات دانلودر تلگرام  📥        ║
  ║  Instagram • YouTube • Pinterest • Spotify   ║
  ║               • SoundCloud                   ║
  ╚══════════════════════════════════════════════╝
EOF

step "نصب پیش‌نیازهای پایه (git, curl)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates >/dev/null

# ── source code ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
if [[ -z "$INSTALL_DIR" ]]; then
    if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/bot/__main__.py" ]]; then
        INSTALL_DIR="$SCRIPT_DIR"   # running from a cloned repository: install in place
    else
        INSTALL_DIR="/opt/downloader-bot"
    fi
fi
step "دریافت سورس ربات در $INSTALL_DIR"
if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" pull --ff-only || yellow "به‌روزرسانی git انجام نشد؛ با نسخه فعلی ادامه می‌دهیم."
elif [[ ! -f "$INSTALL_DIR/bot/__main__.py" ]]; then
    git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"
mkdir -p data cookies

# ── configuration ───────────────────────────────────────────────────────────
env_get() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- || true; }
env_set() {
    local key="$1" value="$2"
    if grep -qE "^$key=" .env; then
        local escaped; escaped=$(printf '%s' "$value" | sed -e 's/[\/&|]/\\&/g')
        sed -i "s|^$key=.*|$key=$escaped|" .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

check_token() {
    local response
    response=$(curl -fsS -m 20 "$TELEGRAM_API/bot$1/getMe" 2>/dev/null) || return 1
    echo "$response" | grep -o '"username":"[^"]*"' | cut -d'"' -f4
}

step "تنظیمات ربات"
[[ -f .env ]] || cp .env.example .env

TOKEN="${BOT_TOKEN:-$(env_get BOT_TOKEN)}"
[[ "$TOKEN" == 123456789:* ]] && TOKEN=""
while :; do
    [[ -n "$TOKEN" ]] || TOKEN=$(ask "🔑 توکن ربات (از @BotFather):")
    [[ -n "$TOKEN" ]] || { interactive || die "BOT_TOKEN داده نشده است."; continue; }
    if BOT_NAME=$(check_token "$TOKEN") && [[ -n "$BOT_NAME" ]]; then
        green "✔ توکن معتبر است: @$BOT_NAME"
        break
    fi
    red "✖ توکن نامعتبر است یا سرور به تلگرام دسترسی ندارد."
    if ! interactive || [[ -n "${BOT_TOKEN:-}" ]]; then
        [[ "${SKIP_TOKEN_CHECK:-0}" == 1 ]] && break
        die "توکن را بررسی کنید (یا اگر سرور در ایران است، PROXY را تنظیم کنید)."
    fi
    TOKEN=""
done
env_set BOT_TOKEN "$TOKEN"

ADMINS="${ADMIN_IDS:-$(env_get ADMIN_IDS)}"
[[ "$ADMINS" == "123456789" ]] && ADMINS=""
while [[ ! "$ADMINS" =~ ^[0-9]+(,[0-9]+)*$ ]]; do
    interactive || die "ADMIN_IDS نامعتبر است."
    ADMINS=$(ask "👤 آیدی عددی ادمین (از @userinfobot، چند مورد را با کاما جدا کنید):")
    ADMINS="${ADMINS// /}"
done
env_set ADMIN_IDS "$ADMINS"

CHANNELS="${FORCE_JOIN_CHANNELS-$(ask "📢 کانال عضویت اجباری (مثلا @mychannel، خالی = ندارد):" "$(env_get FORCE_JOIN_CHANNELS)")}"
env_set FORCE_JOIN_CHANNELS "$CHANNELS"

if [[ -n "${PROXY+x}" ]]; then env_set PROXY "$PROXY"; fi

MODE="${INSTALL_MODE:-}"
if [[ -z "$MODE" ]]; then
    echo
    echo "  روش اجرا را انتخاب کنید:"
    echo "   1) Docker  (پیشنهادی، امکان ارسال فایل تا ۲ گیگ)"
    echo "   2) Python + systemd  (سبک‌تر، بدون Docker)"
    MODE=$( [[ "$(ask "انتخاب شما:" 1)" == 2 ]] && echo native || echo docker )
fi

LOCAL_API=0
if [[ "$MODE" == docker ]]; then
    if [[ "${LOCAL_BOT_API:-}" == 1 ]] || { [[ -z "${LOCAL_BOT_API:-}" ]] && \
        [[ "$(ask "📦 ارسال فایل‌های بزرگ‌تر از ۵۰ مگ فعال شود؟ (نیاز به api_id از my.telegram.org) [y/N]" n)" =~ ^[Yy] ]]; }; then
        API_ID="${TELEGRAM_API_ID:-$(ask "api_id:" "$(env_get TELEGRAM_API_ID)")}"
        API_HASH="${TELEGRAM_API_HASH:-$(ask "api_hash:" "$(env_get TELEGRAM_API_HASH)")}"
        if [[ -n "$API_ID" && -n "$API_HASH" ]]; then
            env_set TELEGRAM_API_ID "$API_ID"
            env_set TELEGRAM_API_HASH "$API_HASH"
            env_set BOT_API_SERVER "http://telegram-bot-api:8081"
            LOCAL_API=1
            # The bot must be logged out of the cloud Bot API before using a local server.
            curl -fsS -m 20 "$TELEGRAM_API/bot$TOKEN/logOut" >/dev/null 2>&1 || true
        else
            yellow "api_id/api_hash داده نشد؛ حداکثر حجم فایل ۵۰ مگ می‌ماند."
        fi
    fi
fi
echo "INSTALL_MODE=$MODE" > .install-mode
echo "LOCAL_API=$LOCAL_API" >> .install-mode
chmod 600 .env

# ── install & start ─────────────────────────────────────────────────────────
compose_profiles() { [[ "$LOCAL_API" == 1 ]] && echo "--profile local-api" || true; }

if [[ "$MODE" == docker ]]; then
    step "نصب Docker"
    if ! command -v docker >/dev/null; then
        curl -fsSL https://get.docker.com | sh
    fi
    systemctl enable --now docker >/dev/null 2>&1 || true
    step "ساخت و اجرای ربات (چند دقیقه طول می‌کشد)"
    # shellcheck disable=SC2046
    docker compose $(compose_profiles) up -d --build
else
    step "نصب Python، ffmpeg و Deno"
    apt-get install -y -qq python3 python3-venv python3-pip ffmpeg unzip >/dev/null
    if ! command -v deno >/dev/null; then
        curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh -s -- -y >/dev/null \
            || yellow "نصب Deno انجام نشد؛ برای یوتیوب JS_RUNTIME=node و نصب Node.js لازم است."
    fi
    step "ساخت محیط Python و نصب کتابخانه‌ها"
    python3 -m venv .venv
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q -r requirements.txt
    if command -v systemctl >/dev/null && [[ -d /run/systemd/system ]]; then
        step "ساخت سرویس systemd"
        cat > "/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=Telegram downloader bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python -m bot
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
        systemctl daemon-reload
        systemctl enable --now "$SERVICE"
    else
        yellow "systemd در دسترس نیست؛ ربات را با «dlbot run» اجرا کنید."
    fi
fi

# ── management command ──────────────────────────────────────────────────────
step "ساخت دستور مدیریت dlbot"
cat > "$CLI" <<EOF
#!/usr/bin/env bash
# Manage the downloader bot: dlbot {start|stop|restart|status|logs|update|config|run|uninstall}
set -e
cd "$INSTALL_DIR"
source .install-mode
profiles() { [[ "\$LOCAL_API" == 1 ]] && echo "--profile local-api" || true; }
dc() { docker compose \$(profiles) "\$@"; }
case "\${1:-help}" in
  start)   if [[ \$INSTALL_MODE == docker ]]; then dc up -d; else systemctl start $SERVICE; fi ;;
  stop)    if [[ \$INSTALL_MODE == docker ]]; then dc stop; else systemctl stop $SERVICE; fi ;;
  restart) if [[ \$INSTALL_MODE == docker ]]; then dc restart bot; else systemctl restart $SERVICE; fi ;;
  status)  if [[ \$INSTALL_MODE == docker ]]; then dc ps; else systemctl status $SERVICE --no-pager; fi ;;
  logs)    if [[ \$INSTALL_MODE == docker ]]; then dc logs -f --tail 100 bot; else journalctl -u $SERVICE -f -n 100; fi ;;
  update)
    git pull --ff-only || true
    if [[ \$INSTALL_MODE == docker ]]; then dc build --pull --no-cache bot && dc up -d
    else .venv/bin/pip install -q -U -r requirements.txt yt-dlp gallery-dl && systemctl restart $SERVICE; fi
    echo "✔ ربات به‌روز شد." ;;
  config)  \${EDITOR:-nano} .env && "\$0" restart ;;
  run)     exec .venv/bin/python -m bot ;;
  uninstall)
    read -r -p "ربات و همه داده‌هایش حذف شود؟ [y/N] " a; [[ \$a =~ ^[Yy] ]] || exit 0
    if [[ \$INSTALL_MODE == docker ]]; then dc down -v || true
    else systemctl disable --now $SERVICE || true; rm -f /etc/systemd/system/$SERVICE.service; fi
    cd / && rm -rf "$INSTALL_DIR" "$CLI" && echo "✔ حذف شد." ;;
  *) echo "dlbot {start|stop|restart|status|logs|update|config|run|uninstall}" ;;
esac
EOF
chmod +x "$CLI"

green "
✅ نصب کامل شد!

🤖 ربات: @${BOT_NAME:-?}
📁 مسیر: $INSTALL_DIR

دستورات مدیریت:
  dlbot logs      مشاهده لاگ
  dlbot restart   ری‌استارت
  dlbot update    به‌روزرسانی ربات و ابزارهای دانلود
  dlbot config    ویرایش تنظیمات
  dlbot uninstall حذف کامل

👉 حالا در تلگرام به ربات /start بدهید.
👉 پنل مدیریت: /admin  (طراحی ربات، کوکی‌ها، آمار، ارسال همگانی)
👉 برای دانلود از اینستاگرام: /admin ← 🍪 کوکی‌ها
"
