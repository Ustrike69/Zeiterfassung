"""Zeiterfassung Telegram Bot"""

import datetime
import logging
import os
import sys

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ── Setup ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

TOKEN = "8673206171:AAEwr7EXU7a2y6frMspRATKRvWIdHlWbCeU"
ADMIN_IDS: set[int] = {7593372353}
AUTHORIZED_IDS: set[int] = {7593372353}  # extended via DB at runtime

# ── DB helpers (reuse connect() from db.py) ──────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from db import connect, init_db  # noqa: E402


def _ensure_authorized(telegram_id: int) -> bool:
    return telegram_id in AUTHORIZED_IDS


def _get_user_id(telegram_id: int) -> "int | None":
    """Return app user_id for a telegram_id, or None."""
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


# ── Calculation helpers (inlined from app.py logic) ──────────────────────────

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


def _get_user_schedule_for_day(user_id: int, iso_day: str) -> "dict | None":
    db = connect()
    try:
        rows = db.execute(
            "SELECT * FROM user_schedules WHERE user_id=? AND valid_from<=? ORDER BY valid_from DESC LIMIT 1",
            (user_id, iso_day),
        ).fetchone()
        if rows:
            return dict(rows)
        # fallback to user_schedule
        r = db.execute("SELECT * FROM user_schedule WHERE user_id=?", (user_id,)).fetchone()
        return dict(r) if r else None
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
    wd = d.weekday()  # 0=Mon
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
            """SELECT a.id FROM absences a
               WHERE a.user_id=? AND a.date_from<=? AND a.date_to>=?""",
            (user_id, iso_day, iso_day),
        ).fetchone()
        return ab is not None
    finally:
        db.close()


def _week_dates_from(iso_day: str) -> list:
    d = datetime.date.fromisoformat(iso_day)
    monday = d - datetime.timedelta(days=d.weekday())
    return [monday + datetime.timedelta(days=i) for i in range(7)]


def _expected_minutes_for_day(user_id: int, iso_day: str) -> int:
    """Correct weekly/daily schedule calculation - mirrors app.py logic."""
    # Check holiday/weekend
    if _is_holiday(iso_day):
        return 0

    schedule = _get_user_schedule_for_day(user_id, iso_day)
    if not schedule:
        return 0

    d = datetime.date.fromisoformat(iso_day)
    wd = d.weekday()

    # Check workdays mask
    mask = int(schedule.get("workdays_mask") or 31)
    if not _mask_allows(mask, wd):
        return 0

    # Weekend block
    block = int(schedule.get("block_weekends_holidays") or 1)
    if block and wd >= 5:
        return 0

    # Check absence
    if _is_absence_on_day(user_id, iso_day):
        return 0

    mode = (schedule.get("mode") or "weekly").strip().lower()

    if mode == "daily":
        col = _WEEKDAY_COLS[wd] + "_minutes"
        return int(schedule.get(col) or 0)

    # Weekly mode: distribute weekly_minutes evenly across eligible days
    weekly = int(schedule.get("weekly_minutes") or 0)
    week_days = _week_dates_from(iso_day)

    eligible = []
    for wd_day in week_days:
        w = wd_day.weekday()
        if not _mask_allows(mask, w):
            continue
        eligible.append(wd_day)

    if not eligible:
        return 0

    eligible = sorted(eligible)
    if d not in eligible:
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
        # fallback time_entries
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
               WHERE a.user_id=? AND LOWER(t.name)='flextag'""",
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
        return {"entitlement_days": float(r["entitlement_days"]) if r else 0.0,
                "carryover_days": float(r["carryover_days"]) if r else 0.0}
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
        if deadline_passed:
            effective_carryover = min(carryover, carryover_started)
        else:
            effective_carryover = carryover

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
    finally:
        db.close()

    # Abwesenheiten laden
    db = connect()
    try:
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


# ── Auth middleware ───────────────────────────────────────────────────────────

async def _check_auth(update: Update) -> "tuple[bool, int|None]":
    """Returns (authorized, user_id). Sends error message if not authorized."""
    tid = update.effective_user.id
    if tid not in AUTHORIZED_IDS:
        await update.message.reply_text("Kein Zugriff. Bitte Admin kontaktieren.")
        return False, None
    uid = _get_user_id(tid)
    if uid is None:
        await update.message.reply_text(
            "Kein Benutzer verknüpft. Bitte Admin kontaktieren.\n"
            f"Deine Telegram-ID: {tid}"
        )
        return False, None
    return True, uid


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    if tid not in AUTHORIZED_IDS:
        await update.message.reply_text("Kein Zugriff. Bitte Admin kontaktieren.")
        return

    is_admin = tid in ADMIN_IDS
    text = (
        "👋 *Zeiterfassung Bot*\n\n"
        "*Befehle:*\n"
        "/saldo — Aktuelles Gleitzeitkonto\n"
        "/urlaub — Urlaubsübersicht\n"
        "/heute — Heutige Zeiteinträge\n"
        "/fehlend — Fehlende Einträge\n"
        "/kontierung — Kontierungsübersicht\n"
        "/user — Aktiver Benutzer\n"
    )
    if is_admin:
        text += (
            "\n*Admin-Befehle:*\n"
            "/users — Alle Benutzer\n"
            "/alssaldo <username> — Saldo eines Users\n"
            "/alsurlaub <username> — Urlaub eines Users\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok, uid = await _check_auth(update)
    if not ok:
        return
    today = datetime.date.today().isoformat()
    mins = _calc_balance_end_at(uid, today)
    sign = "✅" if mins >= 0 else "⚠️"
    await update.message.reply_text(
        f"{sign} *Gleitzeitkonto*\n\nStand {_fmt_date_de(today)}: *{_fmt_minutes_signed(mins)}*",
        parse_mode="Markdown",
    )


async def cmd_urlaub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok, uid = await _check_auth(update)
    if not ok:
        return
    year = datetime.date.today().year
    vc = _vacation_calc(uid, year)
    lines = [f"🏖️ *Urlaubsübersicht {year}*\n"]
    lines.append(f"Anspruch: *{vc['entitlement']:.1f}* Tage")
    if vc["effective_carryover"] > 0:
        lines.append(f"Übertrag: *{vc['effective_carryover']:.1f}* Tage")
    lines.append(f"Genommen: *{vc['used_total']:.1f}* Tage")
    lines.append(f"Verfügbar: *{vc['remaining_total']:.1f}* Tage")
    if not vc["deadline_passed"] and vc["carryover"] > 0:
        lines.append(f"\n⚠️ Übertrag verfällt am {_fmt_date_de(vc['deadline_iso'])}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_heute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok, uid = await _check_auth(update)
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
    ok, uid = await _check_auth(update)
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
    ok, uid = await _check_auth(update)
    if not ok:
        return
    year = datetime.date.today().year
    ci = _get_contouring_info(uid)
    if not ci["enabled"]:
        await update.message.reply_text("Kontierung ist für deinen Account deaktiviert.")
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


async def cmd_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tid = update.effective_user.id
    if tid not in AUTHORIZED_IDS:
        await update.message.reply_text("Kein Zugriff. Bitte Admin kontaktieren.")
        return
    uid = _get_user_id(tid)
    if uid is None:
        await update.message.reply_text(f"Kein Benutzer verknüpft.\nDeine Telegram-ID: {tid}")
        return
    u = _get_user_row(uid)
    name = u["display_name"] or u["username"] if u else f"ID {uid}"
    await update.message.reply_text(f"👤 Aktiver Benutzer: *{name}*", parse_mode="Markdown")


# ── Admin commands ────────────────────────────────────────────────────────────

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
    username = context.args[0]
    u = _get_user_by_username(username)
    if not u:
        await update.message.reply_text(f"Benutzer '{username}' nicht gefunden.")
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
    username = context.args[0]
    u = _get_user_by_username(username)
    if not u:
        await update.message.reply_text(f"Benutzer '{username}' nicht gefunden.")
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    init_db()

    # Load all authorized Telegram IDs from DB
    try:
        db = connect()
        rows = db.execute("SELECT telegram_id FROM telegram_users").fetchall()
        db.close()
        for r in rows:
            AUTHORIZED_IDS.add(int(r["telegram_id"]))
    except Exception as e:
        logger.warning("Konnte telegram_users nicht laden: %s", e)

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("saldo", cmd_saldo))
    app.add_handler(CommandHandler("urlaub", cmd_urlaub))
    app.add_handler(CommandHandler("heute", cmd_heute))
    app.add_handler(CommandHandler("fehlend", cmd_fehlend))
    app.add_handler(CommandHandler("kontierung", cmd_kontierung))
    app.add_handler(CommandHandler("user", cmd_user))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("alssaldo", cmd_alssaldo))
    app.add_handler(CommandHandler("alsurlaub", cmd_alsurlaub))

    logger.info("Bot startet (Polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
