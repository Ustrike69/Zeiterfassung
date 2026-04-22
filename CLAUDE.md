# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Zeiterfassung** (v2.18.0) is a multi-user German-language time tracking web app built with Flask + SQLite. Users record work time blocks, absences, and vacations; the app computes balances against configurable work schedules.

## Running the Application

```bash
# Development (from /opt/zeiterfassung)
.venv/bin/python app.py

# Production service (Gunicorn via systemd)
systemctl restart zeiterfassung
systemctl status zeiterfassung

# Test via Unix socket
curl -s --unix-socket /run/zeiterfassung/zeiterfassung.sock http://localhost/login
```

Database location is configurable via `ZEITERFASSUNG_DB` env var (default: `zeiterfassung.db` in working directory).

No test suite, no linting config.

## Architecture

All business logic and routes live in a single `app.py` (~3,750 lines). The other modules are narrow:

- **`db.py`** — `init_db()` creates all tables + runs inline ALTER TABLE migrations for backward compatibility; `connect()` returns a `sqlite3.Row`-enabled connection with FK enforcement
- **`auth.py`** — session-based auth with Werkzeug hashing; `@login_required` / `@admin_required` decorators; usernames are stored/compared lowercase
- **`templates.py`** — returns a full HTML shell (`layout()`); all page HTML is rendered via `render_template_string` in `app.py`; mobile assets (JS + CSS) are injected globally via the `layout()` wrapper in `app.py`
- **`calendar_seed.py`** — seeds NRW public holidays for 2026 on first run

### Database Schema

Key tables and relationships:
- `users` → `user_schedule` (1:1, legacy single schedule) + `user_schedules` (1:N, validity-dated schedules)
- `users` → `time_blocks` (N:M via day; multiple blocks per day, the modern model)
- `users` → `time_entries` (legacy single-entry-per-day; still read for old data)
- `users` → `absences` → `absence_types`
- `calendar_days` — holiday/weekend flags keyed by ISO date string + region (`DE-NW`)
- `key_types` — presence/status categories (Anwesend, Urlaub, Krank, Flextag…)
- `balance` — stores carry-over start balance per user

### Schedule System

Work schedules support two modes (`mode` column):
- `weekly` — total weekly minutes distributed evenly across workdays
- `daily` — explicit per-weekday minute targets (`mon_minutes`…`sun_minutes`)

`workdays_mask` is a bitmask (Mon=1, Tue=2, Wed=4, Thu=8, Fri=16, Sat=32, Sun=64). The `user_schedules` table supports multiple validity-dated entries per user; `_get_user_schedule_for_day()` picks the applicable row.

### Balance Calculation

`_calc_balance()` and `_calc_balance_end_at()` in `app.py` iterate over days to compute cumulative expected vs. actual minutes. Expected minutes for a day come from `_expected_minutes_for_day()`, which checks the per-day override table first, then falls back to schedule logic. Holidays and weekends can block expected hours depending on user schedule settings.

### Route Groups

| Prefix | Description |
|---|---|
| `/setup`, `/login`, `/logout` | Auth |
| `/`, `/presence` | Dashboard / current week |
| `/day/<YYYY-MM-DD>` | Day detail, time block CRUD |
| `/balance` | Running balance view + CSV |
| `/absences` | Absence CRUD |
| `/calendar` | Month calendar view |
| `/settings` | User preferences, schedule, vacation entitlement |
| `/export/*` | CSV exports |
| `/admin/*` | User management, key types, absence types |
