from flask import Flask, request, redirect, url_for, session, render_template_string, abort
import datetime
import calendar
import sqlite3
import re
import html as _html
from db import init_db, seed_defaults, db_path, connect
from calendar_seed import seed_calendar_2026_nrw
from auth import has_users, create_user, authenticate, current_user, login_required, admin_required, set_password, set_flags
from templates import layout as base_layout


APP_VERSION = "v4.5.9"
app = Flask(__name__)
app.secret_key = "change-me"  # set via env in production


# -------------------------
# Mobile / iPhone Optimierung
# -------------------------

MOBILE_ASSETS = """
<script>
  document.addEventListener('DOMContentLoaded', function(){
    try{
      document.querySelectorAll('table').forEach(function(t){
        if(t.closest('.table-scroll')) return;
        var wrap = document.createElement('div');
        wrap.className = 'table-scroll';
        t.parentNode.insertBefore(wrap, t);
        wrap.appendChild(t);
      });
    }catch(e){}
  });
</script>
"""


def layout(title, body, user, version, show_back=True):
    """Wrapper around templates.layout that injects mobile assets globally."""
    banner = ""
    if session.get("impersonator_id") and user:
        username = _html.escape(user.get("display_name") or user.get("username") or "?")
        banner = (
            '<div style="background:#f59e0b;color:#1c1917;padding:10px 16px;text-align:center;'
            'font-weight:600;display:flex;align-items:center;justify-content:center;gap:16px;flex-wrap:wrap;">'
            f'<span>⚠️ Du agierst als <strong>{username}</strong></span>'
            '<form method="post" action="/admin/impersonate/stop" style="display:inline;">'
            '<button type="submit" style="background:#1c1917;color:#fef3c7;border:none;border-radius:6px;'
            'padding:4px 12px;cursor:pointer;font-weight:600;font-size:14px;">Zurück zu Admin</button>'
            '</form></div>'
        )
    return base_layout(title, MOBILE_ASSETS + body, user, version, impersonation_banner=banner, show_back=show_back)


def bootstrap():
    init_db()
    seed_defaults()
    # keep older DBs compatible
    _ensure_user_schedules_schema()
    _ensure_user_prefs_schema()
    _ensure_expected_override_schema()
    _ensure_vacation_schema()
    _ensure_vacation_carryover_schema()
    _ensure_business_trips_schema()
    _ensure_contoured_days_schema()
    seed_calendar_2026_nrw()




def _ensure_user_schedules_schema() -> None:
    """Ensure user_schedules table exists with required columns; migrate older schemas."""
    db = connect()
    cur = db.cursor()
    # table exists?
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_schedules'")
    if not cur.fetchone():
        cur.execute(
            """
            CREATE TABLE user_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                valid_from TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'weekly', -- 'weekly' or 'daily'
                weekly_minutes INTEGER NOT NULL DEFAULT 0,
                workdays_mask INTEGER NOT NULL DEFAULT 31,
                mon_minutes INTEGER NOT NULL DEFAULT 0,
                tue_minutes INTEGER NOT NULL DEFAULT 0,
                wed_minutes INTEGER NOT NULL DEFAULT 0,
                thu_minutes INTEGER NOT NULL DEFAULT 0,
                fri_minutes INTEGER NOT NULL DEFAULT 0,
                sat_minutes INTEGER NOT NULL DEFAULT 0,
                sun_minutes INTEGER NOT NULL DEFAULT 0,
                block_weekends_holidays INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_schedules_user_valid_from ON user_schedules(user_id, valid_from)")
        db.commit()
        db.close()
        return

    # migrate columns
    cols = {r[1] for r in cur.execute("PRAGMA table_info(user_schedules)").fetchall()}
    def add_col(sql):
        cur.execute(sql)

    if "valid_from" not in cols:
        add_col("ALTER TABLE user_schedules ADD COLUMN valid_from TEXT")
        cur.execute("UPDATE user_schedules SET valid_from = COALESCE(valid_from, date('now'))")
    if "mode" not in cols:
        add_col("ALTER TABLE user_schedules ADD COLUMN mode TEXT DEFAULT 'weekly'")
        cur.execute("UPDATE user_schedules SET mode = COALESCE(mode, 'weekly')")
    if "weekly_minutes" not in cols:
        add_col("ALTER TABLE user_schedules ADD COLUMN weekly_minutes INTEGER DEFAULT 0")
        # If an older column exists, try to convert
        if "weekly_hours" in cols:
            cur.execute("UPDATE user_schedules SET weekly_minutes = CAST(weekly_hours AS INTEGER) * 60 WHERE weekly_minutes IS NULL OR weekly_minutes = 0")
        cur.execute("UPDATE user_schedules SET weekly_minutes = COALESCE(weekly_minutes, 0)")
    if "workdays_mask" not in cols:
        add_col("ALTER TABLE user_schedules ADD COLUMN workdays_mask INTEGER DEFAULT 31")
        cur.execute("UPDATE user_schedules SET workdays_mask = COALESCE(workdays_mask, 31)")
    for c in ["mon_minutes","tue_minutes","wed_minutes","thu_minutes","fri_minutes","sat_minutes","sun_minutes"]:
        if c not in cols:
            add_col(f"ALTER TABLE user_schedules ADD COLUMN {c} INTEGER DEFAULT 0")
            cur.execute(f"UPDATE user_schedules SET {c} = COALESCE({c}, 0)")
    if "block_weekends_holidays" not in cols:
        add_col("ALTER TABLE user_schedules ADD COLUMN block_weekends_holidays INTEGER DEFAULT 1")
        cur.execute("UPDATE user_schedules SET block_weekends_holidays = COALESCE(block_weekends_holidays, 1)")
    if "updated_at" not in cols:
        add_col("ALTER TABLE user_schedules ADD COLUMN updated_at TEXT")

    # Ensure index
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_schedules_user_valid_from ON user_schedules(user_id, valid_from)")
    db.commit()
    db.close()

def _minutes_from_hhmm(hhmm: str) -> int:
    h, m = [int(x) for x in hhmm.split(":")]
    return h * 60 + m



def _schedule_weekly_col(db):
    """Return weekly-minutes column in user_schedules (compat: week_minutes vs weekly_minutes)."""
    try:
        cols = [r["name"] for r in db.execute("PRAGMA table_info(user_schedules)").fetchall()]
        if "weekly_minutes" in cols:
            return "weekly_minutes"
        if "week_minutes" in cols:
            return "week_minutes"
    except Exception:
        pass
    return "weekly_minutes"

def _fmt_minutes(mins: int) -> str:
    if mins < 0:
        mins = 0
    return f"{mins//60:02d}:{mins%60:02d}"







def _fmt_minutes_signed(mins: int) -> str:
    sign = "-" if mins < 0 else "+"
    mins = abs(int(mins or 0))
    return f"{sign}{mins//60:02d}:{mins%60:02d}"


def _balance_color(mins: int) -> str:
    if mins > 0:
        return "var(--ok)"
    if mins < 0:
        return "var(--danger)"
    return "inherit"


def _parse_signed_hhmm_to_minutes(val: str) -> int:
    """Accept +HH:MM or -HH:MM or HH:MM."""
    s = (val or "").strip()
    if not s:
        return 0
    sign = 1
    if s[0] in "+-":
        sign = -1 if s[0] == "-" else 1
        s = s[1:].strip()
    if not re.match(r"^\d{2}:\d{2}$", s):
        raise ValueError("Format (+)HH:MM")
    h, m = s.split(":")
    return sign * (int(h) * 60 + int(m))




def _ensure_user_prefs_schema() -> None:
    """Store per-user preferences (UI/logic toggles)."""
    db = connect()
    try:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id INTEGER PRIMARY KEY,
                auto_breaks INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        db.commit()
    finally:
        db.close()


def _get_pref_auto_breaks(user_id: int) -> int:
    db = connect()
    try:
        _ensure_user_prefs_schema()
        r = db.execute('SELECT auto_breaks FROM user_prefs WHERE user_id=?', (int(user_id),)).fetchone()
        return int(r['auto_breaks']) if r else 0
    finally:
        db.close()



def _set_pref_auto_breaks(user_id: int, enabled: int) -> None:
    db = connect()
    try:
        _ensure_user_prefs_schema()
        db.execute(
            """
            INSERT INTO user_prefs(user_id, auto_breaks, updated_at)
            VALUES(?,?,datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
              auto_breaks=excluded.auto_breaks,
              updated_at=datetime('now')
            """,
            (int(user_id), 1 if int(enabled) else 0),
        )
        db.commit()
    finally:
        db.close()


def _apply_auto_breaks_if_needed(span_minutes: int, break_minutes: int) -> int:
    """Enforce minimum breaks based on recorded span (end-start).

    Rules:
    - span > 6:00  => min 30 min
    - span > 9:30  => min 45 min
    """
    try:
        span = int(span_minutes or 0)
        brk = int(break_minutes or 0)
    except Exception:
        return int(break_minutes or 0)

    min_brk = 0
    if span > 9 * 60 + 30:
        min_brk = 45
    elif span > 6 * 60:
        min_brk = 30

    return brk if brk >= min_brk else min_brk


# --- Sollstunden-Override (pro Tag, pro User) ---

def _ensure_expected_override_schema() -> None:
    """Per-user per-day override for Soll minutes (expected time)."""
    db = connect()
    cur = db.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_expected_overrides (
            user_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            expected_minutes INTEGER NOT NULL,
            updated_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, day),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()
    db.close()


def _get_expected_override_minutes(user_id: int, iso_day: str):
    db = connect()
    try:
        _ensure_expected_override_schema()
        r = db.execute(
            "SELECT expected_minutes FROM user_expected_overrides WHERE user_id=? AND day=?",
            (int(user_id), str(iso_day)),
        ).fetchone()
        if not r:
            return None
        return int(r["expected_minutes"])
    finally:
        db.close()


def _set_expected_override_minutes(user_id: int, iso_day: str, minutes):
    db = connect()
    try:
        _ensure_expected_override_schema()
        if minutes is None:
            db.execute(
                "DELETE FROM user_expected_overrides WHERE user_id=? AND day=?",
                (int(user_id), str(iso_day)),
            )
        else:
            db.execute(
                """
                INSERT INTO user_expected_overrides(user_id, day, expected_minutes, updated_at)
                VALUES(?,?,?,datetime('now'))
                ON CONFLICT(user_id, day) DO UPDATE SET
                  expected_minutes=excluded.expected_minutes,
                  updated_at=datetime('now')
                """,
                (int(user_id), str(iso_day), int(minutes)),
            )
        db.commit()
    finally:
        db.close()


# --- Urlaub (Anspruch / Resturlaub) ---

def _ensure_vacation_schema() -> None:
    db = connect()
    cur = db.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_vacation_year (
            user_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            entitlement_days REAL NOT NULL DEFAULT 0,
            carryover_days REAL NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, year),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()
    db.close()


def _ensure_vacation_carryover_schema() -> None:
    db = connect()
    db.execute("""CREATE TABLE IF NOT EXISTS vacation_carryover_overrides(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        year INTEGER NOT NULL,
        carryover_days REAL NOT NULL DEFAULT 0,
        valid_until TEXT,
        comment TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(user_id, year),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.commit()
    db.close()


def _ensure_business_trips_schema() -> None:
    db = connect()
    # Migrate old Dienstreise absences if any
    try:
        dienst = db.execute(
            "SELECT id FROM absence_types WHERE LOWER(name)='dienstreise' AND active=1 LIMIT 1"
        ).fetchone()
        if dienst:
            type_id = dienst["id"]
            rows = db.execute(
                "SELECT user_id, date_from FROM absences WHERE type_id=?", (type_id,)
            ).fetchall()
            for a in rows:
                db.execute(
                    "INSERT OR IGNORE INTO business_trips(user_id, start_date, destination, updated_at)"
                    " VALUES(?,?,?,datetime('now'))",
                    (a["user_id"], str(a["date_from"])[:10], "(migriert)"),
                )
            db.execute("UPDATE absence_types SET active=0 WHERE id=?", (type_id,))
    except Exception:
        pass
    # Column migrations: date → start_date, add end_date
    cols = {r[1] for r in db.execute("PRAGMA table_info(business_trips)").fetchall()}
    if "date" in cols and "start_date" not in cols:
        db.execute("ALTER TABLE business_trips RENAME COLUMN date TO start_date")
        cols = {r[1] for r in db.execute("PRAGMA table_info(business_trips)").fetchall()}
    if "end_date" not in cols:
        db.execute("ALTER TABLE business_trips ADD COLUMN end_date TEXT")
        db.execute("UPDATE business_trips SET end_date=start_date WHERE end_date IS NULL")
    db.commit()
    db.close()


def _ensure_contoured_days_schema() -> None:
    db = connect()
    db.execute("""
    CREATE TABLE IF NOT EXISTS contoured_days (
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, day),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_contoured_days_user ON contoured_days(user_id, day)")
    db.commit()
    db.close()


def _get_vacation_year(user_id: int, year: int) -> dict:
    db = connect()
    try:
        _ensure_vacation_schema()
        r = db.execute(
            "SELECT entitlement_days, carryover_days FROM user_vacation_year WHERE user_id=? AND year=?",
            (int(user_id), int(year)),
        ).fetchone()
        if not r:
            return {"entitlement_days": 0.0, "carryover_days": 0.0}
        return {"entitlement_days": float(r["entitlement_days"] or 0), "carryover_days": float(r["carryover_days"] or 0)}
    finally:
        db.close()


def _set_vacation_year(user_id: int, year: int, entitlement_days: float, carryover_days: float) -> None:
    db = connect()
    try:
        _ensure_vacation_schema()
        db.execute(
            """
            INSERT INTO user_vacation_year(user_id, year, entitlement_days, carryover_days, updated_at)
            VALUES(?,?,?,?,datetime('now'))
            ON CONFLICT(user_id, year) DO UPDATE SET
              entitlement_days=excluded.entitlement_days,
              carryover_days=excluded.carryover_days,
              updated_at=datetime('now')
            """,
            (int(user_id), int(year), float(entitlement_days), float(carryover_days)),
        )
        db.commit()
    finally:
        db.close()


def _get_vacation_carryover_exception(user_id: int) -> int:
    db = connect()
    try:
        r = db.execute(
            "SELECT vacation_carryover_exception FROM users WHERE id=?", (user_id,)
        ).fetchone()
        return int(r["vacation_carryover_exception"] or 0) if r else 0
    except Exception:
        return 0
    finally:
        db.close()


def _set_vacation_carryover_exception(user_id: int, value: int) -> None:
    db = connect()
    try:
        db.execute(
            "UPDATE users SET vacation_carryover_exception=?, updated_at=datetime('now') WHERE id=?",
            (1 if value else 0, user_id),
        )
        db.commit()
    finally:
        db.close()


def _get_vacation_carryover_override(user_id: int, year: int):
    db = connect()
    try:
        r = db.execute(
            "SELECT id, carryover_days, valid_until, comment FROM vacation_carryover_overrides "
            "WHERE user_id=? AND year=?",
            (user_id, year),
        ).fetchone()
        return dict(r) if r else None
    finally:
        db.close()


def _get_all_vacation_carryover_overrides(user_id: int) -> list:
    db = connect()
    try:
        rows = db.execute(
            "SELECT year, carryover_days, valid_until, comment FROM vacation_carryover_overrides "
            "WHERE user_id=? ORDER BY year DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def _upsert_vacation_carryover_override(
    user_id: int, year: int, carryover_days: float, valid_until: str, comment: str
) -> None:
    db = connect()
    try:
        db.execute(
            """
            INSERT INTO vacation_carryover_overrides(user_id, year, carryover_days, valid_until, comment)
            VALUES(?,?,?,?,?)
            ON CONFLICT(user_id, year) DO UPDATE SET
              carryover_days=excluded.carryover_days,
              valid_until=excluded.valid_until,
              comment=excluded.comment
            """,
            (user_id, year, float(carryover_days), valid_until or None, comment or None),
        )
        db.commit()
    finally:
        db.close()


def _delete_vacation_carryover_override(user_id: int, year: int) -> None:
    db = connect()
    try:
        db.execute(
            "DELETE FROM vacation_carryover_overrides WHERE user_id=? AND year=?",
            (user_id, year),
        )
        db.commit()
    finally:
        db.close()


def _is_user_workday_by_schedule(user_id: int, iso_day: str) -> bool:
    """Workday according to schedule + weekend/holiday blocking, but without absence logic."""
    sched = _normalize_schedule(_get_user_schedule_for_day(user_id, iso_day))
    if int(sched.get("block_weekends_holidays", 1)) == 1 and _blocked_by_calendar(iso_day):
        return False
    d = datetime.date.fromisoformat(iso_day)
    mask = int(sched.get("workdays_mask", _default_workdays_mask()))
    return _mask_allows(mask, d.weekday())


def _vacation_used_days(user_id: int, year: int, date_to_limit: str | None = None) -> float:
    """Count used vacation days (type contains 'Urlaub') in a year.
    Counts only on user workdays (weekends/holidays excluded according to schedule settings).
    Half-day counts 0.5 (only valid when from=to).
    If date_to_limit is set (YYYY-MM-DD), count only up to that date (inclusive).
    """
    y0 = datetime.date(int(year), 1, 1)
    y1 = datetime.date(int(year), 12, 31)
    if date_to_limit:
        try:
            lim = datetime.date.fromisoformat(date_to_limit)
            if lim < y1:
                y1 = lim
        except Exception:
            pass

    db = connect()
    try:
        rows = db.execute(
            """
            SELECT a.date_from, a.date_to, a.is_half_day, t.name AS type_name
            FROM absences a
            JOIN absence_types t ON t.id = a.type_id
            WHERE a.user_id = ?
              AND (LOWER(t.name) LIKE '%urlaub%')
              AND NOT (a.date_to < ? OR a.date_from > ?)
            """,
            (int(user_id), y0.isoformat(), y1.isoformat()),
        ).fetchall()
    finally:
        db.close()

    used = 0.0
    for a in rows:
        d0 = datetime.date.fromisoformat(str(a["date_from"]))
        d1 = datetime.date.fromisoformat(str(a["date_to"]))
        if d0 < y0:
            d0 = y0
        if d1 > y1:
            d1 = y1

        # half day only when single-day
        if int(a["is_half_day"] or 0) == 1 and d0 == d1:
            iso = d0.isoformat()
            if _is_user_workday_by_schedule(user_id, iso):
                used += 0.5
            continue

        cur = d0
        while cur <= d1:
            iso = cur.isoformat()
            if _is_user_workday_by_schedule(user_id, iso):
                used += 1.0
            cur += datetime.timedelta(days=1)

    return float(used)

def _vacation_used_days_started_by(user_id: int, year: int, deadline_iso: str) -> float:
    """Count workday vacation days in `year` for entries whose date_from <= deadline_iso.
    The full duration is counted (days after the deadline are included if the entry started before it)."""
    y0 = datetime.date(int(year), 1, 1)
    y1 = datetime.date(int(year), 12, 31)
    db = connect()
    try:
        rows = db.execute(
            """
            SELECT a.date_from, a.date_to, a.is_half_day
            FROM absences a
            JOIN absence_types t ON t.id = a.type_id
            WHERE a.user_id = ?
              AND LOWER(t.name) LIKE '%urlaub%'
              AND a.date_from <= ?
              AND NOT (a.date_to < ? OR a.date_from > ?)
            """,
            (int(user_id), deadline_iso, y0.isoformat(), y1.isoformat()),
        ).fetchall()
    finally:
        db.close()
    used = 0.0
    for a in rows:
        d0 = datetime.date.fromisoformat(str(a["date_from"]))
        d1 = datetime.date.fromisoformat(str(a["date_to"]))
        if d0 < y0:
            d0 = y0
        if d1 > y1:
            d1 = y1
        if int(a["is_half_day"] or 0) == 1 and d0 == d1:
            if _is_user_workday_by_schedule(user_id, d0.isoformat()):
                used += 0.5
            continue
        cur = d0
        while cur <= d1:
            if _is_user_workday_by_schedule(user_id, cur.isoformat()):
                used += 1.0
            cur += datetime.timedelta(days=1)
    return float(used)


def _vacation_calc(user_id: int, year: int) -> dict:
    """Central vacation calculation. Returns all metrics needed for display and the homepage."""
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
        # Exception: override amount from table, no forfeiture at 31.03.
        override = _get_vacation_carryover_override(user_id, year)
        effective_carryover = float(override["carryover_days"]) if override else carryover
        carryover_forfeited = 0.0
        carryover_started = 0.0
    else:
        # Standard: carryover forfeits at deadline if not started by then.
        carryover_started = float(_vacation_used_days_started_by(user_id, year, deadline_iso) or 0.0)
        if deadline_passed:
            effective_carryover = min(carryover, carryover_started)
        else:
            effective_carryover = carryover
        carryover_forfeited = max(0.0, carryover - effective_carryover)

    carryover_remaining = max(0.0, effective_carryover - used_total)
    entitlement_remaining = max(0.0, entitlement - max(0.0, used_total - effective_carryover))
    remaining_total = max(0.0, entitlement + effective_carryover - used_total)

    return {
        "entitlement": entitlement,
        "carryover": carryover,
        "effective_carryover": effective_carryover,
        "carryover_forfeited": carryover_forfeited,
        "carryover_started": carryover_started,
        "used_total": used_total,
        "entitlement_remaining": entitlement_remaining,
        "carryover_remaining": carryover_remaining,
        "remaining_total": remaining_total,
        "deadline": deadline_iso,
        "deadline_passed": deadline_passed,
        "carryover_exception": bool(carryover_exception),
        "carryover_exception_days": effective_carryover if carryover_exception else 0.0,
    }


def _ensure_balance_table(db: sqlite3.Connection) -> None:
    db.execute("""
    CREATE TABLE IF NOT EXISTS user_balance (
        user_id INTEGER PRIMARY KEY,
        start_minutes INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    db.commit()


def _get_start_balance_minutes(user_id: int) -> int:
    db = connect()
    try:
        _ensure_balance_table(db)
        row = db.execute("SELECT start_minutes FROM user_balance WHERE user_id=?", (user_id,)).fetchone()
        return int(row["start_minutes"]) if row else 0
    finally:
        db.close()


def _set_start_balance_minutes(user_id: int, start_minutes: int) -> None:
    db = connect()
    try:
        _ensure_balance_table(db)
        db.execute(
            "INSERT INTO user_balance(user_id, start_minutes, updated_at) VALUES(?,?,datetime('now')) "
            "ON CONFLICT(user_id) DO UPDATE SET start_minutes=excluded.start_minutes, updated_at=datetime('now')",
            (user_id, int(start_minutes)),
        )
        db.commit()
    finally:
        db.close()
def _workday_bit(weekday: int) -> int:
    # weekday: Monday=0 .. Sunday=6
    return 1 << weekday




def _table_cols(table: str) -> set[str]:
    db = connect()
    cols = set()
    try:
        for r in db.execute(f"PRAGMA table_info({table})").fetchall():
            cols.add(r["name"])
    finally:
        db.close()
    return cols


def _coerce_minutes(val) -> int:
    """Accepts int/float, numeric strings, or HH:MM strings."""
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip()
    if not s:
        return 0
    if ":" in s:
        try:
            return _minutes_from_hhmm(s)
        except Exception:
            return 0
    try:
        return int(float(s))
    except Exception:
        return 0



def _days_with_any_entry(user_id: int, start_iso: str, end_iso: str) -> set[str]:
    """Return ISO days that have any user-owned entry (time blocks, presence, or absences) in [start,end]."""
    days: set[str] = set()
    db = connect()
    try:
        # time blocks
        if "day" in _table_cols("time_blocks"):
            for r in db.execute(
                "SELECT DISTINCT day FROM time_blocks WHERE user_id=? AND day BETWEEN ? AND ?",
                (user_id, start_iso, end_iso),
            ).fetchall():
                days.add(str(r["day"]))

        # presence
        if "day" in _table_cols("daily_presence"):
            for r in db.execute(
                "SELECT DISTINCT day FROM daily_presence WHERE user_id=? AND day BETWEEN ? AND ?",
                (user_id, start_iso, end_iso),
            ).fetchall():
                days.add(str(r["day"]))

        # absences (schema varies)
        acols = _table_cols("absences")
        if acols:
            if "day" in acols:
                for r in db.execute(
                    "SELECT DISTINCT day FROM absences WHERE user_id=? AND day BETWEEN ? AND ?",
                    (user_id, start_iso, end_iso),
                ).fetchall():
                    days.add(str(r["day"]))
            elif "date" in acols:
                for r in db.execute(
                    "SELECT DISTINCT date FROM absences WHERE user_id=? AND date BETWEEN ? AND ?",
                    (user_id, start_iso, end_iso),
                ).fetchall():
                    days.add(str(r["date"]))
            elif "date_from" in acols and "date_to" in acols:
                rows = db.execute(
                    "SELECT date_from, date_to FROM absences WHERE user_id=? AND NOT (date_to < ? OR date_from > ?)",
                    (user_id, start_iso, end_iso),
                ).fetchall()
                sd = datetime.date.fromisoformat(start_iso)
                ed = datetime.date.fromisoformat(end_iso)
                for r in rows:
                    d0 = datetime.date.fromisoformat(str(r["date_from"]))
                    d1 = datetime.date.fromisoformat(str(r["date_to"]))
                    if d0 < sd:
                        d0 = sd
                    if d1 > ed:
                        d1 = ed
                    dcur = d0
                    while dcur <= d1:
                        days.add(dcur.isoformat())
                        dcur += datetime.timedelta(days=1)
    finally:
        db.close()
    return days


def _get_calendar_day_row(iso_day: str) -> dict:
    cols = _table_cols("calendar_days")
    sel = ["day"]
    if "is_weekend" in cols:
        sel.append("COALESCE(is_weekend,0) AS is_weekend")
    else:
        sel.append("0 AS is_weekend")
    if "is_holiday" in cols:
        sel.append("COALESCE(is_holiday,0) AS is_holiday")
    else:
        sel.append("0 AS is_holiday")

    # holiday name column can vary
    if "holiday_name" in cols:
        sel.append("COALESCE(holiday_name,'') AS holiday_name")
    elif "name" in cols:
        sel.append("COALESCE(name,'') AS holiday_name")
    else:
        sel.append("'' AS holiday_name")

    db = connect()
    row = db.execute(f"SELECT {', '.join(sel)} FROM calendar_days WHERE day=?", (iso_day,)).fetchone()
    db.close()
    d = dict(row) if row else {"day": iso_day, "is_weekend": 0, "is_holiday": 0, "holiday_name": ""}
    # fallback weekend compute if column missing/0
    try:
        if "is_weekend" not in cols:
            wd = datetime.date.fromisoformat(iso_day).weekday()
            d["is_weekend"] = 1 if wd >= 5 else 0
    except Exception:
        pass
    return d


def _blocked_by_calendar(iso_day: str) -> bool:
    cd = _get_calendar_day_row(iso_day)
    return bool(int(cd.get("is_weekend", 0))) or bool(int(cd.get("is_holiday", 0)))


def _week_dates_from(iso_day: str):
    d = datetime.date.fromisoformat(iso_day)
    monday = d - datetime.timedelta(days=d.weekday())
    return [monday + datetime.timedelta(days=i) for i in range(7)]


def _weekday_col(d: datetime.date) -> str:
    return ["mon_minutes","tue_minutes","wed_minutes","thu_minutes","fri_minutes","sat_minutes","sun_minutes"][d.weekday()]


def _mask_allows(mask: int, weekday: int) -> bool:
    return bool(int(mask) & _workday_bit(int(weekday)))


def _absence_on_day(user_id: int, iso_day: str) -> bool:
    cols = _table_cols("absences") if "absences" in _table_cols.__globals__ else set()
    # If table doesn't exist, no absence
    if not cols:
        db = connect()
        try:
            db.execute("SELECT 1 FROM absences LIMIT 1")
        except Exception:
            db.close()
            return False
        else:
            db.close()
            cols = _table_cols("absences")

    db = connect()
    try:
        if "day" in cols:
            row = db.execute("SELECT 1 FROM absences WHERE user_id=? AND day=? LIMIT 1", (user_id, iso_day)).fetchone()
            return bool(row)
        if "date" in cols:
            row = db.execute("SELECT 1 FROM absences WHERE user_id=? AND date=? LIMIT 1", (user_id, iso_day)).fetchone()
            return bool(row)
        if "date_from" in cols and "date_to" in cols:
            row = db.execute(
                "SELECT 1 FROM absences WHERE user_id=? AND date_from<=? AND date_to>=? LIMIT 1",
                (user_id, iso_day, iso_day),
            ).fetchone()
            return bool(row)
        # fallback: no compatible columns -> treat as none
        return False
    finally:
        db.close()


def _expected_minutes_for_day(user_id: int, iso_day: str) -> int:
    # manual override has priority (if set)
    ov = _get_expected_override_minutes(user_id, iso_day)
    if ov is not None:
        return max(0, int(ov))
    sched = _normalize_schedule(_get_user_schedule_for_day(user_id, iso_day))

    if int(sched.get("block_weekends_holidays", 1)) == 1 and _blocked_by_calendar(iso_day):
        return 0

    d = datetime.date.fromisoformat(iso_day)
    wd = d.weekday()

    mask = int(sched.get("workdays_mask", _default_workdays_mask()))
    if not _mask_allows(mask, wd):
        return 0

    if _absence_on_day(user_id, iso_day):
        return 0

    mode = (sched.get("mode") or "weekly").strip().lower()
    if mode == "daily":
        return int(sched.get(_weekday_col(d), 0) or 0)

    weekly = int(sched.get("weekly_minutes", 0) or 0)
    week_days = _week_dates_from(iso_day)

    eligible = []
    for wd_day in week_days:
        w = wd_day.weekday()
        if not _mask_allows(mask, w):
            continue
        eligible.append(wd_day)

    if not eligible:
        return 0

    base = weekly // len(eligible)
    rem = weekly % len(eligible)
    eligible = sorted(eligible)
    if d not in eligible:
        return 0
    idx = eligible.index(d)
    return base + (1 if idx < rem else 0)



def _scheduled_minutes_ignoring_absence(user_id: int, iso_day: str) -> int:
    """Like _expected_minutes_for_day but skips the absence check.
    Used to compute the Flextag deduction (how many minutes would have been required)."""
    ov = _get_expected_override_minutes(user_id, iso_day)
    if ov is not None:
        return max(0, int(ov))
    sched = _normalize_schedule(_get_user_schedule_for_day(user_id, iso_day))
    if int(sched.get("block_weekends_holidays", 1)) == 1 and _blocked_by_calendar(iso_day):
        return 0
    d = datetime.date.fromisoformat(iso_day)
    wd = d.weekday()
    mask = int(sched.get("workdays_mask", _default_workdays_mask()))
    if not _mask_allows(mask, wd):
        return 0
    mode = (sched.get("mode") or "weekly").strip().lower()
    if mode == "daily":
        return int(sched.get(_weekday_col(d), 0) or 0)
    weekly = int(sched.get("weekly_minutes", 0) or 0)
    week_days = _week_dates_from(iso_day)
    eligible = []
    for wd_day in week_days:
        w = wd_day.weekday()
        if not _mask_allows(mask, w):
            continue
        eligible.append(wd_day)
    if not eligible:
        return 0
    base = weekly // len(eligible)
    rem = weekly % len(eligible)
    eligible = sorted(eligible)
    if d not in eligible:
        return 0
    idx = eligible.index(d)
    return base + (1 if idx < rem else 0)


def _fetch_flextag_ranges(user_id: int) -> list:
    """Return list of (date_from, date_to) for all Flextag (Sonstige/Flextag) absences."""
    db = connect()
    try:
        rows = db.execute("""
            SELECT a.date_from, a.date_to
            FROM absences a JOIN absence_types t ON a.type_id = t.id
            WHERE a.user_id = ? AND t.name = 'Sonstige'
              AND LOWER(TRIM(COALESCE(a.comment,''))) = 'flextag'
        """, (user_id,)).fetchall()
        return [(r["date_from"], r["date_to"]) for r in rows]
    finally:
        db.close()


def _is_flextag(iso_day: str, flextag_ranges: list) -> bool:
    return any(df <= iso_day <= dt for df, dt in flextag_ranges)


def _absence_summary_for_period(user_id: int, start_iso: str, end_iso: str) -> dict:
    """Count absence workdays by type/remark, split into past (< today) and planned (>= today)."""
    today_iso = datetime.date.today().isoformat()
    db = connect()
    try:
        absences = db.execute("""
            SELECT a.date_from, a.date_to, a.comment, t.name AS type_name
            FROM absences a JOIN absence_types t ON a.type_id = t.id
            WHERE a.user_id = ? AND a.date_to >= ? AND a.date_from <= ?
            ORDER BY a.date_from
        """, (user_id, start_iso, end_iso)).fetchall()
    finally:
        db.close()

    past: dict = {"urlaub": 0, "krank": 0, "sonstige": {}}
    planned: dict = {"urlaub": 0, "sonstige": {}}

    for iso in _iter_days(start_iso, end_iso):
        sched = _normalize_schedule(_get_user_schedule_for_day(user_id, iso))
        mask = int(sched.get("workdays_mask", _default_workdays_mask()))
        d = datetime.date.fromisoformat(iso)
        if not _mask_allows(mask, d.weekday()):
            continue
        if int(sched.get("block_weekends_holidays", 1)) == 1 and _blocked_by_calendar(iso):
            continue
        for ab in absences:
            if ab["date_from"] <= iso <= ab["date_to"]:
                t = ab["type_name"]
                if iso < today_iso:
                    if t == "Urlaub":
                        past["urlaub"] += 1
                    elif t == "Krank":
                        past["krank"] += 1
                    elif t == "Sonstige":
                        remark = (ab["comment"] or "").strip()
                        past["sonstige"][remark] = past["sonstige"].get(remark, 0) + 1
                else:
                    if t == "Urlaub":
                        planned["urlaub"] += 1
                    elif t == "Sonstige":
                        remark = (ab["comment"] or "").strip()
                        planned["sonstige"][remark] = planned["sonstige"].get(remark, 0) + 1
                break

    return {"past": past, "planned": planned}


# ─── Periodenabschluss (Monats- / Jahresabschluss) ───────────────────────────

LOCK_MSG = "Zeitraum ist abgeschlossen und kann nicht mehr bearbeitet werden."
START_DATE_MSG = "Datum liegt vor dem Arbeitsbeginn ({})."


def _is_day_locked(user_id: int, iso_day: str) -> bool:
    """Return True if the month (or year) containing iso_day is locked."""
    year = int(iso_day[:4])
    month = int(iso_day[5:7])
    db = connect()
    try:
        row = db.execute(
            "SELECT 1 FROM period_locks WHERE user_id=? AND year=? "
            "AND (period_type='year' OR (period_type='month' AND month=?)) LIMIT 1",
            (user_id, year, month),
        ).fetchone()
        return bool(row)
    except Exception:
        return False
    finally:
        db.close()


def _is_range_locked(user_id: int, date_from: str, date_to: str) -> bool:
    """Return True if any month spanned by date_from..date_to is locked."""
    try:
        y, m = int(date_from[:4]), int(date_from[5:7])
        ye, me = int(date_to[:4]), int(date_to[5:7])
        db = connect()
        try:
            while (y, m) <= (ye, me):
                row = db.execute(
                    "SELECT 1 FROM period_locks WHERE user_id=? AND year=? "
                    "AND (period_type='year' OR (period_type='month' AND month=?)) LIMIT 1",
                    (user_id, y, m),
                ).fetchone()
                if row:
                    return True
                m += 1
                if m > 12:
                    m, y = 1, y + 1
            return False
        finally:
            db.close()
    except Exception:
        return False


def _lock_period(user_id: int, year: int, month: int | None, locked_by: int) -> None:
    ptype = "month" if month is not None else "year"
    db = connect()
    try:
        db.execute(
            "INSERT OR IGNORE INTO period_locks(user_id,period_type,year,month,locked_at,locked_by) "
            "VALUES(?,?,?,?,datetime('now'),?)",
            (user_id, ptype, year, month, locked_by),
        )
        db.commit()
    finally:
        db.close()


def _unlock_period(user_id: int, year: int, month: int | None) -> None:
    db = connect()
    try:
        if month is not None:
            db.execute(
                "DELETE FROM period_locks WHERE user_id=? AND period_type='month' AND year=? AND month=?",
                (user_id, year, month),
            )
        else:
            db.execute(
                "DELETE FROM period_locks WHERE user_id=? AND year=? AND period_type='year'",
                (user_id, year),
            )
        db.commit()
    finally:
        db.close()


def _get_period_lock_status(user_id: int, year: int) -> dict:
    """Return dict: 'year' → lock row  or  'YYYY-MM' → lock row."""
    db = connect()
    try:
        rows = db.execute(
            "SELECT period_type, year, month, locked_at, locked_by "
            "FROM period_locks WHERE user_id=? AND year=?",
            (user_id, year),
        ).fetchall()
    finally:
        db.close()
    status: dict = {}
    for r in rows:
        if r["period_type"] == "year":
            status["year"] = dict(r)
        else:
            status[f"{year}-{r['month']:02d}"] = dict(r)
    return status


def _normalize_schedule(s: dict) -> dict:
    """Make sure schedule dict contains expected keys even on legacy DB schemas."""
    if s is None:
        return {}
    # weekly_minutes fallback
    if "weekly_minutes" not in s or s.get("weekly_minutes") is None:
        if "weekly_hours" in s and s.get("weekly_hours") is not None:
            try:
                s["weekly_minutes"] = int(float(s["weekly_hours"]) * 60)
            except Exception:
                s["weekly_minutes"] = 0
        else:
            s["weekly_minutes"] = 0
    # valid_from fallback
    if "valid_from" not in s or not s.get("valid_from"):
        s["valid_from"] = datetime.date.today().isoformat()
    # mode fallback
    if "mode" not in s or not s.get("mode"):
        s["mode"] = "weekly"
    # workdays_mask fallback
    if "workdays_mask" not in s or s.get("workdays_mask") is None:
        s["workdays_mask"] = _default_workdays_mask()
    # per-day minutes fallbacks
    for k in ["mon_minutes","tue_minutes","wed_minutes","thu_minutes","fri_minutes","sat_minutes","sun_minutes"]:
        if k not in s or s.get(k) is None:
            s[k] = 0
    if "block_weekends_holidays" not in s or s.get("block_weekends_holidays") is None:
        s["block_weekends_holidays"] = 1
    return s

def _get_user_schedule_current(user_id: int) -> dict:
    """Return latest schedule (by valid_from). Ensure at least one exists."""
    db = connect()
    wcol = _schedule_weekly_col(db)

    row = db.execute(
        """SELECT * FROM user_schedules
           WHERE user_id=?
           ORDER BY valid_from DESC
           LIMIT 1""",
        (user_id,),
    ).fetchone()

    if not row:
        # create a default schedule starting today (Mon-Fri, 40h/week, block weekends/holidays)
        today = datetime.date.today().isoformat()
        workdays_mask = 0
        for wd in [0, 1, 2, 3, 4]:  # Mon-Fri
            workdays_mask |= (1 << wd)

        db.execute(
            f"""INSERT INTO user_schedules (
                user_id, valid_from, mode, {wcol}, workdays_mask,
                mon_minutes, tue_minutes, wed_minutes, thu_minutes, fri_minutes, sat_minutes, sun_minutes,
                block_weekends_holidays
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                user_id, today, "weekly", 40 * 60, workdays_mask,
                8 * 60, 8 * 60, 8 * 60, 8 * 60, 8 * 60, 0, 0,
                1,
            ),
        )
        db.commit()
        row = db.execute(
            """SELECT * FROM user_schedules
               WHERE user_id=?
               ORDER BY valid_from DESC
               LIMIT 1""",
            (user_id,),
        ).fetchone()

    d = dict(row)
    if 'weekly_minutes' not in d and 'week_minutes' in d:
        d['weekly_minutes'] = d['week_minutes']
    return d

def _get_user_schedule_for_day(user_id: int, iso_day: str) -> dict:
    """Return schedule applicable for a given ISO date (YYYY-MM-DD)."""
    db = connect()
    row = db.execute(
        """
        SELECT * FROM user_schedules
        WHERE user_id=? AND valid_from <= ?
        ORDER BY valid_from DESC
        LIMIT 1
        """,
        (user_id, iso_day),
    ).fetchone()
    db.close()
    if not row:
        return _get_user_schedule_current(user_id)
    return _normalize_schedule(dict(row))




def _get_user_schedules_all(user_id: int):
    """Return all schedules for a user ordered by valid_from DESC (if available)."""
    db = connect()
    cols = [r["name"] for r in db.execute("PRAGMA table_info(user_schedules)").fetchall()]
    colset = set(cols)

    order = "id DESC"
    if "valid_from" in colset:
        order = "valid_from DESC, id DESC"
    elif "created_at" in colset:
        order = "created_at DESC, id DESC"

    rows = db.execute(f"SELECT * FROM user_schedules WHERE user_id=? ORDER BY {order}", (user_id,)).fetchall()
    db.close()
    out = []
    for r in rows:
        try:
            out.append(dict(r))
        except Exception:
            out.append({k: r[k] for k in r.keys()})
    return out


def _workdays_str(mask: int) -> str:
    days = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    parts = []
    for i, d in enumerate(days):
        if int(mask) & _workday_bit(i):
            parts.append(d)
    return " ".join(parts) if parts else "-"
# Backward compatible alias (some code paths may still call _get_user_schedule)
def _get_user_schedule(user_id: int, iso_day: str | None = None) -> dict:
    if iso_day:
        return _get_user_schedule_for_day(user_id, iso_day)
    return _get_user_schedule_current(user_id)

def _default_workdays_mask() -> int:
    # Mon-Fri
    return sum(_workday_bit(i) for i in range(5))


def _parse_sched_form(form) -> dict:
    """Parse schedule form fields into a normalized dict."""
    valid_from = _parse_date_input(form.get("valid_from") or "") or ""
    mode = (form.get("mode") or "weekly").strip().lower()
    if mode not in ("weekly", "daily"):
        mode = "weekly"
    weekly_hours_raw = (form.get("weekly_hours") or "0").strip().replace(",", ".")
    try:
        weekly_minutes = int(round(float(weekly_hours_raw) * 60))
    except Exception:
        weekly_minutes = 0
    mask = 0
    for i, key in enumerate(["wd_mon", "wd_tue", "wd_wed", "wd_thu", "wd_fri", "wd_sat", "wd_sun"]):
        if (form.get(key) or "") == "1":
            mask |= _workday_bit(i)
    block = 1 if (form.get("block_weekends_holidays") or "") == "1" else 0

    def dm(name):
        raw = (form.get(name) or "").strip()
        return _coerce_minutes(raw) if raw else 0

    return {
        "valid_from": valid_from,
        "mode": mode,
        "weekly_minutes": weekly_minutes,
        "workdays_mask": mask,
        "block_weekends_holidays": block,
        "mon_minutes": dm("mon"),
        "tue_minutes": dm("tue"),
        "wed_minutes": dm("wed"),
        "thu_minutes": dm("thu"),
        "fri_minutes": dm("fri"),
        "sat_minutes": dm("sat"),
        "sun_minutes": dm("sun"),
    }


def _sched_save_to_db(user_id: int, sched_dict: dict) -> None:
    """Upsert a schedule row for user_id. sched_dict must contain valid_from."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    row = {"user_id": int(user_id), "updated_at": now, **sched_dict}
    db = connect()
    cols = [r["name"] for r in db.execute("PRAGMA table_info(user_schedules)").fetchall()]
    row = {k: v for k, v in row.items() if k in cols}
    if "created_at" in cols and "created_at" not in row:
        row["created_at"] = now
    db.execute("DELETE FROM user_schedules WHERE user_id=? AND valid_from=?", (row["user_id"], row["valid_from"]))
    col_list = ", ".join(row.keys())
    ph_list = ", ".join(["?"] * len(row))
    db.execute(f"INSERT INTO user_schedules ({col_list}) VALUES ({ph_list})", list(row.values()))
    db.commit()
    db.close()


def _sched_form_html(sched, action_url: str, back_url: str, show_auto_breaks: bool = False,
                     auto_breaks_enabled: bool = False) -> str:
    """Return the complete <form> HTML for creating/editing a schedule."""
    def chk(bit):
        return "checked" if (int(sched.get("workdays_mask", 0)) & bit) else ""

    def hm(mins):
        return _fmt_minutes(int(mins or 0))

    vf = sched.get("valid_from") or datetime.date.today().isoformat()
    mode = (sched.get("mode") or "weekly").lower()
    wh = f"{(int(sched.get('weekly_minutes', 0)) / 60):g}"
    block_chk = "checked" if int(sched.get("block_weekends_holidays", 1)) else ""

    auto_breaks_html = ""
    if show_auto_breaks:
        auto_breaks_html = f"""
<div style="margin-bottom:10px;">
  <label><b>Automatische Pausen</b></label><br>
  <label><input type="checkbox" name="auto_breaks" value="1" {"checked" if auto_breaks_enabled else ""}> Mindestpausen automatisch setzen (ab 6:00 → 30 min, ab 9:30 → 45 min)</label>
</div>"""

    return f"""
      <form method="post" action="{_html.escape(action_url)}">
        <div style="margin-bottom:10px;">
          <label><b>Gültig ab</b></label><br>
          {_date_input("valid_from", vf, required=True)}
          <div class="small" style="color:#777;">Ab diesem Datum wird dieses Zeitschema angewendet.</div>
        </div>
        {auto_breaks_html}
        <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:10px;">
          <div>
            <label><b>Modus</b></label><br>
            <label><input type="radio" name="mode" value="weekly" {"checked" if mode=="weekly" else ""}> Wochenarbeitszeit verteilen</label><br>
            <label><input type="radio" name="mode" value="daily" {"checked" if mode=="daily" else ""}> Sollstunden je Wochentag</label>
          </div>
          <div>
            <label><b>Wochenarbeitszeit (Stunden)</b></label><br>
            <input type="number" name="weekly_hours" min="0" step="0.25" value="{wh}">
            <div class="small" style="color:#777;">Nur relevant im Modus "Wochenarbeitszeit verteilen".</div>
          </div>
        </div>
        <hr style="margin:12px 0;">
        <div style="margin-bottom:10px;">
          <label><b>Arbeitstage</b></label><br>
          <label><input type="checkbox" name="wd_mon" value="1" {chk(1)}> Mo</label>
          <label><input type="checkbox" name="wd_tue" value="1" {chk(2)}> Di</label>
          <label><input type="checkbox" name="wd_wed" value="1" {chk(4)}> Mi</label>
          <label><input type="checkbox" name="wd_thu" value="1" {chk(8)}> Do</label>
          <label><input type="checkbox" name="wd_fri" value="1" {chk(16)}> Fr</label>
          <label><input type="checkbox" name="wd_sat" value="1" {chk(32)}> Sa</label>
          <label><input type="checkbox" name="wd_sun" value="1" {chk(64)}> So</label>
        </div>
        <div style="margin-bottom:10px;">
          <label><input type="checkbox" name="block_weekends_holidays" value="1" {block_chk}> Arbeiten an Wochenende/Feiertag blockieren (Standard)</label>
        </div>
        <hr style="margin:12px 0;">
        <div class="card" style="background:#fafafa;">
          <h4 style="margin-top:0;">Sollstunden je Wochentag (nur Modus "Sollstunden je Wochentag")</h4>
          <div style="display:flex;gap:10px;flex-wrap:wrap;">
            <div>Mo<br><input type="text" name="mon" value="{hm(sched.get('mon_minutes'))}" style="width:90px;"></div>
            <div>Di<br><input type="text" name="tue" value="{hm(sched.get('tue_minutes'))}" style="width:90px;"></div>
            <div>Mi<br><input type="text" name="wed" value="{hm(sched.get('wed_minutes'))}" style="width:90px;"></div>
            <div>Do<br><input type="text" name="thu" value="{hm(sched.get('thu_minutes'))}" style="width:90px;"></div>
            <div>Fr<br><input type="text" name="fri" value="{hm(sched.get('fri_minutes'))}" style="width:90px;"></div>
            <div>Sa<br><input type="text" name="sat" value="{hm(sched.get('sat_minutes'))}" style="width:90px;"></div>
            <div>So<br><input type="text" name="sun" value="{hm(sched.get('sun_minutes'))}" style="width:90px;"></div>
          </div>
          <div class="small" style="color:#777;margin-top:6px;">Format: HH:MM (z. B. 07:30). Leer oder 00:00 = kein Soll.</div>
        </div>
        <div style="margin-top:12px;display:flex;gap:8px;">
          <button class="btn primary" type="submit">Speichern</button>
          <a class="btn" href="{_html.escape(back_url)}">Abbrechen</a>
        </div>
      </form>"""


def _is_holiday(iso_day: str) -> bool:
    try:
        db = connect()
        r = db.execute("SELECT is_holiday FROM calendar_days WHERE day=?", (iso_day,)).fetchone()
        db.close()
        return bool(r and int(r["is_holiday"]) == 1)
    except Exception:
        return False


def _is_weekend(iso_day: str) -> bool:
    d = datetime.date.fromisoformat(iso_day)
    return d.weekday() >= 5  # 5=Sat, 6=Sun


def _is_workday_for_user(iso_day: str, sched: dict) -> bool:
    d = datetime.date.fromisoformat(iso_day)
    mask = int(sched.get("workdays_mask") or 0)
    return (mask & _workday_bit(d.weekday())) != 0


def _target_minutes_for_day(iso_day: str, sched: dict) -> int:
    # if not a configured workday: 0
    if not _is_workday_for_user(iso_day, sched):
        return 0

    if str(sched.get("mode")) == "daily":
        wd = datetime.date.fromisoformat(iso_day).weekday()
        key = ["mon_minutes","tue_minutes","wed_minutes","thu_minutes","fri_minutes","sat_minutes","sun_minutes"][wd]
        return int(sched.get(key) or 0)

    # weekly mode: distribute weekly_minutes across configured workdays in that week (Mon..Sun) equally
    weekly = int(sched.get("weekly_minutes") or 0)
    # count workdays in week
    d = datetime.date.fromisoformat(iso_day)
    week_start = d - datetime.timedelta(days=d.weekday())
    cnt = 0
    for i in range(7):
        day = (week_start + datetime.timedelta(days=i)).isoformat()
        if _is_workday_for_user(day, sched):
            cnt += 1
    return int(round(weekly / cnt)) if cnt else 0

def _timepicker_datalist(id_name: str = "time_suggestions") -> str:
    # Suggestions 05:00–20:00 in 15-min steps. Input remains freely editable/overwritable.
    opts = []
    for h in range(5, 21):
        for m in (0, 15, 30, 45):
            if h == 20 and m > 0:
                continue
            opts.append(f"<option value='{h:02d}:{m:02d}'>")
    return f"<datalist id='{id_name}'>" + "".join(opts) + "</datalist>"


FORM_ASSETS_JS = ""

def _parse_date_input(s: str) -> str | None:
    """Accept TT.MM.JJJJ or YYYY-MM-DD, return YYYY-MM-DD or None."""
    s = (s or "").strip()
    m = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$', s)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s
    return None


def _fmt_date_de(iso: str | None, omit_year: bool = False) -> str:
    """YYYY-MM-DD → TT.MM.JJJJ (or TT.MM. if omit_year=True)."""
    if not iso:
        return ""
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', str(iso))
    if not m:
        return str(iso)
    return f"{m.group(3)}.{m.group(2)}." if omit_year else f"{m.group(3)}.{m.group(2)}.{m.group(1)}"


def _date_input(name: str, value_iso: str = "", required: bool = False, min_target: str = "") -> str:
    val_de = _fmt_date_de(value_iso) if value_iso else ""
    req = "required" if required else ""
    mta = f' data-min-target="{min_target}"' if min_target else ""
    return (
        f'<div class="dt-wrap"><input type="text" name="{name}" class="dt-text" '
        f'value="{val_de}" placeholder="TT.MM.JJJJ" maxlength="10" {req}{mta} '
        f'oninput="dt_text(this)">'
        f'<input type="date" class="dt-pick" value="{value_iso}" tabindex="-1" '
        f'onchange="dt_pick(this)"></div>'
    )


def _time_input(name: str, value: str = "", required: bool = False) -> str:
    req = "required" if required else ""
    return f'<input type="time" name="{name}" value="{value}" list="time_suggestions" {req}>'


def flash_html():
    msgs = session.pop("_flash", [])
    out = ""
    for category, text in msgs:
        out += f'<div class="flash {category}">{text}</div>'
    return out


def add_flash(text, category="success"):
    msgs = session.get("_flash", [])
    msgs.append((category, text))
    session["_flash"] = msgs


@app.get("/setup")
def setup():
    bootstrap()
    if has_users():
        return redirect(url_for("login"))
    body = f'''
    {flash_html()}
    {FORM_ASSETS_JS}

    <div class="card">
      <h3>Ersteinrichtung</h3>
      <p>Lege den ersten Admin-Benutzer an.</p>
      <form method="post" action="/setup">
        <div><label>Admin Username</label><br><input name="username" required></div><br>
        <div><label>Admin Passwort</label><br><input type="password" name="password" required></div><br>
        <button class="btn" type="submit">Admin anlegen</button>
      </form>
    </div>
    '''
    return render_template_string(layout("Setup", body, None, APP_VERSION))


@app.post("/setup")
def setup_post():
    bootstrap()
    if has_users():
        return redirect(url_for("login"))
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    if not username or not password:
        add_flash("Bitte Username und Passwort angeben.", "error")
        return redirect(url_for("setup"))
    create_user(username, password, is_admin=True, is_active=True, onboarding_done=1)
    add_flash("Admin angelegt. Bitte einloggen.", "success")
    return redirect(url_for("login"))


@app.get("/login")
def login():
    bootstrap()
    if not has_users():
        return redirect(url_for("setup"))
    nxt = request.args.get("next") or "/"
    body = f'''
    {flash_html()}
    <div class="card">
      <h3>Login</h3>
      <form method="post" action="/login">
        <input type="hidden" name="next" value="{nxt}">
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <div><label>Username</label><br><input name="username" required></div>
          <div><label>Passwort</label><br><input type="password" name="password" required></div>
        </div><br>
        <button class="btn" type="submit">Login</button>
      </form>
      <p class="small">DB: {db_path()}</p>
    </div>
    '''
    return render_template_string(layout("Login", body, None, APP_VERSION))


@app.post("/login")
def login_post():
    bootstrap()
    username = request.form.get("username") or ""
    password = request.form.get("password") or ""
    nxt = request.form.get("next") or "/"
    u = authenticate(username, password)
    if not u:
        add_flash("Login fehlgeschlagen.", "error")
        return redirect(url_for("login", next=nxt))
    session["user_id"] = u["id"]
    return redirect(nxt)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─── Onboarding Wizard ────────────────────────────────────────────────────────

def _onboarding_step_indicator(current_step: int) -> str:
    steps = ["Passwort", "Profil", "Zeitschema", "Urlaub", "Startsaldo", "Fertig"]
    items = []
    for i, label in enumerate(steps, 1):
        if i < current_step:
            style = "color:var(--ok);font-weight:700;"
            icon = "✓ "
        elif i == current_step:
            style = "font-weight:700;color:var(--ac);"
            icon = ""
        else:
            style = "color:var(--mu);"
            icon = ""
        items.append(f"<span style='{style}'>{icon}{i}. {label}</span>")
    sep = " <span style='color:var(--mu);'>·</span> "
    return f"<div style='display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:16px;font-size:13px;'>{sep.join(items)}</div>"


@app.get("/onboarding")
@login_required
def onboarding():
    bootstrap()
    u = current_user()
    if u.get("onboarding_done"):
        return redirect(url_for("index"))

    try:
        step = int(request.args.get("step") or 1)
    except (ValueError, TypeError):
        step = 1
    step = max(1, min(6, step))

    today = datetime.date.today()
    indicator = _onboarding_step_indicator(step)

    if step == 1:
        body = f"""
        {flash_html()}
        {FORM_ASSETS_JS}
        {indicator}
        <div class="card">
          <h3>Schritt 1 – Passwort ändern</h3>
          <p class="small">Bitte ändere dein temporäres Passwort.</p>
          <form method="post" action="/onboarding?step=1" style="display:flex;flex-direction:column;gap:10px;max-width:340px;margin-top:12px;">
            <div><label>Aktuelles Passwort</label><br><input type="password" name="current_password" required></div>
            <div><label>Neues Passwort</label><br><input type="password" name="new_password" required></div>
            <div><label>Wiederholung</label><br><input type="password" name="new_password2" required></div>
            <div><button class="btn primary" type="submit">Weiter →</button></div>
          </form>
        </div>
        """

    elif step == 2:
        dn = u.get("display_name") or ""
        em = u.get("email") or ""
        body = f"""
        {flash_html()}
        {indicator}
        <div class="card">
          <h3>Schritt 2 – Persönliche Daten</h3>
          <p class="small">Optional – kann jederzeit in den Einstellungen geändert werden.</p>
          <form method="post" action="/onboarding?step=2" style="display:flex;flex-direction:column;gap:10px;max-width:340px;margin-top:12px;">
            <div><label>Anzeigename</label><br><input name="display_name" value="{dn}" placeholder="Max Mustermann"></div>
            <div><label>E-Mail</label><br><input type="email" name="email" value="{em}" placeholder="max@example.com"></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary" type="submit">Weiter →</button>
              <a class="btn" href="/onboarding?step=3">Überspringen</a>
            </div>
          </form>
        </div>
        """

    elif step == 3:
        sched = _get_user_schedule_current(u["id"])

        def chk3(bit):
            return "checked" if (int(sched.get("workdays_mask", 31)) & bit) else ""

        def hm3(mins):
            return _fmt_minutes(int(mins or 0))

        body = f"""
        {flash_html()}
        {FORM_ASSETS_JS}
        {indicator}
        <div class="card">
          <h3>Schritt 3 – Zeitschema</h3>
          <p class="small">Dein Arbeitszeitmodell. Kann jederzeit in den Einstellungen angepasst werden.</p>
          <form method="post" action="/onboarding?step=3" style="margin-top:12px;">
            <div style="margin-bottom:10px;">
              <label><b>Gültig ab</b></label><br>
              {_date_input("valid_from", today.isoformat(), required=True)}
            </div>
            <div style="margin-bottom:10px;">
              <label><b>Modus</b></label><br>
              <label><input type="radio" name="mode" value="weekly" {"checked" if sched.get("mode","weekly")=="weekly" else ""}> Wochenarbeitszeit verteilen</label><br>
              <label><input type="radio" name="mode" value="daily" {"checked" if sched.get("mode")=="daily" else ""}> Sollstunden je Wochentag</label>
            </div>
            <div style="margin-bottom:10px;">
              <label><b>Wochenstunden</b></label><br>
              <input type="number" name="weekly_hours" min="0" step="0.25" value="{(int(sched.get('weekly_minutes',2400))/60):g}" style="width:120px;">
            </div>
            <div style="margin-bottom:10px;">
              <label><b>Arbeitstage</b></label><br>
              <label><input type="checkbox" name="wd_mon" value="1" {chk3(1)}> Mo</label>
              <label><input type="checkbox" name="wd_tue" value="1" {chk3(2)}> Di</label>
              <label><input type="checkbox" name="wd_wed" value="1" {chk3(4)}> Mi</label>
              <label><input type="checkbox" name="wd_thu" value="1" {chk3(8)}> Do</label>
              <label><input type="checkbox" name="wd_fri" value="1" {chk3(16)}> Fr</label>
              <label><input type="checkbox" name="wd_sat" value="1" {chk3(32)}> Sa</label>
              <label><input type="checkbox" name="wd_sun" value="1" {chk3(64)}> So</label>
            </div>
            <div class="card" style="margin-bottom:10px;">
              <b>Sollstunden je Wochentag</b> <span class="small">(nur Modus "je Wochentag")</span><br>
              <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;">
                <div>Mo<br><input type="text" name="mon" value="{hm3(sched['mon_minutes'])}" style="width:90px;"></div>
                <div>Di<br><input type="text" name="tue" value="{hm3(sched['tue_minutes'])}" style="width:90px;"></div>
                <div>Mi<br><input type="text" name="wed" value="{hm3(sched['wed_minutes'])}" style="width:90px;"></div>
                <div>Do<br><input type="text" name="thu" value="{hm3(sched['thu_minutes'])}" style="width:90px;"></div>
                <div>Fr<br><input type="text" name="fri" value="{hm3(sched['fri_minutes'])}" style="width:90px;"></div>
                <div>Sa<br><input type="text" name="sat" value="{hm3(sched['sat_minutes'])}" style="width:90px;"></div>
                <div>So<br><input type="text" name="sun" value="{hm3(sched['sun_minutes'])}" style="width:90px;"></div>
              </div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary" type="submit">Weiter →</button>
              <a class="btn" href="/onboarding?step=4">Überspringen</a>
            </div>
          </form>
        </div>
        """

    elif step == 4:
        vc = _vacation_calc(u["id"], today.year)
        body = f"""
        {flash_html()}
        {indicator}
        <div class="card">
          <h3>Schritt 4 – Urlaubskontingent {today.year}</h3>
          <p class="small">Dein jährlicher Urlaubsanspruch und Übertrag aus dem Vorjahr. Kann jederzeit in den Einstellungen angepasst werden.</p>
          <form method="post" action="/onboarding?step=4" style="display:flex;flex-direction:column;gap:10px;max-width:340px;margin-top:12px;">
            <div><label>Urlaubsanspruch (Tage/Jahr)</label><br>
              <input type="number" name="entitlement_days" step="0.5" min="0" value="{vc['entitlement']}" required></div>
            <div><label>Übertrag Vorjahr</label><br>
              <input type="number" name="carryover_days" step="0.5" min="0" value="{vc['carryover']}" required></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary" type="submit">Weiter →</button>
              <a class="btn" href="/onboarding?step=5">Überspringen</a>
            </div>
          </form>
        </div>
        """

    elif step == 5:
        tracking_start = u.get("tracking_start_date") or ""
        start_balance_minutes = _get_start_balance_minutes(u["id"])
        start_balance_txt = _fmt_minutes_signed(start_balance_minutes)
        body = f"""
        {flash_html()}
        {FORM_ASSETS_JS}
        {indicator}
        <div class="card">
          <h3>Schritt 5 – Erfassung ab &amp; Startsaldo</h3>
          <p class="small">Ab wann soll die Zeiterfassung beginnen und welchen Stundensaldo bringst du mit?</p>
          <form method="post" action="/onboarding?step=5" style="display:flex;flex-direction:column;gap:12px;max-width:380px;margin-top:12px;">
            <div>
              <label>Erfassung ab <span class="small">(leer = ab Jahresbeginn)</span></label><br>
              {_date_input("tracking_start_date", tracking_start)}
              <div class="small" style="color:#777;margin-top:4px;">Ab diesem Datum werden fehlende Einträge und der Saldo berechnet.</div>
            </div>
            <div>
              <label>Startsaldo Gleitzeit</label><br>
              <input type="text" name="start_balance" value="{start_balance_txt}" placeholder="+00:00" style="width:120px;">
              <div class="small" style="color:#777;margin-top:4px;">Überstunden die du mitbringst (z. B. +12:30 oder -01:15).</div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary" type="submit">Weiter →</button>
              <a class="btn" href="/onboarding?step=6">Überspringen</a>
            </div>
          </form>
        </div>
        """

    elif step == 6:
        sched = _get_user_schedule_for_day(u["id"], today.isoformat()) or {}
        vc = _vacation_calc(u["id"], today.year)
        start_balance_minutes = _get_start_balance_minutes(u["id"])
        tracking_start = _fmt_date_de(u.get("tracking_start_date")) or "ab Jahresbeginn"
        mode_txt = "Wochenarbeitszeit" if sched.get("mode") == "weekly" else "Je Wochentag"
        weekly_h = f"{(int(sched.get('weekly_minutes', 0))/60):g}h" if sched.get("weekly_minutes") else "—"
        dn = u.get("display_name") or u.get("username") or ""
        body = f"""
        {flash_html()}
        {indicator}
        <div class="card">
          <h3>Schritt 6 – Alles bereit!</h3>
          <p>Hallo <b>{dn}</b>, dein Konto ist konfiguriert.</p>
          <div style="display:flex;flex-direction:column;gap:6px;margin:14px 0;font-size:14px;">
            <div><b>Erfassung ab:</b> {tracking_start}</div>
            <div><b>Zeitschema:</b> {mode_txt}, {weekly_h}</div>
            <div><b>Urlaub {today.year}:</b> {vc['entitlement']:.1f} Tage + {vc['carryover']:.1f} Übertrag</div>
            <div><b>Startsaldo:</b> {_fmt_minutes_signed(start_balance_minutes)}</div>
          </div>
          <p class="small">Alle Einstellungen können jederzeit unter <b>Einstellungen</b> angepasst werden.</p>
          <form method="post" action="/onboarding?step=6" style="margin-top:14px;">
            <button class="btn primary" type="submit">Zeiterfassung starten →</button>
          </form>
        </div>
        """

    else:
        body = f"""<div class="card"><h3>Unbekannter Schritt</h3></div>"""

    return render_template_string(layout("Willkommen", body, u, APP_VERSION))


@app.post("/onboarding")
@login_required
def onboarding_post():
    bootstrap()
    u = current_user()
    if u.get("onboarding_done"):
        return redirect(url_for("index"))

    try:
        step = int(request.args.get("step") or 1)
    except (ValueError, TypeError):
        step = 1

    if step == 1:
        current_password = request.form.get("current_password") or ""
        new_password = (request.form.get("new_password") or "").strip()
        new_password2 = (request.form.get("new_password2") or "").strip()

        from auth import authenticate as _auth_check
        if not _auth_check(u["username"], current_password):
            add_flash("Aktuelles Passwort falsch.", "error")
            return redirect("/onboarding?step=1")
        if len(new_password) < 6:
            add_flash("Neues Passwort muss mindestens 6 Zeichen haben.", "error")
            return redirect("/onboarding?step=1")
        if new_password != new_password2:
            add_flash("Passwörter stimmen nicht überein.", "error")
            return redirect("/onboarding?step=1")
        set_password(u["id"], new_password)
        return redirect("/onboarding?step=2")

    elif step == 2:
        display_name = (request.form.get("display_name") or "").strip() or None
        email = (request.form.get("email") or "").strip() or None
        db = connect()
        db.execute(
            "UPDATE users SET display_name=?, email=?, updated_at=datetime('now') WHERE id=?",
            (display_name, email, u["id"]),
        )
        db.commit()
        db.close()
        return redirect("/onboarding?step=3")

    elif step == 3:
        valid_from = _parse_date_input(request.form.get("valid_from") or "") or ""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", valid_from):
            add_flash("Bitte ein gültiges Datum angeben.", "error")
            return redirect("/onboarding?step=3")
        mode = (request.form.get("mode") or "weekly").strip().lower()
        if mode not in ("weekly", "daily"):
            mode = "weekly"
        weekly_hours_raw = (request.form.get("weekly_hours") or "0").strip().replace(",", ".")
        try:
            weekly_minutes = int(round(float(weekly_hours_raw) * 60))
        except Exception:
            weekly_minutes = 0
        mask = 0
        for i, key in enumerate(["wd_mon", "wd_tue", "wd_wed", "wd_thu", "wd_fri", "wd_sat", "wd_sun"]):
            if (request.form.get(key) or "") == "1":
                mask |= _workday_bit(i)

        def _day_min(name):
            raw = (request.form.get(name) or "").strip()
            return _coerce_minutes(raw) if raw else 0

        row = {
            "user_id": int(u["id"]),
            "valid_from": valid_from,
            "mode": mode,
            "weekly_minutes": int(weekly_minutes),
            "workdays_mask": int(mask),
            "block_weekends_holidays": 1,
            "mon_minutes": _day_min("mon"),
            "tue_minutes": _day_min("tue"),
            "wed_minutes": _day_min("wed"),
            "thu_minutes": _day_min("thu"),
            "fri_minutes": _day_min("fri"),
            "sat_minutes": _day_min("sat"),
            "sun_minutes": _day_min("sun"),
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        db = connect()
        cols = [r["name"] for r in db.execute("PRAGMA table_info(user_schedules)").fetchall()]
        row = {k: v for k, v in row.items() if k in cols}
        db.execute("DELETE FROM user_schedules WHERE user_id=? AND valid_from=?", (row["user_id"], row["valid_from"]))
        col_list = ", ".join(row.keys())
        ph_list = ", ".join(["?"] * len(row))
        db.execute(f"INSERT INTO user_schedules ({col_list}) VALUES ({ph_list})", list(row.values()))
        db.commit()
        db.close()
        return redirect("/onboarding?step=4")

    elif step == 4:
        year = datetime.date.today().year
        try:
            entitlement = float(request.form.get("entitlement_days") or 0)
            carryover = float(request.form.get("carryover_days") or 0)
            if entitlement < 0 or carryover < 0:
                raise ValueError()
        except Exception:
            add_flash("Bitte gültige Werte eingeben.", "error")
            return redirect("/onboarding?step=4")
        _set_vacation_year(u["id"], year, entitlement, carryover)
        return redirect("/onboarding?step=5")

    elif step == 5:
        tracking_start_raw = (request.form.get("tracking_start_date") or "").strip()
        tracking_start_iso = _parse_date_input(tracking_start_raw) if tracking_start_raw else None
        start_balance_raw = (request.form.get("start_balance") or "").strip()
        try:
            start_minutes = _parse_signed_hhmm_to_minutes(start_balance_raw) if start_balance_raw else 0
        except Exception:
            add_flash("Startsaldo: Bitte +HH:MM oder -HH:MM angeben.", "error")
            return redirect("/onboarding?step=5")
        _set_start_balance_minutes(u["id"], start_minutes)
        if tracking_start_iso:
            db = connect()
            db.execute(
                "UPDATE users SET tracking_start_date=?, updated_at=datetime('now') WHERE id=?",
                (tracking_start_iso, u["id"]),
            )
            db.commit()
            db.close()
        return redirect("/onboarding?step=6")

    elif step == 6:
        db = connect()
        db.execute("UPDATE users SET onboarding_done=1, updated_at=datetime('now') WHERE id=?", (u["id"],))
        db.commit()
        db.close()
        return redirect(url_for("index"))

    return redirect("/onboarding?step=1")


def _get_missing_entry_days(user_id: int, year: int) -> set:
    """Return ISO dates of past workdays in `year` with no entry and not a holiday."""
    today = datetime.date.today()
    year_start = datetime.date(year, 1, 1).isoformat()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()

    # Respect tracking_start_date: don't flag days before tracking began
    db = connect()
    try:
        r = db.execute("SELECT tracking_start_date FROM users WHERE id=?", (user_id,)).fetchone()
        tracking_start = r["tracking_start_date"] if r else None
    finally:
        db.close()
    if tracking_start:
        year_start = max(year_start, tracking_start)

    if yesterday < year_start:
        return set()
    days_with = _days_with_any_entry(user_id, year_start, yesterday)
    db = connect()
    try:
        hol_days = {
            str(r["day"])[:10]
            for r in db.execute(
                "SELECT day FROM calendar_days WHERE day BETWEEN ? AND ? AND is_holiday=1",
                (year_start, yesterday),
            ).fetchall()
        }
    finally:
        db.close()
    missing = set()
    for iso in _iter_days(year_start, yesterday):
        if iso in days_with or iso in hol_days:
            continue
        if _is_workday_for_user(iso, _get_user_schedule_for_day(user_id, iso)):
            missing.add(iso)
    return missing


def _get_contoured_days(user_id: int, start_iso: str, end_iso: str) -> set:
    db = connect()
    try:
        return {
            str(r["day"])
            for r in db.execute(
                "SELECT day FROM contoured_days WHERE user_id=? AND day BETWEEN ? AND ?",
                (user_id, start_iso, end_iso),
            ).fetchall()
        }
    finally:
        db.close()


def _has_weekend_exception(user_id: int, day: str) -> bool:
    db = connect()
    try:
        return bool(db.execute(
            "SELECT 1 FROM weekend_exceptions WHERE user_id=? AND day=?", (user_id, day)
        ).fetchone())
    finally:
        db.close()


def _get_weekend_exception(user_id: int, day: str):
    db = connect()
    try:
        return db.execute(
            "SELECT note FROM weekend_exceptions WHERE user_id=? AND day=?", (user_id, day)
        ).fetchone()
    finally:
        db.close()


def _set_weekend_exception(user_id: int, day: str, note: str = "") -> None:
    db = connect()
    db.execute(
        "INSERT OR REPLACE INTO weekend_exceptions(user_id, day, note, created_at) VALUES(?,?,?,datetime('now'))",
        (user_id, day, note),
    )
    db.commit()
    db.close()


def _remove_weekend_exception(user_id: int, day: str) -> None:
    db = connect()
    db.execute("DELETE FROM weekend_exceptions WHERE user_id=? AND day=?", (user_id, day))
    db.commit()
    db.close()


def _get_weekend_exceptions_month(user_id: int, first_iso: str, last_iso: str) -> set:
    db = connect()
    try:
        return {
            str(r["day"])[:10]
            for r in db.execute(
                "SELECT day FROM weekend_exceptions WHERE user_id=? AND day BETWEEN ? AND ?",
                (user_id, first_iso, last_iso),
            ).fetchall()
        }
    finally:
        db.close()


def _get_tracking_start(user_id: int) -> "str | None":
    """Return user's tracking_start_date (ISO) or None."""
    db = connect()
    try:
        r = db.execute("SELECT tracking_start_date FROM users WHERE id=?", (user_id,)).fetchone()
        val = r["tracking_start_date"] if r else None
        return str(val)[:10] if val else None
    finally:
        db.close()


def _get_contouring_info(user_id: int) -> dict:
    """Return {'enabled': int, 'start_date': str|None} for user."""
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


def _before_start_date(user_id: int, iso_day: str) -> "str | None":
    """Return error message if iso_day is before user's tracking_start_date, else None."""
    start = _get_tracking_start(user_id)
    if start and iso_day < start:
        return START_DATE_MSG.format(_fmt_date_de(start))
    return None


def _range_before_start_date(user_id: int, date_from: str, date_to: str) -> "str | None":
    return _before_start_date(user_id, date_from)


def _get_max_contoured_day(user_id: int) -> "str | None":
    db = connect()
    try:
        r = db.execute(
            "SELECT MAX(day) AS m FROM contoured_days WHERE user_id=?", (user_id,)
        ).fetchone()
        return str(r["m"]) if r and r["m"] else None
    finally:
        db.close()


def _get_uncontoured_days(user_id: int, year: int) -> set:
    """Past days-with-entries in year that have not been contoured."""
    ci = _get_contouring_info(user_id)
    if not ci["enabled"]:
        return set()

    today = datetime.date.today()
    year_start = datetime.date(year, 1, 1).isoformat()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()

    db = connect()
    try:
        r = db.execute("SELECT tracking_start_date FROM users WHERE id=?", (user_id,)).fetchone()
        tracking_start = r["tracking_start_date"] if r else None
    finally:
        db.close()
    if tracking_start:
        year_start = max(year_start, tracking_start)
    if ci["start_date"]:
        year_start = max(year_start, ci["start_date"])

    if yesterday < year_start:
        return set()

    days_with = _days_with_any_entry(user_id, year_start, yesterday)
    contoured = _get_contoured_days(user_id, year_start, yesterday)
    return {iso for iso in days_with if year_start <= iso <= yesterday and iso not in contoured}


# -------------------------
# Kontierung API
# -------------------------

@app.post("/api/contour")
@login_required
def api_contour():
    from flask import jsonify
    u = current_user()
    ci = _get_contouring_info(u["id"])
    if not ci["enabled"]:
        return jsonify({"ok": False, "error": "Kontierung ist für diesen Account deaktiviert"}), 403
    data = request.get_json(force=True) or {}
    day = str(data.get("day") or "").strip()[:10]
    action = str(data.get("action") or "mark")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        return jsonify({"ok": False, "error": "Ungültiges Datum"}), 400
    if ci["start_date"] and day < ci["start_date"]:
        return jsonify({"ok": False, "error": "Tag liegt vor dem Kontierungsstartdatum"}), 400
    db = connect()
    try:
        if action == "mark":
            # Nur kontieren wenn Zeiteintrag oder Abwesenheit vorhanden
            has_block = db.execute(
                "SELECT 1 FROM time_blocks WHERE user_id=? AND day=? LIMIT 1", (u["id"], day)
            ).fetchone()
            has_absence = db.execute(
                "SELECT 1 FROM absences WHERE user_id=? AND date_from<=? AND date_to>=? LIMIT 1",
                (u["id"], day, day)
            ).fetchone()
            if not has_block and not has_absence:
                return jsonify({"ok": False, "error": "Kein Eintrag für diesen Tag"}), 400
            db.execute(
                "INSERT OR IGNORE INTO contoured_days(user_id, day) VALUES(?,?)",
                (u["id"], day),
            )
        else:
            db.execute("DELETE FROM contoured_days WHERE user_id=? AND day=?", (u["id"], day))
        db.commit()
    finally:
        db.close()
    return jsonify({"ok": True})


@app.post("/api/contour-until")
@login_required
def api_contour_until():
    from flask import jsonify
    u = current_user()
    ci = _get_contouring_info(u["id"])
    if not ci["enabled"]:
        return jsonify({"ok": False, "error": "Kontierung ist für diesen Account deaktiviert"}), 403
    data = request.get_json(force=True) or {}
    until = str(data.get("until") or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", until):
        return jsonify({"ok": False, "error": "Ungültiges Datum"}), 400
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    until = min(until, yesterday)

    db = connect()
    try:
        r = db.execute("SELECT tracking_start_date FROM users WHERE id=?", (u["id"],)).fetchone()
        tracking_start = r["tracking_start_date"] if r else None
    finally:
        db.close()

    year_start = f"{datetime.date.today().year}-01-01"
    if tracking_start:
        year_start = max(year_start, tracking_start)
    if ci["start_date"]:
        year_start = max(year_start, ci["start_date"])

    if until < year_start:
        return jsonify({"ok": True, "marked": 0})

    # Validate: until must not be before the user's first time_block entry
    db_check = connect()
    try:
        fb = db_check.execute(
            "SELECT MIN(day) AS d FROM time_blocks WHERE user_id=?", (u["id"],)
        ).fetchone()
        first_entry = str(fb["d"])[:10] if fb and fb["d"] else None
    finally:
        db_check.close()
    if first_entry and until < first_entry:
        return jsonify({"ok": False, "error": "Datum liegt vor dem ersten Eintrag"}), 400

    days_with = _days_with_any_entry(u["id"], year_start, until)
    db = connect()
    try:
        count = 0
        for iso in days_with:
            if year_start <= iso <= until:
                db.execute(
                    "INSERT OR IGNORE INTO contoured_days(user_id, day) VALUES(?,?)",
                    (u["id"], iso),
                )
                count += 1
        db.commit()
    finally:
        db.close()
    return jsonify({"ok": True, "marked": count})


@app.get("/api/contoured-days")
@login_required
def api_contoured_days_route():
    from flask import jsonify
    u = current_user()
    ci = _get_contouring_info(u["id"])
    if not ci["enabled"]:
        return jsonify({"ok": False, "error": "Kontierung ist für diesen Account deaktiviert"}), 403
    year = int(request.args.get("year") or datetime.date.today().year)
    start_iso = f"{year}-01-01"
    end_iso = f"{year}-12-31"
    days = sorted(_get_contoured_days(u["id"], start_iso, end_iso))
    max_day = _get_max_contoured_day(u["id"])
    return jsonify({"days": days, "max_day": max_day})


@app.post("/settings/contouring/toggle")
@login_required
def settings_contouring_toggle():
    bootstrap()
    u = current_user()
    ci = _get_contouring_info(u["id"])
    db = connect()
    if ci["enabled"]:
        db.execute(
            "UPDATE users SET contouring_enabled=0, contouring_start_date=NULL, updated_at=datetime('now') WHERE id=?",
            (u["id"],),
        )
        db.commit()
        db.close()
        add_flash("Kontierung wurde deaktiviert. Bestehende Kontierungen bleiben erhalten.", "success")
    else:
        start_date = _parse_date_input(request.form.get("contouring_start_date") or "")
        if not start_date:
            today = datetime.date.today()
            start_date = datetime.date(today.year, today.month, 1).isoformat()
        db.execute(
            "UPDATE users SET contouring_enabled=1, contouring_start_date=?, updated_at=datetime('now') WHERE id=?",
            (start_date, u["id"]),
        )
        db.commit()
        db.close()
        add_flash(f"Kontierung aktiviert ab {_fmt_date_de(start_date)}.", "success")
    return redirect("/settings")


@app.post("/api/set-exception")
@login_required
def api_set_exception():
    bootstrap()
    u = current_user()
    day = (request.form.get("day") or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        add_flash("Ungültiges Datum.", "error")
        return redirect("/calendar")
    note = (request.form.get("note") or "").strip()[:200]
    _set_weekend_exception(u["id"], day, note)
    add_flash(f"Ausnahme für {day} gesetzt – Zeitblöcke können jetzt eingetragen werden.", "success")
    return redirect(f"/day/{day}")


@app.post("/api/remove-exception")
@login_required
def api_remove_exception():
    bootstrap()
    u = current_user()
    day = (request.form.get("day") or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        add_flash("Ungültiges Datum.", "error")
        return redirect("/calendar")
    _remove_weekend_exception(u["id"], day)
    add_flash(f"Ausnahme für {day} entfernt.", "success")
    return redirect(f"/day/{day}")


@app.get("/")
@login_required
def index():
    bootstrap()
    u = current_user()
    today = datetime.date.today()

    # Saldo
    balance_minutes = _calc_balance_end_at(u["id"], today.isoformat())
    balance_str = _fmt_minutes_signed(balance_minutes)
    balance_color = "var(--ok)" if balance_minutes >= 0 else "var(--danger)"

    # Resturlaub
    year = today.year
    vc = _vacation_calc(u["id"], year)
    vac_hint = ""
    if vc.get("carryover_exception"):
        if vc["effective_carryover"] > 0:
            vac_hint = f" · <span style='color:#d97706;'>{vc['effective_carryover']:.1f} Tage Übertrag (gilt weiterhin)</span>"
    elif not vc["deadline_passed"] and vc["carryover"] > 0:
        vac_hint = f" · <span style='color:var(--danger);'>Übertrag verfällt am {vc['deadline']}</span>"
    elif vc["deadline_passed"] and vc["carryover_forfeited"] > 0:
        vac_hint = f" · <span style='color:var(--mu);'>{vc['carryover_forfeited']:.1f} Tage Übertrag verfallen</span>"

    # Fehlende Einträge
    missing_count = len(_get_missing_entry_days(u["id"], year))
    missing_color = "var(--danger)" if missing_count > 0 else "var(--ok)"

    # Kontierung
    contouring_info = _get_contouring_info(u["id"])
    contouring_enabled = contouring_info["enabled"]
    contouring_start = contouring_info["start_date"]
    uncontoured_count = len(_get_uncontoured_days(u["id"], year))
    uc_color = "var(--danger)" if uncontoured_count > 0 else "var(--ok)"
    max_contoured = _get_max_contoured_day(u["id"])
    max_contoured_str = _fmt_date_de(max_contoured) if max_contoured else "–"
    yesterday_iso = (today - datetime.timedelta(days=1)).isoformat()
    yesterday_de = _fmt_date_de(yesterday_iso)
    _db_tmp = connect()
    try:
        _fb = _db_tmp.execute(
            "SELECT MIN(day) AS d FROM time_blocks WHERE user_id=?", (u["id"],)
        ).fetchone()
        first_entry_iso = str(_fb["d"])[:10] if _fb and _fb["d"] else yesterday_iso
    finally:
        _db_tmp.close()
    if contouring_start:
        first_entry_iso = max(first_entry_iso, contouring_start)
    kontier_has_range = first_entry_iso <= yesterday_iso

    # Abwesenheiten Jahresübersicht
    ab_sum = _absence_summary_for_period(u["id"], f"{year}-01-01", f"{year}-12-31")

    def _ci_get(d: dict, key: str) -> int:
        kl = key.lower()
        return sum(v for k, v in d.items() if k.lower() == kl)

    past_urlaub   = ab_sum["past"]["urlaub"]
    planned_urlaub = ab_sum["planned"]["urlaub"]
    past_krank    = ab_sum["past"]["krank"]
    past_verdi    = _ci_get(ab_sum["past"]["sonstige"], "verdi")
    planned_verdi = _ci_get(ab_sum["planned"]["sonstige"], "verdi")
    past_flextag  = _ci_get(ab_sum["past"]["sonstige"], "flextag")
    planned_flextag = _ci_get(ab_sum["planned"]["sonstige"], "flextag")
    vac_available = int(round(vc["remaining_total"]))

    def _ab_cell(label: str, rows: list) -> str:
        content = "".join(
            f"<div style='display:flex;justify-content:space-between;gap:12px;'>"
            f"<span style='color:var(--mu);'>{k}</span><b>{v}</b></div>"
            for k, v in rows
        )
        return (
            f"<div style='background:var(--bg);border:1px solid var(--bd);"
            f"border-radius:var(--rs);padding:10px 12px;'>"
            f"<div style='font-size:11px;font-weight:600;text-transform:uppercase;"
            f"letter-spacing:.04em;color:var(--mu);margin-bottom:6px;'>{label}</div>"
            f"<div style='display:flex;flex-direction:column;gap:3px;font-size:13px;'>{content}</div>"
            f"</div>"
        )

    ab_cells = _ab_cell("Urlaub", [
        ("Genommen", past_urlaub),
        *([("Geplant", planned_urlaub)] if planned_urlaub else []),
        ("Verfügbar", vac_available),
    ])
    if past_krank:
        ab_cells += _ab_cell("Krank", [("Tage", past_krank)])
    if past_verdi or planned_verdi:
        ab_cells += _ab_cell("Verdi", [
            *([("Genommen", past_verdi)] if past_verdi else []),
            *([("Geplant", planned_verdi)] if planned_verdi else []),
        ])
    if past_flextag or planned_flextag:
        ab_cells += _ab_cell("Flextag", [
            *([("Genommen", past_flextag)] if past_flextag else []),
            *([("Geplant", planned_flextag)] if planned_flextag else []),
        ])

    if contouring_enabled:
        _kontiering_grid_card = f"""
      <div class="card" style="margin:0;">
        <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Kontierung {year}</div>
        {"" if not (contouring_start and contouring_start > today.isoformat()) else f"<div style='color:var(--mu);font-size:12px;margin-bottom:4px;'>ab <b style='color:var(--tx);'>{_fmt_date_de(contouring_start)}</b></div>"}
        <div style="font-size:2rem;font-weight:700;letter-spacing:-.02em;color:{uc_color};line-height:1.1;">{uncontoured_count} <span style="font-size:1rem;font-weight:400;color:var(--mu);">Tage</span></div>
        <div class="small" style="margin-top:2px;margin-bottom:8px;">bis: <b style="color:var(--tx);">{max_contoured_str}</b></div>
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <div class="dt-wrap" style="flex:1;min-width:90px;max-width:140px;">
            <input type="text" id="kontier-dt-text" class="dt-text"
                   value="{yesterday_de}" placeholder="TT.MM.JJJJ" maxlength="10"
                   style="font-size:12px;"
                   oninput="kontierDtText(this)">
            <input type="date" id="kontier-dt-pick" class="dt-pick"
                   value="{yesterday_iso}" min="{first_entry_iso}" max="{yesterday_iso}"
                   onchange="kontierDtPick(this)">
          </div>
          <button id="kontier-btn" class="btn primary" onclick="doKontieren()"
                  style="padding:5px 10px;font-size:13px;white-space:nowrap;"
                  {"" if kontier_has_range else "disabled"}>Kontieren</button>
        </div>
        <div id="kontier-toast" style="display:none;margin-top:8px;padding:6px 10px;
             background:var(--ok);color:#fff;border-radius:6px;font-size:12px;font-weight:600;"></div>
      </div>"""
    else:
        _kontiering_grid_card = """
      <div class="card" style="margin:0;opacity:.6;">
        <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Kontierung</div>
        <div style="font-size:15px;font-weight:600;color:var(--mu);">Deaktiviert</div>
        <div style="margin-top:8px;">
          <a class="btn" href="/settings" style="padding:5px 12px;font-size:13px;">Einstellungen</a>
        </div>
      </div>"""

    body = f'''
    {flash_html()}
<style>
.idx-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;margin-bottom:12px;}}
@media(min-width:1024px){{.idx-grid{{grid-template-columns:repeat(4,1fr);}}}}
</style>

    <div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;">
      <a class="btn primary" href="/day/{today.isoformat()}"
         style="flex:1;min-width:160px;padding:12px 16px;font-size:15px;text-align:center;">
        Zeiterfassung heute
      </a>
      <a class="btn primary" href="/calendar"
         style="padding:12px 16px;font-size:15px;white-space:nowrap;">
        Kalender
      </a>
    </div>

    <div class="idx-grid">

      <div class="card" style="margin:0;">
        <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Gleitzeitkonto</div>
        <div style="font-size:2rem;font-weight:700;letter-spacing:-.02em;color:{balance_color};line-height:1.1;">{balance_str}</div>
        <div style="margin-top:8px;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
          <span class="small">Stand heute</span>
          <a class="btn" href="/balance" style="padding:5px 12px;font-size:13px;">Details</a>
        </div>
      </div>

      <div class="card" style="margin:0;">
        <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Resturlaub {year}</div>
        <div style="font-size:2rem;font-weight:700;letter-spacing:-.02em;line-height:1.1;">{vc["remaining_total"]:.1f} <span style="font-size:1rem;font-weight:400;color:var(--mu);">Tage</span></div>
        <div style="margin-top:8px;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
          <span class="small">von {vc["entitlement"] + vc["effective_carryover"]:.1f} verfügbar{vac_hint}</span>
          <a class="btn" href="/settings/vacation" style="padding:5px 12px;font-size:13px;">Details</a>
        </div>
      </div>

      <div class="card" style="margin:0;">
        <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">Fehlende Einträge {year}</div>
        <div style="font-size:2rem;font-weight:700;letter-spacing:-.02em;color:{missing_color};line-height:1.1;">{missing_count} <span style="font-size:1rem;font-weight:400;color:var(--mu);">Tage</span></div>
        <div style="margin-top:8px;">
          <span class="small">vergangene Arbeitstage ohne Zeiteintrag</span>
        </div>
      </div>

      {_kontiering_grid_card}

    </div>

    <script>
    function kontierDtText(inp){{
      var m=inp.value.match(/^(\\d{{1,2}})\\.(\\d{{1,2}})\\.(\\d{{4}})$/);
      var pick=document.getElementById('kontier-dt-pick');
      if(m){{pick.value=m[3]+'-'+m[2].padStart(2,'0')+'-'+m[1].padStart(2,'0');}}
      else{{pick.value='';}}
      _validateKontier();
    }}
    function kontierDtPick(inp){{
      var dt=document.getElementById('kontier-dt-text');
      if(inp.value&&inp.value.length===10){{dt.value=inp.value.slice(8)+'.'+inp.value.slice(5,7)+'.'+inp.value.slice(0,4);}}
      _validateKontier();
    }}
    function _validateKontier(){{
      var pick=document.getElementById('kontier-dt-pick');
      if(!pick)return;
      var v=pick.value;
      var ok=v&&v>='{first_entry_iso}'&&v<='{yesterday_iso}';
      var btn=document.getElementById('kontier-btn');
      if(btn)btn.disabled=!ok;
    }}
    function doKontieren(){{
      var pick=document.getElementById('kontier-dt-pick');
      var until=pick.value;
      if(!until)return;
      var btn=document.getElementById('kontier-btn');
      btn.disabled=true;btn.textContent='Wird kontiert…';
      fetch('/api/contour-until',{{method:'POST',headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{until:until}})
      }}).then(function(r){{return r.json();}})
      .then(function(d){{
        btn.textContent='Kontieren';
        if(d.ok){{
          var dtxt=document.getElementById('kontier-dt-text').value;
          var toast=document.getElementById('kontier-toast');
          toast.textContent=(d.marked?d.marked+' Tage bis '+dtxt+' kontiert':'Alle Tage bereits kontiert');
          toast.style.display='block';
          setTimeout(function(){{location.reload();}},2200);
        }}else{{btn.disabled=false;}}
      }}).catch(function(){{btn.disabled=false;btn.textContent='Kontieren';}});
    }}
    _validateKontier();
    </script>

    <div class="card" style="margin-bottom:12px;">
      <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">Abwesenheiten {year}</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;">{ab_cells}</div>
      <div style="margin-top:10px;">
        <a class="btn" href="/absences" style="padding:5px 12px;font-size:13px;">Alle Abwesenheiten</a>
      </div>
    </div>
    '''
    return render_template_string(layout("Übersicht", body, u, APP_VERSION, show_back=False))



# -------------------------
# Anwesenheit / Tagesstatus
# -------------------------

@app.get("/presence")
@login_required
def presence_redirect():
    return redirect(url_for("balance_view"))



# -------------------------
# Gleitzeitkonto / Saldo
# -------------------------

def _actual_minutes_for_day(user_id: int, iso_day: str) -> int:
    """Return worked minutes for a day from time_blocks (preferred) or time_entries."""
    db = connect()
    try:
        cols_tb = set()
        try:
            cols_tb = _table_cols("time_blocks")
        except Exception:
            cols_tb = set()

        # Prefer time_blocks if schema is present
        if cols_tb and "day" in cols_tb and "time_in" in cols_tb and "time_out" in cols_tb:
            rows = db.execute(
                """
                SELECT time_in, time_out, break_minutes
                FROM time_blocks
                WHERE user_id=? AND day=?
                """,
                (user_id, iso_day),
            ).fetchall()
            total = 0
            for r in rows:
                try:
                    total += _minutes_from_hhmm(r["time_out"]) - _minutes_from_hhmm(r["time_in"]) - int(r["break_minutes"] or 0)
                except Exception:
                    pass
            return max(0, int(total))

        # Fallback: time_entries (one row per day)
        cols_te = set()
        try:
            cols_te = _table_cols("time_entries")
        except Exception:
            cols_te = set()

        if cols_te and "day" in cols_te and "time_in" in cols_te and "time_out" in cols_te:
            r = db.execute(
                """
                SELECT time_in, time_out, break_minutes
                FROM time_entries
                WHERE user_id=? AND day=?
                LIMIT 1
                """,
                (user_id, iso_day),
            ).fetchone()
            if not r:
                return 0
            try:
                return max(0, _minutes_from_hhmm(r["time_out"]) - _minutes_from_hhmm(r["time_in"]) - int(r["break_minutes"] or 0))
            except Exception:
                return 0

        return 0
    finally:
        db.close()


def _iter_days(start_iso: str, end_iso: str):
    sd = datetime.date.fromisoformat(start_iso)
    ed = datetime.date.fromisoformat(end_iso)
    d = sd
    while d <= ed:
        yield d.isoformat()
        d += datetime.timedelta(days=1)


def _calc_balance(user_id: int, start_iso: str, end_iso: str) -> dict:
    """Calculate balance details between two dates (inclusive)."""
    start_minutes = _get_start_balance_minutes(user_id)
    today_iso = datetime.date.today().isoformat()
    flextag_ranges = _fetch_flextag_ranges(user_id)

    rows = []
    running = int(start_minutes)

    for iso in _iter_days(start_iso, end_iso):
        expected = int(_expected_minutes_for_day(user_id, iso) or 0)
        actual = int(_actual_minutes_for_day(user_id, iso) or 0)
        flextag_min = 0
        if iso < today_iso and expected == 0 and _is_flextag(iso, flextag_ranges):
            flextag_min = _scheduled_minutes_ignoring_absence(user_id, iso)
        delta = int(actual - expected - flextag_min)
        running += delta
        rows.append({
            "day": iso,
            "expected": expected,
            "actual": actual,
            "delta": delta,
            "running": running,
            "flextag_min": flextag_min,
        })

    return {
        "start_minutes": int(start_minutes),
        "end_minutes": int(running),
        "rows": rows,
    }


def _render_absence_summary_card(user_id: int, start_iso: str, end_iso: str) -> str:
    summary = _absence_summary_for_period(user_id, start_iso, end_iso)
    past = summary["past"]
    planned = summary["planned"]

    def _sonstige_line(remark: str, n: int) -> str:
        label = remark if remark else "Sonstige (ohne Bemerkung)"
        suffix = " <span class='small' style='color:var(--ac);'>(vom Gleitzeitkonto)</span>" if remark.lower() == "flextag" else ""
        return f"<div><b>{label}:</b> {n} Tag{'e' if n != 1 else ''}{suffix}</div>"

    past_lines = []
    if past["urlaub"]:
        n = past["urlaub"]
        past_lines.append(f"<div><b>Urlaub:</b> {n} Arbeitstag{'e' if n != 1 else ''}</div>")
    if past["krank"]:
        n = past["krank"]
        past_lines.append(f"<div><b>Krank:</b> {n} Arbeitstag{'e' if n != 1 else ''}</div>")
    for remark, n in sorted(past["sonstige"].items()):
        past_lines.append(_sonstige_line(remark, n))

    planned_lines = []
    if planned["urlaub"]:
        n = planned["urlaub"]
        planned_lines.append(f"<div><b>Urlaub:</b> {n} Arbeitstag{'e' if n != 1 else ''}</div>")
    for remark, n in sorted(planned["sonstige"].items()):
        planned_lines.append(_sonstige_line(remark, n))

    if not past_lines and not planned_lines:
        return ""

    def _section(label: str, lines: list) -> str:
        rows = "".join(lines)
        return (
            f"<div style='flex:1;min-width:140px;'>"
            f"<div class='small' style='font-weight:600;text-transform:uppercase;"
            f"letter-spacing:.04em;margin-bottom:6px;'>{label}</div>"
            f"<div style='display:flex;flex-direction:column;gap:5px;'>{rows}</div>"
            f"</div>"
        )

    sections = ""
    if past_lines:
        sections += _section("Erfasst", past_lines)
    if planned_lines:
        sections += _section("Geplant", planned_lines)

    return f"""<div class="card" style="margin-top:12px;">
  <h3 style="margin-bottom:10px;">Abwesenheiten im Zeitraum</h3>
  <div style="display:flex;gap:24px;flex-wrap:wrap;">{sections}</div>
  <p class="small" style="margin-top:8px;">Nur Arbeitstage (ohne Wochenenden/Feiertage)</p>
</div>"""


@app.get("/balance")
@login_required
def balance_view():
    bootstrap()
    u = current_user()
    today = datetime.date.today()

    try:
        sel_year = int(request.args.get("y") or today.year)
    except (ValueError, TypeError):
        sel_year = today.year
    try:
        sel_month = int(request.args.get("m") if request.args.get("m") is not None else today.month)
    except (ValueError, TypeError):
        sel_month = today.month
    only = (request.args.get("only") or "").strip()

    # Available years: from earliest data entry to current year
    db = connect()
    try:
        row = db.execute("""
            SELECT MIN(y) AS min_y FROM (
                SELECT CAST(SUBSTR(day,1,4) AS INTEGER) AS y FROM time_blocks WHERE user_id=?
                UNION ALL
                SELECT CAST(SUBSTR(date_from,1,4) AS INTEGER) AS y FROM absences WHERE user_id=?
            ) t
        """, (u["id"], u["id"])).fetchone()
        min_year = int(row["min_y"]) if row and row["min_y"] else today.year
    except Exception:
        min_year = today.year
    db.close()
    min_year = min(min_year, today.year)
    available_years = list(range(min_year, today.year + 1))
    if sel_year not in available_years:
        sel_year = today.year
    if sel_month not in range(0, 13):
        sel_month = today.month

    # ── Kumulativer Saldo ab 01.01 des gewählten Jahres ──────────────────
    year_start = datetime.date(sel_year, 1, 1).isoformat()
    year_end   = min(datetime.date(sel_year, 12, 31), today).isoformat()
    # Respect tracking_start_date
    if u.get("tracking_start_date"):
        year_start = max(year_start, u["tracking_start_date"])
    today_iso  = today.isoformat()
    start_minutes = _get_start_balance_minutes(u["id"])
    flextag_ranges = _fetch_flextag_ranges(u["id"])
    running = int(start_minutes)
    all_rows: list[dict] = []
    for iso in _iter_days(year_start, year_end):
        expected = int(_expected_minutes_for_day(u["id"], iso) or 0)
        actual   = int(_actual_minutes_for_day(u["id"], iso) or 0)
        flextag_min = 0
        if iso < today_iso and expected == 0 and _is_flextag(iso, flextag_ranges):
            flextag_min = _scheduled_minutes_ignoring_absence(u["id"], iso)
        delta    = actual - expected - flextag_min
        running += delta
        all_rows.append({"day": iso, "expected": expected, "actual": actual,
                         "delta": delta, "running": running, "flextag_min": flextag_min})

    # ── Anzeigebereich bestimmen ─────────────────────────────────────────
    if sel_month == 0:
        display_start = year_start
        display_end   = year_end
        period_label  = f"Gesamtes Jahr {sel_year}"
        period_start_balance = start_minutes
    else:
        m_last_day    = calendar.monthrange(sel_year, sel_month)[1]
        display_start = datetime.date(sel_year, sel_month, 1).isoformat()
        display_end   = datetime.date(sel_year, sel_month, m_last_day).isoformat()
        prior = [r for r in all_rows if r["day"] < display_start]
        period_start_balance = prior[-1]["running"] if prior else start_minutes
        period_label = f"{MONTH_NAMES_DE[sel_month]} {sel_year}"

    display_rows_full = [r for r in all_rows if display_start <= r["day"] <= display_end]

    if only == "1":
        entry_days = _days_with_any_entry(u["id"], display_start, display_end)
        display_rows = [r for r in display_rows_full if r["day"] in entry_days]
    else:
        display_rows = display_rows_full

    period_end_balance = display_rows_full[-1]["running"] if display_rows_full else period_start_balance

    # ── Dropdowns ────────────────────────────────────────────────────────
    year_opts = "".join(
        f'<option value="{y}" {"selected" if y == sel_year else ""}>{y}</option>'
        for y in reversed(available_years)
    )
    month_opts = f'<option value="0" {"selected" if sel_month == 0 else ""}>Gesamtes Jahr</option>'
    for mi in range(1, 13):
        month_opts += f'<option value="{mi}" {"selected" if mi == sel_month else ""}>{MONTH_NAMES_DE[mi]}</option>'

    # ── Status-Badges (Abwesenheiten + Feiertage) für den Anzeigebereich ────
    _day_status: dict[str, list[tuple[str, str]]] = {}
    _db2 = connect()
    for _ab in _db2.execute(
        """SELECT a.date_from, a.date_to, t.name AS type_name, t.color AS type_color
           FROM absences a JOIN absence_types t ON t.id=a.type_id
           WHERE a.user_id=? AND NOT (a.date_to < ? OR a.date_from > ?)""",
        (u["id"], display_start, display_end),
    ).fetchall():
        _d0 = datetime.date.fromisoformat(_ab["date_from"])
        _d1 = datetime.date.fromisoformat(_ab["date_to"])
        _cur = _d0
        while _cur <= _d1:
            _iso = _cur.isoformat()
            if display_start <= _iso <= display_end:
                _day_status.setdefault(_iso, []).append((_ab["type_name"], _ab["type_color"] or "#6c757d"))
            _cur += datetime.timedelta(days=1)
    for _hol in _db2.execute(
        "SELECT day, holiday_name FROM calendar_days WHERE is_holiday=1 AND day BETWEEN ? AND ?",
        (display_start, display_end),
    ).fetchall():
        _day_status.setdefault(str(_hol["day"])[:10], []).append((_hol["holiday_name"], "var(--danger)"))
    _db2.close()

    # ── Zeitblöcke (Beginn/Ende/Pause) für Mobile – alle Blöcke pro Tag ─
    _all_blocks_map: dict = {}  # day -> [{t_in, t_out, brk}, ...]
    _db3 = connect()
    for _blk in _db3.execute(
        "SELECT day, time_in, time_out, break_minutes"
        " FROM time_blocks WHERE user_id=? AND day BETWEEN ? AND ?"
        " ORDER BY day, time_in",
        (u["id"], display_start, display_end),
    ).fetchall():
        _day_key = str(_blk["day"])[:10]
        _all_blocks_map.setdefault(_day_key, []).append({
            "t_in": str(_blk["time_in"] or "")[:5],
            "t_out": str(_blk["time_out"] or "")[:5],
            "brk": int(_blk["break_minutes"] or 0),
        })
    _db3.close()

    # ── Mobile Navigation ────────────────────────────────────────────────
    def _mob_nav_btn(url, lbl):
        if url:
            return f"<a href='{url}' class='btn' style='padding:5px 9px;font-size:13px;line-height:1;'>{lbl}</a>"
        return f"<span class='btn' style='padding:5px 9px;font-size:13px;line-height:1;opacity:.28;cursor:not-allowed;'>{lbl}</span>"

    mob_prev_year_url = f"/balance?y={sel_year - 1}&m={sel_month}" if sel_year > min_year else None
    mob_next_year_url = f"/balance?y={sel_year + 1}&m={sel_month}" if sel_year < today.year else None

    if sel_month == 0:
        _pm_y, _pm_m = sel_year - 1, 12
        _nm_y, _nm_m = sel_year, 1
        mob_month_label = "Gesamtes Jahr"
    else:
        _pm_y = sel_year - 1 if sel_month == 1 else sel_year
        _pm_m = 12 if sel_month == 1 else sel_month - 1
        _nm_y = sel_year + 1 if sel_month == 12 else sel_year
        _nm_m = 1 if sel_month == 12 else sel_month + 1
        mob_month_label = MONTH_NAMES_DE[sel_month]

    mob_prev_month_url = f"/balance?y={_pm_y}&m={_pm_m}" if _pm_y >= min_year else None
    mob_next_month_url = f"/balance?y={_nm_y}&m={_nm_m}" if _nm_y <= today.year else None

    mob_yr_prev = _mob_nav_btn(mob_prev_year_url, "&#9664;")
    mob_yr_next = _mob_nav_btn(mob_next_year_url, "&#9654;")
    mob_mo_prev = _mob_nav_btn(mob_prev_month_url, "&#9664;")
    mob_mo_next = _mob_nav_btn(mob_next_month_url, "&#9654;")

    # ── Mobile Tabellenzeilen ────────────────────────────────────────────
    mob_trs = ""

    # ── Desktop Tabellenzeilen ───────────────────────────────────────────
    _wd_names = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    trs = ""
    for r in display_rows:
        _d_obj    = datetime.date.fromisoformat(r["day"])
        _wd_lbl   = _wd_names[_d_obj.weekday()]
        _blocks_d = _all_blocks_map.get(r["day"], [])
        _statuses = _day_status.get(r["day"], [])
        _is_today_d   = r["day"] == today_iso
        _is_off_d     = r["expected"] == 0 and r["actual"] == 0 and not _statuses
        _is_missing_d = r["expected"] > 0 and r["actual"] == 0 and not _statuses and r["day"] < today_iso
        delta_clr   = _balance_color(r["delta"])
        running_clr = _balance_color(r["running"])
        _delta_str_d   = _fmt_minutes_signed(r["delta"]) if (r["delta"] != 0 or r["actual"] > 0) else ""
        _running_str_d = _fmt_minutes_signed(r["running"])
        _date_str_d    = _fmt_date_de(r["day"])

        # Build status badge HTML (absence + flextag)
        _status_html = ""
        for _label, _color in _statuses[:2]:
            _bg = (_color + "22") if _color.startswith("#") else "rgba(0,0,0,.07)"
            _status_html += (
                f"<span style='font-size:10px;padding:1px 5px;border-radius:4px;"
                f"background:{_bg};color:{_color};white-space:nowrap;font-weight:600;'>"
                f"{_label}</span> "
            )
        if r.get("flextag_min"):
            _status_html += (
                f"<span style='font-size:10px;padding:1px 5px;border-radius:4px;"
                f"background:rgba(37,99,235,.1);color:var(--ac);white-space:nowrap;'>"
                f"Flextag&nbsp;−{_fmt_minutes(r['flextag_min'])}</span>"
            )

        # Row base style
        if _is_missing_d:
            _base_d = "background:rgba(220,38,38,.08);"
        elif _is_today_d:
            _base_d = "background:rgba(37,99,235,.09);border-left:3px solid var(--ac);"
        elif _is_off_d:
            _base_d = "opacity:.38;"
        else:
            _base_d = ""

        _td = "style='padding:8px 6px;vertical-align:middle;'"
        _td_r = "style='padding:8px 6px;vertical-align:middle;text-align:right;'"

        # Single row (no blocks or absence-only day)
        if not _blocks_d:
            trs += (
                f"<tr style='cursor:pointer;border-bottom:1px solid var(--bd);{_base_d}'"
                f" onclick=\"location.href='/day/{r['day']}'\">"
                f"<td {_td} style='padding:8px 6px;color:var(--mu);white-space:nowrap;'>{_wd_lbl}</td>"
                f"<td {_td} style='padding:8px 6px;white-space:nowrap;'>"
                f"<a href='/day/{r['day']}' style='text-decoration:none;color:inherit;'>{_date_str_d}"
                f"<span style='font-size:11px;opacity:.35;margin-left:3px;'>&#8599;</span></a></td>"
                f"<td {_td}>{_status_html}</td>"
                f"<td {_td}></td><td {_td}></td><td {_td_r}></td>"
                f"<td {_td_r}><b style='color:{delta_clr};'>{_delta_str_d}</b></td>"
                f"<td {_td_r}><b style='color:{running_clr};'>{_running_str_d}</b></td>"
                f"</tr>"
            )
            continue

        # Multi-block rows
        for _bi, _blk_i in enumerate(_blocks_d):
            _is_first = _bi == 0
            _is_last  = _bi == len(_blocks_d) - 1
            _border = "border-bottom:1px solid var(--bd);" if _is_last else "border-bottom:1px solid rgba(128,128,128,.13);"
            _t_in  = _blk_i["t_in"]
            _t_out = _blk_i["t_out"]
            _brk   = _blk_i["brk"]

            if _is_first:
                _wd_cell    = f"<td {_td} style='padding:8px 6px;color:var(--mu);white-space:nowrap;'>{_wd_lbl}</td>"
                _date_cell  = (
                    f"<td {_td} style='padding:8px 6px;white-space:nowrap;'>"
                    f"<a href='/day/{r['day']}' style='text-decoration:none;color:inherit;'>{_date_str_d}"
                    f"<span style='font-size:11px;opacity:.35;margin-left:3px;'>&#8599;</span></a></td>"
                )
                _stat_cell  = f"<td {_td}>{_status_html}</td>"
                _delta_cell = f"<td {_td_r}><b style='color:{delta_clr};'>{_delta_str_d}</b></td>"
                _run_cell   = f"<td {_td_r}><b style='color:{running_clr};'>{_running_str_d}</b></td>"
            else:
                _wd_cell    = f"<td {_td}></td>"
                _date_cell  = f"<td {_td}></td>"
                _stat_cell  = f"<td {_td}></td>"
                _delta_cell = f"<td {_td}></td>"
                _run_cell   = f"<td {_td}></td>"

            trs += (
                f"<tr style='cursor:pointer;{_base_d}{_border}'"
                f" onclick=\"location.href='/day/{r['day']}'\">"
                f"{_wd_cell}{_date_cell}{_stat_cell}"
                f"<td {_td}>{_t_in}</td>"
                f"<td {_td}>{_t_out}</td>"
                f"<td {_td_r}>{str(_brk) if _brk else ''}</td>"
                f"{_delta_cell}{_run_cell}"
                f"</tr>"
            )

    # ── Mobile Tabellenzeilen (Schleife) ────────────────────────────────
    for r in display_rows:
        _d_obj_m      = datetime.date.fromisoformat(r["day"])
        _wd_m         = _wd_names[_d_obj_m.weekday()]
        _blocks_m     = _all_blocks_map.get(r["day"], [])
        _stat_m       = _day_status.get(r["day"], [])
        _is_today_m   = r["day"] == today_iso
        _is_off_m     = r["expected"] == 0 and r["actual"] == 0 and not _stat_m
        _is_missing_m = r["expected"] > 0 and r["actual"] == 0 and not _stat_m and r["day"] < today_iso
        _delta_clr_m  = _balance_color(r["delta"])
        _delta_str_m  = _fmt_minutes_signed(r["delta"]) if (r["delta"] != 0 or r["actual"] > 0) else ""
        _date_str_m   = f"{_d_obj_m.day:02d}.{_d_obj_m.month:02d}."

        # Base style for all rows of this day
        if _is_missing_m:
            _base_style = "background:rgba(220,38,38,.08);"
        elif _is_today_m:
            _base_style = "background:rgba(37,99,235,.09);border-left:3px solid var(--ac);"
        elif _is_off_m:
            _base_style = "opacity:.38;"
        else:
            _base_style = ""

        # Absence days: single row with badge spanning time columns
        if _stat_m:
            _abs_label = _stat_m[0][0]
            _abs_color = _stat_m[0][1]
            _abs_bg    = (_abs_color + "22") if _abs_color.startswith("#") else "rgba(0,0,0,.07)"
            mob_trs += (
                f"<tr style='cursor:pointer;border-bottom:1px solid var(--bd);{_base_style}'"
                f" onclick=\"location.href='/day/{r['day']}'\">"
                f"<td style='padding:4px 4px;color:var(--mu);font-size:12px;'>{_wd_m}</td>"
                f"<td style='padding:4px 2px;font-weight:500;white-space:nowrap;'>{_date_str_m}</td>"
                f"<td colspan='3' style='padding:4px 2px;'>"
                f"<span style='font-size:10px;padding:1px 5px;border-radius:3px;"
                f"background:{_abs_bg};color:{_abs_color};font-weight:600;white-space:nowrap;'>{_abs_label}</span>"
                f"</td>"
                f"<td style='padding:4px 4px;text-align:right;font-weight:700;white-space:nowrap;"
                f"color:{_delta_clr_m};'>{_delta_str_m}</td>"
                f"</tr>"
            )
            continue

        # No blocks: single empty row (missing or off day)
        if not _blocks_m:
            mob_trs += (
                f"<tr style='cursor:pointer;border-bottom:1px solid var(--bd);{_base_style}'"
                f" onclick=\"location.href='/day/{r['day']}'\">"
                f"<td style='padding:4px 4px;color:var(--mu);font-size:12px;'>{_wd_m}</td>"
                f"<td style='padding:4px 2px;font-weight:500;white-space:nowrap;'>{_date_str_m}</td>"
                f"<td style='padding:4px 2px;'></td>"
                f"<td style='padding:4px 2px;'></td>"
                f"<td style='padding:4px 2px;'></td>"
                f"<td style='padding:4px 4px;text-align:right;font-weight:700;white-space:nowrap;"
                f"color:{_delta_clr_m};'>{_delta_str_m}</td>"
                f"</tr>"
            )
            continue

        # One or more blocks: one row per block
        for _bi, _blk_i in enumerate(_blocks_m):
            _is_first = _bi == 0
            _is_last  = _bi == len(_blocks_m) - 1
            # Thick separator after last block of day; subtle between sibling blocks
            _border = "border-bottom:1px solid var(--bd);" if _is_last else "border-bottom:1px solid rgba(128,128,128,.13);"
            _t_in  = _blk_i["t_in"]
            _t_out = _blk_i["t_out"]
            _brk   = _blk_i["brk"]
            if _is_first:
                _wd_cell    = f"<td style='padding:4px 4px;color:var(--mu);font-size:12px;'>{_wd_m}</td>"
                _date_cell  = f"<td style='padding:4px 2px;font-weight:500;white-space:nowrap;'>{_date_str_m}</td>"
                _delta_cell = (
                    f"<td style='padding:4px 4px;text-align:right;font-weight:700;white-space:nowrap;"
                    f"color:{_delta_clr_m};'>{_delta_str_m}</td>"
                )
            else:
                _wd_cell    = "<td style='padding:4px 4px;'></td>"
                _date_cell  = "<td style='padding:4px 2px;'></td>"
                _delta_cell = "<td style='padding:4px 4px;'></td>"
            mob_trs += (
                f"<tr style='cursor:pointer;{_base_style}{_border}'"
                f" onclick=\"location.href='/day/{r['day']}'\">"
                f"{_wd_cell}"
                f"{_date_cell}"
                f"<td style='padding:4px 2px;'>{_t_in}</td>"
                f"<td style='padding:4px 2px;'>{_t_out}</td>"
                f"<td style='padding:4px 2px;text-align:right;'>{str(_brk) if _brk else ''}</td>"
                f"{_delta_cell}"
                f"</tr>"
            )

    start_hhmm        = _fmt_minutes_signed(start_minutes)
    period_start_hhmm = _fmt_minutes_signed(period_start_balance)
    period_end_hhmm   = _fmt_minutes_signed(period_end_balance)
    period_start_clr  = _balance_color(period_start_balance)
    period_end_clr    = _balance_color(period_end_balance)

    body = f"""
    {flash_html()}
    <style>
    .bal-mob{{display:none;}}
    @media(max-width:768px){{
      .bal-desk{{display:none!important;}}
      .bal-mob{{display:block!important;}}
    }}
    </style>
    <div class="bal-desk">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Gleitzeitkonto</h3>
        <div class="small">{period_label}</div>
      </div>

      <form method="get" style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-top:12px;">
        <div><label>Jahr</label><br><select name="y">{year_opts}</select></div>
        <div><label>Monat</label><br><select name="m">{month_opts}</select></div>
        <div class="small" style="padding-bottom:4px;">
          <label><input type="checkbox" name="only" value="1" {"checked" if only == "1" else ""}> nur Tage mit Einträgen</label>
        </div>
        <div><button class="btn" type="submit">Anzeigen</button></div>
      </form>

      <div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:14px;">
        <div style="flex:1;min-width:160px;">
          <div class="small">Saldo zu Periodenbeginn</div>
          <div style="font-size:22px;color:{period_start_clr};"><b>{period_start_hhmm}</b></div>
        </div>
        <div style="flex:1;min-width:160px;">
          <div class="small">Saldo zum Periodenende</div>
          <div style="font-size:22px;color:{period_end_clr};"><b>{period_end_hhmm}</b></div>
        </div>
      </div>

      <hr>

      <form method="post" action="/balance/start" style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;">
        <div>
          <label>Jahresstart-Saldo {sel_year}</label><br>
          <input name="start_balance" placeholder="+00:00 / -01:30" value="{start_hhmm}" style="min-width:160px;" required>
          <div class="small">Format: +HH:MM oder -HH:MM</div>
        </div>
        <input type="hidden" name="y" value="{sel_year}">
        <input type="hidden" name="m" value="{sel_month}">
        <div><button class="btn" type="submit">Speichern</button></div>
      </form>

      <hr>

      <p class="small">Delta = Ist − Soll. Wochenenden, Feiertage und Abwesenheitstage zählen als Soll = 0. Flextage werden zusätzlich vom Gleitzeitkonto abgezogen.</p>
      <table style="border-collapse:collapse;width:100%;">
        <thead>
          <tr>
            <th style="padding:6px 6px;text-align:left;width:32px;">Tag</th>
            <th style="padding:6px 6px;text-align:left;">Datum</th>
            <th style="padding:6px 6px;text-align:left;">Status</th>
            <th style="padding:6px 6px;text-align:left;">Von</th>
            <th style="padding:6px 6px;text-align:left;">Bis</th>
            <th style="padding:6px 6px;text-align:right;width:44px;">Pause</th>
            <th style="padding:6px 6px;text-align:right;width:70px;">Delta</th>
            <th style="padding:6px 6px;text-align:right;width:70px;">Saldo</th>
          </tr>
        </thead>
        <tbody>{trs}</tbody>
      </table>
      {("<p class='small'><i>Keine Tage im Zeitraum.</i></p>" if not display_rows else "")}
    </div>
    {_render_absence_summary_card(u["id"], display_start, display_end)}
    </div>

    <div class="bal-mob card" style="padding:0;overflow:hidden;">
      <div style="position:sticky;top:0;z-index:20;background:var(--sf);border-bottom:2px solid var(--bd);padding:10px 12px 8px;">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
          <div style="display:flex;align-items:center;gap:2px;">
            {mob_yr_prev}
            <b style="font-size:14px;min-width:42px;text-align:center;">{sel_year}</b>
            {mob_yr_next}
          </div>
          <div style="display:flex;align-items:center;gap:2px;flex:1;justify-content:center;">
            {mob_mo_prev}
            <b style="font-size:14px;min-width:66px;text-align:center;">{mob_month_label}</b>
            {mob_mo_next}
          </div>
        </div>
        <div style="font-size:30px;font-weight:700;letter-spacing:-.02em;color:{period_end_clr};line-height:1.1;">{period_end_hhmm}</div>
        <div style="font-size:11px;color:var(--mu);margin-top:2px;">Saldo {period_label}</div>
      </div>
      <table style="width:100%;table-layout:fixed;border-collapse:collapse;font-size:13px;">
        <colgroup>
          <col style="width:26px;">
          <col style="width:50px;">
          <col style="width:48px;">
          <col style="width:48px;">
          <col style="width:30px;">
          <col>
        </colgroup>
        <thead>
          <tr style="background:var(--sf);">
            <th style="padding:5px 4px;text-align:left;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Tag</th>
            <th style="padding:5px 2px;text-align:left;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Dat.</th>
            <th style="padding:5px 2px;text-align:left;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Von</th>
            <th style="padding:5px 2px;text-align:left;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Bis</th>
            <th style="padding:5px 2px;text-align:right;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Pse</th>
            <th style="padding:5px 4px;text-align:right;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Delta</th>
          </tr>
        </thead>
        <tbody>{mob_trs}</tbody>
      </table>
      {("<p class='small' style='padding:8px 12px;color:var(--mu);'><i>Keine Tage im Zeitraum.</i></p>" if not display_rows else "")}
    </div>
    """
    return render_template_string(layout("Gleitzeitkonto", body, u, APP_VERSION))



@app.post("/balance/expected")
@login_required
def balance_set_expected_override():
    bootstrap()
    u = current_user()

    day = (request.form.get("day") or "").strip()
    val = (request.form.get("expected") or "").strip()
    y   = (request.form.get("y") or "").strip()
    m   = (request.form.get("m") or "").strip()
    back = f"/balance?y={y}&m={m}" if y and m else "/balance"

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        add_flash("Ungültiges Datum.", "error")
        return redirect(back)

    if not val:
        _set_expected_override_minutes(u["id"], day, None)
        add_flash("Soll-Override entfernt.", "success")
        return redirect(back)

    try:
        mins = _minutes_from_hhmm(val)
    except Exception:
        add_flash("Soll bitte als HH:MM angeben (z.B. 08:00).", "error")
        return redirect(back)

    _set_expected_override_minutes(u["id"], day, int(mins))
    add_flash("Soll gespeichert.", "success")
    return redirect(back)


@app.post("/balance/start")
@login_required
def balance_set_start():
    bootstrap()
    u = current_user()

    start_balance_raw = (request.form.get("start_balance") or "").strip()
    y = (request.form.get("y") or "").strip()
    m = (request.form.get("m") or "").strip()
    back = f"/balance?y={y}&m={m}" if y and m else "/balance"

    try:
        mins = _parse_signed_hhmm_to_minutes(start_balance_raw)
    except Exception:
        add_flash("Ungültiges Format. Bitte +HH:MM oder -HH:MM verwenden.", "error")
        return redirect(back)

    _set_start_balance_minutes(u["id"], mins)
    add_flash("Startsaldo gespeichert.", "success")
    return redirect(back)

def _month_start_end(year: int, month: int):
    first = datetime.date(year, month, 1)
    last = datetime.date(year, month, calendar.monthrange(year, month)[1])
    return first.isoformat(), last.isoformat()


def _calc_balance_end_at(user_id: int, end_iso: str) -> int:
    """Saldo bis zu einem Datum (inkl.) – identische Logik wie balance_view (_iter_days)."""
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


@app.get("/balance/monthly")
@login_required
def balance_monthly():
    bootstrap()
    u = current_user()

    today = datetime.date.today()
    year = int(request.args.get("y") or today.year)

    rows = []
    for m in range(1, 13):
        m_from, m_to = _month_start_end(year, m)
        if year == today.year and m > today.month:
            continue
        calc = _calc_balance(u["id"], m_from, m_to)
        rows.append({
            "month": f"{year}-{m:02d}",
            "from": m_from,
            "to": m_to,
            "delta": int(calc["end_minutes"] - calc["start_minutes"]),
            "end": int(calc["end_minutes"]),
        })

    trs = ""
    for r in rows:
        trs += (
            "<tr>"
            f"<td><a href='/balance?from={r['from']}&to={r['to']}'>{r['month']}</a></td>"
            f"<td style='text-align:right;'><b>{_fmt_minutes_signed(r['delta'])}</b></td>"
            f"<td style='text-align:right;'>{_fmt_minutes_signed(r['end'])}</td>"
            "</tr>"
        )

    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Monatsabschluss</h3>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <a class="btn" href="/balance/monthly?y={year-1}">◀︎ {year-1}</a>
          <a class="btn" href="/balance/monthly?y={today.year}">{today.year}</a>
          <a class="btn" href="/balance/monthly?y={year+1}">{year+1} ▶︎</a>
          <a class="btn" href="/balance/monthly.csv?y={year}">CSV Export</a>
        </div>
      </div>
      <p class="small">Delta = Summe(Ist-Soll) im Monat. Endsaldo = Startsaldo + Deltas seit Jahresbeginn.</p>
      <table>
        <thead><tr><th>Monat</th><th style="text-align:right;">Delta</th><th style="text-align:right;">Endsaldo</th></tr></thead>
        <tbody>{trs}</tbody>
      </table>
    </div>
    """
    return render_template_string(layout("Monatsabschluss", body, u, APP_VERSION))


@app.get("/balance/monthly.csv")
@login_required
def balance_monthly_csv():
    bootstrap()
    u = current_user()

    today = datetime.date.today()
    year = int(request.args.get("y") or today.year)

    lines = ["month,from,to,delta_minutes,end_minutes"]
    for m in range(1, 13):
        m_from, m_to = _month_start_end(year, m)
        if year == today.year and m > today.month:
            continue
        calc = _calc_balance(u["id"], m_from, m_to)
        delta = int(calc["end_minutes"] - calc["start_minutes"])
        endm = int(calc["end_minutes"])
        lines.append(f"{year}-{m:02d},{m_from},{m_to},{delta},{endm}")

    csv_text = "\n".join(lines) + "\n"
    from flask import Response
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=gleitzeit_{year}.csv"},
    )


# -------------------------
# Abwesenheiten (NEU v2.4.0)
# -------------------------

def _validate_absence_dates(date_from: str, date_to: str, is_half_day: int):
    if not date_from or not date_to:
        return "Bitte Von/Bis angeben."
    if date_from > date_to:
        return "Von-Datum darf nicht nach Bis-Datum liegen."
    if is_half_day and date_from != date_to:
        return "Halber Tag ist nur erlaubt, wenn Von = Bis."
    return None


def _has_overlap(conn, user_id: int, date_from: str, date_to: str, exclude_id=None) -> bool:
    sql = """
      SELECT COUNT(1) AS c
      FROM absences
      WHERE user_id = ?
        AND NOT (date_to < ? OR date_from > ?)
    """
    params = [user_id, date_from, date_to]
    if exclude_id is not None:
        sql += " AND id <> ?"
        params.append(exclude_id)
    r = conn.execute(sql, params).fetchone()
    return (r["c"] if r else 0) > 0


FIXED_REMARKS = ["Flextag", "Verdi"]

MONTH_NAMES_DE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
                  "Juli", "August", "September", "Oktober", "November", "Dezember"]

_REMARK_JS = """
function syncRemarkNew(rowId, inpId, sel) {
  var isNew = sel && sel.value === '__new__';
  var row = document.getElementById(rowId);
  var inp = document.getElementById(inpId);
  if (!row || !inp) return;
  row.style.display = isNew ? '' : 'none';
  inp.required = isNew;
}"""

def _remark_select_html(user_remarks: list, selected: str = "", pfx: str = "") -> str:
    """Dropdown for Sonstige remark field with preset options + free-text fallback."""
    all_opts: list[str] = list(FIXED_REMARKS)
    seen: set[str] = set(FIXED_REMARKS)
    for r in sorted(user_remarks):
        if r not in seen:
            all_opts.append(r)
            seen.add(r)
    is_new = bool(selected) and selected not in seen
    opts_html = ""
    for r in all_opts:
        s = "selected" if (r == selected and not is_new) else ""
        opts_html += f'<option value="{r}" {s}>{r}</option>'
    new_sel = "selected" if is_new else ""
    opts_html += f'<option value="__new__" {new_sel}>Neuer Eintrag …</option>'
    new_display = "" if is_new else "none"
    new_val = selected if is_new else ""
    new_req = "required" if is_new else ""
    return (
        f'<label>Bemerkung <span style="color:var(--danger);">*</span></label><br>'
        f'<select name="remark_select" id="{pfx}remark_sel" '
        f'onchange="syncRemarkNew(\'{pfx}remark_new_row\',\'{pfx}remark_new_inp\',this)">'
        f'{opts_html}</select>'
        f'<div id="{pfx}remark_new_row" style="margin-top:6px;display:{new_display};">'
        f'<input name="remark_new" id="{pfx}remark_new_inp" '
        f'placeholder="Bemerkung eingeben …" style="width:100%;" '
        f'value="{new_val}" {new_req}></div>'
    )

def _resolve_comment_from_form() -> str:
    """Read remark_select / remark_new / comment from the current request and return the final value."""
    remark_select = (request.form.get("remark_select") or "").strip()
    remark_new = (request.form.get("remark_new") or "").strip()
    comment_plain = (request.form.get("comment") or "").strip()
    if remark_select == "__new__":
        return remark_new
    if remark_select:
        return remark_select
    return comment_plain


@app.get("/absences")
@login_required
def absences_list():
    bootstrap()
    u = current_user()

    q_from = (request.args.get("from") or "").strip()
    q_to = (request.args.get("to") or "").strip()
    user_start = _get_tracking_start(u["id"])

    db = connect()
    rows_sql = """
      SELECT a.id, a.date_from, a.date_to, a.is_half_day, a.comment,
             t.name AS type_name, t.color AS type_color
      FROM absences a
      JOIN absence_types t ON t.id = a.type_id
      WHERE a.user_id = ?
    """
    params = [u["id"]]
    effective_from = q_from or user_start or ""
    if effective_from:
        rows_sql += " AND a.date_to >= ?"
        params.append(effective_from)
    if q_to:
        rows_sql += " AND a.date_from <= ?"
        params.append(q_to)
    rows_sql += " ORDER BY a.date_from DESC, a.id DESC"
    absences = db.execute(rows_sql, params).fetchall()
    db.close()

    def _fmt_iso(iso_val) -> str:
        try:
            d = datetime.date.fromisoformat(str(iso_val)[:10])
            return d.strftime("%d.%m.%Y")
        except Exception:
            return str(iso_val)

    trs = ""
    for a in absences:
        color = a["type_color"] or "#999"
        scope = "1/2" if a["is_half_day"] else "ganztägig"
        bemerkung = (a["comment"] or "") if a["type_name"] == "Sonstige" else ""
        trs += f"""
        <tr>
          <td><span style='display:inline-block;width:10px;height:10px;background:{color};border-radius:2px;margin-right:6px;'></span>{a["type_name"]}</td>
          <td>{_fmt_iso(a["date_from"])}</td>
          <td>{_fmt_iso(a["date_to"])}</td>
          <td>{scope}</td>
          <td>{bemerkung}</td>
          <td style="white-space:nowrap;">
            <a href="/absences/{a["id"]}/edit">Bearbeiten</a>
            &nbsp;|&nbsp;
            <form method="post" action="/absences/{a["id"]}/delete" style="display:inline;" onsubmit="return confirm('Wirklich löschen?');">
              <button class="btn" type="submit">Löschen</button>
            </form>
          </td>
        </tr>
        """
    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Abwesenheiten</h3>
        <a class="btn" href="/absences/new">+ Neu</a>
      </div>
      <form method="get" style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-top:10px;">
        {FORM_ASSETS_JS}
        <div><label>Von</label><br>{_date_input("from", q_from)}</div>
        <div><label>Bis</label><br>{_date_input("to", q_to)}</div>
        <div><button class="btn" type="submit">Filtern</button> <a class="btn" href="/absences">Reset</a></div>
      </form>
      <hr>
      <table>
        <thead><tr><th>Typ</th><th>Von</th><th>Bis</th><th>Umfang</th><th>Bemerkung</th><th></th></tr></thead>
        <tbody>{trs}</tbody>
      </table>
      {("<p class='small'><i>Keine Einträge.</i></p>" if not absences else "")}
    </div>
    """
    return render_template_string(layout("Abwesenheiten", body, u, APP_VERSION))


@app.get("/absences/new")
@login_required
def absences_new():
    bootstrap()
    u = current_user()
    db = connect()
    types = db.execute("SELECT id, name, color FROM absence_types WHERE active=1 ORDER BY name").fetchall()
    user_remarks = [r["remark"] for r in db.execute(
        "SELECT remark FROM absence_remarks WHERE user_id=? ORDER BY remark", (u["id"],)
    ).fetchall()]
    db.close()

    options = "".join([f'<option value="{t["id"]}">{t["name"]}</option>' for t in types])
    sonstige_id = next((t["id"] for t in types if t["name"] == "Sonstige"), 0)
    remark_html = _remark_select_html(user_remarks)

    body = f"""
    {flash_html()}
    {FORM_ASSETS_JS}
<script>
{_REMARK_JS}
function syncBemerkung(sel, sonstigeId) {{
  var isSonstige = String(sel.value) === String(sonstigeId);
  document.getElementById('remark_row').style.display = isSonstige ? '' : 'none';
  if (isSonstige) syncRemarkNew('remark_new_row','remark_new_inp',document.getElementById('remark_sel'));
}}
</script>
    <div class="card">
      <h3>Abwesenheit anlegen</h3>
      <form method="post" action="/absences/new">
        <div><label>Typ</label><br>
          <select name="type_id" id="absence_type_sel" required onchange="syncBemerkung(this,{sonstige_id})">{options}</select>
        </div><br>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <div><label>Von</label><br>{_date_input("date_from", required=True, min_target="date_to")}</div>
          <div><label>Bis</label><br>{_date_input("date_to", required=True)}</div>
        </div><br>
        <label><input type="checkbox" name="is_half_day" value="1"> Halber Tag (nur wenn Von=Bis)</label><br><br>
        <div id="remark_row" style="display:none;">{remark_html}</div><br>
        <button class="btn" type="submit">Speichern</button>
        <a class="btn" href="/absences">Abbrechen</a>
      </form>
    </div>
<script>syncBemerkung(document.getElementById('absence_type_sel'),{sonstige_id});</script>
    """
    return render_template_string(layout("Abwesenheit", body, u, APP_VERSION))


@app.post("/absences/new")
@login_required
def absences_new_post():
    bootstrap()
    u = current_user()
    type_id = int(request.form.get("type_id") or 0)
    date_from = _parse_date_input(request.form.get("date_from") or "") or ""
    date_to = _parse_date_input(request.form.get("date_to") or "") or ""
    is_half_day = 1 if request.form.get("is_half_day") == "1" else 0
    comment = _resolve_comment_from_form()

    err = _validate_absence_dates(date_from, date_to, is_half_day)
    if err:
        add_flash(err, "error")
        return redirect(url_for("absences_new"))

    if date_from and date_to and _is_range_locked(u["id"], date_from, date_to):
        add_flash(LOCK_MSG, "error")
        return redirect(url_for("absences_new"))
    if date_from:
        sd_err = _range_before_start_date(u["id"], date_from, date_to or date_from)
        if sd_err:
            add_flash(sd_err, "error")
            return redirect(url_for("absences_new"))

    db = connect()
    type_row = db.execute("SELECT name FROM absence_types WHERE id=?", (type_id,)).fetchone()
    type_name = type_row["name"] if type_row else ""
    if type_name == "Sonstige" and not comment:
        db.close()
        add_flash('Bei Typ "Sonstige" ist eine Bemerkung Pflicht.', "error")
        return redirect(url_for("absences_new"))

    if _has_overlap(db, u["id"], date_from, date_to):
        db.close()
        add_flash("Überschneidung mit vorhandener Abwesenheit. Bitte Zeitraum anpassen.", "error")
        return redirect(url_for("absences_new"))

    db.execute(
        "INSERT INTO absences(user_id,type_id,date_from,date_to,is_half_day,comment) VALUES(?,?,?,?,?,?)",
        (u["id"], type_id, date_from, date_to, is_half_day, comment),
    )
    if type_name == "Sonstige" and comment:
        db.execute("INSERT OR IGNORE INTO absence_remarks(user_id,remark) VALUES(?,?)", (u["id"], comment))
    db.commit()
    db.close()
    add_flash("Abwesenheit gespeichert.", "success")
    return redirect(url_for("absences_list"))


@app.get("/absences/<int:absence_id>/edit")
@login_required
def absences_edit(absence_id: int):
    bootstrap()
    u = current_user()
    db = connect()
    row = db.execute(
        "SELECT id, type_id, date_from, date_to, is_half_day, comment FROM absences WHERE id=? AND user_id=?",
        (absence_id, u["id"]),
    ).fetchone()
    if not row:
        db.close()
        abort(404)

    types = db.execute("SELECT id, name FROM absence_types WHERE active=1 ORDER BY name").fetchall()
    user_remarks = [r["remark"] for r in db.execute(
        "SELECT remark FROM absence_remarks WHERE user_id=? ORDER BY remark", (u["id"],)
    ).fetchall()]
    db.close()

    options = ""
    for t in types:
        sel = "selected" if t["id"] == row["type_id"] else ""
        options += f'<option value="{t["id"]}" {sel}>{t["name"]}</option>'

    sonstige_id = next((t["id"] for t in types if t["name"] == "Sonstige"), 0)
    current_type_name = next((t["name"] for t in types if t["id"] == row["type_id"]), "")
    is_sonstige_now = current_type_name == "Sonstige"
    checked = "checked" if row["is_half_day"] else ""
    comment = row["comment"] or ""
    remark_html = _remark_select_html(user_remarks, selected=comment if is_sonstige_now else "")
    remark_display = "" if is_sonstige_now else "none"

    body = f"""
    {flash_html()}
    {FORM_ASSETS_JS}
<script>
{_REMARK_JS}
function syncBemerkung(sel, sonstigeId) {{
  var isSonstige = String(sel.value) === String(sonstigeId);
  document.getElementById('remark_row').style.display = isSonstige ? '' : 'none';
  if (isSonstige) syncRemarkNew('remark_new_row','remark_new_inp',document.getElementById('remark_sel'));
}}
</script>
    <div class="card">
      <h3>Abwesenheit bearbeiten</h3>
      <form method="post" action="/absences/{absence_id}/edit">
        <div><label>Typ</label><br>
          <select name="type_id" id="absence_type_sel" required onchange="syncBemerkung(this,{sonstige_id})">{options}</select>
        </div><br>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <div><label>Von</label><br>{_date_input("date_from", str(row["date_from"]), required=True, min_target="date_to")}</div>
          <div><label>Bis</label><br>{_date_input("date_to", str(row["date_to"]), required=True)}</div>
        </div><br>
        <label><input type="checkbox" name="is_half_day" value="1" {checked}> Halber Tag (nur wenn Von=Bis)</label><br><br>
        <div id="remark_row" style="display:{remark_display};">{remark_html}</div><br>
        <button class="btn" type="submit">Aktualisieren</button>
        <a class="btn" href="/absences">Abbrechen</a>
      </form>
    </div>
    """
    return render_template_string(layout("Abwesenheit bearbeiten", body, u, APP_VERSION))


@app.post("/absences/<int:absence_id>/edit")
@login_required
def absences_edit_post(absence_id: int):
    bootstrap()
    u = current_user()

    type_id = int(request.form.get("type_id") or 0)
    date_from = _parse_date_input(request.form.get("date_from") or "") or ""
    date_to = _parse_date_input(request.form.get("date_to") or "") or ""
    is_half_day = 1 if request.form.get("is_half_day") == "1" else 0
    comment = _resolve_comment_from_form()

    err = _validate_absence_dates(date_from, date_to, is_half_day)
    if err:
        add_flash(err, "error")
        return redirect(f"/absences/{absence_id}/edit")

    db = connect()
    type_row = db.execute("SELECT name FROM absence_types WHERE id=?", (type_id,)).fetchone()
    type_name = type_row["name"] if type_row else ""
    if type_name == "Sonstige" and not comment:
        db.close()
        add_flash('Bei Typ "Sonstige" ist eine Bemerkung Pflicht.', "error")
        return redirect(f"/absences/{absence_id}/edit")

    row = db.execute(
        "SELECT id, date_from AS df, date_to AS dt FROM absences WHERE id=? AND user_id=?",
        (absence_id, u["id"]),
    ).fetchone()
    if not row:
        db.close()
        abort(404)

    if _is_range_locked(u["id"], row["df"], row["dt"]) or (
        date_from and date_to and _is_range_locked(u["id"], date_from, date_to)
    ):
        db.close()
        add_flash(LOCK_MSG, "error")
        return redirect(f"/absences/{absence_id}/edit")
    if date_from:
        sd_err = _range_before_start_date(u["id"], date_from, date_to or date_from)
        if sd_err:
            db.close()
            add_flash(sd_err, "error")
            return redirect(f"/absences/{absence_id}/edit")

    if _has_overlap(db, u["id"], date_from, date_to, exclude_id=absence_id):
        db.close()
        add_flash("Überschneidung mit vorhandener Abwesenheit. Bitte Zeitraum anpassen.", "error")
        return redirect(f"/absences/{absence_id}/edit")

    db.execute(
        "UPDATE absences SET type_id=?, date_from=?, date_to=?, is_half_day=?, comment=?, updated_at=datetime('now') "
        "WHERE id=? AND user_id=?",
        (type_id, date_from, date_to, is_half_day, comment, absence_id, u["id"]),
    )
    if type_name == "Sonstige" and comment:
        db.execute("INSERT OR IGNORE INTO absence_remarks(user_id,remark) VALUES(?,?)", (u["id"], comment))
    db.commit()
    db.close()
    add_flash("Abwesenheit aktualisiert.", "success")
    return redirect(url_for("absences_list"))


@app.post("/absences/<int:absence_id>/delete")
@login_required
def absences_delete(absence_id: int):
    bootstrap()
    u = current_user()
    db = connect()
    row = db.execute(
        "SELECT date_from, date_to FROM absences WHERE id=? AND user_id=?",
        (absence_id, u["id"]),
    ).fetchone()
    if row and _is_range_locked(u["id"], row["date_from"], row["date_to"]):
        db.close()
        add_flash(LOCK_MSG, "error")
        return redirect(url_for("absences_list"))
    db.execute("DELETE FROM absences WHERE id=? AND user_id=?", (absence_id, u["id"]))
    db.commit()
    db.close()
    add_flash("Abwesenheit gelöscht.", "success")
    return redirect(url_for("absences_list"))




# -------------------------
# Kalender (Monatsansicht)
# -------------------------

def _month_range(year: int, month: int):
    first = datetime.date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = datetime.date(year, month, last_day)
    return first.isoformat(), last.isoformat()
CALENDAR_DAYMENU_ASSETS = (
"""
<style>
  td.daycell{
    position:relative;
    vertical-align:top;
    padding:0;
  }
  .dc-head{
    display:flex;
    align-items:center;
    justify-content:space-between;
    height:26px;
    padding:3px 4px 0 5px;
    box-sizing:border-box;
  }
  .dc-num{
    font-size:13px;
    font-weight:700;
    color:var(--tx);
    line-height:1;
  }
  td.daycell .addbtn{
    font-size:13px;
    font-weight:700;
    color:var(--mu);
    padding:1px 5px;
    border-radius:6px;
    background:var(--sf);
    border:1px solid var(--bd);
    text-decoration:none;
    line-height:1.4;
    opacity:0;
    flex-shrink:0;
    transition:opacity .15s;
  }
  td.daycell:hover .addbtn{ opacity:1; }
  .dc-time{
    height:20px;
    display:flex;
    align-items:center;
    padding:0 5px;
    font-size:11px;
    font-weight:600;
    color:var(--mu);
    overflow:hidden;
    white-space:nowrap;
    box-sizing:border-box;
  }
  .dc-abs{ overflow:visible; }
  .dc-exc{ font-size:9px; color:#f59e0b; vertical-align:middle; margin-left:2px; }
  td.daycell-before{ background:repeating-linear-gradient(135deg,transparent,transparent 4px,rgba(0,0,0,.03) 4px,rgba(0,0,0,.03) 8px); cursor:not-allowed; pointer-events:none; }
  .dc-hol{
    font-size:11px;
    font-weight:700;
    color:var(--danger);
    padding:2px 5px;
    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
  }
  .dc-trip{
    font-size:11px;
    color:var(--ac);
    padding:2px 5px;
    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
  }
  td.daycell .daymenu{
    display:none;
    position:fixed;
    min-width:190px;
    background:var(--sf);
    border:1px solid var(--bd);
    border-radius:10px;
    box-shadow:0 6px 24px rgba(0,0,0,.22);
    padding:6px;
    z-index:1500;
  }
  td.daycell .daymenu a{
    display:block;
    padding:6px 8px;
    border-radius:8px;
    color:var(--tx);
    text-decoration:none;
    font-size:13px;
  }
  td.daycell .daymenu a:hover{ background:var(--bd); }
</style>
"""
+ FORM_ASSETS_JS +
"""
<script>
  function _closeAllDayMenus(){
    try{
      document.querySelectorAll('.daymenu').forEach(function(m){
        m.style.display='none';
        m.removeAttribute('data-open');
      });
    }catch(e){}
  }

  function toggleDayMenu(menuId, ev){
    try{
      if(ev){ ev.preventDefault(); ev.stopPropagation(); }
      var m = document.getElementById(menuId);
      if(!m) return false;
      var isOpen = (m.getAttribute('data-open')==='1');
      _closeAllDayMenus();
      if(!isOpen){
        var btn = ev.currentTarget || ev.target;
        var r = btn.getBoundingClientRect();
        var menuW = 195;
        var left = Math.max(4, Math.min(r.right - menuW, window.innerWidth - menuW - 4));
        var top = r.bottom + 6;
        if(top + 140 > window.innerHeight){ top = Math.max(4, r.top - 144); }
        m.style.left = left + 'px';
        m.style.top  = top  + 'px';
        m.style.display = 'block';
        m.setAttribute('data-open','1');
      }
    }catch(e){}
    return false;
  }

  document.addEventListener('click', function(){ _closeAllDayMenus(); });
  document.addEventListener('keydown', function(e){
    if(e && e.key === 'Escape'){ _closeAllDayMenus(); }
  });
  document.addEventListener('scroll', function(){ _closeAllDayMenus(); }, true);
</script>
"""
)




@app.get("/calendar")
@login_required
def calendar_view():
    bootstrap()
    u = current_user()

    today = datetime.date.today()
    user_start_date = _get_tracking_start(u["id"])
    _def_y, _def_m = today.year, today.month
    if user_start_date:
        _sd = datetime.date.fromisoformat(user_start_date)
        if today < _sd:
            _def_y, _def_m = _sd.year, _sd.month
    year  = int(request.args.get("y") or _def_y)
    month = int(request.args.get("m") or _def_m)

    first_iso, last_iso = _month_range(year, month)

    db = connect()

    totals = {}
    for b in db.execute(
        "SELECT day, time_in, time_out, break_minutes FROM time_blocks WHERE user_id=? AND day BETWEEN ? AND ?",
        (u["id"], first_iso, last_iso),
    ).fetchall():
        day_iso = str(b["day"]).strip()[:10]
        mins = _minutes_from_hhmm(b["time_out"]) - _minutes_from_hhmm(b["time_in"]) - int(b["break_minutes"] or 0)
        totals[day_iso] = totals.get(day_iso, 0) + mins
    net_map = {d: _fmt_minutes(m) for d, m in totals.items()}

    hol_map = {
        str(r["day"]).strip()[:10]: r
        for r in db.execute(
            "SELECT day, is_holiday, holiday_name FROM calendar_days WHERE day BETWEEN ? AND ?",
            (first_iso, last_iso),
        ).fetchall()
    }

    abs_rows = db.execute(
        """SELECT a.date_from, a.date_to, a.is_half_day, a.comment, t.name AS type_name, t.color AS type_color
           FROM absences a JOIN absence_types t ON t.id = a.type_id
           WHERE a.user_id = ? AND NOT (a.date_to < ? OR a.date_from > ?)""",
        (u["id"], first_iso, last_iso),
    ).fetchall()

    trip_map = {}
    for r in db.execute(
        "SELECT start_date, end_date, destination FROM business_trips"
        " WHERE user_id=? AND start_date <= ? AND (end_date >= ? OR end_date IS NULL)",
        (u["id"], last_iso, first_iso),
    ).fetchall():
        s = str(r["start_date"])[:10]
        e = str(r["end_date"] or r["start_date"])[:10]
        for _td in _iter_days(s, e):
            if first_iso <= _td <= last_iso:
                trip_map[_td] = r["destination"]

    db.close()

    cal_contouring = _get_contouring_info(u["id"])
    contoured_month = _get_contoured_days(u["id"], first_iso, last_iso)
    exc_days_month = _get_weekend_exceptions_month(u["id"], first_iso, last_iso)

    day_badges = {}
    for a in abs_rows:
        d0 = datetime.date.fromisoformat(a["date_from"])
        d1 = datetime.date.fromisoformat(a["date_to"])
        cur = d0
        while cur <= d1:
            iso = cur.isoformat()
            txt = a["type_name"]
            if a["type_name"] == "Sonstige" and a["comment"]:
                txt += f": {a['comment']}"
            if a["is_half_day"] and a["date_from"] == a["date_to"]:
                txt += " (1/2)"
            vis_first = (cur == d0) or (cur.weekday() == 0)
            vis_last  = (cur == d1) or (cur.weekday() == 6)
            day_badges.setdefault(iso, []).append((txt, a["type_color"] or "#999", vis_first, vis_last))
            cur += datetime.timedelta(days=1)

    month_isos  = set(_iter_days(first_iso, last_iso))
    missing_days = _get_missing_entry_days(u["id"], year) & month_isos
    cal_locked  = _is_day_locked(u["id"], f"{year}-{month:02d}-01")
    lock_badge  = " \U0001f512" if cal_locked else ""

    _wd = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    # ── Desktop grid ──────────────────────────────────────────────────────────
    def _badge_html(items):
        out = ""
        for item in items[:4]:
            txt, col, vis_first, vis_last = item
            bg = col + "22"
            if vis_first and vis_last:
                radius = "6px"
                w_extra = "width:100%;box-sizing:border-box;"
            elif vis_first:
                radius = "6px 0 0 6px"
                w_extra = "width:calc(100% + 8px);margin-right:-8px;box-sizing:border-box;"
            elif vis_last:
                radius = "0 6px 6px 0"
                w_extra = "width:calc(100% + 8px);margin-left:-8px;box-sizing:border-box;"
            else:
                radius = "0"
                w_extra = "width:calc(100% + 16px);margin-left:-8px;margin-right:-8px;box-sizing:border-box;"
            out += (
                f"<div style='height:22px;line-height:22px;padding:0 6px;border-radius:{radius};"
                f"background:{bg};color:var(--tx);font-size:11px;position:relative;z-index:1;"
                f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap;{w_extra}'>"
                f"{txt}</div>"
            )
        if len(items) > 4:
            out += f"<div style='padding:1px 5px;color:var(--mu);font-size:10px;'>+{len(items)-4} mehr…</div>"
        return out

    def _week_num(week_days):
        for d in week_days:
            if d != 0:
                return datetime.date(year, month, d).isocalendar()[1]
        return ""

    def _day_cell(daynum):
        if daynum == 0:
            return "<td></td>"
        d   = datetime.date(year, month, daynum)
        iso = d.isoformat()
        wd  = _wd[d.weekday()]
        if user_start_date and iso < user_start_date:
            return (
                f"<td class='daycell daycell-before' title='Vor Arbeitsbeginn – kein Eintrag möglich'>"
                f"<div class='dc-head'><b class='dc-num' style='opacity:.4;'>{daynum}</b></div>"
                f"</td>"
            )
        hol = hol_map.get(iso)
        badges = day_badges.get(iso, [])
        net   = net_map.get(iso)
        trip  = trip_map.get(iso)

        has_entry   = bool(net or badges)
        is_kontiert = (iso in contoured_month) and has_entry
        is_missing  = iso in missing_days

        # Fixed-height time row (26px header + 20px time = abs section always at offset 46px)
        if is_missing:
            nh_h = (
                f"<div id='nh_{iso}' class='dc-time' data-net='' data-has-net='0'"
                f" style='color:var(--danger);font-size:13px;font-weight:700;'"
                f" title='Fehlender Eintrag'>✕</div>"
            )
        elif net:
            clr = "#b45309" if is_kontiert else "var(--mu)"
            txt = f"· {net}" if is_kontiert else net
            nh_h = (
                f"<div id='nh_{iso}' class='dc-time' data-net='{net}' data-has-net='1'"
                f" style='color:{clr};'>{txt}</div>"
            )
        else:
            dot = "·" if is_kontiert else ""
            clr_style = " style='color:#b45309;'" if is_kontiert else ""
            nh_h = (
                f"<div id='nh_{iso}' class='dc-time' data-net='' data-has-net='0'{clr_style}>{dot}</div>"
            )

        hol_html = (
            f"<div class='dc-hol'>{hol['holiday_name']}</div>"
            if hol and hol["is_holiday"] else ""
        )
        trip_h = f"<div class='dc-trip'>✈ {trip}</div>" if trip else ""

        contour_allowed = (
            cal_contouring["enabled"]
            and (not cal_contouring["start_date"] or iso >= cal_contouring["start_date"])
        )
        if not contour_allowed:
            km_item = ""
        elif is_kontiert:
            km_item = f"  <a href='#' id='km_{iso}' onclick=\"return toggleKontiert('{iso}', event);\">✕ Kontierung aufheben</a>"
        elif has_entry:
            km_item = f"  <a href='#' id='km_{iso}' onclick=\"return toggleKontiert('{iso}', event);\">✓ Als kontiert markieren</a>"
        else:
            km_item = f"  <span style='display:block;padding:6px 8px;font-size:13px;color:var(--mu);'>✓ Kontieren (kein Eintrag)</span>"
        exc_badge = "<span class='dc-exc' title='Ausnahme aktiv'>⚡</span>" if iso in exc_days_month else ""
        return (
            f"<td class='daycell' title='{wd}, {daynum:02d}.{month:02d}.{year}'>"
            f"<div class='dc-head'>"
            f"<b class='dc-num'>{daynum}{exc_badge}</b>"
            f"<a href='#' class='addbtn' title='Aktionen' onclick=\"return toggleDayMenu('m_{iso}', event);\">&#8943;</a>"
            f"</div>"
            f"{nh_h}"
            f"<div class='dc-abs'>{_badge_html(badges)}</div>"
            f"{trip_h}{hol_html}"
            f"<div id='m_{iso}' class='daymenu' onclick='event.stopPropagation();'>"
            f"  <a href='/day/{iso}'>⏱ Zeiten erfassen</a>"
            f"  <a href='/absences/new'>\U0001f3d6 Abwesenheit anlegen</a>"
            f"{km_item}"
            f"</div>"
            f"</td>"
        )

    cal_obj  = calendar.Calendar(firstweekday=0)
    weeks    = cal_obj.monthdayscalendar(year, month)
    grid_head = (
        "<tr><th class='kw-head'>KW</th>"
        + "".join(f"<th>{d}</th>" for d in _wd)
        + "</tr>"
    )
    grid_rows = "".join(
        f"<tr><td class='kw-cell'>{_week_num(w)}</td>"
        + "".join(_day_cell(d) for d in w)
        + "</tr>"
        for w in weeks
    )
    grid_html = f'<table style="margin-top:10px;table-layout:fixed;width:100%;"><thead>{grid_head}</thead><tbody>{grid_rows}</tbody></table>'

    # ── Mobile list ───────────────────────────────────────────────────────────
    list_rows = []
    d_it  = datetime.date(year, month, 1)
    d_end = datetime.date(year, month, calendar.monthrange(year, month)[1])
    while d_it <= d_end:
        iso      = d_it.isoformat()
        if user_start_date and iso < user_start_date:
            d_it += datetime.timedelta(days=1)
            continue
        wd       = _wd[d_it.weekday()]
        date_str = f"{d_it.day:02d}.{month:02d}."
        hol      = hol_map.get(iso)
        is_hol   = bool(hol and hol["is_holiday"])
        is_off   = d_it.weekday() >= 5 or is_hol
        is_today = d_it == today
        badges   = day_badges.get(iso, [])
        net      = net_map.get(iso)
        trip     = trip_map.get(iso)
        is_miss  = iso in missing_days

        row_cls = "cal-lr" + (" cal-lr-today" if is_today else "") + (" cal-lr-off" if is_off else "")

        cp = ""
        if net:
            cp += f"<span class='cal-lr-h'>{net}</span>"
        for txt, col, *_ in badges:
            cp += f"<span class='cal-lr-b' style='border-left:3px solid {col};padding-left:5px;'>{txt}</span>"
        if is_hol:
            cp += f"<span class='cal-lr-hol'>{hol['holiday_name']}</span>"
        if trip:
            cp += f"<span class='cal-lr-trip'>✈ {trip}</span>"

        cal_contour_visible = (
            cal_contouring["enabled"]
            and (not cal_contouring["start_date"] or iso >= cal_contouring["start_date"])
        )
        ic = ""
        if is_miss:
            ic = "<span class='cal-lr-x' title='Fehlender Eintrag'>✕</span>"
        elif cal_contour_visible and iso in contoured_month:
            ic = "<span class='cal-lr-ok' title='Kontiert'>✓</span>"
        elif cal_locked:
            ic = "<span class='cal-lr-lock'>\U0001f512</span>"

        list_rows.append(
            f"<a href='/day/{iso}' class='{row_cls}'>"
            f"<div class='cal-lr-date'><span class='cal-lr-wd'>{wd}</span><span class='cal-lr-dm'>{date_str}</span></div>"
            f"<div class='cal-lr-cnt'>{cp}</div>"
            f"<div class='cal-lr-ico'>{ic}</div>"
            f"</a>"
        )
        d_it += datetime.timedelta(days=1)

    list_html = "".join(list_rows)

    # ── Navigation ────────────────────────────────────────────────────────────
    prev_m, prev_y = (month - 1, year) if month > 1 else (12, year - 1)
    next_m, next_y = (month + 1, year) if month < 12 else (1, year + 1)
    month_label = f"{MONTH_NAMES_DE[month]} {year}"
    _prev_blocked = bool(
        user_start_date and
        datetime.date(prev_y, prev_m, 1) < datetime.date.fromisoformat(user_start_date).replace(day=1)
    )
    prev_nav_btn = (
        f"<span class='btn' style='padding:9px 14px;opacity:.35;cursor:not-allowed;'>&#9664;</span>"
        if _prev_blocked else
        f"<a class='btn' href='/calendar?y={prev_y}&m={prev_m}' style='padding:9px 14px;'>&#9664;</a>"
    )

    # ── Styles (plain strings – no f-string brace escaping needed) ────────────
    cal_css = """<style>
.cal-grid-wrap{display:block;}
.cal-list-wrap{display:none;border-top:1px solid var(--bd);margin-top:8px;}
@media(max-width:767px){
  .cal-grid-wrap{display:none;}
  .cal-list-wrap{display:block;}
}
[data-cal-view=month] .cal-grid-wrap{display:block!important;}
[data-cal-view=month] .cal-list-wrap{display:none!important;}
[data-cal-view=list]  .cal-grid-wrap{display:none!important;}
[data-cal-view=list]  .cal-list-wrap{display:block!important;}
.cal-lr{display:flex;align-items:center;gap:8px;padding:10px 4px;border-bottom:1px solid var(--bd);
  text-decoration:none;color:var(--tx);min-height:44px;-webkit-tap-highlight-color:transparent;}
.cal-lr:active{background:var(--bd);}
.cal-lr-today{background:rgba(37,99,235,.07);border-left:3px solid var(--ac);padding-left:5px;}
.cal-lr-off .cal-lr-wd,.cal-lr-off .cal-lr-dm{color:var(--mu);}
.cal-lr-date{min-width:64px;display:flex;flex-direction:column;line-height:1.3;flex-shrink:0;}
.cal-lr-wd{font-size:11px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;}
.cal-lr-dm{font-size:15px;font-weight:700;}
.cal-lr-cnt{flex:1;display:flex;flex-wrap:wrap;gap:4px 8px;align-items:center;min-width:0;}
.cal-lr-h{font-size:13px;font-weight:700;color:var(--ok);}
.cal-lr-b{font-size:12px;padding:2px 5px;background:var(--bg);border-radius:4px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px;}
.cal-lr-hol{font-size:12px;font-weight:700;color:var(--danger);}
.cal-lr-trip{font-size:12px;color:var(--ac);}
.cal-lr-ico{min-width:20px;text-align:right;flex-shrink:0;}
.cal-lr-x{color:var(--danger);font-size:14px;font-weight:700;}
.cal-lr-lock{font-size:13px;opacity:.55;}
.cal-lr-ok{color:var(--ok);font-size:14px;font-weight:700;}
th.kw-head{width:32px;font-size:10px;color:var(--mu);font-weight:600;text-align:center;padding:4px 2px;}
td.kw-cell{width:32px;font-size:10px;color:var(--mu);font-weight:600;text-align:center;vertical-align:middle;padding:2px;white-space:nowrap;}
</style>"""

    cal_js = """<script>
function setCalView(v){
  try{
    localStorage.setItem('cal_view',v);
    var w=document.getElementById('cal-wrap');
    if(w) w.setAttribute('data-cal-view',v);
    var bm=document.getElementById('cal-tb-month');
    var bl=document.getElementById('cal-tb-list');
    if(bm) bm.classList.toggle('primary',v==='month');
    if(bl) bl.classList.toggle('primary',v==='list');
  }catch(e){}
}
(function(){
  try{ var v=localStorage.getItem('cal_view'); if(v) setCalView(v); }catch(e){}
})();
</script>"""

    js_kontiert_arr = "[" + ",".join(f'"{d}"' for d in sorted(contoured_month)) + "]"
    contour_js = f"""<script>
var _kontiert=new Set({js_kontiert_arr});
function toggleKontiert(iso,ev){{
  if(ev){{ev.preventDefault();ev.stopPropagation();}}
  var isK=_kontiert.has(iso);
  fetch('/api/contour',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{day:iso,action:isK?'unmark':'mark'}})
  }}).then(function(r){{return r.json();}}).then(function(d){{
    if(!d.ok)return;
    var nh=document.getElementById('nh_'+iso);
    var km=document.getElementById('km_'+iso);
    var hasNet=nh&&nh.dataset.hasNet==='1';
    var netVal=nh?(nh.dataset.net||''):'';
    if(isK){{
      _kontiert.delete(iso);
      if(nh){{
        if(hasNet){{nh.style.color='var(--mu)';nh.textContent=netVal;}}
        else{{nh.textContent='';nh.style.color='';}}
      }}
      if(km)km.textContent='✓ Als kontiert markieren';
    }}else{{
      _kontiert.add(iso);
      if(nh){{
        if(hasNet){{nh.style.color='#b45309';nh.textContent='· '+netVal;}}
        else{{nh.textContent='·';nh.style.color='#b45309';}}
      }}
      if(km)km.textContent='✕ Kontierung aufheben';
    }}
  }}).catch(function(){{}});
  return false;
}}
</script>"""

    body = f"""
    {flash_html()}
    {CALENDAR_DAYMENU_ASSETS}
    {cal_css}
    {contour_js}

    <div id="cal-wrap" class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
        <div style="display:flex;align-items:center;gap:4px;">
          {prev_nav_btn}
          <span style="font-size:16px;font-weight:700;padding:0 6px;white-space:nowrap;">{month_label}{lock_badge}</span>
          <a class="btn" href="/calendar?y={next_y}&m={next_m}" style="padding:9px 14px;">&#9654;</a>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          <a class="btn" href="/calendar?y={today.year}&m={today.month}">Heute</a>
          <button id="cal-tb-month" class="btn" type="button" onclick="setCalView('month')" style="font-size:13px;padding:8px 10px;">&#8862; Monat</button>
          <button id="cal-tb-list"  class="btn" type="button" onclick="setCalView('list')"  style="font-size:13px;padding:8px 10px;">&#9776; Liste</button>
        </div>
      </div>

      <div class="small" style="margin-top:8px;display:flex;gap:12px;flex-wrap:wrap;align-items:center;">
        <span><span style="display:inline-block;width:10px;height:10px;background:#999;border-radius:2px;margin-right:4px;vertical-align:middle;"></span>Abwesenheit</span>
        <span style="font-weight:700;color:var(--danger);">&#9679; Feiertag</span>
        <span style="color:var(--ok);font-weight:700;">HH:MM</span> erfasst
        <span style="color:var(--danger);font-weight:700;">&#10005;</span> fehlend
        <span style="color:#b45309;font-weight:700;">·</span> kontiert (Zeitangabe in Bernstein)
      </div>

      <div class="cal-grid-wrap">
        {grid_html}
      </div>

      <div class="cal-list-wrap">
        {list_html}
      </div>
    </div>

    {cal_js}
    """
    return render_template_string(layout("Kalender", body, u, APP_VERSION))





# -------------------------
# Tages-Editor (Zeitblöcke + Abwesenheit) – v2.9.1
# -------------------------

def _round_to_15(hhmm: str) -> str:
    """Round HH:MM minutes to nearest 15; returns unchanged string if not HH:MM."""
    if not hhmm or not re.match(r"^\d{2}:\d{2}$", hhmm):
        return hhmm
    h, m = int(hhmm[:2]), int(hhmm[3:])
    r = round(m / 15) * 15
    if r == 60:
        r, h = 0, (h + 1) % 24
    return f"{h:02d}:{r:02d}"


def _validate_block(time_in: str, time_out: str, break_minutes: int) -> tuple[bool, str]:
    if not re.match(r"^\d{2}:\d{2}$", time_in) or not re.match(r"^\d{2}:\d{2}$", time_out):
        return False, "Bitte Zeiten im Format HH:MM angeben."
    s = _minutes_from_hhmm(time_in)
    e = _minutes_from_hhmm(time_out)
    if e <= s:
        return False, "Gehen muss nach Kommen liegen."
    if break_minutes < 0:
        return False, "Pause darf nicht negativ sein."
    if break_minutes >= (e - s):
        return False, "Pause ist zu groß (>= Blockdauer)."
    return True, ""


def _exception_banner(day: str, is_blocked_day: bool, exc_row, locked: bool) -> str:
    if not is_blocked_day:
        return ""
    if exc_row is not None:
        note = exc_row["note"] or ""
        note_html = f" &ndash; <i>{note}</i>" if note else ""
        remove_btn = "" if locked else (
            f"<form method='post' action='/api/remove-exception' style='margin:0;'>"
            f"<input type='hidden' name='day' value='{day}'>"
            f"<button class='btn danger' type='submit' style='padding:6px 12px;font-size:13px;'>Ausnahme entfernen</button>"
            f"</form>"
        )
        return (
            f"<div class='card' style='margin-top:10px;border-color:#16a34a;background:rgba(22,163,74,.07);'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;'>"
            f"<div><b style='color:#16a34a;'>⚡ Ausnahme aktiv</b>{note_html}"
            f"<div class='small' style='margin-top:2px;'>Zeitblöcke an diesem Wochenende/Feiertag sind erlaubt.</div></div>"
            f"{remove_btn}</div></div>"
        )
    set_form = "" if locked else (
        f"<form method='post' action='/api/set-exception' style='display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:10px;'>"
        f"<input type='hidden' name='day' value='{day}'>"
        f"<div><label style='font-size:13px;'>Grund <span style='color:var(--mu);'>(optional)</span></label><br>"
        f"<input name='note' placeholder='z.B. Notfalleinsatz' style='max-width:260px;'></div>"
        f"<button class='btn primary' type='submit'>Ausnahme setzen</button>"
        f"</form>"
    )
    return (
        f"<div class='card' style='margin-top:10px;border-color:#f59e0b;background:rgba(245,158,11,.07);'>"
        f"<b style='color:#b45309;'>⚠ Wochenende / Feiertag – Speichern blockiert</b>"
        f"<p class='small' style='margin:6px 0 0;'>Zeitblöcke für diesen Tag können erst eingetragen werden, nachdem eine Ausnahme gesetzt wurde.</p>"
        f"{set_form}</div>"
    )


@app.get("/day/<day>")
@login_required
def day_detail(day: str):
    bootstrap()
    u = current_user()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        abort(400)

    db = connect()
    blocks = db.execute(
        "SELECT id, time_in, time_out, break_minutes, comment FROM time_blocks WHERE user_id=? AND day=? ORDER BY time_in",
        (u["id"], day),
    ).fetchall()

    # existing absence (any overlap that day)
    abs_row = db.execute(
        """
        SELECT a.id, a.is_half_day, t.name AS type_name, t.color AS type_color, a.comment
        FROM absences a
        JOIN absence_types t ON t.id=a.type_id
        WHERE a.user_id=? AND NOT (a.date_to < ? OR a.date_from > ?)
        ORDER BY a.id DESC
        LIMIT 1
        """,
        (u["id"], day, day),
    ).fetchone()

    abs_types = db.execute("SELECT id, name FROM absence_types WHERE active=1 ORDER BY name").fetchall()
    abs_sonstige_id = next((t["id"] for t in abs_types if t["name"] == "Sonstige"), 0)
    abs_user_remarks = [r["remark"] for r in db.execute(
        "SELECT remark FROM absence_remarks WHERE user_id=? ORDER BY remark", (u["id"],)
    ).fetchall()]
    trip = db.execute(
        "SELECT * FROM business_trips WHERE user_id=? AND start_date <= ? AND (end_date >= ? OR end_date IS NULL) ORDER BY id DESC LIMIT 1",
        (u["id"], day, day),
    ).fetchone()
    db.close()

    total = 0
    for b in blocks:
        total += (_minutes_from_hhmm(b["time_out"]) - _minutes_from_hhmm(b["time_in"]) - int(b["break_minutes"] or 0))

    # exception banner data
    sched_day = _get_user_schedule(u["id"])
    is_blocked_day = (
        int(sched_day.get("block_weekends_holidays", 1)) == 1
        and (_is_weekend(day) or _is_holiday(day))
    )
    exc_row = _get_weekend_exception(u["id"], day) if is_blocked_day else None

    # prev/next navigation
    try:
        dcur = datetime.date.fromisoformat(day)
        prev_day = (dcur - datetime.timedelta(days=1)).isoformat()
        next_day = (dcur + datetime.timedelta(days=1)).isoformat()
    except Exception:
        prev_day = day
        next_day = day

    day_locked = _is_day_locked(u["id"], day)

    blocks_html = ""
    for b in blocks:
        mins = _minutes_from_hhmm(b["time_out"]) - _minutes_from_hhmm(b["time_in"]) - int(b["break_minutes"] or 0)
        if day_locked:
            actions = ""
        else:
            actions = (
                f"<div style='display:flex;gap:10px;align-items:center;'>"
                f"<a href='/day/{day}/block/{b['id']}/edit'>Bearbeiten</a>"
                f"<form method='post' action='/day/{day}/block/delete' style='margin:0;' onsubmit=\"return confirm('Zeitblock wirklich löschen?');\">"
                f"<input type='hidden' name='block_id' value='{b['id']}'>"
                f"<button class='btn danger' type='submit'>Löschen</button></form></div>"
            )
        cmt = f"<div class='small'>{b['comment']}</div>" if b["comment"] else ""
        blocks_html += (
            f"<div class='card' style='margin-top:10px;'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;'>"
            f"<div><b>{b['time_in']}–{b['time_out']}</b> · Pause {int(b['break_minutes'] or 0)} min"
            f" · <b>{_fmt_minutes(mins)}</b></div>"
            f"{actions}</div>{cmt}</div>"
        )

    abs_html = ""
    if abs_row:
        abs_html = f"""
        <div class="card" style="margin-top:10px;">
          <b>Abwesenheit:</b> <span style="display:inline-block;width:10px;height:10px;background:{abs_row['type_color'] or '#999'};border-radius:2px;margin-right:6px;"></span>{abs_row['type_name']}{" (1/2)" if abs_row['is_half_day'] else ""}
          {f"<div class='small'>{abs_row['comment']}</div>" if abs_row['comment'] else ""}
          <div class="small" style="margin-top:6px;color:#777;">Abwesenheiten bearbeitest du im Modul "Abwesenheiten".</div>
        </div>
        """

    abs_opts = "".join([f"<option value='{t['id']}'>{t['name']}</option>" for t in abs_types])
    abs_sonstige_id_js = abs_sonstige_id
    abs_remark_html = _remark_select_html(abs_user_remarks, pfx="d_")

    _lock_notice = (
        "<div class='card' style='margin-top:10px;background:var(--sf);border-color:var(--bd);'>"
        "<p style='margin:0;'>🔒 <b>Monat abgeschlossen</b> – Dieser Zeitraum kann nicht mehr bearbeitet werden. "
        "<a href=\"/periods\">Abschlüsse verwalten</a></p></div>"
    ) if day_locked else ""

    _add_block_form = "" if day_locked else f"""
    <div class="card" style="margin-top:10px;">
      <h3 style="margin-top:0;">Zeitblock hinzufügen</h3>
      <form method="post" action="/day/{day}/block/add" id="block-add-form" novalidate onsubmit="return validateBlockForm(this)">
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <div><label>Kommen</label><br><input class="tin" id="tin_add" name="time_in" type="time" list="time_suggestions" placeholder="HH:MM" required></div>
          <div><label>Gehen</label><br><input class="tout" id="tout_add" name="time_out" type="time" list="time_suggestions" placeholder="HH:MM" required></div>
          <div><label>Pause (min)</label><br><input id="brk_day_add" class="brk" name="break_minutes" type="number" min="0" value="0" required>
<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;"><button class="btn" type="button" style="padding:4px 8px;" onclick="document.getElementById('brk_day_add').value='30'">30</button><button class="btn" type="button" style="padding:4px 8px;" onclick="document.getElementById('brk_day_add').value='45'">45</button><button class="btn" type="button" style="padding:4px 8px;" onclick="document.getElementById('brk_day_add').value='60'">60</button></div></div>
        </div>
        <div style="margin-top:8px;"><label>Kommentar</label><br><input name="comment" placeholder="optional" style="width:100%;"></div>
        <div id="block-add-err" style="display:none;margin-top:8px;padding:6px 10px;background:rgba(220,38,38,.1);border-radius:6px;color:var(--danger);font-size:13px;"></div>
        <button class="btn" type="submit" style="margin-top:10px;">Speichern</button>
      </form>
    </div>
<script>
function validateBlockForm(form) {{
  var tin  = form.querySelector('[name="time_in"]');
  var tout = form.querySelector('[name="time_out"]');
  var err  = form.querySelector('[id$="-err"]') || form.querySelector('[id*="err"]');
  function showErr(msg) {{
    if (err) {{ err.textContent = msg; err.style.display = 'block'; }}
    else {{ alert(msg); }}
    return false;
  }}
  var tval = /^\\d{{2}}:\\d{{2}}$/;
  if (!tin.value || !tval.test(tin.value))  return showErr('Bitte gültige Kommen-Zeit im Format HH:MM eingeben.');
  if (!tout.value || !tval.test(tout.value)) return showErr('Bitte gültige Gehen-Zeit im Format HH:MM eingeben.');
  var s = parseInt(tin.value.replace(':',''),10);
  var e = parseInt(tout.value.replace(':',''),10);
  if (e <= s) return showErr('Gehen muss nach Kommen liegen.');
  if (err) err.style.display = 'none';
  return true;
}}
</script>"""

    _add_absence_form = "" if day_locked else f"""
    <div class="card" style="margin-top:10px;">
      <h3 style="margin-top:0;">Abwesenheit hinzufügen (optional)</h3>
      <form method="post" action="/day/{day}/absence/add">
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:end;">
          <div><label>Typ</label><br><select name="type_id" id="day_type_sel" required onchange="syncDayBemerkung(this)">{abs_opts}</select></div>
          <label style="margin-left:8px;"><input type="checkbox" name="is_half_day" value="1"> halber Tag</label>
        </div>
        <div id="d_remark_row" style="display:none;margin-top:8px;">{abs_remark_html}</div>
        <button class="btn" type="submit" style="margin-top:10px;">Abwesenheit speichern</button>
      </form>
      <div class="small" style="margin-top:6px;color:#777;">Wenn bereits eine Abwesenheit existiert, wird keine neue angelegt.</div>
    </div>
<script>
{_REMARK_JS}
function syncDayBemerkung(sel) {{
  var isSonstige = String(sel.value) === String({abs_sonstige_id_js});
  document.getElementById("d_remark_row").style.display = isSonstige ? "" : "none";
  if (isSonstige) syncRemarkNew("d_remark_new_row","d_remark_new_inp",document.getElementById("d_remark_sel"));
}}
syncDayBemerkung(document.getElementById("day_type_sel"));
</script>"""

    body = f"""
    {flash_html()}

<script>
  function syncTimeMin(startId, endId){{
    try{{
      const s = document.getElementById(startId);
      const e = document.getElementById(endId);
      if(!s || !e) return;
      if(s.value){{
        e.min = s.value;
        if(e.value && e.value <= s.value){{ e.value = ''; }}
      }} else {{ e.min = ''; }}
    }}catch(_){{}}
  }}
  function setBreak(id, val){{
    const el = document.getElementById(id);
    if(!el) return;
    el.value = String(val);
  }}
</script>

    {FORM_ASSETS_JS}

    {_timepicker_datalist('time_suggestions')}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <div style="display:flex;align-items:center;gap:10px;">
          <button class="btn" type="button"
            onclick="if(history.length>1){{history.back();}}else{{location.href='/';}}">← Zurück</button>
          <h3 style="margin:0;">Tages-Editor – {day}</h3>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <a class="btn" href="/day/{prev_day}">◀︎ Vorheriger Tag</a>
          <a class="btn" href="/calendar?y={day[:4]}&m={int(day[5:7])}">Kalender</a>
          <a class="btn" href="/day/{next_day}">Nächster Tag ▶︎</a>
        </div>
      </div>
      <p class="small">Mehrere Zeitblöcke pro Tag möglich. Netto-Summe: <b>{_fmt_minutes(total)}</b></p>
    </div>

    {_exception_banner(day, is_blocked_day, exc_row, day_locked)}
    {_lock_notice}

    {_add_block_form}

    <h3 style="margin-top:14px;">Vorhandene Zeitblöcke</h3>
    {blocks_html or "<div class='small' style='color:#777;'>Keine Zeitblöcke erfasst.</div>"}

    {_add_absence_form}

    <h3 style="margin-top:14px;">Vorhandene Abwesenheit</h3>
    {abs_html or "<div class='small' style='color:#777;'>Keine Abwesenheit an diesem Tag.</div>"}

    {_business_trip_section(day, trip, locked=day_locked)}
    """
    return render_template_string(layout("Tages-Editor", body, u, APP_VERSION))


def _business_trip_section(day: str, trip, locked: bool = False) -> str:
    """Render the Dienstreise card for the day editor."""
    t = dict(trip) if trip else {}
    trip_id   = t.get("id") or ""
    dest      = t.get("destination") or ""
    dep       = t.get("departure_time") or ""
    dep_e     = t.get("departure_end_time") or ""
    ret       = t.get("return_time") or ""
    ret_e     = t.get("return_end_time") or ""
    notes     = t.get("notes") or ""
    start_iso = str(t.get("start_date") or day)[:10]
    end_iso   = str(t.get("end_date") or start_iso)[:10]
    is_multi  = (start_iso != end_iso)
    multi_checked = "checked" if is_multi else ""
    multi_display = "" if is_multi else "none"

    delete_btn = ""
    if trip_id and not locked:
        delete_btn = f"""
        <form method="post" action="/day/{day}/business_trip/delete" style="display:inline;"
              onsubmit="return confirm('Dienstreise löschen?');">
          <input type="hidden" name="trip_id" value="{trip_id}">
          <button class="btn danger" type="submit" style="margin-left:8px;">Löschen</button>
        </form>"""

    heading = "✈ Dienstreise bearbeiten" if trip else "✈ Dienstreise hinzufügen"
    if locked:
        heading = "✈ Dienstreise (schreibgeschützt)"

    return f"""
    <h3 style="margin-top:14px;">Dienstreise</h3>
    <div class="card" style="margin-top:4px;">
      <h3 style="margin-top:0;">{heading}</h3>
      <form method="post" action="/day/{day}/business_trip/save">
        <input type="hidden" name="trip_id" value="{trip_id}">
        <div style="margin-bottom:8px;">
          <label>Ort *</label><br>
          <input name="destination" required value="{dest}" placeholder="Reiseziel" style="max-width:360px;">
        </div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:8px;align-items:flex-end;">
          <div>
            <label>Startdatum *</label><br>
            {_date_input("start_date", start_iso, required=True)}
          </div>
          <div>
            <label style="font-weight:400;"><input type="checkbox" onchange="toggleMultiday(this)" {multi_checked}> Mehrtägig</label>
          </div>
        </div>
        <div class="multiday-fields" style="display:{multi_display};margin-bottom:8px;">
          <label>Enddatum</label><br>
          {_date_input("end_date", end_iso if is_multi else "")}
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;">
          <div><label>Abreise</label><br>{_time_input("departure_time", dep)}</div>
          <div><label>Ankunft Ziel</label><br>{_time_input("departure_end_time", dep_e)}</div>
          <div><label>Rückreise Start</label><br>{_time_input("return_time", ret)}</div>
          <div><label>Ankunft Zuhause</label><br>{_time_input("return_end_time", ret_e)}</div>
        </div>
        <div style="margin-bottom:8px;">
          <label>Notizen</label><br>
          <textarea name="notes" rows="2" placeholder="optional">{notes}</textarea>
        </div>
        {"" if locked else '<button class="btn" type="submit">Dienstreise speichern</button>'}
        {delete_btn}
      {"</form>" if not locked else "<p class='small' style='margin-top:6px;'>🔒 Schreibgeschützt</p>"}
    </div>"""


@app.post("/day/<day>/business_trip/save")
@login_required
def day_business_trip_save(day: str):
    bootstrap()
    u = current_user()
    day = str(day).strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        abort(400)
    if _is_day_locked(u["id"], day):
        add_flash(LOCK_MSG, "error")
        return redirect(f"/day/{day}")
    destination = (request.form.get("destination") or "").strip()
    if not destination:
        add_flash("Ort ist Pflichtfeld.", "error")
        return redirect(f"/day/{day}")
    start_date = _parse_date_input(request.form.get("start_date") or day)
    if not start_date:
        add_flash("Ungültiges Startdatum.", "error")
        return redirect(f"/day/{day}")
    sd_err = _before_start_date(u["id"], start_date)
    if sd_err:
        add_flash(sd_err, "error")
        return redirect(f"/day/{day}")
    end_date_raw = (request.form.get("end_date") or "").strip()
    end_date = _parse_date_input(end_date_raw) if end_date_raw else start_date
    if end_date and end_date < start_date:
        end_date = start_date
    departure_time     = _round_to_15((request.form.get("departure_time") or "").strip()) or None
    departure_end_time = _round_to_15((request.form.get("departure_end_time") or "").strip()) or None
    return_time        = _round_to_15((request.form.get("return_time") or "").strip()) or None
    return_end_time    = _round_to_15((request.form.get("return_end_time") or "").strip()) or None
    notes              = (request.form.get("notes") or "").strip() or None
    trip_id            = (request.form.get("trip_id") or "").strip() or None
    db = connect()
    if trip_id:
        db.execute(
            """UPDATE business_trips SET
                 start_date=?, end_date=?, destination=?,
                 departure_time=?, departure_end_time=?,
                 return_time=?, return_end_time=?, notes=?, updated_at=datetime('now')
               WHERE id=? AND user_id=?""",
            (start_date, end_date, destination, departure_time, departure_end_time,
             return_time, return_end_time, notes, int(trip_id), u["id"]),
        )
    else:
        db.execute(
            """INSERT INTO business_trips
                   (user_id, start_date, end_date, destination, departure_time, departure_end_time,
                    return_time, return_end_time, notes, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(user_id, start_date) DO UPDATE SET
                 end_date=excluded.end_date,
                 destination=excluded.destination,
                 departure_time=excluded.departure_time,
                 departure_end_time=excluded.departure_end_time,
                 return_time=excluded.return_time,
                 return_end_time=excluded.return_end_time,
                 notes=excluded.notes,
                 updated_at=datetime('now')""",
            (u["id"], start_date, end_date, destination, departure_time, departure_end_time,
             return_time, return_end_time, notes),
        )
    db.commit()
    db.close()
    add_flash("Dienstreise gespeichert.", "success")
    return redirect(f"/day/{day}")


@app.post("/day/<day>/business_trip/delete")
@login_required
def day_business_trip_delete(day: str):
    bootstrap()
    u = current_user()
    day = str(day).strip()[:10]
    if _is_day_locked(u["id"], day):
        add_flash(LOCK_MSG, "error")
        return redirect(f"/day/{day}")
    trip_id = (request.form.get("trip_id") or "").strip()
    db = connect()
    if trip_id:
        db.execute("DELETE FROM business_trips WHERE id=? AND user_id=?", (int(trip_id), u["id"]))
    else:
        db.execute("DELETE FROM business_trips WHERE user_id=? AND start_date=?", (u["id"], day))
    db.commit()
    db.close()
    add_flash("Dienstreise gelöscht.", "success")
    return redirect(f"/day/{day}")


@app.post("/day/<day>/block/add")
@login_required
def day_block_add(day: str):
    bootstrap()
    u = current_user()
    # Normalize to YYYY-MM-DD so calendar and DB always match
    day = str(day).strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        add_flash("Ungültiges Datum.", "error")
        return redirect("/calendar")
    if _is_day_locked(u["id"], day):
        add_flash(LOCK_MSG, "error")
        return redirect(f"/day/{day}")
    sd_err = _before_start_date(u["id"], day)
    if sd_err:
        add_flash(sd_err, "error")
        return redirect(f"/day/{day}")
    sched = _get_user_schedule(u['id'])
    if int(sched.get('block_weekends_holidays',1)) == 1:
        if _is_weekend(day) or _is_holiday(day):
            if not _has_weekend_exception(u['id'], day):
                if request.form.get('override_nonwork'):
                    if request.form.get('save_exception'):
                        _set_weekend_exception(u['id'], day, (request.form.get('exception_note') or '').strip()[:200])
                else:
                    add_flash('Arbeiten an Wochenende/Feiertag ist blockiert. Setze zuerst eine Ausnahme für diesen Tag.', 'error')
                    return redirect(f"/day/{day}")
    time_in = _round_to_15((request.form.get("time_in") or "").strip())
    time_out = _round_to_15((request.form.get("time_out") or "").strip())
    break_minutes = int(request.form.get("break_minutes") or 0)
    comment = (request.form.get("comment") or "").strip()

    ok, msg = _validate_block(time_in, time_out, break_minutes)
    if not ok:
        add_flash(msg, "error")
        return redirect(f"/day/{day}")

    s = _minutes_from_hhmm(time_in)
    e = _minutes_from_hhmm(time_out)

    # automatische Pausen (optional)
    if _get_pref_auto_breaks(u["id"]) == 1:
        break_minutes = _apply_auto_breaks_if_needed(e - s, break_minutes)
        if break_minutes >= (e - s):
            add_flash("Pause ist zu groß (>= Blockdauer).", "error")
            return redirect(f"/day/{day}")

    db = connect()
    existing = db.execute("SELECT time_in, time_out FROM time_blocks WHERE user_id=? AND day=?", (u["id"], day)).fetchall()
    for r in existing:
        s2 = _minutes_from_hhmm(r["time_in"])
        e2 = _minutes_from_hhmm(r["time_out"])
        if not (e <= s2 or s >= e2):
            db.close()
            add_flash("Zeitblock überschneidet sich mit vorhandenem Block.", "error")
            return redirect(f"/day/{day}")

    db.execute(
        "INSERT INTO time_blocks(user_id, day, time_in, time_out, break_minutes, comment, updated_at) VALUES(?,?,?,?,?,?,datetime('now'))",
        (u["id"], day, time_in, time_out, break_minutes, comment),
    )
    db.commit()
    db.close()
    add_flash("Zeitblock gespeichert.", "success")
    return redirect(f"/day/{day}")


@app.get("/day/<day>/block/<int:block_id>/edit")
@login_required
def day_block_edit(day: str, block_id: int):
    bootstrap()
    u = current_user()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        abort(400)
    if _is_day_locked(u["id"], day):
        add_flash(LOCK_MSG, "error")
        return redirect(f"/day/{day}")

    db = connect()
    b = db.execute(
        "SELECT id, time_in, time_out, break_minutes, comment FROM time_blocks WHERE id=? AND user_id=? AND day=?",
        (int(block_id), int(u["id"]), day),
    ).fetchone()
    db.close()
    if not b:
        abort(404)

    body = f"""
    {flash_html()}

<script>
  function syncTimeMin(startId, endId){{
    try{{
      const s = document.getElementById(startId);
      const e = document.getElementById(endId);
      if(!s || !e) return;
      if(s.value){{
        e.min = s.value;
        if(e.value && e.value <= s.value){{ e.value = ''; }}
      }} else {{ e.min = ''; }}
    }}catch(_){{}}
  }}
  function setBreak(id, val){{
    const el = document.getElementById(id);
    if(!el) return;
    el.value = String(val);
  }}
</script>

    {_timepicker_datalist('time_suggestions')}
    <script>
      function setBreakBtn(btn, mins){{
        const f = btn.closest('form');
        if (!f) return false;
        const el = f.querySelector('.brk');
        if (el) el.value = String(mins);
        return false;
      }}
    </script>
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Zeitblock bearbeiten – {day}</h3>
        <a class="btn" href="/day/{day}">Zurück</a>
      </div>

      <form method="post" action="/day/{day}/block/{block_id}/edit" style="margin-top:10px;" novalidate onsubmit="return validateBlockForm(this)">
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <div><label>Kommen</label><br><input class="tin" name="time_in" type="time" list="time_suggestions" placeholder="HH:MM" value="{b['time_in']}" required></div>
          <div><label>Gehen</label><br><input class="tout" name="time_out" type="time" list="time_suggestions" placeholder="HH:MM" value="{b['time_out']}" required></div>
          <div><label>Pause (min)</label><br><input id="brk_day_edit" class="brk" name="break_minutes" type="number" min="0" value="{int(b['break_minutes'] or 0)}" required>
<div style='margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;'><button class='btn' type='button' style='padding:4px 8px;' onclick="document.getElementById('brk_day_edit').value='30'">30</button><button class='btn' type='button' style='padding:4px 8px;' onclick="document.getElementById('brk_day_edit').value='45'">45</button><button class='btn' type='button' style='padding:4px 8px;' onclick="document.getElementById('brk_day_edit').value='60'">60</button></div></div>
          <div class='small' style='display:flex;gap:6px;align-items:center;margin-top:6px;'><span style='color:#777;'>Schnellwahl:</span><a href="#" class="btn" style="padding:4px 8px;" onclick="return setBreak(this,30);">30</a><a href="#" class="btn" style="padding:4px 8px;" onclick="return setBreak(this,45);">45</a><a href="#" class="btn" style="padding:4px 8px;" onclick="return setBreak(this,60);">60</a><span style='color:#777;'>min</span></div>
        </div>
        <div style="margin-top:8px;"><label>Kommentar</label><br><input name="comment" value="{(b['comment'] or '')}" placeholder="optional" style="width:100%;"></div>
        <div id="block-edit-err" style="display:none;margin-top:8px;padding:6px 10px;background:rgba(220,38,38,.1);border-radius:6px;color:var(--danger);font-size:13px;"></div>
        <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;">
          <button class="btn" type="submit">Speichern</button>
          <a class="btn" href="/day/{day}">Abbrechen</a>
        </div>
      </form>
    </div>
<script>
function validateBlockForm(form) {{
  var tin  = form.querySelector('[name="time_in"]');
  var tout = form.querySelector('[name="time_out"]');
  var err  = form.querySelector('[id$="-err"]') || form.querySelector('[id*="err"]');
  function showErr(msg) {{
    if (err) {{ err.textContent = msg; err.style.display = 'block'; }}
    else {{ alert(msg); }}
    return false;
  }}
  var tval = /^\\d{{2}}:\\d{{2}}$/;
  if (!tin.value || !tval.test(tin.value))  return showErr('Bitte gültige Kommen-Zeit im Format HH:MM eingeben.');
  if (!tout.value || !tval.test(tout.value)) return showErr('Bitte gültige Gehen-Zeit im Format HH:MM eingeben.');
  var s = parseInt(tin.value.replace(':',''),10);
  var e = parseInt(tout.value.replace(':',''),10);
  if (e <= s) return showErr('Gehen muss nach Kommen liegen.');
  if (err) err.style.display = 'none';
  return true;
}}
</script>
    """
    return render_template_string(layout("Zeitblock bearbeiten", body, u, APP_VERSION))


@app.post("/day/<day>/block/<int:block_id>/edit")
@login_required
def day_block_edit_post(day: str, block_id: int):
    bootstrap()
    u = current_user()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        abort(400)
    if _is_day_locked(u["id"], day):
        add_flash(LOCK_MSG, "error")
        return redirect(f"/day/{day}")
    sd_err = _before_start_date(u["id"], day)
    if sd_err:
        add_flash(sd_err, "error")
        return redirect(f"/day/{day}/block/{block_id}/edit")

    sched = _get_user_schedule(u['id'])
    if int(sched.get('block_weekends_holidays', 1)) == 1:
        if _is_weekend(day) or _is_holiday(day):
            if not _has_weekend_exception(u['id'], day):
                if request.form.get('override_nonwork'):
                    if request.form.get('save_exception'):
                        _set_weekend_exception(u['id'], day, (request.form.get('exception_note') or '').strip()[:200])
                else:
                    add_flash('Arbeiten an Wochenende/Feiertag ist blockiert. Setze zuerst eine Ausnahme für diesen Tag.', 'error')
                    return redirect(f"/day/{day}/block/{block_id}/edit")

    time_in = _round_to_15((request.form.get("time_in") or "").strip())
    time_out = _round_to_15((request.form.get("time_out") or "").strip())
    try:
        break_minutes = int(request.form.get("break_minutes") or 0)
    except Exception:
        break_minutes = 0
    comment = (request.form.get("comment") or "").strip()

    ok, msg = _validate_block(time_in, time_out, break_minutes)
    if not ok:
        add_flash(msg, "error")
        return redirect(f"/day/{day}/block/{block_id}/edit")

    s = _minutes_from_hhmm(time_in)
    e = _minutes_from_hhmm(time_out)

    # automatische Pausen (optional)
    if _get_pref_auto_breaks(u["id"]) == 1:
        break_minutes = _apply_auto_breaks_if_needed(e - s, break_minutes)
        if break_minutes >= (e - s):
            add_flash("Pause ist zu groß (>= Blockdauer).", "error")
            return redirect(f"/day/{day}/block/{block_id}/edit")

    db = connect()
    # ensure block exists and belongs to user
    b = db.execute(
        "SELECT id FROM time_blocks WHERE id=? AND user_id=? AND day=?",
        (int(block_id), int(u["id"]), day),
    ).fetchone()
    if not b:
        db.close()
        abort(404)

    # overlap check excluding the current block
    existing = db.execute(
        "SELECT id, time_in, time_out FROM time_blocks WHERE user_id=? AND day=? AND id<>?",
        (u["id"], day, int(block_id)),
    ).fetchall()
    for r in existing:
        s2 = _minutes_from_hhmm(r["time_in"])
        e2 = _minutes_from_hhmm(r["time_out"])
        if not (e <= s2 or s >= e2):
            db.close()
            add_flash("Zeitblock überschneidet sich mit vorhandenem Block.", "error")
            return redirect(f"/day/{day}/block/{block_id}/edit")

    db.execute(
        "UPDATE time_blocks SET time_in=?, time_out=?, break_minutes=?, comment=?, updated_at=datetime('now') WHERE id=? AND user_id=?",
        (time_in, time_out, int(break_minutes), comment, int(block_id), int(u["id"])),
    )
    db.commit()
    db.close()
    add_flash("Zeitblock aktualisiert.", "success")
    return redirect(f"/day/{day}")


@app.post("/day/<day>/block/delete")
@login_required
def day_block_delete(day: str):
    bootstrap()
    u = current_user()
    if _is_day_locked(u["id"], day):
        add_flash(LOCK_MSG, "error")
        return redirect(f"/day/{day}")
    block_id = int(request.form.get("block_id") or 0)
    db = connect()
    db.execute("DELETE FROM time_blocks WHERE id=? AND user_id=?", (block_id, u["id"]))
    db.commit()
    db.close()
    add_flash("Zeitblock gelöscht.", "success")
    return redirect(f"/day/{day}")


@app.post("/day/<day>/absence/add")
@login_required
def day_absence_add(day: str):
    bootstrap()
    u = current_user()
    if _is_day_locked(u["id"], day):
        add_flash(LOCK_MSG, "error")
        return redirect(f"/day/{day}")
    sd_err = _before_start_date(u["id"], day)
    if sd_err:
        add_flash(sd_err, "error")
        return redirect(f"/day/{day}")
    type_id = int(request.form.get("type_id") or 0)
    is_half_day = 1 if (request.form.get("is_half_day") == "1") else 0
    comment = _resolve_comment_from_form()

    db = connect()
    type_row = db.execute("SELECT name FROM absence_types WHERE id=?", (type_id,)).fetchone()
    type_name = type_row["name"] if type_row else ""
    if type_name == "Sonstige" and not comment:
        db.close()
        add_flash('Bei Typ "Sonstige" ist eine Bemerkung Pflicht.', "error")
        return redirect(f"/day/{day}")

    overlap = db.execute(
        """
        SELECT 1 FROM absences
        WHERE user_id=?
          AND NOT (date_to < ? OR date_from > ?)
        LIMIT 1
        """,
        (u["id"], day, day),
    ).fetchone()
    if overlap:
        db.close()
        add_flash("Es existiert bereits eine Abwesenheit an diesem Tag.", "error")
        return redirect(f"/day/{day}")

    db.execute(
        "INSERT INTO absences(user_id, type_id, date_from, date_to, is_half_day, comment, updated_at) VALUES(?,?,?,?,?,?,datetime('now'))",
        (u["id"], type_id, day, day, is_half_day, comment),
    )
    if type_name == "Sonstige" and comment:
        db.execute("INSERT OR IGNORE INTO absence_remarks(user_id,remark) VALUES(?,?)", (u["id"], comment))
    db.commit()
    db.close()
    add_flash("Abwesenheit gespeichert.", "success")
    return redirect(f"/day/{day}")




# -------------------------
# Einstellungen (Zeitschema (mit Gültig ab))
# -------------------------

def _contouring_settings_card(user_id: int) -> str:
    ci = _get_contouring_info(user_id)
    today = datetime.date.today()
    default_start = datetime.date(today.year, today.month, 1).isoformat()
    if ci["enabled"]:
        start_label = _fmt_date_de(ci["start_date"]) if ci["start_date"] else "–"
        return f"""
    <div class="card">
      <h3 style="margin-top:0;">Kontierung</h3>
      <div style="margin-bottom:10px;">
        <span style="color:var(--ok);font-weight:600;">&#10003; Kontierung aktiv</span>
        <span style="color:var(--mu);font-size:13px;margin-left:8px;">seit {start_label}</span>
      </div>
      <form method="post" action="/settings/contouring/toggle"
            onsubmit="return confirm('Kontierung wirklich deaktivieren? Bestehende Kontierungen bleiben erhalten.');">
        <button class="btn danger" type="submit">Kontierung deaktivieren</button>
      </form>
    </div>"""
    else:
        return f"""
    <div class="card">
      <h3 style="margin-top:0;">Kontierung</h3>
      <div style="margin-bottom:12px;color:var(--mu);">Kontierung ist deaktiviert.</div>
      <form method="post" action="/settings/contouring/toggle" id="contour-enable-form">
        <div style="margin-bottom:10px;">
          <label>Kontierung gilt ab:</label><br>
          {_date_input("contouring_start_date", default_start)}
          <div class="small" style="color:#777;margin-top:3px;">
            Standard: 1. des aktuellen Monats. Tage vor diesem Datum werden nicht zur Kontierung herangezogen.
          </div>
        </div>
        <button class="btn primary" type="submit">Aktivieren</button>
      </form>
    </div>"""


@app.get("/settings")
@login_required
def settings_view():
    bootstrap()
    u = current_user()
    sched = _get_user_schedule_current(u["id"])
    all_scheds = _get_user_schedules_all(u["id"])
    today_iso = datetime.date.today().isoformat()
    cur_sched = _get_user_schedule_for_day(u["id"], today_iso)
    cur_id = (cur_sched or {}).get("id")
    auto_breaks_enabled = _get_pref_auto_breaks(u["id"]) == 1

    # Urlaub (Inline in Einstellungen)
    vac_year = int(datetime.date.today().year)
    vc = _vacation_calc(u["id"], vac_year)
    vac_entitlement = vc["entitlement"]
    vac_carryover = vc["carryover"]
    vac_deadline = vc["deadline"]
    vac_used_total = vc["used_total"]
    vac_carryover_remaining = vc["carryover_remaining"]
    vac_entitlement_remaining = vc["entitlement_remaining"]
    vac_remaining_total = vc["remaining_total"]
    vac_carryover_forfeited = vc["carryover_forfeited"]
    vac_deadline_passed = vc["deadline_passed"]
    vac_carryover_exception = vc.get("carryover_exception", False)
    vac_effective_carryover = vc.get("effective_carryover", 0.0)

    # Build schedule list with validity dates
    sched_rows = ""
    for s in all_scheds:
        sid = s.get("id")
        valid_from = s.get("valid_from") or ""
        mode = (s.get("mode") or "weekly").lower()
        weekly_minutes = s.get("weekly_minutes")
        weekly_hours_txt = ""
        if weekly_minutes is not None:
            try:
                weekly_hours_txt = f"{(int(weekly_minutes)/60):g}"
            except Exception:
                weekly_hours_txt = ""
        mask = int(s.get("workdays_mask") or _default_workdays_mask())
        workdays_txt = _workdays_str(mask)

        badge = ""
        try:
            if sid and cur_id and int(sid) == int(cur_id):
                badge = "<span class='badge' style='background:#0a7;color:#fff;'>Aktuell</span>"
            elif valid_from and valid_from > today_iso:
                badge = "<span class='badge' style='background:#888;color:#fff;'>Zukünftig</span>"
            else:
                badge = "<span class='badge' style='background:#ddd;'>Historie</span>"
        except Exception:
            badge = ""

        mode_txt = "Woche" if mode == "weekly" else ("Tag" if mode == "daily" else mode)

        if mode == "daily":
            day_parts = []
            for day_key, label in [("mon_minutes","Mo"),("tue_minutes","Di"),("wed_minutes","Mi"),
                                    ("thu_minutes","Do"),("fri_minutes","Fr"),("sat_minutes","Sa"),("sun_minutes","So")]:
                v = int(s.get(day_key) or 0)
                if v:
                    day_parts.append(f"{label}:{_fmt_minutes(v)}")
            soll_txt = " ".join(day_parts) if day_parts else "–"
        else:
            soll_txt = f"{weekly_hours_txt} h/Woche" if weekly_hours_txt else "–"

        del_btn = ""
        if sid:
            del_btn = (f"<form method='post' action='/settings/schedule/{sid}/delete' style='display:inline;'"
                       f" onsubmit=\"return confirm('Zeitschema ab {_fmt_date_de(valid_from) if valid_from else valid_from} löschen?');\">"
                       f"<button class='btn danger' style='padding:3px 8px;font-size:12px;'>Löschen</button></form>")

        sched_rows += f"""<tr>
            <td style='white-space:nowrap;'><b>{_fmt_date_de(valid_from) if valid_from else "-"}</b></td>
            <td>{badge}</td>
            <td>{mode_txt}</td>
            <td class='small'>{soll_txt}</td>
            <td>{workdays_txt}</td>
            <td>{del_btn}</td>
        </tr>"""


    profile_dn = u.get("display_name") or ""
    profile_em = u.get("email") or ""

    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Einstellungen</h3>
        <a class="btn" href="/settings/password">Passwort ändern</a>
      </div>
    </div>

    <div class="card">
      <h3 style="margin-top:0;">Profil</h3>
      <form method="post" action="/settings/profile" style="display:flex;flex-direction:column;gap:10px;max-width:380px;">
        <div>
          <label>Anzeigename</label><br>
          <input name="display_name" value="{profile_dn}" placeholder="{u['username']}">
          <div class="small" style="color:#777;margin-top:3px;">Wird im Header und in der Admin-Übersicht angezeigt. Leer = Benutzername.</div>
        </div>
        <div>
          <label>E-Mail</label><br>
          <input type="email" name="email" value="{profile_em}" placeholder="max@example.com">
        </div>
        <div><button class="btn" type="submit">Speichern</button></div>
      </form>
      <div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--bd);">
        <div class="small" style="color:#777;">Arbeitsbeginn</div>
        <div style="font-size:14px;font-weight:600;">{_fmt_date_de(u.get("tracking_start_date")) or "–"}</div>
        <div class="small" style="color:#777;margin-top:2px;">Kein Eintrag vor diesem Datum möglich. Änderung nur durch Admin.</div>
      </div>
    </div>

    <div class="card">
      <h3 style="margin-top:0;">Urlaub – {vac_year}</h3>
      {"<div style='background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:13px;color:#92400e;'><b>Urlaubsübertrag: Ausnahme gilt</b> – " + f"{vac_effective_carryover:.1f} Tage übertragen (verfallen nicht am 31.03.)</div>" if vac_carryover_exception else ""}
      <p class="small">
        Urlaub wird nur an <b>Arbeitstagen</b> gezählt (gemäß Zeitschema + Wochenenden/Feiertage).
        {"Übertrag-Frist: " + vac_deadline + " <b style='color:#d97706;'>(Ausnahme gilt – kein Verfall)</b>." if vac_carryover_exception else ("<b style='color:var(--danger);'>Übertrag verfällt am " + vac_deadline + " (Urlaubsbeginn muss ≤ " + vac_deadline + " liegen).</b>" if not vac_deadline_passed and vac_carryover > 0 else ("Übertrag verfallen am " + vac_deadline + "." if vac_deadline_passed and vac_carryover_forfeited > 0 else "Übertrag-Frist: " + vac_deadline + "."))}
      </p>

      <form method="post" action="/settings/vacation/save" style="display:flex;gap:12px;flex-wrap:wrap;align-items:end;">
        <input type="hidden" name="year" value="{vac_year}">
        <div>
          <label>Urlaubsanspruch (Tage)</label><br>
          <input name="entitlement_days" type="number" step="0.5" min="0" value="{vac_entitlement}" required>
        </div>
        <div>
          <label>Übertrag Vorjahr (Tage)</label><br>
          <input name="carryover_days" type="number" step="0.5" min="0" value="{vac_carryover}" required>
        </div>
        <div>
          <button class="btn" type="submit">Speichern</button>
        </div>
      </form>

      <div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;">
        <div><div class="small">Genommen (gesamt)</div><div style="font-size:22px;"><b>{vac_used_total:.1f}</b></div></div>
        <div><div class="small">Rest gesamt</div><div style="font-size:22px;"><b>{vac_remaining_total:.1f}</b></div></div>
        <div style="opacity:.6;">|</div>
        <div><div class="small">{"Übertrag (Ausnahme)" if vac_carryover_exception else "Übertrag offen"}</div><div style="font-size:22px;{'color:#d97706;' if vac_carryover_exception else ''}"><b>{vac_carryover_remaining:.1f}</b></div></div>
        <div><div class="small">Anspruch {vac_year} offen</div><div style="font-size:22px;"><b>{vac_entitlement_remaining:.1f}</b></div></div>
        {"<div><div class='small' style='color:var(--danger);'>Übertrag verfallen</div><div style='font-size:22px;color:var(--danger);'><b>" + f"{vac_carryover_forfeited:.1f}" + "</b></div></div>" if vac_carryover_forfeited > 0 else ""}
      </div>
    </div>

    <div class="card">
      <h3 style="margin-top:0;">Zeitschema</h3>
      <p class="small">Regeln: An Wochenenden/Feiertagen wird standardmäßig nicht gearbeitet (kann bei Bedarf als Ausnahme zugelassen werden).</p>

      
      <div class="card" style="margin-bottom:14px;">
        <h3 style="margin:0 0 8px 0;">Vorhandene Zeitschemata</h3>
        <div class="small" style="color:#666;margin-bottom:8px;">Alle Schemas inkl. Gültigkeit (gültig ab).</div>
        <table class="table">
          <thead>
            <tr>
              <th>Gültig ab</th>
              <th>Status</th>
              <th>Modus</th>
              <th>Soll</th>
              <th>Arbeitstage</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sched_rows if sched_rows else "<tr><td colspan='6' style='color:#666;'>Noch kein Zeitschema gespeichert.</td></tr>"}
          </tbody>
        </table>
      </div>

      <h4 style="margin:14px 0 6px 0;">Neues Zeitschema anlegen</h4>
      {_sched_form_html(sched, "/settings/save", "/settings",
                        show_auto_breaks=True, auto_breaks_enabled=auto_breaks_enabled)}
    </div>

    {_contouring_settings_card(u["id"])}
    """
    return render_template_string(layout("Einstellungen", body, u, APP_VERSION))


@app.get("/settings/password")
@login_required
def settings_password():
    bootstrap()
    u = current_user()
    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Passwort ändern</h3>
        <a class="btn" href="/settings">← Zurück</a>
      </div>
      <form method="post" action="/settings/password" style="margin-top:12px;">
        <div style="margin-bottom:10px;">
          <label>Aktuelles Passwort</label><br>
          <input type="password" name="current_password" required autocomplete="current-password">
        </div>
        <div style="margin-bottom:10px;">
          <label>Neues Passwort</label><br>
          <input type="password" name="new_password" required minlength="6" autocomplete="new-password">
          <div class="small" style="color:#777;">Mindestens 6 Zeichen.</div>
        </div>
        <div style="margin-bottom:10px;">
          <label>Neues Passwort (Wiederholung)</label><br>
          <input type="password" name="new_password_confirm" required minlength="6" autocomplete="new-password">
        </div>
        <button class="btn" type="submit">Passwort speichern</button>
        <a class="btn" href="/settings">Abbrechen</a>
      </form>
    </div>
    """
    return render_template_string(layout("Passwort ändern", body, u, APP_VERSION))


@app.post("/settings/profile")
@login_required
def settings_profile_save():
    bootstrap()
    u = current_user()
    display_name = (request.form.get("display_name") or "").strip() or None
    email = (request.form.get("email") or "").strip() or None
    db = connect()
    db.execute(
        "UPDATE users SET display_name=?, email=?, updated_at=datetime('now') WHERE id=?",
        (display_name, email, u["id"]),
    )
    db.commit()
    db.close()
    add_flash("Profil gespeichert.", "success")
    return redirect("/settings")


@app.post("/settings/password")
@login_required
def settings_password_post():
    bootstrap()
    u = current_user()
    current_password = (request.form.get("current_password") or "").strip()
    new_password = (request.form.get("new_password") or "").strip()
    new_password_confirm = (request.form.get("new_password_confirm") or "").strip()

    if not current_password:
        add_flash("Bitte aktuelles Passwort angeben.", "error")
        return redirect("/settings/password")

    if not authenticate(u["username"], current_password):
        add_flash("Aktuelles Passwort ist falsch.", "error")
        return redirect("/settings/password")

    if len(new_password) < 6:
        add_flash("Neues Passwort muss mindestens 6 Zeichen haben.", "error")
        return redirect("/settings/password")

    if new_password != new_password_confirm:
        add_flash("Neues Passwort und Wiederholung stimmen nicht überein.", "error")
        return redirect("/settings/password")

    set_password(u["id"], new_password)
    add_flash("Passwort wurde geändert.", "success")
    return redirect("/settings")


@app.get("/settings/vacation")
@login_required
def settings_vacation():
    bootstrap()
    u = current_user()
    year = int(request.args.get("y") or datetime.date.today().year)

    vc = _vacation_calc(u["id"], year)
    entitlement = vc["entitlement"]
    carryover = vc["carryover"]
    deadline = vc["deadline"]
    deadline_passed = vc["deadline_passed"]
    used_total = vc["used_total"]
    carryover_remaining = vc["carryover_remaining"]
    entitlement_remaining = vc["entitlement_remaining"]
    remaining_total = vc["remaining_total"]
    carryover_forfeited = vc["carryover_forfeited"]
    effective_carryover = vc["effective_carryover"]
    carryover_exception = vc.get("carryover_exception", False)

    if carryover_exception:
        deadline_notice = f"Übertrag-Frist: {deadline}. <b style='color:#d97706;'>Ausnahme gilt – Übertrag verfällt nicht am 31.03.</b>"
    elif not deadline_passed and carryover > 0:
        deadline_notice = f"<b style='color:var(--danger);'>Übertrag verfällt am {deadline} – Urlaubsbeginn muss ≤ {deadline} liegen.</b>"
    elif deadline_passed and carryover_forfeited > 0:
        deadline_notice = f"Übertrag-Frist war {deadline}. <b style='color:var(--danger);'>{carryover_forfeited:.1f} Tage Übertrag verfallen.</b>"
    else:
        deadline_notice = f"Übertrag-Frist: {deadline}."

    exception_banner = ""
    if carryover_exception:
        exception_banner = (
            f"<div style='background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;"
            f"padding:8px 12px;margin-bottom:12px;font-size:13px;color:#92400e;'>"
            f"<b>Urlaubsübertrag: Ausnahme gilt</b> – {effective_carryover:.1f} Tage "
            f"übertragen (verfallen nicht am 31.03.)</div>"
        )

    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Urlaub – {year}</h3>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <a class="btn" href="/settings">← Zurück</a>
          <a class="btn" href="/settings/vacation?y={year-1}">◀︎ {year-1}</a>
          <a class="btn" href="/settings/vacation?y={datetime.date.today().year}">Heute</a>
          <a class="btn" href="/settings/vacation?y={year+1}">{year+1} ▶︎</a>
        </div>
      </div>

      {exception_banner}
      <p class="small">{deadline_notice}</p>

      <form method="post" action="/settings/vacation/save" style="display:flex;gap:12px;flex-wrap:wrap;align-items:end;">
        <input type="hidden" name="year" value="{year}">
        <div>
          <label>Urlaubsanspruch (Tage)</label><br>
          <input name="entitlement_days" type="number" step="0.5" min="0" value="{entitlement}" required>
        </div>
        <div>
          <label>Übertrag Vorjahr (Tage)</label><br>
          <input name="carryover_days" type="number" step="0.5" min="0" value="{carryover}" required>
        </div>
        <div>
          <button class="btn" type="submit">Speichern</button>
        </div>
      </form>

      <hr>

      <div style="display:flex;gap:18px;flex-wrap:wrap;">
        <div><div class="small">Genommen (gesamt)</div><div style="font-size:22px;"><b>{used_total:.1f}</b></div></div>
        <div><div class="small">Rest gesamt</div><div style="font-size:22px;"><b>{remaining_total:.1f}</b></div></div>
        <div style="opacity:.6;">|</div>
        <div><div class="small">{"Übertrag (Ausnahme)" if carryover_exception else "Übertrag offen"}</div><div style="font-size:22px;{'color:#d97706;' if carryover_exception else ''}"><b>{carryover_remaining:.1f}</b></div></div>
        <div><div class="small">Anspruch {year} offen</div><div style="font-size:22px;"><b>{entitlement_remaining:.1f}</b></div></div>
        {"<div><div class='small' style='color:var(--danger);'>Übertrag verfallen</div><div style='font-size:22px;color:var(--danger);'><b>" + f"{carryover_forfeited:.1f}" + "</b></div></div>" if carryover_forfeited > 0 else ""}
      </div>

      <p class="small" style="margin-top:10px;">
        Urlaub wird nur an <b>Arbeitstagen</b> gezählt (gemäß Zeitschema + Wochenenden/Feiertage).
        {"Effektiver Übertrag: <b>" + f"{effective_carryover:.1f}" + " Tage</b> (Ausnahme, konfiguriert: " + f"{carryover:.1f}" + ")." if carryover_exception else "Effektiver Übertrag: <b>" + f"{effective_carryover:.1f}" + "</b> Tage (konfiguriert: " + f"{carryover:.1f}" + ", davon bis " + deadline + " angetreten: " + f"{vc['carryover_started']:.1f}" + ")."}
      </p>
    </div>
    """
    return render_template_string(layout("Urlaub", body, u, APP_VERSION))


@app.post("/settings/vacation/save")
@login_required
def settings_vacation_save():
    bootstrap()
    u = current_user()
    year = int(request.form.get("year") or datetime.date.today().year)
    try:
        entitlement = float(request.form.get("entitlement_days") or 0)
        carryover = float(request.form.get("carryover_days") or 0)
        if entitlement < 0 or carryover < 0:
            raise ValueError()
    except Exception:
        add_flash("Bitte gültige Werte (Tage) eingeben.", "error")
        return redirect("/settings#urlaub")

    _set_vacation_year(u["id"], year, entitlement, carryover)
    add_flash("Urlaubseinstellungen gespeichert.", "success")
    return redirect("/settings#urlaub")




def _parse_hhmm_to_minutes(val: str) -> int:
    val = (val or "").strip()
    if not val:
        return 0
    if not re.match(r"^\d{2}:\d{2}$", val):
        raise ValueError("Format HH:MM erwartet")
    h, m = [int(x) for x in val.split(":")]
    return h*60 + m


def _csv_response(filename: str, headers: list, data: list, delimiter: str = ";"):
    """Build CSV with given delimiter (default ;) and return Flask Response for download."""
    import csv
    from io import StringIO
    from flask import Response
    buf = StringIO()
    w = csv.writer(buf, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
    w.writerow(headers)
    w.writerows(data)
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/settings/save")
@login_required
def settings_save():
    bootstrap()
    u = current_user()

    _set_pref_auto_breaks(u["id"], 1 if (request.form.get("auto_breaks") or "") == "1" else 0)

    sched = _parse_sched_form(request.form)
    if not sched["valid_from"]:
        add_flash("Bitte ein gültiges Datum (TT.MM.JJJJ) angeben.", "error")
        return redirect("/settings")

    # Overlap check: warn if a newer schema exists that would override this one
    if request.form.get("confirm_overlap") != "1":
        db = connect()
        overlap_rows = db.execute(
            "SELECT id, valid_from FROM user_schedules WHERE user_id=? AND valid_from > ? ORDER BY valid_from",
            (u["id"], sched["valid_from"]),
        ).fetchall()
        db.close()
        if overlap_rows:
            dates_str = ", ".join(_fmt_date_de(r["valid_from"]) for r in overlap_rows)
            # Render confirmation page with all form data as hidden fields
            hidden = "\n".join(
                f'<input type="hidden" name="{_html.escape(k)}" value="{_html.escape(v)}">'
                for k, v in request.form.items()
                if k != "confirm_overlap"
            )
            warn_body = f"""
            {flash_html()}
            <div class="card" style="border-left:4px solid #f59e0b;">
              <h3 style="margin-top:0;">⚠ Überschneidung mit vorhandenem Zeitschema</h3>
              <p>Es existiert/existieren bereits neuere Zeitschemata (<b>{dates_str}</b>),
                 die für Daten ab diesem Datum weiterhin gelten und das neue Schema überschreiben.</p>
              <p>Das neue Schema ab <b>{_fmt_date_de(sched["valid_from"])}</b> wird ab dem nächsten neueren Schema
                 (<b>{dates_str}</b>) durch dieses ersetzt.</p>
              <p class="small">Zum vollständigen Ersetzen: zuerst das neuere Schema löschen (Einstellungen → Zeitschemata → Löschen),
                 dann erneut speichern.</p>
              <form method="post" action="/settings/save">
                {hidden}
                <input type="hidden" name="confirm_overlap" value="1">
                <button class="btn primary" type="submit">Trotzdem anlegen</button>
                <a class="btn" href="/settings">Abbrechen</a>
              </form>
            </div>
            """
            return render_template_string(layout("Zeitschema – Überschneidung", warn_body, u, APP_VERSION))

    _sched_save_to_db(u["id"], sched)
    add_flash("Zeitschema gespeichert.", "success")
    return redirect("/settings")


@app.post("/settings/schedule/<int:schedule_id>/delete")
@login_required
def settings_schedule_delete(schedule_id: int):
    bootstrap()
    u = current_user()
    db = connect()
    row = db.execute(
        "SELECT id, valid_from FROM user_schedules WHERE id=? AND user_id=?",
        (schedule_id, u["id"]),
    ).fetchone()
    if not row:
        db.close()
        add_flash("Zeitschema nicht gefunden.", "error")
        return redirect("/settings")
    count = db.execute("SELECT COUNT(*) FROM user_schedules WHERE user_id=?", (u["id"],)).fetchone()[0]
    if count <= 1:
        db.close()
        add_flash("Das letzte Zeitschema kann nicht gelöscht werden.", "error")
        return redirect("/settings")
    db.execute("DELETE FROM user_schedules WHERE id=?", (schedule_id,))
    db.commit()
    db.close()
    add_flash(f"Zeitschema ab {_fmt_date_de(row['valid_from'])} gelöscht.", "success")
    return redirect("/settings")


@app.get("/business_trips")
@login_required
def business_trips_list():
    bootstrap()
    u = current_user()
    today = datetime.date.today()
    year = int(request.args.get("y") or today.year)
    show_form = request.args.get("new") == "1"
    user_start = _get_tracking_start(u["id"])
    _trip_from = f"{year}-01-01"
    if user_start:
        _trip_from = max(_trip_from, user_start)

    db = connect()
    trips = db.execute(
        "SELECT * FROM business_trips WHERE user_id=? AND start_date BETWEEN ? AND ? ORDER BY start_date DESC",
        (u["id"], _trip_from, f"{year}-12-31"),
    ).fetchall()
    db.close()

    prev_year = year - 1
    next_year = year + 1
    _prev_year_blocked = bool(user_start and f"{prev_year}-12-31" < user_start)

    def fmt_time(v):
        return v if v else "–"

    def fmt_date_range(t):
        s = str(t["start_date"])[:10]
        e = str(t["end_date"] or s)[:10]
        sy = _fmt_date_de(s, omit_year=(int(s[:4]) == year))
        if s == e:
            return f"<a href='/day/{s}'>{sy}</a>"
        ey = _fmt_date_de(e, omit_year=(int(e[:4]) == year))
        return f"<a href='/day/{s}'>{sy}</a> – <a href='/day/{e}'>{ey}</a>"

    rows_html = ""
    if trips:
        for t in trips:
            rows_html += (
                f"<tr>"
                f"<td>{fmt_date_range(t)}</td>"
                f"<td><b>{t['destination']}</b></td>"
                f"<td>{fmt_time(t['departure_time'])}</td>"
                f"<td>{fmt_time(t['departure_end_time'])}</td>"
                f"<td>{fmt_time(t['return_time'])}</td>"
                f"<td>{fmt_time(t['return_end_time'])}</td>"
                f"<td class='small'>{t['notes'] or ''}</td>"
                f"<td><a href='/day/{t['start_date']}'>Bearb.</a> "
                f"<form method='post' action='/business_trips/delete' style='display:inline;'"
                f" onsubmit=\"return confirm('Dienstreise löschen?');\">"
                f"<input type='hidden' name='trip_id' value='{t['id']}'>"
                f"<input type='hidden' name='y' value='{year}'>"
                f"<button class='btn danger' type='submit' style='padding:4px 8px;font-size:13px;'>Löschen</button></form></td>"
                f"</tr>"
            )
    else:
        rows_html = f"<tr><td colspan='8' class='small' style='color:var(--mu);'>Keine Dienstreisen in {year}.</td></tr>"

    new_form_html = ""
    if show_form:
        new_form_html = f"""
        <div class="card" style="margin-top:12px;">
          <h3 style="margin-top:0;">+ Neue Dienstreise</h3>
          {FORM_ASSETS_JS}
          <form method="post" action="/business_trips/add">
            <input type="hidden" name="y" value="{year}">
            <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;align-items:flex-end;">
              <div>
                <label>Ort *</label><br>
                <input name="destination" required placeholder="Reiseziel" style="max-width:280px;">
              </div>
              <div>
                <label>Startdatum *</label><br>
                {_date_input("start_date", today.isoformat(), required=True)}
              </div>
              <div>
                <label style="font-weight:400;"><input type="checkbox" onchange="toggleMultiday(this)"> Mehrtägig</label>
              </div>
            </div>
            <div class="multiday-fields" style="display:none;margin-bottom:8px;">
              <label>Enddatum</label><br>
              {_date_input("end_date")}
            </div>
            <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;">
              <div><label>Abreise</label><br>{_time_input("departure_time")}</div>
              <div><label>Ankunft Ziel</label><br>{_time_input("departure_end_time")}</div>
              <div><label>Rückreise Start</label><br>{_time_input("return_time")}</div>
              <div><label>Ankunft Zuhause</label><br>{_time_input("return_end_time")}</div>
            </div>
            <div style="margin-bottom:8px;">
              <label>Notizen</label><br>
              <textarea name="notes" rows="2" placeholder="optional" style="max-width:500px;"></textarea>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary" type="submit">Speichern</button>
              <a class="btn" href="/business_trips?y={year}">Abbrechen</a>
            </div>
          </form>
        </div>"""

    body = f"""
    {_timepicker_datalist('time_suggestions')}
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">✈ Dienstreisen – {year}</h3>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          {"<span class='btn' style='opacity:.35;cursor:not-allowed;'>◀︎ " + str(prev_year) + "</span>" if _prev_year_blocked else f"<a class='btn' href='/business_trips?y={prev_year}'>◀︎ {prev_year}</a>"}
          <a class="btn" href="/business_trips?y={today.year}">Heute</a>
          <a class="btn" href="/business_trips?y={next_year}">{next_year} ▶︎</a>
          <a class="btn primary" href="/business_trips?y={year}&new=1">+ Neue Dienstreise</a>
        </div>
      </div>
      <table style="margin-top:10px;">
        <thead>
          <tr>
            <th>Datum</th><th>Ort</th>
            <th>Abreise</th><th>Ankunft Ziel</th>
            <th>Rückreise</th><th>Ankunft Hause</th>
            <th>Notizen</th><th>Aktionen</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
    {new_form_html}
    """
    return render_template_string(layout("Dienstreisen", body, u, APP_VERSION))


@app.post("/business_trips/add")
@login_required
def business_trips_add():
    bootstrap()
    u = current_user()
    year = (request.form.get("y") or str(datetime.date.today().year)).strip()
    destination = (request.form.get("destination") or "").strip()
    if not destination:
        add_flash("Ort ist Pflichtfeld.", "error")
        return redirect(f"/business_trips?y={year}&new=1")
    start_date = _parse_date_input(request.form.get("start_date") or "")
    if not start_date:
        add_flash("Ungültiges Startdatum.", "error")
        return redirect(f"/business_trips?y={year}&new=1")
    end_date_raw = (request.form.get("end_date") or "").strip()
    end_date = _parse_date_input(end_date_raw) if end_date_raw else start_date
    if end_date and end_date < start_date:
        end_date = start_date
    if _is_range_locked(u["id"], start_date, end_date or start_date):
        add_flash(LOCK_MSG, "error")
        return redirect(f"/business_trips?y={year}&new=1")
    sd_err = _before_start_date(u["id"], start_date)
    if sd_err:
        add_flash(sd_err, "error")
        return redirect(f"/business_trips?y={year}&new=1")
    departure_time     = _round_to_15((request.form.get("departure_time") or "").strip()) or None
    departure_end_time = _round_to_15((request.form.get("departure_end_time") or "").strip()) or None
    return_time        = _round_to_15((request.form.get("return_time") or "").strip()) or None
    return_end_time    = _round_to_15((request.form.get("return_end_time") or "").strip()) or None
    notes              = (request.form.get("notes") or "").strip() or None
    db = connect()
    db.execute(
        """INSERT INTO business_trips
               (user_id, start_date, end_date, destination, departure_time, departure_end_time,
                return_time, return_end_time, notes, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))
           ON CONFLICT(user_id, start_date) DO UPDATE SET
             end_date=excluded.end_date,
             destination=excluded.destination,
             departure_time=excluded.departure_time,
             departure_end_time=excluded.departure_end_time,
             return_time=excluded.return_time,
             return_end_time=excluded.return_end_time,
             notes=excluded.notes,
             updated_at=datetime('now')""",
        (u["id"], start_date, end_date, destination, departure_time, departure_end_time,
         return_time, return_end_time, notes),
    )
    db.commit()
    db.close()
    add_flash("Dienstreise gespeichert.", "success")
    return redirect(f"/business_trips?y={year}")


@app.post("/business_trips/delete")
@login_required
def business_trips_delete():
    bootstrap()
    u = current_user()
    trip_id = (request.form.get("trip_id") or "").strip()
    year = (request.form.get("y") or str(datetime.date.today().year)).strip()
    if trip_id:
        db = connect()
        trip = db.execute(
            "SELECT start_date, end_date FROM business_trips WHERE id=? AND user_id=?",
            (int(trip_id), u["id"]),
        ).fetchone()
        if trip and _is_range_locked(u["id"], trip["start_date"], trip["end_date"] or trip["start_date"]):
            db.close()
            add_flash(LOCK_MSG, "error")
            return redirect(f"/business_trips?y={year}")
        db.execute("DELETE FROM business_trips WHERE id=? AND user_id=?", (int(trip_id), u["id"]))
        db.commit()
        db.close()
        add_flash("Dienstreise gelöscht.", "success")
    return redirect(f"/business_trips?y={year}")


# ─── Periodenabschluss-Verwaltung ────────────────────────────────────────────

@app.get("/periods")
@login_required
def periods_view():
    bootstrap()
    u = current_user()
    today = datetime.date.today()

    try:
        sel_year = int(request.args.get("y") or today.year)
    except (ValueError, TypeError):
        sel_year = today.year

    locks = _get_period_lock_status(u["id"], sel_year)
    year_locked = "year" in locks
    user_start = _get_tracking_start(u["id"])

    # username cache for "locked_by"
    db = connect()
    try:
        users_map = {r["id"]: r["username"] for r in db.execute("SELECT id, username FROM users").fetchall()}
    finally:
        db.close()

    def _lock_who(lock_row: dict) -> str:
        by = lock_row.get("locked_by")
        name = users_map.get(by, f"#{by}") if by else "–"
        ts = (lock_row.get("locked_at") or "")[:16]
        return f"{ts} · {name}"

    trs = ""
    for m in range(1, 13):
        key = f"{sel_year}-{m:02d}"
        month_last_day = f"{sel_year}-{m:02d}-{calendar.monthrange(sel_year, m)[1]:02d}"
        if user_start and month_last_day < user_start:
            trs += (
                f"<tr><td style='color:var(--mu);'>{MONTH_NAMES_DE[m]} {sel_year}</td>"
                f"<td><span class='small' style='color:var(--mu);'>Vor Arbeitsbeginn</span></td>"
                f"<td></td></tr>"
            )
            continue

        month_locked = year_locked or (key in locks)
        lock_row = locks.get(key) or locks.get("year") if month_locked else None

        # determine if month is past (lockable)
        month_is_past = (sel_year < today.year) or (sel_year == today.year and m < today.month)

        if month_locked:
            status_html = f"<span style='color:var(--ok);'>🔒 Abgeschlossen</span>"
            if lock_row:
                status_html += f" <span class='small'>({_lock_who(lock_row)})</span>"
            action = ""
            if u.get("is_admin"):
                # Only allow unlocking individual month locks (not inherited year locks)
                if key in locks:
                    action = (
                        f"<form method='post' action='/periods/unlock' style='display:inline;'>"
                        f"<input type='hidden' name='year' value='{sel_year}'>"
                        f"<input type='hidden' name='month' value='{m}'>"
                        f"<button class='btn danger' style='padding:4px 10px;font-size:13px;'>Entsperren</button></form>"
                    )
                else:
                    action = "<span class='small' style='color:var(--mu);'>via Jahresabschluss</span>"
        elif month_is_past:
            status_html = "<span style='color:var(--mu);'>Offen</span>"
            action = (
                f"<form method='post' action='/periods/lock' style='display:inline;'>"
                f"<input type='hidden' name='year' value='{sel_year}'>"
                f"<input type='hidden' name='month' value='{m}'>"
                f"<button class='btn' style='padding:4px 10px;font-size:13px;'>Abschließen</button></form>"
            )
        else:
            status_html = "<span class='small' style='color:var(--mu);'>–</span>"
            action = ""

        trs += (
            f"<tr><td><a href='/balance?y={sel_year}&m={m}'>{MONTH_NAMES_DE[m]} {sel_year}</a></td>"
            f"<td>{status_html}</td><td>{action}</td></tr>"
        )

    # Year-level lock row
    year_is_past = sel_year < today.year
    year_before_start = bool(user_start and f"{sel_year}-12-31" < user_start)
    if year_before_start:
        yr_status = "<span class='small' style='color:var(--mu);'>Vor Arbeitsbeginn</span>"
        yr_action = ""
    elif year_locked:
        yr_status = f"<span style='color:var(--ok);'>🔒 Jahr abgeschlossen</span>"
        lr = locks.get("year")
        if lr:
            yr_status += f" <span class='small'>({_lock_who(lr)})</span>"
        yr_action = ""
        if u.get("is_admin") and "year" in locks:
            yr_action = (
                f"<form method='post' action='/periods/unlock' style='display:inline;'>"
                f"<input type='hidden' name='year' value='{sel_year}'>"
                f"<button class='btn danger' style='padding:4px 10px;font-size:13px;'>Jahr entsperren</button></form>"
            )
    elif year_is_past:
        yr_status = "<span style='color:var(--mu);'>Offen</span>"
        yr_action = (
            f"<form method='post' action='/periods/lock' style='display:inline;'>"
            f"<input type='hidden' name='year' value='{sel_year}'>"
            f"<button class='btn' style='padding:4px 10px;font-size:13px;'>Jahr abschließen</button></form>"
        )
    else:
        yr_status = "<span class='small' style='color:var(--mu);'>Laufendes Jahr</span>"
        yr_action = ""

    available_years = list(range(max(today.year - 5, 2020), today.year + 1))
    if user_start:
        _sy = int(user_start[:4])
        if _sy not in available_years:
            available_years = sorted(set(available_years) | {_sy})
    year_opts = "".join(
        f'<option value="{y}" {"selected" if y == sel_year else ""}>{y}</option>'
        for y in reversed(available_years)
    )

    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Abschlüsse</h3>
        <form method="get" style="display:flex;gap:8px;align-items:end;">
          <div><label>Jahr</label><br><select name="y">{year_opts}</select></div>
          <button class="btn" type="submit">Anzeigen</button>
        </form>
      </div>
      <p class="small" style="margin-top:8px;">Abgeschlossene Zeiträume können nicht mehr bearbeitet werden. Entsperren nur durch Admins möglich.</p>
      <table style="margin-top:12px;">
        <thead><tr><th>Monat</th><th>Status</th><th></th></tr></thead>
        <tbody>{trs}</tbody>
      </table>
      <hr>
      <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;">
        <b>Jahr {sel_year}:</b> {yr_status} {yr_action}
      </div>
    </div>
    """
    return render_template_string(layout("Abschlüsse", body, u, APP_VERSION))


@app.post("/periods/lock")
@login_required
def periods_lock():
    bootstrap()
    u = current_user()
    today = datetime.date.today()
    try:
        year = int(request.form.get("year") or 0)
        month_raw = request.form.get("month") or ""
        month = int(month_raw) if month_raw.strip() else None
    except (ValueError, TypeError):
        add_flash("Ungültige Eingabe.", "error")
        return redirect("/periods")

    # Guard: cannot lock current or future month
    if month is not None:
        lockable = (year < today.year) or (year == today.year and month < today.month)
        if not lockable:
            add_flash("Nur vergangene Monate können abgeschlossen werden.", "error")
            return redirect(f"/periods?y={year}")
    else:
        if year >= today.year:
            add_flash("Nur vergangene Jahre können als ganzes abgeschlossen werden.", "error")
            return redirect(f"/periods?y={year}")

    user_start = _get_tracking_start(u["id"])
    if user_start and month:
        period_last_day = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        if period_last_day < user_start:
            add_flash(f"Abschluss nicht möglich – Monat liegt vor Arbeitsbeginn ({_fmt_date_de(user_start)}).", "error")
            return redirect(f"/periods?y={year}")
    _lock_period(u["id"], year, month, locked_by=u["id"])
    label = f"{MONTH_NAMES_DE[month]} {year}" if month else f"Jahr {year}"
    add_flash(f"{label} abgeschlossen.", "success")
    return redirect(f"/periods?y={year}")


@app.post("/periods/unlock")
@login_required
def periods_unlock():
    bootstrap()
    u = current_user()
    if not u.get("is_admin"):
        abort(403)
    try:
        year = int(request.form.get("year") or 0)
        month_raw = request.form.get("month") or ""
        month = int(month_raw) if month_raw.strip() else None
    except (ValueError, TypeError):
        add_flash("Ungültige Eingabe.", "error")
        return redirect("/periods")

    _unlock_period(u["id"], year, month)
    label = f"{MONTH_NAMES_DE[month]} {year}" if month else f"Jahr {year}"
    add_flash(f"{label} entsperrt.", "success")
    return redirect(f"/periods?y={year}")


@app.get("/export")
@login_required
def export_home():
    bootstrap()
    u = current_user()
    today = datetime.date.today()
    year = today.year
    month = today.month
    default_from = f"{year}-01-01"
    default_to   = f"{year}-12-31"
    default_from_de = f"01.01.{year}"
    default_to_de   = f"31.12.{year}"
    admin_btn = f'<button class="btn" type="button" onclick="dlExport(\'/export/users.csv\',false)">Benutzer (Admin)</button>' if u.get("is_admin") else ""

    body = f"""
    {flash_html()}
    {FORM_ASSETS_JS}
    <div class="card">
      <h3 style="margin-top:0;">Zeitraum</h3>
      <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:end;margin-bottom:12px;">
        <div>
          <label>Von</label><br>
          <div class="dt-wrap">
            <input type="text" id="exp-from-txt" class="dt-text" placeholder="TT.MM.JJJJ"
                   value="{default_from_de}" maxlength="10" oninput="dt_text(this)">
            <input type="date" id="exp-from-iso" class="dt-pick" value="{default_from}"
                   onchange="dt_pick(this)">
          </div>
        </div>
        <div>
          <label>Bis</label><br>
          <div class="dt-wrap">
            <input type="text" id="exp-to-txt" class="dt-text" placeholder="TT.MM.JJJJ"
                   value="{default_to_de}" maxlength="10" oninput="dt_text(this)">
            <input type="date" id="exp-to-iso" class="dt-pick" value="{default_to}"
                   onchange="dt_pick(this)">
          </div>
        </div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px;">
        <button class="btn" type="button" onclick="setExpRange('month')">Akt. Monat</button>
        <button class="btn" type="button" onclick="setExpRange('lastmonth')">Letzter Monat</button>
        <button class="btn" type="button" onclick="setExpRange('year')">Akt. Jahr</button>
        <button class="btn" type="button" onclick="setExpRange('lastyear')">Letztes Jahr</button>
      </div>
    </div>

    <div class="card">
      <h3 style="margin-top:0;">Download (CSV)</h3>
      <p class="small">Trennzeichen <b>;</b> – Excel-freundlich. Dateiname enthält den gewählten Zeitraum.</p>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <button class="btn" type="button" onclick="dlExport('/export/time_blocks.csv',true)">Zeitblöcke</button>
        <button class="btn" type="button" onclick="dlExport('/export/absences.csv',true)">Abwesenheiten</button>
        <button class="btn" type="button" onclick="dlExport('/export/trips.csv',true)">Dienstreisen</button>
        <button class="btn" type="button" onclick="dlExport('/export/balance.csv',true)">Gleitzeitkonto</button>
        <button class="btn" type="button" onclick="dlExport('/export/calendar_days.csv',false)">Feiertage</button>
        {admin_btn}
      </div>
    </div>

    <script>
    function pad2(n){{return n<10?'0'+n:''+n;}}
    function lastDay(y,m){{return new Date(y,m,0).getDate();}}
    function isoToDE(s){{var p=s.split('-');return p[2]+'.'+p[1]+'.'+p[0];}}
    function setExpRange(preset){{
      var now=new Date(),y=now.getFullYear(),m=now.getMonth()+1,fy,fm,ty,tm;
      if(preset==='month'){{fy=y;fm=m;ty=y;tm=m;}}
      else if(preset==='lastmonth'){{var d=new Date(y,m-2,1);fy=d.getFullYear();fm=d.getMonth()+1;ty=fy;tm=fm;}}
      else if(preset==='year'){{fy=y;fm=1;ty=y;tm=12;}}
      else{{fy=y-1;fm=1;ty=y-1;tm=12;}}
      var from=fy+'-'+pad2(fm)+'-01';
      var to=ty+'-'+pad2(tm)+'-'+pad2(lastDay(ty,tm));
      document.getElementById('exp-from-txt').value=isoToDE(from);
      document.getElementById('exp-to-txt').value=isoToDE(to);
      document.getElementById('exp-from-iso').value=from;
      document.getElementById('exp-to-iso').value=to;
    }}
    function dlExport(base,withRange){{
      if(!withRange){{window.location=base;return;}}
      var from=document.getElementById('exp-from-iso').value;
      var to=document.getElementById('exp-to-iso').value;
      if(!from||!to){{alert('Bitte Von- und Bis-Datum auswählen.');return;}}
      window.location=base+'?from='+from+'&to='+to;
    }}
    </script>
    """
    return render_template_string(layout("Export", body, u, APP_VERSION))


def _export_date_range(user_id: int = 0):
    """Return (date_from_iso, date_to_iso) clamped to user's tracking_start_date."""
    today = datetime.date.today()
    df = request.args.get("from") or f"{today.year}-01-01"
    dt = request.args.get("to")   or f"{today.year}-12-31"
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', df):
        df = f"{today.year}-01-01"
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', dt):
        dt = f"{today.year}-12-31"
    if user_id:
        start = _get_tracking_start(user_id)
        if start:
            df = max(df, start)
    return df, dt


def _export_filename(prefix: str, date_from: str, date_to: str) -> str:
    return f"{prefix}_{date_from}_{date_to}.csv"


@app.get("/export/absences.csv")
@login_required
def export_absences_csv():
    bootstrap()
    u = current_user()
    date_from, date_to = _export_date_range(u["id"])
    db = connect()
    rows = db.execute(
        """
        SELECT a.id, t.name AS type, a.date_from, a.date_to, a.is_half_day, a.comment, a.created_at, a.updated_at
        FROM absences a
        JOIN absence_types t ON t.id = a.type_id
        WHERE a.user_id = ? AND NOT (a.date_to < ? OR a.date_from > ?)
        ORDER BY a.date_from, a.id
        """,
        (u["id"], date_from, date_to),
    ).fetchall()
    db.close()

    data = [[r["id"], r["type"], r["date_from"], r["date_to"], r["is_half_day"], r["comment"] or "", r["created_at"] or "", r["updated_at"] or ""] for r in rows]
    return _csv_response(
        _export_filename("abwesenheiten", date_from, date_to),
        ["id", "type", "date_from", "date_to", "is_half_day", "comment", "created_at", "updated_at"],
        data,
    )




@app.get("/export/time_blocks.csv")
@login_required
def export_time_blocks_csv():
    bootstrap()
    u = current_user()
    date_from, date_to = _export_date_range(u["id"])
    db = connect()
    rows = db.execute(
        """
        SELECT day, time_in, time_out, break_minutes, comment, created_at, updated_at
        FROM time_blocks
        WHERE user_id = ? AND day BETWEEN ? AND ?
        ORDER BY day, time_in
        """,
        (u["id"], date_from, date_to),
    ).fetchall()
    db.close()

    data = []
    for r in rows:
        mins = _minutes_from_hhmm(r["time_out"]) - _minutes_from_hhmm(r["time_in"]) - int(r["break_minutes"] or 0)
        data.append([
            r["day"],
            r["time_in"],
            r["time_out"],
            int(r["break_minutes"] or 0),
            _fmt_minutes(mins),
            r["comment"] or "",
            r["created_at"] or "",
            r["updated_at"] or "",
        ])

    return _csv_response(
        _export_filename("zeitbloecke", date_from, date_to),
        ["day", "time_in", "time_out", "break_minutes", "net_hhmm", "comment", "created_at", "updated_at"],
        data,
    )


@app.get("/export/month_summary.csv")
@login_required
def export_month_summary_csv():
    bootstrap()
    u = current_user()
    today = datetime.date.today()
    year = int(request.args.get("y") or today.year)
    month = int(request.args.get("m") or today.month)
    first_iso, last_iso = _month_range(year, month)

    db = connect()
    rows_tb = db.execute(
        """
        SELECT day, time_in, time_out, break_minutes
        FROM time_blocks
        WHERE user_id=? AND day BETWEEN ? AND ?
        """,
        (u["id"], first_iso, last_iso),
    ).fetchall()

    abs_rows = db.execute(
        """
        SELECT a.date_from, a.date_to, a.is_half_day, t.name AS type_name
        FROM absences a
        JOIN absence_types t ON t.id=a.type_id
        WHERE a.user_id=?
          AND NOT (a.date_to < ? OR a.date_from > ?)
        """,
        (u["id"], first_iso, last_iso),
    ).fetchall()
    db.close()

    totals = {}
    for b in rows_tb:
        day = b["day"]
        mins = _minutes_from_hhmm(b["time_out"]) - _minutes_from_hhmm(b["time_in"]) - int(b["break_minutes"] or 0)
        totals[day] = totals.get(day, 0) + mins

    abs_map = {}
    for a in abs_rows:
        d0 = datetime.date.fromisoformat(a["date_from"])
        d1 = datetime.date.fromisoformat(a["date_to"])
        cur = d0
        while cur <= d1:
            iso = cur.isoformat()
            label = a["type_name"]
            if a["is_half_day"] and a["date_from"] == a["date_to"]:
                label += " (1/2)"
            abs_map.setdefault(iso, []).append(label)
            cur += datetime.timedelta(days=1)

    last_day = calendar.monthrange(year, month)[1]
    data = []
    for d in range(1, last_day + 1):
        iso = datetime.date(year, month, d).isoformat()
        data.append([iso, _fmt_minutes(totals.get(iso, 0)), "; ".join(abs_map.get(iso, []))])

    return _csv_response(
        f"month_summary_{u['username']}_{year}-{month:02d}.csv",
        ["day", "net_hhmm", "absence"],
        data,
    )


@app.get("/export/presence.csv")
@login_required
def export_presence_csv():
    bootstrap()
    u = current_user()
    db = connect()
    try:
        rows = db.execute(
            "SELECT p.day, p.comment, p.created_at, p.updated_at FROM daily_presence p WHERE p.user_id=? ORDER BY p.day",
            (u["id"],),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    db.close()
    data = [[r["day"], r["comment"] or "", r["created_at"] or "", r["updated_at"] or ""] for r in rows]
    return _csv_response(
        f"presence_{u['username']}.csv",
        ["day", "comment", "created_at", "updated_at"],
        data,
    )



@app.get("/export/times.csv")
@login_required
def export_times_csv():
    bootstrap()
    u = current_user()
    date_from, date_to = _export_date_range(u["id"])
    db = connect()
    rows = db.execute(
        """
        SELECT day, time_in, time_out, break_minutes, comment, created_at, updated_at
        FROM time_entries
        WHERE user_id = ? AND day BETWEEN ? AND ?
        ORDER BY day
        """,
        (u["id"], date_from, date_to),
    ).fetchall()
    db.close()
    data = [[r["day"], r["time_in"], r["time_out"], r["break_minutes"], r["comment"] or "", r["created_at"] or "", r["updated_at"] or ""] for r in rows]
    return _csv_response(
        _export_filename("zeiten", date_from, date_to),
        ["day", "time_in", "time_out", "break_minutes", "comment", "created_at", "updated_at"],
        data,
    )


@app.get("/export/trips.csv")
@login_required
def export_trips_csv():
    bootstrap()
    u = current_user()
    date_from, date_to = _export_date_range(u["id"])
    db = connect()
    rows = db.execute(
        """
        SELECT start_date, end_date, destination, departure_time, departure_end_time,
               return_time, return_end_time, notes, created_at
        FROM business_trips
        WHERE user_id = ? AND start_date BETWEEN ? AND ?
        ORDER BY start_date
        """,
        (u["id"], date_from, date_to),
    ).fetchall()
    db.close()
    data = [
        [r["start_date"], r["end_date"] or "", r["destination"],
         r["departure_time"] or "", r["departure_end_time"] or "",
         r["return_time"] or "", r["return_end_time"] or "",
         r["notes"] or "", r["created_at"] or ""]
        for r in rows
    ]
    return _csv_response(
        _export_filename("dienstreisen", date_from, date_to),
        ["start_date", "end_date", "destination", "departure_time", "departure_end_time",
         "return_time", "return_end_time", "notes", "created_at"],
        data,
    )


@app.get("/export/balance.csv")
@login_required
def export_balance_csv():
    bootstrap()
    u = current_user()
    date_from, date_to = _export_date_range(u["id"])
    today_iso = datetime.date.today().isoformat()
    date_to = min(date_to, today_iso)

    start_minutes = _get_start_balance_minutes(u["id"])
    flextag_ranges = _fetch_flextag_ranges(u["id"])
    running = int(start_minutes)
    data = []
    for iso in _iter_days(date_from, date_to):
        expected = int(_expected_minutes_for_day(u["id"], iso) or 0)
        actual   = int(_actual_minutes_for_day(u["id"], iso) or 0)
        flextag_min = 0
        if iso < today_iso and expected == 0 and _is_flextag(iso, flextag_ranges):
            flextag_min = _scheduled_minutes_ignoring_absence(u["id"], iso)
        delta = actual - expected - flextag_min
        running += delta
        if expected or actual:
            data.append([iso, _fmt_minutes(expected), _fmt_minutes(actual),
                         _fmt_minutes_signed(delta), _fmt_minutes_signed(running)])
    return _csv_response(
        _export_filename("gleitzeitkonto", date_from, date_to),
        ["day", "soll", "ist", "delta", "saldo"],
        data,
    )


@app.get("/export/calendar_days.csv")
@login_required
def export_calendar_days_csv():
    bootstrap()
    db = connect()
    rows = db.execute(
        "SELECT day, is_holiday, holiday_name, is_school_holiday, school_holiday_name, region, updated_at FROM calendar_days ORDER BY day"
    ).fetchall()
    db.close()
    data = [[r["day"], r["is_holiday"], r["holiday_name"] or "", r["is_school_holiday"], r["school_holiday_name"] or "", r["region"] or "", r["updated_at"] or ""] for r in rows]
    return _csv_response(
        "calendar_days.csv",
        ["day", "is_holiday", "holiday_name", "is_school_holiday", "school_holiday_name", "region", "updated_at"],
        data,
    )


@app.get("/export/users.csv")
@admin_required
def export_users_csv():
    bootstrap()
    db = connect()
    rows = db.execute(
        "SELECT id, username, is_admin, is_active, created_at, updated_at FROM users ORDER BY username"
    ).fetchall()
    db.close()
    data = [[r["id"], r["username"], r["is_admin"], r["is_active"], r["created_at"] or "", r["updated_at"] or ""] for r in rows]
    return _csv_response(
        "users.csv",
        ["id", "username", "is_admin", "is_active", "created_at", "updated_at"],
        data,
    )

# -------------------------
# Admin: Benutzer
# -------------------------

@app.get("/admin/users")
@admin_required
def admin_users():
    bootstrap()
    u = current_user()
    db = connect()
    users = db.execute(
        "SELECT id, username, display_name, is_admin, is_active, vacation_carryover_exception, "
        "contouring_enabled, contouring_start_date, created_at FROM users ORDER BY username"
    ).fetchall()
    db.close()

    trs = ""
    for r in users:
        display = r["display_name"] or r["username"]
        sub = r["username"] if r["display_name"] else ""
        flags = []
        if r["is_admin"]:
            flags.append("Admin")
        if not r["is_active"]:
            flags.append("inaktiv")
        fl = (" <span class='small'>· " + ", ".join(flags) + "</span>") if flags else ""
        sub_html = f" <span class='small' style='color:var(--mu);'>({sub})</span>" if sub else ""
        delete_btn = ""
        if r["id"] != u["id"]:
            safe_name = display.replace("'", "\\'")
            delete_btn = (
                f'<form method="post" action="/admin/users/{r["id"]}/delete" style="display:inline;margin-left:8px;" '
                f'onsubmit="return confirm(\'Nutzer {safe_name} und alle zugehörigen Daten unwiderruflich löschen?\')">'
                f'<button class="btn danger" type="submit" style="padding:4px 10px;font-size:13px;">Löschen</button></form>'
            )
        impersonate_btn = ""
        if not r["is_admin"] and r["is_active"] and r["id"] != u["id"]:
            impersonate_btn = (
                f'<form method="post" action="/admin/impersonate/{r["id"]}" style="display:inline;margin-left:8px;">'
                f'<button class="btn" type="submit" style="padding:4px 10px;font-size:13px;" title="Identität annehmen">👤 Identität</button></form>'
            )
        carryover_exc_badge = ""
        if r["vacation_carryover_exception"]:
            carryover_exc_badge = " <span class='small' style='color:#d97706;'>Übertrag⚡</span>"
        contouring_on = int(r["contouring_enabled"]) if r["contouring_enabled"] is not None else 1
        csd = str(r["contouring_start_date"] or "")[:10]
        if contouring_on:
            c_badge = f" <span class='small' style='color:var(--ok);'>Kontierung aktiv{(' ab ' + _fmt_date_de(csd)) if csd else ''}</span>"
        else:
            c_badge = " <span class='small' style='color:var(--mu);'>Kontierung deaktiviert</span>"
        trs += (
            f'<tr>'
            f'<td>{display}{sub_html}{fl}{carryover_exc_badge}{c_badge}</td>'
            f'<td class="small">{(r["created_at"] or "")[:10]}</td>'
            f'<td style="white-space:nowrap;">'
            f'<a href="/admin/users/{r["id"]}/edit">Bearbeiten</a>'
            f'<a href="/admin/users/{r["id"]}/vacation-carryover" style="margin-left:8px;">Urlaubsübertrag</a>'
            f'{impersonate_btn}{delete_btn}</td>'
            f'</tr>'
        )

    body = f'''
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Benutzer</h3>
        <a class="btn" href="/admin/users/new">+ Benutzer</a>
      </div>
      <table>
        <thead><tr><th>Name</th><th>Angelegt</th><th></th></tr></thead>
        <tbody>{trs}</tbody>
      </table>
      <p class="small">Benutzernamen sind nicht änderbar. Eigener Account kann nicht gelöscht werden.</p>
    </div>
    '''
    return render_template_string(layout("Admin: Benutzer", body, u, APP_VERSION))


@app.get("/admin/users/new")
@admin_required
def admin_users_new():
    bootstrap()
    u = current_user()
    today_iso = datetime.date.today().isoformat()
    body = f'''
    {flash_html()}
    {FORM_ASSETS_JS}
    <div class="card">
      <h3>Benutzer anlegen</h3>
      <p class="small">Das Passwort ist temporär – der Nutzer wird beim ersten Login durch den Einrichtungs-Wizard geführt.</p>
      <form method="post" action="/admin/users/new">
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;">
          <div><label>Username</label><br><input name="username" required></div>
          <div><label>Temporäres Passwort</label><br><input type="password" name="password" required></div>
        </div>
        <div style="margin-bottom:10px;">
          <label>Erfassung ab <span class="small">(leer = ab Jahresbeginn)</span></label><br>
          {_date_input("tracking_start_date", today_iso)}
        </div>
        <label><input type="checkbox" name="is_admin" value="1"> Admin</label><br>
        <label><input type="checkbox" name="is_active" value="1" checked> aktiv</label><br><br>
        <button class="btn primary" type="submit">Anlegen</button>
        <a class="btn" href="/admin/users">Abbrechen</a>
      </form>
    </div>
    '''
    return render_template_string(layout("Admin: Benutzer anlegen", body, u, APP_VERSION))


@app.post("/admin/users/new")
@admin_required
def admin_users_new_post():
    bootstrap()
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    is_admin = (request.form.get("is_admin") or "0") == "1"
    is_active = (request.form.get("is_active") or "0") == "1"
    tracking_start_date = _parse_date_input(request.form.get("tracking_start_date") or "")

    if not username or not password:
        add_flash("Bitte Username/Passwort angeben.", "error")
        return redirect(url_for("admin_users_new"))

    try:
        create_user(
            username,
            password,
            is_admin=is_admin,
            is_active=is_active,
            tracking_start_date=tracking_start_date,
            onboarding_done=0,
        )
    except Exception:
        add_flash("Benutzer konnte nicht angelegt werden (evtl. Username bereits vorhanden).", "error")
        return redirect(url_for("admin_users_new"))

    add_flash("Benutzer angelegt. Der Nutzer wird beim Login durch den Einrichtungs-Wizard geführt.", "success")
    return redirect(url_for("admin_users"))


@app.get("/admin/users/<int:user_id>/edit")
@admin_required
def admin_users_edit(user_id: int):
    bootstrap()
    u = current_user()
    db = connect()
    r = db.execute("SELECT id, username, is_admin, is_active, tracking_start_date FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    if not r:
        abort(404)

    admin_checked = "checked" if r["is_admin"] else ""
    active_checked = "checked" if r["is_active"] else ""
    tsd_val = str(r["tracking_start_date"] or "")[:10]

    # Schedule list for this user
    all_scheds = _get_user_schedules_all(user_id)
    today_iso = datetime.date.today().isoformat()
    cur_sched = _get_user_schedule_for_day(user_id, today_iso)
    cur_id = (cur_sched or {}).get("id")
    sched_rows = ""
    for s in all_scheds:
        sid = s.get("id")
        vf = s.get("valid_from") or ""
        mode = (s.get("mode") or "weekly").lower()
        if mode == "daily":
            dp = []
            for dk, lbl in [("mon_minutes","Mo"),("tue_minutes","Di"),("wed_minutes","Mi"),
                             ("thu_minutes","Do"),("fri_minutes","Fr"),("sat_minutes","Sa"),("sun_minutes","So")]:
                v = int(s.get(dk) or 0)
                if v:
                    dp.append(f"{lbl}:{_fmt_minutes(v)}")
            soll = " ".join(dp) if dp else "–"
        else:
            wm = int(s.get("weekly_minutes") or 0)
            soll = f"{wm/60:g} h/Woche" if wm else "–"
        try:
            if sid and cur_id and int(sid) == int(cur_id):
                badge = "<span class='badge' style='background:#0a7;color:#fff;'>Aktuell</span>"
            elif vf and vf > today_iso:
                badge = "<span class='badge' style='background:#888;color:#fff;'>Zukünftig</span>"
            else:
                badge = "<span class='badge' style='background:#ddd;'>Historie</span>"
        except Exception:
            badge = ""
        del_form = (f"<form method='post' action='/admin/schedule/{user_id}/delete/{sid}' style='display:inline;'"
                    f" onsubmit=\"return confirm('Zeitschema ab {_fmt_date_de(vf)} löschen?');\">"
                    f"<button class='btn danger' style='padding:3px 8px;font-size:12px;'>Löschen</button></form>") if sid else ""
        edit_link = f"<a href='/admin/schedule/{user_id}/edit/{sid}' style='font-size:12px;'>Bearb.</a>" if sid else ""
        sched_rows += (
            f"<tr><td style='white-space:nowrap;'><b>{_fmt_date_de(vf) if vf else '–'}</b></td>"
            f"<td>{badge}</td><td class='small'>{soll}</td>"
            f"<td style='white-space:nowrap;'>{edit_link} {del_form}</td></tr>"
        )
    if not sched_rows:
        sched_rows = "<tr><td colspan='4' class='small' style='color:#666;'>Noch kein Zeitschema vorhanden.</td></tr>"

    body = f'''
    {flash_html()}
    {FORM_ASSETS_JS}
    <div class="card">
      <h3>Benutzer bearbeiten: {r["username"]}</h3>
      <form method="post" action="/admin/users/{user_id}/edit">
        <label><input type="checkbox" name="is_admin" value="1" {admin_checked}> Admin</label><br>
        <label><input type="checkbox" name="is_active" value="1" {active_checked}> aktiv</label><br><br>

        <div><label>Arbeitsbeginn (start_date)</label><br>
          {_date_input("tracking_start_date", tsd_val)}
          <div class="small" style="color:#777;margin-top:3px;">Kein Eintrag vor diesem Datum möglich.</div>
        </div><br>

        <div><label>Neues Passwort (optional)</label><br>
          <input type="password" name="new_password" placeholder="leer lassen = unverändert">
        </div><br>

        <button class="btn" type="submit">Speichern</button>
        <a class="btn" href="/admin/users">Zurück</a>
      </form>
    </div>

    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px;">
        <h3 style="margin:0;">Zeitschemata</h3>
        <a class="btn" href="/admin/schedule/{user_id}/edit/new">+ Neues Schema</a>
      </div>
      <table>
        <thead><tr><th>Gültig ab</th><th>Status</th><th>Soll</th><th></th></tr></thead>
        <tbody>{sched_rows}</tbody>
      </table>
    </div>
    '''
    return render_template_string(layout("Admin: Benutzer bearbeiten", body, u, APP_VERSION))


@app.post("/admin/users/<int:user_id>/edit")
@admin_required
def admin_users_edit_post(user_id: int):
    bootstrap()
    is_admin = (request.form.get("is_admin") or "0") == "1"
    is_active = (request.form.get("is_active") or "0") == "1"
    set_flags(user_id, is_admin=is_admin, is_active=is_active)

    tsd = _parse_date_input(request.form.get("tracking_start_date") or "")
    if tsd:
        db = connect()
        db.execute("UPDATE users SET tracking_start_date=?, updated_at=datetime('now') WHERE id=?", (tsd, user_id))
        db.commit()
        db.close()

    new_pw = (request.form.get("new_password") or "").strip()
    if new_pw:
        set_password(user_id, new_pw)

    add_flash("Benutzer gespeichert.", "success")
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/delete")
@admin_required
def admin_users_delete(user_id: int):
    bootstrap()
    u = current_user()

    if user_id == u["id"]:
        add_flash("Eigener Account kann nicht gelöscht werden.", "error")
        return redirect(url_for("admin_users"))

    db = connect()
    target = db.execute(
        "SELECT id, username, display_name, is_admin FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if not target:
        db.close()
        abort(404)

    # Prevent deleting the last admin
    if target["is_admin"]:
        admin_count = db.execute("SELECT COUNT(*) FROM users WHERE is_admin=1 AND is_active=1").fetchone()[0]
        if admin_count <= 1:
            db.close()
            add_flash("Letzter Admin-Account kann nicht gelöscht werden.", "error")
            return redirect(url_for("admin_users"))

    display = target["display_name"] or target["username"]
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    db.close()
    add_flash(f"Benutzer '{display}' und alle zugehörigen Daten wurden gelöscht.", "success")
    return redirect(url_for("admin_users"))


@app.get("/admin/users/<int:user_id>/vacation-carryover")
@admin_required
def admin_vacation_carryover(user_id: int):
    bootstrap()
    u = current_user()
    db = connect()
    target = db.execute(
        "SELECT id, username, display_name, vacation_carryover_exception FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    db.close()
    if not target:
        abort(404)

    display = target["display_name"] or target["username"]
    exception_on = int(target["vacation_carryover_exception"] or 0)
    overrides = _get_all_vacation_carryover_overrides(user_id)
    cur_year = datetime.date.today().year
    vc = _vacation_calc(user_id, cur_year)
    prefill_days = vc["carryover"]

    override_rows = ""
    for ov in overrides:
        ov_year = ov["year"]
        override_rows += (
            f"<tr>"
            f"<td>{ov_year}</td>"
            f"<td>{ov['carryover_days']:.1f}</td>"
            f"<td>{ov['valid_until'] or '–'}</td>"
            f"<td class='small'>{_html.escape(ov['comment'] or '')}</td>"
            f"<td>"
            f"<form method='post' action='/admin/users/{user_id}/vacation-carryover/delete/{ov_year}' style='display:inline;'>"
            f"<button class='btn danger' type='submit' style='padding:3px 8px;font-size:12px;'>Löschen</button></form>"
            f"</td>"
            f"</tr>"
        )
    override_table = (
        f"<table><thead><tr><th>Jahr</th><th>Tage</th><th>Gültig bis</th><th>Kommentar</th><th></th></tr></thead>"
        f"<tbody>{override_rows}</tbody></table>"
    ) if overrides else "<p class='small'>Noch keine Übertrag-Ausnahmen konfiguriert.</p>"

    checked = "checked" if exception_on else ""
    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;">
        <h3 style="margin:0;">Urlaubsübertrag-Ausnahme · {_html.escape(display)}</h3>
        <a class="btn" href="/admin/users">← Zurück</a>
      </div>

      <p class="small">
        Standardregel: Übertrag verfällt am 31.03. des Folgejahres.<br>
        Ausnahme: Übertrag bleibt unbegrenzt gültig – Betrag aus der Tabelle unten wird verwendet.
      </p>

      <h3 style="margin-top:14px;">Bestehende Ausnahmen</h3>
      {override_table}

      <hr style="margin:18px 0;">
      <h3 style="margin-top:0;">Einstellung & Eintrag speichern</h3>
      <form method="post" action="/admin/users/{user_id}/vacation-carryover">
        <div style="margin-bottom:12px;">
          <label style="display:flex;align-items:center;gap:8px;font-weight:600;cursor:pointer;">
            <input type="checkbox" name="exception" value="1" {checked} id="exc-cb"
              onchange="document.getElementById('exc-fields').style.display=this.checked?'block':'none';">
            Ausnahme gilt (kein Verfall am 31.03.)
          </label>
        </div>
        <div id="exc-fields" style="display:{'block' if exception_on else 'none'};border-left:3px solid #f59e0b;padding-left:14px;margin-bottom:14px;">
          <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:end;">
            <div>
              <label>Jahr</label><br>
              <input name="year" type="number" min="2020" max="2099" value="{cur_year}" style="width:90px;" required>
            </div>
            <div>
              <label>Übertragstage (Ausnahme)</label><br>
              <input name="carryover_days" type="number" step="0.5" min="0" value="{prefill_days}" style="width:100px;">
            </div>
            <div>
              <label>Gültig bis <span class="small">(optional)</span></label><br>
              {_date_input("valid_until", "")}
            </div>
          </div>
          <div style="margin-top:10px;">
            <label>Kommentar <span class="small">(optional)</span></label><br>
            <input name="comment" style="width:100%;max-width:400px;">
          </div>
        </div>
        <button class="btn primary" type="submit">Speichern</button>
      </form>
    </div>
    """
    return render_template_string(layout("Urlaubsübertrag-Ausnahme", body, u, APP_VERSION))


@app.post("/admin/users/<int:user_id>/vacation-carryover")
@admin_required
def admin_vacation_carryover_post(user_id: int):
    bootstrap()
    db = connect()
    target = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    if not target:
        abort(404)

    exception_on = 1 if request.form.get("exception") == "1" else 0
    _set_vacation_carryover_exception(user_id, exception_on)

    if exception_on and request.form.get("carryover_days") is not None:
        try:
            year = int(request.form.get("year") or datetime.date.today().year)
            carryover_days = float(request.form.get("carryover_days") or 0)
            valid_until = (request.form.get("valid_until") or "").strip() or None
            comment = (request.form.get("comment") or "").strip()
            _upsert_vacation_carryover_override(user_id, year, carryover_days, valid_until, comment)
        except (ValueError, TypeError):
            add_flash("Ungültige Eingabe bei Übertragstagen.", "error")
            return redirect(url_for("admin_vacation_carryover", user_id=user_id))

    add_flash("Urlaubsübertrag-Ausnahme gespeichert.", "success")
    return redirect(url_for("admin_vacation_carryover", user_id=user_id))


@app.post("/admin/users/<int:user_id>/vacation-carryover/delete/<int:year>")
@admin_required
def admin_vacation_carryover_delete(user_id: int, year: int):
    bootstrap()
    _delete_vacation_carryover_override(user_id, year)
    add_flash(f"Übertrag-Ausnahme für {year} gelöscht.", "success")
    return redirect(url_for("admin_vacation_carryover", user_id=user_id))


@app.post("/admin/impersonate/<int:user_id>")
@admin_required
def admin_impersonate(user_id: int):
    bootstrap()
    u = current_user()
    db = connect()
    target = db.execute(
        "SELECT id, username, is_admin, is_active FROM users WHERE id=?", (user_id,)
    ).fetchone()
    db.close()
    if not target:
        abort(404)
    if target["is_admin"]:
        add_flash("Admin-Identität kann nicht angenommen werden.", "error")
        return redirect(url_for("admin_users"))
    if not target["is_active"]:
        add_flash("Inaktive Benutzer können nicht angenommen werden.", "error")
        return redirect(url_for("admin_users"))
    session["impersonator_id"] = u["id"]
    session["user_id"] = user_id
    return redirect("/")


@app.post("/admin/impersonate/stop")
def admin_impersonate_stop():
    impersonator_id = session.get("impersonator_id")
    if not impersonator_id:
        return redirect("/")
    session["user_id"] = impersonator_id
    session.pop("impersonator_id", None)
    return redirect(url_for("admin_users"))


# ─── Admin: Zeitschema bearbeiten / löschen ──────────────────────────────────

@app.get("/admin/schedule/<int:user_id>/edit/<schedule_id>")
@admin_required
def admin_schedule_edit(user_id: int, schedule_id: str):
    bootstrap()
    u = current_user()
    db = connect()
    target = db.execute("SELECT id, username FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    if not target:
        abort(404)

    if schedule_id == "new":
        sched = _normalize_schedule({})
        is_new = True
    else:
        try:
            sid = int(schedule_id)
        except ValueError:
            abort(404)
        db = connect()
        row = db.execute("SELECT * FROM user_schedules WHERE id=? AND user_id=?", (sid, user_id)).fetchone()
        db.close()
        if not row:
            abort(404)
        sched = _normalize_schedule(dict(row))
        is_new = False

    title = (f"Neues Zeitschema – {target['username']}" if is_new
             else f"Zeitschema bearbeiten – {target['username']} (ab {sched.get('valid_from','')})")
    action = f"/admin/schedule/{user_id}/edit/{schedule_id}"
    back = f"/admin/users/{user_id}/edit"

    body = f"""
    {flash_html()}
    {FORM_ASSETS_JS}
    <div class="card">
      <h3 style="margin-top:0;">{title}</h3>
      {_sched_form_html(sched, action, back)}
    </div>
    """
    return render_template_string(layout(title, body, u, APP_VERSION))


@app.post("/admin/schedule/<int:user_id>/edit/<schedule_id>")
@admin_required
def admin_schedule_edit_post(user_id: int, schedule_id: str):
    bootstrap()
    db = connect()
    target = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    if not target:
        abort(404)

    sched = _parse_sched_form(request.form)
    if not sched["valid_from"]:
        add_flash("Bitte ein gültiges Datum angeben.", "error")
        return redirect(f"/admin/schedule/{user_id}/edit/{schedule_id}")

    # When editing an existing entry, delete the old row first (handles valid_from changes)
    if schedule_id != "new":
        try:
            sid = int(schedule_id)
            db = connect()
            db.execute("DELETE FROM user_schedules WHERE id=? AND user_id=?", (sid, user_id))
            db.commit()
            db.close()
        except (ValueError, Exception):
            pass

    _sched_save_to_db(user_id, sched)
    add_flash(f"Zeitschema ab {_fmt_date_de(sched['valid_from'])} gespeichert.", "success")
    return redirect(f"/admin/users/{user_id}/edit")


@app.post("/admin/schedule/<int:user_id>/delete/<int:schedule_id>")
@admin_required
def admin_schedule_delete(user_id: int, schedule_id: int):
    bootstrap()
    db = connect()
    row = db.execute(
        "SELECT id, valid_from FROM user_schedules WHERE id=? AND user_id=?",
        (schedule_id, user_id),
    ).fetchone()
    if row:
        db.execute("DELETE FROM user_schedules WHERE id=?", (schedule_id,))
        db.commit()
        add_flash(f"Zeitschema ab {_fmt_date_de(row['valid_from'])} gelöscht.", "success")
    else:
        add_flash("Zeitschema nicht gefunden.", "error")
    db.close()
    return redirect(f"/admin/users/{user_id}/edit")


@app.get("/admin/periods")
@admin_required
def admin_periods():
    bootstrap()
    u = current_user()
    today = datetime.date.today()

    try:
        sel_year = int(request.args.get("y") or today.year)
    except (ValueError, TypeError):
        sel_year = today.year

    db = connect()
    try:
        all_users = db.execute("SELECT id, username FROM users WHERE is_active=1 ORDER BY username").fetchall()
        locks_raw = db.execute(
            "SELECT pl.*, u.username AS locked_by_name FROM period_locks pl "
            "LEFT JOIN users u ON u.id=pl.locked_by WHERE pl.year=? ORDER BY pl.user_id, pl.period_type, pl.month",
            (sel_year,),
        ).fetchall()
    finally:
        db.close()

    # Group locks by user_id
    locks_by_user: dict = {}
    for r in locks_raw:
        uid = r["user_id"]
        locks_by_user.setdefault(uid, {})
        if r["period_type"] == "year":
            locks_by_user[uid]["year"] = dict(r)
        else:
            locks_by_user[uid][f"{sel_year}-{r['month']:02d}"] = dict(r)

    available_years = list(range(max(today.year - 5, 2020), today.year + 1))
    year_opts = "".join(
        f'<option value="{y}" {"selected" if y == sel_year else ""}>{y}</option>'
        for y in reversed(available_years)
    )

    trs = ""
    for usr in all_users:
        uid = usr["id"]
        ulocks = locks_by_user.get(uid, {})
        year_lk = "year" in ulocks
        locked_months = [
            m for m in range(1, 13)
            if year_lk or f"{sel_year}-{m:02d}" in ulocks
        ]
        n_locked = len(locked_months)
        if n_locked == 0:
            status_txt = "<span class='small' style='color:var(--mu);'>Keine Abschlüsse</span>"
        elif n_locked == 12 or year_lk:
            status_txt = "<span style='color:var(--ok);'>🔒 Jahr abgeschlossen</span>"
        else:
            names = ", ".join(MONTH_NAMES_DE[m][:3] for m in locked_months)
            status_txt = f"<span style='color:var(--ok);'>🔒 {n_locked} Monate ({names})</span>"

        unlock_form = (
            f"<form method='post' action='/admin/periods/unlock' style='display:inline;'>"
            f"<input type='hidden' name='target_user_id' value='{uid}'>"
            f"<input type='hidden' name='year' value='{sel_year}'>"
            f"<button class='btn danger' style='padding:4px 10px;font-size:13px;'>Alle entsperren</button>"
            f"</form>"
        ) if ulocks else ""

        detail_link = f"<a class='btn' href='/periods?y={sel_year}' style='padding:4px 10px;font-size:13px;'>Details</a>" if uid == u["id"] else ""

        trs += f"<tr><td><b>{usr['username']}</b></td><td>{status_txt}</td><td style='white-space:nowrap;'>{detail_link} {unlock_form}</td></tr>"

    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Admin: Abschlüsse</h3>
        <form method="get" style="display:flex;gap:8px;align-items:end;">
          <div><label>Jahr</label><br><select name="y">{year_opts}</select></div>
          <button class="btn" type="submit">Anzeigen</button>
        </form>
      </div>
      <table style="margin-top:12px;">
        <thead><tr><th>Benutzer</th><th>Status {sel_year}</th><th></th></tr></thead>
        <tbody>{trs}</tbody>
      </table>
    </div>
    """
    return render_template_string(layout("Admin: Abschlüsse", body, u, APP_VERSION))


@app.post("/admin/periods/unlock")
@admin_required
def admin_periods_unlock():
    bootstrap()
    try:
        target_uid = int(request.form.get("target_user_id") or 0)
        year = int(request.form.get("year") or 0)
    except (ValueError, TypeError):
        add_flash("Ungültige Eingabe.", "error")
        return redirect("/admin/periods")

    db = connect()
    try:
        db.execute("DELETE FROM period_locks WHERE user_id=? AND year=?", (target_uid, year))
        db.commit()
    finally:
        db.close()
    add_flash(f"Alle Abschlüsse für Jahr {year} entsperrt.", "success")
    return redirect(f"/admin/periods?y={year}")


if __name__ == "__main__":
    app.run(debug=True)