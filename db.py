import sqlite3, os
from pathlib import Path

DB_FILENAME = os.environ.get("ZEITERFASSUNG_DB", "zeiterfassung.db")

def db_path():
    return str(Path(DB_FILENAME).resolve())

def connect():
    c = sqlite3.connect(db_path(), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
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

    # Migrate calendar_days from single-column PK (day) to composite PK (day, region)
    _pk_cols = [r["name"] for r in db.execute("PRAGMA table_info(calendar_days)").fetchall() if r["pk"] > 0]
    if _pk_cols == ["day"]:
        db.execute("""
            CREATE TABLE IF NOT EXISTS _calendar_days_new (
                day TEXT NOT NULL,
                region TEXT NOT NULL DEFAULT 'DE-NW',
                is_weekend INTEGER NOT NULL DEFAULT 0,
                is_holiday INTEGER NOT NULL DEFAULT 0,
                holiday_name TEXT,
                is_school_holiday INTEGER NOT NULL DEFAULT 0,
                school_holiday_name TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (day, region)
            )
        """)
        db.execute("""
            INSERT OR IGNORE INTO _calendar_days_new
            (day, region, is_weekend, is_holiday, holiday_name, is_school_holiday, school_holiday_name, updated_at)
            SELECT day, COALESCE(NULLIF(region,''),'DE-NW'), is_weekend, is_holiday, holiday_name,
                   COALESCE(is_school_holiday,0), school_holiday_name, COALESCE(updated_at,datetime('now'))
            FROM calendar_days
        """)
        db.execute("DROP TABLE calendar_days")
        db.execute("ALTER TABLE _calendar_days_new RENAME TO calendar_days")
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

    # Migration: updated_at Spalte zu absence_types hinzufügen falls fehlt
    if not _col_exists(db, "absence_types", "updated_at"):
        db.execute("ALTER TABLE absence_types ADD COLUMN updated_at TEXT")

    # Rename legacy 'Sonstiges' → 'Sonstige'
    db.execute("UPDATE absence_types SET name='Sonstige', updated_at=datetime('now') WHERE name='Sonstiges'")

    # Ensure only the allowed types exist; remap absences of unknown types to Sonstige then delete
    # Verdi kept here so init_db doesn't strip it before seed_defaults migration can run
    _allowed_types = ('Urlaub', 'Krank', 'Sonstige', 'Flextag', 'Verdi')
    sonstige_row = db.execute("SELECT id FROM absence_types WHERE name='Sonstige'").fetchone()
    if sonstige_row:
        sonstige_id = sonstige_row["id"]
        placeholders = ",".join("?" * len(_allowed_types))
        others = db.execute(
            f"SELECT id FROM absence_types WHERE name NOT IN ({placeholders})", _allowed_types
        ).fetchall()
        for o in others:
            db.execute("UPDATE absences SET type_id=? WHERE type_id=?", (sonstige_id, o["id"]))
        if others:
            db.execute(f"DELETE FROM absence_types WHERE name NOT IN ({placeholders})", _allowed_types)

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

    db.execute("""
    CREATE TABLE IF NOT EXISTS weekend_exceptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(user_id, day),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_weekend_exceptions_user_day ON weekend_exceptions(user_id, day)")

    # User profile / onboarding columns
    if not _col_exists(db, "users", "tracking_start_date"):
        db.execute("ALTER TABLE users ADD COLUMN tracking_start_date TEXT")

    # Migrate: set tracking_start_date for existing users that have none
    # Must come AFTER ALTER TABLE to avoid OperationalError on fresh DB
    db.execute("""
        UPDATE users SET tracking_start_date='2026-01-01'
        WHERE tracking_start_date IS NULL OR tracking_start_date=''
    """)

    if not _col_exists(db, "users", "password_changed"):
        db.execute("ALTER TABLE users ADD COLUMN password_changed INTEGER NOT NULL DEFAULT 0")

    if not _col_exists(db, "users", "onboarding_done"):
        db.execute("ALTER TABLE users ADD COLUMN onboarding_done INTEGER NOT NULL DEFAULT 0")
        # Existing users are already configured – mark wizard as complete
        db.execute("UPDATE users SET onboarding_done=1")

    if not _col_exists(db, "users", "display_name"):
        db.execute("ALTER TABLE users ADD COLUMN display_name TEXT")

    if not _col_exists(db, "users", "email"):
        db.execute("ALTER TABLE users ADD COLUMN email TEXT")

    if not _col_exists(db, "users", "vacation_carryover_exception"):
        db.execute(
            "ALTER TABLE users ADD COLUMN vacation_carryover_exception INTEGER NOT NULL DEFAULT 0"
        )

    if not _col_exists(db, "users", "contouring_enabled"):
        db.execute(
            "ALTER TABLE users ADD COLUMN contouring_enabled INTEGER NOT NULL DEFAULT 1"
        )

    if not _col_exists(db, "users", "contouring_start_date"):
        db.execute("ALTER TABLE users ADD COLUMN contouring_start_date TEXT")

    if not _col_exists(db, "users", "birth_date"):
        db.execute("ALTER TABLE users ADD COLUMN birth_date TEXT")

    if not _col_exists(db, "users", "retirement_age"):
        db.execute("ALTER TABLE users ADD COLUMN retirement_age INTEGER NOT NULL DEFAULT 67")

    if not _col_exists(db, "users", "overtime_limit_plus"):
        db.execute("ALTER TABLE users ADD COLUMN overtime_limit_plus INTEGER")
    if not _col_exists(db, "users", "overtime_limit_minus"):
        db.execute("ALTER TABLE users ADD COLUMN overtime_limit_minus INTEGER")
    if not _col_exists(db, "users", "supervisor_email"):
        db.execute("ALTER TABLE users ADD COLUMN supervisor_email TEXT")
    if not _col_exists(db, "users", "overtime_notify_enabled"):
        db.execute("ALTER TABLE users ADD COLUMN overtime_notify_enabled INTEGER NOT NULL DEFAULT 0")
    if not _col_exists(db, "users", "overtime_notify_interval"):
        db.execute("ALTER TABLE users ADD COLUMN overtime_notify_interval TEXT NOT NULL DEFAULT 'once'")
    if not _col_exists(db, "users", "overtime_last_notified"):
        db.execute("ALTER TABLE users ADD COLUMN overtime_last_notified TEXT")

    if not _col_exists(db, "users", "admin_role"):
        db.execute("ALTER TABLE users ADD COLUMN admin_role TEXT")
        db.execute("UPDATE users SET admin_role='sysadmin' WHERE is_admin=1")

    if not _col_exists(db, "users", "holiday_region"):
        db.execute("ALTER TABLE users ADD COLUMN holiday_region TEXT")

    if not _col_exists(db, "users", "must_change_password"):
        db.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")

    if not _col_exists(db, "users", "admin_only"):
        db.execute("ALTER TABLE users ADD COLUMN admin_only INTEGER NOT NULL DEFAULT 0")

    if not _col_exists(db, "users", "language"):
        db.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'en'")
        # Existing users were German-only — set their language to 'de'
        db.execute("UPDATE users SET language='de'")

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

    db.execute("""CREATE TABLE IF NOT EXISTS mail_config(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL UNIQUE,
        value TEXT,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    # Ensure all expected keys exist (INSERT OR IGNORE leaves existing values intact)
    for _key in ("mail_server", "mail_port", "mail_username", "mail_password", "mail_from"):
        db.execute(
            "INSERT OR IGNORE INTO mail_config(key, value) VALUES(?, '')",
            (_key,),
        )

    db.execute("""CREATE TABLE IF NOT EXISTS bot_config(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    for _key in ("bot_token", "anthropic_api_key", "admin_telegram_ids"):
        db.execute(
            "INSERT OR IGNORE INTO bot_config(key, value) VALUES(?, '')",
            (_key,),
        )

    db.execute("""CREATE TABLE IF NOT EXISTS app_config(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    for _key, _default in (
        ("accent_color", "#2563eb"),
        ("nav_color", ""),
        ("app_label", ""),
        ("app_label_color", "#f59e0b"),
        ("overtime_default_limit_plus", ""),
        ("overtime_default_limit_minus", ""),
        ("default_holiday_region", "DE-NW"),
        ("default_language", "en"),
        ("available_languages", "de,en"),
        ("base_url", ""),
    ):
        db.execute(
            "INSERT OR IGNORE INTO app_config(key, value) VALUES(?, ?)",
            (_key, _default),
        )

    db.execute("""CREATE TABLE IF NOT EXISTS backup_config(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    for _key, _default in (
        ("auto_backup_enabled", "0"),
        ("auto_backup_time", "02:00"),
        ("last_backup_time", ""),
        ("auto_encrypt_enabled", "0"),
        ("auto_encrypt_password", ""),
    ):
        db.execute(
            "INSERT OR IGNORE INTO backup_config(key, value) VALUES(?, ?)",
            (_key, _default),
        )

    # --- Telegram Bot user mapping ---
    db.execute("""CREATE TABLE IF NOT EXISTS telegram_users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL UNIQUE,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_telegram_users_telegram_id ON telegram_users(telegram_id)")
    if not _col_exists(db, "telegram_users", "wizard_enabled"):
        db.execute("ALTER TABLE telegram_users ADD COLUMN wizard_enabled INTEGER NOT NULL DEFAULT 1")
    if not _col_exists(db, "telegram_users", "reminder_time"):
        db.execute("ALTER TABLE telegram_users ADD COLUMN reminder_time TEXT NOT NULL DEFAULT '20:00'")
    if not _col_exists(db, "users", "enabled_absence_types"):
        db.execute("ALTER TABLE users ADD COLUMN enabled_absence_types TEXT")
    if not _col_exists(db, "users", "calendar_system"):
        db.execute("ALTER TABLE users ADD COLUMN calendar_system TEXT NOT NULL DEFAULT 'ical'")
    if not _col_exists(db, "users", "calendar_export_types"):
        db.execute("ALTER TABLE users ADD COLUMN calendar_export_types TEXT NOT NULL DEFAULT 'urlaub,krank,flextag'")
    if not _col_exists(db, "users", "calendar_export_prefix"):
        db.execute("ALTER TABLE users ADD COLUMN calendar_export_prefix TEXT NOT NULL DEFAULT ''")
    if not _col_exists(db, "users", "calendar_token"):
        db.execute("ALTER TABLE users ADD COLUMN calendar_token TEXT")
        import uuid as _uuid
        for _row in db.execute("SELECT id FROM users").fetchall():
            db.execute("UPDATE users SET calendar_token=? WHERE id=?",
                       (str(_uuid.uuid4()), _row[0]))
    if not _col_exists(db, "users", "calendar_auth_mode"):
        db.execute("ALTER TABLE users ADD COLUMN calendar_auth_mode TEXT NOT NULL DEFAULT 'token'")
    if not _col_exists(db, "users", "icloud_enabled"):
        db.execute("ALTER TABLE users ADD COLUMN icloud_enabled INTEGER NOT NULL DEFAULT 0")
    if not _col_exists(db, "users", "icloud_apple_id"):
        db.execute("ALTER TABLE users ADD COLUMN icloud_apple_id TEXT")
    if not _col_exists(db, "users", "icloud_app_password"):
        db.execute("ALTER TABLE users ADD COLUMN icloud_app_password TEXT")
    if not _col_exists(db, "users", "icloud_calendar_name"):
        db.execute("ALTER TABLE users ADD COLUMN icloud_calendar_name TEXT")
    if not _col_exists(db, "users", "icloud_last_sync"):
        db.execute("ALTER TABLE users ADD COLUMN icloud_last_sync TEXT")

    # v2.0.8 – security features
    if not _col_exists(db, "users", "password_compliant"):
        db.execute("ALTER TABLE users ADD COLUMN password_compliant INTEGER NOT NULL DEFAULT 0")
    if not _col_exists(db, "users", "login_attempts"):
        db.execute("ALTER TABLE users ADD COLUMN login_attempts INTEGER NOT NULL DEFAULT 0")
    if not _col_exists(db, "users", "login_locked_until"):
        db.execute("ALTER TABLE users ADD COLUMN login_locked_until TEXT")
    if not _col_exists(db, "users", "login_unlock_token"):
        db.execute("ALTER TABLE users ADD COLUMN login_unlock_token TEXT")
    if not _col_exists(db, "users", "last_login"):
        db.execute("ALTER TABLE users ADD COLUMN last_login TEXT")
    if not _col_exists(db, "users", "totp_secret"):
        db.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT")
    if not _col_exists(db, "users", "totp_enabled"):
        db.execute("ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0")
    if not _col_exists(db, "users", "totp_backup_codes"):
        db.execute("ALTER TABLE users ADD COLUMN totp_backup_codes TEXT")

    # v2.0.9 – approval workflow
    if not _col_exists(db, "users", "is_approver"):
        db.execute("ALTER TABLE users ADD COLUMN is_approver INTEGER NOT NULL DEFAULT 0")
    if not _col_exists(db, "users", "approval_required_types"):
        db.execute("ALTER TABLE users ADD COLUMN approval_required_types TEXT DEFAULT NULL")
    if not _col_exists(db, "users", "approver_id"):
        db.execute("ALTER TABLE users ADD COLUMN approver_id INTEGER DEFAULT NULL REFERENCES users(id)")

    db.execute("""CREATE TABLE IF NOT EXISTS absence_approvals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        absence_id INTEGER NOT NULL,
        approver_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
        comment TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY(absence_id) REFERENCES absences(id) ON DELETE CASCADE,
        FOREIGN KEY(approver_id) REFERENCES users(id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_absence_approvals_absence ON absence_approvals(absence_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_absence_approvals_approver ON absence_approvals(approver_id, status)")

    # v3.0.0 – Teams
    db.execute("""CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        color TEXT DEFAULT '#4a9eff',
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS user_teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
        UNIQUE(user_id, team_id)
    )""")
    for col, defn in [
        ("primary_team_id", "INTEGER DEFAULT NULL"),
        ("team_restriction", "TEXT DEFAULT NULL"),
        ("is_superuser",     "INTEGER DEFAULT 0"),
    ]:
        if not _col_exists(db, "users", col):
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")

    # v3.0.0.dev2 – Staffing
    db.execute("""CREATE TABLE IF NOT EXISTS staffing_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS staffing_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER NOT NULL REFERENCES staffing_plans(id) ON DELETE CASCADE,
        label TEXT NOT NULL,
        slot_type TEXT NOT NULL DEFAULT 'vm',
        weekdays TEXT NOT NULL DEFAULT '0,1,2,3,4',
        nth_week TEXT DEFAULT NULL,
        special_weekday INTEGER DEFAULT NULL,
        min_staff INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        time_from TEXT DEFAULT NULL,
        time_to TEXT DEFAULT NULL
    )""")
    if not _col_exists(db, "staffing_slots", "time_from"):
        db.execute("ALTER TABLE staffing_slots ADD COLUMN time_from TEXT DEFAULT NULL")
    if not _col_exists(db, "staffing_slots", "time_to"):
        db.execute("ALTER TABLE staffing_slots ADD COLUMN time_to TEXT DEFAULT NULL")
    if not _col_exists(db, "staffing_slots", "slot_role"):
        db.execute(
            "ALTER TABLE staffing_slots ADD COLUMN slot_role TEXT DEFAULT 'staff'"
        )
    if not _col_exists(db, "staffing_slots", "min_lead"):
        db.execute(
            "ALTER TABLE staffing_slots ADD COLUMN min_lead INTEGER DEFAULT 0"
        )
    db.execute("""CREATE TABLE IF NOT EXISTS staffing_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slot_id INTEGER NOT NULL REFERENCES staffing_slots(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(slot_id, user_id)
    )""")
    if not _col_exists(db, "staffing_assignments", "is_lead"):
        db.execute(
            "ALTER TABLE staffing_assignments ADD COLUMN is_lead INTEGER DEFAULT 0"
        )
    if not _col_exists(db, "staffing_plans", "default_min_staff"):
        db.execute(
            "ALTER TABLE staffing_plans ADD COLUMN default_min_staff INTEGER DEFAULT 2"
        )
    if not _col_exists(db, "staffing_plans", "require_lead"):
        db.execute(
            "ALTER TABLE staffing_plans ADD COLUMN require_lead INTEGER DEFAULT 0"
        )
    # v3.0.6.dev3 – konfigurierbare Leiter-Bezeichnung pro Plan
    if not _col_exists(db, "staffing_plans", "lead_label"):
        db.execute(
            "ALTER TABLE staffing_plans ADD COLUMN lead_label TEXT DEFAULT 'Leiter'"
        )
    # v3.0.2.dev2 – Team-Standort für Feiertage
    if not _col_exists(db, "teams", "holiday_region"):
        db.execute(
            "ALTER TABLE teams ADD COLUMN holiday_region TEXT DEFAULT NULL"
        )
    db.execute("""CREATE TABLE IF NOT EXISTS balance_adjustments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        minutes INTEGER NOT NULL,
        reason TEXT NOT NULL,
        adjustment_date TEXT NOT NULL,
        created_by INTEGER REFERENCES users(id),
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    # v3.0.0.dev10 – Tagesdetail + Sondereinsätze
    db.execute("""CREATE TABLE IF NOT EXISTS staffing_day_accepted (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER NOT NULL REFERENCES staffing_plans(id) ON DELETE CASCADE,
        iso_date TEXT NOT NULL,
        accepted_by INTEGER REFERENCES users(id),
        note TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(plan_id, iso_date)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS staffing_overrides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id INTEGER NOT NULL REFERENCES staffing_plans(id) ON DELETE CASCADE,
        slot_id INTEGER NOT NULL REFERENCES staffing_slots(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        iso_date TEXT NOT NULL,
        require_confirm INTEGER DEFAULT 0,
        status TEXT DEFAULT 'assigned',
        note TEXT DEFAULT '',
        created_by INTEGER REFERENCES users(id),
        confirmed_at TEXT DEFAULT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    # v3.0.2.dev5 – Zeitvorlagen
    db.execute("""CREATE TABLE IF NOT EXISTS user_time_presets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        label TEXT NOT NULL,
        time_in TEXT NOT NULL,
        time_out TEXT NOT NULL,
        break_minutes INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0
    )""")

    # v3.0.2.dev6 – allow_self_edit in user_schedules
    if not _col_exists(db, "user_schedules", "allow_self_edit"):
        db.execute(
            "ALTER TABLE user_schedules ADD COLUMN allow_self_edit INTEGER DEFAULT 1"
        )

    # v3.0.9.dev1 – Berufsschule
    db.execute("""CREATE TABLE IF NOT EXISTS vocational_school (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        schedule_type TEXT NOT NULL DEFAULT 'weekly',
        weekday INTEGER DEFAULT NULL,
        school_time_from TEXT DEFAULT NULL,
        school_time_to   TEXT DEFAULT NULL,
        work_time_from   TEXT DEFAULT NULL,
        work_time_to     TEXT DEFAULT NULL,
        date_from TEXT DEFAULT NULL,
        date_to   TEXT DEFAULT NULL,
        valid_from TEXT DEFAULT NULL,
        valid_to   TEXT DEFAULT NULL,
        note TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS school_holidays (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        region TEXT NOT NULL,
        name TEXT NOT NULL,
        date_from TEXT NOT NULL,
        date_to TEXT NOT NULL
    )""")
    if not _col_exists(db, "users", "is_apprentice"):
        db.execute("ALTER TABLE users ADD COLUMN is_apprentice INTEGER DEFAULT 0")

    # v3.0.7.dev2 – Urlaubsanspruch-Tabelle
    db.execute("""CREATE TABLE IF NOT EXISTS user_vacation_entitlement (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        days REAL NOT NULL,
        valid_from TEXT NOT NULL,
        note TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    )""")

    # v3.0.7.dev2 – Enddatum + Gleitzeitregel
    for col, defn in [
        ("end_date",         "TEXT DEFAULT NULL"),
        ("balance_rollover", "TEXT DEFAULT 'manual'"),
    ]:
        if not _col_exists(db, "users", col):
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")

    # v3.0.0 – Feature-Flags
    db.execute("""INSERT OR IGNORE INTO app_config (key, value)
        VALUES ('feature_staffing', '0')""")

    # v3.0.13 – fehlende Indizes
    db.execute("CREATE INDEX IF NOT EXISTS idx_staffing_assignments_slot ON staffing_assignments(slot_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_staffing_assignments_user ON staffing_assignments(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_staffing_slots_plan ON staffing_slots(plan_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_user_teams_user ON user_teams(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_user_teams_team ON user_teams(team_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_balance_adjustments_user ON balance_adjustments(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_vocational_school_user ON vocational_school(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_user_time_presets_user ON user_time_presets(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_user_vacation_entitlement_user ON user_vacation_entitlement(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_staffing_overrides_user ON staffing_overrides(user_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_staffing_day_accepted_plan ON staffing_day_accepted(plan_id)")

    db.commit()
    db.close()

def seed_defaults():
    db = connect()
    # default absence types (Feiertag removed – handled via calendar_seed; Verdi NOT auto-created)
    absence_defaults = [
        ('Urlaub',  '#198754', 1),
        ('Krank',   '#dc3545', 1),
        ('Flextag', '#3b82f6', 1),
        ('Sonstige','#6c757d', 1),
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

    # Migration: Sonstige+comment=Flextag → Flextag type (clear comment)
    flextag_row = db.execute("SELECT id FROM absence_types WHERE name='Flextag'").fetchone()
    sonstige_row = db.execute("SELECT id FROM absence_types WHERE name='Sonstige'").fetchone()
    if flextag_row and sonstige_row:
        db.execute(
            "UPDATE absences SET type_id=?, comment=NULL, updated_at=datetime('now') "
            "WHERE type_id=? AND LOWER(TRIM(COALESCE(comment,'')))='flextag'",
            (flextag_row["id"], sonstige_row["id"])
        )

    # v1.4.6.8 reverse migration: Verdi dedicated type → Sonstige+comment='Verdi'
    verdi_row = db.execute("SELECT id FROM absence_types WHERE name='Verdi'").fetchone()
    if verdi_row and sonstige_row:
        db.execute(
            "UPDATE absences SET type_id=?, comment='Verdi', updated_at=datetime('now') "
            "WHERE type_id=?",
            (sonstige_row["id"], verdi_row["id"])
        )
        db.execute("DELETE FROM absence_types WHERE name='Verdi'")
        # Remove Verdi ID from enabled_absence_types for all users
        verdi_id_str = str(verdi_row["id"])
        for urow in db.execute("SELECT id, enabled_absence_types FROM users WHERE enabled_absence_types IS NOT NULL").fetchall():
            ids = [x for x in urow["enabled_absence_types"].split(",") if x.strip() != verdi_id_str]
            std_ids = db.execute(
                "SELECT id FROM absence_types WHERE name IN ('Urlaub','Krank','Flextag','Sonstige') AND active=1"
            ).fetchall()
            std_set = {str(r["id"]) for r in std_ids}
            new_val = ",".join(i for i in ids if i.strip())
            # If result matches the standard set exactly → store NULL
            if set(new_val.split(",")) == std_set:
                new_val = None
            db.execute("UPDATE users SET enabled_absence_types=?, updated_at=datetime('now') WHERE id=?",
                       (new_val, urow["id"]))

    # Clean up absence_remarks that are now dedicated types
    db.execute("DELETE FROM absence_remarks WHERE LOWER(TRIM(remark)) IN ('flextag', 'verdi')")

    db.commit()
    db.close()
