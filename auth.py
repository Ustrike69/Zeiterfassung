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


def create_user(username: str, password: str, is_admin: bool = False, is_active: bool = True) -> int:
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
        "INSERT INTO users(username,password_hash,is_admin,is_active,updated_at) "
        "VALUES(?,?,?,?,datetime('now'))",
        (canonical, generate_password_hash(password), 1 if is_admin else 0, 1 if is_active else 0),
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
    import sqlite3
    uid = session.get("user_id")
    if not uid:
        return None
    db = connect()
    u = db.execute(
        "SELECT id, username, is_admin, is_active FROM users WHERE id=?",
        (uid,),
    ).fetchone()
    db.close()
    return dict(u) if u else None


def set_password(user_id: int, new_password: str) -> None:
    db = connect()
    db.execute(
        "UPDATE users SET password_hash=?, updated_at=datetime('now') WHERE id=?",
        (generate_password_hash(new_password), user_id),
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
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        u = current_user()
        if not u:
            return redirect(url_for("login", next=request.path))
        if not u.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)
    return wrapped
