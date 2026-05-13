# CLAUDE.md

Guidance for Claude Code when working with this repository.

## Project Overview

**Zeiterfassung** (v4.6.6) is a multi-user German-language time tracking web app built with Flask + SQLite, deployed at `/opt/zeiterfassung`, running as a Gunicorn systemd service. Users record work time blocks, absences, and business trips; the app computes flex-time balances against configurable work schedules. All content and UI is in German.

## Running the Application

```bash
# Production (Gunicorn via systemd)
systemctl restart zeiterfassung
systemctl is-active zeiterfassung
journalctl -u zeiterfassung -n 50 --no-pager

# Test via Unix socket
curl -s --unix-socket /run/zeiterfassung/zeiterfassung.sock http://localhost/login
```

Database path is configurable via `ZEITERFASSUNG_DB` env var (default: `zeiterfassung.db` in working dir). Use `.venv/bin/python3` — `python` is not available. No test suite, no linting config.

## Architecture

All business logic and routes live in a single `app.py` (~6,300 lines). Other modules are narrow:

- **`db.py`** — `init_db()` creates all tables + runs inline `ALTER TABLE` migrations; `connect()` returns `sqlite3.Row`-enabled connection with FK enforcement; `seed_defaults()` inserts fixed absence types
- **`auth.py`** — session-based auth with Werkzeug hashing; `@login_required` / `@admin_required` decorators; usernames stored/compared lowercase
- **`templates.py`** — single `layout()` function rendering the full HTML shell (nav, CSS variables, responsive styles, back-button, impersonation banner); all page bodies are f-strings in `app.py`
- **`calendar_seed.py`** — seeds NRW public holidays for 2026

## Database Schema

Key tables:

| Table | Description |
|-------|-------------|
| `users` | User accounts; includes `tracking_start_date`, `contouring_enabled`, `contouring_start_date`, `vacation_carryover_exception` |
| `user_schedules` | Validity-dated work schedules (1:N per user); `_get_user_schedule_for_day()` picks active row |
| `time_blocks` | Multiple time blocks per day (current model) |
| `time_entries` | Legacy single-entry-per-day; still read for old data |
| `absences` | Linked to `absence_types` (exactly 3: Urlaub, Krank, Sonstige) |
| `absence_remarks` | Per-user free-text remark history for Sonstige absences |
| `calendar_days` | Holiday/weekend flags by ISO date + region (DE-NW) |
| `contoured_days` | Days marked as contoured (user_id, day) |
| `vacation_carryover_overrides` | Per-user/year carryover exceptions |
| `weekend_exceptions` | Per-user exceptions allowing work on weekends/holidays |

## Schedule System

`workdays_mask` bitmask: Mon=1, Tue=2, Wed=4, Thu=8, Fri=16, Sat=32, Sun=64. Default Mon–Fri = 31.

Two modes (`mode` in `user_schedules`):
- `weekly` — `weekly_minutes` divided evenly across mask-matching days; holidays/absences return Soll=0 without inflating other days
- `daily` — explicit per-weekday columns (`mon_minutes` … `sun_minutes`)

## Balance Calculation

`_expected_minutes_for_day(user_id, iso_day)` priority:
1. Holiday/weekend → 0
2. Mask check → 0
3. Absence check → 0
4. Schedule-based computation

`_calc_balance_end_at(user_id, end_iso)` iterates **all days** via `_iter_days(start_iso, end_iso)` — identical logic to `balance_view`. Respects `tracking_start_date`. Dashboard and Details always show the same value.

**Flextag rule**: past Flextag days deduct additionally `_scheduled_minutes_ignoring_absence()` from the running balance.

## Contour System

- `contoured_days` table: (user_id, day)
- `_get_contoured_days()` — set of contoured days for a date range
- `_get_uncontoured_days()` — past workdays with entries not yet contoured (respects `contouring_start_date`)
- `POST /api/contour` — toggle single day
- `POST /api/contour-until` — bulk contour up to a date
- Only active when `contouring_enabled = 1` for the user

## Tracking Start Date

`tracking_start_date` on users table: no entries, absences, or closures possible before this date. Default: 2026-01-01. Affects:
- Kalender (days before are disabled)
- Balance calculation start
- Missing entries check
- Jahresabschluss: only months from tracking_start_date must be closed

## Impersonation (Admin)

Admin can act as another user:
- `POST /admin/impersonate/<user_id>` — sets `session['impersonator_id']`
- `POST /admin/impersonate/stop` — restores admin session
- Orange banner shown on all pages during impersonation
- Admins cannot impersonate other admins

## Route Groups

| Prefix | Description |
|--------|-------------|
| `/setup`, `/login`, `/logout` | Auth |
| `/`, | Dashboard |
| `/day/<YYYY-MM-DD>` | Day detail, time block CRUD |
| `/balance` | Gleitzeitkonto with month/year selector |
| `/absences` | Absence CRUD |
| `/business_trips` | Business trip CRUD |
| `/calendar` | Month calendar view |
| `/settings` | User preferences (accordion: personal, vacation, schedule, contouring) |
| `/periods` | Month/year close |
| `/export/*` | CSV exports |
| `/admin/*` | Admin: users, schedules, vacation overrides, impersonation |
| `/api/contour*` | Contouring API |

## UI Conventions

- All buttons use `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger` classes
- Back button (`← Zurück`, `history.back()`) on all navigable pages — defined once in `layout()` in `templates.py`
- Timepicker: 15-minute steps enforced on both frontend (rounding on blur) and backend
- Mobile: responsive layout, same routes, compact Gleitzeitkonto table view
- CSS variables for theming: `--accent`, `--ok`, `--danger`, `--mu`, `--surface`, `--surface2`, `--text`
- App version: `APP_VERSION = "v4.6.6"` at top of `app.py`

## Important Implementation Notes

- Zeitschema overlaps: warn user when new schedule overlaps existing one
- Jahresabschluss: skip months before `tracking_start_date` — they must not block the close
- Gleitzeitkonto table: multiple time_blocks per day → first row shows Tag+Datum+Delta, subsequent rows blank Tag+Datum, no Delta
- `_calc_balance_end_at` must stay in sync with `balance_view` logic — both use `_iter_days`
