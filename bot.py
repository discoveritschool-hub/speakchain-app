"""
SpeakChain Bot v4 — прогалини CEFR, YouTube API, TikTok/Instagram, ланцюг рекомендацій
"""
import sys
print("=== [1] PYTHON STARTED ===", flush=True)
sys.stderr.write("=== [1] STDERR OK ===\n"); sys.stderr.flush()

import os, json, asyncio, logging, tempfile, re, urllib.parse, random, threading
print("=== [2] STD IMPORTS OK ===", flush=True)
from datetime import datetime, time
from pathlib import Path

import aiohttp
from aiohttp import web as _web
print("=== [3] AIOHTTP OK ===", flush=True)
try:
    import gspread
    from google.oauth2.service_account import Credentials as GCredentials
    GSPREAD_OK = True
except ImportError:
    GSPREAD_OK = False
    print("WARNING: gspread not installed — Google Sheets sync disabled")
print("=== [4] GSPREAD OK ===", flush=True)
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand, WebAppInfo
)
print("=== [5] TELEGRAM OK ===", flush=True)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
    PollAnswerHandler,
)
print("=== [6] TELEGRAM EXT OK ===", flush=True)
openai_client = None  # OpenAI не використовується
import urllib.parse
import anthropic
print("=== [7] ANTHROPIC OK ===", flush=True)
from static_content import CEFR_QUESTION_BANK, build_lesson_plan_static, build_vocab_test, build_vocab_size_test
print("=== [8] STATIC CONTENT OK ===", flush=True)
from grammar_engine import (
    GRAMMAR_MAP, detect_topic, format_explanation, format_table_only,
    compute_mastery, apply_decay, build_explanation_prompt,
    build_exercise_prompt, should_nudge, build_nudge_text, nudge_keyboard,
    mark_topic_event, mark_nudge_sent, mark_nudge_snoozed,
    format_progress_bars,
)
print("=== [8b] GRAMMAR ENGINE OK ===", flush=True)
from chain_engine    import get_chain, complete_session as chain_complete, revive_chain, chain_status_text
from demo_flow       import handle_demo_entry, maybe_handle_demo_answer, DEMO_CALLBACKS
from identity_engine import maybe_identity_shift, get_identity_label
from analytics       import track_event, get_retention_report
from trial_engine    import (
    get_trial_status, is_in_trial as trial_is_in_trial,
    trial_links_left, after_trial_chain, soft_paywall_message,
    apply_referral_bonus, STATUS_PAID, STATUS_TRIAL_DONE,
)
from shared_chain    import (
    send_phrase_challenge, handle_partner_voice,
    handle_challenge_deeplink, check_sync_bonus,
    SHARED_CHAIN_CALLBACKS,
)
from timezone_utils  import get_user_hour, guess_utc_offset, save_utc_offset
print("=== [8c] NEW ENGINES OK ===", flush=True)

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
print("=== [9] LOGGING OK ===", flush=True)

BOT_TOKEN        = os.environ.get("BOT_TOKEN", "")
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY", "")
CLAUDE_API_KEY   = os.environ.get("CLAUDE_API_KEY", "")
ADMIN_ID         = int(os.environ.get("ADMIN_ID", "0"))
YOUTUBE_API_KEY  = os.environ.get("YOUTUBE_API_KEY", "")
COMMUNITY_LINK   = os.environ.get("COMMUNITY_LINK", "")
WEBAPP_URL           = os.environ.get("WEBAPP_URL", "")
MINIAPP_URL          = "https://t.me/SpeakChain_bot/SpeakChainApp"
GOOGLE_SHEET_ID      = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_CREDENTIALS   = os.environ.get("GOOGLE_CREDENTIALS", "")
OFFER_FILE_ID        = os.environ.get("OFFER_FILE_ID", "")
ADMIN_STATE: dict     = {}
PRIVACY_FILE_ID      = os.environ.get("PRIVACY_FILE_ID", "")
SUPPORT_EMAIL        = os.environ.get("SUPPORT_EMAIL", "support@speakchain.app")
print(f"=== [10] ENV OK: BOT_TOKEN={'SET' if BOT_TOKEN else 'MISSING'}, CLAUDE={'SET' if CLAUDE_API_KEY else 'MISSING'} ===", flush=True)

# ── Sub-admin система ─────────────────────────────────
# SUB_ADMIN_IDS в ENV: через кому, напр. "123456789,987654321"
_sub_admin_raw = os.environ.get("SUB_ADMIN_IDS", "")
_SUB_ADMINS: set = set()
if _sub_admin_raw:
    for _sid in _sub_admin_raw.split(","):
        try:
            _SUB_ADMINS.add(int(_sid.strip()))
        except ValueError:
            pass

def is_admin(uid: int) -> bool:
    """True для супер-адміна і всіх sub-admin'ів."""
    if not uid:
        return False
    return uid == ADMIN_ID or uid in _SUB_ADMINS

def is_super_admin(uid: int) -> bool:
    """True тільки для головного ADMIN_ID (операції без делегування)."""
    return bool(ADMIN_ID) and uid == ADMIN_ID

def get_sub_admins() -> set:
    """Повертає поточний набір sub-admin IDs."""
    return set(_SUB_ADMINS)

def add_sub_admin(uid: int):
    """Додає sub-admin динамічно (зберігається в пам'яті до рестарту)."""
    _SUB_ADMINS.add(uid)

def remove_sub_admin(uid: int):
    """Видаляє sub-admin."""
    _SUB_ADMINS.discard(uid)



# ── Кеш для Claude відповідей ────────────────────────
import time as _time
_CLAUDE_CACHE: dict = {}

def claude_cache_get(key: str):
    entry = _CLAUDE_CACHE.get(key)
    if entry and _time.time() < entry["exp"]:
        return entry["v"]
    return None

def claude_cache_set(key: str, value, ttl_hours: int = 24):
    _CLAUDE_CACHE[key] = {"v": value, "exp": _time.time() + ttl_hours * 3600}


WAYFORPAY_MERCHANT   = os.environ.get("WAYFORPAY_MERCHANT", "")
WAYFORPAY_SECRET     = os.environ.get("WAYFORPAY_SECRET", "")
BOT_WEBHOOK_URL      = os.environ.get("BOT_WEBHOOK_URL", "")  # публічний URL Railway сервісу
CHAIN_DASHBOARD_URL  = os.environ.get("CHAIN_DASHBOARD_URL", f"{BOT_WEBHOOK_URL}/chain_dashboard" if BOT_WEBHOOK_URL else "")
if not BOT_TOKEN:    raise ValueError("BOT_TOKEN missing")
if not CLAUDE_API_KEY: raise ValueError("CLAUDE_API_KEY missing")
if not YOUTUBE_API_KEY:
    logger.warning("YOUTUBE_API_KEY not set — live search disabled, fallback to library")

print("=== [11] CREATING CLAUDE CLIENT ===", flush=True)
claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
print("=== [12] CLAUDE CLIENT OK ===", flush=True)

# ── Google Sheets sync ───────────────────────────────
_gs_client = None

def _get_gs_client():
    global _gs_client
    if _gs_client:
        return _gs_client
    if not GSPREAD_OK or not GOOGLE_CREDENTIALS or not GOOGLE_SHEET_ID:
        return None
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        scopes     = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds      = GCredentials.from_service_account_info(creds_dict, scopes=scopes)
        _gs_client = gspread.authorize(creds)
        return _gs_client
    except Exception as e:
        logger.warning(f"Google Sheets auth error: {e}")
        return None

def _ensure_sheet(spreadsheet, title: str, headers: list) -> object:
    """Повертає лист з потрібними заголовками, створює якщо немає."""
    try:
        ws = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.append_row(headers)
    return ws

async def gs_sync_student(uid: int):
    """Оновлює або додає рядок студента в Students sheet."""
    try:
        gc = _get_gs_client()
        if not gc:
            return
        s   = get_s(uid)
        sh  = gc.open_by_key(GOOGLE_SHEET_ID)
        ws  = _ensure_sheet(sh, "Students", [
            "ID", "Імʼя", "Username", "Рівень", "Ціль",
            "Уроків", "Стрік", "Premium", "Реферал", "Дата онбоардингу"
        ])
        row = [
            str(uid),
            s.get("name", ""),
            s.get("username", ""),
            s.get("level", ""),
            GOAL_NAMES.get(s.get("goal",""), s.get("goal","")),
            len(s.get("done_lessons", [])),
            s.get("streak_days", 0),
            "Так" if is_premium(s) else "Ні",
            s.get("affiliate_ref", ""),
            s.get("placement_result", {}).get("date", ""),
        ]
        # Шукаємо чи є вже такий студент
        try:
            cell = ws.find(str(uid), in_column=1)
            ws.update(f"A{cell.row}:J{cell.row}", [row])
        except gspread.CellNotFound:
            ws.append_row(row)
    except Exception as e:
        logger.warning(f"gs_sync_student error: {e}")

async def gs_log_payment(uid: int, days: int, until: str, ref: str = "", plan: str = ""):
    """Додає рядок в Payments (загальний), Basic Payments або Premium Payments sheet."""
    try:
        gc = _get_gs_client()
        if not gc:
            return
        s   = get_s(uid)
        sh  = gc.open_by_key(GOOGLE_SHEET_ID)

        # Визначаємо тип плану і ціну
        if not plan:
            plan = s.get("plan", "premium")
        if plan == "basic":
            price      = BASIC_AFFILIATE_PRICE if ref else BASIC_PRICE
            plan_name  = "Basic ⚡️"
            sheet_name = "Basic Payments"
        else:
            price      = PREMIUM_PRICE_AFF if ref else PREMIUM_PRICE_FULL
            plan_name  = "Premium 🌟"
            sheet_name = "Premium Payments"

        # Визначаємо блогера
        blogger = s.get("affiliate_blogger", "")
        if not blogger and ref:
            bloggers = get_registered_bloggers()
            blogger  = next((name for name in bloggers.values() if ref.startswith(name)), ref)
        if not blogger:
            blogger = "\u2014 пряма оплата"

        headers = ["Дата", "ID", "Імʼя", "Тариф", "Блогер", "Днів", "До", "Реферал", "Ціна USD"]
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            str(uid),
            s.get("name", ""),
            plan_name,
            blogger,
            days,
            until,
            ref,
            price,
        ]

        # Загальний лист
        ws_all = _ensure_sheet(sh, "Payments", headers)
        ws_all.append_row(row)

        # Окремий лист по тарифу
        ws_plan = _ensure_sheet(sh, sheet_name, headers)
        ws_plan.append_row(row)

    except Exception as e:
        logger.warning(f"gs_log_payment error: {e}")

# ── Wayforpay інтеграція ─────────────────────────────
import hmac
import hashlib

def wfp_sign(params: list) -> str:
    """Генерує підпис для Wayforpay — HMAC-MD5."""
    msg = ";".join(str(p) for p in params)
    logger.info(f"WFP sign string: {msg}")
    secret = WAYFORPAY_SECRET.encode("utf-8")
    return hmac.new(secret, msg.encode("utf-8"), hashlib.md5).hexdigest()

def wfp_base_url() -> str:
    url = (BOT_WEBHOOK_URL or "").rstrip("/")
    if url and not url.startswith("https://"):
        url = "https://" + url.replace("http://", "")
    return url

def wfp_build_params(user_id: int, plan: str, amount: float, currency: str = "UAH") -> dict:
    """Будує словник параметрів для Wayforpay."""
    import time
    order_id    = f"sc_{plan}_{user_id}_{int(time.time())}"
    order_date  = int(time.time())
    product     = f"SpeakChain {'Basic 6M' if plan == 'basic_6m' else 'Premium 6M' if plan == 'premium_6m' else 'Basic' if plan == 'basic' else 'Premium'}"
    domain      = "speakchain.base44.app"
    base         = wfp_base_url()
    return_url   = "https://t.me/SpeakChainBot"
    service_url  = f"{base}/wayforpay_webhook" if base else ""

    # Підпис — строго за документацією Wayforpay
    sign_str = [
        WAYFORPAY_MERCHANT, domain, order_id,
        str(order_date), str(amount), currency,
        product, "1", str(amount),
    ]
    sig = wfp_sign(sign_str)

    return {
        "merchantAccount":      WAYFORPAY_MERCHANT,
        "merchantDomainName":   domain,
        "orderReference":       order_id,
        "orderDate":            str(order_date),
        "amount":               str(amount),
        "currency":             currency,
        "productName":          product,
        "productCount":         "1",
        "productPrice":         str(amount),
        "returnUrl":            return_url,
        "serviceUrl":           service_url,
        "defaultPaymentSystem": "card",
        "merchantSignature":    sig,
    }

def wfp_create_payment_url(user_id: int, plan: str, amount: float, currency: str = "UAH") -> str:
    """Повертає URL на /pay сторінку."""
    import urllib.parse
    params = wfp_build_params(user_id, plan, amount, currency)
    base   = wfp_base_url()
    return f"{base}/pay?" + urllib.parse.urlencode(params)


async def wfp_charge_by_token(user_id: int, plan: str, amount: float,
                               rec_token: str, currency: str = "UAH") -> dict:
    """
    Списує гроші по збереженому recToken без участі клієнта.
    Повертає dict з результатом від WayForPay.
    """
    import time, aiohttp as _aio
    order_id   = f"rec_{plan}_{user_id}_{int(time.time())}"
    order_date = int(time.time())
    product    = f"SpeakChain {'Basic' if plan == 'basic' else 'Premium'} (auto)"
    domain     = "speakchain.base44.app"
    base       = wfp_base_url()
    service_url= f"{base}/wayforpay_webhook" if base else ""

    sign_str = [
        WAYFORPAY_MERCHANT, domain, order_id,
        str(order_date), str(amount), currency,
        product, "1", str(amount),
    ]
    sig = wfp_sign(sign_str)

    payload = {
        "transactionType":    "CHARGE",
        "merchantAccount":    WAYFORPAY_MERCHANT,
        "merchantDomainName": domain,
        "orderReference":     order_id,
        "orderDate":          order_date,
        "amount":             str(amount),
        "currency":           currency,
        "productName":        [product],
        "productCount":       ["1"],
        "productPrice":       [str(amount)],
        "recToken":           rec_token,
        "serviceUrl":         service_url,
        "merchantSignature":  sig,
        "apiVersion":         "1",
        "straightCharge":     "1",
    }

    try:
        async with _aio.ClientSession() as sess:
            async with sess.post(
                "https://api.wayforpay.com/api",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=_aio.ClientTimeout(total=30)
            ) as resp:
                raw = await resp.text()
                logger.warning(f"WFP charge raw: {raw[:500]}")
                import json as _json
                try:
                    result = _json.loads(raw)
                except Exception:
                    result = {"transactionStatus": "ERROR", "reason": f"Bad response: {raw[:200]}"}
                logger.warning(f"WFP recurrent charge uid={user_id}: {result}")
                return result
    except Exception as e:
        logger.warning(f"WFP recurrent charge error uid={user_id}: {e}")
        return {"transactionStatus": "ERROR", "reason": str(e)}


# ── Місячні назви українською ─────────────────────────
UA_MONTHS = {
    "January":"Січень","February":"Лютий","March":"Березень",
    "April":"Квітень","May":"Травень","June":"Червень",
    "July":"Липень","August":"Серпень","September":"Вересень",
    "October":"Жовтень","November":"Листопад","December":"Грудень",
}
UA_MONTHS_GEN = {
    "January":"Січня","February":"Лютого","March":"Березня",
    "April":"Квітня","May":"Травня","June":"Червня",
    "July":"Липня","August":"Серпня","September":"Вересня",
    "October":"Жовтня","November":"Листопада","December":"Грудня",
}


def _month_stats(s: dict, year_month: str) -> dict:
    """Рахує статистику студента за конкретний місяць (YYYY-MM)."""
    scores    = s.get("scores", [])
    timeline  = s.get("voice_timeline", [])
    sentences = s.get("mined_sentences", [])

    month_scores   = [sc for sc in scores    if sc.get("date","")[:7] == year_month]
    month_voices   = [v  for v  in timeline  if v.get("date","")[:7]  == year_month]
    month_phrases  = [p  for p  in sentences if p.get("date","")[:7]  == year_month]

    avg_score = int(sum(sc.get("score",0) for sc in month_scores) / len(month_scores)) if month_scores else 0

    return {
        "monologues": len(month_voices),
        "phrases":    len(month_phrases),
        "avg_score":  avg_score,
        "lessons":    len(month_scores),
    }


async def job_monthly_report(ctx: ContextTypes.DEFAULT_TYPE):
    """1-го числа: Spotify Wrapped для кожного студента."""
    if datetime.now().day != 1:
        return

    from datetime import timedelta as _td
    db         = load_db()
    prev_dt    = datetime.now().replace(day=1) - _td(days=1)
    prev_ym    = prev_dt.strftime("%Y-%m")          # 2026-05
    month_en   = prev_dt.strftime("%B")             # May
    month_ua   = UA_MONTHS_GEN.get(month_en, month_en)  # Травня
    year       = prev_dt.strftime("%Y")

    # Збираємо всіх активних студентів для розрахунку перцентилів
    all_students = []
    for uid, s in db.items():
        if not isinstance(s, dict) or str(uid) in DB_SKIP_KEYS: continue
        if not s.get("onboarding_done"): continue
        if not (is_premium(s) or is_in_trial(s)): continue
        stats = _month_stats(s, prev_ym)
        if stats["monologues"] > 0 or stats["lessons"] > 0:
            all_students.append((uid, s, stats))

    total_active = len(all_students)

    for uid, s, stats in all_students:
        name    = s.get("name", "Студент")
        level   = s.get("level", "A1")
        blogger = s.get("affiliate_blogger", "")
        streak  = s.get("streak_days", 0)
        xp      = s.get("xp_total", 0)

        monologues = stats["monologues"]
        phrases    = stats["phrases"]
        avg_score  = stats["avg_score"]
        lessons    = stats["lessons"]

        # ── Перцентиль серед студентів цього місяця ──
        if total_active > 1:
            better_than = sum(
                1 for _, _, st in all_students
                if st["monologues"] < monologues or
                   (st["monologues"] == monologues and st["avg_score"] < avg_score)
            )
            pct = int(better_than / (total_active - 1) * 100)
        else:
            pct = 100

        # ── Зірка місяця ──
        if pct >= 90:
            star_line = f"\n🏆 *Ти в топ {100-pct}% студентів {month_ua}!*"
        elif pct >= 70:
            star_line = f"\n🥈 Ти вище *{pct}%* студентів цього місяця!"
        elif pct >= 50:
            star_line = f"\n📈 Ти активніше половини студентів — продовжуй!"
        else:
            star_line = f"\n💪 Наступний місяць буде кращим — ти вже знаєш як!"

        # ── Порівняння з попереднім місяцем ──
        prev_prev_dt = prev_dt.replace(day=1) - _td(days=1)
        prev_prev_ym = prev_prev_dt.strftime("%Y-%m")
        prev_stats   = _month_stats(s, prev_prev_ym)
        delta_mono   = monologues - prev_stats["monologues"]
        delta_line   = ""
        if prev_stats["monologues"] > 0:
            sign = "+" if delta_mono >= 0 else ""
            delta_line = f"\n📈 Монологів: {sign}{delta_mono} vs минулого місяця"

        # ── Мотивуючий факт ──
        if monologues >= 20:
            fact = "20+ монологів — це вже серйозна звичка 🔥"
        elif monologues >= 10:
            fact = "10+ монологів — ти в топ практикуючих! 💪"
        elif monologues >= 5:
            fact = "5+ монологів — мозок вже звикає до мови 🧠"
        elif monologues >= 1:
            fact = "Перший крок зроблено — далі буде легше!"
        else:
            fact = "Цей місяць — старт нового тебе 🚀"

        blogger_line = f"\n\n_{month_ua} разом з @{blogger}_ 🎙" if blogger else ""

        text = (
            f"🎵 *Твій {month_ua} {year} у SpeakChain*\n\n"
            f"👤 *{name}* · {LEVEL_NAMES.get(level, level)}\n\n"
            f"🎙 Монологів записано: *{monologues}*\n"
            f"📚 Нових фраз: *{phrases}*\n"
            f"🏆 Середній бал: *{avg_score}/100*\n"
            f"🔥 Стрік: *{streak} дн.*\n"
            f"⚡️ XP всього: *{xp:,}*"
            f"{delta_line}"
            f"{star_line}"
            f"\n\n💡 _{fact}_"
            f"{blogger_line}"
        )

        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 Мій прогрес",      callback_data="show_progress"),
                     InlineKeyboardButton("🎙 Практикувати",     callback_data="fork_choose")],
                    [InlineKeyboardButton("📤 Поділитись у соцмережах", callback_data="share_socials")],
                ])
            )
        except Exception as e:
            logger.warning(f"monthly_report {uid}: {e}")


async def job_recurrent_charge(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Щомісячне завдання: списує кошти по recToken.
    - День 0 (закінчення): перша спроба
    - День +1: retry якщо перша не пройшла (мовчки)
    - День +2: фінальна retry + повідомлення якщо знову не пройшло
    Ціна через get_prices(s) — враховує джерело трафіку.
    """
    today = datetime.now().date()
    db    = load_db()

    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue

        rec_token = s.get("rec_token", "")
        if not rec_token: continue

        if s.get("autorenew_cancelled"):
            continue

        until_str = s.get("premium_until", "")
        if not until_str: continue
        try:
            until_date = datetime.strptime(until_str, "%Y-%m-%d").date()
        except Exception:
            continue

        days_since = (today - until_date).days
        if days_since not in (0, 1, 2):
            continue

        attempt_key = f"charge_attempt_{today}"
        if s.get(attempt_key):
            continue

        if days_since > 0 and not s.get("charge_failed"):
            continue

        plan   = s.get("plan", "basic")
        p      = get_prices(s)
        amount = float(p["prem_price"] if plan == "premium" else p["basic_price"])

        attempt_num = days_since + 1
        logger.info(f"Recurrent charge attempt {attempt_num}: uid={uid} plan={plan} amount={amount}")
        upd_s(int(uid), {attempt_key: True})

        result = await wfp_charge_by_token(int(uid), plan, amount, rec_token)
        status = result.get("transactionStatus", "")

        if status == "Approved":
            new_order = result.get("orderReference", "")
            await _process_payment(int(uid), plan, str(amount), new_order, rec_token)
            upd_s(int(uid), {"charge_failed": False})
            logger.info(f"✅ Auto-renewed {plan} uid={uid} attempt={attempt_num}")
        else:
            reason = result.get("reason", "невідома помилка")
            upd_s(int(uid), {"charge_failed": True})
            logger.warning(f"❌ Charge failed uid={uid} attempt={attempt_num}: {reason}")

            if days_since == 0:
                msg = (
                    "⚠️ *Не вдалося списати кошти*\n\n"
                    f"Причина: _{reason}_\n\n"
                    "Спробуємо ще раз завтра автоматично.\n"
                    "Або поновіть підписку вручну 👇"
                )
            elif days_since == 2:
                msg = (
                    "🔒 *Підписку не вдалося поновити після 3 спроб*\n\n"
                    f"Причина: _{reason}_\n\n"
                    "Будь ласка, поновіть вручну або перевірте картку 👇"
                )
                upd_s(int(uid), {"charge_failed": False})
            else:
                continue

            try:
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=msg,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("💳 Поновити підписку", callback_data=f"renew_yes_{uid}_{plan}")
                    ]])
                )
            except Exception as e:
                logger.warning(f"recurrent fail notify {uid}: {e}")


async def job_send_weekly_questions(ctx: ContextTypes.DEFAULT_TYPE):
    """Неділя о 9:00 — розсилає відео-питання тижня від блогерів студентам."""
    if datetime.now().weekday() != 6:  # 6 = неділя
        return
    week_key = datetime.now().strftime("%Y-%W")
    db       = load_db()
    wq_data  = db.get("_weekly_questions", {})
    skip = DB_SKIP_KEYS
    sent_total = 0

    for bname, wq in wq_data.items():
        if wq.get("week") != week_key: continue
        if wq.get("sent"): continue

        file_id   = wq.get("file_id","")
        ftype     = wq.get("file_type","video")
        caption   = wq.get("caption","")
        buid      = wq.get("blogger_uid")
        if not file_id: continue

        # Розсилаємо всім студентам цього блогера
        for uid, st in db.items():
            if not isinstance(st, dict) or str(uid) in skip: continue
            if st.get("affiliate_blogger") != bname: continue
            if not st.get("onboarding_done"): continue
            try:
                send_caption = (
                    f"🎯 *Speaking Challenge від @{bname}*\n\n"
                    + (f"_{caption}_\n\n" if caption else "")
                    + "Запиши голосову відповідь — 30-60 секунд англійською 🎙"
                )
                if ftype == "video_note":
                    await ctx.bot.send_video_note(chat_id=int(uid), video_note=file_id)
                    await ctx.bot.send_message(
                        chat_id=int(uid),
                        text=send_caption,
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🎙 Записати відповідь",
                                                callback_data=f"wq_answer_{bname}")
                        ]])
                    )
                else:
                    await ctx.bot.send_video(
                        chat_id=int(uid), video=file_id,
                        caption=send_caption,
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🎙 Записати відповідь",
                                                callback_data=f"wq_answer_{bname}")
                        ]])
                    )

                # Зберігаємо в кабінеті студента
                wq_history = st.get("weekly_questions_received", [])
                wq_history.append({
                    "date":     datetime.now().strftime("%Y-%m-%d"),
                    "week":     week_key,
                    "blogger":  bname,
                    "file_id":  file_id,
                    "answered": False,
                })
                upd_s(int(uid), {"weekly_questions_received": wq_history[-12:]})
                sent_total += 1
            except Exception as e:
                logger.warning(f"wq dispatch {uid}: {e}")

        # Відмічаємо як надіслано
        wq["sent"] = True
        db["_weekly_questions"][bname] = wq

        # Сповіщаємо блогера
        if buid:
            try:
                await ctx.bot.send_message(
                    chat_id=int(buid),
                    text=f"✅ Speaking Challenge розіслано студентам!\n\nВсього отримали: {sent_total} 🎉"
                )
            except Exception:
                pass

    save_db(db)
    logger.info(f"job_send_weekly_questions: sent to {sent_total} students")


async def job_blogger_weekly_q_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    """П'ятниця о 9:00 — нагадує блогерам надіслати питання тижня."""
    if datetime.now().weekday() != 4:  # 4 = п'ятниця
        return
    week_key = datetime.now().strftime("%Y-%W")
    db       = load_db()
    bloggers = get_registered_bloggers()
    wq_data  = db.get("_weekly_questions", {})
    for blogger_uid, bname in bloggers.items():
        if wq_data.get(bname, {}).get("week") == week_key:
            continue
        try:
            await ctx.bot.send_message(
                chat_id=int(blogger_uid),
                text=(
                    "🎯 *Нагадування: питання тижня*\n\n"
                    "Ти ще не надіслав питання тижня своїм студентам.\n\n"
                    "Нагадую, що в неділю студенти мають отримати твій speaking challenge — питання тижня. "
                    "Запиши це завдання протягом 47 годин, щоб студенти могли виконати його в неділю та отримати AI фідбек 🎙\n\n"
                    "`/weekly_question Твоє питання тут`"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🎯 Відкрити меню", callback_data="blogger_weekly_q")
                ]])
            )
        except Exception as e:
            logger.warning(f"weekly_q reminder {blogger_uid}: {e}")


async def wfp_verify_webhook(data: dict) -> bool:
    """Перевіряє підпис webhook від Wayforpay."""
    sign_params = [
        data.get("merchantAccount", ""),
        data.get("orderReference", ""),
        data.get("amount", ""),
        data.get("currency", ""),
        data.get("authCode", ""),
        data.get("cardPan", ""),
        data.get("transactionStatus", ""),
        data.get("reasonCode", ""),
    ]
    expected = wfp_sign(sign_params)
    received = data.get("merchantSignature", "")
    logger.info(f"WFP webhook: expected={expected}, received={received}")
    return expected == received

def wfp_parse_order(order_ref: str) -> tuple:
    """Розбирає orderReference → (user_id, plan)."""
    try:
        # формат: sc_basic_123456_1234567890
        parts   = order_ref.split("_")
        plan    = parts[1]
        user_id = int(parts[2])
        return user_id, plan
    except Exception:
        return 0, ""

# ── Wayforpay Webhook Handler ─────────────────────────
def _build_chain_dashboard_url(uid: int, s: dict, db: dict | None = None) -> str:
    """
    Будує URL для Chain Dashboard з даними юзера.
    db — передавати якщо вже є (уникає зайвого load_db()).
    Один прохід по БД для top + leaderboard одночасно.
    """
    import json as _json, urllib.parse as _ul
    if db is None:
        db = load_db()

    chain   = get_chain(s)
    friends = []

    # Збираємо друзів
    ref_uid = s.get("referrer_uid")
    if ref_uid:
        ref_s = db.get(str(ref_uid), {})
        if isinstance(ref_s, dict) and ref_s.get("name"):
            friends.append({
                "name":  ref_s.get("name", "Друг"),
                "chain": get_chain(ref_s).get("length", 0),
                "role":  "friend",
            })

    # Один прохід: top + leaderboard одночасно
    top_chain, top_name = 0, ""
    all_users = []
    uid_str   = str(uid)

    for u, us in db.items():
        if not isinstance(us, dict) or u in DB_SKIP_KEYS:
            continue
        if not us.get("onboarding_done"):
            continue
        cl = (us.get("chain") or {}).get("length") or us.get("streak_days") or 0
        # top (не сам юзер)
        if cl > top_chain and u != uid_str:
            top_chain = cl
            top_name  = us.get("name", "")
        # leaderboard entry
        all_users.append({
            "name":  us.get("name", ""),
            "chain": cl,
            "xp":    us.get("xp_total", 0),
            "me":    u == uid_str,
        })

    # Сортуємо і беремо топ-8 — гарантовано включаємо самого юзера
    all_users.sort(key=lambda x: x["chain"], reverse=True)
    lb_top7  = [u for u in all_users if not u["me"]][:7]
    me_entry = next((u for u in all_users if u["me"]), None)
    lb = (lb_top7 + ([me_entry] if me_entry else []))
    lb.sort(key=lambda x: x["chain"], reverse=True)

    p = get_prices(s)
    boost_until  = s.get("xp_boost_until", "")
    today_str    = datetime.now().strftime("%Y-%m-%d")
    boost_active = bool(boost_until and boost_until >= today_str)
    boost_days   = 0
    if boost_active:
        try:
            boost_days = max(1, (datetime.strptime(boost_until, "%Y-%m-%d") - datetime.now()).days + 1)
        except Exception:
            boost_days = 1

    data = {
        "name":              s.get("name", ""),
        "uid":               uid,
        "chain_length":      chain.get("length", 0),
        "chain_status":      chain.get("status", "new"),
        "trial_links":       7,
        "xp_total":          s.get("xp_total", 0),
        "xp_boost":          boost_active,
        "xp_boost_days":     boost_days,
        "identity_state":    s.get("identity_state", "new"),
        "done_lessons":      len(s.get("done_lessons", [])),
        "streak_days":       chain.get("length", 0),
        "friends":           friends,
        "top_user":          {"name": top_name, "chain": top_chain} if top_name else None,
        "leaderboard_chain": lb,
        "basic_price":       p["basic_price"],
        "basic_link":        p["basic_link"],
        "prem_price":        p["prem_price"],
        "prem_link":         p["prem_link"],
    }
    base = (BOT_WEBHOOK_URL or "").rstrip("/")
    return f"{base}/chain_dashboard?d={_ul.quote(_json.dumps(data, ensure_ascii=False))}"


async def handle_paywall(request):
    """Віддає paywall.html."""
    from aiohttp.web import FileResponse
    import pathlib
    for path in [
        pathlib.Path(__file__).parent / "paywall.html",
        pathlib.Path("paywall.html"),
        pathlib.Path("/app/paywall.html"),
    ]:
        if path.exists():
            return FileResponse(path, headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
            })
    from aiohttp.web import Response
    return Response(text="paywall.html not found", status=404)


def _build_paywall_url(uid: int, s: dict) -> str:
    """Будує URL для Paywall Mini App з усіма потрібними даними."""
    import json as _j, urllib.parse as _ul

    p        = get_prices(s)
    chain    = get_chain(s)
    scores   = s.get("scores", [])
    avg      = round(sum(sc.get("score", 0) for sc in scores[-10:]) / len(scores[-10:])) if scores else 0

    data = {
        "my_name":      s.get("name", ""),
        "my_uid":       uid,
        "chain_length": chain.get("length", 0),
        "done_lessons": len(s.get("done_lessons", [])),
        "xp_total":     s.get("xp_total", 0),
        "avg_score":    avg,
        "level":        s.get("level", "A1"),
        "streak_days":  chain.get("length", 0),
        "basic_price":  p["basic_price"],
        "basic_link":   p["basic_link"],
        "prem_price":   p["prem_price"],
        "prem_link":    p["prem_link"],
        "basic_6m":     p.get("basic_6m_price", ""),
        "basic_6m_link":p.get("basic_6m_link", ""),
        "prem_6m":      p.get("prem_6m_price", ""),
        "prem_6m_link": p.get("prem_6m_link", ""),
        "source":       p["source"],
        "ref_note":     p["ref_note"].strip(),
        "blogger_name": s.get("affiliate_blogger", ""),
    }
    base = (BOT_WEBHOOK_URL or "").rstrip("/")
    return f"{base}/paywall?d={_ul.quote(_j.dumps(data, ensure_ascii=False))}"


async def handle_leaderboard(request):
    """Віддає leaderboard.html."""
    from aiohttp.web import FileResponse
    import pathlib
    for path in [
        pathlib.Path(__file__).parent / "leaderboard.html",
        pathlib.Path("leaderboard.html"),
        pathlib.Path("/app/leaderboard.html"),
    ]:
        if path.exists():
            return FileResponse(path, headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
            })
    from aiohttp.web import Response
    return Response(text="leaderboard.html not found", status=404)


def _build_leaderboard_url(uid: int, s: dict,
                            period: str = "week",
                            db: dict | None = None) -> str:
    """
    Будує URL для Leaderboard Mini App.
    Один прохід по БД — рахує всі 5 категорій одночасно.
    """
    import json as _j, urllib.parse as _ul
    from datetime import timedelta
    if db is None:
        db = load_db()

    today    = datetime.now()
    week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    uid_str  = str(uid)

    # Друг юзера
    ref_uid     = s.get("referrer_uid")
    friend_name = ""
    if ref_uid:
        ref_s = db.get(str(ref_uid), {})
        if isinstance(ref_s, dict):
            friend_name = ref_s.get("name", "")

    users = []
    for u, us in db.items():
        if not isinstance(us, dict) or u in DB_SKIP_KEYS: continue
        if not us.get("onboarding_done"): continue

        chain_len = (us.get("chain") or {}).get("length", 0) or us.get("streak_days", 0) or 0
        xp_total  = us.get("xp_total", 0) or 0
        streak    = chain_len

        # Weekly XP
        week_xp = 0
        for sc in us.get("scores", []):
            if sc.get("date", "")[:10] >= week_ago:
                week_xp += XP_AWARDS.get("session", 15)
        for ph in us.get("mined_sentences", []):
            if ph.get("date", "")[:10] >= week_ago:
                week_xp += XP_AWARDS.get("phrase_saved", 5)

        # Score jump (покращення за тиждень)
        scores    = us.get("scores", [])
        week_s    = [sc.get("score", 0) for sc in scores if sc.get("date","")[:10] >= week_ago]
        old_s     = [sc.get("score", 0) for sc in scores if sc.get("date","")[:10] < week_ago]
        avg_new   = sum(week_s)/len(week_s) if week_s else 0
        avg_old   = sum(old_s)/len(old_s)   if old_s  else avg_new
        jump      = round(avg_new - avg_old, 1)

        # Consistency (7 днів)
        consist = []
        for i in range(6, -1, -1):
            day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            done = any(sc.get("date","")[:10] == day for sc in scores)
            consist.append(1 if done else 0)

        entry = {
            "name":    us.get("name", "")[:20],
            "chain":   chain_len,
            "xp":      xp_total if period == "all" else week_xp,
            "streak":  streak,
            "jump":    max(0, round(jump, 0)),
            "consist": consist,
            "me":      u == uid_str,
            "friend":  (str(ref_uid) == u) if ref_uid else False,
        }
        if us.get("badges"):
            entry["badges"] = us.get("badges", [])[:3]
        users.append(entry)

    # FOMO — чи друг обігнав по chain
    users_by_chain = sorted(users, key=lambda x: x["chain"], reverse=True)
    my_rank     = next((i+1 for i,u in enumerate(users_by_chain) if u["me"]), 0)
    friend_rank = next((i+1 for i,u in enumerate(users_by_chain) if u["friend"]), 0)
    friend_overtook = bool(friend_rank and my_rank and friend_rank < my_rank)

    data = {
        "my_uid":         uid,
        "my_name":        s.get("name", ""),
        "period":         period,
        "category":       "chain",
        "users":          users_by_chain[:20],  # топ-20 достатньо для UI
        "friend_name":    friend_name,
        "friend_overtook":friend_overtook,
        "reset_day":      "понеділок",
    }
    base = (BOT_WEBHOOK_URL or "").rstrip("/")
    return f"{base}/leaderboard?d={_ul.quote(_j.dumps(data, ensure_ascii=False))}"


async def handle_social_invite(request):
    """Віддає social_invite.html."""
    from aiohttp.web import FileResponse
    import pathlib
    for path in [
        pathlib.Path(__file__).parent / "social_invite.html",
        pathlib.Path("social_invite.html"),
        pathlib.Path("/app/social_invite.html"),
    ]:
        if path.exists():
            return FileResponse(path, headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
            })
    from aiohttp.web import Response
    return Response(text="social_invite.html not found", status=404)


def _build_social_invite_url(uid: int, s: dict, db: dict | None = None) -> str:
    """Будує URL для Social/Invite Mini App."""
    import json as _j, urllib.parse as _ul
    if db is None:
        db = load_db()

    chain    = get_chain(s)
    my_chain = chain.get("length", 0)

    # Друг
    ref_uid    = s.get("referrer_uid")
    friend_has = False
    friend_name, friend_chain, friend_uid = "", 0, None
    if ref_uid:
        ref_s = db.get(str(ref_uid), {})
        if isinstance(ref_s, dict) and ref_s.get("name"):
            friend_has   = True
            friend_name  = ref_s.get("name", "Друг")
            friend_chain = get_chain(ref_s).get("length", 0)
            friend_uid   = int(ref_uid)

    # Перевірка Speaking Challenge стану
    sc_state    = s.get("sc_state", "idle")
    my_score    = s.get("sc_score") if sc_state == "done" else None
    my_feedback = s.get("sc_feedback", "")

    # Чи синхронізовані сьогодні
    today = datetime.now().strftime("%Y-%m-%d")
    synced_today = False
    if friend_uid:
        fr_s = db.get(str(friend_uid), {})
        if isinstance(fr_s, dict):
            fr_last = fr_s.get("last_date", "")
            synced_today = (fr_last == today and s.get("last_date", "") == today)

    # Мережа (топ + друзі)
    top_chain, top_name = 0, ""
    for u, us in db.items():
        if not isinstance(us, dict) or u in DB_SKIP_KEYS: continue
        if not us.get("onboarding_done"): continue
        cl = (us.get("chain") or {}).get("length", 0) or 0
        if cl > top_chain and str(u) != str(uid):
            top_chain, top_name = cl, us.get("name", "")

    network = [{"name": s.get("name", "Ти"), "chain": my_chain, "role": "me"}]
    if friend_has:
        network.append({"name": friend_name, "chain": friend_chain, "role": "friend"})
    if top_name and top_name != friend_name:
        network.append({"name": top_name, "chain": top_chain, "role": "top"})

    # Ref link
    username = s.get("username") or str(uid)
    base     = (BOT_WEBHOOK_URL or "").rstrip("/")
    bot_me_username = "SpeakChain_bot"  # fallback — реальний username підставляється в JS

    data = {
        "my_name":             s.get("name", ""),
        "my_uid":              uid,
        "my_chain":            my_chain,
        "my_xp":               s.get("xp_total", 0),
        "friend_name":         friend_name,
        "friend_uid":          friend_uid,
        "friend_chain":        friend_chain,
        "friend_has":          friend_has,
        "bot_username":        bot_me_username,
        "ref_link":            f"https://t.me/{bot_me_username}?start=ref_{username}",
        "challenge_phrase":    s.get("pending_challenge_phrase", "") or s.get("sc_phrase", ""),
        "challenge_translation": "",
        "sc_state":            sc_state,
        "sc_referrer":         s.get("sc_referrer"),
        "my_score":            my_score,
        "my_feedback":         my_feedback,
        "friend_score":        None,
        "synced_today":        synced_today,
        "network":             network,
    }
    return f"{base}/social_invite?d={_ul.quote(_j.dumps(data, ensure_ascii=False))}"


async def handle_chain_dashboard(request):
    """Віддає chain_dashboard.html файл."""
    from aiohttp.web import Response, FileResponse
    import pathlib
    # Шукаємо файл поруч з bot.py
    for path in [
        pathlib.Path(__file__).parent / "chain_dashboard.html",
        pathlib.Path("chain_dashboard.html"),
        pathlib.Path("/app/chain_dashboard.html"),
    ]:
        if path.exists():
            return FileResponse(path, headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
            })
    return Response(text="chain_dashboard.html not found", status=404)


async def handle_wayforpay_pay_page(request):
    from aiohttp.web import Response
    p = dict(request.rel_url.query)
    logger.info(f"WFP /pay: order={p.get('orderReference','?')} amount={p.get('amount','?')} sig={p.get('merchantSignature','?')}")

    base = wfp_base_url()

    # Виправляємо URLs прямо тут
    p["returnUrl"]  = base or "https://t.me/SpeakChainBot"
    p["serviceUrl"] = f"{base}/wayforpay_webhook" if base else ""

    fields = ""
    for k, v in p.items():
        v_safe = str(v).replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        fields += f'<input type="hidden" name="{k}" value="{v_safe}">\n'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>body{{margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#f0f4f8;font-family:sans-serif}}
.wrap{{text-align:center;padding:40px;background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.1)}}
.logo{{font-size:28px;margin-bottom:8px}}p{{color:#666;font-size:16px}}</style>
</head>
<body onload="document.forms[0].submit()">
<div class="wrap">
  <div class="logo">💳</div>
  <p>Переходимо до оплати...</p>
  <form method="POST" action="https://secure.wayforpay.com/pay">
{fields}
  </form>
</div>
</body></html>"""

    return Response(text=html, content_type="text/html")


async def handle_register_ref(request):
    """POST /register_ref — реєструє реферал коли студент відкриває плеєр по ref посиланню."""
    try:
        data     = await request.json()
        uid      = int(data.get("uid", 0))
        ref_code = data.get("ref_code", "").strip()
        if not uid or not ref_code or not ref_code.startswith("ref_"):
            return _web.Response(status=400)

        s = get_s(uid)
        if s.get("affiliate_ref"):
            return _web.Response(text="already_set")

        # Парсимо: ref_BLOGGER_yt_VIDEOID
        rest            = ref_code[4:]  # відрізаємо "ref_"
        ref_without_vid = rest[:-12] if len(rest) > 12 else rest  # -12 = "_" + 11 chars video ID

        platform_map = {
            "_yt": "YouTube", "_ig": "Instagram",
            "_tt": "TikTok",  "_fb": "Facebook",
        }
        platform  = "Unknown"
        clean_ref = ref_without_vid
        for suffix, pname in platform_map.items():
            if ref_without_vid.endswith(suffix):
                platform  = pname
                clean_ref = ref_without_vid[:-len(suffix)]
                break

        upd_s(uid, {
            "affiliate_ref":      ref_code,
            "affiliate_platform": platform,
            "affiliate_blogger":  clean_ref,
        })
        logger.info(f"Ref registered via player uid={uid}: blogger={clean_ref}, platform={platform}")

        # XP рефереру якщо це student-реферал (не блогер)
        db = load_db()
        referrer_uid = next(
            (int(k) for k, v in db.items()
             if isinstance(v, dict) and (v.get("username") == clean_ref or str(k) == clean_ref)
             and not v.get("is_blogger")),
            None
        )
        if referrer_uid:
            upd_s(uid, {"referrer_uid": referrer_uid})
        if referrer_uid:
            from telegram import Bot as _BotRef
            try:
                b = _HTTP_BOT or _BotRef(token=BOT_TOKEN)
                asyncio.ensure_future(award_xp(b, referrer_uid, "friend_joined"))
            except Exception: pass
        return _web.Response(text="ok")
    except Exception as e:
        logger.warning(f"register_ref error: {e}")
        return _web.Response(status=500)


async def handle_captions_proxy(request):
    """Проксі YouTube субтитрів — обхід CORS для player.html."""
    import re as _re
    vid  = request.rel_url.query.get("v", "")
    lang = request.rel_url.query.get("lang", "en")
    if not vid or not _re.match(r'^[\w-]{11}$', vid):
        return _web.Response(status=400)
    url = f"https://www.youtube.com/api/timedtext?lang={lang}&v={vid}&fmt=json3"
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                text = await resp.text()
                return _web.Response(
                    text=text,
                    content_type="application/json",
                    headers={"Access-Control-Allow-Origin": "*"}
                )
    except Exception as e:
        logger.warning(f"Captions proxy error {vid}: {e}")
        return _web.Response(status=404, headers={"Access-Control-Allow-Origin": "*"})


async def handle_session_end(request):
    """POST /session — зберігає час сесії в плеєрі та нараховує XP."""
    try:
        data    = await request.json()
        uid     = int(data.get("uid", 0))
        minutes = int(data.get("minutes", 0))
        if not uid or minutes < 1:
            return _web.Response(status=400)
        s     = get_s(uid)
        total = s.get("player_minutes_total", 0) + minutes
        upd_s(uid, {"player_minutes_total": total})

        # XP за хвилини у плеєрі: 1 XP за кожні 2 хвилини (макс 20 XP за сесію)
        player_xp = min(20, max(1, minutes // 2))

        async def _notify():
            try:
                bot = _HTTP_BOT
                if not bot: return
                s2      = get_s(uid)
                today   = __import__("datetime").date.today().strftime("%Y-%m-%d")
                mult    = 3 if s2.get("triple_xp_date") == today else 1
                final_xp= player_xp * mult
                new_xp  = s2.get("xp_total", 0) + final_xp
                upd_s(uid, {"xp_total": new_xp})

                video_title = data.get("video_title", "").strip()
                video_url   = data.get("video_url", "").strip()
                video_id_s  = data.get("video_id", "").strip()

                # Зберігаємо для дуелі
                duel_topic = f"Перекажи відео: {video_title}" if video_title else "Розкажи про відео яке щойно переглянув"
                upd_s(uid, {
                    "last_player_video_title": video_title,
                    "last_player_video_url":   video_url or (f"https://youtu.be/{video_id_s}" if video_id_s else ""),
                    "pending_duel_topic":      duel_topic,
                    "pending_duel_score":      0,
                })

                xp_line     = f"⚡️ +{final_xp} XP за практику" + (" (×3 🔥)" if mult == 3 else "")
                video_line  = f"\n🎬 _{video_title}_" if video_title else ""
                has_blogger = bool(s2.get("affiliate_blogger"))
                kb_rows     = []
                if has_blogger:
                    kb_rows.append([InlineKeyboardButton("⚔️ Кинути виклик по цьому відео", callback_data="duel_challenge")])
                kb_rows.append([InlineKeyboardButton("🎙 Записати монолог по темі", callback_data="remind_record")])

                await bot.send_message(
                    chat_id=uid,
                    text=(
                        f"🎯 *Сесію завершено!*{video_line}\n\n"
                        f"⏱ Сьогодні у плеєрі: *{minutes} хв*\n"
                        f"📊 Всього практики: *{total} хв*\n"
                        f"{xp_line}\n\n"
                        f"{'🔥 Чудова робота!' if minutes >= 10 else '✅ Гарний старт!'}\n\n"
                        "Закріпи матеріал 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(kb_rows)
                )
            except Exception as e:
                logger.warning(f"Session notify error: {e}")

        asyncio.create_task(_notify())
        return _web.Response(text="ok")
    except Exception as e:
        logger.warning(f"Session end error: {e}")
        return _web.Response(status=500)


async def handle_player_action(request):
    """POST /player_action — дії з плеєра (збереження фрази тощо)."""
    try:
        data   = await request.json()
        uid    = int(data.get("uid", 0))
        action = data.get("action", "")
        if not uid or not action:
            return _web.Response(status=400)

        if action == "save_phrase":
            phrase = data.get("phrase", "").strip()
            if not phrase:
                return _web.Response(status=400)

            async def _save():
                try:
                    s      = get_s(uid)
                    lesson = s.get("current_lesson_data") or {}
                    await _save_mined_sentence(uid, phrase, lesson)
                    due_count = len(_srs_due_words(get_s(uid)))

                    # ── Граматика: визначаємо тему і оновлюємо прогрес ──
                    topic_key = detect_topic(phrase)
                    nudge_msg = None
                    if topic_key:
                        s = mark_topic_event(get_s(uid), topic_key, "phrase_added")
                        upd_s(uid, {"grammar_topics": s["grammar_topics"]})
                        s = get_s(uid)
                        if should_nudge(s, topic_key):
                            phrase_count = s.get("grammar_topics", {}).get(topic_key, {}).get("phrase_count", 0)
                            nudge_msg    = build_nudge_text(topic_key, phrase_count)
                            s = mark_nudge_sent(s, topic_key)
                            upd_s(uid, {"grammar_topics": s["grammar_topics"]})

                    bot = _HTTP_BOT
                    if bot:
                        await bot.send_message(
                            chat_id=uid,
                            text=(
                                f"💎 *Збережено в картотеку!*\n\n"
                                f"▸ _{phrase}_\n\n"
                                f"Повторю через день 🧠 Всього: *{due_count}*"
                            ),
                            parse_mode="Markdown"
                        )
                        if nudge_msg:
                            import asyncio as _aio
                            await _aio.sleep(1)
                            await bot.send_message(
                                chat_id=uid,
                                text=nudge_msg,
                                parse_mode="Markdown",
                                reply_markup=nudge_keyboard()
                            )
                    logger.info(f"Player phrase uid={uid}: {phrase[:50]} → topic:{topic_key}")
                except Exception as e:
                    logger.warning(f"Player action save error: {e}")

            asyncio.create_task(_save())

        return _web.Response(text="ok", headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        logger.warning(f"Player action error: {e}")
        return _web.Response(status=500, headers={"Access-Control-Allow-Origin": "*"})


async def handle_wayforpay_webhook(request):
    """Обробляє webhook від Wayforpay після оплати."""
    from aiohttp.web import Response
    import time
    try:
        data = await request.json()
        logger.warning(f"WFP webhook received: status={data.get('transactionStatus','?')}, order={data.get('orderReference','?')}, recToken={'YES' if data.get('recToken') else 'NO'}")
    except Exception as e:
        logger.warning(f"WFP webhook parse error: {e}")
        return Response(status=400)

    status    = data.get("transactionStatus", "")
    order_ref = data.get("orderReference", "")
    amount    = data.get("amount", "")

    # ── Відповідаємо WayForPay одразу (щоб не було ретраїв) ──
    ts   = int(time.time())
    sign = wfp_sign([WAYFORPAY_MERCHANT, order_ref, "accept", str(ts)])
    ok_response = Response(
        text=f'{{"orderReference":"{order_ref}","status":"accept","time":{ts},"signature":"{sign}"}}',
        content_type="application/json"
    )

    if status != "Approved":
        logger.warning(f"WFP: not approved ({status}), skipping order={order_ref}")
        return ok_response

    if not await wfp_verify_webhook(data):
        logger.warning(f"WFP: invalid signature — ignoring. order={order_ref}, status={status}")
        return ok_response

    user_id, plan = wfp_parse_order(order_ref)
    if not user_id or not plan:
        logger.warning(f"WFP: cannot parse order {order_ref}")
        return ok_response

    # ── Дедублікація — не обробляємо один order двічі ──
    db = load_db()
    processed_orders = db.get("_processed_orders", [])
    if order_ref in processed_orders:
        logger.info(f"WFP: duplicate webhook for {order_ref}, skipping")
        return ok_response
    processed_orders.append(order_ref)
    if len(processed_orders) > 1000:
        processed_orders = processed_orders[-500:]
    upd_s_raw = db
    upd_s_raw["_processed_orders"] = processed_orders
    save_db(upd_s_raw)

    # ── Обробляємо оплату асинхронно після відповіді ──
    rec_token = data.get("recToken", "") or data.get("recTocken", "")
    asyncio.create_task(_process_payment(user_id, plan, amount, order_ref, rec_token))
    logger.warning(f"WFP: queued activation {plan} for user {user_id}, recToken={'YES' if rec_token else 'NO'}")
    return ok_response



async def _invite_to_premium_group(bot, student_uid: int):
    """Надсилає Premium студенту запрошення в групу + привітання від блогера."""
    s2           = get_s(student_uid)
    blogger_name = s2.get("affiliate_blogger", "")
    group_id     = None
    blogger_uid  = None
    blogger_uname= None

    # 1. Спробуємо групу блогера якщо він є
    if blogger_name:
        bloggers = get_registered_bloggers()
        blogger_uid = next(
            (int(uid) for uid, name in bloggers.items()
             if name.lower() == blogger_name.lower()), None
        )
        if blogger_uid:
            bs       = get_s(blogger_uid)
            group_id = bs.get("live_group_id")
            blogger_uname = blogger_name

    # 2. Fallback — загальна Premium група адміна
    if not group_id:
        db       = load_db()
        pg       = db.get("_premium_group", {})
        group_id = pg.get("group_id")

    if not group_id:
        logger.warning(f"_invite_to_premium_group: no group_id for student {student_uid}")
        return

    # Генеруємо персональне одноразове посилання
    try:
        invite = await bot.create_chat_invite_link(
            chat_id      = group_id,
            member_limit = 1,
            name         = f"premium_{student_uid}"
        )
        name = s2.get("name", f"Студент {str(student_uid)[-4:]}")
        blogger_line = (
            f"👤 Куратор: *@{blogger_uname}*\n\n"
            if blogger_uname else ""
        )
        await bot.send_message(
            chat_id    = student_uid,
            text       = (
                f"🎉 *Вітаємо в Premium!*\n\n"
                f"{blogger_line}"
                f"Твоє персональне посилання в Premium групу:\n"
                f"👇 {invite.invite_link}\n\n"
                f"_Там проходять live заняття, Q&A і закрите спілкування_ 🔴\n\n"
                f"⚠️ Посилання одноразове — тільки для тебе"
            ),
            parse_mode = "Markdown"
        )
        logger.info(f"Premium invite sent to {student_uid} → group {group_id}")
    except Exception as e:
        logger.warning(f"_invite_to_premium_group error uid={student_uid}: {e}")
        return

    # Надсилаємо відео-привітання від блогера якщо є
    if blogger_uid:
        bs           = get_s(blogger_uid)
        welcome_fid  = bs.get("welcome_video_file_id") or bs.get("welcome_voice_file_id")
        welcome_type = bs.get("welcome_file_type", "video")
        if welcome_fid:
            try:
                if welcome_type == "video":
                    await bot.send_video(
                        chat_id=student_uid, video=welcome_fid,
                        caption=f"🎬 Особисте привітання від @{blogger_uname} 👋"
                    )
                else:
                    await bot.send_voice(
                        chat_id=student_uid, voice=welcome_fid,
                        caption=f"🎙 Привітання від @{blogger_uname} 👋"
                    )
            except Exception as e:
                logger.warning(f"welcome media send {student_uid}: {e}")

async def _process_payment(user_id: int, plan: str, amount: str, order_ref: str, rec_token: str = ""):
    """Активує план і надсилає повідомлення — викликається після відповіді WayForPay."""
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)

    # Зберігаємо recToken якщо є
    if rec_token:
        upd_s(user_id, {"rec_token": rec_token, "rec_token_plan": plan})
        logger.warning(f"WFP: recToken saved for user {user_id}")
    else:
        logger.warning(f"WFP: no recToken received for user {user_id} (Google Pay or not enabled)")

    # Визначаємо чи це повторна оплата (продовження) чи перша
    s_before     = get_s(user_id)
    is_renewal   = bool(s_before.get("premium_until"))

    # 6-місячний план — активуємо на 180 днів
    if plan in ("basic_6m", "premium_6m"):
        base_plan = plan.replace("_6m", "")
        await activate_plan(bot, user_id, base_plan, 180, is_renewal=is_renewal)
    else:
        await activate_plan(bot, user_id, plan, 30, is_renewal=is_renewal)
    logger.info(f"WFP: ✅ activated {plan} for user {user_id} (renewal={is_renewal})")

    # ── Записуємо подію платежу для нарахування комісії блогеру ──
    s2           = get_s(user_id)
    blogger_name = s2.get("affiliate_blogger", "")
    if blogger_name:
        year_month   = datetime.now().strftime("%Y-%m")
        # Для 6M платежів беремо реальну суму (вже зі знижкою)
        if plan == "basic_6m":
            paid_amount = BASIC_6M_PRICE
        elif plan == "premium_6m":
            paid_amount = PREMIUM_FULL_6M_PRICE
        elif plan == "basic":
            paid_amount = float(BASIC_PRICE)
        else:
            paid_amount = float(PREMIUM_PRICE_FULL)
        rate         = BLOGGER_COMMISSION_BASIC if plan == "basic" else BLOGGER_COMMISSION_PREMIUM
        commission   = round(paid_amount * rate, 2)
        db           = load_db()
        payouts      = db.get("_payouts", [])
        payouts.append({
            "blogger":      blogger_name,
            "student_uid":  str(user_id),
            "student_name": s2.get("name", f"Студент {str(user_id)[-4:]}"),
            "plan":         plan,
            "amount":       paid_amount,
            "commission":   commission,
            "month":        year_month,
            "order_ref":    order_ref,
            "paid":         False,
            "paid_date":    "",
        })
        db["_payouts"] = payouts
        save_db(db)
        logger.info(f"Payout recorded: {blogger_name} ← ${commission} (student {user_id}, {plan})")

    # Premium студент → запрошуємо в групу автоматично
    if plan in ("premium", "premium_6m"):
        asyncio.create_task(_invite_to_premium_group(bot, user_id))

    # Сповіщення адміну — одне повідомлення
    if ADMIN_ID:
        s    = get_s(user_id)
        name = s.get("name", str(user_id))
        ref  = s.get("affiliate_ref", "")
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"💰 *Нова оплата!*\n\n"
                    f"👤 {name} (`{user_id}`)\n"
                    f"📦 План: *{'Basic ⚡️' if plan == 'basic' else 'Premium 🌟'}*\n"
                    f"💵 Сума: *{amount} UAH*\n"
                    f"🔗 Реферал: {ref or '—'}\n"
                    f"🧾 Order: `{order_ref}`"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"WFP admin notify error: {e}")

    # Сповіщення блогеру
    ref = get_s(user_id).get("affiliate_ref", "")
    if ref:
        blogger_name = ref.split("_")[0] if "_" in ref else ref
        bloggers     = get_registered_bloggers()
        blogger_id   = next((int(uid) for uid, n in bloggers.items() if n == blogger_name), None)
        if blogger_id:
            try:
                name = get_s(user_id).get("name", str(user_id))
                await bot.send_message(
                    chat_id=blogger_id,
                    text=(
                        f"🎉 *Твій студент оплатив!*\n\n"
                        f"👤 {name}\n"
                        f"📦 {'Basic ⚡️' if plan == 'basic' else 'Premium 🌟'}\n"
                        f"💰 Твоя комісія нарахована"
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning(f"WFP blogger notify error: {e}")

# ── Кнопка оплати через Wayforpay ────────────────────
async def cmd_test_wrapped(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/test_wrapped [USER_ID] — миттєво надсилає місячний Wrapped."""
    if not is_admin(update.effective_user.id):
        return
    args      = ctx.args or []
    target_id = int(args[0]) if args else update.effective_user.id

    # Підміняємо поточний місяць для тесту
    from datetime import timedelta as _td2
    prev_dt = datetime.now().replace(day=1) - _td2(days=1)
    prev_ym = prev_dt.strftime("%Y-%m")

    db  = load_db()
    s   = get_s(target_id)
    if not s:
        await update.message.reply_text(f"❌ Студента `{target_id}` не знайдено.", parse_mode="Markdown")
        return

    # Рахуємо всіх активних для перцентилю
    all_students = []
    for uid2, s2 in db.items():
        if not isinstance(s2, dict) or str(uid2) in DB_SKIP_KEYS: continue
        if not s2.get("onboarding_done"): continue
        st2 = _month_stats(s2, prev_ym)
        all_students.append((uid2, s2, st2))

    total_active = max(len(all_students), 1)
    stats        = _month_stats(s, prev_ym)
    name         = s.get("name", update.effective_user.first_name)
    level        = s.get("level", "A1")
    blogger      = s.get("affiliate_blogger", "")
    streak       = s.get("streak_days", 0)
    xp           = s.get("xp_total", 0)
    monologues   = stats["monologues"]
    phrases      = stats["phrases"]
    avg_score    = stats["avg_score"]
    month_en     = prev_dt.strftime("%B")
    month_ua     = UA_MONTHS_GEN.get(month_en, month_en)
    year         = prev_dt.strftime("%Y")

    # Перцентиль
    if total_active > 1:
        better_than = sum(1 for _,_,st in all_students if st["monologues"] < monologues or (st["monologues"] == monologues and st["avg_score"] < avg_score))
        pct = int(better_than / (total_active - 1) * 100)
    else:
        pct = 100

    if pct >= 90:   star_line = f"\n🏆 *Ти в топ {100-pct}% студентів {month_ua}!*"
    elif pct >= 70: star_line = f"\n🥈 Ти вище *{pct}%* студентів цього місяця!"
    elif pct >= 50: star_line = f"\n📈 Ти активніше половини студентів!"
    else:           star_line = f"\n💪 Наступний місяць буде кращим!"

    if monologues >= 20:   fact = "20+ монологів — це вже серйозна звичка 🔥"
    elif monologues >= 10: fact = "10+ монологів — ти в топ практикуючих! 💪"
    elif monologues >= 5:  fact = "5+ монологів — мозок вже звикає до мови 🧠"
    elif monologues >= 1:  fact = "Перший крок зроблено — далі буде легше!"
    else:                   fact = "Цей місяць — старт нового тебе 🚀"

    blogger_line = f"\n\n_{month_ua} разом з @{blogger}_ 🎙" if blogger else ""

    text = (
        f"🧪 *Тест Wrapped* для `{target_id}`:\n\n"
        f"🎵 *Твій {month_ua} {year} у SpeakChain*\n\n"
        f"👤 *{name}* · {LEVEL_NAMES.get(level, level)}\n\n"
        f"🎙 Монологів записано: *{monologues}*\n"
        f"📚 Нових фраз: *{phrases}*\n"
        f"🏆 Середній бал: *{avg_score}/100*\n"
        f"🔥 Стрік: *{streak} дн.*\n"
        f"⚡️ XP всього: *{xp:,}*"
        f"{star_line}"
        f"\n\n💡 _{fact}_"
        f"{blogger_line}"
    )

    await ctx.bot.send_message(
        chat_id=target_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Мій прогрес",           callback_data="show_progress"),
             InlineKeyboardButton("🎙 Практикувати",          callback_data="fork_choose")],
            [InlineKeyboardButton("📤 Поділитись у соцмережах", callback_data="share_socials")],
        ])
    )
    if target_id != update.effective_user.id:
        await update.message.reply_text(f"✅ Надіслано до `{target_id}`", parse_mode="Markdown")


async def cmd_test_phrase_of_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/test_phrase [USER_ID] — миттєво надсилає фразу дня."""
    if not is_admin(update.effective_user.id):
        return
    args      = ctx.args or []
    target_id = int(args[0]) if args else update.effective_user.id
    s         = get_s(target_id)
    srs_db    = s.get("srs_words", {})

    if not srs_db:
        await update.message.reply_text(
            f"❌ У студента `{target_id}` немає фраз в SRS колекції.\n\n"
            "Спочатку треба пройти хоча б один урок і зберегти фрази.",
            parse_mode="Markdown"
        )
        return

    import random as _rnd
    candidates = list(srs_db.items())
    candidates.sort(key=lambda x: x[1].get("count_know", 0))
    word, entry = _rnd.choice(candidates[:5])
    translation = entry.get("translation", "")
    example     = entry.get("example", "")

    # Якщо немає перекладу — генеруємо через AI
    if not translation and not example:
        level_   = get_s(target_id).get("level", "A1")
        enriched = await _enrich_phrase(word, level_)
        translation = enriched.get("translation", "")
        example     = enriched.get("example", "")
        if translation or example:
            srs_db[word]["translation"] = translation
            srs_db[word]["example"]     = example
            upd_s(target_id, {"srs_words": srs_db})

    intro = _rnd.choice(PHRASE_OF_DAY_INTROS)

    text = f"🧪 *Тест фрази дня* для `{target_id}`:\n\n{intro}\n\n"
    text += f"🔤 *{word}*"
    if translation: text += f"\n📖 _{translation}_"
    if example:     text += f"\n\n💬 _{example}_"
    text += "\n\n👇 Використай цю фразу у монолозі!"

    await ctx.bot.send_message(
        chat_id=target_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎙 Записати монолог з цією фразою", callback_data="remind_record")],
            [InlineKeyboardButton("⏭ Побачимось завтра",              callback_data="phrase_skip")],
        ])
    )
    if target_id != update.effective_user.id:
        await update.message.reply_text(f"✅ Надіслано до `{target_id}`", parse_mode="Markdown")


async def cmd_test_streak_rescue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/test_streak_rescue [USER_ID] — миттєво надсилає streak rescue."""
    if not is_admin(update.effective_user.id):
        return
    args      = ctx.args or []
    target_id = int(args[0]) if args else update.effective_user.id
    s         = get_s(target_id)
    streak    = s.get("streak_days", 0)
    name      = s.get("name", "")
    name_line = f"*{name}*, " if name else ""

    if streak < 1:
        # Для тесту — показуємо з streak=7
        streak = 7

    msg = random.choice(STREAK_RESCUE_MSGS).format(streak=streak)
    await ctx.bot.send_message(
        chat_id=target_id,
        text=f"🧪 *Тест streak rescue:*\n\n{name_line}{msg}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔥 Врятувати стрік!", callback_data="rescue_choose"),
        ]])
    )
    if target_id != update.effective_user.id:
        await update.message.reply_text(f"✅ Надіслано до `{target_id}`", parse_mode="Markdown")


async def cmd_test_expiry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/test_expiry [3|0|-1] [USER_ID] — миттєво надсилає нагадування про закінчення підписки.
    3  = за 3 дні (default)
    0  = сьогодні останній день
    -1 = вже закінчилась
    """
    if not is_admin(update.effective_user.id):
        return

    args      = ctx.args or []
    scenario  = int(args[0]) if args and args[0] in ("3","0","-1") else 3
    target_id = int(args[1]) if len(args) > 1 else (int(args[0]) if args and args[0] not in ("3","0","-1") else update.effective_user.id)

    s         = get_s(target_id)
    plan      = s.get("plan", "basic")
    plan_name = "Premium 🌟" if plan == "premium" else "Basic ⚡️"
    name      = s.get("name", update.effective_user.first_name)
    has_ref   = bool(s.get("affiliate_ref"))
    lessons   = len(s.get("done_lessons", []))
    phrases   = len(s.get("mined_sentences", []))
    streak    = s.get("streak", 0)

    p           = get_prices(s)
    basic_price = p["basic_price"]
    prem_price  = p["prem_price"]
    basic_link  = p["basic_link"]
    prem_link   = p["prem_link"]
    price_str   = f"${prem_price}" if plan == "premium" else f"${basic_price}"
    wfp_link    = prem_link if plan == "premium" else basic_link

    from datetime import timedelta
    until_str = (datetime.now() + timedelta(days=max(scenario,0))).strftime("%Y-%m-%d")
    pay_url   = wfp_create_payment_url(target_id, plan, float(prem_price if plan == "premium" else basic_price))

    kb = [[InlineKeyboardButton(f"💳 Оплатити {price_str}", url=pay_url)]]
    if wfp_link:
        kb.append([InlineKeyboardButton("🔗 Альтернативне посилання", url=wfp_link)])

    if scenario == 3:
        text = (
            f"⏳ *{name}*, твій план *{plan_name}* закінчується через *3 дні* — {until_str}.\n\n"
            f"🔥 Стрік: *{streak} дн.* | Уроків: *{lessons}*\n\n"
            f"Продовжи зараз і не переривай прогрес — лише *{price_str}/міс*\n\n"
            f"_Оплата займе 30 секунд_ 👇"
        )
    elif scenario == 0:
        text = (
            f"🔔 *{name}*, сьогодні останній день твого плану *{plan_name}*!\n\n"
            f"📊 Твій прогрес:\n"
            f"🎙 Уроків: *{lessons}* | 📚 Фраз: *{phrases}* | 🔥 Стрік: *{streak} дн.*\n\n"
            f"Продовжи підписку прямо зараз — *{price_str}/міс* — і не втрать темп! 👇"
        )
    else:
        text = (
            f"💤 *{name}*, твій доступ до SpeakChain завершився.\n\n"
            f"Але твій прогрес нікуди не дівся:\n"
            f"🎙 *{lessons}* уроків | 📚 *{phrases}* фраз | 🔥 стрік *{streak} дн.*\n\n"
            f"Відновити доступ — лише *{price_str}/міс* 👇"
        )

    await update.message.reply_text(
        f"🧪 *Тест нагадування (сценарій: {scenario} дн.)* для `{target_id}`:\n\n" + text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    # Також надсилаємо студенту якщо target != адмін
    if target_id != update.effective_user.id:
        try:
            await ctx.bot.send_message(
                chat_id=target_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
            await update.message.reply_text(f"✅ Надіслано студенту `{target_id}`", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Не вдалось надіслати студенту: `{e}`", parse_mode="Markdown")


async def cmd_test_renewal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Застаріла — використовуй /test_expiry."""
    await cmd_test_expiry(update, ctx)


async def cmd_test_pay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Адмін: /test_pay — тестовий звичайний платіж (отримуємо recToken)."""
    if not is_admin(update.effective_user.id):
        return
    user = update.effective_user
    plan = (ctx.args[0] if ctx.args else "basic").lower()
    has_ref = bool(get_s(user.id).get("affiliate_ref"))
    amount = float(BASIC_AFFILIATE_PRICE if plan == "basic" and has_ref
                   else BASIC_PRICE if plan == "basic"
                   else PREMIUM_PRICE_AFF if has_ref
                   else PREMIUM_PRICE_FULL)

    pay_url = wfp_create_payment_url(user.id, plan, amount)
    await update.message.reply_text(
        f"🧪 *Тестовий платіж — {plan.upper()}*\n\n"
        f"Сума: *${amount}*\n\n"
        f"Перейди за посиланням → оплати тестовою карткою WayForPay:\n"
        f"`4111 1111 1111 1111` / 11/26 / CVV 111\n\n"
        f"Після оплати в логах Railway побачиш `recToken saved` ✅",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f"💳 Тестова оплата ${amount}", url=pay_url)
        ]])
    )


async def cmd_test_recurrent(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Адмін: /test_recurrent USER_ID — тестове списання 1 грн по recToken."""
    if not is_admin(update.effective_user.id):
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Використання: `/test_recurrent USER_ID`\n\n"
            "Спробує списати 1 грн по збереженому recToken цього студента.",
            parse_mode="Markdown"
        )
        return

    try:
        target_uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ USER_ID має бути числом.")
        return

    s         = get_s(target_uid)
    rec_token = s.get("rec_token", "")
    plan      = s.get("rec_token_plan", "basic")
    name      = s.get("name", str(target_uid))

    if not rec_token:
        await update.message.reply_text(
            f"❌ У студента *{name}* (`{target_uid}`) немає збереженого recToken.\n\n"
            "Можливі причини:\n"
            "• Оплата була через Google Pay (не повертає токен)\n"
            "• Рекурентні платежі не увімкнені в кабінеті WayForPay\n"
            "• Студент ще не платив після оновлення коду",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"🔄 Тестую рекурентне списання для *{name}*...\n"
        f"recToken: `{rec_token[:20]}...`",
        parse_mode="Markdown"
    )

    # Charge API запит
    import time, aiohttp as _aiohttp
    order_id   = f"sc_rec_test_{target_uid}_{int(time.time())}"
    order_date = int(time.time())
    amount     = 1.0
    currency   = "UAH"
    product    = f"SpeakChain {'Basic' if plan == 'basic' else 'Premium'} (тест)"

    domain   = "speakchain.base44.app"
    sign_str = [
        WAYFORPAY_MERCHANT, domain, order_id, str(order_date),
        str(amount), currency, product, "1", str(amount)
    ]
    sig = wfp_sign(sign_str)

    base        = wfp_base_url()
    service_url = f"{base}/wayforpay_webhook" if base else ""
    payload = {
        "transactionType":    "CHARGE",
        "merchantAccount":    WAYFORPAY_MERCHANT,
        "merchantDomainName": domain,
        "orderReference":     order_id,
        "orderDate":          order_date,
        "amount":             str(amount),
        "currency":           currency,
        "productName":        [product],
        "productCount":       ["1"],
        "productPrice":       [str(amount)],
        "recToken":           rec_token,
        "serviceUrl":         service_url,
        "merchantSignature":  sig,
        "apiVersion":         "1",
        "straightCharge":     "1",
    }
    logger.warning(f"WFP test_recurrent payload: merchant={WAYFORPAY_MERCHANT}, domain={domain}, serviceUrl={service_url}, order={order_id}")

    try:
        async with _aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.wayforpay.com/api",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=_aiohttp.ClientTimeout(total=30)
            ) as resp:
                raw = await resp.text()
                logger.warning(f"WFP raw response: {raw[:500]}")
                import json as _json
                try:
                    result = _json.loads(raw)
                except Exception:
                    result = {"transactionStatus": "ERROR", "reason": f"Bad response: {raw[:200]}"}

        logger.warning(f"WFP recurrent test result: {result}")
        status      = result.get("transactionStatus", "")
        reason      = result.get("reason", "")
        reason_code = result.get("reasonCode", "")

        if status == "Approved":
            await update.message.reply_text(
                f"✅ *Рекурентне списання працює!*\n\n"
                f"Студент: *{name}*  |  Сума: *1 UAH*\n\n"
                "Автопідписка готова до роботи 🚀",
                parse_mode="Markdown"
            )

        elif status == "InProcessing":
            # WFP обробляє — перевіримо статус через 40 секунд
            await update.message.reply_text(
                f"⏳ *WFP обробляє транзакцію...*\n\n"
                f"Перевірю статус через 40 секунд автоматично.",
                parse_mode="Markdown"
            )

            async def _check_status_later():
                import asyncio as _asl, aiohttp as _aio2, json as _j2, time as _t2
                await _asl.sleep(40)
                cs_order = order_id
                cs_sign  = wfp_sign([WAYFORPAY_MERCHANT, cs_order])
                cs_payload = {
                    "transactionType":   "CHECK_STATUS",
                    "merchantAccount":   WAYFORPAY_MERCHANT,
                    "orderReference":    cs_order,
                    "merchantSignature": cs_sign,
                    "apiVersion":        "1",
                }
                try:
                    async with _aio2.ClientSession() as s2:
                        async with s2.post(
                            "https://api.wayforpay.com/api",
                            json=cs_payload,
                            headers={"Content-Type": "application/json"},
                            timeout=_aio2.ClientTimeout(total=20)
                        ) as r2:
                            raw2 = await r2.text()
                    cs_result = _j2.loads(raw2)
                    logger.warning(f"WFP CHECK_STATUS: {cs_result}")
                    cs_status = cs_result.get("transactionStatus", "невідомо")
                    cs_reason = cs_result.get("reason", "")
                    cs_code   = cs_result.get("reasonCode", "")

                    if cs_status == "Approved":
                        txt = (
                            f"✅ *Рекурентне списання підтверджено!*\n\n"
                            f"Студент: *{name}*  |  Сума: *1 UAH*\n\n"
                            "Автопідписка готова 🚀"
                        )
                    elif cs_status in ("Declined", "Expired", "Refunded"):
                        txt = (
                            f"❌ *Списання відхилено*\n\n"
                            f"Статус: `{cs_status}`\n"
                            f"Причина: `{cs_reason}` (код: {cs_code})\n\n"
                            "Можливо картка потребує 3DS або не підтримує рекурентні.\n"
                            "Спробуй увімкнути \"Рекурентні без 3DS\" в кабінеті WFP."
                        )
                    else:
                        txt = (
                            f"⚠️ *Статус після перевірки:* `{cs_status}`\n"
                            f"Причина: `{cs_reason}` (код: {cs_code})"
                        )
                    await ctx.bot.send_message(
                        chat_id=update.effective_user.id,
                        text=txt,
                        parse_mode="Markdown"
                    )
                except Exception as ce:
                    logger.error(f"CHECK_STATUS error: {ce}")
                    await ctx.bot.send_message(
                        chat_id=update.effective_user.id,
                        text=f"⚠️ Не вдалось перевірити статус: `{ce}`",
                        parse_mode="Markdown"
                    )

            asyncio.ensure_future(_check_status_later())

        else:
            await update.message.reply_text(
                f"⚠️ *Списання не пройшло*\n\n"
                f"Статус: `{status}`\n"
                f"Причина: `{reason}` (код: {reason_code})\n\n"
                "Перевір налаштування рекурентних платежів в кабінеті WayForPay.",
                parse_mode="Markdown"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка запиту: `{e}`", parse_mode="Markdown")
async def cmd_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показує кнопки оплати з динамічною ціною."""
    user = update.effective_user
    s    = get_s(user.id)
    p             = get_prices(s)
    basic_price   = float(p["basic_price"])
    premium_price = float(p["prem_price"])
    ref_note      = p["ref_note"].replace("\n", " ").strip()

    kb_rows = []

    if WAYFORPAY_MERCHANT and WAYFORPAY_SECRET:
        basic_url   = wfp_create_payment_url(user.id, "basic",   basic_price)
        premium_url = wfp_create_payment_url(user.id, "premium", premium_price)
        kb_rows = [
            [InlineKeyboardButton(f"🌟 Premium — ${premium_price:.0f}/міс {ref_note}".strip(), url=premium_url)],
            [InlineKeyboardButton(f"⚡️ Basic — ${basic_price:.0f}/міс {ref_note}".strip(),    url=basic_url)],
        ]
    else:
        if p["prem_link"]:
            kb_rows.append([InlineKeyboardButton(
                f"🌟 Premium — ${premium_price:.0f}/міс {ref_note}".strip(),
                url=p["prem_link"]
            )])
        if p["basic_link"]:
            kb_rows.append([InlineKeyboardButton(
                f"⚡️ Basic — ${basic_price:.0f}/міс {ref_note}".strip(),
                url=p["basic_link"]
            )])

    # Кнопка перемикання між місячним і 6М
    billing = "monthly"  # дефолт
    await update.message.reply_text(
        "Обери свій план 👇\n\n"
        f"🌟 *Premium — ${premium_price:.0f}/міс*{ref_note}\n"
        "• Все що в Basic + Live sessions з блогером\n\n"
        f"⚡️ *Basic — ${basic_price:.0f}/міс*{ref_note}\n"
        "• Необмежені уроки · Gap analysis · Speaking partner · Roadmap A1→C2\n\n"
        "💡 *Оплати на 6 місяців і зекономь 17%* →",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            kb_rows + [[InlineKeyboardButton(
                "🗓 Показати ціни на 6 місяців (-17%)",
                callback_data="show_6m_plans"
            )]]
        ) if kb_rows else InlineKeyboardMarkup([[
            InlineKeyboardButton("🗓 Показати ціни на 6 місяців (-17%)", callback_data="show_6m_plans")
        ]])
    )

# ── Google Sheets DB backup ───────────────────────────
BACKUP_SHEET_NAME = "DB_Backup"
BLOGGERS_SHEET_NAME = "Bloggers"

def calculate_monthly_payouts(year_month: str | None = None) -> list[dict]:
    """
    Повертає виплати блогерам за місяць (YYYY-MM).
    Записи створюються автоматично в _process_payment при кожній оплаті.
    """
    if not year_month:
        year_month = datetime.now().strftime("%Y-%m")
    db = load_db()
    return [p for p in db.get("_payouts", [])
            if isinstance(p, dict) and p.get("month") == year_month]


def gs_sync_bloggers():
    """Синхронізує список блогерів і статистику в окремий лист Google Sheets."""
    try:
        gc = _get_gs_client()
        if not gc: return
        sh = gc.open_by_key(GOOGLE_SHEET_ID)
        try:
            ws = sh.worksheet("Bloggers")
        except Exception:
            ws = sh.add_worksheet(title="Bloggers", rows=200, cols=12)

        bloggers = get_registered_bloggers()
        codes    = get_blogger_codes()
        db       = load_db()

        headers = [
            "Ім'я", "Telegram ID", "Статус",
            "Студентів всього", "Basic", "Premium", "На тріалі",
            "Активних цього місяця", "Комісія 25% (Basic)", "Комісія 25% (Premium)",
            "Всього доходу", "Дата реєстрації"
        ]
        rows = [headers]

        for uid, name in bloggers.items():
            students = [
                s for k, s in db.items()
                if isinstance(s, dict) and
                s.get("affiliate_blogger","") == name
            ]
            total   = len(students)
            basic   = sum(1 for s in students if is_premium(s) and s.get("plan","basic") == "basic")
            premium = sum(1 for s in students if is_premium(s) and s.get("plan") == "premium")
            trial   = sum(1 for s in students if is_in_trial(s))
            active  = sum(1 for s in students
                          if s.get("last_date","") >= datetime.now().strftime("%Y-%m-01"))
            comm_basic   = round(basic   * float(BASIC_AFFILIATE_PRICE)  * 0.25, 2)
            comm_prem    = round(premium * float(PREMIUM_PRICE_AFF)       * 0.25, 2)
            total_income = round(comm_basic + comm_prem, 2)
            reg_date = db.get(uid, {}).get("registered_at", "—") if uid in db else "—"

            rows.append([
                name, uid, "✅ Активний",
                total, basic, premium, trial, active,
                f"${comm_basic}", f"${comm_prem}", f"${total_income}", reg_date
            ])

        if codes:
            rows.append([])
            rows.append(["⏳ Невикористані коди", *[""] * 11])
            rows.append(["Код", "Для блогера", *[""] * 10])
            for code, name in codes.items():
                rows.append([code, name, *[""] * 10])

        ws.clear()
        ws.update(rows)
        logger.info(f"gs_sync_bloggers: {len(bloggers)} bloggers synced")
    except Exception as e:
        logger.warning(f"gs_sync_bloggers error: {e}")


def gs_sync_payouts():
    """Синхронізує виплати в Google Sheets (лист Payouts)."""
    try:
        gc = _get_gs_client()
        if not gc: return
        sh      = gc.open_by_key(GOOGLE_SHEET_ID)
        ws      = _ensure_sheet(sh, "Payouts", [
            "Місяць","Блогер","Студент","UID","Тариф","Сума($)","Комісія($)","Статус","Дата виплати"
        ])
        db      = load_db()
        payouts = db.get("_payouts", [])
        rows    = []
        for p in sorted(payouts, key=lambda x: (x.get("month",""), x.get("blogger","")), reverse=True):
            rows.append([
                p.get("month",""),
                p.get("blogger",""),
                p.get("student_name",""),
                p.get("student_uid",""),
                p.get("plan",""),
                p.get("amount",""),
                p.get("commission",""),
                "✅ Виплачено" if p.get("paid") else "⏳ Очікує",
                p.get("paid_date",""),
            ])
        if rows:
            ws.clear()
            ws.append_row(["Місяць","Блогер","Студент","UID","Тариф","Сума($)","Комісія($)","Статус","Дата виплати"])
            ws.append_rows(rows)
    except Exception as e:
        logger.warning(f"gs_sync_payouts error: {e}")
    """Синхронізує список блогерів в окремий лист Google Sheets."""
    try:
        gc = _get_gs_client()
        if not gc:
            return
        sh = gc.open_by_key(GOOGLE_SHEET_ID)

        # Створюємо лист якщо не існує
        try:
            ws = sh.worksheet(BLOGGERS_SHEET_NAME)
        except Exception:
            ws = sh.add_worksheet(title=BLOGGERS_SHEET_NAME, rows=100, cols=10)

        bloggers  = get_registered_bloggers()
        codes     = get_blogger_codes()
        db        = load_db()

        # Заголовки
        headers = [
            "Ім'я", "Telegram ID", "Статус",
            "Студентів всього", "Basic", "Premium", "На тріалі",
            "Активних цього місяця", "Дохід (25%)", "Дата реєстрації"
        ]

        rows = [headers]
        for uid, name in bloggers.items():
            students = [
                s for k, s in db.items()
                if isinstance(s, dict) and
                (s.get("affiliate_blogger","") == name or
                 s.get("affiliate_ref","").startswith(name))
            ]
            total   = len(students)
            basic   = sum(1 for s in students if is_premium(s) and s.get("plan","basic") == "basic")
            premium = sum(1 for s in students if is_premium(s) and s.get("plan") == "premium")
            trial   = sum(1 for s in students if is_in_trial(s))
            active  = sum(1 for s in students
                          if s.get("last_date","") >= datetime.now().strftime("%Y-%m-01"))
            revenue = round((basic * float(BASIC_AFFILIATE_PRICE) +
                             premium * float(PREMIUM_AFFILIATE_PRICE)) * 0.25, 2)
            reg_date = db.get(uid, {}).get("registered_at", "—") if uid in db else "—"

            rows.append([
                name, uid, "✅ Активний",
                total, basic, premium, trial,
                active, f"${revenue}", reg_date
            ])

        # Невикористані коди — окремим блоком
        if codes:
            rows.append([])
            rows.append(["⏳ Невикористані коди", "", "", "", "", "", "", "", "", ""])
            rows.append(["Код", "Для блогера", "", "", "", "", "", "", "", ""])
            for code, name in codes.items():
                rows.append([code, name, "", "", "", "", "", "", "", ""])

        ws.clear()
        ws.update(rows)
        logger.info(f"Bloggers sheet synced: {len(bloggers)} bloggers")
    except Exception as e:
        logger.warning(f"gs_sync_bloggers error: {e}")

def gs_save_db_backup():
    """Зберігає весь students.json в Google Sheets (один рядок JSON)."""
    try:
        gc = _get_gs_client()
        if not gc:
            return
        sh  = gc.open_by_key(GOOGLE_SHEET_ID)
        try:
            ws = sh.worksheet(BACKUP_SHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=BACKUP_SHEET_NAME, rows=10, cols=3)
            ws.append_row(["Timestamp", "Size", "Data"])

        db_path = Path(DB)
        if not db_path.exists():
            return
        data_str = db_path.read_text(encoding="utf-8")
        ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        size     = len(data_str)

        # Оновлюємо перший рядок даних (рядок 2)
        try:
            ws.update("A2:C2", [[ts, size, data_str]])
        except Exception:
            ws.append_row([ts, size, data_str])
        logger.info(f"DB backup saved to Sheets ({size} bytes)")
    except Exception as e:
        logger.warning(f"gs_save_db_backup error: {e}")

def gs_load_db_backup() -> bool:
    """Завантажує students.json з Google Sheets при старті."""
    try:
        gc = _get_gs_client()
        if not gc:
            return False
        sh = gc.open_by_key(GOOGLE_SHEET_ID)
        try:
            ws = sh.worksheet(BACKUP_SHEET_NAME)
        except gspread.WorksheetNotFound:
            return False

        rows = ws.get_all_values()
        if len(rows) < 2 or not rows[1][2]:
            return False

        data_str = rows[1][2]
        # Валідуємо JSON
        data = json.loads(data_str)
        if not isinstance(data, dict):
            return False

        # Записуємо в файл
        Path(DB).write_text(data_str, encoding="utf-8")
        logger.info(f"DB restored from Sheets ({len(data)} students)")
        return True
    except Exception as e:
        logger.warning(f"gs_load_db_backup error: {e}")
        return False

async def job_backup_db(ctx):
    """Job: зберігає DB в Sheets кожні 30 хвилин."""
    gs_save_db_backup()

# ── POLYGLOT PATCH — SRS job ──────────────────────────
async def job_srs_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    """Щоденно о 11:00: нагадує про SRS-повторення."""
    db    = load_db()
    today = datetime.now().strftime("%Y-%m-%d")
    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not s.get("onboarding_done"):
            continue
        if not (is_premium(s) or is_in_trial(s)):
            continue
        if s.get("srs_remind_date") == today:
            continue
        due           = _srs_due_words(s)
        video_history = s.get("video_history", [])
        if not due and not video_history:
            continue
        upd_s(int(uid), {"srs_remind_date": today})

        # Вибираємо відео для повторення (найстаріше переглянуте)
        review_video = None
        if video_history:
            # Пропонуємо відео яке давно не переглядали (останнє в списку = найстаріше)
            import random
            review_video = random.choice(video_history[-3:]) if len(video_history) >= 3 else video_history[-1]

        try:
            kb = [[InlineKeyboardButton("🧠 Повторити фрази", callback_data="srs_start"),
                   InlineKeyboardButton("⏭ Пізніше",          callback_data="srs_skip")]]

            if review_video:
                player_url = _player_url(review_video["url"], s)
                kb.insert(0, [InlineKeyboardButton(
                    "▶️ Переглянути знову у плеєрі",
                    web_app=WebAppInfo(url=player_url)
                )] if player_url else [InlineKeyboardButton(
                    "▶️ Переглянути знову",
                    url=review_video["url"]
                )])
                text = (
                    f"🧠 *Час повторити фрази!*\n\n"
                    f"📚 Фраз до повторення: *{len(due)}*\n\n"
                    f"🎬 *З бібліотеки* — переглянь ще раз і потренуй shadowing:\n"
                    f"`youtube.com/watch?v={review_video['vid_id']}`\n\n"
                    "2 хвилини зараз = фраза назавжди 🎯"
                )
            else:
                words_preview = ", ".join(f"*{w['word']}*" for w in due[:4])
                suffix = " та ще..." if len(due) > 4 else ""
                text = (
                    f"🧠 *Час повторити фрази!*\n\n"
                    f"До повторення: {words_preview}{suffix}\n\n"
                    "2 хвилини зараз = фраза назавжди 🎯"
                )

            await ctx.bot.send_message(
                chat_id=int(uid),
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except Exception as e:
            logger.warning(f"SRS reminder failed {uid}: {e}")

# ── POLYGLOT PATCH — Sleep reminder job ───────────────
SLEEP_AUDIO_RESOURCES = {
    "A1": "EnglishClass101 — Slow English Stories (YouTube / Spotify)",
    "A2": "Easy English Podcast або Short Stories in English (Spotify)",
    "B1": "BBC Learning English подкаст або Friends S1 аудіо",
    "B2": "TED Talks audio або Huberman Lab (перші 20 хв)",
    "C1": "Hardcore History або Lex Fridman podcast",
    "C2": "Будь-яка аудіокнига або лекція (MIT, Yale, Stanford)",
}

SLEEP_MESSAGES = [
    "🌙 Ляжеш спати — увімкни *{resource}* тихенько фоном.\n\nМозок засвоює мову навіть уві сні 🧠",
    "🌙 Ніч — найкращий час для пасивного занурення.\n\nВмикай *{resource}* і засинай 🌙",
    "😴 Час готуватись до сну!\n\nВмикай *{resource}* тихо фоном — засинай з англійською 🎧",
    "🌙 Перед сном — 10 хв *{resource}*.\n\nМаленька звичка з великим ефектом 💤",
]

# ── Streak Rescue phrases ────────────────────────────
STREAK_RESCUE_MSGS = [
    "🔥 Твій стрік *{streak} дн.* під загрозою! Запиши один монолог до півночі — і він збережеться!",
    "⚡️ *{streak} днів* практики можуть згоріти сьогодні вночі. Одна хвилина — і стрік врятований!",
    "😱 Сьогодні ще немає активності! Твій стрік *{streak} дн.* зникне о 00:00. Встигни!",
    "🏃 Швидко! Стрік *{streak} дн.* чекає на тебе. Запиши монолог — будь-яку тему, будь-яка довжина!",
    "🔔 Нагадування: сьогодні ти ще не практикував. Стрік *{streak} дн.* — зберегти за 60 секунд?",
]


async def job_streak_rescue(ctx: ContextTypes.DEFAULT_TYPE):
    """Щоденно о 21:00 — нагадує студентам у яких сьогодні ще не було активності і є стрік > 2."""
    import datetime as _dt
    db    = load_db()
    today = datetime.now().strftime("%Y-%m-%d")

    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not s.get("onboarding_done"): continue
        if not (is_premium(s) or is_in_trial(s)): continue

        streak = s.get("streak_days", 0)
        if streak < 2: continue                          # немає що рятувати

        last_date = s.get("last_date", "")
        if last_date == today: continue                  # вже активний сьогодні

        # Не надсилати якщо вже надіслали rescue сьогодні
        if s.get("streak_rescue_date") == today: continue
        upd_s(int(uid), {"streak_rescue_date": today})

        name = s.get("name", "")
        name_line = f"*{name}*, " if name else ""
        msg = random.choice(STREAK_RESCUE_MSGS).format(streak=streak)

        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=f"{name_line}{msg}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔥 Врятувати стрік!", callback_data="rescue_choose"),
                ]])
            )
            logger.info(f"Streak rescue sent to {uid} (streak={streak})")
        except Exception as e:
            logger.warning(f"Streak rescue failed {uid}: {e}")


# ── Phrase of the day messages ───────────────────────
PHRASE_OF_DAY_INTROS = [
    "🌅 *Фраза дня* — починаємо ранок по-англійськи:",
    "💡 *Фраза дня* — одне речення, яке варто запам'ятати:",
    "🎯 *Фраза дня* — спробуй використати її сьогодні:",
    "⚡️ *Фраза дня* — повтори вголос і запам'ятай назавжди:",
    "🔥 *Фраза дня* — ти вже знаєш її, просто нагадуємо:",
    "📚 *Фраза дня* — з твоєї особистої колекції:",
    "🚀 *Фраза дня* — почни день з практики:",
]


async def _enrich_phrase(phrase: str, level: str) -> dict:
    """
    Якщо у фрази немає перекладу/прикладу — генеруємо через Claude.
    Повертає {translation, example} або {}.
    """
    try:
        prompt = (
            f'English phrase: "{phrase}"\n'
            f'Student level: {level}\n\n'
            'Reply ONLY with valid JSON, no markdown:\n'
            '{"translation": "Ukrainian translation", '
            '"example": "Short example sentence in English"}'
        )
        cr = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}]
        )
        import json as _j
        raw = cr.content[0].text.strip()
        raw = raw[raw.find("{"):raw.rfind("}")+1]
        return _j.loads(raw)
    except Exception as e:
        logger.warning(f"_enrich_phrase error: {e}")
        return {}


async def job_phrase_of_day(ctx: ContextTypes.DEFAULT_TYPE):
    """Щоденно о 8:30 — надсилає студенту фразу дня з його SRS колекції."""
    db    = load_db()
    today = datetime.now().strftime("%Y-%m-%d")

    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not s.get("onboarding_done"): continue
        if not (is_premium(s) or is_in_trial(s)): continue
        if s.get("phrase_of_day_date") == today: continue

        srs_db = s.get("srs_words", {})
        if not srs_db:
            continue

        # Всі фрази — з або без перекладу
        candidates = list(srs_db.items())
        if not candidates:
            continue

        # Пріоритет — найменш відомі
        candidates.sort(key=lambda x: x[1].get("count_know", 0))
        import random as _rnd
        word, entry = _rnd.choice(candidates[:5])

        translation = entry.get("translation", "")
        example     = entry.get("example", "")

        # Якщо немає перекладу — генеруємо через AI і зберігаємо
        if not translation and not example:
            level   = s.get("level", "A1")
            enriched = await _enrich_phrase(word, level)
            if enriched:
                translation = enriched.get("translation", "")
                example     = enriched.get("example", "")
                # Зберігаємо в SRS щоб наступного разу не генерувати
                srs_db[word]["translation"] = translation
                srs_db[word]["example"]     = example
                upd_s(int(uid), {"srs_words": srs_db})
            else:
                continue  # AI не відповів — пропускаємо

        intro = _rnd.choice(PHRASE_OF_DAY_INTROS)
        text  = f"{intro}\n\n🔤 *{word}*"
        if translation:
            text += f"\n📖 _{translation}_"
        if example:
            text += f"\n\n💬 _{example}_"
        text += "\n\n👇 Використай цю фразу у монолозі — і вона залишиться назавжди!"

        upd_s(int(uid), {"phrase_of_day_date": today})
        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎙 Записати монолог з цією фразою", callback_data="remind_record")],
                    [InlineKeyboardButton("⏭ Побачимось завтра",              callback_data="phrase_skip")],
                ])
            )
        except Exception as e:
            logger.warning(f"phrase_of_day {uid}: {e}")


async def job_sleep_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    """Щоденно о 22:00: нагадування про пасивне слухання перед сном."""
    db    = load_db()
    today = datetime.now().strftime("%Y-%m-%d")
    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not s.get("onboarding_done"):
            continue
        if not (is_premium(s) or is_in_trial(s)):
            continue
        if s.get("sleep_remind_date") == today:
            continue
        level    = s.get("level", "A1")
        resource = SLEEP_AUDIO_RESOURCES.get(level, "аудіо англійською")
        msg_tmpl = random.choice(SLEEP_MESSAGES)
        upd_s(int(uid), {"sleep_remind_date": today})
        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=msg_tmpl.format(resource=resource),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Вмикаю зараз",  callback_data="immersion_done"),
                    InlineKeyboardButton("⏭ Не сьогодні",   callback_data="sleep_skip"),
                ]])
            )
        except Exception as e:
            logger.warning(f"Sleep reminder failed {uid}: {e}")

# ── Завантаження збережених file_id для аудіо тесту ──
# ── Аудіо для placement test — env vars або файл ──────
# Railway скидає файли при деплої — тому env vars пріоритет
_SAVED_AUDIO_IDS = {}
for _lvl in ["A1","A2","B1","B2","C1"]:
    _fid = os.environ.get(f"AUDIO_{_lvl}", "")
    if _fid:
        _SAVED_AUDIO_IDS[_lvl] = _fid
# Fallback — файл (для локального запуску)
if not any(_SAVED_AUDIO_IDS.values()):
    _audio_cfg = Path("placement_audio_config.json")
    if _audio_cfg.exists():
        try:
            _SAVED_AUDIO_IDS = json.loads(_audio_cfg.read_text())
        except Exception:
            pass

# ── DB ────────────────────────────────────────────────
DB = os.environ.get("DB_PATH", "students.json")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ════════════════════════════════════════════════════════════
# PERFORMANCE LAYER — connection pool + write-behind cache
# ════════════════════════════════════════════════════════════

# ── PostgreSQL Connection Pool (2-8 з'єднань) ──────────────
_PG_POOL = None

def _get_pg_pool():
    """Ліниво ініціалізує connection pool."""
    global _PG_POOL
    if not DATABASE_URL:
        return None
    if _PG_POOL is None:
        try:
            import psycopg2.pool
            _PG_POOL = psycopg2.pool.ThreadedConnectionPool(
                2, 8, DATABASE_URL, sslmode="require",
                connect_timeout=5
            )
            logger.info("✅ PG connection pool ready (2-8 conns)")
        except Exception as e:
            logger.warning(f"PG pool init error: {e}")
    return _PG_POOL

def _pg_conn():
    """Бере з'єднання з пулу (не створює нове щоразу)."""
    pool = _get_pg_pool()
    if not pool:
        return None
    try:
        return pool.getconn()
    except Exception as e:
        logger.warning(f"PG pool getconn: {e}")
        return None

def _pg_release(conn):
    """Повертає з'єднання в пул."""
    pool = _get_pg_pool()
    if pool and conn:
        try:
            pool.putconn(conn)
        except Exception:
            pass

# ── In-memory DB — постійно актуальний, без TTL ────────────
_DB_MEM:   dict = {"data": None}
_DB_DIRTY: set  = set()          # UIDs з незбереженими змінами

def _db_cache_invalidate():
    _DB_MEM["data"] = None

# ── Shared Bot для HTTP handlers (не створюємо щоразу) ─────
_HTTP_BOT = None   # встановлюється в main()


def load_db() -> dict:
    """Повертає in-memory DB (завантажує один раз при старті)."""
    if _DB_MEM["data"] is not None:
        return _DB_MEM["data"]
    # Одноразове завантаження при старті
    if DATABASE_URL:
        conn = _pg_conn()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT data FROM speakchain_db WHERE id='main'")
                    row = cur.fetchone()
                    result = row[0] if row else {}
                    _DB_MEM["data"] = result
                    return result
            except Exception as e:
                logger.warning(f"PG load error: {e}")
            finally:
                _pg_release(conn)
    try:
        result = json.loads(Path(DB).read_text()) if Path(DB).exists() else {}
        _DB_MEM["data"] = result
        return result
    except Exception:
        _DB_MEM["data"] = {}
        return {}


def save_db(db: dict):
    """Зберігає БД в PostgreSQL або JSON. Викликати тільки з flush job."""
    if DATABASE_URL:
        conn = _pg_conn()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO speakchain_db (id, data)
                        VALUES ('main', %s::jsonb)
                        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data
                    """, (json.dumps(db, ensure_ascii=False),))
                conn.commit()
                return
            except Exception as e:
                logger.warning(f"PG save error: {e}")
            finally:
                _pg_release(conn)
    try:
        Path(DB).write_text(json.dumps(db, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning(f"JSON save error: {e}")


# ── Службові ключі в DB які не є юзерами — використовується у всіх job'ах ──
DB_SKIP_KEYS: frozenset = frozenset({
    "_blogger_codes", "_registered_bloggers", "_processed_orders",
    "_payouts", "_partner_queue", "_community_posts", "_feedback_queue",
    "_weekly_questions", "_premium_group", "quiz_cache", "_blogger_challenges", "_active_duels",
})

# ── Rate limiter для масових розсилок ────────────────────────
# Telegram: 30 повідомлень/сек глобально, 1 повідомлення/сек на юзера
# При 5000 юзерів без затримки → 429 Too Many Requests
# asyncio.sleep(0.034) = ~29 msg/sec → безпечно

_TG_SEND_DELAY  = 0.034   # секунд між повідомленнями в job-розсилках
_BATCH_SIZE     = 1000    # юзерів на батч
_BATCH_PAUSE    = 5.0     # секунд паузи між батчами


async def _send_in_batches(bot, tasks: list, batch_size: int = _BATCH_SIZE, pause: float = _BATCH_PAUSE) -> dict:
    """
    Надсилає повідомлення батчами щоб не перевантажувати Telegram.

    tasks — список coroutines або callable що повертають coroutine.
    Кожен батч: batch_size задач → пауза pause секунд → наступний батч.

    При 5000 юзерів і batch_size=1000:
      5 батчів × ~34 сек кожен + 4 паузи × 5 сек = ~190 сек (~3 хв)
    """
    stats = {"sent": 0, "errors": 0}
    total = len(tasks)

    for batch_start in range(0, total, batch_size):
        batch = tasks[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size

        logger.info(f"Batch {batch_num}/{total_batches}: sending {len(batch)} messages")

        for task in batch:
            try:
                if callable(task):
                    result = await task()
                else:
                    result = await task
                if result is not False:
                    stats["sent"] += 1
                else:
                    stats["errors"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.warning(f"batch task error: {e}")
            await asyncio.sleep(_TG_SEND_DELAY)

        # Пауза між батчами (крім останнього)
        if batch_start + batch_size < total:
            logger.info(f"Batch {batch_num} done. Pausing {pause}s before next batch...")
            await asyncio.sleep(pause)

    logger.info(f"All batches done: {stats}")
    return stats

async def _safe_send(bot, chat_id: int, text: str, **kwargs) -> bool:
    """
    Надсилає повідомлення з автоматичним retry при 429.
    Повертає True якщо успішно, False якщо юзер заблокував бота.
    Використовувати в усіх job-циклах замість bot.send_message напряму.
    """
    from telegram.error import RetryAfter, Forbidden, BadRequest
    for attempt in range(3):
        try:
            await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            await asyncio.sleep(_TG_SEND_DELAY)
            return True
        except RetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(f"Rate limit hit for {chat_id}, waiting {wait}s")
            await asyncio.sleep(wait)
        except Forbidden:
            # Юзер заблокував бота — позначаємо і пропускаємо
            upd_s(chat_id, {"bot_blocked": True})
            return False
        except BadRequest as e:
            logger.warning(f"BadRequest {chat_id}: {e}")
            return False
        except Exception as e:
            logger.warning(f"send_message {chat_id} attempt {attempt+1}: {e}")
            await asyncio.sleep(1)
    return False


def get_s(uid: int) -> dict:
    return load_db().get(str(uid), {})


def upd_s(uid: int, data: dict, force: bool = False):
    """
    Оновлює дані юзера в пам'яті.
    force=True → одразу в PostgreSQL (для платежів та критичних даних).
    force=False (default) → тільки в пам'яті, flush кожні 30 сек.
    """
    db = load_db()
    db.setdefault(str(uid), {}).update(data)
    _DB_MEM["data"] = db
    _DB_DIRTY.add(str(uid))
    if force:
        save_db(db)


# ── Batch flush — раз на 30 секунд ──────────────────────────
async def job_flush_db(ctx=None):
    """
    Зберігає тільки змінених юзерів (dirty) замість всього blob.
    При 5000 юзерів з 50 активними: 5ms замість 243ms.

    PostgreSQL: jsonb_set patch по uid замість заміни всього об'єкта.
    Fallback (JSON file): як раніше — весь blob.
    """
    if not _DB_DIRTY:
        return

    dirty_uids  = set(_DB_DIRTY)
    dirty_count = len(dirty_uids)
    _DB_DIRTY.clear()

    db = _DB_MEM.get("data")
    if db is None:
        return

    if DATABASE_URL:
        # ── Patch тільки dirty юзерів через jsonb_set ──────────
        conn = _pg_conn()
        if conn:
            try:
                dirty_patch = {
                    uid: db[uid]
                    for uid in dirty_uids
                    if uid in db
                }
                if dirty_patch:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO speakchain_db (id, data)
                            VALUES ('main', %s::jsonb)
                            ON CONFLICT (id) DO UPDATE
                            SET data = speakchain_db.data || EXCLUDED.data
                        """, (json.dumps(dirty_patch, ensure_ascii=False),))
                    conn.commit()
                logger.info(f"DB flush: {dirty_count} dirty → PG patch ({len(json.dumps(dirty_patch).encode())//1024}KB)")
                return
            except Exception as e:
                logger.warning(f"PG partial flush error: {e} — falling back to full save")
            finally:
                _pg_release(conn)

    # Fallback — JSON file, весь blob
    await asyncio.to_thread(save_db, db)
    logger.info(f"DB flush: {dirty_count} dirty → JSON file")

def _pg_init():
    """Створює таблицю якщо не існує."""
    conn = _pg_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS speakchain_db (
                    id   TEXT PRIMARY KEY DEFAULT 'main',
                    data JSONB NOT NULL DEFAULT '{}'
                )
            """)
            cur.execute("""
                INSERT INTO speakchain_db (id, data)
                VALUES ('main', '{}')
                ON CONFLICT (id) DO NOTHING
            """)
        conn.commit()
        logger.info("✅ PostgreSQL table ready")
    except Exception as e:
        logger.warning(f"PG init error: {e}")
    finally:
        _pg_release(conn)

# ── Social URL detection ──────────────────────────────
def detect_platform(url: str) -> str:
    """Return 'youtube'|'tiktok'|'instagram'|'unknown'"""
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u: return "youtube"
    if "tiktok.com" in u or "vm.tiktok" in u: return "tiktok"
    if "instagram.com" in u or "instagr.am" in u: return "instagram"
    return "unknown"

def is_supported_video(url: str) -> bool:
    return detect_platform(url) != "unknown"

# ── YouTube API search ───────────────────────────────
async def youtube_search(query: str, max_results: int = 5,
                         age_group: str = "adult",
                         max_duration_min: int = 8) -> list[dict]:
    """Search YouTube and return list of {id, url, title, channel, duration_sec}"""
    if not YOUTUBE_API_KEY:
        return []
    # Дітям — short (до 4 хв), дорослим — medium (до 20 хв, фільтруємо по 8 хв нижче)
    duration = "short" if age_group == "kids" else "medium"
    params = {
        "part":             "snippet",
        "q":                query,
        "type":             "video",
        "maxResults":       max_results * 2,  # беремо більше щоб є з чого фільтрувати
        "relevanceLanguage":"en",
        "videoDuration":    duration,
        "videoEmbeddable":  "true",
        "videoSyndicated":  "true",
        "videoDefinition":  "high",
        "videoCategoryId":  "27",
        "order":            "relevance",
        "key":              YOUTUBE_API_KEY,
    }
    search_url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                data = await r.json()

        video_ids = [
            item["id"].get("videoId","")
            for item in data.get("items", [])
            if item["id"].get("videoId","")
        ]
        if not video_ids:
            return []

        # Запитуємо тривалість через contentDetails
        details_url = (
            "https://www.googleapis.com/youtube/v3/videos?"
            + urllib.parse.urlencode({
                "part": "contentDetails,snippet",
                "id":   ",".join(video_ids),
                "key":  YOUTUBE_API_KEY,
            })
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(details_url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                details = await r.json()

        def parse_duration(iso: str) -> int:
            """ISO 8601 PT4M13S → секунди."""
            import re
            m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
            if not m: return 9999
            h, mn, s = (int(x or 0) for x in m.groups())
            return h * 3600 + mn * 60 + s

        results = []
        for item in details.get("items", []):
            vid_id   = item.get("id","")
            duration = parse_duration(item.get("contentDetails",{}).get("duration",""))
            # Відфільтровуємо відео довші max_duration_min хвилин
            if duration > max_duration_min * 60:
                continue
            snippet = item.get("snippet", {})
            results.append({
                "id":           f"yt_{vid_id}",
                "url":          f"https://www.youtube.com/watch?v={vid_id}",
                "title":        snippet.get("title", ""),
                "channel":      snippet.get("channelTitle", ""),
                "duration_sec": duration,
            })
            if len(results) >= max_results:
                break

        return results
    except Exception as e:
        logger.warning(f"YouTube API error: {e}")
        return []

# ── Next unmastered CEFR topic ───────────────────────
def next_cefr_topic(s: dict) -> str | None:
    """Return the first unmastered grammar topic for the student's level."""
    level    = s.get("level", "A1")
    mastered = s.get("mastered_grammar", [])
    for topic in CEFR_GRAMMAR.get(level, []):
        if topic not in mastered:
            return topic
    return None

# Map CEFR topic → concise YouTube search keywords
CEFR_TOPIC_QUERIES = {
    # ── A1 ──
    "The ABC, spelling":                              "English alphabet spelling pronunciation beginner",
    "The Numbers":                                    "English numbers counting ordinal cardinal beginner",
    "a / an":                                         "English indefinite article a an beginner lesson",
    "Countable nouns with a/an and some":             "countable nouns a an some English beginner",
    "Present Simple":                                 "present simple English lesson facts habits",
    "Present Continuous":                             "present continuous English lesson now",
    "Non-Continuous Verbs (stative)":                 "stative verbs know want like English lesson",
    "Imperative Mood":                                "imperative mood English commands requests",
    "Possessive Case ('s / s')":                      "possessive case apostrophe s English",
    "In, on, at — time":                              "prepositions time in on at English lesson",
    "Comparative and Superlative Degrees":            "comparative superlative adjectives English lesson",
    "Zero Conditional":                               "zero conditional English if always true",
    "Modal Verbs: basic (can/must/should)":           "modal verbs can must should English beginner",
    "Going to (future plans)":                        "going to future plans English lesson",
    "Question Tags":                                  "question tags English isn't it aren't they",
    # ── A2 ──
    "Past Simple":                                    "past simple English lesson irregular verbs",
    "Future Simple (will)":                           "will future simple English predictions",
    "The (definite article)":                         "definite article the English lesson",
    "Uncountable nouns":                              "uncountable nouns some any much English",
    "Few, little, a few, a little, much, many":       "few little much many quantifiers English",
    "Adverbs":                                        "adverbs English manner frequency place",
    "As … as / Than":                                 "as as than comparisons English",
    "Used to":                                        "used to past habits English lesson",
    "First Conditional":                              "first conditional English real future if",
    "Gerund + V (basic)":                             "gerund after verbs like enjoy love English",
    "Infinitive + V (basic)":                         "infinitive after verbs want need would like English",
    "Modal Verbs: extended (might/may/have to/could)":"might may have to could modal English",
    # ── B1 ──
    "Present Perfect":                                "present perfect English ever never just already yet",
    "Present Perfect Continuous":                     "present perfect continuous English been doing",
    "Past Continuous":                                "past continuous English was doing background",
    "Passive Voice (Present & Past)":                 "passive voice is made was built English lesson",
    "Second Conditional":                             "second conditional English hypothetical if were would",
    "Enough and too":                                 "enough too English too cold not warm enough",
    "Because / Because of":                           "because because of English cause reason",
    "Despite / In spite of":                          "despite in spite of English concession",
    "As soon as / As long as":                        "as soon as as long as English time conditionals",
    "Gerund + V (full system)":                       "gerund avoid keep suggest consider English",
    "Infinitive + V (full system)":                   "infinitive decide manage refuse agree English",
    "Would rather / sooner / better":                 "would rather sooner better English preference",
    "Be used to / Get used to":                       "be used to get used to English adaptation habit",
    "Either … or / Neither … nor":                    "either or neither nor English correlative conjunctions",
    "Modal Verbs: advanced (must have / can't have / should have)": "must have can't have should have modals English",
    "Reported Speech":                                "reported speech indirect speech English said asked",
    # ── B2 ──
    "Past Perfect":                                   "past perfect English had done before",
    "Past Perfect Continuous":                        "past perfect continuous English had been doing",
    "Future Perfect":                                 "future perfect English will have done",
    "Future Continuous":                              "future continuous English will be doing",
    "Future Perfect Continuous":                      "future perfect continuous English will have been",
    "Third Conditional":                              "third conditional English if had done would have",
    "Passive Voice (Continuous)":                     "passive continuous is being built was being repaired English",
    "Participle 1 (Present Participle)":              "present participle clause English running catching",
    "Participle 2 (Past Participle)":                 "past participle clause English written broken",
    "It is said that …":                              "impersonal passive it is said believed reported English",
    "Complex Object":                                 "complex object want him to go saw her leave English",
    "Everyone, everybody / Either, neither of + Prep":"neither of either of everyone everybody English",
    "Wish / If only":                                 "wish if only English unreal past regret",
    "Mixed Conditionals":                             "mixed conditionals English past present unreal",
    # ── C1 ──
    "He is said to / He is supposed to":             "personal passive said to supposed to believed to English C1",
    "Complex Subject":                               "complex subject known to have lived seems to be English C1",
    "The Prepositional Infinitive Complex":          "for object infinitive important for him to attend English",
    "Inversion (emphatic structures)":               "inversion emphatic never have I not only did English C1",
    "Cleft Sentences":                               "cleft sentences it was who what I need is English C1",
    # ── C2 ──
    "Stylistic inversion for literary effect":              "stylistic inversion literary English C2",
    "Nuanced modal meanings (epistemic / deontic / dynamic)": "modal verbs epistemic deontic meaning English",
    "Advanced ellipsis in complex discourse":               "ellipsis complex discourse advanced English",
    "Rhetoric devices (anaphora, chiasmus, litotes)":       "rhetoric devices anaphora chiasmus English",
    "Discourse cohesion across paragraphs":                 "discourse cohesion paragraphs academic English",
    "Irony, understatement and euphemism in context":       "irony understatement euphemism English",
    "Complex syntax: multiple embedded clauses":            "complex syntax embedded clauses English C2",
    "Idiomatic and colloquial precision":                   "idiomatic colloquial English native precision",
    "Lexical density and academic register":                "lexical density academic register English C2",
    "Pragmatics: implicature and indirect speech acts":     "pragmatics implicature indirect speech English",
}

# ── Build a live lesson from YouTube API ─────────────
async def youtube_search_lesson(s: dict) -> dict | None:
    """
    Search YouTube for a lesson video targeting the next unmastered CEFR topic,
    personalised to the student's interests and goal.
    Якщо є pending_gaps — пріоритет gap над черговою CEFR темою.
    Якщо студент прийшов від блогера — спочатку шукаємо відео цього каналу.
    """
    goal      = s.get("goal", "daily")
    level     = s.get("level", "A1")
    interests = s.get("interests", [])
    profession= s.get("profession", "")
    age_group = s.get("age_group", "adult")
    blogger   = s.get("affiliate_blogger", "")  # блогер студента

    # Вікові підказки для запиту — враховуємо точний вік дитини
    kids_age = s.get("kids_age", "")
    kids_sub = s.get("kids_sub", "")
    if kids_sub == "lullaby":
        age_hint = "lullaby nursery rhymes babies English"
        max_dur_override = None
    elif kids_sub == "games":
        age_hint = "English games activities toddlers 1 2 3 years"
        max_dur_override = None
    elif kids_age == "0–1 рік":
        age_hint = "for babies toddlers nursery rhymes"
        max_dur_override = None
    elif kids_age == "4–6 років":
        age_hint = "for kids preschool kindergarten"
        max_dur_override = 5
    elif kids_age == "7–9 років":
        age_hint = "for kids elementary school"
        max_dur_override = 6
    elif kids_age == "10–12 років":
        age_hint = "for kids tweens"
        max_dur_override = 7
    elif kids_age == "13–15 років":
        age_hint = "for teenagers"
        max_dur_override = 8
    elif age_group == "kids":
        age_hint = "for kids children"
        max_dur_override = 5
    elif age_group == "teen":
        age_hint = "for teenagers"
        max_dur_override = 8
    elif age_group == "senior":
        age_hint = "for adults"
        max_dur_override = None
    else:
        age_hint = ""
        max_dur_override = None

    # ── Step 1: перевіряємо pending_gaps (пріоритет) ──
    pending_gaps = s.get("pending_gaps", {})
    gap_query    = pending_gaps.get("grammar_query", "") if pending_gaps else ""
    cefr_topic   = None

    # ── Тип уроку: чергуємо теоретичний і практичний ──
    lessons_done = len(s.get("done_lessons", []))
    is_practice  = (lessons_done % 2 == 1)  # непарний урок = практика

    if gap_query:
        interest_hint = interests[0] if interests else (profession or "")
        if is_practice:
            query = f"{gap_query} shadowing repeat after me practice {age_hint}".strip()
        else:
            query = f"{gap_query} explained short {age_hint} {interest_hint}".strip()
        cefr_topic = pending_gaps.get("grammar_gap", "")
    else:
        # ── Step 2: черговa CEFR тема ──
        cefr_topic = next_cefr_topic(s)
        if cefr_topic:
            grammar_query = CEFR_TOPIC_QUERIES.get(cefr_topic, cefr_topic.lower())
            interest_hint = interests[0] if interests else (profession or "")
            if is_practice:
                query = f"{grammar_query} shadowing dialogue practice {age_hint}".strip()
            else:
                query = f"{grammar_query} explained short {age_hint} {interest_hint}".strip()
        else:
            goal_hints = {
                "travel":  "travel English conversation",
                "work":    "business English speaking",
                "study":   "academic English speaking",
                "daily":   "everyday English conversation",
                "kids":    "English for kids",
            }
            level_hints = {
                "A1": "beginner", "A2": "elementary",
                "B1": "intermediate", "B2": "upper intermediate",
                "C1": "advanced", "C2": "proficiency",
            }
            base      = goal_hints.get(goal, "English speaking")
            lvl_hint  = level_hints.get(level, "")
            personal  = interests[0] if interests else (profession or "")
            if is_practice:
                query = f"{base} shadowing repeat after me {age_hint}".strip()
            else:
                query = f"{base} {lvl_hint} explained short {age_hint} {personal}".strip()
            cefr_topic = None

    # Для практики ліміт 8 хв, для теорії 5 хв
    # Для малюків — ще коротші
    if max_dur_override:
        max_dur = max_dur_override
    else:
        max_dur = 8 if is_practice else 5

    # ── Якщо студент від блогера — спочатку шукаємо на його каналі ──
    blogger_results = []
    if blogger:
        blogger_query = f"{query} {blogger}"
        blogger_results = await youtube_search(blogger_query, max_results=3,
                                                age_group=age_group, max_duration_min=max_dur)

    results = await youtube_search(query, max_results=5, age_group=age_group, max_duration_min=max_dur)

    # Відео блогера ставимо першими
    if blogger_results:
        seen = {r["id"] for r in blogger_results}
        other = [r for r in results if r["id"] not in seen]
        results = blogger_results + other

    if not results:
        return None

    # Pick first result not already done
    done = s.get("done_lessons", [])
    for r in results:
        if r["id"] not in done:
            try:
                interests_str = ", ".join(interests) or "general"
                grammar_hint  = f'Focus specifically on teaching "{cefr_topic}" grammar.' if cefr_topic else ""
                pr = (
                    f"Student level: {level}. Video: \"{r['title']}\" by {r.get('channel','')}.\n"
                    f"Goal: {goal}. Profession: {profession or 'unknown'}. "
                    f"Interests: {interests_str}.\n"
                    f"{grammar_hint}\n"
                    f"Create a speaking practice task. The task must start with the exact phrase in Ukrainian: "
                    f"'А тепер практика: повтори те, що говорилось у відео. Рекомендую застосувати і модифікувати ці речення до себе та свого життя — так мозок включається активніше.' "
                    f"Then add 2-3 personalised example sentences from the video using their interest context. Reply ONLY:\n"
                    f"TOPIC: [start with the fixed Ukrainian phrase above, then add 1 personalised sentence]\n"
                    f"GRAMMAR: [{cefr_topic or 'grammar focus for ' + level}]\n"
                    f"HINT: [2-3 English sentence starters from the video adapted to their interests]"
                )
                cr = claude_client.messages.create(
                    model="claude-haiku-4-5-20251001", max_tokens=200,
                    messages=[{"role": "user", "content": pr}]
                )
                task    = cr.content[0].text
                topic   = "А тепер практика: повтори те, що говорилось у відео. Рекомендую застосувати і модифікувати ці речення до себе та свого життя — так мозок включається активніше."
                grammar = cefr_topic or "Present Simple + I think / I believe"
                hint    = "I think the main idea is... / In my life I also... / I found it interesting that..."
                for line in task.splitlines():
                    line = line.strip()
                    if line.startswith("TOPIC:"):     topic   = line[6:].strip()
                    elif line.startswith("GRAMMAR:"):  grammar = line[8:].strip()
                    elif line.startswith("HINT:"):     hint    = line[5:].strip()
            except Exception as e:
                logger.warning(f"Lesson task generation error: {e}")
                topic   = "А тепер практика: повтори те, що говорилось у відео. Рекомендую застосувати і модифікувати ці речення до себе та свого життя — так мозок включається активніше."
                grammar = cefr_topic or "Present Simple + I think / I believe"
                hint    = "I think the main idea is... / In my life I also... / I found it interesting that..."

            return {
                "id":         r["id"],
                "url":        r["url"],
                "title":      r["title"],
                "channel":    r.get("channel", ""),
                "topic":      topic,
                "grammar":    grammar,
                "hint":       hint,
                "cefr_topic": cefr_topic,
                "source":     "api",
                "gap_used":   bool(gap_query),  # True якщо урок підібраний під gap
            }
    return None

# ── Gap analysis via Claude ───────────────────────────
async def analyse_gaps(transcript: str, level: str, grammar_focus: str,
                       interests: list, profession: str) -> dict:
    """Claude identifies grammar/vocabulary gaps — with caching."""
    interests_str = ", ".join(interests[:3]) if interests else "general"

    # Кешуємо по рівню і граматиці (не по транскрипту — він унікальний)
    # Але кешуємо search queries — вони залежать від рівня і граматики
    cache_key = f"gaps_{level}_{grammar_focus[:30]}_{interests_str[:20]}"
    cached = claude_cache_get(cache_key)
    if cached:
        logger.info(f"Gap analysis cache HIT: {cache_key}")
        return cached

    prompt = f"""English coach. Student level: {level}. Lesson grammar: {grammar_focus}.
Profession: {profession or 'unknown'}. Interests: {interests_str}.
Transcript: \"\"\"{transcript[:500]}\"\"\"

Reply ONLY JSON (no markdown):
{{"grammar_gap":"Ukrainian description","vocab_gap":"Ukrainian description","grammar_query":"youtube search query","vocab_query":"youtube search query","reinforce_query":"youtube search query"}}"""

    try:
        cr = claude_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = re.sub(r"```json|```", "", cr.content[0].text).strip()
        result = json.loads(raw)
        claude_cache_set(cache_key, result, ttl_hours=12)
        return result
    except Exception as e:
        logger.warning(f"Gap analysis error: {e}")
        return {}


# ── Streak helpers ────────────────────────────────────

def count_plans(students_iter, db=None):
    """Рахує Basic, Premium і тріал серед студентів."""
    basic = premium = trial = 0
    for s in students_iter:
        if not isinstance(s, dict): continue
        if is_in_trial(s):    trial   += 1
        elif is_premium(s):
            if s.get("plan") == "premium": premium += 1
            else:                          basic   += 1
    return basic, premium, trial

def plans_line(basic, premium, trial):
    """Форматує рядок Basic/Premium/Trial."""
    parts = []
    if basic:   parts.append(f"⚡️Basic:{basic}")
    if premium: parts.append(f"🌟Premium:{premium}")
    if trial:   parts.append(f"🎁Тріал:{trial}")
    return "  ".join(parts) if parts else "немає платних"

def get_streak(s: dict) -> int:
    return s.get("streak_days", 0)

def update_streak(uid: int) -> tuple[int, bool]:
    import datetime as _dt
    s      = get_s(uid)
    today  = datetime.now().strftime("%Y-%m-%d")
    last   = s.get("last_date", "")
    streak = s.get("streak_days", 0)
    best   = s.get("best_streak", 0)
    if last == today:
        return streak, False
    yesterday = (_dt.datetime.now() - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
    streak = streak + 1 if last == yesterday else 1
    is_record = streak > best
    upd_s(uid, {"streak_days": streak, "best_streak": max(streak, best), "last_date": today})

    # XP за стрік-майлстони (тільки в перший раз досягнення)
    s2 = get_s(uid)
    if streak == 7  and s2.get("xp_streak7_date")  != today:
        upd_s(uid, {"xp_streak7_date":  today})
        return "streak_7"
    if streak == 30 and s2.get("xp_streak30_date") != today:
        upd_s(uid, {"xp_streak30_date": today})
        return "streak_30"
    return None


STREAK_MILESTONES = {3, 7, 14, 30, 60, 100}

def streak_message(streak: int, is_record: bool) -> str:
    if streak in STREAK_MILESTONES or is_record:
        emojis = {3:"🔥",7:"⚡️",14:"🚀",30:"🏆",60:"💎",100:"👑"}
        e = emojis.get(streak, "🌟")
        if is_record and streak > 7:
            return f"\n\n{e} *{streak} днів поспіль — твій новий рекорд!* Так тримати!"
        return f"\n\n{e} *{streak} днів поспіль!* Це вже справжній стрік!"
    if streak > 1:
        return f"\n\n🔥 Стрік: *{streak} дні поспіль*"
    return ""

# ════════════════════════════════════════════════════════════
# POLYGLOT PATCH — SRS (Spaced Repetition System)
# ════════════════════════════════════════════════════════════

def _srs_next_date(action: str, prev_interval_days: int = 0) -> str:
    """Розраховує дату наступного повторення (спрощений SM-2)."""
    import datetime as _dt
    INTERVALS = [1, 3, 7, 14, 30, 60]
    if action == "know":
        idx = 0
        for i, d in enumerate(INTERVALS):
            if prev_interval_days >= d:
                idx = i + 1
        next_days = INTERVALS[min(idx, len(INTERVALS) - 1)]
    else:
        next_days = 1
    return (_dt.datetime.now() + _dt.timedelta(days=next_days)).strftime("%Y-%m-%d")

async def _srs_update_word(uid: int, word_data: dict, action: str):
    """Оновлює SRS-статус слова/фрази в профілі студента."""
    s    = get_s(uid)
    word = word_data.get("word", "")
    if not word:
        return
    srs_db = s.get("srs_words", {})
    entry  = srs_db.get(word, {"interval_days": 0, "count_know": 0, "count_learn": 0})
    INTERVALS = [1, 3, 7, 14, 30, 60]
    if action == "know":
        entry["count_know"] = entry.get("count_know", 0) + 1
        prev_idx = 0
        for i, d in enumerate(INTERVALS):
            if entry.get("interval_days", 0) >= d:
                prev_idx = i + 1
        entry["interval_days"] = INTERVALS[min(prev_idx, len(INTERVALS) - 1)]
        entry["next_review"]   = _srs_next_date("know", entry["interval_days"])
    else:
        entry["count_learn"]   = entry.get("count_learn", 0) + 1
        entry["interval_days"] = 1
        entry["next_review"]   = _srs_next_date("learn", 0)
    srs_db[word] = entry
    learned = s.get("vocab_learned", [])
    if action == "know" and word not in learned:
        learned = learned + [word]
    upd_s(uid, {
        "srs_words":           srs_db,
        "vocab_learned":       learned,
        "vocab_session_known": s.get("vocab_session_known", 0) + (1 if action == "know" else 0),
    })

def _srs_due_words(s: dict) -> list:
    """Повертає список слів/фраз до повторення сьогодні (макс. 10)."""
    today  = datetime.now().strftime("%Y-%m-%d")
    srs_db = s.get("srs_words", {})
    due = [
        {"word": w, "interval_days": e.get("interval_days", 0)}
        for w, e in srs_db.items()
        if not e.get("next_review") or e.get("next_review", "") <= today
    ]
    due.sort(key=lambda x: x["interval_days"])
    return due[:10]

# ════════════════════════════════════════════════════════════
# POLYGLOT PATCH — Milestones + «До/Після»
# ════════════════════════════════════════════════════════════

MILESTONES = {
    1:   ("🎉", "Перший монолог! Ти вже говориш англійською — це не жарт."),
    3:   ("🔥", "3 уроки! Ти вже в топ-20% тих хто починав."),
    5:   ("⚡️", "5 уроків! Твій мозок вже адаптується до мови."),
    7:   ("🚀", "7 уроків — тиждень щоденної практики! Це реальна звичка."),
    10:  ("🏆", "10 уроків! Ось твій прогрес — порівняй себе на старті і зараз."),
    15:  ("💎", "15 уроків! Ти в 5% найстійкіших студентів SpeakChain."),
    20:  ("👑", "20 уроків! Більшість кидають на першому тижні. Ти — ні."),
    30:  ("🌟", "30 уроків — місяць практики! Тут починається справжній прогрес."),
    50:  ("🎓", "50 уроків! Ти вже не той, хто починав. Серйозно."),
    100: ("🏅", "100 уроків! Ти офіційно поліглот-практик SpeakChain. Легенда."),
}

MILESTONE_LEVEL_MESSAGES = {
    "A1": "Ти вже можеш познайомитись і розповісти про себе 🌱",
    "A2": "Замовляєш їжу, орієнтуєшся в місті, розумієш прості тексти ✈️",
    "B1": "Розмовляєш на побутові теми, висловлюєш думки, дивишся відео з субтитрами 💬",
    "B2": "Проводиш ділові зустрічі, дивишся серіали без субтитрів, читаєш статті 🎯",
    "C1": "Пишеш есе, ведеш переговори, розумієш гумор носіїв 🏆",
    "C2": "Говориш як носій мови. Дослівно 👑",
}

async def check_and_send_milestone(bot, user_id: int, lesson_count: int, s: dict):
    """Перевіряє Milestone після N уроків і надсилає святковий момент."""
    if lesson_count not in MILESTONES:
        return
    emoji, msg    = MILESTONES[lesson_count]
    level         = s.get("level", "A1")
    level_name    = LEVEL_NAMES.get(level, level)
    level_msg     = MILESTONE_LEVEL_MESSAGES.get(level, "")
    streak        = s.get("streak_days", 0)
    mined_cnt     = len(s.get("mined_sentences", []))
    first_file    = s.get("first_voice_file_id", "")
    first_date    = s.get("first_voice_date", "")
    first_score   = s.get("first_voice_score", 0)
    last_scores   = s.get("scores", [])
    recent_score  = last_scores[-1].get("score", 0) if last_scores else 0

    text = (
        f"{emoji} *Milestone: {lesson_count} {'урок' if lesson_count == 1 else 'уроків'}!*\n\n"
        f"{msg}\n\n"
        f"📊 Рівень: *{level_name}*\n"
        f"🔥 Стрік: *{streak} дн.*\n"
        f"💎 Збережених фраз: *{mined_cnt}*\n\n"
        f"_{level_msg}_"
    )

    kb_rows = [
        [InlineKeyboardButton("📤 Поділитись досягненням", callback_data="share_socials")],
    ]

    # ── Спеціальний момент на уроці 10: «До і після» ──
    if lesson_count == 10 and first_file and recent_score > 0:
        diff = recent_score - first_score
        sign = "+" if diff >= 0 else ""
        text += (
            f"\n\n🎙 *Твій прогрес у говорінні:*\n"
            f"Перший монолог: *{first_score}/100* _{first_date}_\n"
            f"Зараз: *{recent_score}/100*\n"
            f"Зростання: *{sign}{diff} балів* {'📈' if diff >= 0 else '📉'}\n\n"
            "⬇️ Нижче — твій перший голосовий запис"
        )
        kb_rows.insert(0, [InlineKeyboardButton(
            "🎙 Порівняти голоси", callback_data="before_after"
        )])

    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )
        if lesson_count == 10 and first_file:
            await bot.send_voice(
                chat_id=user_id,
                voice=first_file,
                caption=f"🎙 Твій перший монолог — _{first_date}_",
                parse_mode="Markdown"
            )
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "⬆️ Твій перший монолог\n\n"
                    "Чуєш різницю? Це і є прогрес.\n\n"
                    "_Продовжуй — через 10 уроків ти знову почуєш цю різницю_ 🚀"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🎯 Далі!", callback_data="fork_choose")
                ]])
            )
    except Exception as e:
        logger.warning(f"Milestone send error {user_id}: {e}")

# ── Premium helpers ───────────────────────────────────
# ── Basic план ───────────────────────────────────────
BASIC_PRICE          = os.environ.get("BASIC_PRICE", "22.00")
BASIC_AFFILIATE_PRICE= os.environ.get("BASIC_AFFILIATE_PRICE", "19.77")
BASIC_FRIEND_PRICE   = os.environ.get("BASIC_FRIEND_PRICE", "19.77")  # ціна для друзів

# ── Комісії блогерів ──────────────────────────────────
BLOGGER_COMMISSION_BASIC    = float(os.environ.get("BLOGGER_COMMISSION_BASIC",   "0.25"))
BLOGGER_COMMISSION_PREMIUM  = float(os.environ.get("BLOGGER_COMMISSION_PREMIUM", "0.25"))
BASIC_PAYMENT_LINK   = os.environ.get("BASIC_LINK", "")
BASIC_AFFILIATE_LINK = os.environ.get("BASIC_AFFILIATE_LINK", "")
BASIC_FRIEND_LINK    = os.environ.get("BASIC_FRIEND_LINK", "")  # окреме посилання для друзів

# ── Premium план ──────────────────────────────────────
PREMIUM_PRICE_FULL    = os.environ.get("PREMIUM_PRICE_FULL", "93.00")
PREMIUM_PRICE_AFF     = os.environ.get("PREMIUM_PRICE_AFF",  "79.00")
PREMIUM_FRIEND_PRICE  = os.environ.get("PREMIUM_FRIEND_PRICE", "79.00")
PREMIUM_PAYMENT_LINK  = os.environ.get("PREMIUM_LINK", "")
PREMIUM_AFFILIATE_LINK= os.environ.get("PREMIUM_AFFILIATE_LINK", "")
PREMIUM_FRIEND_LINK   = os.environ.get("PREMIUM_FRIEND_LINK", "")

# ── Джерела трафіку ───────────────────────────────────
SOURCE_LANDING  = "landing"   # загальний лендінг — повна ціна
SOURCE_BLOGGER  = "blogger"   # від блогера — affiliate ціна
SOURCE_FRIEND   = "friend"    # від друга через Speaking Challenge — friend ціна
SOURCE_DEMO     = "demo"      # TikTok demo — повна ціна після реєстрації


def get_source(s: dict) -> str:
    """
    Визначає джерело трафіку юзера.
    Єдина точка логіки — використовується скрізь замість has_ref.
    """
    # Явно збережене джерело (найточніше)
    explicit = s.get("traffic_source", "")
    if explicit:
        return explicit

    # Визначаємо по наявних полях
    if s.get("affiliate_blogger"):
        return SOURCE_BLOGGER
    if s.get("sc_referrer") or s.get("ref_bonus_applied"):
        return SOURCE_FRIEND
    return SOURCE_LANDING


def get_prices(s: dict) -> dict:
    """
    Повертає правильні ціни і посилання залежно від джерела трафіку.

    Використання (замість has_ref скрізь):
        p = get_prices(s)
        price = p["basic_price"]
        link  = p["basic_link"]
        note  = p["ref_note"]
    """
    source = get_source(s)

    if source == SOURCE_BLOGGER:
        return {
            "basic_price":    BASIC_AFFILIATE_PRICE,
            "basic_link":     BASIC_AFFILIATE_LINK or BASIC_PAYMENT_LINK,
            "prem_price":     PREMIUM_PRICE_AFF,
            "prem_link":      PREMIUM_AFFILIATE_LINK or PREMIUM_PAYMENT_LINK,
            "basic_6m_price": str(BASIC_AFF_6M_PRICE),
            "basic_6m_link":  BASIC_AFF_6M_LINK or BASIC_6M_LINK,
            "prem_6m_price":  str(PREMIUM_AFF_6M_PRICE),
            "prem_6m_link":   PREMIUM_AFF_6M_LINK or PREMIUM_6M_LINK,
            "ref_note":       "\n💸 _Твоя ціна від блогера_",
            "source":         SOURCE_BLOGGER,
        }
    if source == SOURCE_FRIEND:
        return {
            "basic_price":    BASIC_FRIEND_PRICE or BASIC_AFFILIATE_PRICE,
            "basic_link":     BASIC_FRIEND_LINK or BASIC_AFFILIATE_LINK or BASIC_PAYMENT_LINK,
            "prem_price":     PREMIUM_FRIEND_PRICE or PREMIUM_PRICE_AFF,
            "prem_link":      PREMIUM_FRIEND_LINK or PREMIUM_AFFILIATE_LINK or PREMIUM_PAYMENT_LINK,
            "basic_6m_price": str(BASIC_AFF_6M_PRICE),
            "basic_6m_link":  BASIC_AFF_6M_LINK or BASIC_6M_LINK,
            "prem_6m_price":  str(PREMIUM_AFF_6M_PRICE),
            "prem_6m_link":   PREMIUM_AFF_6M_LINK or PREMIUM_6M_LINK,
            "ref_note":       "\n🤝 _Ціна для друзів_",
            "source":         SOURCE_FRIEND,
        }
    # landing або demo — повна ціна
    return {
        "basic_price":    BASIC_PRICE,
        "basic_link":     BASIC_PAYMENT_LINK,
        "prem_price":     PREMIUM_PRICE_FULL,
        "prem_link":      PREMIUM_PAYMENT_LINK,
        "basic_6m_price": str(BASIC_6M_PRICE),
        "basic_6m_link":  BASIC_6M_LINK,
        "prem_6m_price":  str(PREMIUM_FULL_6M_PRICE),
        "prem_6m_link":   PREMIUM_6M_LINK,
        "ref_note":       "",
        "source":         source,
    }

# ── 6-місячна підписка (знижка 17%) ──────────────────
# ── 6-місячні ціни (фіксовані) ───────────────────────
BASIC_6M_PRICE         = float(os.environ.get("BASIC_6M_PRICE",        "99.00"))
BASIC_AFF_6M_PRICE     = float(os.environ.get("BASIC_AFF_6M_PRICE",    "89.00"))
PREMIUM_FULL_6M_PRICE  = float(os.environ.get("PREMIUM_FULL_6M_PRICE", "397.00"))
PREMIUM_AFF_6M_PRICE   = float(os.environ.get("PREMIUM_AFF_6M_PRICE",  "349.00"))

BASIC_6M_LINK          = os.environ.get("BASIC_6M_LINK",    "")
BASIC_AFF_6M_LINK      = os.environ.get("BASIC_AFF_6M_LINK","")
PREMIUM_6M_LINK        = os.environ.get("PREMIUM_6M_LINK",  "")
PREMIUM_AFF_6M_LINK    = os.environ.get("PREMIUM_AFF_6M_LINK","")

# ── Аліаси для зворотної сумісності ──────────────────
PREMIUM_MONTHLY_PRICE  = BASIC_PRICE
PREMIUM_AFFILIATE_PRICE= PREMIUM_PRICE_AFF
FREE_TRIAL_DAYS = 7  # залишаємо константу для сумісності зі старим кодом

def is_in_trial(s: dict) -> bool:
    """
    Рахує ланки (не дні).
    Замінена trial_engine.is_in_trial.
    """
    return trial_is_in_trial(s)

def trial_days_left(s: dict) -> int:
    """Сумісність зі старим кодом — повертає ланки що залишились."""
    return trial_links_left(s)

def is_premium(s: dict) -> bool:
    until = s.get("premium_until", "")
    if not until:
        return False
    try:
        return datetime.strptime(until, "%Y-%m-%d") >= datetime.now()
    except Exception:
        return False

def is_basic(s: dict) -> bool:
    """True якщо активний Basic план."""
    return is_premium(s) and s.get("plan", "basic") == "basic"

def is_premium_only(s: dict) -> bool:
    """True якщо активний Premium план."""
    return is_premium(s) and s.get("plan") == "premium"


def has_trial_feature(s: dict, feature: str) -> bool:
    """
    Перевіряє доступ до фічі залежно від статусу юзера.

    Trial (1-7 ланок) відкриває:
      'roadmap'      — Roadmap A1→C2 (повний шлях і статистика)
      'gap_analysis' — Gap analysis після монологу

    Все інше — тільки платно.
    """
    if is_premium(s):
        return True
    trial_status = get_trial_status(s)
    if trial_status in (STATUS_TRIAL, STATUS_TRIAL_DONE):
        return feature in ("roadmap", "gap_analysis")
    return False

def is_in_trial(s: dict) -> bool:
    """Повертає True якщо студент в межах 5 безкоштовних днів."""
    reg = s.get("registered_at", "")
    if not reg:
        return True  # старі акаунти без дати — даємо доступ
    try:
        from datetime import timedelta
        reg_date = datetime.strptime(reg[:10], "%Y-%m-%d")
        return datetime.now() <= reg_date + timedelta(days=FREE_TRIAL_DAYS)
    except Exception:
        return True

def trial_days_left(s: dict) -> int:
    """Скільки безкоштовних днів залишилось."""
    reg = s.get("registered_at", "")
    if not reg:
        return FREE_TRIAL_DAYS
    try:
        from datetime import timedelta
        reg_date = datetime.strptime(reg[:10], "%Y-%m-%d")
        left = (reg_date + timedelta(days=FREE_TRIAL_DAYS) - datetime.now()).days
        return max(0, left)
    except Exception:
        return 0

async def check_premium_gate(update, s: dict) -> bool:
    if is_premium(s) or is_in_trial(s):
        return True

    # ── Paywall Mini App ─────────────────────────────────
    if BOT_WEBHOOK_URL:
        uid = update.effective_user.id
        url = _build_paywall_url(uid, s)
        await update.message.reply_text(
            "🔒 *Пробний період завершено*\n\nОбери свій план і продовж навчання 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 Обрати план", web_app=WebAppInfo(url=url))
            ]])
        )
        return False

    # Fallback — текстовий paywall
    p            = get_prices(s)
    basic_price  = p["basic_price"]
    basic_link   = p["basic_link"]
    prem_price   = p["prem_price"]
    prem_link    = p["prem_link"]
    ref_note     = p["ref_note"]

    msg = (
        "🔒 *Ти завершив пробний період — 7 ланок пройдено!*\n\n"
        "Ти вже побудував основу свого мовного ланцюжка — не зупиняйся.\n\n"
        "Обери свій план 👇\n\n"
        f"🌟 *Premium — ${prem_price}/міс*{ref_note}\n"
        "• Все що нижче +\n"
        "• 🎬 Live sessions with your favourite blogger teacher\n\n"
        f"⚡️ *Basic — ${basic_price}/міс*{ref_note}\n"
        "• ♾️ Необмежені уроки та Community\n"
        "• 🎯 Gap analysis після кожного монологу\n"
        "• 👥 Speaking partner\n"
        "• 📊 Повний roadmap A1→C2\n"
        "• 🏆 Сертифікат"
    )

    kb_rows = []
    if prem_link:
        kb_rows.append([InlineKeyboardButton(f"🌟 Premium — ${prem_price}/міс", url=prem_link)])
    if basic_link:
        kb_rows.append([InlineKeyboardButton(f"⚡️ Basic — ${basic_price}/міс", url=basic_link)])
    kb_rows.append([InlineKeyboardButton("🎁 Ще один безкоштовний урок", callback_data="premium_trial")])
    await update.message.reply_text(msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_rows))
    return False

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Адмін надсилає документ → бот повертає file_id з підказкою."""
    user = update.effective_user
    if not is_admin(user.id):
        return
    doc = update.message.document
    if not doc:
        return

    name = (doc.file_name or "").lower()

    if "privacy" in name or "конфіденц" in name:
        var_name = "PRIVACY_FILE_ID"
        label    = "Політика конфіденційності"
    elif "offer" in name or "оферт" in name:
        var_name = "OFFER_FILE_ID"
        label    = "Публічна оферта"
    elif "blogger" in name or "партнер" in name or "agreement" in name:
        var_name = "BLOGGER_AGREEMENT_FILE_ID"
        label    = "Договір з блогером"
    elif "nda" in name:
        var_name = "NDA_FILE_ID"
        label    = "NDA"
    else:
        var_name = "OFFER_FILE_ID"
        label    = doc.file_name

    await update.message.reply_text(
        f"📄 *{label}*\n\n"
        f"`{var_name}={doc.file_id}`\n\n"
        f"Додай це значення в Railway Variables як `{var_name}`",
        parse_mode="Markdown"
    )

async def cb_show_offer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показує оферту при paywall."""
    q = update.callback_query
    await q.answer()
    await _send_offer(q.message, ctx)

async def cb_offer_accepted(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент погодився з офертою — показуємо плани оплати."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer("✅ Дякуємо!")
    await q.edit_message_text(
        "✅ *Ти прийняв умови оферти*\n\nОбери свій план 👇",
        parse_mode="Markdown"
    )

    has_ref   = bool(s.get("affiliate_ref"))
    prem_price= PREMIUM_AFFILIATE_PRICE if has_ref else PREMIUM_PRICE_FULL
    basic_price= BASIC_AFFILIATE_PRICE  if has_ref else BASIC_PRICE
    prem_link = PREMIUM_AFFILIATE_LINK  if has_ref else PREMIUM_PAYMENT_LINK
    basic_link= BASIC_AFFILIATE_LINK    if has_ref else BASIC_PAYMENT_LINK
    ref_note  = " _(партнерська ціна)_" if has_ref else ""

    msg = (
        f"🌟 *Premium — ${prem_price}/міс*{ref_note}\n"
        "• Все що нижче +\n"
        "• 🎬 Live sessions з блогером-викладачем\n\n"
        f"⚡️ *Basic — ${basic_price}/міс*{ref_note}\n"
        "• ♾️ Необмежені уроки та Community\n"
        "• 🎯 Gap analysis після кожного монологу\n"
        "• 👥 Speaking partner\n"
        "• 📊 Повний roadmap A1→C2\n"
        "• 🏆 Сертифікат"
    )
    kb_rows = []
    if prem_link:
        kb_rows.append([InlineKeyboardButton(f"🌟 Premium — ${prem_price}/міс", url=prem_link)])
    if basic_link:
        kb_rows.append([InlineKeyboardButton(f"⚡️ Basic — ${basic_price}/міс", url=basic_link)])
    kb_rows.append([InlineKeyboardButton("🎁 Ще один безкоштовний урок", callback_data="premium_trial")])
    await ctx.bot.send_message(
        chat_id=user.id,
        text=msg,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_rows)
    )

async def cb_premium_trial(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()
    if s.get("trial_used"):
        await q.edit_message_text(
            "😊 Ти вже використав безкоштовний урок від Алекса.\n\nЩоб продовжити — підключи Premium 👇",
            parse_mode="Markdown"
        )
        return
    done = s.get("done_lessons", [])
    if done:
        done = done[:-1]
    upd_s(user.id, {"done_lessons": done, "trial_used": True})
    await q.edit_message_text(
        "🎁 *Ще один урок — подарунок від Алекса!*\n\n"
        "Покажи на що здатний — і сам зрозумієш чому варто залишитись 😉",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def cmd_premium(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    s    = get_s(user.id)

    if is_premium(s):
        plan      = s.get("plan","basic").capitalize()
        until     = s.get("premium_until","")
        await update.message.reply_text(
            f"✅ *SpeakChain {plan} активний!*\n\nДійсний до: *{until}*\n\nВсе відкрито — вперед 🚀",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return

    done      = len(s.get("done_lessons", []))
    in_trial  = is_in_trial(s)
    days_left = trial_days_left(s)
    trial_str = f"✅ Безкоштовний період: ще *{days_left} дн.*" if in_trial else "❌ Безкоштовний період завершено"
    has_ref      = bool(s.get("affiliate_ref"))
    basic_price  = float(BASIC_AFFILIATE_PRICE  if has_ref else BASIC_PRICE)
    prem_price   = float(PREMIUM_PRICE_AFF      if has_ref else PREMIUM_PRICE_FULL)
    ref_note     = " _(реферальна)_" if has_ref else ""

    msg = (
        f"📊 Уроків пройдено: *{done}*\n{trial_str}\n\n"
        "Обери свій план 👇\n\n"
        f"🌟 *Premium — ${prem_price:.0f}/міс*{ref_note}\n"
        "• Все з Basic + 🎬 Live sessions з блогером\n\n"
        f"⚡️ *Basic — ${basic_price:.0f}/міс*{ref_note}\n"
        "• ♾️ Необмежені уроки · Gap analysis · Speaking partner · Roadmap A1→C2"
    )

    # Динамічні кнопки через Wayforpay або статичні посилання
    if WAYFORPAY_MERCHANT and WAYFORPAY_SECRET:
        basic_url   = wfp_create_payment_url(user.id, "basic",   basic_price)
        premium_url = wfp_create_payment_url(user.id, "premium", prem_price)
        kb_rows = [
            [InlineKeyboardButton(f"🌟 Premium — ${prem_price:.0f}/міс", url=premium_url)],
            [InlineKeyboardButton(f"⚡️ Basic — ${basic_price:.0f}/міс",  url=basic_url)],
        ]
    else:
        basic_link = BASIC_AFFILIATE_LINK   if has_ref else BASIC_PAYMENT_LINK
        prem_link  = PREMIUM_AFFILIATE_LINK if has_ref else PREMIUM_PAYMENT_LINK
        kb_rows = []
        if prem_link:
            kb_rows.append([InlineKeyboardButton(f"🌟 Premium — ${prem_price:.0f}/міс", url=prem_link)])
        if basic_link:
            kb_rows.append([InlineKeyboardButton(f"⚡️ Basic — ${basic_price:.0f}/міс", url=basic_link)])

    await update.message.reply_text(
        msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_rows) if kb_rows else main_menu()
    )

# ── Speaking partner matching ─────────────────────────
PARTNER_QUEUE_FILE = "partner_queue.json"
PARTNER_MIN_SCORE  = 5   # мінімальна схожість для метчу

def load_partner_queue() -> dict:
    """Завантажує чергу з DB (переживає деплої)."""
    db = load_db()
    if "_partner_queue" in db:
        return db["_partner_queue"]
    p = Path(PARTNER_QUEUE_FILE)
    return json.loads(p.read_text()) if p.exists() else {}

def save_partner_queue(q: dict):
    """Зберігає чергу в DB."""
    db = load_db()
    db["_partner_queue"] = q
    save_db(db)

def partner_score(s1: dict, s2: dict) -> int:
    score = 0
    if s1.get("level") == s2.get("level"): score += 10
    if s1.get("goal")  == s2.get("goal"):  score += 5
    score += len(set(s1.get("interests",[])) & set(s2.get("interests",[]))) * 3
    return score

async def cmd_partner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    s     = get_s(user.id)
    queue = load_partner_queue()

    if not s.get("onboarding_done"):
        await update.message.reply_text("Спочатку пройди знайомство — /start 👋", reply_markup=main_menu())
        return

    if not is_premium(s) and not is_in_trial(s):
        has_ref  = bool(s.get("affiliate_ref"))
        price    = BASIC_AFFILIATE_PRICE if has_ref else BASIC_PRICE
        pay_link = BASIC_AFFILIATE_LINK  if has_ref else BASIC_PAYMENT_LINK
        kb_rows  = [[InlineKeyboardButton(f"⚡️ Basic — ${price}/місяць", url=pay_link)]] if pay_link else []
        await update.message.reply_text(
            "👥 *Speaking Buddy*\n\nЖива практика з партнером — доступно з Basic 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb_rows) if kb_rows else main_menu()
        )
        return

    # Вже в черзі — показуємо статус
    if str(user.id) in queue:
        added = queue[str(user.id)].get("added", "")
        await update.message.reply_text(
            "🔍 *Ти вже в черзі пошуку*\n\n"
            f"Додано: {added[:10] if added else '—'}\n\n"
            "Як тільки знайдеться buddy — напишу 📩",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Скасувати пошук", callback_data="partner_cancel")
            ]])
        )
        return

    # Запитуємо формат: голос чи відео
    await update.message.reply_text(
        "👥 *Speaking Buddy*\n\n"
        "Знаходжу партнера з таким самим рівнем для живої практики.\n\n"
        "В якому форматі хочеш практикуватись?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎙 Голосові повідомлення", callback_data="buddy_format_voice")],
            [InlineKeyboardButton("📹 Відео повідомлення",    callback_data="buddy_format_video")],
            [InlineKeyboardButton("🎙📹 Будь-який формат",    callback_data="buddy_format_any")],
        ])
    )


async def cb_buddy_format(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент обрав формат — шукаємо buddy."""
    q      = update.callback_query
    user   = q.from_user
    s      = get_s(user.id)
    await q.answer()

    fmt_map = {
        "buddy_format_voice": ("voice", "🎙 Голосові"),
        "buddy_format_video": ("video", "📹 Відео"),
        "buddy_format_any":   ("any",   "🎙📹 Будь-який"),
    }
    fmt_key, fmt_label = fmt_map.get(q.data, ("any", "Будь-який"))

    queue   = load_partner_queue()
    level   = s.get("level", "A1")
    goal    = s.get("goal",  "")
    blogger = s.get("affiliate_blogger", "")

    # ── Два рівні матчингу ────────────────────────────────
    def score(data):
        p      = data.get("profile", {})
        pts    = 0
        if p.get("level") == level:          pts += 10
        elif abs(["A1","A2","B1","B2","C1","C2"].index(p.get("level","A1")) -
                 ["A1","A2","B1","B2","C1","C2"].index(level)) == 1: pts += 5
        if p.get("goal") == goal:            pts += 3
        if data.get("fmt") in (fmt_key, "any") or fmt_key == "any": pts += 2
        return pts

    # Рівень 1: тільки студенти того самого блогера
    same_blogger = {uid: d for uid, d in queue.items()
                    if d.get("profile", {}).get("blogger") == blogger and blogger}
    # Рівень 2: вся платформа
    all_students = queue

    best_uid, best_score_val = None, -1
    for pool in ([same_blogger, all_students] if same_blogger else [all_students]):
        for uid, data in pool.items():
            sc = score(data)
            if sc > best_score_val:
                best_score_val, best_uid = sc, uid
        if best_uid:
            break

    if best_uid:
        pdata = queue.pop(best_uid)
        save_partner_queue(queue)
        pfmt  = pdata.get("fmt", "any")
        pname = pdata.get("name", "Студент")
        pusr  = pdata.get("username", "")
        same  = pdata.get("profile", {}).get("blogger") == blogger and blogger

        tag = "👥 _Buddy з твоєї спільноти_" if same else ""
        msg_to_match = (
            f"🎉 *Знайшовся Speaking Buddy!*\n\n"
            f"*{user.first_name}* — {LEVEL_NAMES.get(level,'')}\n"
            f"Формат: {fmt_label}\n\n"
            f"Пиши: @{user.username or user.first_name}\n\n"
            "💡 Запишіть голосове/відео — 3 речення про себе англійською!"
        )
        await ctx.bot.send_message(chat_id=int(best_uid), text=msg_to_match, parse_mode="Markdown")
        await q.edit_message_text(
            f"🎉 *Buddy знайдено!* {tag}\n\n"
            f"*{pname}* — {LEVEL_NAMES.get(pdata.get('profile',{}).get('level',''),'')}\n"
            f"Формат: {'🎙 Голос' if pfmt=='voice' else '📹 Відео' if pfmt=='video' else '🎙📹 Будь-який'}\n\n"
            f"Пиши: @{pusr or pname}\n\n"
            "💡 Розпочни з 3 речень про себе англійською!",
            parse_mode="Markdown"
        )
    else:
        queue[str(user.id)] = {
            "name":    user.first_name,
            "username":user.username or "",
            "fmt":     fmt_key,
            "profile": {"level": level, "goal": goal, "blogger": blogger},
            "added":   datetime.now().isoformat(),
        }
        save_partner_queue(queue)
        await q.edit_message_text(
            f"🔍 *Шукаю buddy...*\n\n"
            f"Рівень: *{LEVEL_NAMES.get(level,'')}*  |  Формат: {fmt_label}\n\n"
            "Як тільки знайдеться — одразу напишу 📩\n"
            "_Зазвичай від кількох хвилин до кількох годин._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Скасувати", callback_data="partner_cancel")
            ]])
        )

async def _do_partner_search(update, ctx, s):
    """Безпосередній пошук партнера після заповнення профілю."""
    user  = update.effective_user
    queue = load_partner_queue()

    # Якщо вже в черзі — показуємо статус
    if str(user.id) in queue:
        added = queue[str(user.id)].get("added","")
        bot_username = (await ctx.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user.username or user.id}"
        await update.message.reply_text(
            "🔍 *Ти вже в черзі пошуку*\n\n"
            f"Додано: {added[:10] if added else '—'}\n\n"
            "Як тільки знайдеться партнер — одразу напишу 📩\n\n"
            "💡 *Прискор пошук:* Запроси друга — і обидва отримаєте partner одразу!\n"
            f"`{ref_link}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Скасувати пошук", callback_data="partner_cancel")
            ]])
        )
        return

    # Шукаємо найкращий метч
    best_uid, best_score = None, -1
    for uid, data in queue.items():
        sc = partner_score(s, data.get("profile", {}))
        if sc > best_score and sc >= PARTNER_MIN_SCORE:
            best_score, best_uid = sc, uid

    if best_uid:
        pdata  = queue.pop(best_uid)
        save_partner_queue(queue)
        plevel = pdata.get("profile", {}).get("level", "")
        pgoal  = pdata.get("profile", {}).get("goal", "")
        pname  = pdata.get("real_name") or pdata.get("name","")
        pcountry = pdata.get("country","")

        await ctx.bot.send_message(
            chat_id=int(best_uid),
            text=(
                f"🎉 *Знайшовся speaking partner!*\n\n"
                f"*{s.get('partner_name') or user.first_name}* — "
                f"{LEVEL_NAMES.get(s.get('level',''),'')} · "
                f"{s.get('partner_country','')}\n\n"
                f"Пиши: @{user.username or user.first_name}\n\n"
                "💡 Розкажи 3 речення про себе англійською — і попроси у відповідь!\n"
                "_Не підходить? Напиши /partner ще раз_"
            ), parse_mode="Markdown"
        )
        await update.message.reply_text(
            f"🎉 *Метч знайдено!*\n\n"
            f"*{pname}* — {LEVEL_NAMES.get(plevel,'')} · {pcountry}\n\n"
            f"Пиши: @{pdata.get('username') or pdata.get('name','')}\n\n"
            "💡 Розкажи 3 речення про себе англійською — і попроси у відповідь!\n"
            "_Не підходить? Напиши /partner ще раз_",
            parse_mode="Markdown"
        )
    else:
        queue[str(user.id)] = {
            "name":       user.first_name,
            "real_name":  s.get("partner_name",""),
            "username":   user.username or "",
            "country":    s.get("partner_country",""),
            "profile": {
                "level":     s.get("level",""),
                "goal":      s.get("goal",""),
                "interests": s.get("interests",[]),
            },
            "added": datetime.now().isoformat(),
        }
        save_partner_queue(queue)
        await update.message.reply_text(
            f"🔍 *Шукаю speaking partner...*\n\n"
            f"Рівень: *{LEVEL_NAMES.get(s.get('level',''), '')}* · "
            f"{GOAL_NAMES.get(s.get('goal',''),'')}\n\n"
            "Ваш запит опрацьовується 🔍\n"
            "Як тільки знайдеться студент зі схожим рівнем — одразу напишу 📩\n"
            "_Зазвичай від кількох хвилин до кількох годин._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Скасувати пошук", callback_data="partner_cancel")
            ]])
        )

async def handle_partner_registration(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Обробляє кроки реєстрації для speaking partner. Повертає True якщо крок оброблено."""
    user = update.effective_user
    s    = get_s(user.id)
    step = s.get("partner_reg_step","")
    text = update.message.text.strip()

    if not step:
        return False

    if step == "name":
        upd_s(user.id, {
            "partner_name":         text,
            "partner_reg_step":     "",
            "partner_profile_done": True,
        })
        await update.message.reply_text(
            f"Приємно познайомитись, *{text}*! 👋\n\nШукаю партнера... 🔍",
            parse_mode="Markdown"
        )
        s2 = get_s(user.id)
        await _do_partner_search(update, ctx, s2)
        return True

    elif step == "email":
        email = "" if text.startswith("/skip") else text
        upd_s(user.id, {"partner_email": email, "partner_reg_step": "country"})
        await update.message.reply_text(
            "З якої ти країни? 🌍\n\n"
            "_(Наприклад: Україна, Польща, США...)_\n\n"
            "_Або_ /skip",
            parse_mode="Markdown"
        )
        return True

    elif step == "country":
        country = "" if text.startswith("/skip") else text
        upd_s(user.id, {"partner_country": country, "partner_reg_step": "motivation"})
        await update.message.reply_text(
            "Чому ти вчиш англійську? ✍️\n\n"
            "Напиши одне речення — партнер побачить це при знайомстві.\n\n"
            "_Або_ /skip",
            parse_mode="Markdown"
        )
        return True

    elif step == "motivation":
        motivation = "" if text.startswith("/skip") else text
        upd_s(user.id, {
            "partner_motivation":   motivation,
            "partner_reg_step":     "",
            "partner_profile_done": True,
        })
        name    = s.get("partner_name", user.first_name)
        country = s.get("partner_country","")
        await update.message.reply_text(
            f"✅ *Профіль заповнено!*\n\n"
            f"👤 {name}"
            + (f" · {country}" if country else "")
            + (f"\n💬 _{motivation}_" if motivation else "")
            + f"\n🎯 {LEVEL_NAMES.get(s.get('level',''),'')}\n\n"
            "Шукаю тобі партнера... 🔍",
            parse_mode="Markdown"
        )
        # Запускаємо пошук
        s = get_s(user.id)
        await _do_partner_search(update, ctx, s)
        return True

    return False


async def cb_partner_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    queue = load_partner_queue()
    if str(user.id) in queue:
        queue.pop(str(user.id))
        save_partner_queue(queue)
        await q.edit_message_text("✅ Пошук скасовано.")
    else:
        await q.edit_message_text("Тебе вже немає в черзі.")

async def cmd_admin_partners(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Доступ заборонено.")
        return
    queue = load_partner_queue()
    if not queue:
        await update.message.reply_text("👥 Черга порожня.")
        return
    lines_out = [f"👥 *Черга Speaking Partner ({len(queue)}):*\n"]
    for uid, data in queue.items():
        prof  = data.get("profile", {})
        added = data.get("added","")[:10]
        lines_out.append(
            f"• *{data.get('name','?')}* (`{uid}`)\n"
            f"  {LEVEL_NAMES.get(prof.get('level',''),'?')} · "
            f"{GOAL_NAMES.get(prof.get('goal',''),'?')} · з {added}"
        )
    await update.message.reply_text(chr(10).join(lines_out), parse_mode="Markdown")


# ── Shareable progress card ───────────────────────────
def build_progress_card(name: str, s: dict) -> str:
    level   = s.get("level", "A1")
    done    = len(s.get("done_lessons", []))
    mastered= len(s.get("mastered_grammar", []))
    streak  = s.get("streak_days", 0)
    best    = s.get("best_streak", 0)
    total_t = sum(len(v) for v in CEFR_GRAMMAR.values())
    since   = s.get("placement_result", {}).get("date", "")
    prem    = "⭐️ Premium" if is_premium(s) else ""
    pct     = int(min(mastered, total_t) / total_t * 10)
    bar     = "🟩" * pct + "⬜️" * (10 - pct)
    lines   = [
        "━━━━━━━━━━━━━━━━━━━━",
        "🏅 *SpeakChain — картка прогресу*",
        f"👤 {name}  {prem}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🎯 Рівень: *{LEVEL_NAMES.get(level, level)}*",
        f"📚 Уроків: *{done}*   ✅ Тем: *{mastered}/{total_t}*",
        bar,
        f"🔥 Стрік: *{streak} дн.*  (рекорд: {best} дн.)",
    ]
    if since:
        lines.append(f"📅 Навчаюся з: {since}")
    lines += ["━━━━━━━━━━━━━━━━━━━━", "🌍 *SpeakChain* — speak more, fear less", "@SpeakChainBot"]
    return "\n".join(lines)

async def cb_share_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()
    card = build_progress_card(user.first_name, s)
    await ctx.bot.send_message(
        chat_id=user.id,
        text=card + "\n\n_Скопіюй і поділись з друзями_ 👆",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📱 Caption для соцмереж", callback_data="share_socials")
        ]])
    )


# ── Відео бібліотека ──────────────────────────────────
VIDEOS = {
    "travel": {
        "A1": [
            {"id":"tr_a1_1","url":"https://www.youtube.com/watch?v=GzEMQ5mypM0","title":"Vanessa — Describe a Place",
             "topic":"Describe a place you want to visit — what it looks like, why you want to go there",
             "grammar":"There is / There are + adjectives","hint":"I want to visit... because... There is... I imagine it is..."},
            {"id":"tr_a1_2","url":"https://www.youtube.com/watch?v=5wvzgid7RvU","title":"BBC — Travel Vocabulary",
             "topic":"Talk about your dream holiday — where, who with, what you would do",
             "grammar":"I want to / I would like to","hint":"My dream holiday is... I want to go to... I would like to... because..."},
            {"id":"tr_a1_3","url":"https://www.youtube.com/watch?v=WLRBm7DQqfE","title":"Learn English — Transport",
             "topic":"How do you usually travel? What do you like and dislike about it?",
             "grammar":"I like / I don't like + -ing","hint":"I usually travel by... I like... because... I don't like... when I travel."},
        ],
        "A2": [
            {"id":"tr_a2_1","url":"https://www.youtube.com/watch?v=ReRBDS0gFgA","title":"BBC — Cities",
             "topic":"Compare two cities — which is better for tourists and why",
             "grammar":"Comparatives: bigger / more beautiful / better than","hint":"I think... is better than... because... However..."},
            {"id":"tr_a2_2","url":"https://www.youtube.com/watch?v=VlBVqUqSIpo","title":"mmmEnglish — Past Travel",
             "topic":"Tell about the best trip you ever took",
             "grammar":"Past Simple: went / saw / stayed / ate","hint":"The best trip I took was to... I went there in... I visited... It was..."},
            {"id":"tr_a2_3","url":"https://www.youtube.com/watch?v=0SUTInEaQ3Q","title":"Linguamarina — Travel Goals",
             "topic":"Talk about your travel plans — where you plan to go next",
             "grammar":"PLAN TO / HOPE TO / WANT TO","hint":"I plan to visit... I hope to... I really want to experience..."},
        ],
        "B1": [
            {"id":"tr_b1_1","url":"https://www.youtube.com/watch?v=arj7oStGLkU","title":"TED — Why We Travel",
             "topic":"Why do people travel? What does travel give us that everyday life cannot?",
             "grammar":"Present Perfect: I have been / I have seen / I have never","hint":"I believe people travel because... I have been to... and it showed me..."},
            {"id":"tr_b1_2","url":"https://www.youtube.com/watch?v=iG9CE55wbtY","title":"Kurzgesagt — Our World",
             "topic":"How has travel changed your perspective on the world?",
             "grammar":"Used to: I used to think... but after travelling I realised...","hint":"Before I travelled, I used to think... But when I visited... I realised..."},
        ],
        "B2": [
            {"id":"tr_b2_1","url":"https://www.youtube.com/watch?v=iCvmsMzlF7o","title":"TED — Transformation",
             "topic":"Is travel truly transformative, or do we bring our problems everywhere?",
             "grammar":"Mixed conditionals + discourse markers","hint":"While many believe travel transforms us... it could be argued... Nevertheless..."},
        ],
    },
    "work": {
        "A1": [
            {"id":"wk_a1_1","url":"https://www.youtube.com/watch?v=5wvzgid7RvU","title":"BBC — Jobs Vocabulary",
             "topic":"Describe your job — what you do, where you work, what you like about it",
             "grammar":"Simple Present: I work / I help / I make","hint":"I work as a... at... My job is to... I like it because..."},
            {"id":"wk_a1_2","url":"https://www.youtube.com/watch?v=wLJnHCIFBgM","title":"English with Lucy — Work",
             "topic":"Describe your typical work day from morning to evening",
             "grammar":"Simple Present + time: first / then / after that","hint":"I start work at... First I... Then I... After that I..."},
            {"id":"wk_a1_3","url":"https://www.youtube.com/watch?v=WLRBm7DQqfE","title":"Learn English — Skills",
             "topic":"What skills do you have? What are you good at?",
             "grammar":"CAN: I can... / I am good at + -ing","hint":"I can... I am also good at... My strongest skill is..."},
        ],
        "A2": [
            {"id":"wk_a2_1","url":"https://www.youtube.com/watch?v=0SUTInEaQ3Q","title":"Linguamarina — Career English",
             "topic":"Talk about your career goals — where you want to be in 3-5 years",
             "grammar":"Future plans: I want to / I plan to / I am going to","hint":"In 3 years I want to... I plan to... To do this I am going to..."},
            {"id":"wk_a2_2","url":"https://www.youtube.com/watch?v=VlBVqUqSIpo","title":"mmmEnglish — Work Challenges",
             "topic":"Describe a challenge at work and how you solved it",
             "grammar":"Past Simple: I had / I solved / I decided","hint":"One challenge I faced was... I decided to... In the end..."},
        ],
        "B1": [
            {"id":"wk_b1_1","url":"https://www.youtube.com/watch?v=qp0HIF3SfI4","title":"Simon Sinek — Leaders",
             "topic":"What makes someone effective at work? Talk about qualities you admire",
             "grammar":"Present Perfect + opinion: I believe / I have noticed","hint":"I believe the most important quality at work is... I have noticed that..."},
            {"id":"wk_b1_2","url":"https://www.youtube.com/watch?v=_HEnohs6yYw","title":"Mel Robbins — Motivation",
             "topic":"What motivates you at work and what kills your motivation?",
             "grammar":"Used to: I used to be motivated by... but now...","hint":"I am most motivated when... I used to think... but now I believe..."},
        ],
        "B2": [
            {"id":"wk_b2_1","url":"https://www.youtube.com/watch?v=qp0HIF3SfI4","title":"TED — Future of Work",
             "topic":"How is your field changing? What skills will matter most in 10 years?",
             "grammar":"Future speculation: will have / is likely to / might well","hint":"My field is changing because... In 10 years I believe... The skills that will matter most are..."},
        ],
    },
    "study": {
        "A1": [
            {"id":"st_a1_1","url":"https://www.youtube.com/watch?v=5wvzgid7RvU","title":"BBC — Student Life",
             "topic":"Introduce yourself as a student — what you study, where, why you chose it",
             "grammar":"Verb TO BE + Simple Present","hint":"I am a student at... I study... I chose this because..."},
            {"id":"st_a1_2","url":"https://www.youtube.com/watch?v=WLRBm7DQqfE","title":"Learn English — Study Habits",
             "topic":"Describe your typical study day — when, how, where you study",
             "grammar":"Simple Present + adverbs: always / usually / sometimes","hint":"I usually study in the... I always... before class. I sometimes..."},
        ],
        "A2": [
            {"id":"st_a2_1","url":"https://www.youtube.com/watch?v=0SUTInEaQ3Q","title":"Linguamarina — Study Goals",
             "topic":"Talk about your study goals — what you want to achieve and why",
             "grammar":"WANT TO / HOPE TO / PLAN TO","hint":"I want to... by the end of this year. I hope to... I plan to..."},
            {"id":"st_a2_2","url":"https://www.youtube.com/watch?v=MjEHCJJVLHI","title":"TED-Ed — How to Learn",
             "topic":"What is your best method for learning something new?",
             "grammar":"Comparatives + I think... is better than... because","hint":"I learn best by... I think... is more effective than... because..."},
        ],
        "B1": [
            {"id":"st_b1_1","url":"https://www.youtube.com/watch?v=arj7oStGLkU","title":"TED — Learning from Life",
             "topic":"Talk about the most valuable thing you have learned — not at school, but from life",
             "grammar":"Present Perfect: I have learned / I have realised / Since then I have","hint":"The most valuable thing I have learned is... I realised this when... Since then I have..."},
            {"id":"st_b1_2","url":"https://www.youtube.com/watch?v=iG9CE55wbtY","title":"Kurzgesagt — Knowledge",
             "topic":"Is formal education enough to succeed today? Give your opinion with examples.",
             "grammar":"Opinion: I believe / In my view / On the other hand","hint":"I believe formal education... On the other hand... In my view the most important thing is..."},
        ],
        "B2": [
            {"id":"st_b2_1","url":"https://www.youtube.com/watch?v=60GaqnefpDk","title":"Kurzgesagt — What Are You?",
             "topic":"How should education change to prepare people for the future?",
             "grammar":"Discourse markers: Furthermore / In addition / Nevertheless","hint":"Education today... Furthermore... In addition... Nevertheless... As a consequence..."},
        ],
    },
    "daily": {
        "A1": [
            {"id":"dl_a1_1","url":"https://www.youtube.com/watch?v=WLRBm7DQqfE","title":"Learn English — Daily Routine",
             "topic":"Describe your morning routine from waking up to leaving home",
             "grammar":"Simple Present: I wake up / I eat / I brush / I leave","hint":"Every morning I wake up at... First I... Then I... Before I leave I always..."},
            {"id":"dl_a1_2","url":"https://www.youtube.com/watch?v=GzEMQ5mypM0","title":"Vanessa — Your Home",
             "topic":"Describe where you live — your home, neighbourhood, what you love about it",
             "grammar":"There is / There are + prepositions","hint":"I live in... There is a... next to my home. I love my neighbourhood because..."},
            {"id":"dl_a1_3","url":"https://www.youtube.com/watch?v=wLJnHCIFBgM","title":"English with Lucy — Free Time",
             "topic":"Talk about what you do in your free time — hobbies, how often",
             "grammar":"Frequency adverbs: always / usually / sometimes / never","hint":"In my free time I usually... I sometimes... My favourite hobby is..."},
        ],
        "A2": [
            {"id":"dl_a2_1","url":"https://www.youtube.com/watch?v=ReRBDS0gFgA","title":"BBC — Weekend Activities",
             "topic":"Tell about last weekend — what you did, who you met, how you felt",
             "grammar":"Past Simple: went / met / watched / cooked / felt","hint":"Last weekend I... On Saturday I went to... I felt... because..."},
            {"id":"dl_a2_2","url":"https://www.youtube.com/watch?v=0SUTInEaQ3Q","title":"Linguamarina — Daily English",
             "topic":"Talk about a habit you want to build — what, why, how you will start",
             "grammar":"WANT TO / PLAN TO / GOING TO","hint":"I want to build a habit of... because... I plan to start by... Every day I am going to..."},
        ],
        "B1": [
            {"id":"dl_b1_1","url":"https://www.youtube.com/watch?v=_HEnohs6yYw","title":"Mel Robbins — Small Habits",
             "topic":"Talk about one habit that changed your life",
             "grammar":"Used to / would: I used to... but now... / Since I started...","hint":"One habit that changed my life is... I used to... but since I started... Now I..."},
            {"id":"dl_b1_2","url":"https://www.youtube.com/watch?v=arj7oStGLkU","title":"TED — Small Choices",
             "topic":"How do your daily choices shape who you become?",
             "grammar":"Present Perfect Continuous: I have been doing... for...","hint":"I believe daily choices shape us because... I have been trying to... for... Small things like..."},
        ],
        "B2": [
            {"id":"dl_b2_1","url":"https://www.youtube.com/watch?v=iCvmsMzlF7o","title":"Brené Brown — Authenticity",
             "topic":"What does a meaningful daily life look like to you?",
             "grammar":"Mixed conditionals + discourse markers","hint":"A meaningful life to me means... I believe that if I... However... As a result..."},
        ],
    },
    "kids": {
        "A1": [
            {"id":"kd_a1_1","url":"https://www.youtube.com/watch?v=7oVMJBGEzok","title":"EnglishClass101 — Family",
             "topic":"Tell about your family — who is in your family, what they like to do",
             "grammar":"TO BE + HAS/HAVE","hint":"My family has... people. My mum is... She has... We like to..."},
            {"id":"kd_a1_2","url":"https://www.youtube.com/watch?v=wLJnHCIFBgM","title":"English with Lucy — Animals",
             "topic":"Talk about your favourite animal — what it looks like, what it eats, why you like it",
             "grammar":"Simple Present: It has / It eats / It lives","hint":"My favourite animal is... It has... It eats... I like it because..."},
            {"id":"kd_a1_3","url":"https://www.youtube.com/watch?v=WLRBm7DQqfE","title":"Learn English — School",
             "topic":"Describe your school or room — colours, furniture, what you like about it",
             "grammar":"There is / There are + colours and adjectives","hint":"My school has... There is a... There are... I like it because..."},
            {"id":"kd_a1_4","url":"https://www.youtube.com/watch?v=5wvzgid7RvU","title":"BBC — Food and Numbers",
             "topic":"Talk about your favourite food for breakfast, lunch and dinner",
             "grammar":"I like / I love / I don't like","hint":"My favourite food is... I love eating... For breakfast I usually..."},
        ],
        "A2": [
            {"id":"kd_a2_1","url":"https://www.youtube.com/watch?v=MjEHCJJVLHI","title":"TED-Ed — Amazing Animals",
             "topic":"Tell about an animal you find amazing — why it is special, what it can do",
             "grammar":"CAN / CAN'T","hint":"I think... is the most amazing animal because... It can... It cannot..."},
            {"id":"kd_a2_2","url":"https://www.youtube.com/watch?v=VlBVqUqSIpo","title":"mmmEnglish — Favourite Things",
             "topic":"Talk about your three favourite things — a game, a food, and a place",
             "grammar":"Past Simple + present: I started liking...","hint":"My three favourite things are... I love... because... My favourite place is..."},
        ],
        "B1": [
            {"id":"kd_b1_1","url":"https://www.youtube.com/watch?v=iG9CE55wbtY","title":"Kurzgesagt — The Egg",
             "topic":"What do you want to be when you grow up and why? What steps will you take?",
             "grammar":"Future plans: I want to / I am going to / I will need to","hint":"When I grow up I want to... because... I am going to... To achieve this I will need to..."},
        ],
        "B2": [
            {"id":"kd_b2_1","url":"https://www.youtube.com/watch?v=60GaqnefpDk","title":"Kurzgesagt — What is Life?",
             "topic":"What is the most important thing young people should learn today and why?",
             "grammar":"Discourse markers: Furthermore / In contrast / As a result","hint":"I believe the most important thing is... Furthermore... In contrast to what many think... As a result..."},
        ],
        "C1": [
            {"id":"kd_c1_1","url":"https://www.youtube.com/watch?v=RcGyVTAoXEU","title":"TED — How to Raise Successful Kids",
             "topic":"What role should parents play in a child's education and independence?",
             "grammar":"Complex passive + concession clauses: Much as parents want... children are believed to...","hint":"Much as parents want to protect their children... it is widely believed that... Nevertheless..."},
        ],
        "C2": [
            {"id":"kd_c2_1","url":"https://www.youtube.com/watch?v=H14bBuluwB8","title":"TED — The Danger of a Single Story",
             "topic":"How does the way we tell stories shape what children believe about themselves and the world?",
             "grammar":"Rhetorical devices + nuanced modals: would appear / might well","hint":"It would appear that the stories we tell children... One might argue... The implications are..."},
        ],
    },
    # ── C1/C2 extensions for adult goals ──────────────────
}

# Додаємо C1/C2 відео для дорослих цілей
_C1C2_VIDEOS = {
    "travel": {
        "C1": [
            {"id":"tr_c1_1","url":"https://www.youtube.com/watch?v=R1vskiVDwl4","title":"TED — The Art of Slow Travel",
             "topic":"Is mass tourism destroying the places we love? Argue your position with nuance.",
             "grammar":"Concession + complex passive: It could be argued / much as tourism is seen as...","hint":"Much as tourism is seen as beneficial... one could argue that... It is widely believed that... Nevertheless the evidence suggests..."},
            {"id":"tr_c1_2","url":"https://www.youtube.com/watch?v=d9uTH0iprVQ","title":"TED — Why We Travel (Deeper)",
             "topic":"What does it mean to truly understand a foreign culture — not just visit it?",
             "grammar":"Fronting + participle clauses: Having lived abroad... / What strikes me most is...","hint":"Having spent time in... what strikes me most is... Deeply embedded in the culture is... One cannot fully appreciate..."},
        ],
        "C2": [
            {"id":"tr_c2_1","url":"https://www.youtube.com/watch?v=iG9CE55wbtY","title":"Alain de Botton — The Art of Travel",
             "topic":"Can travel ever truly change who we are, or do we always return to ourselves?",
             "grammar":"Rhetorical devices + stylistic inversion: Never have I felt... / Rarely does travel...","hint":"Never have I felt more aware of my own limitations than when... Rarely does travel... The paradox lies in..."},
        ],
    },
    "work": {
        "C1": [
            {"id":"wk_c1_1","url":"https://www.youtube.com/watch?v=lmyZMtPVodo","title":"TED — The Power of Vulnerability at Work",
             "topic":"How does psychological safety shape team performance? Use evidence and your own experience.",
             "grammar":"Advanced hedging + nominalisations: The prevalence of... / It would appear that...","hint":"The prevalence of burnout in modern workplaces suggests... It would appear that psychological safety... The nominalisation of 'leading' into 'leadership' reflects..."},
            {"id":"wk_c1_2","url":"https://www.youtube.com/watch?v=qp0HIF3SfI4","title":"Simon Sinek — The Infinite Game",
             "topic":"What is the difference between winning and building something that lasts?",
             "grammar":"Ellipsis + register shifting: In short... / To put it plainly... / The crux of the matter...","hint":"To put it plainly... The crux of the matter is... In formal terms one might say... yet in practice..."},
        ],
        "C2": [
            {"id":"wk_c2_1","url":"https://www.youtube.com/watch?v=H14bBuluwB8","title":"TED — The Danger of a Single Narrative in Business",
             "topic":"How do dominant narratives in your industry limit innovation? Challenge one assumption.",
             "grammar":"Pragmatic implicature + lexical density: The assumption underlying... / implicit in this view is...","hint":"Implicit in this view is the assumption that... The discourse around... belies a deeper tension between... One might infer from this that..."},
        ],
    },
    "study": {
        "C1": [
            {"id":"st_c1_1","url":"https://www.youtube.com/watch?v=MjEHCJJVLHI","title":"TED-Ed — How to Argue",
             "topic":"What is the strongest argument against your own most deeply held belief? Steelman it.",
             "grammar":"Advanced reported speech + concession: Proponents would contend that... / Granted that...","hint":"Granted that my position has merit... proponents of the opposing view would contend that... I would concede that... however the weight of evidence..."},
            {"id":"st_c1_2","url":"https://www.youtube.com/watch?v=arj7oStGLkU","title":"TED — The Surprising Truth About Learning",
             "topic":"How does the illusion of knowing something prevent us from truly mastering it?",
             "grammar":"Fronting + complex syntax: What remains underexplored is... / Embedded in this paradox...","hint":"What remains underexplored is the role of... Embedded in this paradox is the assumption that... One is struck by the irony that..."},
        ],
        "C2": [
            {"id":"st_c2_1","url":"https://www.youtube.com/watch?v=60GaqnefpDk","title":"Noam Chomsky — On Learning",
             "topic":"Is the purpose of education to produce thinkers or workers? Deconstruct the question itself.",
             "grammar":"Discourse cohesion + pragmatic irony: The very framing of the question... / It is telling that...","hint":"It is telling that the question assumes a binary... The very framing reveals... One might argue with some irony that... The discourse cohesion here relies on..."},
        ],
    },
    "daily": {
        "C1": [
            {"id":"dl_c1_1","url":"https://www.youtube.com/watch?v=lmyZMtPVodo","title":"Brené Brown — Belonging vs Fitting In",
             "topic":"What is the difference between belonging and conformity? Where do you stand?",
             "grammar":"Register shifting + advanced hedging: There is a tendency to conflate... / It would appear that...","hint":"There is a tendency to conflate belonging with conformity... It would appear that most people... I would venture to say that..."},
            {"id":"dl_c1_2","url":"https://www.youtube.com/watch?v=iCvmsMzlF7o","title":"TED — The Price of Certainty",
             "topic":"Talk about a time you were completely wrong about something important. What changed?",
             "grammar":"Participle clauses + ellipsis: Having assumed... / Looking back... / What I failed to see was...","hint":"Having assumed for years that... Looking back, what I failed to see was... The ellipsis in my thinking lay in..."},
        ],
        "C2": [
            {"id":"dl_c2_1","url":"https://www.youtube.com/watch?v=R1vskiVDwl4","title":"Derek Sivers — How to Live",
             "topic":"What single principle, if followed consistently, would most transform your daily life?",
             "grammar":"Stylistic inversion + rhetorical precision: Not once did I consider... / Rarely is the answer...","hint":"Not once did I consider that... Rarely is the answer as simple as... The rhetorical force of this lies in... One might, with some justification, argue..."},
        ],
    },
}

for goal, levels in _C1C2_VIDEOS.items():
    if goal not in VIDEOS:
        VIDEOS[goal] = {}
    for level, vids in levels.items():
        VIDEOS[goal][level] = vids

LEVEL_NAMES = {"A1":"Початківець A1","A2":"Базовий A2","B1":"Середній B1","B2":"Вище середнього B2","C1":"Просунутий C1","C2":"Вільне володіння C2"}
GOAL_NAMES  = {"travel":"Подорожі ✈️","work":"Робота 💼","study":"Навчання 🎓","daily":"Щоденне спілкування 🌍","kids":"Для дитини 👧"}

# ── CEFR Grammar Topics per Level ─────────────────────
# ── Результат як навичка — що вмієш після кожного рівня ──
LEVEL_SKILLS = {
    "A1": "Тепер ти можеш: познайомитись, розповісти де живеш і що любиш, замовити каву 🍵",
    "A2": "Тепер ти можеш: розповісти про свій день, купити квиток, описати місце де був ✈️",
    "B1": "Тепер ти можеш: обговорити новини, розповісти про роботу, висловити свою думку 💬",
    "B2": "Тепер ти можеш: провести ділову зустріч, дивитись серіали без субтитрів, дискутувати 🎯",
    "C1": "Тепер ти можеш: читати наукові статті, вести переговори, писати професійні есе 🏆",
    "C2": "Тепер ти можеш: все. Ти говориш як носій мови 👑",
}

CEFR_GRAMMAR = {
    "A1": [
        "The ABC, spelling",
        "The Numbers",
        "a / an",
        "Countable nouns with a/an and some",
        "Present Simple",
        "Present Continuous",
        "Non-Continuous Verbs (stative)",
        "Imperative Mood",
        "Possessive Case ('s / s')",
        "In, on, at — time",
        "Comparative and Superlative Degrees",
        "Zero Conditional",
        "Modal Verbs: basic (can/must/should)",
        "Going to (future plans)",
        "Question Tags",
    ],
    "A2": [
        "Past Simple",
        "Future Simple (will)",
        "The (definite article)",
        "Uncountable nouns",
        "Few, little, a few, a little, much, many",
        "Adverbs",
        "As … as / Than",
        "Used to",
        "First Conditional",
        "Gerund + V (basic)",
        "Infinitive + V (basic)",
        "Modal Verbs: extended (might/may/have to/could)",
    ],
    "B1": [
        "Present Perfect",
        "Present Perfect Continuous",
        "Past Continuous",
        "Passive Voice (Present & Past)",
        "Second Conditional",
        "Enough and too",
        "Because / Because of",
        "Despite / In spite of",
        "As soon as / As long as",
        "Gerund + V (full system)",
        "Infinitive + V (full system)",
        "Would rather / sooner / better",
        "Be used to / Get used to",
        "Either … or / Neither … nor",
        "Modal Verbs: advanced (must have / can't have / should have)",
        "Reported Speech",
    ],
    "B2": [
        "Past Perfect",
        "Past Perfect Continuous",
        "Future Perfect",
        "Future Continuous",
        "Future Perfect Continuous",
        "Third Conditional",
        "Passive Voice (Continuous)",
        "Participle 1 (Present Participle)",
        "Participle 2 (Past Participle)",
        "It is said that …",
        "Complex Object",
        "Everyone, everybody / Either, neither of + Prep",
        "Wish / If only",
        "Mixed Conditionals",
    ],
    "C1": [
        "He is said to / He is supposed to",
        "Complex Subject",
        "The Prepositional Infinitive Complex",
        "Inversion (emphatic structures)",
        "Cleft Sentences",
    ],
    "C2": [
        "Stylistic inversion for literary effect",
        "Nuanced modal meanings (epistemic / deontic / dynamic)",
        "Advanced ellipsis in complex discourse",
        "Rhetoric devices (anaphora, chiasmus, litotes)",
        "Discourse cohesion across paragraphs",
        "Irony, understatement and euphemism in context",
        "Complex syntax: multiple embedded clauses",
        "Idiomatic and colloquial precision",
        "Lexical density and academic register",
        "Pragmatics: implicature and indirect speech acts",
    ],
}

LEVELS_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]

# ── Interest / Personalization labels ─────────────────
INTEREST_NAMES = {
    "tech":    "💻 Технології / IT",
    "business":"💰 Бізнес / Фінанси",
    "science": "🔬 Наука",
    "health":  "🏋️ Здоров'я / Спорт",
    "art":     "🎨 Мистецтво / Музика",
    "news":    "📰 Новини / Суспільство",
    "nature":  "🌿 Природа / Екологія",
    "food":    "🍕 Їжа / Кулінарія",
}

# ── Helpers ───────────────────────────────────────────
def get_lessons(s):
    goal  = s.get("goal","daily")
    level = s.get("level","A1")
    if goal not in VIDEOS: goal = "daily"
    lessons = VIDEOS.get(goal,{}).get(level,[])
    if not lessons: lessons = VIDEOS.get("daily",{}).get(level,[])
    return lessons

def next_lesson(s):
    done = s.get("done_lessons",[])
    for l in get_lessons(s):
        if l["id"] not in done: return l
    return None

def main_menu():
    return ReplyKeyboardMarkup(
        [["🎬 Мої відео",         "📊 Прогрес"],
         ["🎯 Челендж дня",       "❓ Допомога"]],
        resize_keyboard=True,
        is_persistent=True
    )

def active_lesson_kb(video_url: str, s: dict = None) -> InlineKeyboardMarkup:
    """Кнопки під активним уроком."""
    vid_id   = extract_youtube_id(video_url)
    platform = detect_platform(video_url)
    if s is None:
        s = {}
    if WEBAPP_URL and vid_id and platform == "youtube":
        watch_btn = InlineKeyboardButton("▶️ Дивитись відео",
            web_app={"url": f"{WEBAPP_URL}?v={vid_id}&d={urllib.parse.quote(json.dumps({'level':s.get('level','A1'),'mastered':s.get('mastered_grammar',[]),'done_lessons':len(s.get('done_lessons',[]))},ensure_ascii=False))}"})
    else:
        watch_btn = InlineKeyboardButton("▶️ Дивитись відео", url=video_url)
    return InlineKeyboardMarkup([
        [watch_btn],
        [InlineKeyboardButton("🎙 Записати монолог", callback_data="remind_record")],
    ])

def breadcrumb(s: dict) -> str:
    """Рядок навігації: A1 · Present Perfect · Урок 3"""
    level    = s.get("level", "A1")
    mastered = s.get("mastered_grammar", [])
    topic    = next_cefr_topic(s) or "Всі теми пройдено 🏆"
    done     = len(s.get("done_lessons", []))
    return f"_{level} · {topic} · Урок {done + 1}_"

def extract_youtube_id(url: str) -> str | None:
    patterns = [
        r"youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m: return m.group(1)
    return None

def miniapp_video_url(video_url: str) -> str:
    """Генерує пряме посилання на плеєр через Mini App."""
    vid_id = extract_youtube_id(video_url)
    if not vid_id:
        return MINIAPP_URL
    return f"{MINIAPP_URL}?startapp={vid_id}"


def _player_url(video_url: str, s: dict) -> str:
    """Будує URL плеєра з даними студента для Journey strip."""
    vid_id = extract_youtube_id(video_url)
    if not vid_id or not WEBAPP_URL:
        return ""
    _base = (BOT_WEBHOOK_URL or "").rstrip("/")
    data = {
        "level":        s.get("level", "A1"),
        "mastered":     s.get("mastered_grammar", []),
        "done_lessons": len(s.get("done_lessons", [])),
        "levels":       LEVELS_ORDER,
        "cefr_grammar": CEFR_GRAMMAR,
        "xp_total":     s.get("xp_total", 0),
        "streak_days":  s.get("streak_days", 0),
        "player_minutes_total": s.get("player_minutes_total", 0),
        "api":          BOT_WEBHOOK_URL,
        "captions_url": f"{_base}/captions" if _base else "",
        "uid":          s.get("uid", 0),
        "name":         s.get("name", ""),
    }
    encoded = urllib.parse.quote(json.dumps(data, ensure_ascii=False))
    return f"{WEBAPP_URL}?v={vid_id}&d={encoded}"


def video_watch_keyboard(video_url: str, s: dict = None, show_dur: bool = False) -> InlineKeyboardMarkup:
    """Кнопка ▶️ що відкриває відео: WebApp якщо є WEBAPP_URL, інакше зовнішнє посилання"""
    vid_id   = extract_youtube_id(video_url)
    platform = detect_platform(video_url)

    if WEBAPP_URL and vid_id and platform == "youtube":
        url = _player_url(video_url, s or {})
        watch_btn = InlineKeyboardButton("▶️ Дивитись відео", web_app={"url": url})
    else:
        watch_btn = InlineKeyboardButton("▶️ Дивитись відео", url=video_url)

    return InlineKeyboardMarkup([[watch_btn]])

# ════════════════════════════════════════════════════════════
# XP СИСТЕМА — нараховується за дію, не за якість
# ════════════════════════════════════════════════════════════

XP_LEVELS = [
    (0,      "🌱 Beginner"),       # A1 рівень
    (6_000,  "🗺️ Explorer"),       # A2 рівень
    (14_000, "🎯 Practitioner"),   # B1 рівень
    (28_000, "💬 Fluent"),         # B2 рівень
    (45_000, "🏆 Master"),         # B2 повністю пройдено!
]

# XP потрібно для проходження кожного рівня (650h до B2 включно)
CEFR_LEVEL_XP = {
    "A1": 6_000,    # 90h  × ~67 XP/h
    "A2": 8_000,    # 110h × ~73 XP/h
    "B1": 14_000,   # 200h × ~70 XP/h
    "B2": 17_000,   # 250h × ~68 XP/h
    "C1": 21_000,   # 300h
    "C2": 21_000,   # 300h
}

# Кумулятивні пороги (total XP від нуля)
CEFR_CUMULATIVE_XP = {}
_cum = 0
for _lvl in ["A1","A2","B1","B2","C1","C2"]:
    _cum += CEFR_LEVEL_XP[_lvl]
    CEFR_CUMULATIVE_XP[_lvl] = _cum

XP_AWARDS = {
    # ── Основна практика ──────────────────────────────
    "session":              15,   # завершив сесію монологу
    "shadowing":             8,   # повторив за спікером
    "first_of_day":          8,   # перший урок дня (бонус)
    "video_watched":        10,   # переглянув відео в плеєрі (мін 3 хв)
    "phrase_saved":          5,   # зберіг фразу в картотеку

    # ── Граматика ────────────────────────────────────
    "tutor_me_lesson":      20,   # пройшов міні-урок /tutor_me
    "quiz_passed":          15,   # тест ≥70% у вправах
    "grammar_topic_100":    30,   # тема засвоєна на 100%
    "spaced_rep_done":      10,   # успішне повторення через 7+ днів

    # ── Стріки ───────────────────────────────────────
    "streak_7":             20,   # стрік 7 днів
    "streak_30":            75,   # стрік 30 днів
    "streak_100":          200,   # стрік 100 днів

    # ── Спільнота ─────────────────────────────────────
    "shared_community":     12,   # поділився записом у спільноті
    "reaction_received":     8,   # отримав реакцію на запис
    "reaction_x10":         50,   # 10+ реакцій на один запис

    # ── Власне відео ──────────────────────────────────
    "own_video_published":     200,  # опублікував власне відео
    "own_video_reaction":       15,  # реакція на власне відео
    "own_video_reaction_x10":  300,  # 10+ реакцій на власне відео

    # ── Реферали (множник ×5) ─────────────────────────
    "friend_joined":           100,  # друг зареєструвався по рефералу (було 20)
    "friend_paid":             250,  # реферал оформив платну підписку
    "friend_30d_active":       150,  # реферал активний через 30 днів
}

def get_xp_level(xp: int) -> str:
    """Повертає назву рівня по XP."""
    level = XP_LEVELS[0][1]
    for threshold, name in XP_LEVELS:
        if xp >= threshold:
            level = name
    return level

def get_xp_next(xp: int) -> tuple[int, int]:
    """Повертає (поточний поріг, наступний поріг)."""
    cur, nxt = 0, XP_LEVELS[-1][0]
    for i, (threshold, _) in enumerate(XP_LEVELS):
        if xp >= threshold:
            cur = threshold
            nxt = XP_LEVELS[i+1][0] if i+1 < len(XP_LEVELS) else threshold
    return cur, nxt

def get_cefr_xp_progress(xp_total: int, current_level: str) -> dict:
    """
    Повертає прогрес по CEFR рівнях в XP.
    Показує XP в межах поточного рівня та загальний шлях до B2.
    """
    levels = ["A1","A2","B1","B2","C1","C2"]
    cur_idx = levels.index(current_level) if current_level in levels else 0

    # XP в межах поточного рівня
    prev_cum  = CEFR_CUMULATIVE_XP.get(levels[cur_idx-1], 0) if cur_idx > 0 else 0
    level_xp  = CEFR_LEVEL_XP.get(current_level, 6_000)
    xp_in_lvl = max(0, xp_total - prev_cum)
    xp_in_lvl = min(xp_in_lvl, level_xp)  # не більше ніж треба для рівня
    pct       = int(xp_in_lvl / level_xp * 100) if level_xp else 0

    # Загальний шлях до B2
    b2_total  = CEFR_CUMULATIVE_XP.get("B2", 45_000)
    xp_to_b2  = max(0, b2_total - xp_total)

    # Оцінка темпу (XP за останні 30 днів)
    months_to_b2 = None

    return {
        "current_level":   current_level,
        "xp_in_level":     xp_in_lvl,
        "level_xp_needed": level_xp,
        "level_pct":       pct,
        "xp_total":        xp_total,
        "b2_total":        b2_total,
        "xp_to_b2":        xp_to_b2,
        "levels":          levels,
        "cur_idx":         cur_idx,
    }

def build_cefr_xp_display(xp_total: int, current_level: str) -> str:
    """Будує текстовий прогрес-бар шляху A1→B2 в XP."""
    d      = get_cefr_xp_progress(xp_total, current_level)
    levels = d["levels"][:4]  # A1→B2
    lines  = []

    cum = 0
    for lvl in levels:
        lvl_xp = CEFR_LEVEL_XP.get(lvl, 0)
        lvl_start = cum
        lvl_end   = cum + lvl_xp
        cum       = lvl_end

        if xp_total >= lvl_end:
            # Рівень пройдено
            bar  = "█" * 10
            lines.append(f"✅ *{lvl}*  `{bar}`  {lvl_xp:,} XP")
        elif xp_total > lvl_start:
            # Поточний рівень
            xp_here = xp_total - lvl_start
            fill    = round(xp_here / lvl_xp * 10)
            bar     = "█" * fill + "░" * (10 - fill)
            lines.append(f"🔵 *{lvl}*  `{bar}`  {xp_here:,} / {lvl_xp:,} XP  ← зараз")
        else:
            # Ще не розпочато
            goal = "🎯" if lvl == "B2" else "  "
            lines.append(f"{goal}⬜ *{lvl}*  `░░░░░░░░░░`  0 / {lvl_xp:,} XP")

    xp_to_b2 = max(0, CEFR_CUMULATIVE_XP["B2"] - xp_total)
    lines.append(f"\n⚡️ Всього: *{xp_total:,} / {CEFR_CUMULATIVE_XP['B2']:,} XP* до B2")
    if xp_to_b2 > 0:
        lines.append(f"Залишилось: *{xp_to_b2:,} XP*")

    return "\n".join(lines)

def build_level_progress_bar(s: dict) -> str:
    """
    Компактний прогрес-бар після монологу.
    Показує: поточний рівень, % до наступного, скільки монологів лишилось.
    """
    xp_total = s.get("xp_total", 0)
    level    = s.get("level", "A1")
    levels   = ["A1","A2","B1","B2","C1","C2"]
    cur_idx  = levels.index(level) if level in levels else 0

    # XP в межах поточного рівня
    prev_cum  = CEFR_CUMULATIVE_XP.get(levels[cur_idx - 1], 0) if cur_idx > 0 else 0
    level_xp  = CEFR_LEVEL_XP.get(level, 6_000)
    xp_in_lvl = max(0, min(xp_total - prev_cum, level_xp))
    pct       = int(xp_in_lvl / level_xp * 100) if level_xp else 0
    fill      = round(pct / 10)
    bar       = "█" * fill + "░" * (10 - fill)

    # Скільки монологів (session=10 XP) до наступного рівня
    xp_left      = level_xp - xp_in_lvl
    monologues   = max(1, -(-xp_left // XP_AWARDS.get("session", 10)))  # ceil division

    next_level = levels[cur_idx + 1] if cur_idx + 1 < len(levels) else None
    level_name = LEVEL_NAMES.get(level, level)

    if next_level:
        next_name = LEVEL_NAMES.get(next_level, next_level)
        line1 = f"📈 *{level_name}* → {next_name}"
        line2 = f"`{bar}` {pct}%"
        line3 = f"До наступного рівня: *~{monologues} монологів*"
    else:
        line1 = f"🏆 *{level_name}* — фінальний рівень!"
        line2 = f"`{bar}` {pct}%"
        line3 = f"⚡️ XP: *{xp_total:,}* — ти легенда!"

    return f"{line1}\n{line2}\n{line3}"


async def award_xp(bot, uid: int, reason: str) -> dict | None:
    """
    Нараховує XP за дію. Якщо сьогодні потрійний XP день — множить на 3.
    Повертає dict або None.
    """
    amount = XP_AWARDS.get(reason, 0)
    if not amount:
        return None

    s         = get_s(uid)
    today     = datetime.now().strftime("%Y-%m-%d")

    # Перевіряємо потрійний XP день
    multiplier = 3 if s.get("triple_xp_date") == today else 1

    # Перевіряємо referral XP boost (+20% на 7 днів)
    boost_until = s.get("xp_boost_until", "")
    boost_pct   = s.get("xp_boost_pct", 0)
    if boost_until and boost_pct and boost_until >= today:
        multiplier = multiplier * (1 + boost_pct / 100)

    amount = round(amount * multiplier)

    old_xp    = s.get("xp_total", 0)
    new_xp    = old_xp + amount
    old_level = get_xp_level(old_xp)
    new_level = get_xp_level(new_xp)

    upd_s(uid, {"xp_total": new_xp})

    leveled_up = old_level != new_level
    if leveled_up:
        try:
            await bot.send_message(
                chat_id=uid,
                text=(
                    f"🎉 *Новий рівень!*\n\n"
                    f"{old_level} → *{new_level}*\n\n"
                    f"Ти набрав *{new_xp} XP* — продовжуй говорити! 🚀"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"XP level up notify error: {e}")

    return {
        "xp_added":   amount,
        "multiplier": multiplier,
        "total_xp":   new_xp,
        "leveled_up": leveled_up,
        "new_level":  new_level,
    }

MAX_ANALYSES_PER_DAY = int(os.environ.get("MAX_ANALYSES_PER_DAY", "3"))


def get_analyses_remaining(s: dict) -> int:
    """Повертає кількість аналізів що залишились сьогодні."""
    today = datetime.now().strftime("%Y-%m-%d")
    if s.get("analyses_date") != today:
        return MAX_ANALYSES_PER_DAY  # новий день — повний ліміт
    used = s.get("analyses_used_today", 0)
    return max(0, MAX_ANALYSES_PER_DAY - used)


def voice_review_kb(remaining: int = 0) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton("✅ Відправити на перевірку AI", callback_data="voice_submit")]]
    if remaining <= 0:
        kb = [[InlineKeyboardButton("⚠️ Ліміт аналізів вичерпано", callback_data="voice_limit_info")]]
    kb.append([InlineKeyboardButton("🔄 Записати ще раз", callback_data="voice_retry")])
    return InlineKeyboardMarkup(kb)

# ── Onboarding keyboards ──────────────────────────────
def goal_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✈️ Подорожі",        callback_data="g_travel"),
         InlineKeyboardButton("💼 Робота/кар'єра",  callback_data="g_work")],
        [InlineKeyboardButton("🎓 Навчання/іспити", callback_data="g_study"),
         InlineKeyboardButton("🌍 Щоденне спілкування", callback_data="g_daily")],
        [InlineKeyboardButton("👧 Для дитини",      callback_data="g_kids")],
    ])

def level_choice_kb():
    """Крок перед вибором рівня — знає/не знає."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Вказати свій рівень",       callback_data="plc_manual")],
        [InlineKeyboardButton("🤔 Не знаю свій рівень — пройти тест", callback_data="plc_test")],
    ])

def level_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌱 A1 — Початківець",        callback_data="lv_A1"),
         InlineKeyboardButton("📖 A2 — Базовий",             callback_data="lv_A2")],
        [InlineKeyboardButton("💬 B1 — Середній",            callback_data="lv_B1"),
         InlineKeyboardButton("🚀 B2 — Вище середнього",     callback_data="lv_B2")],
        [InlineKeyboardButton("🎓 C1 — Просунутий",          callback_data="lv_C1"),
         InlineKeyboardButton("🏆 C2 — Вільне володіння",    callback_data="lv_C2")],
    ])

def profession_kb():
    professions = [
        ("👨‍💻 IT / Розробка",   "it"),
        ("📊 Менеджмент",       "management"),
        ("🎓 Освіта",           "education"),
        ("🏥 Медицина",         "medicine"),
        ("🎨 Дизайн / Творчість","design"),
        ("📦 Бізнес / Продажі", "sales"),
        ("🌍 Інше",             "other"),
    ]
    rows = []
    for i in range(0, len(professions), 2):
        row = [InlineKeyboardButton(label, callback_data=f"prof_{code}") for label,code in professions[i:i+2]]
        rows.append(row)
    return InlineKeyboardMarkup(rows)

AGE_GROUP_NAMES = {
    "kids":  "👧 До 12 років",
    "teen":  "🧑 13–17 років",
    "adult": "🧑‍💼 18–35 років",
    "senior":"👴 35+ років",
}

def age_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👧 До 12",     callback_data="age_kids"),
         InlineKeyboardButton("🧑 13–17",     callback_data="age_teen")],
        [InlineKeyboardButton("🧑‍💼 18–35",  callback_data="age_adult"),
         InlineKeyboardButton("👴 35+",       callback_data="age_senior")],
    ])


def kids_interests_kb():
    """Інтереси дитини для персоналізації відео."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🦁 Тварини",    callback_data="kint_animals"),
         InlineKeyboardButton("🚀 Космос",     callback_data="kint_space")],
        [InlineKeyboardButton("🎮 Ігри",       callback_data="kint_games"),
         InlineKeyboardButton("🎵 Музика",     callback_data="kint_music")],
        [InlineKeyboardButton("⚽️ Спорт",      callback_data="kint_sports"),
         InlineKeyboardButton("🎨 Малювання",  callback_data="kint_art")],
        [InlineKeyboardButton("📖 Казки",      callback_data="kint_stories"),
         InlineKeyboardButton("🔬 Наука",      callback_data="kint_science")],
    ])

def kids_age_kb():
    """Вік дитини для онбоардингу kids."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍼 0–3 років",  callback_data="kids_age_0"),
         InlineKeyboardButton("🐣 4–6 років",  callback_data="kids_age_4")],
        [InlineKeyboardButton("🌱 7–9 років",  callback_data="kids_age_7"),
         InlineKeyboardButton("📚 10–12 років",callback_data="kids_age_10")],
        [InlineKeyboardButton("🧑 13–15 років",callback_data="kids_age_13")],
    ])

# ── /start ────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # В групах /start ігноруємо
    if update.effective_chat and update.effective_chat.type in ("group", "supergroup", "channel"):
        return
    logger.info(f"START from {user.id} {user.first_name}")

    # ── Demo entry point (TikTok → /start demo) ──────────
    if ctx.args and ctx.args[0] == "demo":
        upd_s(user.id, {"traffic_source": SOURCE_DEMO})
        return await handle_demo_entry(update, ctx, get_s, upd_s)

    # ── Shared Chain виклик (Speaking Challenge deeplink) ─
    if ctx.args and ctx.args[0].startswith("sc_"):
        s = get_s(user.id)
        upd_s(user.id, {"traffic_source": SOURCE_FRIEND})
        return await handle_challenge_deeplink(ctx.bot, user.id, s, ctx.args[0], upd_s)

    s    = get_s(user.id)

    # ── Реферальний бонус — старт з ланки 3 ──────────────
    if not s.get("ref_bonus_applied") and s.get("referrer_uid"):
        s_with_bonus = apply_referral_bonus(dict(s))
        upd_s(user.id, {
            "chain":            s_with_bonus["chain"],
            "ref_bonus_applied": True,
        })
        # П.4 — Friend landing замість звичайного /start
        referrer_uid = s.get("referrer_uid")
        if referrer_uid and not s.get("friend_landing_shown"):
            upd_s(user.id, {"friend_landing_shown": True})
            asyncio.create_task(_send_friend_landing(ctx.bot, user.id, int(referrer_uid), s))
            return
        s = get_s(user.id)

    # Зберігаємо базові дані і синхронізуємо в Sheets при кожному /start
    is_new = not s.get("registered_at")
    _utc_offset = guess_utc_offset(s, user)
    upd_s(user.id, {
        "telegram_id":  user.id,
        "name":         user.first_name,
        "username":     user.username or "",
        "active":       True,
        "registered_at": s.get("registered_at") or datetime.now().strftime("%Y-%m-%d"),
        "language_code": getattr(user, "language_code", "") or s.get("language_code", ""),
        "utc_offset":   s.get("utc_offset") if s.get("utc_offset") is not None else _utc_offset,
        "partner_reg_step": "",
        "waiting_blogger_code": False,
        "waiting_gen_ref": False,
        "waiting_blogger_username": False,
    })
    asyncio.create_task(gs_sync_student(user.id))

    # ── Повернення вже налаштованого студента ──
    if s.get("onboarding_done"):
        streak     = s.get("streak_days", 0)
        done       = len(s.get("done_lessons", []))
        level      = LEVEL_NAMES.get(s.get("level",""), "")
        streak_line = f"🔥 Стрік: *{streak} днів поспіль*\n" if streak > 1 else ""

        await update.message.reply_text(
            f"З поверненням, {user.first_name}! 👋\n\n"
            f"{streak_line}"
            f"📊 Рівень: *{level}* · Уроків: *{done}*\n\n"
            "Продовжуємо? 👇",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        return

    # ── Тест на рівень був розпочатий але не завершений ──
    if s.get("placement_active") and s.get("placement_current"):
        await update.message.reply_text(
            f"Привіт, {user.first_name}! 👋\n\n"
            "Схоже, ти вже починав тест на визначення рівня але не завершив його.\n\n"
            "Що робимо?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Продовжити тест",    callback_data="plc_resume")],
                [InlineKeyboardButton("🔄 Почати спочатку",    callback_data="plc_restart")],
            ])
        )
        return

    # ── Deeplink: ?start=VIDEO_ID (посилання з відео блогера) ──
    args        = ctx.args
    video_param = args[0] if args else None

    # ── Deeplink: ref_BLOGGER або ref_BLOGGER_video_YOUTUBE_ID ──
    if video_param and video_param.startswith("ref_"):
        # Не перезаписуємо якщо реферал вже є
        if not get_s(user.id).get("affiliate_ref"):
            rest = video_param[4:]  # все після "ref_"
            if "_video_" in rest:
                parts    = rest.split("_video_", 1)
                ref_code = parts[0]
                vid_id   = parts[1]
            else:
                ref_code = rest
                vid_id   = None

            platform_map = {
                "_yt": "YouTube", "_ig": "Instagram",
                "_tt": "TikTok",  "_fb": "Facebook",
                "_tw": "Twitter/X",
            }
            platform  = "Unknown"
            clean_ref = ref_code
            for suffix, pname in platform_map.items():
                if ref_code.endswith(suffix):
                    platform  = pname
                    clean_ref = ref_code[:-len(suffix)]
                    break

            upd_s(user.id, {
                "affiliate_ref":      ref_code,
                "affiliate_platform": platform,
                "affiliate_blogger":  clean_ref,
            })
        else:
            # Реферал вже є — тільки парсимо vid_id для запуску відео
            rest   = video_param[4:]
            vid_id = rest.split("_video_", 1)[1] if "_video_" in rest else None

        if vid_id:
            # Є YouTube відео — одразу запускаємо урок
            video_url = f"https://www.youtube.com/watch?v={vid_id}"
            upd_s(user.id, {
                "waiting_video":    False,
                "current_lesson_id":"custom",
                "custom_video_url": video_url,
                "videos_watched":   0,
            })
            await update.message.reply_text(
                "Я SpeakChain — твій AI-тренер з вивчення англійської. "
                "Дивишся відео → повторюй → застосуй → отримай відгук від АІ 🎯\n\n"
                "Починаємо з відео яке ти щойно дивився 👇",
                parse_mode="Markdown"
            )
            await _send_first_video_task(update.message, ctx, video_url, user.id)
            return
        # Без відео — продовжуємо до онбоардингу нижче

    # ── Новий онбоардинг: БЕЗ питань → одразу відео ──
    await update.message.reply_text(
        "Вчи англійську по відео блогерів 🎬\n"
        "AI знаходить твої прогалини 🎯\n"
        "Говори з живими партнерами 👥\n\n"
        "Підбираю твоє перше відео... 🔍",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )
    # Встановлюємо базовий профіль
    upd_s(user.id, {
        "level":            "A1",
        "goal":             "daily",
        "done_lessons":     [],
        "scores":           [],
        "mastered_grammar": [],
        "onboarding_done":  True,
        "is_first_lesson":  True,
        "registered_at":    datetime.now().strftime("%Y-%m-%d"),
    })
    asyncio.create_task(gs_sync_student(user.id))
    await _auto_send_next_lesson(ctx.bot, user.id)

# ── Helper: надіслати завдання по першому відео ──────
async def _send_first_video_task(message, ctx, video_url: str, user_id: int):
    """Перше відео — WOW онбоардинг: повтори за спікером."""
    s     = get_s(user_id)
    level = s.get("level", "A1")
    msg   = await message.reply_text("⏳ Готую твоє перше завдання...")
    try:
        pr = (
            f"Student level: {level}. Video: {video_url}\n"
            f"Create a shadowing task — student repeats after the speaker OR records a short video using words from this video.\n"
            f"Reply ONLY:\n"
            f"TOPIC: [Ukrainian instruction starting with: 'Повтори за спікером або запиши своє відео, використавши слова і фрази з цього відео.']\n"
            f"GRAMMAR: [one simple grammar point]\n"
            f"HINT: [2-3 simple English phrases from the video to repeat]"
        )
        cr = claude_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=200,
            messages=[{"role": "user", "content": pr}]
        )
        task    = cr.content[0].text
        topic   = "Повтори за спікером або запиши своє відео, використавши слова і фрази з цього відео."
        grammar = "Present Simple"
        hint    = "I think... / In my opinion... / I found it interesting that..."
        for line in task.splitlines():
            line = line.strip()
            if line.startswith("TOPIC:"):    topic   = line[6:].strip()
            elif line.startswith("GRAMMAR:"): grammar = line[8:].strip()
            elif line.startswith("HINT:"):    hint    = line[5:].strip()

        upd_s(user_id, {
            "current_lesson_id":           "custom",
            "current_lesson_data":         {"id":"custom","url":video_url,"title":"Перше відео","grammar":grammar,"topic":topic,"hint":hint},
            "custom_video_url":            video_url,
            "pending_first_video_grammar": grammar,
            "pending_first_video_topic":   topic,
            "is_first_lesson":             True,
        })
        await msg.edit_text(
            f"🎬 *Перше завдання!*\n\n"
            f"🎤 {topic}\n\n"
            f"💡 _{hint}_\n\n"
            "Подивись відео → повтори вголос або запиши відео → натисни 🎙 👇",
            parse_mode="Markdown",
            reply_markup=video_watch_keyboard(video_url, show_dur=True)
        )
    except Exception as e:
        logger.error(f"First video task error: {e}")
        upd_s(user_id, {"current_lesson_id": "custom", "custom_video_url": video_url, "is_first_lesson": True})
        await msg.edit_text(
            "🎬 *Перше завдання!*\n\n"
            "🎤 Повтори за спікером або запиши своє відео, використавши слова і фрази з цього відео.\n\n"
            "Подивись відео → повтори вголос або запиши відео → натисни 🎙 👇",
            parse_mode="Markdown",
            reply_markup=video_watch_keyboard(video_url, show_dur=True)
        )

# ── Entry callbacks: обери / я вже обрав ─────────────
async def cb_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    if q.data == "entry_choose":
        # Не запускаємо онбоардинг одразу — спочатку два відео
        upd_s(user.id, {"videos_watched": 0, "waiting_video": False})
        await q.edit_message_text("🔍 Підбираю відео для тебе...")
        await _auto_send_next_lesson(ctx.bot, user.id)

    elif q.data == "entry_own":
        upd_s(user.id, {"waiting_video": True, "videos_watched": 0})
        await q.edit_message_text(
            "Надішли посилання на відео:\n"
            "• 🎬 YouTube\n\n"
            "👇",
            parse_mode="Markdown"
        )

# ── Placement test data ───────────────────────────────
# file_id заповнюється після завантаження аудіо в бота
PLACEMENT_AUDIO = {
    "A1": "",   # audio_a1.m4a → надішли боту як голосове, встав file_id сюди
    "A2": "",   # audio_a2.m4a
    "B1": "",   # audio_b1.m4a
    "B2": "",   # audio_b2.m4a
    "C1": "",   # audio_c1.m4a
}
# Застосовуємо збережені file_id якщо є
PLACEMENT_AUDIO.update({k: v for k, v in _SAVED_AUDIO_IDS.items() if v})

# Адаптивний тест: кожне питання має рівень, правильну відповідь (індекс 0-3)
# і наступний крок: якщо правильно → up, якщо неправильно → down
PLACEMENT_QUESTIONS = [
    # ── ГРАМАТИКА ──────────────────────────────────────
    {
        "id": "g_a1", "level": "A1", "type": "grammar",
        "q": "She ___ a teacher.",
        "opts": ["am", "is", "are", "be"],
        "correct": 1,
    },
    {
        "id": "g_a2", "level": "A2", "type": "grammar",
        "q": "We ___ to New York last summer.",
        "opts": ["go", "goes", "went", "have gone"],
        "correct": 2,
    },
    {
        "id": "g_b1", "level": "B1", "type": "grammar",
        "q": "If I ___ more time, I would travel the world.",
        "opts": ["have", "had", "would have", "has"],
        "correct": 1,
    },
    {
        "id": "g_b2", "level": "B2", "type": "grammar",
        "q": "The report ___ by the time the meeting started.",
        "opts": ["was finished", "has been finished", "had been finished", "is finished"],
        "correct": 2,
    },
    {
        "id": "g_c1", "level": "C1", "type": "grammar",
        "q": "It is vital that every student ___ the assignment on time.",
        "opts": ["submits", "submit", "submitted", "will submit"],
        "correct": 1,
    },
    {
        "id": "g_c2", "level": "C2", "type": "grammar",
        "q": "Not only ___ the deadline, but she also exceeded expectations.",
        "opts": ["she met", "did she meet", "she did meet", "has she met"],
        "correct": 1,
    },
    # ── ЛЕКСИКА ────────────────────────────────────────
    {
        "id": "v_a1", "level": "A1", "type": "vocab",
        "q": "🔤 HAPPY means...",
        "opts": ["sad", "angry", "glad", "tired"],
        "correct": 2,
    },
    {
        "id": "v_a2", "level": "A2", "type": "vocab",
        "q": "🔤 Choose the correct word:\nShe gave me a ___ smile that made me feel welcome.",
        "opts": ["hot", "warm", "boiling", "burning"],
        "correct": 1,
    },
    {
        "id": "v_b1", "level": "B1", "type": "vocab",
        "q": "🔤 SIGNIFICANT means...",
        "opts": ["tiny", "vague", "obvious", "considerable"],
        "correct": 3,
    },
    {
        "id": "v_b2", "level": "B2", "type": "vocab",
        "q": "🔤 To HINDER means...",
        "opts": ["to assist", "to obstruct", "to achieve", "to ignore"],
        "correct": 1,
    },
    {
        "id": "v_c1", "level": "C1", "type": "vocab",
        "q": "🔤 EQUIVOCAL means...",
        "opts": ["fair", "straightforward", "ambiguous", "equal"],
        "correct": 2,
    },
    {
        "id": "v_c2", "level": "C2", "type": "vocab",
        "q": "🔤 To AMELIORATE means...",
        "opts": ["to worsen", "to measure", "to compare", "to improve"],
        "correct": 3,
    },
    # ── АУДІЮВАННЯ ─────────────────────────────────────
    {
        "id": "l_a1", "level": "A1", "type": "listening",
        "audio_key": "A1",
        "q": "🎧 Прослухай і відповідай:\nWhere does Sarah work?",
        "opts": ["A school", "A hospital", "A coffee shop", "A bank"],
        "correct": 2,
    },
    {
        "id": "l_a2", "level": "A2", "type": "listening",
        "audio_key": "A2",
        "q": "🎧 Прослухай і відповідай:\nHow did the family travel to the Grand Canyon?",
        "opts": ["By plane", "By train", "By bus", "By car"],
        "correct": 3,
    },
    {
        "id": "l_b1", "level": "B1", "type": "listening",
        "audio_key": "B1",
        "q": "🎧 Прослухай і відповідай:\nWhat challenge do managers face with remote work?",
        "opts": ["Hiring new people", "Managing office space", "Building team culture remotely", "Buying equipment"],
        "correct": 2,
    },
    {
        "id": "l_b2", "level": "B2", "type": "listening",
        "audio_key": "B2",
        "q": "🎧 Прослухай і відповідай:\nWhere do emotionally intelligent people tend to perform better?",
        "opts": ["In technical roles", "In creative roles", "In leadership roles", "In manual jobs"],
        "correct": 2,
    },
    {
        "id": "l_c1", "level": "C1", "type": "listening",
        "audio_key": "C1",
        "q": "🎧 Прослухай і відповідай:\nWhat does the speaker say about the benefits of globalization?",
        "opts": [
            "They are shared equally among all people",
            "They mostly go to corporations and elites",
            "They help working-class communities most",
            "They are impossible to measure",
        ],
        "correct": 1,
    },
]

# Адаптивний маршрут: залежно від результату попереднього питання
# формат: { question_id: { "correct": next_id, "wrong": next_id, "end": True/False } }
PLACEMENT_FLOW = {
    # Старт завжди з A2 граматики
    "start":  "g_a2",
    "g_a2":   {"correct": "g_b1",  "wrong":  "g_a1"},
    "g_a1":   {"correct": "v_a2",  "wrong":  "end_a1"},
    "g_b1":   {"correct": "g_b2",  "wrong":  "v_a2"},
    "g_b2":   {"correct": "g_c1",  "wrong":  "v_b1"},
    "g_c1":   {"correct": "g_c2",  "wrong":  "v_c1"},
    "g_c2":   {"correct": "l_c1",  "wrong":  "v_c1"},
    # Лексика
    "v_a2":   {"correct": "v_b1",  "wrong":  "v_a1"},
    "v_a1":   {"correct": "l_a1",  "wrong":  "end_a1"},
    "v_b1":   {"correct": "v_b2",  "wrong":  "l_a2"},
    "v_b2":   {"correct": "v_c1",  "wrong":  "l_b1"},
    "v_c1":   {"correct": "l_c1",  "wrong":  "l_b2"},
    # Аудіювання
    "l_a1":   {"correct": "l_a2",  "wrong":  "end_a1"},
    "l_a2":   {"correct": "l_b1",  "wrong":  "end_a2"},
    "l_b1":   {"correct": "l_b2",  "wrong":  "end_b1"},
    "l_b2":   {"correct": "l_c1",  "wrong":  "end_b2"},
    "l_c1":   {"correct": "end_c2","wrong":  "end_c1"},
}

# Кінцеві вузли → рівень
PLACEMENT_RESULTS = {
    "end_a1": "A1",
    "end_a2": "A2",
    "end_b1": "B1",
    "end_b2": "B2",
    "end_c1": "C1",
    "end_c2": "C2",
}

def get_placement_question(qid: str) -> dict | None:
    for q in PLACEMENT_QUESTIONS:
        if q["id"] == qid:
            return q
    return None

# ── Placement test keyboards ──────────────────────────
def placement_opts_kb(qid: str, opts: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(opt, callback_data=f"plc_ans_{qid}_{i}")]
        for i, opt in enumerate(opts)
    ])

# ── Placement test: send a question ──────────────────
async def send_placement_question(bot, user_id: int, qid: str):
    q = get_placement_question(qid)
    if not q:
        return
    upd_s(user_id, {"placement_current": qid})

    if q["type"] == "listening":
        audio_key = q.get("audio_key", "")
        file_id   = PLACEMENT_AUDIO.get(audio_key, "")
        if file_id:
            await bot.send_voice(chat_id=user_id, voice=file_id)
        else:
            await bot.send_message(
                chat_id=user_id,
                text="🎧 _(аудіо буде додано незабаром)_",
                parse_mode="Markdown"
            )

    await bot.send_message(
        chat_id=user_id,
        text=f"*{q['q']}*",
        parse_mode="Markdown",
        reply_markup=placement_opts_kb(qid, q["opts"])
    )

# ── Placement: вибір рівня або тест ──────────────────
async def cb_placement_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    if q.data == "plc_manual":
        await q.edit_message_text(
            "Обери свій рівень англійської 👇",
            parse_mode="Markdown",
            reply_markup=level_kb()
        )

    elif q.data == "plc_test":
        upd_s(user.id, {
            "placement_active":  True,
            "placement_score":   0,
            "placement_count":   0,
            "placement_current": PLACEMENT_FLOW["start"],
        })
        await q.edit_message_text(
            "🧪 *Тест на визначення рівня*\n\n"
            "Близько 10–12 питань — граматика, лексика та аудіювання.\n"
            "Відповідай чесно — це допоможе підібрати відео саме для тебе 🎯\n\n"
            "Починаємо! 👇",
            parse_mode="Markdown"
        )
        await send_placement_question(ctx.bot, user.id, PLACEMENT_FLOW["start"])

    elif q.data == "plc_resume":
        s      = get_s(user.id)
        cur_qid = s.get("placement_current", PLACEMENT_FLOW["start"])
        await q.edit_message_text(
            "▶️ Продовжуємо тест! 👇",
            parse_mode="Markdown"
        )
        await send_placement_question(ctx.bot, user.id, cur_qid)

    elif q.data == "plc_restart":
        upd_s(user.id, {
            "placement_active":  True,
            "placement_score":   0,
            "placement_count":   0,
            "placement_current": PLACEMENT_FLOW["start"],
        })
        await q.edit_message_text(
            "🧪 *Починаємо тест заново!*\n\n"
            "Близько 10–12 питань — граматика, лексика та аудіювання 🎯\n\n"
            "Починаємо! 👇",
            parse_mode="Markdown"
        )
        await send_placement_question(ctx.bot, user.id, PLACEMENT_FLOW["start"])

# ── Placement: обробка відповіді ─────────────────────
async def cb_placement_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    # plc_ans_{qid}_{answer_index}
    # qid може містити '_' (напр. g_a2, v_b1) — тому ріжемо з кінця
    data      = q.data                      # "plc_ans_g_a2_1"
    ans_idx   = int(data.rsplit("_", 1)[1]) # "1"
    qid       = data[len("plc_ans_"):]      # "g_a2_1"
    qid       = qid.rsplit("_", 1)[0]       # "g_a2"
    question  = get_placement_question(qid)
    if not question:
        return

    is_correct   = (ans_idx == question["correct"])
    s            = get_s(user.id)
    count        = s.get("placement_count", 0) + 1
    score        = s.get("placement_score", 0) + (1 if is_correct else 0)
    wrong_list   = s.get("placement_wrong", [])
    if not is_correct:
        wrong_list.append({"type": question["type"], "level": question["level"], "id": qid})
    upd_s(user.id, {"placement_count": count, "placement_score": score, "placement_wrong": wrong_list})

    # ── Показуємо результат прямо на кнопках ──
    result_rows = []
    for i, opt in enumerate(question["opts"]):
        if i == question["correct"] and i == ans_idx:
            label = f"✅ {opt}"
        elif i == question["correct"]:
            label = f"✅ {opt}"
        elif i == ans_idx:
            label = f"❌ {opt}"
        else:
            label = f"· {opt}"
        result_rows.append([InlineKeyboardButton(label, callback_data="plc_done")])

    await q.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup(result_rows)
    )

    # Визначаємо наступний крок
    flow_node = PLACEMENT_FLOW.get(qid, {})
    next_qid  = flow_node.get("correct") if is_correct else flow_node.get("wrong")

    await asyncio.sleep(1.0)

    # Перевіряємо чи це кінцевий вузол
    if not next_qid or next_qid in PLACEMENT_RESULTS:
        result_level = PLACEMENT_RESULTS.get(next_qid, "B1")
        # ── Формуємо gaps з помилок тесту ──
        wrong_list   = s.get("placement_wrong", [])
        grammar_gaps = [w for w in wrong_list if w["type"] == "grammar"]
        vocab_gaps   = [w for w in wrong_list if w["type"] == "vocab"]

        # Беремо найнижчий рівень помилки як пріоритет
        GRAMMAR_QUERIES = {
            "A1": "verb to be am is are English beginner",
            "A2": "past simple English lesson exercises",
            "B1": "second conditional English grammar lesson",
            "B2": "passive voice advanced English had been",
            "C1": "subjunctive mood English advanced grammar",
            "C2": "inversion advanced English grammar native",
        }
        VOCAB_QUERIES = {
            "A1": "basic English vocabulary beginner words",
            "A2": "everyday English vocabulary intermediate",
            "B1": "English vocabulary in context B1 lesson",
            "B2": "advanced English vocabulary B2 collocations",
            "C1": "C1 advanced English vocabulary academic words",
            "C2": "C2 proficiency English vocabulary sophisticated",
        }
        GRAMMAR_LABELS = {
            "A1": "Базова граматика (дієслово TO BE)",
            "A2": "Минулий час (Past Simple)",
            "B1": "Умовні речення (Conditionals)",
            "B2": "Пасивний стан (Advanced Passive)",
            "C1": "Підрядний спосіб (Subjunctive)",
            "C2": "Інверсія (Advanced Inversion)",
        }
        VOCAB_LABELS = {
            "A1": "Базова лексика A1",
            "A2": "Побутова лексика A2",
            "B1": "Лексика в контексті B1",
            "B2": "Розширена лексика B2",
            "C1": "Академічна лексика C1",
            "C2": "Лексика рівня носія C2",
        }

        placement_gaps = {}
        if grammar_gaps:
            gap_level = grammar_gaps[0]["level"]
            placement_gaps["grammar_gap"]   = GRAMMAR_LABELS.get(gap_level, f"Граматика {gap_level}")
            placement_gaps["grammar_query"] = GRAMMAR_QUERIES.get(gap_level, f"English grammar {gap_level}")
        if vocab_gaps:
            gap_level = vocab_gaps[0]["level"]
            placement_gaps["vocab_gap"]   = VOCAB_LABELS.get(gap_level, f"Лексика {gap_level}")
            placement_gaps["vocab_query"] = VOCAB_QUERIES.get(gap_level, f"English vocabulary {gap_level}")
        if grammar_gaps:
            placement_gaps["reinforce_query"] = GRAMMAR_QUERIES.get(grammar_gaps[0]["level"], "English grammar practice")

        upd_s(user.id, {
            "level":            result_level,
            "done_lessons":     [],
            "scores":           [],
            "mastered_grammar": [],
            "placement_active": False,
            "placement_done":   True,
            "placement_wrong":  [],
            "pending_gaps":     placement_gaps,
            "placement_result": {
                "level":        result_level,
                "score":        score,
                "total":        count,
                "date":         datetime.now().strftime("%d.%m.%Y"),
                "grammar_gaps": [GRAMMAR_LABELS.get(w["level"], w["level"]) for w in grammar_gaps],
                "vocab_gaps":   [VOCAB_LABELS.get(w["level"], w["level"]) for w in vocab_gaps],
            },
        })
        gap_lines = []
        if placement_gaps.get("grammar_gap"):
            gap_lines.append(f"⚠️ Граматика: _{placement_gaps['grammar_gap']}_")
        if placement_gaps.get("vocab_gap"):
            gap_lines.append(f"📖 Лексика: _{placement_gaps['vocab_gap']}_")
        gaps_text = ("\n\n*Виявлені прогалини:*\n" + "\n".join(gap_lines)) if gap_lines else ""

        await ctx.bot.send_message(
            chat_id=user.id,
            text=(
                f"🎉 *Тест завершено!*\n\n"
                f"Твій рівень: *{LEVEL_NAMES.get(result_level, result_level)}*\n"
                f"Правильних відповідей: *{score}/{count}*"
                f"{gaps_text}\n\n"
                "Підбираю перше відео для тебе... 🔍"
            ),
            parse_mode="Markdown"
        )
        upd_s(user.id, {
            "onboarding_done": True,
            "registered_at": get_s(user.id).get("registered_at") or datetime.now().strftime("%Y-%m-%d"),
        })
        asyncio.create_task(gs_sync_student(user.id))
        await _auto_send_next_lesson(ctx.bot, user.id)
        return

    # Наступне питання
    await send_placement_question(ctx.bot, user.id, next_qid)

# ── Onboarding: крок 1 — ціль ─────────────────────────
async def cb_goal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    goal = q.data.replace("g_","")
    upd_s(q.from_user.id, {"goal": goal})

    if goal == "kids":
        await q.edit_message_text(
            f"Чудово! *{GOAL_NAMES.get(goal,goal)}* 👧\n\n"
            "Скільки років дитині? 👇",
            parse_mode="Markdown",
            reply_markup=kids_age_kb()
        )
    else:
        # Одразу запускаємо перше відео — рівень A1 за замовчуванням
        # Рівень визначимо після першого монологу
        upd_s(q.from_user.id, {
            "level":            "A1",
            "done_lessons":     [],
            "scores":           [],
            "mastered_grammar": [],
            "onboarding_done":  True,
            "registered_at":    get_s(q.from_user.id).get("registered_at") or datetime.now().strftime("%Y-%m-%d"),
        })
        asyncio.create_task(gs_sync_student(q.from_user.id))
        await q.edit_message_text(
            "🔍 Підбираю відео для тебе...",
        )
        await _auto_send_next_lesson(ctx.bot, q.from_user.id)

# ── Onboarding: вік дитини (kids) ────────────────────
async def cb_kids_age(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    age_code = q.data.replace("kids_age_","")
    age_map  = {
        "0":  ("kids",  "A1", "0–3 років"),
        "4":  ("kids",  "A1", "4–6 років"),
        "7":  ("kids",  "A1", "7–9 років"),
        "10": ("teen",  "A1", "10–12 років"),
        "13": ("teen",  "A2", "13–15 років"),
    }
    age_group, default_level, age_label = age_map.get(age_code, ("kids", "A1", ""))

    upd_s(user.id, {"age_group": age_group, "kids_age": age_label})

    # Для 0-3 — уточнюємо підвік
    if age_code == "0":
        await q.edit_message_text(
            "🍼 Скільки місяців/років малюку? 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👶 0–1 рік",  callback_data="kids_sub_lullaby")],
                [InlineKeyboardButton("🧸 1–3 роки", callback_data="kids_sub_games")],
            ])
        )
        return

    # Для всіх інших — питаємо про інтереси
    await q.edit_message_text(
        f"👧 Вік: *{age_label}*\n\n"
        "Що найбільше цікавить дитину? 👇",
        parse_mode="Markdown",
        reply_markup=kids_interests_kb()
    )


# ── Kids: інтереси ────────────────────────────────────
async def cb_kids_interests(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    interest_map = {
        "kint_animals":  "animals",
        "kint_space":    "space",
        "kint_games":    "games",
        "kint_music":    "music",
        "kint_sports":   "sports",
        "kint_art":      "drawing art",
        "kint_stories":  "stories fairy tales",
        "kint_science":  "science",
    }
    interest = interest_map.get(q.data, "")

    # Рівень визначається автоматично по віку
    s2 = get_s(user.id)
    kids_age = s2.get("kids_age", "")
    age_to_level = {
        "0–3 років":   "A1",
        "4–6 років":   "A1",
        "7–9 років":   "A1",
        "10–12 років": "A1",
        "13–15 років": "A2",
    }
    level = age_to_level.get(kids_age, "A1")

    upd_s(user.id, {
        "interests":       [interest],
        "level":           level,
        "done_lessons":    [],
        "scores":          [],
        "mastered_grammar":[],
        "onboarding_done": True,
        "registered_at":   s2.get("registered_at") or datetime.now().strftime("%Y-%m-%d"),
    })
    asyncio.create_task(gs_sync_student(user.id))

    await q.edit_message_text(
        "🎉 Відмінно! Підбираю відео...",
        parse_mode="Markdown"
    )
    await _auto_send_next_lesson(ctx.bot, user.id)

async def cb_kids_sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обробляє підвік 0-1 (lullaby) і 1-3 (games)."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    if q.data == "kids_sub_lullaby":
        upd_s(user.id, {
            "kids_age":         "0–1 рік",
            "kids_sub":         "lullaby",
            "interests":        ["lullaby nursery rhymes"],
            "level":            "A1",
            "done_lessons":     [],
            "scores":           [],
            "mastered_grammar": [],
            "onboarding_done":  True,
            "registered_at":    get_s(user.id).get("registered_at") or datetime.now().strftime("%Y-%m-%d"),
        })
        asyncio.create_task(gs_sync_student(user.id))
        await q.edit_message_text("🎵 Підбираю колискові та пісеньки... 🔍")

    elif q.data == "kids_sub_games":
        upd_s(user.id, {
            "kids_age":         "1–3 роки",
            "kids_sub":         "games",
            "interests":        ["games activities toddlers"],
            "level":            "A1",
            "done_lessons":     [],
            "scores":           [],
            "mastered_grammar": [],
            "onboarding_done":  True,
            "registered_at":    get_s(user.id).get("registered_at") or datetime.now().strftime("%Y-%m-%d"),
        })
        asyncio.create_task(gs_sync_student(user.id))
        await q.edit_message_text("🧸 Підбираю відео з іграми... 🔍")

    await _auto_send_next_lesson(ctx.bot, user.id)

# ── Onboarding: крок 2 — рівень ───────────────────────
async def cb_level(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    level = q.data.replace("lv_","")
    upd_s(q.from_user.id, {
        "level": level,
        "done_lessons": [],
        "scores": [],
        "mastered_grammar": [],
    })
    s    = get_s(q.from_user.id)
    goal = s.get("goal", "daily")

    # Для kids — питаємо про інтереси дитини
    if goal == "kids":
        kids_age = s.get("kids_age", "")
        await q.edit_message_text(
            f"✅ Рівень: *{LEVEL_NAMES.get(level, level)}*\n\n"
            "Що найбільше цікавить дитину? 👇",
            parse_mode="Markdown",
            reply_markup=kids_interests_kb()
        )
        return

    upd_s(q.from_user.id, {
        "onboarding_done": True,
        "registered_at": get_s(q.from_user.id).get("registered_at") or datetime.now().strftime("%Y-%m-%d"),
    })
    asyncio.create_task(gs_sync_student(q.from_user.id))

    await q.edit_message_text(
        f"✅ *Рівень: {LEVEL_NAMES.get(level, level)}*\n\n"
        "Підбираю перше відео для тебе... 🔍",
        parse_mode="Markdown"
    )
    await _auto_send_next_lesson(ctx.bot, q.from_user.id)

# ── Onboarding: крок 3 — професія ────────────────────
async def cb_profession(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    prof = q.data.replace("prof_", "")
    upd_s(q.from_user.id, {"profession": prof})
    # Крок 4 — вікова група
    await q.edit_message_text(
        "Чудово! Скільки тобі років?\n\n"
        "Це допоможе підібрати лексику тестів саме для тебе 👇",
        parse_mode="Markdown",
        reply_markup=age_kb()
    )

# ── Onboarding: крок 4 — вік ──────────────────────────
async def cb_age(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    age_group = q.data.replace("age_", "")
    s     = get_s(q.from_user.id)
    goal  = s.get("goal", "daily")
    level = s.get("level", "A1")
    upd_s(q.from_user.id, {"age_group": age_group, "onboarding_done": True,
                        "registered_at": get_s(q.from_user.id).get("registered_at") or datetime.now().strftime("%Y-%m-%d")})
    asyncio.create_task(gs_sync_student(q.from_user.id))
    await q.edit_message_text(
        f"🎉 *Профіль готовий!*\n\n"
        f"Ціль: *{GOAL_NAMES.get(goal, goal)}*\n"
        f"Рівень: *{LEVEL_NAMES.get(level, level)}*\n"
        f"Вік: *{AGE_GROUP_NAMES.get(age_group, age_group)}*\n\n"
        "Підбираю перше відео для тебе... 🔍",
        parse_mode="Markdown"
    )
    await _auto_send_next_lesson(ctx.bot, q.from_user.id)

# ── Onboarding: крок 4 — інтереси (multi-select) ─────
async def cb_interests(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "int_done":
        s         = get_s(q.from_user.id)
        goal      = s.get("goal", "daily")
        level     = s.get("level", "A1")
        age_group = s.get("age_group", "adult")
        interests = s.get("interests", [])
        interests_str = ", ".join(INTEREST_NAMES.get(i, i) for i in interests) if interests else "не вказано"
        upd_s(q.from_user.id, {"onboarding_done": True,
                                "registered_at": get_s(q.from_user.id).get("registered_at") or datetime.now().strftime("%Y-%m-%d")})
        asyncio.create_task(gs_sync_student(q.from_user.id))
        await q.edit_message_text(
            f"🎉 *Профіль готовий!*\n\n"
            f"Ціль: *{GOAL_NAMES.get(goal, goal)}*\n"
            f"Рівень: *{LEVEL_NAMES.get(level, level)}*\n"
            f"Вік: *{AGE_GROUP_NAMES.get(age_group, age_group)}*\n"
            f"Інтереси: _{interests_str}_\n\n"
            "Останнє питання 👇",
            parse_mode="Markdown"
        )
        # ── Запит таймзони ────────────────────────────────
        await ctx.bot.send_message(
            chat_id=q.from_user.id,
            text=(
                "🕐 *В якому часовому поясі ти живеш?*\n\n"
                "Це потрібно щоб нагадування приходили о *21:00 за твоїм часом* — "
                "а не посеред ночі."
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("UTC−5  🇺🇸 Нью-Йорк",    callback_data="tz_-5"),
                    InlineKeyboardButton("UTC+0  🇬🇧 Лондон",       callback_data="tz_0"),
                ],
                [
                    InlineKeyboardButton("UTC+1  🇵🇱 Варшава",      callback_data="tz_1"),
                    InlineKeyboardButton("UTC+2  🇺🇦 Київ",         callback_data="tz_2"),
                ],
                [
                    InlineKeyboardButton("UTC+3  🇷🇺 Москва",       callback_data="tz_3"),
                    InlineKeyboardButton("UTC+4  🇦🇪 Дубай",        callback_data="tz_4"),
                ],
                [
                    InlineKeyboardButton("UTC+5  🇰🇿 Алмати",       callback_data="tz_5"),
                    InlineKeyboardButton("UTC+6  🇧🇩 Дакка",        callback_data="tz_6"),
                ],
                [
                    InlineKeyboardButton("UTC+8  🇨🇳 Пекін",        callback_data="tz_8"),
                    InlineKeyboardButton("UTC+9  🇯🇵 Токіо",        callback_data="tz_9"),
                ],
                [
                    InlineKeyboardButton("🔍 Інший пояс",           callback_data="tz_other"),
                ],
            ])
        )
        return

    # Toggle interest
    interest = data.replace("int_", "")
    s = get_s(q.from_user.id)
    interests = s.get("interests", [])
    if interest in interests:
        interests.remove(interest)
    else:
        interests.append(interest)
    upd_s(q.from_user.id, {"interests": interests})

    # Update keyboard to show selections
    rows = []
    items = list(INTEREST_NAMES.items())
    for i in range(0, len(items), 2):
        row = []
        for k, v in items[i:i+2]:
            label = ("✅ " + v) if k in interests else v
            row.append(InlineKeyboardButton(label, callback_data=f"int_{k}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("✅ Готово", callback_data="int_done")])
    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))

# ── Timezone selection (після онбордингу) ────────────
async def cb_timezone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data  # tz_2, tz_other, тощо

    if data == "tz_other":
        # Показуємо розширений список
        await q.edit_message_text(
            "🕐 *Обери свій часовий пояс:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("UTC−8  🇺🇸 Лос-Анджелес",  callback_data="tz_-8")],
                [InlineKeyboardButton("UTC−6  🇲🇽 Мехіко",        callback_data="tz_-6")],
                [InlineKeyboardButton("UTC−3  🇧🇷 Бразилія",      callback_data="tz_-3")],
                [InlineKeyboardButton("UTC+2  🇺🇦 Київ",          callback_data="tz_2")],
                [InlineKeyboardButton("UTC+3  🇹🇷 Стамбул",       callback_data="tz_3")],
                [InlineKeyboardButton("UTC+5  🇵🇰 Карачі",        callback_data="tz_5")],
                [InlineKeyboardButton("UTC+5:30 🇮🇳 Індія",       callback_data="tz_5")],
                [InlineKeyboardButton("UTC+7  🇻🇳 Ханой",         callback_data="tz_7")],
                [InlineKeyboardButton("UTC+10 🇦🇺 Сідней",        callback_data="tz_10")],
                [InlineKeyboardButton("UTC+12 🇳🇿 Окленд",        callback_data="tz_12")],
            ])
        )
        return

    # Парсимо offset
    try:
        offset = int(data.replace("tz_", ""))
    except Exception:
        offset = 2

    save_utc_offset(uid, offset, upd_s)

    # Показуємо підтвердження і стартуємо
    from timezone_utils import COUNTRY_TO_OFFSET
    sign = "+" if offset >= 0 else ""
    await q.edit_message_text(
        f"✅ *UTC{sign}{offset} збережено*\n\n"
        "Нагадування приходитимуть о *21:00 за твоїм часом*.\n\n"
        "Підбираю перше відео для тебе... 🔍",
        parse_mode="Markdown"
    )
    await _auto_send_next_lesson(ctx.bot, uid)

# ── Motivational phrases ──────────────────────────────
# ── Алекс — голос бота ───────────────────────────────
# Алекс — твій тренер. Прямий, трохи саркастичний, але завжди на твоєму боці.
# Він не каже "чудово!" на кожне речення — але коли каже, ти знаєш що заробив.

ALEX_PHRASES = [
    "Окей, підбираю. Без зупинок — вперед 🎯",
    "Зараз знайдемо щось варте твого часу 🔍",
    "Ти тут — значить вже молодець. Решта за мною 💪",
    "Один урок ближче до тієї розмови, яку ти уявляєш 🌍",
    "Не ідеально — але реально. Поїхали ⚡️",
    "Нагадаю: помилки — це дані, не провал 🧠",
    "Ти знаєш більше, ніж думаєш. Довіряй процесу 🔥",
    "Добре. Підбираю відео під твій рівень і цілі — секунду 🎬",
    "Флуентність — це не талант, це звичка. Будуємо її зараз 🧱",
    "Чесно? Більшість кидають на цьому місці. Ти — ні. Це важливо 🏆",
]

MOTIVATIONAL = ALEX_PHRASES + [
    "Ще один крок до мети! 💪",
    "Рухаємось далі 🚀",
    "Інвестуємо час у твою мрію ✨",
    "Чудове рішення! 🎯",
    "Так тримати! 🔥",
    "Ходімо далі 👣",
    "Вперед! ⚡️",
    "І хоча кожен крок здається мізерним — ти вже наближаєшся до мети 🌟",
    "Ще трошки — і результат буде помітний 📈",
    "Кожне відео робить тебе кращим 🎬",
    "Твій мозок вже працює на тебе 🧠",
    "Практика — єдиний шлях до вільної мови 🗣",
    "Сьогодні ти знову обрав зростання 🌱",
    "Не зупиняйся — ти вже далі, ніж вчора 🏆",
    "Маленькі дії щодня — великий результат за рік 📅",
    "Мова відкриває двері, які інакше залишились би зачиненими 🚪",
    "Ти не просто вчиш мову — ти змінюєш своє майбутнє 🌍",
    "Кожна хвилина практики — це інвестиція у себе 💎",
    "Твоя наполегливість вражає! Продовжуй 🎖",
    "Дорогу осилить той, хто йде 🌄",
    "Найкращий момент почати був вчора. Другий найкращий — зараз ⏰",
    "Флуентність будується по одному реченню за раз 🧱",
    "Ти вже говориш краще, ніж думаєш 💬",
    "Один урок сьогодні — впевненість завтра 🌅",
    "Помилки — це не провал, це навчання у прямому ефірі 🎓",
    "The one can do only by doing 🎯",
    "Every expert was once a beginner 🌱",
    "Progress, not perfection 📈",
    "Fluency is built one sentence at a time 🧱",
    "Speak more, fear less 🗣",
    "You don't have to be great to start, but you have to start to be great ⚡️",
    "Small daily improvements lead to stunning results 🏆",
    "The secret of getting ahead is getting started 🚀",
    "Done is better than perfect 💪",
    "Every time you speak, you get better 🎙",
    "Mistakes are proof that you are trying 💡",
    "Your future self is grateful you started today 🌟",
    "Language learning is not a sprint — it's a journey 🌍",
    "One video closer to your goal 🎬",
    "Consistency beats intensity every time 🔥",
    "You've got this 💎",
    "The only way out is through 👣",
    "Be proud of every step forward, no matter how small ✨",
    "Invest in yourself — no one can take that away from you 💰",
    "Hard work always pays off 🎖",
]

# ── /lesson ───────────────────────────────────────────
async def cmd_lesson(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    s    = get_s(user.id)

    if not s.get("goal") or not s.get("level"):
        kids_age = s.get("kids_age", "")
        is_small_kid = kids_age in ("0–1 рік", "1–3 роки", "0–3 років", "4–6 років")
        if not is_small_kid:
            await update.message.reply_text(
                "Схоже, ми ще не знайомі 👋\n\n"
                "Дай відповідь на кілька запитань, щоб отримати свій індивідуальний прогрес 👇",
                parse_mode="Markdown"
            )
        await update.message.reply_text(
            "Для чого тобі потрібна англійської? 👇",
            parse_mode="Markdown",
            reply_markup=goal_kb()
        )
        return

    level = s.get("level", "A1")
    done  = s.get("done_lessons", [])

    phrase = random.choice(MOTIVATIONAL)
    await update.message.reply_text(phrase)
    thinking = await update.message.reply_text("🔍 Підбираю відео...")

    # ── 1. Спробуємо YouTube API ──
    lesson = await youtube_search_lesson(s)

    # ── 2. Fallback на бібліотеку ──
    if not lesson:
        lesson = next_lesson(s)

    # ── 3. Якщо бібліотека теж вичерпана — підвищуємо рівень ──
    if not lesson:
        idx    = LEVELS_ORDER.index(level) if level in LEVELS_ORDER else -1
        next_l = LEVELS_ORDER[idx + 1] if idx < len(LEVELS_ORDER) - 1 else None
        await thinking.delete()
        if next_l:
            upd_s(user.id, {"level": next_l, "done_lessons": []})
            await update.message.reply_text(
                f"🎉 Рівень *{LEVEL_NAMES[level]}* пройдено!\n\n"
                f"Переходимо на *{LEVEL_NAMES[next_l]}* 🚀\n\n"
                "Натисни *🎬 Наступне відео* щоб продовжити.",
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
        else:
            await update.message.reply_text("🏆 Ти пройшов усі рівні! Браво!")
        return

    upd_s(user.id, {"current_lesson_id": lesson["id"], "current_lesson_data": lesson})
    total = len(get_lessons(s)) or 10

    await thinking.delete()

    source_label = ""
    if lesson.get("channel"):
        source_label = f"\n_📺 {lesson['channel']}_"
    cefr_label = ""
    if lesson.get("cefr_topic"):
        cefr_label = f"\n🎯 *CEFR тема:* _{lesson['cefr_topic']}_"

    await _send_merged_lesson_card(ctx.bot, user.id, lesson, s)

# ── Duration callback ─────────────────────────────────
# ── /myvideo ──────────────────────────────────────────
async def cmd_myvideo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """🎬 Мої відео — заклик ввести посилання + кнопка бібліотека."""
    user = update.effective_user
    s    = get_s(user.id)
    history = s.get("video_history", [])
    msg = update.message or (update.callback_query and update.callback_query.message)

    # Будуємо кнопки плеєра для останнього відео (якщо є)
    kb = []
    if history and WEBAPP_URL:
        last = history[0]
        vid_id = last.get("vid_id", "")
        title  = (last.get("title") or "останнє відео")[:30]
        if vid_id:
            player_url = _player_url(last.get("url", f"https://youtu.be/{vid_id}"), s)
            if player_url:
                kb.append([InlineKeyboardButton(
                    f"▶️ Відкрити в плеєрі: {title}",
                    web_app=WebAppInfo(url=player_url)
                )])

    # Кнопка бібліотека (тільки якщо є хоч одне відео)
    if history:
        kb.append([InlineKeyboardButton(
            f"📂 Моя бібліотека ({len(history)} відео)",
            callback_data="myvideo_library"
        )])

    kb.append([InlineKeyboardButton("➕ Обрати нове відео", callback_data="myvideo_add")])

    await msg.reply_text(
        "🎬 *Встав посилання на YouTube-відео*\n\n"
        "Скопіюй посилання з YouTube і надішли сюди — "
        "відео відкриється в плеєрі з субтитрами і картоткою слів 👇\n\n"
        "_Наприклад: https://youtu.be/dQw4w9WgXcQ_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb) if kb else None,
        disable_web_page_preview=True
    )
    upd_s(user.id, {"waiting_video": True})


async def cb_myvideo_library(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показує бібліотеку переглянутих відео."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    history = s.get("video_history", [])
    if not history:
        await q.message.reply_text("📂 Бібліотека поки порожня.")
        return

    lines = ["📂 *Моя бібліотека відео*\n"]
    for i, v in enumerate(history[:20], 1):
        vid_id = v.get("vid_id", "")
        date   = v.get("date", "")[:10]
        title  = v.get("title") or "YouTube відео"
        url    = v.get("url", f"https://youtu.be/{vid_id}")
        lines.append(f"{i}. [{title}]({url}) _({date})_")

    if len(history) > 20:
        lines.append(f"\n_…і ще {len(history)-20} відео_")

    # Кнопки — відкрити в плеєрі для останніх 3
    kb = []
    for v in history[:3]:
        vid_id = v.get("vid_id", "")
        date   = v.get("date", "")[:10]
        if vid_id and WEBAPP_URL:
            player_url = _player_url(v.get("url", f"https://youtu.be/{vid_id}"), s)
            if player_url:
                kb.append([InlineKeyboardButton(
                    f"▶️ Плеєр ({date})",
                    web_app=WebAppInfo(url=player_url)
                )])

    await q.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb) if kb else None,
        disable_web_page_preview=True
    )


async def cb_myvideo_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Кнопка ➕ Обрати нове відео."""
    q = update.callback_query
    await q.answer()
    await q.message.reply_text(
        "🎬 *Встав посилання на YouTube-відео*\n\n"
        "Скопіюй посилання і надішли сюди — відео відкриється в плеєрі 👇",
        parse_mode="Markdown"
    )
    upd_s(q.from_user.id, {"waiting_video": True})

# ── Build next-video recommendation ─────────────────
# ── /progress ─────────────────────────────────────────
async def cmd_progress(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = get_s(update.effective_user.id)

    if not s.get("level"):
        await update.message.reply_text(
            "👋 Схоже, ми ще не знайомі!\n\n"
            "Щоб я міг підібрати тобі відео, дай відповідь на кілька питань — це швидко 🚀",
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            "Для чого тобі потрібна англійська? 👇",
            parse_mode="Markdown",
            reply_markup=goal_kb()
        )
        return

    level    = s.get("level", "A1")
    done     = s.get("done_lessons", [])
    scores   = s.get("scores", [])
    mastered = s.get("mastered_grammar", [])
    total    = len(get_lessons(s))

    # Якщо є WEBAPP_URL — відкриваємо візуальний прогрес
    if WEBAPP_URL:
        total_topics = sum(len(v) for v in CEFR_GRAMMAR.values())
        progress_data = {
            "name":         s.get("name", "Студент"),
            "level":        level,
            "mastered":     mastered,
            "done_lessons": len(done),
            "scores":       [sc.get("score", 0) for sc in scores[-10:]],
            "streak":       s.get("streak_days", 0),
            "best_streak":  s.get("best_streak", 0),
            "total_topics": total_topics,
            "levels":       LEVELS_ORDER,
            "level_names":  LEVEL_NAMES,
            "cefr_grammar": {lvl: CEFR_GRAMMAR.get(lvl, []) for lvl in LEVELS_ORDER},
        }
        encoded    = urllib.parse.quote(json.dumps(progress_data, ensure_ascii=False))
        # Новий progress_v3 через окремий роут
        from urllib.parse import urlparse
        _parsed = urlparse(WEBAPP_URL)
        _base = f"{_parsed.scheme}://{_parsed.netloc}" if _parsed.scheme else WEBAPP_URL.rsplit("/", 1)[0]
        webapp_url = f"{_base}/progress_v3?d={encoded}"

        placement  = s.get("placement_result", {})
        test_str   = ""
        vocab_str  = ""
        if s.get("vocab_size_est"):
            vocab_str = (
                f"\n\n📖 *Словниковий запас:* ≈ {s['vocab_size_est']:,} слів  "
                f"_{s.get('vocab_level_est', '')} рівень_"
            ).replace(",", " ")
        if placement:
            g_gaps   = placement.get("grammar_gaps", [])
            v_gaps   = placement.get("vocab_gaps", [])
            gap_str  = ""
            if g_gaps: gap_str += f"\n  ⚠️ Граматика: {', '.join(g_gaps)}"
            if v_gaps: gap_str += f"\n  📖 Лексика: {', '.join(v_gaps)}"
            test_str = (
                f"\n\n🧪 Тест: *{LEVEL_NAMES.get(placement.get('level',''), '')}* "
                f"({placement.get('score','?')}/{placement.get('total','?')}) · {placement.get('date','')}"
                f"{gap_str}"
            )

        # Відсотки пройденого рівня
        level_topics   = CEFR_GRAMMAR.get(level, [])
        level_mastered = sum(1 for t in level_topics if t in mastered)
        level_pct      = int(level_mastered / len(level_topics) * 100) if level_topics else 0
        bar_done       = round(level_pct / 10)
        bar            = "█" * bar_done + "░" * (10 - bar_done)

        # ── XP і шлях до B2 ───────────────────────────────────
        xp_total  = s.get("xp_total", 0)
        xp_level  = get_xp_level(xp_total)
        cefr_xp   = build_cefr_xp_display(xp_total, level)
        xp_str    = f"\n\n{xp_level}\n{cefr_xp}"

        delta_str = ""

        kb_rows = [
            [InlineKeyboardButton("📊 Відкрити прогрес", web_app={"url": webapp_url})],
            [InlineKeyboardButton("📚 Мої фрази",         callback_data="show_my_phrases"),
             InlineKeyboardButton("🔍 Мої прогалини",     callback_data="show_gaps")],
            [InlineKeyboardButton("🎙 Мій прогрес у звуці", callback_data="voice_timeline")],
            [InlineKeyboardButton("🚀 Рухатись далі",       callback_data="progress_continue")],
        ]
        if s.get("quiz_ready"):
            kb_rows.insert(2, [InlineKeyboardButton(
                "📝 Пройти тест з останнього уроку", callback_data="quiz_start"
            )])
        kb_rows.append([InlineKeyboardButton(
            "🔄 Пройти тест знову" if s.get("cefr_test_results") else "🧪 Діагностичний тест",
            callback_data="cefr_test_start"
        )])

        # ── Питання тижня в кабінеті ──────────────────────
        wq_received = s.get("weekly_questions_received", [])
        wq_this_week = next(
            (wq for wq in reversed(wq_received)
             if wq.get("week") == datetime.now().strftime("%Y-%W")),
            None
        )
        if wq_this_week:
            answered = wq_this_week.get("answered", False)
            kb_rows.insert(0, [InlineKeyboardButton(
                "✅ Speaking Challenge виконано" if answered else "🎯 Speaking Challenge тижня",
                callback_data="wq_open_current"
            )])
        level_prog = build_level_progress_bar(s)
        await update.message.reply_text(
            f"📊 *{s.get('name','')} — Прогрес*\n\n"
            f"🎯 Рівень: *{LEVEL_NAMES.get(level, level)}*\n"
            f"`{bar}` {level_pct}% рівня пройдено\n\n"
            f"📚 Уроків: *{len(done)}*  ✅ Тем: *{level_mastered}/{len(level_topics)}*\n"
            f"🔥 Стрік: *{s.get('streak_days',0)} дн.*{xp_str}{delta_str}{vocab_str}{test_str}\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{level_prog}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb_rows)
        )
        return

    # Fallback — текстовий прогрес
    level_topics    = CEFR_GRAMMAR.get(level, [])
    level_mastered  = sum(1 for t in level_topics if t in mastered)
    level_pct       = int(level_mastered / len(level_topics) * 100) if level_topics else 0
    bar_done        = round(level_pct / 10)
    bar             = "█" * bar_done + "░" * (10 - bar_done)
    topics_left     = len(level_topics) - level_mastered

    # Наступний рівень
    cur_idx         = LEVELS_ORDER.index(level) if level in LEVELS_ORDER else 0
    next_level      = LEVELS_ORDER[cur_idx + 1] if cur_idx < len(LEVELS_ORDER) - 1 else None
    next_level_str  = f"До {LEVEL_NAMES.get(next_level, next_level)}: ще *{topics_left} тем*" if next_level and topics_left > 0 else ""

    # Рекорд тижня
    from datetime import timedelta
    week_ago        = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    prev_week_ago   = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    this_week       = sum(1 for sc in scores if sc.get("date","")[:10] >= week_ago)
    last_week       = sum(1 for sc in scores if prev_week_ago <= sc.get("date","")[:10] < week_ago)
    record_str      = ""
    if last_week > 0 and this_week < last_week:
        record_str  = f"\n\n💪 Минулого тижня: *{last_week} уроків*, цього: *{this_week}* — побий рекорд!"
    elif this_week > 0 and this_week >= last_week:
        record_str  = f"\n\n🔥 Цього тижня: *{this_week} уроків* — відмінний темп!"

    lines = [
        f"📊 *Мій шлях A1→C2: {s.get('name','')}\n",
        f"Рівень: *{LEVEL_NAMES.get(level, level)}*",
        f"`{bar}` {level_pct}% рівня пройдено",
    ]
    if next_level_str:
        lines.append(next_level_str)
    lines += [
        f"\n*Тем пройдено:* {level_mastered}/{len(level_topics)}",
        f"*Уроків всього:* {len(done)}",
        f"🔥 Стрік: *{s.get('streak_days',0)} дн.*{record_str}",
    ]

    current_topic = next_cefr_topic(s)
    if current_topic:
        lines.append(f"\n📍 *Наступна тема:* {current_topic}")

    # ── Графік останніх балів ──
    if scores:
        lines.append("\n📈 *Останні уроки:*")
        for sc in scores[-5:]:
            sc_bar = "█" * (sc["score"] // 10) + "░" * (10 - sc["score"] // 10)
            lines.append(f"Урок {sc.get('lesson_num','?')}: `{sc_bar}` {sc['score']}/100")
        if len(scores) >= 2:
            diff = scores[-1]["score"] - scores[0]["score"]
            sign = "+" if diff >= 0 else ""
            trend = "📈" if diff >= 0 else "📉"
            lines.append(f"Зростання: *{sign}{diff} балів* {trend}")

    # ── Результат placement test з прогалинами ──
    placement = s.get("placement_result", {})
    if placement:
        g_gaps  = placement.get("grammar_gaps", [])
        v_gaps  = placement.get("vocab_gaps", [])
        gap_str = ""
        if g_gaps: gap_str += f"\n  ⚠️ Граматика: {', '.join(g_gaps)}"
        if v_gaps: gap_str += f"\n  📖 Лексика: {', '.join(v_gaps)}"
        lines.append(
            f"\n🧪 *Тест на рівень:* {placement.get('date','—')}\n"
            f"Результат: *{LEVEL_NAMES.get(placement.get('level',''), placement.get('level',''))}* "
            f"({placement.get('score','?')}/{placement.get('total','?')} правильних)"
            f"{gap_str}"
        )

    # ── Повний roadmap A1 → C2 ──
    kb_rows = []
    if s.get("quiz_ready"):
        kb_rows.append([InlineKeyboardButton(
            "📝 Пройти тест з останнього уроку", callback_data="quiz_start"
        )])
    kb_rows += [
        [InlineKeyboardButton("🎙 Мій прогрес у звуці", callback_data="voice_timeline")],
        [InlineKeyboardButton("🔍 Мої прогалини",       callback_data="show_gaps")],
        [InlineKeyboardButton("🚀 Рухатись далі",       callback_data="progress_continue")],
        [InlineKeyboardButton("📤 Поділитись",          callback_data="share_card")],
        [InlineKeyboardButton(
            "🔄 Пройти тест знову" if s.get("cefr_test_results") else "🧪 Діагностичний тест",
            callback_data="cefr_test_start"
        )],
    ]
    level_prog = build_level_progress_bar(s)
    lines.append(f"\n━━━━━━━━━━━━━━━━\n{level_prog}")
    await update.message.reply_text(
        chr(10).join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_rows)
    )

    # Roadmap по рівнях — окремі повідомлення
    current_idx = LEVELS_ORDER.index(level) if level in LEVELS_ORDER else 0
    for lvl in LEVELS_ORDER:
        topics     = CEFR_GRAMMAR.get(lvl, [])
        done_count = sum(1 for t in topics if t in mastered)
        lvl_idx    = LEVELS_ORDER.index(lvl)
        is_current  = (lvl == level)
        is_unlocked = (lvl_idx <= current_idx)

        if is_current:
            header = f"📍 *{LEVEL_NAMES.get(lvl, lvl)}* ← ти тут  ({done_count}/{len(topics)})"
        elif is_unlocked:
            header = f"✅ *{LEVEL_NAMES.get(lvl, lvl)}*  ({done_count}/{len(topics)})"
        else:
            header = f"🔒 {LEVEL_NAMES.get(lvl, lvl)}  (0/{len(topics)})"

        topic_lines = [header]
        for topic in topics:
            if is_unlocked:
                mark = "✅" if topic in mastered else "⬜️"
            else:
                mark = "🔒"
            topic_lines.append(f"  {mark} {topic}")

        try:
            await update.message.reply_text(
                chr(10).join(topic_lines),
                parse_mode="Markdown"
            )
        except Exception:
            pass
    return


# ── Progress continue callback ────────────────────────
async def cb_progress_continue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()
    await q.edit_message_reply_markup(reply_markup=None)

    level    = s.get("level", "A1")
    mastered = s.get("mastered_grammar", [])
    topics   = CEFR_GRAMMAR.get(level, [])
    all_done = all(t in mastered for t in topics) and len(topics) > 0

    # ── Динамічне підвищення рівня ──
    if all_done:
        cur_idx = LEVELS_ORDER.index(level) if level in LEVELS_ORDER else -1
        next_l  = LEVELS_ORDER[cur_idx + 1] if cur_idx < len(LEVELS_ORDER) - 1 else None
        if next_l:
            await ctx.bot.send_message(
                chat_id=user.id,
                text=(
                    f"🏆 *Вітаємо! Ти пройшов усі теми рівня {LEVEL_NAMES.get(level, level)}!*\n\n"
                    f"Готовий перейти на *{LEVEL_NAMES.get(next_l, next_l)}*? 🚀"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"🚀 Перейти на {next_l}", callback_data=f"levelup_{next_l}")],
                    [InlineKeyboardButton("📚 Залишитись на поточному", callback_data="fork_choose")],
                ])
            )
            return

    next_topic = next_cefr_topic(s) or "нова тема"

    # ── Простий цикл: Відео → Монолог → Оцінка ──
    # Тест — опційно після оцінки
    upd_s(user.id, {"cycle_topic": next_topic, "cycle_step": 1})

    await ctx.bot.send_message(
        chat_id=user.id,
        text=(
            f"🎯 *Наступна тема:* _{next_topic}_\n\n"
            "Підбираю відео... 🔍"
        ),
        parse_mode="Markdown"
    )
    await _auto_send_next_lesson(ctx.bot, user.id)

# ── Cycle video handler ───────────────────────────────
async def cb_cycle_get_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Підбирає відео для поточного кроку циклу."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    is_theory   = s.get("force_theory", False)
    is_practice = s.get("force_practice", False)
    topic       = s.get("cycle_topic", next_cefr_topic(s) or "")

    # Очищаємо флаги
    upd_s(user.id, {"force_theory": False, "force_practice": False})

    await q.edit_message_text(
        "🔍 Підбираю відео...",
        parse_mode="Markdown"
    )

    # Формуємо запит залежно від кроку
    level     = s.get("level", "A1")
    age_group = s.get("age_group", "adult")
    grammar_q = CEFR_TOPIC_QUERIES.get(topic, topic.lower())

    if is_theory:
        query   = f"{grammar_q} explained short"
        max_dur = 5
    else:
        query   = f"{grammar_q} shadowing repeat after me practice"
        max_dur = 8

    results = await youtube_search(query, max_results=5, age_group=age_group, max_duration_min=max_dur)

    if not results:
        await ctx.bot.send_message(
            chat_id=user.id,
            text="😔 Не знайшов підходящого відео. Спробуй через хвилину.",
            reply_markup=main_menu()
        )
        return

    r = results[0]
    upd_s(user.id, {"current_lesson_id": r["id"], "current_lesson_data": r,
                    "current_lesson_title": r.get("title", "")})

    await _send_merged_lesson_card(ctx.bot, user.id, r, s)

async def cb_retest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    upd_s(user.id, {
        "placement_active":  True,
        "placement_score":   0,
        "placement_count":   0,
        "placement_current": PLACEMENT_FLOW["start"],
    })
    await q.edit_message_reply_markup(reply_markup=None)
    await ctx.bot.send_message(
        chat_id=user.id,
        text=(
            "🧪 *Тест на визначення рівня*\n\n"
            "Близько 10–12 питань — граматика, лексика та аудіювання.\n"
            "Відповідай чесно — підберемо найточніші відео 🎯\n\n"
            "Починаємо! 👇"
        ),
        parse_mode="Markdown"
    )
    await send_placement_question(ctx.bot, user.id, PLACEMENT_FLOW["start"])

# ── Level up callback ─────────────────────────────────
async def cb_levelup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()
    next_l = q.data.replace("levelup_", "")
    if next_l not in LEVELS_ORDER:
        return

    old_level = s.get("level", "A1")
    upd_s(user.id, {
        "level":        next_l,
        "done_lessons": [],
        "mastered_grammar": [],
    })
    await q.edit_message_reply_markup(reply_markup=None)

    # ── Святковий момент з конкретними цифрами ──
    level_emojis = {"A2":"🌱","B1":"🔥","B2":"⚡️","C1":"💎","C2":"👑"}
    emoji = level_emojis.get(next_l, "🎉")

    # Підраховуємо скільки днів пішло на рівень
    reg_str    = s.get("registered_at","")
    days_spent = ""
    if reg_str:
        try:
            from datetime import timedelta
            reg_date   = datetime.strptime(reg_str, "%Y-%m-%d")
            days_count = (datetime.now() - reg_date).days
            if days_count > 0:
                days_spent = f" за *{days_count} днів*"
        except Exception:
            pass

    done_count = len(s.get("done_lessons", []))
    share_text = (
        f"Я перейшов з {LEVEL_NAMES.get(old_level,old_level)} "
        f"на {LEVEL_NAMES.get(next_l,next_l)}{days_spent} "
        f"у SpeakChain! 🚀"
    )
    upd_s(user.id, {"last_levelup_share": share_text})

    await ctx.bot.send_message(
        chat_id=user.id,
        text=(
            f"{emoji} *Вітаємо! Ти перейшов на {LEVEL_NAMES.get(next_l, next_l)}!*\n\n"
            f"З *{LEVEL_NAMES.get(old_level,old_level)}* до *{LEVEL_NAMES.get(next_l,next_l)}*"
            f"{days_spent} · {done_count} уроків — це реальний результат 💪\n\n"
            f"🎯 _{LEVEL_SKILLS.get(next_l, '')}_\n\n"
            f"Перша тема: _{CEFR_GRAMMAR.get(next_l, [''])[0]}_\n\n"
            f"_«{share_text}»_"
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Поділитись результатом", callback_data="share_socials")],
            [InlineKeyboardButton("🎙 Послухати прогрес",      callback_data="before_after")],
            [InlineKeyboardButton("🚀 Новий рівень",           callback_data="fork_choose")],
        ])
    )



# ── "До і після" — порівняння першого і останнього монологу ──
async def cb_before_after(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    first_id  = s.get("first_voice_file_id","")
    last_id   = s.get("last_voice_file_id","")
    first_date= s.get("first_voice_date","")
    first_score = s.get("first_voice_score", 0)

    if not first_id or not last_id or first_id == last_id:
        await q.edit_message_text(
            "🎙 Як тільки запишеш ще кілька монологів — я покажу твій прогрес у звуці 🔥",
            parse_mode="Markdown"
        )
        return

    await q.edit_message_text(
        f"🎙 *Твій прогрес у звуці*\n\n"
        f"День 1 ({first_date}) — бал: *{first_score}/100*\n"
        "👇",
        parse_mode="Markdown"
    )
    try:
        await ctx.bot.send_voice(chat_id=user.id, voice=first_id, caption="📅 Перший монолог")
        await ctx.bot.send_message(chat_id=user.id, text="⬇️ А ось ти зараз:")
        await ctx.bot.send_voice(chat_id=user.id, voice=last_id,  caption="🔥 Останній монолог")
        await ctx.bot.send_message(
            chat_id=user.id,
            text="Чуєш різницю? Це ти за кілька тижнів роботи 💪\n\nПоділись — нехай інші теж почують!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📱 Поділитись прогресом", callback_data="share_socials")
            ]])
        )
    except Exception as e:
        logger.warning(f"Before/after error: {e}")
        await ctx.bot.send_message(chat_id=user.id, text="😔 Записи не знайдено. Продовжуй навчатись!")

async def job_before_after_reminder(ctx):
    """Щомісяця нагадує студентам послухати свій прогрес."""
    from datetime import timedelta
    db    = load_db()
    today = datetime.now()
    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) == "quiz_cache": continue
        if not s.get("onboarding_done"): continue
        if not s.get("first_voice_file_id"): continue
        if not s.get("last_voice_file_id"): continue
        if s.get("first_voice_file_id") == s.get("last_voice_file_id"): continue

        reg_str = s.get("registered_at","")
        if not reg_str: continue
        try:
            reg_date   = datetime.strptime(reg_str, "%Y-%m-%d")
            days_since = (today - reg_date).days
            # Надсилаємо на 30-й, 60-й, 90-й день
            if days_since in (30, 60, 90) and not s.get(f"before_after_sent_{days_since}"):
                upd_s(int(uid), {f"before_after_sent_{days_since}": True})
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"🎙 *{days_since} днів з SpeakChain!*\n\n"
                        "Хочеш почути як змінилось твоє мовлення з першого дня? 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🎧 Послухати прогрес", callback_data="before_after")
                    ]])
                )
        except Exception:
            continue

# ── Admin helpers ─────────────────────────────────────
def admin_only(func):
    async def wrapper(update, ctx):
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("⛔️ Доступ заборонено.")
            return
        await func(update, ctx)
    return wrapper

async def cmd_gen_ref(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Генерує реферальні посилання для блогера."""
    if not is_admin(update.effective_user.id):
        return
    args = ctx.args or []
    if not args:
        from telegram import ForceReply
        await update.message.reply_text(
            "🔗 Введи Telegram username блогера 👇\n\nНаприклад: maria або @maria",
            reply_markup=ForceReply(selective=True, input_field_placeholder="@username")
        )
        ADMIN_STATE["waiting"] = "gen_ref"
        return
    await _do_gen_ref(update, ctx, args[0])

async def _do_gen_ref(update, ctx, raw_name: str):
    name = raw_name.lstrip("@").lower().strip()
    if not name:
        await update.message.reply_text("❌ Введи коректний username.")
        return
    import secrets
    bot_user = (await ctx.bot.get_me()).username
    code     = f"spk_{name}_{secrets.token_hex(4)}"
    codes    = get_blogger_codes()
    existing = [c for c, n in codes.items() if n == name]
    if not existing:
        codes[code] = name
        save_blogger_codes(codes)
    else:
        code = existing[0]

    text = (
        f"✅ Код створено для блогера @{name}\n"
        f"Секретний код для входу в панель:\n{code}\n\n"
        f"─────────────────────\n"
        f"🔗 Реферальні посилання:\n\n"
        f"▶️ YouTube:\nhttps://t.me/{bot_user}?start=ref_{name}_yt\n\n"
        f"📸 Instagram:\nhttps://t.me/{bot_user}?start=ref_{name}_ig\n\n"
        f"🎵 TikTok:\nhttps://t.me/{bot_user}?start=ref_{name}_tt\n\n"
        f"👤 Facebook:\nhttps://t.me/{bot_user}?start=ref_{name}_fb\n\n"
        f"─────────────────────\n"
        f"📹 YouTube з конкретним відео:\n"
        f"🎬 *Посилання для відео* (підстав ID відео замість VIDEO_ID):\n"
        f"`{MINIAPP_URL}?startapp=VIDEO_ID`\n\n"
        f"Студент клікає → Telegram відкриває плеєр з відео одразу 🚀"
        f"Заміни YOUTUBE_ID на ID відео з URL"
    )
    await update.message.reply_text(text)

# ── Retest callback ───────────────────────────────────

@admin_only
async def cmd_admin(update, ctx):
    from datetime import timedelta
    db    = load_db()
    users = [s for s in db.values() if isinstance(s, dict) and any(k in s for k in ("onboarding_done", "last_date", "level", "goal", "plan"))]

    total     = len(users)
    onboarded = sum(1 for s in users if s.get("onboarding_done"))
    premium   = sum(1 for s in users if is_premium(s) and s.get("plan") == "premium")
    basic     = sum(1 for s in users if is_premium(s) and s.get("plan","basic") == "basic")
    trial     = sum(1 for s in users if is_in_trial(s))
    week_ago  = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    active_7  = sum(1 for s in users if s.get("last_date","") >= week_ago)

    # Статистика оплат за поточний місяць (з plan_activated — покриває всі оплати)
    this_month    = datetime.now().strftime("%Y-%m")
    month_basic   = sum(1 for s in users if is_premium(s) and s.get("plan","basic") == "basic"
                        and s.get("plan_activated","").startswith(this_month))
    month_premium = sum(1 for s in users if is_premium(s) and s.get("plan") == "premium"
                        and s.get("plan_activated","").startswith(this_month))
    month_rev_b   = month_basic   * float(BASIC_PRICE)
    month_rev_p   = month_premium * float(PREMIUM_PRICE_FULL)
    month_rev     = month_rev_b + month_rev_p

    levels_count = {}
    for s in users:
        lvl = s.get("level","?")
        levels_count[lvl] = levels_count.get(lvl, 0) + 1
    levels_str = "  ".join(f"{l}:{c}" for l,c in sorted(levels_count.items()))

    goals_count = {}
    for s in users:
        g = s.get("goal","?")
        goals_count[g] = goals_count.get(g, 0) + 1
    goals_str = chr(10).join(
        f"  {GOAL_NAMES.get(g,g)}: {c}"
        for g,c in sorted(goals_count.items(), key=lambda x:-x[1])
    )

    refs_count = {}
    for s in users:
        ref = s.get("affiliate_ref","")
        if ref:
            refs_count[ref] = refs_count.get(ref, 0) + 1
    refs_total = sum(refs_count.values())
    refs_str   = "  ".join(f"{r}:{c}" for r,c in sorted(refs_count.items(), key=lambda x:-x[1]))

    msg = (
        "📊 *SpeakChain — Статистика*\n\n"
        f"👥 Всього студентів: *{total}*\n"
        f"✅ Онбоардинг пройшли: *{onboarded}*\n"
        f"⚡️ Basic: *{basic}*  🌟 Premium: *{premium}*  🎁 Тріал: *{trial}*\n"
        f"🔥 Активних за 7 днів: *{active_7}*\n\n"
        f"💰 *Оплати за {this_month}:*\n"
        f"  ⚡️ Basic: *{month_basic}* оплат  (~${month_rev_b:.0f})\n"
        f"  🌟 Premium: *{month_premium}* оплат  (~${month_rev_p:.0f})\n"
        f"  📦 Разом: *{month_basic+month_premium}* оплат  (~*${month_rev:.0f}*)\n\n"
        f"📈 *Рівні:*\n  {levels_str}\n\n"
        f"🎯 *Цілі:*\n{goals_str}\n\n"
        f"🔗 *Реферали:* {refs_total} студентів"
    )
    if refs_str:
        msg += f"\n  {refs_str}"

    await update.message.reply_text(msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡️ Список Basic",  callback_data="adm_basic_list"),
             InlineKeyboardButton("🌟 Список Premium", callback_data="adm_premium_list")],
            [InlineKeyboardButton("🔗 Звіт по рефералах", callback_data="adm_refs_report")],
            [InlineKeyboardButton("💸 Виплати блогерам",  callback_data="adm_payouts_now")],
            [InlineKeyboardButton("👥 Блогери",           callback_data="adm_bloggers_list")],
            [InlineKeyboardButton("👥 Premium група",      callback_data="adm_setup_group")],
            [InlineKeyboardButton("🏆 Опублікувати рейтинг", callback_data="adm_post_rating")],
            [InlineKeyboardButton("📢 Розсилка",            callback_data="adm_broadcast")],
            [InlineKeyboardButton("🔧 Admin Panel",         callback_data="help_admin")],
        ])
    )

# ── Broadcast — масова розсилка з типами ─────────────────────
#
# Типи повідомлень:
#   system   📢  — від SpeakChain (оновлення, анонси)
#   blogger  🎬  — від конкретного блогера
#   chain    🔗  — системна подія (milestone, chain update)
#   promo    🎁  — акція, спецпропозиція
#
# ВАЖЛИВО: broadcast НЕ надсилає критичні (платіжні) повідомлення.
# Критичні повідомлення завжди надсилаються напряму через send_message.

BROADCAST_PREFIXES = {
    "system":  "📢 *SpeakChain*",
    "blogger": "🎬",
    "chain":   "🔗 *Chain Update*",
    "promo":   "🎁 *Для тебе*",
}

async def broadcast(
    bot,
    text:          str,
    notification_type: str = "system",
    blogger_name:  str | None = None,
    filter_fn              = None,
    only_premium:  bool    = False,
    only_trial:    bool    = False,
    skip_blocked:  bool    = True,
    db:            dict | None = None,
) -> dict:
    """
    Масова розсилка з типами.

    Args:
        text              — текст повідомлення (Markdown)
        notification_type — 'system' | 'blogger' | 'chain' | 'promo'
        blogger_name      — ім'я блогера (якщо type='blogger')
        filter_fn         — lambda s: bool — додатковий фільтр юзерів
        only_premium      — тільки платним
        only_trial        — тільки тріал юзерам
        skip_blocked      — пропускати тих хто заблокував бота (default: True)
        db                — передати якщо вже є (уникає зайвого load_db)

    Returns:
        {"sent": int, "skipped": int, "blocked": int, "errors": int}
    """
    if db is None:
        db = load_db()

    prefix = BROADCAST_PREFIXES.get(notification_type, "📢")
    if notification_type == "blogger" and blogger_name:
        prefix = f"🎬 *{blogger_name}*"

    full_text = f"{prefix}\n\n{text}"

    stats = {"sent": 0, "skipped": 0, "blocked": 0, "errors": 0}

    tasks = []
    for uid, s in db.items():
        if not isinstance(s, dict):       continue
        if uid in DB_SKIP_KEYS:           continue
        if not s.get("onboarding_done"):  continue

        # Фільтри аудиторії
        if only_premium and not is_premium(s):
            stats["skipped"] += 1
            continue
        if only_trial and not is_in_trial(s):
            stats["skipped"] += 1
            continue
        if filter_fn and not filter_fn(s):
            stats["skipped"] += 1
            continue
        if skip_blocked and s.get("bot_blocked"):
            stats["blocked"] += 1
            continue

        _uid = int(uid)
        async def _task(u=_uid, t=full_text):
            return await _safe_send(bot, u, t, parse_mode="Markdown")
        tasks.append(_task)

    batch_stats = await _send_in_batches(bot, tasks)
    stats["sent"]   = batch_stats["sent"]
    stats["errors"] = batch_stats["errors"]

    logger.info(f"Broadcast [{notification_type}]: {stats}")
    return stats


async def cmd_blogger_broadcast(update, ctx):
    """
    /blogger_broadcast Текст
    Блогер надсилає повідомлення тільки своїм студентам.
    Автоматично підставляє імʼя блогера як prefix.
    """
    uid  = update.effective_user.id
    if not is_blogger(uid):
        await update.message.reply_text("⛔️ Тільки для блогерів.")
        return

    args = ctx.args or []
    text = " ".join(args).strip()
    if not text:
        await update.message.reply_text(
            "Використання:\n`/blogger_broadcast Текст для студентів`",
            parse_mode="Markdown"
        )
        return

    bname    = get_blogger_name(uid)
    db       = load_db()

    # Студенти цього блогера
    students = [
        (k, v) for k, v in db.items()
        if isinstance(v, dict)
        and v.get("affiliate_blogger", "").lower() == bname.lower()
        and v.get("onboarding_done")
        and not v.get("bot_blocked")
    ]

    if not students:
        await update.message.reply_text("У тебе ще немає студентів.")
        return

    # Превʼю
    upd_s(uid, {
        "pending_blogger_broadcast": {"text": text, "blogger_name": bname}
    })

    await update.message.reply_text(
        f"📤 *Превʼю*\n\n"
        f"🎬 *{bname}*\n\n{text}\n\n"
        f"─────────────\n"
        f"Отримають: *{len(students)}* студентів",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Надіслати студентам", callback_data="blogger_bc_confirm")],
            [InlineKeyboardButton("❌ Скасувати",           callback_data="blogger_bc_cancel")],
        ])
    )


async def cb_blogger_bc_confirm(update, ctx):
    q   = update.callback_query
    uid = q.from_user.id
    await q.answer()

    if not is_blogger(uid):
        return

    s       = get_s(uid)
    pending = s.get("pending_blogger_broadcast")
    if not pending:
        await q.edit_message_text("❌ Нема pending розсилки.")
        return

    await q.edit_message_text("⏳ Надсилаю студентам...")

    bname = pending["blogger_name"]
    db    = load_db()

    stats = await broadcast(
        bot               = ctx.bot,
        text              = pending["text"],
        notification_type = "blogger",
        blogger_name      = bname,
        filter_fn         = lambda s: s.get("affiliate_blogger","").lower() == bname.lower(),
        db                = db,
    )

    upd_s(uid, {"pending_blogger_broadcast": None})

    await ctx.bot.send_message(
        uid,
        f"✅ Надіслано *{stats['sent']}* студентам\n"
        f"🚫 Заблокованих: *{stats['blocked']}*",
        parse_mode="Markdown"
    )


async def cb_blogger_bc_cancel(update, ctx):
    q = update.callback_query
    await q.answer()
    upd_s(q.from_user.id, {"pending_blogger_broadcast": None})
    await q.edit_message_text("❌ Скасовано.")


async def cmd_broadcast(update, ctx):
    """
    /broadcast [тип] текст
    Типи: system (default), blogger, chain, promo
    Тільки адмін.

    Приклади:
      /broadcast Нова функція — Speaking Buddy вже доступний!
      /broadcast promo Знижка 20% тільки сьогодні
      /broadcast blogger @ivan_english Нове відео вже в боті!
    """
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("⛔️ Тільки адмін.")
        return

    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Використання:\n"
            "`/broadcast Текст повідомлення`\n"
            "`/broadcast promo Текст`\n"
            "`/broadcast blogger @name Текст`\n\n"
            "Типи: system · blogger · chain · promo",
            parse_mode="Markdown"
        )
        return

    # Парсимо тип і текст
    notification_type = "system"
    blogger_name      = None
    text_start        = 0

    if args[0] in BROADCAST_PREFIXES:
        notification_type = args[0]
        text_start = 1
        if notification_type == "blogger" and len(args) > 1 and args[1].startswith("@"):
            blogger_name = args[1].lstrip("@")
            text_start   = 2

    text = " ".join(args[text_start:]).strip()
    if not text:
        await update.message.reply_text("❌ Текст порожній.")
        return

    # Показуємо превʼю і питаємо підтвердження
    prefix = BROADCAST_PREFIXES.get(notification_type, "📢")
    if notification_type == "blogger" and blogger_name:
        prefix = f"🎬 *{blogger_name}*"

    db        = load_db()
    total     = sum(1 for s in db.values() if isinstance(s, dict) and s.get("onboarding_done"))
    blocked   = sum(1 for s in db.values() if isinstance(s, dict) and s.get("bot_blocked"))
    will_send = total - blocked

    # Зберігаємо pending broadcast
    upd_s(uid, {
        "pending_broadcast": {
            "text":              text,
            "notification_type": notification_type,
            "blogger_name":      blogger_name,
        }
    })

    await update.message.reply_text(
        f"📤 *Превʼю розсилки*\n\n"
        f"{prefix}\n\n{text}\n\n"
        f"─────────────────\n"
        f"👥 Отримають: *{will_send}* юзерів\n"
        f"🚫 Заблокували бота: *{blocked}*\n"
        f"⏱ Час відправки: ~{will_send // 29 // 60 + 1} хв\n\n"
        f"Тип: *{notification_type}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Надіслати", callback_data="broadcast_confirm")],
            [InlineKeyboardButton("❌ Скасувати", callback_data="broadcast_cancel")],
        ])
    )


async def cb_broadcast_confirm(update, ctx):
    """Підтвердження і запуск broadcast."""
    q   = update.callback_query
    uid = q.from_user.id
    await q.answer()

    if not is_admin(uid):
        return

    s       = get_s(uid)
    pending = s.get("pending_broadcast")
    if not pending:
        await q.edit_message_text("❌ Нема pending розсилки. Почни з /broadcast")
        return

    await q.edit_message_text("⏳ Розсилка розпочата...")

    stats = await broadcast(
        bot               = ctx.bot,
        text              = pending["text"],
        notification_type = pending.get("notification_type", "system"),
        blogger_name      = pending.get("blogger_name"),
    )

    # Очищаємо pending
    upd_s(uid, {"pending_broadcast": None})

    await ctx.bot.send_message(
        uid,
        f"✅ *Розсилка завершена*\n\n"
        f"📤 Надіслано: *{stats['sent']}*\n"
        f"⏭ Пропущено: *{stats['skipped']}*\n"
        f"🚫 Заблоковано: *{stats['blocked']}*\n"
        f"❌ Помилок: *{stats['errors']}*",
        parse_mode="Markdown"
    )


async def cb_broadcast_cancel(update, ctx):
    q = update.callback_query
    await q.answer()
    upd_s(q.from_user.id, {"pending_broadcast": None})
    await q.edit_message_text("❌ Розсилку скасовано.")


# ── Блогер: реєстрація через секретний код ────────────

def get_blogger_codes() -> dict:
    """Словник {код: blogger_name}."""
    return load_db().get("_blogger_codes", {})

def save_blogger_codes(codes: dict):
    db = load_db(); db["_blogger_codes"] = codes; save_db(db)

def get_registered_bloggers() -> dict:
    """Словник {str(user_id): blogger_name}."""
    return load_db().get("_registered_bloggers", {})

def save_registered_bloggers(bloggers: dict):
    db = load_db(); db["_registered_bloggers"] = bloggers; save_db(db)

def is_blogger(user_id: int) -> bool:
    return str(user_id) in get_registered_bloggers()

def get_blogger_name(user_id: int) -> str:
    return get_registered_bloggers().get(str(user_id), "")


def blogger_main_menu() -> ReplyKeyboardMarkup:
    """Головне меню для блогера — замість стандартного."""
    return ReplyKeyboardMarkup(
        [["🎬 Мої відео",          "📊 Прогрес"],
         ["🏆 Мій челендж",         "👤 Панель блогера"],
         ["❓ Допомога"]],
        resize_keyboard=True,
        is_persistent=True
    )

# Повний набір кнопок меню — для скидання waiting_* станів
ALL_MENU_BUTTONS = {
    "🎬 Мої відео", "📎 Я вже обрав відео", "📎 Я сам обрав відео",
    "📊 Прогрес", "📊 Мій шлях A1→C2", "📊 Мій прогрес",
    "❓ Допомога", "🎯 Челендж дня", "🎯 Челендж", "🏆 Мій челендж",
    "👤 Панель блогера", "📚 Мої слова", "📚 Мої фрази",
    "🎯 Порадь мені відео", "🎬 Наступне відео", "📚 Урок",
}

# ════════════════════════════════════════════════════
# BLOGGER CHALLENGE SYSTEM
# ════════════════════════════════════════════════════

def get_blogger_challenge(blogger_name: str) -> dict:
    """Повертає активний challenge блогера або {}."""
    db = load_db()
    challenges = db.get("_blogger_challenges", {})
    return challenges.get(blogger_name.lower(), {})


def set_blogger_challenge(blogger_name: str, topic: str, blogger_uid: int):
    """Зберігає новий challenge блогера."""
    db = load_db()
    challenges = db.get("_blogger_challenges", {})
    challenges[blogger_name.lower()] = {
        "topic":        topic,
        "blogger_name": blogger_name,
        "blogger_uid":  str(blogger_uid),
        "created_at":   datetime.now().strftime("%Y-%m-%d"),
        "week":         datetime.now().strftime("%Y-%W"),
        "active":       True,
        "submissions":  [],   # [{uid, name, score, date}]
    }
    db["_blogger_challenges"] = challenges
    save_db(db)


async def cmd_blogger_set_challenge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/my_challenge ТЕМА — блогер задає новий челендж своїм студентам."""
    user = update.effective_user
    if not is_blogger(user.id) and not is_admin(user.id):
        await update.message.reply_text("⛔️ Тільки для блогерів.")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "📝 Використання:\n`/my_challenge Розкажи про своє улюблене місце в Україні`\n\n"
            "Тема отримають усі твої студенти як кнопку в меню.",
            parse_mode="Markdown"
        )
        return

    s    = get_s(user.id)
    bname = s.get("blogger_name", user.username or str(user.id))
    topic = " ".join(args)

    set_blogger_challenge(bname, topic, user.id)

    # Розсилка студентам блогера
    db      = load_db()
    bloggers = get_registered_bloggers()
    sent    = 0
    for uid, st in db.items():
        if not isinstance(st, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not st.get("onboarding_done"): continue
        if st.get("affiliate_blogger", "").lower() != bname.lower(): continue
        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=(
                    f"🏆 *Новий челендж від @{bname}!*\n\n"
                    f"🎯 *Тема:* {topic}\n\n"
                    "Запиши монолог 30–60 секунд на цю тему — AI оцінить і порівняє з іншими студентами.\n\n"
                    "Натисни кнопку *🎯 Челендж* в меню щоб розпочати 👇"
                ),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
            sent += 1
        except Exception as e:
            logger.warning(f"challenge notify {uid}: {e}")

    await update.message.reply_text(
        f"✅ *Челендж запущено!*\n\n"
        f"Тема: _{topic}_\n"
        f"Надіслано: *{sent}* студентів\n\n"
        "Студенти побачать кнопку 🎯 Челендж в меню.",
        parse_mode="Markdown"
    )


async def cmd_student_challenge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """🎯 Челендж — студент бачить активний challenge свого блогера."""
    user = update.effective_user
    s    = get_s(user.id)
    bname = s.get("affiliate_blogger", "")

    if not bname:
        # Немає блогера — показуємо загальний challenge
        await cmd_challenge(update, ctx)
        return

    ch = get_blogger_challenge(bname)
    if not ch or not ch.get("active"):
        # Блогер є але челендж неактивний → показуємо ботівський 7-денний
        await update.message.reply_text(
            f"🎯 *@{bname}* поки не запустив новий челендж.\n"
            "Поки що — приєднуйся до загального speaking challenge від SpeakChain! 👇",
            parse_mode="Markdown",
        )
        await cmd_challenge(update, ctx)
        return

    topic       = ch.get("topic", "")
    submissions = ch.get("submissions", [])
    total       = len(submissions)

    # Чи вже брав участь цей студент цього тижня
    week_key    = datetime.now().strftime("%Y-%W")
    already     = any(str(s2.get("uid")) == str(user.id) and s2.get("week") == week_key
                      for s2 in submissions)

    # Топ-3 учасники
    top3 = sorted(submissions, key=lambda x: x.get("score", 0), reverse=True)[:3]
    medals = ["🥇", "🥈", "🥉"]
    top_lines = ""
    if top3:
        top_lines = "\n\n🏆 *Топ учасників:*\n"
        for i, sub in enumerate(top3):
            top_lines += f"{medals[i]} {sub.get('name','?')} — *{sub.get('score',0)}/100*\n"

    text = (
        f"🎯 *Челендж від @{bname}*\n\n"
        f"📝 *Тема:* {topic}\n\n"
        f"👥 Вже взяли участь: *{total}*{top_lines}\n\n"
    )

    if already:
        text += "✅ Ти вже взяв участь цього тижня! Чекаємо результатів."
        kb = [[InlineKeyboardButton("🏆 Таблиця лідерів", callback_data="blogger_challenge_leaderboard")]]
    else:
        text += "Запиши монолог на цю тему — 30–60 секунд англійською 🎙"
        # Зберігаємо тему щоб handle_voice знав контекст
        upd_s(user.id, {
            "blogger_challenge_topic":  topic,
            "blogger_challenge_blogger": bname,
            "blogger_challenge_active": True,
        })
        kb = [
            [InlineKeyboardButton("🎙 Записати монолог", callback_data="remind_record")],
            [InlineKeyboardButton("🏆 Таблиця лідерів", callback_data="blogger_challenge_leaderboard")],
        ]

    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def cb_blogger_new_challenge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Блогер хоче запустити новий челендж."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    await q.edit_message_text(
        "📝 *Новий челендж*\n\n"
        "Надішли тему командою:\n"
        "`/my_challenge Твоя тема тут`\n\n"
        "_Наприклад: «Розкажи про своє улюблене місце в Україні» або «Опиши ідеальний день»_",
        parse_mode="Markdown"
    )


async def cb_blogger_challenge_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Блогер нагадує студентам про challenge."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer("Надсилаю нагадування...")
    bname = s.get("blogger_name", "")
    ch    = get_blogger_challenge(bname)
    if not ch:
        await q.edit_message_text("Немає активного челенджу.")
        return

    topic = ch.get("topic", "")
    db    = load_db()
    sent  = 0
    subs_uids = {str(x.get("uid")) for x in ch.get("submissions", [])}

    for uid, st in db.items():
        if not isinstance(st, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not st.get("onboarding_done"): continue
        if st.get("affiliate_blogger", "").lower() != bname.lower(): continue
        if str(uid) in subs_uids: continue  # вже взяли участь
        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=(
                    f"🔔 *Нагадування від @{bname}*\n\n"
                    f"🎯 Челендж ще активний: _{topic}_\n\n"
                    "Ти ще не записав монолог — є час взяти участь! 🎙"
                ),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
            sent += 1
        except Exception:
            pass

    await q.edit_message_text(
        f"✅ Нагадування надіслано *{sent}* студентам які ще не взяли участь.",
        parse_mode="Markdown"
    )


async def cb_blogger_challenge_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Таблиця лідерів blogger challenge."""
    q     = update.callback_query
    user  = q.from_user
    s     = get_s(user.id)
    bname = s.get("affiliate_blogger", "")
    await q.answer()

    if not bname:
        await q.edit_message_text("❌ Блогера не знайдено.")
        return

    ch = get_blogger_challenge(bname)
    if not ch:
        await q.edit_message_text("Активних челенджів немає.")
        return

    submissions = sorted(ch.get("submissions", []), key=lambda x: x.get("score", 0), reverse=True)
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    lines = [f"🏆 *Челендж @{bname}*\n_{ch.get('topic','')}_\n"]
    if not submissions:
        lines.append("Поки немає учасників. Будь першим! 🚀")
    else:
        for i, sub in enumerate(submissions[:10]):
            medal = medals[i] if i < len(medals) else f"{i+1}."
            me    = "← ти" if str(sub.get("uid")) == str(user.id) else ""
            lines.append(f"{medal} *{sub.get('name','?')}* — {sub.get('score',0)}/100 {me}")

    await q.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_challenge")
        ]])
    )


# ════════════════════════════════════════════════════
# DUEL SYSTEM — челендж між студентами
# ════════════════════════════════════════════════════

def _get_duel_opponents(uid: int, blogger_name: str, db: dict, limit: int = 5) -> list:
    """Повертає список потенційних опонентів — студенти того ж блогера близького рівня."""
    s       = get_s(uid)
    my_lvl  = s.get("level", "A1")
    levels  = ["A1","A2","B1","B2","C1","C2"]
    my_idx  = levels.index(my_lvl) if my_lvl in levels else 0
    # Допустимі рівні: -1 / 0 / +1
    ok_lvls = {levels[i] for i in range(max(0,my_idx-1), min(len(levels),my_idx+2))}

    opponents = []
    for u, st in db.items():
        if not isinstance(st, dict): continue
        if str(u) in DB_SKIP_KEYS: continue
        if str(u) == str(uid): continue
        if not st.get("onboarding_done"): continue
        if st.get("affiliate_blogger","").lower() != blogger_name.lower(): continue
        if st.get("level","A1") not in ok_lvls: continue
        opponents.append((u, st.get("name","?"), st.get("level","A1")))

    import random as _rnd
    _rnd.shuffle(opponents)
    return opponents[:limit]


def _create_duel(challenger_uid: int, challenged_uid: int, topic: str, challenger_score: int) -> str:
    """Створює новий дует і повертає duel_id."""
    import time as _t
    duel_id = f"duel_{challenger_uid}_{challenged_uid}_{int(_t.time())}"
    db      = load_db()
    duels   = db.get("_active_duels", {})
    duels[duel_id] = {
        "challenger":       str(challenger_uid),
        "challenged":       str(challenged_uid),
        "topic":            topic,
        "challenger_score": challenger_score,
        "challenged_score": None,
        "status":           "pending",   # pending → accepted → completed / declined
        "created_at":       datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    db["_active_duels"] = duels
    save_db(db)
    return duel_id


def _get_duel(duel_id: str) -> dict:
    return load_db().get("_active_duels", {}).get(duel_id, {})


def _update_duel(duel_id: str, data: dict):
    db    = load_db()
    duels = db.get("_active_duels", {})
    if duel_id in duels:
        duels[duel_id].update(data)
        db["_active_duels"] = duels
        save_db(db)



# ══════════════════════════════════════════════════════════════
# ГРАМАТИЧНІ CALLBACKS
# ══════════════════════════════════════════════════════════════

async def cb_grammar_lesson_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент натиснув 'Так, давай' — запускаємо міні-урок."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    pending_topic  = s.get("grammar_pending_topic", "")
    pending_phrase = s.get("grammar_pending_phrase", "")
    if not pending_topic or pending_topic not in GRAMMAR_MAP:
        await q.message.reply_text("⚠️ Тема не знайдена. Продовжуй дивитись відео!")
        return

    level = s.get("level", "A1")

    # Крок 1: пояснення у стилі Голіцинського
    explanation = format_explanation(pending_topic, pending_phrase)
    await q.message.reply_text(explanation, parse_mode="Markdown")

    # Крок 2: перша вправа
    import asyncio as _aio
    await _aio.sleep(2)
    await _send_grammar_exercise(ctx.bot, user.id, pending_topic, level, 1, 0)


async def cb_grammar_nudge_snooze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент натиснув 'Пізніше'."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    topic_key = s.get("grammar_pending_topic", "")
    if topic_key:
        s_updated = mark_nudge_snoozed(s, topic_key)
        upd_s(user.id, {"grammar_topics": s_updated["grammar_topics"]})
    await q.answer("Добре, нагадаю пізніше 👌")
    try:
        await q.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


async def cb_grammar_exercise(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент обрав варіант відповіді у вправі (gram_ex_A/B/C/D)."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    q    = update.callback_query
    user = q.from_user
    data = q.data
    chosen = data.replace("gram_ex_", "")  # A, B, C або D
    s    = get_s(user.id)
    ex_state = s.get("grammar_exercise_state", {})
    if not ex_state:
        await q.answer()
        return

    correct     = ex_state.get("correct", "")
    explanation = ex_state.get("explanation", "")
    count       = ex_state.get("count", 1)
    score       = ex_state.get("score", 0)
    topic_key   = ex_state.get("topic", "")
    level       = s.get("level", "A1")

    is_correct = (chosen == correct)
    if is_correct:
        score += 1
        result_text = f"✅ Правильно!\n_{explanation}_"
    else:
        result_text = f"❌ Не зовсім. Правильно: *{correct}*\n_{explanation}_"

    await q.answer()
    try:
        await q.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await q.message.reply_text(result_text, parse_mode="Markdown")

    if count >= 30:
        # Вправу завершено — показуємо результат
        pct = round(score / 30 * 100)
        if pct >= 70:
            s_upd = mark_topic_event(get_s(user.id), topic_key, "quiz_passed")
            s_upd = mark_topic_event(s_upd, topic_key, "lesson_done")
            upd_s(user.id, {"grammar_topics": s_upd["grammar_topics"]})
        s2 = get_s(user.id)
        events = s2.get("grammar_topics", {}).get(topic_key, {})
        mastery = compute_mastery({
            k: events.get(k, False)
            for k in ["first_contact","lesson_done","quiz_passed","used_in_free","spaced_rep"]
        })
        from grammar_engine import _make_bar
        bar = _make_bar(mastery)
        t   = GRAMMAR_MAP.get(topic_key, {})
        await ctx.bot.send_message(
            chat_id=user.id,
            text=(
                f"🎉 *Вправу завершено!*\n\n"
                f"Правильних: *{score}/30* ({pct}%)\n\n"
                f"{bar} *{mastery}%* — _{t.get('ua', topic_key)}_\n\n"
                f"{'Відмінно! Тема засвоєна 💪' if pct >= 70 else 'Продовжуй — практика дає результат!'}"
            ),
            parse_mode="Markdown"
        )
        upd_s(user.id, {"grammar_exercise_state": {}})
    else:
        # Наступна вправа
        form = "positive" if count < 10 else ("negative" if count < 20 else "question")
        ex_state["count"] = count + 1
        ex_state["score"] = score
        upd_s(user.id, {"grammar_exercise_state": ex_state})
        await _send_grammar_exercise(ctx.bot, user.id, topic_key, level, count + 1, score)


async def _send_grammar_exercise(bot, uid: int, topic_key: str, level: str, count: int, score: int):
    """Генерує і надсилає одну вправу через Claude."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import json as _j

    form = "positive" if count <= 10 else ("negative" if count <= 20 else "question")
    prompt = build_exercise_prompt(topic_key, level, form)

    try:
        cr = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = cr.content[0].text.strip()
        raw = raw[raw.find("{"):raw.rfind("}")+1]
        ex  = _j.loads(raw)

        sentence    = ex.get("sentence", "")
        opts        = ex.get("options", {})
        signal      = ex.get("signal", "")
        correct     = ex.get("correct", "")
        expl        = ex.get("explanation", "")

        # Зберігаємо стан вправи
        upd_s(uid, {"grammar_exercise_state": {
            "topic":       topic_key,
            "correct":     correct,
            "sentence":    sentence,
            "count":       count,
            "score":       score,
            "explanation": expl,
        }})

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"A) {opts.get('A','')}", callback_data="gram_ex_A"),
            InlineKeyboardButton(f"B) {opts.get('B','')}", callback_data="gram_ex_B"),
        ],[
            InlineKeyboardButton(f"C) {opts.get('C','')}", callback_data="gram_ex_C"),
            InlineKeyboardButton(f"D) {opts.get('D','')}", callback_data="gram_ex_D"),
        ]])

        form_icon = "✅" if form == "positive" else ("❌" if form == "negative" else "❓")
        text = f"📝 *Вправа {count}/30* {form_icon}\n\n{sentence}"
        if signal:
            text += f"\n\n🔑 _{signal}_"

        await bot.send_message(
            chat_id=uid,
            text=text,
            parse_mode="Markdown",
            reply_markup=kb
        )
    except Exception as e:
        logger.warning(f"Grammar exercise send error: {e}")
        await bot.send_message(
            chat_id=uid,
            text="⚠️ Помилка генерації вправи. Спробуй пізніше."
        )


async def cmd_grammar_progress(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/grammar — показує граматичний прогрес студента."""
    user = update.effective_user
    s    = get_s(user.id)
    text = format_progress_bars(s)
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_grammar_topic(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/topic [topic_key] — показує таблицю Голіцинського для теми."""
    user  = update.effective_user
    args  = ctx.args or []
    topic = args[0] if args else ""
    if not topic or topic not in GRAMMAR_MAP:
        topics_list = "\n".join(
            f"• `{k}` — {v['ua']}"
            for k, v in sorted(GRAMMAR_MAP.items(), key=lambda x: x[1]["order"])
        )
        await update.message.reply_text(
            f"📚 *Всі граматичні теми:*\n\n{topics_list}\n\nВикористовуй: /topic past_simple",
            parse_mode="Markdown"
        )
        return
    text = format_table_only(topic)
    await update.message.reply_text(text, parse_mode="Markdown")



async def cmd_tutor_me(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/tutor_me — список тем зі статусом, студент обирає кнопкою."""
    user    = update.effective_user
    s       = get_s(user.id)
    grammar = s.get("grammar_topics", {})
    level   = s.get("level", "A1")

    from grammar_engine import compute_mastery, apply_decay, _make_bar

    LEVELS_ORDER_LOCAL = ["A1", "A2", "B1", "B2", "C1", "C2"]
    lvl_idx = LEVELS_ORDER_LOCAL.index(level) if level in LEVELS_ORDER_LOCAL else 0

    CEFR_TO_KEY = {
        "Present Simple": "present_simple",
        "Present Continuous": "present_continuous",
        "Present Perfect": "present_perfect",
        "Present Perfect Continuous": "present_perfect_continuous",
        "Past Simple": "past_simple",
        "Past Continuous": "past_continuous",
        "Past Perfect": "past_perfect",
        "Past Perfect Continuous": "past_perfect_continuous",
        "Future Simple (will)": "future_simple",
        "Future Continuous": "future_continuous",
        "Future Perfect": "future_perfect",
        "Future Perfect Continuous": "future_perfect_continuous",
        "Going to (future plans)": "future_going_to",
        "Zero Conditional": "zero_conditional",
        "First Conditional": "conditional_1",
        "Second Conditional": "conditional_2",
        "Third Conditional": "conditional_3",
        "Wish / If only": "i_wish",
        "Mixed Conditionals": "mixed_conditionals",
        "Passive Voice (Present & Past)": "passive_simple",
        "Passive Voice (Continuous)": "passive_continuous",
        "Reported Speech": "reported_statements",
        "a / an": "article_a_an",
        "The (definite article)": "article_the",
        "Countable nouns with a/an and some": "article_a_an",
        "Uncountable nouns": "noun_plural",
        "Possessive Case ('s / s')": "possessive_case",
        "In, on, at — time": "prepositions_time",
        "Comparative and Superlative Degrees": "adjectives_comparison",
        "As \u2026 as / Than": "as_as",
        "Enough and too": "enough_too",
        "Few, little, a few, a little, much, many": "pronouns_much_many",
        "Adverbs": "adverbs",
        "Used to": "used_to",
        "Non-Continuous Verbs (stative)": "non_continuous_verbs",
        "Imperative Mood": "imperative",
        "Modal Verbs: basic (can/must/should)": "modal_can_could",
        "Modal Verbs: extended (might/may/have to/could)": "modal_may_might",
        "Modal Verbs: advanced (must have / can't have / should have)": "modal_perfect",
        "Gerund + V (basic)": "gerund",
        "Gerund + V (full system)": "gerund_vs_infinitive",
        "Infinitive + V (basic)": "infinitive_to",
        "Infinitive + V (full system)": "prepositional_infinitive_complex",
        "Would rather / sooner / better": "would_rather_had_better",
        "Be used to / Get used to": "be_used_to_get_used_to",
        "Either \u2026 or / Neither \u2026 nor": "neither_nor_either_or",
        "Everyone, everybody / Either, neither of + Prep": "everyone_everybody",
        "Because / Because of": "because_because_of",
        "Despite / In spite of": "despite_in_spite_of",
        "As soon as / As long as": "as_soon_as",
        "Question Tags": "question_tags",
        "Participle 1 (Present Participle)": "participle_1",
        "Participle 2 (Past Participle)": "participle_2",
        "It is said that \u2026": "complex_subject",
        "Complex Object": "complex_object",
        "Complex Subject": "complex_subject",
        "He is said to / He is supposed to": "complex_subject",
        "The Prepositional Infinitive Complex": "prepositional_infinitive_complex",
        "Inversion (emphatic structures)": "inversion",
        "Cleft Sentences": "cleft_sentences",
    }

    topics_data = []
    seen_keys = set()
    for lvl in LEVELS_ORDER_LOCAL[:lvl_idx + 1]:
        for cefr_name in CEFR_GRAMMAR.get(lvl, []):
            key = CEFR_TO_KEY.get(cefr_name)
            if not key or key in seen_keys or key not in GRAMMAR_MAP:
                continue
            seen_keys.add(key)
            t_s = grammar.get(key, {})
            events = {k: t_s.get(k, False)
                      for k in ["first_contact","lesson_done","quiz_passed","used_in_free","spaced_rep"]}
            score = compute_mastery(events)
            score = apply_decay(score, t_s.get("days_since_practice", 0))
            topics_data.append({"key": key, "name": cefr_name, "score": score})

    if not topics_data:
        await update.message.reply_text(
            "\u2139\ufe0f Теми ще не визначені. Спочатку перегляньте кілька відео!",
        )
        return

    topics_data.sort(key=lambda x: (x["score"] == 100, x["score"]))
    top = topics_data[:10]

    header = (
        "\U0001f393 *Репетитор \u2014 обери тему*\n\n"
        f"_{level} \u0440\u0456\u0432\u0435\u043d\u044c \u00b7 {len(topics_data)} \u0442\u0435\u043c \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e_\n\n"
        "\U0001f4cc *\u0420\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u043e\u0432\u0430\u043d\u0456 \u0437\u0430\u0440\u0430\u0437:*\n"
    )
    recs = "\n".join(
        f"{_make_bar(t['score'])} *{t['score']}%* \u2014 {t['name']}"
        for t in top[:3]
    )
    footer = "\n\n\u041e\u0431\u0435\u0440\u0438 \u0442\u0435\u043c\u0443 \u043d\u0438\u0436\u0447\u0435 \U0001f447"

    kb_rows = []
    row = []
    for t in top:
        label = f"{t['score']}% \u00b7 {t['name'][:22]}"
        row.append(InlineKeyboardButton(label, callback_data=f"tutor_topic_{t['key']}"))
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    kb_rows.append([InlineKeyboardButton(
        "\U0001f4cb \u041f\u043e\u043a\u0430\u0437\u0430\u0442\u0438 \u0432\u0441\u0456 \u0442\u0435\u043c\u0438",
        callback_data="tutor_all_topics"
    )])

    await update.message.reply_text(
        header + recs + footer,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_rows)
    )


async def cb_tutor_topic(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент обрав тему \u2192 запускаємо міні-урок."""
    q         = update.callback_query
    user      = q.from_user
    topic_key = q.data.replace("tutor_topic_", "")
    await q.answer()

    if topic_key not in GRAMMAR_MAP:
        await q.message.reply_text("\u26a0\ufe0f Тема не знайдена")
        return

    s     = get_s(user.id)
    level = s.get("level", "A1")

    upd_s(user.id, {
        "grammar_pending_topic":  topic_key,
        "grammar_pending_phrase": "",
    })

    explanation = format_explanation(topic_key, "")
    await q.message.reply_text(explanation, parse_mode="Markdown")
    asyncio.create_task(award_xp(ctx.bot, user.id, "tutor_me_lesson"))

    import asyncio as _aio
    await _aio.sleep(2)
    await _send_grammar_exercise(ctx.bot, user.id, topic_key, level, 1, 0)


async def cb_tutor_all_topics(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показує всі теми зі статусом."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    from grammar_engine import compute_mastery, apply_decay

    grammar = s.get("grammar_topics", {})
    level   = s.get("level", "A1")
    LEVELS_ORDER_LOCAL = ["A1", "A2", "B1", "B2", "C1", "C2"]
    lvl_idx = LEVELS_ORDER_LOCAL.index(level) if level in LEVELS_ORDER_LOCAL else 0

    lines = [f"\U0001f4da *\u0412\u0441\u0456 \u0442\u0435\u043c\u0438 \u2014 {level}*\n"]
    cur_lvl = None
    for lvl in LEVELS_ORDER_LOCAL[:lvl_idx + 1]:
        for cefr_name in CEFR_GRAMMAR.get(lvl, []):
            if cur_lvl != lvl:
                lines.append(f"\n*{lvl}*")
                cur_lvl = lvl
            key = next(
                (k for k, v in GRAMMAR_MAP.items()
                 if k.replace("_"," ") in cefr_name.lower()
                 or cefr_name.lower().startswith(k.replace("_"," "))),
                None
            )
            if not key:
                lines.append(f"\u25ab\ufe0f {cefr_name}")
                continue
            t_s = grammar.get(key, {})
            events = {k: t_s.get(k, False)
                      for k in ["first_contact","lesson_done","quiz_passed","used_in_free","spaced_rep"]}
            score = apply_decay(compute_mastery(events), t_s.get("days_since_practice", 0))
            icon  = "\u2705" if score == 100 else ("\U0001f535" if score > 0 else "\u25ab\ufe0f")
            lines.append(f"{icon} {cefr_name} \u2014 *{score}%*")

    lines.append("\n_/tutor\\_me \u2014 \u043e\u0431\u0435\u0440\u0438 \u0442\u0435\u043c\u0443 \u0456 \u043f\u043e\u0447\u043d\u0438_")

    await q.message.reply_text("\n".join(lines), parse_mode="Markdown")



async def cb_show_6m_plans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показує ціни на 6-місячну підписку зі знижкою 17%."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    has_ref       = bool(s.get("affiliate_ref"))
    basic_m       = float(BASIC_AFFILIATE_PRICE  if has_ref else BASIC_PRICE)
    premium_m     = float(PREMIUM_PRICE_AFF if has_ref else PREMIUM_PRICE_FULL)
    basic_6m      = BASIC_AFF_6M_PRICE    if has_ref else BASIC_6M_PRICE
    premium_6m    = PREMIUM_AFF_6M_PRICE  if has_ref else PREMIUM_FULL_6M_PRICE
    ref_note      = " (партнерська ціна)" if has_ref else ""

    basic_save    = round(basic_m * 6 - basic_6m)
    premium_save  = round(premium_m * 6 - premium_6m)

    kb_rows = []
    if WAYFORPAY_MERCHANT and WAYFORPAY_SECRET:
        basic_6m_url   = wfp_create_payment_url(user.id, "basic_6m",   basic_6m)
        premium_6m_url = wfp_create_payment_url(user.id, "premium_6m", premium_6m)
        kb_rows = [
            [InlineKeyboardButton(
                f"🌟 Premium 6 міс — ${premium_6m:.0f} (економія ${premium_save:.0f})",
                url=premium_6m_url
            )],
            [InlineKeyboardButton(
                f"⚡️ Basic 6 міс — ${basic_6m:.0f} (економія ${basic_save:.0f})",
                url=basic_6m_url
            )],
        ]

    kb_rows.append([InlineKeyboardButton(
        "← Повернутись до місячних планів",
        callback_data="show_monthly_plans"
    )])

    await q.edit_message_text(
        f"🗓 *Підписка на 6 місяців — знижка 17%*{ref_note}\n\n"
        f"🌟 *Premium* — ${premium_6m:.0f} за 6 місяців\n"
        f"    замість ${premium_m * 6:.0f} → *економія ${premium_save:.0f}*\n\n"
        f"⚡️ *Basic* — ${basic_6m:.0f} за 6 місяців\n"
        f"    замість ${basic_m * 6:.0f} → *економія ${basic_save:.0f}*\n\n"
        "_Оплата одноразова. Доступ відкривається одразу на 6 місяців._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_rows) if kb_rows else None
    )


async def cb_show_monthly_plans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Повертає до місячних планів."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    has_ref       = bool(s.get("affiliate_ref"))
    basic_price   = float(BASIC_AFFILIATE_PRICE  if has_ref else BASIC_PRICE)
    premium_price = float(PREMIUM_PRICE_AFF if has_ref else PREMIUM_PRICE_FULL)
    ref_note      = " (партнерська ціна)" if has_ref else ""

    kb_rows = []
    if WAYFORPAY_MERCHANT and WAYFORPAY_SECRET:
        basic_url   = wfp_create_payment_url(user.id, "basic",   basic_price)
        premium_url = wfp_create_payment_url(user.id, "premium", premium_price)
        kb_rows = [
            [InlineKeyboardButton(f"🌟 Premium — ${premium_price:.0f}/міс{ref_note}", url=premium_url)],
            [InlineKeyboardButton(f"⚡️ Basic — ${basic_price:.0f}/міс{ref_note}",    url=basic_url)],
        ]
    kb_rows.append([InlineKeyboardButton(
        "🗓 Показати ціни на 6 місяців (-17%)",
        callback_data="show_6m_plans"
    )])

    await q.edit_message_text(
        "Обери свій план 👇\n\n"
        f"🌟 *Premium — ${premium_price:.0f}/міс*{ref_note}\n"
        "• Все що в Basic + Live sessions з блогером\n\n"
        f"⚡️ *Basic — ${basic_price:.0f}/міс*{ref_note}\n"
        "• Необмежені уроки · Gap analysis · Speaking partner · Roadmap A1→C2\n\n"
        "💡 *Оплати на 6 місяців і зекономь 17%* →",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_rows) if kb_rows else None
    )


async def job_grammar_decay(ctx: ContextTypes.DEFAULT_TYPE):
    """Щоденно о 03:00: оновлює days_since_practice для всіх студентів."""
    from datetime import datetime
    db = load_db()
    today = datetime.now().date()
    updated = 0
    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        grammar = s.get("grammar_topics", {})
        if not grammar: continue
        changed = False
        for topic_key, topic in grammar.items():
            last_str = topic.get("last_practice")
            if not last_str:
                continue
            try:
                last_dt = datetime.fromisoformat(last_str).date()
                days = (today - last_dt).days
                if topic.get("days_since_practice", 0) != days:
                    topic["days_since_practice"] = days
                    changed = True
            except Exception:
                pass
        if changed:
            upd_s(int(uid), {"grammar_topics": grammar})
            updated += 1
    logger.info(f"job_grammar_decay: updated {updated} students")


async def job_grammar_spaced_rep(ctx: ContextTypes.DEFAULT_TYPE):
    """Щоденно о 11:30: нагадує про повторення теми через 7+ днів."""
    from datetime import datetime
    db = load_db()
    today = datetime.now().date()
    sent = 0
    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not s.get("onboarding_done"): continue
        grammar = s.get("grammar_topics", {})
        if not grammar: continue

        # Знайти теми де quiz_passed але spaced_rep ще False і 7+ днів
        for topic_key, topic in grammar.items():
            if not topic.get("quiz_passed"): continue
            if topic.get("spaced_rep"): continue
            days = topic.get("days_since_practice", 0)
            if days < 7: continue
            # Ще не нагадували про spaced rep
            if topic.get("spaced_rep_notified"): continue

            t = GRAMMAR_MAP.get(topic_key, {})
            section = t.get("section", topic_key)
            ua = t.get("ua", "")
            try:
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"🔄 *Час повторити!*\n\n"
                        f"Минуло *{days} днів* з останнього контакту з темою:\n"
                        f"_{section} — {ua}_\n\n"
                        f"Коротке повторення закріпить тему на 100% 💪"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔄 Повторити", callback_data=f"gram_repeat_{topic_key}"),
                        InlineKeyboardButton("⏭ Пізніше",   callback_data="gram_repeat_skip"),
                    ]])
                )
                # Відмічаємо що повідомлення надіслано
                grammar[topic_key]["spaced_rep_notified"] = True
                upd_s(int(uid), {"grammar_topics": grammar})
                sent += 1
                break  # Одне нагадування за раз
            except Exception as e:
                logger.warning(f"job_grammar_spaced_rep uid={uid}: {e}")
    logger.info(f"job_grammar_spaced_rep: sent {sent} reminders")



async def cb_gram_repeat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент натиснув 'Повторити' — запускаємо вправу для spaced rep."""
    q    = update.callback_query
    user = q.from_user
    data = q.data  # gram_repeat_past_simple
    topic_key = data.replace("gram_repeat_", "")
    await q.answer()

    if topic_key not in GRAMMAR_MAP:
        await q.message.reply_text("⚠️ Тема не знайдена")
        return

    s     = get_s(user.id)
    level = s.get("level", "A1")

    # Збережи pending_topic для флоу вправ
    upd_s(user.id, {
        "grammar_pending_topic":  topic_key,
        "grammar_pending_phrase": "",
    })

    # Коротке нагадування таблиці
    table_text = format_table_only(topic_key)
    await q.message.reply_text(table_text, parse_mode="Markdown")

    import asyncio as _aio
    await _aio.sleep(2)
    await _send_grammar_exercise(ctx.bot, user.id, topic_key, level, 1, 0)


async def cb_gram_repeat_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент пропустив spaced rep нагадування."""
    q = update.callback_query
    await q.answer("Добре, нагадаю пізніше 👌")
    try:
        await q.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


async def cb_gram_repeat_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Після успішного повторення — відмічаємо spaced_rep = True."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    ex   = s.get("grammar_exercise_state", {})
    topic_key = ex.get("topic", "")
    score     = ex.get("score", 0)

    if topic_key and score >= 7:  # ≥70% з 10 питань повторення
        s_upd = mark_topic_event(get_s(user.id), topic_key, "spaced_rep")
        upd_s(user.id, {"grammar_topics": s_upd["grammar_topics"]})
        t   = GRAMMAR_MAP.get(topic_key, {})
        events = s_upd.get("grammar_topics", {}).get(topic_key, {})
        mastery = compute_mastery({
            k: events.get(k, False)
            for k in ["first_contact","lesson_done","quiz_passed","used_in_free","spaced_rep"]
        })
        from grammar_engine import _make_bar
        await ctx.bot.send_message(
            chat_id=user.id,
            text=(
                f"🎉 *Повторення завершено!*\n\n"
                f"{_make_bar(mastery)} *{mastery}%*\n"
                f"_{t.get('ua', topic_key)}_\n\n"
                f"{'✅ Тема повністю засвоєна!' if mastery == 100 else '💪 Чудово! Продовжуй у тому ж дусі.'}"
            ),
            parse_mode="Markdown"
        )
    await q.answer()



async def classify_topic_llm(phrase: str) -> str | None:
    """
    Рівень 2 класифікації — Claude Haiku для фраз без regex-матчу.
    Повертає topic_key або None.
    """
    topics_list = ", ".join(GRAMMAR_MAP.keys())
    prompt = (
        f"Classify this English phrase into ONE grammar topic.\n"
        f"Phrase: \"{phrase}\"\n"
        f"Available topics: {topics_list}\n"
        f"Respond ONLY with valid JSON, no markdown:\n"
        f'{{\"topic\": \"past_simple\", \"confidence\": 0.95}}'
    )
    try:
        cr = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}]
        )
        import json as _j
        raw  = cr.content[0].text.strip()
        raw  = raw[raw.find("{"):raw.rfind("}")+1]
        data = _j.loads(raw)
        topic      = data.get("topic", "")
        confidence = float(data.get("confidence", 0))
        if confidence >= 0.75 and topic in GRAMMAR_MAP:
            return topic
    except Exception as e:
        logger.warning(f"classify_topic_llm error: {e}")
    return None



async def _detect_used_in_free(uid: int, transcript: str):
    """
    Аналізує транскрипт монологу студента.
    Якщо знаходить граматичні структури з вивчених тем — відмічає used_in_free.
    """
    s = get_s(uid)
    grammar = s.get("grammar_topics", {})
    if not grammar:
        return

    # Перевіряємо лише теми де є перший контакт але used_in_free ще False
    candidates = [
        k for k, v in grammar.items()
        if v.get("first_contact") and not v.get("used_in_free")
    ]
    if not candidates:
        return

    found = []
    for topic_key in candidates:
        # Швидка перевірка regex — чи є ця структура в транскрипті
        detected = detect_topic(transcript)
        if detected == topic_key:
            found.append(topic_key)
        # Також перевіряємо по сигнальних словах
        t = GRAMMAR_MAP.get(topic_key, {})
        signals = t.get("signals", [])
        transcript_lower = transcript.lower()
        if any(sig.lower() in transcript_lower for sig in signals if len(sig) > 3):
            if topic_key not in found:
                found.append(topic_key)

    if not found:
        return

    # Оновлюємо used_in_free для знайдених тем
    s_fresh = get_s(uid)
    for topic_key in found:
        s_fresh = mark_topic_event(s_fresh, topic_key, "used_in_free")

    upd_s(uid, {"grammar_topics": s_fresh["grammar_topics"]})

    # Повідомляємо студента
    if found:
        t     = GRAMMAR_MAP.get(found[0], {})
        ua    = t.get("ua", found[0])
        events = s_fresh.get("grammar_topics", {}).get(found[0], {})
        mastery = compute_mastery({
            k: events.get(k, False)
            for k in ["first_contact","lesson_done","quiz_passed","used_in_free","spaced_rep"]
        })
        from grammar_engine import _make_bar
        try:
            from telegram import Bot
            bot = Bot(token=BOT_TOKEN)
            await bot.send_message(
                chat_id=uid,
                text=(
                    f"🌟 *Чудово!* Ти використав нову структуру в монолозі!\n\n"
                    f"_{ua}_\n\n"
                    f"{_make_bar(mastery)} *{mastery}%* засвоєно"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"_detect_used_in_free notify error: {e}")


async def cb_duel_challenge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент натиснув ⚔️ Кинути виклик після монологу."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    blogger_name = s.get("affiliate_blogger", "")
    if not blogger_name:
        await q.edit_message_text(
            "⚔️ Виклики доступні тільки студентам блогерів.\n\n"
            "Зареєструйся через реферальне посилання блогера!",
            parse_mode="Markdown"
        )
        return

    db        = load_db()
    opponents = _get_duel_opponents(user.id, blogger_name, db)
    if not opponents:
        await q.edit_message_text(
            "😔 Поки немає інших студентів @{} того ж рівня.\n\n"
            "Виклики з'являться коли приєднається більше студентів! 💪".format(blogger_name),
            parse_mode="Markdown"
        )
        return

    # Показуємо список опонентів
    score    = s.get("last_voice_score", 0)
    topic    = s.get("voice_lesson_data", {}).get("topic", "") or s.get("current_lesson_data", {}).get("topic", "Speaking challenge")
    # Зберігаємо тему і бал для майбутнього виклику
    upd_s(user.id, {"pending_duel_topic": topic, "pending_duel_score": score})

    kb = []
    for opp_uid, opp_name, opp_lvl in opponents:
        kb.append([InlineKeyboardButton(
            f"⚔️ {opp_name} ({opp_lvl})",
            callback_data=f"duel_send_{opp_uid}"
        )])
    kb.append([InlineKeyboardButton("❌ Скасувати", callback_data="duel_cancel")])

    await q.edit_message_text(
        f"⚔️ *Кому кидаємо виклик?*\n\n"
        f"Тема: _{topic}_\n"
        f"Твій бал: *{score}/100*\n\n"
        "Обери опонента 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def cb_duel_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Надсилає виклик конкретному студенту."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    challenged_uid = int(q.data.replace("duel_send_", ""))
    topic          = s.get("pending_duel_topic", "Speaking challenge")
    score          = s.get("pending_duel_score", 0)
    my_name        = s.get("name", user.first_name)

    duel_id = _create_duel(user.id, challenged_uid, topic, score)

    # Повідомлення ініціатору
    # Зберігаємо file_id відео якщо студент надсилав відео
    my_video_id = get_s(user.id).get("pending_video_file_id", "") or get_s(user.id).get("last_video_file_id", "")
    my_voice_id = get_s(user.id).get("last_voice_file_id", "")
    if my_video_id:
        upd_s(user.id, {"duel_my_file_id": my_video_id, "duel_my_type": "video"})
    elif my_voice_id:
        upd_s(user.id, {"duel_my_file_id": my_voice_id, "duel_my_type": "voice"})

    await q.edit_message_text(
        f"⚔️ *Виклик надіслано!*\n\n"
        f"Тема: _{topic}_\n"
        f"Твій бал: *{score}/100*\n\n"
        "Чекаємо відповіді опонента... ⏳",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎙 Ще практикувати", callback_data="fork_choose"),
        ]])
    )

    # Повідомлення опоненту
    ch_s    = get_s(challenged_uid)
    ch_name = ch_s.get("name", "Студент")
    try:
        await ctx.bot.send_message(
            chat_id=challenged_uid,
            text=(
                f"⚔️ *{my_name} кидає тобі виклик!*\n\n"
                f"🎯 Тема: _{topic}_\n\n"
                f"Запиши монолог на цю тему — AI порівняє ваші бали.\n\n"
                f"Приймаєш? 👇"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎙 Прийняти виклик!", callback_data=f"duel_accept_{duel_id}")],
                [InlineKeyboardButton("❌ Відхилити",        callback_data=f"duel_decline_{duel_id}")],
            ])
        )
    except Exception as e:
        logger.warning(f"duel notify error: {e}")


async def cb_duel_accept(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Опонент прийняв виклик."""
    q       = update.callback_query
    user    = q.from_user
    duel_id = q.data.replace("duel_accept_", "")
    duel    = _get_duel(duel_id)
    await q.answer("💪 Виклик прийнято!")

    if not duel or duel.get("status") != "pending":
        await q.edit_message_text("❌ Цей виклик вже неактуальний.")
        return

    _update_duel(duel_id, {"status": "accepted"})
    topic = duel.get("topic", "Speaking challenge")

    # Зберігаємо duel_id щоб handle_voice знав контекст
    upd_s(user.id, {
        "pending_duel_id":    duel_id,
        "duel_topic":         topic,
        "blogger_challenge_active": False,
    })

    await q.edit_message_text(
        f"⚔️ *Виклик прийнято!*\n\n"
        f"🎯 Тема: _{topic}_\n\n"
        "Запиши монолог або відео на цю тему — і ми порівняємо ваші записи!\n\n"
        "👇 Обери формат:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎙 Голосовий монолог", callback_data="remind_record")],
            [InlineKeyboardButton("🎬 Відео монолог",     callback_data="duel_video_mode")],
        ])
    )

    # Сповіщаємо ініціатора
    challenger_uid = int(duel.get("challenger", 0))
    ch_s           = get_s(challenger_uid)
    ch_name        = get_s(user.id).get("name", user.first_name)
    try:
        await ctx.bot.send_message(
            chat_id=challenger_uid,
            text=f"⚔️ *{ch_name} прийняв(ла) твій виклик!*\n\nЧекаємо на їх монолог... ⏳",
            parse_mode="Markdown"
        )
    except Exception:
        pass


async def cb_duel_decline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Опонент відхилив виклик."""
    q       = update.callback_query
    user    = q.from_user
    duel_id = q.data.replace("duel_decline_", "")
    duel    = _get_duel(duel_id)
    await q.answer("Виклик відхилено")

    if not duel:
        await q.edit_message_text("❌ Виклик не знайдено.")
        return

    _update_duel(duel_id, {"status": "declined"})
    await q.edit_message_text("👋 Виклик відхилено. Може наступного разу!")

    challenger_uid = int(duel.get("challenger", 0))
    decliner_name  = get_s(user.id).get("name", user.first_name)
    try:
        await ctx.bot.send_message(
            chat_id=challenger_uid,
            text=f"😔 *{decliner_name}* відхилив(ла) твій виклик.\n\nСпробуй кинути виклик комусь іншому! ⚔️",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚔️ Новий виклик", callback_data="duel_challenge"),
            ]])
        )
    except Exception:
        pass


async def _complete_duel(bot, duel_id: str, challenged_score: int, challenged_uid: int):
    """Завершує дует, надсилає результати обом учасникам."""
    duel = _get_duel(duel_id)
    if not duel or duel.get("status") != "accepted":
        return

    _update_duel(duel_id, {
        "challenged_score": challenged_score,
        "status": "completed",
        "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })

    challenger_uid   = int(duel.get("challenger", 0))
    challenger_score = duel.get("challenger_score", 0)
    topic            = duel.get("topic", "")

    ch_s    = get_s(challenger_uid)
    opp_s   = get_s(challenged_uid)
    ch_name  = ch_s.get("name", "Суперник")
    opp_name = opp_s.get("name", "Суперник")

    # Визначаємо переможця
    if challenger_score > challenged_score:
        winner_name = ch_name
        ch_result   = f"🥇 *{ch_name}* — *{challenger_score}/100*"
        opp_result  = f"🥈 *{opp_name}* — *{challenged_score}/100*"
        ch_msg      = f"🎉 Ти переміг(ла)! *{challenger_score}* vs *{challenged_score}*"
        opp_msg     = f"💪 Ти програв(ла): *{challenged_score}* vs *{challenger_score}*. Реванш?"
    elif challenged_score > challenger_score:
        winner_name = opp_name
        ch_result   = f"🥈 *{ch_name}* — *{challenger_score}/100*"
        opp_result  = f"🥇 *{opp_name}* — *{challenged_score}/100*"
        ch_msg      = f"💪 Ти програв(ла): *{challenger_score}* vs *{challenged_score}*. Реванш?"
        opp_msg     = f"🎉 Ти переміг(ла)! *{challenged_score}* vs *{challenger_score}*"
    else:
        winner_name = "Нічия"
        ch_result   = f"🤝 *{ch_name}* — *{challenger_score}/100*"
        opp_result  = f"🤝 *{opp_name}* — *{challenged_score}/100*"
        ch_msg      = opp_msg = f"🤝 Нічия! По *{challenger_score}* балів кожен"

    result_text = (
        f"⚔️ *Результат дуелі*\n\n"
        f"🎯 Тема: _{topic}_\n\n"
        f"{ch_result}\n"
        f"{opp_result}\n\n"
        f"🏆 Переміг(ла): *{winner_name}*"
    )

    revenge_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Реванш!",       callback_data=f"duel_revenge_{duel_id}")],
        [InlineKeyboardButton("⚔️ Новий виклик",  callback_data="duel_challenge")],
        [InlineKeyboardButton("🎙 Практикувати",  callback_data="fork_choose")],
    ])

    for uid_send, personal_msg in [(challenger_uid, ch_msg), (challenged_uid, opp_msg)]:
        try:
            await bot.send_message(
                chat_id=uid_send,
                text=f"{result_text}\n\n_{personal_msg}_",
                parse_mode="Markdown",
                reply_markup=revenge_kb
            )
        except Exception as e:
            logger.warning(f"duel result notify {uid_send}: {e}")


async def cb_duel_revenge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Реванш — новий дует з тим самим опонентом."""
    q       = update.callback_query
    user    = q.from_user
    duel_id = q.data.replace("duel_revenge_", "")
    duel    = _get_duel(duel_id)
    await q.answer()

    if not duel:
        await q.edit_message_text("❌ Дует не знайдено.")
        return

    # Визначаємо хто ініціює реванш
    my_uid        = str(user.id)
    challenger_id = duel.get("challenger", "")
    challenged_id = duel.get("challenged", "")
    opponent_uid  = int(challenged_id if my_uid == challenger_id else challenger_id)
    topic         = duel.get("topic", "Speaking challenge")
    my_score      = (duel.get("challenger_score",0) if my_uid == challenger_id
                     else duel.get("challenged_score",0)) or 0
    my_name       = get_s(user.id).get("name", user.first_name)

    new_duel_id = _create_duel(user.id, opponent_uid, topic, my_score)

    await q.edit_message_text(
        f"🔄 *Реванш надіслано!*\n\nЧекаємо відповіді... ⏳",
        parse_mode="Markdown"
    )

    opp_s = get_s(opponent_uid)
    try:
        await ctx.bot.send_message(
            chat_id=opponent_uid,
            text=(
                f"🔄 *{my_name} хоче реваншу!*\n\n"
                f"🎯 Тема: _{topic}_\n\n"
                "Приймаєш? 👇"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎙 Прийняти реванш!", callback_data=f"duel_accept_{new_duel_id}")],
                [InlineKeyboardButton("❌ Відхилити",         callback_data=f"duel_decline_{new_duel_id}")],
            ])
        )
    except Exception as e:
        logger.warning(f"duel revenge notify: {e}")


async def cmd_blogger_challenge_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """🏆 Мій челендж — панель блогера з поточним challenge і результатами."""
    user  = update.effective_user
    if not is_blogger(user.id) and not is_admin(user.id):
        await update.message.reply_text("⛔️ Тільки для блогерів.")
        return
    s     = get_s(user.id)
    bname = s.get("blogger_name", user.username or str(user.id))
    ch    = get_blogger_challenge(bname)

    if not ch or not ch.get("active"):
        await update.message.reply_text(
            "🏆 *Твій challenger*\n\n"
            "Зараз немає активного челенджу.\n\n"
            "Запусти новий командою:\n"
            "`/my_challenge Тема для студентів`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎯 Запустити челендж", callback_data="blogger_new_challenge"),
            ]])
        )
        return

    topic       = ch.get("topic", "")
    submissions = sorted(ch.get("submissions", []), key=lambda x: x.get("score", 0), reverse=True)
    total       = len(submissions)
    medals      = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

    lines = [
        f"🏆 *Твій поточний челендж*\n",
        f"📝 _{topic}_\n",
        f"👥 Учасників: *{total}*\n",
    ]
    if submissions:
        lines.append("*Результати:*")
        for i, sub in enumerate(submissions[:5]):
            medal = medals[i] if i < len(medals) else f"{i+1}."
            lines.append(f"{medal} *{sub.get('name','?')}* — {sub.get('score',0)}/100")
    else:
        lines.append("_Поки немає записів — студенти ще не взяли участь_")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Новий челендж", callback_data="blogger_new_challenge")],
            [InlineKeyboardButton("📢 Нагадати студентам", callback_data="blogger_challenge_remind")],
        ])
    )


async def cmd_blogger(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Прихована команда /blogger — вхід для блогерів і адміна."""
    user = update.effective_user

    # Адмін — теж вводить код щоб переглянути панель блогера
    if user.id == ADMIN_ID:
        ADMIN_STATE["waiting"] = "blogger_view"
        await update.message.reply_text(
            "👤 Введи код блогера щоб переглянути його панель 👇\n\n"
            "Або введи @username напряму.",
        )
        return

    # Вже зареєстрований блогер — одразу дашборд з блогерським меню
    if is_blogger(user.id):
        await update.message.reply_text(
            "👤 Панель блогера",
            reply_markup=blogger_main_menu()
        )
        await cmd_my_students(update, ctx)
        return

    # Ще не зареєстрований — просимо код
    upd_s(user.id, {"waiting_blogger_code": True})
    await update.message.reply_text(
        "👋 Вітаємо!\n\n"
        "Введи свій партнерський код щоб отримати доступ до панелі блогера 👇",
    )

async def cmd_test_full_flow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /test_full_flow [basic|premium] — повний тест рекурентного флоу.
    """
    user = update.effective_user

    # Діагностика — показуємо хто звертається
    if not ADMIN_ID:
        await update.message.reply_text(
            f"❌ ADMIN_ID не встановлено в Railway Variables.\n"
            f"Твій ID: `{user.id}`\nДодай `ADMIN_ID={user.id}` в Railway.",
            parse_mode="Markdown"
        )
        return
    if not is_admin(user.id):
        await update.message.reply_text(f"❌ Доступ заборонено. Твій ID: `{user.id}`", parse_mode="Markdown")
        return

    s    = get_s(user.id)
    plan    = (ctx.args[0] if ctx.args else "basic").lower()
    has_ref = bool(s.get("affiliate_ref"))

    try:
        amount = float(BASIC_AFFILIATE_PRICE if plan == "basic" and has_ref
                       else BASIC_PRICE if plan == "basic"
                       else PREMIUM_PRICE_AFF if has_ref
                       else PREMIUM_PRICE_FULL)
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка суми: {e}")
        return

    if not WAYFORPAY_MERCHANT or not WAYFORPAY_SECRET:
        await update.message.reply_text(
            "❌ *WAYFORPAY_MERCHANT* або *WAYFORPAY_SECRET* не встановлено в Railway Variables.",
            parse_mode="Markdown"
        )
        return

    pay_url = wfp_create_payment_url(user.id, plan, amount)
    upd_s(user.id, {
        "test_recurrent_plan":    plan,
        "test_recurrent_amount":  amount,
        "test_recurrent_pending": True,
    })

    await update.message.reply_text(
        f"🧪 *Тест повного рекурентного флоу — {plan.upper()}*\n\n"
        f"*Крок 1:* Оплати тестовою карткою 👇\n"
        f"`4111 1111 1111 1111` / 11/26 / CVV 111\n\n"
        f"*Крок 2:* Через *10 хвилин* бот автоматично спише "
        f"${amount} по recToken без твоєї участі.\n\n"
        f"Стеж за Railway Logs та повідомленнями тут 👀",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f"💳 Крок 1 — Оплатити ${amount}", url=pay_url)
        ]])
    )

    async def _delayed_recurrent(context):
        s2        = get_s(user.id)
        rec_token = s2.get("rec_token", "")

        if not rec_token or not s2.get("test_recurrent_pending"):
            await context.bot.send_message(
                chat_id=user.id,
                text="⚠️ Тест скасовано — recToken не знайдено.\nПереконайся що перший платіж пройшов успішно."
            )
            return

        upd_s(user.id, {"test_recurrent_pending": False})
        await context.bot.send_message(
            chat_id=user.id,
            text=(
                f"⏰ *10 хвилин минуло — запускаю рекурентне списання...*\n\n"
                f"Plan: *{plan}* | Сума: *${amount}*\n"
                f"Token: `{rec_token[:12]}...`"
            ),
            parse_mode="Markdown"
        )

        result = await wfp_charge_by_token(user.id, plan, amount, rec_token)
        status = result.get("transactionStatus", "UNKNOWN")
        reason = result.get("reason", "")

        if status == "Approved":
            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    f"✅ *Рекурентне списання пройшло!*\n\n"
                    f"Order: `{result.get('orderReference','')}`\n\n"
                    f"🎉 Повний флоу протестовано успішно!\n"
                    f"1️⃣ Перший платіж → recToken збережено ✅\n"
                    f"2️⃣ Авто-списання через 10 хв → Approved ✅"
                ),
                parse_mode="Markdown"
            )
            await _process_payment(user.id, plan, str(amount),
                                   result.get("orderReference", ""), rec_token)
        else:
            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    f"❌ *Рекурентне списання не пройшло*\n\n"
                    f"Статус: `{status}`\n"
                    f"Причина: _{reason}_\n\n"
                    "Перевір налаштування токенізації в кабінеті WayForPay."
                ),
                parse_mode="Markdown"
            )

    ctx.application.job_queue.run_once(
        _delayed_recurrent, when=600, name=f"test_rec_{user.id}"
    )


async def cmd_create_blogger_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Адмін: /create_blogger_code @username"""
    if not is_admin(update.effective_user.id):
        return
    args = ctx.args or []
    if not args:
        from telegram import ForceReply
        ADMIN_STATE["waiting"] = "blogger_code"
        await update.message.reply_text(
            "👤 Введи Telegram username блогера 👇\n\nНаприклад: maria або @maria",
            reply_markup=ForceReply(selective=True, input_field_placeholder="@username")
        )
        return
    await _do_create_blogger_code(update, ctx, args[0])


async def cmd_list_blogger_codes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Адмін: /list_blogger_codes — показує всі активні (невикористані) коди блогерів."""
    if not is_admin(update.effective_user.id):
        return
    codes    = get_blogger_codes()
    bloggers = get_registered_bloggers()
    registered_names = set(bloggers.values())

    if not codes:
        await update.message.reply_text("📭 Активних кодів немає. Створи: /create_blogger_code @username")
        return

    lines = ["🔑 *Активні коди блогерів:*\n"]
    for code, name in sorted(codes.items(), key=lambda x: x[1]):
        status = "✅ вже зареєстрований" if name in registered_names else "⏳ очікує реєстрації"
        lines.append(f"@{name} — `{code}`  {status}")

    lines.append(f"\nВсього: *{len(codes)}*")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown"
    )

async def _do_create_blogger_code(update, ctx, raw_username: str):
    import secrets
    username = raw_username.lstrip("@").lower().strip()
    if not username:
        await update.message.reply_text("❌ Введи коректний username.")
        return
    codes    = get_blogger_codes()
    existing = [c for c, n in codes.items() if n == username]
    if existing:
        await update.message.reply_text(
            f"⚠️ Для блогера @{username} вже існує код:\n{existing[0]}\n\nНадішли його блогеру."
        )
        return
    code = f"spk_{username}_{secrets.token_hex(4)}"
    codes[code] = username
    save_blogger_codes(codes)
    asyncio.get_event_loop().run_in_executor(None, gs_sync_bloggers)
    bot_user = (await ctx.bot.get_me()).username
    text = (
        f"✅ Код створено для блогера @{username}\n\n"
        f"🔑 *Секретний код для входу:*\n"
        f"`{code}`\n\n"
        f"_Блогер має написати боту /blogger і вставити код вище цілком_\n\n"
        f"─────────────────────\n"
        f"🔗 Реферальні посилання:\n\n"
        f"▶️ YouTube:\nhttps://t.me/{bot_user}?start=ref_{username}_yt\n\n"
        f"📸 Instagram:\nhttps://t.me/{bot_user}?start=ref_{username}_ig\n\n"
        f"🎵 TikTok:\nhttps://t.me/{bot_user}?start=ref_{username}_tt\n\n"
        f"👤 Facebook:\nhttps://t.me/{bot_user}?start=ref_{username}_fb\n\n"
        f"─────────────────────\n"
        f"Надішли блогеру код та посилання для його платформи."
    )
    await update.message.reply_text(text)

# ── Реєстр активних poll-ів для live сесій ────────────────
# {poll_id: {blogger_uid, correct_idx, question, poll_num}}
_ACTIVE_POLLS: dict = {}


async def handle_poll_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Обробляє відповіді студентів на quiz-поли під час live сесії.
    Зберігає результат і оновлює рейтинг сесії.
    """
    answer   = update.poll_answer
    poll_id  = answer.poll_id
    student  = answer.user
    selected = answer.option_ids  # список обраних індексів

    if poll_id not in _ACTIVE_POLLS:
        return  # не наш poll

    poll_info    = _ACTIVE_POLLS[poll_id]
    blogger_uid  = poll_info["blogger_uid"]
    correct_idx  = poll_info.get("correct_idx")
    poll_num     = poll_info.get("poll_num", 1)

    is_correct = (
        correct_idx is not None and
        len(selected) == 1 and
        selected[0] == correct_idx
    )

    # Оновлюємо результати в профілі блогера
    s     = get_s(blogger_uid)
    polls = s.get("live_session_polls", [])

    # Знаходимо потрібний poll по номеру
    if poll_num - 1 < len(polls):
        p = polls[poll_num - 1]
        answers = p.get("answers", {})
        answers[str(student.id)] = {
            "name":       student.first_name,
            "correct":    is_correct,
            "option_idx": selected[0] if selected else -1,
        }
        p["answers"] = answers
        polls[poll_num - 1] = p
        upd_s(blogger_uid, {"live_session_polls": polls})


async def cb_peek_dismiss(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент відхилив підглядання в Premium."""
    q = update.callback_query
    await q.answer()
    await q.delete_message()


async def job_premium_peek(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Щотижня по неділях: Basic студентам надсилаємо підглядання #2 і #3.
    #2 — speaking buddy (якщо не використовував цього тижня)
    #3 — вебінар блогера (раз на місяць)
    """
    today     = datetime.now()
    is_monday = today.weekday() == 0  # понеділок — підглядання #3
    db        = load_db()

    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not s.get("onboarding_done"): continue
        if is_premium(s) or is_in_trial(s): continue  # тільки Basic

        blogger  = s.get("affiliate_blogger", "")
        has_ref  = bool(s.get("affiliate_ref"))
        price    = PREMIUM_PRICE_AFF if has_ref else PREMIUM_PRICE_FULL
        pay_link = PREMIUM_AFFILIATE_LINK if has_ref else PREMIUM_PAYMENT_LINK
        btag     = f"@{blogger}" if blogger else "блогера"

        kb = []
        if pay_link:
            kb.append([InlineKeyboardButton(f"🌟 Спробувати Premium — ${price}/міс", url=pay_link)])
        kb.append([InlineKeyboardButton("⏭ Пізніше", callback_data="peek_dismiss")])

        # Підглядання #2 — speaking buddy (середа)
        if today.weekday() == 2:
            week_key = f"peek2_{today.strftime('%Y-%W')}"
            if s.get(week_key): continue
            upd_s(int(uid), {week_key: True})
            try:
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        "👥 *Хтось шукає партнера для розмови*\n\n"
                        f"У нас є кілька студентів рівня *{s.get('level','A1')}* "
                        "які хочуть практикувати разом.\n\n"
                        "Speaking Buddy — жива практика з партнером. "
                        "Знайди партнера і практикуй живу розмову щотижня 🗣"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            except Exception as e:
                logger.warning(f"peek2 error {uid}: {e}")

        # Підглядання #3 — вебінар (перший понеділок місяця)
        elif is_monday and today.day <= 7:
            month_key = f"peek3_{today.strftime('%Y-%m')}"
            if s.get(month_key): continue
            upd_s(int(uid), {month_key: True})
            try:
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"🎥 *{btag} провів вебінар цього місяця*\n\n"
                        "Premium студенти практикували живу розмову, "
                        "отримали фідбек і відповіді на питання.\n\n"
                        "Наступний вебінар — вже скоро. "
                        "Хочеш бути там? 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            except Exception as e:
                logger.warning(f"peek3 error {uid}: {e}")


async def cmd_weekly_question(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/weekly_question — блогер записує відео-питання тижня."""
    user = update.effective_user
    if not is_blogger(user.id):
        await update.message.reply_text("Тільки для блогерів.")
        return
    upd_s(user.id, {"waiting_wq_video": True})
    await update.message.reply_text(
        "🎬 *Запиши відео-питання тижня!*\n\n"
        "Надішли коротке відео (до 60 сек) — постав питання студентам англійською.\n\n"
        "💡 *Приклад:* «Tell me about your weekend in 30 seconds!»\n\n"
        "Відео буде автоматично розіслано всім студентам у *неділю о 9:00* 🕘",
        parse_mode="Markdown"
    )


async def handle_blogger_wq_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Обробляє відео від блогера як питання тижня. Повертає True якщо оброблено."""
    user = update.effective_user
    s    = get_s(user.id)
    if not s.get("waiting_wq_video"):
        return False

    video = update.message.video or update.message.video_note
    if not video:
        return False

    upd_s(user.id, {"waiting_wq_video": False})
    bname    = s.get("blogger_name", "")
    file_id  = video.file_id
    caption  = update.message.caption or ""
    week_key = datetime.now().strftime("%Y-%W")

    db = load_db()
    db.setdefault("_weekly_questions", {})[bname] = {
        "file_id":    file_id,
        "file_type":  "video_note" if update.message.video_note else "video",
        "caption":    caption,
        "week":       week_key,
        "date":       datetime.now().strftime("%Y-%m-%d"),
        "blogger":    bname,
        "blogger_uid": user.id,
        "sent":       False,  # буде розіслано в неділю о 9:00
    }
    save_db(db)

    # Підраховуємо студентів
    student_count = sum(
        1 for uid, st in db.items()
        if isinstance(st, dict) and st.get("affiliate_blogger") == bname
        and st.get("onboarding_done")
    )

    await update.message.reply_text(
        "✅ *Відео-питання збережено!*\n\n"
        f"👥 Отримають: *{student_count}* студентів\n"
        f"📅 Розсилка: *неділя о 9:00*\n\n"
        "Переглянути: /preview_welcome\n"
        "Замінити: надішли нове відео після /weekly_question",
        parse_mode="Markdown"
    )
    return True


async def cb_wq_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент натиснув 'Записати відповідь' на питання тижня."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    bname    = q.data.replace("wq_answer_", "")
    db       = load_db()
    question = db.get("_weekly_questions", {}).get(bname, {}).get("question", "Розкажи про себе")
    upd_s(user.id, {"waiting_wq_voice": True, "wq_question": question, "wq_blogger": bname})
    await q.edit_message_text(
        f"🎙 *Записуй відповідь!*\n\n_{question}_\n\n"
        "Надішли голосове — 30-60 секунд англійською 👇",
        parse_mode="Markdown"
    )


async def cmd_feedback_queue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/feedback_queue — черга записів студентів що чекають фідбеку від блогера."""
    user = update.effective_user
    if not is_blogger(user.id):
        return
    s            = get_s(user.id)
    blogger_name = s.get("blogger_name", "")
    db           = load_db()
    queue        = [r for r in db.get("_feedback_queue", [])
                    if isinstance(r, dict)
                    and r.get("blogger") == blogger_name
                    and not r.get("done")]

    if not queue:
        await update.message.reply_text(
            "✅ Черга порожня — нових запитів немає.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"🎙 *Запити на фідбек: {len(queue)}*\n\n"
        "Відправляю записи студентів 👇",
        parse_mode="Markdown"
    )

    for i, req in enumerate(queue[:10]):  # макс 10 за раз
        try:
            await ctx.bot.send_voice(
                chat_id=user.id,
                voice=req["file_id"],
                caption=(
                    f"#{i+1} | 👤 {req['student_name']}  {req['student_level']}\n"
                    f"📝 {req.get('topic','')[:80]}\n"
                    f"📅 {req['date']}"
                ),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "💬 Відповісти",
                        callback_data=f"fb_reply_{req['student_uid']}"
                    ),
                    InlineKeyboardButton(
                        "✅ Пропустити",
                        callback_data=f"fb_skip_{req['student_uid']}_{req['date']}"
                    ),
                ]])
            )
        except Exception as e:
            logger.warning(f"feedback_queue send error: {e}")


async def cb_fb_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Блогер натиснув 'Відповісти' — просимо надіслати голосове."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    student_uid = int(q.data.split("_")[-1])
    upd_s(user.id, {
        "pending_fb_reply_to": student_uid,
        "pending_fb_reply_ts": datetime.now().isoformat(),
    })
    await q.edit_message_caption(
        caption=(q.message.caption or "") + "\n\n⏳ _Надішли голосове — я перешлю студенту_",
        parse_mode="Markdown"
    )


async def cb_fb_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Блогер пропускає запит."""
    q    = update.callback_query
    await q.answer("Пропущено")
    parts       = q.data.split("_")
    student_uid = int(parts[2])
    date        = parts[3]
    db          = load_db()
    for r in db.get("_feedback_queue", []):
        if isinstance(r, dict) and r.get("student_uid") == student_uid and r.get("date") == date:
            r["done"] = True
    save_db(db)
    await q.edit_message_caption(caption="⏭ Пропущено")


async def handle_blogger_feedback_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Блогер надіслав голосовий — пересилаємо студенту як фідбек."""
    user = update.effective_user
    if not is_blogger(user.id):
        return
    s           = get_s(user.id)
    student_uid = s.get("pending_fb_reply_to")
    if not student_uid:
        return  # не в режимі відповіді — звичайний voice

    voice   = update.message.voice
    if not voice:
        return

    st      = get_s(student_uid)
    st_name = st.get("name", f"Студент {str(student_uid)[-4:]}")

    try:
        await ctx.bot.send_voice(
            chat_id=student_uid,
            voice=voice.file_id,
            caption=(
                f"🎙 *Фідбек від @{user.username or user.first_name}*\n\n"
                "Слухай уважно і запиши що будеш покращувати 📝"
            ),
            parse_mode="Markdown"
        )
        # Позначаємо як виконано
        db    = load_db()
        today = datetime.now().strftime("%Y-%m-%d")
        for r in db.get("_feedback_queue", []):
            if isinstance(r, dict) and r.get("student_uid") == student_uid and not r.get("done"):
                r["done"] = True
        save_db(db)
        upd_s(user.id, {"pending_fb_reply_to": None})
        await update.message.reply_text(
            f"✅ Фідбек надіслано *{st_name}*!",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {e}")


async def cmd_set_welcome(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/set_welcome — блогер надсилає відео-привітання для нових рефералів."""
    user = update.effective_user
    if not is_blogger(user.id):
        return
    upd_s(user.id, {"waiting_welcome_video": True})
    await update.message.reply_text(
        "🎬 *Запиши відео-привітання для нових студентів!*\n\n"
        "Надішли коротке відео (до 60 сек) — воно автоматично надійде кожному "
        "хто зареєструється через твоє посилання.\n\n"
        "💡 Скажи хто ти, чому варто вчитись з SpeakChain і що чекає на студентів.",
        parse_mode="Markdown"
    )


async def cmd_preview_welcome(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/preview_welcome — переглянути збережене привітання."""
    user = update.effective_user
    if not is_blogger(user.id):
        return
    s        = get_s(user.id)
    file_id  = s.get("welcome_video_file_id") or s.get("welcome_voice_file_id")
    ftype    = s.get("welcome_file_type", "video")
    if not file_id:
        await update.message.reply_text(
            "❌ Привітання ще не записано. Використай /set_welcome",
        )
        return
    if ftype == "video":
        await ctx.bot.send_video(chat_id=user.id, video=file_id,
                                  caption="🎬 Твоє поточне привітання для нових студентів")
    else:
        await ctx.bot.send_voice(chat_id=user.id, voice=file_id,
                                  caption="🎙 Твоє поточне привітання для нових студентів")


async def handle_blogger_welcome_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Обробляє відео/голос від блогера як привітання. Повертає True якщо оброблено."""
    user = update.effective_user
    s    = get_s(user.id)
    if not s.get("waiting_welcome_video"):
        return False
    upd_s(user.id, {"waiting_welcome_video": False})

    video = update.message.video or update.message.video_note
    voice = update.message.voice
    if video:
        file_id = video.file_id
        ftype   = "video"
    elif voice:
        file_id = voice.file_id
        ftype   = "voice"
    else:
        return False

    upd_s(user.id, {
        "welcome_video_file_id" if ftype == "video" else "welcome_voice_file_id": file_id,
        "welcome_file_type": ftype,
    })
    await update.message.reply_text(
        "✅ *Привітання збережено!*\n\n"
        "Кожен новий студент через твоє реферальне посилання "
        "автоматично отримає це відео.\n\n"
        "Переглянути: /preview_welcome\n"
        "Замінити: /set_welcome",
        parse_mode="Markdown"
    )
    return True


async def cmd_best_of_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /best_of_month — студент обирає свій найкращий запис місяця.
    Показує останні 5 записів і пропонує обрати.
    """
    user = update.effective_user
    s    = get_s(user.id)

    timeline = s.get("voice_timeline", [])
    if not timeline:
        await update.message.reply_text(
            "🎙 У тебе ще немає збережених записів.\n\n"
            "Зроби кілька монологів — і зможеш обрати найкращий!",
        )
        return

    await update.message.reply_text(
        "🏆 *Моє найкраще аудіо місяця*\n\n"
        "Надсилаю твої останні записи — послухай і обери той де найкраще звучиш 👇",
        parse_mode="Markdown"
    )

    recent = timeline[-5:]  # останні 5
    for i, entry in enumerate(reversed(recent)):
        try:
            await ctx.bot.send_voice(
                chat_id=user.id,
                voice=entry.get("file_id", ""),
                caption=f"Запис #{len(recent)-i} · {entry.get('date','')}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "⭐️ Це мій найкращий!",
                        callback_data=f"best_pick_{entry.get('date','')}"
                    )
                ]])
            )
        except Exception as e:
            logger.warning(f"best_of_month send {user.id}: {e}")


async def cb_best_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент обрав свій найкращий запис місяця."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer("⭐️ Відмічено!")

    date = q.data.replace("best_pick_", "")
    month = datetime.now().strftime("%Y-%m")

    # Знаходимо запис по даті
    timeline  = s.get("voice_timeline", [])
    best_entry = next((e for e in timeline if e.get("date") == date), None)
    if not best_entry:
        await q.edit_message_caption(caption="⭐️ Відмічено як найкращий!")
        return

    # Зберігаємо в профілі
    best_history = s.get("best_of_month", {})
    best_history[month] = {
        "file_id": best_entry.get("file_id",""),
        "date":    date,
        "lesson":  best_entry.get("lesson_num", 0),
        "picked":  datetime.now().strftime("%Y-%m-%d"),
    }
    upd_s(user.id, {"best_of_month": best_history})

    # Пропонуємо поділитись
    blogger  = s.get("affiliate_blogger","")
    btag     = f"@{blogger}" if blogger else "спільноті"
    await q.edit_message_caption(
        caption=(
            f"⭐️ *Твій найкращий запис {month}!*\n\n"
            "Поділись з друзями — покажи свій прогрес 🚀"
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📹 Поділитись в Community", callback_data="share_voice_confirm"),
            InlineKeyboardButton("📱 В соцмережі",            callback_data="share_socials"),
        ]])
    )


async def cmd_setup_live_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/setup_live_group — адмін прив'язує Premium групу за посиланням або ID."""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔️ Тільки для адміна.")
        return

    args = ctx.args or []

    if not args:
        await update.message.reply_text(
            "👥 *Підключення Premium групи*\n\n"
            "Надішли команду з посиланням на групу або її ID:\n\n"
            "📎 *За посиланням (рекомендовано):*\n"
            "`/setup_live_group https://t.me/+aBcDeFgHiJk`\n\n"
            "📎 *За посиланням з @:*\n"
            "`/setup_live_group https://t.me/mygroupname`\n\n"
            "📎 *Для конкретного блогера:*\n"
            "`/setup_live_group https://t.me/+aBcDeFgHiJk @maria_english`\n\n"
            "_Бот має бути адміном тієї групи_",
            parse_mode="Markdown"
        )
        return

    link_or_id = args[0]
    blogger_username = args[1].lstrip("@").lower() if len(args) > 1 else None

    # Визначаємо group_id
    group_id = None

    # Варіант 1: числовий ID
    if link_or_id.lstrip("-").isdigit():
        group_id = int(link_or_id)

    # Варіант 2: посилання t.me/+hash або t.me/joinchat/hash
    elif "t.me/+" in link_or_id or "t.me/joinchat/" in link_or_id:
        await update.message.reply_text(
            "⏳ Перевіряю посилання...",
        )
        try:
            # Для invite-посилань беремо chat через export_chat_invite_link
            # Спробуємо get_chat з посиланням напряму
            chat = await ctx.bot.get_chat(link_or_id)
            group_id = chat.id
        except Exception:
            # Якщо не вдалось — просимо додати бота і надіслати /myid в групі
            await update.message.reply_text(
                "❌ Не вдалось знайти групу за посиланням.\n\n"
                "*Зроби так:*\n"
                "1. Додай бота в групу як адміна\n"
                "2. Напиши `/myid` прямо в тій групі\n"
                "3. Скопіюй ID і виконай:\n"
                "`/setup_live_group -1001234567890`",
                parse_mode="Markdown"
            )
            return

    # Варіант 3: публічна група @username або t.me/username
    elif link_or_id.startswith("@") or "t.me/" in link_or_id:
        username = link_or_id.replace("https://t.me/","").replace("http://t.me/","").replace("@","")
        try:
            chat = await ctx.bot.get_chat(f"@{username}")
            group_id = chat.id
        except Exception as e:
            await update.message.reply_text(
                f"❌ Не вдалось знайти групу: {e}\n\n"
                "_Переконайся що бот є адміном цієї групи_"
            )
            return
    else:
        await update.message.reply_text(
            "❌ Не розпізнав посилання.\n\n"
            "Надішли у форматі:\n"
            "`/setup_live_group https://t.me/+aBcDeFgHiJk`",
            parse_mode="Markdown"
        )
        return

    # Перевіряємо чи бот є адміном
    try:
        chat   = await ctx.bot.get_chat(group_id)
        member = await ctx.bot.get_chat_member(group_id, ctx.bot.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text(
                "❌ Бот не є адміном цієї групи.\n\n"
                "Зайди в групу → Адміністратори → Додати → знайди бота → підтвердь."
            )
            return
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка доступу до групи: {e}")
        return

    # Зберігаємо
    if blogger_username:
        bloggers = get_registered_bloggers()
        blogger_uid = next(
            (int(uid) for uid, name in bloggers.items()
             if name.lower() == blogger_username), None
        )
        if not blogger_uid:
            await update.message.reply_text(
                f"❌ Блогер @{blogger_username} не знайдений.\n"
                f"Спочатку зареєструй через /create_blogger_code"
            )
            return
        upd_s(blogger_uid, {"live_group_id": group_id, "live_group_title": chat.title})
        await update.message.reply_text(
            f"✅ *Групу підключено до блогера!*\n\n"
            f"👥 Група: *{chat.title}*\n"
            f"👤 Блогер: *@{blogger_username}*\n\n"
            f"Premium студенти @{blogger_username} автоматично отримають запрошення при оплаті.",
            parse_mode="Markdown"
        )
    else:
        db = load_db()
        db["_premium_group"] = {"group_id": group_id, "title": chat.title}
        save_db(db)
        await update.message.reply_text(
            f"✅ *Загальна Premium група підключена!*\n\n"
            f"👥 Група: *{chat.title}*\n\n"
            f"Всі Premium студенти автоматично отримають запрошення при оплаті.",
            parse_mode="Markdown"
        )

    try:
        await ctx.bot.send_message(
            chat_id=group_id,
            text="✅ Групу підключено до SpeakChain! Premium студенти будуть приєднуватись автоматично 🎉",
        )
    except Exception:
        pass


async def cmd_live_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/live_start [тема] — відкриває live сесію."""
    user = update.effective_user
    if not is_blogger(user.id): return
    s        = get_s(user.id)
    group_id = s.get("live_group_id")
    if not group_id:
        await update.message.reply_text("⚠️ Спочатку: /setup_live_group")
        return

    topic_raw  = " ".join(ctx.args) if ctx.args else "Розмовна практика"

    # Підтримуємо формат: "Тема | граматична тема для зарахування"
    if "|" in topic_raw:
        parts        = topic_raw.split("|", 1)
        topic        = parts[0].strip()
        grammar_tag  = parts[1].strip()
    else:
        topic        = topic_raw
        grammar_tag  = ""

    now = datetime.now().strftime("%H:%M")
    upd_s(user.id, {
        "live_session_active":       True,
        "live_session_start":        datetime.now().strftime("%Y-%m-%d %H:%M"),
        "live_session_topic":        topic,
        "live_session_grammar_tag":  grammar_tag,
        "live_session_polls":        [],
    })
    try:
        msg = await ctx.bot.send_message(
            chat_id=group_id,
            text=(
                f"🔴 *LIVE сесія починається!*\n\n"
                f"📌 Тема: *{topic}*\n"
                f"⏰ {now}\n\n"
                "Блогер запускає відеодзвінок у групі.\n"
                "Тести надсилатимуться прямо тут! 🎯"
            ),
            parse_mode="Markdown"
        )
        await ctx.bot.pin_message(chat_id=group_id, message_id=msg.message_id)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Помилка: {e}")
        return

    grammar_hint = (
        f"\n📚 Тема для зарахування: *{grammar_tag}*"
        if grammar_tag else
        "\n💡 Щоб зарахувати тему студентам:\n`/live_start Назва | Граматична тема`\nНаприклад: `/live_start Кафе | Past Simple`"
    )
    await update.message.reply_text(
        f"✅ *Сесія розпочата!* Тема: *{topic}*{grammar_hint}\n\n"
        "Запускай відеодзвінок у групі.\n\n"
        "Надіслати тест:\n"
        "`/quiz Питання | Варіант1 | Варіант2 | Варіант3 | Варіант4 | 1`\n"
        "_де 1 — індекс правильної відповіді (0, 1, 2, 3)_\n\n"
        "Завершити: `/live_end`",
        parse_mode="Markdown"
    )


async def cmd_live_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/quiz Питання | В1 | В2 | В3 | В4 | 0 — клікабельні кнопки з цифрами."""
    user = update.effective_user
    if not is_blogger(user.id): return
    s        = get_s(user.id)
    group_id = s.get("live_group_id")
    if not s.get("live_session_active"):
        await update.message.reply_text("⚠️ Немає активної сесії. /live_start"); return
    if not group_id: return

    raw   = update.message.text.split(" ", 1)[1].strip() if " " in update.message.text else ""
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 3:
        await update.message.reply_text(
            "Формат: `/quiz Питання | В1 | В2 | В3 | В4 | 0`\n"
            "_де 0 — індекс правильної відповіді_\n\n"
            "Скинути тест: `/quiz_reset`",
            parse_mode="Markdown"); return

    question = parts[0]
    try:    correct_idx = int(parts[-1]); options = parts[1:-1]
    except: correct_idx = None;          options = parts[1:]

    polls    = s.get("live_session_polls", [])
    poll_num = len(polls) + 1
    nums     = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"]
    kb       = [[InlineKeyboardButton(f"{nums[i]} {opt}",
                   callback_data=f"lq_{user.id}_{poll_num}_{i}")]
                for i, opt in enumerate(options[:8])]
    try:
        msg = await ctx.bot.send_message(
            chat_id=group_id,
            text=f"❓ *Тест #{poll_num}*\n\n*{question}*\n\n_Клікни на свій варіант 👇_",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        entry = {"question":question,"options":options,"correct_idx":correct_idx,
                 "message_id":msg.message_id,"poll_num":poll_num,
                 "time":datetime.now().strftime("%H:%M"),"answers":{}}
        polls.append(entry)
        _ACTIVE_POLLS[f"lq_{user.id}_{poll_num}"] = {
            "blogger_uid":user.id,"correct_idx":correct_idx,
            "question":question,"poll_num":poll_num,
            "msg_id":msg.message_id,"group_id":group_id}
        upd_s(user.id, {"live_session_polls": polls})
        await update.message.reply_text(f"✅ Тест #{poll_num} надіслано!")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def cb_live_quiz_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент натиснув кнопку відповіді."""
    q    = update.callback_query
    user = q.from_user
    await q.answer("✅ Відповідь прийнято!")
    parts      = q.data.split("_")
    blogger_id = int(parts[1]); poll_num = int(parts[2]); opt_idx = int(parts[3])
    poll_key   = f"lq_{blogger_id}_{poll_num}"
    if poll_key not in _ACTIVE_POLLS: return
    info        = _ACTIVE_POLLS[poll_key]
    correct_idx = info.get("correct_idx")
    is_correct  = correct_idx is not None and opt_idx == correct_idx
    s           = get_s(blogger_id)
    polls       = s.get("live_session_polls", [])
    if poll_num - 1 < len(polls):
        polls[poll_num-1].setdefault("answers",{})[str(user.id)] = {
            "name":user.first_name,"correct":is_correct,"option":opt_idx}
        upd_s(blogger_id, {"live_session_polls": polls})
    # Оновлюємо кнопки з лічильником
    info_poll = polls[poll_num-1] if poll_num-1 < len(polls) else {}
    options   = info_poll.get("options",[])
    answers   = info_poll.get("answers",{})
    nums      = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"]
    counts    = {}
    for a in answers.values(): counts[a["option"]] = counts.get(a["option"],0)+1
    new_kb = [[InlineKeyboardButton(
        f"{nums[i]} {opt}" + (f"  ·{counts[i]}" if counts.get(i) else ""),
        callback_data=f"lq_{blogger_id}_{poll_num}_{i}"
    )] for i, opt in enumerate(options[:8])]
    try: await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(new_kb))
    except Exception: pass


async def cmd_quiz_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/quiz_reset — скидає активний тест."""
    user = update.effective_user
    if not is_blogger(user.id): return
    s        = get_s(user.id)
    group_id = s.get("live_group_id")
    stale    = [k for k in list(_ACTIVE_POLLS.keys()) if k.startswith(f"lq_{user.id}_")]
    for k in stale:
        info = _ACTIVE_POLLS.pop(k)
        try:
            await ctx.bot.edit_message_reply_markup(
                chat_id=group_id, message_id=info.get("msg_id"), reply_markup=None)
        except Exception: pass
    await update.message.reply_text(
        f"🔄 {'Тест скинуто.' if stale else 'Немає активних тестів.'} Можеш надсилати новий /quiz")



async def cmd_live_end(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/live_end — завершує сесію і надсилає підсумки в групу."""
    user = update.effective_user
    if not is_blogger(user.id): return
    s = get_s(user.id)
    if not s.get("live_session_active"):
        await update.message.reply_text("Немає активної сесії.")
        return

    group_id = s.get("live_group_id")
    topic    = s.get("live_session_topic", "")
    polls    = s.get("live_session_polls", [])
    start    = s.get("live_session_start", "")
    duration = ""
    if start:
        try:
            st   = datetime.strptime(start, "%Y-%m-%d %H:%M")
            mins = int((datetime.now() - st).total_seconds() / 60)
            duration = f"⏱ *{mins} хв*  "
        except Exception:
            pass

    # Очищаємо реєстр активних poll-ів (безпечно — список створюється спочатку)
    stale = [k for k, v in _ACTIVE_POLLS.items() if v.get("blogger_uid") == user.id]
    for pid in stale:
        _ACTIVE_POLLS.pop(pid, None)

    # Рахуємо рейтинг студентів за відповідями
    student_scores: dict = {}
    for poll in polls:
        for uid_str, ans in poll.get("answers", {}).items():
            if uid_str not in student_scores:
                student_scores[uid_str] = {"name": ans.get("name", "?"), "correct": 0, "total": 0}
            student_scores[uid_str]["total"]   += 1
            student_scores[uid_str]["correct"] += 1 if ans.get("correct") else 0

    ranked   = sorted(student_scores.items(), key=lambda x: x[1]["correct"], reverse=True)
    medals   = ["🥇", "🥈", "🥉"]
    lb_lines = []
    for i, (uid_str, data) in enumerate(ranked):
        medal = medals[i] if i < 3 else f"{i+1}."
        pct   = int(data["correct"] / data["total"] * 100) if data["total"] else 0
        lb_lines.append(f"{medal} {data['name']}  ✅{data['correct']}/{data['total']}  ({pct}%)")

    grammar_tag = s.get("live_session_grammar_tag", "")

    upd_s(user.id, {
        "live_session_active":  False,
        "live_sessions_total":  s.get("live_sessions_total", 0) + 1,
    })

    # ── XP тільки тим хто відповідав + зарахування теми ────
    for uid_str, data in student_scores.items():
        try:
            student_uid = int(uid_str)
        except ValueError:
            continue
        st      = get_s(student_uid)
        pct     = int(data["correct"] / data["total"] * 100) if data["total"] else 0
        updates = {"xp_total": st.get("xp_total", 0) + 15}

        # Зараховуємо граматичну тему якщо ≥50% правильних
        topic_credited = False
        if grammar_tag and pct >= 50:
            mastered = st.get("mastered_grammar", [])
            if grammar_tag not in mastered:
                updates["mastered_grammar"] = mastered + [grammar_tag]
                topic_credited = True

        # Зберігаємо сесію в історії студента
        history = st.get("live_sessions_attended", [])
        history.append({"date": datetime.now().strftime("%Y-%m-%d"),
                        "topic": topic, "grammar": grammar_tag,
                        "score": f"{data['correct']}/{data['total']}", "pct": pct})
        updates["live_sessions_attended"] = history[-50:]
        upd_s(student_uid, updates)

        # Повідомлення студенту
        credit_line = (
            f"\n\n📚 *Тема зарахована:* {grammar_tag} ✅" if topic_credited else
            (f"\n\n💪 Потрібно 50%+ для зарахування *{grammar_tag}*" if grammar_tag and pct < 50 else "")
        )
        try:
            await ctx.bot.send_message(
                chat_id=student_uid,
                text=(f"🏁 *Live заняття завершено!*\n\n"
                      f"📌 {topic}\n"
                      f"Твій результат: *{data['correct']}/{data['total']}* ({pct}%)\n"
                      f"+15 XP нараховано 🎯{credit_line}"),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"live_end student notify {uid_str}: {e}")

    lb_text = ""
    if lb_lines:
        lb_text = "\n\n🏆 *Результати тестів:*\n" + "\n".join(lb_lines[:10])

    grammar_line = f"\n📚 Тема зарахована студентам: *{grammar_tag}* (≥50%)" if grammar_tag else ""
    summary = (
        f"🏁 *Сесія завершена!*\n\n"
        f"📌 {topic}\n"
        f"{duration}📊 Тестів: *{len(polls)}*{grammar_line}"
        f"{lb_text}\n\n"
        f"Дякуємо! Продовжуй практику: @SpeakChain_bot 🚀"
    )
    try:
        await ctx.bot.send_message(chat_id=group_id, text=summary, parse_mode="Markdown")
        await ctx.bot.unpin_all_chat_messages(chat_id=group_id)
    except Exception as e:
        logger.warning(f"live_end group msg error: {e}")

    await update.message.reply_text(
        f"✅ *Сесія завершена!* {duration}Тестів: *{len(polls)}*\n\n"
        + (("🏆 *Рейтинг:*\n" + "\n".join(lb_lines[:10])) if lb_lines else "_Жодних відповідей не зафіксовано_")
        + (f"\n\n📚 Тема *{grammar_tag}* зарахована студентам з ≥50%" if grammar_tag else "")
        + f"\n\n+15 XP учасникам нараховано 🎉",
        parse_mode="Markdown"
    )


async def cmd_get_group_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Надсилає ID поточного чату."""
    chat = update.effective_chat
    await update.message.reply_text(
        f"📋 ID цього чату:\n`{chat.id}`\n\nНазва: *{chat.title or 'особистий чат'}*",
        parse_mode="Markdown"
    )


async def cmd_invite_premium_to_group(bot, student_uid: int, blogger_uid: int):
    """Надсилає студенту посилання в Premium групу блогера."""
    s_blogger = get_s(blogger_uid)
    group_id  = s_blogger.get("live_group_id")
    # Fallback — адмінська Premium-група якщо блогер не підключив свою
    if not group_id:
        group_id = os.environ.get("PREMIUM_GROUP_ID", "")
    if not group_id: return
    try:
        invite = await bot.create_chat_invite_link(
            chat_id      = group_id,
            member_limit = 1,
            name         = f"student_{student_uid}"
        )
        blogger_name = get_blogger_name(blogger_uid)
        await bot.send_message(
            chat_id=student_uid,
            text=(
                f"🎉 *Вітаємо в Premium!*\n\n"
                f"Ти отримуєш доступ до live занять з *@{blogger_name}*.\n\n"
                f"👥 Приєднуйся до Premium групи:\n{invite.invite_link}\n\n"
                "_Там проходять живі заняття з тестами в реальному часі_ 🔴"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"invite_premium_to_group error uid={student_uid}: {e}")




async def cmd_post_rating(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/post_rating — адмін публікує рейтинг вручну прямо зараз."""
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("📊 Публікую рейтинг...")
    await job_group_rating(ctx)
    await update.message.reply_text("✅ Рейтинг опубліковано в групах!")

async def cmd_admin_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/reply <uid> <текст> — адмін відповідає на питання студента."""
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text("Використання: /reply <uid> <текст відповіді>")
        return
    try:
        target_uid = int(ctx.args[0])
        answer     = " ".join(ctx.args[1:])
    except ValueError:
        await update.message.reply_text("❌ Невірний uid")
        return

    # Зберігаємо відповідь в історію
    s       = get_s(target_uid)
    history = s.get("admin_questions", [])
    if history:
        history[-1]["a"] = answer   # відповідь до останнього питання
        upd_s(target_uid, {"admin_questions": history})

    try:
        await ctx.bot.send_message(
            chat_id=target_uid,
            text=(
                f"📬 *Відповідь від адміна:*\n\n{answer}"
            ),
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"✅ Відповідь надіслано студенту {target_uid}")
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {e}")

async def cmd_admin_payouts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Адмін: /admin_payouts [YYYY-MM] — таблиця виплат блогерам."""
    if not is_admin(update.effective_user.id):
        return

    args = ctx.args or []
    year_month = args[0] if args else datetime.now().strftime("%Y-%m")

    payouts = calculate_monthly_payouts(year_month)

    if not payouts:
        await update.message.reply_text(
            f"💸 *Виплати за {year_month}*\n\nНемає даних за цей місяць.",
            parse_mode="Markdown"
        )
        return

    # Групуємо по блогеру
    by_blogger: dict = {}
    for p in payouts:
        b = p["blogger"]
        by_blogger.setdefault(b, []).append(p)

    lines = [f"💸 *Виплати блогерам — {year_month}*\n"]
    kb    = []

    for blogger, entries in sorted(by_blogger.items()):
        total      = sum(e["commission"] for e in entries)
        paid       = sum(e["commission"] for e in entries if e.get("paid"))
        unpaid     = total - paid
        paid_count = sum(1 for e in entries if e.get("paid"))

        status = "✅" if paid_count == len(entries) else ("⚠️" if paid_count > 0 else "⏳")
        lines.append(
            f"{status} *@{blogger}*\n"
            f"  👥 {len(entries)} студ.  💰 Разом: ${total:.2f}  "
            f"{'✅ Виплачено' if unpaid == 0 else f'⏳ До виплати: ${unpaid:.2f}'}"
        )

        if unpaid > 0:
            kb.append([InlineKeyboardButton(
                f"✅ Виплатити @{blogger} ${unpaid:.2f}",
                callback_data=f"pay_blogger_{blogger}_{year_month}"
            )])

    total_all   = sum(e["commission"] for e in payouts)
    unpaid_all  = sum(e["commission"] for e in payouts if not e.get("paid"))
    lines.append(f"\n📊 Всього: *${total_all:.2f}*  |  До виплати: *${unpaid_all:.2f}*")

    kb.append([InlineKeyboardButton("📊 Оновити Google Sheets", callback_data=f"payouts_gs_sync_{year_month}")])

    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb) if kb else None
    )


async def cb_pay_blogger(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Адмін: відмічає виплату блогеру як здійснену."""
    q    = update.callback_query
    user = q.from_user
    if not is_admin(user.id):
        await q.answer("Тільки для адміна")
        return

    await q.answer()
    parts      = q.data.split("_")  # pay_blogger_NAME_YYYY-MM
    year_month = parts[-1]
    blogger    = "_".join(parts[2:-1])

    db      = load_db()
    payouts = db.get("_payouts", [])
    total   = 0.0
    today   = datetime.now().strftime("%Y-%m-%d")

    for p in payouts:
        if p.get("blogger") == blogger and p.get("month") == year_month and not p.get("paid"):
            p["paid"]      = True
            p["paid_date"] = today
            total         += p["commission"]

    db["_payouts"] = payouts
    save_db(db)
    asyncio.create_task(asyncio.to_thread(gs_sync_payouts))

    # Сповіщаємо блогера
    bloggers = get_registered_bloggers()
    blogger_uid = next((int(uid) for uid, name in bloggers.items() if name == blogger), None)
    if blogger_uid:
        try:
            await ctx.bot.send_message(
                chat_id=blogger_uid,
                text=(
                    f"💰 *Виплата отримана!*\n\n"
                    f"За {year_month}: *${total:.2f}*\n"
                    f"Дата: {today}\n\n"
                    "Дякуємо за роботу! 🙌"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Blogger payout notify error: {e}")

    await q.edit_message_text(
        f"✅ Виплата @{blogger} ${total:.2f} за {year_month} відмічена!\n"
        f"Блогер отримав сповіщення. Google Sheets оновлено.",
        parse_mode="Markdown"
    )


async def cb_payouts_gs_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Синхронізує виплати в Google Sheets."""
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("⛔️ Доступ заборонено", show_alert=True)
        return
    await q.answer("Синхронізую...")
    await asyncio.to_thread(gs_sync_payouts)
    await q.edit_message_text("✅ Google Sheets оновлено!", parse_mode="Markdown")


async def cb_view_blogger_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Натискання на ім'я блогера в списку → показує його дашборд."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    if not is_admin(user.id):
        return
    name = q.data.replace("view_blogger_", "")
    ctx.args = [name]
    await cmd_view_blogger(q, ctx)

async def handle_blogger_code_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Перехоплює введення секретного коду блогера."""
    user = update.effective_user
    s    = get_s(user.id)
    if not s.get("waiting_blogger_code"):
        return False

    raw   = update.message.text.strip()
    codes = get_blogger_codes()

    # Шукаємо точний збіг, або з префіксом spk_, або частковий збіг в кінці
    code = None
    if raw in codes:
        code = raw
    elif f"spk_{raw}" in codes:
        code = f"spk_{raw}"
    else:
        # Шукаємо код який закінчується на введений текст (на випадок часткового вводу)
        for k in codes:
            if k.endswith(raw) or k == raw:
                code = k
                break

    if not code:
        await update.message.reply_text(
            "❌ Невірний код. Спробуй ще раз або зверніться до адміністратора.\n\n"
            "_Перевір що скопіював код повністю_ 👆"
        )
        return True

    name = codes[code]

    # ── Адмін — переглядає панель блогера БЕЗ реєстрації ──
    if is_admin(user.id):
        upd_s(user.id, {"waiting_blogger_code": False})
        await update.message.reply_text(
            f"👤 *Панель блогера: @{name}*\n\n"
            "_Ти переглядаєш як адмін. Твої права незмінні._",
            parse_mode="Markdown"
        )
        # Показуємо дашборд через /view_blogger
        ctx.args = [name]
        await cmd_view_blogger(update, ctx)
        return True

    # ── Блогер — реєструємо ──
    bloggers = get_registered_bloggers()
    bloggers[str(user.id)] = name
    save_registered_bloggers(bloggers)

    # Видаляємо використаний код
    del codes[code]
    save_blogger_codes(codes)

    upd_s(user.id, {"waiting_blogger_code": False, "is_blogger": True, "blogger_name": name})

    # Сповіщаємо адміна
    if ADMIN_ID:
        try:
            await ctx.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"✅ *Новий блогер зареєструвався!*\n\n"
                    f"Ім'я: *@{name}*\n"
                    f"Telegram: @{user.username or '—'}\n"
                    f"ID: `{user.id}`"
                ),
                parse_mode="Markdown"
            )
        except Exception:
            pass

    await update.message.reply_text(
        f"✅ *Вітаємо, @{name}!*\n\n"
        "Ти тепер партнер SpeakChain 🎉\n\n"
        "Твоя панель відкрита 👇",
        parse_mode="Markdown"
    )
    gs_sync_bloggers()
    await cmd_my_students(update, ctx)
    return True

async def cmd_view_blogger(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Адмін: /view_blogger NAME — переглянути дашборд блогера."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Доступ заборонено.")
        return
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Використання: `/view_blogger NAME`\n\nНаприклад: `/view_blogger maria`",
            parse_mode="Markdown"
        )
        return

    name = args[0].lower()
    db   = load_db()

    # Знаходимо студентів цього блогера
    students = []
    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        blogger = s.get("affiliate_blogger","").lower()
        ref     = s.get("affiliate_ref","").lower()
        if blogger == name or ref.startswith(name):
            students.append((uid, s))

    if not students:
        await update.message.reply_text(f"😔 Студентів блогера *{name}* не знайдено.", parse_mode="Markdown")
        return

    total   = len(students)
    active  = sum(1 for _,s in students
                  if s.get("last_date","") >= datetime.now().strftime("%Y-%m-01"))
    premium = sum(1 for _,s in students if is_premium(s) and s.get("plan") == "premium")
    basic   = sum(1 for _,s in students if is_premium(s) and s.get("plan","basic") == "basic")
    trial   = sum(1 for _,s in students if is_in_trial(s))
    revenue = (basic * float(BASIC_AFFILIATE_PRICE) + premium * float(PREMIUM_AFFILIATE_PRICE)) * 0.25

    lines = [
        f"🔍 *Дашборд блогера: {name}*\n",
        f"👥 Всього студентів: *{total}*",
        f"✅ Активних цього місяця: *{active}*",
        f"⚡️ Basic: *{basic}*",
        f"⭐️ Premium: *{premium}*",
        f"🎁 На тріалі: *{trial}*",
        f"💰 Дохід блогера: *~${revenue:.0f}* (25%)\n",
        "─────────────────────",
    ]

    # Всі студенти з деталями
    sorted_students = sorted(students, key=lambda x: len(x[1].get("done_lessons",[])), reverse=True)
    for uid, s in sorted_students[:15]:
        lvl    = LEVEL_NAMES.get(s.get("level",""),"—")
        done   = len(s.get("done_lessons",[]))
        streak = s.get("streak_days",0)
        prem   = "⭐️" if is_premium(s) else ("🎁" if is_in_trial(s) else "  ")
        name_s = s.get("name","?")
        reg    = s.get("registered_at","")[:10]
        platform = s.get("affiliate_platform","")
        lines.append(f"{prem} *{name_s}* (`{uid}`)\n  {lvl} · {done} ур. · 🔥{streak} · {platform} · з {reg}")

    if total > 15:
        lines.append(f"\n_...і ще {total-15} студентів_")

    await update.message.reply_text(chr(10).join(lines), parse_mode="Markdown")

async def cmd_my_students(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Дашборд блогера — його студенти, прогрес, дохід."""
    user = update.effective_user

    # Адмін — тільки через /view_blogger NAME
    if user.id == ADMIN_ID:
        await update.message.reply_text(
            "👤 Для перегляду панелі блогера використай:\n\n"
            "`/view_blogger @username`\n\n"
            "Наприклад: `/view_blogger @maria_english`",
            parse_mode="Markdown"
        )
        return

    # Перевіряємо реєстрацію блогера
    if not is_blogger(user.id):
        await update.message.reply_text(
            "⛔️ Доступ тільки для партнерів SpeakChain.\n\nНапиши /blogger щоб увійти."
        )
        return

    db       = load_db()
    username = get_blogger_name(user.id) or (user.username or str(user.id)).lower()
    students = []
    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) == "quiz_cache": continue
        blogger = s.get("affiliate_blogger","").lower()
        ref     = s.get("affiliate_ref","").lower()
        if blogger == username or ref.startswith(username):
            students.append((uid, s))

    if not students:
        await update.message.reply_text(
            "👥 Твоїх студентів поки немає.\n\n"
            "Поділись своїм реферальним посиланням щоб студенти приходили саме до тебе.",
            parse_mode="Markdown"
        )
        return

    total   = len(students)
    active  = sum(1 for _,s in students if s.get("last_date","") >= (datetime.now().strftime("%Y-%m-%d")[:8] + "01"))
    basic   = sum(1 for _,s in students if is_premium(s) and s.get("plan","basic") == "basic")
    premium = sum(1 for _,s in students if is_premium(s) and s.get("plan") == "premium")
    revenue = (basic * float(BASIC_AFFILIATE_PRICE) + premium * float(PREMIUM_AFFILIATE_PRICE)) * 0.25

    # ── Топ-5 студентів ─────────────────────────────────────────────
    top5 = sorted(students, key=lambda x: len(x[1].get("done_lessons",[])), reverse=True)[:5]

    # ── Кнопки ──────────────────────────────────────────────────────
    kb = []

    if WEBAPP_URL:
        blogger_data = {
            "mode":     "blogger",
            "name":     username,
            "total":    total,
            "active":   active,
            "basic":    basic,
            "premium":  premium,
            "revenue":  round(revenue),
            "top_students": [
                {
                    "name":   s.get("name","?"),
                    "level":  LEVEL_NAMES.get(s.get("level",""), s.get("level","")),
                    "done":   len(s.get("done_lessons",[])),
                    "streak": s.get("streak_days",0),
                    "plan":   s.get("plan","basic"),
                }
                for _, s in top5
            ],
        }
        webapp_url = WEBAPP_URL.replace("player.html","blogger.html") +                      "?d=" + urllib.parse.quote(json.dumps(blogger_data, ensure_ascii=False))
        kb.append([InlineKeyboardButton(
            "📊 Відкрити дашборд", web_app=WebAppInfo(url=webapp_url)
        )])

    kb += [
        [
            InlineKeyboardButton("🔗 Моє посилання",   callback_data="blogger_my_link"),
            InlineKeyboardButton("🎬 Відео-посилання", callback_data="blogger_gen_video_link"),
        ],
        [
            InlineKeyboardButton("🔴 Live заняття",    callback_data="blogger_live_menu"),
            InlineKeyboardButton("🎯 Питання тижня",   callback_data="blogger_weekly_q"),
        ],
        [InlineKeyboardButton("💬 Черга фідбеків",     callback_data="blogger_feedback_q")],
        [InlineKeyboardButton("📈 Повна статистика",   callback_data="blogger_full_stats")],
    ]

    # ── Текстова картка ──────────────────────────────────────────────
    prem_pct  = round(premium / total * 100) if total else 0
    top_lines = []
    for _, s in top5:
        icon  = "⭐️" if s.get("plan") == "premium" else "·"
        name  = s.get("name","?")
        lvl   = LEVEL_NAMES.get(s.get("level",""), "")
        done  = len(s.get("done_lessons",[]))
        streak= s.get("streak_days",0)
        top_lines.append(f"  {icon} {name} — {lvl} · {done} ур · 🔥{streak}")

    msg = (
        f"👤 *Панель блогера — @{username}*\n\n"
        f"👥 Студентів: *{total}*   ✅ Активних: *{active}*\n"
        f"⚡️ Basic: *{basic}*   ⭐️ Premium: *{premium}* ({prem_pct}%)\n"
        f"💰 Дохід цього місяця: *~${revenue:.0f}*\n\n"
        f"*Топ студентів:*\n" + "\n".join(top_lines) +
        "\n\n_/voice_comment ID — надіслати голосовий коментар_"
    )

    msg_obj = update.message or (update.callback_query and update.callback_query.message)
    await msg_obj.reply_text(msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb))
async def cmd_voice_comment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Блогер надсилає голосовий коментар студенту."""
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Використання: `/voice_comment STUDENT_ID`\n\n"
            "Потім надішли голосове повідомлення — воно піде студенту від тебе.",
            parse_mode="Markdown"
        )
        return
    student_id = args[0]
    upd_s(update.effective_user.id, {"pending_voice_comment_to": student_id})
    await update.message.reply_text(
        f"🎙 Надішли голосове — воно піде студенту `{student_id}` від тебе 👇",
        parse_mode="Markdown"
    )

async def handle_blogger_voice_comment(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Перехоплює голосове від блогера і пересилає студенту."""
    user = update.effective_user
    s    = get_s(user.id)
    target_id = s.get("pending_voice_comment_to","")
    if not target_id:
        return False

    upd_s(user.id, {"pending_voice_comment_to": ""})
    voice = update.message.voice
    if not voice:
        return False

    try:
        target_s   = get_s(int(target_id))
        target_name = target_s.get("name","студент")
        blogger_name = user.first_name or user.username or "Вчитель"

        await ctx.bot.send_voice(
            chat_id=int(target_id),
            voice=voice.file_id,
            caption=f"🎙 *{blogger_name}* залишив коментар до твого монологу 👆",
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"✅ Коментар надіслано студенту {target_name}!")
    except Exception as e:
        logger.warning(f"Voice comment error: {e}")
        await update.message.reply_text("😔 Не вдалось надіслати. Перевір ID студента.")
    return True

async def cb_blogger_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    if q.data == "blogger_my_link":
        bot_username = (await ctx.bot.get_me()).username
        username = user.username or str(user.id)
        await q.edit_message_text(
            f"🔗 *Твої реферальні посилання:*\n\n"
            f"▶️ YouTube:\n`https://t.me/{bot_username}?start=ref_{username}_yt`\n\n"
            f"📸 Instagram:\n`https://t.me/{bot_username}?start=ref_{username}_ig`\n\n"
            f"🎵 TikTok:\n`https://t.me/{bot_username}?start=ref_{username}_tt`",
            parse_mode="Markdown"
        )
    elif q.data == "blogger_live_menu":
        s2       = get_s(user.id)
        group_id = s2.get("live_group_id")
        active   = s2.get("live_session_active", False)
        total    = s2.get("live_sessions_total", 0)
        if group_id:
            group_title = s2.get("live_group_title", str(group_id))
            status = "🔴 Активна зараз" if active else f"✅ Готова · Сесій всього: {total}"
            text   = (
                f"🎓 *Live заняття*\n\n"
                f"Група: *{group_title}*\n"
                f"Статус: {status}\n\n"
                "Команди:\n"
                "`/live_start [тема]` — почати\n"
                "`/quiz Питання | Варіант1 | Варіант2 | ... | 0`\n"
                "`/live_end` — завершити"
            )
        else:
            text = (
                "🎓 *Live заняття*\n\n"
                "Premium групу ще не налаштовано.\n\n"
                "Як налаштувати:\n"
                "1️⃣ Створи Telegram групу\n"
                "2️⃣ Додай бота як адміна\n"
                "3️⃣ Надішли `/get_id` в групі\n"
                "4️⃣ Виконай `/setup_live_group <ID>`"
            )
        await q.edit_message_text(text, parse_mode="Markdown")

    elif q.data == "blogger_gen_video_link":
        upd_s(user.id, {"waiting_blogger_video_url": True})
        await q.edit_message_text(
            "🎬 *Посилання для відео*\n\n"
            "Вставте YouTube посилання на відео яке хочете надіслати студентам — "
            "система згенерує готове реферальне посилання для поширення:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Скасувати", callback_data="blogger_cancel_video")
            ]])
        )

    elif q.data == "blogger_cancel_video":
        upd_s(user.id, {"waiting_blogger_video_url": False})
        await q.edit_message_text(
            "Скасовано. Повертайся в кабінет через /blogger",
            parse_mode="Markdown"
        )

    elif q.data == "blogger_full_stats":
        # Безпечна заміна _get_message_update()
        class _FMsg:
            async def reply_text(self_i, *a, **kw):
                await ctx.bot.send_message(chat_id=user.id, *a, **kw)
        class _FUpd:
            effective_user = user
            message = _FMsg()
            callback_query = None
        await cmd_my_students(_FUpd(), ctx)

    elif q.data == "blogger_weekly_q":
        s2    = get_s(user.id)
        bname = s2.get("blogger_name", "")
        db    = load_db()
        last_q = db.get("_weekly_questions", {}).get(bname, {})
        last_date = last_q.get("date", "")
        last_text = last_q.get("question", "")
        week_key  = datetime.now().strftime("%Y-%W")
        sent_this_week = last_q.get("week") == week_key

        status = (
            f"✅ Надіслано цього тижня:\n_{last_text}_"
            if sent_this_week else
            f"⚠️ Цього тижня ще не надіслано\n_(останнє: {last_date or 'ніколи'})_"
        )
        await q.edit_message_text(
            f"🎯 *Питання тижня*\n\n"
            f"{status}\n\n"
            "📝 *Як надіслати:*\n"
            "Напиши команду з питанням:\n"
            "`/weekly_question Розкажи за 30 секунд — що ти робив учора?`\n\n"
            "💡 *Поради:*\n"
            "• Питання має бути коротким і конкретним\n"
            "• Ідеальна відповідь — 30-60 секунд\n"
            "• Теми: повсякденне життя, думки, досвід\n"
            "• Студенти записують голосову — AI оцінює вимову\n\n"
            "_Надсилай питання раз на тиждень — студенти отримають і запишуть відповідь_ 🎙",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="blogger_back")
            ]])
        )

    elif q.data == "blogger_feedback_q":
        class _FMsg2:
            async def reply_text(self_i, *a, **kw):
                await ctx.bot.send_message(chat_id=user.id, *a, **kw)
        class _FUpd2:
            effective_user = user
            message = _FMsg2()
            callback_query = None
        await cmd_feedback_queue(_FUpd2(), ctx)

    elif q.data == "blogger_back":
        class _FMsg3:
            async def reply_text(self_i, *a, **kw):
                await ctx.bot.send_message(chat_id=user.id, *a, **kw)
        class _FUpd3:
            effective_user = user
            message = _FMsg3()
            callback_query = None
        await cmd_blogger(_FUpd3(), ctx)

async def cmd_admin_refs(update, ctx):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Доступ заборонено.")
        return
    db   = load_db()
    refs = {}
    for uid, s in db.items():
        if not isinstance(s, dict): continue
        ref      = s.get("affiliate_ref","")
        if not ref: continue
        blogger  = s.get("affiliate_blogger", ref)
        platform = s.get("affiliate_platform", "Unknown")
        refs.setdefault((blogger, platform), []).append({
            "name":    s.get("name","?"),
            "premium": is_premium(s),
            "level":   s.get("level","?"),
            "lessons": len(s.get("done_lessons",[])),
        })
    if not refs:
        await update.message.reply_text("Реферальних переходів поки немає.")
        return
    platform_emoji = {"YouTube":"▶️","Instagram":"📸","TikTok":"🎵",
                      "Facebook":"👤","Twitter/X":"🐦","Unknown":"🌐"}
    lines = ["🔗 *Звіт по рефералах*", ""]
    for (blogger, platform), students in sorted(refs.items(), key=lambda x:-len(x[1])):
        paid    = sum(1 for st in students if st["premium"])
        revenue = paid * float(PREMIUM_AFFILIATE_PRICE)
        emoji   = platform_emoji.get(platform, "🌐")
        lines.append(
            f"{emoji} *{blogger}* ({platform})\n"
            f"  👥 {len(students)} студ.  ⭐️ {paid} платних  💰 ~${revenue:.0f}"
        )
        for st in students[:3]:
            mark = "⭐️" if st["premium"] else "·"
            lines.append(f"  {mark} {st['name']} ({st['level']}, {st['lessons']} ур.)")
        if len(students) > 3:
            lines.append(f"  _...і ще {len(students)-3}_")
        lines.append("")
    await update.message.reply_text(
        chr(10).join(lines), parse_mode="Markdown"
    )

# ── Sub-admin management commands ─────────────────────
async def cmd_add_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/add_admin USER_ID — супер-адмін додає sub-admin."""
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Тільки для головного адміна.")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Використання: `/add_admin USER_ID`\n\nНаприклад: `/add_admin 123456789`",
            parse_mode="Markdown"
        )
        return
    try:
        new_uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ USER_ID має бути числом.")
        return
    if new_uid == ADMIN_ID:
        await update.message.reply_text("Це і є головний адмін 😄")
        return
    add_sub_admin(new_uid)
    s = get_s(new_uid)
    name = s.get("name") or f"ID {new_uid}"
    await update.message.reply_text(
        f"✅ *{name}* (`{new_uid}`) отримав права sub-admin!\n\n"
        "_Діє до перезапуску. Для постійного — додай в `SUB_ADMIN_IDS` в Railway Variables._",
        parse_mode="Markdown"
    )
    try:
        await ctx.bot.send_message(
            chat_id=new_uid,
            text="🔑 Тебе призначено sub-admin SpeakChain!\n\nВикористай /admin для доступу до панелі."
        )
    except Exception:
        pass


async def cmd_remove_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/remove_admin USER_ID — відкликати права sub-admin."""
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Тільки для головного адміна.")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Використання: `/remove_admin USER_ID`",
            parse_mode="Markdown"
        )
        return
    try:
        rem_uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ USER_ID має бути числом.")
        return
    remove_sub_admin(rem_uid)
    await update.message.reply_text(f"✅ Права sub-admin для `{rem_uid}` відкликані.", parse_mode="Markdown")


async def cmd_list_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/list_admins — показати всіх адмінів."""
    if not is_admin(update.effective_user.id):
        return
    sub = get_sub_admins()
    lines = [f"👑 *Супер-адмін:* `{ADMIN_ID}`"]
    if sub:
        lines.append(f"\n🔑 *Sub-admins ({len(sub)}):*")
        for uid in sorted(sub):
            s = get_s(uid)
            name = s.get("name") or f"ID {uid}"
            lines.append(f"• *{name}* (`{uid}`)")
    else:
        lines.append("\n_Sub-admins не призначено._")
    lines.append(f"\n\nДодати: `/add_admin USER_ID`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Фрази подяки при продовженні підписки ────────────
RENEWAL_PHRASES = [
    "Дякуємо, що обираєте йти до мети з нами! 🙌",
    "Вибір докладати зусиль щодня — це вже найважливіший крок! 💪",
    "Ще один місяць до вільної англійської — разом у нас все вийде! 🚀",
    "Дякуємо, що обрали розвиток! Продовжуємо разом 🔥",
    "Дякуємо за довіру — йдемо до нових результатів разом! ⭐️",
    "Ти вже на шляху — і ми раді бути поруч! 🎯",
    "Ще один місяць практики — ще на крок ближче до мети! 🏆",
    "Твій вибір продовжити — найкраще що можна зробити для своєї англійської. А може, і для всього життя в цілому? 📈",
    "Раді бачити Вас знову! Цінуйте власну оплату — зробіть цей місяць продуктивним 💡",
    "Послідовність — ключ до успіху. Оплативши, практикуйте — це Ваше все! 🗝",
    "Дякуємо! Кожен місяць практики — це сотні нових фраз і впевненість у собі 🎙",
    "З поверненням! Мова вивчається саме так — крок за кроком, місяць за місяцем 🌱",
    "Рухаймося далі до нових вершин 🏔",
]


async def activate_plan(bot, user_id: int, plan: str, days: int, is_renewal: bool = False):
    """Активує план — викликається вручну і автоматично через WayForPay webhook."""
    from datetime import timedelta
    until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    s     = get_s(user_id)
    ref   = s.get("affiliate_ref", "")

    upd_s(user_id, {
        "premium_until":  until,
        "plan":           plan,
        "plan_activated": datetime.now().strftime("%Y-%m-%d"),
    }, force=True)  # платіж — зберігаємо одразу в PostgreSQL

    asyncio.create_task(gs_log_payment(user_id, days, until, ref, plan))
    asyncio.create_task(gs_sync_student(user_id))
    asyncio.create_task(asyncio.to_thread(gs_sync_bloggers))

    plan_name = "Basic ⚡️" if plan == "basic" else "Premium 🌟"
    s2        = get_s(user_id)
    name      = s2.get("name", "")
    name_line = f"*{name}*, " if name else ""
    lessons   = len(s2.get("done_lessons", []))
    streak    = s2.get("streak", 0)
    phrases   = len(s2.get("mined_sentences", []))

    if plan == "premium":
        plan_perks = (
            "🌟 *Що відкрито:*\n"
            "• AI-розбір кожного монологу\n"
            "• Speaking challenges від блогера\n"
            "• Доступ до Premium групи\n"
            "• Необмежені уроки і граматика"
        )
    else:
        plan_perks = (
            "⚡️ *Що відкрито:*\n"
            "• AI-оцінка вимови\n"
            "• Персональний плеєр\n"
            "• Уроки і граматика\n"
            "• SRS нагадування фраз"
        )

    try:
        if is_renewal:
            import random as _rnd
            phrase = _rnd.choice(RENEWAL_PHRASES)
            progress_line = ""
            if lessons > 0 or streak > 0:
                progress_line = (
                    f"\n📊 *Твій прогрес:*\n"
                    f"🎙 Уроків: *{lessons}* | 📚 Фраз: *{phrases}* | 🔥 Стрік: *{streak} дн.*\n"
                )
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"🎉 {name_line}{phrase}\n\n"
                    f"Твій план *{plan_name}* продовжено до *{until}* ✅"
                    f"{progress_line}\n\n"
                    "Продовжуй практику 👇"
                ),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
        else:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"🎉 {name_line}ласкаво просимо до SpeakChain!\n\n"
                    f"Твій план *{plan_name}* активовано до *{until}* ✅\n\n"
                    f"{plan_perks}\n\n"
                    "Натисни кнопку нижче і починай 👇"
                ),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
    except Exception as e:
        logger.warning(f"activate_plan notify error: {e}")

async def cmd_setpremium(update, ctx):
    if not is_admin(update.effective_user.id):
        return
    args = ctx.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Використання:\n"
            "/setpremium USER_ID DAYS — Premium\n"
            "/setpremium USER_ID DAYS basic — Basic"
        )
        return
    try:
        target_uid = int(args[0])
        days       = int(args[1])
        plan       = args[2].lower() if len(args) > 2 else "premium"
        if plan not in ("basic", "premium"):
            plan = "premium"
    except ValueError:
        await update.message.reply_text("❌ USER_ID і DAYS мають бути числами.")
        return

    await activate_plan(ctx.bot, target_uid, plan, days)
    s    = get_s(target_uid)
    name = s.get("name", str(target_uid))
    await update.message.reply_text(
        f"✅ {plan.capitalize()} активовано для {name} ({target_uid}) на {days} днів."
    )


async def cb_admin(update, ctx):
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    if not is_admin(user.id):
        return
    db = load_db()

    if q.data == "adm_basic_list":
        basic_users = [(uid, s) for uid, s in db.items()
                       if isinstance(s, dict) and is_premium(s) and s.get("plan","basic") == "basic"]
        if not basic_users:
            await q.edit_message_text("⚡️ Активних Basic поки немає.")
            return
        lines = [f"⚡️ *Basic студенти ({len(basic_users)}):*", ""]
        for uid, s in sorted(basic_users, key=lambda x: x[1].get("premium_until","")):
            ref = f" 🔗{s.get('affiliate_ref','')}" if s.get("affiliate_ref") else ""
            lines.append(
                f"• *{s.get('name','?')}* (`{uid}`){ref}\n"
                f"  {LEVEL_NAMES.get(s.get('level',''),'?')} · "
                f"{len(s.get('done_lessons',[]))} ур. · до {s.get('premium_until','?')}"
            )
        text = chr(10).join(lines)
        if len(text) > 4000:
            text = text[:4000] + f"\n\n_...список обрізано, всього {len(basic_users)} студентів_"
        await q.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="adm_back")
            ]])
        )

    elif q.data == "adm_premium_list":
        premium_users = [(uid, s) for uid, s in db.items()
                         if isinstance(s, dict) and is_premium(s)]
        if not premium_users:
            await q.edit_message_text("⭐️ Активних Premium поки немає.")
            return
        lines = [f"⭐️ *Premium студенти ({len(premium_users)}):*", ""]
        for uid, s in sorted(premium_users, key=lambda x: x[1].get("premium_until","")):
            ref  = f" 🔗{s.get('affiliate_ref','')}" if s.get("affiliate_ref") else ""
            lines.append(
                f"• *{s.get('name','?')}* (`{uid}`){ref}\n"
                f"  {LEVEL_NAMES.get(s.get('level',''),'?')} · "
                f"{len(s.get('done_lessons',[]))} ур. · до {s.get('premium_until','?')}"
            )
        text = chr(10).join(lines)
        if len(text) > 4000:
            text = text[:4000] + f"\n\n_...список обрізано, всього {len(premium_users)} студентів_"
        await q.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="adm_back")
            ]])
        )

    elif q.data == "adm_post_rating":
        await q.message.reply_text("📊 Публікую рейтинг в групах...")
        await job_group_rating(ctx)
        await q.message.reply_text("✅ Рейтинг опубліковано!")
        return

    elif q.data == "adm_setup_group":
        # Показуємо поточний стан і інструкцію
        db = load_db()
        pg = db.get("_premium_group", {})
        group_id    = pg.get("group_id", "")
        group_title = pg.get("title", "")

        # Збираємо групи блогерів
        bloggers = get_registered_bloggers()
        blogger_groups = []
        for uid, name in bloggers.items():
            bs = get_s(int(uid))
            gid = bs.get("live_group_id")
            gtitle = bs.get("live_group_title", "")
            if gid:
                blogger_groups.append(f"  @{name} → `{gid}` ({gtitle})")

        status = ""
        if group_id:
            status = f"✅ *Загальна Premium група:*\n  `{group_id}` ({group_title})\n\n"
        else:
            status = "❌ *Загальна Premium група не підключена*\n\n"

        if blogger_groups:
            status += "*Групи блогерів:*\n" + "\n".join(blogger_groups) + "\n\n"

        await q.message.reply_text(
            f"👥 *Налаштування Premium групи*\n\n"
            f"{status}"
            f"*Як підключити:*\n"
            f"1. Створи групу в Telegram\n"
            f"2. Додай бота як адміна групи\n"
            f"3. Напиши /myid прямо в тій групі — бот покаже ID\n"
            f"4. Виконай команду тут у боті:\n\n"
            f"Загальна Premium група:\n"
            f"`/setup_live_group -1004396905575`\n\n"
            f"Для конкретного блогера:\n"
            f"`/setup_live_group -1004396905575 @blogger`\n\n"
            f"Зразок: саме так підключено @EasyEnglishUkr_PREMIUM ✅",
            parse_mode="Markdown"
        )
        return

    elif q.data == "adm_bloggers_list":
        bloggers = get_registered_bloggers()
        codes    = get_blogger_codes()
        if not bloggers:
            await q.edit_message_text(
                "👥 Зареєстрованих блогерів поки немає.\n\n"
                "Використай /create_blogger_code @username щоб створити код.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="adm_back")
                ]])
            )
            return
        lines = ["👥 *Блогери SpeakChain*\n"]
        kb    = []
        total_students = total_basic_b = total_premium_b = 0
        this_month_b   = datetime.now().strftime("%Y-%m-01")
        for uid, name in sorted(bloggers.items(), key=lambda x: x[1]):
            students = [s for k, s in db.items()
                        if isinstance(s, dict) and (
                            s.get("affiliate_blogger","") == name or
                            s.get("affiliate_ref","").startswith(name)
                        )]
            b = sum(1 for s in students if is_premium(s) and s.get("plan","basic") == "basic")
            p = sum(1 for s in students if is_premium(s) and s.get("plan") == "premium")
            t = sum(1 for s in students if is_in_trial(s))
            active  = sum(1 for s in students if s.get("last_date","") >= this_month_b)
            revenue = round((b * float(BASIC_AFFILIATE_PRICE) + p * float(PREMIUM_PRICE_AFF)) * 0.25, 2)
            total_students += len(students); total_basic_b += b; total_premium_b += p
            lines.append(
                f"• *@{name}*\n"
                f"  👥 {len(students)} студ.  ⚡️{b} 🌟{p} 🎁{t}\n"
                f"  🔥 {active} активних  💰 комісія: ${revenue}"
            )
            kb.append([InlineKeyboardButton(f"👤 @{name} ({len(students)})", callback_data=f"view_blogger_{name}")])
        unused = {c: n for c, n in codes.items() if n not in bloggers.values()}
        if unused:
            lines.append(f"\n⏳ *Невикористані коди ({len(unused)}):*")
            for code, name in unused.items():
                lines.append(f"  `{code}` → {name}")
        lines.append(f"\n📊 *Всього:* 👥{total_students}  ⚡️{total_basic_b}  🌟{total_premium_b}")
        text = chr(10).join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n\n_...список обрізано_"
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="adm_back")])
        await q.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "adm_refs_report":
        refs = {}
        for uid, s in db.items():
            if not isinstance(s, dict): continue
            ref = s.get("affiliate_ref","")
            if ref:
                refs.setdefault(ref, []).append(s)
        if not refs:
            await q.edit_message_text("Реферальних переходів поки немає.")
            return
        lines = ["🔗 *Реферали:*", ""]
        for ref_code, students in sorted(refs.items(), key=lambda x: -len(x[1])):
            paid    = sum(1 for s in students if is_premium(s))
            basic_r = sum(1 for s in students if is_premium(s) and s.get("plan","basic") == "basic")
            prem_r  = sum(1 for s in students if is_premium(s) and s.get("plan") == "premium")
            revenue = (basic_r * float(BASIC_AFFILIATE_PRICE) +
                       prem_r  * float(PREMIUM_PRICE_AFF)) * 0.255
            lines.append(
                f"*#{ref_code}*\n"
                f"  👥 {len(students)} студ.  ⭐️ {paid} платять  💰 ~${revenue:.0f}/міс"
            )
        text = chr(10).join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n\n_...список обрізано_"
        await q.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="adm_back")
            ]])
        )

    elif q.data == "adm_payouts_now":
        await q.answer()
        year_month = datetime.now().strftime("%Y-%m")
        payouts    = calculate_monthly_payouts(year_month)

        if not payouts:
            await ctx.bot.send_message(
                chat_id=user.id,
                text=f"💸 *Виплати за {year_month}*\n\nНемає даних за цей місяць.\nМожливо ще не було оплат.",
                parse_mode="Markdown"
            )
        else:
            by_blogger: dict = {}
            for p in payouts:
                by_blogger.setdefault(p["blogger"], []).append(p)

            lines = [f"💸 *Виплати блогерам — {year_month}*\n"]
            kb    = []
            for blogger, entries in sorted(by_blogger.items()):
                total  = sum(e["commission"] for e in entries)
                unpaid = sum(e["commission"] for e in entries if not e.get("paid"))
                status = "✅" if unpaid == 0 else "⏳"
                lines.append(
                    f"{status} *@{blogger}*  👥{len(entries)}  💰${total:.2f}"
                    + (f"  ← виплатити ${unpaid:.2f}" if unpaid > 0 else "  ✅ виплачено")
                )
                if unpaid > 0:
                    kb.append([InlineKeyboardButton(
                        f"✅ Виплатити @{blogger} ${unpaid:.2f}",
                        callback_data=f"pay_blogger_{blogger}_{year_month}"
                    )])

            total_all  = sum(e["commission"] for e in payouts)
            unpaid_all = sum(e["commission"] for e in payouts if not e.get("paid"))
            lines.append(f"\n📊 Всього: *${total_all:.2f}*  |  До виплати: *${unpaid_all:.2f}*")
            kb.append([InlineKeyboardButton("📊 Sync Google Sheets", callback_data=f"payouts_gs_sync_{year_month}")])

            await ctx.bot.send_message(
                chat_id=user.id,
                text="\n".join(lines),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb) if kb else None
            )

    elif q.data == "adm_back":
        await cmd_admin(update, ctx)


async def cmd_resetaudio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    Path("audio_ids.json").unlink(missing_ok=True)
    Path("placement_audio_config.json").unlink(missing_ok=True)
    for k in PLACEMENT_AUDIO:
        PLACEMENT_AUDIO[k] = ""
    await update.message.reply_text(
        "✅ Аудіо скинуто. Надішли 5 голосових заново — по порядку:\n\n"
        "1️⃣ A1\n2️⃣ A2\n3️⃣ B1\n4️⃣ B2\n5️⃣ C1"
    )

async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    chat    = update.effective_chat
    is_admin_flag = is_admin(user.id)

    if chat.type in ("group", "supergroup", "channel"):
        # Тільки адмін бачить ID групи — решта мовчки ігноруються
        if not is_admin(user.id):
            return
        try:
            await update.message.reply_text(
                f"🆔 ID групи: {chat.id}\nНазва: {chat.title}"
            )
        except Exception as e:
            logger.warning(f"cmd_myid group error: {e}")
        return
    else:
        # Особисті повідомлення — показуємо ID користувача
        admin_str = "так ✅" if is_admin_flag else "ні"
        uname = f"@{user.username}" if user.username else "немає"
        await update.message.reply_text(
            f"👤 Твій Telegram ID: <code>{user.id}</code>\n"
            f"🔤 Username: {uname}\n"
            f"🔧 Адмін: {admin_str}\n\n"
            f"<i>Щоб дізнатись ID групи — напиши /myid прямо в тій групі</i>",
            parse_mode="HTML"
        )

# ── Reset profile callback ───────────────────────────
async def cb_reset_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    # Скидаємо онбоардинг але зберігаємо прогрес
    upd_s(user.id, {
        "onboarding_done":        False,
        "goal":                   None,
        "level":                  None,
        "placement_done":         False,
        "daily_report_sent_date": None,
    })
    await q.edit_message_text(
        "🔄 Гаразд — починаємо знайомство заново!\n\n"
        "Для чого тобі потрібна англійська? 👇",
        parse_mode="Markdown",
        reply_markup=goal_kb()
    )



# ── Повний CEFR тест ──────────────────────────────────
async def cb_cefr_test_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Запускає динамічний тест по всіх пройдених темах."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    mastered = s.get("mastered_grammar", [])
    level    = s.get("level", "A1")

    # Збираємо всі теми до поточного рівня включно
    topics_to_test = []
    for lvl in LEVELS_ORDER:
        topics_to_test.extend(CEFR_GRAMMAR.get(lvl, []))
        if lvl == level:
            break

    if not topics_to_test:
        await q.edit_message_text(
            "Ще немає тем для перевірки — пройди кілька уроків спочатку 👇",
            reply_markup=main_menu()
        )
        return

    # Беремо максимум 20 тем (рівномірно по рівнях)
    import math
    step = max(1, math.ceil(len(topics_to_test) / 20))
    selected = topics_to_test[::step][:20]

    await q.edit_message_text(
        f"🧪 *Діагностичний тест*\n\n"
        f"Перевіряю граматику ({len(selected)} тем) і лексику твого профілю.\n\n"
        f"Готую тест... ⏳",
        parse_mode="Markdown"
    )

    # ── Граматичні питання зі статичного банку ──
    grammar_questions = []
    for topic in selected:
        bank = CEFR_QUESTION_BANK.get(topic)
        if bank:
            grammar_questions.append(random.choice(bank))

    # ── Лексичні питання — рівномірно по всіх рівнях для оцінки розміру ──
    profile  = s.get("syl_profile") or s.get("goal")
    vocab_questions = build_vocab_size_test(
        profile=profile,
        student_level=level,
        n_per_level=2,          # 2 слова × 5 рівнів × 2 питання = ~20 vocab питань
    )

    # ── Мікс: ~75% граматика, ~25% лексика, перемішуємо ──
    questions = grammar_questions + vocab_questions
    random.shuffle(questions)

    if not questions:
        await ctx.bot.send_message(
            chat_id=user.id,
            text="😔 Не вдалося зібрати тест. Спробуй через хвилину.",
            reply_markup=main_menu()
        )
        return

    # Зберігаємо тест
    upd_s(user.id, {
        "cefr_test_questions": questions,
        "cefr_test_current":   0,
        "cefr_test_results":   {},  # topic → correct/wrong
    })

    await ctx.bot.send_message(
        chat_id=user.id,
        text=(
            f"✅ *{len(questions)} питань готово!*\n\n"
            f"Граматика: {len(grammar_questions)} · Лексика: {len(vocab_questions)}\n\n"
            "Відповідай чесно — результат покаже твої сильні і слабкі місця 🎯\n\n"
            "Починаємо 👇"
        ),
        parse_mode="Markdown"
    )
    await _send_cefr_test_question(ctx.bot, user.id, questions, 0)


async def _send_cefr_test_question(bot, user_id: int, questions: list, idx: int):
    """Надсилає одне питання CEFR тесту."""
    q   = questions[idx]
    total = len(questions)
    kb  = InlineKeyboardMarkup([
        [InlineKeyboardButton(opt, callback_data=f"ct_{idx}_{i}")]
        for i, opt in enumerate(q["options"])
    ])
    await bot.send_message(
        chat_id=user_id,
        text=(
            f"*{idx+1}/{total}* — _{q['topic']}_\n\n"
            f"*{q['question']}*"
        ),
        parse_mode="Markdown",
        reply_markup=kb
    )


async def cb_cefr_test_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обробляє відповідь на питання CEFR тесту."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    # ct_{q_idx}_{ans_idx}
    data  = q.data
    parts = data.split("_")
    q_idx = int(parts[1])
    a_idx = int(parts[2])

    questions = s.get("cefr_test_questions", [])
    if q_idx >= len(questions):
        return

    question    = questions[q_idx]
    is_correct  = (a_idx == question["correct"])
    results     = s.get("cefr_test_results", {})
    results[question["topic"]] = "✅" if is_correct else "❌"
    upd_s(user.id, {"cefr_test_results": results, "cefr_test_current": q_idx + 1})

    # Показуємо результат на кнопках
    result_rows = []
    for i, opt in enumerate(question["options"]):
        if i == question["correct"] and i == a_idx:
            label = f"✅ {opt}"
        elif i == question["correct"]:
            label = f"✅ {opt}"
        elif i == a_idx:
            label = f"❌ {opt}"
        else:
            label = f"· {opt}"
        result_rows.append([InlineKeyboardButton(label, callback_data="ct_done")])

    await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(result_rows))

    # Пояснення
    if question.get("explanation"):
        await ctx.bot.send_message(
            chat_id=user.id,
            text=f"💡 _{question['explanation']}_",
            parse_mode="Markdown"
        )

    await asyncio.sleep(0.8)

    # Наступне питання або результат
    next_idx = q_idx + 1
    if next_idx < len(questions):
        await _send_cefr_test_question(ctx.bot, user.id, questions, next_idx)
    else:
        # Тест завершено — показуємо результати
        await _show_cefr_test_results(ctx.bot, user.id, s, results, questions)


async def _show_cefr_test_results(bot, user_id: int, s: dict, results: dict, questions: list):
    """Показує детальні результати CEFR тесту по темах."""
    correct = sum(1 for v in results.values() if v == "✅")
    total   = len(results)
    score   = int(correct / total * 100) if total else 0

    # ── Підрахунок vocab vs grammar результатів ──────────────
    all_grammar_topics = {t for topics in CEFR_GRAMMAR.values() for t in topics}

    # Словник: topic → (correct_bool, vocab_level)
    vocab_by_level: dict[str, list[bool]] = {"A1": [], "A2": [], "B1": [], "B2": [], "C1": []}
    grammar_gaps = []
    vocab_gaps   = []

    # Збираємо рівні з питань (якщо є vocab_level)
    q_level_map = {}
    for q in questions:
        if q.get("vocab_level") and q.get("vocab_word"):
            q_level_map[q["vocab_word"]] = q["vocab_level"]

    vocab_results   = []
    grammar_results = []
    for topic, mark in results.items():
        is_correct = (mark == "✅")
        if topic in all_grammar_topics:
            grammar_results.append((topic, mark))
            if not is_correct:
                grammar_gaps.append(topic)
        else:
            vocab_results.append((topic, mark))
            if not is_correct:
                vocab_gaps.append(topic)
            # Записуємо в рівневий аналіз
            lvl = q_level_map.get(topic, "")
            if lvl in vocab_by_level:
                vocab_by_level[lvl].append(is_correct)

    # ── Оцінка розміру словника по рівнях ────────────────────
    # Базові розміри словника на початку кожного рівня
    LEVEL_VOCAB_RANGE = {
        "A1": (100,   500),
        "A2": (500,  1500),
        "B1": (1500, 3500),
        "B2": (3500, 6000),
        "C1": (6000, 9000),
        "C2": (9000, 12000),
    }
    level = s.get("level", "A1")

    # Знаходимо «зламну точку» — де % правильних падає нижче 60%
    CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1"]
    highest_confident_level = "A1"
    for lvl in CEFR_ORDER:
        answers = vocab_by_level.get(lvl, [])
        if not answers:
            # Немає питань цього рівня — якщо це нижче рівня студента, вважаємо знає
            if CEFR_ORDER.index(lvl) < CEFR_ORDER.index(level):
                highest_confident_level = lvl
            continue
        pct = sum(answers) / len(answers)
        if pct >= 0.6:
            highest_confident_level = lvl
        else:
            break   # далі вже не знає → зупиняємось

    # Розраховуємо розмір словника в межах знайденого рівня
    low, high = LEVEL_VOCAB_RANGE.get(highest_confident_level, (300, 1000))
    # Корегуємо по % правильних у цьому рівні
    lvl_answers = vocab_by_level.get(highest_confident_level, [])
    pct_in_level = (sum(lvl_answers) / len(lvl_answers)) if lvl_answers else 0.7
    vocab_size = int(low + (high - low) * pct_in_level)

    # Якщо питань по рівнях не було — fallback по загальному %
    if all(not v for v in vocab_by_level.values()):
        base_sizes = {"A1": 300, "A2": 1000, "B1": 2500, "B2": 5000, "C1": 8000, "C2": 12000}
        base = base_sizes.get(level, 300)
        all_vocab = [r == "✅" for _, r in vocab_results]
        pct_all = (sum(all_vocab) / len(all_vocab)) if all_vocab else 0.7
        vocab_size = int(base * (0.6 + pct_all * 0.8))

    # ── Визначаємо vocab рівень і опис ───────────────────────
    VOCAB_LEVEL_MAP = [
        (300,   "A1", "Базовий рівень",     "Знаєш базові слова для виживання. Час нарощувати словник! 💪"),
        (1000,  "A2", "Елементарний",       "Можеш говорити про повсякденне. Додавай 5 слів на день!"),
        (2500,  "B1", "Середній",           "Справляєшся з більшістю ситуацій. Читай більше — лексика росте швидко."),
        (5000,  "B2", "Вище середнього",    "Легко підбираєш слова й точно висловлюєш думки. Час до нюансів! 🌟"),
        (8000,  "C1", "Просунутий",         "Говориш природно, розумієш підтекст. Читай оригінальні тексти."),
        (12000, "C2", "Вільне володіння",   "Словник на рівні освіченого носія мови. Вражаюче! 🏆"),
    ]
    vocab_label = "A1"
    vocab_desc_title = "Базовий рівень"
    vocab_desc_body  = "Час нарощувати словник!"
    for threshold, lbl, title, body in VOCAB_LEVEL_MAP:
        if vocab_size >= threshold:
            vocab_label      = lbl
            vocab_desc_title = title
            vocab_desc_body  = body

    # ── Шкала A1→C2 (10 сегментів) ───────────────────────────
    max_size   = 12000
    filled     = min(10, round(vocab_size / max_size * 10))
    scale_bar  = "█" * filled + "░" * (10 - filled)
    # Позначки під шкалою
    scale_line = "`A1   A2    B1    B2    C1  C2`"

    lines = [f"🏆 *Результати тесту*\n\n*{correct}/{total}* правильних ({score}%)\n"]

    # ── БЛОК 1: Аналіз словникового запасу ───────────────────
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📖 *Аналіз лексичного запасу*\n")
    lines.append(f"Оцінений словник: *≈ {vocab_size:,} слів*".replace(",", " "))
    lines.append(f"\n`{scale_bar}`")
    lines.append(scale_line)
    lines.append(f"\n🎯 Рівень: *{vocab_desc_title}*")
    lines.append(f"_{vocab_desc_body}_\n")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━\n")

    # ── БЛОК 2: Граматика по рівнях ───────────────────────────
    grammar_gaps = []
    vocab_gaps   = []

    grammar_shown = False
    for lvl in LEVELS_ORDER:
        lvl_topics  = CEFR_GRAMMAR.get(lvl, [])
        lvl_results = [(t, results[t]) for t in lvl_topics if t in results]
        if not lvl_results:
            continue
        if not grammar_shown:
            lines.append("*📝 Граматика:*")
            grammar_shown = True
        lines.append(f"\n  *{LEVEL_NAMES.get(lvl, lvl)}*")
        for topic, mark in lvl_results:
            lines.append(f"    {mark} {topic}")
            if mark == "❌":
                grammar_gaps.append(topic)

    # ── БЛОК 3: Лексика — деталі ──────────────────────────────
    if vocab_results:
        lines.append("\n*📖 Лексика:*")
        for word, mark in vocab_results:
            lines.append(f"  {mark} {word}")
            if mark == "❌":
                vocab_gaps.append(word)

    # ── Прогалини ─────────────────────────────────────────────
    all_gaps = grammar_gaps + vocab_gaps
    if all_gaps:
        lines.append(f"\n\n⚠️ *Прогалини ({len(all_gaps)}):*")
        if grammar_gaps:
            lines.append(f"  Граматика: {', '.join(grammar_gaps[:3])}")
        if vocab_gaps:
            lines.append(f"  Лексика: {', '.join(vocab_gaps[:3])}")

        cur_idx = LEVELS_ORDER.index(level) if level in LEVELS_ORDER else 0
        def _gap_rank(topic):
            for i, lvl in enumerate(LEVELS_ORDER):
                if topic in CEFR_GRAMMAR.get(lvl, []):
                    return abs(i - cur_idx)
            return 99
        if grammar_gaps:
            first_gap = min(grammar_gaps, key=_gap_rank)
            gap_query = CEFR_TOPIC_QUERIES.get(first_gap, first_gap.lower())
            pending   = {"grammar_gap": first_gap, "grammar_query": gap_query}
        else:
            first_word = vocab_gaps[0]
            interest   = (s.get("interests") or [""])[0]
            gap_query  = f"{first_word} vocabulary English {level} lesson {interest}".strip()
            pending    = {"grammar_gap": first_word, "grammar_query": gap_query}

        upd_s(user_id, {
            "pending_gaps":    pending,
            "cefr_test_gaps":  all_gaps,
            "vocab_size_est":  vocab_size,
            "vocab_level_est": vocab_label,
        })
        lines.append("\n\n🎯 *Наступне відео підберу саме під цю прогалину!*")
    else:
        upd_s(user_id, {"vocab_size_est": vocab_size, "vocab_level_est": vocab_label})
        lines.append("\n\n🌟 *Відмінно! Всі теми засвоєні!*")

    await bot.send_message(
        chat_id=user_id,
        text=chr(10).join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Порадь відео під прогалини", callback_data="fork_choose")],
        ]) if all_gaps else main_menu()
    )



async def cb_suggest_tutor_me(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Пропонує /tutor_me після gap analysis."""
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🎓 */tutor_me* — Індивідуальна програма\n\n"
        "Отримай лексику і граматику саме під твою сферу діяльності.\n\n"
        "Натисни /tutor_me щоб обрати профіль 👇",
        parse_mode="Markdown"
    )

# ── Публічний контент ─────────────────────────────────
COMMUNITY_CHANNEL = "@speakchain_community"

# ── Weekly Community Challenge ────────────────────────
CURRENT_CHALLENGE = {
    "topic":    "Розкажи про своє хобі за 30 секунд",
    "deadline": "",  # встановлюється адміном
    "prize":    "1 місяць Basic",
    "active":   False,
}

CURRENT_CHALLENGE = {
    "topic":    "Розкажи про своє хобі за 30 секунд",
    "deadline": "",
    "prize":    "1 місяць Basic",
    "active":   False,
}

# ════════════════════════════════════════════════════════════
# SPEAKING COMMUNITY + B2B
# ════════════════════════════════════════════════════════════
#
# Логіка:
#   1. Студент переходить по реферальному посиланню блогера
#      або вводить код /join <channel_slug>
#   2. Бот створює або знаходить спільноту для цього каналу
#   3. Студент отримує 7-денний тріал (FREE_TRIAL_DAYS)
#   4. Для спільноти генерується щоденний Speaking Challenge
#   5. Не виконав 2 дні поспіль → попередження
#   6. Не виконав 3 дні поспіль → виключення + бот видаляється
#
# Зберігається в БД:
#   community_slug    → "bbc_learning" | "lets_talk" тощо
#   community_joined  → "2026-06-14"
#   community_trial_end → "2026-06-21"
#   community_missed_days → int (лічильник пропусків)
#   community_warned  → bool
# ════════════════════════════════════════════════════════════

COMMUNITY_CHALLENGE_TOPICS = [
    "Розкажи про себе за 45 секунд — хто ти і чим займаєшся?",
    "Опиши своє ідеальне ранкове рутино англійською",
    "Розкажи про останній фільм чи серіал який дивився",
    "Поясни своє хобі так, щоб незнайомець зрозумів",
    "Опиши місто де живеш — що в ньому особливого?",
    "Розкажи про свою роботу або навчання",
    "Що ти хочеш досягнути з англійською — конкретно?",
]

def _community_challenge_today(slug: str) -> str:
    """Повертає Speaking Challenge для спільноти на сьогодні (по дню тижня)."""
    day_idx = datetime.now().weekday()
    topics  = COMMUNITY_CHALLENGE_TOPICS
    return topics[day_idx % len(topics)]

def _community_trial_active(s: dict) -> bool:
    """Чи є активний тріал спільноти."""
    end_str = s.get("community_trial_end", "")
    if not end_str:
        return False
    try:
        end = datetime.strptime(end_str, "%Y-%m-%d")
        return datetime.now() <= end
    except Exception:
        return False

def _community_trial_days_left(s: dict) -> int:
    end_str = s.get("community_trial_end", "")
    if not end_str:
        return 0
    try:
        end  = datetime.strptime(end_str, "%Y-%m-%d")
        left = (end - datetime.now()).days
        return max(0, left)
    except Exception:
        return 0


async def cmd_join_community(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /join <slug> — приєднатись до спільноти блогера/каналу.
    Також викликається автоматично при переході по реферальному посиланню.
    """
    user = update.effective_user
    s    = get_s(user.id)
    args = ctx.args or []
    slug = args[0].lower().strip() if args else s.get("community_slug", "")

    if not slug:
        await update.message.reply_text(
            "Вкажи код спільноти: `/join <код>`\n\n"
            "Наприклад: `/join bbc_learning`",
            parse_mode="Markdown"
        )
        return

    # Вже в спільноті
    if s.get("community_slug") == slug and _community_trial_active(s):
        left = _community_trial_days_left(s)
        await update.message.reply_text(
            f"✅ Ти вже в спільноті *{slug}*!\n\n"
            f"Тріал активний ще *{left} дн.*\n\n"
            "Сьогоднішнє завдання 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎯 Сьогоднішній Challenge", callback_data=f"community_challenge"),
            ]])
        )
        return

    # Нова спільнота — 7-денний тріал
    today   = datetime.now().strftime("%Y-%m-%d")
    end     = (datetime.now() + timedelta(days=FREE_TRIAL_DAYS)).strftime("%Y-%m-%d")
    upd_s(user.id, {
        "community_slug":       slug,
        "community_joined":     today,
        "community_trial_end":  end,
        "community_missed_days": 0,
        "community_warned":     False,
        "community_done_today": None,
        # Якщо не зареєстрований — встановлюємо дату реєстрації для загального тріалу
        "registered_at": s.get("registered_at") or today,
    })

    topic = _community_challenge_today(slug)
    await update.message.reply_text(
        f"🎉 *Вітаємо у спільноті {slug}!*\n\n"
        f"У тебе є *{FREE_TRIAL_DAYS} днів безкоштовного доступу:*\n"
        "  🎙 Speaking Challenges щодня\n"
        "  👥 Speaking Partner підбір\n"
        "  📊 AI-аналіз монологів\n"
        "  🏆 Таблиця лідерів спільноти\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 *Сьогоднішній Challenge:*\n\n"
        f"_{topic}_\n\n"
        "Запиши голосове — 30–60 секунд 🎙\n\n"
        f"_Тріал діє до {end}. Потім — Basic від $9/міс_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎙 Записати монолог", callback_data="remind_record")],
            [InlineKeyboardButton("👥 Знайти партнера",  callback_data="partner_search")],
            [InlineKeyboardButton("🏆 Таблиця лідерів", callback_data="community_leaderboard")],
        ])
    )


async def cb_community_challenge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показує сьогоднішній Speaking Challenge спільноти."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    slug  = s.get("community_slug", "")
    topic = _community_challenge_today(slug)
    left  = _community_trial_days_left(s)
    done_today = s.get("community_done_today") == datetime.now().strftime("%Y-%m-%d")
    missed = s.get("community_missed_days", 0)

    status = "✅ Сьогодні виконано!" if done_today else f"🎯 Ще не виконано сьогодні"

    await q.edit_message_text(
        f"🎯 *Speaking Challenge — {slug}*\n\n"
        f"{status}\n"
        f"Тріал: ще *{left} дн.*  |  Пропусків: *{missed}/3*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Сьогоднішнє завдання:*\n\n_{topic}_\n\n"
        "Запиши монолог 30–60 секунд і натисни ✅",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎙 Записати монолог",   callback_data="remind_record")],
            [InlineKeyboardButton("✅ Відзначити виконано", callback_data="community_checkin")],
            [InlineKeyboardButton("🏆 Лідерборд",          callback_data="community_leaderboard")],
        ]) if not done_today else InlineKeyboardMarkup([[
            InlineKeyboardButton("🏆 Лідерборд", callback_data="community_leaderboard"),
        ]])
    )


async def cb_community_checkin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент відзначає виконання челенджу."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer("✅ Зараховано!")

    today = datetime.now().strftime("%Y-%m-%d")
    if s.get("community_done_today") == today:
        await q.answer("Вже відмічено сьогодні!", show_alert=True)
        return

    upd_s(user.id, {
        "community_done_today":  today,
        "community_missed_days": 0,
        "community_warned":      False,
    })
    asyncio.create_task(award_xp(ctx.bot, user.id, "session"))

    left      = _community_trial_days_left(s)
    is_prem   = is_premium(s)
    file_id   = s.get("pending_voice_file_id", "")
    blogger   = s.get("affiliate_blogger", "")

    # Кнопки залежно від тарифу
    kb = [[InlineKeyboardButton("🏆 Лідерборд", callback_data="community_leaderboard")]]
    if is_prem and blogger and file_id:
        kb.insert(0, [InlineKeyboardButton(
            "💬 Хочу фідбек від блогера",
            callback_data=f"req_blogger_fb_{user.id}"
        )])

    prem_hint = ""
    if not is_prem:
        prem_hint = "\n\n💡 _Premium студенти отримують живий фідбек від блогера на свої записи_"

    await q.edit_message_text(
        "✅ *Challenge виконано!*\n\n"
        f"Тріал: ще *{left} дн.*\n\n"
        f"_Повертайся завтра за новим завданням 🔥_{prem_hint}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def cb_req_blogger_feedback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Premium студент запросив фідбек від блогера на запис."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    if not is_premium(s):
        await q.answer("Доступно тільки в Premium 🌟", show_alert=True)
        return

    file_id = s.get("pending_voice_file_id", "")
    if not file_id:
        await q.answer("Спочатку надішли голосовий запис 🎙", show_alert=True)
        return

    blogger_name = s.get("affiliate_blogger", "")
    if not blogger_name:
        await q.answer("Блогера не знайдено", show_alert=True)
        return

    # Зберігаємо запит у чергу фідбеку блогера
    db    = load_db()
    queue = db.get("_feedback_queue", [])
    # Перевіряємо чи вже є запит від цього студента сьогодні
    today = datetime.now().strftime("%Y-%m-%d")
    already = any(
        r.get("student_uid") == user.id and r.get("date") == today
        for r in queue
    )
    if already:
        await q.answer("Ти вже надіслав запит сьогодні 👍", show_alert=True)
        return

    queue.append({
        "student_uid":  user.id,
        "student_name": s.get("name", user.first_name),
        "student_level": s.get("level", "A1"),
        "blogger":      blogger_name,
        "file_id":      file_id,
        "date":         today,
        "topic":        _community_challenge_today(s.get("community_slug", "")),
        "done":         False,
    })
    db["_feedback_queue"] = queue
    save_db(db)

    # Сповіщаємо блогера
    bloggers_db = db.get("_registered_bloggers", {})
    blogger_uid = None
    for uid, bdata in bloggers_db.items():
        if isinstance(bdata, dict) and bdata.get("name") == blogger_name:
            blogger_uid = int(uid)
            break

    if blogger_uid:
        try:
            await ctx.bot.send_message(
                chat_id=blogger_uid,
                text=(
                    f"🎙 *Новий запит на фідбек!*\n\n"
                    f"👤 {s.get('name', user.first_name)}  |  {s.get('level','A1')}\n"
                    f"📝 Тема: _{_community_challenge_today(s.get('community_slug',''))}_\n\n"
                    "Переглянь чергу: /feedback_queue"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"blogger notify feedback req: {e}")

    await q.edit_message_text(
        "💬 *Запит надіслано блогеру!*\n\n"
        "Блогер прослухає твій запис і відповість голосовим.\n"
        "_Зазвичай протягом 24-48 годин_ 🎯",
        parse_mode="Markdown"
    )


async def cb_share_video_community(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Надсилає відео в Community канал."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    file_id = s.get("pending_video_file_id") or s.get("pending_voice_file_id")
    is_note = s.get("pending_video_is_note", False)
    if not file_id:
        await q.edit_message_text("⚠️ Файл не знайдено. Надішли ще раз.")
        return

    community_chat = COMMUNITY_LINK
    if not community_chat:
        await q.edit_message_text("⚠️ Community не налаштовано.")
        return

    level   = s.get("level", "A1")
    name    = s.get("name", user.first_name)
    lessons = len(s.get("done_lessons", []))
    streak  = s.get("streak_days", 0)
    caption = (
        f"🎙 *{name}*  {level}  📚{lessons} ур.  🔥{streak} днів\n"
        "#SpeakChain"
    )

    try:
        if is_note:
            await ctx.bot.send_video_note(chat_id=community_chat, video_note=file_id)
        else:
            try:
                await ctx.bot.send_video(chat_id=community_chat, video=file_id, caption=caption, parse_mode="Markdown")
            except Exception:
                await ctx.bot.send_voice(chat_id=community_chat, voice=file_id, caption=caption, parse_mode="Markdown")

        upd_s(user.id, {"pending_video_file_id": None})
        await q.edit_message_text("✅ *Дякую за сміливість!* 🔥\nВідео опубліковано в Community.", parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Video community share error: {e}")
        await q.edit_message_text("⚠️ Помилка публікації. Спробуй ще раз.")


async def cb_share_video_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Окей, пропускаємо 👍")


def get_improvement_delta(s: dict, days: int = 14) -> dict:
    """Повертає покращення балів за N днів."""
    scores = s.get("scores", [])
    if not scores: return {}
    cutoff = (__import__("datetime").date.today() - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
    old_scores  = [sc.get("score",0) for sc in scores if sc.get("date","")[:10] <  cutoff]
    new_scores  = [sc.get("score",0) for sc in scores if sc.get("date","")[:10] >= cutoff]
    if not new_scores: return {}
    avg_new = round(sum(new_scores) / len(new_scores))
    avg_old = round(sum(old_scores) / len(old_scores)) if old_scores else avg_new
    delta   = avg_new - avg_old
    return {"avg_now": avg_new, "avg_before": avg_old, "delta": delta, "days": days}


async def cb_community_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Три лідерборди: стрибок тижня / активність / зала слави."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    # ── Якщо є Mini App — відкриваємо його ──────────────
    if BOT_WEBHOOK_URL:
        db  = load_db()
        url = _build_leaderboard_url(user.id, s, db=db)
        await q.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(
            user.id,
            "🏆 *Leaderboard*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏆 Відкрити Leaderboard", web_app=WebAppInfo(url=url))
            ]])
        )
        return

    tab  = q.data.replace("community_leaderboard", "").lstrip("_") or "jump"
    slug = s.get("community_slug", "")
    db   = load_db()

    # Вибірка членів спільноти
    members = [
        (str(uid), st)
        for uid, st in db.items()
        if isinstance(st, dict) and st.get("community_slug") == slug
    ]

    today     = datetime.now().date()
    week_ago  = (today - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d")
    this_week = today.strftime("%Y-W%W")

    def score_improvement(st: dict) -> float:
        scores = st.get("scores", [])
        week_s = [sc.get("score", 0) for sc in scores if sc.get("date","")[:10] >= week_ago]
        old_s  = [sc.get("score", 0) for sc in scores if sc.get("date","")[:10] < week_ago]
        if not week_s: return 0.0
        avg_new = sum(week_s) / len(week_s)
        avg_old = sum(old_s) / len(old_s) if old_s else avg_new
        return round(avg_new - avg_old, 1)

    medals = ["🥇","🥈","🥉"]

    if tab == "jump":
        # Найбільший стрибок тижня
        ranked = sorted(members, key=lambda x: score_improvement(x[1]), reverse=True)
        lines  = [f"📈 *Стрибок тижня — {slug}*\n_Скидається щопонеділка_\n"]
        for i, (uid, st) in enumerate(ranked[:10]):
            delta = score_improvement(st)
            if delta <= 0: continue
            name  = st.get("name", f"Студент {uid[-4:]}")
            medal = medals[i] if i < 3 else f"{i+1}."
            mark  = "👤" if str(uid) == str(user.id) else ""
            lines.append(f"{medal} {name} {mark}  📈 +{delta} балів")
        if len(lines) == 2: lines.append("_Грай активніше щоб потрапити сюди! 🚀_")

    elif tab == "active":
        # Найбільше XP тижня (нараховується за дії, не за якість)
        def week_xp(st):
            # Рахуємо XP зароблений цього тижня через сесії
            sessions = sum(1 for sc in st.get("scores", []) if sc.get("date","")[:10] >= week_ago)
            phrases  = len([m for m in st.get("mined_sentences",[]) if m.get("date","")[:10] >= week_ago])
            return sessions * XP_AWARDS["session"] + phrases * XP_AWARDS["phrase_saved"]
        ranked = sorted(members, key=lambda x: week_xp(x[1]), reverse=True)
        lines  = [f"🔥 *Активні цього тижня — {slug}*\n_XP за дії · скидається щопонеділка_\n"]
        for i, (uid, st) in enumerate(ranked[:10]):
            xp    = week_xp(st)
            if xp == 0: continue
            name  = st.get("name", f"Студент {uid[-4:]}")
            medal = medals[i] if i < 3 else f"{i+1}."
            mark  = "👤" if str(uid) == str(user.id) else ""
            total_xp = st.get("xp_total", 0)
            lvl   = get_xp_level(total_xp)
            lines.append(f"{medal} {name} {mark}  ⚡️ {xp} XP  {lvl}")
        if len(lines) == 2: lines.append("_Почни говорити сьогодні! 💪_")

    else:  # hall
        # Зала слави — топ за весь час
        ranked = sorted(members, key=lambda x: (
            len(x[1].get("done_lessons",[])),
            x[1].get("streak_days",0)
        ), reverse=True)
        lines  = [f"🏛 *Зала слави — {slug}*\n_Топ за весь час_\n"]
        for i, (uid, st) in enumerate(ranked[:10]):
            name    = st.get("name", f"Студент {uid[-4:]}")
            lessons = len(st.get("done_lessons",[]))
            medal   = medals[i] if i < 3 else f"{i+1}."
            mark    = "👤" if str(uid) == str(user.id) else ""
            level   = st.get("level","?")
            lines.append(f"{medal} {name} {mark}  📚{lessons}  {level}")

    lines.append(f"\nУчасників: *{len(members)}*")

    await q.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📈 Стрибок" + (" ✓" if tab=="jump"   else ""), callback_data="community_leaderboard_jump"),
                InlineKeyboardButton("🔥 Активні" + (" ✓" if tab=="active" else ""), callback_data="community_leaderboard_active"),
                InlineKeyboardButton("🏛 Слава"   + (" ✓" if tab=="hall"   else ""), callback_data="community_leaderboard_hall"),
            ],
            [InlineKeyboardButton("🎯 Мій Challenge", callback_data="community_challenge")],
        ])
    )


async def job_community_monitor(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Щоденно о 20:00:
    - Перевіряє хто не виконав challenge
    - Збільшує лічильник пропусків
    - При 2 пропусках → попередження
    - При 3 пропусках → виключення (bot видаляє себе зі списку контактів, надсилає прощання)
    - Після закінчення тріалу → нагадування про оплату або виключення
    """
    db    = load_db()
    today = datetime.now().strftime("%Y-%m-%d")

    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if not s.get("community_slug"):   continue
        if not s.get("onboarding_done"):  continue
        if is_premium(s): continue   # premium — не видаляємо

        slug    = s.get("community_slug", "")
        missed  = s.get("community_missed_days", 0)
        warned  = s.get("community_warned", False)
        done_td = s.get("community_done_today", "")
        left    = _community_trial_days_left(s)

        # ── Тріал закінчився ──────────────────────────────────
        if left == 0 and not is_premium(s):
            try:
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        "⏰ *Тріал спільноти закінчився!*\n\n"
                        f"Спільнота *{slug}* — 7 днів пройшло.\n\n"
                        "Щоб залишитись і продовжувати Speaking Challenges — "
                        "обери план 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⚡️ Продовжити Basic",
                            url=BASIC_PAYMENT_LINK or "https://t.me/speakchain_bot")],
                        [InlineKeyboardButton("📊 Мій прогрес за 7 днів",
                            callback_data="progress_continue")],
                    ])
                )
            except Exception as e:
                logger.warning(f"Community trial end notify {uid}: {e}")
            continue

        # ── Пропустив сьогодні ────────────────────────────────
        if done_td != today:
            new_missed = missed + 1
            upd_s(int(uid), {"community_missed_days": new_missed})

            # ── 2 пропуски → попередження ─────────────────────
            if new_missed == 2 and not warned:
                upd_s(int(uid), {"community_warned": True})
                topic = _community_challenge_today(slug)
                try:
                    await ctx.bot.send_message(
                        chat_id=int(uid),
                        text=(
                            f"⚠️ *{slug} — останнє попередження!*\n\n"
                            f"Ти пропустив *2 дні* поспіль без виконання Challenge.\n\n"
                            "Ще 1 пропуск — і бот автоматично видалить тебе зі спільноти.\n\n"
                            f"*Сьогоднішнє завдання:*\n_{topic}_\n\n"
                            "Запиши зараз і натисни ✅ 👇"
                        ),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🎙 Записати зараз",    callback_data="remind_record"),
                            InlineKeyboardButton("✅ Відзначити виконано", callback_data="community_checkin"),
                        ]])
                    )
                except Exception as e:
                    logger.warning(f"Community warn {uid}: {e}")

            # ── 3 пропуски → виключення ───────────────────────
            elif new_missed >= 3:
                try:
                    await ctx.bot.send_message(
                        chat_id=int(uid),
                        text=(
                            f"👋 *{slug} — ти виключений зі спільноти*\n\n"
                            f"3 дні без виконання Speaking Challenge.\n\n"
                            "Це було автоматичне рішення — не особисте.\n\n"
                            "Якщо хочеш повернутись — просто напиши `/join {slug}` "
                            "і починай з нуля. Або обери платний план і залишайся назавжди 👇"
                        ),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Повернутись",
                                callback_data=f"join_community_{slug}")],
                            [InlineKeyboardButton("⚡️ Basic план",
                                url=BASIC_PAYMENT_LINK or "https://t.me/speakchain_bot")],
                        ])
                    )
                except Exception as e:
                    logger.warning(f"Community kick {uid}: {e}")

                # Видаляємо зі спільноти
                upd_s(int(uid), {
                    "community_slug":        None,
                    "community_joined":      None,
                    "community_trial_end":   None,
                    "community_missed_days": 0,
                    "community_warned":      False,
                    "community_done_today":  None,
                })


async def cb_join_community_inline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Callback для повернення в спільноту через кнопку."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    data = q.data  # join_community_<slug>
    slug = data.replace("join_community_", "")
    ctx.args = [slug]

    class _FMsg:
        _bot = ctx.bot
        async def reply_text(self_i, *a, **kw):
            await q.message.reply_text(*a, **kw)
    class _FUpd:
        effective_user = user
        message = _FMsg()

    await cmd_join_community(_FUpd(), ctx)


async def cmd_community_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/mystatus — статус у спільноті."""
    user = update.effective_user
    s    = get_s(user.id)
    slug = s.get("community_slug", "")

    if not slug:
        await update.message.reply_text(
            "Ти ще не в жодній спільноті.\n\n"
            "Приєднайся: `/join <код>`",
            parse_mode="Markdown"
        )
        return

    left    = _community_trial_days_left(s)
    missed  = s.get("community_missed_days", 0)
    joined  = s.get("community_joined", "")
    active  = _community_trial_active(s)
    topic   = _community_challenge_today(slug)
    done_td = s.get("community_done_today") == datetime.now().strftime("%Y-%m-%d")

    status_icon = "✅" if done_td else "⏳"
    trial_str   = f"Тріал: ще *{left} дн.*" if active else "❌ Тріал закінчився"

    await update.message.reply_text(
        f"👥 *Спільнота: {slug}*\n\n"
        f"{trial_str}\n"
        f"Приєднався: _{joined}_\n"
        f"Пропусків: *{missed}/3*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Сьогоднішній Challenge:*\n_{topic}_\n\n"
        f"{status_icon} {'Виконано сьогодні!' if done_td else 'Ще не виконано'}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 До Challenge",   callback_data="community_challenge")],
            [InlineKeyboardButton("🏆 Лідерборд",     callback_data="community_leaderboard")],
            [InlineKeyboardButton("👥 Знайти партнера", callback_data="partner_search")],
        ])
    )

async def cmd_oferta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Надсилає публічну оферту."""
    await _send_offer(update.message, ctx)


async def cmd_refuse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Відмова від підписки."""
    user = update.effective_user
    s    = get_s(user.id)
    if not is_premium(s):
        await update.message.reply_text(
            "ℹ️ У тебе немає активної підписки.",
            parse_mode="Markdown"
        )
        return
    until = s.get("premium_until", "")
    await update.message.reply_text(
        f"🚫 *Відмова від підписки*\n\n"
        f"Твоя підписка активна до: *{until}*\n\n"
        f"Щоб скасувати — надішли запит на:\n"
        f"📧 speakchain.admin@gmail.com\n\n"
        f"Зазнач:\n"
        f"• Telegram: @{user.username or user.id}\n"
        f"• Причину (необов'язково)\n\n"
        f"Доступ зберігається до кінця оплаченого періоду (*{until}*).\n"
        f"Повернення коштів — відповідно до умов оферти (/oferta).",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📄 Умови оферти", callback_data="help_offer")
        ]])
    )


async def cmd_privacy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Командa /privacy — надсилає політику конфіденційності."""
    if PRIVACY_FILE_ID:
        await update.message.reply_document(
            document=PRIVACY_FILE_ID,
            caption=(
                "🔒 *Політика конфіденційності SpeakChain*\n\n"
                "Документ описує які дані ми збираємо та як їх захищаємо."
            ),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🔒 *Політика конфіденційності SpeakChain*\n\n"
            "Ми збираємо: Telegram ID, ім'я, голосові записи, результати тестів, прогрес навчання.\n\n"
            "Дані використовуються виключно для надання Послуги та не передаються третім особам.\n\n"
            f"Повний текст: надішліть запит на _{SUPPORT_EMAIL}_",
            parse_mode="Markdown"
        )

async def cmd_offer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /offer — надсилає публічну оферту."""
    await _send_offer(update.message, ctx)

async def _send_offer(message, ctx):
    """Надсилає оферту — файл або текстове посилання."""
    if OFFER_FILE_ID:
        await message.reply_document(
            document=OFFER_FILE_ID,
            caption=(
                "📄 *Публічна оферта SpeakChain*\n\n"
                "Оплачуючи послуги ви підтверджуєте згоду з умовами договору."
            ),
            parse_mode="Markdown"
        )
    else:
        await message.reply_text(
            "📄 *Публічна оферта SpeakChain*\n\n"
            "_Оплачуючи послуги ви підтверджуєте згоду з умовами договору оферти._",
            parse_mode="Markdown"
        )

async def cmd_community_challenge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показує поточний community challenge (адмін-тема)."""
    if not CURRENT_CHALLENGE.get("active"):
        await update.message.reply_text(
            "🏆 *Community Challenge*\n\n"
            "Наразі активного челенджу немає.\n"
            "Слідкуй за оновленнями в @speakchain_community 👀",
            parse_mode="Markdown"
        )
        return

    topic_safe = CURRENT_CHALLENGE['topic'].replace('*','').replace('_','').replace('`','')
    prize_safe = CURRENT_CHALLENGE.get('prize','🎁').replace('*','').replace('_','').replace('`','')
    await update.message.reply_text(
        f"🏆 *Weekly Challenge!*\n\n"
        f"Тема: {topic_safe}\n\n"
        f"Приз: {prize_safe} 🎁\n\n"
        "Запиши 30-секундний монолог на цю тему і опублікуй у Community!\n\n"
        "_Найкращий монолог тижня отримує приз_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎙 Записати і відправити", callback_data="challenge_record"),
        ]])
    )

async def cmd_set_challenge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Адмін: встановити новий challenge."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Доступ заборонено.")
        return
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Використання: `/set_challenge Тема челенджу`",
            parse_mode="Markdown"
        )
        return
    topic = " ".join(args)
    CURRENT_CHALLENGE["topic"]  = topic
    CURRENT_CHALLENGE["active"] = True

    # Розсилаємо всім студентам
    db = load_db()
    count = 0
    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) == "quiz_cache": continue
        if not s.get("onboarding_done"): continue
        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=(
                    f"🏆 *Новий Weekly Challenge!*\n\n"
                    f"*Тема:* {topic}\n\n"
                    f"*Приз:* {CURRENT_CHALLENGE['prize']} 🎁\n\n"
                    "Запиши 30-секундний монолог і опублікуй у Community!\n\n"
                    "/challenge — деталі"
                ),
                parse_mode="Markdown"
            )
            count += 1
        except Exception:
            pass

    await update.message.reply_text(f"✅ Challenge запущено! Надіслано {count} студентам.")



def build_social_captions(name: str, s: dict, score_text: str = "") -> dict:
    import urllib.parse as _up
    BOT_LINK  = "https://t.me/SpeakChainBot"
    level     = LEVEL_NAMES.get(s.get("level",""), s.get("level","")) or "A1"
    done      = len(s.get("done_lessons", []))
    streak    = s.get("streak_days", 0) or 0
    score_l   = f" 🏆 {score_text}" if score_text else ""
    days_l    = ""
    reg_str   = s.get("registered_at","")
    if reg_str:
        try:
            d = (datetime.now() - datetime.strptime(reg_str, "%Y-%m-%d")).days
            if d > 3: days_l = f" · 📅 {d} днів"
        except Exception:
            pass
    lv = s.get("last_levelup_share", "")
    base = f"{'🎉 ' + lv if lv else '🎯 Вчу англійську по відео блогерів у SpeakChain!'}"
    ig = (f"{base}\n\n✅ Рівень: {level} · {done} уроків · 🔥{streak} днів{score_l}{days_l}\n\n"
          f"🤖 ШІ-репетитор + Speaking Partners + roadmap A1→C2\n\n"
          f"👉 {BOT_LINK}\n\n#SpeakChain #LearnEnglish #AIcoach #EnglishChallenge")
    fb = (f"{base}\n\n✅ Рівень: {level} · Уроків: {done} · 🔥 Стрік: {streak} днів{score_l}{days_l}\n\n"
          f"🤖 ШІ знаходить прогалини → відео → живий фідбек\n\nСпробуй безкоштовно 👉 {BOT_LINK}")
    tw = (f"{'🎉 ' + lv if lv else '🎯 Learning English with SpeakChain!'} "
          f"Level: {level} · {done} lessons · 🔥{streak} days{score_l}\n"
          f"AI coach + speaking partners 🚀 {BOT_LINK} #SpeakChain #LearnEnglish")
    li = (f"{'🎉 ' + lv if lv else '🚀 Learning English with SpeakChain'}\n\n"
          f"✅ Level: {level} · {done} lessons · 🔥{streak}-day streak{score_l}{days_l}\n\n"
          f"AI finds my gaps → personalised videos → live speaking practice.\n\n"
          f"Try free: {BOT_LINK}\n\n#ProfessionalDevelopment #EnglishSkills #AIcoach")
    return {
        "ig_tiktok":   ig, "facebook": fb, "twitter": tw, "linkedin": li,
        "twitter_url":  "https://twitter.com/intent/tweet?text=" + _up.quote(tw),
        "linkedin_url": "https://www.linkedin.com/sharing/share-offsite/?url=" + _up.quote(BOT_LINK),
        "facebook_url": "https://www.facebook.com/sharer/sharer.php?u=" + _up.quote(BOT_LINK),
    }

async def cb_share_socials(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()
    c    = build_social_captions(user.first_name, s, s.get("last_quiz_score_text",""))
    today = datetime.now().strftime("%Y-%m-%d")
    already_triple = s.get("triple_xp_date") == today

    triple_row = (
        [InlineKeyboardButton("✅ Вже опублікував — отримати XP", callback_data="social_published")]
        if not already_triple else
        [InlineKeyboardButton("🔥 Сьогодні вже потрійний XP день!", callback_data="social_already")]
    )

    text = (
        "📱 *Поділись своїм прогресом!*\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📸 *Instagram / TikTok* — скопіюй:\n"
        f"`{c['ig_tiktok']}`\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "👤 *Facebook* — скопіюй:\n"
        f"`{c['facebook']}`\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🔥 *Опублікував відео з #SpeakChain?*\n"
        "_Вставте посилання і отримай потрійний XP на весь день!_"
    )
    await q.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 Instagram", url="https://www.instagram.com/"),
             InlineKeyboardButton("🎵 TikTok",    url="https://www.tiktok.com/upload")],
            [InlineKeyboardButton("👤 Facebook",  url=c["facebook_url"])],
            triple_row,
        ])
    )


async def cb_social_published(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент повідомляє що опублікував відео — просимо посилання."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    upd_s(user.id, {"waiting_social_link": True})
    await q.edit_message_text(
        "🔗 *Вставте посилання на свою публікацію*\n\n"
        "Переконайся що в пості є хештег *#SpeakChain* 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Скасувати", callback_data="social_link_cancel")
        ]])
    )


async def cb_social_already(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Потрійний XP вже активний сьогодні! 🔥", show_alert=True)


async def cb_social_link_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    upd_s(q.from_user.id, {"waiting_social_link": False})
    await q.edit_message_text("Окей, скасовано 👍")




# ── Силабус — персоналізований юніт ──────────────────
SYLLABUS_DATA = {
    "it": {
        "name": "IT / розробка",
        "A1": {
            "topic": "Знайомство + цифри в IT",
            "lex":   ["name", "job title", "developer", "tester", "company",
                      "email", "laptop", "screen", "number", "version"],
            "gram":  ["#1 ABC, spelling", "#2 Numbers", "#5 Present Simple", "#13 Modal: can/must"],
            "note":  "«I work as a developer», порти, версії — числа в IT-контексті.",
        },
        "A2": {
            "topic": "Робоче місце, завдання, інструменти",
            "lex":   ["bug", "fix", "deploy", "update", "feature",
                      "deadline", "task", "sprint", "team", "remote"],
            "gram":  ["#16 Past Simple", "#17 Future Simple", "#25 Gerund basic", "#27 Modal extended"],
            "note":  "Стендапи, щоденні звіти, опис завдань.",
        },
        "B1": {
            "topic": "Проєкти, команда, архітектура",
            "lex":   ["repository", "pull request", "backend", "frontend", "agile",
                      "stakeholder", "requirement", "security", "pipeline", "sprint"],
            "gram":  ["#28 Present Perfect", "#31 Passive", "#43 Reported Speech", "#42 Modal advanced"],
            "note":  "Код-рев'ю, технічні листи, архітектурні обговорення.",
        },
        "B2": {
            "topic": "Архітектура, дослідження, переговори",
            "lex":   ["scalability", "latency", "microservices", "API", "SLA",
                      "roadmap", "trade-off", "benchmark", "refactoring", "deployment"],
            "gram":  ["#49 Third Conditional", "#57 Mixed Conditionals", "#51 Participle", "#53 It is said"],
            "note":  "Технічні специфікації, дизайн-документи.",
        },
        "C1": {
            "topic": "Академічна та лідерська комунікація",
            "lex":   ["paradigm", "implication", "albeit", "leverage", "disruptive",
                      "nuance", "resilience", "governance", "innovation", "coherence"],
            "gram":  ["#61 Inversion", "#62 Cleft Sentences", "#59 Complex Subject", "#60 For-infinitive"],
            "note":  "Конференції, наукові статті, лідерські виступи.",
        },
        "diffs": {
            "A1": [("programme","program"),("colour","color"),("organise","organize"),("licence","license"),("maths","math")],
            "A2": [("travelling","traveling"),("behaviour","behavior"),("centre","center"),("catalogue","catalog"),("grey","gray")],
            "B1": [("analyse","analyze"),("defence","defense"),("practise","practice"),("learnt","learned"),("burnt","burned")],
            "B2": [("specialisation","specialization"),("authorise","authorize"),("recognise","recognize"),("labour","labor"),("favour","favor")],
            "C1": [("whilst","while"),("amongst","among"),("aeroplane","airplane"),("draught","draft"),("tyre","tire")],
        },
    },
    "med": {
        "name": "Медицина",
        "A1": {
            "topic": "Знайомство + тіло і симптоми",
            "lex":   ["doctor", "nurse", "patient", "hospital", "head",
                      "stomach", "pain", "temperature", "clinic", "arm"],
            "gram":  ["#5 Present Simple", "#8 Imperative", "#13 Modal: can/must", "#10 In/on/at"],
            "note":  "Базові фрази з пацієнтом: огляд, вказівки.",
        },
        "A2": {
            "topic": "Прийом пацієнта, анамнез",
            "lex":   ["symptom", "allergy", "medication", "prescription", "diagnosis",
                      "blood pressure", "fever", "dose", "treatment", "referral"],
            "gram":  ["#16 Past Simple", "#24 First Conditional", "#27 Modal extended", "#17 Future Simple"],
            "note":  "Збір анамнезу, пояснення призначень.",
        },
        "B1": {
            "topic": "Консультація, лікування",
            "lex":   ["chronic", "inflammation", "surgery", "recovery", "side effects",
                      "referral", "scan", "consent", "prognosis", "complications"],
            "gram":  ["#28 Present Perfect", "#31 Passive", "#43 Reported Speech", "#32 Second Conditional"],
            "note":  "Пояснення лікування, медичні записи.",
        },
        "B2": {
            "topic": "Дослідження, протоколи",
            "lex":   ["clinical trial", "placebo", "efficacy", "contraindication", "prognosis",
                      "intervention", "comorbidity", "mortality", "protocol", "randomized"],
            "gram":  ["#53 It is reported", "#50 Passive Continuous", "#51 Participle", "#49 Third Conditional"],
            "note":  "Медичні протоколи, анотації досліджень.",
        },
        "C1": {
            "topic": "Академічна медична мова, етика",
            "lex":   ["mortality", "morbidity", "albeit", "nuance", "implication",
                      "dilemma", "concede", "paradigm shift", "equity", "ethics"],
            "gram":  ["#61 Inversion", "#62 Cleft Sentences", "#59 Complex Subject", "#60 For-infinitive"],
            "note":  "Наукові статті, медична етика, конференції.",
        },
        "diffs": {
            "A1": [("anaesthetic","anesthetic"),("paediatric","pediatric"),("haemoglobin","hemoglobin"),("gynaecology","gynecology"),("oestrogen","estrogen")],
            "A2": [("casualty (A&E)","emergency room"),("theatre","OR"),("plaster","band-aid"),("fortnight","two weeks"),("GP","primary care physician")],
            "B1": [("leukaemia","leukemia"),("oedema","edema"),("diarrhoea","diarrhea"),("orthopaedic","orthopedic"),("foetus","fetus")],
            "B2": [("labour","labor"),("defence mechanism","defense mechanism"),("behaviour","behavior"),("ageing","aging"),("programme","program")],
            "C1": [("whilst","while"),("practise","practice"),("authorise","authorize"),("recognise","recognize"),("amongst","among")],
        },
    },
    "bus": {
        "name": "Бізнес",
        "A1": {
            "topic": "Знайомство в бізнес-контексті",
            "lex":   ["company", "position", "manager", "office", "product",
                      "client", "price", "email", "meeting", "schedule"],
            "gram":  ["#5 Present Simple", "#8 Imperative", "#13 Modal: can I help?", "#14 Going to"],
            "note":  "Перші ділові контакти, листи-знайомства.",
        },
        "A2": {
            "topic": "Ділове листування, покупки",
            "lex":   ["order", "invoice", "delivery", "discount", "contract",
                      "supplier", "budget", "profit", "loss", "payment"],
            "gram":  ["#16 Past Simple", "#17 Future Simple", "#24 First Conditional", "#27 Modal extended"],
            "note":  "Базові ділові листи, замовлення, умови угод.",
        },
        "B1": {
            "topic": "Презентації, звіти, команда",
            "lex":   ["revenue", "market share", "growth", "target", "strategy",
                      "launch", "campaign", "feedback", "quarterly", "forecast"],
            "gram":  ["#28 Present Perfect", "#31 Passive", "#43 Reported Speech", "#32 Second Conditional"],
            "note":  "Квартальні звіти, ділові презентації.",
        },
        "B2": {
            "topic": "Стратегія, переговори",
            "lex":   ["stakeholder", "ROI", "leverage", "due diligence", "merger",
                      "compliance", "KPI", "competitive advantage", "acquisition", "equity"],
            "gram":  ["#49 Third Conditional", "#57 Mixed Conditionals", "#53 It is reported", "#54 Complex Object"],
            "note":  "Стратегічні звіти, переговори з партнерами.",
        },
        "C1": {
            "topic": "Лідерство, риторика",
            "lex":   ["paradigm", "disruptive", "albeit", "implication", "concede",
                      "nuance", "governance", "resilience", "leverage", "accountability"],
            "gram":  ["#61 Inversion", "#62 Cleft Sentences", "#59 Complex Subject", "#60 For-infinitive"],
            "note":  "Конференції, бізнес-есе, лідерська комунікація.",
        },
        "diffs": {
            "A1": [("cheque","check"),("colour","color"),("centre","center"),("organise","organize"),("travelling","traveling")],
            "A2": [("shop","store"),("flat","apartment"),("autumn","fall"),("redundant","laid off"),("post","mail")],
            "B1": [("turnover","revenue"),("shareholder","stockholder"),("labour","labor"),("behaviour","behavior"),("authorise","authorize")],
            "B2": [("favour","favor"),("honour","honor"),("neighbour","neighbor"),("recognise","recognize"),("specialise","specialize")],
            "C1": [("whilst","while"),("amongst","among"),("endeavour","endeavor"),("programme","program"),("defence","defense")],
        },
    },
    "edu": {
        "name": "Освіта",
        "A1": {
            "topic": "Клас, школа, навчання",
            "lex":   ["teacher", "student", "lesson", "class", "subject",
                      "homework", "book", "pen", "board", "answer"],
            "gram":  ["#5 Present Simple", "#8 Imperative", "#15 Question Tags", "#6 Present Continuous"],
            "note":  "Мова класу, базові інструкції, завдання.",
        },
        "A2": {
            "topic": "Навчальний процес, оцінки",
            "lex":   ["grade", "exam", "test", "pass", "fail",
                      "schedule", "semester", "assignment", "deadline", "campus"],
            "gram":  ["#16 Past Simple", "#24 First Conditional", "#25 Gerund", "#26 Infinitive"],
            "note":  "Розмови про прогрес, дедлайни, результати.",
        },
        "B1": {
            "topic": "Методика, пояснення",
            "lex":   ["curriculum", "syllabus", "assessment", "feedback", "objective",
                      "engage", "motivate", "differentiate", "outcome", "portfolio"],
            "gram":  ["#28 Present Perfect", "#31 Passive", "#43 Reported Speech", "#40 Be used to"],
            "note":  "Обговорення методики на нарадах.",
        },
        "B2": {
            "topic": "Педагогічні дослідження",
            "lex":   ["pedagogy", "constructivism", "literacy", "critical thinking", "evidence-based",
                      "cohort", "peer review", "scaffolding", "metacognition", "differentiation"],
            "gram":  ["#53 It is argued", "#50 Passive Continuous", "#51 Participle", "#56 Wish / If only"],
            "note":  "Наукові статті, звіти, освітні дослідження.",
        },
        "C1": {
            "topic": "Академічний дискурс, освітня політика",
            "lex":   ["epistemology", "paradigm", "implication", "albeit", "concede",
                      "equity", "inclusion", "accountability", "discourse", "hegemony"],
            "gram":  ["#61 Inversion", "#62 Cleft Sentences", "#59 Complex Subject", "#60 For-infinitive"],
            "note":  "Конференції, академічне письмо, освітня реформа.",
        },
        "diffs": {
            "A1": [("maths","math"),("colour","color"),("programme","program"),("practise","practice"),("behaviour","behavior")],
            "A2": [("timetable","schedule"),("term","semester"),("marks","grades"),("learnt","learned"),("revise","review/study")],
            "B1": [("analyse","analyze"),("organise","organize"),("recognise","recognize"),("defence","defense"),("labour","labor")],
            "B2": [("amongst","among"),("whilst","while"),("favour","favor"),("honour","honor"),("neighbour","neighbor")],
            "C1": [("whilst","while"),("endeavour","endeavor"),("practise","practice"),("authorise","authorize"),("recognise","recognize")],
        },
    },
    "art": {
        "name": "Творчість",
        "A1": {
            "topic": "Знайомство + творчі заняття",
            "lex":   ["artist", "music", "painting", "drawing", "write",
                      "style", "gallery", "instrument", "create", "colour"],
            "gram":  ["#5 Present Simple", "#6 Present Continuous", "#13 Modal: can", "#11 Comparative"],
            "note":  "Розповідь про себе як митця, хобі.",
        },
        "A2": {
            "topic": "Творчий процес, описи",
            "lex":   ["exhibition", "performance", "compose", "rehearse", "inspire",
                      "audience", "theme", "technique", "portfolio", "premiere"],
            "gram":  ["#16 Past Simple", "#25 Gerund", "#22 As…as / Than", "#21 Adverbs"],
            "note":  "Описи картин, музичних творів, виступів.",
        },
        "B1": {
            "topic": "Культура, мистецький контекст",
            "lex":   ["movement", "genre", "symbolism", "abstract", "narrative",
                      "critique", "commission", "residency", "curator", "installation"],
            "gram":  ["#28 Present Perfect", "#32 Second Conditional", "#39 Would rather", "#35 Despite"],
            "note":  "Артист-стейтменти, відгуки, інтерв'ю.",
        },
        "B2": {
            "topic": "Культурна критика, проєкти",
            "lex":   ["aesthetic", "discourse", "avant-garde", "manifesto", "patronage",
                      "intellectual property", "grant", "subversive", "conceptual", "provenance"],
            "gram":  ["#53 It is argued", "#51 Participle", "#56 Wish", "#57 Mixed Conditionals"],
            "note":  "Мистецька критика, гранти, культурні проєкти.",
        },
        "C1": {
            "topic": "Академічна критика",
            "lex":   ["semiotics", "postmodern", "albeit", "nuance", "implication",
                      "subvert", "deconstruct", "agency", "canon", "hegemony"],
            "gram":  ["#61 Inversion", "#62 Cleft Sentences", "#59 Complex Subject", "#60 For-infinitive"],
            "note":  "Академічні есе, мистецька критика.",
        },
        "diffs": {
            "A1": [("colour","color"),("grey","gray"),("programme","program"),("centre","center"),("travelling","traveling")],
            "A2": [("theatre","theater"),("harbour","harbor"),("catalogue","catalog"),("recognise","recognize"),("practise","practice")],
            "B1": [("organise","organize"),("analyse","analyze"),("defence","defense"),("behaviour","behavior"),("favour","favor")],
            "B2": [("whilst","while"),("amongst","among"),("endeavour","endeavor"),("honour","honor"),("neighbour","neighbor")],
            "C1": [("whilst","while"),("endeavour","endeavor"),("recognise","recognize"),("authorise","authorize"),("amongst","among")],
        },
    },
    "tra": {
        "name": "Туризм / подорожі",
        "A1": {
            "topic": "Знайомство + базові подорожі",
            "lex":   ["hotel", "airport", "ticket", "passport", "check-in",
                      "room", "map", "street", "taxi", "price"],
            "gram":  ["#5 Present Simple", "#8 Imperative", "#10 In/on/at", "#13 Modal: can"],
            "note":  "Перші фрази туриста: заселення, орієнтування.",
        },
        "A2": {
            "topic": "Подорож, бронювання",
            "lex":   ["booking", "reservation", "tour", "guide", "attraction",
                      "sightseeing", "departure", "arrival", "luggage", "itinerary"],
            "gram":  ["#16 Past Simple", "#17 Future Simple", "#24 First Conditional", "#27 Modal extended"],
            "note":  "Бронювання, розповіді про поїздки.",
        },
        "B1": {
            "topic": "Гід, культура, туристи",
            "lex":   ["itinerary", "landmark", "heritage site", "customs", "cuisine",
                      "tradition", "currency", "visa", "local", "excursion"],
            "gram":  ["#28 Present Perfect", "#31 Passive", "#43 Reported Speech", "#34 Because/of"],
            "note":  "Екскурсійні тексти, робота гіда.",
        },
        "B2": {
            "topic": "Туристична індустрія",
            "lex":   ["hospitality", "sustainable tourism", "occupancy rate", "revenue management", "eco-tourism",
                      "KPI", "destination", "niche tourism", "concierge", "resort"],
            "gram":  ["#49 Third Conditional", "#57 Mixed Conditionals", "#53 It is reported", "#54 Complex Object"],
            "note":  "Звіти для готелів, стратегії компаній.",
        },
        "C1": {
            "topic": "Культурний туризм, академічна мова",
            "lex":   ["geopolitics", "cultural diplomacy", "overtourism", "resilience", "sustainability",
                      "albeit", "nuance", "commodification", "authenticity", "diaspora"],
            "gram":  ["#61 Inversion", "#62 Cleft Sentences", "#59 Complex Subject", "#60 For-infinitive"],
            "note":  "Академічні конференції, культурна дипломатія.",
        },
        "diffs": {
            "A1": [("cheque","check"),("colour","color"),("centre","center"),("travelling","traveling"),("flat","apartment")],
            "A2": [("holiday","vacation"),("return ticket","round trip"),("car park","parking lot"),("railway","railroad"),("boot","trunk")],
            "B1": [("motorway","highway"),("petrol","gas"),("pavement","sidewalk"),("queue","line"),("pub","bar")],
            "B2": [("recognise","recognize"),("authorise","authorize"),("favour","favor"),("behaviour","behavior"),("organise","organize")],
            "C1": [("whilst","while"),("amongst","among"),("endeavour","endeavor"),("programme","program"),("defence","defense")],
        },
    },
}

SYLLABUS_DATA["general"] = {
    "name": "Загальна англійська",
    "A1": {
        "topic": "Знайомство, сім'я, повсякденне життя",
        "lex":   ["hello", "name", "family", "home", "food", "work", "time", "day", "friend", "like"],
        "gram":  ["#5 Present Simple", "#6 Present Continuous", "#13 Modal: can/must", "#8 Imperative"],
        "note":  "Базові фрази для будь-якої ситуації.",
    },
    "A2": {
        "topic": "Покупки, подорожі, вільний час",
        "lex":   ["shop", "travel", "hobby", "weather", "money", "restaurant", "transport", "health", "sport", "city"],
        "gram":  ["#16 Past Simple", "#17 Future Simple", "#24 First Conditional", "#23 Used to"],
        "note":  "Розмови в побуті та подорожах.",
    },
    "B1": {
        "topic": "Робота, навчання, стосунки",
        "lex":   ["career", "education", "opinion", "problem", "solution", "experience", "culture", "news", "society", "change"],
        "gram":  ["#28 Present Perfect", "#31 Passive", "#32 Second Conditional", "#43 Reported Speech"],
        "note":  "Дискусії, думки, опис досвіду.",
    },
    "B2": {
        "topic": "Суспільство, технології, глобальні теми",
        "lex":   ["technology", "environment", "politics", "economy", "media", "diversity", "innovation", "challenge", "impact", "perspective"],
        "gram":  ["#49 Third Conditional", "#57 Mixed Conditionals", "#53 It is said", "#56 Wish"],
        "note":  "Складні дискусії, есе, аргументація.",
    },
    "C1": {
        "topic": "Абстрактні теми, нюанси, риторика",
        "lex":   ["nuance", "implication", "albeit", "coherence", "discourse", "paradigm", "rhetoric", "ambiguity", "concede", "assertion"],
        "gram":  ["#61 Inversion", "#62 Cleft Sentences", "#59 Complex Subject", "#60 For-infinitive"],
        "note":  "Академічний стиль, публічні виступи.",
    },
    "diffs": {
        "A1": [("colour","color"),("travelling","traveling"),("centre","center"),("organise","organize"),("programme","program")],
        "A2": [("holiday","vacation"),("flat","apartment"),("shop","store"),("autumn","fall"),("post","mail")],
        "B1": [("analyse","analyze"),("recognise","recognize"),("behaviour","behavior"),("labour","labor"),("defence","defense")],
        "B2": [("whilst","while"),("amongst","among"),("favour","favor"),("honour","honor"),("neighbour","neighbor")],
        "C1": [("endeavour","endeavor"),("practise","practice"),("authorise","authorize"),("programme","program"),("grey","gray")],
    },
}
SYLLABUS_LEVEL_NAMES = {
    "A2": "A2 — Elementary",
    "B1": "B1 — Intermediate",
    "B2": "B2 — Upper-Intermediate",
    "C1": "C1 — Advanced",
}

def syllabus_profile_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💻 IT / розробка",      callback_data="syl_prof_it"),
         InlineKeyboardButton("🏥 Медицина",           callback_data="syl_prof_med")],
        [InlineKeyboardButton("📊 Бізнес",             callback_data="syl_prof_bus"),
         InlineKeyboardButton("📚 Освіта",             callback_data="syl_prof_edu")],
        [InlineKeyboardButton("🎨 Творчість",          callback_data="syl_prof_art"),
         InlineKeyboardButton("✈️ Туризм / подорожі",  callback_data="syl_prof_tra")],
        [InlineKeyboardButton("🌍 Загальна англійська", callback_data="syl_prof_general")],
        [InlineKeyboardButton("✏️ Інше (написати своє)", callback_data="syl_prof_other")],
    ])

def syllabus_level_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("A1 — Beginner",          callback_data="syl_lvl_A1"),
         InlineKeyboardButton("A2 — Elementary",        callback_data="syl_lvl_A2")],
        [InlineKeyboardButton("B1 — Intermediate",      callback_data="syl_lvl_B1"),
         InlineKeyboardButton("B2 — Upper-Intermediate",callback_data="syl_lvl_B2")],
        [InlineKeyboardButton("C1 — Advanced",          callback_data="syl_lvl_C1")],
    ])

def syllabus_variant_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇬🇧 British English", callback_data="syl_var_bre"),
        InlineKeyboardButton("🇺🇸 American English",callback_data="syl_var_ame"),
    ]])

def build_syllabus_message(profile: str, level: str, variant: str) -> tuple[str, InlineKeyboardMarkup]:
    """Формує повідомлення силабус-юніту."""
    data    = SYLLABUS_DATA.get(profile, {})
    unit    = data.get(level, {})
    diffs   = data.get("diffs", {}).get(level, [])
    prof_name = data.get("name", profile)
    flag = "🇬🇧" if variant == "bre" else "🇺🇸"
    var_name  = "BrE" if variant == "bre" else "AmE"

    # Лексика — перші 3 жирним
    lex = unit.get("lex", [])
    lex_parts = []
    for i, word in enumerate(lex):
        lex_parts.append(f"*{word}*" if i < 3 else word)
    lex_str = " · ".join(lex_parts)

    # Граматика
    gram_str = " · ".join(unit.get("gram", []))

    # BrE ↔ AmE відмінності
    if variant == "bre":
        diffs_str = " · ".join(f"{b} ↔ {a}" for b, a in diffs)
    else:
        diffs_str = " · ".join(f"{a} ↔ {b}" for b, a in diffs)

    msg = (
        f"*[{level} · {prof_name} · {flag} {var_name}]*\n\n"
        f"*Тема:* {unit.get('topic','')}\n\n"
        f"*Лексика:*\n{lex_str}\n\n"
        f"*Граматика (з силабусу):*\n{gram_str}\n\n"
        f"*{flag} відмінності:*\n{diffs_str}\n\n"
        f"_{unit.get('note','')}_"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Змінити рівень",   callback_data="syl_restart_level"),
         InlineKeyboardButton("👤 Змінити профіль",  callback_data="syl_restart_profile")],
        [InlineKeyboardButton("🌐 Змінити варіант",  callback_data="syl_restart_variant"),
         InlineKeyboardButton("📋 Повний план уроку",callback_data="syl_full_plan")],
    ])
    return msg, kb

async def cb_syllabus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обробник всіх кнопок силабусу."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()
    data = q.data

    # Вибір профілю
    if data.startswith("syl_prof_"):
        prof = data.replace("syl_prof_","")

        # "Інше" — просимо написати свою сферу
        if prof == "other":
            upd_s(user.id, {"syl_waiting_custom_prof": True})
            await q.edit_message_text(
                "✏️ *Напиши свою сферу діяльності*\n\n"
                "Наприклад: юриспруденція, архітектура, психологія...\n\n"
                "Я побудую індивідуальну програму саме для тебе 👇",
                parse_mode="Markdown"
            )
            return

        upd_s(user.id, {"syl_profile": prof})
        level = s.get("syl_level", s.get("level",""))
        if level and level in ["A1","A2","B1","B2","C1"]:
            await q.edit_message_text(
                f"Профіль: *{SYLLABUS_DATA.get(prof,{}).get('name',prof)}*\n\n"
                "Який варіант англійської? 👇",
                parse_mode="Markdown",
                reply_markup=syllabus_variant_kb()
            )
        else:
            await q.edit_message_text(
                f"Профіль: *{SYLLABUS_DATA.get(prof,{}).get('name',prof)}*\n\n"
                "Тепер обери рівень 👇",
                parse_mode="Markdown",
                reply_markup=syllabus_level_kb()
            )

    # Вибір рівня
    elif data.startswith("syl_lvl_"):
        level = data.replace("syl_lvl_","")
        upd_s(user.id, {"syl_level": level})
        await q.edit_message_text(
            f"Рівень: *{level}*\n\nЯкий варіант англійської? 👇",
            parse_mode="Markdown",
            reply_markup=syllabus_variant_kb()
        )

    # Вибір варіанту → показуємо юніт
    elif data.startswith("syl_var_"):
        variant = data.replace("syl_var_","")
        upd_s(user.id, {"syl_variant": variant})
        prof  = get_s(user.id).get("syl_profile","")
        level = get_s(user.id).get("syl_level", s.get("level","A1"))
        if not prof:
            await q.edit_message_text("Спочатку обери профіль 👇", reply_markup=syllabus_profile_kb())
            return
        msg, kb = build_syllabus_message(prof, level, variant)
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)

    # Restart buttons
    elif data == "syl_restart_level":
        await q.edit_message_text("Обери рівень 👇", reply_markup=syllabus_level_kb())
    elif data == "syl_restart_profile":
        await q.edit_message_text("Обери профіль 👇", reply_markup=syllabus_profile_kb())
    elif data == "syl_restart_variant":
        await q.edit_message_text("Обери варіант англійської 👇", reply_markup=syllabus_variant_kb())

    # Повний план уроку — статичний шаблон (без виклику Claude)
    elif data == "syl_full_plan":
        s2    = get_s(user.id)
        prof  = s2.get("syl_profile","")
        level = s2.get("syl_level", s2.get("level","A1"))
        variant = s2.get("syl_variant","ame")
        unit  = SYLLABUS_DATA.get(prof,{}).get(level,{})
        if not unit:
            await q.edit_message_text("Спочатку обери профіль і рівень.")
            return
        await q.edit_message_text("📋 Готую план уроку...")
        plan = build_lesson_plan_static(prof, level, variant, SYLLABUS_DATA)
        await ctx.bot.send_message(
            chat_id=user.id,
            text=plan,
            parse_mode="Markdown"
        )

async def handle_syllabus_custom_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Генерує індивідуальну програму для кастомної сфери через Claude."""
    user = update.effective_user
    s    = get_s(user.id)
    if not s.get("syl_waiting_custom_prof"):
        return False

    field = update.message.text.strip()
    upd_s(user.id, {
        "syl_waiting_custom_prof": False,
        "syl_profile":             "custom",
        "syl_custom_field":        field,
    })

    level   = s.get("syl_level", s.get("level", "A1"))
    variant = s.get("syl_variant", "ame")
    flag    = "🇬🇧" if variant == "bre" else "🇺🇸"
    var_name= "BrE" if variant == "bre" else "AmE"

    await update.message.reply_text(f"⏳ Будую індивідуальну програму для *{field}*...", parse_mode="Markdown")

    prompt = (
        f"Create a personalized English learning unit for a student at {level} level working in: {field}\n"
        f"Variant: {'British' if variant=='bre' else 'American'} English\n\n"
        "Reply ONLY with valid JSON (no markdown):\n"
        '{"topic": "...", "lex": ["word1","word2","word3","word4","word5","word6","word7","word8","word9","word10"], '
        '"gram": ["grammar point 1", "grammar point 2", "grammar point 3"], '
        '"note": "one sentence about practical use", '
        '"diffs": [["BrE_word","AmE_word"],["BrE2","AmE2"],["BrE3","AmE3"]]}'
    )
    try:
        cr = claude_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        raw  = re.sub(r"```json|```","", cr.content[0].text).strip()
        unit = json.loads(raw)

        lex_parts = [f"*{w}*" if i < 3 else w for i, w in enumerate(unit.get("lex",[]))]
        lex_str   = " · ".join(lex_parts)
        gram_str  = " · ".join(unit.get("gram",[]))
        diffs     = unit.get("diffs",[])
        if variant == "bre":
            diffs_str = " · ".join(f"{b} ↔ {a}" for b,a in diffs)
        else:
            diffs_str = " · ".join(f"{a} ↔ {b}" for b,a in diffs)

        msg = (
            f"*[{level} · {field} · {flag} {var_name}]*\n\n"
            f"*Тема:* {unit.get('topic','')}\n\n"
            f"*Лексика:*\n{lex_str}\n\n"
            f"*Граматика:*\n{gram_str}\n\n"
            f"*{flag} відмінності:*\n{diffs_str}\n\n"
            f"_{unit.get('note','')}_"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Змінити рівень",   callback_data="syl_restart_level"),
             InlineKeyboardButton("👤 Змінити профіль",  callback_data="syl_restart_profile")],
            [InlineKeyboardButton("🌐 Змінити варіант",  callback_data="syl_restart_variant"),
             InlineKeyboardButton("📋 Повний план уроку",callback_data="syl_full_plan")],
        ])
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.warning(f"Custom syllabus error: {e}")
        await update.message.reply_text("😔 Помилка генерації. Спробуй ще раз — /tutor_me")
    return True

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    s    = get_s(user.id)
    level = LEVEL_NAMES.get(s.get("level",""), "не вказано")
    goal  = GOAL_NAMES.get(s.get("goal",""), "не вказано")
    await update.message.reply_text(
        f"⚙️ *Налаштування профілю*\n\n"
        f"🎯 Ціль: *{goal}*\n"
        f"📊 Рівень: *{level}*\n\n"
        "Що хочеш змінити?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Змінити ціль",   callback_data="settings_goal"),
             InlineKeyboardButton("📊 Змінити рівень", callback_data="settings_level")],
        ])
    )

async def cb_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    if q.data == "settings_goal":
        await q.edit_message_text(
            "Для чого тобі потрібна англійська? 👇",
            parse_mode="Markdown",
            reply_markup=goal_kb()
        )

    elif q.data == "settings_level":
        await q.edit_message_text(
            "Обери свій рівень англійської 👇",
            parse_mode="Markdown",
            reply_markup=level_choice_kb()
        )

    elif q.data == "settings_reset":
        upd_s(user.id, {
            "onboarding_done":  False,
            "goal":             None,
            "level":            None,
            "placement_done":   False,
            "cycle_step":       0,
        })
        await q.edit_message_text(
            "🔄 *Профіль скинуто*\n\n"
            "Прогрес збережено — тільки ціль і рівень скинуті.\n\n"
            "Натисни /start щоб почати заново 👇",
            parse_mode="Markdown"
        )

# ── Community ─────────────────────────────────────────
async def cmd_community(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👥 *Що зараз:*\n"
        "Спільнота SpeakChain — місце де студенти діляться прогресом, "
        "підтримують одне одного і публікують свої записи.",
        parse_mode="Markdown"
    )
    if COMMUNITY_LINK:
        await update.message.reply_text(
            f"Приєднуйся до групи:\n{COMMUNITY_LINK}"
        )
    else:
        await update.message.reply_text("Спільнота скоро буде доступна! 🔜")

# ════════════════════════════════════════════════════════════
# POLYGLOT PATCH — Shadowing
# ════════════════════════════════════════════════════════════

def _shadowing_message(lesson: dict, level: str) -> str:
    """Будує текст shadowing-інструкції для уроку."""
    hint    = lesson.get("hint", "")
    grammar = lesson.get("grammar", "")
    phrases = [p.strip() for p in hint.replace("/ ", "\n").split("\n") if p.strip()][:3]
    text = (
        "🔊 *SHADOWING — повтори за спікером*\n\n"
        "*Крок 1* — Просто слухай, не говори\n"
        "*Крок 2* — Постав паузу після кожного речення, повтори вголос\n"
        "*Крок 3* — Спробуй говорити ОДНОЧАСНО зі спікером\n\n"
    )
    if grammar:
        text += f"📌 *Граматика:* _{grammar}_\n\n"
    if phrases:
        text += "💬 *Фрази для shadowing:*\n"
        text += "\n".join(f"  ▸ _{p}_" for p in phrases)
        text += "\n\n"
    text += (
        "🧠 _Не намагайся зрозуміти кожне слово — відчувай ритм і звук мови_\n\n"
        "Коли повторив 2–3 рази — натисни 👇"
    )
    return text

def active_lesson_kb_v2(video_url: str, s: dict = None) -> InlineKeyboardMarkup:
    """Клавіатура уроку з кнопками: Дивитись → Повторив → Монолог."""
    vid_id   = extract_youtube_id(video_url)
    platform = detect_platform(video_url)
    if s is None:
        s = {}
    if WEBAPP_URL and vid_id and platform == "youtube":
        watch_btn = InlineKeyboardButton(
            "▶️ Дивитись відео",
            web_app={"url": _player_url(video_url, s)}
        )
    else:
        watch_btn = InlineKeyboardButton("▶️ Дивитись відео", url=video_url)
    return InlineKeyboardMarkup([
        [watch_btn],
        [InlineKeyboardButton("🔊 Повторив за спікером → далі", callback_data="shadow_done")],
        [InlineKeyboardButton("🎙 Записати монолог",            callback_data="remind_record")],
    ])

async def cb_shadow_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент повторив — одразу до монологу."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer("🔥 +5 XP за shadowing!")
    upd_s(user.id, {"shadow_sessions": s.get("shadow_sessions", 0) + 1})
    asyncio.create_task(award_xp(ctx.bot, user.id, "shadowing"))
    await q.edit_message_reply_markup(reply_markup=None)
    await _send_monologue_prompt(ctx.bot, user.id)

# ════════════════════════════════════════════════════════════
# POLYGLOT PATCH — Sentence Mining
# ════════════════════════════════════════════════════════════

async def _ask_sentence_mining(bot, user_id: int, after_video: bool = False):
    """Питає про улюблену фразу після відео."""
    upd_s(user_id, {"waiting_mining_phrase": True})
    if after_video:
        text = (
            "💎 *Sentence Mining*\n\n"
            "Поки дивишся відео — звертай увагу на фрази.\n\n"
            "Яке речення або вислів тебе вразив? Напиши його англійською 👇\n\n"
            "_або натисни «Пропустити» і одразу до shadowing_"
        )
    else:
        text = (
            "💎 *Sentence Mining*\n\n"
            "Яка фраза з відео найбільше запала в пам'ять?\n"
            "Напиши її англійською — додам в картотеку 🗃"
        )
    await bot.send_message(
        chat_id=user_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ Пропустити", callback_data="mining_skip")
        ]])
    )

async def _save_mined_sentence(uid: int, phrase: str, lesson: dict):
    """Зберігає фразу в профілі та в SRS-картотеці."""
    s     = get_s(uid)
    mined = s.get("mined_sentences", [])
    entry = {
        "phrase":       phrase,
        "lesson_id":    lesson.get("id", ""),
        "lesson_title": lesson.get("title", ""),
        "date":         datetime.now().strftime("%Y-%m-%d"),
    }
    mined = [entry] + mined
    mined = mined[:50]
    srs_db = s.get("srs_words", {})
    if phrase not in srs_db:
        srs_db[phrase] = {
            "interval_days": 0,
            "next_review":   _srs_next_date("learn", 0),
            "count_know":    0,
            "count_learn":   1,
            "type":          "mined",
            "source_lesson": lesson.get("title", ""),
        }
    upd_s(uid, {
        "mined_sentences":       mined,
        "srs_words":             srs_db,
        "waiting_mining_phrase": False,
    })
    # XP за збережену фразу (відкладено — функція може не мати bot)
    s2 = get_s(uid)
    upd_s(uid, {"xp_total": s2.get("xp_total", 0) + XP_AWARDS["phrase_saved"]})

async def _send_monologue_prompt(bot, user_id: int):
    """Надсилає запрошення записати монолог."""
    s      = get_s(user_id)
    lesson = s.get("current_lesson_data", {})
    topic  = lesson.get("topic", "")
    await bot.send_message(
        chat_id=user_id,
        text=(
            "🎙 *Твій монолог*\n\n"
            + (f"_{topic}_\n\n" if topic else "")
            + "Говори вільно 30–60 секунд — не думай про граматику 👇"
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎙 Записати монолог", callback_data="remind_record"),
        ]])
    )


async def _offer_mining_from_transcript(bot, user_id: int, transcript: str, lesson: dict):
    """Питає студента яку фразу він хоче запам'ятати."""
    try:
        upd_s(user_id, {
            "waiting_mining_phrase": True,
            "pending_mining_lesson": lesson
        })
        await bot.send_message(
            chat_id=user_id,
            text=(
                "💎 *Sentence Mining*\n\n"
                "Яку фразу з цього відео хочеш запам'ятати?\n\n"
                "_Напиши її — і вона потрапить в твою картотеку для повторення_ 🧠"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭ Пропустити", callback_data="mining_skip"),
            ]])
        )
    except Exception as e:
        logger.warning(f"Mining ask failed {user_id}: {e}")


async def cb_mining_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Зберігає фрази з монологу в SRS-картотеку."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    phrases = s.get("pending_mining_phrases", [])
    lesson  = s.get("pending_mining_lesson", {})

    if not phrases:
        await q.edit_message_text("⏭ Нічого не знайдено для збереження.")
        return

    for phrase in phrases:
        await _save_mined_sentence(user.id, phrase, lesson)

    upd_s(user.id, {"pending_mining_phrases": [], "pending_mining_lesson": {}})
    s2        = get_s(user.id)
    due_count = len(_srs_due_words(s2))

    phrases_text = "\n".join(f"  ▸ _{p}_" for p in phrases)
    await q.edit_message_text(
        f"💎 *Збережено в картотеку!*\n\n{phrases_text}\n\n"
        f"Всього в SRS: *{due_count}* фраз 🧠",
        parse_mode="Markdown"
    )

async def cb_mining_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Пропустити Sentence Mining (з контексту після оцінки монологу)."""
    q = update.callback_query
    await q.answer()
    upd_s(q.from_user.id, {"waiting_mining_phrase": False})
    await q.edit_message_text(
        "⏭ Добре!\n\n"
        "_Наступного разу запиши 1 фразу — найшвидший спосіб наростити лексику_ 💡",
        parse_mode="Markdown"
    )

async def cb_mining_skip_to_record(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Пропустити Sentence Mining після shadowing → одразу до монологу."""
    q = update.callback_query
    await q.answer()
    upd_s(q.from_user.id, {"waiting_mining_phrase": False})
    await q.edit_message_reply_markup(reply_markup=None)
    await _send_monologue_prompt(ctx.bot, q.from_user.id)

# ════════════════════════════════════════════════════════════
# POLYGLOT PATCH — SRS callbacks
# ════════════════════════════════════════════════════════════

async def cb_srs_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Запускає SRS-сесію повторення."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()
    due = _srs_due_words(s)
    if not due:
        await q.edit_message_text("✅ Всі слова повторені! Так тримати 🎉")
        return
    srs_db     = s.get("srs_words", {})
    words_data = []
    for w in due:
        entry = srs_db.get(w["word"], {})
        words_data.append({
            "word":        w["word"],
            "translation": entry.get("translation", ""),
            "example":     entry.get("example", ""),
        })
    upd_s(user.id, {
        "vocab_session_words_data": words_data,
        "vocab_session_words":      [w["word"] for w in due],
        "vocab_session_idx":        0,
        "vocab_session_known":      0,
        "vocab_session_total":      len(due),
        "vocab_done":               False,
        "srs_session_active":       True,
    })
    await q.edit_message_text(
        f"🧠 *SRS — інтервальне повторення*\n\n"
        f"Слів до повторення: *{len(due)}*\n\n"
        "Натискай ✅ якщо пам'ятаєш, 📖 якщо ні 👇",
        parse_mode="Markdown"
    )
    await send_vocab_card(ctx.bot, user.id, words_data, 0)

async def cb_srs_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "⏭ Добре, нагадаю завтра 👍\n\n"
        "_Слова чекають — чим раніше повториш, тим краще закріпиш_ 🧠",
        parse_mode="Markdown"
    )

# ════════════════════════════════════════════════════════════
# POLYGLOT PATCH — Immersion Loop + /today + /immersion
# ════════════════════════════════════════════════════════════

DAILY_TIPS = [
    "💡 _20 хв щодня >>> 3 год раз на тиждень. Завжди._",
    "💡 _Думай про себе англійською — хоча б 5 хвилин на день_",
    "💡 _Дивися серіал без субтитрів — навіть якщо мало розумієш_",
    "💡 _Говори вголос під час практики — рот теж треба тренувати_",
    "💡 _Один новий вираз щодня = 365 за рік. Це рівень B2_",
    "💡 _Не чекай «готовності» говорити — говори зараз, з помилками_",
    "💡 _Слухай англійські подкасти під час прогулянки або їжі_",
    "💡 _Повторення через 1→3→7→14 днів = слово назавжди_",
    "💡 _Shadowing 10 хв = більше ніж 1 год граматики з підручника_",
    "💡 _Мозок засвоює мову уві сні — слухай аудіо перед сном_",
]

IMMERSION_RESOURCES = {
    "A1": [
        "📺 *YouTube:* EnglishClass101, Vanilla Pop (3–5 хв)",
        "🎵 *Podcast:* Simple English Podcast (Spotify)",
        "📱 *TikTok/Reels:* @learnenglish_withvanessa",
        "🎬 *Перед сном:* дитячі серіали англійською без субтитрів",
    ],
    "A2": [
        "📺 *YouTube:* English with Lucy, mmmEnglish",
        "🎵 *Podcast:* Easy English Podcast (Spotify)",
        "📱 *TikTok/Reels:* @english.with.james",
        "🎬 *Перед сном:* Friends S1–2 з англ. субтитрами",
    ],
    "B1": [
        "📺 *YouTube:* BBC Learning English, Kurzgesagt",
        "🎵 *Podcast:* All Ears English, 6 Minute English (BBC)",
        "📺 *Netflix:* Friends без субтитрів або Stranger Things",
        "🎬 *Перед сном:* TED Talks (5–10 хв)",
    ],
    "B2": [
        "📺 *YouTube:* TED Talks, Veritasium, Mark Rober",
        "🎵 *Podcast:* The Daily (NYT), Huberman Lab",
        "📺 *Netflix:* будь-який серіал без субтитрів",
        "🎬 *Перед сном:* аудіокниги англійською (Audible)",
    ],
    "C1": [
        "📺 *YouTube:* Lex Fridman, CGP Grey, Kurzgesagt",
        "🎵 *Podcast:* Hardcore History, 80,000 Hours",
        "📰 *Читай:* The Guardian, The Economist",
        "🎬 *Перед сном:* audiobook — будь-який жанр",
    ],
    "C2": [
        "📚 Читай оригінальні книги без словника",
        "🎧 Академічні лекції (MIT OpenCourseWare, Yale)",
        "🗣 Говори та думай тільки англійською",
        "🎬 *Перед сном:* Documentaries (Netflix, YouTube)",
    ],
}

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/today — Персональний щоденний план."""
    user  = update.effective_user
    s     = get_s(user.id)
    today = datetime.now().strftime("%Y-%m-%d")
    if not s.get("onboarding_done"):
        await update.message.reply_text("👋 Спочатку познайомимось! Натисни /start — це займе 1 хвилину 🚀")
        return
    level       = s.get("level", "A1")
    level_name  = LEVEL_NAMES.get(level, level)
    streak      = s.get("streak_days", 0)
    done_today  = s.get("last_date", "") == today
    due_words   = _srs_due_words(s)
    shadow_cnt  = s.get("shadow_sessions", 0)
    mined_cnt   = len(s.get("mined_sentences", []))
    lessons_cnt = len(s.get("done_lessons", []))

    lines = [f"📅 *Твій план на сьогодні*\n"]
    lines.append(f"📊 {level_name}  🔥 {streak} дн.  📚 {lessons_cnt} уроків\n")

    done_items = []
    if done_today:
        done_items.append("✅ Урок + монолог")
    if not due_words:
        done_items.append("✅ SRS — всі слова повторені")
    if done_items:
        lines.append("*Зроблено:*")
        for item in done_items:
            lines.append(f"  {item}")
        lines.append("")

    todo_items = []
    if not done_today:
        todo_items.append(("🎬", "Відео → Sentence Mining → Shadowing → Монолог  (~12 хв)"))
    if due_words:
        todo_items.append(("🧠", f"SRS: {len(due_words)} слів до повторення  (~2 хв)"))
    todo_items.append(("🎧", "Пасивне занурення: 20–30 хв контенту фоном"))
    todo_items.append(("🌙", "Перед сном: 10–20 хв аудіо англійською"))
    if todo_items:
        lines.append("*Залишилось:*")
        for emoji_s, t in todo_items:
            lines.append(f"  {emoji_s} {t}")
        lines.append("")

    resources = IMMERSION_RESOURCES.get(level, IMMERSION_RESOURCES["B1"])
    lines.append("*🎧 Пасивне занурення — твій рівень:*")
    for r in resources:
        lines.append(f"  {r}")
    lines.append("")

    sleep_res = SLEEP_AUDIO_RESOURCES.get(level, "")
    if sleep_res:
        lines.append(f"*🌙 Аудіо перед сном:*\n  _{sleep_res}_\n")

    lines.append(random.choice(DAILY_TIPS))
    if shadow_cnt > 0 or mined_cnt > 0:
        lines.append(f"\n_Shadowing: {shadow_cnt} сесій  •  Збережених фраз: {mined_cnt}_")

    kb_rows = []
    if not done_today:
        kb_rows.append([InlineKeyboardButton("🎬 Почати урок", callback_data="fork_choose")])
    if due_words:
        kb_rows.append([InlineKeyboardButton(
            f"🧠 SRS ({len(due_words)} слів)", callback_data="srs_start"
        )])
    kb_rows.append([InlineKeyboardButton("📊 Прогрес", callback_data="progress_continue")])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_rows) if kb_rows else main_menu()
    )

async def cmd_immersion(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/immersion — Ресурси пасивного занурення по рівню."""
    user  = update.effective_user
    s     = get_s(user.id)
    if not s.get("onboarding_done"):
        await update.message.reply_text("👋 Спочатку познайомимось! Натисни /start 🚀")
        return
    level = s.get("level", "A1")
    level_name = LEVEL_NAMES.get(level, level)
    resources  = IMMERSION_RESOURCES.get(level, IMMERSION_RESOURCES["B1"])
    sleep_res  = SLEEP_AUDIO_RESOURCES.get(level, "")

    level_name_safe = level_name.replace('*','').replace('_','')
    sleep_safe      = sleep_res.replace('_', ' ').replace('*', '') if sleep_res else "Аудіо англійською фоном"

    text = (
        f"🎧 *Immersion Loop — {level_name_safe}*\n\n"
        "Метод AJATT: мова скрізь, весь час.\n"
        "Мета — 20+ годин занурення на тиждень.\n\n"
        "*📺 Активне (з увагою):*\n"
    )
    for r in resources[:2]:
        text += f"  {r}\n"
    text += "\n*🎧 Пасивне (фоном, без уваги):*\n"
    for r in resources[2:]:
        text += f"  {r}\n"
    text += (
        f"\n*🌙 Перед сном (10–20 хв):*\n  {sleep_safe}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*Immersion по ситуаціях:*\n\n"
        "🚿 *Душ/вмивання* → Shadowing вголос (5 хв)\n"
        "🚗 *Дорога* → Подкаст або аудіокнига\n"
        "🍽 *Їжа* → Серіал або відео без субтитрів\n"
        "🏋️ *Тренування* → Музика або podcast англійською\n"
        "🛏 *Перед сном* → Аудіо тихо фоном\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "_Мозок обробляє мову навіть коли ти «не вчишся». "
        "Так діти засвоюють рідну мову — через занурення._"
    )
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Занурення сьогодні виконано!", callback_data="immersion_done")],
            [InlineKeyboardButton("📅 Мій план на сьогодні",        callback_data="today_plan")],
        ])
    )

async def cb_immersion_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer("🎧 Зараховано!")
    today         = datetime.now().strftime("%Y-%m-%d")
    immersion_log = s.get("immersion_log", [])
    if today not in immersion_log:
        immersion_log.append(today)
        immersion_log = immersion_log[-90:]
    upd_s(user.id, {"immersion_log": immersion_log})
    await q.edit_message_text(
        f"🎧 *Immersion зараховано!*\n\n"
        f"Всього днів занурення: *{len(immersion_log)}*\n\n"
        "_Мозок обробляє мову навіть коли ти спиш 🧠_\n\n"
        "Продовжуй завтра 🔥",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 Мій план", callback_data="today_plan"),
        ]])
    )

async def cb_today_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Callback-версія /today для inline-кнопок."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    class _FakeMsg:
        async def reply_text(self_inner, *a, **kw):
            await q.message.reply_text(*a, **kw)
    class _FakeUpd:
        effective_user = user
        message = _FakeMsg()
    await cmd_today(_FakeUpd(), ctx)

async def cb_sleep_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "⏭ Добре, відпочивай 😴\n\n"
        "_Завтра спробуй — навіть 5 хв аудіо перед сном дає результат_",
        parse_mode="Markdown"
    )

# ════════════════════════════════════════════════════════════
# POLYGLOT PATCH — /phrases  Моя картотека слів і фраз
# ════════════════════════════════════════════════════════════

async def cmd_my_words(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/phrases — Персональна картотека: SRS-слова + Sentence Mining фрази."""
    user = update.effective_user
    s    = get_s(user.id)

    srs_db      = s.get("srs_words", {})
    mined       = s.get("mined_sentences", [])
    vocab_list  = s.get("vocab_learned", [])
    today       = datetime.now().strftime("%Y-%m-%d")

    # ── Розбиваємо SRS на категорії ─────────────────────────
    due_now  = []   # потрібно повторити сьогодні
    learning = []   # в процесі (interval 1–6 днів)
    strong   = []   # добре знає (interval 7+ днів)
    mined_srs = []  # зі Sentence Mining

    for word, entry in srs_db.items():
        next_rev  = entry.get("next_review", "")
        interval  = entry.get("interval_days", 0)
        is_mined  = entry.get("type") == "mined"
        is_due    = not next_rev or next_rev <= today

        if is_due:
            due_now.append(word)
        elif interval >= 7:
            strong.append(word)
        else:
            learning.append(word)

        if is_mined:
            mined_srs.append(word)

    total_srs = len(srs_db)

    # ── Повідомлення 1: Загальна статистика ─────────────────
    stat_lines = [
        "📚 *Моя картотека слів*\n",
        f"🔢 Всього слів/фраз: *{total_srs}*",
        f"🔴 Повторити сьогодні: *{len(due_now)}*",
        f"🟡 Вивчаються: *{len(learning)}*",
        f"🟢 Знаю добре: *{len(strong)}*",
        f"💎 Зі Sentence Mining: *{len(mined_srs)}*",
        f"📖 Вивчено всього: *{len(vocab_list)}*",
    ]
    kb = []
    if due_now:
        kb.append([InlineKeyboardButton(
            f"🧠 Повторити ({len(due_now)} слів)", callback_data="srs_start"
        )])
    kb.append([InlineKeyboardButton("💎 Мої фрази",   callback_data="words_show_mined")])
    kb.append([InlineKeyboardButton("🟢 Знаю добре",  callback_data="words_show_strong")])
    kb.append([InlineKeyboardButton("🔴 До повторення", callback_data="words_show_due")])

    if update.callback_query:
        await ctx.bot.send_message(
            chat_id=update.effective_user.id,
            text="\n".join(stat_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        await update.message.reply_text(
            "\n".join(stat_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )


async def cb_words_show(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показує список слів за категорією."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    srs_db = s.get("srs_words", {})
    mined  = s.get("mined_sentences", [])
    today  = datetime.now().strftime("%Y-%m-%d")
    action = q.data  # words_show_mined | words_show_strong | words_show_due

    if action == "words_show_mined":
        if not mined:
            await q.message.reply_text(
                "💎 *Збережені фрази*\n\nПоки порожньо.\n\n"
                "_Під час перегляду відео натискай «Яка фраза запала?» — і фраза збережеться тут_",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="words_back")
                ]])
            )
            return

        # Нормалізуємо: підтримуємо і старий формат (str) і новий (dict)
        def _phrase_text(entry):
            if isinstance(entry, str):  return entry
            return entry.get("phrase") or entry.get("text") or str(entry)

        def _phrase_source(entry):
            if isinstance(entry, str):  return ""
            return entry.get("lesson_title") or entry.get("source") or ""

        # Розбиваємо на сторінки по 20 фраз
        PAGE = 20
        page = int(ctx.user_data.get("phrases_page", 0))
        total = len(mined)
        chunk = mined[page*PAGE : (page+1)*PAGE]

        lines = [f"💎 *Мої фрази* ({total} всього)\n"]
        for i, entry in enumerate(chunk, page*PAGE + 1):
            phrase   = _phrase_text(entry)
            source   = _phrase_source(entry)
            srs_e    = srs_db.get(phrase, {})
            interval = srs_e.get("interval_days", 0)
            strength = "🟢" if interval >= 7 else ("🟡" if interval >= 1 else "🔴")
            src_str  = f"  _← {source[:28]}_" if source else ""
            lines.append(f"{i}. {strength} {phrase}{src_str}")

        if total > PAGE:
            lines.append(f"\n_Сторінка {page+1} з {(total-1)//PAGE + 1}_")

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"phrases_page_{page-1}"))
        if (page+1)*PAGE < total:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"phrases_page_{page+1}"))

        kb_rows = []
        if nav: kb_rows.append(nav)
        kb_rows.append([InlineKeyboardButton("🧠 Повторити всі", callback_data="srs_start")])
        kb_rows.append([InlineKeyboardButton("◀️ Назад",         callback_data="words_back")])

        try:
            await q.edit_message_text(
                "\n".join(lines),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
        except Exception:
            await q.message.reply_text(
                "\n".join(lines),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )

    elif action == "words_show_strong":
        strong = [w for w, e in srs_db.items() if e.get("interval_days", 0) >= 7]
        if not strong:
            await q.edit_message_text(
                "🟢 *Слова які знаю добре*\n\nПоки порожньо — продовжуй повторювати 🧠",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="words_back")
                ]])
            )
            return
        # Сортуємо по силі (більший інтервал = краще знає)
        strong.sort(key=lambda w: srs_db[w].get("interval_days", 0), reverse=True)
        lines = [f"🟢 *Слова які знаю добре ({len(strong)}):*\n"]
        for w in strong[:25]:
            interval = srs_db[w].get("interval_days", 0)
            label    = "💪" if interval >= 30 else ("✅" if interval >= 14 else "🟢")
            tr       = srs_db[w].get("translation", "")
            tr_str   = f" — _{tr}_" if tr else ""
            lines.append(f"{label} {w}{tr_str}")
        if len(strong) > 25:
            lines.append(f"\n_…і ще {len(strong)-25} слів_")

        await q.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="words_back")
            ]])
        )

    elif action == "words_show_due":
        due = [w for w, e in srs_db.items()
               if not e.get("next_review") or e.get("next_review", "") <= today]
        if not due:
            await q.edit_message_text(
                "🔴 *До повторення сьогодні*\n\n✅ Все повторено! Повертайся завтра 🎉",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="words_back")
                ]])
            )
            return
        lines = [f"🔴 *До повторення сьогодні ({len(due)}):*\n"]
        for w in due[:20]:
            tr     = srs_db[w].get("translation", "")
            tr_str = f" — _{tr}_" if tr else ""
            lines.append(f"• {w}{tr_str}")
        if len(due) > 20:
            lines.append(f"\n_…і ще {len(due)-20} слів_")

        await q.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧠 Повторити зараз", callback_data="srs_start")],
                [InlineKeyboardButton("◀️ Назад",           callback_data="words_back")],
            ])
        )


async def cb_show_gaps(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показує граматичні та лексичні прогалини зі збереженого аналізу."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    # Gap analysis доступний в trial і paid
    if not has_trial_feature(s, "gap_analysis"):
        await q.edit_message_text(
            "🔒 *Gap analysis — Basic і вище*\n\n"
            "Ця функція аналізує твої граматичні та лексичні прогалини "
            "після кожного монологу і підбирає відео саме під них.\n\n"
            "Доступно з пробного доступу (ланка 1+) і Basic плану.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚡️ Розблокувати", callback_data="paywall_fluent")
            ]])
        )
        return
    gaps      = s.get("pending_gaps", {})
    placement = s.get("placement_result", {})
    lines = ["🔍 *Мої прогалини — AI-аналіз*\n"]
    has_gaps = False
    if gaps:
        has_gaps = True
        lines.append("*З останнього монологу:*")
        if gaps.get("grammar_gap"):
            lines.append(f"  ⚠️ Граматика: _{gaps['grammar_gap']}_")
        if gaps.get("vocab_gap"):
            lines.append(f"  📖 Лексика: _{gaps['vocab_gap']}_")
        lines.append("")
    g_gaps = placement.get("grammar_gaps", [])
    v_gaps = placement.get("vocab_gaps", [])
    if g_gaps or v_gaps:
        has_gaps = True
        lines.append("*З діагностичного тесту:*")
        if g_gaps:
            lines.append(f"  ⚠️ Граматика: {', '.join(g_gaps)}")
        if v_gaps:
            lines.append(f"  📖 Лексика: {', '.join(v_gaps)}")
        lines.append("")
    if not has_gaps:
        lines.append("_Поки немає даних. Запиши кілька монологів — AI проаналізує твоє мовлення 🎙_")
    else:
        lines.append("_Наступне відео підбирається саме під ці прогалини автоматично_ 🎯")
    await q.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🎬 Підібрати відео під прогалини", callback_data="progress_continue"),
        ]])
    )


# ════════════════════════════════════════════════════════════
# ФІЧА 3: VOICE TIMELINE — Монологи у часі
# ════════════════════════════════════════════════════════════

async def cmd_voice_timeline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/timeline — Прогрес голосу у часі: перший vs останній + динаміка sub-scores."""
    user = update.effective_user
    s    = get_s(user.id)

    first_id    = s.get("first_voice_file_id", "")
    last_id     = s.get("last_voice_file_id", "")
    first_date  = s.get("first_voice_date", "")
    first_score = s.get("first_voice_score", 0)
    scores      = s.get("scores", [])
    timeline    = s.get("voice_timeline", [])

    if not first_id:
        await update.message.reply_text(
            "🎙 *Твій аудіо-прогрес*\n\n"
            "Запиши перший монолог — і тут з'явиться твій прогрес у звуці 🔥",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎙 Записати монолог", callback_data="remind_record")
            ]])
        )
        return

    recent_score = scores[-1].get("score", 0) if scores else first_score
    diff         = recent_score - first_score
    sign         = "+" if diff >= 0 else ""
    trend        = "📈" if diff > 0 else ("📉" if diff < 0 else "➡️")

    # ── Загальна статистика ────────────────────────────────
    lines = ["🎙 *Мій прогрес у говорінні*\n"]
    lines.append(f"Перший монолог: *{first_score}/100*  _{first_date}_")
    lines.append(f"Зараз: *{recent_score}/100*")
    lines.append(f"Зростання: *{sign}{diff} балів* {trend}\n")

    # ── Sub-score тренд ────────────────────────────────────
    pron  = s.get("last_pronunciation_score", 0)
    flu   = s.get("last_fluency_score", 0)
    gram  = s.get("last_grammar_score", 0)
    vocab = s.get("last_vocab_score", 0)
    if any([pron, flu, gram, vocab]):
        lines.append("*Останній монолог:*")
        if gram:  lines.append(f"  📐 Граматика: *{gram}/100*")
        if vocab: lines.append(f"  📚 Лексика: *{vocab}/100*")
        if flu:   lines.append(f"  🌊 Fluency: *{flu}/100*")
        if pron:  lines.append(f"  🔉 Вимова: *{pron}/100*")
        lines.append("")

    # ── Динаміка балів з останніх уроків ──────────────────
    if len(scores) >= 2:
        lines.append("*Динаміка останніх уроків:*")
        for sc in scores[-6:]:
            bar_val = sc.get("score", 0)
            bar     = "█" * (bar_val // 14) + "░" * (7 - bar_val // 14)
            lines.append(f"  Урок {sc.get('lesson_num','?')}: `{bar}` *{bar_val}*")
        lines.append("")

    # ── Timeline checkpoint'и ──────────────────────────────
    if timeline:
        lines.append("*Checkpoints кожні 5 уроків:*")
        for pt in timeline[-5:]:
            pron_str = f" 🔉{pt['pronunciation']}" if pt.get("pronunciation") else ""
            flu_str  = f" 🌊{pt['fluency']}" if pt.get("fluency") else ""
            lines.append(
                f"  Урок {pt['lesson_num']} _{pt['date']}_ — "
                f"*{pt['score']}/100*{pron_str}{flu_str}"
            )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎙 Послухати: Перший монолог", callback_data="before_after")],
            [InlineKeyboardButton("📤 Поділитись прогресом",      callback_data="share_socials")],
        ])
    )


async def cb_voice_timeline_inline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Callback-версія timeline для inline-кнопки з Прогресу."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    class _FakeMsg:
        async def reply_text(self_i, *a, **kw):
            await q.message.reply_text(*a, **kw)
    class _FakeUpd:
        effective_user = user
        message = _FakeMsg()
    await cmd_voice_timeline(_FakeUpd(), ctx)


# ════════════════════════════════════════════════════════════
# ФІЧА 2: WEEKLY CHALLENGE — 7-денний публічний челендж
# ════════════════════════════════════════════════════════════

CHALLENGE_DAYS = 7
CHALLENGE_DAY_TOPICS = [
    "Розкажи про своє ранкове рутинне. Що ти робиш першим після пробудження?",
    "Опиши найкращу книгу або фільм які ти переглядав за останній місяць.",
    "Розкажи про місце де ти виріс. Чим воно особливе для тебе?",
    "Що для тебе означає успіх? Як ти його вимірюєш?",
    "Опиши свого найкращого друга — чому він особливий?",
    "Розкажи про виклик який ти подолав і що з цього навчився.",
    "Яка твоя мрія? Що ти вже робиш щоб її досягти?",
    "Опиши ідеальний вікенд. Що б ти робив?",
    "Розкажи про традицію своєї родини яка тобі подобається.",
    "Яку пораду ти б дав собі 5 років тому?",
    "Опиши місто або країну де хотів би пожити. Чому?",
    "Розкажи про свою улюблену їжу і як її готують.",
    "Що тебе надихає? Звідки ти черпаєш мотивацію?",
    "Опиши типовий робочий або навчальний день.",
    "Яка навичка яку ти хотів би освоїти? Чому саме вона?",
    "Розкажи про подорож яка тебе змінила або запам'яталась.",
    "Як ти відпочиваєш після важкого дня?",
    "Опиши людину яка вплинула на тебе найбільше.",
    "Що робить тебе щасливим у буденному житті?",
    "Розкажи про свій улюблений вид спорту або фізичної активності.",
    "Якби міг переїхати в будь-яке місто світу — куди б поїхав?",
    "Опиши свій найбільший страх і як ти з ним справляєшся.",
    "Розкажи про технологію яка змінила твоє життя.",
    "Що ти думаєш про соціальні мережі — плюси і мінуси?",
    "Опиши ідеальну роботу або кар'єру. Що в ній важливо?",
    "Розкажи про традицію або свято яке тобі подобається.",
    "Яка музика допомагає тобі зосередитись або розслабитись?",
    "Опиши момент коли ти пишався собою.",
    "Розкажи про домашнього улюбленця або тварину яку хотів би мати.",
    "Що для тебе важливіше — кар'єра чи сім'я? Чому?",
]

def _challenge_week_key() -> str:
    """Повертає ключ поточного тижня (ISO: 2026-W24)."""
    now = datetime.now()
    return f"{now.year}-W{now.isocalendar()[1]:02d}"

def _challenge_day_num(joined_date: str) -> int:
    """Повертає день челенджу (1–7) від дати приєднання."""
    try:
        start = datetime.strptime(joined_date, "%Y-%m-%d")
        delta = (datetime.now() - start).days + 1
        return min(max(delta, 1), CHALLENGE_DAYS)
    except Exception:
        return 1

async def cmd_challenge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/challenge — 7-денний speaking challenge з таблицею лідерів."""
    user = update.effective_user
    s    = get_s(user.id)
    if not s.get("onboarding_done"):
        await (update.message or update.callback_query.message).reply_text(
            "👋 Спочатку познайомимось! Натисни /start — це займе 1 хвилину 🚀"
        )
        return

    week_key      = _challenge_week_key()
    challenge     = s.get("weekly_challenge", {})
    in_challenge  = challenge.get("week") == week_key
    joined_date   = challenge.get("joined_date", "")
    days_done     = challenge.get("days_done", 0)
    day_num       = _challenge_day_num(joined_date) if in_challenge else 0

    if not in_challenge:
        # ── Запрошення приєднатись ─────────────────────────
        db         = load_db()
        total_week = sum(
            1 for uid, st in db.items()
            if isinstance(st, dict)
            and st.get("weekly_challenge", {}).get("week") == week_key
        )
        await update.message.reply_text(
            f"🏆 <b>7-денний Speaking Challenge</b>\n\n"
            f"📝 <b>Тема дня:</b> {CHALLENGE_DAY_TOPICS[datetime.now().timetuple().tm_yday % len(CHALLENGE_DAY_TOPICS)]}\n\n"
            f"Щодня — 1 монолог на цю тему. 7 днів поспіль.\n"
            f"Учасників цього тижня: <b>{total_week}</b>\n\n"
            "Правила:\n"
            "  1️⃣ Один монолог на день (будь-яке відео)\n"
            "  2️⃣ Мінімум 30 секунд\n"
            "  3️⃣ 7 днів — отримуєш бейдж 🏅\n\n"
            "<i>Більшість студентів кидають на 3-й день. Доведи що ти не більшість.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚀 Приєднатись до челенджу", callback_data="challenge_join"),
            ]])
        )
        return

    # ── Статус учасника ────────────────────────────────────
    progress_bar = "🟢" * days_done + "⚪️" * (CHALLENGE_DAYS - days_done)
    today_done   = challenge.get("today_done") == datetime.now().strftime("%Y-%m-%d")

    status_lines = [
        f"🏆 *7-денний Challenge — День {day_num}/{CHALLENGE_DAYS}*\n",
        f"{progress_bar}",
        f"Виконано: *{days_done}/7 днів*\n",
    ]
    if today_done:
        status_lines.append("✅ Сьогодні виконано! Повертайся завтра 🔥")
    else:
        status_lines.append("🎙 Запиши монолог сьогодні — і відзнач виконання!")

    if days_done == CHALLENGE_DAYS:
        status_lines = [
            "🏅 *Ти завершив 7-денний Challenge!*\n",
            "Це вже топ-5% найдисциплінованіших студентів.\n",
            "Поділись своїм досягненням — надихни інших! 💪",
        ]

    kb = []
    if not today_done and days_done < CHALLENGE_DAYS:
        kb.append([InlineKeyboardButton("✅ Відзначити сьогоднішній день", callback_data="challenge_checkin")])
    kb.append([InlineKeyboardButton("🏆 Таблиця лідерів", callback_data="challenge_leaderboard")])
    if days_done == CHALLENGE_DAYS:
        kb.append([InlineKeyboardButton("📤 Поділитись досягненням", callback_data="share_socials")])

    await update.message.reply_text(
        "\n".join(status_lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb) if kb else main_menu()
    )


async def cb_challenge_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Приєднатись до Weekly Challenge."""
    q    = update.callback_query
    user = q.from_user
    await q.answer("🚀 Ти в грі!")
    today    = datetime.now().strftime("%Y-%m-%d")
    week_key = _challenge_week_key()
    upd_s(user.id, {
        "weekly_challenge": {
            "week":        week_key,
            "joined_date": today,
            "days_done":   0,
            "today_done":  None,
        }
    })
    await q.edit_message_text(
        "🏆 *Ти в 7-денному Challenge!*\n\n"
        "День 1 з 7. Запиши монолог сьогодні і відзнач виконання.\n\n"
        "🟢⚪️⚪️⚪️⚪️⚪️⚪️\n\n"
        "_Щодня після монологу натискай ✅ Відзначити день_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Відзначити сьогодні", callback_data="challenge_checkin"),
        ]])
    )


async def cb_challenge_checkin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Відзначає виконання дня челенджу."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()
    today     = datetime.now().strftime("%Y-%m-%d")
    week_key  = _challenge_week_key()
    challenge = s.get("weekly_challenge", {})

    if challenge.get("week") != week_key:
        await q.answer("❌ Твій челендж вже закінчився. Починай новий!", show_alert=True)
        return

    if challenge.get("today_done") == today:
        await q.answer("✅ Сьогодні вже відмічено!", show_alert=True)
        return

    days_done = challenge.get("days_done", 0) + 1
    challenge.update({"today_done": today, "days_done": days_done})
    upd_s(user.id, {"weekly_challenge": challenge})

    progress_bar = "🟢" * days_done + "⚪️" * (CHALLENGE_DAYS - days_done)

    if days_done >= CHALLENGE_DAYS:
        # ── Завершив челендж! ──────────────────────────────
        upd_s(user.id, {"badges": s.get("badges", []) + ["challenge_7day"]})
        await q.edit_message_text(
            f"🏅 *Ти завершив 7-денний Challenge!*\n\n"
            f"{progress_bar}\n\n"
            "Це топ-5% найдисциплінованіших студентів SpeakChain.\n"
            "Бейдж 🏅 додано до твого профілю!\n\n"
            "_Більшість кидали на 3-й день. Ти — ні._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📤 Поділитись досягненням", callback_data="share_socials"),
            ]])
        )
    else:
        await q.edit_message_text(
            f"✅ *День {days_done}/7 виконано!*\n\n"
            f"{progress_bar}\n\n"
            f"Залишилось: *{CHALLENGE_DAYS - days_done} дні*\n\n"
            "_Повертайся завтра_ 🔥",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏆 Таблиця лідерів", callback_data="challenge_leaderboard"),
            ]])
        )


async def cb_challenge_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Таблиця лідерів цього тижня."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    week_key = _challenge_week_key()
    db       = load_db()

    participants = []
    for uid, st in db.items():
        if not isinstance(st, dict): continue
        ch = st.get("weekly_challenge", {})
        if ch.get("week") != week_key: continue
        name      = st.get("name", f"Студент {str(uid)[-4:]}")
        days_done = ch.get("days_done", 0)
        participants.append((name, days_done))

    participants.sort(key=lambda x: x[1], reverse=True)

    lines = [f"🏆 *Таблиця лідерів — поточний тиждень*\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, days) in enumerate(participants[:10]):
        medal = medals[i] if i < 3 else f"{i+1}."
        bar   = "🟢" * days + "⚪️" * (CHALLENGE_DAYS - days)
        lines.append(f"{medal} {name}  {bar}  *{days}/7*")

    if not participants:
        lines.append("_Поки ніхто не приєднався. Будь першим! 🚀_")

    lines.append(f"\nУсього учасників: *{len(participants)}*")

    await q.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 Мій статус", callback_data="challenge_status"),
        ]])
    )


async def cb_challenge_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Callback для показу статусу челенджу."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()
    class _FMsg:
        async def reply_text(self_i, *a, **kw):
            await q.message.reply_text(*a, **kw)
    class _FUpd:
        effective_user = user
        message = _FMsg()
    await cmd_challenge(_FUpd(), ctx)


async def job_challenge_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    """Щодня о 19:00 — нагадування учасникам челенджу якщо не відзначили день."""
    db    = load_db()
    today = datetime.now().strftime("%Y-%m-%d")
    week_key = _challenge_week_key()
    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if not s.get("onboarding_done"): continue
        ch = s.get("weekly_challenge", {})
        if ch.get("week") != week_key: continue
        if ch.get("today_done") == today: continue
        if ch.get("days_done", 0) >= CHALLENGE_DAYS: continue
        days_done = ch.get("days_done", 0)
        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=(
                    f"⏰ *Challenge — день {days_done + 1}/7*\n\n"
                    "Ти ще не відзначив сьогоднішній день!\n"
                    "Запиши монолог і натисни ✅ 👇"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Відзначити день", callback_data="challenge_checkin"),
                    InlineKeyboardButton("📊 Мій прогрес",    callback_data="challenge_status"),
                ]])
            )
        except Exception as e:
            logger.warning(f"Challenge reminder failed {uid}: {e}")



async def cb_phrases_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Пагінація списку фраз: phrases_page_0, phrases_page_1, ..."""
    q    = update.callback_query
    await q.answer()
    page = int(q.data.split("_")[-1])
    ctx.user_data["phrases_page"] = page
    # Повторно викликаємо cb_words_show з action words_show_mined
    q.data = "words_show_mined"
    await cb_words_show(update, ctx)

async def cb_words_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Повертає на головний екран картотеки."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    srs_db = s.get("srs_words", {})
    today  = datetime.now().strftime("%Y-%m-%d")
    mined  = s.get("mined_sentences", [])

    due_count    = sum(1 for e in srs_db.values()
                       if not e.get("next_review") or e.get("next_review","") <= today)
    strong_count = sum(1 for e in srs_db.values() if e.get("interval_days", 0) >= 7)
    learn_count  = len(srs_db) - due_count - strong_count

    stat_lines = [
        "📚 *Моя картотека слів*\n",
        f"🔢 Всього: *{len(srs_db)}*",
        f"🔴 Повторити сьогодні: *{due_count}*",
        f"🟡 Вивчаються: *{max(0, learn_count)}*",
        f"🟢 Знаю добре: *{strong_count}*",
        f"💎 Зі Sentence Mining: *{len(mined)}*",
    ]
    kb = []
    if due_count:
        kb.append([InlineKeyboardButton(
            f"🧠 Повторити ({due_count} слів)", callback_data="srs_start"
        )])
    kb.append([InlineKeyboardButton("💎 Мої фрази",    callback_data="words_show_mined")])
    kb.append([InlineKeyboardButton("🟢 Знаю добре",   callback_data="words_show_strong")])
    kb.append([InlineKeyboardButton("🔴 До повторення", callback_data="words_show_due")])

    await q.edit_message_text(
        "\n".join(stat_lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ── /help ─────────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    s    = get_s(user.id)
    name = s.get("name") or user.first_name or ""
    greeting = f"{name}, " if name else ""

    # ── Основна інструкція (з маркетинговим підтекстом) ──────────────
    guide = (
        f"*{greeting}ось як SpeakChain веде тебе до C2* 🎯\n\n"

        "Більшість людей роками вчать англійську — і досі не можуть нормально говорити. "
        "Знають слова, знають граматику, але щойно треба щось сказати — мова не йде.\n\n"
        "SpeakChain вирішує саме це.\n\n"

        "*🎬 Крок 1 — Реальне відео замість підручника*\n"
        "Дивишся те що цікаво тобі: TED, серіал, влог. "
        "Субтитри — в плеєрі. Зачепила фраза — зберігаєш одним тапом.\n\n"

        "*🎙 Крок 2 — Shadowing*\n"
        "Чуєш фразу → повторюєш вголос → записуєш себе → чуєш різницю. "
        "Саме так мозок запам'ятовує вимову — не очима, а ротом.\n\n"
        "_«Немає часу»_ — одна фраза займає 30 секунд. "
        "П'ять на день = 2.5 хвилини. За місяць — 75 фраз в м'язовій пам'яті.\n\n"

        "*🧠 Крок 3 — Картотека яка сама нагадує*\n"
        "Фрази зберігаються автоматично. Система нагадує повторити "
        "в точний момент коли мозок вже майже забув — тоді закріплення найглибше.\n\n"
        "_«Пробував щось інше і не зайшло?»_ — Тут зібрані найдієвіші, найпростіші і найшвидші методи: ти просто дивишся і говориш, і вільне володіння прийде само з часом. "
        "Тут вони збираються поки ти просто дивишся відео.\n\n"

        "*📊 Крок 4 — Прогрес який видно*\n"
        "Рівень A1→C2, XP, стрік, граматичні теми. "
        "Не абстрактні відсотки — конкретні фрази які ти вже можеш сказати.\n\n"

        "━━━━━━━━━━━━━━━━━\n"
        "*Одне правило:* 15 хвилин щодня > 3 години раз на тиждень. Завжди.\n\n"
        "👇 *Що хочеш зробити?*"
    )

    kb = []
    if is_admin(user.id):
        kb.append([InlineKeyboardButton("🔧 Адмін-панель", callback_data="help_admin")])
    elif is_blogger(user.id):
        kb.append([InlineKeyboardButton("👤 Моя панель блогера", callback_data="help_blogger")])

    kb += [
        [InlineKeyboardButton("🎬 Почати урок",              callback_data="progress_continue")],
        [InlineKeyboardButton("📊 Мій прогрес",              callback_data="show_progress")],
        [InlineKeyboardButton("✉️ Написати адміну",          callback_data="help_ask_admin")],
        [InlineKeyboardButton("🚫 Відмовитись від підписки", callback_data="help_refuse")],
    ]

    msg = update.message if update.message else update.callback_query.message
    await msg.reply_text(guide, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def cb_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    if q.data == "help_partner":
        await q.message.reply_text(
            "👥 *Speaking Partner*\n\n"
            "Знаходимо студента з твоїм рівнем для живої розмовної практики.\n\n"
            "Напиши /partner щоб почати пошук.",
            parse_mode="Markdown"
        )
    elif q.data == "help_tutor":
        await q.message.reply_text(
            "🎓 */tutor_me — Індивідуальна програма*\n\n"
            "Отримай лексику і граматику під свою сферу: IT, медицина, бізнес та інше.\n\n"
            "Напиши /tutor_me щоб обрати профіль.",
            parse_mode="Markdown"
        )
    elif q.data == "help_settings":
        await q.message.reply_text(
            "⚙️ */settings — Налаштування*\n\n"
            "Змінити ціль навчання або рівень.\n\n"
            "Напиши /settings.",
            parse_mode="Markdown"
        )
    elif q.data == "help_offer":
        await _send_offer(q.message, ctx)
    elif q.data == "help_ask_admin":
        upd_s(user.id, {"waiting_admin_question": True})
        await q.message.reply_text(
            "✉️ *Напиши своє питання* — я передам його адміну і він відповість тобі особисто 👇",
            parse_mode="Markdown"
        )
    elif q.data == "help_refuse":
        await cmd_refuse(update, ctx)
    elif q.data == "help_privacy":
        await cmd_privacy(update._get_message_update() if hasattr(update, '_get_message_update') else update, ctx)
        if PRIVACY_FILE_ID:
            await q.message.reply_document(
                document=PRIVACY_FILE_ID,
                caption="🔒 Політика конфіденційності SpeakChain"
            )
        else:
            await q.message.reply_text("Напиши /privacy для отримання документу.")
    elif q.data == "help_blogger" and is_blogger(user.id):
        await cmd_my_students(q, ctx)
    elif q.data == "help_admin" and ADMIN_ID and user.id == ADMIN_ID:
        await q.message.reply_text(
            "🔧 Admin Panel — команди:\n\n"
            "/admin — статистика бота\n"
            "/myid — твій Telegram ID\n"
            "/admin_refs — статистика рефералів\n"
            "/admin_partners — черга speaking partner\n"
            "/setpremium ID DAYS — активувати Premium\n"
            "/gen_ref @username — посилання для блогера\n"
            "/create_blogger_code @username — код для блогера\n"
            "/list_bloggers — список блогерів\n"
            "/view_blogger @username — дашборд блогера\n"
            "/blogger — панель блогера за кодом\n"
            "/set_challenge Тема — запустити challenge",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Статистика",      callback_data="adm_cmd_admin")],
                [InlineKeyboardButton("🔗 Реферали",        callback_data="adm_cmd_refs"),
                 InlineKeyboardButton("👥 Партнери",        callback_data="adm_cmd_partners")],
                [InlineKeyboardButton("👥 Блогери",         callback_data="adm_cmd_list_bloggers")],
            ])
        )

async def cb_admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обробляє кнопки Admin Panel."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    # Захист — тільки адмін
    if not is_admin(user.id):
        await q.answer("⛔️ Доступ заборонено.", show_alert=True)
        return

    if q.data == "adm_cmd_admin":
        # Simulate message update for admin command
        class FakeUpdate:
            effective_user = q.from_user
            message = q.message
        await cmd_admin(FakeUpdate(), ctx)
    elif q.data == "adm_cmd_refs":
        class FakeUpdate:
            effective_user = q.from_user
            message = q.message
        await cmd_admin_refs(FakeUpdate(), ctx)
    elif q.data == "adm_cmd_partners":
        class FakeUpdate:
            effective_user = q.from_user
            message = q.message
        await cmd_admin_partners(FakeUpdate(), ctx)
    elif q.data == "adm_cmd_list_bloggers":
        class FakeUpdate:
            effective_user = q.from_user
            message = q.message
        await cmd_view_blogger(FakeUpdate(), ctx)
    elif q.data == "adm_cmd_offer":
        if OFFER_FILE_ID:
            await q.message.reply_document(
                document=OFFER_FILE_ID,
                caption="📄 Публічна оферта SpeakChain"
            )
        else:
            await q.message.reply_text("Файл оферти не завантажено. Додай OFFER_FILE_ID в Railway.")
    elif q.data == "adm_cmd_privacy":
        if PRIVACY_FILE_ID:
            await q.message.reply_document(
                document=PRIVACY_FILE_ID,
                caption="🔒 Політика конфіденційності SpeakChain"
            )
        else:
            await q.message.reply_text("Файл не завантажено. Додай PRIVACY_FILE_ID в Railway.")
    elif q.data == "adm_cmd_challenge":
        await q.message.reply_text(
            "🏆 Введи тему челенджу:\n\n`/set_challenge Тема`",
            parse_mode="Markdown"
        )
    elif q.data == "adm_broadcast":
        await q.message.reply_text(
            "📢 *Розсилка*\n\n"
            "Використання:\n"
            "`/broadcast Текст`\n"
            "`/broadcast promo Текст`\n"
            "`/broadcast blogger @name Текст`\n\n"
            "Типи: `system` · `blogger` · `chain` · `promo`",
            parse_mode="Markdown"
        )

# ── Auto-send next lesson (після онбоардингу і далі) ─
def _build_lesson_card(lesson: dict, s: dict) -> str:
    """Будує текст єдиної картки уроку: відео + shadowing + завдання."""
    title    = lesson.get("title", "")
    channel  = lesson.get("channel", "")
    grammar  = lesson.get("grammar", "")
    topic    = lesson.get("topic", "")
    hint     = lesson.get("hint", "")
    cefr     = lesson.get("cefr_topic", "")
    gap_used = lesson.get("gap_used", False)

    # Shadowing фрази з підказки
    phrases  = [p.strip() for p in hint.replace("/ ", "\n").split("\n") if len(p.strip()) > 4][:2]

    lines = []

    # ── Заголовок ──────────────────────────────────────────
    lines.append(f"🎬 *{title}*")
    if channel:
        lines.append(f"_📺 {channel}_")
    if cefr:
        label = "⚠️ Підібрано під прогалину:" if gap_used else "🎯"
        lines.append(f"{label} _{cefr}_")
    lines.append("")

    # ── Shadowing ──────────────────────────────────────────
    lines.append("🔊 *SHADOWING — повтори за спікером*")
    lines.append("1️⃣ Слухай відео мовчки")
    lines.append("2️⃣ Постав паузу — повтори кожне речення вголос")
    lines.append("3️⃣ Говори *одночасно* зі спікером")
    lines.append("")

    # ── Граматика (один раз) ───────────────────────────────
    if grammar:
        lines.append(f"📌 _{grammar}_")
        lines.append("")

    # ── Завдання монологу ──────────────────────────────────
    if topic:
        lines.append(f"🎤 {topic}")
    if phrases:
        for p in phrases:
            lines.append(f"  ▸ _{p}_")
    lines.append("")

    lines.append("_Відчувай ритм мови — не кожне слово. Говори вголос 🗣_")

    return "\n".join(lines)


async def _send_merged_lesson_card(bot, user_id: int, lesson: dict, s: dict):
    """Надсилає одну картку: відео + shadowing + кнопки."""
    vid_id   = extract_youtube_id(lesson["url"])
    platform = detect_platform(lesson["url"])

    if WEBAPP_URL and vid_id and platform == "youtube":
        watch_btn = InlineKeyboardButton(
            "▶️ Дивитись відео",
            web_app={"url": _player_url(lesson["url"], s)}
        )
    else:
        watch_btn = InlineKeyboardButton("▶️ Дивитись відео", url=lesson["url"])

    await bot.send_message(
        chat_id=user_id,
        text=_build_lesson_card(lesson, s),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [watch_btn],
            [InlineKeyboardButton("🔊 Повторив — записую монолог 🎙", callback_data="shadow_done")],
        ])
    )


async def _auto_send_next_lesson(bot, user_id: int):
    """Одна картка: відео + shadowing + завдання. Sentence Mining — автоматично з монологу."""
    s = get_s(user_id)
    if not s.get("level"):
        upd_s(user_id, {"level": "A1", "done_lessons": [], "scores": [], "mastered_grammar": []})
        s = get_s(user_id)
    lesson = await youtube_search_lesson(s)
    if not lesson:
        await bot.send_message(
            chat_id=user_id,
            text="Натисни *🎬 Наступне відео* щоб продовжити навчання 🎬",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        return
    upd_s(user_id, {
        "current_lesson_id":    lesson["id"],
        "current_lesson_data":  lesson,
        "current_lesson_title": lesson.get("title", "відео"),
    })
    s = get_s(user_id)
    await _send_merged_lesson_card(bot, user_id, lesson, s)

# ── Next-video fork keyboard ──────────────────────────
def next_video_fork_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📎 Я сам обрав відео", callback_data="fork_own"),
    ]])

async def cb_fork(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    if q.data == "rescue_choose":
        # Streak rescue — вибір між відео і SRS перед монологом
        await q.answer()
        s2      = get_s(user.id)
        streak  = s2.get("streak_days", 0)
        has_srs = bool(_srs_due_words(s2))
        kb = []
        if has_srs:
            kb.append([InlineKeyboardButton("🧠 Повторити фрази (SRS)", callback_data="rescue_srs")])
        kb.append([InlineKeyboardButton("📺 Подивитись нове відео",  callback_data="fork_choose")])
        await q.edit_message_text(
            f"🔥 Стрік *{streak} дн.* ще живий!\n\n"
            "Обери з чого почати — і після цього запишемо монолог 🎙",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif q.data == "rescue_srs":
        # Показати 5 фраз з SRS перед монологом
        await q.answer()
        s2   = get_s(user.id)
        due  = _srs_due_words(s2)[:3]   # беремо 3
        if not due:
            await q.edit_message_text(
                "✅ Всі фрази вже повторені сьогодні!\n\n"
                "Тоді одразу до монологу 🎙",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🎙 Записати монолог", callback_data="remind_record"),
                ]])
            )
            return
        srs_db     = s2.get("srs_words", {})
        words_data = []
        for w in due:
            entry = srs_db.get(w["word"], {})
            words_data.append({
                "word":        w["word"],
                "translation": entry.get("translation", ""),
                "example":     entry.get("example", ""),
            })
        upd_s(user.id, {
            "vocab_session_words_data": words_data,
            "vocab_session_words":      [w["word"] for w in due],
            "vocab_session_idx":        0,
            "vocab_session_known":      0,
            "vocab_session_total":      len(due),
            "vocab_done":               False,
            "srs_session_active":       True,
            "srs_after_rescue":         True,   # щоб після SRS запропонувати монолог
        })
        await q.edit_message_text(
            f"🧠 *Повторення фраз — {len(due)} з 3*\n\n"
            "Натискай ✅ якщо пам'ятаєш, 📖 якщо ні 👇",
            parse_mode="Markdown"
        )
        await send_vocab_card(ctx.bot, user.id, words_data, 0)

    elif q.data == "remind_record":
        await q.answer()
        s2      = get_s(user.id)
        phrases = s2.get("mined_sentences", [])
        hint_phrases = phrases[-5:] if phrases else []
        if hint_phrases:
            phrases_text = "\n".join(f"• _{p}_" for p in hint_phrases[-5:])
            hint = (
                f"💡 *Ось твої останні фрази — використай їх:*\n\n"
                f"{phrases_text}\n\n"
            )
        else:
            hint = "💡 *Говори на будь-яку тему* — що робив сьогодні, плани, думки.\n\n"
        await q.edit_message_text(
            f"{hint}"
            "🎙 Запиши голосовий монолог 30–60 секунд англійською.\n"
            "AI оцінить вимову і дасть фідбек 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📺 Краще подивлюсь відео", callback_data="fork_choose"),
            ]])
        )


    elif q.data == "duel_video_mode":
        await q.answer()
        await q.edit_message_text(
            "🎬 *Відео дуель!*\n\n"
            "Запиши коротке відео (30–60 сек) на тему виклику.\n\n"
            "Натисни 📎 → «Відео» або запиши відеоповідомлення (кружечок) 👇",
            parse_mode="Markdown"
        )
        # Статус вже встановлено в duel_accept

    elif q.data == "duel_cancel":
        await q.answer("Скасовано")
        await q.edit_message_text(
            "❌ Виклик скасовано.\n\nПрактикуй далі — і кидай виклики! 💪",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎙 Ще практикувати", callback_data="fork_choose"),
            ]])
        )

    elif q.data == "phrase_skip":
        await q.answer("Добре, побачимось завтра! 👋")
        await q.edit_message_text(
            "⏭ *Зрозуміло!*\n\nФраза дня чекатиме завтра вранці 🌅",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎬 Почати урок", callback_data="fork_choose"),
            ]])
        )

    elif q.data == "rescue_done":
        await q.answer()
        streak = s.get("streak_days", 0)
        await q.edit_message_text(
            f"✅ *Відмінна робота сьогодні!*\n\n"
            f"🔥 Стрік: *{streak} дн.*\n\n"
            "Побачимось завтра — практикуємо далі! 💪",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📊 Мій прогрес", callback_data="show_progress"),
            ]])
        )

    elif q.data == "fork_choose":
        videos_watched = s.get("videos_watched", 0)
        # Онбоардинг — лише один раз, після 2-го відео
        if not s.get("onboarding_done") and videos_watched >= 2:
            upd_s(user.id, {"onboarding_triggered": True})
            await q.edit_message_text(
                "Перш ніж підібрати відео — кілька швидких питань 🎯\n\n"
                "Для чого тобі потрібна англійська? 👇",
                parse_mode="Markdown",
                reply_markup=goal_kb()
            )
        else:
            await q.edit_message_text("🔍 Підбираю відео...")
            await _auto_send_next_lesson(ctx.bot, user.id)

    elif q.data == "fork_own":
        upd_s(user.id, {"waiting_video": True})
        await q.edit_message_text(
            "Надішли посилання на відео:\n"
            "• 🎬 YouTube\n\n👇",
            parse_mode="Markdown"
        )

# ── Handle voice / audio ──────────────────────────────
async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    s    = get_s(user.id)
    logger.info(f"VOICE received from {user.id} {user.first_name}")

    # ── Голосовий коментар блогера студенту ──
    if s.get("pending_voice_comment_to"):
        handled = await handle_blogger_voice_comment(update, ctx)
        if handled:
            return

    # ── Відео-привітання блогера ──────────────────────────
    if is_blogger(user.id) and get_s(user.id).get("waiting_welcome_video"):
        handled = await handle_blogger_welcome_media(update, ctx)
        if handled:
            return

    # ── Відео-питання тижня від блогера ──────────────────
    if is_blogger(user.id) and get_s(user.id).get("waiting_wq_video"):
        handled = await handle_blogger_wq_video(update, ctx)
        if handled:
            return

    # ── Відповідь на питання тижня ──────────────────────
    if s.get("waiting_wq_voice") and (update.message.voice or update.message.audio):
        upd_s(user.id, {"waiting_wq_voice": False})
        question = s.get("wq_question", "")
        file_id  = update.message.voice.file_id if update.message.voice else update.message.audio.file_id
        upd_s(user.id, {"pending_voice_file_id": file_id})
        # Відмічаємо питання як відповіджене
        wq_hist = s.get("weekly_questions_received", [])
        week_key = datetime.now().strftime("%Y-%W")
        for wq in wq_hist:
            if wq.get("week") == week_key:
                wq["answered"] = True
        upd_s(user.id, {"weekly_questions_received": wq_hist})
        await update.message.reply_text(
            f"✅ Запис отримано!\n\n_{question}_\n\n"
            "Надсилаю на AI оцінку 🎙",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Оцінити мою відповідь", callback_data="voice_submit")
            ]])
        )
        return

    # ── Фідбек блогера на challenge запис ──
    if is_blogger(user.id) and s.get("pending_fb_reply_to"):
        await handle_blogger_feedback_voice(update, ctx)
        return

    # ── Відео від студента → перенаправляємо в handle_video ──────────
    if update.message.video or update.message.video_note:
        await handle_video(update, ctx)
        return

    # Підтримуємо і voice і audio повідомлення
    if update.message.voice:
        file_id  = update.message.voice.file_id
        duration = update.message.voice.duration
    elif update.message.audio:
        file_id  = update.message.audio.file_id
        duration = update.message.audio.duration or 0
    else:
        await update.message.reply_text("Надішли голосове повідомлення 🎤")
        return

    # ── Автозбір file_id для placement test аудіо ──────
    # Адмін може надсилати і як voice і як audio file
    empty_keys = [k for k, v in PLACEMENT_AUDIO.items() if not v]
    is_admin_upload = bool(is_admin(user.id) and empty_keys)

    if is_admin_upload:
        ids_path = Path("audio_ids.json")
        collected = json.loads(ids_path.read_text()) if ids_path.exists() else {}
        next_key  = next((k for k in ["A1","A2","B1","B2","C1"] if not collected.get(k)), None)
        if next_key:
            collected[next_key] = file_id
            ids_path.write_text(json.dumps(collected, indent=2))
            remaining = [k for k in ["A1","A2","B1","B2","C1"] if not collected.get(k)]
            msg = (
                f"✅ *Аудіо збережено!*\n\n"
                f"Рівень: *{next_key}*\n"
                f"file\\_id: `{file_id}`\n\n"
            )
            if remaining:
                msg += f"Залишилось завантажити: *{', '.join(remaining)}*\n\nНадішли наступний файл 👇"
            else:
                # Всі зібрані — вставляємо в PLACEMENT_AUDIO автоматично
                for k, v in collected.items():
                    PLACEMENT_AUDIO[k] = v
                # Зберігаємо у файл конфігурації
                Path("placement_audio_config.json").write_text(
                    json.dumps(collected, indent=2)
                )
                msg += (
                    "🎉 *Всі 5 аудіо завантажено!*\n\n"
                    "file\\_id збережено у `placement_audio_config.json`\n\n"
                    "Тест на визначення рівня готовий до роботи ✅"
                )
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

    # ── Якщо level не встановлено — даємо A1 за замовчуванням ──
    if not s.get("level"):
        upd_s(user.id, {"level": "A1"})
        s = get_s(user.id)

    upd_s(user.id, {"pending_voice_file_id": file_id})
    remaining = get_analyses_remaining(get_s(user.id))

    await update.message.reply_text(
        "🎤 *Запис отримано!*\n\n"
        "Прослухай його вище 👆\n\n"
        + ("🤖 Готовий до AI-аналізу 👇" if remaining > 0
           else "⚠️ Ліміт аналізів на сьогодні вичерпано — спробуй завтра"),
        parse_mode="Markdown",
        reply_markup=voice_review_kb(remaining)
    )

# ── Voice review callbacks ─────────────────────────────
async def cb_voice_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    if q.data == "voice_limit_info":
        await q.answer("⚠️ Ліміт AI-аналізів: 3 на день. Оновиться завтра.", show_alert=True)
        return

    if q.data == "voice_retry":
        upd_s(user.id, {"pending_voice_file_id": None})
        await q.edit_message_text(
            "🔄 *Запиши ще раз!*\n\n"
            "🎙 Натисни мікрофон у полі введення → говори → відпусти.\n\n"
            "_Новий запис з'явиться тут автоматично._",
            parse_mode="Markdown"
        )
        return

    if q.data == "voice_text_mode":
        upd_s(user.id, {"waiting_text_monologue": True})
        await q.edit_message_text(
            "✍️ *Напиши свій монолог текстом*\n\n"
            "Напиши кілька речень англійською про тему відео — і надішли як звичайне повідомлення 👇",
            parse_mode="Markdown"
        )
        return

    # voice_submit — AI оцінка голосового запису
    file_id   = s.get("pending_voice_file_id")
    lesson_id = s.get("current_lesson_id")
    level     = s.get("level","A1")
    today_ai  = datetime.now().strftime("%Y-%m-%d")

    if q.data == "voice_submit" and file_id:
        msg = await q.edit_message_text(
            "🎙 *Аналізую твій запис…*\n\n_AI слухає — це займе кілька секунд_",
            parse_mode="Markdown"
        )
        try:
            # Завантажуємо голосовий файл
            tg_file   = await ctx.bot.get_file(file_id)
            import io as _io, tempfile, os as _os, httpx as _httpx
            voice_buf = _io.BytesIO()
            await tg_file.download_to_memory(voice_buf)
            voice_buf.seek(0)

            lesson = s.get("voice_lesson_data") or s.get("current_lesson_data") or {}
            topic  = lesson.get("topic","Speak freely about what you watched")
            hint   = lesson.get("hint","")
            lvl    = LEVEL_NAMES.get(level, level)

            # ── Крок 1: Транскрипція через Whisper ──────────────
            transcript = None
            openai_key = os.environ.get("OPENAI_API_KEY", "")
            if openai_key:
                try:
                    voice_buf.seek(0)
                    resp = _httpx.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {openai_key}"},
                        data={"model": "whisper-1", "language": "en"},
                        files={"file": ("audio.ogg", voice_buf, "audio/ogg")},
                        timeout=60
                    )
                    if resp.status_code == 200:
                        transcript = resp.json().get("text", "").strip()
                        logger.info(f"Whisper OK uid={user.id}: {transcript[:60]}")
                    else:
                        logger.warning(f"Whisper error {resp.status_code}: {resp.text[:200]}")
                except Exception as e:
                    logger.warning(f"Whisper exception uid={user.id}: {e}")

            if not transcript:
                await msg.edit_text(
                    "🎙 *Запис отримано!*\n\n"
                    "Транскрипція тимчасово недоступна.\n\n"
                    "✍️ Напиши текстом що ти сказав(ла) — і я оціню твій монолог 👇",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⌨️ Написати текстом", callback_data="voice_text_mode"),
                        InlineKeyboardButton("🔁 Записати знову",   callback_data="voice_retry"),
                    ]])
                )
                return

            # ── Крок 2: Оцінка через Claude (текст) ─────────────
            prompt = (
                f"An English learner (level {lvl}) recorded a spoken monologue.\n"
                f"Topic: {topic}\n"
                f"Hint given: {hint}\n\n"
                f"Their transcribed speech:\n\"{transcript}\"\n\n"
                "Evaluate their spoken English based on the transcript.\n"
                "Find the ONE most important real mistake.\n"
                "RULE: Never suggest changing a grammatically correct tense.\n\n"
                "Write in Ukrainian. Warm, simple, no jargon.\n\n"
                "FORMAT (keep emoji and bold):\n"
                "🎯 *Загальний бал: X/100*\n\n"
                "✅ *Що вийшло добре:*\n"
                "[1-2 речення, процитуй їхні слова]\n\n"
                "🔧 *Що виправити:*\n"
                "Сказав: \"[точна фраза з транскрипту]\"\n"
                "Правильно: \"[виправлена фраза]\"\n"
                "Чому: [просте пояснення]\n\n"
                "🚀 *Спробуй наступного разу:*\n"
                "[одне конкретне речення]\n\n"
                "Max 130 words. If score>=75 add: 🌟 Опублікуй з #SpeakChain!"
            )

            cr = claude_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}]
            )
            feedback = cr.content[0].text

            # Зберігаємо транскрипт
            upd_s(user.id, {"last_voice_transcript": transcript})

            # ── used_in_free: перевіряємо чи студент вжив граматичні структури ──
            try:
                import asyncio as _aio
                _aio.create_task(_detect_used_in_free(user.id, transcript))
            except Exception as _e:
                logger.warning(f"used_in_free task error: {_e}")

            # Витягуємо бал
            score = 0
            for line in feedback.split("\n"):
                if "загальний бал" in line.lower():
                    nums = re.findall(r'\b(\d{1,3})\b', line)
                    for n in nums:
                        if 0 < int(n) <= 100: score = int(n); break
                    if score: break

            upd_s(user.id, {
                "last_voice_score": score,
                "last_voice_feedback": feedback,
            })

            # XP одразу — щоб прогрес-бар показував актуальний стан
            asyncio.create_task(award_xp(ctx.bot, user.id, "session"))
            if s.get("last_date") != today_ai:
                asyncio.create_task(award_xp(ctx.bot, user.id, "first_of_day"))
            streak_b = update_streak(user.id)
            if streak_b:
                asyncio.create_task(award_xp(ctx.bot, user.id, streak_b))

            # Будуємо прогрес-бар з актуальним XP
            s_fresh    = get_s(user.id)
            prog_bar   = build_level_progress_bar(s_fresh)

            # Рейтинг серед студентів блогера
            blogger_name = s_fresh.get("affiliate_blogger", "")
            if blogger_name:
                asyncio.ensure_future(send_rank_update(ctx.bot, user.id, blogger_name, load_db()))

            # Завершення дуелі якщо студент відповідав на виклик
            pending_duel = s_fresh.get("pending_duel_id", "")
            if pending_duel and score > 0:
                upd_s(user.id, {"pending_duel_id": None, "duel_topic": None})
                asyncio.ensure_future(_complete_duel(ctx.bot, pending_duel, score, user.id))

            # Зберігаємо результат blogger challenge якщо активний
            if s_fresh.get("blogger_challenge_active") and score > 0:
                ch_bname = s_fresh.get("blogger_challenge_blogger", "")
                ch_topic = s_fresh.get("blogger_challenge_topic", "")
                if ch_bname:
                    db_ch  = load_db()
                    challs = db_ch.get("_blogger_challenges", {})
                    ch_key = ch_bname.lower()
                    if ch_key in challs:
                        week_key = datetime.now().strftime("%Y-%W")
                        subs = challs[ch_key].get("submissions", [])
                        # Оновлюємо або додаємо
                        existing = next((i for i,x in enumerate(subs)
                                         if str(x.get("uid")) == str(user.id)
                                         and x.get("week") == week_key), None)
                        entry = {
                            "uid":   str(user.id),
                            "name":  s_fresh.get("name", user.first_name),
                            "score": score,
                            "date":  datetime.now().strftime("%Y-%m-%d"),
                            "week":  week_key,
                        }
                        if existing is not None:
                            if score > subs[existing].get("score", 0):
                                subs[existing] = entry  # зберігаємо кращий результат
                        else:
                            subs.append(entry)
                        challs[ch_key]["submissions"] = subs
                        db_ch["_blogger_challenges"]  = challs
                        save_db(db_ch)
                        upd_s(user.id, {"blogger_challenge_active": False})
                        logger.info(f"Blogger challenge score saved: uid={user.id} bname={ch_bname} score={score}")

            # Завершення rescue-флоу — подяка і вибір
            if s.get("streak_rescue_date") == today_ai:
                streak_now = s_fresh.get("streak_days", 0)
                import random as _rnd2
                thanks = _rnd2.choice([
                    "Стрік врятовано — ти молодець!",
                    "Ось це так практика! Стрік живий!",
                    "Зробив — і правильно зробив!",
                    "Це і є справжня послідовність!",
                ])
                asyncio.ensure_future(ctx.bot.send_message(
                    chat_id=user.id,
                    text=(
                        f"🔥 *{thanks}*\n\n"
                        f"Стрік: *{streak_now} дн.* збережено ✅\n\n"
                        "Що далі?"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🚀 Ще займаємось!", callback_data="fork_choose")],
                        [InlineKeyboardButton("✅ На сьогодні все",  callback_data="rescue_done")],
                    ])
                ))
            streak_now = s_fresh.get("streak_days", 0)
            streak_line = f"\n🔥 Стрік: *{streak_now} дн.*" if streak_now > 1 else ""

            # Показуємо кнопку дуелі якщо є блогер і є опоненти
            has_blogger  = bool(s_fresh.get("affiliate_blogger"))
            duel_kb_row  = [InlineKeyboardButton("⚔️ Кинути виклик", callback_data="duel_challenge")] if has_blogger else []

            kb_rows = [[InlineKeyboardButton("📹 В Community",       callback_data="share_voice_confirm")],
                       [InlineKeyboardButton("🔁 Записати ще раз",  callback_data="voice_retry"),
                        InlineKeyboardButton("📊 Мій прогрес",      callback_data="show_progress")]]
            if duel_kb_row:
                kb_rows.append(duel_kb_row)

            await msg.edit_text(
                f"🎙 *Оцінка голосового*\n\n{feedback}\n\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{prog_bar}"
                f"{streak_line}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
            return

        except Exception as e:
            logger.warning(f"Voice AI eval error uid={user.id}: {e}")
            await msg.edit_text(
                "🎙 *Запис отримано!*\n\n"
                "_AI-аналіз тимчасово недоступний — спробуй пізніше_\n\n"
                "Продовжуй практикуватись! 💪",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔁 Записати ще раз", callback_data="voice_retry")],
                ])
            )
            return



    # XP за сесію говоріння
    asyncio.create_task(award_xp(ctx.bot, user.id, "session"))
    # Бонус за перший урок дня
    if s.get("last_date") != today:
        asyncio.create_task(award_xp(ctx.bot, user.id, "first_of_day"))
    # Стрік-бонуси (update_streak повертає reason якщо є milestone)
    streak_bonus = update_streak(user.id)
    if streak_bonus:
        asyncio.create_task(award_xp(ctx.bot, user.id, streak_bonus))

    if not file_id:
        await q.edit_message_text("Помилка: аудіо не знайдено. Надішли голосове знову.")
        return

    # Знаходимо урок — спочатку з збережених даних, потім з бібліотеки
    lesson = None
    if lesson_id == "custom" and s.get("custom_video_url"):
        lesson = {
            "id":"custom","url":s["custom_video_url"],
            "title":"Твоє відео",
            "topic":"Speak about the main idea of the video you watched",
            "grammar":"Present Simple + I think / I believe",
            "hint":"In this video I learned... / I think... / I found it interesting that..."
        }
    elif s.get("voice_lesson_data"):
        # Урок зафіксований в момент натискання кнопки "Записати монолог"
        lesson = s["voice_lesson_data"]
    elif s.get("current_lesson_data"):
        # Fallback — поточний урок
        lesson = s["current_lesson_data"]
    elif lesson_id:
        for l in get_lessons(s):
            if l["id"] == lesson_id:
                lesson = l; break
    if not lesson:
        lesson = {
            "id": "default",
            "url": "",
            "title": "Відео",
            "topic": "Talk about what you learned from the video",
            "grammar": "Present Simple",
            "hint": "I think... / In my opinion... / I found it interesting that..."
        }

    await q.edit_message_text("🎤 Аналізую запис... (~30 сек)")

    try:
        # Завантажуємо аудіо з Telegram
        vf = await ctx.bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await vf.download_to_drive(tmp.name)
            path = tmp.name

        transcript = None

        # Спроба 1: OpenAI Whisper (якщо є ключ)
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            try:
                import httpx
                with open(path, "rb") as af:
                    resp = httpx.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {openai_key}"},
                        data={"model": "whisper-1", "language": "en"},
                        files={"file": ("audio.ogg", af, "audio/ogg")},
                        timeout=60
                    )
                if resp.status_code == 200:
                    transcript = resp.json().get("text", "").strip()
                    logger.info(f"Whisper OK: {transcript[:50]}")
            except Exception as e:
                logger.warning(f"Whisper error: {e}")

        # Спроба 2: Claude з описом (без аудіо — просимо студента написати)
        if not transcript:
            os.unlink(path)
            await q.edit_message_text(
                "✍️ *Транскрипція недоступна*\n\n"
                "Напиши що ти сказав(ла) англійською — і я оціню твій монолог 👇",
                parse_mode="Markdown"
            )
            upd_s(user.id, {"waiting_text_monologue": True})
            return

        os.unlink(path)

    except Exception as e:
        logger.error(f"Voice download error uid={user.id}: {e}")
        await q.edit_message_text(
            "😔 Помилка завантаження аудіо. Спробуй ще раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Спробувати ще раз", callback_data="voice_retry")
            ]])
        )
        return

    if len(transcript) < 5:
        await q.edit_message_text("😅 Не вдалося розпізнати. Говори голосніше і надішли ще раз.")
        return

    await q.edit_message_text("✅ Транскрипція готова! Оцінюю...")

    try:
        interests = s.get("interests", [])
        profession = s.get("profession", "")
        personal_context = ""
        if interests or profession:
            parts = []
            if profession: parts.append(f"profession: {profession}")
            if interests:  parts.append(f"interests: {', '.join(interests)}")
            personal_context = f"Student background — {'; '.join(parts)}.\n"

        recording_mode = s.get("recording_mode", "shadowing")
        # Скидаємо режим після оцінки
        upd_s(user.id, {"recording_mode": "monologue"})

        if recording_mode == "shadowing":
            # ── Shadowing: тільки вимова, ритм, інтонація ──
            prompt = f"""You are a friendly English pronunciation coach. Evaluate the student's shadowing recording and give feedback in Ukrainian.

Student level: {level}.
Student said: \"\"\"{transcript[:600]}\"\"\"

This is a SHADOWING exercise — the student repeated phrases after a speaker. Do NOT evaluate grammar or vocabulary. Focus ONLY on:
- Pronunciation (sounds, stress, vowels, consonants)
- Intonation (rising/falling patterns, natural melody)
- Rhythm and connected speech (linking words, weak forms)
- Fluency and pace (smooth delivery, hesitations)

FORMAT (keep emoji, bold, exact sub-score lines):
🎯 *Загальний бал: X/100*
└ 🔉 Вимова: X | 🎵 Інтонація: X | 🌊 Ритм: X | ⚡️ Fluency: X

✅ *Що звучить добре:*
[1-2 речення — конкретно, що саме]

🔧 *Над чим попрацювати:*
Звучить як: "[як студент сказав]"
Має звучати: "[правильно]"
Порада: [одне просте речення про вимову/інтонацію]

🚀 *Спробуй ще раз:*
[одне конкретне що зробити в наступному повторі]

Max 120 words. Warm, encouraging tone. Never mention grammar."""

        else:
            # ── Вільний монолог: повний аналіз ──
            prompt = f"""You are a friendly English speaking coach. Evaluate the student's monologue and give feedback in Ukrainian.

Student level: {level}.
Student said: \"\"\"{transcript[:600]}\"\"\"

Evaluate four areas and give each a score out of 100:
- Grammar (correctness of tenses, structure)
- Vocabulary (range, appropriateness)
- Fluency (natural flow, connected speech, hesitations)
- Pronunciation (based on word choices, patterns, common L1 Ukrainian interference errors)

Find the ONE most important real mistake — something genuinely wrong.
RULE: Never suggest changing a grammatically correct tense. Past Simple for past events is always correct.

Write in Ukrainian. Warm, simple, no jargon.

FORMAT (keep emoji, bold, and exact sub-score lines):
🎯 *Загальний бал: X/100*
└ 📐 Граматика: X | 📚 Лексика: X | 🌊 Fluency: X | 🔉 Вимова: X

✅ *Що вийшло добре:*
[1-2 речення — конкретно, процитуй їхні слова]

🔧 *Що виправити:*
Сказав: "[точна фраза студента]"
Правильно: "[виправлена фраза]"
Чому: [одне просте речення]

🚀 *Спробуй наступного разу:*
[одне конкретне речення що потренувати]

Max 150 words. If score>=75 add: 🌟 Опублікуй з #SpeakChain!"""

        cr = claude_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=600,
            messages=[{"role":"user","content":prompt}]
        )
        feedback = cr.content[0].text

        score = 0
        for line in feedback.split("\n"):
            if "загальний бал" in line.lower():
                nums = re.findall(r'\b(\d{1,3})\b', line)
                for n in nums:
                    if 0 < int(n) <= 100: score = int(n); break
                if score: break

        done = s.get("done_lessons",[])
        if lesson_id and lesson_id != "custom" and lesson_id not in done:
            done.append(lesson_id)

        # Оновлюємо пройдені граматичні теми
        mastered = s.get("mastered_grammar", [])
        grammar_focus = lesson.get("grammar","")
        if grammar_focus:
            level_topics = CEFR_GRAMMAR.get(level, [])
            for topic in level_topics:
                if any(kw.lower() in grammar_focus.lower() for kw in topic.split()[:2]) and topic not in mastered:
                    mastered.append(topic)

        scores = s.get("scores",[])
        scores.append({"lesson_num":len(done),"level":level,"score":score,
                       "date":datetime.now().isoformat()})
        # ── Витягуємо sub-scores з feedback ──────────────────────
        pronunciation_score = 0
        fluency_score       = 0
        grammar_score       = 0
        vocab_score         = 0
        for line in feedback.split("\n"):
            if "вимова" in line.lower() or "pronunciation" in line.lower():
                nums = re.findall(r'\b(\d{1,3})\b', line)
                if nums: pronunciation_score = int(nums[-1])
            if "fluency" in line.lower() or "ритм" in line.lower():
                nums = re.findall(r'\b(\d{1,3})\b', line)
                if nums: fluency_score = int(nums[-1])
            if "граматика" in line.lower():
                nums = re.findall(r'\b(\d{1,3})\b', line)
                if nums: grammar_score = int(nums[-1])
            if "лексика" in line.lower():
                nums = re.findall(r'\b(\d{1,3})\b', line)
                if nums: vocab_score = int(nums[-1])
            if "інтонація" in line.lower():
                nums = re.findall(r'\b(\d{1,3})\b', line)
                if nums and not fluency_score: fluency_score = int(nums[-1])

        upd_s(user.id, {
            "done_lessons":done,"scores":scores,
            "mastered_grammar": mastered,
            "current_lesson_id":None,
            "pending_voice_file_id": None,
            "last_date":datetime.now().isoformat()[:10]
        })

        streak, is_record = update_streak(user.id)
        streak_msg = streak_message(streak, is_record)

        # ── Milestone перевірка (Polyglot Patch) ──
        if not s.get("is_first_lesson", False):
            await check_and_send_milestone(ctx.bot, user.id, len(done), get_s(user.id))

        # ── Зберігаємо voice file_id + sub-scores ─────────────
        voice_file_id = s.get("pending_voice_file_id","")
        upd_s(user.id, {
            "last_voice_file_id":       voice_file_id,
            "last_pronunciation_score": pronunciation_score,
            "last_fluency_score":       fluency_score,
            "last_grammar_score":       grammar_score,
            "last_vocab_score":         vocab_score,
        })

        # ── Зберігаємо ПЕРШИЙ монолог ─────────────────────────
        if not s.get("first_voice_file_id") and voice_file_id:
            upd_s(user.id, {
                "first_voice_file_id":   voice_file_id,
                "first_voice_date":      datetime.now().strftime("%Y-%m-%d"),
                "first_voice_score":     score,
            })

        # ── Зберігаємо timeline — кожен 5-й монолог ───────────
        lesson_num = len(done)
        if voice_file_id and lesson_num % 5 == 0:
            timeline = s.get("voice_timeline", [])
            timeline.append({
                "file_id":  voice_file_id,
                "date":     datetime.now().strftime("%Y-%m-%d"),
                "score":    score,
                "pronunciation": pronunciation_score,
                "fluency":       fluency_score,
                "lesson_num":    lesson_num,
            })
            timeline = timeline[-10:]  # зберігаємо останні 10 точок
            upd_s(user.id, {"voice_timeline": timeline})

        is_first = s.get("is_first_lesson", False)

        if is_first:
            # ── WOW-момент після першого монологу ──
            upd_s(user.id, {"is_first_lesson": False})

            # Автовизначення рівня по score
            detected_level = "A1"
            if score >= 85:   detected_level = "B2"
            elif score >= 70: detected_level = "B1"
            elif score >= 50: detected_level = "A2"
            else:             detected_level = "A1"
            upd_s(user.id, {"level": detected_level})

            skill_text = LEVEL_SKILLS.get(detected_level, "")

            await q.edit_message_text(
                f"🎉 *Бачиш? Ти вже говориш англійською!*\n\n"
                f"{feedback}\n\n"
                f"📊 Рівень: *{LEVEL_NAMES.get(detected_level, detected_level)}*\n\n"
                f"_{skill_text}_\n\n"
                "Тепер AI підбиратиме відео саме під твої прогалини 🎯",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 Продовжити навчання", callback_data="fork_choose")],
                ])
            )

            # ── Мотиваційна картка + share ──────────────────────
            bot_username_obj = await ctx.bot.get_me()
            bot_uname = bot_username_obj.username or "SpeakChainBot"
            ref_code  = s.get("affiliate_ref", "")
            ref_link  = (
                f"https://t.me/{bot_uname}?start=ref_{user.username or user.id}"
                if not ref_code else
                f"https://t.me/{bot_uname}?start={ref_code}"
            )
            await ctx.bot.send_message(
                chat_id=user.id,
                text=(
                    "✨ *Бачиш — ти можеш!*\n\n"
                    "Єдине, що відділяє тебе від вільного володіння — *практика*.\n"
                    "Щодня. По одному відео.\n\n"
                    "Вперед до своєї цілі з нами! 🚀\n\n"
                    "📲 *Поділись своїм результатом* — запроси друга і навчайтесь разом:"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📹 В Community", callback_data="share_voice_confirm")],
                    [InlineKeyboardButton("📱 В соцмережі", callback_data="share_socials")],
                    [InlineKeyboardButton("👥 Запросити друга", url=ref_link)],
                ])
            )

            # ── Перевіряємо реферальний бонус ───────────────────
            asyncio.create_task(_maybe_grant_referral_bonus(ctx.bot, user.id))

            # ── Після WOW — питаємо ціль для персоналізації ──
            await ctx.bot.send_message(
                chat_id=user.id,
                text="До речі — для чого тобі англійська? Підберу відео ще точніше 👇",
                reply_markup=goal_kb()
            )
        else:
            await q.edit_message_text(
                f"✅ *Оцінка готова!*\n\n{feedback}{streak_msg}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎯 Наступний урок", callback_data="fork_choose")],
                ])
            )

            # ── Мотиваційна картка за Speaking Challenge тижня ──
            if s.get("wq_question") or s.get("wq_blogger"):
                upd_s(user.id, {"wq_question": None, "wq_blogger": None})
                # +25 XP за Speaking Challenge
                s2      = get_s(user.id)
                today   = datetime.now().strftime("%Y-%m-%d")
                mult    = 3 if s2.get("triple_xp_date") == today else 1
                wq_xp   = 25 * mult
                upd_s(user.id, {"xp_total": s2.get("xp_total", 0) + wq_xp})
                await ctx.bot.send_message(
                    chat_id=user.id,
                    text=(
                        f"🏆 *+{wq_xp} XP за Speaking Challenge!*\n\n"
                        "Ти навіть не уявляєш, що ти зробив.\n\n"
                        "Ти навіть не можеш зараз оцінити, наскільки цей маленький крок "
                        "є стрибком до великої мети.\n\n"
                        "*Так тримати! Все вийде!* 🚀"
                    ),
                    parse_mode="Markdown"
                )
                return  # не показуємо Premium peek після challenge

            # ── Підглядання #1 — Premium уpsell після AI фідбеку ──
            if not is_premium(s) and not is_in_trial(s):
                blogger = s.get("affiliate_blogger", "")
                blogger_tag = f"@{blogger}" if blogger else "блогера"
                has_ref  = bool(s.get("affiliate_ref"))
                price    = PREMIUM_PRICE_AFF if has_ref else PREMIUM_PRICE_FULL
                pay_link = PREMIUM_AFFILIATE_LINK if has_ref else PREMIUM_PAYMENT_LINK
                kb_peek  = []
                if pay_link:
                    kb_peek.append([InlineKeyboardButton(
                        f"🌟 Premium — ${price}/міс", url=pay_link)])
                kb_peek.append([InlineKeyboardButton(
                    "⏭ Дякую, залишуся в Basic", callback_data="peek_dismiss")])
                await ctx.bot.send_message(
                    chat_id=user.id,
                    text=(
                        f"💬 *А що думає {blogger_tag}?*\n\n"
                        "AI дав оцінку — але жива людина чує інакше.\n"
                        f"Premium студенти щотижня отримують питання від {blogger_tag} "
                        "і беруть участь у живих вебінарах.\n\n"
                        f"_Спробуй Premium за ${price}/міс_ 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(kb_peek)
                )
            # ── Sentence Mining: пропонуємо зберегти фрази з монологу ──
            if transcript and len(transcript) > 20:
                await _offer_mining_from_transcript(ctx.bot, user.id, transcript, lesson)
            # ── Пропонуємо поділитись в Community або соцмережах ──
            voice_file = s.get("last_voice_file_id","") or s.get("pending_voice_file_id","")
            if voice_file:
                share_kb_rows = [
                    [InlineKeyboardButton("📹 В Community",  callback_data="share_voice_confirm"),
                     InlineKeyboardButton("📱 В соцмережі", callback_data="share_socials")],
                    [InlineKeyboardButton("⏭ Пропустити",   callback_data="share_voice_cancel")],
                ]
                # Агресивний пуш якщо бал хороший або milestone
                lesson_count = len(done)
                if score >= 65 or lesson_count in MILESTONES:
                    share_prompt = (
                        "🔥 *Гарний результат!*\n\n"
                        
                        "Поділись своїм монологом — нехай друзі бачать твій прогрес 👇"
                    )
                else:
                    share_prompt = (
                        "🎙 *Поділись своїм монологом!*\n\n"
                        f"Рівень *{LEVEL_NAMES.get(s.get('level',''),'')!s}* · "
                        f"{'🔥' + str(streak) + ' дн.' if streak > 1 else ''}\n\n"
                        "Інші студенти почують і підтримають 👏"
                    )
                await ctx.bot.send_message(
                    chat_id=user.id,
                    text=share_prompt,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(share_kb_rows)
                )

        # Збільшуємо лічильник переглянутих відео
        videos_watched = s.get("videos_watched", 0) + 1
        upd_s(user.id, {"videos_watched": videos_watched})
        s = get_s(user.id)  # reload after update

        # Механіка 1: після першого уроку — нагадування через 24 год
        if videos_watched == 1:
            from datetime import timedelta
            ctx.job_queue.run_once(
                send_day2_reminder,
                when=timedelta(hours=24),
                data={"uid": user.id},
                name=f"day2_{user.id}"
            )

        await asyncio.sleep(1)

        if not s.get("onboarding_done") and videos_watched == 1:
            # ── Після першого відео до онбоардингу: тільки розвилка ──
            await ctx.bot.send_message(
                chat_id=user.id,
                text="🎉 *Відмінно! Перше завдання виконано.*\n\nЩо робимо далі?",
                parse_mode="Markdown",
                reply_markup=next_video_fork_kb()
            )
        else:
            # ── Зберігаємо дані для тесту (доступний через Прогрес) ──
            # Тест показується одразу лише після відео рекомендованого ботом
            is_bot_lesson = lesson_id and lesson_id != "custom"
            upd_s(user.id, {
                "quiz_lesson_title":   lesson.get("title", ""),
                "quiz_lesson_topic":   lesson.get("topic", ""),
                "quiz_lesson_grammar": lesson.get("grammar", ""),
                "quiz_transcript":     transcript,
                "quiz_level":          level,
                "quiz_after_action":   "fork",
                "quiz_ready":          True,   # флаг — тест готовий, доступний з Прогресу
            })
            if is_bot_lesson:
                await ctx.bot.send_message(
                    chat_id=user.id,
                    text=(
                        "📝 *Тест на матеріал уроку*\n\n"
                        "~2 хвилини. Результат іде в прогрес 🎯"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Пройти тест", callback_data="quiz_start"),
                        InlineKeyboardButton("⏭ Пізніше",     callback_data="quiz_skip"),
                    ]])
                )
            else:
                await ctx.bot.send_message(
                    chat_id=user.id,
                    text="Що робимо далі?",
                    reply_markup=next_video_fork_kb()
                )

        gaps = await analyse_gaps(
            transcript    = transcript,
            level         = level,
            grammar_focus = lesson.get("grammar", ""),
            interests     = s.get("interests", []),
            profession    = s.get("profession", "")
        )
        # Зберігаємо gaps — показуємо тільки через вкладку Прогрес
        upd_s(user.id, {"pending_gaps": gaps})

    except Exception as e:
        logger.error(f"Voice evaluation error uid={user.id}: {type(e).__name__}: {e}")
        try:
            await ctx.bot.send_message(
                chat_id=user.id,
                text=(
                    f"😔 Помилка: `{type(e).__name__}`\n\n"
                    "Перевір баланс на OpenAI і Anthropic або спробуй ще раз."
                ),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
        except Exception:
            pass

# ── Gap recommendations helper ────────────────────────
async def send_gap_recommendations(bot, user_id: int, s: dict):
    gaps      = s.get("pending_gaps", {})
    is_first  = s.get("is_first_lesson", False)

    if not gaps:
        await bot.send_message(
            chat_id=user_id,
            text="🎯 Продовжуємо навчання 👇",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return

    # ── Gap analysis — показуємо яскраво як killer feature ──
    gap_lines = []
    if gaps.get("grammar_gap"):
        gap_lines.append(f"⚠️ *Граматика:* _{gaps['grammar_gap']}_")
    if gaps.get("vocab_gap"):
        gap_lines.append(f"📖 *Словник:* _{gaps['vocab_gap']}_")

    if gap_lines:
        await bot.send_message(
            chat_id=user_id,
            text=(
                "🔍 *AI проаналізував твоє мовлення*\n\n"
                + "\n".join(gap_lines)
                + "\n\n_Наступне відео підібрано саме під ці прогалини_\n\nХочеш програму під свою сферу? → /tutor\\_me"
            ),
            parse_mode="Markdown",
            reply_markup=None
        )

    await bot.send_message(chat_id=user_id,
        text="🔍 *Підбираю відео для закріплення...*", parse_mode="Markdown")

    level     = s.get("level", "A1")
    interests = s.get("interests", [])
    rec_messages = []
    for rtype in ("grammar", "vocab", "reinforce"):
        query = gaps.get(f"{rtype}_query", "")
        if not query: continue
        full_query = f"{query} {level} {interests[0] if interests else ''}".strip()
        results = await youtube_search(full_query, max_results=1)
        if not results: continue
        vid = results[0]
        if rtype == "grammar":
            header = "🎯 *Рекомендую для граматики:*"
            reason = f"📌 _{gaps.get('grammar_gap','Граматична помилка')}_ — ось відео щоб виправити:"
        elif rtype == "vocab":
            header = "📚 *Рекомендую для словника:*"
            reason = f"📖 _{gaps.get('vocab_gap','Розшир словниковий запас')}_ — ось відео по темі:"
        else:
            header = "🇬🇧 *Закріплення патернів:*"
            reason = "🔁 _Закріп мовні патерни з носіями мови:_"
        rec_messages.append((f"{header}\n{reason}\n\n*{vid['title']}*\n_{vid.get('channel','')}_", vid["url"]))

    if rec_messages:
        for msg_text, rec_url in rec_messages:
            await bot.send_message(
                chat_id=user_id, text=msg_text, parse_mode="Markdown",
                reply_markup=video_watch_keyboard(rec_url),
                disable_web_page_preview=True
            )
            await asyncio.sleep(0.5)

    await bot.send_message(
        chat_id=user_id,
        text="Що робимо далі?",
        reply_markup=next_video_fork_kb()
    )

# ── Quiz cache ────────────────────────────────────────
QUIZ_CACHE_FILE = "quiz_cache.json"

def _normalise_grammar(grammar: str) -> str:
    """Turn grammar focus string into a short stable cache key."""
    g = grammar.lower()
    mappings = [
        (["present perfect"],          "present_perfect"),
        (["past simple", "past tense"],"past_simple"),
        (["present simple", "simple present"], "present_simple"),
        (["present continuous"],        "present_continuous"),
        (["future", "going to", "will"],"future"),
        (["past continuous"],           "past_continuous"),
        (["conditional", "if clause"],  "conditionals"),
        (["passive"],                   "passive_voice"),
        (["modal"],                     "modals"),
        (["reported speech"],           "reported_speech"),
        (["relative clause"],           "relative_clauses"),
        (["comparative"],               "comparatives"),
        (["there is", "there are"],     "there_is_are"),
        (["used to"],                   "used_to"),
        (["present perfect continuous"],"present_perfect_continuous"),
    ]
    for keywords, canonical in mappings:
        if any(kw in g for kw in keywords):
            return canonical
    words = re.findall(r"[a-z]+", g)
    return "_".join(words[:3]) or "general"

def quiz_cache_key(level: str, grammar: str, age_group: str = "adult") -> str:
    return f"{level}__{_normalise_grammar(grammar)}__{age_group}"

# Кеш зберігається в DB під ключем "quiz_cache" щоб пережити Railway деплой
QUIZ_CACHE_DB_KEY = "quiz_cache"

def load_quiz_cache() -> dict:
    # Спочатку DB, потім файл як fallback
    db = load_db()
    if QUIZ_CACHE_DB_KEY in db:
        return db[QUIZ_CACHE_DB_KEY]
    p = Path(QUIZ_CACHE_FILE)
    return json.loads(p.read_text()) if p.exists() else {}

def save_quiz_cache(cache: dict):
    db = load_db()
    db[QUIZ_CACHE_DB_KEY] = cache
    save_db(db)

def get_cached_quiz(level: str, grammar: str, age_group: str = "adult") -> list | None:
    key = quiz_cache_key(level, grammar, age_group)
    return load_quiz_cache().get(key)

def store_quiz_cache(level: str, grammar: str, age_group: str, questions: list):
    cache = load_quiz_cache()
    key   = quiz_cache_key(level, grammar, age_group)
    cache[key] = questions
    save_quiz_cache(cache)
    logger.info(f"Quiz cached: {key}")

# ── Quiz: generate 10 questions (with cache) ──────────
async def generate_quiz(s: dict) -> list[dict] | None:
    """
    Returns list of 10 dicts: { question, options: [A,B,C,D], correct: 0-3 }
    Cache key = level + normalised grammar + age_group.
    Same grammar topic → same test for same age group, regardless of video.
    """
    level     = s.get("quiz_level", s.get("level", "A1"))
    grammar   = s.get("quiz_lesson_grammar", "")
    title     = s.get("quiz_lesson_title", "")
    topic     = s.get("quiz_lesson_topic", "")
    age_group = s.get("age_group", "adult")

    # Age-group context for Claude
    age_contexts = {
        "kids":  "The student is a child (under 12). Use simple vocabulary, fun examples about animals, school, games, family. Short sentences.",
        "teen":  "The student is a teenager (13-17). Use relatable examples about music, social media, friends, hobbies, school life.",
        "adult": "The student is an adult (18-35). Use practical examples about work, travel, daily life, technology.",
        "senior":"The student is an adult (35+). Use mature examples about career, family, travel, health, life experience.",
    }
    age_ctx = age_contexts.get(age_group, age_contexts["adult"])

    # ── Cache hit ──
    cached = get_cached_quiz(level, grammar, age_group)
    if cached:
        logger.info(f"Quiz cache HIT: {quiz_cache_key(level, grammar, age_group)}")
        return cached

    # ── Cache miss → generate via Claude ──
    logger.info(f"Quiz cache MISS: {quiz_cache_key(level, grammar, age_group)} — generating...")
    prompt = f"""You are an English teacher. Create a 10-question multiple-choice quiz.

Level: {level}
Grammar focus: {grammar}
Context topic: {title} — {topic}
Age group: {age_group}. {age_ctx}

Mix question types: grammar usage, fill-in-the-blank, error correction, vocabulary in context.
Questions should test understanding of "{grammar}" at {level} level.
Vocabulary and examples MUST match the age group described above.
Keep questions reusable (not tied to one specific video).

Reply ONLY with valid JSON array, no markdown, no extra text:
[
  {{
    "question": "question text in Ukrainian",
    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
    "correct": 0
  }},
  ...10 items total...
]

Rules:
- "correct" is 0-indexed (0=A, 1=B, 2=C, 3=D)
- Options in English, question in Ukrainian
- Difficulty appropriate for {level}
- One clearly correct answer per question"""

    try:
        cr = claude_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = cr.content[0].text.strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        questions = json.loads(raw)
        if isinstance(questions, list) and len(questions) >= 5:
            questions = questions[:10]
            store_quiz_cache(level, grammar, age_group, questions)
            return questions
    except Exception as e:
        logger.warning(f"Quiz generation error: {e}")

    # ── Fallback — базові питання якщо Claude недоступний ──
    return [
        {"question": f"Яка правильна форма дієслова у Present Simple?",
         "options": ["A) She go to school", "B) She goes to school", "C) She going to school", "D) She gone to school"],
         "correct": 1},
        {"question": "Яке речення граматично правильне?",
         "options": ["A) I am agree", "B) I agrees", "C) I agree", "D) I agreeing"],
         "correct": 2},
        {"question": "Оберіть правильний варіант:",
         "options": ["A) He don't like coffee", "B) He doesn't likes coffee", "C) He doesn't like coffee", "D) He not like coffee"],
         "correct": 2},
        {"question": "Яке слово означає 'великий'?",
         "options": ["A) small", "B) fast", "C) big", "D) cold"],
         "correct": 2},
        {"question": "Як правильно сказати 'я вчора пішов'?",
         "options": ["A) I go yesterday", "B) I went yesterday", "C) I gone yesterday", "D) I going yesterday"],
         "correct": 1},
    ]

# ── Лексика з відео ────────────────────────────────────
async def extract_vocab_from_video(title: str, topic: str, grammar: str, level: str) -> list[dict]:
    """Claude витягує 5 ключових слів з відео для вивчення."""
    try:
        prompt = (
            f"You are an English vocabulary teacher.\n"
            f"Video: '{title}'. Topic: {topic}. Grammar focus: {grammar}. Level: {level}.\n\n"
            f"Extract exactly 5 key vocabulary words/phrases from this video context.\n"
            f"Reply ONLY with valid JSON, no markdown:\n"
            f'[{{"word":"...","translation":"...","example":"..."}},...5 items]'
        )
        cr = claude_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=400,
            messages=[{"role":"user","content":prompt}]
        )
        raw   = re.sub(r"```json|```","", cr.content[0].text).strip()
        start = raw.find("["); end = raw.rfind("]") + 1
        return json.loads(raw[start:end]) if start >= 0 else []
    except Exception as e:
        logger.warning(f"Vocab extraction error: {e}")
        return []

async def send_vocab_card(bot, user_id: int, words: list[dict], idx: int = 0):
    """Надсилає картку слова — студент натискає Знаю/Не знаю."""
    if idx >= len(words):
        # Всі слова пройдено — завершуємо лексичний блок
        s = get_s(user_id)
        known   = s.get("vocab_session_known", 0)
        total   = s.get("vocab_session_total", len(words))
        is_srs  = s.get("srs_session_active", False)

        upd_s(user_id, {
            "vocab_session_known":      0,
            "vocab_session_total":      0,
            "vocab_session_words":      [],
            "vocab_session_words_data": [],
            "vocab_session_idx":        0,
            "vocab_done":               True,
            "srs_session_active":       False,
        })

        if is_srs:
            # SRS-сесія: vocab_learned вже оновлено через _srs_update_word
            due_left    = len(_srs_due_words(get_s(user_id)))
            s2          = get_s(user_id)
            srs_db      = s2.get("srs_words", {})
            session_wds = s2.get("vocab_session_words", []) or [
                w.get("word","") for w in (words or []) if w.get("word")
            ]
            # Беремо слова які студент НЕ знав — їх треба проговорити
            learn_words = [
                w for w in session_wds
                if srs_db.get(w, {}).get("count_know", 0) == 0
            ] or session_wds
            words_list  = ", ".join(f"*{w}*" for w in learn_words[:6])

            is_rescue = s2.get("srs_after_rescue", False)
            if is_rescue:
                upd_s(user_id, {"srs_after_rescue": False})
                challenge_text = (
                    f"✅ *Чудово! {known} з {total} фраз повторено!*\n\n"
                    f"Тепер запиши короткий монолог — використай ці фрази:\n{words_list}\n\n"
                    "_30–60 секунд — і стрік врятовано_ 🔥\n\n"
                    "🎙 Натисни мікрофон і говори 👇"
                )
            else:
                challenge_text = (
                    f"🧠 *SRS-сесію завершено!*\n\n"
                    f"Пригадав: *{known}/{total}* слів\n\n"
                    "━━━━━━━━━━━━━━━━\n"
                    "🎙 *Speaking Challenge — закріпи слова голосом!*\n\n"
                    f"Склади 2–3 речення з цими словами:\n{words_list}\n\n"
                    "_Запиши голосове або відео — найшвидший спосіб закріпити слова в пам'яті. "
                    "Мозок запам'ятовує те, що проговорене вголос, у 3× краще ніж прочитане._\n\n"
                    "Натисни мікрофон і говори 👇"
                )
            kb_rows = [
                [InlineKeyboardButton("🎙 Записати голосове", callback_data="remind_record")],
            ]
            if due_left:
                kb_rows.append([
                    InlineKeyboardButton("🧠 Повторити решту", callback_data="srs_start"),
                    InlineKeyboardButton("⏭ Пропустити",       callback_data="fork_choose"),
                ])
            else:
                challenge_text += "\n\n✅ _Всі слова повторені на сьогодні!_"
                kb_rows.append([InlineKeyboardButton("⏭ Пропустити виклик", callback_data="fork_choose")])

            await bot.send_message(
                chat_id=user_id,
                text=challenge_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb_rows)
            )
        else:
            # Звичайна vocab-сесія уроку
            learned       = s.get("vocab_learned", [])
            session_words = s.get("vocab_session_words", [])
            new_learned   = [w for w in session_words if w not in learned]
            upd_s(user_id, {"vocab_learned": learned + new_learned})
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"📚 *Лексику пройдено!*\n\n"
                    f"Знав: *{known}/{total}* слів\n"
                    f"Всього в словнику: *{len(learned) + len(new_learned)}* слів\n\n"
                    "Тепер запиши монолог — використай нові слова! 🎙"
                ),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
        return

    word = words[idx]
    await bot.send_message(
        chat_id=user_id,
        text=(
            f"📚 *Слово {idx+1}/{len(words)}*\n\n"
            f"🇬🇧 *{word.get('word','')}*\n"
            f"🇺🇦 _{word.get('translation','')}_\n\n"
            f"💬 _{word.get('example','')}_"
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Знаю",    callback_data=f"vocab_know_{idx}"),
            InlineKeyboardButton("📖 Вчу",    callback_data=f"vocab_learn_{idx}"),
        ]])
    )

async def cb_vocab(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обробляє Знаю/Вчу — з SRS-логікою (Polyglot Patch)."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    parts  = q.data.split("_")
    action = parts[1]   # know або learn
    idx    = int(parts[2])
    words  = s.get("vocab_session_words_data", [])

    # SRS-оновлення замість простого "додати до learned"
    if idx < len(words):
        await _srs_update_word(user.id, words[idx], action)
        # Зберігаємо translation/example в SRS якщо є
        if words[idx].get("translation"):
            s2     = get_s(user.id)
            word   = words[idx].get("word", "")
            srs_db = s2.get("srs_words", {})
            if word in srs_db:
                srs_db[word]["translation"] = words[idx].get("translation", "")
                srs_db[word]["example"]     = words[idx].get("example", "")
                upd_s(user.id, {"srs_words": srs_db})

    await q.edit_message_reply_markup(reply_markup=None)
    await send_vocab_card(ctx.bot, user.id, words, idx + 1)

# ── Три лічильники прогресу ─────────────────────────────
def get_skill_progress(s: dict) -> dict:
    """Повертає прогрес по трьох навичках у відсотках."""
    level   = s.get("level", "A1")
    levels  = LEVELS_ORDER
    cur_idx = levels.index(level) if level in levels else 0

    # 1. Граматика — теми пройдені на поточному рівні
    lvl_topics   = CEFR_GRAMMAR.get(level, [])
    mastered     = s.get("mastered_grammar", [])
    lvl_mastered = sum(1 for t in lvl_topics if t in mastered)
    grammar_pct  = int(lvl_mastered / len(lvl_topics) * 100) if lvl_topics else 0

    # 2. Лексика — слів вивчено (орієнтир: 50 слів на рівень)
    WORDS_PER_LEVEL = 50
    vocab_count = len(s.get("vocab_learned", []))
    vocab_pct   = min(100, int(vocab_count / WORDS_PER_LEVEL * 100))

    # 3. Говоріння — середній бал монологів (scores)
    scores       = [sc.get("score",0) for sc in s.get("scores",[]) if sc.get("score",0) > 0]
    speaking_pct = int(sum(scores) / len(scores)) if scores else 0

    # Загальний рівень = середнє трьох навичок
    overall = int((grammar_pct + vocab_pct + speaking_pct) / 3)

    return {
        "grammar":  grammar_pct,
        "vocab":    vocab_pct,
        "speaking": speaking_pct,
        "overall":  overall,
        "vocab_count": vocab_count,
    }

# ── Юніт-логіка: відео → лексика → монолог ─────────────
async def start_unit_vocab(bot, user_id: int, lesson: dict):
    """Запускає лексичний блок після відео."""
    s     = get_s(user_id)
    title  = lesson.get("title","")
    topic  = lesson.get("topic","")
    grammar= lesson.get("grammar","")
    level  = s.get("level","A1")

    await bot.send_message(
        chat_id=user_id,
        text=(
            "📚 *Лексика з відео*\n\n"
            "Перевір 5 ключових слів — це займе 1 хвилину.\n"
            "Натисни ✅ якщо знаєш слово, 📖 якщо вчиш."
        ),
        parse_mode="Markdown"
    )

    words = await extract_vocab_from_video(title, topic, grammar, level)
    if not words:
        # Fallback — одразу до монологу
        await bot.send_message(
            chat_id=user_id,
            text="🎙 Тепер запиши монолог про те що побачив у відео 👇",
            reply_markup=main_menu()
        )
        return

    upd_s(user_id, {
        "vocab_session_words_data": words,
        "vocab_session_words":      [w.get("word","") for w in words],
        "vocab_session_idx":        0,
        "vocab_session_known":      0,
        "vocab_session_total":      len(words),
        "vocab_done":               False,
    })
    await send_vocab_card(bot, user_id, words, 0)

# ── Quiz callbacks ─────────────────────────────────────
async def cb_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()
    data = q.data

    # ── Пропустити тест ──
    if data == "quiz_skip":
        await q.edit_message_text("⏭ Тест пропущено.")
        if s.get("quiz_after_action") == "fork":
            upd_s(user.id, {"quiz_after_action": None})
            videos_watched = s.get("videos_watched", 0)
            if not s.get("onboarding_done") and videos_watched >= 2:
                upd_s(user.id, {"onboarding_triggered": True})
                await ctx.bot.send_message(
                    chat_id=user.id,
                    text=(
                        "Щоб підібрати найкращі відео для тебе — "
                        "кілька швидких питань 🎯\n\n"
                        "Для чого тобі потрібна англійська? 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=goal_kb()
                )
            else:
                await ctx.bot.send_message(
                    chat_id=user.id,
                    text="Що робимо далі?",
                    reply_markup=next_video_fork_kb()
                )
        else:
            await ctx.bot.send_message(
                chat_id=user.id,
                text="Що робимо далі?",
                reply_markup=next_video_fork_kb()
            )
        return

    # ── Почати тест ──
    if data == "quiz_start":
        level     = s.get("quiz_level", s.get("level", "A1"))
        grammar   = s.get("quiz_lesson_grammar", "")
        age_group = s.get("age_group", "adult")
        cached    = get_cached_quiz(level, grammar, age_group)
        wait_msg  = "⚡️ Завантажую тест..." if cached else "📝 Генерую питання... (~10 сек)"
        await q.edit_message_text(wait_msg)
        questions = await generate_quiz(s)
        if not questions:
            await q.edit_message_text("😔 Не вдалося згенерувати тест. Спробуй пізніше.")
            await ctx.bot.send_message(chat_id=user.id, text="Що робимо далі?",
                                       reply_markup=next_video_fork_kb())
            return
        upd_s(user.id, {
            "quiz_questions": questions,
            "quiz_current":   0,
            "quiz_correct":   0,
        })
        await send_quiz_question(ctx.bot, user.id, questions, 0)
        await q.delete_message()
        return

    # ── Відповідь на питання ──
    if data.startswith("qa_"):
        # qa_{question_index}_{answer_index}
        parts = data.split("_")
        q_idx = int(parts[1])
        a_idx = int(parts[2])

        questions = s.get("quiz_questions", [])
        if q_idx >= len(questions):
            return

        current_q  = questions[q_idx]
        correct_idx = current_q.get("correct", 0)
        is_correct  = (a_idx == correct_idx)
        correct_count = s.get("quiz_correct", 0) + (1 if is_correct else 0)
        upd_s(user.id, {"quiz_correct": correct_count, "quiz_current": q_idx + 1})

        # Show result for this question
        options = current_q.get("options", [])
        result_lines = []
        for i, opt in enumerate(options):
            if i == correct_idx and i == a_idx:
                result_lines.append(f"✅ {opt}")
            elif i == correct_idx:
                result_lines.append(f"✅ {opt}")
            elif i == a_idx:
                result_lines.append(f"❌ {opt}")
            else:
                result_lines.append(f"     {opt}")

        await q.edit_message_text(
            f"*{q_idx + 1}/10*\n\n"
            f"{current_q['question']}\n\n"
            + "\n".join(result_lines),
            parse_mode="Markdown"
        )
        await asyncio.sleep(1.2)

        next_idx = q_idx + 1
        if next_idx < len(questions):
            await send_quiz_question(ctx.bot, user.id, questions, next_idx)
        else:
            # Тест завершено
            total    = len(questions)
            pct      = int(correct_count / total * 100)
            bar      = "█" * (pct // 10) + "░" * (10 - pct // 10)
            if pct >= 80:   verdict = "🏆 Відмінно!"
            elif pct >= 60: verdict = "👍 Добре!"
            elif pct >= 40: verdict = "📚 Є над чим попрацювати."
            else:           verdict = "💪 Повтори матеріал ще раз."

            await ctx.bot.send_message(
                chat_id=user.id,
                text=(
                    f"📊 *Результат тесту:*\n\n"
                    f"`{bar}` {pct}%\n"
                    f"Правильних відповідей: *{correct_count}/{total}*\n\n"
                    f"{verdict}"
                ),
                parse_mode="Markdown"
            )
            # Save quiz score
            quiz_scores = s.get("quiz_scores", [])
            quiz_scores.append({
                "score": correct_count, "total": total,
                "pct": pct, "date": datetime.now().isoformat()
            })
            after_action = s.get("quiz_after_action")
            upd_s(user.id, {
                "quiz_scores":      quiz_scores,
                "quiz_questions":   None,
                "quiz_after_action": None,
                "quiz_ready":       False,   # тест пройдено — прибираємо з Прогресу
            })
            await asyncio.sleep(1)
            if after_action == "cycle":
                # Після тесту в циклі → крок монологу
                topic = s.get("cycle_topic", "")
                await ctx.bot.send_message(
                    chat_id=user.id,
                    text=(
                        f"✅ Тест пройдено!\n\n"
                        f"*Крок 4/4 — 🎙 Монолог*\n\n"
                        f"Тема: _{topic}_\n\n"
                        "Запиши кілька речень англійською про тему уроку — і отримай оцінку AI 👇\n\n"
                        "_Натисни мікрофон або напиши текст_"
                    ),
                    parse_mode="Markdown",
                    reply_markup=main_menu()
                )
            elif after_action == "fork":
                videos_watched = s.get("videos_watched", 0)
                if not s.get("onboarding_done") and videos_watched >= 2:
                    upd_s(user.id, {"onboarding_triggered": True})
                    await ctx.bot.send_message(
                        chat_id=user.id,
                        text=(
                            "Щоб підібрати найкращі відео для тебе — "
                            "кілька швидких питань 🎯\n\n"
                            "Для чого тобі потрібна англійська? 👇"
                        ),
                        parse_mode="Markdown",
                        reply_markup=goal_kb()
                    )
            else:
                await ctx.bot.send_message(
                    chat_id=user.id,
                    text="Що робимо далі?",
                    reply_markup=next_video_fork_kb()
                )

async def send_quiz_question(bot, user_id: int, questions: list, idx: int):
    q    = questions[idx]
    opts = q.get("options", [])
    kb   = InlineKeyboardMarkup([[
        InlineKeyboardButton(opts[i], callback_data=f"qa_{idx}_{i}")
    ] for i in range(len(opts))])
    await bot.send_message(
        chat_id=user_id,
        text=f"*Питання {idx + 1}/10*\n\n{q['question']}",
        parse_mode="Markdown",
        reply_markup=kb
    )
async def cb_start_vocab(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Запускає лексичний блок після кнопки 'Слова з відео'."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()
    await q.edit_message_reply_markup(reply_markup=None)

    lesson = s.get("current_lesson_data") or {
        "title":   s.get("quiz_lesson_title",""),
        "topic":   s.get("quiz_lesson_topic",""),
        "grammar": s.get("quiz_lesson_grammar",""),
    }
    await start_unit_vocab(ctx.bot, user.id, lesson)

async def cb_remind_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("⏭ Добре, повернемось пізніше 👍")

# ── Remind record callback ────────────────────────────
async def cb_remind_record(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    # Зберігаємо урок і позначаємо режим shadowing
    current_lesson = s.get("current_lesson_data", {})
    if current_lesson:
        upd_s(user.id, {"voice_lesson_data": current_lesson})
    upd_s(user.id, {"recording_mode": "shadowing"})

    await q.edit_message_text(
        "🎙 *Час записати монолог!*\n\n"
        "Натисни мікрофон у полі введення → говори → відпусти.\n\n"
        "_Запис з'явиться тут автоматично._",
        parse_mode="Markdown"
    )


# ── Відео від студента → Community ───────────────────
async def handle_web_app_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обробляє дані з Mini App плеєра (збереження фраз)."""
    user = update.effective_user
    s    = get_s(user.id)

    try:
        raw     = update.effective_message.web_app_data.data
        payload = json.loads(raw)
    except Exception as e:
        logger.warning(f"web_app_data parse error: {e}")
        return

    action = payload.get("action", "")

    if action == "save_phrase":
        phrase = payload.get("phrase", "").strip()
        if not phrase or len(phrase) < 2:
            return
        lesson = s.get("current_lesson_data") or {}

        # ── Soft paywall якщо тріал завершено ────────────
        _s_now = get_s(user.id)
        _blocked = await soft_paywall_message(ctx.bot, user.id, _s_now, phrase)
        if _blocked:
            return

        await _save_mined_sentence(user.id, phrase, lesson)
        due_count = len(_srs_due_words(get_s(user.id)))
        await ctx.bot.send_message(
            chat_id=user.id,
            text=(
                f"💎 *Збережено в картотеку!*\n\n"
                f"▸ _{phrase}_\n\n"
                f"Повторю через день 🧠 Всього: *{due_count}*"
            ),
            parse_mode="Markdown"
        )
        logger.info(f"Player phrase saved uid={user.id}: {phrase[:50]}")

        # ── Speaking Challenge пропозиція ─────────────────
        asyncio.create_task(send_phrase_challenge(ctx.bot, user.id, get_s(user.id), phrase, upd_s))

        # ── Граматика: визначаємо тему і перевіряємо нудж ──
        topic_key = detect_topic(phrase)
        if topic_key:
            s = mark_topic_event(get_s(user.id), topic_key, "phrase_added")
            upd_s(user.id, {"grammar_topics": s["grammar_topics"]})
            s = get_s(user.id)
            if should_nudge(s, topic_key):
                phrase_count = s.get("grammar_topics", {}).get(topic_key, {}).get("phrase_count", 0)
                nudge_msg    = build_nudge_text(topic_key, phrase_count)
                s = mark_nudge_sent(s, topic_key)
                upd_s(user.id, {"grammar_topics": s["grammar_topics"]})
                import asyncio as _aio
                await _aio.sleep(1)
                await ctx.bot.send_message(
                    chat_id=user.id,
                    text=nudge_msg,
                    parse_mode="Markdown",
                    reply_markup=nudge_keyboard()
                )

    elif action == "session_end":
        minutes   = int(payload.get("minutes", 0))
        video_title = payload.get("video_title", "").strip()
        video_url   = payload.get("video_url", "").strip()
        if minutes < 1:
            return
        # Зберігаємо загальний час у плеєрі + тему для дуелі
        total = s.get("player_minutes_total", 0) + minutes
        duel_topic = f"Перекажи відео: {video_title}" if video_title else "Розкажи про відео яке щойно переглянув"
        upd_s(user.id, {
            "player_minutes_total": total,
            "last_player_video_title": video_title,
            "last_player_video_url":   video_url,
            "pending_duel_topic":      duel_topic,
            "pending_duel_score":      0,
        })
        logger.info(f"Player session uid={user.id}: {minutes} хв (всього {total} хв) video={video_title[:40] if video_title else 'n/a'}")

        # Кнопка дуелі якщо є блогер і студенти
        has_blogger = bool(s.get("affiliate_blogger"))
        kb = []
        if has_blogger:
            kb.append([InlineKeyboardButton("⚔️ Кинути виклик по цьому відео", callback_data="duel_challenge")])
        kb.append([InlineKeyboardButton("🎙 Записати монолог по темі",       callback_data="remind_record")])

        video_line = f"\n🎬 _{video_title}_" if video_title else ""
        await ctx.bot.send_message(
            chat_id=user.id,
            text=(
                f"🎯 *Сесію завершено!*{video_line}\n\n"
                f"⏱ Сьогодні у плеєрі: *{minutes} хв*\n"
                f"📊 Всього практики: *{total} хв*\n\n"
                f"{'🔥 Чудова робота — так тримати!' if minutes >= 10 else '✅ Гарний старт — завтра ще!'}\n\n"
                "Закріпи матеріал — запиши монолог або кинь виклик іншому студенту! 👇"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb) if kb else None
        )
    else:
        logger.info(f"Unknown web_app action: {action}")
    """Приймає відео від студента, оцінює через AI і пропонує в Community."""
    user = update.effective_user
    s    = get_s(user.id)

    video   = update.message.video or update.message.video_note
    file_id = video.file_id if video else None

    if not file_id:
        return

    upd_s(user.id, {"last_video_file_id": file_id})

    # Пробуємо транскрибувати аудіо з відео через Whisper
    msg = await update.message.reply_text("🎬 Аналізую відео... (~30 сек)")

    transcript = None
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    if openai_key:
        try:
            import httpx, tempfile
            vf = await ctx.bot.get_file(file_id)
            suffix = ".mp4" if update.message.video else ".mp4"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                await vf.download_to_drive(tmp.name)
                path = tmp.name

            with open(path, "rb") as af:
                resp = httpx.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {openai_key}"},
                    data={"model": "whisper-1", "language": "en"},
                    files={"file": ("video.mp4", af, "video/mp4")},
                    timeout=60
                )
            os.unlink(path)
            if resp.status_code == 200:
                transcript = resp.json().get("text", "").strip()
                logger.info(f"Video Whisper OK: {transcript[:50]}")
        except Exception as e:
            logger.warning(f"Video transcription error: {e}")

    level   = s.get("level", "A1")
    topic   = s.get("cycle_topic") or s.get("quiz_lesson_title") or ""
    lesson  = {"title": topic, "grammar": s.get("quiz_lesson_grammar", ""), "url": ""}

    if transcript:
        # AI оцінка
        try:
            personal_context = ""
            parts = []
            if s.get("profession"): parts.append(f"profession: {s['profession']}")
            if s.get("interests"):  parts.append(f"interests: {', '.join(s['interests'][:3])}")
            if parts: personal_context = f"Student background — {'; '.join(parts)}.\n"

            prompt = f"""You are a friendly English speaking coach. Evaluate the student's monologue and give feedback in Ukrainian.

Student level: {level}.
{personal_context}
Student said: \"\"\"{transcript[:600]}\"\"\"

Evaluate grammar correctness, vocabulary and natural flow.
Find the ONE most important real mistake — something genuinely wrong.
RULE: Never suggest changing a grammatically correct tense. Past Simple for past events is always correct.

Write in Ukrainian. Warm, simple, no jargon.

FORMAT (keep emoji and bold):
🎯 *Загальний бал: X/100*

✅ *Що вийшло добре:*
[1-2 речення, процитуй їхні слова]

🔧 *Що виправити:*
Сказав: "[точна фраза]"
Правильно: "[виправлена фраза]"
Чому: [просте пояснення]

🚀 *Спробуй наступного разу:*
[одне конкретне речення]

Max 130 words. If score>=75 add: 🌟 Опублікуй з #SpeakChain!"""

            cr = claude_client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=600,
                messages=[{"role": "user", "content": prompt}]
            )
            feedback = cr.content[0].text

            # Витягуємо бал
            score = 0
            for line in feedback.split("\n"):
                if "загальний бал" in line.lower():
                    nums = re.findall(r'\b(\d{1,3})\b', line)
                    for n in nums:
                        if 0 < int(n) <= 100: score = int(n); break
                    if score: break

            upd_s(user.id, {
                "pending_video_transcript": transcript,
                "pending_video_score":      score,
            })

            await msg.edit_text(
                f"🎬 *Оцінка відео-монологу*\n\n{feedback}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📹 В Community",        callback_data="share_video_confirm")],
                    [InlineKeyboardButton("📤 В Premium-групу",    callback_data="share_video_group")],
                    [InlineKeyboardButton("📱 Caption для соцмереж", callback_data="share_socials")],
                    [InlineKeyboardButton("❌ Не зараз",            callback_data="share_video_cancel")],
                ])
            )
            return
        except Exception as e:
            logger.warning(f"Video AI eval error: {e}")

    # Без транскрипції — просто пропонуємо поділитись
    level_name = LEVEL_NAMES.get(level, level)
    await msg.edit_text(
        "📹 *Відео отримано!*\n\n"
        "Хочеш поділитись ним у спільноті SpeakChain?\n\n"
        f"Рівень: *{level_name}*"
        + (f"\nТема: _{topic}_" if topic else ""),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📹 В Community",        callback_data="share_video_confirm")],
            [InlineKeyboardButton("📤 В Premium-групу",    callback_data="share_video_group")],
            [InlineKeyboardButton("📱 Caption для соцмереж", callback_data="share_socials")],
            [InlineKeyboardButton("❌ Не зараз",            callback_data="share_video_cancel")],
        ])
    )

async def cb_share_voice_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Публікує голосовий монолог в Community канал."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()
    file_id = s.get("last_voice_file_id", "")
    if not file_id:
        await q.edit_message_text("😔 Запис не знайдено.")
        return
    level  = LEVEL_NAMES.get(s.get("level",""), "")
    topic  = s.get("cycle_topic") or s.get("quiz_lesson_title") or ""
    caption = (
        f"🎙 *{user.first_name}* — {level}\n"
        + (f"Тема: _{topic}_\n" if topic else "")
        + f"\n@SpeakChainBot #SpeakChain #LearnEnglish"
    )
    try:
        msg = await ctx.bot.send_voice(chat_id=COMMUNITY_CHANNEL, voice=file_id,
                                       caption=caption, parse_mode="Markdown")
        # Зберігаємо message_id → uid для нарахування XP за реакції
        db = load_db()
        cm = db.get("_community_posts", {})
        cm[str(msg.message_id)] = {"uid": user.id, "name": user.first_name}
        db["_community_posts"] = cm
        save_db(db)
        asyncio.create_task(award_xp(ctx.bot, user.id, "shared_community"))
        # Якщо це власне відео (не урок) — окрема нагорода
        if s.get("is_own_video"):
            asyncio.create_task(award_xp(ctx.bot, user.id, "own_video_published"))
        await q.edit_message_text(
            f"✅ *Опубліковано в {COMMUNITY_CHANNEL}!* 🔥",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📱 Caption для соцмереж", callback_data="share_socials")
            ]])
        )
    except Exception as e:
        logger.warning(f"Share voice error: {e}")
        await q.edit_message_text("😔 Не вдалось опублікувати.")

async def handle_message_reaction(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """XP за отриману реакцію на пост в Community."""
    reaction = update.message_reaction
    if not reaction or not reaction.new_reaction:
        return
    msg_id = str(reaction.message_id)
    db = load_db()
    cm = db.get("_community_posts", {})
    if msg_id not in cm:
        return
    post_uid = cm[msg_id].get("uid")
    if not post_uid or post_uid == reaction.user.id:
        return  # не нараховуємо XP собі
    bot = ctx.bot
    asyncio.create_task(award_xp(bot, post_uid, "reaction_received"))
    # Перевірити чи досягли 10+ реакцій
    post_reactions = get_s(post_uid).get("community_reactions", {}).get(str(post_uid), 0)
    if post_reactions == 10:
        asyncio.create_task(award_xp(bot, post_uid, "reaction_x10"))
    # Власне відео
    if get_s(post_uid).get("is_own_video"):
        asyncio.create_task(award_xp(bot, post_uid, "own_video_reaction"))
        if post_reactions == 10:
            asyncio.create_task(award_xp(bot, post_uid, "own_video_reaction_x10"))
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Добре, не публікуємо 👍", reply_markup=main_menu())


async def cb_share_video_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Надіслати відео-монолог напряму в Telegram-групу (LIVE_GROUP_ID)."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    group_id = s.get("live_group_id") or ctx.bot_data.get("live_group_id")
    if not group_id:
        await q.message.reply_text(
            "❌ Групу не підключено. Адмін має спочатку запустити /setup_live_group."
        )
        return

    file_id = s.get("last_video_file_id") or s.get("pending_video_file_id")
    if not file_id:
        await q.message.reply_text("❌ Відео не знайдено. Спробуй надіслати ще раз.")
        return

    name  = s.get("name") or user.first_name or "Студент"
    level = LEVEL_NAMES.get(s.get("level", ""), s.get("level", ""))
    topic = s.get("last_topic", "")
    score = s.get("pending_video_score", 0)
    score_str = f"  |  Бал: *{score}/100*" if score else ""
    caption = (
        f"🎬 *{name}* — відео-монолог\nРівень: *{level}*{score_str}" + (f"\nТема: _{topic}_" if topic else "")
    )

    try:
        await ctx.bot.send_video(
            chat_id=group_id,
            video=file_id,
            caption=caption,
            parse_mode="Markdown"
        )
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text("✅ Відео надіслано в групу!")
    except Exception as e:
        logger.warning(f"cb_share_video_group error: {e}")
        await q.message.reply_text(f"❌ Не вдалось надіслати: {e}")


async def cb_video_ai_eval(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Кнопка 'AI-оцінка монологу' — запускає аналіз відео."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    file_id = s.get("pending_video_file_id")
    if not file_id:
        await q.message.reply_text("❌ Відео не знайдено. Надішли ще раз.")
        return

    # Перенаправляємо в handle_video зі штучним update щоб запустити AI eval
    # Зберігаємо file_id і запускаємо AI напряму
    msg = await q.edit_message_text(
        "🎬 *Аналізую відео...* (~30 сек)\n\n_AI дивиться і слухає_",
        parse_mode="Markdown"
    )

    level   = s.get("level","A1")
    lvl_name= LEVEL_NAMES.get(level, level)
    topic   = s.get("last_topic", "Speak about what you watched")

    import aiohttp as _aiohttp
    openai_key = os.environ.get("OPENAI_API_KEY","")
    transcript = None

    if openai_key:
        try:
            tg_file  = await ctx.bot.get_file(file_id)
            import io as _io
            buf = _io.BytesIO()
            await tg_file.download_to_memory(buf)
            buf.seek(0)
            async with _aiohttp.ClientSession() as sess:
                form = _aiohttp.FormData()
                form.add_field("file", buf, filename="video.mp4", content_type="video/mp4")
                form.add_field("model","whisper-1")
                form.add_field("language","en")
                async with sess.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {openai_key}"},
                    data=form
                ) as r:
                    if r.status == 200:
                        j = await r.json()
                        transcript = j.get("text","").strip()
        except Exception as e:
            logger.warning(f"cb_video_ai_eval whisper error: {e}")

    if transcript:
        try:
            prompt = (
                f"English learner (level {lvl_name}) recorded a video monologue.\n"
                f"Topic: {topic}\n\n"
                f"Transcript:\n{transcript[:1200]}\n\n"
                "Evaluate their spoken English. Find the ONE most important real mistake.\n"
                "RULE: Never suggest changing a grammatically correct tense.\n\n"
                "Write in Ukrainian. Warm tone.\n\n"
                "FORMAT:\n"
                "🎯 *Загальний бал: X/100*\n\n"
                "✅ *Що вийшло добре:*\n[процитуй їхні слова]\n\n"
                "🔧 *Що виправити:*\n"
                "Сказав: \"[фраза]\"\n"
                "Правильно: \"[виправлення]\"\n"
                "Чому: [пояснення]\n\n"
                "🚀 *Спробуй наступного разу:*\n[конкретна порада]\n\n"
                "Max 130 words. If score>=75: 🌟 Опублікуй з #SpeakChain!"
            )
            cr = claude_client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=600,
                messages=[{"role":"user","content": prompt}]
            )
            feedback = cr.content[0].text

            import re as _re
            score = 0
            for line in feedback.split("\n"):
                if "загальний бал" in line.lower():
                    nums = _re.findall(r'\b(\d{1,3})\b', line)
                    for n in nums:
                        if 0 < int(n) <= 100: score = int(n); break
                    if score: break

            upd_s(user.id, {"pending_video_score": score, "pending_video_transcript": transcript})

            await msg.edit_text(
                f"🎬 *Оцінка відео-монологу*\n\n{feedback}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📹 В Community",      callback_data="share_video_confirm")],
                    [InlineKeyboardButton("📤 В Premium-групу",  callback_data="share_video_group")],
                    [InlineKeyboardButton("🔁 Записати ще раз",  callback_data="share_video_cancel")],
                ])
            )
            return
        except Exception as e:
            logger.warning(f"cb_video_ai_eval claude error: {e}")

    # Немає транскрипції або помилка — показуємо без AI
    await msg.edit_text(
        "🎬 *Відео отримано!*\n\n_AI-аналіз тимчасово недоступний_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📹 В Community",      callback_data="share_video_confirm")],
            [InlineKeyboardButton("📤 В Premium-групу",  callback_data="share_video_group")],
            [InlineKeyboardButton("🔁 Записати ще раз",  callback_data="share_video_cancel")],
        ])
    )

async def cb_share_video_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Публікує відео в Community канал."""
    q    = update.callback_query
    user = q.from_user
    s    = get_s(user.id)
    await q.answer()

    file_id = s.get("last_video_file_id","")
    if not file_id:
        await q.edit_message_text("😔 Відео не знайдено. Спробуй надіслати ще раз.")
        return

    level = LEVEL_NAMES.get(s.get("level",""), s.get("level",""))
    topic = s.get("cycle_topic") or s.get("quiz_lesson_title") or ""
    caption = (
        f"📹 *{user.first_name}* — {level}\n"
        + (f"Тема: _{topic}_\n" if topic else "")
        + "Навчається в @SpeakChainBot 🚀"
    )

    try:
        # Спробуємо як video, потім як video_note
        try:
            await ctx.bot.send_video(
                chat_id=COMMUNITY_CHANNEL,
                video=file_id,
                caption=caption,
                parse_mode="Markdown"
            )
        except Exception:
            await ctx.bot.send_video_note(
                chat_id=COMMUNITY_CHANNEL,
                video_note=file_id
            )
        await q.edit_message_text(
            f"🎉 *Опубліковано в {COMMUNITY_CHANNEL}!*\n\n"
            "Дякую за сміливість! 🔥",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Failed to publish video: {e}")
        await q.edit_message_text(
            "😔 Не вдалось опублікувати. Перевір що бот є адміном каналу."
        )

async def cb_share_video_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Зрозуміло — залишаємо для себе 👍")


async def process_text_monologue(update: Update, ctx: ContextTypes.DEFAULT_TYPE, transcript: str):
    """Обробляє текстовий монолог — оцінює через Claude без транскрипції."""
    user  = update.effective_user
    s     = get_s(user.id)
    level = s.get("level", "A1")

    # Знаходимо поточний урок
    lesson_id = s.get("current_lesson_id")
    lesson = s.get("current_lesson_data")
    if not lesson:
        lesson = {
            "id": "default", "url": "", "title": "Відео",
            "topic": "Talk about what you learned",
            "grammar": "Present Simple", "hint": "I think... / I found it interesting that..."
        }

    await update.message.reply_text("⏳ Оцінюю твій текст...")

    try:
        interests = s.get("interests", [])
        profession = s.get("profession", "")
        personal_context = ""
        if interests or profession:
            parts = []
            if profession: parts.append(f"profession: {profession}")
            if interests:  parts.append(f"interests: {', '.join(interests)}")
            personal_context = f"Student background — {'; '.join(parts)}.\n"

        prompt = f"""You are a friendly English speaking coach. Read what this student wrote and give honest, simple feedback.

Level: {level} ({LEVEL_NAMES.get(level,level)})
{personal_context}Video topic: {lesson['title']}
Grammar focus: {lesson['grammar']}

What the student wrote:
\"\"\"{transcript}\"\"\"

Evaluate four areas, score each out of 100:
- Grammar | Vocabulary | Fluency | Pronunciation

Write feedback in Ukrainian. Warm, simple, no jargon.

FORMAT:
🎯 *Загальний бал: X/100*
└ 📐 Граматика: X | 📚 Лексика: X | 🌊 Fluency: X | 🔉 Вимова: X

✅ *Що добре:* [1-2 речення]
🔧 *Що покращити:* [1 конкретна помилка з виправленням]
🚀 *Спробуй наступного разу:* [одне речення]

Max 130 words."""

        cr = claude_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        feedback = cr.content[0].text

        score = 0
        pronunciation_score = fluency_score = grammar_score = vocab_score = 0
        for line in feedback.split("\n"):
            ll = line.lower()
            if "загальний бал" in ll:
                nums = re.findall(r'\b(\d{1,3})\b', line)
                for n in nums:
                    if 0 < int(n) <= 100: score = int(n); break
            if "вимова" in ll or "pronunciation" in ll:
                nums = re.findall(r'\b(\d{1,3})\b', line)
                if nums: pronunciation_score = int(nums[-1])
            if "fluency" in ll or "плавніст" in ll:
                nums = re.findall(r'\b(\d{1,3})\b', line)
                if nums: fluency_score = int(nums[-1])
            if "граматика" in ll:
                nums = re.findall(r'\b(\d{1,3})\b', line)
                if nums: grammar_score = int(nums[-1])
            if "лексика" in ll:
                nums = re.findall(r'\b(\d{1,3})\b', line)
                if nums: vocab_score = int(nums[-1])

        done = s.get("done_lessons", [])
        if lesson_id and lesson_id != "custom" and lesson_id not in done:
            done.append(lesson_id)

        mastered = s.get("mastered_grammar", [])
        grammar_focus = lesson.get("grammar", "")
        if grammar_focus:
            level_topics = CEFR_GRAMMAR.get(level, [])
            for topic in level_topics:
                if any(kw.lower() in grammar_focus.lower() for kw in topic.split()[:2]) and topic not in mastered:
                    mastered.append(topic)

        scores = s.get("scores", [])
        scores.append({"lesson_num": len(done), "level": level, "score": score,
                       "date": datetime.now().isoformat()})
        streak, is_record = update_streak(user.id)
        streak_msg = streak_message(streak, is_record)

        upd_s(user.id, {
            "done_lessons": done, "scores": scores,
            "mastered_grammar": mastered,
            "current_lesson_id": None,
            "last_date": datetime.now().isoformat()[:10],
            "last_pronunciation_score": pronunciation_score,
            "last_fluency_score":       fluency_score,
            "last_grammar_score":       grammar_score,
            "last_vocab_score":         vocab_score,
        })

        # ── Chain + Identity + Analytics ──────────────────
        _s_after = get_s(user.id)
        asyncio.create_task(chain_complete(ctx.bot, user.id, _s_after, upd_s))
        asyncio.create_task(maybe_identity_shift(ctx.bot, user.id, _s_after, upd_s))
        asyncio.create_task(track_event(user.id, "lesson_complete", _s_after, upd_s))
        asyncio.create_task(after_trial_chain(ctx.bot, user.id, _s_after, upd_s))
        asyncio.create_task(check_sync_bonus(ctx.bot, user.id, _s_after, upd_s))
        asyncio.create_task(_maybe_show_referral_prompt(ctx.bot, user.id, _s_after))

        # Chain Dashboard кнопка після уроку
        if BOT_WEBHOOK_URL:
            _db_now   = load_db()
            _dash_url = _build_chain_dashboard_url(user.id, _s_after, db=_db_now)
            asyncio.create_task(ctx.bot.send_message(
                user.id,
                "🔗 Подивись як росте твій ланцюжок:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📊 Chain Dashboard", web_app=WebAppInfo(url=_dash_url))
                ]])
            ))

        # ── Перший монолог ─────────────────────────────────────
        s2 = get_s(user.id)
        if not s2.get("first_voice_file_id"):
            upd_s(user.id, {
                "first_voice_date":  datetime.now().strftime("%Y-%m-%d"),
                "first_voice_score": score,
            })

        # ── Voice timeline кожні 5 уроків ──────────────────────
        if len(done) % 5 == 0:
            tl = s2.get("voice_timeline", [])
            tl.append({
                "file_id":       "",
                "date":          datetime.now().strftime("%Y-%m-%d"),
                "score":         score,
                "pronunciation": pronunciation_score,
                "fluency":       fluency_score,
                "lesson_num":    len(done),
            })
            upd_s(user.id, {"voice_timeline": tl[-10:]})

        # ── Milestone перевірка (Polyglot Patch) ──
        if not s.get("is_first_lesson", False):
            await check_and_send_milestone(ctx.bot, user.id, len(done), get_s(user.id))

        await update.message.reply_text(
            f"✅ *Оцінка готова!*\n\n{feedback}{streak_msg}",
            parse_mode="Markdown"
        )

        # Пропонуємо тест
        upd_s(user.id, {
            "quiz_lesson_title":   lesson.get("title", ""),
            "quiz_lesson_grammar": lesson.get("grammar", ""),
            "quiz_transcript":     transcript,
            "quiz_level":          level,
            "quiz_after_action":   "fork",
        })
        await update.message.reply_text(
            "📝 *Закріпи матеріал!*\n\nКороткий тест — ~2 хвилини 🎯",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Пройти тест", callback_data="quiz_start"),
                InlineKeyboardButton("⏭ Пропустити",  callback_data="quiz_skip"),
            ]])
        )

    except Exception as e:
        logger.error(f"Text monologue error uid={user.id}: {type(e).__name__}: {e}")
        await update.message.reply_text(
            "😔 Помилка оцінки. Спробуй ще раз.",
            reply_markup=main_menu()
        )

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # ── В групах бот мовчить — /myid обробляється окремим CommandHandler ──
    chat = update.effective_chat
    if chat and chat.type in ("group", "supergroup", "channel"):
        return

    user = update.effective_user
    s    = get_s(user.id)
    text = update.message.text.strip()

    # ── Demo mode: перехоплення відповіді на урок ────────
    _demo_handled = await maybe_handle_demo_answer(update, ctx, get_s, upd_s, claude_client)
    if _demo_handled:
        return

    # ── АДМІН — всі режими очікування (найвищий пріоритет) ──
    if is_admin(user.id):
        admin_waiting = ADMIN_STATE.get("waiting", "")

        # Відповідь на ForceReply або стан очікування
        is_reply_to_bot = bool(
            update.message.reply_to_message and
            update.message.reply_to_message.from_user and
            update.message.reply_to_message.from_user.is_bot
        )

        if admin_waiting == "gen_ref" or (is_reply_to_bot and admin_waiting == "gen_ref"):
            ADMIN_STATE["waiting"] = ""
            await _do_gen_ref(update, ctx, text)
            return
        if is_reply_to_bot and admin_waiting == "":
            # Відповідь на будь-яке повідомлення бота — перевіряємо текст
            reply_text = update.message.reply_to_message.text or ""
            if "username блогера" in reply_text:
                await _do_gen_ref(update, ctx, text)
                return
        if admin_waiting == "blogger_code":
            ADMIN_STATE["waiting"] = ""
            await _do_create_blogger_code(update, ctx, text)
            return
        if admin_waiting == "blogger_view":
            ADMIN_STATE["waiting"] = ""
            ctx.args = [text.lstrip("@")]
            await cmd_view_blogger(update, ctx)
            return

    # ── Секретний код блогера ──
    if s.get("waiting_blogger_code"):
        handled = await handle_blogger_code_input(update, ctx)
        if handled:
            return

    # ── Оферта і приватність — реакція на слово ──
    if text.lower() in ("оферта", "оферту", "договір", "умови", "offer"):
        await _send_offer(update.message, ctx)
        return
    if text.lower() in ("приватність", "конфіденційність", "privacy", "персональні дані", "дані"):
        await cmd_privacy(update, ctx)
        return

    # ── Кастомний профіль для /tutor_me ──
    if s.get("syl_waiting_custom_prof"):
        handled = await handle_syllabus_custom_profile(update, ctx)
        if handled:
            return

    # ── Реєстрація для speaking partner ──
    if s.get("partner_reg_step"):
        handled = await handle_partner_registration(update, ctx)
        if handled:
            return

    # ── Якщо кнопка меню — скидаємо ВСІ waiting_* стани одразу ──────
    if text in ALL_MENU_BUTTONS:
        upd_s(user.id, {
            "waiting_video":          False,
            "waiting_mining_phrase":  False,
            "waiting_text_monologue": False,
            "waiting_social_link":    False,
            "waiting_admin_question": False,
        })
        # Далі падає в обробку кнопок меню нижче

    # ── Sentence Mining — обробка введеної фрази ──────────────────────
    if s.get("waiting_mining_phrase"):
        if text in ALL_MENU_BUTTONS:
            pass  # скинуто вище — далі
        elif len(text) > 2:
            upd_s(user.id, {"waiting_mining_phrase": False})
            lesson = s.get("pending_mining_lesson") or s.get("current_lesson_data") or {}
            await _save_mined_sentence(user.id, text, lesson)
            upd_s(user.id, {"pending_mining_lesson": {}})
            due_count = len(_srs_due_words(get_s(user.id)))
            await update.message.reply_text(
                f"💎 *Збережено!*\n\n"
                f"▸ _{text}_\n\n"
                f"Повторю через день 🧠 Всього в картотеці: *{due_count}*",
                parse_mode="Markdown"
            )
            await _send_monologue_prompt(ctx.bot, user.id)
            return
        else:
            await update.message.reply_text(
                "Напиши фразу англійською (мінімум 3 символи) 👇\n\n"
                "_Наприклад: «I've been working on this for a while»_",
                parse_mode="Markdown"
            )
            return

    if s.get("waiting_text_monologue"):
        if text in ALL_MENU_BUTTONS:
            pass  # скинуто вище — далі
        elif len(text) > 10:
            upd_s(user.id, {"waiting_text_monologue": False})
            await process_text_monologue(update, ctx, text)
            return
        else:
            await update.message.reply_text(
                "✍️ Напиши кілька речень англійською — мінімум одне повне речення 👇"
            )
            return

    # ── Питання до адміна (перед кнопками меню щоб не блокувалось) ──
    if s.get("waiting_admin_question"):
        upd_s(user.id, {"waiting_admin_question": False})
        name    = s.get("name") or user.first_name or "Студент"
        q_text  = update.message.text.strip()
        uid     = user.id
        # Зберігаємо в історію питань
        history = s.get("admin_questions", [])
        history.append({"date": datetime.now().strftime("%Y-%m-%d %H:%M"), "q": q_text, "a": ""})
        upd_s(uid, {"admin_questions": history[-50:]})   # зберігаємо останні 50
        # Надсилаємо адміну
        if ADMIN_ID:
            try:
                await ctx.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"✉️ *Питання від студента*\n\n👤 {name} (`{uid}`)\n\n❓ {q_text}\n\n_Щоб відповісти:_ `/reply {uid} <текст відповіді>`"
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning(f"admin_question forward error: {e}")
        await update.message.reply_text(
            "✅ Питання передано! Адмін відповість тобі особисто.",
            parse_mode="Markdown"
        )
        return

    # Кнопки меню
    if text in ("🎯 Порадь мені відео", "🎯 Порадь мені відео", "🎬 Наступне відео", "📚 Урок"): await cmd_bot_recommends(update, ctx); return
    if text in ("🎬 Мої відео", "📎 Я вже обрав відео", "📎 Я сам обрав", "🎥 Опрацювати відео", "🎤 Своє відео"): await cmd_myvideo(update, ctx); return
    if text in ("📊 Прогрес", "📊 Мій шлях A1→C2", "📊 Мій прогрес"):  await cmd_progress(update, ctx); return
    if text in ("📚 Мої слова", "📚 Словник", "🗃 Картотека", "📚 Мої фрази"): await cmd_my_words(update, ctx); return
    if text in ("🎯 Челендж дня", "🎯 Челендж"):                   await cmd_student_challenge(update, ctx); return
    if text == "🏆 Мій челендж":                                     await cmd_blogger_challenge_panel(update, ctx); return
    if text in ("❓ Допомога"):                                        await cmd_help(update, ctx); return
    if text in ("👤 Панель блогера") and is_blogger(user.id):          await cmd_my_students(update, ctx); return

    # ── Студент вставляє посилання на соц. публікацію ──────
    if s.get("waiting_social_link"):
        upd_s(user.id, {"waiting_social_link": False})
        today = datetime.now().strftime("%Y-%m-%d")

        # Перевіряємо що це схоже на URL
        is_url = text.startswith("http") and ("." in text)
        if not is_url:
            await update.message.reply_text(
                "⚠️ Схоже це не посилання. Спробуй ще раз або скасуй /start",
                parse_mode="Markdown"
            )
            upd_s(user.id, {"waiting_social_link": True})
            return

        # Зберігаємо посилання і активуємо потрійний XP день
        social_links = s.get("social_publish_links", [])
        social_links.append({"url": text, "date": today})
        upd_s(user.id, {
            "social_publish_links": social_links[-20:],  # останні 20
            "triple_xp_date":       today,
        })

        # Нараховуємо XP за публікацію (з урахуванням що triple вже активний)
        xp_added = XP_AWARDS.get("shared_community", 8) * 3  # 24 XP за факт публікації
        s2       = get_s(user.id)
        upd_s(user.id, {"xp_total": s2.get("xp_total", 0) + xp_added})

        await update.message.reply_text(
            "🔥 *Потрійний XP день активовано!*\n\n"
            f"*+{xp_added} XP* за публікацію\n\n"
            "До кінця дня *усі* твої XP множаться на 3:\n"
            "• Shadowing: +15 XP замість +5\n"
            "• Сесія говоріння: +30 XP замість +10\n"
            "• Збережена фраза: +9 XP замість +3\n\n"
            "Говори більше сьогодні — це твій найкращий день! 🚀",
            parse_mode="Markdown"
        )
        return
    if s.get("waiting_blogger_video_url"):
        vid_id = extract_youtube_id(text)
        if vid_id:
            upd_s(user.id, {"waiting_blogger_video_url": False})
            username    = user.username or str(user.id)
            ref_link    = f"{MINIAPP_URL}?startapp=ref_{username}_yt_{vid_id}"
            await update.message.reply_text(
                "✅ *Готове посилання для поширення:*\n\n"
                f"`{ref_link}`\n\n"
                "_Натисни щоб скопіювати_ 👆",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🎬 Ще одне відео", callback_data="blogger_gen_video_link")
                ]])
            )
        else:
            await update.message.reply_text(
                "⚠️ Не розпізнав YouTube посилання. Спробуй ще раз — має виглядати як:\n"
                "`https://youtube.com/watch?v=...` або `https://youtu.be/...`",
                parse_mode="Markdown"
            )
        return
    if s.get("waiting_video") or is_supported_video(text):
        await handle_video_link(update, ctx); return

    await update.message.reply_text(
        "Використовуй кнопки меню внизу 👇",
        reply_markup=main_menu()
    )

# ── Handle any supported video link ──────────────────
async def handle_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обробляє відеофайли надіслані в бот — пропонує поширити в Community."""
    user    = update.effective_user
    video   = update.message.video or update.message.video_note
    if not video: return
    file_id = video.file_id
    is_note = bool(update.message.video_note)
    upd_s(user.id, {
        "pending_video_file_id": file_id,
        "pending_video_is_note": is_note,
        "last_video_file_id":    file_id,
    })
    s     = get_s(user.id)
    level = LEVEL_NAMES.get(s.get("level",""), s.get("level",""))

    # ── Перевіряємо активну дуель ──────────────────────
    pending_duel = s.get("pending_duel_id", "")
    if pending_duel:
        duel = _get_duel(pending_duel)
        if duel and duel.get("status") == "accepted":
            upd_s(user.id, {"pending_duel_id": None, "duel_topic": None})
            challenger_uid = int(duel.get("challenger", 0))
            challenged_uid = int(duel.get("challenged", 0))
            topic          = duel.get("topic", "")
            my_name        = s.get("name", user.first_name)

            # Надсилаємо відео ініціатору
            opponent_uid = challenger_uid if str(user.id) == duel.get("challenged") else challenged_uid
            opp_name     = get_s(opponent_uid).get("name", "Опонент")
            try:
                if is_note:
                    await ctx.bot.send_video_note(
                        chat_id=opponent_uid,
                        video_note=file_id,
                    )
                else:
                    await ctx.bot.send_video(
                        chat_id=opponent_uid,
                        video=file_id,
                        caption=f"⚔️ *{my_name}* надіслав(ла) відео відповідь на виклик!\n🎯 Тема: _{topic}_",
                        parse_mode="Markdown"
                    )
                # Повідомлення опоненту з пропозицією відповісти
                await ctx.bot.send_message(
                    chat_id=opponent_uid,
                    text=(
                        f"⚔️ *{my_name}* надіслав(ла) своє відео!\n\n"
                        f"🎯 Тема: _{topic}_\n\n"
                        "Тепер твій хід — запиши відповідь 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🎬 Записати відео відповідь", callback_data=f"duel_accept_{pending_duel}")],
                        [InlineKeyboardButton("🎙 Голосову відповідь",        callback_data=f"duel_accept_{pending_duel}")],
                    ])
                )
            except Exception as e:
                logger.warning(f"duel video forward error: {e}")

            await update.message.reply_text(
                f"✅ *Відео надіслано суперникам!*\n\n"
                f"Чекаємо відповіді від *{opp_name}* ⏳",
                parse_mode="Markdown"
            )
            return

    # ── Стандартний флоу ───────────────────────────────
    kb = [
        [InlineKeyboardButton("🤖 AI-оцінка монологу",  callback_data="video_ai_eval")],
        [InlineKeyboardButton("📹 В Community",          callback_data="share_video_confirm")],
        [InlineKeyboardButton("📤 В Premium-групу",      callback_data="share_video_group")],
        [InlineKeyboardButton("🔁 Записати ще раз",      callback_data="share_video_cancel")],
    ]
    # Кнопка дуелі якщо є блогер
    if s.get("affiliate_blogger"):
        kb.append([InlineKeyboardButton("⚔️ Кинути виклик", callback_data="duel_challenge")])

    await update.message.reply_text(
        f"🎬 *Відео отримано!* Рівень: *{level}*\n\n"
        "Хочеш отримати AI-оцінку свого монологу?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def handle_video_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обробляє YouTube посилання надіслане в бот — показує плеєр і генерує завдання."""
    user      = update.effective_user
    s         = get_s(user.id)
    text      = (update.message.text or "").strip()
    video_url = text
    platform  = detect_platform(video_url)
    vid_id    = extract_youtube_id(video_url)

    # ── Зберігаємо в бібліотеку відео ────────────────────
    s2           = get_s(user.id)
    video_history = s2.get("video_history", [])
    existing_ids  = [v.get("vid_id") for v in video_history]
    if vid_id and vid_id not in existing_ids:
        # Отримуємо назву через YouTube oEmbed (безкоштовно, без ключа)
        yt_title = ""
        try:
            import httpx as _httpx
            oe = _httpx.get(
                f"https://www.youtube.com/oembed?url=https://youtu.be/{vid_id}&format=json",
                timeout=4
            )
            if oe.status_code == 200:
                yt_title = oe.json().get("title", "")[:80]
        except Exception:
            pass
        video_history.insert(0, {
            "url":    video_url,
            "vid_id": vid_id,
            "date":   datetime.now().strftime("%Y-%m-%d"),
            "title":  yt_title or f"YouTube відео",
        })
        video_history = video_history[:30]  # зберігаємо останні 30

    upd_s(user.id, {
        "waiting_video":         False,
        "current_lesson_id":     "custom",
        "custom_video_url":      video_url,
        "custom_video_platform": platform,
        "video_history":         video_history,
    })

    # Показуємо кнопку плеєра одразу
    if platform == "youtube" and WEBAPP_URL:
        await update.message.reply_text(
            "✅ *YouTube відео отримано!*\n\n"
            "Відкрий у плеєрі — shadowing, петля, запис 👇",
            parse_mode="Markdown",
            reply_markup=video_watch_keyboard(video_url, s=get_s(user.id))
        )

    """Обробляє відеофайли надіслані в бот — пропонує поширити в Community."""
    user = update.effective_user
    s    = get_s(user.id)

    video     = update.message.video or update.message.video_note
    if not video: return
    file_id   = video.file_id
    is_note   = bool(update.message.video_note)  # кругле відео

    # Зберігаємо для можливого поширення
    upd_s(user.id, {"pending_video_file_id": file_id, "pending_video_is_note": is_note})

    await update.message.reply_text(
        "🎬 *Відео отримано!*\n\n"
        "Хочеш поділитись з Community або в соцмережах?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 AI-оцінка монологу",  callback_data="video_ai_eval")],
            [InlineKeyboardButton("📹 В Community",          callback_data="share_video_confirm")],
            [InlineKeyboardButton("📤 В Premium-групу",      callback_data="share_video_group")],
            [InlineKeyboardButton("🔁 Записати ще раз",      callback_data="share_video_cancel")],
        ])
    )



    user     = update.effective_user
    s        = get_s(user.id)
    text     = update.message.text.strip()
    platform = detect_platform(text)

    if platform == "unknown":
        await update.message.reply_text(
            "Надішли посилання на YouTube, TikTok або Instagram Reels 👇"
        )
        return

    platform_labels = {
        "youtube":   "YouTube",
        "tiktok":    "TikTok",
        "instagram": "Instagram Reels",
    }
    platform_label = platform_labels.get(platform, "відео")

    upd_s(user.id, {
        "waiting_video": False,
        "current_lesson_id": "custom",
        "custom_video_url": text,
        "custom_video_platform": platform,
    })
    level = s.get("level", "A1")

    # ── Кнопку плеєра показуємо ОДРАЗУ — не чекаємо Claude ──
    if platform == "youtube":
        await update.message.reply_text(
            f"✅ *YouTube відео отримано!*\n\n"
            "Відкрий у плеєрі — shadowing, петля, запис — все там 👇",
            parse_mode="Markdown",
            reply_markup=video_watch_keyboard(text, s=get_s(user.id))
        )

    msg = await update.message.reply_text(f"⏳ Готую завдання...")

    try:
        interests_str = ", ".join(s.get("interests", []) or ["general"])
        pr = (
            f"Student level: {level}. They watched this {platform_label} video: {text}\n"
            f"Student profession: {s.get('profession','unknown')}. "
            f"Interests: {interests_str}.\n"
            f"Create a speaking practice task. The TOPIC must start with this exact Ukrainian phrase: "
            f"'А тепер практика: повтори те, що говорилось у відео. Рекомендую застосувати і модифікувати ці речення до себе та свого життя — так мозок включається активніше.' "
            f"Then add 1 personalised sentence. Reply ONLY:\n"
            f"TOPIC: [fixed Ukrainian phrase + 1 personalised sentence]\n"
            f"GRAMMAR: [grammar focus for {level}]\n"
            f"HINT: [2-3 English sentence starters adapted to their interests]\n"
            f"KEYWORDS: [3-5 key English words/phrases from this topic for vocabulary]"
        )
        cr = claude_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=250,
            messages=[{"role": "user", "content": pr}]
        )
        task    = cr.content[0].text
        topic   = "А тепер практика: повтори те, що говорилось у відео. Рекомендую застосувати і модифікувати ці речення до себе та свого життя — так мозок включається активніше."
        grammar = "Present Simple + I think / I believe / In my view"
        hint    = "In this video I learned... / In my life I also... / I found it interesting that..."
        keywords = ""
        for line in task.splitlines():
            line = line.strip()
            if line.startswith("TOPIC:"):    topic    = line[6:].strip()
            elif line.startswith("GRAMMAR:"): grammar  = line[8:].strip()
            elif line.startswith("HINT:"):    hint     = line[5:].strip()
            elif line.startswith("KEYWORDS:"): keywords = line[9:].strip()

        kw_line = f"\n📝 *Ключові слова:* _{keywords}_" if keywords else ""
        await msg.edit_text(
            f"🎯 *Завдання для практики:*\n\n"
            f"🎤 {topic}\n\n"
            f"📌 Граматика: _{grammar}_\n"
            f"💡 Підказка: _{hint}_{kw_line}\n\n"
            "Подивись відео у плеєрі вище, потім надішли голосовий 🎙",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Video link task error: {e}")
        await msg.edit_text(
            "✅ Відео прийнято!\n\n"
            "А тепер практика: повтори те, що говорилось у відео. "
            "Рекомендую застосувати і модифікувати ці речення до себе та свого життя — так мозок включається активніше.\n\n"
            "Подивись відео, потім натисни 🎙 щоб записати монолог 👇",
            parse_mode="Markdown",
        )

# ── /bot_recommends ──────────────────────────────────
async def cmd_bot_recommends(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    s    = get_s(user.id)
    videos_watched = s.get("videos_watched", 0)

    if not s.get("onboarding_done"):
        kids_age     = s.get("kids_age", "")
        is_small_kid = kids_age in ("0–1 рік", "1–3 роки", "0–3 років", "4–6 років")
        if not is_small_kid:
            await update.message.reply_text(
                "Схоже, ми ще не знайомі 👋\n\n"
                "Дай відповідь на кілька запитань, щоб отримати свій індивідуальний прогрес 👇",
                parse_mode="Markdown"
            )
        await update.message.reply_text(
            "Для чого тобі потрібна англійська? 👇",
            parse_mode="Markdown",
            reply_markup=goal_kb()
        )
        return
    else:
        if not await check_premium_gate(update, s):
            return
        phrase = random.choice(MOTIVATIONAL)
        await update.message.reply_text(phrase)
        thinking = await update.message.reply_text("🔍 Підбираю відео...")
        lesson = await youtube_search_lesson(s)
        await thinking.delete()
        if not lesson:
            await update.message.reply_text(
                "😔 YouTube зараз не відповідає. Спробуй через хвилину 👇",
                reply_markup=main_menu()
            )
            return
        upd_s(user.id, {
            "current_lesson_id":    lesson["id"],
            "current_lesson_title": lesson.get("title","відео"),
        })
        # Якщо урок підібраний під gap — очищаємо pending_gaps
        if lesson.get("gap_used"):
            upd_s(user.id, {"pending_gaps": {}})
        # Механіка 2: нагадування якщо не запише монолог через 3 год
        from datetime import timedelta
        update.message._bot.get_updates  # dummy to get bot reference
        ctx.job_queue.run_once(
            send_unfinished_reminder,
            when=timedelta(hours=3),
            data={"uid": user.id},
            name=f"unfinished_{user.id}"
        )
        await _send_merged_lesson_card(ctx.bot, user.id, lesson, s)

# ── Daily reminder ────────────────────────────────────

# ── Механіка 1: Нагадування через 24 год після першого уроку ──
async def send_day2_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    """Надсилається через 24 год після першого уроку якщо студент не повернувся."""
    job_data = ctx.job.data
    uid      = job_data["uid"]
    s        = get_s(uid)

    # Якщо вже повернувся сьогодні — не турбуємо
    today = datetime.now().strftime("%Y-%m-%d")
    if s.get("last_date") == today:
        return

    streak = s.get("streak_days", 0)
    level  = LEVEL_NAMES.get(s.get("level",""), "")

    try:
        await ctx.bot.send_message(
            chat_id=uid,
            text=(
                f"🔥 Привіт! Вчора ти зробив перший урок — це вже початок!\n\n"
                f"Рівень: *{level}* | Стрік: *{streak} дн.*\n\n"
                "Один урок сьогодні — і стрік живий. Це займе 10 хвилин 👇"
            ),
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
    except Exception as e:
        logger.warning(f"Day2 reminder failed {uid}: {e}")

# ── Механіка 2: Нагадування про незавершений монолог ─────
async def send_unfinished_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    """Надсилається через 3 год якщо студент дивився відео але не записав монолог."""
    job_data = ctx.job.data
    uid      = job_data["uid"]
    s        = get_s(uid)

    # Якщо вже записав — не турбуємо
    if not s.get("current_lesson_id") or s.get("pending_voice_file_id"):
        return

    lesson_title = s.get("current_lesson_title", "відео")
    topic        = s.get("quiz_lesson_topic", "")

    try:
        await ctx.bot.send_message(
            chat_id=uid,
            text=(
                f"🎙 Ти ще не записав монолог до *{lesson_title}*\n\n"
                + (f"📌 Тема: _{topic}_\n\n" if topic else "")
                + "Запис займає 1-2 хвилини — твій прогрес чекає! 👇"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎙 Записати зараз", callback_data="remind_record"),
                InlineKeyboardButton("⏭ Пропустити",      callback_data="remind_skip"),
            ]])
        )
    except Exception as e:
        logger.warning(f"Unfinished reminder failed {uid}: {e}")

# ── Механіка 3: М'який paywall — попередження на 4-5 день ──
async def send_trial_warning(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Щоденний маркетинговий сиквенс для тріалу.

    РОЗКЛАД (chain_len = кількість завершених ланок):
      Ланка 1  — не зробив урок наступного дня → нагадування «наступна ланка чекає»
      Ланка 2  — зробив урок → похвала + «ланцюжок має 2 ланки»
      Ланка 3  — показ фічей + перший натяк на оплату
      Ланка 4  — прогрес порівняно з ланкою 1
      Ланка 5  — FOMO + leaderboard
      Ланка 6  — «1 ланка до кінця тріалу»
      Ланка 7  — фінальний paywall
      Після 7  — soft paywall щодня поки не платять
    """
    from datetime import timedelta
    db    = load_db()
    today = datetime.now()

    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not s.get("onboarding_done"): continue
        if is_premium(s): continue
        if not s.get("registered_at"): continue

        # ── Рахуємо ланки, не дні ────────────────────────
        chain      = s.get("chain", {})
        chain_len  = chain.get("length", s.get("streak_days", 0)) or 0
        links_left = max(0, 7 - chain_len)
        last_date  = s.get("last_date", s.get("last_lesson_date", "")) or ""
        did_today  = last_date == today.strftime("%Y-%m-%d")

        done     = len(s.get("done_lessons", []))
        mastered = len(s.get("mastered_grammar", []))
        level    = LEVEL_NAMES.get(s.get("level", ""), "")
        name     = s.get("name", "Студенте")
        p        = get_prices(s)
        basic_price = p["basic_price"]
        basic_link  = p["basic_link"]
        prem_price  = p["prem_price"]
        prem_link   = p["prem_link"]
        ref_note    = p["ref_note"]

        try:

            # ══════════════════════════════════════════════════
            # НАГАДУВАННЯ "ПІЗНІШЕ" — юзер відклав paywall
            # ══════════════════════════════════════════════════
            remind_date = s.get("paywall_remind_date", "")
            if (remind_date == today.strftime("%Y-%m-%d")
                    and s.get("paywall_remind_later")
                    and not is_premium(s)
                    and not s.get(f"paywall_reminded_{remind_date}")):
                upd_s(int(uid), {f"paywall_reminded_{remind_date}": True})
                url_pw = ""
                if BOT_WEBHOOK_URL:
                    try:
                        from chain_engine import get_chain as _gc
                        url_pw = _build_paywall_url(int(uid), s)
                    except Exception:
                        pass
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("💳 Обрати план", web_app=WebAppInfo(url=url_pw))
                ]]) if url_pw else InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"⚡️ Basic — ${basic_price}/міс", url=basic_link)] if basic_link else [],
                ])
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"👋 {name}, ти просив нагадати!\n\n"
                        f"Твій прогрес збережено — *{chain_len} ланок* і *{len(s.get('done_lessons',[]))} уроків*.\n\n"
                        "Продовж звідси де зупинився 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=kb
                )

            # ══════════════════════════════════════════════════
            # ЛАНКА 1 — зробив перший урок але не повернувся
            # ══════════════════════════════════════════════════
            if chain_len == 1 and not did_today and not s.get("remind_link1_sent"):
                upd_s(int(uid), {"remind_link1_sent": True})
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"🔗 {name}, твоя наступна ланка чекає!\n\n"
                        f"◆◇◇◇◇◇◇ 1/7\n\n"
                        "Ланцюжок росте тільки коли ти повертаєшся.\n"
                        "5 хвилин сьогодні — і буде вже 2 ланки 👇"
                    ),
                    reply_markup=main_menu()
                )

            # ══════════════════════════════════════════════════
            # ЛАНКА 2 — похвала + соціальне порівняння
            # ══════════════════════════════════════════════════
            elif chain_len == 2 and not s.get("remind_link2_sent"):
                upd_s(int(uid), {"remind_link2_sent": True})
                same_lvl = [u for u in db.values()
                            if u.get("level") == s.get("level") and u.get("onboarding_done")]
                avg = 0
                if same_lvl:
                    week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
                    avg = round(
                        sum(sum(1 for sc in u.get("scores", []) if sc.get("date", "")[:10] >= week_ago)
                            for u in same_lvl) / len(same_lvl), 1)
                social = (
                    f"\n\n📊 Студенти рівня *{level}* роблять в середньому "
                    f"*{avg}* уроки на тиждень. Ти на правильному шляху!"
                ) if avg > 0 else ""

                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"⚡️ {name}, твій ланцюжок має вже *2 ланки!*\n\n"
                        f"◆◆◇◇◇◇◇ 2/7\n\n"
                        f"Уроків: *{done}* · Граматики: *{mastered}* тем{social}\n\n"
                        "Знаєш що відрізняє тих хто досягає B2 від тих хто кидає?\n"
                        "Просто приходять на третій день.\n\n"
                        "Продовжуємо 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=main_menu()
                )

            # ══════════════════════════════════════════════════
            # ЛАНКА 3 — показ фічей + перший натяк на оплату
            # ══════════════════════════════════════════════════
            elif chain_len == 3 and not s.get("remind_link3_sent"):
                upd_s(int(uid), {"remind_link3_sent": True})
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"💪 *{name} — 3 ланки!*\n\n"
                        f"◆◆◆◇◇◇◇ 3/7\n\n"
                        "Ось що вже працює для тебе:\n"
                        "• 🎙 AI аналізує твою вимову\n"
                        "• 📊 XP росте з кожною ланкою\n"
                        "• 🔗 Ланцюжок показує твій прогрес\n"
                        "• 👥 Спільнота мовців\n\n"
                        f"Залишилось *{links_left} ланки* у пробному доступі.\n\n"
                        f"⚡️ *Basic — ${basic_price}/міс*{ref_note}\n"
                        "Необмежені уроки · Speaking Partner · Gap-аналіз"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"⚡️ Basic — ${basic_price}/міс",
                            url=basic_link)] if basic_link else [],
                        [InlineKeyboardButton("📊 Мій прогрес",
                            callback_data="progress_continue")],
                    ])
                )

            # ══════════════════════════════════════════════════
            # ЛАНКА 4 — прогрес порівняно з ланкою 1
            # ══════════════════════════════════════════════════
            elif chain_len == 4 and not s.get("remind_link4_sent"):
                upd_s(int(uid), {"remind_link4_sent": True})
                scores = s.get("scores", [])
                first_score  = s.get("first_voice_score", 0)
                recent_score = scores[-1].get("score", 0) if scores else 0
                delta     = recent_score - first_score
                delta_str = f"+{delta}" if delta >= 0 else str(delta)
                growth_line = f"\n🎙 Score: ланка 1 → зараз: *{delta_str} балів*\n" if first_score else ""

                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"📈 *{name} — 4 ланки. Дивись як ти ріс:*\n\n"
                        f"◆◆◆◆◇◇◇ 4/7\n"
                        f"{growth_line}\n"
                        f"Уроків: *{done}* · Граматики: *{mastered}* тем\n\n"
                        f"Залишилось безкоштовних: *{links_left} ланки*\n\n"
                        "Після тріалу прогрес збережеться — продовжуй з того місця 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"⚡️ Basic — ${basic_price}/міс",
                            url=basic_link)] if basic_link else [],
                        [InlineKeyboardButton("📊 Переглянути прогрес",
                            callback_data="progress_continue")],
                    ])
                )

            # ══════════════════════════════════════════════════
            # ЛАНКА 5 — FOMO + leaderboard
            # ══════════════════════════════════════════════════
            elif chain_len == 5 and not s.get("remind_link5_sent"):
                upd_s(int(uid), {"remind_link5_sent": True})
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"🏆 *{name} — 5 ланок!*\n\n"
                        f"◆◆◆◆◆◇◇ 5/7\n\n"
                        "Студенти які продовжують після тріалу досягають B1 "
                        "в середньому за *3 місяці*.\n\n"
                        "Ті хто зупиняються — через рік повертаються з нуля.\n\n"
                        f"Твої *{done} уроків* — це вже щось реальне. "
                        "Не склади це в архів.\n\n"
                        f"*${basic_price}/міс* — дешевше ніж два уроки англійської 📚"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🏆 Leaderboard",
                            callback_data="community_leaderboard")],
                        [InlineKeyboardButton(f"🚀 Залишитись — ${basic_price}/міс",
                            url=basic_link)] if basic_link else [],
                    ])
                )

            # ══════════════════════════════════════════════════
            # ЛАНКА 6 — залишилась 1 ланка до кінця тріалу
            # ══════════════════════════════════════════════════
            elif chain_len == 6 and not s.get("remind_link6_sent"):
                upd_s(int(uid), {"remind_link6_sent": True})
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"⏰ *{name}, залишилась 1 безкоштовна ланка!*\n\n"
                        f"◆◆◆◆◆◆◇ 6/7\n\n"
                        f"Що ти вже маєш:\n"
                        f"• {done} уроків записано\n"
                        f"• {mastered} граматичних тем засвоєно\n"
                        f"• AI-аналіз твоїх прогалин\n"
                        f"• Ланцюжок {chain_len} ланок\n\n"
                        "Все це збережеться. Просто підпишись і продовжуй 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"⚡️ Basic — ${basic_price}/міс",
                            url=basic_link)] if basic_link else [],
                        [InlineKeyboardButton(f"🌟 Premium — ${prem_price}/міс",
                            url=prem_link)] if prem_link else [],
                        [InlineKeyboardButton("🎙 Мій прогрес у звуці",
                            callback_data="voice_timeline")],
                    ])
                )

            # ══════════════════════════════════════════════════
            # ЛАНКА 7 — фінальний paywall
            # ══════════════════════════════════════════════════
            elif chain_len >= 7 and not s.get("remind_link7_sent"):
                upd_s(int(uid), {"remind_link7_sent": True})
                scores = s.get("scores", [])
                first_score  = s.get("first_voice_score", 0)
                recent_score = scores[-1].get("score", 0) if scores else 0
                growth_line  = ""
                if first_score and recent_score:
                    diff = recent_score - first_score
                    sign = "+" if diff >= 0 else ""
                    growth_line = f"\n🎙 Твій голос виріс: *{sign}{diff} балів*\n"

                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"🏁 *{name} — ти завершив пробний період!*\n\n"
                        f"◆◆◆◆◆◆◆ 7/7\n"
                        f"{growth_line}\n"
                        f"{done} уроків · {mastered} граматичних тем\n\n"
                        "Ти пройшов далі ніж 80% тих хто починав.\n\n"
                        "Ти вже побудував основу свого мовного ланцюжка.\n"
                        "*Розблокуй продовження* — і він не зупиниться.\n\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        f"⚡️ Basic — *${basic_price}/міс*{ref_note}\n"
                        f"🌟 Premium — *${prem_price}/міс*{ref_note}\n\n"
                        "Перший місяць — і ти побачиш різницю."
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(f"⚡️ Basic — ${basic_price}/міс", url=basic_link)]]
                        + ([[InlineKeyboardButton(f"🌟 Premium — ${prem_price}/міс", url=prem_link)]]
                           if prem_link else [])
                        + [[InlineKeyboardButton("📊 Мій прогрес", callback_data="progress_continue")]]
                    ) if basic_link else main_menu()
                )

            # ══════════════════════════════════════════════════
            # ПІСЛЯ 7 ЛАНОК — soft paywall щодня поки не платять
            # ══════════════════════════════════════════════════
            elif chain_len >= 7 and s.get("remind_link7_sent") and not is_premium(s):
                remind_key = f"paywall_remind_{today.strftime('%Y-%m-%d')}"
                if s.get(remind_key): continue
                upd_s(int(uid), {remind_key: True})

                if not s.get("post_trial_sent"):
                    upd_s(int(uid), {"post_trial_sent": True})
                    await ctx.bot.send_message(
                        chat_id=int(uid),
                        text=(
                            f"🔒 {name}, твій тріал завершився.\n\n"
                            f"Ти збудував *{chain_len} ланок* і зробив *{done} уроків*.\n\n"
                            "Це не точка. Це момент вибору.\n\n"
                            "SpeakChain чекає — твій прогрес збережений. "
                            "Продовжи з тієї ж секунди 👇"
                        ),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(f"⚡️ Basic — ${basic_price}/міс",
                                url=basic_link)] if basic_link else [],
                            [InlineKeyboardButton(f"🌟 Premium — ${prem_price}/міс",
                                url=prem_link)] if prem_link else [],
                        ])
                    )
                else:
                    await ctx.bot.send_message(
                        chat_id=int(uid),
                        text=(
                            f"🔒 {name}, ланцюжок чекає.\n\n"
                            f"*{chain_len} ланок* збережено.\n"
                            f"Basic — *${basic_price}/міс* → продовж зараз 👇"
                        ),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(f"⚡️ Продовжити — ${basic_price}/міс",
                                url=basic_link)] if basic_link else [],
                        ])
                    )

        except Exception as e:
            logger.warning(f"Trial warning failed {uid}: {e}")


async def daily_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Щовечірнє нагадування о 21:00 за часом ЮЗЕРА (не бота).
    Запускається щогодини з 18:00 UTC і перевіряє чи вже 21:00 у кожного юзера.
    30 варіантів фраз — щоб не набридало.
    """
    from timezone_utils import get_user_hour

    # 30 варіантів нагадувань
    REMINDER_TEXTS = [
        "🔗 Ти ще не додав ланку сьогодні. Один урок — і ланцюжок живе.",
        "🎙 21:00. Ідеальний час для 5-хвилинного монологу.",
        "⚡️ Твій ланцюжок чекає. Не дай йому зупинитись сьогодні.",
        "🌙 До кінця дня ще є час. Одна ланка — і можна спати спокійно.",
        "🔥 Стрік не зламається сам. Зайди на 5 хвилин.",
        "🎯 Сьогодні ще не було практики. Це легко виправити 👇",
        "💬 Один монолог сьогодні = одна ланка в ланцюжку. Починаємо?",
        "🧠 Мозок краще засвоює мову увечері. Саме час для уроку.",
        "📈 Твій прогрес не росте поки ти не відкриєш бот. Відкрий 👇",
        "🌟 Кращий момент для практики — зараз. Другий кращий — через 5 хвилин.",
        "⏰ 21:00 у тебе. Ланцюжок ще не поповнено сьогодні.",
        "🔗 Ланцюжок — це звичка. Звички не роблять вихідних.",
        "💡 5 хвилин англійської зараз — і день не пройшов даремно.",
        "🎬 Є хвилина? Відео чекає. Ланка чекає. Починаємо?",
        "🏃 Ті хто роблять урок щовечора — прогресують у 3 рази швидше.",
        "🌙 Вечір — найкращий час щоб додати ланку. Не пропускай.",
        "⚡️ Один короткий урок зараз — і завтра прокинешся з відчуттям прогресу.",
        "🎙 Твій голос чекає практики. Дай йому 5 хвилин сьогодні.",
        "🔑 Постійність важливіша за досконалість. Просто відкрий урок.",
        "💪 Не потрібно багато часу. Потрібно просто почати.",
        "📊 Юзери які практикують щовечора досягають B1 за 3 місяці.",
        "🌟 Одна ланка сьогодні — і завтра буде легше повернутись.",
        "🎯 Найважча частина — відкрити бот. Ти вже тут. Лишилось трохи.",
        "🔗 Ланцюжок росте з кожною ланкою. Додай свою сьогодні.",
        "🧩 Мова вивчається по шматочках. Сьогоднішній шматочок ще не додано.",
        "⭐️ Маленький крок щодня = великий результат через рік.",
        "🎤 Говорити англійською стає легше коли практикуєш щодня. Навіть 5 хвилин.",
        "🌙 До півночі ще є час додати ланку. Не відкладай на завтра.",
        "💬 Один урок — це все що потрібно сьогодні. Починаємо?",
        "🔥 Ланцюжок живий. Утримай його сьогодні.",
    ]

    db    = load_db()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d") if hasattr(datetime.now(), 'utc') else datetime.utcnow().strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not s.get("onboarding_done") or not s.get("level"): continue
        if is_premium(s) and s.get("last_date") == today: continue  # платний і вже зробив — не турбуємо

        # ── Вже зробив урок сьогодні — не надсилаємо ────
        if s.get("last_date") == today:
            continue

        if s.get("bot_blocked"):
            continue

        # ── Перевіряємо чи вже 21:00 у юзера ────────────
        try:
            user_hour = get_user_hour(s)
        except Exception:
            user_hour = 21  # якщо помилка — відправляємо

        if user_hour < 21:
            continue  # ще не час

        # ── Не надсилати двічі за день ───────────────────
        remind_key = f"evening_remind_{today}"
        if s.get(remind_key):
            continue
        upd_s(int(uid), {remind_key: True})

        try:
            import hashlib
            seed = int(hashlib.md5(f"{uid}{today}".encode()).hexdigest(), 16)
            text = REMINDER_TEXTS[seed % len(REMINDER_TEXTS)]

            current_lesson_id = s.get("current_lesson_id")
            video_url         = s.get("custom_video_url", "")

            if current_lesson_id and video_url:
                topic = next_cefr_topic(s) or "поточна тема"
                await _safe_send(
                    ctx.bot, int(uid),
                    f"{text}\n\n📍 Тема чекає: _{topic}_",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🎙 Записати зараз", callback_data="remind_record"),
                        InlineKeyboardButton("⏭ Пропустити",      callback_data="remind_skip"),
                    ]])
                )
            else:
                await _safe_send(
                    ctx.bot, int(uid), text,
                    parse_mode="Markdown",
                    reply_markup=main_menu()
                )

            due = _srs_due_words(s)
            if due and s.get("srs_remind_date") != today:
                upd_s(int(uid), {"srs_remind_date": today})
                words_preview = ", ".join(f"*{w['word']}*" for w in due[:3])
                await _safe_send(
                    ctx.bot, int(uid),
                    f"🧠 Також: {len(due)} слів чекають на повторення — {words_preview}...",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🧠 Повторити", callback_data="srs_start"),
                    ]])
                )

        except Exception as e:
            logger.warning(f"Evening reminder failed {uid}: {e}")

# ── Main ──────────────────────────────────────────────
async def post_init(app):
    # ── Ініціалізуємо PostgreSQL ──
    global _HTTP_BOT
    _HTTP_BOT = app.bot   # shared bot instance для HTTP handlers

    _pg_init()
    load_db()             # preload DB into memory at startup

    # ── Відновлюємо DB з Google Sheets при старті ──
    if not Path(DB).exists() or Path(DB).stat().st_size < 10:
        logger.info("DB not found locally — trying to restore from Sheets...")
        restored = gs_load_db_backup()
        if not restored:
            logger.info("No backup found — starting fresh")

    from telegram import MenuButtonCommands
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await app.bot.set_my_commands([
        BotCommand("start",    "Почати / Головне меню"),
        BotCommand("progress", "Мій шлях A1→C2"),
        BotCommand("bot_recommends", "Порадь мені відео 🎯"),
        BotCommand("myvideo",  "🎬 Мої відео — бібліотека"),
        BotCommand("community","Спільнота"),
        BotCommand("tutor_me",  "Персональний репетитор: індивідуальна програма 🎓"),
        BotCommand("partner",  "Знайти speaking partner 👥"),
        BotCommand("premium",  "SpeakChain Premium ⭐️"),
        BotCommand("cancel",   "Скасувати авторенью підписки"),
        BotCommand("chain",    "🔗 Chain Dashboard — мій прогрес"),
        BotCommand("leaders",  "🏆 Leaderboard — топ гравці"),
        BotCommand("upgrade",  "💳 Обрати план — Basic або Premium"),
        BotCommand("today",     "📅 Мій план на сьогодні"),
        BotCommand("immersion", "🎧 Пасивне занурення"),
        BotCommand("phrases",     "📚 Моя картотека слів"),
        BotCommand("timeline",  "🎙 Мій прогрес у звуці"),
        BotCommand("challenge", "🏆 7-денний Speaking Challenge"),
        BotCommand("join",      "👥 Приєднатись до спільноти"),
        BotCommand("mystatus",  "📊 Мій статус у спільноті"),
        BotCommand("help",     "Допомога"),
    ])
    # Адмін-команди — встановлюємо окремо тільки для адміна
    if ADMIN_ID and ADMIN_ID > 1:
        try:
            await app.bot.set_my_commands([
                BotCommand("admin",      "📊 Статистика"),
                BotCommand("admin_refs", "🔗 Звіт по рефералах"),
                BotCommand("setpremium", "⭐️ Активувати Premium"),
                BotCommand("gen_ref",     "🔗 Генерувати посилання для блогера"),
            ], scope={"type": "chat", "chat_id": ADMIN_ID})
        except Exception as e:
            logger.warning(f"Could not set admin commands: {e}")

def main():
    import time as _time
    # ── Затримка старту — щоб старий Railway процес встиг зупинитись ──
    _startup_delay = int(os.environ.get("STARTUP_DELAY", "5"))
    if _startup_delay > 0:
        logger.info(f"=== STARTUP DELAY {_startup_delay}s (щоб уникнути Telegram Conflict) ===")
        _time.sleep(_startup_delay)

    # ── Async helpers — визначаємо першими ──────────────
    async def _show_my_phrases(u, c):
        if u.callback_query:
            await u.callback_query.answer()
            # Надсилаємо як нове повідомлення
            await c.bot.send_message(
                chat_id=u.effective_user.id,
                text="📚 *Мої фрази*\n\nЗавантажую...",
                parse_mode="Markdown"
            )
            # Створюємо фейковий update з message для cmd_my_words
            await cmd_my_words(u, c)
        else:
            await cmd_my_words(u, c)
    async def _find_partner(u, c):    await cmd_partner(u, c)
    async def _ct_done(u, c):         await u.callback_query.answer()

    # ── Перевірка цілісності — якщо функція зникла при редагуванні ──
    _REQUIRED_FUNCTIONS = [
        # ── Команди ───────────────────────────────────────────
        "cmd_test_renewal", "cmd_test_pay", "cmd_test_recurrent", "cmd_buy",
        "cmd_premium", "cmd_partner", "cmd_admin_partners", "cmd_start",
        "cmd_lesson", "cmd_myvideo", "cb_myvideo_add", "cmd_progress", "cmd_gen_ref",
        "cmd_admin", "cmd_blogger", "cmd_test_full_flow", "cmd_create_blogger_code", "cmd_list_blogger_codes",
        "cmd_add_admin", "cmd_remove_admin", "cmd_list_admins",
        "is_admin", "is_super_admin", "add_sub_admin", "remove_sub_admin", "get_sub_admins",
        "cmd_weekly_question", "cmd_feedback_queue", "cmd_set_welcome", "cmd_preview_welcome",
        "cmd_best_of_month", "cmd_setup_live_group", "_invite_to_premium_group", "cmd_live_start", "cmd_live_quiz",
        "cmd_quiz_reset", "cmd_live_end", "cmd_get_group_id", "cmd_invite_premium_to_group",
        "cmd_admin_payouts", "cmd_admin_reply", "cmd_post_rating", "cmd_view_blogger", "cmd_my_students", "cmd_voice_comment",
        "cmd_admin_refs", "cmd_setpremium", "cmd_resetaudio", "cmd_myid",
        "cmd_join_community", "cmd_community_status", "cmd_oferta", "cmd_refuse",
        "cmd_privacy", "cmd_offer", "cmd_community_challenge", "cmd_set_challenge",
        "cmd_tutor_me", "cmd_settings", "cmd_community", "cmd_today",
        "cmd_immersion", "cmd_my_words", "cmd_voice_timeline", "cmd_challenge",
        "cmd_help", "cmd_bot_recommends",
        # ── Callback-обробники ────────────────────────────────
        "cb_show_offer", "cb_offer_accepted", "cb_premium_trial", "cb_buddy_format",
        "cb_partner_cancel", "cb_share_card", "cb_entry", "cb_placement_choice",
        "cb_placement_answer", "cb_goal", "cb_kids_age", "cb_kids_interests",
        "cb_kids_sub", "cb_level", "cb_profession", "cb_age",
        "cb_interests", "cb_progress_continue", "cb_cycle_get_video", "cb_retest",
        "cb_levelup", "cb_before_after", "cb_peek_dismiss", "cb_wq_answer",
        "cb_fb_reply", "cb_fb_skip", "cb_best_pick", "cb_live_quiz_answer",
        "cb_pay_blogger", "cb_payouts_gs_sync", "cb_view_blogger_btn", "cb_blogger_stats",
        "cb_admin", "cb_reset_profile", "cb_cefr_test_start", "cb_cefr_test_answer",
        "cb_suggest_tutor_me", "cb_community_challenge", "cb_community_checkin", "cb_req_blogger_feedback",
        "cb_share_video_community", "cb_share_video_skip", "cb_community_leaderboard", "cb_join_community_inline",
        "cb_share_socials", "cb_social_published", "cb_social_already", "cb_social_link_cancel",
        "cb_syllabus", "cb_settings", "cb_shadow_done", "cb_mining_save",
        "cb_mining_skip", "cb_mining_skip_to_record", "cb_srs_start", "cb_srs_skip",
        "cb_immersion_done", "cb_today_plan", "cb_sleep_skip", "cb_words_show",
        "cb_show_gaps", "cb_voice_timeline_inline", "cb_challenge_join", "cb_challenge_checkin",
        "cb_challenge_leaderboard", "cb_challenge_status", "cb_words_back", "cb_phrases_page", "cb_help",
        "cb_admin_panel", "cb_fork", "cb_voice_action", "cb_vocab",
        "cb_quiz", "cb_start_vocab", "cb_remind_skip", "cb_remind_record",
        "cb_share_voice_confirm", "cb_share_video_confirm", "cb_share_video_group", "cb_video_ai_eval", "cb_share_video_cancel", "cb_renew_yes",
        "cb_renew_no",
        # ── Message / HTTP обробники ──────────────────────────
        "handle_wayforpay_pay_page", "handle_register_ref", "handle_captions_proxy", "handle_session_end",
        "handle_player_action", "handle_wayforpay_webhook", "handle_document", "handle_partner_registration",
        "handle_poll_answer", "handle_blogger_wq_video", "handle_blogger_feedback_voice", "handle_blogger_welcome_media",
        "handle_blogger_code_input", "handle_blogger_voice_comment", "handle_syllabus_custom_profile", "handle_voice",
        "handle_web_app_data", "handle_message_reaction", "handle_text", "handle_video",
        "handle_video_link",
        # ── Jobs / scheduled ──────────────────────────────────
        "job_monthly_report", "job_recurrent_charge", "job_send_weekly_questions", "job_blogger_weekly_q_reminder",
        "job_backup_db", "job_srs_reminder", "job_sleep_reminder", "job_streak_rescue", "job_phrase_of_day", "job_flush_db",
        "job_before_after_reminder", "job_premium_peek", "job_community_monitor", "job_challenge_reminder",
        "job_plan_expiry", "job_weekly_report", "job_daily_report", "job_group_rating", "_calc_activity_score",
        # ── WayForPay ─────────────────────────────────────────
        "wfp_sign", "wfp_base_url", "wfp_build_params", "wfp_create_payment_url",
        "wfp_charge_by_token", "wfp_verify_webhook", "wfp_parse_order",
        # ── Google Sheets ─────────────────────────────────────
        "gs_sync_student", "gs_log_payment", "gs_sync_bloggers", "gs_sync_payouts",
        "gs_save_db_backup", "gs_load_db_backup",
        # ── SRS ───────────────────────────────────────────────
        "_srs_next_date", "_srs_update_word", "_srs_due_words",
        # ── Розсилки / post_init ──────────────────────────────
        "send_placement_question", "send_gap_recommendations", "send_vocab_card", "send_quiz_question",
        "send_day2_reminder", "send_unfinished_reminder", "send_trial_warning", "daily_reminder",
        "post_init",
        # ── Утиліти та бізнес-логіка ──────────────────────────
        "claude_cache_get", "claude_cache_set", "calculate_monthly_payouts", "load_db",
        "save_db", "get_s", "upd_s", "detect_platform",
        "is_supported_video", "youtube_search", "next_cefr_topic", "youtube_search_lesson",
        "analyse_gaps", "count_plans", "plans_line", "get_streak",
        "update_streak", "streak_message", "check_and_send_milestone", "is_premium",
        "is_basic", "is_premium_only", "is_in_trial", "trial_days_left",
        "check_premium_gate", "load_partner_queue", "save_partner_queue", "partner_score",
        "build_progress_card", "get_lessons", "next_lesson", "main_menu", "blogger_main_menu",
        "active_lesson_kb", "breadcrumb", "extract_youtube_id", "miniapp_video_url",
        "video_watch_keyboard", "get_xp_level", "get_xp_next", "get_cefr_xp_progress",
        "build_cefr_xp_display", "award_xp", "get_analyses_remaining", "voice_review_kb",
        "goal_kb", "level_choice_kb", "level_kb", "profession_kb",
        "age_kb", "kids_interests_kb", "kids_age_kb", "get_placement_question",
        "placement_opts_kb", "admin_only", "get_blogger_codes", "save_blogger_codes",
        "get_registered_bloggers", "save_registered_bloggers", "is_blogger", "get_blogger_name",
        "activate_plan", "get_improvement_delta", "build_social_captions", "syllabus_profile_kb",
        "syllabus_level_kb", "syllabus_variant_kb", "build_syllabus_message", "active_lesson_kb_v2",
        "next_video_fork_kb", "quiz_cache_key", "load_quiz_cache", "save_quiz_cache",
        "get_cached_quiz", "store_quiz_cache", "generate_quiz", "extract_vocab_from_video",
        "get_skill_progress", "start_unit_vocab", "process_text_monologue",
        # ── Приватні хелпери (_) ──────────────────────────────
        "_get_gs_client", "_ensure_sheet", "_process_payment", "_get_pg_pool",
        "_pg_conn", "_pg_release", "_db_cache_invalidate", "_pg_init",
        "_do_partner_search", "_player_url", "_send_first_video_task", "_do_gen_ref",
        "_do_create_blogger_code", "_send_cefr_test_question", "_show_cefr_test_results", "_community_challenge_today",
        "_community_trial_active", "_community_trial_days_left", "_send_offer", "_shadowing_message",
        "_ask_sentence_mining", "_save_mined_sentence", "_send_monologue_prompt", "_offer_mining_from_transcript",
        "_challenge_week_key", "_challenge_day_num", "_build_lesson_card", "_send_merged_lesson_card",
        "_auto_send_next_lesson", "_normalise_grammar", "_maybe_grant_referral_bonus",
    ]
    _missing = [fn for fn in _REQUIRED_FUNCTIONS if fn not in globals()]
    if _missing:
        print(f"❌ INTEGRITY CHECK FAILED — missing functions: {_missing}", flush=True)
        raise RuntimeError(f"Missing functions: {_missing}")
    print(f"✅ INTEGRITY CHECK OK — all {len(_REQUIRED_FUNCTIONS)} functions present", flush=True)
    # ────────────────────────────────────────────────────────────────
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("myid", cmd_myid, filters=filters.ChatType.GROUPS))
    app.add_handler(CommandHandler("myid", cmd_myid, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("resetaudio",cmd_resetaudio, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("start",     cmd_start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("lesson",   cmd_lesson, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("bot_recommends", cmd_bot_recommends, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("myvideo",  cmd_myvideo, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_myvideo_add, pattern="^myvideo_add$"))
    app.add_handler(CommandHandler("progress", cmd_progress, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("community",cmd_community, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("join",              cmd_join_community, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("tutor_me",  cmd_tutor_me, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_syllabus, pattern="^syl_"))
    app.add_handler(CommandHandler("help",     cmd_help, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_help, pattern="^help_"))
    app.add_handler(CallbackQueryHandler(cb_admin_panel, pattern="^adm_cmd_"))
    app.add_handler(CommandHandler("settings",  cmd_settings, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_settings, pattern="^settings_"))
    app.add_handler(CommandHandler("partner",        cmd_partner, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("admin_partners", cmd_admin_partners, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_partner_cancel, pattern="^partner_cancel$"))
    app.add_handler(CommandHandler("premium",   cmd_premium, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("admin",     cmd_admin, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("reply", cmd_admin_reply, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("admin_refs",cmd_admin_refs, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("setpremium",cmd_setpremium, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("gen_ref",      cmd_gen_ref, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("add_admin",    cmd_add_admin, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("remove_admin", cmd_remove_admin, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("list_admins",  cmd_list_admins, filters=filters.ChatType.PRIVATE))

    # ── Demo flow callbacks ───────────────────────────────
    async def _cb_demo_dispatch(update, ctx):
        data = update.callback_query.data
        if data in DEMO_CALLBACKS:
            return await DEMO_CALLBACKS[data](update, ctx, get_s, upd_s, claude_client)
    app.add_handler(CallbackQueryHandler(_cb_demo_dispatch, pattern="^demo_"))

    # ── Shared Chain callbacks ────────────────────────────
    async def _cb_sc_dispatch(update, ctx):
        data = update.callback_query.data
        if data in SHARED_CHAIN_CALLBACKS:
            return await SHARED_CHAIN_CALLBACKS[data](update, ctx, get_s, upd_s, claude_client)
    app.add_handler(CallbackQueryHandler(_cb_sc_dispatch, pattern="^sc_"))

    # ── Timezone selection ────────────────────────────────
    app.add_handler(CallbackQueryHandler(cb_timezone, pattern="^tz_"))

    # ── Chain invite / referral mechanics ─────────────────
    app.add_handler(CallbackQueryHandler(cb_chain_invite_screen, pattern="^chain_invite_screen$"))
    app.add_handler(CallbackQueryHandler(cb_copy_ref_link,       pattern="^copy_ref_link_"))

    async def _cb_remind_friend(update, ctx):
        q   = update.callback_query
        await q.answer()
        data = q.data  # remind_friend_12345
        try:
            friend_uid = int(data.split("_")[-1])
            friend_s   = get_s(friend_uid)
            friend_name = friend_s.get("name", "Друг")
            await ctx.bot.send_message(
                friend_uid,
                f"🔗 *Твій друг нагадує:*\n\n"
                "Не зупиняйся — ланцюжок чекає!\n"
                "Один урок зараз і він знову живий 👇",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🎬 Продовжити", callback_data="progress_continue"),
                ]])
            )
            await q.edit_message_text(f"✅ Нагадування надіслано {friend_name}!")
        except Exception as e:
            logger.warning(f"remind_friend: {e}")
    app.add_handler(CallbackQueryHandler(_cb_remind_friend, pattern="^remind_friend_"))

    async def cmd_timezone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Змінити часовий пояс в будь-який момент."""
        s = get_s(update.effective_user.id)
        from timezone_utils import guess_utc_offset
        current = s.get("utc_offset")
        current_str = f"UTC+{current}" if current is not None else "не встановлено"
        await update.message.reply_text(
            f"🕐 *Часовий пояс*\n\n"
            f"Поточний: *{current_str}*\n\n"
            "Обери новий 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("UTC−5  🇺🇸 Нью-Йорк",  callback_data="tz_-5"),
                    InlineKeyboardButton("UTC+0  🇬🇧 Лондон",     callback_data="tz_0"),
                ],
                [
                    InlineKeyboardButton("UTC+1  🇵🇱 Варшава",    callback_data="tz_1"),
                    InlineKeyboardButton("UTC+2  🇺🇦 Київ",       callback_data="tz_2"),
                ],
                [
                    InlineKeyboardButton("UTC+3  🇷🇺 Москва",     callback_data="tz_3"),
                    InlineKeyboardButton("UTC+4  🇦🇪 Дубай",      callback_data="tz_4"),
                ],
                [
                    InlineKeyboardButton("UTC+5  🇰🇿 Алмати",     callback_data="tz_5"),
                    InlineKeyboardButton("UTC+8  🇨🇳 Пекін",      callback_data="tz_8"),
                ],
                [
                    InlineKeyboardButton("UTC+9  🇯🇵 Токіо",      callback_data="tz_9"),
                    InlineKeyboardButton("🔍 Інший",               callback_data="tz_other"),
                ],
            ])
        )
    # ── Chain Dashboard ───────────────────────────────────
    async def cmd_chain(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Відкриває Chain Dashboard Mini App."""
        uid = update.effective_user.id
        s   = get_s(uid)
        url = _build_chain_dashboard_url(uid, s, db=load_db())
        if not url or not BOT_WEBHOOK_URL:
            # Fallback — показуємо chain статус в боті
            chain = get_chain(s)
            await update.message.reply_text(
                f"{chain_status_text(chain)}\n\n"
                f"XP: *{s.get('xp_total', 0)}*\n"
                f"Статус: {get_identity_label(s)}",
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
            return
        await update.message.reply_text(
            "🔗 *Chain Dashboard*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🔗 Відкрити Dashboard",
                    web_app=WebAppInfo(url=url)
                )
            ]])
        )
    app.add_handler(CommandHandler("chain", cmd_chain, filters=filters.ChatType.PRIVATE))

    # ── Social / Invite Mini App ──────────────────────────
    async def cmd_social(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Відкриває Social/Invite Mini App."""
        uid = update.effective_user.id
        s   = get_s(uid)
        if not BOT_WEBHOOK_URL:
            await update.message.reply_text(
                "🔗 Запроси друга і обидва отримаєте +20% XP на 7 днів!\n\n"
                f"Твоє посилання:\n`https://t.me/{ctx.bot.username}?start=ref_{s.get('username') or uid}`",
                parse_mode="Markdown"
            )
            return
        url = _build_social_invite_url(uid, s, db=load_db())
        await update.message.reply_text(
            "🔗 *Зміцни свій ланцюжок*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👥 Social & Invite", web_app=WebAppInfo(url=url))
            ]])
        )
    app.add_handler(CommandHandler("social", cmd_social, filters=filters.ChatType.PRIVATE))

    # ── Leaderboard Mini App ──────────────────────────────
    async def cmd_leaders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Відкриває Leaderboard Mini App."""
        uid = update.effective_user.id
        s   = get_s(uid)
        if not BOT_WEBHOOK_URL:
            # Fallback — текст
            await cb_community_leaderboard(update, ctx)
            return
        url = _build_leaderboard_url(uid, s, db=load_db())
        await update.message.reply_text(
            "🏆 *Leaderboard*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏆 Відкрити Leaderboard", web_app=WebAppInfo(url=url))
            ]])
        )
    app.add_handler(CommandHandler("leaders", cmd_leaders, filters=filters.ChatType.PRIVATE))

    # ── Paywall Mini App ──────────────────────────────────
    async def cmd_upgrade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Відкриває Paywall Mini App (/upgrade або /buy)."""
        uid = update.effective_user.id
        s   = get_s(uid)
        if is_premium(s):
            plan = s.get("plan","basic").capitalize()
            await update.message.reply_text(
                f"✅ У тебе вже активний *{plan}* план.\n\n"
                f"Активний до: *{s.get('premium_until','')}*",
                parse_mode="Markdown"
            )
            return
        if not BOT_WEBHOOK_URL:
            await cmd_premium(update, ctx)
            return
        url = _build_paywall_url(uid, s)
        await update.message.reply_text(
            "💳 *Обери свій план*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 Відкрити плани", web_app=WebAppInfo(url=url))
            ]])
        )
    app.add_handler(CommandHandler("upgrade", cmd_upgrade, filters=filters.ChatType.PRIVATE))

    # paywall_buy — обробка вибору плану з Mini App
    async def _cb_paywall_buy(update, ctx):
        """Юзер натиснув кнопку оплати в Paywall Mini App."""
        try:
            data = json.loads(update.effective_message.web_app_data.data)
        except Exception:
            return
        uid  = update.effective_user.id
        action = data.get("action", "")
        plan   = data.get("plan", "basic")
        src    = data.get("source", "landing")

        if action == "paywall_buy":
            await track_event(uid, f"paywall_buy_{plan}", get_s(uid), upd_s)
            logger.info(f"paywall_buy uid={uid} plan={plan} source={src}")

        elif action == "paywall_buy_6m":
            await track_event(uid, f"paywall_buy_6m_{plan}", get_s(uid), upd_s)
            logger.info(f"paywall_buy_6m uid={uid} plan={plan} source={src}")

        elif action == "paywall_remind_later":
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            upd_s(uid, {
                "paywall_remind_later": True,
                "paywall_remind_date":  tomorrow,
            })
            await ctx.bot.send_message(uid, "👌 Нагадаю завтра!")

    from telegram.ext import MessageHandler
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, _cb_paywall_buy))

    app.add_handler(CommandHandler("timezone", cmd_timezone, filters=filters.ChatType.PRIVATE))

    # ── Chain revive ──────────────────────────────────────
    async def _cb_chain_revive(update, ctx):
        uid = update.callback_query.from_user.id
        s   = get_s(uid)
        success, msg = await revive_chain(ctx.bot, uid, s, upd_s)
        await update.callback_query.answer(msg[:200], show_alert=not success)
    app.add_handler(CallbackQueryHandler(_cb_chain_revive, pattern="^chain_revive$"))

    # ── Analytics command ─────────────────────────────────
    from analytics import cmd_analytics as _cmd_analytics_fn
    async def _cmd_analytics(u, c):
        await _cmd_analytics_fn(u, c, load_db, is_admin)
    app.add_handler(CommandHandler("analytics", _cmd_analytics, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("offer",   cmd_offer, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("oferta",  cmd_oferta, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("refuse",  cmd_refuse, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("quiz_reset",       cmd_quiz_reset, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_live_quiz_answer, pattern="^lq_"))
    app.add_handler(CommandHandler("feedback_queue",  cmd_feedback_queue, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_req_blogger_feedback, pattern="^req_blogger_fb_"))
    app.add_handler(CallbackQueryHandler(cb_fb_reply,             pattern="^fb_reply_"))
    app.add_handler(CallbackQueryHandler(cb_fb_skip,              pattern="^fb_skip_"))
    app.add_handler(CommandHandler("setup_live_group", cmd_setup_live_group, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("live_start",       cmd_live_start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("quiz",             cmd_live_quiz, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("live_end",         cmd_live_end, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("get_id",           cmd_get_group_id, filters=filters.ChatType.PRIVATE))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    app.add_handler(CommandHandler("admin_payouts",    cmd_admin_payouts, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_pay_blogger,          pattern="^pay_blogger_"))
    app.add_handler(CallbackQueryHandler(cb_payouts_gs_sync,      pattern="^payouts_gs_sync_"))
    app.add_handler(CallbackQueryHandler(cb_share_video_community,pattern="^share_video_community$"))
    app.add_handler(CallbackQueryHandler(cb_share_video_skip,     pattern="^share_video_skip$"))
    app.add_handler(CallbackQueryHandler(cb_community_leaderboard,pattern="^community_leaderboard"))
    app.add_handler(CallbackQueryHandler(cb_social_published,   pattern="^social_published$"))
    app.add_handler(CallbackQueryHandler(cb_social_already,     pattern="^social_already$"))
    app.add_handler(CallbackQueryHandler(cb_social_link_cancel, pattern="^social_link_cancel$"))
    app.add_handler(CommandHandler("privacy",     cmd_privacy, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_show_offer,    pattern="^show_offer$"))
    app.add_handler(CallbackQueryHandler(cb_offer_accepted, pattern="^offer_accepted$"))
    app.add_handler(CommandHandler("challenge",     cmd_community_challenge, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("set_challenge", cmd_set_challenge, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("blogger",             cmd_blogger, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("my_students",         cmd_my_students, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("voice_comment",       cmd_voice_comment, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("create_blogger_code", cmd_create_blogger_code, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("list_blogger_codes",  cmd_list_blogger_codes, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("list_bloggers",       cmd_view_blogger, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("view_blogger",        cmd_view_blogger, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_view_blogger_btn, pattern="^view_blogger_"))
    app.add_handler(CallbackQueryHandler(cb_before_after,  pattern="^before_after$"))
    app.add_handler(CallbackQueryHandler(cb_blogger_stats, pattern="^blogger_"))
    app.add_handler(CallbackQueryHandler(cb_admin, pattern="^adm_"))

    app.add_handler(CallbackQueryHandler(cb_placement_choice, pattern="^plc_(manual|test|resume|restart)$"))
    app.add_handler(CallbackQueryHandler(cb_placement_answer, pattern="^plc_ans_"))
    app.add_handler(CallbackQueryHandler(_ct_done, pattern="^plc_done$"))
    app.add_handler(CallbackQueryHandler(cb_cycle_get_video, pattern="^cycle_get_video$"))
    app.add_handler(CallbackQueryHandler(cb_retest,          pattern="^plc_retest$"))
    app.add_handler(CallbackQueryHandler(cb_cefr_test_start, pattern="^cefr_test_start$"))
    app.add_handler(CallbackQueryHandler(cb_cefr_test_answer,pattern=r"^ct_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_levelup,  pattern="^levelup_"))
    app.add_handler(CallbackQueryHandler(cb_entry,            pattern="^entry_"))
    app.add_handler(CallbackQueryHandler(cb_fork,             pattern="^fork_"))
    app.add_handler(CallbackQueryHandler(cb_fork,             pattern="^rescue_choose$"))
    app.add_handler(CallbackQueryHandler(cb_fork,             pattern="^rescue_srs$"))
    app.add_handler(CallbackQueryHandler(cb_fork,             pattern="^remind_record$"))
    app.add_handler(CallbackQueryHandler(cb_fork,             pattern="^rescue_done$"))
    app.add_handler(CallbackQueryHandler(cb_fork,             pattern="^phrase_skip$"))
    app.add_handler(CallbackQueryHandler(cb_fork,             pattern="^duel_cancel$"))
    app.add_handler(CallbackQueryHandler(cb_fork,             pattern="^duel_video_mode$"))
    app.add_handler(CallbackQueryHandler(cb_blogger_challenge_leaderboard, pattern="^blogger_challenge_leaderboard$"))
    # ── Граматика ─────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(cb_grammar_lesson_start, pattern="^grammar_lesson_start$"))
    app.add_handler(CallbackQueryHandler(cb_gram_repeat_skip, pattern="^gram_repeat_skip$"))
    app.add_handler(CallbackQueryHandler(cb_gram_repeat,      pattern=r"^gram_repeat_(?!skip).+$"))
    app.add_handler(CallbackQueryHandler(cb_grammar_nudge_snooze, pattern="^grammar_nudge_snooze$"))
    app.add_handler(CallbackQueryHandler(cb_grammar_exercise,     pattern="^gram_ex_[ABCD]$"))
    app.add_handler(CommandHandler("grammar",   cmd_grammar_progress))
    app.add_handler(CommandHandler("topic",     cmd_grammar_topic))
    app.add_handler(CommandHandler("tutor_me",  cmd_tutor_me))
    app.add_handler(CallbackQueryHandler(cb_myvideo_library,  pattern="^myvideo_library$"))
    app.add_handler(CallbackQueryHandler(cb_show_6m_plans,     pattern="^show_6m_plans$"))
    app.add_handler(CallbackQueryHandler(cb_show_monthly_plans, pattern="^show_monthly_plans$"))
    app.add_handler(CallbackQueryHandler(cb_tutor_topic,      pattern=r"^tutor_topic_.+$"))
    app.add_handler(CallbackQueryHandler(cb_tutor_all_topics, pattern="^tutor_all_topics$"))
    # ── Дуелі ──────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(cb_duel_challenge,  pattern="^duel_challenge$"))
    app.add_handler(CallbackQueryHandler(cb_duel_send,       pattern="^duel_send_"))
    app.add_handler(CallbackQueryHandler(cb_duel_accept,     pattern="^duel_accept_"))
    app.add_handler(CallbackQueryHandler(cb_duel_decline,    pattern="^duel_decline_"))
    app.add_handler(CallbackQueryHandler(cb_duel_revenge,    pattern="^duel_revenge_"))
    app.add_handler(CallbackQueryHandler(cb_blogger_new_challenge,         pattern="^blogger_new_challenge$"))
    app.add_handler(CallbackQueryHandler(cb_blogger_challenge_remind,      pattern="^blogger_challenge_remind$"))
    app.add_handler(CallbackQueryHandler(cb_progress_continue,pattern="^progress_continue$"))
    app.add_handler(CallbackQueryHandler(cb_goal,             pattern="^g_"))
    app.add_handler(CallbackQueryHandler(cb_kids_age,       pattern="^kids_age_"))
    app.add_handler(CallbackQueryHandler(cb_kids_sub,        pattern="^kids_sub_"))
    app.add_handler(CallbackQueryHandler(cb_kids_interests,  pattern="^kint_"))
    app.add_handler(CallbackQueryHandler(cb_level,           pattern="^lv_"))
    app.add_handler(CallbackQueryHandler(cb_profession,  pattern="^prof_"))
    app.add_handler(CallbackQueryHandler(cb_age,         pattern="^age_"))
    app.add_handler(CallbackQueryHandler(cb_interests,   pattern="^int_"))
    app.add_handler(CallbackQueryHandler(cb_voice_action, pattern="^voice_"))
    app.add_handler(CallbackQueryHandler(cb_quiz,        pattern="^(quiz_|qa_)"))
    app.add_handler(CallbackQueryHandler(cb_suggest_tutor_me, pattern="^suggest_tutor_me$"))
    app.add_handler(CallbackQueryHandler(cb_reset_profile, pattern="^reset_profile$"))
    app.add_handler(CallbackQueryHandler(cb_remind_record,  pattern="^remind_record$"))
    app.add_handler(CallbackQueryHandler(cb_start_vocab,    pattern="^start_vocab$"))
    app.add_handler(CallbackQueryHandler(cb_vocab,          pattern="^vocab_(know|learn)_"))
    app.add_handler(CallbackQueryHandler(cb_remind_skip,    pattern="^remind_skip$"))
    app.add_handler(CallbackQueryHandler(cb_premium_trial,  pattern="^premium_trial$"))
    app.add_handler(CallbackQueryHandler(cb_share_card,          pattern="^share_card$"))
    app.add_handler(CallbackQueryHandler(cb_share_socials,       pattern="^share_socials$"))
    app.add_handler(CallbackQueryHandler(cb_share_voice_confirm, pattern="^share_voice_confirm$"))
    app.add_handler(CallbackQueryHandler(cb_share_voice_confirm, pattern="^share_voice_publish$"))
    app.add_handler(CallbackQueryHandler(cb_share_video_cancel,  pattern="^share_voice_cancel$"))
    async def _wq_open_current(u, c):
        user2 = u.effective_user
        s2    = get_s(user2.id)
        wq_received = s2.get("weekly_questions_received", [])
        wq = next((w for w in reversed(wq_received)
                   if w.get("week") == datetime.now().strftime("%Y-%W")), None)
        q2 = u.callback_query
        await q2.answer()
        if not wq:
            await q2.answer("Питань цього тижня ще не було", show_alert=True)
            return
        bname = wq.get("blogger","")
        try:
            if wq.get("file_id"):
                if wq.get("file_type") == "video_note":
                    await c.bot.send_video_note(chat_id=user2.id, video_note=wq["file_id"])
                else:
                    await c.bot.send_video(chat_id=user2.id, video=wq["file_id"],
                        caption=f"🎯 Speaking Challenge від @{bname}")
            await c.bot.send_message(
                chat_id=user2.id,
                text="🎙 Запиши голосову відповідь — 30-60 секунд англійською!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🎙 Записати відповідь",
                                         callback_data=f"wq_answer_{bname}")
                ]])
            )
        except Exception as e:
            logger.warning(f"wq_open_current {user2.id}: {e}")

    app.add_handler(CallbackQueryHandler(_wq_open_current, pattern="^wq_open_current$"))
    app.add_handler(CommandHandler("best_of_month",  cmd_best_of_month, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_best_pick, pattern="^best_pick_"))

    async def _best_of_month_cb(u, c): await cmd_best_of_month(u, c)
    app.add_handler(CallbackQueryHandler(_best_of_month_cb, pattern="^best_of_month_prompt$"))
    app.add_handler(CommandHandler("set_welcome",      cmd_set_welcome, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("preview_welcome",  cmd_preview_welcome, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("weekly_question",  cmd_weekly_question, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_wq_answer, pattern="^wq_answer_"))
    app.add_handler(CallbackQueryHandler(cb_peek_dismiss, pattern="^peek_dismiss$"))
    app.add_handler(CallbackQueryHandler(cb_buddy_format, pattern="^buddy_format_"))
    app.add_handler(CallbackQueryHandler(cb_renew_yes,   pattern="^renew_yes_"))
    app.add_handler(CallbackQueryHandler(cb_renew_no,    pattern="^renew_no_"))
    app.add_handler(CallbackQueryHandler(cb_cancel_abort, pattern="^cancel_abort$"))
    app.add_handler(CommandHandler("cancel", cmd_cancel_subscription, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("broadcast",         cmd_broadcast,          filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("blogger_broadcast", cmd_blogger_broadcast,  filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_broadcast_confirm,  pattern="^broadcast_confirm$"))
    app.add_handler(CallbackQueryHandler(cb_broadcast_cancel,   pattern="^broadcast_cancel$"))
    app.add_handler(CallbackQueryHandler(cb_blogger_bc_confirm, pattern="^blogger_bc_confirm$"))
    app.add_handler(CallbackQueryHandler(cb_blogger_bc_cancel,  pattern="^blogger_bc_cancel$"))
    app.add_handler(CallbackQueryHandler(cb_renew_no,  pattern="^renew_no_"))
    app.add_handler(CallbackQueryHandler(_show_my_phrases, pattern="^show_my_phrases$"))
    app.add_handler(CallbackQueryHandler(_ct_done,         pattern="^ct_done$"))
    app.add_handler(CallbackQueryHandler(_ct_done,         pattern="^plc_done$"))
    app.add_handler(CallbackQueryHandler(_find_partner,    pattern="^find_partner$"))

    # ═══════════════════════════════════════════════════
    # GLOBAL ERROR HANDLER — ловить всі помилки у хендлерах
    # ═══════════════════════════════════════════════════
    async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
        import traceback
        err     = ctx.error
        tb_str  = "".join(traceback.format_exception(type(err), err, err.__traceback__))

        # 1. Завжди пишемо в Railway Logs
        logger.error(f"\n{'='*60}\n❌ UNHANDLED ERROR\n{tb_str}{'='*60}")

        # 2. Повідомляємо адміна в Telegram
        if ADMIN_ID:
            # Скорочуємо якщо дуже довго
            short_tb = tb_str[-1500:] if len(tb_str) > 1500 else tb_str
            update_info = ""
            if update and hasattr(update, "effective_user") and update.effective_user:
                u = update.effective_user
                update_info = f"👤 {u.first_name} (id={u.id})\n"
            if update and hasattr(update, "callback_query") and update.callback_query:
                update_info += f"🔘 callback: {update.callback_query.data!r}\n"
            elif update and hasattr(update, "message") and update.message and update.message.text:
                update_info += f"💬 text: {update.message.text[:80]!r}\n"

            try:
                await ctx.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"🚨 *Помилка в боті*\n\n"
                        f"{update_info}\n"
                        f"`{short_tb}`"
                    ),
                    parse_mode="Markdown"
                )
            except Exception:
                pass  # якщо не вдалось надіслати адміну — не критично

        # 3. Надсилаємо юзеру ввічливе повідомлення
        if update:
            try:
                if hasattr(update, "callback_query") and update.callback_query:
                    await update.callback_query.answer(
                        "⚠️ Щось пішло не так. Спробуй ще раз.", show_alert=False
                    )
                elif hasattr(update, "message") and update.message:
                    await update.message.reply_text(
                        "⚠️ Сталася помилка. Спробуй ще раз або напиши /start"
                    )
            except Exception:
                pass

    app.add_error_handler(error_handler)

    # ── Catch-all для debug (видалити після тестування) ──
    async def _debug_cb(u, c):
        q = u.callback_query
        logger.warning(f"⚠️ Unmatched callback: {q.data!r}")
        await q.answer()

    app.add_handler(CallbackQueryHandler(_debug_cb))

    # ── Групові повідомлення — ігноруємо все крім команд що обробляють самі себе ──
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.VOICE | filters.AUDIO), handle_voice))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.VIDEO | filters.VIDEO_NOTE), handle_video))
    app.add_handler(CallbackQueryHandler(cb_share_video_confirm, pattern="^share_video_confirm$"))
    app.add_handler(CallbackQueryHandler(cb_share_video_group,   pattern="^share_video_group$"))
    app.add_handler(CallbackQueryHandler(cb_video_ai_eval,       pattern="^video_ai_eval$"))
    app.add_handler(CallbackQueryHandler(cb_share_video_cancel,  pattern="^share_video_cancel$"))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    # TODO: app.add_handler(MessageReactionHandler(handle_message_reaction))  # потребує PTB v21.3+
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text))

    app.add_handler(CommandHandler("buy",      cmd_buy, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("test_wrapped",       cmd_test_wrapped,        filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("test_phrase",        cmd_test_phrase_of_day,  filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("test_streak_rescue", cmd_test_streak_rescue,  filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("my_challenge",        cmd_blogger_set_challenge, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("test_expiry",         cmd_test_expiry,        filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("test_renewal",   cmd_test_renewal,  filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("test_pay",       cmd_test_pay,      filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("test_recurrent", cmd_test_recurrent,filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("test_full_flow", cmd_test_full_flow, filters=filters.ChatType.PRIVATE))

    # ── Polyglot Patch — нові handlers ──────────────────────
    app.add_handler(CommandHandler("today",     cmd_today, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("immersion", cmd_immersion, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("phrases",   cmd_my_words, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("timeline",  cmd_voice_timeline, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("mystatus",  cmd_community_status, filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(cb_community_challenge,   pattern="^community_challenge$"))
    app.add_handler(CallbackQueryHandler(cb_community_checkin,     pattern="^community_checkin$"))
    app.add_handler(CallbackQueryHandler(cb_community_leaderboard, pattern="^community_leaderboard$"))
    app.add_handler(CallbackQueryHandler(cb_join_community_inline, pattern="^join_community_"))
    app.add_handler(CallbackQueryHandler(cb_srs_start,             pattern="^srs_start$"))
    app.add_handler(CallbackQueryHandler(cb_srs_skip,              pattern="^srs_skip$"))
    app.add_handler(CallbackQueryHandler(cb_shadow_done,           pattern="^shadow_done$"))
    app.add_handler(CallbackQueryHandler(cb_mining_skip,           pattern="^mining_skip$"))
    app.add_handler(CallbackQueryHandler(cb_mining_skip_to_record, pattern="^mining_skip_to_record$"))
    app.add_handler(CallbackQueryHandler(cb_mining_save,           pattern="^mining_save$"))
    app.add_handler(CallbackQueryHandler(cb_immersion_done,        pattern="^immersion_done$"))
    app.add_handler(CallbackQueryHandler(cb_today_plan,            pattern="^today_plan$"))
    app.add_handler(CallbackQueryHandler(cb_sleep_skip,            pattern="^sleep_skip$"))
    app.add_handler(CallbackQueryHandler(cb_words_show,            pattern="^words_show_"))
    app.add_handler(CallbackQueryHandler(cb_phrases_page,          pattern="^phrases_page_"))
    app.add_handler(CallbackQueryHandler(cb_words_back,            pattern="^words_back$"))
    app.add_handler(CallbackQueryHandler(cb_show_gaps,             pattern="^show_gaps$"))
    app.add_handler(CallbackQueryHandler(cb_voice_timeline_inline, pattern="^voice_timeline$"))
    app.add_handler(CallbackQueryHandler(cb_challenge_join,        pattern="^challenge_join$"))
    app.add_handler(CallbackQueryHandler(cb_challenge_checkin,     pattern="^challenge_checkin$"))
    app.add_handler(CallbackQueryHandler(cb_challenge_leaderboard, pattern="^challenge_leaderboard$"))
    app.add_handler(CallbackQueryHandler(cb_challenge_status,      pattern="^challenge_status$"))

    # ── Daily jobs — рознесені по часу щоб не перевантажувати Telegram API ──
    # daily_reminder щогодини 18-23 UTC — перевіряє чи вже 21:00 у юзера
    for _h in range(18, 24):
        app.job_queue.run_daily(daily_reminder, time=time(hour=_h, minute=5))

    # ── Referral social mechanics ─────────────────────────
    async def _job_referral_social(ctx):
        """
        Щодня о 12:00:
        - Нотифікація якщо друг обігнав на 1 ланку
        - Return loop: інвайтер дізнається що друг розірвав chain

        Батчинг по 1000 юзерів — всі отримують, навіть якщо довго.
        O(n) — одна ітерація по БД, без вкладених циклів.
        """
        db = load_db()

        # Збираємо всі задачі заздалегідь (O(n) scan)
        overtook_tasks  = []
        return_tasks    = []

        for uid, s in db.items():
            if not isinstance(s, dict): continue
            if not s.get("onboarding_done"): continue

            uid_int = int(uid)

            # Перевіряємо чи друг обігнав (читаємо з вже завантаженого db)
            referrer_uid = s.get("referrer_uid")
            if referrer_uid:
                my_chain  = (s.get("chain") or {}).get("length", 0) or 0
                ref_s     = db.get(str(referrer_uid), {})
                if isinstance(ref_s, dict):
                    ref_chain = (ref_s.get("chain") or {}).get("length", 0) or 0
                    ref_name  = ref_s.get("name", "Твій друг")

                    # Друг обігнав на 1 ланку — notify (один раз)
                    overtook_key = f"overtook_notified_{ref_chain}"
                    if ref_chain == my_chain + 1 and not s.get(overtook_key):
                        upd_s(uid_int, {overtook_key: True})
                        _uid, _key, _ref_name, _ref_chain, _my_chain = uid_int, overtook_key, ref_name, ref_chain, my_chain
                        async def _send_overtook(u=_uid, rn=_ref_name, rc=_ref_chain, mc=_my_chain):
                            return await _safe_send(
                                ctx.bot, u,
                                f"⚡️ *{rn} обігнав тебе на 1 ланку!*\n\n"
                                f"Він: *{rc} ланок* · Ти: *{mc} ланок*\n\n"
                                "Зроби урок зараз — і вирівняй рахунок 👇",
                                parse_mode="Markdown",
                                reply_markup=InlineKeyboardMarkup([[
                                    InlineKeyboardButton("🎬 Зробити ланку", callback_data="progress_continue"),
                                ]])
                            )
                        overtook_tasks.append(_send_overtook)

            # Return loop — якщо chain розірваний, нотифікуємо інвайтера
            chain = s.get("chain", {})
            if chain.get("status") == "broken":
                broke_at   = chain.get("broke_at", "")
                broken_key = f"return_loop_notified_{broke_at}"
                if broke_at and not s.get(broken_key) and referrer_uid:
                    upd_s(uid_int, {broken_key: True})
                    stud_name = s.get("name", "Твій друг")
                    _ref_uid, _stud, _uid = int(referrer_uid), stud_name, uid_int
                    async def _send_return(ru=_ref_uid, sn=_stud, su=_uid):
                        return await _safe_send(
                            ctx.bot, ru,
                            f"🔗 *{sn} розірвав ланцюжок.*\n\n"
                            "Надішли йому нагадування — разом легше не зупинятись.",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("📤 Нагадати другу", callback_data=f"remind_friend_{su}"),
                            ]])
                        )
                    return_tasks.append(_send_return)

        all_tasks = overtook_tasks + return_tasks
        if all_tasks:
            logger.info(f"_job_referral_social: {len(overtook_tasks)} overtook + {len(return_tasks)} return = {len(all_tasks)} tasks")
            await _send_in_batches(ctx.bot, all_tasks)

    # ── Розклад jobs рівномірно по дню ────────────────────
    # Принцип: не більше 2 важких jobs в одну годину
    # Важкий job = скан всіх юзерів + масова розсилка
    #
    # Час UTC:
    #  03:00 — grammar_decay (нічний, без розсилки)
    #  08:30 — phrase_of_day
    #  09:00 — monthly_report
    #  09:10 — send_weekly_questions
    #  09:40 — blogger_weekly_q_reminder
    #  10:00 — send_trial_warning   ← важкий
    #  10:30 — plan_expiry          ← важкий
    #  11:00 — recurrent_charge
    #  11:30 — srs_reminder
    #  12:00 — referral_social
    #  13:00 — grammar_spaced_rep
    #  14:00 — premium_peek
    #  15:00 — group_rating
    #  16:00 — before_after_reminder
    #  19:00 — challenge_reminder
    #  20:00 — community_monitor
    #  20:30 — streak_rescue
    #  21:00 — weekly_report
    #  21:15 — daily_report
    #  22:00 — sleep_reminder
    app.job_queue.run_daily(job_grammar_decay,              time=time(hour=3,  minute=0))
    app.job_queue.run_daily(job_phrase_of_day,              time=time(hour=8,  minute=30))
    app.job_queue.run_daily(job_monthly_report,             time=time(hour=9,  minute=0))
    app.job_queue.run_daily(job_send_weekly_questions,      time=time(hour=9,  minute=10))
    app.job_queue.run_daily(job_blogger_weekly_q_reminder,  time=time(hour=9,  minute=40))
    app.job_queue.run_daily(send_trial_warning,             time=time(hour=10, minute=0))
    app.job_queue.run_daily(job_plan_expiry,                time=time(hour=10, minute=30))
    app.job_queue.run_daily(job_recurrent_charge,           time=time(hour=11, minute=0))
    app.job_queue.run_daily(job_srs_reminder,               time=time(hour=11, minute=30))
    app.job_queue.run_daily(_job_referral_social,           time=time(hour=12, minute=0))
    app.job_queue.run_daily(job_grammar_spaced_rep,         time=time(hour=13, minute=0))
    app.job_queue.run_daily(job_premium_peek,               time=time(hour=14, minute=0))
    app.job_queue.run_daily(job_group_rating,               time=time(hour=15, minute=0))
    app.job_queue.run_daily(job_before_after_reminder,      time=time(hour=16, minute=0))
    app.job_queue.run_daily(job_challenge_reminder,         time=time(hour=19, minute=0))
    app.job_queue.run_daily(job_community_monitor,          time=time(hour=20, minute=0))
    app.job_queue.run_daily(job_streak_rescue,              time=time(hour=20, minute=30))
    app.job_queue.run_daily(job_weekly_report,              time=time(hour=21, minute=0))
    app.job_queue.run_daily(job_daily_report,               time=time(hour=21, minute=15))
    app.job_queue.run_daily(job_sleep_reminder,             time=time(hour=22, minute=0))

    # ── Repeating jobs ────────────────────────────────────
    app.job_queue.run_repeating(job_backup_db,   interval=1800,  first=60)
    app.job_queue.run_repeating(job_flush_db,    interval=30,    first=10)

    # ── Job health monitor — alert адміну при збоях ──────
    async def _job_health_monitor(ctx):
        alerts = _DB_MEM.get("job_errors") or {}
        if not alerts:
            return
        db = load_db()
        admins = get_admins_list(db)
        text = "⚠️ *Job errors за 6 годин:*\n\n"
        for job_name, cnt in list(alerts.items())[:10]:
            text += f"• `{job_name}`: {cnt} помилок\n"
        for admin_uid in list(admins)[:3]:
            try:
                await ctx.bot.send_message(int(admin_uid), text, parse_mode="Markdown")
            except Exception:
                pass
        _DB_MEM["job_errors"] = {}
    app.job_queue.run_repeating(_job_health_monitor, interval=21600, first=3600)

    logger.info("✅ SpeakChain running!")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,       # ігноруємо накопичені оновлення при рестарті
        close_loop=False,
    )

# ════════════════════════════════════════════════════════════
# WEEKLY PROGRESS REPORT — щонеділі автоматичний підсумок
# ════════════════════════════════════════════════════════════

async def cb_renew_yes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент дав згоду на продовження — надсилаємо платіжне посилання."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    # Парсимо: renew_yes_{uid}_{plan}
    parts = q.data.split("_")
    plan  = parts[-1]  # basic або premium
    s     = get_s(user.id)
    has_ref = bool(s.get("affiliate_ref"))

    basic_price = BASIC_AFFILIATE_PRICE  if has_ref else BASIC_PRICE
    prem_price  = PREMIUM_PRICE_AFF      if has_ref else PREMIUM_PRICE_FULL
    basic_link  = BASIC_AFFILIATE_LINK   if has_ref else BASIC_PAYMENT_LINK
    prem_link   = PREMIUM_AFFILIATE_LINK if has_ref else PREMIUM_PAYMENT_LINK

    price = prem_price  if plan == "premium" else basic_price
    link  = prem_link   if plan == "premium" else basic_link
    name  = "Premium 🌟" if plan == "premium" else "Basic ⚡️"

    # Фіксуємо згоду
    upd_s(user.id, {
        "renewal_consent":      True,
        "renewal_consent_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "renewal_consent_plan": plan,
    })

    if link:
        await q.edit_message_text(
            f"✅ *Дякуємо за підтвердження!*\n\n"
            f"Ти підтвердив/ла згоду на продовження плану *{name}* за *${price}/міс*.\n\n"
            "Перейди за посиланням для оплати 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"💳 Оплатити ${price}", url=link)
            ]])
        )
    else:
        await q.edit_message_text(
            "✅ Дякуємо! Напиши /buy щоб оновити підписку.",
            parse_mode="Markdown"
        )


async def cb_renew_no(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Студент відмовився від продовження — скасовує авторенью."""
    q    = update.callback_query
    user = q.from_user
    await q.answer()

    s     = get_s(user.id)
    until = s.get("premium_until", "")
    upd_s(user.id, {"autorenew_cancelled": True})

    await q.edit_message_text(
        f"✅ Авторенью скасовано.\n\n"
        f"Твій доступ активний до *{until}*.\n\n"
        "Картка не буде списана автоматично.\n"
        "Якщо захочеш продовжити — /buy у будь-який момент.",
        parse_mode="Markdown"
    )


async def cmd_cancel_subscription(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /cancel — скасувати авторенью підписки.
    Доступ залишається до кінця оплаченого періоду.
    """
    uid = update.effective_user.id
    s   = get_s(uid)

    if not is_premium(s):
        await update.message.reply_text(
            "У тебе зараз немає активної підписки.\n"
            "Переглянь плани: /buy",
        )
        return

    until    = s.get("premium_until", "")
    plan     = s.get("plan", "basic")
    rec_token = s.get("rec_token", "")

    if s.get("autorenew_cancelled"):
        await update.message.reply_text(
            f"ℹ️ Авторенью вже скасовано.\n\n"
            f"Доступ активний до *{until}*.",
            parse_mode="Markdown"
        )
        return

    if not rec_token:
        await update.message.reply_text(
            f"ℹ️ У тебе немає авторенью — підписка не продовжується автоматично.\n\n"
            f"Доступ активний до *{until}*.",
            parse_mode="Markdown"
        )
        return

    plan_name = "Basic ⚡️" if plan == "basic" else "Premium 🌟"
    await update.message.reply_text(
        f"⚠️ *Скасувати авторенью?*\n\n"
        f"План: *{plan_name}*\n"
        f"Активний до: *{until}*\n\n"
        "Після скасування картка більше не буде списуватись.\n"
        "Доступ залишиться до кінця оплаченого терміну.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Так, скасувати", callback_data=f"renew_no_{uid}")],
            [InlineKeyboardButton("↩️ Залишити підписку", callback_data="cancel_abort")],
        ])
    )


async def cb_cancel_abort(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("✅ Добре, підписка залишається активною.")


async def job_plan_expiry(ctx: ContextTypes.DEFAULT_TYPE):
    """
    Щоденно о 10:30:
    - За 3 дні до кінця → попередження + пропозиція продовжити
    - В день закінчення → повідомлення + offer
    """
    from datetime import timedelta
    db    = load_db()
    today = datetime.now().date()

    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not isinstance(s, dict): continue
        if not s.get("onboarding_done"): continue

        until_str = s.get("premium_until", "")
        if not until_str: continue

        try:
            until_date = datetime.strptime(until_str, "%Y-%m-%d").date()
        except Exception:
            continue

        plan      = s.get("plan", "basic")
        plan_name = "Basic ⚡️" if plan == "basic" else "Premium 🌟"
        name      = s.get("name", "Студенте")
        p            = get_prices(s)
        basic_price  = p["basic_price"]
        prem_price   = p["prem_price"]
        basic_link   = p["basic_link"]
        prem_link    = p["prem_link"]

        days_left = (until_date - today).days

        try:
            # ── За 3 дні — питаємо згоду на продовження ────────
            if days_left == 3 and not s.get(f"expiry_warn3_{until_str}"):
                upd_s(int(uid), {f"expiry_warn3_{until_str}": True})
                rec_token = s.get("rec_token", "")
                price_str = f"${prem_price}" if plan == "premium" else f"${basic_price}"

                if rec_token:
                    # Є токен — але рекурентні поки вимкнені, даємо посилання
                    pay_url  = wfp_create_payment_url(int(uid), plan, float(prem_price if plan == "premium" else basic_price))
                    wfp_link = prem_link if plan == "premium" else basic_link
                    streak   = s.get("streak", 0)
                    kb = [[InlineKeyboardButton(f"💳 Продовжити {price_str}", url=pay_url)]]
                    if wfp_link:
                        kb.append([InlineKeyboardButton("🔗 Альтернативне посилання", url=wfp_link)])
                    await ctx.bot.send_message(
                        chat_id=int(uid),
                        text=(
                            f"⏳ *{name}*, твій план *{plan_name}* закінчується через *3 дні* — {until_str}.\n\n"
                            f"🔥 Стрік: *{streak} дн.* — не переривай!\n\n"
                            f"Продовжи підписку зараз — лише *{price_str}/міс* 👇"
                        ),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(kb)
                    )
                else:
                    # Немає токена — прямі посилання на оплату
                    lessons   = len(s.get("done_lessons", []))
                    streak    = s.get("streak", 0)
                    pay_url   = wfp_create_payment_url(int(uid), plan, float(prem_price if plan == "premium" else basic_price))
                    wfp_link  = prem_link if plan == "premium" else basic_link
                    kb = [[
                        InlineKeyboardButton(f"💳 Оплатити {price_str}", url=pay_url),
                    ]]
                    if wfp_link:
                        kb.append([InlineKeyboardButton("🔗 Альтернативне посилання", url=wfp_link)])
                    await ctx.bot.send_message(
                        chat_id=int(uid),
                        text=(
                            f"⏳ *{name}*, твій план *{plan_name}* закінчується через *3 дні* — {until_str}.\n\n"
                            f"🔥 Стрік: *{streak} дн.* | Уроків: *{lessons}*\n\n"
                            f"Продовжи зараз і не переривай прогрес — лише *{price_str}/міс*\n\n"
                            f"_Оплата займе 30 секунд — картка вже збережена не потрібна_ 👇"
                        ),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(kb)
                    )

            # ── В день закінчення ────────────────────────────────
            elif days_left == 0 and not s.get(f"expiry_day0_{until_str}"):
                upd_s(int(uid), {f"expiry_day0_{until_str}": True})
                rec_token = s.get("rec_token", "")
                price_str = f"${prem_price}" if plan == "premium" else f"${basic_price}"

                if rec_token:
                    await ctx.bot.send_message(
                        chat_id=int(uid),
                        text=(
                            f"🔔 *{name}*, сьогодні закінчується твій план *{plan_name}*.\n\n"
                            f"⚡️ Зараз автоматично спишемо *{price_str}* і продовжимо підписку.\n\n"
                            f"Ти пройшов *{len(s.get('done_lessons', []))} уроків* — так тримати!"
                        ),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🚫 Скасувати", callback_data=f"renew_no_{uid}"),
                        ]])
                    )
                else:
                    lessons  = len(s.get("done_lessons", []))
                    phrases  = len(s.get("mined_sentences", []))
                    streak   = s.get("streak", 0)
                    pay_url  = wfp_create_payment_url(int(uid), plan, float(prem_price if plan == "premium" else basic_price))
                    wfp_link = prem_link if plan == "premium" else basic_link
                    kb = [[
                        InlineKeyboardButton(f"💳 Продовжити {price_str}", url=pay_url),
                    ]]
                    if wfp_link:
                        kb.append([InlineKeyboardButton("🔗 Альтернативне посилання", url=wfp_link)])
                    await ctx.bot.send_message(
                        chat_id=int(uid),
                        text=(
                            f"🔔 *{name}*, сьогодні останній день твого плану *{plan_name}*!\n\n"
                            f"📊 Твій прогрес:\n"
                            f"🎙 Уроків: *{lessons}* | 📚 Фраз: *{phrases}* | 🔥 Стрік: *{streak} дн.*\n\n"
                            f"Продовж підписку прямо зараз — *{price_str}/міс* — і не втрать темп! 👇"
                        ),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(kb)
                    )

            # ── День після закінчення ────────────────────────
            elif days_left == -1 and not s.get(f"expiry_day1_{until_str}"):
                upd_s(int(uid), {f"expiry_day1_{until_str}": True})
                lessons  = len(s.get("done_lessons", []))
                phrases  = len(s.get("mined_sentences", []))
                streak   = s.get("streak", 0)
                pay_url  = wfp_create_payment_url(int(uid), plan, float(prem_price if plan == "premium" else basic_price))
                wfp_link = prem_link if plan == "premium" else basic_link
                kb = [[InlineKeyboardButton(f"💳 Відновити {plan_name} — {price_str}", url=pay_url)]]
                if wfp_link:
                    kb.append([InlineKeyboardButton("🔗 Альтернативне посилання", url=wfp_link)])
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=(
                        f"💤 *{name}*, твій доступ до SpeakChain завершився.\n\n"
                        f"Але твій прогрес нікуди не дівся:\n"
                        f"🎙 *{lessons}* уроків | 📚 *{phrases}* фраз | 🔥 стрік *{streak} дн.*\n\n"
                        f"Відновити доступ — лише *{price_str}/міс* 👇"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(kb)
                )

        except Exception as e:
            logger.warning(f"job_plan_expiry error uid={uid}: {e}")


async def job_weekly_report(ctx: ContextTypes.DEFAULT_TYPE):
    """Щонеділі о 10:05 — персональний тижневий звіт."""
    import datetime as _dt
    if datetime.now().weekday() != 6:  # 6 = неділя
        return

    db    = load_db()
    today = datetime.now()
    week_ago = (today - _dt.timedelta(days=7)).strftime("%Y-%m-%d")
    bot_me   = await ctx.bot.get_me()
    bot_uname = bot_me.username or "SpeakChainBot"

    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if str(uid) in DB_SKIP_KEYS: continue
        if not s.get("onboarding_done"): continue
        if s.get("weekly_report_sent_week") == today.strftime("%Y-W%W"): continue

        all_scores  = s.get("scores", [])
        week_scores = [sc for sc in all_scores if sc.get("date","")[:10] >= week_ago]
        lessons_week = len(week_scores)

        if lessons_week == 0 and not s.get("last_date","") >= week_ago:
            continue

        level      = LEVEL_NAMES.get(s.get("level",""), "")
        streak     = s.get("streak_days", 0)
        total_done = len(s.get("done_lessons", []))
        mined_cnt  = len(s.get("mined_sentences", []))
        name       = s.get("name", "Студенте")
        avg_score  = round(sum(sc.get("score",0) for sc in week_scores) / lessons_week) if lessons_week else 0

        if lessons_week >= 5:   week_emoji, week_verdict = "🏆", "Ти в топ-10% цього тижня!"
        elif lessons_week >= 3: week_emoji, week_verdict = "🔥", "Відмінний тиждень — ти вже в ритмі."
        elif lessons_week >= 1: week_emoji, week_verdict = "✅", "Хороший старт. Ще 2–3 уроки — і відчуєш прогрес."
        else:                   week_emoji, week_verdict = "💤", "Цього тижня поки немає уроків. Один урок зараз змінить це."

        ref_link = f"https://t.me/{bot_uname}?start=ref_{s.get('username') or uid}"

        upd_s(int(uid), {"weekly_report_sent_week": today.strftime("%Y-W%W")})
        try:
            # Денний блок (що зроблено саме сьогодні — неділя)
                today_str    = datetime.now().strftime("%Y-%m-%d")
                scores_today = [sc for sc in s.get("scores",[]) if sc.get("date","")[:10] == today_str]
                had_lesson   = bool(scores_today)
                had_mining   = s.get("last_mining_date","") == today_str
                today_score  = scores_today[-1].get("score",0) if scores_today else 0

                day_part = "\n\n📅 *Сьогодні:*\n"
                if had_lesson:
                    day_part += f"  🎙 Уроків: *{len(scores_today)}*"
                    if today_score: day_part += f"  Бал: *{today_score}/100*"
                    day_part += "\n"
                if had_mining:
                    day_part += "  💎 Фрази збережено\n"
                if not had_lesson and not had_mining:
                    day_part += "  _Сьогодні відпочивав — але тиждень підбито! 💪_\n"

                xp      = s.get("xp_total", 0)
                streak_w = s.get("streak_days", 0)
                phrases  = len([m for m in s.get("mined_sentences",[]) if m.get("date","")[:10] >= week_ago])

                text = (
                    f"{week_emoji} *{name} — підсумок тижня*\n\n"
                    f"📚 Уроків за тиждень: *{lessons_week}*"
                    + (f"  (середній бал: *{avg_score}/100*)" if avg_score else "") + "\n"
                    f"💎 Нових фраз: *{phrases}*   🔥 Стрік: *{streak_w} дн.*\n"
                    f"⚡️ XP всього: *{xp}*\n"
                    f"_{week_verdict}_"
                    + day_part
                )

                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🎬 Новий урок",  callback_data="progress_continue"),
                        InlineKeyboardButton("📊 Прогрес",     callback_data="show_progress"),
                    ]])
                )
        except Exception as e:
            logger.warning(f"Weekly report failed {uid}: {e}")




def _get_blogger_rank(uid: int, blogger_name: str, db: dict) -> tuple[int, int]:
    """
    Повертає (місце студента, загальна кількість) в рейтингу студентів блогера.
    """
    if not blogger_name:
        return 0, 0

    students = [
        (u, s) for u, s in db.items()
        if isinstance(s, dict)
        and str(u) not in DB_SKIP_KEYS
        and s.get("onboarding_done")
        and s.get("affiliate_blogger", "").lower() == blogger_name.lower()
    ]
    if not students:
        return 0, 0

    ranked = sorted(students, key=lambda x: _calc_activity_score(x[1]), reverse=True)
    total  = len(ranked)
    for i, (u, s) in enumerate(ranked, 1):
        if str(u) == str(uid):
            return i, total
    return 0, total


async def send_rank_update(bot, uid: int, blogger_name: str, db: dict):
    """
    Надсилає студенту його поточне місце в рейтингу після монологу.
    """
    rank, total = _get_blogger_rank(uid, blogger_name, db)
    if rank == 0 or total < 2:
        return   # немає сенсу показувати рейтинг з 1 людини

    if rank == 1:
        rank_line = f"🥇 Ти *#1 з {total}* студентів @{blogger_name}! Так тримати!"
    elif rank == 2:
        rank_line = f"🥈 Ти *#2 з {total}* — один крок до першого місця!"
    elif rank == 3:
        rank_line = f"🥉 Ти *#3 з {total}* — топ-3! Продовжуй!"
    elif rank <= total // 2:
        rank_line = f"📈 Ти *#{rank} з {total}* студентів @{blogger_name} — вище середнього!"
    else:
        rank_line = f"🎯 Ти *#{rank} з {total}* студентів @{blogger_name} — є куди рости!"

    try:
        await bot.send_message(
            chat_id=int(uid),
            text=rank_line,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"send_rank_update error uid={uid}: {e}")


def _calc_activity_score(s: dict) -> int:
    """Рахує бал активності студента для рейтингу."""
    # Плеєр і уроки
    player_min  = s.get("player_minutes_total", 0)
    lessons     = len(s.get("done_lessons", []))
    scores      = s.get("scores", [])
    avg_score   = (sum(sc.get("score", 0) for sc in scores) / len(scores)) if scores else 0
    shadow      = s.get("shadow_sessions", 0)
    streak      = s.get("streak_days", 0)
    xp          = s.get("xp_total", 0)

    # Фрази і записи
    phrases     = len(s.get("mined_sentences", []))
    voice_tl    = len(s.get("voice_timeline", []))
    videos      = len(s.get("video_history", []))
    live_sess   = s.get("live_sessions_total", 0)

    # Поширення
    community   = 1 if s.get("community_joined") else 0

    score = (
        player_min  * 2   +   # хвилини в плеєрі
        lessons     * 10  +   # уроки
        avg_score   * 0.5 +   # середній бал
        shadow      * 5   +   # shadowing сесії
        streak      * 3   +   # стрік
        xp          * 0.1 +   # XP
        phrases     * 4   +   # збережені фрази
        voice_tl    * 6   +   # голосові записи
        videos      * 5   +   # відео
        live_sess   * 8   +   # live заняття
        community   * 20      # учасник спільноти
    )
    return int(score)


async def job_group_rating(ctx: ContextTypes.DEFAULT_TYPE):
    """Щотижня в понеділок о 10:00 — публікує рейтинг в Premium групах."""
    from datetime import datetime as _dt
    if _dt.now().weekday() != 0:  # 0 = понеділок
        return

    db   = load_db()
    skip = {"_blogger_codes", "_registered_bloggers", "_processed_orders",
            "_payouts", "_partner_queue", "_community_posts",
            "_feedback_queue", "_weekly_questions", "_premium_group"}

    # Збираємо всіх онбордованих студентів
    students = [
        (uid, s) for uid, s in db.items()
        if isinstance(s, dict)
        and str(uid) not in skip
        and s.get("onboarding_done")
        and s.get("name")
    ]

    if not students:
        return

    # Рахуємо бал кожному
    ranked = sorted(
        [(uid, s, _calc_activity_score(s)) for uid, s in students],
        key=lambda x: x[2], reverse=True
    )

    top10 = ranked[:10]

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    lines = ["🏆 *Рейтинг активності SpeakChain*\n"]
    for i, (uid, s, score) in enumerate(top10):
        name    = s.get("name", "Студент")
        level   = LEVEL_NAMES.get(s.get("level", ""), s.get("level", ""))
        streak  = s.get("streak_days", 0)
        phrases = len(s.get("mined_sentences", []))
        voices  = len(s.get("voice_timeline", []))
        medal   = medals[i]
        lines.append(
            f"{medal} *{name}* — {level}\n"
            f"    🔥 {streak} дн · 💎 {phrases} фраз · 🎙 {voices} записів"
        )

    lines.append("\n_Рейтинг оновлюється щопонеділка_")
    text = "\n".join(lines)

    # Публікуємо в Community
    if COMMUNITY_LINK:
        try:
            await ctx.bot.send_message(
                chat_id=COMMUNITY_LINK, text=text, parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"job_group_rating community error: {e}")

    # Публікуємо в загальну Premium групу
    pg = db.get("_premium_group", {})
    general_gid = pg.get("group_id")
    if general_gid:
        try:
            await ctx.bot.send_message(
                chat_id=general_gid, text=text, parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"job_group_rating general group error: {e}")

    # Публікуємо в групи блогерів
    bloggers = get_registered_bloggers()
    sent_groups = {general_gid}
    for uid, name in bloggers.items():
        bs  = get_s(int(uid))
        gid = bs.get("live_group_id")
        if not gid or gid in sent_groups:
            continue
        # Фільтруємо студентів цього блогера
        blogger_students = [
            (u, s, sc) for u, s, sc in ranked
            if s.get("affiliate_blogger", "").lower() == name.lower()
        ][:10]
        if not blogger_students:
            continue
        b_lines = [f"🏆 *Рейтинг активності — @{name}*\n"]
        for i, (u, s, sc) in enumerate(blogger_students):
            bname   = s.get("name", "Студент")
            level   = LEVEL_NAMES.get(s.get("level", ""), s.get("level", ""))
            streak  = s.get("streak_days", 0)
            phrases = len(s.get("mined_sentences", []))
            voices  = len(s.get("voice_timeline", []))
            medal   = medals[i] if i < len(medals) else f"{i+1}."
            b_lines.append(
                f"{medal} *{bname}* — {level}\n"
                f"    🔥 {streak} дн · 💎 {phrases} фраз · 🎙 {voices} записів"
            )
        b_lines.append("\n_Рейтинг оновлюється щопонеділка_")
        try:
            await ctx.bot.send_message(
                chat_id=gid,
                text="\n".join(b_lines),
                parse_mode="Markdown"
            )
            sent_groups.add(gid)
        except Exception as e:
            logger.warning(f"job_group_rating blogger {name} error: {e}")

async def job_daily_report(ctx: ContextTypes.DEFAULT_TYPE):
    """Щодня о 21:05 — короткий денний звіт. В неділю пропускаємо — weekly_report вже включає денний блок."""
    from datetime import date as _date, timedelta as _td
    if datetime.now().weekday() == 6:  # неділя — надсилає job_weekly_report
        return
    today_str = datetime.now().strftime("%Y-%m-%d")
    db = load_db()
    skip = {"_blogger_codes", "_registered_bloggers", "_processed_orders",
            "_payouts", "_partner_queue", "_community_posts",
            "_feedback_queue", "_weekly_questions"}

    for uid, s in db.items():
        if not isinstance(s, dict) or str(uid) in skip:
            continue
        if not s.get("onboarding_done"):
            continue
        # Тільки тим, хто сьогодні хоч щось зробив
        last = s.get("last_date", "")
        scores_today = [sc for sc in s.get("scores", []) if sc.get("date", "")[:10] == today_str]
        had_lesson   = bool(scores_today)
        had_mining   = s.get("last_mining_date", "") == today_str
        had_srs      = s.get("srs_remind_date", "") == today_str
        # Не дублюємо: якщо вже надіслали сьогодні — пропускаємо
        if s.get("daily_report_sent_date") == today_str:
            continue

        is_active = had_lesson or had_mining or had_srs

        # Неактивним — м'яке нагадування (раз на день, лише онбордженим)
        if not is_active:
            import random as _random
            gentle_nudges = [
                "А пам'ятаєш, ти хотів заговорити англійською? Приділи цьому хоча б кілька хвилин — і ти будеш ближче до мети 🎯",
                "Один маленький урок сьогодні — і завтра буде легше. Твоя англійська чекає 🎙",
                "Не треба багато. Навіть 5 хвилин практики сьогодні — це крок уперед, якого не було вчора 🌱",
                "Ти вже стільки зробив! Не зупиняйся — один урок зараз збереже твій прогрес 🔥",
                "Сьогодні ще є час. Маленький крок щодня — це і є той секрет, який працює 💬",
            ]
            nudge = _random.choice(gentle_nudges)
            name_n = s.get("name", "")
            greeting = f"Привіт, {name_n} 👋\n\n" if name_n else "Привіт 👋\n\n"
            upd_s(int(uid), {"daily_report_sent_date": today_str})
            try:
                await ctx.bot.send_message(
                    chat_id=int(uid),
                    text=greeting + nudge,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🎬 Почати урок", callback_data="progress_continue"),
                    ]])
                )
            except Exception as e:
                logger.warning(f"daily_nudge {uid}: {e}")
            continue

        name    = s.get("name", "Студенте")
        streak  = s.get("streak_days", 0)
        xp      = s.get("xp_total", 0)
        lessons = len(s.get("done_lessons", []))
        phrases = len(s.get("mined_sentences", []))
        score   = scores_today[-1].get("score", 0) if scores_today else 0
        level   = LEVEL_NAMES.get(s.get("level", ""), s.get("level", ""))

        if streak >= 30:   fire, verdict = "🏆", "Легенда! 30+ днів поспіль."
        elif streak >= 14: fire, verdict = "🔥", "Двотижневий стрік — ти машина!"
        elif streak >= 7:  fire, verdict = "💪", "Тиждень без пропусків — так тримати."
        elif streak >= 3:  fire, verdict = "✅", "Три дні поспіль — гарний ритм."
        else:              fire, verdict = "📌", "Сьогодні — зроблено. Завтра — знову."

        lines = [f"{fire} *{name} — підсумок дня*\n"]
        if had_lesson:
            lines.append(f"🎙 Уроків сьогодні: *{len(scores_today)}*" +
                         (f"  (бал: *{score}/100*)" if score else ""))
        if had_mining:
            lines.append(f"💎 Фраз збережено всього: *{phrases}*")
        if had_srs:
            lines.append("🧠 Картки повторення — виконано")
        lines.append(f"🔥 Стрік: *{streak} дн.*")
        lines.append(f"⚡️ XP: *{xp}*  |  Рівень: *{level}*")
        lines.append(f"📈 Уроків всього: *{lessons}*")
        lines.append(f"\n_{verdict}_")

        upd_s(int(uid), {"daily_report_sent_date": today_str})
        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text="\n".join(lines),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🎬 Новий урок",   callback_data="progress_continue"),
                    InlineKeyboardButton("📊 Прогрес",      callback_data="show_progress"),
                ]])
            )
        except Exception as e:
            logger.warning(f"daily_report {uid}: {e}")


# ── Referral gift: +3 days when invited friend completes first lesson ──
async def _maybe_show_referral_prompt(bot, uid: int, s: dict):
    """
    П.1 — Entry point. Показує рефералку після 2-ї або 3-ї ланки.
    Тільки один раз. Не блокує нічого.
    """
    if s.get("referral_prompt_shown"):
        return
    chain_len = s.get("chain", {}).get("length", s.get("streak_days", 0)) or 0
    if chain_len < 2:
        return
    name = s.get("name", "")
    upd_s(uid, {"referral_prompt_shown": True})
    try:
        bot_me = await bot.get_me()
        username = s.get("username") or str(uid)
        ref_link = f"https://t.me/{bot_me.username}?start=ref_{username}"
        await bot.send_message(
            uid,
            f"🔗 {name}, твій ланцюжок росте!\n\n"
            f"Прискор його разом з друзями — "
            "коли ви будуєте ланцюжки разом, обидва ростете швидше.\n\n"
            "👇 Запроси друга і обидва отримаєте бонус:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔗 Зміцнити ланцюжок → Запросити", callback_data="chain_invite_screen"),
            ]])
        )
    except Exception as e:
        logger.warning(f"_maybe_show_referral_prompt {uid}: {e}")


async def cb_chain_invite_screen(update, ctx):
    """
    П.2 — Share moment. Відкриває Social/Invite Mini App.
    """
    q   = update.callback_query
    await q.answer()
    uid = q.from_user.id
    s   = get_s(uid)

    if BOT_WEBHOOK_URL:
        url = _build_social_invite_url(uid, s, db=load_db())
        await q.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(
            uid,
            "🔗 *Зміцни свій ланцюжок*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👥 Відкрити Social", web_app=WebAppInfo(url=url))
            ]])
        )
        return

    # Fallback — текстовий варіант
    chain_len  = s.get("chain", {}).get("length", s.get("streak_days", 0)) or 0
    filled     = "◆" * min(chain_len, 7)
    empty      = "◇" * max(0, 7 - chain_len)
    bar        = f"{filled}{empty}"
    xp         = s.get("xp_total", 0)
    username   = s.get("username") or str(uid)
    ref_link   = f"https://t.me/{ctx.bot.username}?start=ref_{username}"
    wa_text    = f"Я будую мовний ланцюжок у SpeakChain 🔗 Приєднуйся — почнемо разом. {ref_link}"
    wa_url     = f"https://wa.me/?text={wa_text.replace(' ', '%20')}"
    tg_url     = f"https://t.me/share/url?url={ref_link}&text=Я%20будую%20мовний%20ланцюжок%20у%20SpeakChain%20%F0%9F%94%97"

    await q.edit_message_text(
        f"🔗 *Зміцни свій ланцюжок*\n\n"
        f"{bar} {chain_len}/7\n"
        f"⚡️ XP: *{xp}*\n\n"
        f"Коли друг приєднається:\n"
        f"• Стартує з ланки 3\n"
        f"• Обидва отримаєте *+20% XP* на 7 днів\n\n"
        f"Посилання:\n`{ref_link}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Telegram", url=tg_url)],
            [InlineKeyboardButton("💬 WhatsApp", url=wa_url)],
        ])
    )


async def cb_copy_ref_link(update, ctx):
    """П.3 — Copy link."""
    q   = update.callback_query
    uid = q.from_user.id
    s   = get_s(uid)
    bot_me   = await ctx.bot.get_me()
    username = s.get("username") or str(uid)
    ref_link = f"https://t.me/{bot_me.username}?start=ref_{username}"
    await q.answer("Посилання скопійовано!", show_alert=False)
    await ctx.bot.send_message(
        uid,
        f"`{ref_link}`\n\n"
        "_Відправ це посилання другу в будь-якому месенджері_ 👆",
        parse_mode="Markdown"
    )


async def _send_friend_landing(bot, uid: int, referrer_uid: int, s: dict):
    """
    П.4 — Friend landing. Показується коли друг приходить по реферальному посиланню.
    Замість звичайного /start.
    """
    ref_s      = get_s(referrer_uid)
    ref_name   = ref_s.get("name", "Твій друг")
    ref_chain  = ref_s.get("chain", {}).get("length", ref_s.get("streak_days", 0)) or 0
    filled     = "◆" * min(ref_chain, 7)
    empty      = "◇" * max(0, 7 - ref_chain)
    bar        = f"{filled}{empty} {ref_chain} ланок"

    try:
        await bot.send_message(
            uid,
            f"🔗 *Тебе запросили до мовного ланцюжка*\n\n"
            f"*{ref_name}* вже має:\n"
            f"{bar}\n\n"
            f"Коли ти зробиш першу ланку — обидва отримаєте:\n"
            f"• ⚡️ *+20% XP boost* на 7 днів\n"
            f"• 🔗 *+1 бонусна ланка*\n\n"
            f"Ти стартуєш не з нуля — а одразу з ланки 3. 🚀",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔗 Почати свій ланцюжок", callback_data="onboarding_start"),
            ]])
        )
    except Exception as e:
        logger.warning(f"_send_friend_landing {uid}: {e}")


async def _check_friend_overtook(bot, db: dict):
    """
    П.8 — "Твій друг обігнав тебе на 1 ланку."
    Запускається щодня з daily jobs.
    """
    for uid, s in db.items():
        if not isinstance(s, dict): continue
        if not s.get("onboarding_done"): continue

        referrer_uid = s.get("referrer_uid")
        if not referrer_uid:
            continue

        my_chain  = s.get("chain", {}).get("length", 0) or 0
        ref_s     = db.get(str(referrer_uid), {})
        if not isinstance(ref_s, dict):
            continue
        ref_chain = ref_s.get("chain", {}).get("length", 0) or 0
        ref_name  = ref_s.get("name", "Твій друг")

        # Друг обігнав на 1 ланку — надсилаємо один раз
        overtook_key = f"overtook_notified_{ref_chain}"
        if ref_chain == my_chain + 1 and not s.get(overtook_key):
            upd_s(int(uid), {overtook_key: True})
            try:
                await bot.send_message(
                    int(uid),
                    f"⚡️ *{ref_name} обігнав тебе на 1 ланку!*\n\n"
                    f"Він: *{ref_chain} ланок* · Ти: *{my_chain} ланок*\n\n"
                    "Зроби урок зараз — і вирівняй рахунок 👇",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🎬 Зробити ланку", callback_data="progress_continue"),
                    ]])
                )
            except Exception as e:
                logger.warning(f"_check_friend_overtook {uid}: {e}")


async def _send_network_chains(bot, uid: int, s: dict, db: dict):
    """
    П.7 — Social comparison. 'Your network chains.'
    Показує ланцюжки юзера, друга і топ юзера.
    """
    my_chain   = s.get("chain", {}).get("length", 0) or 0
    ref_uid    = s.get("referrer_uid")
    ref_name   = "—"
    ref_chain  = 0

    if ref_uid:
        ref_s     = db.get(str(ref_uid), {})
        ref_name  = ref_s.get("name", "Друг") if isinstance(ref_s, dict) else "Друг"
        ref_chain = ref_s.get("chain", {}).get("length", 0) if isinstance(ref_s, dict) else 0

    # Топ юзер по chain length
    top_chain = 0
    top_name  = "—"
    for u, us in db.items():
        if not isinstance(us, dict): continue
        cl = us.get("chain", {}).get("length", 0) or 0
        if cl > top_chain:
            top_chain = cl
            top_name  = us.get("name", "Невідомий")

    def bar(n):
        n = min(n, 10)
        return "◆" * n + "◇" * (10 - n)

    name = s.get("name", "Ти")
    try:
        await bot.send_message(
            uid,
            f"📊 *Ваші ланцюжки*\n\n"
            f"👤 *{name}*\n{bar(my_chain)} {my_chain}\n\n"
            f"🤝 *{ref_name}*\n{bar(ref_chain)} {ref_chain}\n\n"
            f"🏆 *{top_name}* (топ)\n{bar(top_chain)} {top_chain}\n\n"
            "_Роби урок щодня — і твій ланцюжок росте_ 🔗",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎬 Додати ланку", callback_data="progress_continue"),
            ]])
        )
    except Exception as e:
        logger.warning(f"_send_network_chains {uid}: {e}")


async def _check_return_loop(bot, uid: int, s: dict):
    """
    П.9 — Return loop. Коли друг (якого запросили) падає в chain.
    Надсилає нотифікацію інвайтеру.
    """
    chain = s.get("chain", {})
    if chain.get("status") != "broken":
        return

    referrer_uid = s.get("referrer_uid")
    if not referrer_uid:
        return

    broken_key = f"return_loop_notified_{chain.get('broke_at','')}"
    if s.get(broken_key):
        return
    upd_s(uid, {broken_key: True})

    stud_name = s.get("name", "Твій друг")
    try:
        await bot.send_message(
            referrer_uid,
            f"🔗 *{stud_name} розірвав ланцюжок.*\n\n"
            "Надішли йому нагадування — разом легше не зупинятись.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📤 Нагадати другу", callback_data=f"remind_friend_{uid}"),
            ]])
        )
    except Exception as e:
        logger.warning(f"_check_return_loop {uid}: {e}")


async def _maybe_grant_referral_bonus(bot, student_uid: int):
    """
    Викликається після першої ланки студента.
    Обидва отримують: +20% XP boost на 7 днів + +1 bonus chain link.
    """
    s        = get_s(student_uid)
    ref_code = s.get("affiliate_ref", "")
    if not ref_code or s.get("referral_bonus_granted"):
        return

    # Шукаємо реферера-студента (не блогера)
    db = load_db()
    referrer_uid = None
    for uid, us in db.items():
        if not isinstance(us, dict): continue
        uname = us.get("username", "") or str(uid)
        if ref_code == uname or ref_code.startswith(uname + "_"):
            if not us.get("is_blogger"):
                referrer_uid = int(uid)
                break

    if not referrer_uid:
        return

    from datetime import timedelta
    boost_until = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    # Застосовуємо бонус обом
    for target_uid in (student_uid, referrer_uid):
        ts    = get_s(target_uid)
        chain = ts.get("chain", {})
        chain["length"] = chain.get("length", 0) + 1   # +1 bonus link
        upd_s(target_uid, {
            "chain":           chain,
            "xp_boost_until":  boost_until,
            "xp_boost_pct":    20,
        })

    upd_s(student_uid, {"referral_bonus_granted": True})

    ref_name  = get_s(referrer_uid).get("name", "твій друг")
    stud_name = s.get("name", "студент")

    try:
        await bot.send_message(
            chat_id=student_uid,
            text=(
                f"🔗 *Ланцюжок зміцнено!*\n\n"
                f"Ти прийшов по запрошенню *{ref_name}* — обидва отримуєте:\n\n"
                f"• ⚡️ *+20% XP boost* на 7 днів\n"
                f"• 🔗 *+1 бонусна ланка* до ланцюжка\n\n"
                "Навчайтесь разом і ростіть швидше 💪"
            ),
            parse_mode="Markdown"
        )
        await bot.send_message(
            chat_id=referrer_uid,
            text=(
                f"🔗 *Твій ланцюжок зміцнився!*\n\n"
                f"*{stud_name}* зробив першу ланку по твоєму запрошенню.\n\n"
                f"• ⚡️ *+20% XP boost* на 7 днів\n"
                f"• 🔗 *+1 бонусна ланка* до ланцюжка\n\n"
                "Ви будуєте ланцюжки разом 🎉"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Referral bonus notify error: {e}")


# ══════════════════════════════════════════════════════════════
# SPEAKING BUDDY + AI TUTOR + REWARDS — нові handlers
# ══════════════════════════════════════════════════════════════

import hmac as _hmac_buddy, hashlib as _hashlib_buddy
import urllib.parse as _urlp_buddy

PIXABAY_API_KEY      = os.environ.get("PIXABAY_API_KEY", "")
DEMO_LIMIT           = 5
TRIAL_LIMIT          = 200
BASIC_LIMIT          = 9999
CONTEXT_FREE         = 4
CONTEXT_TRIAL        = 8
CONTEXT_PAID         = 20

# Тимчасові кеші в RAM (картинки і rate limit) — не критичні для персистентності
_PIXABAY_CACHE: dict = {}
_REWARD_RATE: dict   = {}


def verify_telegram_init_data(init_data: str):
    """Перевірка підпису Telegram WebApp initData."""
    if not init_data or not BOT_TOKEN:
        return None
    try:
        params = dict(p.split('=', 1) for p in init_data.split('&') if '=' in p)
        received_hash = params.pop('hash', '')
        data_check = '\n'.join(f"{k}={v}" for k, v in sorted(params.items()))
        secret = _hmac_buddy.new(b'WebAppData', BOT_TOKEN.encode(), _hashlib_buddy.sha256).digest()
        expected = _hmac_buddy.new(secret, data_check.encode(), _hashlib_buddy.sha256).hexdigest()
        if not _hmac_buddy.compare_digest(expected, received_hash):
            return None
        return json.loads(_urlp_buddy.unquote(params.get('user', '{}')))
    except Exception as e:
        logger.warning(f"verify_init_data error: {e}")
        return None


def _get_buddy_daily(uid: int) -> dict:
    """
    Повертає buddy_daily стан з БД юзера. Якщо інший день — скидає лічильник.
    Структура: {"date": "YYYY-MM-DD", "count": N}
    """
    import time as _t
    today = _t.strftime("%Y-%m-%d", _t.localtime())
    if not uid:
        return {"date": today, "count": 0}
    try:
        s = get_s(uid)
        bd = s.get("buddy_daily", {})
        if bd.get("date") != today:
            return {"date": today, "count": 0}
        return bd
    except Exception:
        return {"date": today, "count": 0}


def _save_buddy_daily(uid: int, bd: dict):
    """Зберігає buddy_daily через upd_s (write-behind → PostgreSQL)."""
    if not uid:
        return
    try:
        upd_s(uid, {"buddy_daily": bd})
    except Exception as e:
        logger.warning(f"buddy_daily save error uid={uid}: {e}")


def get_buddy_user_status(uid: int) -> dict:
    """Статус юзера для Speaking Buddy: 'demo' | 'trial' | 'paid'."""
    if not uid:
        return {"status": "demo", "max_msgs": DEMO_LIMIT, "msg_count": 0}
    try:
        s = get_s(uid)
        if is_premium(s):
            status, max_msgs = "paid", BASIC_LIMIT
        elif is_in_trial(s):
            status, max_msgs = "trial", TRIAL_LIMIT
        else:
            status, max_msgs = "demo", DEMO_LIMIT
    except Exception:
        status, max_msgs = "demo", DEMO_LIMIT

    bd = _get_buddy_daily(uid)
    return {
        "status":    status,
        "max_msgs":  max_msgs,
        "msg_count": bd["count"],
    }


def _check_and_increment_buddy(uid: int, status: str):
    """Перевірка ліміту і інкремент. Returns (allowed, remaining)."""
    limits = {"demo": DEMO_LIMIT, "trial": TRIAL_LIMIT, "paid": BASIC_LIMIT}
    limit = limits.get(status, DEMO_LIMIT)
    bd = _get_buddy_daily(uid)
    if bd["count"] >= limit:
        return False, 0
    bd["count"] += 1
    _save_buddy_daily(uid, bd)
    return True, limit - bd["count"]


ROLE_PROMPTS_BUDDY = {
    "friendly": "You are a warm, encouraging English conversation partner. Play the other person in the scenario naturally. After EACH reply, add 1-2 short feedback items in Ukrainian on the learner's last message (grammar, phrasing). Be encouraging. Skip feedback if perfect.",
    "strict": "You are a strict English teacher playing the scenario role. Correct EVERY grammar mistake. After each reply, provide specific corrections in Ukrainian. Be direct and precise.",
    "native": "You are a native English speaker in this scenario. Speak completely naturally — use contractions, colloquialisms, natural rhythm. Don't simplify. Only flag major errors that would confuse a native.",
    "patient": "You are a patient teacher playing the scenario role. Speak clearly. If learner struggles, offer hints. Always encourage. Explain difficult vocabulary. Give gentle, detailed feedback in Ukrainian.",
}

LEVEL_CONTEXT_BUDDY = {
    "beginner":     "Learner level: A1-A2. Use simple vocabulary and short sentences.",
    "intermediate": "Learner level: B1-B2. Normal conversational complexity.",
    "advanced":     "Learner level: C1-C2. Use rich vocabulary, complex structures.",
}


def build_buddy_system_prompt(scenario, scenario_desc, role, level):
    return f"""You are an AI English conversation practice partner.

SCENARIO: {scenario}
CONTEXT: {scenario_desc}

STYLE: {ROLE_PROMPTS_BUDDY.get(role, ROLE_PROMPTS_BUDDY['friendly'])}

{LEVEL_CONTEXT_BUDDY.get(level, LEVEL_CONTEXT_BUDDY['intermediate'])}

RULES:
- Stay in character at all times
- Keep YOUR replies to 2-4 sentences max
- Feedback in Ukrainian (max 12 words per item)
- Conversation in English only

RESPOND ONLY with valid JSON (no markdown, no backticks):
{{"reply": "your English response", "feedback": [{{"type": "good", "text": "✓ Ukrainian"}}, {{"type": "tip", "text": "💡 Ukrainian"}}]}}

Empty feedback array if none needed: "feedback": []"""


CORS_BUDDY = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


async def handle_buddy_page(request):
    """GET /buddy → speaking_buddy_v2.html"""
    import pathlib
    for path in [
        pathlib.Path(__file__).parent / "miniapps" / "speaking_buddy_v2.html",
        pathlib.Path(__file__).parent / "speaking_buddy_v2.html",
        pathlib.Path("miniapps/speaking_buddy_v2.html"),
        pathlib.Path("speaking_buddy_v2.html"),
    ]:
        if path.exists():
            return _web.FileResponse(path, headers={**CORS_BUDDY, "Cache-Control": "no-cache"})
    return _web.Response(text="speaking_buddy_v2.html not found", status=404)


async def handle_progress_page(request):
    """GET /progress_v3 → progress_v3.html"""
    import pathlib
    for path in [
        pathlib.Path(__file__).parent / "miniapps" / "progress_v3.html",
        pathlib.Path(__file__).parent / "progress_v3.html",
        pathlib.Path("miniapps/progress_v3.html"),
        pathlib.Path("progress_v3.html"),
    ]:
        if path.exists():
            return _web.FileResponse(path, headers={**CORS_BUDDY, "Cache-Control": "no-cache"})
    return _web.Response(text="progress_v3.html not found", status=404)


async def handle_toast_js(request):
    """GET /toast_rewards.js"""
    import pathlib
    for path in [
        pathlib.Path(__file__).parent / "miniapps" / "toast_rewards.js",
        pathlib.Path(__file__).parent / "toast_rewards.js",
        pathlib.Path("miniapps/toast_rewards.js"),
        pathlib.Path("toast_rewards.js"),
    ]:
        if path.exists():
            return _web.FileResponse(path, headers={
                **CORS_BUDDY,
                "Content-Type": "application/javascript",
                "Cache-Control": "public, max-age=3600",
            })
    return _web.Response(text="toast_rewards.js not found", status=404)


async def handle_buddy_status(request):
    """POST /buddy_status → {status, max_msgs, msg_count}"""
    try:
        data = await request.json()
    except Exception:
        return _web.json_response({"status": "demo", "max_msgs": DEMO_LIMIT, "msg_count": 0}, headers=CORS_BUDDY)
    uid = int(data.get("uid", 0))
    init_data = data.get("init_data", "")
    if init_data:
        tg_user = verify_telegram_init_data(init_data)
        if tg_user:
            uid = tg_user.get("id", uid)
    return _web.json_response(get_buddy_user_status(uid), headers=CORS_BUDDY)


async def handle_buddy_image(request):
    """GET /buddy_image?q=airport → {url}"""
    import time as _t
    q = request.rel_url.query.get("q", "").strip()
    if not q:
        return _web.json_response({"url": None}, headers=CORS_BUDDY)
    cached = _PIXABAY_CACHE.get(q.lower())
    if cached and _t.time() < cached.get("exp", 0):
        return _web.json_response({"url": cached["url"]}, headers=CORS_BUDDY)
    if not PIXABAY_API_KEY:
        return _web.json_response({"url": None}, headers=CORS_BUDDY)
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                "https://pixabay.com/api/",
                params={"key": PIXABAY_API_KEY, "q": q, "image_type": "photo",
                        "orientation": "horizontal", "min_width": 640,
                        "safesearch": "true", "per_page": 5},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                hits = (await resp.json()).get("hits", [])
        url = hits[0]["webformatURL"] if hits else None
        _PIXABAY_CACHE[q.lower()] = {"url": url, "exp": _t.time() + 86400}
        return _web.json_response({"url": url}, headers=CORS_BUDDY)
    except Exception as e:
        logger.warning(f"Pixabay error '{q}': {e}")
        return _web.json_response({"url": None}, headers=CORS_BUDDY)


async def handle_buddy_chat(request):
    """POST /buddy_chat → {reply, feedback} або {error}"""
    import time as _t
    if request.method == "OPTIONS":
        return _web.Response(headers=CORS_BUDDY)
    try:
        data = await request.json()
    except Exception:
        return _web.json_response({"error": "Invalid JSON"}, status=400, headers=CORS_BUDDY)

    uid = int(data.get("uid", 0))
    init_data = data.get("init_data", "")
    if init_data:
        tg_user = verify_telegram_init_data(init_data)
        if tg_user:
            uid = tg_user.get("id", uid)

    user_status = get_buddy_user_status(uid) if uid else {"status": "demo"}
    status = user_status["status"]

    allowed, remaining = _check_and_increment_buddy(uid or -1, status)
    if not allowed:
        return _web.json_response({
            "show_paywall": True,
            "reply": "Чудова розмова! Щоб продовжити — починай безкоштовний тріал SpeakChain 🚀"
        }, headers=CORS_BUDDY)

    rate_key = f"_buddy_rate_{uid}"
    last = getattr(handle_buddy_chat, rate_key, 0)
    if _t.time() - last < 2:
        return _web.json_response({"error": "Зачекай секунду..."}, status=429, headers=CORS_BUDDY)
    setattr(handle_buddy_chat, rate_key, _t.time())

    ctx_limits = {"demo": CONTEXT_FREE, "trial": CONTEXT_TRIAL, "paid": CONTEXT_PAID}
    ctx_limit = ctx_limits.get(status, CONTEXT_FREE)
    history = [m for m in data.get("history", []) if m.get("content") != "[START]"][-ctx_limit:]

    system = build_buddy_system_prompt(
        data.get("scenario", "General conversation"),
        data.get("scenario_desc", ""),
        data.get("role", "friendly"),
        data.get("level", "intermediate"),
    )

    try:
        response = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=system,
            messages=history or [{"role": "user", "content": "Let's start the scenario."}],
        )
        raw = response.content[0].text.strip()
        raw = raw[raw.find("{"):raw.rfind("}")+1]
        parsed = json.loads(raw)

        # ── Зберігаємо статистику сесії в БД (write-behind) ──
        if uid:
            try:
                _s = get_s(uid)
                stats = _s.get("buddy_stats", {
                    "total_messages": 0,
                    "total_sessions": 0,
                    "scenarios_tried": [],
                    "last_session_date": None,
                    "feedback_good_count": 0,
                    "feedback_tip_count": 0,
                })
                stats["total_messages"] = stats.get("total_messages", 0) + 1
                stats["last_session_date"] = datetime.now().isoformat()

                scenario_name = data.get("scenario", "")
                if scenario_name and scenario_name not in stats.get("scenarios_tried", []):
                    stats.setdefault("scenarios_tried", []).append(scenario_name)
                    stats["scenarios_tried"] = stats["scenarios_tried"][-50:]
                    stats["total_sessions"] = stats.get("total_sessions", 0) + 1

                for f in parsed.get("feedback", []):
                    if f.get("type") == "good":
                        stats["feedback_good_count"] = stats.get("feedback_good_count", 0) + 1
                    elif f.get("type") == "tip":
                        stats["feedback_tip_count"] = stats.get("feedback_tip_count", 0) + 1

                upd_s(uid, {"buddy_stats": stats})
            except Exception as e:
                logger.warning(f"buddy_stats save error uid={uid}: {e}")

        return _web.json_response({
            "reply":     parsed.get("reply", raw),
            "feedback":  parsed.get("feedback", []),
            "remaining": remaining,
        }, headers=CORS_BUDDY)
    except json.JSONDecodeError:
        return _web.json_response({"reply": raw, "feedback": []}, headers=CORS_BUDDY)
    except Exception as e:
        logger.error(f"buddy_chat error uid={uid}: {e}")
        return _web.json_response({"error": "AI error. Try again."}, status=500, headers=CORS_BUDDY)


# ── Toast rewards ──
RATE_WINDOW_SEC_R = 60
RATE_MAX_PER_WINDOW_R = 30


def _check_reward_rate(uid: int) -> bool:
    """Anti-spam: не більше N подій за хвилину."""
    import time as _t
    now = _t.time()
    events = _REWARD_RATE.get(uid, [])
    events = [t for t in events if now - t < RATE_WINDOW_SEC_R]
    if len(events) >= RATE_MAX_PER_WINDOW_R:
        return False
    events.append(now)
    _REWARD_RATE[uid] = events
    return True


async def handle_sc_reward(request):
    """POST /sc_reward — toast подія від miniapp, записує XP + chain."""
    if request.method == "OPTIONS":
        return _web.Response(headers=CORS_BUDDY)
    try:
        data = await request.json()
    except Exception:
        return _web.json_response({"ok": False}, status=400, headers=CORS_BUDDY)

    uid = int(data.get("uid", 0))
    init_data = data.get("init_data", "")
    if init_data:
        tg_user = verify_telegram_init_data(init_data)
        if tg_user:
            uid = tg_user.get("id", uid)
    if not uid:
        return _web.json_response({"ok": False}, status=400, headers=CORS_BUDDY)

    if not _check_reward_rate(uid):
        return _web.json_response({"ok": False, "error": "rate limit"}, status=429, headers=CORS_BUDDY)

    action       = data.get("action", "")
    xp_amount    = max(0, min(int(data.get("xp", 0)), 100))
    chain_amount = max(0, min(int(data.get("chain", 0)), 5))

    try:
        s = get_s(uid)
    except Exception:
        return _web.json_response({"ok": False}, status=500, headers=CORS_BUDDY)

    updates = {}
    if xp_amount > 0:
        updates["xp_total"] = s.get("xp_total", 0) + xp_amount
        xp_log = s.get("xp_log", [])
        xp_log.append({
            "date":   datetime.now().isoformat(),
            "action": action,
            "amount": xp_amount,
        })
        updates["xp_log"] = xp_log[-100:]

    if chain_amount > 0:
        today = datetime.now().strftime("%Y-%m-%d")
        actions_today = s.get("actions_today", {})
        if actions_today.get("date") != today:
            actions_today = {"date": today, "count": 0}
        actions_today["count"] += chain_amount
        updates["actions_today"] = actions_today
        if s.get("last_date") != today:
            updates["last_date"] = today

    if updates:
        try:
            upd_s(uid, updates)
        except Exception as e:
            logger.warning(f"sc_reward upd_s error uid={uid}: {e}")
            return _web.json_response({"ok": False}, status=500, headers=CORS_BUDDY)

    return _web.json_response({
        "ok":          True,
        "xp_added":    xp_amount,
        "chain_added": chain_amount,
    }, headers=CORS_BUDDY)


# ══════════════════════════════════════════════════════════════
# END SPEAKING BUDDY HANDLERS
# ══════════════════════════════════════════════════════════════


if __name__ == "__main__":
    import threading
    from aiohttp import web as _web

    print("=== STARTING HTTP SERVER ===", flush=True)

    def run_http():
        import asyncio as _asyncio
        print("=== HTTP THREAD STARTED ===", flush=True)

        async def _start():
            wfp = _web.Application()
            wfp.router.add_get("/pay",                handle_wayforpay_pay_page)
            wfp.router.add_post("/wayforpay_webhook", handle_wayforpay_webhook)
            wfp.router.add_get("/captions",           handle_captions_proxy)
            wfp.router.add_post("/register_ref",     handle_register_ref)
            wfp.router.add_post("/session",           handle_session_end)
            wfp.router.add_post("/player_action",     handle_player_action)
            wfp.router.add_get("/chain_dashboard",    handle_chain_dashboard)
            wfp.router.add_get("/social_invite",      handle_social_invite)
            wfp.router.add_get("/leaderboard",        handle_leaderboard)
            wfp.router.add_get("/paywall",            handle_paywall)

            # ── Speaking Buddy + AI Tutor ──
            wfp.router.add_get ("/buddy",            handle_buddy_page)
            wfp.router.add_post("/buddy_status",     handle_buddy_status)
            wfp.router.add_get ("/buddy_image",      handle_buddy_image)
            wfp.router.add_post("/buddy_chat",       handle_buddy_chat)
            wfp.router.add_get ("/progress_v3",      handle_progress_page)
            wfp.router.add_get ("/toast_rewards.js", handle_toast_js)
            wfp.router.add_post("/sc_reward",        handle_sc_reward)

            # ── CORS preflight для всіх ендпоінтів ──────────
            cors_headers = {
                "Access-Control-Allow-Origin":  "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            }
            async def handle_options(request):
                return _web.Response(status=200, headers=cors_headers)
            wfp.router.add_route("OPTIONS", "/{path_info:.*}", handle_options)
            wfp.router.add_get("/health",             lambda r: _web.Response(text="ok"))
            wfp.router.add_get("/",                   lambda r: _web.HTTPFound("https://t.me/SpeakChainBot"))
            wfp.router.add_post("/",                  lambda r: _web.HTTPFound("https://t.me/SpeakChainBot"))
            runner = _web.AppRunner(wfp)
            await runner.setup()
            port = int(os.environ.get("PORT", "8080"))
            for _p in [port, 8081, 8082, 9000]:
                try:
                    site = _web.TCPSite(runner, "0.0.0.0", _p)
                    await site.start()
                    print(f"=== HTTP :{_p} READY ===", flush=True)
                    break
                except OSError:
                    print(f"Port {_p} busy, trying next...", flush=True)
            await _asyncio.Event().wait()

        _asyncio.run(_start())

    http_thread = threading.Thread(target=run_http, daemon=True)
    http_thread.start()
    import time as _time
    _time.sleep(1)
    print("=== HTTP THREAD LAUNCHED ===", flush=True)

    main()
