# CLAUDE.md

Guidance for Claude Code when working with this repository.

## Project Overview

**Zeiterfassung** (v3.0.0) is a multi-user time tracking web app built with Flask + SQLite, deployed at `/opt/zeiterfassung`, running as a Gunicorn systemd service. Users record work time blocks, absences, and business trips; the app computes flex-time balances against configurable work schedules. Fully bilingual (DE/EN), with a European public holiday database covering 20 countries.

## Running the Application

```bash
# Production (Gunicorn via systemd)
systemctl restart zeiterfassung zeiterfassung-bot
systemctl is-active zeiterfassung zeiterfassung-bot
journalctl -u zeiterfassung -n 50 --no-pager

# Syntax check before restart
python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"
```

Database path configurable via `ZEITERFASSUNG_DB` env var (default: `zeiterfassung.db`). Use `.venv/bin/python3` for venv operations. No test suite, no linting config.

## Standard Workflow (for every change)

1. Edit `app.py` (and `db.py` / `auth.py` / `templates.py` / `translations.py` as needed)
2. Syntax check: `python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"`
3. Restart: `systemctl restart zeiterfassung zeiterfassung-bot`
4. Verify: `systemctl is-active zeiterfassung zeiterfassung-bot`

## Architecture

All business logic and routes live in a single `app.py` (~12,000 lines). Other modules:

- **`db.py`** — `init_db()` creates all tables + runs inline `ALTER TABLE` migrations; `connect()` returns `sqlite3.Row`-enabled connection with FK enforcement; `seed_defaults()` inserts fixed absence types
- **`auth.py`** — session-based auth with Werkzeug hashing; decorators: `@login_required`, `@admin_required` (sysadmin + timemanager), `@sysadmin_required` (sysadmin only), `@timemanager_required` (alias for admin_required); helpers: `is_sysadmin()`, `is_timemanager()`; usernames stored/compared lowercase
- **`templates.py`** — single `layout()` function rendering the full HTML shell (nav, CSS variables, responsive styles, back-button, impersonation banner)
- **`translations.py`** — i18n framework; `TRANSLATIONS` dict with `"de"` and `"en"` sub-dicts; `t(key, lang=None)` reads `session['lang']` with fallback chain: requested lang → `"en"` → `"de"` → key itself; `fmt_date()` / `fmt_time()` locale-aware formatters
- **`bot.py`** — Telegram bot with APScheduler; `_is_bot_admin(telegram_id)` checks ADMIN_IDS set OR DB admin_role
- **`bot_translations.py`** — bot-specific translations; `t_bot(key, user_id=None, lang=None)` reads user language from DB
- **`backup.py`** — backup/restore logic (full / settings / user data)
- **`calendar_seed.py`** — seeds public holidays for 20 countries / 51 regions; `REGION_GROUPS`, `ALL_REGIONS`, `HOLIDAY_NAMES` (de/en); `_SEED_VERSION` guards re-seeding

Local `layout()` wrapper in `app.py` (line ~39): `def layout(title, body, user, version, show_back=True)` — delegates to `base_layout` (imported as `from templates import layout as base_layout`), injects MOBILE_ASSETS and impersonation banner.

## i18n Framework

```python
from translations import t

# In route handlers and _render_* functions (Flask request context):
t('key')                    # reads session['lang'], fallback en→de→key
t('key', lang='en')         # explicit lang override

# Common translation key prefixes:
# admin.*       admin area (tabs, accordions, labels, buttons)
# absences.*    absence management
# calendar.*    calendar view
# common.*      generic (name, days, date, time, status…)
# export.*      export page
# periods.*     lock periods page
# settings.*    settings page
# schedule.*    schedule labels (mo/tu/we… hours_week mode_weekly/daily)
# trips.*       business trips
# weekday.*     weekday names (0=Mon…6=Sun); weekday.short.*
# month.*       month names (1–12); month.short.*
```

**F-string quoting rule:** Never use `\"` inside `{}` expressions — Python treats `\` as line continuation. Use `t('key')` (single quotes) inside double-quoted f-strings, or `t("key")` inside single-quoted f-strings.

**JS variable conflict:** Never name a Python/Jinja variable `t` in a scope where the `t()` translation function is also used. Use `tk`, `tv`, `trip`, etc.

## Admin Roles

Two admin roles controlled by `admin_role` column on `users` table:

| Value | Role | Access |
|-------|------|--------|
| `NULL` | Normal user | `is_admin=0` |
| `'sysadmin'` | 🔧 Systemadmin | `is_admin=1`; both admin tabs |
| `'timemanager'` | 📋 Zeitmanager | `is_admin=1`; only "Benutzerübersichten" tab |

**Admin-Only users** (`admin_only=1`): no time account; redirected from index/balance/calendar/day to `/admin`; nav shows only Admin + Settings + Help.

### Decorator Usage

| Decorator | Who can access |
|-----------|---------------|
| `@admin_required` | sysadmin + timemanager (checks `is_admin=1`) |
| `@timemanager_required` | alias for `@admin_required` |
| `@sysadmin_required` | only `admin_role='sysadmin'` |

### Approval Routes (login_required + is_approver check)

- `GET /approvals` — approver dashboard: pending queue + decision history
- `POST /approvals/<approval_id>/approve` — approve (uses `absence_approvals.id`)
- `POST /approvals/<approval_id>/reject` — reject with mandatory `comment` field

### Auth / Security Routes

- `GET /login/2fa`, `POST /login/2fa` — TOTP verification step after password login
- `GET /login/unlock/<token>` — self-service account unlock via emailed token
- `GET /change-password`, `POST /change-password` — forced password change

### Sysadmin-only Routes

- `/admin/users/new`, `/admin/users/<id>/delete`
- `/admin/backup/*` (all backup routes)
- `/admin/update/*`, `/admin/bot/*`, `/admin/bot-config/save`
- `/admin/mail-settings` (GET + POST), `/admin/mail-settings/test`
- `/admin/appearance`, `/admin/overtime/save-defaults`
- `/admin/regional`, `/export/users.csv`

### Both-role Routes

- `GET /admin` (main), `/admin/users/<id>/edit` (limited for timemanager: no role change)
- `/admin/schedule/*`, `/admin/impersonate/*`
- `/admin/users/<id>/vacation-carryover*`
- `/admin/periods`, `/admin/periods/unlock`
- `/admin/absences`, `/admin/absences/export`
- `/admin/overtime/save`, `/admin/overtime/check`
- `/admin/batch/absence-types`

### Helper Functions

```python
is_sysadmin(u=None) -> bool       # checks admin_role == 'sysadmin'
is_timemanager(u=None) -> bool    # True for both sysadmin and timemanager
set_admin_role(user_id, role)     # sets admin_role + syncs is_admin flag
set_active(user_id, is_active)    # sets is_active only
```

## Database Schema

Key tables:

| Table | Description |
|-------|-------------|
| `users` | User accounts; key columns below |
| `user_schedules` | Validity-dated work schedules (1:N per user) |
| `time_blocks` | Multiple time blocks per day (current model) |
| `time_entries` | Legacy single-entry-per-day |
| `absences` | Linked to `absence_types` |
| `teams` | id, name, description, color |
| `user_teams` | user_id, team_id (M:N mapping) |
| `absence_approvals` | Approval records per absence: `absence_id`, `approver_id`, `status` (pending/approved/rejected), `comment` |
| `staffing_plans` | id, team_id, name, active — Besetzungspläne pro Team |
| `staffing_slots` | id, plan_id, slot_type, weekdays, nth_week, time_from, time_to, min_staff |
| `staffing_assignments` | id, slot_id, user_id, assignment_type |
| `balance_adjustments` | id, user_id, minutes, reason, adjustment_date — manuelle Gleitzeitkorrekturen |
| `schedule_daily_blocks` | id, schedule_id, weekday, time_from, time_to — mehrere Zeitblöcke pro Schematag |
| `absence_types` | Urlaub, Krank, Flextag, Sonstige (+ custom) |
| `calendar_days` | Holiday/weekend flags by ISO date + region; composite PK (day, region) |
| `contoured_days` | Days marked as contoured (user_id, day) |
| `vacation_carryover_overrides` | Per-user/year carryover exceptions |
| `weekend_exceptions` | Per-user exceptions allowing work on weekends/holidays |
| `period_locks` | Month/year locks per user |
| `mail_config` | SMTP config |
| `bot_config` | Telegram bot config (bot_token, anthropic_api_key, admin_telegram_ids) |
| `app_config` | App-wide settings (colors, labels, limits, language defaults) |
| `backup_config` | Backup settings |
| `telegram_users` | Telegram ID ↔ user_id mapping |

### users Table – Key Columns

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `username` | TEXT | Unique, lowercase |
| `is_admin` | INTEGER | 1 for sysadmin + timemanager |
| `admin_role` | TEXT | NULL / 'sysadmin' / 'timemanager' |
| `admin_only` | INTEGER | 1 = no time account, admin-only |
| `is_active` | INTEGER | 0 = disabled |
| `language` | TEXT | 'de' / 'en' (set on login → session['lang']) |
| `must_change_password` | INTEGER | 1 = forced password change on next login |
| `tracking_start_date` | TEXT | Earliest recordable date |
| `display_name` | TEXT | Display name (optional) |
| `email` | TEXT | For notifications |
| `holiday_region` | TEXT | Region code e.g. 'DE-NW', 'AT-9', 'FR' |
| `enabled_absence_types` | TEXT | Comma-separated type IDs (NULL = standard set) |
| `overtime_limit_plus` | INTEGER | Plus-limit in minutes (NULL = use default) |
| `overtime_limit_minus` | INTEGER | Minus-limit in minutes (NULL = use default) |
| `supervisor_email` | TEXT | For overtime notifications |
| `overtime_notify_enabled` | INTEGER | 1 = send notifications |
| `overtime_notify_interval` | TEXT | 'once' / 'daily' / 'weekly' |
| `vacation_carryover_exception` | INTEGER | 1 = no 31.03. expiry rule |
| `contouring_enabled` | INTEGER | 1 = contouring active |
| `birth_date` | TEXT | For retirement countdown |
| `retirement_age` | INTEGER | Default 67 |
| `calendar_system` | TEXT | 'apple' / 'google' / 'outlook' / 'other' |
| `calendar_export_types` | TEXT | Comma-separated absence type IDs to export (NULL = all) |
| `calendar_export_prefix` | TEXT | Prefix string prepended to each calendar entry |
| `calendar_token` | TEXT | UUID token for subscription URL auth |
| `calendar_auth_mode` | TEXT | 'token' (default) / 'basic' |
| `icloud_enabled` | INTEGER | 1 = outgoing iCloud sync active |
| `icloud_apple_id` | TEXT | Apple ID (iCloud e-mail) |
| `icloud_app_password` | TEXT | Fernet-encrypted app-specific password |
| `icloud_calendar_name` | TEXT | Exact iCloud calendar name to write to |
| `icloud_last_sync` | TEXT | Timestamp of last successful sync (YYYY-MM-DD HH:MM) |
| `is_approver` | INTEGER | 1 = user can approve other users' absences |
| `approver_id` | INTEGER | FK → users.id; who approves this user's absences |
| `approval_required_types` | TEXT | Comma-separated absence type IDs requiring approval (NULL = none) |
| `password_compliant` | INTEGER | 1 = password meets current rules |
| `login_attempts` | INTEGER | Failed login counter (reset on success) |
| `login_locked_until` | TEXT | ISO datetime; account locked until this time |
| `login_unlock_token` | TEXT | UUID token for self-service unlock link |
| `last_login` | TEXT | ISO datetime of last successful login |
| `totp_secret` | TEXT | Fernet-encrypted TOTP secret |
| `totp_enabled` | INTEGER | 1 = 2FA active |
| `totp_backup_codes` | TEXT | Fernet-encrypted JSON array of one-time backup codes |
| `primary_team_id` | INTEGER | FK → teams.id; Haupt-Team des Users |
| `team_restriction` | TEXT | Komma-sep. Team-IDs; schränkt Zeitmanager/Genehmiger auf diese Teams ein |
| `is_superuser` | INTEGER | 1 = Superuser (nur aktiv wenn `ZEITERFASSUNG_DEV_MODE=1`) |

## Schedule System

`workdays_mask` bitmask: Mon=1, Tue=2, Wed=4, Thu=8, Fri=16, Sat=32, Sun=64. Default Mon–Fri = 31.

### user_schedules – Additional Columns (v3.0.0)

| Column | Description |
|--------|-------------|
| `sync_to_staffing` | 1 = Zeitschema-Zeiten in Besetzungsplan übernehmen |
| `sync_plan_id` | FK → staffing_plans.id; Zielplan für den Sync |
| `allow_self_edit` | 1 = Nutzer darf das Schema selbst bearbeiten |

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

**Saldo display**: always "Stand gestern" (as-of yesterday).

## Holidays / Regions

`calendar_seed.py` seeds public holidays for 20 countries / 51 regions. Key structures:
- `REGION_GROUPS` — list of `(flag, label, [(code, label), …])` for grouped UI select
- `ALL_REGIONS` — flat set of all valid region codes for validation
- `_REGION_LABEL` — flat dict `{code: label}` for badges
- `_is_holiday(iso_day, user_id=None)` — region-aware; looks up user's `holiday_region`, falls back to system default, falls back to `DE-NW`
- `_region_picker(name, current, include_default)` — two-step country→region JS picker

## CSV Export

`_build_rich_day_export(user_id, date_from, date_to)` — columns:
`Wochentag | Datum | Beginn | Ende | Pause (min) | Soll | Delta | Bemerkung`

UTF-8 BOM encoding, semicolon delimiter.

### Key Helper Functions (v2.0.9+)

| Function | Description |
|----------|-------------|
| `_get_timezone()` | Reads `timezone` from `app_config`; returns `ZoneInfo` object (default `Europe/Berlin`) |
| `_notify_absence_decision(user_id, email, lang, …)` | Background thread: sends mail + Telegram to requester on approve/reject |
| `_send_approval_request_mail(absence_id, requester, …)` | Background thread: notifies approver of new pending absence |
| `_send_tg_message(user_id, text)` | Fire-and-forget Telegram message via HTTP API; reads token from `bot_config` |
| `_send_absence_decision_mail` | Deprecated alias; use `_notify_absence_decision` |
| `_timezone_select(name, current)` | Renders HTML `<select>` for timezone picker |

**`auth.py` helpers (v2.0.9+):**
- `_get_configured_timezone()` — reads timezone from `app_config` DB table (used in auth.py, no Flask context dependency)
- `_now()` — `datetime.datetime.now(tz=_get_configured_timezone())`
- `_send_lockout_mail(email, token, user_id)` — fire-and-forget thread using `app.app_context()` (not `current_app` proxy)
- `_dispatch_lockout_mail(email, token, user_id)` — called inside app context; fetches user language from DB; logs errors

## Mail Configuration

`_get_mail_config()` reads from `mail_config` DB table, falls back to env vars. `_send_mail_simple(to, subject, body)` uses `username` as SMTP envelope sender; `From` header formatted as display name when `mail_from` has no `@`.

## Backup Types

| Type | Content | Route |
|------|---------|-------|
| Full | Complete SQLite DB file (.db.gz) | `/admin/backup/download` |
| Settings | Mail + Bot config as JSON (no passwords) | `/admin/backup/settings/export` |
| User data | Single user: time blocks, absences, trips, schedules | `/admin/backup/user/export?uid=N` |

Auto-backup: configurable time, max 7 local backups kept.

## Admin UI – Tab Structure

Admin page (`/admin`) has two tabs:

**⚙ Systemeinstellungen** (`data-tab="system"`, sysadmin only):
`acc-user`, `acc-mail`, `acc-overtime-defaults`, `acc-regional`, `acc-appearance`, `acc-backup`, `acc-bot`, `acc-update`

**👥 Benutzerübersichten** (`data-tab="users"`, both roles):
`acc-tm-users`, `acc-absoverview`, `acc-overtime`, `acc-zeit`, `acc-urlaub`, `acc-abschl`, `acc-per-user-settings`

Tab persistence via `sessionStorage.getItem('adminTab')`. Default: `'system'` for sysadmin, `'users'` for timemanager. Hash-based auto-open switches to the correct tab.

Render functions for complex accordions: `_render_backup_section()`, `_render_bot_section()`, `_render_update_section()`, `_render_admin_absences_section()`, `_render_overtime_defaults_section()`, `_render_admin_overtime_section()`, `_render_regional_section()`, `_render_per_user_settings_section()`, `_render_appearance_section()`, `_render_calendar_integration_section()`, `_render_icloud_settings_section()`.

## Calendar / iCloud Integration (v2.0.5)

**iCal export helpers:**
- `_build_ical_for_user(user_id, lang, period)` — builds full iCal string for a user's absences
- `_ical_response(user_id, lang)` — returns Flask `Response` with correct `text/calendar` headers
- `_ical_escape(text)` — escapes special chars for iCal strings

**iCloud encryption:**
- `_icloud_encrypt(text)` / `_icloud_decrypt(token)` — Fernet symmetric encryption using SHA-256 of `app.secret_key`
- `_icloud_update_sync_time(user_id)` — writes current timestamp to `icloud_last_sync`

**Outgoing iCloud sync:**
- `_sync_to_icloud(user_id, absence_id, action)` — syncs one absence to iCloud; `action`: `'create'` / `'update'` / `'delete'`; never raises (all exceptions logged)
- Called at: `absences_new_post`, `absences_edit_post`, `absences_delete`, `day_absence_add`
- Delete path: called **before** DB delete so absence is still in scope; uses raw `httpx.delete()` to bypass iCloud CalDAV 412 precondition errors
- Create/update path: uses `caldav.DAVClient(timeout=10)` via `cal.save_event()`; event URL = `{cal.url}/{uid}.ics` where `uid = f"zeiterfassung-{user_id}-{absence_id}@ustrike"`

**CalDAV server routes** (Home Assistant integration):
- `GET/PROPFIND /caldav/<token>/` — principal discovery (token auth)
- `GET/PROPFIND/REPORT /caldav/<token>/calendar/` — calendar collection
- `GET /caldav/<token>/calendar/<filename>` — single event .ics
- Same three routes under `/caldav/basic/` for HTTP Basic Auth
- Static segments registered before variable `<token>` routes to avoid conflicts

**Calendar subscription routes:**
- `GET /absences/calendar/<token>.ics` — token-authenticated iCal feed
- `GET /absences/calendar/kalender.ics` — HTTP Basic Auth iCal feed (for HA)

## Overtime Notifications

`_run_overtime_notifications()` in `app.py` and `check_overtime_limits()` in `bot.py` (runs daily at 08:00):
- Checks all users with `overtime_notify_enabled=1`
- Respects `overtime_notify_interval`: `'once'` (only if never notified), `'daily'`, `'weekly'`
- Sends email via `_send_mail_simple` + Telegram if user has telegram linked
- Updates `overtime_last_notified` on send

## Password System

- `validate_password(pw)` — min 8 chars, uppercase, digit, special char
- `must_change_password` column — forces `/change-password` on next login
- `_generate_password()` — random 12-char password
- Admin PW reset: generates random password, sets `must_change_password=1`, sends by email if configured

## Impersonation (Admin)

Admin can act as another user:
- `POST /admin/impersonate/<user_id>` — sets `session['impersonator_id']`; only for non-admin users (`is_admin=0`)
- `POST /admin/impersonate/stop` — restores admin session
- Orange banner shown on all pages during impersonation

## UI Conventions

- All buttons use `.btn` base class + modifiers: `.btn-primary`, `.btn-danger`, `.btn-sm`, `.btn-lg`
- CSS variables: `--bg`, `--sf`, `--bd`, `--tx`, `--mu`, `--ac`, `--ac-fg`, `--danger`, `--ok`, `--r`, `--rs`, `--nav-bg`
- Back button (`← Zurück` / `← Back`, `goBack()`) defined in `templates.py`; `show_back=False` on dashboard
- Timepicker: 15-minute steps enforced on both frontend (`snapTo15`) and backend (`_round_to_15()`)
- Accordion pattern: CSS `.acc`/`.acc-hdr`/`.acc-body` + JS `accToggle(id)`
- Admin page: tab bar with `data-tab` attributes + `switchTab()` JS

## Important Implementation Notes

- **f-string JS escaping**: In f-strings, use `{{` / `}}` for literal JS braces.
- **`display:contents` on forms**: Use when a `<form>` is inside a flex/grid container.
- **JS strings from Python**: Pre-compute `t()` values into Python vars (e.g., `_lbl = t('key')`), then embed via `repr(_lbl)` in `<script>` blocks to avoid quote conflicts.
- `_calc_balance_end_at` must stay in sync with `balance_view` logic — both use `_iter_days`
- `bootstrap()` called on every route → runs `init_db()` + `seed_defaults()` + `seed_all_regions()`
- App version: `APP_VERSION = "v3.0.0"` at top of `app.py`
- Dev-Mode: `ZEITERFASSUNG_DEV_MODE=1` env var activates superuser features and debug tooling
