# CLAUDE.md

Guidance for Claude Code when working with this repository.

## Project Overview

**Zeiterfassung** (v1.4.5) is a multi-user German-language time tracking web app built with Flask + SQLite, deployed at `/opt/zeiterfassung`, running as a Gunicorn systemd service. Users record work time blocks, absences, and business trips; the app computes flex-time balances against configurable work schedules. All content and UI is in German.

## Running the Application

```bash
# Production (Gunicorn via systemd)
systemctl restart zeiterfassung zeiterfassung-bot
systemctl is-active zeiterfassung zeiterfassung-bot
journalctl -u zeiterfassung -n 50 --no-pager

# Test via Unix socket
curl -s --unix-socket /run/zeiterfassung/zeiterfassung.sock http://localhost/login
```

Database path is configurable via `ZEITERFASSUNG_DB` env var (default: `zeiterfassung.db` in working dir). Use `.venv/bin/python3` — `python` is not available. No test suite, no linting config.

## Standard Workflow (for every change)

1. Edit `app.py` (and `db.py` / `auth.py` / `templates.py` as needed)
2. Syntax check: `.venv/bin/python -m py_compile app.py`
3. Restart: `systemctl restart zeiterfassung zeiterfassung-bot`
4. Verify: `systemctl is-active zeiterfassung zeiterfassung-bot`

## Architecture

All business logic and routes live in a single `app.py` (~11,000 lines). Other modules are narrow:

- **`db.py`** — `init_db()` creates all tables + runs inline `ALTER TABLE` migrations; `connect()` returns `sqlite3.Row`-enabled connection with FK enforcement; `seed_defaults()` inserts fixed absence types
- **`auth.py`** — session-based auth with Werkzeug hashing; decorators: `@login_required`, `@admin_required` (sysadmin + timemanager), `@sysadmin_required` (sysadmin only), `@timemanager_required` (alias for admin_required); helpers: `is_sysadmin()`, `is_timemanager()`; usernames stored/compared lowercase
- **`templates.py`** — single `layout()` function rendering the full HTML shell (nav, CSS variables, responsive styles, back-button, impersonation banner); all page bodies are f-strings in `app.py`
- **`bot.py`** — Telegram bot with APScheduler; `_is_bot_admin(telegram_id)` checks ADMIN_IDS set OR DB admin_role
- **`backup.py`** — backup/restore logic (full / settings / user data)
- **`calendar_seed.py`** — seeds NRW public holidays for 2026

Local `layout()` wrapper in `app.py` (line ~39): `def layout(title, body, user, version, show_back=True)` — delegates to `base_layout` (imported as `from templates import layout as base_layout`), injects MOBILE_ASSETS and impersonation banner.

## Admin Roles

Two admin roles controlled by `admin_role` column on `users` table:

| Value | Role | Access |
|-------|------|--------|
| `NULL` | Normal user | `is_admin=0` |
| `'sysadmin'` | 🔧 Systemadmin | `is_admin=1`; both admin tabs |
| `'timemanager'` | 📋 Zeitmanager | `is_admin=1`; only "Benutzerübersichten" tab |

### Decorator Usage

| Decorator | Who can access |
|-----------|---------------|
| `@admin_required` | sysadmin + timemanager (checks `is_admin=1`) |
| `@timemanager_required` | alias for `@admin_required` |
| `@sysadmin_required` | only `admin_role='sysadmin'` |

### Sysadmin-only Routes

- `/admin/users/new`, `/admin/users/<id>/delete`
- `/admin/backup/*` (all backup routes)
- `/admin/update/*`, `/admin/bot/*`, `/admin/bot-config/save`
- `/admin/mail-settings` (GET + POST), `/admin/mail-settings/test`
- `/admin/appearance`, `/admin/overtime/save-defaults`
- `/export/users.csv`

### Both-role Routes

- `GET /admin` (main), `/admin/users/<id>/edit` (limited for timemanager: no role change)
- `/admin/schedule/*`, `/admin/impersonate/*`
- `/admin/users/<id>/vacation-carryover*`
- `/admin/periods`, `/admin/periods/unlock`
- `/admin/absences`, `/admin/absences/export`
- `/admin/overtime/save`, `/admin/overtime/check`

### Helper Functions

```python
is_sysadmin(u=None) -> bool   # checks admin_role == 'sysadmin'
is_timemanager(u=None) -> bool  # True for both sysadmin and timemanager
set_admin_role(user_id, role)   # sets admin_role + syncs is_admin flag
set_active(user_id, is_active)  # sets is_active only
```

## Database Schema

Key tables:

| Table | Description |
|-------|-------------|
| `users` | User accounts; key columns below |
| `user_schedules` | Validity-dated work schedules (1:N per user) |
| `time_blocks` | Multiple time blocks per day (current model) |
| `time_entries` | Legacy single-entry-per-day |
| `absences` | Linked to `absence_types` (exactly 3: Urlaub, Krank, Sonstige) |
| `absence_remarks` | Per-user free-text remark history for Sonstige |
| `calendar_days` | Holiday/weekend flags by ISO date + region (DE-NW) |
| `contoured_days` | Days marked as contoured (user_id, day) |
| `vacation_carryover_overrides` | Per-user/year carryover exceptions |
| `weekend_exceptions` | Per-user exceptions allowing work on weekends/holidays |
| `period_locks` | Month/year locks per user |
| `mail_config` | SMTP config (mail_server, mail_port, mail_username, mail_password, mail_from) |
| `bot_config` | Telegram bot config (bot_token, anthropic_api_key, admin_telegram_ids) |
| `app_config` | App-wide settings (accent_color, nav_color, app_label, app_label_color, overtime_default_limit_plus, overtime_default_limit_minus) |
| `backup_config` | Backup settings (auto_backup_enabled, auto_backup_time, last_backup_time) |
| `telegram_users` | Telegram ID ↔ user_id mapping; wizard_enabled, reminder_time |

### users Table – Key Columns

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `username` | TEXT | Unique, lowercase |
| `is_admin` | INTEGER | 1 for sysadmin + timemanager |
| `admin_role` | TEXT | NULL / 'sysadmin' / 'timemanager' |
| `is_active` | INTEGER | 0 = disabled |
| `tracking_start_date` | TEXT | Earliest recordable date |
| `display_name` | TEXT | Display name (optional) |
| `email` | TEXT | For notifications |
| `overtime_limit_plus` | INTEGER | Plus-limit in minutes (NULL = use default) |
| `overtime_limit_minus` | INTEGER | Minus-limit in minutes (NULL = use default) |
| `supervisor_email` | TEXT | For overtime notifications |
| `overtime_notify_enabled` | INTEGER | 1 = send notifications |
| `overtime_notify_interval` | TEXT | 'once' / 'daily' / 'weekly' |
| `overtime_last_notified` | TEXT | ISO date of last notification |
| `vacation_carryover_exception` | INTEGER | 1 = no 31.03. expiry rule |
| `contouring_enabled` | INTEGER | 1 = contouring active |
| `birth_date` | TEXT | For retirement countdown |
| `retirement_age` | INTEGER | Default 67 |

## Schedule System

`workdays_mask` bitmask: Mon=1, Tue=2, Wed=4, Thu=8, Fri=16, Sat=32, Sun=64. Default Mon–Fri = 31.

Two modes (`mode` in `user_schedules`):
- `weekly` — `weekly_minutes` divided evenly across mask-matching days
- `daily` — explicit per-weekday columns (`mon_minutes` … `sun_minutes`)

## Balance Calculation

`_expected_minutes_for_day(user_id, iso_day)` priority:
1. Holiday/weekend → 0
2. Mask check → 0
3. Absence check → 0
4. Schedule-based computation

`_calc_balance_end_at(user_id, end_iso)` iterates **all days** via `_iter_days(start_iso, end_iso)`.

**Flextag rule**: past Flextag days deduct additionally `_scheduled_minutes_ignoring_absence()`.

## CSV Export

`_build_rich_day_export(user_id, date_from, date_to)` — columns:
`Wochentag | Datum | Beginn | Ende | Pause (min) | Soll | Delta | Bemerkung`

UTF-8 BOM encoding, semicolon delimiter.

## Mail Configuration

`_get_mail_config()` reads from `mail_config` DB table, falls back to env vars. `_send_mail_simple(to, subject, body)` uses `username` as SMTP envelope sender (not `mail_from`); `From` header is formatted as `"Display Name <username>"` when `mail_from` has no `@`.

## Backup Types

| Type | Content | Route |
|------|---------|-------|
| Full | Complete SQLite DB file | `/admin/backup/download` |
| Settings | Mail + Bot config as JSON (no passwords) | `/admin/backup/settings/export` |
| User data | Single user: time blocks, absences, schedule | `/admin/backup/user/export?user_id=N` |

## Admin UI – Tab Structure

Admin page (`/admin`) has two tabs:

**⚙ Systemeinstellungen** (`data-tab="system"`, sysadmin only):
`acc-user`, `acc-mail`, `acc-overtime-defaults`, `acc-appearance`, `acc-backup`, `acc-bot`, `acc-update`

**👥 Benutzerübersichten** (`data-tab="users"`, both roles):
`acc-absoverview`, `acc-overtime`, `acc-zeit`, `acc-urlaub`, `acc-abschl`

Tab persistence via `sessionStorage.getItem('adminTab')`. Default: `'system'` for sysadmin, `'users'` for timemanager. Hash-based auto-open switches to the correct tab.

## Overtime Notifications

`_run_overtime_notifications()` in `app.py` and `check_overtime_limits()` in `bot.py` (runs daily at 08:00):
- Checks all users with `overtime_notify_enabled=1`
- Respects `overtime_notify_interval`: `'once'` (only if never notified), `'daily'`, `'weekly'`
- Sends email via `_send_mail_simple` + Telegram if user has telegram linked
- Updates `overtime_last_notified` on send

## Contour System

- `contoured_days` table: (user_id, day)
- Only active when `contouring_enabled = 1` for the user
- `POST /api/contour` — toggle single day
- `POST /api/contour-until` — bulk contour up to a date

## Impersonation (Admin)

Admin can act as another user:
- `POST /admin/impersonate/<user_id>` — sets `session['impersonator_id']`; only for non-admin users (`is_admin=0`)
- `POST /admin/impersonate/stop` — restores admin session
- Orange banner shown on all pages during impersonation

## UI Conventions

- All buttons use `.btn` base class + modifiers: `.btn-primary`, `.btn-danger`, `.btn-sm`, `.btn-lg`
- CSS variables: `--bg`, `--sf`, `--bd`, `--tx`, `--mu`, `--ac`, `--ac-fg`, `--danger`, `--ok`, `--r`, `--rs`, `--nav-bg`
- Back button (`← Zurück`, `goBack()`) defined in `templates.py` global script block; `show_back=False` on dashboard
- Timepicker: 15-minute steps enforced on both frontend (`snapTo15`) and backend (`_round_to_15()`)
- Accordion pattern: CSS `.acc`/`.acc-hdr`/`.acc-body` + JS `accToggle(id)`
- Admin page: tab bar with `data-tab` attributes + `switchTab()` JS

## Important Implementation Notes

- **f-string JS escaping**: In f-strings, use `{{` / `}}` for literal JS braces.
- **`display:contents` on forms**: Use when a `<form>` is inside a flex/grid container.
- `_calc_balance_end_at` must stay in sync with `balance_view` logic — both use `_iter_days`
- App version: `APP_VERSION = "v1.4.5"` at top of `app.py`; also in `templates.py` default parameter
