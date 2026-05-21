import functools
from flask import session, redirect, url_for, request, abort
from werkzeug.security import generate_password_hash, check_password_hash
from db import connect


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
    if not any(c.isupper() for c in password):
        errors.append("Mindestens ein Großbuchstabe")
    if not any(c.islower() for c in password):
        errors.append("Mindestens ein Kleinbuchstabe")
    if not any(c.isdigit() for c in password):
        errors.append("Mindestens eine Ziffer")
    _specials = set(r"""!@#$%^&*()-_=+[]{}|;:'",.<>?/\`~""")
    if not any(c in _specials for c in password):
        errors.append("Mindestens ein Sonderzeichen")
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
    canonical = _username_canonical(username)
    if not canonical:
        return None
    db = connect()
    u = db.execute(
        "SELECT id, username, password_hash, is_admin, is_active FROM users WHERE LOWER(username)=?",
        (canonical,),
    ).fetchone()
    db.close()

    if not u:
        return None
    if not u["is_active"]:
        return None
    if not check_password_hash(u["password_hash"], password):
        return None
    return dict(u)


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    db = connect()
    u = db.execute(
        "SELECT id, username, is_admin, is_active, tracking_start_date, "
        "password_changed, onboarding_done, display_name, email, admin_role, "
        "must_change_password, admin_only, language FROM users WHERE id=?",
        (uid,),
    ).fetchone()
    db.close()
    return dict(u) if u else None


def is_sysadmin(u=None) -> bool:
    if u is None:
        u = current_user()
    return bool(u and u.get("admin_role") == "sysadmin")


def is_timemanager(u=None) -> bool:
    """True for any admin role (sysadmin or timemanager)."""
    if u is None:
        u = current_user()
    return bool(u and u.get("admin_role") in ("sysadmin", "timemanager"))


def set_admin_role(user_id: int, role) -> None:
    """Set admin_role and sync is_admin flag. role: 'sysadmin', 'timemanager', or None."""
    db = connect()
    db.execute(
        "UPDATE users SET admin_role=?, is_admin=?, updated_at=datetime('now') WHERE id=?",
        (role or None, 1 if role in ("sysadmin", "timemanager") else 0, user_id),
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
        "UPDATE users SET password_hash=?, password_changed=1, must_change_password=0, updated_at=datetime('now') WHERE id=?",
        (generate_password_hash(new_password), user_id),
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
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        u = current_user()
        if not u or not u.get("is_active"):
            session.clear()
            return redirect(url_for("login"))
        ep = request.endpoint
        if u.get("must_change_password") and ep not in ("change_password", "change_password_post"):
            return redirect(url_for("change_password"))
        if not u.get("must_change_password") and not u.get("onboarding_done") and ep not in ("onboarding", "onboarding_post"):
            return redirect(url_for("onboarding"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Allows both sysadmin and timemanager (any admin role)."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u:
            return redirect(url_for("login", next=request.path))
        if not u.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


# Alias – semantically clearer in route definitions
timemanager_required = admin_required


def sysadmin_required(view):
    """Allows only sysadmin role."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u:
            return redirect(url_for("login", next=request.path))
        if u.get("admin_role") != "sysadmin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped
