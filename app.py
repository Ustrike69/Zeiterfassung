from flask import Flask, request, redirect, url_for, session, render_template_string, abort, jsonify, send_file
from werkzeug.middleware.proxy_fix import ProxyFix
import datetime
import calendar
import sqlite3
import re
import html as _html
import os
import json as _json
from db import init_db, seed_defaults, db_path, connect
from calendar_seed import seed_all_regions_if_needed, REGION_GROUPS, ALL_REGIONS
from auth import (has_users, create_user, authenticate, current_user, login_required,
                  admin_required, sysadmin_required, timemanager_required, hr_required,
                  set_password, set_flags, set_admin_role, set_active,
                  is_sysadmin, is_timemanager, is_hr, validate_password, set_must_change_password,
                  set_language, unlock_account, validate_unlock_token, get_lockout_until,
                  set_totp, disable_totp, get_totp_row, update_totp_backup_codes)
from templates import layout as base_layout
from translations import t, fmt_date as _fmt_date_i18n, fmt_time as _fmt_time_i18n, available_languages as _available_languages
from blueprints.school_holidays import school_holidays_bp
from blueprints.vocational import vocational_bp
from blueprints.admin import admin_bp
from blueprints.absences import absences_bp
from blueprints.caldav import caldav_bp
from blueprints.business_trips import business_trips_bp
from blueprints.export import export_bp
from blueprints.settings import settings_bp
from blueprints.api import api_bp
from blueprints.staffing import staffing_bp
from blueprints.day import day_bp
from blueprints.auth_routes import auth_routes_bp
from blueprints.core import core_bp
from blueprints.balance import balance_bp
from blueprints.approvals import approvals_bp
from blueprints.calendar import calendar_routes_bp
from blueprints.dev import dev_bp


APP_VERSION = "v3.0.15"

IS_DEV = os.environ.get("ZEITERFASSUNG_DEV_MODE") == "1"
if IS_DEV:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "⚠️  DEV MODE AKTIV — niemals in Produktion nutzen!"
    )

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_for=1)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
app.register_blueprint(school_holidays_bp)
app.register_blueprint(vocational_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(absences_bp)
app.register_blueprint(caldav_bp)
app.register_blueprint(business_trips_bp)
app.register_blueprint(export_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(api_bp)
app.register_blueprint(staffing_bp)
app.register_blueprint(day_bp)
app.register_blueprint(auth_routes_bp)
app.register_blueprint(core_bp)
app.register_blueprint(balance_bp)
app.register_blueprint(approvals_bp)
app.register_blueprint(calendar_routes_bp)
app.register_blueprint(dev_bp)


@app.errorhandler(404)
def handle_404(e):
    try:
        u = current_user()
    except Exception:
        u = None
    body = f"""
    <div style="max-width:480px;margin:80px auto;text-align:center;padding:0 20px;">
      <div style="font-size:64px;margin-bottom:16px;">🔍</div>
      <h2 style="margin-bottom:8px;">{t('error.404_title')}</h2>
      <p style="color:var(--mu);margin-bottom:24px;">{t('error.404_text')}</p>
      <a href="/" class="btn primary">{t('error.back_home')}</a>
    </div>
    """
    return render_template_string(
        layout(t('error.404_title'), body, u, APP_VERSION, show_back=False)
    ), 404


@app.errorhandler(403)
def handle_403(e):
    try:
        u = current_user()
    except Exception:
        u = None
    body = f"""
    <div style="max-width:480px;margin:80px auto;text-align:center;padding:0 20px;">
      <div style="font-size:64px;margin-bottom:16px;">🔒</div>
      <h2 style="margin-bottom:8px;">{t('error.403_title')}</h2>
      <p style="color:var(--mu);margin-bottom:24px;">{t('error.403_text')}</p>
      <a href="/" class="btn primary">{t('error.back_home')}</a>
    </div>
    """
    return render_template_string(
        layout(t('error.403_title'), body, u, APP_VERSION, show_back=False)
    ), 403


@app.errorhandler(500)
def handle_500(e):
    try:
        u = current_user()
    except Exception:
        u = None
    app.logger.error(f"500 error: {e}", exc_info=True)
    body = f"""
    <div style="max-width:480px;margin:80px auto;text-align:center;padding:0 20px;">
      <div style="font-size:64px;margin-bottom:16px;">⚠️</div>
      <h2 style="margin-bottom:8px;">{t('error.500_title')}</h2>
      <p style="color:var(--mu);margin-bottom:24px;">{t('error.500_text')}</p>
      <a href="/" class="btn primary">{t('error.back_home')}</a>
    </div>
    """
    try:
        return render_template_string(
            layout(t('error.500_title'), body, u, APP_VERSION, show_back=False)
        ), 500
    except Exception:
        return f"<h2>{t('error.500_title')}</h2><p><a href='/'>{t('error.back_home')}</a></p>", 500
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(days=30)


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


def _get_app_config() -> dict:
    from flask import g
    if hasattr(g, '_app_config_cache'):
        return g._app_config_cache
    try:
        db = connect()
        rows = db.execute("SELECT key, value FROM app_config").fetchall()
        db.close()
        result = {r["key"]: r["value"] for r in rows}
    except Exception:
        result = {}
    g._app_config_cache = result
    return result


def _feature_enabled(key: str) -> bool:
    return _get_app_config().get(f"feature_{key}", "0") == "1"


def _get_visible_user_ids(u: dict):
    """Return list of user IDs visible to this admin, or None (= all) for sysadmin."""
    role = u.get("admin_role")
    if role == "sysadmin":
        return None
    db = connect()
    restriction = u.get("team_restriction")
    if restriction:
        team_ids = [int(x) for x in restriction.split(",") if x.strip().isdigit()]
    else:
        rows = db.execute(
            "SELECT team_id FROM user_teams WHERE user_id=?", (u["id"],)
        ).fetchall()
        team_ids = [r["team_id"] for r in rows]
    if not team_ids:
        db.close()
        return []
    ph = ",".join("?" * len(team_ids))
    users = db.execute(
        f"SELECT DISTINCT user_id FROM user_teams WHERE team_id IN ({ph})",
        team_ids
    ).fetchall()
    db.close()
    return [r["user_id"] for r in users]


def _user_has_team_plan(user_id: int) -> bool:
    """True if user belongs to a team that has an active staffing plan."""
    try:
        db = connect()
        row = db.execute("""
            SELECT sp.id FROM staffing_plans sp
            JOIN user_teams ut ON ut.team_id = sp.team_id
            WHERE ut.user_id = ? AND sp.active = 1
            LIMIT 1
        """, (user_id,)).fetchone()
        db.close()
        return row is not None
    except Exception:
        return False


def _slot_applies_on_date(slot, iso_date: str,
                          plan_id: int = None) -> bool:
    d = datetime.date.fromisoformat(iso_date)
    wd = d.weekday()

    slot_days = []
    if slot["weekdays"]:
        slot_days = [int(x) for x in str(slot["weekdays"]).split(",")]

    if wd >= 5 and wd not in slot_days:
        return False

    if plan_id:
        try:
            _db_hol = connect()
            _region = _db_hol.execute(
                "SELECT t.holiday_region FROM staffing_plans sp "
                "JOIN teams t ON t.id=sp.team_id WHERE sp.id=?",
                (plan_id,)
            ).fetchone()
            if _region and _region["holiday_region"]:
                _reg = _region["holiday_region"]
            else:
                _reg = (_get_app_config().get("default_holiday_region")
                        or "DE-NW")
            _hol = _db_hol.execute(
                "SELECT is_holiday FROM calendar_days "
                "WHERE day=? AND region=?",
                (iso_date, _reg)
            ).fetchone()
            _db_hol.close()
            if _hol and int(_hol["is_holiday"]) == 1:
                return False
        except Exception:
            pass

    stype = slot["slot_type"]
    if stype in ("vm", "nm"):
        return wd in slot_days
    elif stype == "special":
        if slot["special_weekday"] is None:
            return False
        if wd != int(slot["special_weekday"]):
            return False
        if not slot["nth_week"]:
            return False
        week_num = (d.day - 1) // 7 + 1
        weeks = [int(x) for x in str(slot["nth_week"]).split(",")]
        return week_num in weeks
    return False


def _user_works_in_slot(user_id: int, iso_date: str, time_from: str, time_to: str) -> bool:
    """True wenn der User laut Zeitschema im Slot-Zeitfenster arbeitet (Überlappung)."""
    wd = datetime.date.fromisoformat(iso_date).weekday()
    _db = connect()
    blocks = _db.execute(
        "SELECT sdb.time_from, sdb.time_to "
        "FROM schedule_daily_blocks sdb "
        "JOIN user_schedules us ON us.id = sdb.schedule_id "
        "WHERE us.user_id=? AND sdb.weekday=? AND us.valid_from <= ? "
        "ORDER BY us.valid_from DESC",
        (user_id, wd, iso_date)
    ).fetchall()
    _db.close()
    if not blocks:
        return False
    try:
        s_from = int(time_from[:2]) * 60 + int(time_from[3:])
        s_to   = int(time_to[:2])   * 60 + int(time_to[3:])
    except (ValueError, IndexError):
        return True
    for b in blocks:
        try:
            b_from = int(b["time_from"][:2]) * 60 + int(b["time_from"][3:])
            b_to   = int(b["time_to"][:2])   * 60 + int(b["time_to"][3:])
            if b_from < s_to and b_to > s_from:
                return True
        except (ValueError, IndexError):
            continue
    return False


_COMMON_TIMEZONES = [
    ("Europe/Berlin",     "Europe/Berlin (Deutschland, Österreich)"),
    ("Europe/Vienna",     "Europe/Vienna (Österreich)"),
    ("Europe/Zurich",     "Europe/Zurich (Schweiz)"),
    ("Europe/London",     "Europe/London (Großbritannien)"),
    ("Europe/Paris",      "Europe/Paris (Frankreich)"),
    ("Europe/Amsterdam",  "Europe/Amsterdam (Niederlande)"),
    ("Europe/Warsaw",     "Europe/Warsaw (Polen)"),
    ("Europe/Prague",     "Europe/Prague (Tschechien)"),
    ("Europe/Rome",       "Europe/Rome (Italien)"),
    ("Europe/Madrid",     "Europe/Madrid (Spanien)"),
    ("UTC",               "UTC"),
]


def _get_timezone():
    from zoneinfo import ZoneInfo
    tz = (_get_app_config().get("timezone") or "Europe/Berlin").strip()
    try:
        return ZoneInfo(tz)
    except Exception:
        return ZoneInfo("Europe/Berlin")


def _timezone_select(name: str, current: str = "Europe/Berlin") -> str:
    opts = "".join(
        f'<option value="{v}"{"  selected" if v == current else ""}>{_html.escape(label)}</option>'
        for v, label in _COMMON_TIMEZONES
    )
    return f'<select name="{name}" style="width:100%;max-width:400px;margin-top:4px;">{opts}</select>'


_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{3,8}$')


def _fernet():
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    import base64
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=b"zeiterfassung_totp_v1", iterations=100_000)
    key = base64.urlsafe_b64encode(kdf.derive(app.secret_key.encode()))
    return Fernet(key)


def _totp_encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def _totp_decrypt(text: str) -> str:
    return _fernet().decrypt(text.encode()).decode()


def _generate_totp_secret() -> str:
    import pyotp
    return pyotp.random_base32()


def _verify_totp(secret_encrypted: str, code: str) -> bool:
    import pyotp
    try:
        secret = _totp_decrypt(secret_encrypted)
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:
        return False


def _generate_backup_codes(n: int = 8) -> list:
    import secrets
    return [secrets.token_hex(4).upper() for _ in range(n)]


def _check_backup_code(codes_json_encrypted: str, code: str) -> tuple:
    """Returns (valid: bool, updated_json_encrypted: str)."""
    import json as _j
    try:
        codes = _j.loads(_totp_decrypt(codes_json_encrypted))
        code = code.strip().upper()
        if code in codes:
            codes.remove(code)
            return True, _totp_encrypt(_j.dumps(codes))
        return False, codes_json_encrypted
    except Exception:
        return False, codes_json_encrypted


def _get_base_url() -> str:
    """Return the configured external server URL, falling back to the current request origin."""
    base = (_get_app_config().get("base_url") or "").strip().rstrip("/")
    if not base:
        proto = request.headers.get("X-Forwarded-Proto") or request.scheme or "http"
        host  = request.headers.get("X-Forwarded-Host") or request.host
        base  = f"{proto}://{host}"
    return base


def _get_webcal_url(token: str) -> str:
    base = _get_base_url()
    if base.startswith("https://"):
        webcal = base.replace("https://", "webcal://", 1)
    else:
        webcal = base.replace("http://", "webcal://", 1)
    return f"{webcal}/absences/calendar/{token}.ics"


def layout(title, body, user, version, show_back=True):
    """Wrapper around templates.layout that injects mobile assets globally."""
    banner = ""
    if session.get("impersonator_id") and user:
        username = _html.escape(user.get("display_name") or user.get("username") or "?")
        banner = (
            '<div style="background:#f59e0b;color:#1c1917;padding:10px 16px;text-align:center;'
            'font-weight:600;display:flex;align-items:center;justify-content:center;gap:16px;flex-wrap:wrap;">'
            f'<span>{t("admin.impersonate_banner")} <strong>{username}</strong></span>'
            '<form method="post" action="/admin/impersonate/stop" style="display:inline;">'
            f'<button type="submit" style="background:#1c1917;color:#fef3c7;border:none;border-radius:6px;'
            f'padding:4px 12px;cursor:pointer;font-weight:600;font-size:14px;">{t("admin.impersonate_stop")}</button>'
            '</form></div>'
        )
    cfg = _get_app_config()
    accent = cfg.get("accent_color") or ""
    nav_color = cfg.get("nav_color") or ""
    app_label = (cfg.get("app_label") or "").strip()
    app_label_color = cfg.get("app_label_color") or "#f59e0b"

    root_parts = []
    if accent and _HEX_COLOR_RE.match(accent):
        root_parts.append(f"--ac:{accent};--ac-fg:#ffffff;")
    if nav_color and _HEX_COLOR_RE.match(nav_color):
        root_parts.append(f"--nav-bg:{nav_color};")
    extra_root_css = " ".join(root_parts)

    return base_layout(title, MOBILE_ASSETS + body, user, version,
                       impersonation_banner=banner, show_back=show_back,
                       extra_root_css=extra_root_css,
                       app_label=app_label,
                       app_label_color=app_label_color if _HEX_COLOR_RE.match(app_label_color) else "#f59e0b")


_bootstrap_done = False

def bootstrap():
    global _bootstrap_done
    if _bootstrap_done:
        return
    import threading as _threading
    import fcntl as _fcntl
    _lock_path = os.path.join(os.path.dirname(db_path()), ".bootstrap.lock")
    try:
        with open(_lock_path, "w") as _lf:
            _fcntl.flock(_lf, _fcntl.LOCK_EX)
            if not _bootstrap_done:
                _bootstrap_done = True
                init_db()
                seed_defaults()
                _ensure_user_schedules_schema()
                _ensure_user_prefs_schema()
                _ensure_expected_override_schema()
                _ensure_vacation_schema()
                _ensure_vacation_carryover_schema()
                _ensure_business_trips_schema()
                _ensure_contoured_days_schema()
                seed_all_regions_if_needed()
                _auto_lock_expired_users()
    except Exception as _be:
        import logging as _lg
        _lg.getLogger(__name__).error(f"bootstrap error: {_be}")




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

    # v3.0.0.dev4 – Tagesblöcke
    cur.execute("""CREATE TABLE IF NOT EXISTS schedule_daily_blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id INTEGER NOT NULL
            REFERENCES user_schedules(id) ON DELETE CASCADE,
        weekday INTEGER NOT NULL,
        time_from TEXT NOT NULL,
        time_to TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_schedule_daily_blocks_schedule ON schedule_daily_blocks(schedule_id)")

    # v3.0.6.dev1 – Ausnahmen (nth_weekday) für Tagesblöcke-Modus
    cur.execute("""CREATE TABLE IF NOT EXISTS schedule_exceptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id INTEGER NOT NULL
            REFERENCES user_schedules(id) ON DELETE CASCADE,
        weekday INTEGER NOT NULL,
        nth_weeks TEXT NOT NULL,
        time_from TEXT NOT NULL,
        time_to TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_schedule_exceptions_schedule ON schedule_exceptions(schedule_id)")

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


def _calc_ist_minutes(blocks) -> int:
    total = 0
    for b in blocks:
        if b["time_in"] and b["time_out"]:
            h_in, m_in = map(int, b["time_in"].split(":"))
            h_out, m_out = map(int, b["time_out"].split(":"))
            duration = (h_out * 60 + m_out) - (h_in * 60 + m_in)
            pause = int(b.get("break_minutes") or 0)
            total += max(0, duration - pause)
    return total


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
    if int(sched.get("block_weekends_holidays", 1)) == 1 and _blocked_by_calendar(iso_day, user_id):
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


def _get_vacation_entitlement(user_id: int, year: int) -> float:
    """Return vacation entitlement for user+year from user_vacation_entitlement table, else app default."""
    try:
        db = connect()
        row = db.execute("""
            SELECT days FROM user_vacation_entitlement
            WHERE user_id=? AND valid_from <= ?
            ORDER BY valid_from DESC LIMIT 1
        """, (user_id, f"{year}-12-31")).fetchone()
        db.close()
        if row:
            return float(row["days"])
    except Exception:
        pass
    cfg = _get_app_config()
    return float(cfg.get("default_vacation_days") or 30)


def _auto_lock_expired_users() -> None:
    """Deactivate users whose end_date has passed."""
    try:
        today = datetime.date.today().isoformat()
        db = connect()
        db.execute("""
            UPDATE users SET is_active=0, updated_at=datetime('now')
            WHERE end_date IS NOT NULL AND end_date < ? AND is_active=1
        """, (today,))
        db.commit()
        db.close()
    except Exception:
        pass


def _vacation_calc(user_id: int, year: int) -> dict:
    """Central vacation calculation. Returns all metrics needed for display and the homepage."""
    today = datetime.date.today()
    vac = _get_vacation_year(user_id, year)
    entitlement = float(vac.get("entitlement_days", 0.0) or 0.0)
    if entitlement == 0.0:
        entitlement = _get_vacation_entitlement(user_id, year)
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


def _fmt_vac_days(d: float) -> str:
    return str(int(d)) if d == int(d) else f"{d:.1f}"


def _count_absence_workdays(user_id: int, date_from: str, date_to: str, is_half_day: int) -> float:
    if is_half_day and date_from == date_to:
        return 0.5 if _is_user_workday_by_schedule(user_id, date_from) else 0.0
    total = 0.0
    cur = datetime.date.fromisoformat(date_from)
    end_d = datetime.date.fromisoformat(date_to)
    while cur <= end_d:
        if _is_user_workday_by_schedule(user_id, cur.isoformat()):
            total += 1.0
        cur += datetime.timedelta(days=1)
    return total


def _vacation_limit_check(
    user_id: int, date_from: str, date_to: str, is_half_day: int, exclude_id: int = None
) -> "tuple[float, float] | None":
    """Return (available, requested) vacation days. None if dates invalid."""
    if not date_from or not date_to:
        return None
    year = int(date_from[:4])
    vc = _vacation_calc(user_id, year)
    available = float(vc["remaining_total"])
    if exclude_id is not None:
        db = connect()
        row = db.execute(
            "SELECT a.date_from, a.date_to, a.is_half_day FROM absences a "
            "JOIN absence_types t ON t.id=a.type_id "
            "WHERE a.id=? AND LOWER(t.name) LIKE '%urlaub%'",
            (exclude_id,),
        ).fetchone()
        db.close()
        if row:
            available += _count_absence_workdays(
                user_id, str(row["date_from"]), str(row["date_to"]), int(row["is_half_day"])
            )
    requested = _count_absence_workdays(user_id, date_from, date_to, is_half_day)
    return available, requested


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


def _blocked_by_calendar(iso_day: str, user_id=None) -> bool:
    return _is_weekend(iso_day) or _is_holiday(iso_day, user_id)


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
            # Only count absences that are not pending/rejected (no approval record, or approved)
            row = db.execute(
                "SELECT 1 FROM absences a "
                "WHERE a.user_id=? AND a.date_from<=? AND a.date_to>=? "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM absence_approvals aa "
                "  WHERE aa.absence_id=a.id AND aa.status IN ('pending','rejected')"
                ") LIMIT 1",
                (user_id, iso_day, iso_day),
            ).fetchone()
            return bool(row)
        # fallback: no compatible columns -> treat as none
        return False
    finally:
        db.close()


def _get_vocational_school_entry(user_id: int, iso_day: str):
    """Return first matching vocational_school row for user+day, or None."""
    try:
        d = datetime.date.fromisoformat(iso_day)
        wd = d.weekday()
        db = connect()
        entries = db.execute("""
            SELECT * FROM vocational_school
            WHERE user_id=?
            AND (valid_from IS NULL OR valid_from <= ?)
            AND (valid_to IS NULL OR valid_to >= ?)
        """, (user_id, iso_day, iso_day)).fetchall()
        db.close()
        for e in entries:
            if e["schedule_type"] == "weekly":
                if e["weekday"] is not None and int(e["weekday"]) == wd:
                    return dict(e)
            elif e["schedule_type"] == "block":
                if e["date_from"] and e["date_to"]:
                    if e["date_from"] <= iso_day <= e["date_to"]:
                        return dict(e)
    except Exception:
        pass
    return None


def _is_school_holiday(iso_day: str, user_id=None) -> bool:
    """True if there is a school holiday for user's region on this day."""
    try:
        region = _get_user_holiday_region(user_id)
        db = connect()
        row = db.execute("""
            SELECT id FROM school_holidays
            WHERE region=? AND date_from <= ? AND date_to >= ? LIMIT 1
        """, (region, iso_day, iso_day)).fetchone()
        db.close()
        return row is not None
    except Exception:
        return False


def _expected_minutes_for_day(user_id: int, iso_day: str) -> int:
    # manual override has priority (if set)
    ov = _get_expected_override_minutes(user_id, iso_day)
    if ov is not None:
        return max(0, int(ov))
    sched = _normalize_schedule(_get_user_schedule_for_day(user_id, iso_day))

    if int(sched.get("block_weekends_holidays", 1)) == 1 and _blocked_by_calendar(iso_day, user_id):
        return 0

    d = datetime.date.fromisoformat(iso_day)
    wd = d.weekday()

    mask = int(sched.get("workdays_mask", _default_workdays_mask()))
    if not _mask_allows(mask, wd):
        return 0

    if _absence_on_day(user_id, iso_day):
        return 0

    # Berufsschule: Soll=0 (Ganztag) oder reduziert (Halbtag)
    voc = _get_vocational_school_entry(user_id, iso_day)
    if voc and not _is_holiday(iso_day, user_id):
        # Schulferien nur bei wöchentlichem BS-Tag relevant (Blockunterricht läuft durch)
        if voc["schedule_type"] == "weekly" and _is_school_holiday(iso_day, user_id):
            pass  # Ferientag → normaler Arbeitstag
        else:
            if voc.get("work_time_from") and voc.get("work_time_to"):
                try:
                    h_from = int(voc["work_time_from"][:2]) * 60 + int(voc["work_time_from"][3:])
                    h_to   = int(voc["work_time_to"][:2]) * 60 + int(voc["work_time_to"][3:])
                    return max(0, h_to - h_from)
                except Exception:
                    pass
            return 0

    mode = (sched.get("mode") or "weekly").strip().lower()
    if mode == "daily_hours":
        return int(sched.get(_weekday_col(d), 0) or 0)
    if mode == "daily":
        sched_id = sched.get("id")
        if sched_id:
            _db2 = connect()
            _blocks = _db2.execute(
                "SELECT time_from, time_to FROM schedule_daily_blocks "
                "WHERE schedule_id=? AND weekday=? ORDER BY sort_order",
                (sched_id, wd)
            ).fetchall()
            _db2.close()
            if _blocks:
                # Check nth-week exceptions first — they override normal blocks
                week_num = (d.day - 1) // 7 + 1
                _db3 = connect()
                try:
                    _exceptions = _db3.execute(
                        "SELECT nth_weeks, time_from, time_to FROM schedule_exceptions "
                        "WHERE schedule_id=? AND weekday=?",
                        (sched_id, wd)
                    ).fetchall()
                except Exception:
                    _exceptions = []
                finally:
                    _db3.close()
                for exc in _exceptions:
                    weeks = [int(w) for w in exc["nth_weeks"].split(",") if w.strip()]
                    if week_num in weeks:
                        try:
                            h_from = int(exc["time_from"][:2]) * 60 + int(exc["time_from"][3:])
                            h_to   = int(exc["time_to"][:2]) * 60 + int(exc["time_to"][3:])
                            return max(0, h_to - h_from)
                        except Exception:
                            pass
                total = 0
                for b in _blocks:
                    try:
                        hf, mf = map(int, b["time_from"].split(":"))
                        ht, mt = map(int, b["time_to"].split(":"))
                        total += (ht * 60 + mt) - (hf * 60 + mf)
                    except Exception:
                        pass
                return max(0, total)
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
    if int(sched.get("block_weekends_holidays", 1)) == 1 and _blocked_by_calendar(iso_day, user_id):
        return 0
    d = datetime.date.fromisoformat(iso_day)
    wd = d.weekday()
    mask = int(sched.get("workdays_mask", _default_workdays_mask()))
    if not _mask_allows(mask, wd):
        return 0
    mode = (sched.get("mode") or "weekly").strip().lower()
    if mode == "daily_hours":
        return int(sched.get(_weekday_col(d), 0) or 0)
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
    """Return list of (date_from, date_to) for all Flextag absences (own type or legacy Sonstige+comment)."""
    db = connect()
    try:
        rows = db.execute("""
            SELECT a.date_from, a.date_to
            FROM absences a JOIN absence_types t ON a.type_id = t.id
            WHERE a.user_id = ? AND (
                t.name = 'Flextag'
                OR (t.name = 'Sonstige' AND LOWER(TRIM(COALESCE(a.comment,''))) = 'flextag')
            )
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
        if int(sched.get("block_weekends_holidays", 1)) == 1 and _blocked_by_calendar(iso, user_id):
            continue
        for ab in absences:
            if ab["date_from"] <= iso <= ab["date_to"]:
                t = ab["type_name"]
                if iso < today_iso:
                    if t == "Urlaub":
                        past["urlaub"] += 1
                    elif t == "Krank":
                        past["krank"] += 1
                    elif t == "Flextag":
                        past["sonstige"]["Flextag"] = past["sonstige"].get("Flextag", 0) + 1
                    elif t == "Verdi":
                        past["sonstige"]["Verdi"] = past["sonstige"].get("Verdi", 0) + 1
                    elif t == "Sonstige":
                        remark = (ab["comment"] or "").strip()
                        past["sonstige"][remark] = past["sonstige"].get(remark, 0) + 1
                else:
                    if t == "Urlaub":
                        planned["urlaub"] += 1
                    elif t == "Flextag":
                        planned["sonstige"]["Flextag"] = planned["sonstige"].get("Flextag", 0) + 1
                    elif t == "Sonstige":
                        remark = (ab["comment"] or "").strip()
                        planned["sonstige"][remark] = planned["sonstige"].get(remark, 0) + 1
                break

    return {"past": past, "planned": planned}


# ─── Periodenabschluss (Monats- / Jahresabschluss) ───────────────────────────



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
    if mode not in ("weekly", "daily_hours", "daily"):
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


def _sched_save_to_db(user_id: int, sched_dict: dict) -> int:
    """Upsert a schedule row for user_id. Returns the schedule_id."""
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
    cur = db.execute(f"INSERT INTO user_schedules ({col_list}) VALUES ({ph_list})", list(row.values()))
    schedule_id = cur.lastrowid
    db.commit()
    db.close()
    return schedule_id


def _parse_sched_blocks_from_form(form) -> dict[int, list[tuple[str, str]]]:
    """Parse block_{wd}_from[] / block_{wd}_to[] from form. Returns {weekday: [(from, to), ...]}."""
    blocks: dict[int, list] = {}
    for wd in range(7):
        froms = form.getlist(f"block_{wd}_from[]")
        tos   = form.getlist(f"block_{wd}_to[]")
        pairs = []
        for tf, tt in zip(froms, tos):
            tf = (tf or "").strip()
            tt = (tt or "").strip()
            if tf and tt and tf < tt:
                pairs.append((tf, tt))
        if pairs:
            blocks[wd] = pairs
    return blocks


def _sched_save_blocks(schedule_id: int, blocks: dict) -> None:
    """Replace schedule_daily_blocks for schedule_id."""
    db = connect()
    db.execute("DELETE FROM schedule_daily_blocks WHERE schedule_id=?", (schedule_id,))
    for wd, pairs in blocks.items():
        for order, (tf, tt) in enumerate(pairs):
            db.execute(
                "INSERT INTO schedule_daily_blocks "
                "(schedule_id, weekday, time_from, time_to, sort_order) VALUES (?,?,?,?,?)",
                (schedule_id, int(wd), tf, tt, order)
            )
    db.commit()
    db.close()


def _sched_save_exceptions_from_form(sched_id: int, form) -> None:
    """Replace schedule_exceptions for schedule_id from form exc_{wd}_* fields."""
    db = connect()
    db.execute("DELETE FROM schedule_exceptions WHERE schedule_id=?", (sched_id,))
    for wd in range(7):
        exc_froms = form.getlist(f"exc_{wd}_from[]")
        exc_tos   = form.getlist(f"exc_{wd}_to[]")
        exc_weeks = form.getlist(f"exc_{wd}_weeks[]")
        for tf, tt in zip(exc_froms, exc_tos):
            tf = (tf or "").strip()
            tt = (tt or "").strip()
            if tf and tt and exc_weeks:
                db.execute(
                    "INSERT INTO schedule_exceptions "
                    "(schedule_id, weekday, nth_weeks, time_from, time_to) VALUES (?,?,?,?,?)",
                    (sched_id, wd, ",".join(exc_weeks), tf, tt)
                )
    db.commit()
    db.close()


def _sched_daily_blocks_html(sched_id, mode: str,
                              show_checkbox: bool = True,
                              always_visible: bool = False) -> str:
    """Render the Tagesblöcke section for the schedule form."""
    _WD_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    existing: dict[int, list] = {}
    existing_exc: dict[int, list] = {}
    has_blocks = False
    if sched_id:
        try:
            _db = connect()
            rows = _db.execute(
                "SELECT weekday, time_from, time_to FROM schedule_daily_blocks "
                "WHERE schedule_id=? ORDER BY weekday, sort_order",
                (sched_id,)
            ).fetchall()
            exc_rows = []
            try:
                exc_rows = _db.execute(
                    "SELECT weekday, nth_weeks, time_from, time_to FROM schedule_exceptions "
                    "WHERE schedule_id=? ORDER BY weekday, id",
                    (sched_id,)
                ).fetchall()
            except Exception:
                pass
            _db.close()
            for r in rows:
                existing.setdefault(r["weekday"], []).append((r["time_from"], r["time_to"]))
                has_blocks = True
            for r in exc_rows:
                existing_exc.setdefault(r["weekday"], []).append(
                    (r["nth_weeks"], r["time_from"], r["time_to"])
                )
        except Exception:
            pass

    if always_visible or not show_checkbox:
        checked = "checked"
        display = "block"
    else:
        checked = "checked" if has_blocks else ""
        display = "block" if has_blocks else "none"
    _exc_label = t("settings.schedule_exceptions")
    _add_exc_label = t("settings.schedule_add_exception")

    wd_rows = ""
    for wd in range(7):
        blk_html = ""
        _inp = 'background:var(--surface);color:var(--fg);border:1px solid var(--br);border-radius:4px;padding:4px 6px;'
        for tf, tt in existing.get(wd, []):
            blk_html += (
                f'<div class="sdb-row" style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
                f'<input type="time" name="block_{wd}_from[]" value="{tf}" step="900" style="width:100px;{_inp}">'
                f'<span>–</span>'
                f'<input type="time" name="block_{wd}_to[]" value="{tt}" step="900" style="width:100px;{_inp}">'
                f'<button type="button" onclick="this.parentElement.remove()" '
                f'style="background:none;border:none;color:#dc2626;cursor:pointer;font-size:16px;padding:0 4px;">×</button>'
                f'</div>'
            )
        exc_html = ""
        for nth_weeks, etf, ett in existing_exc.get(wd, []):
            weeks_set = nth_weeks.split(",")
            week_checks = "".join(
                f'<label><input type="checkbox" name="exc_{wd}_weeks[]" value="{wn}"'
                f'{" checked" if wn in weeks_set else ""}> {wn}.</label> '
                for wn in ["1", "2", "3", "4", "5"]
            )
            exc_html += (
                f'<div style="display:flex;gap:6px;align-items:center;margin-top:4px;flex-wrap:wrap;">'
                f'<span style="font-size:12px;color:var(--mu);">{_exc_label}:</span> '
                f'{week_checks}'
                f'<input type="time" name="exc_{wd}_from[]" value="{etf}" step="900" style="font-size:13px;{_inp}">'
                f'<span>–</span>'
                f'<input type="time" name="exc_{wd}_to[]" value="{ett}" step="900" style="font-size:13px;{_inp}">'
                f'<button type="button" onclick="this.parentElement.remove()" '
                f'style="color:#dc2626;background:none;border:none;cursor:pointer;">×</button>'
                f'</div>'
            )
        wd_rows += (
            f'<div style="margin-bottom:10px;padding:8px;border-radius:6px;background:var(--surface);">'
            f'<div style="font-size:13px;font-weight:700;color:var(--fg);'
            f'margin-bottom:6px;padding:4px 0;border-bottom:1px solid var(--br);">{_WD_LABELS[wd]}</div>'
            f'<div id="sdb-{wd}">{blk_html}</div>'
            f'<button type="button" onclick="sdbAdd({wd})" '
            f'style="font-size:12px;color:var(--ac);background:none;border:none;cursor:pointer;padding:0;">'
            f'+ {t("settings.schedule_add_block")}</button>'
            f'<div class="sched-exceptions" id="exc-{wd}">{exc_html}</div>'
            f'<button type="button" onclick="addSchedException({wd})" '
            f'style="font-size:12px;color:var(--ac);background:none;border:none;cursor:pointer;padding:0;margin-top:2px;">'
            f'+ {_add_exc_label}</button>'
            f'</div>'
        )

    if show_checkbox:
        _header_html = f"""
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
            <label style="font-weight:600;">
              <input type="checkbox" name="use_daily_blocks" value="1" {checked}
                     id="sdb-toggle"
                     onchange="document.getElementById('sdb-section').style.display=this.checked?'block':'none';">
              {t('settings.schedule_blocks')}
            </label>
            <span class="small" style="color:#777;">{t('settings.schedule_blocks_hint')}</span>
          </div>"""
    else:
        _header_html = f"""
          <input type="hidden" name="use_daily_blocks" value="1">"""

    return f"""
        <div class="card" style="margin-top:12px;">
          {_header_html}
          <div id="sdb-section" style="display:{display};">
            {wd_rows}
          </div>
        </div>
        <script>
        function sdbAdd(wd){{
          var c=document.getElementById('sdb-'+wd);
          var d=document.createElement('div');
          d.className='sdb-row';
          d.style.cssText='display:flex;align-items:center;gap:6px;margin-bottom:4px;';
          var si='width:100px;background:var(--surface);color:var(--fg);border:1px solid var(--br);border-radius:4px;padding:4px 6px;';
          d.innerHTML='<input type="time" name="block_'+wd+'_from[]" step="900" style="'+si+'">'
            +'<span>–</span>'
            +'<input type="time" name="block_'+wd+'_to[]" step="900" style="'+si+'">'
            +'<button type="button" onclick="this.parentElement.remove()" '
            +'style="background:none;border:none;color:#dc2626;cursor:pointer;font-size:16px;padding:0 4px;">×</button>';
          c.appendChild(d);
        }}
        function addSchedException(wd){{
          var container=document.getElementById('exc-'+wd);
          var div=document.createElement('div');
          div.style.cssText='display:flex;gap:6px;align-items:center;margin-top:4px;flex-wrap:wrap;';
          div.innerHTML='<span style="font-size:12px;color:var(--mu);">{_exc_label}:</span> '
            +'<label><input type="checkbox" name="exc_'+wd+'_weeks[]" value="1"> 1.</label> '
            +'<label><input type="checkbox" name="exc_'+wd+'_weeks[]" value="2"> 2.</label> '
            +'<label><input type="checkbox" name="exc_'+wd+'_weeks[]" value="3"> 3.</label> '
            +'<label><input type="checkbox" name="exc_'+wd+'_weeks[]" value="4"> 4.</label> '
            +'<label><input type="checkbox" name="exc_'+wd+'_weeks[]" value="5"> 5.</label> '
            +'<input type="time" name="exc_'+wd+'_from[]" step="900" style="font-size:13px;background:var(--surface);color:var(--fg);border:1px solid var(--br);border-radius:4px;padding:4px 6px;"> '
            +'<span>–</span> '
            +'<input type="time" name="exc_'+wd+'_to[]" step="900" style="font-size:13px;background:var(--surface);color:var(--fg);border:1px solid var(--br);border-radius:4px;padding:4px 6px;"> '
            +'<button type="button" onclick="this.parentElement.remove()" '
            +'style="color:#dc2626;background:none;border:none;cursor:pointer;">×</button>';
          container.appendChild(div);
        }}
        </script>"""


def _sched_form_html(sched, action_url: str, back_url: str, show_auto_breaks: bool = False,
                     auto_breaks_enabled: bool = False, sched_id: int = None) -> str:
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
        <div style="margin-bottom:10px;">
          <label><b>Modus</b></label><br>
          <label><input type="radio" name="mode" value="weekly" {"checked" if mode=="weekly" else ""}
                 onchange="switchSchedModeForm('weekly')"> Wochenarbeitszeit verteilen</label><br>
          <label><input type="radio" name="mode" value="daily_hours" {"checked" if mode=="daily_hours" else ""}
                 onchange="switchSchedModeForm('daily_hours')"> Sollstunden je Wochentag</label><br>
          <label><input type="radio" name="mode" value="daily" {"checked" if mode=="daily" else ""}
                 onchange="switchSchedModeForm('daily')"> {t('onboarding.sched_fixed')}</label>
        </div>
        <div id="sform-weekly" style="">
          <div style="margin-bottom:10px;">
            <label><b>Wochenarbeitszeit (Stunden)</b></label><br>
            <input type="number" name="weekly_hours" min="0" step="0.25" value="{wh}">
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
        <div id="sform-daily-hours" style="display:none;">
          <div class="card" style="background:#fafafa;">
            <h4 style="margin-top:0;">Sollstunden je Wochentag</h4>
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
        </div>
        <div id="sform-daily-blocks" style="display:none;">
          {_sched_daily_blocks_html(sched_id, mode)}
        </div>
        <div style="margin-top:12px;display:flex;gap:8px;">
          <button class="btn primary" type="submit">Speichern</button>
          <a class="btn" href="{_html.escape(back_url)}">Abbrechen</a>
        </div>
      </form>
      <script>
      function switchSchedModeForm(m){{
        document.getElementById('sform-weekly').style.display = m==='weekly' ? '' : 'none';
        document.getElementById('sform-daily-hours').style.display = m==='daily_hours' ? '' : 'none';
        document.getElementById('sform-daily-blocks').style.display = m==='daily' ? '' : 'none';
      }}
      switchSchedModeForm('{mode}');
      </script>"""


def _get_user_holiday_region(user_id=None) -> str:
    if user_id:
        try:
            db = connect()
            row = db.execute("SELECT holiday_region FROM users WHERE id=?", (user_id,)).fetchone()
            db.close()
            if row and row["holiday_region"]:
                return row["holiday_region"]
        except Exception:
            pass
    cfg = _get_app_config()
    return cfg.get("default_holiday_region") or "DE-NW"


def _is_holiday(iso_day: str, user_id=None) -> bool:
    try:
        region = _get_user_holiday_region(user_id)
        db = connect()
        r = db.execute(
            "SELECT is_holiday FROM calendar_days WHERE day=? AND region=?",
            (iso_day, region),
        ).fetchone()
        db.close()
        return bool(r and int(r["is_holiday"]) == 1)
    except Exception:
        return False


def _get_team_holiday_region(plan_id: int) -> str:
    try:
        db = connect()
        row = db.execute("""
            SELECT t.holiday_region
            FROM staffing_plans sp
            JOIN teams t ON t.id = sp.team_id
            WHERE sp.id = ?
        """, (plan_id,)).fetchone()
        db.close()
        if row and row["holiday_region"]:
            return row["holiday_region"]
    except Exception:
        pass
    cfg = _get_app_config()
    return cfg.get("default_holiday_region") or "DE-NW"


def _is_holiday_for_plan(iso_day: str, plan_id: int) -> bool:
    try:
        region = _get_team_holiday_region(plan_id)
        db = connect()
        r = db.execute(
            "SELECT is_holiday FROM calendar_days "
            "WHERE day=? AND region=?",
            (iso_day, region)
        ).fetchone()
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

_PW_STRENGTH_JS = r"""<script>
function _pwChk(pw,uname){
  return{len:pw.length>=10,upper:/[A-Z]/.test(pw),lower:/[a-z]/.test(pw),
    digit:/[0-9]/.test(pw),special:/[^a-zA-Z0-9\s]/.test(pw),
    nouser:!uname||pw.toLowerCase().indexOf(uname.toLowerCase())<0};
}
function _pwUpdate(iid,lid,uname){
  var pw=(document.getElementById(iid)||{}).value||'';
  var el=document.getElementById(lid);if(!el)return;
  var c=_pwChk(pw,uname);
  var required=[[c.len,'Mindestens 10 Zeichen'],[c.upper,'Großbuchstabe (A-Z)'],
    [c.lower,'Kleinbuchstabe (a-z)'],[c.digit,'Zahl (0-9)']];
  if(uname)required.push([c.nouser,'Kein Benutzernamen enthalten']);
  var html=required.map(function(x){
    var col=x[0]?'var(--ok)':'var(--danger)';
    return '<span style="display:block;color:'+col+';font-size:12px;">'+(x[0]?'✓ ':'✗ ')+x[1]+'</span>';
  }).join('');
  var scol=c.special?'var(--ok)':'var(--muted,#888)';
  var smark=c.special?'✓ ':'○ ';
  html+='<span style="display:block;color:'+scol+';font-size:12px;">'+smark+'Sonderzeichen (optional, empfohlen)</span>';
  el.innerHTML=html;
}
</script>"""


def _generate_password() -> str:
    import secrets
    import string
    upper = string.ascii_uppercase
    lower = string.ascii_lowercase
    digits = string.digits
    specials = "!@#$%^&*()-_=+"
    pw = [secrets.choice(upper), secrets.choice(lower), secrets.choice(digits), secrets.choice(specials)]
    pool = upper + lower + digits + specials
    pw += [secrets.choice(pool) for _ in range(8)]
    for i in range(len(pw) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        pw[i], pw[j] = pw[j], pw[i]
    return "".join(pw)


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
    _region = _get_user_holiday_region(user_id)
    db = connect()
    try:
        hol_days = {
            str(r["day"])[:10]
            for r in db.execute(
                "SELECT day FROM calendar_days WHERE day BETWEEN ? AND ? AND is_holiday=1 AND region=?",
                (year_start, yesterday, _region),
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
        return t("flash.error.before_start_date").format(date=_fmt_date_de(start))
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

def _calc_retirement(user_id: int):
    db = connect()
    try:
        row = db.execute("SELECT birth_date, retirement_age FROM users WHERE id=?", (user_id,)).fetchone()
    finally:
        db.close()
    if not row or not row["birth_date"]:
        return None
    try:
        bd = datetime.date.fromisoformat(row["birth_date"])
    except (ValueError, TypeError):
        return None
    age = int(row["retirement_age"] or 67)
    try:
        ret_date = bd.replace(year=bd.year + age)
    except ValueError:
        ret_date = bd.replace(year=bd.year + age, day=28)
    today = datetime.date.today()
    delta = ret_date - today
    cal_days = delta.days
    if cal_days <= 0:
        return {"retired": True, "retirement_date": ret_date.isoformat(), "age": age}
    weeks = cal_days // 7
    # count remaining full years and months
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
    remaining_days = (ret_date - d).days
    full_weeks = cal_days // 7
    extra = cal_days % 7
    start_dow = today.weekday()
    net_workdays = full_weeks * 5
    for i in range(extra):
        if (start_dow + i) % 7 < 5:
            net_workdays += 1
    return {
        "retired": False,
        "retirement_date": ret_date.isoformat(),
        "age": age,
        "cal_days": cal_days,
        "weeks": weeks,
        "years": years,
        "months": months,
        "days": remaining_days,
        "net_workdays": net_workdays,
    }





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
    try:
        _rdb = connect()
        _rrow = _rdb.execute("SELECT balance_rollover FROM users WHERE id=?", (user_id,)).fetchone()
        _rdb.close()
        _rollover = (_rrow["balance_rollover"] or "manual") if _rrow else "manual"
    except Exception:
        _rollover = "manual"
    running = 0 if _rollover == "forfeit" else int(start_minutes)
    today_iso = datetime.date.today().isoformat()
    flextag_ranges = _fetch_flextag_ranges(user_id)

    for iso in _iter_days(year_start, end_iso):
        expected = int(_expected_minutes_for_day(user_id, iso) or 0)
        actual = int(_actual_minutes_for_day(user_id, iso) or 0)
        flextag_min = 0
        if iso < today_iso and expected == 0 and _is_flextag(iso, flextag_ranges):
            flextag_min = _scheduled_minutes_ignoring_absence(user_id, iso)
        running += int(actual - expected - flextag_min)

    # Manuelle Korrekturen einrechnen
    try:
        _db_adj = connect()
        _adj = _db_adj.execute(
            "SELECT COALESCE(SUM(minutes),0) AS total FROM balance_adjustments "
            "WHERE user_id=? AND adjustment_date BETWEEN ? AND ?",
            (user_id, year_start, end_iso)
        ).fetchone()
        _db_adj.close()
        running += int(_adj["total"] or 0)
    except Exception:
        pass

    return int(running)




# -------------------------
# Abwesenheiten (NEU v2.4.0)
# -------------------------

def _validate_absence_dates(date_from: str, date_to: str, is_half_day: int):
    if not date_from or not date_to:
        return t("flash.error.absence_date_required")
    if date_from > date_to:
        return t("flash.error.absence_date_order")
    if is_half_day and date_from != date_to:
        return t("flash.error.absence_half_day")
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


FIXED_REMARKS: list[str] = []  # Flextag and Verdi are now dedicated absence types

MONTH_NAMES_DE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
                  "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _t_month(n: int) -> str:
    return t(f"month.{n}")


def _t_month_short(n: int) -> str:
    return t(f"month.short.{n}")

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


def _fmt_iso_short(iso_val) -> str:
    try:
        return datetime.date.fromisoformat(str(iso_val)[:10]).strftime("%d.%m.%Y")
    except Exception:
        return str(iso_val)








def _notify_absence_decision(user_id: int, email: str, lang: str, type_name: str, date_from: str, date_to: str, approved: bool, reason: str) -> None:
    """Background thread: mail + Telegram to requester after approve/reject."""
    import threading as _thr
    def _do():
        try:
            with app.app_context():
                if email:
                    if approved:
                        subj = t("mail.absence_approved_subject", lang)
                        body = t("mail.absence_approved_body", lang).format(
                            type=type_name, from_date=date_from, to_date=date_to
                        )
                    else:
                        subj = t("mail.absence_rejected_subject", lang)
                        body = t("mail.absence_rejected_body", lang).format(
                            type=type_name, from_date=date_from, to_date=date_to, reason=reason
                        )
                    try:
                        _send_mail_simple(email, subj, body)
                    except Exception as e:
                        app.logger.error(f"Decision-Mail Fehler: {e}")
                tg_msg = (
                    f"✅ Dein {type_name} vom {date_from} bis {date_to} wurde genehmigt."
                    if approved else
                    f"❌ Dein {type_name} vom {date_from} bis {date_to} wurde abgelehnt: {reason}"
                )
                _send_tg_message(user_id, tg_msg)
        except Exception as e:
            app.logger.error(f"Decision notification Fehler: {e}")
    _thr.Thread(target=_do, daemon=True).start()








# ── iCal / Kalender-Export ─────────────────────────────────────────────────

_ICAL_TYPE_MAP = {
    "urlaub":  "Urlaub",
    "krank":   "Krank",
    "flextag": "Flextag",
    "sonstige":"Sonstige",
}

def _ical_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


# ── iCloud Sync ────────────────────────────────────────────────────────────────

def _icloud_encrypt(text: str) -> str:
    import base64, hashlib
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(app.secret_key.encode()).digest())
    return Fernet(key).encrypt(text.encode()).decode()


def _icloud_decrypt(token: str) -> str:
    import base64, hashlib
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(app.secret_key.encode()).digest())
    return Fernet(key).decrypt(token.encode()).decode()


def _icloud_update_sync_time(user_id: int) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    db = connect()
    db.execute("UPDATE users SET icloud_last_sync=? WHERE id=?", (ts, user_id))
    db.commit()
    db.close()


def _sync_to_icloud(user_id: int, absence_id: int, action: str) -> None:
    """Sync a single absence to iCloud. action: 'create'|'update'|'delete'. Never raises."""
    try:
        import caldav as _caldav_lib
        db = connect()
        urow = db.execute(
            "SELECT icloud_enabled, icloud_apple_id, icloud_app_password, "
            "icloud_calendar_name, calendar_export_prefix, language FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not urow or not int(urow["icloud_enabled"] or 0):
            db.close()
            return
        apple_id = (urow["icloud_apple_id"] or "").strip()
        enc_pw   = (urow["icloud_app_password"] or "").strip()
        cal_name = (urow["icloud_calendar_name"] or "").strip()
        prefix   = (urow["calendar_export_prefix"] or "").strip()
        lang     = urow["language"] or "en"
        if not apple_id or not enc_pw or not cal_name:
            db.close()
            return
        password = _icloud_decrypt(enc_pw)
        uid      = f"zeiterfassung-{user_id}-{absence_id}@ustrike"

        if action == "delete":
            db.close()
            ical_str = None
        else:
            abrow = db.execute(
                "SELECT a.date_from, a.date_to, a.comment, at.name AS type_name "
                "FROM absences a JOIN absence_types at ON a.type_id=at.id "
                "WHERE a.id=? AND a.user_id=?",
                (absence_id, user_id),
            ).fetchone()
            db.close()
            if not abrow:
                return
            _lmap = {
                "Urlaub":   t("absence_type.urlaub",   lang=lang),
                "Krank":    t("absence_type.krank",     lang=lang),
                "Flextag":  t("absence_type.flextag",   lang=lang),
                "Sonstige": t("absence_type.sonstige",  lang=lang),
            }
            type_name = abrow["type_name"] or ""
            remark    = (abrow["comment"] or "").strip()
            label     = remark if (type_name == "Sonstige" and remark) else _lmap.get(type_name, type_name)
            summary   = f"{prefix} {label}".strip() if prefix else label
            try:
                dtend = (datetime.date.fromisoformat(abrow["date_to"]) + datetime.timedelta(days=1)).strftime("%Y%m%d")
            except Exception:
                dtend = abrow["date_to"].replace("-", "") + "01"
            dtstart  = abrow["date_from"].replace("-", "")
            dtstamp  = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            desc     = _ical_escape(remark) if remark else ""
            ev_lines = [
                "BEGIN:VCALENDAR", "VERSION:2.0",
                "PRODID:-//Zeiterfassung//DE", "CALSCALE:GREGORIAN",
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTART;VALUE=DATE:{dtstart}",
                f"DTEND;VALUE=DATE:{dtend}",
                f"SUMMARY:{_ical_escape(summary)}",
                f"DTSTAMP:{dtstamp}",
                "STATUS:CONFIRMED", "TRANSP:TRANSPARENT",
            ]
            if desc:
                ev_lines.append(f"DESCRIPTION:{desc}")
            ev_lines += ["END:VEVENT", "END:VCALENDAR"]
            ical_str = "\r\n".join(ev_lines) + "\r\n"

        client    = _caldav_lib.DAVClient(url="https://caldav.icloud.com", username=apple_id, password=password, timeout=10)
        principal = client.principal()
        cal       = next((c for c in principal.calendars() if c.name == cal_name), None)
        if not cal:
            app.logger.warning("iCloud: calendar '%s' not found for user %s", cal_name, user_id)
            return

        if action == "delete":
            try:
                import httpx as _httpx
                # Bypass event_by_uid (REPORT) and caldav DELETE (If-Match) — both cause 412 on iCloud.
                # save_event() puts events at {cal.url}/{uid}.ics, so we can construct the URL directly.
                event_url = str(cal.url).rstrip("/") + "/" + uid + ".ics"
                _resp = _httpx.delete(event_url, auth=(apple_id, password), timeout=10)
                if _resp.status_code not in (200, 204, 404):
                    raise Exception(f"iCloud DELETE HTTP {_resp.status_code}: {_resp.text[:200]}")
            except Exception as _del_e:
                app.logger.error("iCloud DELETE Fehler: %s", _del_e)
        elif action == "create":
            cal.save_event(ical_str)
        elif action == "update":
            try:
                ev = cal.event_by_uid(uid)
                ev.data = ical_str
                ev.save()
            except Exception:
                cal.save_event(ical_str)

        _icloud_update_sync_time(user_id)
    except Exception:
        app.logger.exception("iCloud sync error: user=%s absence=%s action=%s", user_id, absence_id, action)


def _build_ical_for_user(user_id: int, lang: str, period: str = "all") -> str:
    import uuid as _uuid
    db = connect()
    row = db.execute(
        "SELECT username, display_name, calendar_export_types, calendar_export_prefix FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if not row:
        db.close()
        return ""
    username       = row["username"] or ""
    display_name   = row["display_name"] or username
    export_types   = (row["calendar_export_types"] or "urlaub,krank,flextag").split(",")
    prefix         = (row["calendar_export_prefix"] or "").strip()

    # map chosen keys to DB type names
    wanted_names = {_ICAL_TYPE_MAP[k] for k in export_types if k in _ICAL_TYPE_MAP}

    # date filter
    today = datetime.date.today()
    if period == "year":
        date_filter = f" AND date_from >= '{today.year}-01-01' AND date_to <= '{today.year}-12-31'"
    else:
        date_filter = ""

    absences = db.execute(
        f"SELECT a.id, a.date_from, a.date_to, a.comment, at.name as type_name "
        f"FROM absences a JOIN absence_types at ON a.type_id=at.id "
        f"WHERE a.user_id=?{date_filter} ORDER BY a.date_from",
        (user_id,),
    ).fetchall()
    db.close()

    cal_name = f"{t('calendar.cal_name', lang=lang)} {display_name}"

    _type_label = {
        "Urlaub":  t("absence_type.urlaub",  lang=lang),
        "Krank":   t("absence_type.krank",   lang=lang),
        "Flextag": t("absence_type.flextag", lang=lang),
        "Sonstige":t("absence_type.sonstige",lang=lang),
    }

    events = []
    for ab in absences:
        type_name = ab["type_name"] or ""
        if type_name not in wanted_names:
            continue
        remark = (ab["comment"] or "").strip()

        # SUMMARY: prefix + translated type (or remark for Sonstige)
        if type_name == "Sonstige" and remark:
            label = remark
        else:
            label = _type_label.get(type_name, type_name)
        summary = f"{prefix} {label}".strip() if prefix else label

        # DTEND is exclusive (date + 1 day)
        try:
            dtend = (datetime.date.fromisoformat(ab["date_to"]) + datetime.timedelta(days=1)).strftime("%Y%m%d")
        except Exception:
            dtend = ab["date_to"].replace("-", "") + "01"  # fallback

        dtstart = ab["date_from"].replace("-", "")
        uid = f"{user_id}-{ab['id']}@zeiterfassung"
        desc = _ical_escape(remark) if remark else ""

        ev = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART;VALUE=DATE:{dtstart}",
            f"DTEND;VALUE=DATE:{dtend}",
            f"SUMMARY:{_ical_escape(summary)}",
            "STATUS:CONFIRMED",
            "TRANSP:TRANSPARENT",
        ]
        if desc:
            ev.append(f"DESCRIPTION:{desc}")
        ev.append("END:VEVENT")
        events.append("\r\n".join(ev))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Zeiterfassung//DE",
        f"X-WR-CALNAME:{_ical_escape(cal_name)}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    lines.extend(events)
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"




def _ical_response(user_id: int, lang: str):
    from flask import Response as _Resp
    ical_data = _build_ical_for_user(user_id, lang)
    resp = _Resp(ical_data, status=200)
    resp.headers["Content-Type"]                = "text/calendar; charset=utf-8"
    resp.headers["Content-Disposition"]         = "inline"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"]               = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"]                      = "no-cache"
    return resp




# ---------------------------
# CalDAV (Home Assistant)
# ---------------------------



def _caldav_unauth():
    from flask import make_response as _mr
    r = _mr("Unauthorized", 401)
    r.headers["WWW-Authenticate"] = 'Basic realm="Zeiterfassung CalDAV"'
    return r


def _caldav_xml_resp(xml: str, status: int = 207):
    from flask import Response as _Resp
    r = _Resp(xml, status=status)
    r.headers["Content-Type"] = "application/xml; charset=utf-8"
    r.headers["DAV"]          = "1, 2, calendar-access"
    r.headers["Allow"]        = "GET, HEAD, PROPFIND, REPORT, OPTIONS"
    return r


def _caldav_options():
    from flask import Response as _Resp
    r = _Resp("", status=204)
    r.headers["DAV"]   = "1, 2, calendar-access"
    r.headers["Allow"] = "GET, HEAD, PROPFIND, REPORT, OPTIONS"
    return r


def _cdx(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _caldav_user_by_token(token: str):
    db = connect()
    row = db.execute(
        "SELECT id, username, display_name, language FROM users WHERE calendar_token=? AND is_active=1",
        (token,),
    ).fetchone()
    db.close()
    return dict(row) if row else None


def _caldav_user_by_basic():
    auth = request.authorization
    if not auth:
        return None, _caldav_unauth()
    u, _auth_err = authenticate(auth.username, auth.password)
    if not u or _auth_err:
        return None, _caldav_unauth()
    db = connect()
    row = db.execute(
        "SELECT id, username, display_name, language FROM users WHERE id=? AND is_active=1",
        (u["id"],),
    ).fetchone()
    db.close()
    return (dict(row), None) if row else (None, _caldav_unauth())


def _caldav_propfind_principal(href: str, user: dict) -> str:
    dn = _cdx(user.get("display_name") or user.get("username") or "")
    h  = _cdx(href)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">\n'
        '  <response>\n'
        f'    <href>{h}</href>\n'
        '    <propstat>\n'
        '      <prop>\n'
        '        <resourcetype><principal/><collection/></resourcetype>\n'
        f'        <displayname>{dn}</displayname>\n'
        f'        <C:calendar-home-set><href>{h}</href></C:calendar-home-set>\n'
        '      </prop>\n'
        '      <status>HTTP/1.1 200 OK</status>\n'
        '    </propstat>\n'
        '  </response>\n'
        '</multistatus>'
    )


def _caldav_propfind_calendar(href: str, user: dict, lang: str) -> str:
    dn    = user.get("display_name") or user.get("username") or ""
    cname = _cdx(f"{t('calendar.cal_name', lang=lang)} {dn}")
    cdesc = _cdx(t("calendar.cal_name", lang=lang))
    h     = _cdx(href)
    import time as _time
    ctag  = str(int(_time.time()))
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"'
        ' xmlns:CS="http://calendarserver.org/ns/">\n'
        '  <response>\n'
        f'    <href>{h}</href>\n'
        '    <propstat>\n'
        '      <prop>\n'
        '        <resourcetype><collection/><C:calendar/></resourcetype>\n'
        f'        <displayname>{cname}</displayname>\n'
        f'        <C:calendar-description>{cdesc}</C:calendar-description>\n'
        '        <C:supported-calendar-component-set>\n'
        '          <C:comp name="VEVENT"/>\n'
        '        </C:supported-calendar-component-set>\n'
        f'        <CS:getctag>{ctag}</CS:getctag>\n'
        '      </prop>\n'
        '      <status>HTTP/1.1 200 OK</status>\n'
        '    </propstat>\n'
        '  </response>\n'
        '</multistatus>'
    )


def _caldav_absences(user_id: int):
    db = connect()
    row = db.execute(
        "SELECT calendar_export_types, calendar_export_prefix FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if not row:
        db.close()
        return [], set(), ""
    export_types = (row["calendar_export_types"] or "urlaub,krank,flextag").split(",")
    prefix       = (row["calendar_export_prefix"] or "").strip()
    wanted       = {_ICAL_TYPE_MAP[k] for k in export_types if k in _ICAL_TYPE_MAP}
    abs_rows = db.execute(
        "SELECT a.id, a.date_from, a.date_to, a.comment, at.name AS type_name "
        "FROM absences a JOIN absence_types at ON a.type_id=at.id "
        "WHERE a.user_id=? ORDER BY a.date_from",
        (user_id,),
    ).fetchall()
    db.close()
    return [dict(r) for r in abs_rows], wanted, prefix


def _caldav_vevent(ab: dict, user_id: int, prefix: str, lmap: dict, wanted: set) -> str:
    tn = ab.get("type_name") or ""
    if tn not in wanted:
        return ""
    remark  = (ab.get("comment") or "").strip()
    label   = remark if (tn == "Sonstige" and remark) else lmap.get(tn, tn)
    summary = (f"{prefix} {label}".strip() if prefix else label)
    try:
        dtend = (datetime.date.fromisoformat(ab["date_to"]) + datetime.timedelta(days=1)).strftime("%Y%m%d")
    except Exception:
        dtend = ab["date_to"].replace("-", "") + "01"
    dtstart = ab["date_from"].replace("-", "")
    uid  = f"{user_id}-{ab['id']}@zeiterfassung"
    desc = _ical_escape(remark) if remark else ""
    ev = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART;VALUE=DATE:{dtstart}",
        f"DTEND;VALUE=DATE:{dtend}",
        f"SUMMARY:{_ical_escape(summary)}",
        "STATUS:CONFIRMED",
        "TRANSP:TRANSPARENT",
    ]
    if desc:
        ev.append(f"DESCRIPTION:{desc}")
    ev.append("END:VEVENT")
    return "\r\n".join(ev)


def _caldav_report(cal_href: str, user: dict, lang: str) -> str:
    absences, wanted, prefix = _caldav_absences(user["id"])
    lmap = {
        "Urlaub":   t("absence_type.urlaub",   lang=lang),
        "Krank":    t("absence_type.krank",     lang=lang),
        "Flextag":  t("absence_type.flextag",   lang=lang),
        "Sonstige": t("absence_type.sonstige",  lang=lang),
    }
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<multistatus xmlns="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">',
    ]
    for ab in absences:
        vevent = _caldav_vevent(ab, user["id"], prefix, lmap, wanted)
        if not vevent:
            continue
        ev_href = _cdx(f"{cal_href}{user['id']}-{ab['id']}.ics")
        vcal = _cdx(
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Zeiterfassung//DE\r\n"
            "CALSCALE:GREGORIAN\r\n"
            f"{vevent}\r\n"
            "END:VCALENDAR\r\n"
        )
        parts += [
            "  <response>",
            f"    <href>{ev_href}</href>",
            "    <propstat>",
            f"      <prop><C:calendar-data>{vcal}</C:calendar-data></prop>",
            "      <status>HTTP/1.1 200 OK</status>",
            "    </propstat>",
            "  </response>",
        ]
    parts.append("</multistatus>")
    return "\n".join(parts)


def _caldav_single_ical(user: dict, lang: str, filename: str) -> "str | None":
    parts = filename.replace(".ics", "").rsplit("-", 1)
    if len(parts) != 2:
        return None
    try:
        ab_id = int(parts[1])
    except ValueError:
        return None
    absences, wanted, prefix = _caldav_absences(user["id"])
    lmap = {
        "Urlaub":   t("absence_type.urlaub",   lang=lang),
        "Krank":    t("absence_type.krank",     lang=lang),
        "Flextag":  t("absence_type.flextag",   lang=lang),
        "Sonstige": t("absence_type.sonstige",  lang=lang),
    }
    for ab in absences:
        if ab["id"] == ab_id:
            vevent = _caldav_vevent(ab, user["id"], prefix, lmap, wanted)
            if not vevent:
                return None
            return (
                "BEGIN:VCALENDAR\r\n"
                "VERSION:2.0\r\n"
                "PRODID:-//Zeiterfassung//DE\r\n"
                "CALSCALE:GREGORIAN\r\n"
                f"{vevent}\r\n"
                "END:VCALENDAR\r\n"
            )
    return None


def _caldav_do_principal(user: dict, href: str):
    m = request.method.upper()
    if m == "OPTIONS":
        return _caldav_options()
    if m == "PROPFIND":
        return _caldav_xml_resp(_caldav_propfind_principal(href, user))
    from flask import Response as _Resp
    r = _Resp("", status=200)
    r.headers["DAV"]   = "1, 2, calendar-access"
    r.headers["Allow"] = "GET, HEAD, PROPFIND, OPTIONS"
    return r


def _caldav_do_calendar(user: dict, href: str, lang: str):
    m = request.method.upper()
    if m == "OPTIONS":
        return _caldav_options()
    if m == "PROPFIND":
        return _caldav_xml_resp(_caldav_propfind_calendar(href, user, lang))
    if m == "REPORT":
        return _caldav_xml_resp(_caldav_report(href, user, lang))
    from flask import Response as _Resp
    ical = _build_ical_for_user(user["id"], lang)
    r = _Resp(ical, status=200)
    r.headers["Content-Type"] = "text/calendar; charset=utf-8"
    r.headers["DAV"]          = "1, 2, calendar-access"
    r.headers["Allow"]        = "GET, HEAD, PROPFIND, REPORT, OPTIONS"
    return r


def _caldav_do_event(user: dict, lang: str, filename: str):
    ical = _caldav_single_ical(user, lang, filename)
    if not ical:
        abort(404)
    from flask import Response as _Resp
    r = _Resp(ical, status=200)
    r.headers["Content-Type"] = "text/calendar; charset=utf-8"
    r.headers["DAV"] = "1, 2, calendar-access"
    return r



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
        return False, t("flash.error.time_format")
    s = _minutes_from_hhmm(time_in)
    e = _minutes_from_hhmm(time_out)
    if e <= s:
        return False, t("flash.error.time_order")
    if break_minutes < 0:
        return False, t("flash.error.break_negative")
    if break_minutes >= (e - s):
        return False, t("flash.error.break_too_large")
    return True, ""


def _exception_banner(day: str, is_blocked_day: bool, exc_row, locked: bool) -> str:
    if not is_blocked_day:
        return ""
    if exc_row is not None:
        note = exc_row["note"] or ""
        note_part = f" &ndash; <i style='font-weight:400;'>{note}</i>" if note else ""
        remove_btn = "" if locked else (
            f"<form method='post' action='/api/remove-exception' style='display:contents;'>"
            f"<input type='hidden' name='day' value='{day}'>"
            f"<button class='btn danger btn-sm' type='submit'>Entfernen</button></form>"
        )
        return (
            f"<div class='exc-banner exc-ok'>"
            f"<span style='flex:1;min-width:0;'>⚡ <b>Ausnahme aktiv</b>{note_part}"
            f"<span class='exc-sub'>Zeitblöcke an diesem Wochenende/Feiertag sind erlaubt.</span></span>"
            f"{remove_btn}</div>"
        )
    set_form = "" if locked else (
        f"<form method='post' action='/api/set-exception' style='display:flex;gap:6px;align-items:center;flex-wrap:wrap;'>"
        f"<input type='hidden' name='day' value='{day}'>"
        f"<input name='note' placeholder='Grund (optional)' style='font-size:13px;padding:4px 8px;width:160px;'>"
        f"<button class='btn primary btn-sm' type='submit'>Ausnahme setzen</button>"
        f"</form>"
    )
    return (
        f"<div class='exc-banner exc-warn'>"
        f"<span style='flex:1;min-width:0;'>⚠ <b>Wochenende / Feiertag</b>"
        f"<span class='exc-sub'>Ausnahme erforderlich, um Zeitblöcke zu erfassen.</span></span>"
        f"{set_form}</div>"
    )


def _business_trip_section_compact(day: str, trip, locked: bool = False) -> str:
    """Compact Dienstreise card for the redesigned day editor."""
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
        delete_btn = (
            f"<form method='post' action='/day/{day}/business_trip/delete' style='display:contents;'"
            f" onsubmit=\"return confirm('Dienstreise löschen?');\">"
            f"<input type='hidden' name='trip_id' value='{trip_id}'>"
            f"<button class='btn danger btn-sm' type='submit'>Löschen</button></form>"
        )

    hdr_label = "Dienstreise bearbeiten" if trip else "Dienstreise hinzufügen"
    if locked:
        hdr_label = "Dienstreise (schreibgeschützt)"

    inner = "" if locked else f"""
      <form method="post" action="/day/{day}/business_trip/save">
        <input type="hidden" name="trip_id" value="{trip_id}">
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-bottom:8px;">
          <div class="tb-field" style="flex:1;min-width:160px;">
            <label>Ort *</label>
            <input name="destination" required value="{dest}" placeholder="Reiseziel" style="font-size:13px;padding:5px 8px;">
          </div>
          <div class="tb-field">
            <label>Startdatum *</label>
            {_date_input("start_date", start_iso, required=True)}
          </div>
          <div class="tb-field" style="justify-content:flex-end;padding-bottom:6px;">
            <label style="font-weight:400;font-size:13px;"><input type="checkbox" onchange="toggleMultiday(this)" {multi_checked}> Mehrtägig</label>
          </div>
        </div>
        <div class="multiday-fields" style="display:{multi_display};margin-bottom:8px;">
          <div class="tb-field" style="display:inline-flex;">
            <label>Enddatum</label>
            {_date_input("end_date", end_iso if is_multi else "")}
          </div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
          <div class="tb-field"><label>Abreise</label>{_time_input("departure_time", dep)}</div>
          <div class="tb-field"><label>Am Ziel</label>{_time_input("departure_end_time", dep_e)}</div>
          <div class="tb-field"><label>Rückreise</label>{_time_input("return_time", ret)}</div>
          <div class="tb-field"><label>Zuhause</label>{_time_input("return_end_time", ret_e)}</div>
        </div>
        <div style="margin-bottom:8px;">
          <textarea name="notes" rows="2" placeholder="Notizen (optional)" style="font-size:13px;padding:5px 8px;">{notes}</textarea>
        </div>
        <div style="display:flex;gap:6px;">
          <button class="btn primary btn-sm" type="submit">Dienstreise speichern</button>
          <div style="display:contents;">{delete_btn}</div>
        </div>
      </form>"""

    if locked and trip:
        inner = (
            f"<div style='font-size:13px;'><b>{dest}</b> · {_fmt_date_de(start_iso)}"
            f"{' – ' + _fmt_date_de(end_iso) if is_multi else ''}</div>"
            f"<div class='small' style='color:var(--mu);margin-top:4px;'>🔒 Schreibgeschützt</div>"
        )
    elif locked:
        inner = "<div class='day-empty'>Keine Dienstreise / gesperrt.</div>"

    return (
        f"<div class='day-sec-hdr'>✈ {hdr_label}</div>"
        f"<div class='day-sec-body'>{inner}</div>"
    )


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


def _render_calendar_integration_section(
    cal_system: str,
    cal_types: "list[str]",
    cal_prefix: str,
    cal_token: str,
    webcal_url: str,
    ical_url: str,
    cal_auth_mode: str = "token",
    basic_webcal_url: str = "",
    basic_ical_url: str = "",
    caldav_token_url: str = "",
    caldav_basic_url: str = "",
) -> str:
    lang = session.get("lang", "en")

    # Radio buttons for calendar system
    def _sys_radio(val: str, lbl: str) -> str:
        chk = "checked" if cal_system == val else ""
        return (f"<label style='display:flex;align-items:center;gap:6px;margin-bottom:6px;cursor:pointer;'>"
                f"<input type='radio' name='calendar_system' value='{val}' {chk}> {lbl}</label>")

    # Radio buttons for auth mode
    def _auth_radio(val: str, lbl: str) -> str:
        chk = "checked" if cal_auth_mode == val else ""
        return (f"<label style='display:flex;align-items:center;gap:6px;margin-bottom:6px;cursor:pointer;'>"
                f"<input type='radio' name='calendar_auth_mode' value='{val}' {chk}> {lbl}</label>")

    # Checkboxes for absence types
    def _type_cb(key: str, lbl: str) -> str:
        chk = "checked" if key in cal_types else ""
        return (f"<label style='display:flex;align-items:center;gap:6px;margin-bottom:4px;cursor:pointer;'>"
                f"<input type='checkbox' name='type_{key}' value='1' {chk}> {lbl}</label>")

    # Preview text
    _prefix_escaped = _html.escape(cal_prefix)
    _preview_label  = _html.escape(t("absence_type.urlaub", lang=lang))
    _preview_text   = f"{_prefix_escaped} {_preview_label}".strip() if cal_prefix else _preview_label

    # Instructions per system
    _instructions = {
        "apple":   t("settings.calendar_instructions_apple",   lang=lang),
        "google":  t("settings.calendar_instructions_google",  lang=lang),
        "outlook": t("settings.calendar_instructions_outlook", lang=lang),
        "ical":    "",
    }.get(cal_system, "")

    _copy_lbl    = _html.escape(t("btn.copy", lang=lang))
    _dl_url_year = "/absences/export/calendar?period=year"
    _dl_url_all  = "/absences/export/calendar?period=all"

    # URL block — depends on auth mode
    if cal_auth_mode == "basic":
        _primary_url   = basic_webcal_url if cal_system == "apple" else basic_ical_url
        _secondary_url = basic_ical_url
        _caldav_url    = caldav_basic_url
        _ics_block = f"""
        <div class="acc-sub">
          <b style="font-size:13px;">{t('settings.calendar_token_label')}</b>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap;">
            <input id="cal-sub-url" type="text" value="{_html.escape(_primary_url)}" readonly
                   style="flex:1;min-width:200px;font-size:12px;font-family:monospace;">
            <button class="btn btn-sm" type="button"
                    onclick="navigator.clipboard.writeText(document.getElementById('cal-sub-url').value)">{_copy_lbl}</button>
          </div>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap;">
            <input id="cal-sub-url2" type="text" value="{_html.escape(_secondary_url)}" readonly
                   style="flex:1;min-width:200px;font-size:12px;font-family:monospace;">
            <button class="btn btn-sm" type="button"
                    onclick="navigator.clipboard.writeText(document.getElementById('cal-sub-url2').value)">{_copy_lbl}</button>
          </div>
          <div class="small" style="color:var(--mu);margin-top:4px;">{_html.escape(t('settings.calendar_auth_basic_hint', lang=lang))}</div>
          <div class="small" style="color:var(--mu);margin-top:4px;">{_html.escape(t('settings.calendar_ha_hint', lang=lang))}</div>
        </div>"""
    else:
        _sub_url   = webcal_url if cal_system == "apple" else ical_url
        _caldav_url = caldav_token_url
        _ics_block = ""
        if _sub_url:
            _ics_block = f"""
        <div class="acc-sub">
          <b style="font-size:13px;">{t('settings.calendar_token_label')}</b>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap;">
            <input id="cal-sub-url" type="text" value="{_html.escape(_sub_url)}" readonly
                   style="flex:1;min-width:200px;font-size:12px;font-family:monospace;">
            <button class="btn btn-sm" type="button"
                    onclick="navigator.clipboard.writeText(document.getElementById('cal-sub-url').value)">{_copy_lbl}</button>
          </div>
          <div class="small" style="color:var(--mu);margin-top:4px;">{t('settings.calendar_subscribe_hint')}</div>
          <form method="post" action="/settings/calendar/reset-token" style="margin-top:10px;"
                onsubmit="return confirm('{_html.escape(t('settings.calendar_token_reset_warning'))}');">
            <button class="btn btn-sm danger" type="submit">{t('settings.calendar_token_reset')}</button>
          </form>
        </div>"""

    _caldav_block = ""
    if _caldav_url:
        _caldav_block = f"""
        <div class="acc-sub">
          <b style="font-size:13px;">{_html.escape(t('settings.calendar_caldav_url', lang=lang))}</b>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap;">
            <input id="cal-caldav-url" type="text" value="{_html.escape(_caldav_url)}" readonly
                   style="flex:1;min-width:200px;font-size:12px;font-family:monospace;">
            <button class="btn btn-sm" type="button"
                    onclick="navigator.clipboard.writeText(document.getElementById('cal-caldav-url').value)">{_copy_lbl}</button>
          </div>
          <div class="small" style="color:var(--mu);margin-top:4px;">{_html.escape(t('settings.calendar_caldav_hint', lang=lang))}</div>
        </div>"""

    _url_block = _ics_block + _caldav_block

    _instr_html = f"<p class='small' style='color:var(--mu);margin-bottom:10px;'>{_html.escape(_instructions)}</p>" if _instructions else ""

    return f"""
    <div class="acc" id="acc-cal-int">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-cal-int-body')">
        <span>{t('settings.calendar_integration')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-cal-int-body">
        <div class="acc-inner">
          <form method="post" action="/settings/calendar">

            <div class="acc-sub" style="margin-top:0;padding-top:0;border-top:none;">
              <b style="font-size:13px;display:block;margin-bottom:8px;">{t('settings.calendar_system')}</b>
              {_sys_radio('apple',   t('settings.calendar_apple'))}
              {_sys_radio('google',  t('settings.calendar_google'))}
              {_sys_radio('outlook', t('settings.calendar_outlook'))}
              {_sys_radio('ical',    t('settings.calendar_other'))}
            </div>

            <div class="acc-sub">
              <b style="font-size:13px;display:block;margin-bottom:8px;">{t('settings.calendar_auth_mode')}</b>
              {_auth_radio('token', t('settings.calendar_auth_none',  lang=lang))}
              {_auth_radio('basic', t('settings.calendar_auth_basic', lang=lang))}
            </div>

            <div class="acc-sub">
              <b style="font-size:13px;display:block;margin-bottom:8px;">{t('settings.calendar_entry_settings')}</b>
              <div style="margin-bottom:10px;">
                <label>{t('settings.calendar_prefix')}</label>
                <input type="text" name="calendar_export_prefix" value="{_prefix_escaped}"
                       maxlength="20" style="width:200px;margin-top:4px;" placeholder="ZE: ">
                <div class="small" style="color:var(--mu);margin-top:3px;">{t('settings.calendar_prefix_hint')}</div>
                <div class="small" style="margin-top:4px;">
                  <b>{t('settings.calendar_prefix_preview')}</b> {_html.escape(_preview_text)}
                </div>
              </div>
              <div>
                <label style="display:block;margin-bottom:6px;">{t('settings.calendar_export_types')}</label>
                {_type_cb('urlaub',  t('absence_type.urlaub',  lang=lang))}
                {_type_cb('krank',   t('absence_type.krank',   lang=lang))}
                {_type_cb('flextag', t('absence_type.flextag', lang=lang))}
                {_type_cb('sonstige',t('absence_type.sonstige',lang=lang))}
              </div>
            </div>

            <div class="acc-sub" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              <button class="btn btn-sm" type="submit">{t('common.save')}</button>
            </div>
          </form>

          <div class="acc-sub">
            <b style="font-size:13px;display:block;margin-bottom:8px;">{t('settings.calendar_export')}</b>
            {_instr_html}
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
              <a class="btn btn-sm" href="{_dl_url_year}">{t('settings.calendar_download')} ({t('settings.calendar_period_year')})</a>
              <a class="btn btn-sm" href="{_dl_url_all}">{t('settings.calendar_download')} ({t('settings.calendar_period_all')})</a>
            </div>
          </div>

          {_url_block}
        </div>
      </div>
    </div>"""


def _render_security_accordion(u: dict, totp_enabled: bool) -> str:
    _totp_status = t('settings.two_factor_enabled') if totp_enabled else t('settings.two_factor_disabled')
    _totp_color  = "var(--ok)" if totp_enabled else "var(--mu)"
    _last_login  = (u.get("last_login") or "")[:16].replace("T", " ")
    _attempts    = int(u.get("login_attempts") or 0)
    _attempts_color = "var(--danger)" if _attempts > 0 else "var(--ok)"

    _totp_section = f"""
      <div class="acc-sub">
        <b style="font-size:14px;">{t('settings.two_factor')}</b>
        <div style="margin-top:8px;">
          <span style="color:{_totp_color};font-weight:600;">{_totp_status}</span>
        </div>
        {"" if not totp_enabled else f'''
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
          <form method="post" action="/settings/2fa/backup-codes">
            <button class="btn btn-sm" type="submit">{t('settings.regenerate_backup_codes')}</button>
          </form>
          <form method="post" action="/settings/2fa/disable"
                onsubmit="return confirm('{t('settings.totp_disable_confirm')}');">
            <button class="btn danger btn-sm" type="submit">{t('settings.disable_2fa')}</button>
          </form>
        </div>'''}
        {"" if totp_enabled else f'''
        <div style="margin-top:10px;">
          <a class="btn btn-sm primary" href="/settings/2fa/enable">{t('settings.enable_2fa')}</a>
        </div>'''}
        <p class="small" style="color:var(--mu);margin-top:6px;">{t('settings.backup_codes_hint')}</p>
      </div>
      <div class="acc-sub">
        <b style="font-size:14px;">{t('settings.login_activity')}</b>
        <div style="margin-top:8px;font-size:13px;">
          <div>{t('settings.last_login')}: <b>{_last_login or "–"}</b></div>
          <div style="margin-top:4px;">{t('settings.failed_attempts')}: <span style="color:{_attempts_color};font-weight:600;">{_attempts}</span></div>
        </div>
      </div>
    """

    return f"""
    <div class="acc" id="acc-security">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-security-body')">
        <span>&#128274; {t('settings.security')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-security-body">
        <div class="acc-inner">
          <div class="acc-sub" style="border-top:none;margin-top:0;padding-top:0;">
            <b style="font-size:14px;">{t('settings.pw_section')}</b>
            <form method="post" action="/settings/password" style="display:flex;flex-direction:column;gap:10px;max-width:400px;margin-top:10px;">
              <div>
                <label>{t('settings.password_old')}</label><br>
                <input type="password" name="current_password" required autocomplete="current-password">
              </div>
              <div>
                <label>{t('settings.password_new')}</label><br>
                <input type="password" name="new_password" id="spw-inp" required autocomplete="new-password" minlength="6"
                       oninput="_pwUpdate('spw-inp','spw-chk','{_html.escape(u.get('username') or '')}')">
                <div id="spw-chk" style="margin-top:6px;padding:8px;background:var(--sf);border-radius:var(--rs);border:1px solid var(--bd);line-height:1.7;"></div>
              </div>
              <div>
                <label>{t('settings.pw_confirm_repeat')}</label><br>
                <input type="password" name="new_password_confirm" required autocomplete="new-password">
              </div>
              <div><button class="btn" type="submit">{t('btn.change_pw')}</button></div>
            </form>
          </div>
          {_totp_section}
        </div>
      </div>
    </div>
    {_PW_STRENGTH_JS}
    """


# ── iCloud Einstellungen ───────────────────────────────────────────────────────

def _render_icloud_settings_section(
    ic_enabled: bool,
    ic_apple_id: str,
    ic_has_pw: bool,
    ic_cal_name: str,
    ic_last_sync: str,
) -> str:
    lang = session.get("lang", "en")
    chk  = "checked" if ic_enabled else ""
    _pw_placeholder = "••••••••" if ic_has_pw else ""
    _pw_keep_note   = (f"<div class='small' style='color:var(--mu);margin-top:3px;'>"
                       f"{_html.escape(t('settings.icloud_pw_keep', lang=lang))}</div>") if ic_has_pw else ""
    _last_sync_html = ""
    if ic_last_sync:
        _last_sync_html = (f"<div class='small' style='color:var(--mu);margin-top:6px;'>"
                           f"{_html.escape(t('settings.icloud_last_sync', lang=lang))}: "
                           f"{_html.escape(ic_last_sync)}</div>")
    _t_test     = _html.escape(t("settings.icloud_test",     lang=lang))
    _t_sync_all = _html.escape(t("settings.icloud_sync_all", lang=lang))
    return f"""
    <div class="acc" id="acc-icloud">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-icloud-body')">
        <span>{t('settings.icloud_integration')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-icloud-body">
        <div class="acc-inner">
          <form method="post" action="/settings/icloud">
            <div class="acc-sub" style="margin-top:0;padding-top:0;border-top:none;">
              <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-bottom:10px;">
                <input type="checkbox" name="icloud_enabled" value="1" {chk}>
                <span>{_html.escape(t('settings.icloud_enabled', lang=lang))}</span>
              </label>
              <div style="display:flex;flex-direction:column;gap:10px;max-width:420px;">
                <div>
                  <label>{_html.escape(t('settings.icloud_apple_id', lang=lang))}</label><br>
                  <input type="email" name="icloud_apple_id" value="{_html.escape(ic_apple_id)}"
                         placeholder="name@icloud.com" autocomplete="off" data-lpignore="true"
                         style="width:100%;margin-top:4px;">
                </div>
                <div>
                  <label>{_html.escape(t('settings.icloud_app_password', lang=lang))}</label><br>
                  <input type="password" name="icloud_app_password" value=""
                         placeholder="{_pw_placeholder}" autocomplete="new-password" data-lpignore="true"
                         style="width:100%;margin-top:4px;">
                  {_pw_keep_note}
                  <div class="small" style="color:var(--mu);margin-top:3px;">
                    {_html.escape(t('settings.icloud_app_password_hint', lang=lang))}
                  </div>
                </div>
                <div>
                  <label>{_html.escape(t('settings.icloud_calendar_name', lang=lang))}</label><br>
                  <input type="text" name="icloud_calendar_name" value="{_html.escape(ic_cal_name)}"
                         placeholder="Familie" style="width:100%;margin-top:4px;">
                  <div class="small" style="color:var(--mu);margin-top:3px;">
                    {_html.escape(t('settings.icloud_calendar_hint', lang=lang))}
                  </div>
                </div>
              </div>
            </div>
            <div class="acc-sub" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              <button class="btn btn-sm" type="submit">{t('common.save')}</button>
            </div>
          </form>
          <div class="acc-sub">
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              <button class="btn btn-sm" type="button" id="icloud-test-btn"
                      onclick="icloudTest()">{_t_test}</button>
              <button class="btn btn-sm" type="button" id="icloud-sync-btn"
                      onclick="icloudSyncAll()">{_t_sync_all}</button>
            </div>
            <div id="icloud-action-result" style="margin-top:8px;font-size:13px;"></div>
            {_last_sync_html}
          </div>
        </div>
      </div>
    </div>
    <script>
    function icloudTest(){{
      var btn=document.getElementById('icloud-test-btn');
      var res=document.getElementById('icloud-action-result');
      btn.disabled=true; res.textContent='…';
      fetch('/settings/icloud/test')
        .then(r=>r.json())
        .then(d=>{{
          if(d.ok){{ res.style.color='var(--ok)'; res.textContent=d.message; }}
          else{{ res.style.color='var(--err,#c00)'; res.textContent=d.error; }}
        }})
        .catch(e=>{{ res.style.color='var(--err,#c00)'; res.textContent=''+e; }})
        .finally(()=>{{ btn.disabled=false; }});
    }}
    function icloudSyncAll(){{
      var btn=document.getElementById('icloud-sync-btn');
      var res=document.getElementById('icloud-action-result');
      btn.disabled=true; res.textContent='…';
      fetch('/settings/icloud/sync-all',{{method:'POST',headers:{{'X-Requested-With':'XMLHttpRequest'}}}})
        .then(r=>r.json())
        .then(d=>{{
          if(d.ok){{ res.style.color='var(--ok)'; res.textContent=d.message; }}
          else{{ res.style.color='var(--err,#c00)'; res.textContent=d.error; }}
        }})
        .catch(e=>{{ res.style.color='var(--err,#c00)'; res.textContent=''+e; }})
        .finally(()=>{{ btn.disabled=false; }});
    }}
    </script>"""






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


def _build_csv_bytes(headers: list, data: list, delimiter: str = ";") -> bytes:
    import csv
    from io import StringIO
    buf = StringIO()
    w = csv.writer(buf, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
    w.writerow(headers)
    w.writerows(data)
    return buf.getvalue().encode("utf-8-sig")


def _get_mail_config() -> dict:
    """Read SMTP config from mail_config table, falling back to env vars."""
    import os
    db = connect()
    rows = db.execute("SELECT key, value FROM mail_config").fetchall()
    db.close()
    cfg = {r["key"]: (r["value"] or "") for r in rows}
    # Env var fallback for any key not set in DB
    defaults = {
        "mail_server":   os.environ.get("MAIL_SERVER", ""),
        "mail_port":     os.environ.get("MAIL_PORT", "587"),
        "mail_username": os.environ.get("MAIL_USERNAME", ""),
        "mail_password": os.environ.get("MAIL_PASSWORD", ""),
        "mail_from":     os.environ.get("MAIL_FROM", ""),
    }
    for k, v in defaults.items():
        if not cfg.get(k):
            cfg[k] = v
    return cfg


def _save_mail_config(server: str, port: str, username: str, password: str, from_addr: str, update_password: bool) -> None:
    db = connect()
    now = "datetime('now')"
    for key, val in [
        ("mail_server",   server),
        ("mail_port",     port),
        ("mail_username", username),
        ("mail_from",     from_addr),
    ]:
        db.execute(
            "UPDATE mail_config SET value=?, updated_at=datetime('now') WHERE key=?",
            (val, key),
        )
    if update_password:
        db.execute(
            "UPDATE mail_config SET value=?, updated_at=datetime('now') WHERE key='mail_password'",
            (password,),
        )
    db.commit()
    db.close()


_MAIL_PW_PLACEHOLDER = "••••••••"


# ── Backup helpers ─────────────────────────────────────────────────────────────

def _get_backup_config() -> dict:
    db = connect()
    try:
        rows = db.execute("SELECT key, value FROM backup_config").fetchall()
    except Exception:
        rows = []
    finally:
        db.close()
    return {r["key"]: r["value"] for r in rows}


def _save_backup_config(enabled: bool, backup_time: str,
                        auto_encrypt_enabled: bool = False,
                        auto_encrypt_password: str = "") -> None:
    db = connect()
    try:
        db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('auto_backup_enabled',?,datetime('now'))", ("1" if enabled else "0",))
        db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('auto_backup_time',?,datetime('now'))", (backup_time,))
        db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('auto_encrypt_enabled',?,datetime('now'))", ("1" if auto_encrypt_enabled else "0",))
        if auto_encrypt_password:
            from backup import encrypt_password as _enc_pw
            _secret = app.secret_key
            db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('auto_encrypt_password',?,datetime('now'))", (_enc_pw(auto_encrypt_password, _secret),))
        elif not auto_encrypt_enabled:
            db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('auto_encrypt_password',?,datetime('now'))", ("",))
        db.commit()
    finally:
        db.close()


def _record_last_backup() -> None:
    db = connect()
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('last_backup_time',?,datetime('now'))", (now,))
        db.commit()
    finally:
        db.close()


def _fmt_backup_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    return f"{n/1024/1024:.1f} MB"


# ── Bot-Config helpers ─────────────────────────────────────────────────────────

def _get_bot_config() -> dict:
    db = connect()
    try:
        rows = db.execute("SELECT key, value FROM bot_config").fetchall()
    except Exception:
        rows = []
    finally:
        db.close()
    return {r["key"]: r["value"] for r in rows}


def _save_bot_config(token: str, api_key: str, admin_ids: str) -> None:
    db = connect()
    try:
        for key, val in (("bot_token", token), ("anthropic_api_key", api_key), ("admin_telegram_ids", admin_ids)):
            db.execute(
                "INSERT OR REPLACE INTO bot_config(key,value,updated_at) VALUES(?,?,datetime('now'))",
                (key, val),
            )
        db.commit()
    finally:
        db.close()


# ── System helpers ─────────────────────────────────────────────────────────────

def _bot_service_status() -> str:
    import subprocess
    try:
        r = subprocess.run(["systemctl", "is-active", "zeiterfassung-bot"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return "unknown"


def _bot_service_exists() -> bool:
    return os.path.exists("/etc/systemd/system/zeiterfassung-bot.service")


_GIT_REMOTE_URL = "https://github.com/Ustrike69/Zeiterfassung.git"


def _git_pending_commits() -> "list[str] | None | str":
    import subprocess
    project = os.path.dirname(os.path.abspath(__file__))
    try:
        subprocess.run(
            ["git", "-C", project, "remote", "set-url", "origin", _GIT_REMOTE_URL],
            capture_output=True, timeout=5,
        )
        r_fetch = subprocess.run(
            ["git", "-C", project, "fetch", "origin", "main"],
            capture_output=True, text=True, timeout=20,
        )
        if r_fetch.returncode != 0:
            err = r_fetch.stderr.strip() or r_fetch.stdout.strip() or "fetch failed"
            return f"ERROR:{err}"
        r = subprocess.run(
            ["git", "-C", project, "log", "HEAD..origin/main", "--oneline"],
            capture_output=True, text=True, timeout=5,
        )
        lines = [ln.strip() for ln in r.stdout.strip().splitlines() if ln.strip()]
        return lines
    except Exception as e:
        return f"ERROR:{e}"


def _git_last_commit_info() -> str:
    import subprocess
    try:
        r = subprocess.run(
            ["git", "-C", "/opt/zeiterfassung", "log", "-1",
             "--format=%h  %s  (%cd)", "--date=format:%d.%m.%Y %H:%M"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip()
    except Exception:
        return "–"


def _service_started_at(name: str) -> str:
    import subprocess
    try:
        r = subprocess.run(
            ["systemctl", "show", name, "--property=ActiveEnterTimestamp"],
            capture_output=True, text=True, timeout=5,
        )
        val = r.stdout.strip().replace("ActiveEnterTimestamp=", "").strip()
        return val or "–"
    except Exception:
        return "–"


def _run_update() -> "tuple[bool, list[str]]":
    import subprocess
    project = os.path.dirname(os.path.abspath(__file__))
    out = []

    # Remote URL setzen
    subprocess.run(
        ["git", "-C", project, "remote", "set-url", "origin", _GIT_REMOTE_URL],
        capture_output=True, timeout=5,
    )

    # Lokale Änderungen stashen (verhindert Pull-Fehler)
    r_stash = subprocess.run(
        ["git", "-C", project, "stash", "--include-untracked"],
        capture_output=True, text=True, timeout=10,
    )
    stashed = "No local changes" not in r_stash.stdout
    if stashed:
        out.append(f"git stash: {r_stash.stdout.strip()}")

    # Pull
    r1 = subprocess.run(
        ["git", "-C", project, "pull", "origin", "main"],
        capture_output=True, text=True, timeout=60,
    )
    out.append("git pull:")
    out.append(r1.stdout.strip() or r1.stderr.strip() or "(keine Ausgabe)")

    if r1.returncode != 0:
        # Stash wiederherstellen wenn Pull fehlschlug
        if stashed:
            subprocess.run(
                ["git", "-C", project, "stash", "pop"],
                capture_output=True, timeout=10,
            )
        return False, out

    # Pip install
    r2 = subprocess.run(
        [f"{project}/.venv/bin/pip", "install", "-r",
         f"{project}/requirements.txt", "-q"],
        capture_output=True, text=True, timeout=120,
    )
    out.append("pip install:")
    msg = r2.stdout.strip()
    if r2.stderr.strip():
        msg += ("\n" if msg else "") + r2.stderr.strip()
    out.append(msg or "(keine neuen Pakete)")
    return r2.returncode == 0, out


def _send_mail(to: str, subject: str, body_text: str, attachment_name: str, attachment_bytes: bytes) -> None:
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders

    cfg = _get_mail_config()
    server    = cfg.get("mail_server", "")
    port      = int(cfg.get("mail_port") or "587")
    username  = cfg.get("mail_username", "")
    password  = cfg.get("mail_password", "")
    from_addr = cfg.get("mail_from") or username

    if not server or not username:
        raise RuntimeError("SMTP nicht konfiguriert (Mailserver / Benutzername fehlt).")
    if not password:
        raise RuntimeError("SMTP-Passwort nicht konfiguriert.")

    msg = MIMEMultipart()
    msg["From"]    = from_addr
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    part = MIMEBase("text", "csv")
    part.set_payload(attachment_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
    msg.attach(part)

    with smtplib.SMTP(server, port, timeout=10) as s:
        s.ehlo()
        s.starttls()
        s.login(username, password)
        s.sendmail(username, [to], msg.as_string())


def _send_mail_simple(to: str, subject: str, body_text: str) -> None:
    import smtplib
    from email.mime.text import MIMEText as _MIMEText
    cfg = _get_mail_config()
    server    = cfg.get("mail_server", "")
    port      = int(cfg.get("mail_port") or "587")
    username  = cfg.get("mail_username", "")
    password  = cfg.get("mail_password", "")
    from_addr = cfg.get("mail_from") or username
    if not server or not username:
        raise RuntimeError("SMTP nicht konfiguriert.")
    if not password:
        raise RuntimeError("SMTP-Passwort nicht konfiguriert.")
    msg = _MIMEText(body_text, "plain", "utf-8")
    from_header = f"{from_addr} <{username}>" if from_addr and "@" not in from_addr else (from_addr or username)
    msg["From"]    = from_header
    msg["To"]      = to
    msg["Subject"] = subject
    with smtplib.SMTP(server, port, timeout=10) as s:
        s.ehlo()
        s.starttls()
        s.login(username, password)
        s.sendmail(username, [to], msg.as_string())


def _send_tg_message(user_id: int, text: str) -> None:
    """Send a Telegram message to a user (fire-and-forget). Uses bot token from bot_config."""
    import threading as _thr
    def _do():
        try:
            import urllib.request as _ur
            import urllib.parse as _up
            db = connect()
            cfg = db.execute("SELECT key, value FROM bot_config").fetchall()
            tg_row = db.execute("SELECT telegram_id FROM telegram_users WHERE user_id=?", (user_id,)).fetchone()
            db.close()
            token = next((r["value"] for r in cfg if r["key"] == "bot_token"), None)
            if not token or not tg_row:
                return
            chat_id = tg_row["telegram_id"]
            data = _up.urlencode({"chat_id": chat_id, "text": text}).encode()
            _ur.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=10)
        except Exception as e:
            app.logger.warning(f"TG-Nachricht Fehler für user {user_id}: {e}")
    _thr.Thread(target=_do, daemon=True).start()


def _send_approval_request_mail(absence_id: int, requester: dict, type_name: str, date_from: str, date_to: str, approver_id: int) -> None:
    """Send approval request email to approver in a background thread."""
    import threading as _thr
    def _do():
        try:
            with app.app_context():
                db = connect()
                apr = db.execute("SELECT email, language, display_name, username FROM users WHERE id=?", (approver_id,)).fetchone()
                db.close()
                if not apr or not apr["email"]:
                    app.logger.warning(f"Approval-Mail: Genehmiger {approver_id} hat keine E-Mail")
                    return
                lang = (apr["language"] or "de")
                requester_name = requester.get("display_name") or requester.get("username", "?")
                base_url = _get_base_url()
                url = f"{base_url}/admin"
                body = t("mail.approval_request_body", lang).format(
                    name=requester_name,
                    type=type_name,
                    from_date=date_from,
                    to_date=date_to,
                    url=url,
                )
                _send_mail_simple(apr["email"], t("mail.approval_request_subject", lang), body)
                app.logger.info(f"Approval-Mail gesendet an {apr['email']} für Abwesenheit {absence_id}")
                # Telegram notification to approver
                base_url = _get_base_url()
                tg_text = (
                    f"📋 {requester_name} beantragt {type_name} "
                    f"{date_from} – {date_to}.\n"
                    f"Zur Genehmigung: {base_url}/approvals"
                )
                _send_tg_message(approver_id, tg_text)
        except Exception as e:
            app.logger.error(f"Approval-Mail Fehler: {e}")
    _thr.Thread(target=_do, daemon=True).start()


def _build_rich_day_export(user_id: int, date_from: str, date_to: str):
    """Build day-by-day export matching balance view: Wochentag|Datum|Beginn|Ende|Pause|Soll|Delta|Bemerkung."""
    _WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    db = connect()
    blocks_raw = db.execute(
        "SELECT day, time_in, time_out, break_minutes FROM time_blocks "
        "WHERE user_id=? AND day BETWEEN ? AND ? ORDER BY day, time_in",
        (user_id, date_from, date_to),
    ).fetchall()
    absences_raw = db.execute(
        "SELECT a.date_from, a.date_to, t.name AS type_name, a.comment "
        "FROM absences a JOIN absence_types t ON t.id=a.type_id "
        "WHERE a.user_id=? AND NOT (a.date_to < ? OR a.date_from > ?)",
        (user_id, date_from, date_to),
    ).fetchall()
    _export_region = _get_user_holiday_region(user_id)
    holidays_raw = db.execute(
        "SELECT day, holiday_name FROM calendar_days WHERE is_holiday=1 AND region=? AND day BETWEEN ? AND ?",
        (_export_region, date_from, date_to),
    ).fetchall()
    trips_raw = db.execute(
        "SELECT start_date, end_date, destination FROM business_trips "
        "WHERE user_id=? AND start_date <= ? AND (end_date >= ? OR end_date IS NULL)",
        (user_id, date_to, date_from),
    ).fetchall()
    db.close()

    # Build lookup maps
    blocks_by_day: dict = {}
    for b in blocks_raw:
        blocks_by_day.setdefault(b["day"], []).append(dict(b))

    absence_map: dict = {}
    for a in absences_raw:
        d0 = datetime.date.fromisoformat(a["date_from"])
        d1 = datetime.date.fromisoformat(a["date_to"])
        cur = d0
        while cur <= d1:
            iso = cur.isoformat()
            if date_from <= iso <= date_to:
                absence_map.setdefault(iso, (a["type_name"], a["comment"] or ""))
            cur += datetime.timedelta(days=1)

    holiday_map: dict = {str(h["day"])[:10]: h["holiday_name"] or "" for h in holidays_raw}

    trip_map: dict = {}
    for t in trips_raw:
        sd = t["start_date"][:10]
        ed = (t["end_date"] or sd)[:10]
        cur = datetime.date.fromisoformat(max(sd, date_from))
        end = datetime.date.fromisoformat(min(ed, date_to))
        while cur <= end:
            trip_map[cur.isoformat()] = t["destination"]
            cur += datetime.timedelta(days=1)

    headers = ["Wochentag", "Datum", "Beginn", "Ende", "Pause (min)", "Soll", "Delta", "Bemerkung"]
    data = []
    total_actual = 0

    for iso in _iter_days(date_from, date_to):
        d = datetime.date.fromisoformat(iso)
        wd = _WD[d.weekday()]
        datum = f"{d.day:02d}.{d.month:02d}.{d.year}"

        expected = _expected_minutes_for_day(user_id, iso)
        soll_str = _fmt_minutes(expected) if expected else ""

        # Build Bemerkung
        parts = []
        if iso in holiday_map and holiday_map[iso]:
            parts.append(holiday_map[iso])
        if iso in absence_map:
            atype, acomment = absence_map[iso]
            parts.append(acomment if (atype == "Sonstige" and acomment) else atype)
        if iso in trip_map:
            parts.append(f"Dienstreise: {trip_map[iso]}")
        bemerkung = " | ".join(parts)

        day_blocks = blocks_by_day.get(iso, [])

        if not day_blocks:
            if expected or bemerkung:
                delta_str = _fmt_minutes_signed(-expected) if expected else ""
                data.append([wd, datum, "", "", "", soll_str, delta_str, bemerkung])
        else:
            actual_total = sum(
                _minutes_from_hhmm(b["time_out"]) - _minutes_from_hhmm(b["time_in"]) - int(b["break_minutes"] or 0)
                for b in day_blocks
            )
            total_actual += actual_total
            delta = actual_total - expected
            delta_str = _fmt_minutes_signed(delta)

            for i, b in enumerate(day_blocks):
                brk = int(b["break_minutes"] or 0)
                if i == 0:
                    data.append([wd, datum, b["time_in"], b["time_out"], brk,
                                 soll_str, delta_str, bemerkung])
                else:
                    data.append(["", "", b["time_in"], b["time_out"], brk, "", "", ""])

    return headers, data, total_actual


def _build_time_blocks_export(user_id: int, date_from: str, date_to: str):
    """Legacy simple export — delegates to rich export."""
    headers, data, total = _build_rich_day_export(user_id, date_from, date_to)
    return headers, data, total



# ─── Periodenabschluss-Verwaltung ────────────────────────────────────────────








# -------------------------
# Admin: Benutzer
# -------------------------



# ─── Admin: Zeitschema bearbeiten / löschen ──────────────────────────────────

def _render_backup_section() -> str:
    from backup import list_local_backups
    cfg = _get_backup_config()
    last_ts = cfg.get("last_backup_time") or ""
    auto_on = cfg.get("auto_backup_enabled", "0") == "1"
    auto_time = cfg.get("auto_backup_time") or "02:00"
    auto_checked = "checked" if auto_on else ""
    auto_enc_on = cfg.get("auto_encrypt_enabled", "0") == "1"
    auto_enc_checked = "checked" if auto_enc_on else ""
    auto_enc_pw_set = bool(cfg.get("auto_encrypt_password", ""))

    # Local full backups list
    backups = list_local_backups()
    backup_rows = ""
    for b in backups:
        safe = b["name"].replace("'", "\\'")
        mtime_str = b["mtime"].strftime("%d.%m.%Y %H:%M")
        size_str = _fmt_backup_size(b["size"])
        enc_badge = " <span style='font-size:10px;color:#6366f1;font-weight:600;'>🔒</span>" if b.get("encrypted") else ""
        backup_rows += (
            f"<tr>"
            f"<td style='font-size:12px;'>{mtime_str}</td>"
            f"<td style='font-size:12px;'>{size_str}</td>"
            f"<td style='font-size:12px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--mu);'>{b['name']}{enc_badge}</td>"
            f"<td style='white-space:nowrap;'>"
            f"<a class='btn btn-sm' href='/admin/backup/local/{b['name']}'>&#11123;</a>"
            f"<form method='post' action='/admin/backup/delete/{b['name']}' style='display:inline;margin-left:4px;'"
            f" onsubmit=\"return confirm('Backup {safe} löschen?')\">"
            f"<button class='btn danger btn-sm' type='submit'>✕</button></form>"
            f"</td>"
            f"</tr>"
        )
    if not backup_rows:
        backup_rows = f"<tr><td colspan='4' style='color:var(--mu);font-size:13px;'>{t('admin.backup_none_local')}</td></tr>"

    # Users for export/import dropdowns
    _db = connect()
    _all_users = _db.execute(
        "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY username"
    ).fetchall()
    _db.close()
    user_export_opts = "".join(
        f'<option value="{u["id"]}">{u["display_name"] or u["username"]}</option>'
        for u in _all_users
    )
    user_import_opts = "".join(
        f'<option value="{u["id"]}">{u["display_name"] or u["username"]}</option>'
        for u in _all_users
    )

    _auto_enc_pw_hint = f" <span style='color:var(--mu);font-size:11px;'>({t('settings.saved')})</span>" if auto_enc_pw_set else ""
    _restore_confirm = t('admin.backup_restore_confirm')
    return f"""
    <div class="acc" data-tab="system" id="acc-backup">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-backup-body')">
        <span>{t('admin.acc_backup')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-backup-body">
        <div class="acc-inner">

          <!-- ── 1. Vollständiges Backup ── -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.backup_full_title')}</div>
          <p class="small" style="color:var(--mu);margin-bottom:10px;">{t('admin.backup_full_hint')}</p>

          <!-- Download-Formular mit optionaler Verschlüsselung -->
          <form method="post" action="/admin/backup/download" style="margin-bottom:12px;">
            <div style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap;margin-bottom:8px;">
              <div>
                <label style="font-size:13px;font-weight:400;display:flex;align-items:center;gap:6px;">
                  <input type="checkbox" id="dl-enc-toggle" name="encrypt" value="1"
                         onchange="bkDlToggle()"> {t('backup.encrypt')}
                </label>
              </div>
              <div class="small" style="color:var(--mu);padding-top:3px;">
                {t('admin.backup_last') + " <b>" + last_ts + "</b>" if last_ts else t('admin.backup_none')}
              </div>
            </div>
            <div id="dl-enc-fields" style="display:none;margin-bottom:8px;background:var(--sf);border:1px solid var(--bd);border-radius:var(--rs);padding:10px;">
              <p class="small" style="color:#6366f1;margin-bottom:8px;">&#128274; {t('backup.encrypt_hint')}</p>
              <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <div>
                  <label style="font-size:12px;">{t('backup.password')}</label><br>
                  <input type="password" name="password" id="dl-enc-pw" autocomplete="new-password"
                         style="font-size:13px;padding:4px 8px;width:180px;">
                </div>
                <div>
                  <label style="font-size:12px;">{t('backup.password_confirm')}</label><br>
                  <input type="password" name="password_confirm" id="dl-enc-pw2" autocomplete="new-password"
                         style="font-size:13px;padding:4px 8px;width:180px;">
                </div>
              </div>
            </div>
            <button class="btn primary btn-sm" type="submit">&#11015; {t('admin.backup_download_btn')}</button>
          </form>

          <!-- Auto-Backup + Auto-Verschlüsselung -->
          <form method="post" action="/admin/backup/auto-config" style="margin-bottom:12px;">
            <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
              <label style="font-size:13px;font-weight:400;display:flex;align-items:center;gap:6px;">
                <input type="checkbox" name="auto_enabled" value="1" {auto_checked}> {t('admin.backup_auto')}
              </label>
              <div>
                <label style="font-size:12px;">{t('common.time')}</label>
                <input type="time" name="auto_time" value="{auto_time}" style="font-size:13px;padding:4px 8px;width:110px;">
              </div>
            </div>
            <div style="margin-top:8px;">
              <label style="font-size:13px;font-weight:400;display:flex;align-items:center;gap:6px;">
                <input type="checkbox" id="auto-enc-toggle" name="auto_encrypt_enabled" value="1"
                       {auto_enc_checked} onchange="autoEncToggle()"> {t('backup.auto_encrypt')}
              </label>
            </div>
            <div id="auto-enc-fields" style="display:{'block' if auto_enc_on else 'none'};margin-top:8px;background:var(--sf);border:1px solid var(--bd);border-radius:var(--rs);padding:10px;">
              <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <div>
                  <label style="font-size:12px;">{t('backup.auto_encrypt_password')}{_auto_enc_pw_hint}</label><br>
                  <input type="password" name="auto_encrypt_password" autocomplete="new-password"
                         placeholder="{'••••••••' if auto_enc_pw_set else ''}"
                         style="font-size:13px;padding:4px 8px;width:180px;">
                </div>
                <div>
                  <label style="font-size:12px;">{t('backup.password_confirm')}</label><br>
                  <input type="password" name="auto_encrypt_password_confirm" autocomplete="new-password"
                         style="font-size:13px;padding:4px 8px;width:180px;">
                </div>
              </div>
            </div>
            <div style="margin-top:8px;">
              <button class="btn btn-sm" type="submit">{t('btn.save')}</button>
            </div>
            <p class="small" style="margin-top:6px;color:var(--mu);">{t('admin.backup_keep_hint')}</p>
          </form>

          <!-- Restore -->
          <div style="font-size:13px;font-weight:600;margin-bottom:6px;">{t('admin.backup_restore_title')}</div>
          <form method="post" action="/admin/backup/restore" enctype="multipart/form-data"
                onsubmit="return confirm('{_restore_confirm}');" id="restore-form">
            <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:6px;">
              <div>
                <label style="font-size:12px;">{t('admin.backup_file_label')} / {t('backup.encrypted_file')}</label>
                <input type="file" name="backup_file" accept=".db,.db.gz,.gz,.enc"
                       required style="font-size:13px;display:block;margin-top:2px;"
                       onchange="restoreEncDetect(this)">
              </div>
              <button class="btn danger btn-sm" type="submit">&#11014; {t('btn.import')}</button>
            </div>
            <div id="restore-enc-field" style="display:none;margin-bottom:6px;">
              <label style="font-size:12px;">&#128274; {t('backup.password')}</label><br>
              <input type="password" name="enc_password" id="restore-enc-pw"
                     style="font-size:13px;padding:4px 8px;width:200px;" autocomplete="current-password">
            </div>
          </form>
          <p class="small" style="color:var(--mu);margin-bottom:12px;">{t('admin.backup_restore_hint')}</p>

          <!-- Lokale Backups Liste -->
          <div style="font-size:13px;font-weight:600;margin-bottom:6px;">{t('admin.backup_local_title')} ({len(backups)})</div>
          <div class="table-scroll" style="margin-bottom:0;">
            <table>
              <thead><tr><th>{t('common.date')}</th><th>{t('admin.backup_size')}</th><th>{t('admin.backup_filename')}</th><th></th></tr></thead>
              <tbody>{backup_rows}</tbody>
            </table>
          </div>

          <hr style="margin:20px 0;">

          <!-- ── 2. Einstellungen-Backup ── -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.backup_settings_title')}</div>
          <p class="small" style="color:var(--mu);margin-bottom:10px;">{t('admin.backup_settings_hint')}</p>
          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;">
            <a class="btn btn-sm" href="/admin/backup/settings/export">&#11015; {t('admin.backup_settings_export_btn')}</a>
          </div>
          <div style="font-size:13px;font-weight:600;margin-bottom:6px;">{t('admin.backup_settings_import_title')}</div>
          <form method="post" action="/admin/backup/settings/import" enctype="multipart/form-data">
            <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:6px;">
              <div>
                <label style="font-size:12px;">{t('admin.backup_settings_file_label')}</label>
                <input type="file" name="settings_file" accept=".json" required style="font-size:13px;">
              </div>
              <button class="btn btn-sm" type="submit">&#11014; {t('btn.import')}</button>
            </div>
          </form>
          <p class="small" style="color:var(--mu);">{t('admin.backup_settings_import_hint')}</p>

        </div>
      </div>
    </div>
<script>
function bkDlToggle(){{
  var on=document.getElementById('dl-enc-toggle').checked;
  document.getElementById('dl-enc-fields').style.display=on?'block':'none';
  var pw=document.getElementById('dl-enc-pw');
  if(pw) pw.required=on;
}}
function autoEncToggle(){{
  var on=document.getElementById('auto-enc-toggle').checked;
  document.getElementById('auto-enc-fields').style.display=on?'block':'none';
}}
function restoreEncDetect(inp){{
  var fname=(inp.value||'').toLowerCase();
  var isEnc=fname.endsWith('.enc');
  document.getElementById('restore-enc-field').style.display=isEnc?'block':'none';
  var pw=document.getElementById('restore-enc-pw');
  if(pw) pw.required=isEnc;
}}
function userImportPreview(){{
  var fi=document.getElementById('user-import-file');
  if(!fi||!fi.files||!fi.files[0]){{alert('Bitte zuerst eine Datei auswählen.');return;}}
  var fr=new FileReader();
  fr.onload=function(e){{
    try{{
      var d=JSON.parse(e.target.result);
      if(d._type!=='zeiterfassung_user_export'){{alert('Ungültige User-Export-Datei.');return;}}
      var u=(d.user||{{}});
      var tb=(d.time_blocks||[]).length;
      var ab=(d.absences||[]).length;
      var bt=(d.business_trips||[]).length;
      var sc=(d.user_schedules||[]).length;
      var pr=document.getElementById('user-import-preview');
      pr.style.display='block';
      pr.innerHTML='<b>Export von: '+_esc(u.username||'?')+'</b>'
        +(u.display_name?' <span style="color:var(--mu);">('+_esc(u.display_name)+')</span>':'')+'<br>'
        +'<span style="color:var(--mu);font-size:12px;">Exportiert: '+_esc(d._exported_at||'')+'</span>'
        +'<div style="margin-top:8px;">Zeitblöcke: <b>'+tb+'</b> &nbsp;·&nbsp; '
        +'Abwesenheiten: <b>'+ab+'</b> &nbsp;·&nbsp; '
        +'Dienstreisen: <b>'+bt+'</b> &nbsp;·&nbsp; '
        +'Zeitschemas: <b>'+sc+'</b></div>';
      document.getElementById('user-import-confirm').style.display='inline-block';
    }}catch(ex){{alert('Fehler beim Lesen der Datei: '+ex);}}
  }};
  fr.readAsText(fi.files[0],'utf-8');
}}
function prepareUserImport(){{
  var fi=document.getElementById('user-import-file');
  var fh=document.getElementById('user-import-file-hidden');
  var tgt=document.getElementById('user-import-target');
  var th=document.getElementById('user-import-target-hidden');
  if(!fi||!fi.files||!fi.files[0]){{alert('Keine Datei ausgewählt.');return false;}}
  var dt=new DataTransfer();
  dt.items.add(fi.files[0]);
  fh.files=dt.files;
  th.value=tgt.value;
  return true;
}}
function _esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
</script>"""


# ── Bot section ────────────────────────────────────────────────────────────────

def _render_bot_section() -> str:
    import html as _h
    cfg = _get_bot_config()
    tok_set = bool(cfg.get("bot_token"))
    api_set = bool(cfg.get("anthropic_api_key"))
    admin_ids = cfg.get("admin_telegram_ids") or ""

    status = _bot_service_status()
    svc_exists = _bot_service_exists()

    if status == "active":
        status_badge = f"<span style='color:var(--ok);font-weight:600;'>● {t('admin.bot_running')}</span>"
    elif status in ("inactive", "failed", "activating"):
        status_badge = f"<span style='color:var(--danger);font-weight:600;'>● {status.capitalize()}</span>"
    elif status == "not-found":
        status_badge = f"<span style='color:var(--mu);font-weight:600;'>{t('admin.bot_not_configured')}</span>"
    else:
        status_badge = f"<span style='color:var(--mu);'>● {_h.escape(status)}</span>"

    setup_btn = ""
    if not svc_exists:
        setup_btn = f"""
          <form method="post" action="/admin/bot/setup-service" style="display:inline;">
            <button class="btn btn-sm" type="submit">{t('admin.bot_setup_service_btn')}</button>
          </form>"""

    tok_hint = f"<span style='color:var(--ok);font-size:11px;'>{t('admin.set_hint')}</span>" if tok_set else f"<span style='color:var(--mu);font-size:11px;'>{t('admin.empty_hint')}</span>"
    api_hint = f"<span style='color:var(--ok);font-size:11px;'>{t('admin.set_hint')}</span>" if api_set else f"<span style='color:var(--mu);font-size:11px;'>{t('admin.empty_hint')}</span>"

    return f"""
    <div class="acc" data-tab="system" id="acc-bot">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-bot-body')">
        <span>{t('admin.acc_bot')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-bot-body">
        <div class="acc-inner">

          <div style="font-size:13px;font-weight:700;margin-bottom:10px;">{t('admin.bot_config')}</div>
          <form method="post" action="/admin/bot-config/save" style="margin-bottom:18px;">
            <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;">
              <div style="flex:1;min-width:220px;">
                <label style="font-size:12px;">{t('admin.bot_token')} {tok_hint}</label>
                <input type="password" name="bot_token" value="" placeholder="{'**' if tok_set else 'Token von @BotFather'}" autocomplete="new-password" style="font-size:13px;padding:5px 8px;width:100%;">
                <div class="small" style="color:var(--mu);margin-top:3px;">{t('admin.bot_token_hint')}</div>
              </div>
              <div style="flex:1;min-width:220px;">
                <label style="font-size:12px;">{t('admin.anthropic_api_key')} {api_hint}</label>
                <input type="password" name="anthropic_api_key" value="" placeholder="{'**' if api_set else 'sk-ant-...'}" autocomplete="new-password" style="font-size:13px;padding:5px 8px;width:100%;">
                <div class="small" style="color:var(--mu);margin-top:3px;">{t('admin.api_key_hint')}</div>
              </div>
            </div>
            <div style="margin-bottom:10px;">
              <label style="font-size:12px;">{t('admin.admin_tg_ids')}</label>
              <input type="text" name="admin_telegram_ids" value="{_h.escape(admin_ids)}" placeholder="z.B. 123456789, 987654321" style="font-size:13px;padding:5px 8px;min-width:280px;">
              <div class="small" style="color:var(--mu);margin-top:3px;">{t('admin.admin_tg_ids_hint')}</div>
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
          </form>

          <hr style="margin:12px 0;">

          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.bot_status')}</div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
            <div>{t('admin.bot_status')}: {status_badge}</div>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <form method="post" action="/admin/bot/control" style="display:inline;">
              <input type="hidden" name="action" value="start">
              <button class="btn btn-sm" type="submit">{t('admin.bot_start_btn')}</button>
            </form>
            <form method="post" action="/admin/bot/control" style="display:inline;">
              <input type="hidden" name="action" value="stop">
              <button class="btn btn-sm" type="submit">{t('admin.bot_stop_btn')}</button>
            </form>
            <form method="post" action="/admin/bot/control" style="display:inline;">
              <input type="hidden" name="action" value="restart">
              <button class="btn btn-sm" type="submit">{t('admin.bot_restart_btn')}</button>
            </form>
            {setup_btn}
          </div>

        </div>
      </div>
    </div>"""


# ── Update section ─────────────────────────────────────────────────────────────

def _live_app_version() -> str:
    try:
        import re as _re
        with open("/opt/zeiterfassung/app.py", "r", encoding="utf-8") as _f:
            for _line in _f:
                _m = _re.match(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', _line)
                if _m:
                    return _m.group(1)
    except Exception:
        pass
    return APP_VERSION


def _render_update_section() -> str:
    import sys as _sys, platform as _plat
    import html as _h
    last_commit = _h.escape(_git_last_commit_info())
    started_web = _h.escape(_service_started_at("zeiterfassung"))
    started_bot = _h.escape(_service_started_at("zeiterfassung-bot"))
    py_ver = _h.escape(_sys.version.split()[0])
    os_info = _h.escape(_plat.platform())
    live_version = _h.escape(_live_app_version())

    _check_btn_lbl = t('admin.update_check_btn')
    _checking_lbl = t('admin.update_checking')
    _up_to_date_lbl = t('admin.update_up_to_date')
    _avail_lbl = t('admin.update_available_js')
    _update_confirm = t('admin.update_confirm')
    return f"""
    <div class="acc" data-tab="system" id="acc-update">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-update-body')">
        <span>{t('admin.acc_update')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-update-body">
        <div class="acc-inner">

          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.update_current_state')}</div>
          <table style="width:auto;margin-bottom:12px;">
            <tr><td style="color:var(--mu);font-size:12px;padding-right:14px;">{t('admin.update_version')}</td><td style="font-size:13px;">{live_version}</td></tr>
            <tr><td style="color:var(--mu);font-size:12px;">{t('admin.update_last_commit')}</td><td style="font-size:12px;font-family:monospace;">{last_commit}</td></tr>
          </table>

          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px;">
            <button class="btn btn-sm" type="button" onclick="checkUpdates(this)">{_check_btn_lbl}</button>
            <span id="update-check-result" style="font-size:13px;"></span>
          </div>

          <hr style="margin:12px 0;">

          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.update_section')}</div>
          <p class="small" style="color:var(--mu);">{t('admin.update_hint')}</p>
          <form method="post" action="/admin/update/run"
                onsubmit="return confirm('{_update_confirm}');">
            <button class="btn primary btn-sm" type="submit">{t('admin.update_run_btn')}</button>
          </form>

          <hr style="margin:12px 0;">

          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.update_sys_info')}</div>
          <table style="width:auto;">
            <tr><td style="color:var(--mu);font-size:12px;padding-right:14px;">{t('admin.update_python')}</td><td style="font-size:12px;">{py_ver}</td></tr>
            <tr><td style="color:var(--mu);font-size:12px;">{t('admin.update_os')}</td><td style="font-size:12px;">{os_info}</td></tr>
            <tr><td style="color:var(--mu);font-size:12px;">{t('admin.update_web_since')}</td><td style="font-size:12px;">{started_web}</td></tr>
            <tr><td style="color:var(--mu);font-size:12px;">{t('admin.update_bot_since')}</td><td style="font-size:12px;">{started_bot}</td></tr>
          </table>

        </div>
      </div>
    </div>
    <script>
    var _UPD_CHECK_LBL = {repr(_check_btn_lbl)};
    var _UPD_CHECKING_LBL = {repr(_checking_lbl)};
    var _UPD_OK_LBL = {repr(_up_to_date_lbl)};
    var _UPD_AVAIL_LBL = {repr(_avail_lbl)};
    function checkUpdates(btn) {{
      btn.disabled = true;
      btn.textContent = _UPD_CHECKING_LBL;
      var el = document.getElementById('update-check-result');
      el.textContent = '';
      fetch('/admin/update/check')
        .then(function(r){{return r.json();}})
        .then(function(d){{
          btn.disabled = false;
          btn.textContent = _UPD_CHECK_LBL;
          if(d.error) {{el.textContent = '⚠ ' + d.error; el.style.color='var(--danger)';}}
          else if(d.count === 0) {{el.textContent = _UPD_OK_LBL; el.style.color='var(--ok)';}}
          else {{el.innerHTML = '<b style="color:var(--danger);">' + d.count + ' ' + _UPD_AVAIL_LBL + '</b>: ' + d.commits.slice(0,3).map(function(c){{return '<code>'+c+'</code>';}}).join(', ');}}
        }})
        .catch(function(){{btn.disabled=false;btn.textContent=_UPD_CHECK_LBL;el.textContent='⚠ Fehler';el.style.color='var(--danger)';}});
    }}
    </script>"""


def _render_admin_absences_section(u=None) -> str:
    today = datetime.date.today()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()

    # --- year for vacation status ---
    try:
        abs_year = int(request.args.get("abs_year") or today.year)
    except (ValueError, TypeError):
        abs_year = today.year
    year_start = f"{abs_year}-01-01"
    year_end = f"{abs_year}-12-31"

    available_years = list(range(max(today.year - 3, 2020), today.year + 2))
    year_opts = "".join(
        f'<option value="{y}" {"selected" if y == abs_year else ""}>{y}</option>'
        for y in reversed(available_years)
    )

    db = connect()
    active_users = db.execute(
        "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY display_name, username"
    ).fetchall()
    db.close()
    if u and not is_sysadmin(u):
        _vis = _get_visible_user_ids(u)
        if _vis is not None:
            _vis_set = set(_vis)
            active_users = [r for r in active_users if r["id"] in _vis_set]

    # --- Section 1: vacation status all users ---
    vac_rows = ""
    for u_row in active_users:
        uid = u_row["id"]
        name = _html.escape(u_row["display_name"] or u_row["username"])
        vc = _vacation_calc(uid, abs_year)
        entitlement = vc["entitlement"]
        eff_carry = vc["effective_carryover"]
        total = entitlement + eff_carry
        used_total = vc["used_total"]
        genommen = _vacation_used_days(uid, abs_year, date_to_limit=yesterday)
        geplant = max(0.0, used_total - genommen)
        remaining = vc["remaining_total"]
        if remaining > 0:
            rem_col = "var(--ok)"
        elif remaining == 0:
            rem_col = "var(--mu)"
        else:
            rem_col = "var(--danger)"
        _vac_search_key = _html.escape((u_row["username"] + " " + (u_row["display_name"] or "")).lower())
        vac_rows += (
            f"<tr data-search='{_vac_search_key}'><td>{name}</td>"
            f"<td style='text-align:center;'>{_fmt_vac_days(entitlement)}</td>"
            f"<td style='text-align:center;'>{_fmt_vac_days(eff_carry)}</td>"
            f"<td style='text-align:center;font-weight:600;'>{_fmt_vac_days(total)}</td>"
            f"<td style='text-align:center;'>{_fmt_vac_days(genommen)}</td>"
            f"<td style='text-align:center;'>{_fmt_vac_days(geplant)}</td>"
            f"<td style='text-align:center;font-weight:600;color:{rem_col};'>{_fmt_vac_days(remaining)}</td>"
            f"</tr>"
        )

    # --- Section 2: per-user absences ---
    abs_from = (request.args.get("abs_from") or year_start).strip()
    abs_to = (request.args.get("abs_to") or year_end).strip()
    sel_uid_str = (request.args.get("abs_uid") or "").strip()
    sel_uid = int(sel_uid_str) if sel_uid_str.isdigit() else (active_users[0]["id"] if active_users else None)

    user_opts = "".join(
        f'<option value="{u_row["id"]}" {"selected" if u_row["id"] == sel_uid else ""}>'
        f'{_html.escape(u_row["display_name"] or u_row["username"])}</option>'
        for u_row in active_users
    )

    detail_rows = ""
    if sel_uid:
        db = connect()
        abs_list = db.execute(
            """SELECT a.date_from, a.date_to, a.is_half_day, a.comment, t.name AS type_name
               FROM absences a JOIN absence_types t ON a.type_id = t.id
               WHERE a.user_id = ? AND a.date_to >= ? AND a.date_from <= ?
               ORDER BY a.date_from""",
            (sel_uid, abs_from, abs_to),
        ).fetchall()
        db.close()
        type_sums: dict[str, float] = {}
        for row in abs_list:
            df = str(row["date_from"])[:10]
            dt = str(row["date_to"])[:10]
            half = int(row["is_half_day"] or 0)
            cmt = (row["comment"] or "").strip()
            tname = row["type_name"]
            disp_type = cmt if (tname == "Sonstige" and cmt) else tname
            days = _count_absence_workdays(sel_uid, df, dt, half)
            type_sums[disp_type] = type_sums.get(disp_type, 0.0) + days
            detail_rows += (
                f"<tr>"
                f"<td style='font-size:12px;'>{_fmt_date_de(df)}</td>"
                f"<td style='font-size:12px;'>{_fmt_date_de(dt)}</td>"
                f"<td style='font-size:12px;'>{_html.escape(disp_type)}</td>"
                f"<td style='text-align:center;font-size:12px;'>{_fmt_vac_days(days)}</td>"
                f"<td style='font-size:12px;color:var(--mu);'>{_html.escape(cmt) if tname != 'Sonstige' else ''}</td>"
                f"</tr>"
            )
        if type_sums:
            sum_parts = " &nbsp;·&nbsp; ".join(
                f"<b>{_html.escape(tk)}:</b> {_fmt_vac_days(tv)}"
                for tk, tv in sorted(type_sums.items())
            )
            detail_rows += (
                f"<tr><td colspan='5' style='font-size:12px;font-weight:600;"
                f"border-top:2px solid var(--bd);padding-top:8px;'>Summe: {sum_parts}</td></tr>"
            )
    if not detail_rows:
        detail_rows = f"<tr><td colspan='5' style='color:var(--mu);font-size:13px;'>{t('admin.no_data')}</td></tr>"

    # --- Section 3: compact overview all users ---
    db = connect()
    all_abs = db.execute(
        """SELECT a.user_id, a.date_from, a.date_to, a.is_half_day, a.comment, t.name AS type_name
           FROM absences a JOIN absence_types t ON a.type_id = t.id
           WHERE a.date_to >= ? AND a.date_from <= ?""",
        (abs_from, abs_to),
    ).fetchall()
    db.close()

    user_type_sums: dict[int, dict[str, float]] = {
        u_row["id"]: {"Urlaub": 0.0, "Krank": 0.0, "Flextag": 0.0, "Verdi": 0.0, "Sonstige": 0.0}
        for u_row in active_users
    }
    for ab in all_abs:
        uid_ab = ab["user_id"]
        if uid_ab not in user_type_sums:
            continue
        df = str(ab["date_from"])[:10]
        dt = str(ab["date_to"])[:10]
        half = int(ab["is_half_day"] or 0)
        cmt = (ab["comment"] or "").strip().lower()
        tname = ab["type_name"]
        days = _count_absence_workdays(uid_ab, df, dt, half)
        if tname == "Urlaub":
            user_type_sums[uid_ab]["Urlaub"] += days
        elif tname == "Krank":
            user_type_sums[uid_ab]["Krank"] += days
        elif tname == "Flextag" or (tname == "Sonstige" and cmt == "flextag"):
            user_type_sums[uid_ab]["Flextag"] += days
        elif tname == "Verdi" or (tname == "Sonstige" and cmt == "verdi"):
            user_type_sums[uid_ab]["Verdi"] += days
        else:
            user_type_sums[uid_ab]["Sonstige"] += days

    overview_rows = ""
    for u_row in active_users:
        uid_ov = u_row["id"]
        s = user_type_sums.get(uid_ov, {})
        cells = "".join(
            f"<td style='text-align:center;font-size:12px;'>"
            f"{'–' if s.get(k, 0.0) == 0 else _fmt_vac_days(s[k])}</td>"
            for k in ("Urlaub", "Krank", "Flextag", "Verdi", "Sonstige")
        )
        overview_rows += f"<tr><td style='font-size:12px;'>{_html.escape(u_row['display_name'] or u_row['username'])}</td>{cells}</tr>"

    export_url = f"/admin/absences/export?uid={sel_uid or ''}&from={abs_from}&to={abs_to}"

    _no_users_row = f"<tr><td colspan='7' style='color:var(--mu);'>{t('admin.no_users')}</td></tr>"
    _no_data_row = f"<tr><td colspan='6' style='color:var(--mu);'>{t('admin.no_data')}</td></tr>"
    return f"""
    <div class="acc" data-tab="reporting" id="acc-absoverview">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-absoverview-body')">
        <span>{t('admin.acc_absences')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-absoverview-body">
        <div class="acc-inner">

          <!-- Urlaubsstatus alle User -->
          <form method="get" action="/admin" onsubmit="sessionStorage.setItem('openAcc','acc-absoverview')" style="display:flex;gap:8px;align-items:flex-end;margin-bottom:12px;flex-wrap:wrap;">
            <input type="hidden" name="abs_uid" value="{_html.escape(sel_uid_str)}">
            <input type="hidden" name="abs_from" value="{_html.escape(abs_from)}">
            <input type="hidden" name="abs_to" value="{_html.escape(abs_to)}">
            <div><label style="font-size:12px;">{t('admin.vac_status_year')}</label><br>
              <select name="abs_year" style="font-size:13px;padding:4px 8px;">{year_opts}</select>
            </div>
            <button class="btn btn-sm" type="submit">{t('periods.show_btn')}</button>
          </form>
          <div style="margin-bottom:8px;">
            <input type="text" id="vac-search-input"
                   placeholder="{t('admin.search_users_placeholder')}"
                   oninput="filterVacTable(this.value)"
                   style="width:100%;max-width:320px;padding:7px 10px;border-radius:6px;font-size:13px;">
          </div>
          <div class="table-scroll" style="margin-bottom:16px;">
            <table>
              <thead><tr>
                <th>{t('common.name')}</th>
                <th style="text-align:center;">{t('admin.vac_entitlement')}</th>
                <th style="text-align:center;">{t('admin.vac_carryover')}</th>
                <th style="text-align:center;">{t('admin.vac_total')}</th>
                <th style="text-align:center;">{t('admin.vac_taken')}</th>
                <th style="text-align:center;">{t('admin.vac_planned')}</th>
                <th style="text-align:center;">{t('admin.vac_available')}</th>
              </tr></thead>
              <tbody>{vac_rows or _no_users_row}</tbody>
            </table>
          </div>

          <hr style="margin:14px 0;">

          <!-- Abwesenheiten je User -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.abs_per_user')}</div>
          <form method="get" action="/admin" onsubmit="sessionStorage.setItem('openAcc','acc-absoverview')" style="display:flex;gap:8px;align-items:flex-end;margin-bottom:10px;flex-wrap:wrap;">
            <input type="hidden" name="abs_year" value="{abs_year}">
            <div><label style="font-size:12px;">{t('admin.users_title')}</label><br>
              <select name="abs_uid" style="font-size:13px;padding:4px 8px;">{user_opts}</select>
            </div>
            <div><label style="font-size:12px;">{t('absences.from')}</label><br>
              {_date_input("abs_from", abs_from)}
            </div>
            <div><label style="font-size:12px;">{t('absences.to')}</label><br>
              {_date_input("abs_to", abs_to)}
            </div>
            <div style="padding-bottom:2px;display:flex;gap:6px;align-items:flex-end;">
              <button class="btn btn-sm" type="submit">{t('periods.show_btn')}</button>
              <a class="btn btn-sm" href="{_html.escape(export_url)}">CSV ↓</a>
            </div>
          </form>
          <div class="table-scroll" style="margin-bottom:16px;">
            <table>
              <thead><tr><th>{t('absences.from')}</th><th>{t('absences.to')}</th><th>{t('absences.type')}</th><th style="text-align:center;">{t('common.days')}</th><th>{t('absences.comment')}</th></tr></thead>
              <tbody>{detail_rows}</tbody>
            </table>
          </div>

          <hr style="margin:14px 0;">

          <!-- Kompakte Übersicht alle User -->
          <div style="font-size:13px;font-weight:700;margin-bottom:6px;">
            {t('admin.abs_all_users')}
            <span style="font-size:11px;font-weight:400;color:var(--mu);">{_fmt_date_de(abs_from)} – {_fmt_date_de(abs_to)}</span>
          </div>
          <div class="table-scroll">
            <table>
              <thead><tr>
                <th>{t('common.name')}</th>
                <th style="text-align:center;">Urlaub</th>
                <th style="text-align:center;">Krank</th>
                <th style="text-align:center;">Flextag</th>
                <th style="text-align:center;">Verdi</th>
                <th style="text-align:center;">Sonstige</th>
              </tr></thead>
              <tbody>{overview_rows or _no_data_row}</tbody>
            </table>
          </div>

        </div>
      </div>
    </div>"""


def _render_admin_teams(teams, all_users, team_members) -> str:
    _WD_LABELS = [t('wd.mon'), t('wd.tue'), t('wd.wed'), t('wd.thu'), t('wd.fri'), t('wd.sat'), t('wd.sun')]
    team_rows = ""
    for tm in teams:
        tid = tm["id"]
        color = _html.escape(tm["color"] or "#4a9eff")
        name  = _html.escape(tm["name"])
        desc  = _html.escape(tm["description"] or "")
        cnt   = tm["member_count"]
        member_ids = team_members.get(tid, [])
        checkboxes = "".join(
            f'<label style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
            f'<input type="checkbox" name="user_ids" value="{u["id"]}"'
            f'{" checked" if u["id"] in member_ids else ""}>'
            f'{_html.escape(u["display_name"] or u["username"])}</label>'
            for u in all_users
        )
        team_rows += f"""
        <div class="acc" style="margin-bottom:8px;">
          <button class="acc-hdr" type="button"
                  onclick="accToggle('tm-body-{tid}')"
                  style="background:none;border:1px solid var(--br);border-radius:8px;">
            <span style="display:flex;align-items:center;gap:8px;">
              <span style="width:14px;height:14px;border-radius:50%;
                           background:{color};display:inline-block;flex-shrink:0;"></span>
              <strong>{name}</strong>
              <span style="color:var(--mu);font-size:12px;">{cnt} {t('admin.team_members')}</span>
              {('<span style="color:var(--mu);font-size:12px;">' + desc + '</span>') if desc else ''}
            </span>
            <span class="acc-arr">▼</span>
          </button>
          <div class="acc-body" id="tm-body-{tid}" style="display:none;">
            <div class="acc-inner">
              <form method="post" action="/admin/teams">
                <input type="hidden" name="action" value="members">
                <input type="hidden" name="team_id" value="{tid}">
                <p style="font-size:13px;font-weight:600;margin-bottom:8px;">{t('admin.team_members')}</p>
                {checkboxes}
                <div style="margin-top:12px;">
                  <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
                </div>
              </form>
              <div style="margin-top:8px;">
                <form method="post" action="/admin/teams" style="margin:0;"
                      onsubmit="return confirm('{t('confirm.delete')}')">
                  <input type="hidden" name="action" value="delete">
                  <input type="hidden" name="team_id" value="{tid}">
                  <button class="btn btn-sm" type="submit"
                          style="color:#dc2626;">{t('btn.delete')}</button>
                </form>
              </div>
              <hr style="border:none;border-top:1px solid var(--br);margin:12px 0;">
              <p style="font-size:13px;font-weight:600;margin-bottom:8px;">{t('admin.edit_team')}</p>
              <form method="post" action="/admin/teams">
                <input type="hidden" name="action" value="edit">
                <input type="hidden" name="team_id" value="{tid}">
                <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;">
                  <div>
                    <label style="font-size:12px;">{t('admin.team_name')}</label>
                    <input type="text" name="name" value="{name}"
                           required maxlength="60"
                           style="display:block;margin-top:4px;min-width:160px;">
                  </div>
                  <div>
                    <label style="font-size:12px;">{t('admin.team_color')}</label>
                    <input type="color" name="color" value="{color}"
                           style="display:block;margin-top:4px;width:48px;height:34px;padding:2px;">
                  </div>
                  <div style="flex:1;min-width:140px;">
                    <label style="font-size:12px;">{t('admin.team_description')}</label>
                    <input type="text" name="description" value="{desc}"
                           maxlength="120"
                           style="display:block;margin-top:4px;width:100%;">
                  </div>
                  <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
                </div>
              </form>
            </div>
          </div>
        </div>"""

    return f"""
    <div style="max-width:700px;margin:1.5rem auto;">
      <div style="margin-bottom:1rem;">
        <a href="/admin" class="btn btn-sm">← {t('nav.admin')}</a>
      </div>
      <h2 style="margin-bottom:1.5rem;">{t('admin.teams')}</h2>

      <!-- Neues Team -->
      <div style="background:var(--ca);border:1px solid var(--br);border-radius:10px;
                  padding:16px;margin-bottom:1.5rem;">
        <h3 style="margin:0 0 12px;">{t('admin.add_team')}</h3>
        <form method="post" action="/admin/teams">
          <input type="hidden" name="action" value="create">
          <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;">
            <div>
              <label style="font-size:12px;">{t('admin.team_name')} *</label>
              <input type="text" name="name" required maxlength="60"
                     style="display:block;margin-top:4px;min-width:180px;">
            </div>
            <div>
              <label style="font-size:12px;">{t('admin.team_color')}</label>
              <input type="color" name="color" value="#4a9eff"
                     style="display:block;margin-top:4px;width:48px;height:34px;padding:2px;">
            </div>
            <div style="flex:1;min-width:160px;">
              <label style="font-size:12px;">Beschreibung</label>
              <input type="text" name="description" maxlength="120"
                     style="display:block;margin-top:4px;width:100%;">
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
          </div>
        </form>
      </div>

      <!-- Teams Liste -->
      {team_rows if team_rows else f'<p style="color:var(--mu);">{t("admin.no_teams")}</p>'}

    </div>
    <script>
    function accToggle(id) {{
      var el = document.getElementById(id);
      if (!el) return;
      var isHidden = el.style.display === 'none' || el.style.display === '';
      el.style.display = isHidden ? 'block' : 'none';
      var btn = el.previousElementSibling;
      if (btn) {{
        var arr = btn.querySelector('.acc-arr');
        if (arr) arr.textContent = isHidden ? '▲' : '▼';
      }}
    }}
    </script>"""


def _render_admin_teams_inline(teams, all_users, team_members) -> str:
    team_rows = ""
    for tm in teams:
        tid = tm["id"]
        color = _html.escape(tm["color"] or "#4a9eff")
        name  = _html.escape(tm["name"])
        desc  = _html.escape(tm["description"] or "")
        cnt   = tm["member_count"]
        cur_region = tm["holiday_region"] or "" if "holiday_region" in tm.keys() else ""
        member_ids = team_members.get(tid, [])
        checkboxes = "".join(
            f'<label style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
            f'<input type="checkbox" name="user_ids" value="{u["id"]}"'
            f'{" checked" if u["id"] in member_ids else ""}>'
            f'{_html.escape(u["display_name"] or u["username"])}</label>'
            for u in all_users
        )
        team_rows += f"""
        <div class="acc" style="margin-bottom:8px;">
          <button class="acc-hdr" type="button"
                  onclick="accToggle('tm-body-{tid}')"
                  style="background:none;border:1px solid var(--br);border-radius:8px;">
            <span style="display:flex;align-items:center;gap:8px;">
              <span style="width:14px;height:14px;border-radius:50%;
                           background:{color};display:inline-block;flex-shrink:0;"></span>
              <strong>{name}</strong>
              <span style="color:var(--mu);font-size:12px;">{cnt} {t('admin.team_members')}</span>
              {('<span style="color:var(--mu);font-size:12px;">' + desc + '</span>') if desc else ''}
            </span>
            <span class="acc-arr">▼</span>
          </button>
          <div class="acc-body" id="tm-body-{tid}">
            <div class="acc-inner">
              <form method="post" action="/admin/teams">
                <input type="hidden" name="action" value="members">
                <input type="hidden" name="team_id" value="{tid}">
                <p style="font-size:13px;font-weight:600;margin-bottom:8px;">{t('admin.team_members')}</p>
                {checkboxes}
                <div style="margin-top:12px;">
                  <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
                </div>
              </form>
              <div style="margin-top:8px;">
                <form method="post" action="/admin/teams" style="margin:0;"
                      onsubmit="return confirm('{t('confirm.delete')}')">
                  <input type="hidden" name="action" value="delete">
                  <input type="hidden" name="team_id" value="{tid}">
                  <button class="btn btn-sm" type="submit"
                          style="color:#dc2626;">{t('btn.delete')}</button>
                </form>
              </div>
              <hr style="border:none;border-top:1px solid var(--br);margin:12px 0;">
              <p style="font-size:13px;font-weight:600;margin-bottom:8px;">{t('admin.edit_team')}</p>
              <form method="post" action="/admin/teams">
                <input type="hidden" name="action" value="edit">
                <input type="hidden" name="team_id" value="{tid}">
                <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;">
                  <div>
                    <label style="font-size:12px;">{t('admin.team_name')}</label>
                    <input type="text" name="name" value="{name}"
                           required maxlength="60"
                           style="display:block;margin-top:4px;min-width:160px;">
                  </div>
                  <div>
                    <label style="font-size:12px;">{t('admin.team_color')}</label>
                    <input type="color" name="color" value="{color}"
                           style="display:block;margin-top:4px;width:48px;height:34px;padding:2px;">
                  </div>
                  <div style="flex:1;min-width:140px;">
                    <label style="font-size:12px;">{t('admin.team_description')}</label>
                    <input type="text" name="description" value="{desc}"
                           maxlength="120"
                           style="display:block;margin-top:4px;width:100%;">
                  </div>
                  <div>
                    <label style="font-size:12px;">{t('admin.team_region')}</label>
                    <div style="margin-top:4px;">{_region_picker(f'team_hr_{tid}', cur_region, include_default=True)}</div>
                    <input type="hidden" name="holiday_region" id="team_hr_{tid}_val">
                  </div>
                  <button class="btn primary btn-sm" type="submit"
                          onclick="document.getElementById('team_hr_{tid}_val').value=document.getElementById('team_hr_{tid}_r').value">{t('btn.save')}</button>
                </div>
              </form>
            </div>
          </div>
        </div>"""

    return f"""
      <!-- Neues Team -->
      <div style="background:var(--ca);border:1px solid var(--br);border-radius:10px;
                  padding:16px;margin-bottom:1.5rem;">
        <h3 style="margin:0 0 12px;">{t('admin.add_team')}</h3>
        <form method="post" action="/admin/teams">
          <input type="hidden" name="action" value="create">
          <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;">
            <div>
              <label style="font-size:12px;">{t('admin.team_name')} *</label>
              <input type="text" name="name" required maxlength="60"
                     style="display:block;margin-top:4px;min-width:180px;">
            </div>
            <div>
              <label style="font-size:12px;">{t('admin.team_color')}</label>
              <input type="color" name="color" value="#4a9eff"
                     style="display:block;margin-top:4px;width:48px;height:34px;padding:2px;">
            </div>
            <div style="flex:1;min-width:160px;">
              <label style="font-size:12px;">{t('admin.team_description')}</label>
              <input type="text" name="description" maxlength="120"
                     style="display:block;margin-top:4px;width:100%;">
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
          </div>
        </form>
      </div>
      <!-- Teams Liste -->
      {team_rows if team_rows else f'<p style="color:var(--mu);">{t("admin.no_teams")}</p>'}"""


def _render_admin_staffing_inline(teams, plans, slots, all_assignments, u) -> str:
    assigned = {}
    assigned_lead = {}
    for a in all_assignments:
        assigned.setdefault(a["slot_id"], set()).add(a["user_id"])
        if int(a["is_lead"] or 0):
            assigned_lead.setdefault(a["slot_id"], set()).add(a["user_id"])

    slots_by_plan = {}
    for s in slots:
        slots_by_plan.setdefault(s["plan_id"], []).append(s)

    _WD_MAP = {0: t('wd.mon'), 1: t('wd.tue'), 2: t('wd.wed'),
               3: t('wd.thu'), 4: t('wd.fri'), 5: t('wd.sat'), 6: t('wd.sun')}
    _STYPE = {"vm": t('staffing.slot_vm'), "nm": t('staffing.slot_nm'),
              "special": t('staffing.slot_special')}

    def _wd_label(slot):
        if slot["slot_type"] == "special":
            wd = _WD_MAP.get(int(slot["special_weekday"] or 0), "")
            weeks = slot["nth_week"] or ""
            return f"{wd} ({weeks}. Wo.)"
        days = [_WD_MAP.get(int(x), "") for x in str(slot["weekdays"]).split(",")]
        return ", ".join(days)

    plan_html = ""
    plans_by_team = {}
    for p in plans:
        plans_by_team.setdefault(p["team_id"], []).append(p)

    for tm in teams:
        tid = tm["id"]
        team_plans = plans_by_team.get(tid, [])
        team_color = _html.escape(tm["color"] or "#4a9eff")

        db_tmp = connect()
        team_user_rows = db_tmp.execute(
            "SELECT u.id, u.username, u.display_name FROM users u "
            "JOIN user_teams ut ON ut.user_id=u.id "
            "WHERE ut.team_id=? AND u.is_active=1 ORDER BY u.display_name",
            (tid,)
        ).fetchall()
        db_tmp.close()

        plans_html = ""
        for p in team_plans:
            pid = p["id"]
            pname = _html.escape(p["name"])
            plan_slots = slots_by_plan.get(pid, [])

            slots_html = ""
            for s in plan_slots:
                sid = s["id"]
                slabel = _html.escape(s["label"])
                stype_label = _STYPE.get(s["slot_type"], s["slot_type"])
                wd_str = _wd_label(s)
                assigned_ids = assigned.get(sid, set())

                available_cards   = ""
                assigned_cards    = ""
                assigned_lead_ids = assigned_lead.get(sid, set())
                for tu in team_user_rows:
                    uname = _html.escape(tu["display_name"] or tu["username"])
                    if tu["id"] in assigned_ids:
                        is_u_lead  = tu["id"] in assigned_lead_ids
                        lead_icon  = "👑" if is_u_lead else "○"
                        lead_style = "color:#eab308;" if is_u_lead else "color:var(--mu);"
                        card = (
                            f'<div class="user-card" draggable="true" data-user-id="{tu["id"]}" '
                            f'data-is-lead="{1 if is_u_lead else 0}" ondragstart="drag(event)">'
                            f'<span class="user-dot" style="background:{team_color}"></span>'
                            f'<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;'
                            f'white-space:nowrap;">{uname}</span>'
                            f'<button type="button" onclick="toggleLead(this)" '
                            f'style="border:none;background:none;cursor:pointer;font-size:13px;'
                            f'padding:0 2px;{lead_style}flex-shrink:0;" '
                            f'title="{t("staffing.is_lead")}">{lead_icon}</button></div>'
                        )
                        assigned_cards += card
                    else:
                        card = (
                            f'<div class="user-card" draggable="true" data-user-id="{tu["id"]}" '
                            f'ondragstart="drag(event)">'
                            f'<span class="user-dot" style="background:{team_color}"></span>'
                            f'{uname}</div>'
                        )
                        available_cards += card

                no_members = f'<p style="font-size:12px;color:var(--mu);">{t("admin.no_team_members")}</p>' if not team_user_rows else ""

                _srole       = s["slot_role"] or "staff"
                _plan_lead_label2 = (p["lead_label"] if p["lead_label"] else "Leiter") if "lead_label" in p.keys() else "Leiter"
                _srole_label = _html.escape(_plan_lead_label2) if _srole == "lead" else t("staffing.role_staff")
                _srole_bg    = "#eab308" if _srole == "lead" else "var(--ca)"
                _srole_color = "#000"    if _srole == "lead" else "var(--tx)"
                _s_wd_checks2 = "".join(
                    f'<label style="font-size:12px;display:flex;align-items:center;gap:3px;">'
                    f'<input type="checkbox" name="wd_{i}" value="{i}"'
                    f'{" checked" if s["weekdays"] and str(i) in str(s["weekdays"]).split(",") else ""}>'
                    f' {_WD_MAP[i]}</label>'
                    for i in range(7)
                )
                _s_nth_checks2 = "".join(
                    f'<label style="font-size:12px;display:flex;align-items:center;gap:3px;">'
                    f'<input type="checkbox" name="nth_w_{i}" value="{i}"'
                    f'{" checked" if s["nth_week"] and str(i) in str(s["nth_week"]).split(",") else ""}>'
                    f' {i}.</label>'
                    for i in range(1, 6)
                )
                _s_spwd_opts2 = "".join(
                    f'<option value="{i}" {"selected" if s["special_weekday"] is not None and int(s["special_weekday"])==i else ""}>{_WD_MAP[i]}</option>'
                    for i in range(7)
                )
                slots_html += f"""
                <div class="slot-card" data-slot-id="{sid}">
                  <div class="slot-header">
                    <span class="slot-label"><strong>{slabel}</strong></span>
                    <span class="slot-type-badge" style="font-size:11px;background:var(--ca);
                          border-radius:4px;padding:2px 6px;">{stype_label}</span>
                    <span style="font-size:11px;background:{_srole_bg};color:{_srole_color};
                          border-radius:4px;padding:2px 6px;">{_srole_label}</span>
                    <span class="slot-days" style="font-size:12px;color:var(--mu);">{wd_str}</span>
                    {f'<span style="font-size:12px;color:var(--ac);">{s["time_from"]}–{s["time_to"]}</span>' if s["time_from"] and s["time_to"] else ""}
                    <span class="slot-min" style="font-size:12px;color:var(--mu);">Min: {s["min_staff"]}</span>
                    {f'<span style="font-size:12px;color:#eab308;">👑≥{s["min_lead"]}</span>' if (s["min_lead"] or 0) > 0 else ""}
                    <button class="btn btn-sm" style="margin-left:auto;padding:2px 8px;"
                            onclick="toggleSlotEdit({sid})">✏</button>
                    <button class="btn btn-sm" style="color:#dc2626;padding:2px 8px;"
                            onclick="deleteSlot({sid})">×</button>
                  </div>
                  <div id="slot-edit-{sid}" style="display:none;margin-bottom:12px;padding:12px;background:var(--ca);border-radius:8px;border:1px solid var(--bd);">
                    <form method="post" action="/admin/staffing">
                      <input type="hidden" name="action" value="edit_slot">
                      <input type="hidden" name="slot_id" value="{sid}">
                      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
                        <div>
                          <label style="font-size:12px;">{t('staffing.slot_label')} *</label>
                          <input type="text" name="label" required maxlength="60"
                                 value="{_html.escape(s['label'])}"
                                 style="display:block;margin-top:4px;min-width:120px;">
                        </div>
                        <div>
                          <label style="font-size:12px;">{t('staffing.slot_type')}</label>
                          <select name="slot_type" style="display:block;margin-top:4px;"
                                  onchange="toggleSlotType(this,'edit-{sid}')">
                            <option value="vm" {"selected" if s["slot_type"]=="vm" else ""}>{t('staffing.slot_vm')}</option>
                            <option value="nm" {"selected" if s["slot_type"]=="nm" else ""}>{t('staffing.slot_nm')}</option>
                            <option value="special" {"selected" if s["slot_type"]=="special" else ""}>{t('staffing.slot_special')}</option>
                          </select>
                        </div>
                        <div>
                          <label style="font-size:12px;">{t('staffing.min_staff')}</label>
                          <input type="number" name="min_staff" value="{s['min_staff']}" min="1" max="99"
                                 style="display:block;margin-top:4px;width:70px;">
                        </div>
                        <div>
                          <label style="font-size:12px;">{t('staffing.slot_role')}</label>
                          <select name="slot_role" style="display:block;margin-top:4px;">
                            <option value="staff" {"selected" if (s["slot_role"] or "staff")=="staff" else ""}>{t('staffing.role_staff')}</option>
                            <option value="lead" {"selected" if s["slot_role"]=="lead" else ""}>{t('staffing.role_lead')}</option>
                          </select>
                        </div>
                        <div>
                          <label style="font-size:12px;">{t('staffing.min_lead')}</label>
                          <input type="number" name="min_lead" value="{s['min_lead'] or 0}" min="0" max="99"
                                 style="display:block;margin-top:4px;width:70px;">
                        </div>
                        <div>
                          <label style="font-size:12px;">Von – Bis</label>
                          <div style="display:flex;align-items:center;gap:4px;margin-top:4px;">
                            <input type="time" name="time_from" step="900" value="{s['time_from'] or ''}" style="width:96px;">
                            <span>–</span>
                            <input type="time" name="time_to" step="900" value="{s['time_to'] or ''}" style="width:96px;">
                          </div>
                        </div>
                      </div>
                      <div id="wd-normal-edit-{sid}" style="margin-top:8px;{"display:none;" if s["slot_type"]=="special" else ""}">
                        <label style="font-size:12px;display:block;margin-bottom:4px;">{t('staffing.weekdays')}</label>
                        <div style="display:flex;gap:10px;flex-wrap:wrap;">{_s_wd_checks2}</div>
                        <input type="hidden" name="weekdays" id="wd-val-edit-{sid}" value="{s['weekdays'] or '0,1,2,3,4'}">
                      </div>
                      <div id="wd-special-edit-{sid}" style="margin-top:8px;{"" if s["slot_type"]=="special" else "display:none;"}">
                        <div style="display:flex;gap:12px;flex-wrap:wrap;">
                          <div>
                            <label style="font-size:12px;">{t('wd.weekday')}</label>
                            <select name="special_weekday" style="display:block;margin-top:4px;">{_s_spwd_opts2}</select>
                          </div>
                          <div>
                            <label style="font-size:12px;">{t('staffing.nth_week')}</label>
                            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px;">{_s_nth_checks2}</div>
                            <input type="hidden" name="nth_week" id="nth-val-edit-{sid}" value="{s['nth_week'] or ''}">
                          </div>
                        </div>
                      </div>
                      <div style="margin-top:10px;display:flex;gap:8px;">
                        <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
                        <button class="btn btn-sm" type="button" onclick="toggleSlotEdit({sid})">{t('btn.cancel')}</button>
                      </div>
                      <script>(function(){{
                        var _div=document.getElementById('slot-edit-{sid}');
                        if(!_div)return;
                        var _sel=_div.querySelector('select[name="slot_type"]');
                        if(!_sel)return;
                        function doToggle(){{
                          var n=document.getElementById('wd-normal-edit-{sid}');
                          var s=document.getElementById('wd-special-edit-{sid}');
                          if(!n||!s)return;
                          if(_sel.value==='special'){{n.style.display='none';s.style.display='';}}
                          else{{n.style.display='';s.style.display='none';}}
                        }}
                        _sel.addEventListener('change',doToggle);
                      }})();</script>
                    </form>
                  </div>
                  {no_members}
                  <div class="slot-body">
                    <div class="assign-col">
                      <h6>{t('staffing.available')}</h6>
                      <div class="droptarget" id="available-{sid}"
                           ondragover="allowDrop(event)"
                           ondrop="drop(event,{sid},'available')">
                        {available_cards}
                      </div>
                    </div>
                    <div class="assign-col">
                      <h6>{t('staffing.assigned')}</h6>
                      <div class="droptarget" id="assigned-{sid}"
                           ondragover="allowDrop(event)"
                           ondrop="drop(event,{sid},'assigned')">
                        {assigned_cards}
                      </div>
                    </div>
                  </div>
                  <button class="btn primary btn-sm" style="margin-top:8px;"
                          onclick="saveAssignments({sid})">{t('btn.save')}</button>
                </div>"""

            wd_checkboxes = "".join(
                f'<label style="font-size:12px;display:flex;align-items:center;gap:4px;">'
                f'<input type="checkbox" name="wd_{i}" value="{i}" checked> {_WD_MAP[i]}</label>'
                for i in range(5)
            )
            _plan_lead_lbl2 = _html.escape(
                (p["lead_label"] if "lead_label" in p.keys() and p["lead_label"] else None) or "Leiter"
            )
            plans_html += f"""
            <div style="background:var(--bg);border:1px solid var(--br);border-radius:10px;
                         padding:14px;margin-bottom:12px;">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap;">
                <strong style="font-size:15px;">{pname}</strong>
                <span style="font-size:12px;color:var(--mu);">{p["description"] or ""}</span>
                <form method="post" action="/admin/staffing"
                      style="display:flex;align-items:center;gap:6px;margin-left:auto;">
                  <input type="hidden" name="action" value="edit_plan">
                  <input type="hidden" name="plan_id" value="{pid}">
                  <label style="font-size:12px;color:var(--mu);">{t("staffing.lead_label")}:</label>
                  <input type="text" name="lead_label" value="{_plan_lead_lbl2}"
                         maxlength="30" placeholder="Leiter"
                         style="font-size:12px;padding:3px 6px;border-radius:4px;width:120px;">
                  <button class="btn btn-sm" type="submit"
                          style="font-size:12px;padding:3px 8px;">{t("btn.save")}</button>
                </form>
              </div>
              {slots_html if slots_html else f'<p style="font-size:12px;color:var(--mu);margin-bottom:8px;">{t("staffing.no_slots")}</p>'}
              <details style="margin-top:8px;" ontoggle="if(this.open)slotFormInit(this);">
                <summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--ac);">
                  + {t('staffing.add_slot')}
                </summary>
                <form method="post" action="/admin/staffing"
                      style="margin-top:10px;padding:12px;background:var(--ca);
                             border-radius:8px;border:1px solid var(--br);">
                  <input type="hidden" name="action" value="create_slot">
                  <input type="hidden" name="plan_id" value="{pid}">
                  <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
                    <div>
                      <label style="font-size:12px;">{t('staffing.slot_label')} *</label>
                      <input type="text" name="label" required maxlength="60"
                             placeholder="{t('staffing.slot_vm')}"
                             style="display:block;margin-top:4px;min-width:140px;">
                    </div>
                    <div>
                      <label style="font-size:12px;">{t('staffing.slot_type')}</label>
                      <select name="slot_type" style="display:block;margin-top:4px;"
                              onchange="toggleSlotType(this,'{pid}')">
                        <option value="vm">{t('staffing.slot_vm')}</option>
                        <option value="nm">{t('staffing.slot_nm')}</option>
                        <option value="special">{t('staffing.slot_special')}</option>
                      </select>
                    </div>
                    <div>
                      <label style="font-size:12px;">{t('staffing.min_staff')}</label>
                      <input type="number" name="min_staff" value="1" min="1" max="99"
                             style="display:block;margin-top:4px;width:70px;">
                    </div>
                    <div>
                      <label style="font-size:12px;">{t('staffing.slot_role')}</label>
                      <select name="slot_role" style="display:block;margin-top:4px;">
                        <option value="staff">{t('staffing.role_staff')}</option>
                        <option value="lead">{t('staffing.role_lead')}</option>
                      </select>
                    </div>
                    <div>
                      <label style="font-size:12px;">{t('staffing.min_lead')}</label>
                      <input type="number" name="min_lead" value="0" min="0" max="99"
                             style="display:block;margin-top:4px;width:70px;">
                      <div style="font-size:10px;color:var(--mu);margin-top:2px;">{t('staffing.min_lead_hint')}</div>
                    </div>
                    <div>
                      <label style="font-size:12px;">Von – Bis</label>
                      <div style="display:flex;align-items:center;gap:4px;margin-top:4px;">
                        <input type="time" name="time_from" step="900" style="width:96px;">
                        <span style="color:var(--mu);">–</span>
                        <input type="time" name="time_to" step="900" style="width:96px;">
                      </div>
                    </div>
                  </div>
                  <div id="wd-normal-{pid}" style="margin-bottom:10px;">
                    <label style="font-size:12px;display:block;margin-bottom:4px;">{t('staffing.weekdays')}</label>
                    <div style="display:flex;gap:10px;flex-wrap:wrap;">{wd_checkboxes}</div>
                    <input type="hidden" name="weekdays" id="wd-val-{pid}" value="0,1,2,3,4">
                  </div>
                  <div id="wd-special-{pid}" style="display:none;margin-bottom:10px;">
                    <div style="display:flex;gap:12px;flex-wrap:wrap;">
                      <div>
                        <label style="font-size:12px;">{t('wd.weekday')}</label>
                        <select name="special_weekday" style="display:block;margin-top:4px;">
                          {"".join(f'<option value="{i}">{_WD_MAP[i]}</option>' for i in range(7))}
                        </select>
                      </div>
                      <div>
                        <label style="font-size:12px;">{t('staffing.nth_week')}</label>
                        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px;">
                          {"".join(f'<label style="font-size:12px;display:flex;align-items:center;gap:3px;"><input type="checkbox" name="nth_w_{i}" value="{i}"> {i}.</label>' for i in range(1,6))}
                        </div>
                        <input type="hidden" name="nth_week" id="nth-val-{pid}" value="">
                      </div>
                    </div>
                  </div>
                  <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
                </form>
              </details>
            </div>"""

        plan_html += f"""
        <div style="margin-bottom:1.5rem;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
            <span style="width:12px;height:12px;border-radius:50%;
                         background:{team_color};display:inline-block;"></span>
            <strong style="font-size:16px;">{_html.escape(tm["name"])}</strong>
          </div>
          {plans_html if plans_html else f'<p style="font-size:13px;color:var(--mu);margin-bottom:8px;">{t("staffing.no_plans")}</p>'}
          <details>
            <summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--ac);margin-bottom:4px;">
              + {t('staffing.add_plan')}
            </summary>
            <form method="post" action="/admin/staffing"
                  style="margin-top:8px;padding:12px;background:var(--ca);
                         border-radius:8px;border:1px solid var(--br);">
              <input type="hidden" name="action" value="create_plan">
              <input type="hidden" name="team_id" value="{tid}">
              <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;">
                <div>
                  <label style="font-size:12px;">{t('staffing.plan_name')} *</label>
                  <input type="text" name="name" required maxlength="80"
                         style="display:block;margin-top:4px;min-width:160px;">
                </div>
                <div style="flex:1;min-width:140px;">
                  <label style="font-size:12px;">Beschreibung</label>
                  <input type="text" name="description" maxlength="120"
                         style="display:block;margin-top:4px;width:100%;">
                </div>
                <div>
                  <label style="font-size:12px;">{t('staffing.default_min_staff')}</label>
                  <input type="number" name="default_min_staff" value="2" min="1" max="99"
                         style="display:block;margin-top:4px;width:70px;">
                </div>
                <div style="display:flex;align-items:flex-end;padding-bottom:6px;">
                  <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;">
                    <input type="checkbox" name="require_lead" value="1">
                    {t('staffing.require_lead')}
                  </label>
                </div>
                <div>
                  <label style="font-size:12px;">{t('staffing.lead_label')}</label>
                  <input type="text" name="lead_label" value="Leiter" maxlength="30"
                         placeholder="z.B. Arzt, Leiter, Supervisor"
                         style="display:block;margin-top:4px;width:180px;">
                  <small style="color:var(--mu);">{t('staffing.lead_label_hint')}</small>
                </div>
                <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
              </div>
            </form>
          </details>
        </div>"""

    no_teams_hint = f'<p style="color:var(--mu);">{t("admin.no_teams")}</p>' if not teams else ""

    return f"""
    <style>
    .slot-card{{border:1px solid var(--br);border-radius:8px;padding:1rem;margin-bottom:1rem;}}
    .slot-header{{display:flex;gap:8px;align-items:center;margin-bottom:.75rem;flex-wrap:wrap;}}
    .slot-body{{display:grid;grid-template-columns:1fr 1fr;gap:1rem;}}
    @media(max-width:500px){{.slot-body{{grid-template-columns:1fr;}}}}
    .assign-col h6{{font-size:12px;color:var(--mu);margin-bottom:6px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;}}
    .droptarget{{min-height:80px;background:var(--ca);border:2px dashed var(--br);border-radius:6px;padding:8px;transition:border-color .15s,background .15s;}}
    .droptarget.dragover{{border-color:var(--ac);background:color-mix(in srgb,var(--ac) 10%,var(--ca));}}
    .user-card{{background:var(--bg);border:1px solid var(--br);border-radius:4px;padding:4px 8px;margin-bottom:4px;cursor:grab;display:flex;align-items:center;gap:6px;font-size:13px;user-select:none;}}
    .user-card:hover{{opacity:.85;}}
    .user-card:active{{cursor:grabbing;}}
    .user-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0;}}
    </style>
    {no_teams_hint}
    {plan_html}"""


_DE_STATES = [
    ("DE-BW", "BW", "Baden-Württemberg"),
    ("DE-BY", "BY", "Bayern"),
    ("DE-BE", "BE", "Berlin"),
    ("DE-BB", "BB", "Brandenburg"),
    ("DE-HB", "HB", "Bremen"),
    ("DE-HH", "HH", "Hamburg"),
    ("DE-HE", "HE", "Hessen"),
    ("DE-MV", "MV", "Mecklenburg-Vorpommern"),
    ("DE-NI", "NI", "Niedersachsen"),
    ("DE-NW", "NW", "Nordrhein-Westfalen"),
    ("DE-RP", "RP", "Rheinland-Pfalz"),
    ("DE-SL", "SL", "Saarland"),
    ("DE-SN", "SN", "Sachsen"),
    ("DE-ST", "ST", "Sachsen-Anhalt"),
    ("DE-SH", "SH", "Schleswig-Holstein"),
    ("DE-TH", "TH", "Thüringen"),
]


def _render_school_holidays_section() -> str:
    db = connect()
    entries = db.execute(
        "SELECT * FROM school_holidays ORDER BY region, date_from"
    ).fetchall()
    db.close()

    rows_by_region: dict = {}
    for e in entries:
        rows_by_region.setdefault(e["region"], []).append(e)

    trs = ""
    for region, hols in sorted(rows_by_region.items()):
        state_name = next((name for rcode, _, name in _DE_STATES if rcode == region), region)
        for h in hols:
            trs += (
                f"<tr>"
                f"<td style='font-size:12px;color:var(--mu);'>{_html.escape(region)}</td>"
                f"<td style='font-size:13px;'>{_html.escape(h['name'])}</td>"
                f"<td style='font-size:13px;'>{h['date_from']}</td>"
                f"<td style='font-size:13px;'>{h['date_to']}</td>"
                f"<td><form method='post' action='/admin/school-holidays/delete' style='display:inline;'"
                f" onsubmit=\"if(!confirm('{t('confirm.delete_school_holiday')}'))return false;sessionStorage.setItem('openAcc','acc-schoolhols')\">"
                f"<input type='hidden' name='entry_id' value='{h['id']}'>"
                f"<button class='btn btn-sm danger' type='submit' style='padding:2px 7px;'>×</button>"
                f"</form></td>"
                f"</tr>"
            )
    if not trs:
        trs = f"<tr><td colspan='5' style='color:var(--mu);'>Noch keine Schulferien importiert.</td></tr>"

    state_opts = "".join(
        f'<option value="{api}">{name} ({api})</option>'
        for _, api, name in _DE_STATES
    )
    clear_opts = "".join(
        f'<option value="{rcode}">{name}</option>'
        for rcode, _, name in _DE_STATES
    )
    cur_year = datetime.date.today().year
    year_opts = "".join(
        f'<option value="{y}" {"selected" if y == cur_year else ""}>{y}</option>'
        for y in range(cur_year - 1, cur_year + 3)
    )

    return f"""
    <div class="acc" data-tab="system" id="acc-schoolhols">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-schoolhols-body')">
        <span>🎓 Schulferien</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-schoolhols-body">
        <div class="acc-inner">
          <p class="small" style="color:var(--mu);margin-bottom:14px;">
            Schulferien werden bei wöchentlichen Berufsschultagen automatisch berücksichtigt.
            Quelle: <a href="https://ferien-api.de" target="_blank">ferien-api.de</a>
          </p>

          <!-- Fetch von API -->
          <div style="border:1px solid var(--bd);border-radius:8px;padding:14px;margin-bottom:14px;background:var(--sf);">
            <div style="font-weight:600;font-size:14px;margin-bottom:10px;">🌐 Online-Import (ferien-api.de)</div>
            <form method="post" action="/admin/school-holidays/fetch"
                  onsubmit="sessionStorage.setItem('openAcc','acc-schoolhols')">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
                <div>
                  <label style="font-size:12px;color:var(--mu);">Bundesland</label>
                  <select name="state_code" style="display:block;margin-top:4px;font-size:13px;">{state_opts}</select>
                </div>
                <div>
                  <label style="font-size:12px;color:var(--mu);">Jahr</label>
                  <select name="year" style="display:block;margin-top:4px;font-size:13px;">{year_opts}</select>
                </div>
                <div style="display:flex;gap:6px;align-items:flex-end;">
                  <button class="btn primary btn-sm" type="submit">⬇ Importieren</button>
                  <label style="font-size:12px;display:flex;align-items:center;gap:4px;cursor:pointer;">
                    <input type="checkbox" name="replace" value="1"> Vorhandene ersetzen
                  </label>
                </div>
              </div>
            </form>
          </div>

          <!-- Manuell hinzufügen -->
          <div style="border:1px solid var(--bd);border-radius:8px;padding:14px;margin-bottom:14px;background:var(--sf);">
            <div style="font-weight:600;font-size:14px;margin-bottom:10px;">✏ Manuell hinzufügen</div>
            <form method="post" action="/admin/school-holidays/add"
                  onsubmit="sessionStorage.setItem('openAcc','acc-schoolhols')">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
                <div>
                  <label style="font-size:12px;color:var(--mu);">Region</label>
                  <select name="region" style="display:block;margin-top:4px;font-size:13px;">{clear_opts}</select>
                </div>
                <div style="flex:1;min-width:140px;">
                  <label style="font-size:12px;color:var(--mu);">Name</label>
                  <input type="text" name="name" required maxlength="80" placeholder="Sommerferien"
                         style="display:block;margin-top:4px;">
                </div>
                <div>
                  <label style="font-size:12px;color:var(--mu);">Von</label>
                  <input type="date" name="date_from" required style="display:block;margin-top:4px;">
                </div>
                <div>
                  <label style="font-size:12px;color:var(--mu);">Bis</label>
                  <input type="date" name="date_to" required style="display:block;margin-top:4px;">
                </div>
                <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
              </div>
            </form>
          </div>

          <!-- Vorhandene Einträge -->
          <div style="font-weight:600;font-size:14px;margin-bottom:8px;">Eingetragene Schulferien ({len(entries)})</div>
          <div class="table-scroll" style="margin-bottom:12px;">
            <table style="width:100%;font-size:13px;">
              <thead><tr><th>Region</th><th>Name</th><th>Von</th><th>Bis</th><th></th></tr></thead>
              <tbody>{trs}</tbody>
            </table>
          </div>

          <!-- Alle löschen für Region -->
          <form method="post" action="/admin/school-holidays/clear"
                onsubmit="return confirm('Alle Schulferien für diese Region löschen?')&&(sessionStorage.setItem('openAcc','acc-schoolhols'),true)">
            <div style="display:flex;gap:8px;align-items:flex-end;">
              <div>
                <label style="font-size:12px;color:var(--mu);">Region leeren</label>
                <select name="region" style="display:block;margin-top:4px;font-size:13px;">{clear_opts}</select>
              </div>
              <button class="btn danger btn-sm" type="submit">🗑 Region löschen</button>
            </div>
          </form>
        </div>
      </div>
    </div>"""


def _render_features_section() -> str:
    checked = 'checked' if _feature_enabled('staffing') else ''
    return f"""
    <div class="acc" data-tab="system" id="acc-features">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-features-body')">
        <span>{t('admin.features')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-features-body">
        <div class="acc-inner">
          <form method="post" action="/admin/features" onsubmit="sessionStorage.setItem('openAcc','acc-features')">
            <div style="margin-bottom:16px;">
              <label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer;">
                <input type="checkbox" name="feature_staffing" {checked} style="margin-top:3px;">
                <div>
                  <div style="font-weight:600;font-size:14px;">{t('admin.feature_staffing')}</div>
                  <div style="font-size:12px;color:var(--mu);margin-top:2px;">{t('admin.feature_staffing_hint')}</div>
                </div>
              </label>
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
          </form>
        </div>
      </div>
    </div>"""


def _render_overtime_defaults_section() -> str:
    cfg = _get_app_config()
    def_plus_h  = cfg.get("overtime_default_limit_plus") or ""
    def_minus_h = cfg.get("overtime_default_limit_minus") or ""
    return f"""
    <div class="acc" id="acc-overtime-defaults">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-overtime-defaults-body')">
        <span>{t('admin.acc_ot_defaults')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-overtime-defaults-body">
        <div class="acc-inner">
          <p class="small" style="color:var(--mu);margin-bottom:12px;">{t('admin.ot_defaults_hint')}</p>
          <form method="post" action="/admin/overtime/save-defaults" onsubmit="sessionStorage.setItem('openAcc','acc-overtime-defaults')">
            <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin-bottom:12px;">
              <div>
                <label style="font-size:12px;">{t('admin.ot_default_plus')}</label>
                <input type="number" name="def_plus" value="{_html.escape(def_plus_h)}" placeholder="–" step="0.5"
                  style="width:80px;font-size:13px;padding:4px 8px;">
              </div>
              <div>
                <label style="font-size:12px;">{t('admin.ot_default_minus')}</label>
                <input type="number" name="def_minus" value="{_html.escape(def_minus_h)}" placeholder="–" step="0.5"
                  style="width:80px;font-size:13px;padding:4px 8px;">
              </div>
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
          </form>
        </div>
      </div>
    </div>"""


def _render_admin_overtime_section(u=None) -> str:
    today_iso = datetime.date.today().isoformat()

    cfg = _get_app_config()
    def_plus_h  = cfg.get("overtime_default_limit_plus") or ""
    def_minus_h = cfg.get("overtime_default_limit_minus") or ""

    db = connect()
    active_users = db.execute(
        "SELECT id, username, display_name, email, supervisor_email, "
        "overtime_limit_plus, overtime_limit_minus, "
        "overtime_notify_enabled, overtime_notify_interval, overtime_last_notified "
        "FROM users WHERE is_active=1 ORDER BY display_name, username"
    ).fetchall()
    _adj_users = db.execute(
        "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY display_name, username"
    ).fetchall()
    if u and not is_sysadmin(u):
        _vis = _get_visible_user_ids(u)
        if _vis is not None:
            _vis_set = set(_vis)
            active_users = [r for r in active_users if r["id"] in _vis_set]
            _adj_users = [r for r in _adj_users if r["id"] in _vis_set]
    _adj_rows = db.execute("""
        SELECT ba.*, u.display_name as uname, u.username,
               cb.display_name as cname
        FROM balance_adjustments ba
        JOIN users u ON u.id=ba.user_id
        LEFT JOIN users cb ON cb.id=ba.created_by
        ORDER BY ba.adjustment_date DESC
        LIMIT 50
    """).fetchall()
    db.close()

    def _fmt_adj_h(m):
        h = m / 60
        sign = "+" if m >= 0 else ""
        return f"{sign}{h:.2f}h".replace(".00h","h")

    _adj_trs = ""
    for _a in _adj_rows:
        _udisp = _html.escape(_a["uname"] or _a["username"] or "?")
        _cdisp = _html.escape(_a["cname"] or "–")
        _hdisp = _fmt_adj_h(int(_a["minutes"]))
        _clr   = "#16a34a" if int(_a["minutes"]) >= 0 else "#dc2626"
        _adj_trs += (
            f"<tr>"
            f"<td style='padding:4px 6px;font-size:12px;'>{_a['adjustment_date']}</td>"
            f"<td style='padding:4px 6px;font-size:12px;'>{_udisp}</td>"
            f"<td style='padding:4px 6px;font-size:12px;font-weight:600;color:{_clr};'>{_hdisp}</td>"
            f"<td style='padding:4px 6px;font-size:12px;'>{_html.escape(_a['reason'])}</td>"
            f"<td style='padding:4px 6px;font-size:12px;color:var(--mu);'>{_cdisp}</td>"
            f"<td style='padding:4px 6px;'>"
            f"<form method='post' action='/admin/balance-adjustment' style='margin:0;'>"
            f"<input type='hidden' name='action' value='delete'>"
            f"<input type='hidden' name='adj_id' value='{_a['id']}'>"
            f"<button class='btn btn-sm' type='submit' style='color:#dc2626;font-size:11px;padding:1px 6px;'"
            + f" onclick=\"return confirm('{t('confirm.delete')}')\">×</button>"
            f"</form></td>"
            f"</tr>"
        )
    _adj_table = ""
    if _adj_trs:
        _adj_table = f"""
        <div class="table-scroll" style="margin-top:12px;">
          <table style="font-size:12px;">
            <thead><tr>
              <th>Datum</th><th>{t('common.name')}</th>
              <th>Stunden</th><th>{t('balance.adjustment_reason')}</th>
              <th>Erstellt von</th><th></th>
            </tr></thead>
            <tbody>{_adj_trs}</tbody>
          </table>
        </div>"""

    def _mins_to_h(m) -> str:
        if m is None:
            return ""
        m = int(m)
        sign = "-" if m < 0 else ""
        m = abs(m)
        return f"{sign}{m // 60}" if m % 60 == 0 else f"{sign}{m / 60:.2f}".rstrip("0").rstrip(".")

    def _h_to_mins(s: str):
        s = s.strip()
        if not s:
            return None
        try:
            return int(float(s) * 60)
        except ValueError:
            return None

    # Balances
    balances: dict[int, int] = {}
    for u_row in active_users:
        balances[u_row["id"]] = _calc_balance_end_at(u_row["id"], today_iso)

    # --- Table rows ---
    def_plus_mins  = _h_to_mins(def_plus_h)
    def_minus_mins = _h_to_mins(def_minus_h)

    saldo_rows = ""
    for u_row in active_users:
        uid  = u_row["id"]
        name = _html.escape(u_row["display_name"] or u_row["username"])
        saldo = balances[uid]
        saldo_str = _fmt_minutes_signed(saldo)

        lp = u_row["overtime_limit_plus"]
        lm = u_row["overtime_limit_minus"]
        eff_lp = lp if lp is not None else def_plus_mins
        eff_lm = lm if lm is not None else def_minus_mins

        if eff_lp is not None and saldo > eff_lp:
            status = f"<span style='color:var(--danger);font-weight:600;'>{t('admin.ot_over_plus')}</span>"
            row_bg = "background:rgba(220,38,38,.04);"
        elif eff_lm is not None and saldo < -(eff_lm):
            status = f"<span style='color:var(--danger);font-weight:600;'>{t('admin.ot_over_minus')}</span>"
            row_bg = "background:rgba(220,38,38,.04);"
        elif eff_lp is not None and saldo > eff_lp * 0.9:
            status = f"<span style='color:#d97706;'>{t('admin.ot_near_plus')}</span>"
            row_bg = "background:rgba(251,191,36,.05);"
        elif eff_lm is not None and saldo < -(eff_lm) * 0.9:
            status = f"<span style='color:#d97706;'>{t('admin.ot_near_minus')}</span>"
            row_bg = "background:rgba(251,191,36,.05);"
        else:
            status = "<span style='color:var(--ok);'>✓ OK</span>"
            row_bg = ""

        lp_str = _mins_to_h(eff_lp) + (" h" if eff_lp is not None else "")
        lm_str = _mins_to_h(eff_lm) + (" h" if eff_lm is not None else "")
        saldo_color = "var(--ok)" if saldo >= 0 else "var(--danger)"

        saldo_rows += (
            f"<tr style='{row_bg}'>"
            f"<td style='font-size:12px;'>{name}</td>"
            f"<td style='text-align:center;font-weight:600;color:{saldo_color};font-size:12px;'>{saldo_str}</td>"
            f"<td style='text-align:center;font-size:12px;color:var(--mu);'>{'+' + lp_str if eff_lp is not None else '–'}</td>"
            f"<td style='text-align:center;font-size:12px;color:var(--mu);'>{'-' + lm_str if eff_lm is not None else '–'}</td>"
            f"<td style='font-size:12px;'>{status}</td>"
            f"</tr>"
        )

    # --- Limits + Notify form rows ---
    form_rows = ""
    for u_row in active_users:
        uid  = u_row["id"]
        name = _html.escape(u_row["display_name"] or u_row["username"])
        lp   = _mins_to_h(u_row["overtime_limit_plus"])
        lm   = _mins_to_h(u_row["overtime_limit_minus"])
        sup  = _html.escape(u_row["supervisor_email"] or "")
        en   = "checked" if int(u_row["overtime_notify_enabled"] or 0) else ""
        iv   = u_row["overtime_notify_interval"] or "once"

        def _iv_sel(val):
            opts = [("once",t("admin.ot_once")),("daily",t("admin.ot_daily")),("weekly",t("admin.ot_weekly"))]
            return "".join(
                f'<option value="{v}" {"selected" if v==val else ""}>{l}</option>'
                for v, l in opts
            )

        form_rows += f"""
        <tr>
          <td style="font-size:12px;">{name}</td>
          <td><input type="number" name="lp_{uid}" value="{lp}" placeholder="–" step="0.5"
            style="width:70px;font-size:12px;padding:3px 6px;" title="{t('admin.ot_limits_hint')}"></td>
          <td><input type="number" name="lm_{uid}" value="{lm}" placeholder="–" step="0.5"
            style="width:70px;font-size:12px;padding:3px 6px;" title="{t('admin.ot_limits_hint')}"></td>
          <td style="text-align:center;"><input type="checkbox" name="en_{uid}" value="1" {en}></td>
          <td><select name="iv_{uid}" style="font-size:12px;padding:3px 5px;">{_iv_sel(iv)}</select></td>
          <td><input type="email" name="sup_{uid}" value="{sup}" placeholder="{t('admin.supervisor_email')}"
            style="font-size:12px;padding:3px 6px;width:200px;"></td>
        </tr>"""

    _no_users_ot = f"<tr><td colspan='5' style='color:var(--mu);'>{t('admin.no_users')}</td></tr>"
    return f"""
    <div class="acc" data-tab="reporting" id="acc-overtime">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-overtime-body')">
        <span>{t('admin.acc_balance')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-overtime-body">
        <div class="acc-inner">

          <!-- Salden alle User -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.balance_current_title')}</div>
          <div class="table-scroll" style="margin-bottom:16px;">
            <table>
              <thead><tr>
                <th>{t('common.name')}</th>
                <th style="text-align:center;">{t('admin.col_saldo')}</th>
                <th style="text-align:center;">{t('admin.col_limit_plus')}</th>
                <th style="text-align:center;">{t('admin.col_limit_minus')}</th>
                <th>{t('common.status')}</th>
              </tr></thead>
              <tbody>{saldo_rows or _no_users_ot}</tbody>
            </table>
          </div>

          <hr style="margin:14px 0;">

          <!-- Limits + Benachrichtigungen konfigurieren -->
          <div style="font-size:13px;font-weight:700;margin-bottom:6px;">{t('admin.ot_limits_notify')}</div>
          <p class="small" style="color:var(--mu);margin-bottom:10px;">{t('admin.ot_limits_hint')}</p>

          <form method="post" action="/admin/overtime/save" onsubmit="sessionStorage.setItem('openAcc','acc-overtime')">
            <div class="table-scroll" style="margin-bottom:12px;">
              <table>
                <thead><tr>
                  <th>{t('common.name')}</th>
                  <th style="text-align:center;">{t('admin.ot_plus_limit')}</th>
                  <th style="text-align:center;">{t('admin.ot_minus_limit')}</th>
                  <th style="text-align:center;">{t('admin.ot_notify')}</th>
                  <th>{t('admin.ot_interval')}</th>
                  <th>{t('admin.supervisor_email')}</th>
                </tr></thead>
                <tbody>{form_rows}</tbody>
              </table>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
              <button class="btn btn-sm" type="submit" formaction="/admin/overtime/check"
                onclick="sessionStorage.setItem('openAcc','acc-overtime')">
                {t('admin.ot_check_now')}
              </button>
            </div>
          </form>

          <hr style="margin:14px 0;">

          <!-- Manuelle Korrekturen -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('balance.add_adjustment')}</div>
          <form method="post" action="/admin/balance-adjustment"
                onsubmit="sessionStorage.setItem('openAcc','acc-overtime')"
                style="margin-bottom:16px;">
            <input type="hidden" name="action" value="create">
            <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
              <div>
                <label style="font-size:12px;">{t('common.name')}</label>
                <select name="user_id" style="display:block;margin-top:4px;min-width:140px;">
                  {"".join('<option value="' + str(u2["id"]) + '">' + _html.escape(u2["display_name"] or u2["username"]) + '</option>' for u2 in _adj_users)}
                </select>
              </div>
              <div>
                <label style="font-size:12px;">Datum</label>
                <input type="date" name="date" required style="display:block;margin-top:4px;">
              </div>
              <div>
                <label style="font-size:12px;">{t('balance.adjustment_hours')}</label>
                <input type="number" name="hours" step="0.25" required
                       placeholder="{t('balance.adjustment_hint')}"
                       style="display:block;margin-top:4px;width:130px;">
              </div>
              <div style="flex:1;min-width:150px;">
                <label style="font-size:12px;">{t('balance.adjustment_reason')}</label>
                <input type="text" name="reason" required maxlength="120"
                       style="display:block;margin-top:4px;width:100%;">
              </div>
              <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
            </div>
          </form>
          {_adj_table}

        </div>
      </div>
    </div>"""


def _run_overtime_notifications() -> tuple[int, int]:
    """Run overtime limit checks and send notifications. Returns (sent, errors)."""
    today_iso = datetime.date.today().isoformat()
    cfg = _get_app_config()

    def _h_to_mins(s):
        s = (s or "").strip()
        if not s:
            return None
        try:
            return int(float(s) * 60)
        except ValueError:
            return None

    def_plus  = _h_to_mins(cfg.get("overtime_default_limit_plus"))
    def_minus = _h_to_mins(cfg.get("overtime_default_limit_minus"))

    db = connect()
    users = db.execute(
        "SELECT id, username, display_name, email, supervisor_email, "
        "overtime_limit_plus, overtime_limit_minus, overtime_notify_enabled, "
        "overtime_notify_interval, overtime_last_notified "
        "FROM users WHERE is_active=1 AND overtime_notify_enabled=1"
    ).fetchall()
    db.close()

    sent = 0
    errors = 0
    for u_row in users:
        uid   = u_row["id"]
        lp    = u_row["overtime_limit_plus"] if u_row["overtime_limit_plus"] is not None else def_plus
        lm    = u_row["overtime_limit_minus"] if u_row["overtime_limit_minus"] is not None else def_minus
        if lp is None and lm is None:
            continue

        saldo = _calc_balance_end_at(uid, today_iso)
        over_plus  = lp is not None and saldo > lp
        over_minus = lm is not None and saldo < -(lm)
        if not over_plus and not over_minus:
            continue

        interval      = u_row["overtime_notify_interval"] or "once"
        last_notified = u_row["overtime_last_notified"]
        should = False
        if interval == "once" and not last_notified:
            should = True
        elif interval == "daily":
            should = not last_notified or last_notified < today_iso
        elif interval == "weekly":
            if not last_notified:
                should = True
            else:
                diff = (datetime.date.today() - datetime.date.fromisoformat(last_notified)).days
                should = diff >= 7
        if not should:
            continue

        name = u_row["display_name"] or u_row["username"]
        saldo_str = _fmt_minutes_signed(saldo)
        if over_plus and lp:
            limit_str = f"+{lp // 60:02d}:{lp % 60:02d}"
            reason = "Plus-Limit (Überstunden)"
        else:
            limit_str = f"-{abs(lm) // 60:02d}:{abs(lm) % 60:02d}"
            reason = "Minus-Limit (Minderstunden)"

        body = (
            f"Hallo {name},\n\n"
            f"dein Gleitzeitkonto hat das eingestellte Limit überschritten.\n\n"
            f"Aktueller Saldo: {saldo_str}\n"
            f"Limit ({reason}): {limit_str}\n\n"
            f"Bitte stimme das weitere Vorgehen mit deinem Vorgesetzten ab.\n"
        )
        subject = f"Gleitzeitkonto Hinweis – {name}"

        recipients = [r for r in [u_row["email"] or "", u_row["supervisor_email"] or ""] if r]
        for recipient in recipients:
            try:
                _send_mail_simple(recipient, subject, body)
                sent += 1
            except Exception:
                errors += 1

        db2 = connect()
        db2.execute(
            "UPDATE users SET overtime_last_notified=? WHERE id=?",
            (today_iso, uid),
        )
        db2.commit()
        db2.close()

    return sent, errors


# Flat label lookup: region code → display label (for badges etc.)
_REGION_LABEL: dict[str, str] = {
    code: label
    for _, _, entries in REGION_GROUPS
    for code, label in entries
}

# Standard types available to all users by default (everything except Verdi)
_STANDARD_TYPE_NAMES = {"Urlaub", "Krank", "Flextag", "Sonstige"}


def _get_user_enabled_absence_type_ids(user_id: int) -> list[int]:
    """Return absence type IDs enabled for this user.
    NULL enabled_absence_types = standard set (all active except Verdi)."""
    db = connect()
    try:
        user_row = db.execute(
            "SELECT enabled_absence_types FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if user_row and user_row["enabled_absence_types"]:
            return [int(x) for x in user_row["enabled_absence_types"].split(",") if x.strip().isdigit()]
        rows = db.execute(
            "SELECT id FROM absence_types WHERE active=1 AND name != 'Verdi' ORDER BY id"
        ).fetchall()
        return [r["id"] for r in rows]
    finally:
        db.close()


def _region_country_key(entries: list) -> str:
    """Derive the JS country key from a REGION_GROUPS entries list."""
    c = entries[0][0]
    return c.split("-")[0] if "-" in c else c


def _region_picker(field_name: str, current: str, include_default: bool = False) -> str:
    """Two-step country → region picker. Submits region code as field_name."""
    # Find which group the current region belongs to
    current_country = ""
    for _, _, entries in REGION_GROUPS:
        if any(code == current for code, _ in entries):
            current_country = _region_country_key(entries)
            break

    # Build JS region data {country_key: [[code, label], ...]}
    data: dict = {}
    for _, _, entries in REGION_GROUPS:
        ck = _region_country_key(entries)
        data[ck] = [[c, l] for c, l in entries]
    regions_json = _json.dumps(data, ensure_ascii=False)

    # Build country dropdown
    country_opts = ""
    if include_default:
        sel = " selected" if not current else ""
        country_opts += f'<option value=""{sel}>— Standard verwenden —</option>'
    for flag, group_label, entries in REGION_GROUPS:
        ck = _region_country_key(entries)
        sel = " selected" if ck == current_country and current else ""
        country_opts += f'<option value="{ck}"{sel}>{_html.escape(flag + " " + group_label)}</option>'

    # Build initial region dropdown options for current country
    region_opts = ""
    region_display = "none" if (include_default and not current) else ""
    if current_country:
        for _, _, entries in REGION_GROUPS:
            if _region_country_key(entries) == current_country:
                if include_default:
                    sel = " selected" if not current else ""
                    region_opts += f'<option value=""{sel}>— Standard verwenden —</option>'
                for code, label in entries:
                    sel = " selected" if code == current else ""
                    region_opts += f'<option value="{code}"{sel}>{_html.escape(label)}</option>'
                break

    # Unique JS function name (replace non-alphanumeric with _)
    uniq = re.sub(r'[^a-zA-Z0-9]', '_', field_name)
    inc_default_js = "true" if include_default else "false"
    cur_js = _json.dumps(current)

    return (
        f'<select id="{uniq}_c" style="font-size:13px;padding:5px 8px;" '
        f'onchange="_rp_{uniq}(this.value)">{country_opts}</select>'
        f'<br><select name="{field_name}" id="{uniq}_r" '
        f'style="font-size:13px;padding:5px 8px;margin-top:6px;display:{region_display};">'
        f'{region_opts}</select>'
        f'<script>(function(){{'
        f'var _d={regions_json};'
        f'var _inc={inc_default_js};'
        f'var _cur={cur_js};'
        f'window["_rp_{uniq}"]=function(c){{'
        f'var r=document.getElementById("{uniq}_r");'
        f'if(!c){{r.style.display="none";r.innerHTML="";return;}}'
        f'var opts="";'
        f'if(_inc)opts+=\'<option value="">— Standard verwenden —</option>\';'
        f'(_d[c]||[]).forEach(function(e){{'
        f'var s=e[0]===_cur?" selected":"";'
        f'opts+=\'<option value="\'+e[0]+\'"\'+s+\'>\'+e[1]+\'</option>\';}});'
        f'r.innerHTML=opts;r.style.display="";'
        f'if(!r.value&&r.options.length>0)r.selectedIndex=0;'
        f'}};'
        f'_rp_{uniq}(document.getElementById("{uniq}_c").value);'
        f'}})();</script>'
    )


def _bundesland_select(name: str, current: str, include_default: bool = False) -> str:
    html = f'<select name="{name}" style="font-size:13px;padding:5px 8px;">'
    if include_default:
        sel = " selected" if not current else ""
        html += f'<option value=""{sel}>— Standard verwenden —</option>'
    for flag, group_label, entries in REGION_GROUPS:
        html += f'<optgroup label="{_html.escape(flag + " " + group_label)}">'
        for code, label in entries:
            sel = " selected" if code == current else ""
            html += f'<option value="{_html.escape(code)}"{sel}>{_html.escape(label)}</option>'
        html += "</optgroup>"
    html += "</select>"
    return html


def _render_regional_section() -> str:
    cfg = _get_app_config()
    default_region = cfg.get("default_holiday_region") or "DE-NW"
    base_url_val   = _html.escape(cfg.get("base_url") or "")
    current_tz     = cfg.get("timezone") or "Europe/Berlin"
    return f"""
    <div class="acc" data-tab="system" id="acc-regional">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-regional-body')">
        <span>{t('admin.acc_regional')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-regional-body">
        <div class="acc-inner">

          <form method="post" action="/admin/server-config" style="margin-bottom:20px;">
            <div style="font-size:13px;font-weight:700;margin-bottom:10px;">{t('admin.server_config')}</div>
            <div style="margin-bottom:10px;">
              <label style="font-size:12px;">{t('admin.base_url')}</label>
              <input type="url" name="base_url" value="{base_url_val}"
                     placeholder="https://zeiten.firma.de"
                     style="width:100%;max-width:400px;margin-top:4px;">
              <div class="small" style="color:var(--mu);margin-top:3px;">{t('admin.base_url_hint')}</div>
            </div>
            <div style="margin-bottom:10px;">
              <label style="font-size:12px;">{t('admin.timezone')}</label>
              {_timezone_select("timezone", current_tz)}
              <div class="small" style="color:var(--mu);margin-top:3px;">{t('admin.timezone_hint')}</div>
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
          </form>

          <hr style="margin:0 0 16px 0;border:none;border-top:1px solid var(--bd);">

          <form method="post" action="/admin/regional">
            <div style="font-size:13px;font-weight:700;margin-bottom:12px;">{t('admin.regional_holidays')}</div>
            <div style="margin-bottom:14px;">
              <label style="font-size:12px;">{t('admin.regional_default_label')}
                <span style="font-weight:400;color:var(--mu);">{t('admin.regional_default_hint')}</span>
              </label><br>
              <div style="margin-top:6px;">{_region_picker("default_holiday_region", default_region, include_default=False)}</div>
            </div>
            <div>
              <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    """


def _render_per_user_settings_section() -> str:
    """Accordion: per-user region and absence type configuration."""
    cfg = _get_app_config()
    default_region_code = cfg.get("default_holiday_region") or "DE-NW"
    default_region_label = _REGION_LABEL.get(default_region_code, default_region_code)

    db = connect()
    active_users = db.execute(
        "SELECT id, username, display_name, holiday_region, enabled_absence_types "
        "FROM users WHERE is_active=1 ORDER BY display_name, username"
    ).fetchall()
    all_types = db.execute(
        "SELECT id, name FROM absence_types WHERE active=1 ORDER BY name"
    ).fetchall()
    db.close()

    _tbyn = {t["name"]: t["id"] for t in all_types}
    _has_verdi = bool(_tbyn.get("Verdi"))
    _has_flextag = bool(_tbyn.get("Flextag"))

    # --- Per-user region rows ---
    region_rows = ""
    for urow in active_users:
        uid = urow["id"]
        uname = _html.escape(urow["display_name"] or urow["username"])
        cur_r = urow["holiday_region"] or ""
        cur_label = _REGION_LABEL.get(cur_r, "—")
        flag_txt = ""
        for fla, _, entries in REGION_GROUPS:
            if any(c == cur_r for c, _ in entries):
                flag_txt = fla + " "
                break
        region_rows += (
            f"<tr>"
            f"<td style='font-size:13px;'>{uname}</td>"
            f"<td style='font-size:12px;color:var(--mu);'>"
            f"{t('admin.regional_standard') + ' (' + _html.escape(default_region_label) + ')' if not cur_r else flag_txt + _html.escape(cur_label)}"
            f"</td>"
            f"<td><a class='btn btn-sm' href='/admin/users/{uid}/edit'>{t('btn.edit')}</a></td>"
            f"</tr>"
        )

    # --- Per-user absence types rows ---
    at_headers = "<th>Urlaub</th><th>Krank</th>"
    if _has_flextag:
        at_headers += "<th>Flextag</th>"
    if _has_verdi:
        at_headers += "<th>Verdi</th>"
    at_headers += "<th>Sonstige</th>"

    at_rows = ""
    for urow in active_users:
        uid = urow["id"]
        uname = _html.escape(urow["display_name"] or urow["username"])
        eat_str = urow["enabled_absence_types"] or ""
        eat_ids = {int(x) for x in eat_str.split(",") if x.strip().isdigit()} if eat_str else None

        def _chk(name: str) -> str:
            tid = _tbyn.get(name)
            if not tid:
                return "<td>–</td>"
            if name in ("Urlaub", "Krank"):
                return f"<td style='text-align:center;'>✓</td>"
            if eat_ids is None:
                checked = "checked" if name in _STANDARD_TYPE_NAMES else ""
            else:
                checked = "checked" if tid in eat_ids else ""
            field_id = f"eat_{uid}_{name.lower()}"
            return (f"<td style='text-align:center;'>"
                    f"<input type='checkbox' name='eat_{uid}_{name.lower()}' value='1' {checked}>"
                    f"</td>")

        at_rows += f"<tr><td style='font-size:13px;'>{uname}</td>"
        at_rows += f"<td style='text-align:center;'>✓</td><td style='text-align:center;'>✓</td>"
        if _has_flextag:
            at_rows += _chk("Flextag")
        if _has_verdi:
            at_rows += _chk("Verdi")
        at_rows += _chk("Sonstige")
        at_rows += "</tr>"

    _no_users_row = f"<tr><td colspan='3' style='color:var(--mu);'>{t('admin.no_users')}</td></tr>"
    _no_users_at  = f"<tr><td colspan='6' style='color:var(--mu);'>{t('admin.no_users')}</td></tr>"
    return f"""
    <div class="acc" data-tab="users" id="acc-per-user-settings">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-per-user-settings-body')">
        <span>{t('admin.acc_per_user')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-per-user-settings-body">
        <div class="acc-inner">

          <!-- Default region info -->
          <div style="font-size:12px;color:var(--mu);margin-bottom:16px;">
            {t('admin.regional_default_label')} <b>{_html.escape(default_region_label)}</b>
          </div>

          <!-- Per-user regions -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.regional_per_user')}</div>
          <div class="table-scroll" style="margin-bottom:20px;">
            <table>
              <thead><tr><th>{t('admin.users_title')}</th><th>{t('admin.regional')}</th><th></th></tr></thead>
              <tbody>{region_rows or _no_users_row}</tbody>
            </table>
          </div>

          <!-- Per-user absence types -->
          <div style="font-size:13px;font-weight:700;margin-bottom:4px;">{t('admin.abs_types_per_user')}</div>
          <div class="small" style="color:var(--mu);margin-bottom:8px;">{t('admin.abs_types_always')}</div>
          <form method="post" action="/admin/batch/absence-types">
            <div class="table-scroll" style="margin-bottom:10px;">
              <table>
                <thead><tr><th>{t('admin.users_title')}</th>{at_headers}</tr></thead>
                <tbody>{at_rows or _no_users_at}</tbody>
              </table>
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
          </form>

        </div>
      </div>
    </div>"""


def _render_appearance_section() -> str:
    cfg = _get_app_config()
    accent    = cfg.get("accent_color") or "#2563eb"
    nav_color = cfg.get("nav_color") or ""
    app_label = (cfg.get("app_label") or "")[:10]
    lbl_color = cfg.get("app_label_color") or "#f59e0b"

    lbl_preview = (
        f'<span style="background:{_html.escape(lbl_color)};color:#fff;'
        f'font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;'
        f'letter-spacing:.07em;text-transform:uppercase;" id="lbl-preview">'
        f'{_html.escape(app_label) or "PREVIEW"}</span>'
    )

    return f"""
    <div class="acc" data-tab="system" id="acc-appearance">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-appearance-body')">
        <span>{t('admin.acc_appearance')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-appearance-body">
        <div class="acc-inner">
          <form method="post" action="/admin/appearance" id="appearance-form">

            <!-- App-Farben -->
            <div style="font-size:13px;font-weight:700;margin-bottom:12px;">{t('admin.appearance_colors')}</div>

            <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;">
              <div>
                <label style="font-size:12px;">{t('admin.appearance_accent')}</label>
                <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
                  <input type="color" name="accent_color" id="inp-accent" value="{_html.escape(accent)}"
                    style="width:44px;height:36px;padding:2px;border-radius:6px;cursor:pointer;border:1px solid var(--bd);"
                    oninput="applyPreview()">
                  <input type="text" id="inp-accent-txt" value="{_html.escape(accent)}"
                    style="width:90px;font-size:13px;padding:5px 8px;"
                    oninput="syncColor('inp-accent','inp-accent-txt')">
                </div>
              </div>
              <div>
                <label style="font-size:12px;">{t('admin.appearance_nav')}</label>
                <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
                  <input type="color" name="nav_color" id="inp-nav" value="{_html.escape(nav_color) or '#f9fafb'}"
                    style="width:44px;height:36px;padding:2px;border-radius:6px;cursor:pointer;border:1px solid var(--bd);"
                    oninput="applyPreview()">
                  <input type="text" id="inp-nav-txt" value="{_html.escape(nav_color)}"
                    style="width:90px;font-size:13px;padding:5px 8px;"
                    placeholder="{t('admin.appearance_preset_default')}"
                    oninput="syncColor('inp-nav','inp-nav-txt')">
                </div>
              </div>
            </div>

            <!-- Schnellauswahl -->
            <div style="margin-bottom:14px;">
              <label style="font-size:12px;margin-bottom:6px;display:block;">{t('admin.appearance_presets')}</label>
              <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <button type="button" class="btn btn-sm"
                  onclick="setPreset('#2563eb','','','#f59e0b')"
                  style="border-left:4px solid #2563eb;">{t('admin.appearance_preset_default')}</button>
                <button type="button" class="btn btn-sm"
                  onclick="setPreset('#16a34a','#f0fdf4','PROD','#16a34a')"
                  style="border-left:4px solid #16a34a;">{t('admin.appearance_preset_prod')}</button>
                <button type="button" class="btn btn-sm"
                  onclick="setPreset('#ea580c','#fff7ed','DEV','#ea580c')"
                  style="border-left:4px solid #ea580c;">{t('admin.appearance_preset_dev')}</button>
                <button type="button" class="btn btn-sm"
                  onclick="setPreset('#7c3aed','#faf5ff','TEST','#7c3aed')"
                  style="border-left:4px solid #7c3aed;">{t('admin.appearance_preset_test')}</button>
              </div>
            </div>

            <hr style="margin:14px 0;">

            <!-- App-Label -->
            <div style="font-size:13px;font-weight:700;margin-bottom:12px;">{t('admin.appearance_label_section')}</div>
            <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-end;margin-bottom:12px;">
              <div>
                <label style="font-size:12px;">{t('admin.appearance_label_text')} <span style="font-weight:400;color:var(--mu);">{t('admin.appearance_label_hint')}</span></label>
                <input type="text" name="app_label" id="inp-label" maxlength="10"
                  value="{_html.escape(app_label)}"
                  placeholder="z. B. DEV, TEST, STAGING"
                  style="font-size:13px;padding:5px 8px;"
                  oninput="updateLabelPreview()">
              </div>
              <div>
                <label style="font-size:12px;">{t('admin.appearance_label_color')}</label>
                <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
                  <input type="color" name="app_label_color" id="inp-lbl-color"
                    value="{_html.escape(lbl_color)}"
                    style="width:44px;height:36px;padding:2px;border-radius:6px;cursor:pointer;border:1px solid var(--bd);"
                    oninput="updateLabelPreview()">
                  <input type="text" id="inp-lbl-color-txt" value="{_html.escape(lbl_color)}"
                    style="width:90px;font-size:13px;padding:5px 8px;"
                    oninput="syncColor('inp-lbl-color','inp-lbl-color-txt');updateLabelPreview()">
                </div>
              </div>
              <div style="padding-bottom:4px;">
                <label style="font-size:12px;">{t('admin.appearance_preview')}</label>
                <div style="margin-top:6px;background:var(--nav-bg);border:1px solid var(--bd);border-radius:6px;padding:6px 10px;display:inline-flex;align-items:center;gap:8px;">
                  <span style="font-size:13px;font-weight:700;">Zeiterfassung</span>
                  {lbl_preview}
                </div>
              </div>
            </div>

            <hr style="margin:14px 0;">

            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
              <button class="btn btn-sm" type="button"
                onclick="setPreset('#2563eb','','','#f59e0b');document.getElementById('inp-label').value='';updateLabelPreview();document.getElementById('appearance-form').submit();">
                {t('admin.appearance_reset')}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
<script>
function applyPreview(){{
  var ac=document.getElementById('inp-accent');
  var nav=document.getElementById('inp-nav');
  if(ac)document.getElementById('inp-accent-txt').value=ac.value;
  if(nav)document.getElementById('inp-nav-txt').value=nav.value;
  if(ac)document.documentElement.style.setProperty('--ac',ac.value);
  if(nav)document.documentElement.style.setProperty('--nav-bg',nav.value||'var(--sf)');
}}
function syncColor(pickerId,textId){{
  var txt=document.getElementById(textId);
  var m=txt.value.match(/^#[0-9a-fA-F]{{3,8}}$/);
  if(m){{document.getElementById(pickerId).value=txt.value.slice(0,7);}}
  applyPreview();
}}
function setPreset(accent,nav,label,lblColor){{
  var ai=document.getElementById('inp-accent');
  var ni=document.getElementById('inp-nav');
  var li=document.getElementById('inp-label');
  var lc=document.getElementById('inp-lbl-color');
  if(ai){{ai.value=accent;document.getElementById('inp-accent-txt').value=accent;}}
  if(ni){{ni.value=nav||'#f9fafb';document.getElementById('inp-nav-txt').value=nav;}}
  if(li)li.value=label||'';
  if(lc){{lc.value=lblColor;document.getElementById('inp-lbl-color-txt').value=lblColor;}}
  applyPreview();
  updateLabelPreview();
}}
function updateLabelPreview(){{
  var txt=document.getElementById('inp-label');
  var clr=document.getElementById('inp-lbl-color');
  var prev=document.getElementById('lbl-preview');
  if(!prev)return;
  var label=(txt?txt.value:'').trim().toUpperCase()||'VORSCHAU';
  prev.textContent=label;
  if(clr)prev.style.background=clr.value;
}}
</script>"""


_MONTH_NAMES = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
                "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _get_staffing_week_data(plan_id: int) -> dict:
    today    = datetime.date.today()
    week_arg = request.args.get("week", "")
    try:
        monday = datetime.date.fromisoformat(week_arg) if week_arg else None
    except ValueError:
        monday = None
    if monday is None:
        monday = today - datetime.timedelta(days=today.weekday())

    days = [monday + datetime.timedelta(days=i) for i in range(5)]

    db = connect()
    slots = db.execute(
        "SELECT * FROM staffing_slots WHERE plan_id=? ORDER BY COALESCE(time_from,'99:99'), sort_order",
        (plan_id,)
    ).fetchall()
    assignments = db.execute("""
        SELECT sa.*, u.username, u.display_name
        FROM staffing_assignments sa
        JOIN users u ON u.id = sa.user_id
        WHERE sa.slot_id IN (SELECT id FROM staffing_slots WHERE plan_id=?)
    """, (plan_id,)).fetchall()

    assign_map = {}
    for a in assignments:
        assign_map.setdefault(a["slot_id"], []).append(a)

    user_ids = list({a["user_id"] for a in assignments})
    absences = []
    if user_ids:
        ph     = ",".join("?" * len(user_ids))
        d_from = days[0].isoformat()
        d_to   = days[-1].isoformat()
        absences = db.execute(
            f"SELECT user_id, date_from, date_to FROM absences "
            f"WHERE user_id IN ({ph}) AND date_from <= ? AND date_to >= ?",
            (*user_ids, d_to, d_from)
        ).fetchall()
    try:
        _plan_row = db.execute("SELECT lead_label FROM staffing_plans WHERE id=?", (plan_id,)).fetchone()
        lead_label = (_plan_row["lead_label"] if _plan_row and _plan_row["lead_label"] else None) or "Leiter"
    except Exception:
        lead_label = "Leiter"
    db.close()

    _voc_cache_w: dict = {}

    def is_absent(uid, iso):
        if any(
            ab["user_id"] == uid and ab["date_from"] <= iso <= ab["date_to"]
            for ab in absences
        ):
            return True
        key = (uid, iso)
        if key not in _voc_cache_w:
            voc = _get_vocational_school_entry(uid, iso)
            is_voc_active = False
            if voc and not _is_holiday(iso, uid):
                if voc["schedule_type"] == "weekly" and _is_school_holiday(iso, uid):
                    is_voc_active = False  # Schulferien → Berufsschule entfällt
                else:
                    is_voc_active = True
            _voc_cache_w[key] = bool(
                is_voc_active and not (voc.get("work_time_from") and voc.get("work_time_to"))
            )
        return _voc_cache_w[key]

    result = {"monday": monday, "days": days, "slots": [], "lead_label": lead_label}
    for slot in slots:
        slot_days = []
        tf = slot["time_from"]
        tt = slot["time_to"]
        for day in days:
            iso = day.isoformat()
            if not _slot_applies_on_date(slot, iso, plan_id=plan_id):
                slot_days.append(None)
                continue
            assigned_list = assign_map.get(slot["id"], [])
            present = []
            absent  = []
            for a in assigned_list:
                uid = a["user_id"]
                if is_absent(uid, iso):
                    absent.append(a)
                elif tf and tt:
                    if _user_works_in_slot(uid, iso, tf, tt):
                        present.append(a)
                else:
                    present.append(a)
            count         = len(present)
            min_s         = slot["min_staff"]
            min_l         = int(slot["min_lead"] or 0)
            lead_present  = [a for a in present if int(a["is_lead"] or 0)]
            staff_present = [a for a in present if not int(a["is_lead"] or 0)]
            lead_missing  = (min_l > 0 and len(lead_present) == 0)
            lead_ok       = len(lead_present) >= min_l if min_l > 0 else True
            status        = "ok" if (count >= min_s and lead_ok) else ("warn" if count > 0 else "empty")
            slot_days.append({
                "present":       present,
                "lead_present":  lead_present,
                "staff_present": staff_present,
                "absent":        absent,
                "count":         count,
                "min_staff":     min_s,
                "min_lead":      min_l,
                "lead_missing":  lead_missing,
                "status":        status,
                "slot_role":     slot["slot_role"] or "staff",
            })
        result["slots"].append({"slot": slot, "days": slot_days})
    return result


def _get_staffing_month_data(plan_id: int) -> dict:
    today = datetime.date.today()
    year  = request.args.get("y", type=int, default=today.year)
    month = request.args.get("m", type=int, default=today.month)

    days_in_month = calendar.monthrange(year, month)[1]
    days = [datetime.date(year, month, d) for d in range(1, days_in_month + 1)]

    db = connect()
    slots = db.execute(
        "SELECT * FROM staffing_slots WHERE plan_id=? ORDER BY COALESCE(time_from,'99:99'), sort_order",
        (plan_id,)
    ).fetchall()
    assignments = db.execute("""
        SELECT sa.*, u.username, u.display_name
        FROM staffing_assignments sa
        JOIN users u ON u.id = sa.user_id
        WHERE sa.slot_id IN (SELECT id FROM staffing_slots WHERE plan_id=?)
    """, (plan_id,)).fetchall()

    assign_map = {}
    for a in assignments:
        assign_map.setdefault(a["slot_id"], []).append(a)

    user_ids = list({a["user_id"] for a in assignments})
    absences = []
    if user_ids:
        ph     = ",".join("?" * len(user_ids))
        d_from = days[0].isoformat()
        d_to   = days[-1].isoformat()
        absences = db.execute(
            f"SELECT user_id, date_from, date_to FROM absences "
            f"WHERE user_id IN ({ph}) AND date_from <= ? AND date_to >= ?",
            (*user_ids, d_to, d_from)
        ).fetchall()
    # Accepted dates – query before closing connection
    try:
        _acc_rows = db.execute(
            "SELECT iso_date FROM staffing_day_accepted WHERE plan_id=? "
            "AND iso_date BETWEEN ? AND ?",
            (plan_id, days[0].isoformat(), days[-1].isoformat())
        ).fetchall()
        accepted_dates = {r["iso_date"] for r in _acc_rows}
    except Exception:
        accepted_dates = set()
    try:
        _plan_row_m = db.execute("SELECT lead_label FROM staffing_plans WHERE id=?", (plan_id,)).fetchone()
        lead_label_m = (_plan_row_m["lead_label"] if _plan_row_m and _plan_row_m["lead_label"] else None) or "Leiter"
    except Exception:
        lead_label_m = "Leiter"
    db.close()

    _voc_cache_m: dict = {}

    def is_absent(uid, iso):
        if any(
            ab["user_id"] == uid and ab["date_from"] <= iso <= ab["date_to"]
            for ab in absences
        ):
            return True
        key = (uid, iso)
        if key not in _voc_cache_m:
            voc = _get_vocational_school_entry(uid, iso)
            is_voc_active = False
            if voc and not _is_holiday(iso, uid):
                if voc["schedule_type"] == "weekly" and _is_school_holiday(iso, uid):
                    is_voc_active = False  # Schulferien → Berufsschule entfällt
                else:
                    is_voc_active = True
            _voc_cache_m[key] = bool(
                is_voc_active and not (voc.get("work_time_from") and voc.get("work_time_to"))
            )
        return _voc_cache_m[key]

    result = {"year": year, "month": month, "days": [], "accepted_dates": accepted_dates,
              "lead_label": lead_label_m}
    for day in days:
        iso = day.isoformat()
        day_slots = []
        has_warning = False
        for slot in slots:
            if not _slot_applies_on_date(slot, iso, plan_id=plan_id):
                continue
            assigned_list = assign_map.get(slot["id"], [])
            tf = slot["time_from"]
            tt = slot["time_to"]
            present_count = 0
            lead_count    = 0
            for a in assigned_list:
                uid = a["user_id"]
                if is_absent(uid, iso):
                    continue
                if tf and tt:
                    if _user_works_in_slot(uid, iso, tf, tt):
                        present_count += 1
                        if int(a["is_lead"] or 0):
                            lead_count += 1
                else:
                    present_count += 1
                    if int(a["is_lead"] or 0):
                        lead_count += 1
            min_s        = slot["min_staff"]
            min_l        = int(slot["min_lead"] or 0)
            lead_missing = (min_l > 0 and lead_count == 0)
            lead_ok      = lead_count >= min_l if min_l > 0 else True
            status       = "ok" if (present_count >= min_s and lead_ok) else ("warn" if present_count > 0 else "empty")
            if status != "ok" or lead_missing:
                has_warning = True
            day_slots.append({"label": slot["label"], "count": present_count,
                               "min_staff": min_s, "status": status,
                               "time_from": slot["time_from"], "time_to": slot["time_to"],
                               "slot_role": slot["slot_role"] or "staff",
                               "lead_missing": lead_missing})
        result["days"].append({"date": day, "iso": iso,
                                "slots": day_slots, "has_warning": has_warning})
    return result


def _render_staffing_week(data: dict, plan_id: int) -> str:
    monday = data["monday"]
    days   = data["days"]
    today  = datetime.date.today()
    lead_label = data.get("lead_label", "Leiter")

    prev_mon = (monday - datetime.timedelta(days=7)).isoformat()
    next_mon = (monday + datetime.timedelta(days=7)).isoformat()
    this_mon = (today - datetime.timedelta(days=today.weekday())).isoformat()
    kw       = monday.isocalendar()[1]
    d_from   = monday.strftime("%d.%m")
    d_to     = (monday + datetime.timedelta(days=4)).strftime("%d.%m.%Y")

    nav = (
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;flex-wrap:wrap;">'
        f'<a href="/staffing?plan_id={plan_id}&view=week&week={prev_mon}" class="btn btn-sm">◀</a>'
        f'<strong>KW {kw} &nbsp;{d_from}–{d_to}</strong>'
        f'<a href="/staffing?plan_id={plan_id}&view=week&week={next_mon}" class="btn btn-sm">▶</a>'
        f'<a href="/staffing?plan_id={plan_id}&view=week&week={this_mon}" class="btn btn-sm">Heute</a>'
        f'</div>'
    )

    _WD = ["Mo", "Di", "Mi", "Do", "Fr"]
    _SI = {"ok": "✅", "warn": "⚠️", "empty": "❌"}
    _SC = {"ok": "#16a34a", "warn": "#d97706", "empty": "#dc2626"}

    th = "<th style='padding:6px 10px;text-align:left;border-bottom:2px solid rgba(128,128,128,0.5);background:var(--ca);'></th>"
    _hol_cache = {day.isoformat(): _is_holiday_for_plan(day.isoformat(), plan_id) for day in days}
    _hol_names = {}
    try:
        _hdb = connect()
        _hregion = _get_team_holiday_region(plan_id)
        for _d in days:
            _iso = _d.isoformat()
            _hr = _hdb.execute(
                "SELECT name FROM calendar_days WHERE day=? AND region=? AND is_holiday=1",
                (_iso, _hregion)
            ).fetchone()
            if _hr:
                _hol_names[_iso] = _hr["name"]
        _hdb.close()
    except Exception:
        pass
    for day in days:
        _day_iso = day.isoformat()
        _is_hol = _hol_cache.get(_day_iso, False)
        if _is_hol:
            today_bg = "background:color-mix(in srgb,#dc2626 8%,var(--ca));"
            _date_style = "color:#dc2626;font-weight:700;"
            _hol_hint = f"<div style='font-size:10px;color:#dc2626;'>{_html.escape(_hol_names.get(_day_iso,'Feiertag'))}</div>"
        elif day == today:
            today_bg = "background:color-mix(in srgb,var(--ac) 12%,var(--ca));"
            _date_style = ""
            _hol_hint = ""
        else:
            today_bg = "background:var(--ca);"
            _date_style = ""
            _hol_hint = ""
        th += (f"<th style='padding:6px 10px;text-align:center;white-space:nowrap;"
               f"border-bottom:2px solid rgba(128,128,128,0.5);border-left:2px solid rgba(128,128,128,0.35);cursor:pointer;{today_bg}' "
               f"onclick=\"location.href='/staffing/day?date={_day_iso}&plan_id={plan_id}'\">"
               f"<span style='{_date_style}'>{_WD[day.weekday()]} {day.strftime('%d.%m')}</span>{_hol_hint}</th>")

    rows = ""
    for slot_idx, entry in enumerate(data["slots"]):
        slot = entry["slot"]
        row_bg = "background:var(--bg);" if slot_idx % 2 == 0 else "background:color-mix(in srgb,var(--ca) 50%,var(--bg));"
        _slot_time_div = (
            f"<div style='font-size:10px;color:var(--mu);margin-top:2px;'>{slot['time_from']}–{slot['time_to']}</div>"
            if slot["time_from"] and slot["time_to"] else ""
        )
        _min_lead_hint = (
            f'<span style="font-size:10px;color:#eab308;margin-left:4px;" '
            f'title="{_html.escape(lead_label)}">♦≥{slot["min_lead"]}</span>'
            if int(slot["min_lead"] or 0) > 0 else ""
        )
        cells = (
            f"<td style='padding:6px 10px;font-size:13px;"
            f"border-right:2px solid var(--br);min-width:120px;background:var(--ca);'>"
            f"<div><strong>{_html.escape(slot['label'])}</strong>{_min_lead_hint}</div>"
            f"{_slot_time_div}"
            f"<div style='font-size:11px;color:var(--mu);'>{slot['slot_type'].upper()}</div></td>"
        )
        for di, day_data in enumerate(entry["days"]):
            day_iso   = days[di].isoformat()
            _r_border = "" if di == 4 else "border-right:2px solid rgba(128,128,128,0.35);"
            _hol_bg   = "background:color-mix(in srgb,#6b7280 15%,var(--bg));" if _hol_cache.get(day_iso) else row_bg
            if day_data is None:
                cells += (f"<td style='padding:6px 10px;{_hol_bg}{_r_border}cursor:pointer;'"
                          f" onclick=\"location.href='/staffing/day?date={day_iso}&plan_id={plan_id}'\"></td>")
                continue
            status    = day_data["status"]
            color     = "#dc2626" if day_data.get("lead_missing") else _SC[status]
            _badge_bg = {"ok": "#16a34a", "warn": "#d97706", "empty": "#dc2626"}[status]
            lead_html = " ".join(
                f'<span style="background:#eab308;color:#000;border-radius:3px;'
                f'padding:1px 5px;font-size:11px;white-space:nowrap;"'
                f' title="{_html.escape(lead_label)}: {_html.escape((a["display_name"] or a["username"] or "?"))}">'
                f'♦ {_html.escape((a["display_name"] or a["username"] or "?")[:8])}</span>'
                for a in day_data.get("lead_present", [])
            )
            staff_html = " ".join(
                f'<span style="background:#16a34a;color:#fff;border-radius:3px;'
                f'padding:1px 5px;font-size:11px;white-space:nowrap;">'
                f'{_html.escape((a["display_name"] or a["username"] or "?")[:10])}</span>'
                for a in day_data.get("staff_present", [])
            )
            def _absent_badge(a):
                return (
                    f'<span style="background:#dc2626;color:#fff;border-radius:3px;'
                    f'padding:1px 5px;font-size:11px;text-decoration:line-through;white-space:nowrap;">'
                    f'{_html.escape((a["display_name"] or a["username"] or "?")[:10])}</span>'
                )
            lead_absent_html = " ".join(
                _absent_badge(a) for a in day_data["absent"]
                if int(a["is_lead"] or 0)
            )
            staff_absent_html = " ".join(
                _absent_badge(a) for a in day_data["absent"]
                if not int(a["is_lead"] or 0)
            )
            _lead_warn = (
                f'<div style="font-size:11px;color:#dc2626;margin-top:2px;">'
                f'⚠️ Kein {_html.escape(lead_label)} anwesend</div>'
                if day_data.get("lead_missing") else ""
            )
            _lead_row = (
                f'<div style="display:flex;flex-wrap:wrap;gap:3px;">'
                f'{lead_html}{lead_absent_html}</div>'
                if (lead_html or lead_absent_html) else ""
            )
            _staff_row = (
                f'<div style="display:flex;flex-wrap:wrap;gap:3px;margin-top:2px;">'
                f'{staff_html}{staff_absent_html}</div>'
                if (staff_html or staff_absent_html) else ""
            )
            cells += (
                f"<td style='padding:6px 10px;border-left:3px solid {color};{_r_border}{_hol_bg}cursor:pointer;'"
                f" onclick=\"location.href='/staffing/day?date={day_iso}&plan_id={plan_id}'\">"
                f'<div style="display:inline-block;background:{_badge_bg};color:#fff;'
                f'border-radius:4px;padding:1px 7px;font-size:12px;font-weight:700;margin-bottom:4px;">'
                f'{day_data["count"]}/{day_data["min_staff"]} {_SI[status]}</div>'
                f'{_lead_row}{_staff_row}'
                f'{_lead_warn}'
                f'</td>'
            )
        rows += f"<tr style='border-bottom:1px solid rgba(128,128,128,0.2);'>{cells}</tr>"

    if not rows:
        rows = f"<tr><td colspan='6' style='padding:1rem;color:var(--mu);'>{t('staffing.no_slots')}</td></tr>"

    return f"""{nav}
    <div style="overflow-x:auto;">
      <div style="border:2px solid rgba(128,128,128,0.35);border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <thead><tr>{th}</tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>"""


def _render_staffing_month(data: dict, plan_id: int) -> str:
    year  = data["year"]
    month = data["month"]
    today = datetime.date.today()
    lead_label = data.get("lead_label", "Leiter")

    prev_y, prev_m = (year, month - 1) if month > 1 else (year - 1, 12)
    next_y, next_m = (year, month + 1) if month < 12 else (year + 1, 1)

    nav = (
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">'
        f'<a href="/staffing?plan_id={plan_id}&view=month&y={prev_y}&m={prev_m}" class="btn btn-sm">◀</a>'
        f'<strong>{_MONTH_NAMES[month]} {year}</strong>'
        f'<a href="/staffing?plan_id={plan_id}&view=month&y={next_y}&m={next_m}" class="btn btn-sm">▶</a>'
        f'</div>'
    )

    wd_headers = "".join(
        f'<th style="padding:4px 6px;font-size:12px;color:var(--mu);text-align:center;'
        f'font-weight:600;">{d}</th>'
        for d in ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    )

    first_wd = data["days"][0]["date"].weekday()
    tds = ["<td></td>"] * first_wd
    accepted_dates = data.get("accepted_dates", set())

    _SI = {"ok": "✅", "warn": "⚠️", "empty": "❌"}

    def _slot_badge_color(status):
        if status == "ok":   return "#16a34a"
        if status == "warn": return "#d97706"
        return "#dc2626"

    for day_data in data["days"]:
        day  = day_data["date"]
        iso  = day_data["iso"]
        is_we     = day.weekday() >= 5
        is_today  = day == today
        warn      = day_data["has_warning"]
        is_accepted = iso in accepted_dates
        if warn and not is_accepted:
            any_empty = any(s["status"] == "empty" or s.get("lead_missing") for s in day_data["slots"])
            border = "border:2px solid #dc2626;background:rgba(220,38,38,0.05);" if any_empty \
                     else "border:2px solid #d97706;background:rgba(217,119,6,0.05);"
        elif is_accepted and warn:
            border = "border:1px solid #16a34a;background:rgba(22,163,74,0.04);"
        else:
            border = "border:1px solid var(--br);"
        bg        = "background:var(--ca);" if is_we else ""
        today_ol  = "outline:2px solid var(--ac);outline-offset:-2px;" if is_today else ""
        accepted_badge = '<span style="float:right;font-size:9px;color:#16a34a;font-weight:700;">✓</span>' if is_accepted else ""

        slot_lines = ""
        for s in day_data["slots"]:
            slot_lines += (
                f'<div style="font-size:10px;line-height:1.6;white-space:nowrap;'
                f'color:{_slot_badge_color(s["status"])};font-weight:600;">'
                f'{_html.escape(s["label"])} '
                f'{s["count"]}/{s["min_staff"]} {_SI[s["status"]]}'
                f'</div>'
            )
            if s.get("lead_missing"):
                slot_lines += (
                    f'<div style="font-size:9px;color:#dc2626;white-space:nowrap;">'
                    f'⚠️ Kein {_html.escape(lead_label)}</div>'
                )
        tds.append(
            f'<td style="padding:4px;vertical-align:top;cursor:pointer;{border}{bg}{today_ol}'
            f"min-width:72px;\" onclick=\"location.href='/staffing/day?date={iso}&plan_id={plan_id}'\">"
            f'<div style="font-size:11px;font-weight:700;margin-bottom:2px;">'
            f'{day.day}{accepted_badge}</div>'
            f'{slot_lines}</td>'
        )

    # Pad to full weeks and build rows
    while len(tds) % 7:
        tds.append("<td style='background:var(--ca);'></td>")

    rows = ""
    for i in range(0, len(tds), 7):
        rows += "<tr>" + "".join(tds[i:i+7]) + "</tr>"

    return f"""{nav}
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;table-layout:fixed;">
        <thead><tr>{wd_headers}</tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


def _render_staffing_view(plans, plan_id, view, data, u) -> str:
    plan_opts = "".join(
        f'<option value="{p["id"]}"{"  selected" if p["id"] == plan_id else ""}>'
        f'{_html.escape(p["team_name"])} – {_html.escape(p["name"])}</option>'
        for p in plans
    )
    plan_selector = (
        f'<form method="get" action="/staffing" style="display:inline-flex;gap:6px;align-items:center;">'
        f'<select name="plan_id" onchange="this.form.submit()" style="font-size:13px;">'
        f'{plan_opts}</select>'
        f'<input type="hidden" name="view" value="{view}">'
        f'</form>'
    ) if plans else ""

    view_btns = (
        f'<a href="/staffing?plan_id={plan_id or ""}&view=week" '
        f'class="btn btn-sm{"  primary" if view=="week" else ""}">{t("staffing.week_view")}</a> '
        f'<a href="/staffing?plan_id={plan_id or ""}&view=month" '
        f'class="btn btn-sm{"  primary" if view=="month" else ""}">{t("staffing.month_view")}</a>'
    )

    if not plans:
        body_html = f'<p style="color:var(--mu);margin-top:1rem;">{t("staffing.no_plans")}</p>'
    elif view == "week":
        body_html = _render_staffing_week(data, plan_id)
    else:
        body_html = _render_staffing_month(data, plan_id)

    manage_link = ""
    if u.get("admin_role") in ("sysadmin", "timemanager", "hr"):
        manage_link = (
            f'<a href="/admin/staffing" class="btn btn-sm" style="margin-left:8px;">'
            f'⚙ {t("staffing.manage_plans")}</a>'
        )

    _is_readonly = u.get("admin_role") not in ("sysadmin", "timemanager", "hr") and not u.get("is_approver")
    readonly_hint = (
        f'<div class="small" style="color:var(--mu);margin-bottom:8px;">'
        f'ℹ {t("staffing.readonly_hint")}</div>'
    ) if _is_readonly else ""

    return f"""
    <div style="max-width:960px;margin:1rem auto;">
      <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:1.25rem;">
        <h2 style="margin:0;">{t('nav.staffing')}</h2>
        {plan_selector}
        <div style="display:flex;gap:4px;">{view_btns}</div>
        {manage_link}
      </div>
      {readonly_hint}
      {body_html}
    </div>"""


def _render_staffing_day(iso_date, d, plan, plan_id, slot_data,
                          team_users, absent_ids, absences,
                          overrides, accepted, u) -> str:
    _WD_NAMES = [t("wd.mon"), t("wd.tue"), t("wd.wed"), t("wd.thu"),
                 t("wd.fri"), t("wd.sat"), t("wd.sun")]
    prev_d   = (d - datetime.timedelta(days=1)).isoformat()
    next_d   = (d + datetime.timedelta(days=1)).isoformat()
    wd_name  = _WD_NAMES[d.weekday()]
    date_str = d.strftime("%d.%m.%Y")

    lead_label = (plan["lead_label"] if plan and "lead_label" in plan.keys() and plan["lead_label"] else "Leiter")

    # Pre-resolve all t() calls — avoids issues inside nested f-strings
    _lbl_present   = t("staffing.present")
    _lbl_absent    = t("staffing.absent")
    _lbl_override  = t("staffing.override_title")
    _lbl_assign    = t("staffing.override_assign")
    _lbl_request   = t("staffing.override_request")
    _lbl_confirm   = t("staffing.override_require_confirm")
    _lbl_note      = t("staffing.override_note")
    _lbl_dates     = t("staffing.override_dates")
    _lbl_accept    = t("staffing.accept_day")
    _lbl_acpt_note = t("staffing.accept_note")
    _lbl_acpt_bdg  = t("staffing.accepted_badge")

    def _row_name(a):
        return a["display_name"] or a["username"] or "?"

    def _row_uid(a):
        try:
            return a["user_id"]
        except (IndexError, KeyError):
            return None

    def _row_has(a, key):
        try:
            return bool(a[key])
        except (IndexError, KeyError):
            return False

    accepted_html = ""
    if accepted:
        note_txt = _html.escape(accepted["note"] or "")
        accepted_html = (
            f'<span style="background:#16a34a;color:#fff;border-radius:4px;'
            f'padding:2px 10px;font-size:12px;font-weight:600;">'
            f'{_lbl_acpt_bdg}'
            f'{(" – " + note_txt) if note_txt else ""}</span>'
        )
    else:
        has_warn = any(s["status"] != "ok" for s in slot_data)
        if has_warn:
            accepted_html = (
                f'<form method="post" action="/staffing/day/accept" style="display:inline;">'
                f'<input type="hidden" name="date" value="{iso_date}">'
                f'<input type="hidden" name="plan_id" value="{plan_id}">'
                f'<input type="text" name="note" placeholder="{_lbl_acpt_note}"'
                f' style="font-size:12px;padding:3px 8px;margin-right:4px;width:180px;">'
                f'<button class="btn btn-sm" type="submit"'
                f' style="background:#d97706;color:#fff;">{_lbl_accept}</button>'
                f'</form>'
            )

    absence_map = {}
    for ab in absences:
        absence_map[ab["user_id"]] = _html.escape(ab["typ"])

    _SI = {"ok": "✅", "warn": "⚠️", "empty": "❌"}
    _BC = {"ok": "#16a34a", "warn": "#d97706", "empty": "#dc2626"}

    slots_html = ""
    for sd in slot_data:
        slot     = sd["slot"]
        status   = sd["status"]
        count    = sd["count"]
        min_s    = sd["min_staff"]
        sid      = slot["id"]
        badge_bg = _BC[status]
        time_str = (f" {slot['time_from']}–{slot['time_to']}"
                    if slot["time_from"] and slot["time_to"] else "")

        present_rows = "".join(
            '<div style="padding:3px 0;display:flex;align-items:center;gap:6px;">'
            '<span style="background:#16a34a;color:#fff;border-radius:3px;'
            'padding:1px 6px;font-size:11px;">✓</span>'
            + _html.escape(_row_name(a))
            + (' <span style="font-size:10px;color:#a855f7;">⭐ Sonder</span>'
               if _row_has(a, "iso_date") else "")
            + '</div>'
            for a in sd["present"]
        ) or '<div style="color:var(--mu);font-size:12px;">–</div>'

        absent_rows = "".join(
            '<div style="padding:3px 0;display:flex;align-items:center;gap:6px;">'
            '<span style="background:#dc2626;color:#fff;border-radius:3px;'
            'padding:1px 6px;font-size:11px;">✗</span>'
            + _html.escape(_row_name(a))
            + f'<span style="font-size:10px;color:var(--mu);">'
              f'{absence_map.get(_row_uid(a) or 0, "")}</span>'
            + '</div>'
            for a in sd["absent"]
        ) if sd["absent"] else ""

        override_form = ""
        if status != "ok":
            present_uids = {_row_uid(a) for a in sd["present"]}
            avail_users = [
                u2 for u2 in team_users
                if u2["id"] not in absent_ids and u2["id"] not in present_uids
            ]
            user_opts = "".join(
                '<option value="' + str(u2["id"]) + '">'
                + _html.escape(u2["display_name"] or u2["username"]) + '</option>'
                for u2 in avail_users
            )
            day_checks = "".join(
                f'<label style="font-size:12px;display:flex;align-items:center;gap:3px;margin-right:6px;">'
                f'<input type="checkbox" name="dates"'
                f' value="{(d + datetime.timedelta(days=i)).isoformat()}"'
                f'{" checked" if i == 0 else ""}>'
                f'{_WD_NAMES[(d.weekday() + i) % 7]}'
                f' {(d + datetime.timedelta(days=i)).strftime("%d.%m")}'
                f'</label>'
                for i in range(7)
            )
            if avail_users:
                override_form = (
                    f'<div class="staff-section" style="margin-top:10px;padding-top:10px;'
                    f'border-top:1px solid var(--br);">'
                    f'<div style="font-size:11px;color:var(--mu);font-weight:600;margin-bottom:6px;">'
                    f'➕ {_lbl_override}</div>'
                    f'<form method="post" action="/staffing/day/override">'
                    f'<input type="hidden" name="date" value="{iso_date}">'
                    f'<input type="hidden" name="plan_id" value="{plan_id}">'
                    f'<input type="hidden" name="slot_id" value="{sid}">'
                    f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;align-items:flex-end;">'
                    f'<div><label style="font-size:11px;color:var(--mu);">Mitarbeiter</label>'
                    f'<select name="user_id" style="display:block;margin-top:3px;font-size:13px;">'
                    f'{user_opts}</select></div>'
                    f'<div><label style="font-size:11px;color:var(--mu);">{_lbl_note}</label>'
                    f'<input type="text" name="note" maxlength="120"'
                    f' style="display:block;margin-top:3px;font-size:13px;min-width:160px;"></div>'
                    f'</div>'
                    f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;">'
                    f'<span style="font-size:11px;color:var(--mu);margin-right:4px;">{_lbl_dates}:</span>'
                    f'{day_checks}</div>'
                    f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">'
                    f'<label style="font-size:12px;display:flex;align-items:center;gap:4px;">'
                    f'<input type="checkbox" name="require_confirm" value="1"'
                    f' id="req-{sid}" onchange="(function(c){{'
                    f'var b=document.getElementById(\'ob-{sid}\');'
                    f'if(b)b.textContent=c.checked?\'{_lbl_request}\':\'{_lbl_assign}\';}}'
                    f')(this)">'
                    f'{_lbl_confirm}</label>'
                    f'<button class="btn primary btn-sm" type="submit"'
                    f' id="ob-{sid}">{_lbl_assign}</button>'
                    f'</div></form></div>'
                )

        absent_section = (
            f'<div class="staff-section">'
            f'<div class="staff-section-hdr">🏖 {_lbl_absent}</div>'
            f'{absent_rows}</div>'
        ) if absent_rows else ""

        slots_html += (
            f'<div class="slot-day-card status-{status}">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;">'
            f'<strong style="font-size:14px;">{_html.escape(slot["label"])}</strong>'
            f'<span style="font-size:12px;color:var(--mu);">{time_str}</span>'
            f'<span style="background:{badge_bg};color:#fff;border-radius:4px;'
            f'padding:1px 8px;font-size:12px;font-weight:700;margin-left:auto;">'
            f'{count}/{min_s} {_SI[status]}</span></div>'
            f'<div class="staff-section">'
            f'<div class="staff-section-hdr">✅ {_lbl_present} ({count})</div>'
            f'{present_rows}</div>'
            f'{absent_section}'
            f'{override_form}'
            f'</div>'
        )

    return f"""
    <style>
    .slot-day-card{{border-radius:8px;padding:1rem;margin-bottom:1rem;border:2px solid;}}
    .slot-day-card.status-ok   {{border-color:#16a34a;background:rgba(22,163,74,.05);}}
    .slot-day-card.status-warn {{border-color:#d97706;background:rgba(217,119,6,.05);}}
    .slot-day-card.status-empty{{border-color:#dc2626;background:rgba(220,38,38,.05);}}
    .staff-section{{margin-top:.5rem;font-size:13px;}}
    .staff-section-hdr{{font-size:11px;color:var(--mu);margin-bottom:4px;font-weight:600;text-transform:uppercase;}}
    </style>
    <div style="max-width:700px;margin:1rem auto;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:1rem;flex-wrap:wrap;">
        <a href="/staffing/day?date={prev_d}&plan_id={plan_id}" class="btn btn-sm">◀</a>
        <div>
          <strong style="font-size:16px;">{wd_name}, {date_str}</strong>
          <span style="font-size:13px;color:var(--mu);margin-left:8px;">{_html.escape(plan['name'])}</span>
        </div>
        <a href="/staffing/day?date={next_d}&plan_id={plan_id}" class="btn btn-sm">▶</a>
        <a href="/staffing?plan_id={plan_id}&view=month" class="btn btn-sm" style="margin-left:4px;">↩</a>
        <div style="margin-left:auto;">{accepted_html}</div>
      </div>
      {slots_html if slots_html else f'<p style="color:var(--mu);">{t("staffing.no_slots")}</p>'}
    </div>"""


def _render_override_respond(pending, u) -> str:
    if not pending:
        return f'<div style="max-width:600px;margin:1rem auto;"><p style="color:var(--mu);">{t("staffing.no_pending_overrides")}</p></div>'

    rows = ""
    for o in pending:
        rows += f"""
        <div style="border:1px solid var(--br);border-radius:8px;padding:14px;margin-bottom:12px;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
            <div>
              <strong>{_html.escape(o["plan_name"])}</strong>
              <span style="color:var(--mu);font-size:13px;margin-left:8px;">
                {_html.escape(o["team_name"])}
              </span><br>
              <span style="font-size:13px;">{o["iso_date"]} · {_html.escape(o["slot_label"])}</span>
              {('<br><span style="font-size:12px;color:var(--mu);">' + _html.escape(o["note"]) + '</span>') if o["note"] else ""}
            </div>
            <div style="display:flex;gap:6px;">
              <form method="post" action="/staffing/override/respond">
                <input type="hidden" name="override_id" value="{o['id']}">
                <input type="hidden" name="action" value="confirm">
                <button class="btn primary btn-sm" type="submit">✓ {t('staffing.override_confirmed')}</button>
              </form>
              <form method="post" action="/staffing/override/respond">
                <input type="hidden" name="override_id" value="{o['id']}">
                <input type="hidden" name="action" value="decline">
                <button class="btn btn-sm" type="submit" style="color:#dc2626;">✗ {t('staffing.override_declined')}</button>
              </form>
            </div>
          </div>
        </div>"""

    return f"""
    <div style="max-width:600px;margin:1rem auto;">
      <h2 style="margin-bottom:1rem;">{t('staffing.my_overrides')}</h2>
      {rows}
    </div>"""


# ── Schulferien Admin ──────────────────────────────────────────────────────────

# ── DEV-Mode routes (only active when ZEITERFASSUNG_DEV_MODE=1) ──────────────







if __name__ == "__main__":
    app.run(debug=True)