import gzip
import io
import json
import os
import shutil
import datetime
from pathlib import Path

from db import db_path

import os as _os
BACKUPS_DIR = Path(_os.environ.get("BACKUPS_DIR", _os.path.join(_os.path.dirname(__file__), "backups")))

PASS_MASK = "********"


def _ensure_dir():
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


def create_backup_gz(dest_path: str = None):
    """
    Create a gzip-compressed backup of the DB.
    dest_path given → save there, return path string.
    dest_path None  → return (BytesIO, filename).
    """
    src = db_path()
    now = datetime.datetime.now()
    fname = f"zeiterfassung_full_{now.strftime('%Y-%m-%d_%H-%M')}.db.gz"

    buf = io.BytesIO()
    with open(src, "rb") as f_in:
        with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
            shutil.copyfileobj(f_in, gz)
    buf.seek(0)

    if dest_path:
        _ensure_dir()
        with open(dest_path, "wb") as f_out:
            f_out.write(buf.getvalue())
        return dest_path

    return buf, fname


def list_local_backups():
    """Return list of dicts {name, size, mtime} for each local backup, newest first."""
    _ensure_dir()
    files = []
    for f in sorted(BACKUPS_DIR.glob("*.db.gz"), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = f.stat()
        files.append({
            "name": f.name,
            "size": stat.st_size,
            "mtime": datetime.datetime.fromtimestamp(stat.st_mtime),
        })
    return files


def prune_backups(keep: int = 7):
    """Delete oldest backups, keeping the most recent `keep` files."""
    _ensure_dir()
    files = sorted(BACKUPS_DIR.glob("*.db.gz"), key=lambda x: x.stat().st_mtime, reverse=True)
    for f in files[keep:]:
        try:
            f.unlink()
        except Exception:
            pass


def restore_from_bytes(data: bytes, is_gz: bool) -> str:
    """
    Restore DB from raw bytes. Creates a pre-restore safety backup first.
    Returns the path of the pre-restore backup.
    """
    _ensure_dir()
    now = datetime.datetime.now()
    pre_path = str(BACKUPS_DIR / f"pre_restore_{now.strftime('%Y-%m-%d_%H-%M-%S')}.db.gz")
    create_backup_gz(dest_path=pre_path)

    if is_gz:
        with gzip.open(io.BytesIO(data)) as gz:
            raw = gz.read()
    else:
        raw = data

    src = db_path()
    with open(src, "wb") as f:
        f.write(raw)

    return pre_path


# ── Settings export / import ────────────────────────────────────────────────

def export_settings() -> tuple:
    """Export mail_config + bot_config as JSON. Passwords/keys are masked."""
    from db import connect
    db = connect()
    mail_rows = db.execute("SELECT key, value FROM mail_config").fetchall()
    bot_rows = db.execute("SELECT key, value FROM bot_config").fetchall()
    db.close()

    mail = {r["key"]: r["value"] for r in mail_rows}
    bot = {r["key"]: r["value"] for r in bot_rows}

    for k in ("mail_password",):
        if mail.get(k):
            mail[k] = PASS_MASK
    for k in ("anthropic_api_key", "bot_token"):
        if bot.get(k):
            bot[k] = PASS_MASK

    payload = {
        "_type": "zeiterfassung_settings",
        "_version": 1,
        "_exported_at": datetime.datetime.now().isoformat(),
        "_note": "Passwörter müssen nach Import neu gesetzt werden.",
        "mail_config": mail,
        "bot_config": bot,
    }

    fname = f"zeiterfassung_settings_{datetime.datetime.now().strftime('%Y-%m-%d')}.json"
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), fname


def import_settings(json_data: bytes) -> dict:
    """Import mail_config + bot_config from JSON. Skips masked values. Returns counts."""
    from db import connect
    data = json.loads(json_data)
    if data.get("_type") != "zeiterfassung_settings":
        raise ValueError("Ungültige Einstellungsdatei (falscher _type).")

    db = connect()
    counts = {"mail": 0, "bot": 0}

    for key, val in (data.get("mail_config") or {}).items():
        if val == PASS_MASK:
            continue
        db.execute(
            "INSERT OR REPLACE INTO mail_config(key, value, updated_at) VALUES(?, ?, datetime('now'))",
            (key, val),
        )
        counts["mail"] += 1

    for key, val in (data.get("bot_config") or {}).items():
        if val == PASS_MASK:
            continue
        db.execute(
            "INSERT OR REPLACE INTO bot_config(key, value, updated_at) VALUES(?, ?, datetime('now'))",
            (key, val),
        )
        counts["bot"] += 1

    db.commit()
    db.close()
    return counts


# ── User export / import ─────────────────────────────────────────────────────

def export_user_data(user_id: int) -> tuple:
    """Export all data for a single user as JSON."""
    from db import connect
    db = connect()

    user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        db.close()
        raise ValueError(f"User {user_id} nicht gefunden.")

    username = user["username"]

    def _rows(rows):
        return [dict(r) for r in rows]

    payload = {
        "_type": "zeiterfassung_user_export",
        "_version": 1,
        "_exported_at": datetime.datetime.now().isoformat(),
        "user": {
            "username": user["username"],
            "display_name": user["display_name"],
            "email": user["email"],
            "tracking_start_date": user["tracking_start_date"],
            "contouring_enabled": user["contouring_enabled"],
            "contouring_start_date": user["contouring_start_date"],
            "birth_date": user["birth_date"],
            "retirement_age": user["retirement_age"],
            "vacation_carryover_exception": user["vacation_carryover_exception"],
        },
        "time_blocks": _rows(db.execute(
            "SELECT day, time_in, time_out, break_minutes, comment FROM time_blocks "
            "WHERE user_id=? ORDER BY day, time_in", (user_id,)).fetchall()),
        "time_entries": _rows(db.execute(
            "SELECT day, time_in, time_out, break_minutes, comment FROM time_entries "
            "WHERE user_id=? ORDER BY day", (user_id,)).fetchall()),
        "absences": _rows(db.execute(
            "SELECT at.name AS type_name, a.date_from, a.date_to, a.is_half_day, a.comment "
            "FROM absences a JOIN absence_types at ON at.id=a.type_id "
            "WHERE a.user_id=? ORDER BY a.date_from", (user_id,)).fetchall()),
        "business_trips": _rows(db.execute(
            "SELECT start_date, end_date, destination, departure_time, departure_end_time, "
            "return_time, return_end_time, notes FROM business_trips "
            "WHERE user_id=? ORDER BY start_date", (user_id,)).fetchall()),
        "user_schedules": _rows(db.execute(
            "SELECT valid_from, mode, weekly_minutes, workdays_mask, mon_minutes, tue_minutes, "
            "wed_minutes, thu_minutes, fri_minutes, sat_minutes, sun_minutes, block_weekends_holidays "
            "FROM user_schedules WHERE user_id=? ORDER BY valid_from", (user_id,)).fetchall()),
        "vacation_carryover_overrides": _rows(db.execute(
            "SELECT year, carryover_days, valid_until, comment "
            "FROM vacation_carryover_overrides WHERE user_id=? ORDER BY year", (user_id,)).fetchall()),
        "contoured_days": _rows(db.execute(
            "SELECT day FROM contoured_days WHERE user_id=? ORDER BY day", (user_id,)).fetchall()),
    }

    db.close()
    fname = f"zeiterfassung_user_{username}_{datetime.datetime.now().strftime('%Y-%m-%d')}.json"
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), fname


def import_user_data(json_data: bytes, target_user_id: int) -> dict:
    """Import user data into an existing user. Returns summary of imported/skipped records."""
    from db import connect
    data = json.loads(json_data)
    if data.get("_type") != "zeiterfassung_user_export":
        raise ValueError("Ungültige User-Export-Datei (falscher _type).")

    db = connect()
    s = {"time_blocks": 0, "time_entries": 0, "absences": 0,
         "business_trips": 0, "schedules": 0, "skipped": 0}

    for r in data.get("time_blocks") or []:
        try:
            db.execute(
                "INSERT INTO time_blocks(user_id, day, time_in, time_out, break_minutes, comment) "
                "VALUES(?,?,?,?,?,?)",
                (target_user_id, r["day"], r["time_in"], r["time_out"],
                 r.get("break_minutes", 0), r.get("comment")),
            )
            s["time_blocks"] += 1
        except Exception:
            s["skipped"] += 1

    for r in data.get("time_entries") or []:
        try:
            db.execute(
                "INSERT OR IGNORE INTO time_entries(user_id, day, time_in, time_out, break_minutes, comment) "
                "VALUES(?,?,?,?,?,?)",
                (target_user_id, r["day"], r["time_in"], r["time_out"],
                 r.get("break_minutes", 0), r.get("comment")),
            )
            s["time_entries"] += 1
        except Exception:
            s["skipped"] += 1

    for r in data.get("absences") or []:
        try:
            type_row = db.execute(
                "SELECT id FROM absence_types WHERE name=?", (r["type_name"],)
            ).fetchone()
            if not type_row:
                type_row = db.execute(
                    "SELECT id FROM absence_types WHERE name='Sonstige'"
                ).fetchone()
            if type_row:
                db.execute(
                    "INSERT INTO absences(user_id, type_id, date_from, date_to, is_half_day, comment) "
                    "VALUES(?,?,?,?,?,?)",
                    (target_user_id, type_row["id"], r["date_from"], r["date_to"],
                     r.get("is_half_day", 0), r.get("comment")),
                )
                s["absences"] += 1
        except Exception:
            s["skipped"] += 1

    for r in data.get("business_trips") or []:
        try:
            db.execute(
                "INSERT OR IGNORE INTO business_trips(user_id, start_date, end_date, destination, "
                "departure_time, departure_end_time, return_time, return_end_time, notes) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (target_user_id, r["start_date"], r.get("end_date"), r["destination"],
                 r.get("departure_time"), r.get("departure_end_time"),
                 r.get("return_time"), r.get("return_end_time"), r.get("notes")),
            )
            s["business_trips"] += 1
        except Exception:
            s["skipped"] += 1

    for r in data.get("user_schedules") or []:
        try:
            db.execute(
                "INSERT OR IGNORE INTO user_schedules(user_id, valid_from, mode, weekly_minutes, "
                "workdays_mask, mon_minutes, tue_minutes, wed_minutes, thu_minutes, fri_minutes, "
                "sat_minutes, sun_minutes, block_weekends_holidays) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (target_user_id, r["valid_from"], r.get("mode", "weekly"),
                 r.get("weekly_minutes", 2400), r.get("workdays_mask", 31),
                 r.get("mon_minutes", 480), r.get("tue_minutes", 480),
                 r.get("wed_minutes", 480), r.get("thu_minutes", 480),
                 r.get("fri_minutes", 480), r.get("sat_minutes", 0),
                 r.get("sun_minutes", 0), r.get("block_weekends_holidays", 1)),
            )
            s["schedules"] += 1
        except Exception:
            s["skipped"] += 1

    for r in data.get("vacation_carryover_overrides") or []:
        try:
            db.execute(
                "INSERT OR IGNORE INTO vacation_carryover_overrides"
                "(user_id, year, carryover_days, valid_until, comment) VALUES(?,?,?,?,?)",
                (target_user_id, r["year"], r.get("carryover_days", 0),
                 r.get("valid_until"), r.get("comment")),
            )
        except Exception:
            s["skipped"] += 1

    for r in data.get("contoured_days") or []:
        try:
            db.execute(
                "INSERT OR IGNORE INTO contoured_days(user_id, day) VALUES(?,?)",
                (target_user_id, r["day"]),
            )
        except Exception:
            s["skipped"] += 1

    db.commit()
    db.close()
    return s
