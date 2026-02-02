"""Calendar seeding (NRW / 2026).

The app uses `calendar_days` for weekend/holiday logic.

This module is defensive against schema drift:
- Creates the table if it doesn't exist
- Adds missing columns if the table exists with an older schema

Seeded data:
- All days of 2026 (weekend flag)
- NRW public holidays (holiday flag + holiday_name)

You can extend this later (e.g., other years/regions, school holidays).
"""

from __future__ import annotations

from datetime import date, timedelta

from db import connect


def _easter_sunday(year: int) -> date:
    """Compute Easter Sunday (Gregorian calendar) for given year."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _ensure_calendar_days_schema(db) -> None:
    # Create table with current schema
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS calendar_days (
            day TEXT PRIMARY KEY,
            is_weekend INTEGER DEFAULT 0,
            is_holiday INTEGER DEFAULT 0,
            holiday_name TEXT,
            is_school_holiday INTEGER DEFAULT 0,
            school_holiday_name TEXT,
            region TEXT DEFAULT 'NRW',
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )

    # Add missing columns if table exists with older schema
    cols = {row[1] for row in db.execute("PRAGMA table_info(calendar_days)").fetchall()}

    def add(col_sql: str) -> None:
        db.execute(f"ALTER TABLE calendar_days ADD COLUMN {col_sql}")

    if "holiday_name" not in cols:
        add("holiday_name TEXT")
    if "is_school_holiday" not in cols:
        add("is_school_holiday INTEGER DEFAULT 0")
    if "school_holiday_name" not in cols:
        add("school_holiday_name TEXT")
    if "region" not in cols:
        add("region TEXT DEFAULT 'NRW'")
    if "updated_at" not in cols:
        add("updated_at TEXT DEFAULT (datetime('now'))")


def seed_calendar_2026_nrw() -> None:
    db = connect()
    _ensure_calendar_days_schema(db)

    year = 2026
    region = "NRW"

    # NRW public holidays (nationwide + NRW-specific All Saints)
    easter = _easter_sunday(year)
    holidays: dict[str, str] = {
        date(year, 1, 1).isoformat(): "Neujahr",
        date(year, 5, 1).isoformat(): "Tag der Arbeit",
        date(year, 10, 3).isoformat(): "Tag der Deutschen Einheit",
        date(year, 11, 1).isoformat(): "Allerheiligen",
        date(year, 12, 25).isoformat(): "1. Weihnachtstag",
        date(year, 12, 26).isoformat(): "2. Weihnachtstag",
        (easter - timedelta(days=2)).isoformat(): "Karfreitag",
        easter.isoformat(): "Ostersonntag",
        (easter + timedelta(days=1)).isoformat(): "Ostermontag",
        (easter + timedelta(days=39)).isoformat(): "Christi Himmelfahrt",
        (easter + timedelta(days=49)).isoformat(): "Pfingstsonntag",
        (easter + timedelta(days=50)).isoformat(): "Pfingstmontag",
        (easter + timedelta(days=60)).isoformat(): "Fronleichnam",
    }

    # Seed every day of the year
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        iso = d.isoformat()
        is_weekend = 1 if d.weekday() >= 5 else 0  # 5=Sat, 6=Sun
        holiday_name = holidays.get(iso)
        is_holiday = 1 if holiday_name else 0

        db.execute(
            """
            INSERT INTO calendar_days (
                day, is_weekend, is_holiday, holiday_name,
                is_school_holiday, school_holiday_name,
                region, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(day) DO UPDATE SET
                is_weekend=excluded.is_weekend,
                is_holiday=excluded.is_holiday,
                holiday_name=excluded.holiday_name,
                is_school_holiday=excluded.is_school_holiday,
                school_holiday_name=excluded.school_holiday_name,
                region=excluded.region,
                updated_at=datetime('now')
            """,
            (
                iso,
                is_weekend,
                is_holiday,
                holiday_name,
                0,
                None,
                region,
            ),
        )
        d += timedelta(days=1)

    db.commit()


if __name__ == "__main__":
    seed_calendar_2026_nrw()
    print("Seeded calendar_days for NRW 2026")
