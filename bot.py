"""Zeiterfassung Telegram Bot v1.2.6"""

import datetime
import io
import json
import logging
import os
import re
import sys
from zoneinfo import ZoneInfo

import anthropic
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ── Setup ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

TOKEN = "8673206171:AAEwr7EXU7a2y6frMspRATKRvWIdHlWbCeU"
ADMIN_IDS: set[int] = {7593372353}

# ── Wizard state ──────────────────────────────────────────────────────────────
WAITING_HOURS = 1
WAITING_ABSENCE_CONFIRM = 2
WAITING_TRIP_DESTINATION = 3

# {telegram_id: {"state": int|None, "date": iso, "absence_type": str|None, "expires": datetime}}
wizard_state: dict = {}
# {date_iso: set(telegram_ids)} – reset daily
already_asked: dict = {}

NLP_EXAMPLES = (
    "❓ Das habe ich nicht verstanden. Beispiele:\n"
    "• Heute von 7:30 bis 13:00 gearbeitet\n"
    "• Am 15.5. von 8 bis 16 Uhr\n"
    "• Urlaub vom 1.7. bis 15.7.\n"
    "• Am 3.8. Flextag\n"
    "• Krank von 10.6. bis 12.6."
)

_WEEKDAY_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_WEEKDAY_SHORT = _WEEKDAY_DE  # Alias
_MONTH_DE = ["Januar","Februar","März","April","Mai","Juni",
             "Juli","August","September","Oktober","November","Dezember"]

# ── DB helpers ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from db import connect, init_db  # noqa: E402


def _load_bot_config_from_db() -> dict:
    try:
        db = connect()
        rows = db.execute("SELECT key, value FROM bot_config").fetchall()
        db.close()
        return {r["key"]: (r["value"] or "") for r in rows}
    except Exception:
        return {}


_bot_db_cfg = _load_bot_config_from_db()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or _bot_db_cfg.get("bot_token") or TOKEN  # noqa: F811

_ids_raw = os.environ.get("TELEGRAM_ADMIN_IDS") or _bot_db_cfg.get("admin_telegram_ids") or ""
if _ids_raw:
    _parsed = {int(x.strip()) for x in _ids_raw.split(",") if x.strip().isdigit()}
    if _parsed:
        ADMIN_IDS = _parsed  # noqa: F811

_db_api_key = _bot_db_cfg.get("anthropic_api_key") or ""
if _db_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = _db_api_key


def _get_user_id(telegram_id: int) -> "int | None":
    db = connect()
    try:
        r = db.execute(
            "SELECT user_id FROM telegram_users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        return int(r["user_id"]) if r else None
    finally:
        db.close()


def _get_user_row(user_id: int) -> "dict | None":
    db = connect()
    try:
        r = db.execute(
            "SELECT id, username, display_name FROM users WHERE id=? AND is_active=1",
            (user_id,),
        ).fetchone()
        return dict(r) if r else None
    finally:
        db.close()


def _get_user_by_username(username: str) -> "dict | None":
    db = connect()
    try:
        r = db.execute(
            "SELECT id, username, display_name FROM users WHERE username=? AND is_active=1",
            (username,),
        ).fetchone()
        return dict(r) if r else None
    finally:
        db.close()


def _all_users() -> list[dict]:
    db = connect()
    try:
        return [
            dict(r)
            for r in db.execute(
                "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY username"
            ).fetchall()
        ]
    finally:
        db.close()


def _get_reminder_settings(telegram_id: int) -> dict:
    db = connect()
    try:
        r = db.execute(
            "SELECT wizard_enabled, reminder_time FROM telegram_users WHERE telegram_id=?",
            (telegram_id,),
        ).fetchone()
        if r:
            return {
                "enabled": bool(int(r["wizard_enabled"] or 0)),
                "time": r["reminder_time"] or "20:00",
            }
        return {"enabled": True, "time": "20:00"}
    finally:
        db.close()


def _set_reminder_settings(telegram_id: int, enabled: bool, reminder_time: str) -> None:
    db = connect()
    try:
        db.execute(
            "UPDATE telegram_users SET wizard_enabled=?, reminder_time=? WHERE telegram_id=?",
            (1 if enabled else 0, reminder_time, telegram_id),
        )
        db.commit()
        logger.info("reminder_settings updated: telegram_id=%s enabled=%s time=%s", telegram_id, enabled, reminder_time)
    finally:
        db.close()


def _get_telegram_id_for_user(user_id: int) -> "int | None":
    db = connect()
    try:
        r = db.execute(
            "SELECT telegram_id FROM telegram_users WHERE user_id=?", (user_id,)
        ).fetchone()
        return int(r["telegram_id"]) if r else None
    finally:
        db.close()


def _parse_reminder_time(s: str) -> "str | None":
    m = re.match(r"^(\d{1,2}):(\d{2})$", s.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (15 <= h <= 23) or not (0 <= mi <= 59):
        return None
    return f"{h:02d}:{mi:02d}"


# ── Calculation helpers ───────────────────────────────────────────────────────

def _minutes_from_hhmm(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _fmt_minutes_signed(mins: int) -> str:
    sign = "+" if mins >= 0 else "-"
    mins = abs(mins)
    return f"{sign}{mins // 60:02d}:{mins % 60:02d}"


def _fmt_minutes(mins: int) -> str:
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _fmt_date_de(iso: str) -> str:
    if not iso:
        return ""
    parts = str(iso)[:10].split("-")
    if len(parts) == 3:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return iso


def _iter_days(start_iso: str, end_iso: str):
    sd = datetime.date.fromisoformat(start_iso)
    ed = datetime.date.fromisoformat(end_iso)
    d = sd
    while d <= ed:
        yield d.isoformat()
        d += datetime.timedelta(days=1)


def _get_tracking_start(user_id: int) -> "str | None":
    db = connect()
    try:
        r = db.execute("SELECT tracking_start_date FROM users WHERE id=?", (user_id,)).fetchone()
        val = r["tracking_start_date"] if r else None
        return str(val)[:10] if val else None
    finally:
        db.close()


def _get_start_balance_minutes(user_id: int) -> int:
    db = connect()
    try:
        r = db.execute(
            "SELECT start_minutes FROM user_balance WHERE user_id=?", (user_id,)
        ).fetchone()
        return int(r["start_minutes"]) if r else 0
    finally:
        db.close()


def _normalize_schedule(s: "dict | None") -> dict:
    """Stellt sicher dass alle Keys vorhanden sind (identisch zu app.py)."""
    if not s:
        return {}
    # weekly_minutes Fallback aus weekly_hours
    if not s.get("weekly_minutes"):
        wh = s.get("weekly_hours")
        try:
            s["weekly_minutes"] = int(float(wh) * 60) if wh else 0
        except Exception:
            s["weekly_minutes"] = 0
    if not s.get("mode"):
        s["mode"] = "weekly"
    if s.get("workdays_mask") is None:
        s["workdays_mask"] = 31
    if s.get("block_weekends_holidays") is None:
        s["block_weekends_holidays"] = 1
    for k in ["mon_minutes","tue_minutes","wed_minutes","thu_minutes","fri_minutes","sat_minutes","sun_minutes"]:
        if s.get(k) is None:
            s[k] = 0
    return s


def _get_user_schedule_for_day(user_id: int, iso_day: str) -> dict:
    db = connect()
    try:
        row = db.execute(
            "SELECT * FROM user_schedules WHERE user_id=? AND valid_from<=? ORDER BY valid_from DESC LIMIT 1",
            (user_id, iso_day),
        ).fetchone()
        if row:
            return _normalize_schedule(dict(row))
        r = db.execute("SELECT * FROM user_schedule WHERE user_id=?", (user_id,)).fetchone()
        return _normalize_schedule(dict(r) if r else None)
    finally:
        db.close()


_WEEKDAY_COLS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_WEEKDAY_BITS = [1, 2, 4, 8, 16, 32, 64]


def _mask_allows(mask: int, weekday: int) -> bool:
    return bool(mask & _WEEKDAY_BITS[weekday])


def _is_workday_for_user(iso_day: str, schedule: "dict | None") -> bool:
    if not schedule:
        return False
    d = datetime.date.fromisoformat(iso_day)
    wd = d.weekday()
    block = int(schedule.get("block_weekends_holidays") or 1)
    if block and wd >= 5:
        return False
    mask = int(schedule.get("workdays_mask") or 31)
    return _mask_allows(mask, wd)


def _is_holiday(iso_day: str) -> bool:
    db = connect()
    try:
        r = db.execute(
            "SELECT is_holiday FROM calendar_days WHERE day=?", (iso_day,)
        ).fetchone()
        return bool(r and r["is_holiday"])
    finally:
        db.close()


def _is_absence_on_day(user_id: int, iso_day: str) -> bool:
    db = connect()
    try:
        ab = db.execute(
            "SELECT id FROM absences WHERE user_id=? AND date_from<=? AND date_to>=?",
            (user_id, iso_day, iso_day),
        ).fetchone()
        return ab is not None
    finally:
        db.close()


def _has_entry_today(user_id: int, iso_day: str) -> bool:
    db = connect()
    try:
        r = db.execute(
            "SELECT id FROM time_blocks WHERE user_id=? AND day=? LIMIT 1",
            (user_id, iso_day),
        ).fetchone()
        if r:
            return True
        r = db.execute(
            "SELECT id FROM time_entries WHERE user_id=? AND day=? LIMIT 1",
            (user_id, iso_day),
        ).fetchone()
        return r is not None
    finally:
        db.close()


def _week_dates_from(iso_day: str) -> list:
    d = datetime.date.fromisoformat(iso_day)
    monday = d - datetime.timedelta(days=d.weekday())
    return [monday + datetime.timedelta(days=i) for i in range(7)]


def _expected_minutes_for_day(user_id: int, iso_day: str) -> int:
    if _is_holiday(iso_day):
        return 0
    schedule = _get_user_schedule_for_day(user_id, iso_day)
    if not schedule:
        return 0
    d = datetime.date.fromisoformat(iso_day)
    wd = d.weekday()
    mask = int(schedule.get("workdays_mask") or 31)
    if not _mask_allows(mask, wd):
        return 0
    block = int(schedule.get("block_weekends_holidays") or 1)
    if block and wd >= 5:
        return 0
    if _is_absence_on_day(user_id, iso_day):
        return 0
    mode = (schedule.get("mode") or "weekly").strip().lower()
    if mode == "daily":
        col = _WEEKDAY_COLS[wd] + "_minutes"
        return int(schedule.get(col) or 0)
    weekly = int(schedule.get("weekly_minutes") or 0)
    eligible = sorted(
        wd_day for wd_day in _week_dates_from(iso_day)
        if _mask_allows(mask, wd_day.weekday())
    )
    if not eligible or d not in eligible:
        return 0
    base = weekly // len(eligible)
    rem = weekly % len(eligible)
    idx = eligible.index(d)
    return base + (1 if idx < rem else 0)


def _actual_minutes_for_day(user_id: int, iso_day: str) -> int:
    db = connect()
    try:
        rows = db.execute(
            "SELECT time_in, time_out, break_minutes FROM time_blocks WHERE user_id=? AND day=?",
            (user_id, iso_day),
        ).fetchall()
        total = 0
        for r in rows:
            try:
                total += _minutes_from_hhmm(r["time_out"]) - _minutes_from_hhmm(r["time_in"]) - int(r["break_minutes"] or 0)
            except Exception:
                pass
        if total > 0:
            return max(0, total)
        r = db.execute(
            "SELECT time_in, time_out, break_minutes FROM time_entries WHERE user_id=? AND day=?",
            (user_id, iso_day),
        ).fetchone()
        if r:
            try:
                return max(0, _minutes_from_hhmm(r["time_out"]) - _minutes_from_hhmm(r["time_in"]) - int(r["break_minutes"] or 0))
            except Exception:
                pass
        return 0
    finally:
        db.close()


def _fetch_flextag_ranges(user_id: int) -> list:
    db = connect()
    try:
        rows = db.execute(
            """SELECT a.date_from, a.date_to FROM absences a
               JOIN absence_types t ON t.id=a.type_id
               WHERE a.user_id=? AND t.name='Sonstige'
                 AND LOWER(TRIM(COALESCE(a.comment,'')))='flextag'""",
            (user_id,),
        ).fetchall()
        return [{"date_from": str(r["date_from"])[:10], "date_to": str(r["date_to"])[:10]} for r in rows]
    finally:
        db.close()


def _is_flextag(iso_day: str, flextag_ranges: list) -> bool:
    return any(r["date_from"] <= iso_day <= r["date_to"] for r in flextag_ranges)


def _scheduled_minutes_ignoring_absence(user_id: int, iso_day: str) -> int:
    schedule = _get_user_schedule_for_day(user_id, iso_day)
    if not schedule:
        return 0
    if not _is_workday_for_user(iso_day, schedule):
        return 0
    d = datetime.date.fromisoformat(iso_day)
    col = _WEEKDAY_COLS[d.weekday()] + "_minutes"
    return int(schedule.get(col) or 0)


def _calc_balance_end_at(user_id: int, end_iso: str) -> int:
    d = datetime.date.fromisoformat(end_iso)
    year_start = datetime.date(d.year, 1, 1).isoformat()
    tracking_start = _get_tracking_start(user_id)
    if tracking_start:
        year_start = max(year_start, tracking_start)
    start_minutes = _get_start_balance_minutes(user_id)
    running = int(start_minutes)
    today_iso = datetime.date.today().isoformat()
    flextag_ranges = _fetch_flextag_ranges(user_id)
    for iso in _iter_days(year_start, end_iso):
        expected = int(_expected_minutes_for_day(user_id, iso) or 0)
        actual = int(_actual_minutes_for_day(user_id, iso) or 0)
        flextag_min = 0
        if iso < today_iso and expected == 0 and _is_flextag(iso, flextag_ranges):
            flextag_min = _scheduled_minutes_ignoring_absence(user_id, iso)
        running += int(actual - expected - flextag_min)
    return int(running)


def _get_vacation_year(user_id: int, year: int) -> dict:
    db = connect()
    try:
        r = db.execute(
            "SELECT entitlement_days, carryover_days FROM user_vacation_year WHERE user_id=? AND year=?",
            (user_id, year),
        ).fetchone()
        return {
            "entitlement_days": float(r["entitlement_days"]) if r else 0.0,
            "carryover_days": float(r["carryover_days"]) if r else 0.0,
        }
    except Exception:
        return {"entitlement_days": 0.0, "carryover_days": 0.0}
    finally:
        db.close()


def _vacation_used_days(user_id: int, year: int) -> float:
    db = connect()
    try:
        rows = db.execute(
            """SELECT a.date_from, a.date_to, a.is_half_day
               FROM absences a
               JOIN absence_types t ON t.id=a.type_id
               WHERE a.user_id=? AND SUBSTR(a.date_from,1,4)=?
               AND LOWER(t.name) LIKE '%urlaub%'""",
            (user_id, str(year)),
        ).fetchall()
    finally:
        db.close()
    total = 0.0
    for row in rows:
        if row["is_half_day"]:
            total += 0.5
        else:
            for iso in _iter_days(str(row["date_from"])[:10], str(row["date_to"])[:10]):
                if _is_holiday(iso):
                    continue
                schedule = _get_user_schedule_for_day(user_id, iso)
                if _is_workday_for_user(iso, schedule):
                    total += 1.0
    return total


def _vacation_used_days_started_by(user_id: int, year: int, deadline_iso: str) -> float:
    db = connect()
    try:
        rows = db.execute(
            """SELECT a.date_from, a.date_to, a.is_half_day
               FROM absences a
               JOIN absence_types t ON t.id=a.type_id
               WHERE a.user_id=? AND SUBSTR(a.date_from,1,4)=?
               AND a.date_from<=?
               AND LOWER(t.name) LIKE '%urlaub%'""",
            (user_id, str(year), deadline_iso),
        ).fetchall()
    finally:
        db.close()
    total = 0.0
    for row in rows:
        if row["is_half_day"]:
            total += 0.5
        else:
            for iso in _iter_days(str(row["date_from"])[:10], str(row["date_to"])[:10]):
                if _is_holiday(iso):
                    continue
                schedule = _get_user_schedule_for_day(user_id, iso)
                if _is_workday_for_user(iso, schedule):
                    total += 1.0
    return total


def _get_vacation_carryover_exception(user_id: int) -> int:
    db = connect()
    try:
        r = db.execute(
            "SELECT vacation_carryover_exception FROM users WHERE id=?", (user_id,)
        ).fetchone()
        return int(r["vacation_carryover_exception"] or 0) if r else 0
    finally:
        db.close()


def _get_vacation_carryover_override(user_id: int, year: int):
    db = connect()
    try:
        r = db.execute(
            "SELECT carryover_days FROM vacation_carryover_overrides WHERE user_id=? AND year=?",
            (user_id, year),
        ).fetchone()
        return dict(r) if r else None
    except Exception:
        return None
    finally:
        db.close()


def _vacation_calc(user_id: int, year: int) -> dict:
    today = datetime.date.today()
    vac = _get_vacation_year(user_id, year)
    entitlement = float(vac.get("entitlement_days", 0.0) or 0.0)
    carryover = float(vac.get("carryover_days", 0.0) or 0.0)
    deadline = datetime.date(year, 3, 31)
    deadline_iso = deadline.isoformat()
    deadline_passed = today > deadline
    used_total = float(_vacation_used_days(user_id, year) or 0.0)
    carryover_exception = _get_vacation_carryover_exception(user_id)
    if carryover_exception:
        override = _get_vacation_carryover_override(user_id, year)
        effective_carryover = float(override["carryover_days"]) if override else carryover
    else:
        carryover_started = float(_vacation_used_days_started_by(user_id, year, deadline_iso) or 0.0)
        effective_carryover = min(carryover, carryover_started) if deadline_passed else carryover
    remaining_total = max(0.0, entitlement + effective_carryover - used_total)
    return {
        "entitlement": entitlement,
        "carryover": carryover,
        "effective_carryover": effective_carryover,
        "used_total": used_total,
        "remaining_total": remaining_total,
        "deadline_iso": deadline_iso,
        "deadline_passed": deadline_passed,
    }


def _get_missing_entry_days(user_id: int, year: int) -> list[str]:
    today = datetime.date.today()
    year_start = datetime.date(year, 1, 1).isoformat()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()
    tracking_start = _get_tracking_start(user_id)
    if tracking_start:
        year_start = max(year_start, tracking_start)
    if yesterday < year_start:
        return []
    db = connect()
    try:
        have = {
            str(r["day"])[:10]
            for r in db.execute(
                """SELECT DISTINCT day FROM time_blocks WHERE user_id=? AND day BETWEEN ? AND ?
                   UNION SELECT DISTINCT day FROM time_entries WHERE user_id=? AND day BETWEEN ? AND ?""",
                (user_id, year_start, yesterday, user_id, year_start, yesterday),
            ).fetchall()
        }
        hol = {
            str(r["day"])[:10]
            for r in db.execute(
                "SELECT day FROM calendar_days WHERE day BETWEEN ? AND ? AND is_holiday=1",
                (year_start, yesterday),
            ).fetchall()
        }
        abs_rows = db.execute(
            "SELECT date_from, date_to FROM absences WHERE user_id=? AND date_from<=? AND date_to>=?",
            (user_id, yesterday, year_start),
        ).fetchall()
    finally:
        db.close()
    absent = set()
    for row in abs_rows:
        for iso in _iter_days(str(row["date_from"])[:10], str(row["date_to"])[:10]):
            absent.add(iso)
    missing = []
    for iso in _iter_days(year_start, yesterday):
        if iso in have or iso in hol or iso in absent:
            continue
        schedule = _get_user_schedule_for_day(user_id, iso)
        if _is_workday_for_user(iso, schedule):
            missing.append(iso)
    return sorted(missing)


def _get_contouring_info(user_id: int) -> dict:
    db = connect()
    try:
        r = db.execute(
            "SELECT contouring_enabled, contouring_start_date FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if r:
            return {
                "enabled": int(r["contouring_enabled"]) if r["contouring_enabled"] is not None else 1,
                "start_date": str(r["contouring_start_date"])[:10] if r["contouring_start_date"] else None,
            }
        return {"enabled": 1, "start_date": None}
    finally:
        db.close()


def _get_max_contoured_day(user_id: int) -> "str | None":
    db = connect()
    try:
        r = db.execute(
            "SELECT MAX(day) AS m FROM contoured_days WHERE user_id=?", (user_id,)
        ).fetchone()
        return str(r["m"])[:10] if r and r["m"] else None
    finally:
        db.close()


def _get_uncontoured_days(user_id: int, year: int) -> list[str]:
    ci = _get_contouring_info(user_id)
    if not ci["enabled"]:
        return []
    today = datetime.date.today()
    year_start = datetime.date(year, 1, 1).isoformat()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()
    tracking_start = _get_tracking_start(user_id)
    if tracking_start:
        year_start = max(year_start, tracking_start)
    if ci["start_date"]:
        year_start = max(year_start, ci["start_date"])
    if yesterday < year_start:
        return []
    db = connect()
    try:
        have = {
            str(r["day"])[:10]
            for r in db.execute(
                """SELECT DISTINCT day FROM time_blocks WHERE user_id=? AND day BETWEEN ? AND ?
                   UNION SELECT DISTINCT day FROM time_entries WHERE user_id=? AND day BETWEEN ? AND ?""",
                (user_id, year_start, yesterday, user_id, year_start, yesterday),
            ).fetchall()
        }
        contoured = {
            str(r["day"])[:10]
            for r in db.execute(
                "SELECT day FROM contoured_days WHERE user_id=? AND day BETWEEN ? AND ?",
                (user_id, year_start, yesterday),
            ).fetchall()
        }
    finally:
        db.close()
    return sorted(d for d in have if d not in contoured)


# ── Write helpers ─────────────────────────────────────────────────────────────

def _is_day_locked(user_id: int, iso_day: str) -> bool:
    year = int(iso_day[:4])
    month = int(iso_day[5:7])
    db = connect()
    try:
        r = db.execute(
            "SELECT id FROM period_locks WHERE user_id=? AND period_type='year' AND year=?",
            (user_id, year),
        ).fetchone()
        if r:
            return True
        r = db.execute(
            "SELECT id FROM period_locks WHERE user_id=? AND period_type='month' AND year=? AND month=?",
            (user_id, year, month),
        ).fetchone()
        return r is not None
    finally:
        db.close()


def _calc_auto_break(user_id: int, time_in_str: str, time_out_str: str) -> int:
    """Return auto-break minutes based on user preference and span (mirrors app.py logic).

    Rules (only when auto_breaks pref enabled):
    - span > 9h30 → 45 min
    - span > 6h   → 30 min
    - otherwise   → 0
    """
    try:
        db = connect()
        try:
            r = db.execute("SELECT auto_breaks FROM user_prefs WHERE user_id=?", (user_id,)).fetchone()
            enabled = bool(int(r["auto_breaks"])) if r else False
        finally:
            db.close()
    except Exception:
        return 0
    if not enabled:
        logger.debug("auto_break: user_id=%s auto_breaks disabled", user_id)
        return 0
    span = _minutes_from_hhmm(time_out_str) - _minutes_from_hhmm(time_in_str)
    brk = 45 if span > 9 * 60 + 30 else (30 if span > 6 * 60 else 0)
    logger.info("auto_break: user_id=%s span=%dmin → %dmin Pause", user_id, span, brk)
    return brk


def _do_insert_time_block(
    user_id: int, day: str, time_in: str, time_out: str, break_minutes: int, break_auto: bool = False
) -> str:
    try:
        db = connect()
        try:
            db.execute(
                "INSERT INTO time_blocks(user_id, day, time_in, time_out, break_minutes, created_at) "
                "VALUES(?,?,?,?,?,datetime('now'))",
                (user_id, day, time_in, time_out, break_minutes),
            )
            db.commit()
        finally:
            db.close()
        d = datetime.date.fromisoformat(day)
        wd = _WEEKDAY_DE[d.weekday()]
        mins = _minutes_from_hhmm(time_out) - _minutes_from_hhmm(time_in) - break_minutes
        pause_line = ""
        if break_minutes:
            label = "(automatisch)" if break_auto else "(manuell)"
            pause_line = f"\n☕ Pause: {break_minutes} Min {label}"
        return f"✅ Eingetragen: {wd} {_fmt_date_de(day)}\n⏰ {time_in} – {time_out} ({_fmt_minutes(mins)} Std){pause_line}"
    except Exception as e:
        return f"❌ Konnte nicht eingetragen werden: {e}"


def _do_insert_absence(user_id: int, absence_type: str, date_from: str, date_to: str) -> str:
    try:
        db = connect()
        try:
            overlap = db.execute(
                "SELECT id FROM absences WHERE user_id=? AND date_from<=? AND date_to>=?",
                (user_id, date_to, date_from),
            ).fetchone()
        finally:
            db.close()
        if overlap:
            return (
                f"⚠️ Es gibt bereits eine Abwesenheit im Zeitraum "
                f"{_fmt_date_de(date_from)} – {_fmt_date_de(date_to)}."
            )
        _sonstige = {"Flextag", "Verdi"}
        if absence_type in _sonstige:
            lookup_name = "Sonstige"
            comment = absence_type
        else:
            lookup_name = absence_type
            comment = None
        db = connect()
        try:
            r = db.execute(
                "SELECT id FROM absence_types WHERE name=?", (lookup_name,)
            ).fetchone()
            if not r:
                return f"❌ Abwesenheitstyp '{lookup_name}' nicht gefunden."
            type_id = int(r["id"])
            db.execute(
                "INSERT INTO absences(user_id, type_id, date_from, date_to, is_half_day, comment, created_at) "
                "VALUES(?,?,?,?,0,?,datetime('now'))",
                (user_id, type_id, date_from, date_to, comment),
            )
            db.commit()
        finally:
            db.close()
        return f"✅ Eingetragen: {absence_type}\n📅 {_fmt_date_de(date_from)} – {_fmt_date_de(date_to)}"
    except Exception as e:
        return f"❌ Konnte nicht eingetragen werden: {e}"


def _do_insert_business_trip(user_id: int, day: str, destination: str) -> str:
    try:
        db = connect()
        try:
            db.execute(
                "INSERT OR IGNORE INTO business_trips"
                "(user_id, start_date, end_date, destination, created_at) "
                "VALUES(?,?,?,?,datetime('now'))",
                (user_id, day, day, destination),
            )
            db.commit()
        finally:
            db.close()
        return f"✅ Dienstreise eingetragen: {_fmt_date_de(day)}\n📍 {destination}"
    except Exception as e:
        return f"❌ Konnte nicht eingetragen werden: {e}"


# ── NLP parsing ───────────────────────────────────────────────────────────────

def _clean_json(raw: str) -> str:
    """Entferne Markdown-Backticks und führende/nachfolgende Leerzeichen."""
    raw = raw.strip()
    # Entferne ```json ... ``` oder ``` ... ```
    if raw.startswith("```"):
        lines = raw.split("\n")
        # erste Zeile (```json oder ```) und letzte Zeile (```) entfernen
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        raw = "\n".join(inner).strip()
    return raw


def _parse_nlp(text: str) -> "list | None":
    today = datetime.date.today()
    today_iso = today.isoformat()
    tomorrow_iso = (today + datetime.timedelta(days=1)).isoformat()
    yesterday_iso = (today - datetime.timedelta(days=1)).isoformat()

    system_prompt = (
        f"Du bist ein Parser für eine Zeiterfassungs-App.\n"
        f"Heute ist {today_iso} ({today.strftime('%A')}).\n"
        f"Morgen ist {tomorrow_iso}, gestern war {yesterday_iso}.\n\n"
        "Extrahiere aus dem Text ALLE Aktionen und antworte NUR mit einem JSON-Array.\n"
        "KEINE Erklärungen, KEINE Markdown-Backticks, NUR das JSON-Array.\n\n"
        "Aktionstypen:\n"
        "[1] Zeiteintrag:\n"
        '  {"action": "time", "date": "YYYY-MM-DD", "time_in": "HH:MM", "time_out": "HH:MM", "break_minutes": 0}\n'
        "[2] Abwesenheit (Urlaub / Krank / Flextag):\n"
        '  {"action": "absence", "type": "Urlaub", "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"}\n\n'
        "Parsing-Regeln:\n"
        "- 'heute', 'jetzt' → " + today_iso + "\n"
        "- 'morgen' → " + tomorrow_iso + "\n"
        "- 'gestern' → " + yesterday_iso + "\n"
        "- Trennzeichen zwischen Daten: 'bis', '-', '–', 'bis zum'\n"
        "- Uhrzeiten auf 15 Minuten runden: 6→06:00, 6:10→06:15, 7:30→07:30, 12→12:00\n"
        "- 'bis 12' oder 'bis 12 Uhr' → time_out: '12:00'\n"
        "- Fehlendes Bis-Datum bei Abwesenheit → date_to = date_from\n"
        "- Typ 'Flextag' → type: 'Flextag'\n"
        "- Datumsformat im Text: TT.MM. oder TT.MM.JJJJ → in YYYY-MM-DD umwandeln\n"
        "- Jahr fehlt → aktuelles Jahr annehmen\n"
        "- Wenn Text nicht verständlich → leeres Array []\n\n"
        "Beispiele (ersetze DATUM durch " + today_iso + "):\n"
        "- Heute von 6 bis 10 gearbeitet\n"
        "- Am 6.5. von 7:30 bis 12\n"
        "- Urlaub vom 7.6. bis 20.6.\n"
        "- Urlaub 7.6.-20.6.\n"
        "- Am 3.8. Flextag\n"
        "- Krank von 10.6. bis 12.6."
    )

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": text}],
        )
        raw = response.content[0].text.strip()
        logger.info("NLP raw response: %s", raw)
        raw = _clean_json(raw)
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            # Leeres Array = nicht verstanden
            if not parsed:
                return None
            return parsed
        # Einzelnes Objekt in Liste wrappen
        if isinstance(parsed, dict):
            return [parsed]
        return None
    except json.JSONDecodeError as e:
        logger.error("NLP JSON parse error: %s | raw: %s", e, raw)
        return None
    except Exception as e:
        logger.error("NLP error: %s", e)
        return None


async def _execute_actions(
    actions: list,
    uid: int,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    for action in actions:
        act = action.get("action")

        if act == "time":
            day = action.get("date", "")
            time_in = action.get("time_in", "")
            time_out = action.get("time_out", "")
            break_minutes = int(action.get("break_minutes") or 0)
            explicit_break = break_minutes > 0
            break_auto = False
            if not explicit_break:
                auto_brk = _calc_auto_break(uid, time_in, time_out)
                if auto_brk:
                    break_minutes = auto_brk
                    break_auto = True

            if not day or not time_in or not time_out:
                await update.message.reply_text(f"❌ Konnte nicht eingetragen werden: Unvollständige Zeitangaben.")
                continue

            if _is_day_locked(uid, day):
                d = datetime.date.fromisoformat(day)
                await update.message.reply_text(
                    f"❌ {_WEEKDAY_DE[d.weekday()]} {_fmt_date_de(day)} ist gesperrt."
                )
                continue

            db = connect()
            try:
                existing = db.execute(
                    "SELECT id FROM time_blocks WHERE user_id=? AND day=?",
                    (uid, day),
                ).fetchone()
            finally:
                db.close()

            if existing:
                context.user_data["pending_confirm"] = {
                    "action": "time",
                    "user_id": uid,
                    "day": day,
                    "time_in": time_in,
                    "time_out": time_out,
                    "break_minutes": break_minutes,
                    "break_auto": break_auto,
                }
                d = datetime.date.fromisoformat(day)
                wd = _WEEKDAY_DE[d.weekday()]
                await update.message.reply_text(
                    f"⚠️ Am {wd} {_fmt_date_de(day)} gibt es bereits einen Eintrag. "
                    f"Trotzdem eintragen? (ja/nein)"
                )
            else:
                result = _do_insert_time_block(uid, day, time_in, time_out, break_minutes, break_auto)
                await update.message.reply_text(result)

        elif act == "absence":
            absence_type = action.get("type", "")
            date_from = action.get("date_from", "")
            date_to = action.get("date_to", "") or date_from

            if not absence_type or not date_from:
                await update.message.reply_text("❌ Konnte nicht eingetragen werden: Unvollständige Abwesenheitsangaben.")
                continue

            result = _do_insert_absence(uid, absence_type, date_from, date_to)
            await update.message.reply_text(result)

        else:
            await update.message.reply_text(NLP_EXAMPLES)


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _is_authorized(telegram_id: int) -> bool:
    if telegram_id in ADMIN_IDS:
        return True
    db = connect()
    try:
        r = db.execute(
            "SELECT id FROM telegram_users WHERE telegram_id=?",
            (telegram_id,)
        ).fetchone()
        return r is not None
    finally:
        db.close()


async def _check_auth(
    update: Update, context: "ContextTypes.DEFAULT_TYPE | None" = None
) -> "tuple[bool, int|None]":
    tid = update.effective_user.id
    if not _is_authorized(tid):
        await update.message.reply_text("Kein Zugriff. Bitte Admin kontaktieren.")
        return False, None
    own_uid = _get_user_id(tid)
    if own_uid is None:
        await update.message.reply_text(
            "Kein Benutzer verknüpft. Bitte Admin kontaktieren.\n"
            f"Deine Telegram-ID: {tid}"
        )
        return False, None
    if context is not None and tid in ADMIN_IDS:
        ctx_uid = context.user_data.get("context_uid")
        if ctx_uid is not None:
            return True, ctx_uid
    return True, own_uid


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    if not _is_authorized(tid):
        await update.message.reply_text("Kein Zugriff. Bitte Admin kontaktieren.")
        return
    is_admin = tid in ADMIN_IDS
    text = (
        "👋 *Zeiterfassung Bot*\n\n"
        "*Freitext-Eingabe:*\n"
        "Schreib einfach was du gemacht hast, z.B.:\n"
        "_Heute von 8 bis 16 Uhr gearbeitet_\n"
        "_Urlaub vom 1.7. bis 15.7._\n\n"
        "*Befehle:*\n"
        "/saldo — Aktuelles Gleitzeitkonto\n"
        "/urlaub — Urlaubsübersicht\n"
        "/heute — Heutige Zeiteinträge\n"
        "/fehlend — Fehlende Einträge\n"
        "/kontierung — Kontierungsübersicht\n"
        "/bericht — Gleitzeitkonto Monatsübersicht\n"
        "/bericht jahr — Gleitzeitkonto ganzes Jahr\n"
        "/abwesenheiten — Abwesenheitsliste aktuelles Jahr\n"
        "/user — Aktiver Benutzer\n"
        "\n*Abend-Erinnerung:*\n"
        "Schreib _erinnerung_ (Status), _erinnerung an_, _erinnerung aus_ oder _erinnerung 19:30_\n"
    )
    if is_admin:
        text += (
            "\n*Admin-Befehle:*\n"
            "/als <username> — Kontext wechseln\n"
            "/als ich — Eigenen Kontext wiederherstellen\n"
            "/users — Alle Benutzer\n"
            "/alssaldo <username> — Saldo eines Users\n"
            "/alsurlaub <username> — Urlaub eines Users\n"
            "/alsabw <username> — Abwesenheiten eines Users\n"
            "/testwizard [username] — Wizard sofort testen\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok, uid = await _check_auth(update, context)
    if not ok:
        return
    today = datetime.date.today().isoformat()
    mins = _calc_balance_end_at(uid, today)
    sign = "✅" if mins >= 0 else "⚠️"
    u = _get_user_row(uid)
    name = (u["display_name"] or u["username"]) if u else f"ID {uid}"
    await update.message.reply_text(
        f"{sign} *Gleitzeitkonto – {name}*\n\nStand {_fmt_date_de(today)}: *{_fmt_minutes_signed(mins)}*",
        parse_mode="Markdown",
    )


async def cmd_urlaub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok, uid = await _check_auth(update, context)
    if not ok:
        return
    year = datetime.date.today().year
    vc = _vacation_calc(uid, year)
    u = _get_user_row(uid)
    name = (u["display_name"] or u["username"]) if u else f"ID {uid}"
    lines = [f"🏖️ *Urlaubsübersicht {year} – {name}*\n"]
    lines.append(f"Anspruch: *{vc['entitlement']:.1f}* Tage")
    if vc["effective_carryover"] > 0:
        lines.append(f"Übertrag: *{vc['effective_carryover']:.1f}* Tage")
    lines.append(f"Genommen: *{vc['used_total']:.1f}* Tage")
    lines.append(f"Verfügbar: *{vc['remaining_total']:.1f}* Tage")
    if not vc["deadline_passed"] and vc["carryover"] > 0:
        lines.append(f"\n⚠️ Übertrag verfällt am {_fmt_date_de(vc['deadline_iso'])}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_heute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok, uid = await _check_auth(update, context)
    if not ok:
        return
    today = datetime.date.today().isoformat()
    db = connect()
    try:
        blocks = db.execute(
            "SELECT time_in, time_out, break_minutes, comment FROM time_blocks "
            "WHERE user_id=? AND day=? ORDER BY time_in",
            (uid, today),
        ).fetchall()
    finally:
        db.close()
    actual = _actual_minutes_for_day(uid, today)
    expected = _expected_minutes_for_day(uid, today)
    delta = actual - expected
    lines = [f"📅 *Heute – {_fmt_date_de(today)}*\n"]
    if blocks:
        for b in blocks:
            br = f" (Pause {b['break_minutes']} min)" if b["break_minutes"] else ""
            cmt = f" – {b['comment']}" if b["comment"] else ""
            lines.append(f"• {b['time_in']}–{b['time_out']}{br}{cmt}")
        lines.append(f"\nGearbeitet: *{_fmt_minutes(actual)}*")
        lines.append(f"Soll: *{_fmt_minutes(expected)}*")
        lines.append(f"Tagessaldo: *{_fmt_minutes_signed(delta)}*")
    else:
        lines.append("Keine Einträge für heute.")
        if expected > 0:
            lines.append(f"Soll: *{_fmt_minutes(expected)}*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_fehlend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok, uid = await _check_auth(update, context)
    if not ok:
        return
    year = datetime.date.today().year
    missing = _get_missing_entry_days(uid, year)
    count = len(missing)
    sign = "✅" if count == 0 else "⚠️"
    lines = [f"{sign} *Fehlende Einträge {year}*\n"]
    lines.append(f"Anzahl: *{count}*")
    if missing:
        lines.append("\nLetzte 5 fehlende Tage:")
        for d in missing[-5:]:
            lines.append(f"• {_fmt_date_de(d)}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_kontierung(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok, uid = await _check_auth(update, context)
    if not ok:
        return
    year = datetime.date.today().year
    ci = _get_contouring_info(uid)
    if not ci["enabled"]:
        await update.message.reply_text("Kontierung ist für diesen Account deaktiviert.")
        return
    unc = _get_uncontoured_days(uid, year)
    count = len(unc)
    max_day = _get_max_contoured_day(uid)
    sign = "✅" if count == 0 else "⚠️"
    lines = [f"{sign} *Kontierung {year}*\n"]
    lines.append(f"Unkontierte Tage: *{count}*")
    if max_day:
        lines.append(f"Kontiert bis: *{_fmt_date_de(max_day)}*")
    else:
        lines.append("Noch keine Kontierung.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")




def _rtf_escape(text: str) -> str:
    umlaut_map = {
        '\xe4': r"\'e4", '\xf6': r"\'f6", '\xfc': r"\'fc",
        '\xc4': r"\'c4", '\xd6': r"\'d6", '\xdc': r"\'dc",
        '\xdf': r"\'df",
        '\\': '\\\\', '{': '\\{', '}': '\\}',
    }
    result = []
    for ch in text:
        if ch in umlaut_map:
            result.append(umlaut_map[ch])
        elif ord(ch) > 127:
            result.append(f'\\u{ord(ch)}?')
        else:
            result.append(ch)
    return ''.join(result)


def _rtf_signed(mins: int) -> str:
    if mins > 0:
        return '{\\cf1 +' + f'{mins // 60:02d}:{mins % 60:02d}' + '}'
    elif mins < 0:
        m = abs(mins)
        return '{\\cf2 -' + f'{m // 60:02d}:{m % 60:02d}' + '}'
    else:
        return '+00:00'


def _count_working_days(uid: int, date_from: str, date_to: str, is_half_day: bool) -> float:
    if is_half_day:
        return 0.5
    total = 0.0
    for iso in _iter_days(date_from, date_to):
        if _is_holiday(iso):
            continue
        schedule = _get_user_schedule_for_day(uid, iso)
        if _is_workday_for_user(iso, schedule):
            total += 1.0
    return total


def _fmt_days(d: float) -> str:
    if d == 1.0:
        return "1 Tag"
    elif d == int(d):
        return f"{int(d)} Tage"
    else:
        return f"{d:.1f} Tage"


def _get_abwesenheiten_liste(uid: int, year: int) -> str:
    db = connect()
    try:
        rows = db.execute(
            """SELECT a.date_from, a.date_to, a.is_half_day, a.comment, t.name AS typ
               FROM absences a
               JOIN absence_types t ON t.id = a.type_id
               WHERE a.user_id = ? AND SUBSTR(a.date_from, 1, 4) = ?
               ORDER BY a.date_from ASC""",
            (uid, str(year))
        ).fetchall()
    finally:
        db.close()

    if not rows:
        return f"Keine Abwesenheiten f\xfcr {year}."

    groups: dict[str, list] = {}
    for row in rows:
        typ = row["typ"]
        cmt = (row["comment"] or "").strip()
        if "urlaub" in typ.lower():
            grp = "Urlaub"
        elif "krank" in typ.lower():
            grp = "Krank"
        elif typ == "Sonstige" and cmt.lower() == "flextag":
            grp = "Flextag"
        elif typ == "Sonstige" and cmt:
            grp = cmt
        else:
            grp = typ
        date_from = str(row["date_from"])[:10]
        date_to = str(row["date_to"])[:10]
        days = _count_working_days(uid, date_from, date_to, bool(row["is_half_day"]))
        groups.setdefault(grp, []).append({
            "date_from": date_from, "date_to": date_to,
            "is_half_day": bool(row["is_half_day"]), "days": days,
        })

    lines = []
    totals: dict[str, float] = {}
    for grp, entries in groups.items():
        total = sum(e["days"] for e in entries)
        totals[grp] = total
        lines.append(f"\n*{grp.upper()}* ({_fmt_days(total)})")
        for e in entries:
            df = datetime.date.fromisoformat(e["date_from"])
            dt = datetime.date.fromisoformat(e["date_to"])
            df_s = f"{df.day:02d}.{df.month:02d}."
            dt_s = f"{dt.day:02d}.{dt.month:02d}."
            if e["is_half_day"]:
                lines.append(f"  {df_s} | halber Tag")
            elif e["date_from"] == e["date_to"]:
                lines.append(f"  {df_s} | {_fmt_days(e['days'])}")
            else:
                lines.append(f"  {df_s} - {dt_s} | {_fmt_days(e['days'])}")

    summary = " | ".join(
        f"{grp} {int(v) if v == int(v) else f'{v:.1f}'}" for grp, v in totals.items()
    )
    lines.append(f"\n*Gesamt:* {summary}")
    return "\n".join(lines)


def _build_liste(uid: int, year: int, month: "int | None") -> tuple:
    """Erstellt Gleitzeitkonto-Liste. Returns (content, filename, is_rtf)."""
    today = datetime.date.today()
    today_iso = today.isoformat()

    if month:
        import calendar as cal_mod
        last_day = cal_mod.monthrange(year, month)[1]
        start_iso = f"{year}-{month:02d}-01"
        end_iso = f"{year}-{month:02d}-{last_day:02d}"
        titel = f"{_MONTH_DE[month-1]} {year}"
    else:
        start_iso = f"{year}-01-01"
        end_iso = f"{year}-12-31"
        titel = f"Jahr {year}"

    tracking_start = _get_tracking_start(uid)
    if tracking_start:
        start_iso = max(start_iso, tracking_start)

    end_iso = min(end_iso, today_iso)

    if start_iso > end_iso:
        return (f"Keine Daten f\xfcr {titel}.", "", False)

    year_start = f"{year}-01-01"
    if tracking_start:
        year_start = max(year_start, tracking_start)

    start_balance = _get_start_balance_minutes(uid)
    running = int(start_balance)
    flextag_ranges = _fetch_flextag_ranges(uid)

    if year_start < start_iso:
        for iso in _iter_days(year_start, (datetime.date.fromisoformat(start_iso) - datetime.timedelta(days=1)).isoformat()):
            exp = int(_expected_minutes_for_day(uid, iso) or 0)
            act = int(_actual_minutes_for_day(uid, iso) or 0)
            ft = _scheduled_minutes_ignoring_absence(uid, iso) if (iso < today_iso and exp == 0 and _is_flextag(iso, flextag_ranges)) else 0
            running += act - exp - ft

    db = connect()
    try:
        abs_rows = db.execute(
            """SELECT a.date_from, a.date_to, t.name as typ, a.comment
               FROM absences a JOIN absence_types t ON t.id=a.type_id
               WHERE a.user_id=? AND a.date_from<=? AND a.date_to>=?""",
            (uid, end_iso, start_iso)
        ).fetchall()
        trip_rows = db.execute(
            "SELECT start_date, end_date, destination FROM business_trips "
            "WHERE user_id=? AND start_date<=? AND COALESCE(end_date,start_date)>=?",
            (uid, end_iso, start_iso)
        ).fetchall()
        block_rows = db.execute(
            "SELECT day, time_in, time_out, break_minutes FROM time_blocks "
            "WHERE user_id=? AND day BETWEEN ? AND ? ORDER BY day, time_in",
            (uid, start_iso, end_iso)
        ).fetchall()
    finally:
        db.close()

    abs_map: dict[str, str] = {}
    for row in abs_rows:
        for iso in _iter_days(str(row["date_from"])[:10], str(row["date_to"])[:10]):
            typ = row["typ"]
            cmt = row["comment"] or ""
            abs_map[iso] = cmt if (typ == "Sonstige" and cmt) else typ

    trip_map: dict[str, str] = {}
    for row in trip_rows:
        t_start = str(row["start_date"])[:10]
        t_end = str(row["end_date"])[:10] if row["end_date"] else t_start
        for iso in _iter_days(t_start, t_end):
            trip_map[iso] = str(row["destination"] or "")

    blocks_by_day: dict[str, list] = {}
    for row in block_rows:
        blocks_by_day.setdefault(str(row["day"])[:10], []).append(row)

    start_running = running

    # Collect rows: one entry per time block (multiple per day if needed)
    day_rows = []
    for iso in _iter_days(start_iso, end_iso):
        exp = int(_expected_minutes_for_day(uid, iso) or 0)
        act = int(_actual_minutes_for_day(uid, iso) or 0)
        ft = _scheduled_minutes_ignoring_absence(uid, iso) if (iso < today_iso and exp == 0 and _is_flextag(iso, flextag_ranges)) else 0
        delta = act - exp - ft
        running += delta

        d = datetime.date.fromisoformat(iso)
        wd = d.weekday()
        is_hol = _is_holiday(iso)
        is_weekend = wd >= 5

        if is_weekend and act == 0 and exp == 0:
            continue
        if is_hol and act == 0 and exp == 0:
            continue

        tag = _WEEKDAY_SHORT[wd]
        datum = f"{d.day:02d}.{d.month:02d}."
        bemerkung = abs_map.get(iso) or (f"✈ {trip_map[iso]}" if iso in trip_map else ("Feiertag" if is_hol else ""))
        day_blocks = blocks_by_day.get(iso, [])

        if act > 0 and day_blocks:
            total_brk = sum(int(blk["break_minutes"] or 0) for blk in day_blocks)
            first_in = str(day_blocks[0]["time_in"] or "")[:5]
            last_out = str(day_blocks[-1]["time_out"] or "")[:5]
            for i, blk in enumerate(day_blocks):
                zeit = f"{str(blk['time_in'] or '')[:5]}-{str(blk['time_out'] or '')[:5]}"
                if i == 0:
                    day_rows.append({
                        'tag': tag, 'datum': datum,
                        'zeit': f"{first_in}-{last_out}",
                        'pause': str(total_brk) if total_brk else '',
                        'ist': _fmt_minutes(act),
                        'exp': exp, 'act': act, 'delta': delta, 'running': running,
                        'is_hol': is_hol, 'is_weekend': is_weekend, 'is_first': True,
                    })
                else:
                    day_rows.append({
                        'tag': '', 'datum': '', 'zeit': zeit,
                        'pause': '', 'ist': '',
                        'exp': 0, 'act': 0, 'delta': None, 'running': None,
                        'is_hol': is_hol, 'is_weekend': is_weekend, 'is_first': False,
                    })
        elif act > 0:
            day_rows.append({
                'tag': tag, 'datum': datum, 'zeit': _fmt_minutes(act),
                'pause': '', 'ist': _fmt_minutes(act),
                'exp': exp, 'act': act, 'delta': delta, 'running': running,
                'is_hol': is_hol, 'is_weekend': is_weekend, 'is_first': True,
            })
        else:
            day_rows.append({
                'tag': tag, 'datum': datum, 'zeit': bemerkung if bemerkung else "-",
                'pause': '', 'ist': '',
                'exp': exp, 'act': act, 'delta': delta, 'running': running,
                'is_hol': is_hol, 'is_weekend': is_weekend, 'is_first': True,
            })

    end_running = running

    # Build markdown
    md_lines = [f"📊 *Gleitzeitkonto – {titel}*", f"Startsaldo: *{_fmt_minutes_signed(start_running)}*", ""]
    for row in day_rows:
        if not row['is_first']:
            md_lines.append(f"`         ` {row['zeit']}")
            continue
        delta = row['delta']
        exp = row['exp']
        act = row['act']
        delta_str = _fmt_minutes_signed(delta) if (exp > 0 or act > 0) else ""
        saldo_str = _fmt_minutes_signed(row['running'])
        line = f"`{row['tag']} {row['datum']}` {row['zeit']}"
        if delta_str and delta_str != "+00:00":
            line += f" | {delta_str}"
        line += f" | *{saldo_str}*"
        md_lines.append(line)
    md_lines += ["", f"*Endsaldo: {_fmt_minutes_signed(end_running)}*"]
    md_text = "\n".join(md_lines)

    if len(md_text) <= 3500:
        return (md_text, "", False)

    # Build RTF
    rtf = []
    rtf.append(r'{\rtf1\ansi\ansicpg1252\deff0')
    rtf.append(r'{\fonttbl{\f0\fmodern\fcharset0 Courier New;}}')
    rtf.append(r'{\colortbl;\red0\green128\blue0;\red200\green0\blue0;\red160\green160\blue160;}')
    rtf.append(r'\f0\fs18')
    rtf.append(r'\pard\tx2200\tx4200\tx5400\tx6800\tx7800\tx9000\tx10400')
    rtf.append(_rtf_escape(f'Gleitzeitkonto – {titel}') + r'\line')
    rtf.append('Startsaldo: ' + _rtf_signed(start_running) + r'\line')
    rtf.append(r'\line')

    for row in day_rows:
        zeit_r = _rtf_escape(row['zeit'])
        pause_r = _rtf_escape(row.get('pause') or '')
        ist_r = _rtf_escape(row.get('ist') or '')
        if not row['is_first']:
            # Subsequent block: only time column filled
            if row['is_weekend'] or row['is_hol']:
                rtf_line = r'\tab ' + '{\\cf3 ' + zeit_r + '}' + r'\tab \tab \tab \tab \tab \tab \line'
            else:
                rtf_line = r'\tab ' + zeit_r + r'\tab \tab \tab \tab \tab \tab \line'
            rtf.append(rtf_line)
            continue

        delta = row['delta']
        exp = row['exp']
        act = row['act']
        tag_r = _rtf_escape(row['tag'])
        datum_r = row['datum']
        soll_str = _fmt_minutes(exp) if exp > 0 else ''
        delta_rtf = _rtf_signed(delta) if (exp > 0 or act > 0) else ''
        saldo_rtf = _rtf_signed(row['running']) if row['running'] is not None else ''

        if row['is_weekend'] or row['is_hol']:
            rtf_line = (
                '{\\cf3 ' + tag_r + ' ' + datum_r + '}' + r'\tab '
                + '{\\cf3 ' + zeit_r + '}' + r'\tab '
                + '{\\cf3 ' + pause_r + '}' + r'\tab '
                + '{\\cf3 ' + ist_r + '}' + r'\tab '
                + '{\\cf3 ' + soll_str + '}' + r'\tab '
                + delta_rtf + r'\tab '
                + saldo_rtf + r'\line'
            )
        else:
            rtf_line = (
                tag_r + ' ' + datum_r + r'\tab '
                + zeit_r + r'\tab '
                + pause_r + r'\tab '
                + ist_r + r'\tab '
                + soll_str + r'\tab '
                + delta_rtf + r'\tab '
                + saldo_rtf + r'\line'
            )
        rtf.append(rtf_line)

    rtf.append(r'\line')
    rtf.append(_rtf_escape('Endsaldo: ') + _rtf_signed(end_running))
    rtf.append(r'\par}')

    rtf_content = '\n'.join(rtf)
    fname = f"gleitzeitkonto_{month:02d}_{year}.rtf" if month else f"gleitzeitkonto_{year}.rtf"
    return (rtf_content, fname, True)




async def cmd_bericht(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /bericht          → aktueller Monat
    /bericht jahr     → ganzes Jahr
    /bericht 5        → Mai aktuelles Jahr
    /bericht 5 2026   → Mai 2026
    """
    ok, uid = await _check_auth(update, context)
    if not ok:
        return

    today = datetime.date.today()
    year = today.year
    month = today.month

    args = context.args or []
    if args:
        if args[0].lower() in ("jahr", "year", "all", "alles"):
            month = None
        else:
            try:
                month = int(args[0])
                if not 1 <= month <= 12:
                    await update.message.reply_text("❌ Ungültiger Monat (1-12)")
                    return
            except ValueError:
                await update.message.reply_text(
                    "Verwendung:\n"
                    "/bericht — aktueller Monat\n"
                    "/bericht jahr — ganzes Jahr\n"
                    "/bericht 5 — Mai\n"
                )
                return
        if len(args) >= 2:
            try:
                year = int(args[1])
            except ValueError:
                pass

    await update.message.reply_text("⏳ Berechne...")
    content, fname, is_rtf = _build_liste(uid, year, month)

    if not is_rtf:
        await update.message.reply_text(content, parse_mode="Markdown")
    else:
        buf = io.BytesIO(content.encode("latin-1", errors="replace"))
        titel = f"{_MONTH_DE[month-1]} {year}" if month else f"Jahr {year}"
        await update.message.reply_document(
            document=buf,
            filename=fname,
            caption=f"📊 Gleitzeitkonto {titel}",
        )

async def cmd_abwesenheiten(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok, uid = await _check_auth(update, context)
    if not ok:
        return
    year = datetime.date.today().year
    args = context.args or []
    if args:
        try:
            year = int(args[0])
        except ValueError:
            await update.message.reply_text("Verwendung: /abwesenheiten [Jahr]")
            return
    u = _get_user_row(uid)
    name = (u["display_name"] or u["username"]) if u else f"ID {uid}"
    header = f"📋 *Abwesenheiten {year} – {name}*"
    body = _get_abwesenheiten_liste(uid, year)
    await update.message.reply_text(f"{header}\n{body}", parse_mode="Markdown")


async def cmd_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    if not _is_authorized(tid):
        await update.message.reply_text("Kein Zugriff. Bitte Admin kontaktieren.")
        return
    own_uid = _get_user_id(tid)
    if own_uid is None:
        await update.message.reply_text(f"Kein Benutzer verknüpft.\nDeine Telegram-ID: {tid}")
        return
    u = _get_user_row(own_uid)
    own_name = (u["display_name"] or u["username"]) if u else f"ID {own_uid}"
    if tid in ADMIN_IDS:
        ctx_uid = context.user_data.get("context_uid")
        if ctx_uid is not None and ctx_uid != own_uid:
            ctx_u = _get_user_row(ctx_uid)
            ctx_name = (ctx_u["display_name"] or ctx_u["username"]) if ctx_u else f"ID {ctx_uid}"
            await update.message.reply_text(
                f"👤 Eigener Account: *{own_name}*\n"
                f"👥 Aktiver Kontext: *{ctx_name}*",
                parse_mode="Markdown",
            )
            return
    await update.message.reply_text(f"👤 Aktiver Benutzer: *{own_name}*", parse_mode="Markdown")


# ── Admin commands ────────────────────────────────────────────────────────────

async def cmd_als(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    if tid not in ADMIN_IDS:
        await update.message.reply_text("Kein Zugriff.")
        return
    if not context.args:
        await update.message.reply_text("Verwendung: /als <username> oder /als ich")
        return
    arg = context.args[0]
    if arg.lower() == "ich":
        context.user_data.pop("context_uid", None)
        own_uid = _get_user_id(tid)
        u = _get_user_row(own_uid) if own_uid else None
        name = (u["display_name"] or u["username"]) if u else "eigener Account"
        await update.message.reply_text(
            f"👤 Kontext zurückgesetzt auf: *{name}*", parse_mode="Markdown"
        )
        return
    u = _get_user_by_username(arg)
    if not u:
        await update.message.reply_text(f"Benutzer '{arg}' nicht gefunden.")
        return
    context.user_data["context_uid"] = u["id"]
    name = u["display_name"] or u["username"]
    await update.message.reply_text(
        f"👤 Kontext gewechselt zu: *{name}*", parse_mode="Markdown"
    )


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    if tid not in ADMIN_IDS:
        await update.message.reply_text("Kein Zugriff.")
        return
    users = _all_users()
    if not users:
        await update.message.reply_text("Keine Benutzer gefunden.")
        return
    lines = ["👥 *Alle Benutzer:*\n"]
    for u in users:
        name = u["display_name"] or ""
        lines.append(f"• `{u['username']}`" + (f" – {name}" if name else ""))
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_alssaldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    if tid not in ADMIN_IDS:
        await update.message.reply_text("Kein Zugriff.")
        return
    if not context.args:
        await update.message.reply_text("Verwendung: /alssaldo <username>")
        return
    u = _get_user_by_username(context.args[0])
    if not u:
        await update.message.reply_text(f"Benutzer '{context.args[0]}' nicht gefunden.")
        return
    today = datetime.date.today().isoformat()
    mins = _calc_balance_end_at(u["id"], today)
    sign = "✅" if mins >= 0 else "⚠️"
    name = u["display_name"] or u["username"]
    await update.message.reply_text(
        f"{sign} *Gleitzeitkonto – {name}*\n\nStand {_fmt_date_de(today)}: *{_fmt_minutes_signed(mins)}*",
        parse_mode="Markdown",
    )


async def cmd_alsurlaub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    if tid not in ADMIN_IDS:
        await update.message.reply_text("Kein Zugriff.")
        return
    if not context.args:
        await update.message.reply_text("Verwendung: /alsurlaub <username>")
        return
    u = _get_user_by_username(context.args[0])
    if not u:
        await update.message.reply_text(f"Benutzer '{context.args[0]}' nicht gefunden.")
        return
    year = datetime.date.today().year
    vc = _vacation_calc(u["id"], year)
    name = u["display_name"] or u["username"]
    lines = [f"🏖️ *Urlaubsübersicht {year} – {name}*\n"]
    lines.append(f"Anspruch: *{vc['entitlement']:.1f}* Tage")
    if vc["effective_carryover"] > 0:
        lines.append(f"Übertrag: *{vc['effective_carryover']:.1f}* Tage")
    lines.append(f"Genommen: *{vc['used_total']:.1f}* Tage")
    lines.append(f"Verfügbar: *{vc['remaining_total']:.1f}* Tage")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_alsabw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    if tid not in ADMIN_IDS:
        await update.message.reply_text("Kein Zugriff.")
        return
    if not context.args:
        await update.message.reply_text("Verwendung: /alsabw <username> [Jahr]")
        return
    u = _get_user_by_username(context.args[0])
    if not u:
        await update.message.reply_text(f"Benutzer '{context.args[0]}' nicht gefunden.")
        return
    year = datetime.date.today().year
    if len(context.args) >= 2:
        try:
            year = int(context.args[1])
        except ValueError:
            pass
    name = u["display_name"] or u["username"]
    header = f"📋 *Abwesenheiten {year} – {name}*"
    body = _get_abwesenheiten_liste(u["id"], year)
    await update.message.reply_text(f"{header}\n{body}", parse_mode="Markdown")


# ── Wizard helpers ────────────────────────────────────────────────────────────

def _wizard_kb_yesno() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ja, gearbeitet", callback_data="wizard_yes"),
        InlineKeyboardButton("🏠 Nein", callback_data="wizard_no"),
    ]])


def _wizard_kb_absence() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏖 Urlaub", callback_data="wizard_abs_urlaub"),
            InlineKeyboardButton("🤒 Krank", callback_data="wizard_abs_krank"),
        ],
        [
            InlineKeyboardButton("💆 Flextag", callback_data="wizard_abs_flextag"),
            InlineKeyboardButton("🔧 Verdi", callback_data="wizard_abs_verdi"),
        ],
        [
            InlineKeyboardButton("✈ Dienstreise", callback_data="wizard_abs_trip"),
            InlineKeyboardButton("❌ Abbrechen", callback_data="wizard_cancel"),
        ],
    ])


def _wizard_kb_confirm(typ: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ja, eintragen", callback_data=f"wizard_confirm_{typ}"),
        InlineKeyboardButton("◀ Zurück", callback_data="wizard_back"),
    ]])


def _wizard_expires() -> datetime.datetime:
    return datetime.datetime.now() + datetime.timedelta(hours=2)


async def _wizard_send_step1(bot, telegram_id: int, today_iso: str) -> None:
    d = datetime.date.fromisoformat(today_iso)
    text = (
        f"Guten Abend! 👋\n"
        f"Für heute ({_WEEKDAY_DE[d.weekday()]} {_fmt_date_de(today_iso)}) fehlt noch ein Eintrag.\n\n"
        f"Heute gearbeitet?"
    )
    wizard_state[telegram_id] = {
        "state": None,
        "date": today_iso,
        "absence_type": None,
        "expires": _wizard_expires(),
    }
    await bot.send_message(chat_id=telegram_id, text=text, reply_markup=_wizard_kb_yesno())


async def trigger_wizard(
    bot, telegram_id: int, user_id: int, today_iso: str, *, force: bool = False
) -> bool:
    """Send wizard if conditions are met. Returns True when wizard was sent."""
    if not force:
        if telegram_id in already_asked.get(today_iso, set()):
            return False
        if telegram_id in wizard_state:
            return False
        tracking_start = _get_tracking_start(user_id)
        if tracking_start and tracking_start > today_iso:
            return False
        schedule = _get_user_schedule_for_day(user_id, today_iso)
        if not _is_workday_for_user(today_iso, schedule):
            return False
        if _is_holiday(today_iso):
            return False
        if _has_entry_today(user_id, today_iso):
            return False
        if _is_absence_on_day(user_id, today_iso):
            return False
        if _is_day_locked(user_id, today_iso):
            return False
    try:
        await _wizard_send_step1(bot, telegram_id, today_iso)
        already_asked.setdefault(today_iso, set()).add(telegram_id)
        return True
    except Exception as e:
        logger.error("Wizard send failed for %d: %s", telegram_id, e)
        return False


async def check_reminders(app) -> None:
    now = datetime.datetime.now(tz=ZoneInfo("Europe/Berlin"))
    current_time = now.strftime("%H:%M")
    today_iso = now.date().isoformat()

    for old in list(already_asked.keys()):
        if old != today_iso:
            del already_asked[old]

    db = connect()
    try:
        rows = db.execute(
            "SELECT telegram_id, user_id FROM telegram_users "
            "WHERE wizard_enabled=1 AND reminder_time=?",
            (current_time,),
        ).fetchall()
    finally:
        db.close()

    for row in rows:
        await trigger_wizard(app.bot, int(row["telegram_id"]), int(row["user_id"]), today_iso)


_auto_backup_done_today: "str | None" = None


async def check_auto_backup() -> None:
    global _auto_backup_done_today
    today = datetime.date.today().isoformat()
    if _auto_backup_done_today == today:
        return
    db = connect()
    try:
        rows = db.execute("SELECT key, value FROM backup_config").fetchall()
    except Exception:
        return
    finally:
        db.close()
    cfg = {r["key"]: r["value"] for r in rows}
    if cfg.get("auto_backup_enabled", "0") != "1":
        return
    backup_time = cfg.get("auto_backup_time", "02:00")
    if datetime.datetime.now().strftime("%H:%M") != backup_time:
        return
    _auto_backup_done_today = today
    try:
        from backup import create_backup_gz, prune_backups, BACKUPS_DIR
        dest = str(BACKUPS_DIR / f"zeiterfassung_{today}_{backup_time.replace(':','-')}.db.gz")
        create_backup_gz(dest_path=dest)
        prune_backups(keep=7)
        db2 = connect()
        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db2.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('last_backup_time',?,datetime('now'))", (now_str,))
            db2.commit()
        finally:
            db2.close()
        logger.info(f"Auto-Backup erstellt: {dest}")
    except Exception as e:
        logger.error(f"Auto-Backup Fehler: {e}")


async def _on_startup(application: Application) -> None:
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
    scheduler.add_job(check_reminders, "cron", minute="*", args=[application])
    scheduler.add_job(check_auto_backup, "cron", minute="*")
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info("Abend-Wizard + Auto-Backup Scheduler gestartet (minütliche Prüfung)")


async def handle_wizard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    tid = query.from_user.id
    data = query.data

    if not data.startswith("wizard_"):
        return

    own_uid = _get_user_id(tid)
    if own_uid is None:
        await query.edit_message_text("Kein Benutzer verknüpft.")
        return

    ws = wizard_state.get(tid, {})
    today_iso = ws.get("date", datetime.date.today().isoformat())
    d = datetime.date.fromisoformat(today_iso)
    datum_de = _fmt_date_de(today_iso)

    expires = ws.get("expires")
    if expires and datetime.datetime.now() > expires:
        wizard_state.pop(tid, None)
        await query.edit_message_text("⏰ Zeit abgelaufen. Einfach direkt eintippen.")
        return

    if data == "wizard_yes":
        wizard_state[tid] = {**ws, "state": WAITING_HOURS, "expires": _wizard_expires()}
        await query.edit_message_text(
            "Super! Von wann bis wann hast du heute gearbeitet?\n\n"
            "Einfach schreiben, z.B.:\n"
            "• 7:30 bis 16:00\n"
            "• 8 bis 13:30\n"
            "• 7 bis 12 Pause 30"
        )

    elif data == "wizard_no":
        wizard_state[tid] = {**ws, "state": None, "expires": _wizard_expires()}
        await query.edit_message_text(
            "Kein Problem! Was war der Grund?",
            reply_markup=_wizard_kb_absence(),
        )

    elif data == "wizard_abs_trip":
        wizard_state[tid] = {**ws, "state": WAITING_TRIP_DESTINATION, "expires": _wizard_expires()}
        await query.edit_message_text("Wohin war die Dienstreise?")

    elif data.startswith("wizard_abs_"):
        typ_key = data[len("wizard_abs_"):]
        labels = {"urlaub": "Urlaub", "krank": "Krank", "flextag": "Flextag", "verdi": "Verdi"}
        label = labels.get(typ_key, typ_key.capitalize())
        wizard_state[tid] = {
            **ws, "state": WAITING_ABSENCE_CONFIRM,
            "absence_type": typ_key, "expires": _wizard_expires(),
        }
        await query.edit_message_text(
            f"{label} für heute ({datum_de}) eintragen?",
            reply_markup=_wizard_kb_confirm(typ_key),
        )

    elif data.startswith("wizard_confirm_"):
        typ_key = data[len("wizard_confirm_"):]
        type_map = {"urlaub": "Urlaub", "krank": "Krank", "flextag": "Flextag", "verdi": "Verdi"}
        absence_type = type_map.get(typ_key, typ_key.capitalize())
        wizard_state.pop(tid, None)
        result = _do_insert_absence(own_uid, absence_type, today_iso, today_iso)
        await query.edit_message_text(result)

    elif data == "wizard_cancel":
        wizard_state.pop(tid, None)
        await query.edit_message_text("Abgebrochen. Du kannst es jederzeit manuell eintragen.")

    elif data == "wizard_back":
        wizard_state[tid] = {**ws, "state": None, "absence_type": None, "expires": _wizard_expires()}
        await query.edit_message_text(
            "Kein Problem! Was war der Grund?",
            reply_markup=_wizard_kb_absence(),
        )


async def _handle_erinnerung(telegram_id: int, text: str, update: Update) -> None:
    parts = text.split()
    settings = _get_reminder_settings(telegram_id)

    if len(parts) == 1:
        if settings["enabled"]:
            await update.message.reply_text(
                f"Erinnerung: ✅ aktiv um {settings['time']} Uhr"
            )
        else:
            await update.message.reply_text("Erinnerung: 🔕 deaktiviert")
        return

    cmd = parts[1].lower()

    if cmd == "aus":
        _set_reminder_settings(telegram_id, False, settings["time"])
        await update.message.reply_text(
            "Erinnerung deaktiviert. Du erhältst keine Abfragen mehr."
        )
        return

    if cmd == "an":
        if len(parts) >= 3:
            t = _parse_reminder_time(parts[2])
            if t is None:
                await update.message.reply_text(
                    "Ungültige Uhrzeit. Bitte im Format HH:MM angeben, z.B. 19:30\n"
                    "Erlaubter Bereich: 15:00 – 23:00"
                )
                return
            _set_reminder_settings(telegram_id, True, t)
            await update.message.reply_text(f"Erinnerung aktiviert um {t} Uhr.")
        else:
            keep_time = settings["time"]
            _set_reminder_settings(telegram_id, True, keep_time)
            await update.message.reply_text(f"Erinnerung aktiviert um {keep_time} Uhr.")
        return

    t = _parse_reminder_time(parts[1])
    if t is not None:
        _set_reminder_settings(telegram_id, True, t)
        await update.message.reply_text(f"Erinnerung auf {t} Uhr gesetzt.")
        return

    await update.message.reply_text(
        "Verwendung:\n"
        "• _erinnerung_ — Status anzeigen\n"
        "• _erinnerung an_ — aktivieren (20:00)\n"
        "• _erinnerung aus_ — deaktivieren\n"
        "• _erinnerung 19:30_ — Uhrzeit setzen\n"
        "• _erinnerung an 18:00_ — aktivieren mit Uhrzeit",
        parse_mode="Markdown",
    )


async def cmd_testwizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    if tid not in ADMIN_IDS:
        await update.message.reply_text("Kein Zugriff.")
        return

    today_iso = datetime.date.today().isoformat()

    if not context.args:
        own_uid = _get_user_id(tid)
        if own_uid is None:
            await update.message.reply_text("Kein Benutzer verknüpft.")
            return
        sent = await trigger_wizard(context.bot, tid, own_uid, today_iso, force=True)
        if sent:
            await update.message.reply_text("Wizard für dich gesendet.")
        else:
            await update.message.reply_text("Wizard konnte nicht gesendet werden.")
        return

    u = _get_user_by_username(context.args[0])
    if not u:
        await update.message.reply_text(f"Benutzer '{context.args[0]}' nicht gefunden.")
        return

    target_tid = _get_telegram_id_for_user(u["id"])
    if target_tid is None:
        name = u["display_name"] or u["username"]
        await update.message.reply_text(
            f"User {name} hat keine Telegram-ID hinterlegt."
        )
        return

    sent = await trigger_wizard(context.bot, target_tid, u["id"], today_iso, force=True)
    name = u["display_name"] or u["username"]
    if sent:
        await update.message.reply_text(
            f"Wizard für {name} (Telegram-ID: {target_tid}) gesendet."
        )
    else:
        await update.message.reply_text(f"Wizard konnte nicht gesendet werden.")


# ── Free-text handler ─────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    if not _is_authorized(tid):
        await update.message.reply_text("Kein Zugriff. Bitte Admin kontaktieren.")
        return
    own_uid = _get_user_id(tid)
    if own_uid is None:
        await update.message.reply_text(
            f"Kein Benutzer verknüpft. Bitte Admin kontaktieren.\nDeine Telegram-ID: {tid}"
        )
        return

    # Effective user (admin context override)
    uid = own_uid
    if tid in ADMIN_IDS:
        ctx_uid = context.user_data.get("context_uid")
        if ctx_uid is not None:
            uid = ctx_uid

    text = (update.message.text or "").strip()
    text_lower = text.lower()

    # Handle "erinnerung" command
    if text_lower == "erinnerung" or text_lower.startswith("erinnerung "):
        await _handle_erinnerung(tid, text, update)
        return

    # Handle wizard states
    ws = wizard_state.get(tid)
    if ws:
        expires = ws.get("expires")
        if expires and datetime.datetime.now() > expires:
            wizard_state.pop(tid, None)
        elif ws.get("state") == WAITING_HOURS:
            today_iso = ws["date"]
            wizard_state.pop(tid, None)
            nlp_text = text if any(w in text_lower for w in ("bis", "uhr", ":")) else f"Heute von {text}"
            actions = _parse_nlp(nlp_text)
            if actions:
                for action in actions:
                    if action.get("action") == "time":
                        action["date"] = today_iso
                await _execute_actions(actions, uid, update, context)
            else:
                await update.message.reply_text(
                    "❓ Das habe ich nicht verstanden.\n"
                    "Beispiele:\n• 7:30 bis 16:00\n• 8 bis 13:30\n• 7 bis 12 Pause 30"
                )
            return
        elif ws.get("state") == WAITING_TRIP_DESTINATION:
            today_iso = ws["date"]
            wizard_state.pop(tid, None)
            result = _do_insert_business_trip(uid, today_iso, text.strip())
            await update.message.reply_text(result)
            return

    # Handle pending ja/nein confirmation
    pending = context.user_data.get("pending_confirm")
    if pending:
        if text.lower() in ("ja", "j", "yes", "y"):
            context.user_data.pop("pending_confirm", None)
            if pending["action"] == "time":
                result = _do_insert_time_block(
                    pending["user_id"],
                    pending["day"],
                    pending["time_in"],
                    pending["time_out"],
                    pending["break_minutes"],
                    pending.get("break_auto", False),
                )
            else:
                result = "❌ Unbekannte ausstehende Aktion."
            await update.message.reply_text(result)
        elif text.lower() in ("nein", "n", "no"):
            context.user_data.pop("pending_confirm", None)
            await update.message.reply_text("Abgebrochen.")
        else:
            # Not a yes/no – treat as new input
            context.user_data.pop("pending_confirm", None)
            await _process_nlp(text, uid, update, context)
        return

    await _process_nlp(text, uid, update, context)


async def _process_nlp(
    text: str, uid: int, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    actions = _parse_nlp(text)
    if not actions:
        await update.message.reply_text(NLP_EXAMPLES)
        return
    await _execute_actions(actions, uid, update, context)


async def cmd_rente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    uid = _get_user_id(tid)
    if uid is None:
        await update.message.reply_text("Kein Benutzer verknüpft. Bitte zuerst /start.")
        return
    db = connect()
    try:
        row = db.execute("SELECT birth_date, retirement_age FROM users WHERE id=?", (uid,)).fetchone()
    finally:
        db.close()
    if not row or not row["birth_date"]:
        await update.message.reply_text(
            "Kein Geburtsdatum hinterlegt. Bitte in den Einstellungen (Persönliche Einstellungen) eintragen."
        )
        return
    try:
        bd = datetime.date.fromisoformat(row["birth_date"])
    except (ValueError, TypeError):
        await update.message.reply_text("Ungültiges Geburtsdatum in den Einstellungen.")
        return
    age = int(row["retirement_age"] or 67)
    try:
        ret_date = bd.replace(year=bd.year + age)
    except ValueError:
        ret_date = bd.replace(year=bd.year + age, day=28)
    today = datetime.date.today()
    delta = ret_date - today
    cal_days = delta.days
    if cal_days <= 0:
        ret_de = ret_date.strftime("%d.%m.%Y")
        await update.message.reply_text(f"🎉 Du bist seit {ret_de} im Rentenalter!")
        return
    weeks = cal_days // 7
    years = 0
    months = 0
    d = today
    while True:
        try:
            nxt = d.replace(year=d.year + 1)
        except ValueError:
            nxt = d.replace(year=d.year + 1, day=28)
        if nxt > ret_date:
            break
        years += 1
        d = nxt
    while True:
        m = d.month + 1
        y = d.year + (1 if m > 12 else 0)
        m = m if m <= 12 else 1
        try:
            nxt = d.replace(year=y, month=m)
        except ValueError:
            nxt = d.replace(year=y, month=m, day=28)
        if nxt > ret_date:
            break
        months += 1
        d = nxt
    rem_days = (ret_date - d).days
    full_weeks = cal_days // 7
    extra = cal_days % 7
    start_dow = today.weekday()
    net_workdays = full_weeks * 5
    for i in range(extra):
        if (start_dow + i) % 7 < 5:
            net_workdays += 1
    ret_de = ret_date.strftime("%d.%m.%Y")
    msg = (
        f"🧓 *Rentencountdown* (Alter {age})\n\n"
        f"Renteneintritt: *{ret_de}*\n"
        f"Noch *{years} J. {months} Mon. {rem_days} Tage*\n\n"
        f"Kalendertage: {cal_days:,}\n"
        f"Arbeitstage (netto): {net_workdays:,}\n"
        f"Wochen: {weeks:,}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    init_db()

    app = Application.builder().token(TOKEN).post_init(_on_startup).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("saldo", cmd_saldo))
    app.add_handler(CommandHandler("urlaub", cmd_urlaub))
    app.add_handler(CommandHandler("heute", cmd_heute))
    app.add_handler(CommandHandler("fehlend", cmd_fehlend))
    app.add_handler(CommandHandler("kontierung", cmd_kontierung))
    app.add_handler(CommandHandler("bericht", cmd_bericht))
    app.add_handler(CommandHandler("abwesenheiten", cmd_abwesenheiten))
    app.add_handler(CommandHandler("user", cmd_user))
    app.add_handler(CommandHandler("als", cmd_als))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("alssaldo", cmd_alssaldo))
    app.add_handler(CommandHandler("alsurlaub", cmd_alsurlaub))
    app.add_handler(CommandHandler("alsabw", cmd_alsabw))
    app.add_handler(CommandHandler("testwizard", cmd_testwizard))
    app.add_handler(CommandHandler("rente", cmd_rente))
    app.add_handler(CallbackQueryHandler(handle_wizard_callback, pattern="^wizard_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot startet (Polling) – v1.2.6…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
