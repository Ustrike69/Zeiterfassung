import sqlite3, os
from pathlib import Path

DB_FILENAME = os.environ.get("ZEITERFASSUNG_DB", "zeiterfassung.db")

def db_path():
    return str(Path(DB_FILENAME).resolve())

def connect():
    c = sqlite3.connect(db_path())
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def _col_exists(db, table, col):
    rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == col for r in rows)

def init_db():
    db = connect()
    db.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS calendar_days(
        day TEXT PRIMARY KEY,
        is_weekend INTEGER NOT NULL DEFAULT 0,
        is_holiday INTEGER NOT NULL DEFAULT 0,
        holiday_name TEXT,
        is_school_holiday INTEGER NOT NULL DEFAULT 0,
        school_holiday_name TEXT,
        region TEXT NOT NULL DEFAULT 'DE-NW',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_calendar_days_region ON calendar_days(region, day)")

    # migrations for older DBs
    if not _col_exists(db, "calendar_days", "is_weekend"):
        db.execute("ALTER TABLE calendar_days ADD COLUMN is_weekend INTEGER NOT NULL DEFAULT 0")

    # Drop legacy key_types table (no longer used)
    db.execute("DROP TABLE IF EXISTS key_types")

    # --- time entries (single per day; legacy) ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS time_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        time_in TEXT NOT NULL,
        time_out TEXT NOT NULL,
        break_minutes INTEGER NOT NULL DEFAULT 0,
        comment TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT,
        UNIQUE(user_id, day),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # --- time blocks (multiple per day) ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS time_blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        time_in TEXT NOT NULL,
        time_out TEXT NOT NULL,
        break_minutes INTEGER NOT NULL DEFAULT 0,
        comment TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_time_entries_user_day ON time_entries(user_id, day)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_time_blocks_user_day ON time_blocks(user_id, day)")

    # --- user schedule / work rules ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS user_schedule (
        user_id INTEGER PRIMARY KEY,
        mode TEXT NOT NULL DEFAULT 'weekly',            -- 'weekly' or 'daily'
        weekly_minutes INTEGER NOT NULL DEFAULT 2400,   -- 40:00
        workdays_mask INTEGER NOT NULL DEFAULT 31,      -- bitmask Mon..Sun (Mon=1, Tue=2, ..., Sun=64) default Mon-Fri
        mon_minutes INTEGER NOT NULL DEFAULT 480,
        tue_minutes INTEGER NOT NULL DEFAULT 480,
        wed_minutes INTEGER NOT NULL DEFAULT 480,
        thu_minutes INTEGER NOT NULL DEFAULT 480,
        fri_minutes INTEGER NOT NULL DEFAULT 480,
        sat_minutes INTEGER NOT NULL DEFAULT 0,
        sun_minutes INTEGER NOT NULL DEFAULT 0,
        block_weekends_holidays INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # --- user schedules (with validity date) ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS user_schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        valid_from TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'weekly',
        weekly_minutes INTEGER NOT NULL DEFAULT 2400,
        workdays_mask INTEGER NOT NULL DEFAULT 31,
        mon_minutes INTEGER NOT NULL DEFAULT 480,
        tue_minutes INTEGER NOT NULL DEFAULT 480,
        wed_minutes INTEGER NOT NULL DEFAULT 480,
        thu_minutes INTEGER NOT NULL DEFAULT 480,
        fri_minutes INTEGER NOT NULL DEFAULT 480,
        sat_minutes INTEGER NOT NULL DEFAULT 0,
        sun_minutes INTEGER NOT NULL DEFAULT 0,
        block_weekends_holidays INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT,
        UNIQUE(user_id, valid_from),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # --- absence types ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS absence_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        color TEXT DEFAULT '#0d6efd',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT
    );
    """)

    # --- absences ---
    db.execute("""
    CREATE TABLE IF NOT EXISTS absences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type_id INTEGER NOT NULL,
        date_from TEXT NOT NULL,
        date_to TEXT NOT NULL,
        is_half_day INTEGER NOT NULL DEFAULT 0,
        comment TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(type_id) REFERENCES absence_types(id)
    );
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_absences_user_from_to ON absences(user_id, date_from, date_to)")

    db.execute("""
    CREATE TABLE IF NOT EXISTS absence_remarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        remark TEXT NOT NULL,
        UNIQUE(user_id, remark),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # Rename legacy 'Sonstiges' → 'Sonstige'
    db.execute("UPDATE absence_types SET name='Sonstige', updated_at=datetime('now') WHERE name='Sonstiges'")

    # Ensure only the three fixed types exist; remap absences of other types to Sonstige then delete
    sonstige_row = db.execute("SELECT id FROM absence_types WHERE name='Sonstige'").fetchone()
    if sonstige_row:
        sonstige_id = sonstige_row["id"]
        others = db.execute(
            "SELECT id FROM absence_types WHERE name NOT IN ('Urlaub','Krank','Sonstige')"
        ).fetchall()
        for o in others:
            db.execute("UPDATE absences SET type_id=? WHERE type_id=?", (sonstige_id, o["id"]))
        if others:
            db.execute("DELETE FROM absence_types WHERE name NOT IN ('Urlaub','Krank','Sonstige')")

    db.execute("""
    CREATE TABLE IF NOT EXISTS business_trips (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT,
        destination TEXT NOT NULL,
        departure_time TEXT,
        departure_end_time TEXT,
        return_time TEXT,
        return_end_time TEXT,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT,
        UNIQUE(user_id, start_date),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_business_trips_user_date ON business_trips(user_id, start_date)")

    db.execute("""
    CREATE TABLE IF NOT EXISTS period_locks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        period_type TEXT NOT NULL CHECK(period_type IN ('month','year')),
        year INTEGER NOT NULL,
        month INTEGER,
        locked_at TEXT NOT NULL DEFAULT (datetime('now')),
        locked_by INTEGER REFERENCES users(id),
        UNIQUE(user_id, period_type, year, month)
    );
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_period_locks_user_year ON period_locks(user_id, year)")












    db.commit()
    db.close()

def seed_defaults():
    db = connect()
    # default absence types (Feiertag removed – handled via calendar_seed)
    absence_defaults = [
        ('Urlaub', '#198754', 1),
        ('Krank', '#dc3545', 1),
        ('Sonstige', '#6c757d', 1),
    ]
    for name, color, active in absence_defaults:
        db.execute(
            "INSERT OR IGNORE INTO absence_types(name,color,active,updated_at) VALUES(?,?,?,datetime('now'))",
            (name, color, active),
        )

    # Migration: remove Feiertag absence type if no absences reference it
    row = db.execute(
        "SELECT id FROM absence_types WHERE LOWER(name)='feiertag' LIMIT 1"
    ).fetchone()
    if row:
        in_use = db.execute(
            "SELECT 1 FROM absences WHERE type_id=? LIMIT 1", (row["id"],)
        ).fetchone()
        if not in_use:
            db.execute("DELETE FROM absence_types WHERE id=?", (row["id"],))

    db.commit()
    db.close()
