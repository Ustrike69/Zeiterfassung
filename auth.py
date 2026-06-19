import functools
import datetime
import uuid
import logging
from flask import session, redirect, url_for, request, abort
from werkzeug.security import generate_password_hash, check_password_hash
from db import connect
from zoneinfo import ZoneInfo

_LOGIN_MAX_ATTEMPTS = 3
_LOCK_MINUTES = 30
_UNLOCK_TOKEN_HOURS = 24


def _get_configured_timezone() -> ZoneInfo:
    try:
        db = connect()
        row = db.execute("SELECT value FROM app_config WHERE key='timezone'").fetchone()
        db.close()
        tz_str = (row["value"] if row else None) or "Europe/Berlin"
        return ZoneInfo(tz_str)
    except Exception:
        return ZoneInfo("Europe/Berlin")


def _now() -> datetime.datetime:
    return datetime.datetime.now(tz=_get_configured_timezone())


def has_users() -> bool:
    db = connect()
    r = db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    db.close()
    return r is not None


def _username_canonical(username: str) -> str:
    """Normalize username for case-insensitive comparison and storage."""
    return (username or "").strip().lower()


def validate_password(password: str, username: str = "") -> list:
    """Returns list of error strings; empty list = password is valid."""
    errors = []
    if len(password) < 10:
        errors.append("Mindestens 10 Zeichen")
    if not any(c.isupper() for c in password) or not any(c.islower() for c in password):
        errors.append("Groß- und Kleinbuchstaben erforderlich")
    if not any(c.isdigit() for c in password):
        errors.append("Mindestens eine Zahl erforderlich")
    if username and username.lower() in password.lower():
        errors.append("Passwort darf nicht den Benutzernamen enthalten")
    return errors


def create_user(
    username: str,
    password: str,
    is_admin: bool = False,
    is_active: bool = True,
    tracking_start_date: str = None,
    onboarding_done: int = 0,
) -> int:
    canonical = _username_canonical(username)
    if not canonical:
        raise ValueError("Username is required")
    db = connect()
    cur = db.cursor()
    existing = cur.execute(
        "SELECT id FROM users WHERE LOWER(username)=?",
        (canonical,),
    ).fetchone()
    if existing:
        db.close()
        raise ValueError("Username already exists")
    cur.execute(
        "INSERT INTO users(username,password_hash,is_admin,is_active,password_changed,"
        "onboarding_done,tracking_start_date,updated_at) "
        "VALUES(?,?,?,?,0,?,?,datetime('now'))",
        (
            canonical,
            generate_password_hash(password),
            1 if is_admin else 0,
            1 if is_active else 0,
            1 if onboarding_done else 0,
            tracking_start_date,
        ),
    )
    db.commit()
    user_id = cur.lastrowid
    db.close()
    return int(user_id)


def authenticate(username: str, password: str):
    """
    Returns (user_dict, error_code) where error_code is None on success or one of:
      'invalid', 'inactive', 'locked'
    """
    canonical = _username_canonical(username)
    if not canonical:
        return None, "invalid"
    db = connect()
    u = db.execute(
        "SELECT id, username, password_hash, is_admin, is_active, "
        "login_attempts, login_locked_until, email FROM users WHERE LOWER(username)=?",
        (canonical,),
    ).fetchone()
    db.close()

    if not u:
        return None, "invalid"
    if not u["is_active"]:
        return None, "inactive"

    # Check lockout
    locked_until_str = u["login_locked_until"]
    if locked_until_str:
        locked_until = datetime.datetime.fromisoformat(locked_until_str)
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=datetime.timezone.utc)
        if _now() < locked_until:
            return None, "locked"
        else:
            # Lock expired – clear it
            _clear_lockout(u["id"])

    if not check_password_hash(u["password_hash"], password):
        _record_failed_attempt(u["id"], u["email"] or "")
        return None, "invalid"

    # Success – reset counter, update last_login
    _record_success(u["id"])
    return dict(u), None


def get_lockout_until(username: str):
    """Return the locked_until datetime for a user, or None."""
    canonical = _username_canonical(username)
    if not canonical:
        return None
    db = connect()
    row = db.execute(
        "SELECT login_locked_until FROM users WHERE LOWER(username)=?", (canonical,)
    ).fetchone()
    db.close()
    if not row or not row["login_locked_until"]:
        return None
    try:
        dt = datetime.datetime.fromisoformat(row["login_locked_until"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(_get_configured_timezone())
    except Exception:
        return None


def _record_failed_attempt(user_id: int, email: str) -> None:
    db = connect()
    row = db.execute(
        "SELECT login_attempts FROM users WHERE id=?", (user_id,)
    ).fetchone()
    attempts = (row["login_attempts"] or 0) + 1 if row else 1

    if attempts >= _LOGIN_MAX_ATTEMPTS:
        locked_until = (_now() + datetime.timedelta(minutes=_LOCK_MINUTES)).isoformat()
        token = str(uuid.uuid4())
        db.execute(
            "UPDATE users SET login_attempts=?, login_locked_until=?, login_unlock_token=? WHERE id=?",
            (attempts, locked_until, token, user_id),
        )
        db.commit()
        db.close()
        if email:
            _send_lockout_mail(email, token, user_id)
    else:
        db.execute(
            "UPDATE users SET login_attempts=? WHERE id=?", (attempts, user_id)
        )
        db.commit()
        db.close()


def _record_success(user_id: int) -> None:
    db = connect()
    db.execute(
        "UPDATE users SET login_attempts=0, login_locked_until=NULL, login_unlock_token=NULL, "
        "last_login=datetime('now') WHERE id=?",
        (user_id,),
    )
    db.commit()
    db.close()


def _clear_lockout(user_id: int) -> None:
    db = connect()
    db.execute(
        "UPDATE users SET login_attempts=0, login_locked_until=NULL, login_unlock_token=NULL WHERE id=?",
        (user_id,),
    )
    db.commit()
    db.close()


def unlock_account(user_id: int) -> None:
    _clear_lockout(user_id)


def validate_unlock_token(token: str):
    """Return user dict if token is valid and not expired, else None."""
    if not token:
        return None
    db = connect()
    row = db.execute(
        "SELECT id, login_locked_until FROM users WHERE login_unlock_token=?", (token,)
    ).fetchone()
    db.close()
    if not row:
        return None
    if not row["login_locked_until"]:
        return None
    try:
        locked_until = datetime.datetime.fromisoformat(row["login_locked_until"])
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None
    # Token valid for UNLOCK_TOKEN_HOURS from lock time
    token_expiry = locked_until + datetime.timedelta(hours=_UNLOCK_TOKEN_HOURS)
    if _now() > token_expiry:
        return None
    return dict(row)


def _send_lockout_mail(email: str, token: str, user_id: int) -> None:
    """Fire-and-forget: send account lockout email."""
    try:
        import threading as _thr
        def _do():
            try:
                import app as _app_module
                with _app_module.app.app_context():
                    _dispatch_lockout_mail(email, token, user_id)
            except Exception as e:
                logging.getLogger(__name__).error(f"Unlock-Mail thread Fehler: {e}")
        _thr.Thread(target=_do, daemon=True).start()
    except Exception as e:
        logging.getLogger(__name__).error(f"Unlock-Mail start Fehler: {e}")


def _dispatch_lockout_mail(email: str, token: str, user_id: int) -> None:
    """Called inside app context. Imports app-level helpers."""
    import app as _app_module
    from translations import t as _t
    try:
        lang = "de"
        try:
            db = connect()
            urow = db.execute("SELECT language FROM users WHERE id=?", (user_id,)).fetchone()
            db.close()
            lang = (urow["language"] if urow and urow["language"] else None) or "de"
        except Exception:
            pass
        base_url = _app_module._get_base_url()
        unlock_url = f"{base_url}/login/unlock/{token}"
        subject = _t("mail.account_locked_subject", lang)
        body = (
            f"{_t('auth.account_locked_mail_intro', lang)}\n\n"
            f"{unlock_url}\n\n"
            f"{_t('auth.account_locked_mail_hint', lang)}"
        )
        _app_module._send_mail_simple(email, subject, body)
    except Exception as e:
        _app_module.app.logger.error(f"Unlock-Mail Fehler: {e}")


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    db = connect()
    u = db.execute(
        "SELECT id, username, is_admin, is_active, tracking_start_date, "
        "password_changed, onboarding_done, display_name, email, admin_role, "
        "must_change_password, admin_only, language, password_compliant, "
        "totp_enabled, login_attempts, last_login, is_approver, team_restriction, "
        "is_apprentice FROM users WHERE id=?",
        (uid,),
    ).fetchone()
    db.close()
    return dict(u) if u else None


def is_sysadmin(u=None) -> bool:
    if u is None:
        u = current_user()
    return bool(u and u.get("admin_role") == "sysadmin")


def is_timemanager(u=None) -> bool:
    """True for any admin role (sysadmin, timemanager, or hr)."""
    if u is None:
        u = current_user()
    return bool(u and u.get("admin_role") in ("sysadmin", "timemanager", "hr"))


def is_hr(u=None) -> bool:
    """True for sysadmin, timemanager, or hr role."""
    if u is None:
        u = current_user()
    return bool(u and u.get("admin_role") in ("sysadmin", "timemanager", "hr"))


def set_admin_role(user_id: int, role) -> None:
    """Set admin_role and sync is_admin flag. role: 'sysadmin', 'timemanager', 'hr', or None."""
    db = connect()
    db.execute(
        "UPDATE users SET admin_role=?, is_admin=?, updated_at=datetime('now') WHERE id=?",
        (role or None, 1 if role in ("sysadmin", "timemanager", "hr") else 0, user_id),
    )
    db.commit()
    db.close()


def set_active(user_id: int, is_active: bool) -> None:
    db = connect()
    db.execute(
        "UPDATE users SET is_active=?, updated_at=datetime('now') WHERE id=?",
        (1 if is_active else 0, user_id),
    )
    db.commit()
    db.close()


def set_password(user_id: int, new_password: str) -> None:
    db = connect()
    db.execute(
        "UPDATE users SET password_hash=?, password_changed=1, must_change_password=0, "
        "password_compliant=1, updated_at=datetime('now') WHERE id=?",
        (generate_password_hash(new_password), user_id),
    )
    db.commit()
    db.close()


def set_totp(user_id: int, secret_encrypted: str, backup_codes_json: str) -> None:
    db = connect()
    db.execute(
        "UPDATE users SET totp_secret=?, totp_enabled=1, totp_backup_codes=?, updated_at=datetime('now') WHERE id=?",
        (secret_encrypted, backup_codes_json, user_id),
    )
    db.commit()
    db.close()


def disable_totp(user_id: int) -> None:
    db = connect()
    db.execute(
        "UPDATE users SET totp_secret=NULL, totp_enabled=0, totp_backup_codes=NULL, updated_at=datetime('now') WHERE id=?",
        (user_id,),
    )
    db.commit()
    db.close()


def get_totp_row(user_id: int) -> dict:
    db = connect()
    row = db.execute(
        "SELECT totp_secret, totp_enabled, totp_backup_codes FROM users WHERE id=?", (user_id,)
    ).fetchone()
    db.close()
    return dict(row) if row else {}


def update_totp_backup_codes(user_id: int, backup_codes_json: str) -> None:
    db = connect()
    db.execute(
        "UPDATE users SET totp_backup_codes=?, updated_at=datetime('now') WHERE id=?",
        (backup_codes_json, user_id),
    )
    db.commit()
    db.close()


def set_language(user_id: int, lang: str) -> None:
    db = connect()
    db.execute(
        "UPDATE users SET language=?, updated_at=datetime('now') WHERE id=?",
        (lang, user_id),
    )
    db.commit()
    db.close()


def set_must_change_password(user_id: int, flag: bool) -> None:
    db = connect()
    db.execute(
        "UPDATE users SET must_change_password=?, updated_at=datetime('now') WHERE id=?",
        (1 if flag else 0, user_id),
    )
    db.commit()
    db.close()


def set_flags(user_id: int, is_admin: bool, is_active: bool) -> None:
    db = connect()
    db.execute(
        "UPDATE users SET is_admin=?, is_active=?, updated_at=datetime('now') WHERE id=?",
        (1 if is_admin else 0, 1 if is_active else 0, user_id),
    )
    db.commit()
    db.close()


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        # 2FA pending: redirect to 2FA page for all protected routes
        if session.get("awaiting_2fa") and not session.get("user_id"):
            ep = request.endpoint
            if ep not in ("auth_routes.login_2fa", "auth_routes.login_2fa_post"):
                return redirect(url_for("auth_routes.login_2fa"))
        if not session.get("user_id"):
            return redirect(url_for("auth_routes.login", next=request.path))
        u = current_user()
        if not u or not u.get("is_active"):
            session.clear()
            return redirect(url_for("auth_routes.login"))
        ep = request.endpoint
        need_pw_change = u.get("must_change_password") or not u.get("password_compliant")
        if need_pw_change and ep not in ("auth_routes.change_password", "auth_routes.change_password_post"):
            return redirect(url_for("auth_routes.change_password"))
        if not need_pw_change and not u.get("onboarding_done") and ep not in ("core.onboarding", "core.onboarding_post"):
            return redirect(url_for("core.onboarding"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Allows both sysadmin and timemanager (any admin role)."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u:
            return redirect(url_for("auth_routes.login", next=request.path))
        if not u.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


# Alias – semantically clearer in route definitions
timemanager_required = admin_required


def hr_required(f):
    """Allows sysadmin, timemanager, and hr roles."""
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u:
            return redirect(url_for("auth_routes.login"))
        if u.get("admin_role") not in ("sysadmin", "timemanager", "hr"):
            abort(403)
        return f(*args, **kwargs)
    return wrapped


def sysadmin_required(view):
    """Allows only sysadmin role."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u:
            return redirect(url_for("auth_routes.login", next=request.path))
        if u.get("admin_role") != "sysadmin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped
