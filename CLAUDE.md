# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Zeiterfassung** (v3.0.0) is a multi-user German-language time tracking web app built with Flask + SQLite. Users record work time blocks, absences, and vacations; the app computes balances against configurable work schedules.

## Running the Application

```bash
# Production service (Gunicorn via systemd)
systemctl restart zeiterfassung.service
systemctl is-active zeiterfassung.service

# Test via Unix socket
curl -s --unix-socket /run/zeiterfassung/zeiterfassung.sock http://localhost/login
```

Database location is configurable via `ZEITERFASSUNG_DB` env var (default: `zeiterfassung.db` in working directory). Use `.venv/bin/python3` — `python` is not available. No test suite, no linting config.

## Architecture

All business logic and routes live in a single `app.py` (~4,000 lines). The other modules are narrow:

- **`db.py`** — `init_db()` creates all tables + runs inline `ALTER TABLE` migrations; `connect()` returns a `sqlite3.Row`-enabled connection with FK enforcement on; `seed_defaults()` inserts the three fixed absence types
- **`auth.py`** — session-based auth with Werkzeug hashing; `@login_required` / `@admin_required` decorators; usernames stored/compared lowercase
- **`templates.py`** — single `layout()` function that renders the full HTML shell including nav, CSS variables, and responsive styles; all page bodies are f-strings passed into `render_template_string` in `app.py`
- **`calendar_seed.py`** — seeds NRW public holidays for 2026 on first run

### Database Schema

Key tables:
- `users` → `user_schedules` (1:N validity-dated schedules; `_get_user_schedule_for_day()` picks the row active on a given date)
- `user_schedule` — legacy single-schedule table; still present but superseded by `user_schedules`
- `users` → `time_blocks` (multiple per day; the current model) + `time_entries` (legacy single-entry-per-day; still read for old data)
- `users` → `absences` → `absence_types` (exactly three fixed types: Urlaub, Krank, Sonstige)
- `absence_remarks` — per-user history of free-text remarks used with "Sonstige" absences
- `calendar_days` — holiday/weekend flags keyed by ISO date + region (`DE-NW`)

Removed tables (dropped via migration): `key_types`.

### Schedule System

`workdays_mask` is a bitmask: Mon=1, Tue=2, Wed=4, Thu=8, Fri=16, Sat=32, Sun=64. Default Mon–Fri = 31.

Two modes (`mode` column in `user_schedules`):
- `weekly` — `weekly_minutes` divided evenly across the days that match `workdays_mask`. **The denominator is the count of mask-matching days in the week, ignoring holidays and absences** — holidays/absences cause those days to return Soll=0 via early returns, but do not inflate the Soll of other days.
- `daily` — explicit per-weekday columns (`mon_minutes` … `sun_minutes`)

### Balance Calculation

`_expected_minutes_for_day(user_id, iso_day)` priority order:
1. Manual per-day override (stored in `time_entries.expected_minutes` or an override table)
2. Holiday/weekend block → 0
3. Mask check → 0
4. Absence check → 0
5. Schedule-based computation

`_calc_balance()` and `_calc_balance_end_at()` iterate days and accumulate `actual − expected`. **Flextag special rule**: if a day is a "Sonstige/Flextag" absence and is in the past, `_scheduled_minutes_ignoring_absence()` is called to get the day's planned Soll, and that amount is additionally subtracted from the running balance (the day "consumes" saved overtime). Future Flextag days have no effect on the balance.

`balance_view` always computes from Jan 1 of the selected year and filters display to the chosen month, ensuring cumulative correctness.

### Absence Types

Hardcoded to exactly three types (enforced at DB seed + migration time):
- **Urlaub** — no comment required; shown in absence list without Bemerkung column
- **Krank** — same
- **Sonstige** — requires a Bemerkung (comment); stored in `absences.comment`; per-user remark history saved to `absence_remarks`; preset suggestions: `FIXED_REMARKS = ["Flextag", "Verdi"]`

### Route Groups

| Prefix | Description |
|---|---|
| `/setup`, `/login`, `/logout` | Auth |
| `/`, `/presence` | Dashboard / current week |
| `/day/<YYYY-MM-DD>` | Day detail, time block CRUD |
| `/balance` | Running balance with month/year selector, absence summary, Flextag deduction |
| `/absences` | Absence CRUD |
| `/business_trips` | Business trip CRUD |
| `/calendar` | Month calendar view |
| `/settings` | User preferences, schedule |
| `/export/*` | CSV exports |
| `/admin/users` | User management only (absence-types and key-types admin removed) |
