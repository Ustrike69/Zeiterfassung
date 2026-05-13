# CLAUDE.md

Guidance for Claude Code when working with this repository.

## Project Overview

**Zeiterfassung** (v1.0.0) is a multi-user German-language time tracking web app built with Flask + SQLite, deployed at `/opt/zeiterfassung`, running as a Gunicorn systemd service. Users record work time blocks, absences, and business trips; the app computes flex-time balances against configurable work schedules. All content and UI is in German.

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

## Standard Workflow (for every change)

1. Edit `app.py` (and `db.py` / `templates.py` as needed)
2. Syntax check: `.venv/bin/python3 -c "import app"`
3. Clear cache: `find /opt/zeiterfassung/__pycache__ -name "*.pyc" -delete`
4. Restart: `systemctl restart zeiterfassung.service && systemctl is-active zeiterfassung.service`
5. Verify version: `curl -s --unix-socket /run/zeiterfassung/zeiterfassung.sock http://localhost/login | grep -o "v[0-9.]*"`

## Architecture

All business logic and routes live in a single `app.py` (~8,000 lines). Other modules are narrow:

- **`db.py`** — `init_db()` creates all tables + runs inline `ALTER TABLE` migrations; `connect()` returns `sqlite3.Row`-enabled connection with FK enforcement; `seed_defaults()` inserts fixed absence types
- **`auth.py`** — session-based auth with Werkzeug hashing; `@login_required` / `@admin_required` decorators; usernames stored/compared lowercase
- **`templates.py`** — single `layout()` function rendering the full HTML shell (nav, CSS variables, responsive styles, back-button, impersonation banner); all page bodies are f-strings in `app.py`
- **`calendar_seed.py`** — seeds NRW public holidays for 2026

Local `layout()` wrapper in `app.py` (line ~39): `def layout(title, body, user, version, show_back=True)` — delegates to `base_layout` (imported as `from templates import layout as base_layout`), injects MOBILE_ASSETS and impersonation banner.

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
| `period_locks` | Month/year locks per user |
| `mail_config` | SMTP config (keys: mail_server, mail_port, mail_username, mail_password, mail_from); DB values override env vars |

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

## CSV Export

`_build_rich_day_export(user_id, date_from, date_to)` — day-by-day export with columns:
`Wochentag | Datum | Beginn | Ende | Pause (min) | Soll | Delta | Bemerkung`

- Bemerkung combines: holiday name, absence type (Sonstige → comment text), business trip destination
- Multiple blocks per day: first row has day-level data, subsequent rows only Beginn/Ende/Pause
- UTF-8 BOM encoding, semicolon delimiter

`_send_mail(to, subject, body_text, attachment_name, attachment_bytes)` — SMTP via `_get_mail_config()` (DB first, env var fallback), STARTTLS port 587, 10s timeout.

## Mail Configuration

`_get_mail_config()` reads from `mail_config` DB table, falls back to env vars (`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`). `_save_mail_config()` updates DB; password only updated when explicitly changed (not placeholder).

## Contour System

- `contoured_days` table: (user_id, day)
- `_get_contoured_days()` — set of contoured days for a date range
- `_get_uncontoured_days()` — past workdays with entries not yet contoured (respects `contouring_start_date`)
- `POST /api/contour` — toggle single day
- `POST /api/contour-until` — bulk contour up to a date
- Only active when `contouring_enabled = 1` for the user

## Tracking Start Date

`tracking_start_date` on users table: no entries, absences, or closures possible before this date. Default: 2026-01-01. Affects balance start, missing entries check, Jahresabschluss validation.

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
| `/` | Dashboard |
| `/day/<YYYY-MM-DD>` | Day detail, time block CRUD (compact 2-col grid) |
| `/balance` | Gleitzeitkonto with month/year selector |
| `/absences` | Absence CRUD |
| `/business_trips` | Business trip CRUD |
| `/calendar` | Month calendar view |
| `/settings` | User preferences (accordion: personal, vacation, schedule, contouring) |
| `/periods` | Month/year close |
| `/export` | CSV downloads + email send |
| `/export/mail` | POST: generate CSV and send via SMTP |
| `/admin` | Admin dashboard (accordion: users, schedules, vacation, periods, mail) |
| `/admin/users/*` | User CRUD, edit, delete, vacation-carryover |
| `/admin/schedule/*` | Schedule edit/delete per user |
| `/admin/periods` | Period locks overview (legacy, still accessible) |
| `/admin/mail-settings` | Mail config page (legacy, still accessible) |
| `/admin/impersonate/*` | Impersonation |
| `/api/contour*` | Contouring API |

## UI Conventions

- All buttons use `.btn` base class + modifiers: `.btn-primary`, `.btn-danger`, `.btn-sm`, `.btn-lg`
- CSS variables: `--bg`, `--sf`, `--bd`, `--tx`, `--mu`, `--ac`, `--ac-fg`, `--danger`, `--ok`, `--r`, `--rs`
- Back button (`← Zurück`, `goBack()`) defined in `templates.py` global script block; `show_back=False` on dashboard
- Timepicker: 15-minute steps enforced on both frontend (`snapTo15` on change event) and backend (`_round_to_15()`)
- Accordion pattern (settings + admin): CSS `.acc`/`.acc-hdr`/`.acc-body` + JS `accToggle(id)`, smooth max-height transition
- Day editor: compact 2-col grid (`.day-grid`) on ≥640px; Soll/Ist/Δ badges in header; exception banner as inline strip (`.exc-banner`)
- Mobile: responsive layout, same routes, compact tables

## Important Implementation Notes

- **f-string JS escaping**: In f-strings, use `{{` / `}}` for literal JS braces. Jinja2 interprets `{{...}}` as template expressions in `render_template_string`.
- **`display:contents` on forms**: Use when a `<form>` is inside a flex/grid container so its children participate directly in the layout.
- Zeitschema overlaps: warn user when new schedule overlaps existing one
- Jahresabschluss: skip months before `tracking_start_date` — they must not block the close
- `_calc_balance_end_at` must stay in sync with `balance_view` logic — both use `_iter_days`
- Stale `.pyc` cache: always `find __pycache__ -name "*.pyc" -delete` before restarting after `templates.py` changes
- App version: `APP_VERSION = "v1.0.0"` at top of `app.py`; also update `templates.py` default parameter comment if needed
