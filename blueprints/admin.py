"""
Blueprint: Admin-Verwaltung.

Alle Routen unter /admin/* sowie /settings/admin-only.

bootstrap, add_flash und weitere app.py-Helpers werden lokal in jeder Route
importiert, um den zirkulären Import (app.py → blueprint → app.py) zu vermeiden.
"""
from flask import Blueprint, request, redirect, url_for, send_file, jsonify, session, render_template_string, abort
import datetime
import re
from db import connect
from auth import login_required, admin_required, sysadmin_required, current_user, timemanager_required, is_sysadmin, is_timemanager, set_active, set_admin_role, set_password, set_must_change_password, unlock_account
from calendar_seed import ALL_REGIONS, REGION_GROUPS
from translations import t

admin_bp = Blueprint("admin", __name__)


@admin_bp.post("/settings/admin-only")
@login_required
def settings_admin_only():
    from app import bootstrap, add_flash, flash_html, layout, FORM_ASSETS_JS, _date_input, _fmt_date_de, _fmt_minutes_signed, _parse_date_input, _send_mail_simple, _send_mail, _build_csv_bytes, _parse_sched_blocks_from_form, _sched_save_blocks, _sched_save_exceptions_from_form, _vacation_calc, _fmt_backup_size, _record_last_backup, _get_backup_config, _save_backup_config, _get_mail_config, _save_mail_config, _get_bot_config, _save_bot_config, _bot_service_status, _bot_service_exists, _git_pending_commits, _run_update, _git_last_commit_info, _service_started_at, _fmt_minutes
    bootstrap()
    u = current_user()
    if not is_sysadmin(u):
        abort(403)
    new_val = 1 if (request.form.get("admin_only") or "0") == "1" else 0
    db = connect()
    db.execute(
        "UPDATE users SET admin_only=?, updated_at=datetime('now') WHERE id=?",
        (new_val, u["id"]),
    )
    db.commit()
    db.close()
    msg = t("flash.success.time_tracking_disabled") if new_val else t("flash.success.time_tracking_enabled")
    add_flash(msg, "success")
    return redirect("/settings")


# ── iCloud Einstellungen ───────────────────────────────────────────────────────

def _render_icloud_settings_section(
    ic_enabled: bool,
    ic_apple_id: str,
    ic_has_pw: bool,
    ic_cal_name: str,
    ic_last_sync: str,
) -> str:
    lang = session.get("lang", "en")
    chk  = "checked" if ic_enabled else ""
    _pw_placeholder = "••••••••" if ic_has_pw else ""
    _pw_keep_note   = (f"<div class='small' style='color:var(--mu);margin-top:3px;'>"
                       f"{_html.escape(t('settings.icloud_pw_keep', lang=lang))}</div>") if ic_has_pw else ""
    _last_sync_html = ""
    if ic_last_sync:
        _last_sync_html = (f"<div class='small' style='color:var(--mu);margin-top:6px;'>"
                           f"{_html.escape(t('settings.icloud_last_sync', lang=lang))}: "
                           f"{_html.escape(ic_last_sync)}</div>")
    _t_test     = _html.escape(t("settings.icloud_test",     lang=lang))
    _t_sync_all = _html.escape(t("settings.icloud_sync_all", lang=lang))
    return f"""
    <div class="acc" id="acc-icloud">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-icloud-body')">
        <span>{t('settings.icloud_integration')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-icloud-body">
        <div class="acc-inner">
          <form method="post" action="/settings/icloud">
            <div class="acc-sub" style="margin-top:0;padding-top:0;border-top:none;">
              <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-bottom:10px;">
                <input type="checkbox" name="icloud_enabled" value="1" {chk}>
                <span>{_html.escape(t('settings.icloud_enabled', lang=lang))}</span>
              </label>
              <div style="display:flex;flex-direction:column;gap:10px;max-width:420px;">
                <div>
                  <label>{_html.escape(t('settings.icloud_apple_id', lang=lang))}</label><br>
                  <input type="email" name="icloud_apple_id" value="{_html.escape(ic_apple_id)}"
                         placeholder="name@icloud.com" autocomplete="off" data-lpignore="true"
                         style="width:100%;margin-top:4px;">
                </div>
                <div>
                  <label>{_html.escape(t('settings.icloud_app_password', lang=lang))}</label><br>
                  <input type="password" name="icloud_app_password" value=""
                         placeholder="{_pw_placeholder}" autocomplete="new-password" data-lpignore="true"
                         style="width:100%;margin-top:4px;">
                  {_pw_keep_note}
                  <div class="small" style="color:var(--mu);margin-top:3px;">
                    {_html.escape(t('settings.icloud_app_password_hint', lang=lang))}
                  </div>
                </div>
                <div>
                  <label>{_html.escape(t('settings.icloud_calendar_name', lang=lang))}</label><br>
                  <input type="text" name="icloud_calendar_name" value="{_html.escape(ic_cal_name)}"
                         placeholder="Familie" style="width:100%;margin-top:4px;">
                  <div class="small" style="color:var(--mu);margin-top:3px;">
                    {_html.escape(t('settings.icloud_calendar_hint', lang=lang))}
                  </div>
                </div>
              </div>
            </div>
            <div class="acc-sub" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              <button class="btn btn-sm" type="submit">{t('common.save')}</button>
            </div>
          </form>
          <div class="acc-sub">
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              <button class="btn btn-sm" type="button" id="icloud-test-btn"
                      onclick="icloudTest()">{_t_test}</button>
              <button class="btn btn-sm" type="button" id="icloud-sync-btn"
                      onclick="icloudSyncAll()">{_t_sync_all}</button>
            </div>
            <div id="icloud-action-result" style="margin-top:8px;font-size:13px;"></div>
            {_last_sync_html}
          </div>
        </div>
      </div>
    </div>
    <script>
    function icloudTest(){{
      var btn=document.getElementById('icloud-test-btn');
      var res=document.getElementById('icloud-action-result');
      btn.disabled=true; res.textContent='…';
      fetch('/settings/icloud/test')
        .then(r=>r.json())
        .then(d=>{{
          if(d.ok){{ res.style.color='var(--ok)'; res.textContent=d.message; }}
          else{{ res.style.color='var(--err,#c00)'; res.textContent=d.error; }}
        }})
        .catch(e=>{{ res.style.color='var(--err,#c00)'; res.textContent=''+e; }})
        .finally(()=>{{ btn.disabled=false; }});
    }}
    function icloudSyncAll(){{
      var btn=document.getElementById('icloud-sync-btn');
      var res=document.getElementById('icloud-action-result');
      btn.disabled=true; res.textContent='…';
      fetch('/settings/icloud/sync-all',{{method:'POST',headers:{{'X-Requested-With':'XMLHttpRequest'}}}})
        .then(r=>r.json())
        .then(d=>{{
          if(d.ok){{ res.style.color='var(--ok)'; res.textContent=d.message; }}
          else{{ res.style.color='var(--err,#c00)'; res.textContent=d.error; }}
        }})
        .catch(e=>{{ res.style.color='var(--err,#c00)'; res.textContent=''+e; }})
        .finally(()=>{{ btn.disabled=false; }});
    }}
    </script>"""


def _parse_hhmm_to_minutes(val: str) -> int:
    val = (val or "").strip()
    if not val:
        return 0
    if not re.match(r"^\d{2}:\d{2}$", val):
        raise ValueError("Format HH:MM erwartet")
    h, m = [int(x) for x in val.split(":")]
    return h*60 + m


def _csv_response(filename: str, headers: list, data: list, delimiter: str = ";"):
    """Build CSV with given delimiter (default ;) and return Flask Response for download."""
    import csv
    from io import StringIO
    from flask import Response
    buf = StringIO()
    w = csv.writer(buf, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
    w.writerow(headers)
    w.writerows(data)
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _build_csv_bytes(headers: list, data: list, delimiter: str = ";") -> bytes:
    import csv
    from io import StringIO
    buf = StringIO()
    w = csv.writer(buf, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
    w.writerow(headers)
    w.writerows(data)
    return buf.getvalue().encode("utf-8-sig")


def _get_mail_config() -> dict:
    """Read SMTP config from mail_config table, falling back to env vars."""
    import os
    db = connect()
    rows = db.execute("SELECT key, value FROM mail_config").fetchall()
    db.close()
    cfg = {r["key"]: (r["value"] or "") for r in rows}
    # Env var fallback for any key not set in DB
    defaults = {
        "mail_server":   os.environ.get("MAIL_SERVER", ""),
        "mail_port":     os.environ.get("MAIL_PORT", "587"),
        "mail_username": os.environ.get("MAIL_USERNAME", ""),
        "mail_password": os.environ.get("MAIL_PASSWORD", ""),
        "mail_from":     os.environ.get("MAIL_FROM", ""),
    }
    for k, v in defaults.items():
        if not cfg.get(k):
            cfg[k] = v
    return cfg


def _save_mail_config(server: str, port: str, username: str, password: str, from_addr: str, update_password: bool) -> None:
    db = connect()
    now = "datetime('now')"
    for key, val in [
        ("mail_server",   server),
        ("mail_port",     port),
        ("mail_username", username),
        ("mail_from",     from_addr),
    ]:
        db.execute(
            "UPDATE mail_config SET value=?, updated_at=datetime('now') WHERE key=?",
            (val, key),
        )
    if update_password:
        db.execute(
            "UPDATE mail_config SET value=?, updated_at=datetime('now') WHERE key='mail_password'",
            (password,),
        )
    db.commit()
    db.close()


_MAIL_PW_PLACEHOLDER = "••••••••"


# ── Backup helpers ─────────────────────────────────────────────────────────────

def _get_backup_config() -> dict:
    db = connect()
    try:
        rows = db.execute("SELECT key, value FROM backup_config").fetchall()
    except Exception:
        rows = []
    finally:
        db.close()
    return {r["key"]: r["value"] for r in rows}


def _save_backup_config(enabled: bool, backup_time: str,
                        auto_encrypt_enabled: bool = False,
                        auto_encrypt_password: str = "") -> None:
    db = connect()
    try:
        db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('auto_backup_enabled',?,datetime('now'))", ("1" if enabled else "0",))
        db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('auto_backup_time',?,datetime('now'))", (backup_time,))
        db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('auto_encrypt_enabled',?,datetime('now'))", ("1" if auto_encrypt_enabled else "0",))
        if auto_encrypt_password:
            from backup import encrypt_password as _enc_pw
            _secret = app.secret_key
            db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('auto_encrypt_password',?,datetime('now'))", (_enc_pw(auto_encrypt_password, _secret),))
        elif not auto_encrypt_enabled:
            db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('auto_encrypt_password',?,datetime('now'))", ("",))
        db.commit()
    finally:
        db.close()


def _record_last_backup() -> None:
    db = connect()
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("INSERT OR REPLACE INTO backup_config(key,value,updated_at) VALUES('last_backup_time',?,datetime('now'))", (now,))
        db.commit()
    finally:
        db.close()


def _fmt_backup_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    return f"{n/1024/1024:.1f} MB"


# ── Bot-Config helpers ─────────────────────────────────────────────────────────

def _get_bot_config() -> dict:
    db = connect()
    try:
        rows = db.execute("SELECT key, value FROM bot_config").fetchall()
    except Exception:
        rows = []
    finally:
        db.close()
    return {r["key"]: r["value"] for r in rows}


def _save_bot_config(token: str, api_key: str, admin_ids: str) -> None:
    db = connect()
    try:
        for key, val in (("bot_token", token), ("anthropic_api_key", api_key), ("admin_telegram_ids", admin_ids)):
            db.execute(
                "INSERT OR REPLACE INTO bot_config(key,value,updated_at) VALUES(?,?,datetime('now'))",
                (key, val),
            )
        db.commit()
    finally:
        db.close()


# ── System helpers ─────────────────────────────────────────────────────────────

def _bot_service_status() -> str:
    import subprocess
    try:
        r = subprocess.run(["systemctl", "is-active", "zeiterfassung-bot"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return "unknown"


def _bot_service_exists() -> bool:
    return os.path.exists("/etc/systemd/system/zeiterfassung-bot.service")


_GIT_REMOTE_URL = "https://github.com/Ustrike69/Zeiterfassung.git"


def _git_pending_commits() -> "list[str] | None | str":
    import subprocess
    project = os.path.dirname(os.path.abspath(__file__))
    try:
        subprocess.run(
            ["git", "-C", project, "remote", "set-url", "origin", _GIT_REMOTE_URL],
            capture_output=True, timeout=5,
        )
        r_fetch = subprocess.run(
            ["git", "-C", project, "fetch", "origin", "main"],
            capture_output=True, text=True, timeout=20,
        )
        if r_fetch.returncode != 0:
            err = r_fetch.stderr.strip() or r_fetch.stdout.strip() or "fetch failed"
            return f"ERROR:{err}"
        r = subprocess.run(
            ["git", "-C", project, "log", "HEAD..origin/main", "--oneline"],
            capture_output=True, text=True, timeout=5,
        )
        lines = [ln.strip() for ln in r.stdout.strip().splitlines() if ln.strip()]
        return lines
    except Exception as e:
        return f"ERROR:{e}"


def _git_last_commit_info() -> str:
    import subprocess
    try:
        r = subprocess.run(
            ["git", "-C", "/opt/zeiterfassung", "log", "-1",
             "--format=%h  %s  (%cd)", "--date=format:%d.%m.%Y %H:%M"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip()
    except Exception:
        return "–"


def _service_started_at(name: str) -> str:
    import subprocess
    try:
        r = subprocess.run(
            ["systemctl", "show", name, "--property=ActiveEnterTimestamp"],
            capture_output=True, text=True, timeout=5,
        )
        val = r.stdout.strip().replace("ActiveEnterTimestamp=", "").strip()
        return val or "–"
    except Exception:
        return "–"


def _run_update() -> "tuple[bool, list[str]]":
    import subprocess
    project = os.path.dirname(os.path.abspath(__file__))
    out = []

    # Remote URL setzen
    subprocess.run(
        ["git", "-C", project, "remote", "set-url", "origin", _GIT_REMOTE_URL],
        capture_output=True, timeout=5,
    )

    # Lokale Änderungen stashen (verhindert Pull-Fehler)
    r_stash = subprocess.run(
        ["git", "-C", project, "stash", "--include-untracked"],
        capture_output=True, text=True, timeout=10,
    )
    stashed = "No local changes" not in r_stash.stdout
    if stashed:
        out.append(f"git stash: {r_stash.stdout.strip()}")

    # Pull
    r1 = subprocess.run(
        ["git", "-C", project, "pull", "origin", "main"],
        capture_output=True, text=True, timeout=60,
    )
    out.append("git pull:")
    out.append(r1.stdout.strip() or r1.stderr.strip() or "(keine Ausgabe)")

    if r1.returncode != 0:
        # Stash wiederherstellen wenn Pull fehlschlug
        if stashed:
            subprocess.run(
                ["git", "-C", project, "stash", "pop"],
                capture_output=True, timeout=10,
            )
        return False, out

    # Pip install
    r2 = subprocess.run(
        [f"{project}/.venv/bin/pip", "install", "-r",
         f"{project}/requirements.txt", "-q"],
        capture_output=True, text=True, timeout=120,
    )
    out.append("pip install:")
    msg = r2.stdout.strip()
    if r2.stderr.strip():
        msg += ("\n" if msg else "") + r2.stderr.strip()
    out.append(msg or "(keine neuen Pakete)")
    return r2.returncode == 0, out


def _send_mail(to: str, subject: str, body_text: str, attachment_name: str, attachment_bytes: bytes) -> None:
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders

    cfg = _get_mail_config()
    server    = cfg.get("mail_server", "")
    port      = int(cfg.get("mail_port") or "587")
    username  = cfg.get("mail_username", "")
    password  = cfg.get("mail_password", "")
    from_addr = cfg.get("mail_from") or username

    if not server or not username:
        raise RuntimeError("SMTP nicht konfiguriert (Mailserver / Benutzername fehlt).")
    if not password:
        raise RuntimeError("SMTP-Passwort nicht konfiguriert.")

    msg = MIMEMultipart()
    msg["From"]    = from_addr
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    part = MIMEBase("text", "csv")
    part.set_payload(attachment_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
    msg.attach(part)

    with smtplib.SMTP(server, port, timeout=10) as s:
        s.ehlo()
        s.starttls()
        s.login(username, password)
        s.sendmail(username, [to], msg.as_string())


def _send_mail_simple(to: str, subject: str, body_text: str) -> None:
    import smtplib
    from email.mime.text import MIMEText as _MIMEText
    cfg = _get_mail_config()
    server    = cfg.get("mail_server", "")
    port      = int(cfg.get("mail_port") or "587")
    username  = cfg.get("mail_username", "")
    password  = cfg.get("mail_password", "")
    from_addr = cfg.get("mail_from") or username
    if not server or not username:
        raise RuntimeError("SMTP nicht konfiguriert.")
    if not password:
        raise RuntimeError("SMTP-Passwort nicht konfiguriert.")
    msg = _MIMEText(body_text, "plain", "utf-8")
    from_header = f"{from_addr} <{username}>" if from_addr and "@" not in from_addr else (from_addr or username)
    msg["From"]    = from_header
    msg["To"]      = to
    msg["Subject"] = subject
    with smtplib.SMTP(server, port, timeout=10) as s:
        s.ehlo()
        s.starttls()
        s.login(username, password)
        s.sendmail(username, [to], msg.as_string())


def _send_tg_message(user_id: int, text: str) -> None:
    """Send a Telegram message to a user (fire-and-forget). Uses bot token from bot_config."""
    import threading as _thr
    def _do():
        try:
            import urllib.request as _ur
            import urllib.parse as _up
            db = connect()
            cfg = db.execute("SELECT key, value FROM bot_config").fetchall()
            tg_row = db.execute("SELECT telegram_id FROM telegram_users WHERE user_id=?", (user_id,)).fetchone()
            db.close()
            token = next((r["value"] for r in cfg if r["key"] == "bot_token"), None)
            if not token or not tg_row:
                return
            chat_id = tg_row["telegram_id"]
            data = _up.urlencode({"chat_id": chat_id, "text": text}).encode()
            _ur.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=10)
        except Exception as e:
            app.logger.warning(f"TG-Nachricht Fehler für user {user_id}: {e}")
    _thr.Thread(target=_do, daemon=True).start()


def _send_approval_request_mail(absence_id: int, requester: dict, type_name: str, date_from: str, date_to: str, approver_id: int) -> None:
    """Send approval request email to approver in a background thread."""
    import threading as _thr
    def _do():
        try:
            with app.app_context():
                db = connect()
                apr = db.execute("SELECT email, language, display_name, username FROM users WHERE id=?", (approver_id,)).fetchone()
                db.close()
                if not apr or not apr["email"]:
                    app.logger.warning(f"Approval-Mail: Genehmiger {approver_id} hat keine E-Mail")
                    return
                lang = (apr["language"] or "de")
                requester_name = requester.get("display_name") or requester.get("username", "?")
                base_url = _get_base_url()
                url = f"{base_url}/admin"
                body = t("mail.approval_request_body", lang).format(
                    name=requester_name,
                    type=type_name,
                    from_date=date_from,
                    to_date=date_to,
                    url=url,
                )
                _send_mail_simple(apr["email"], t("mail.approval_request_subject", lang), body)
                app.logger.info(f"Approval-Mail gesendet an {apr['email']} für Abwesenheit {absence_id}")
                # Telegram notification to approver
                base_url = _get_base_url()
                tg_text = (
                    f"📋 {requester_name} beantragt {type_name} "
                    f"{date_from} – {date_to}.\n"
                    f"Zur Genehmigung: {base_url}/approvals"
                )
                _send_tg_message(approver_id, tg_text)
        except Exception as e:
            app.logger.error(f"Approval-Mail Fehler: {e}")
    _thr.Thread(target=_do, daemon=True).start()


def _build_rich_day_export(user_id: int, date_from: str, date_to: str):
    """Build day-by-day export matching balance view: Wochentag|Datum|Beginn|Ende|Pause|Soll|Delta|Bemerkung."""
    _WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    db = connect()
    blocks_raw = db.execute(
        "SELECT day, time_in, time_out, break_minutes FROM time_blocks "
        "WHERE user_id=? AND day BETWEEN ? AND ? ORDER BY day, time_in",
        (user_id, date_from, date_to),
    ).fetchall()
    absences_raw = db.execute(
        "SELECT a.date_from, a.date_to, t.name AS type_name, a.comment "
        "FROM absences a JOIN absence_types t ON t.id=a.type_id "
        "WHERE a.user_id=? AND NOT (a.date_to < ? OR a.date_from > ?)",
        (user_id, date_from, date_to),
    ).fetchall()
    _export_region = _get_user_holiday_region(user_id)
    holidays_raw = db.execute(
        "SELECT day, holiday_name FROM calendar_days WHERE is_holiday=1 AND region=? AND day BETWEEN ? AND ?",
        (_export_region, date_from, date_to),
    ).fetchall()
    trips_raw = db.execute(
        "SELECT start_date, end_date, destination FROM business_trips "
        "WHERE user_id=? AND start_date <= ? AND (end_date >= ? OR end_date IS NULL)",
        (user_id, date_to, date_from),
    ).fetchall()
    db.close()

    # Build lookup maps
    blocks_by_day: dict = {}
    for b in blocks_raw:
        blocks_by_day.setdefault(b["day"], []).append(dict(b))

    absence_map: dict = {}
    for a in absences_raw:
        d0 = datetime.date.fromisoformat(a["date_from"])
        d1 = datetime.date.fromisoformat(a["date_to"])
        cur = d0
        while cur <= d1:
            iso = cur.isoformat()
            if date_from <= iso <= date_to:
                absence_map.setdefault(iso, (a["type_name"], a["comment"] or ""))
            cur += datetime.timedelta(days=1)

    holiday_map: dict = {str(h["day"])[:10]: h["holiday_name"] or "" for h in holidays_raw}

    trip_map: dict = {}
    for t in trips_raw:
        sd = t["start_date"][:10]
        ed = (t["end_date"] or sd)[:10]
        cur = datetime.date.fromisoformat(max(sd, date_from))
        end = datetime.date.fromisoformat(min(ed, date_to))
        while cur <= end:
            trip_map[cur.isoformat()] = t["destination"]
            cur += datetime.timedelta(days=1)

    headers = ["Wochentag", "Datum", "Beginn", "Ende", "Pause (min)", "Soll", "Delta", "Bemerkung"]
    data = []
    total_actual = 0

    for iso in _iter_days(date_from, date_to):
        d = datetime.date.fromisoformat(iso)
        wd = _WD[d.weekday()]
        datum = f"{d.day:02d}.{d.month:02d}.{d.year}"

        expected = _expected_minutes_for_day(user_id, iso)
        soll_str = _fmt_minutes(expected) if expected else ""

        # Build Bemerkung
        parts = []
        if iso in holiday_map and holiday_map[iso]:
            parts.append(holiday_map[iso])
        if iso in absence_map:
            atype, acomment = absence_map[iso]
            parts.append(acomment if (atype == "Sonstige" and acomment) else atype)
        if iso in trip_map:
            parts.append(f"Dienstreise: {trip_map[iso]}")
        bemerkung = " | ".join(parts)

        day_blocks = blocks_by_day.get(iso, [])

        if not day_blocks:
            if expected or bemerkung:
                delta_str = _fmt_minutes_signed(-expected) if expected else ""
                data.append([wd, datum, "", "", "", soll_str, delta_str, bemerkung])
        else:
            actual_total = sum(
                _minutes_from_hhmm(b["time_out"]) - _minutes_from_hhmm(b["time_in"]) - int(b["break_minutes"] or 0)
                for b in day_blocks
            )
            total_actual += actual_total
            delta = actual_total - expected
            delta_str = _fmt_minutes_signed(delta)

            for i, b in enumerate(day_blocks):
                brk = int(b["break_minutes"] or 0)
                if i == 0:
                    data.append([wd, datum, b["time_in"], b["time_out"], brk,
                                 soll_str, delta_str, bemerkung])
                else:
                    data.append(["", "", b["time_in"], b["time_out"], brk, "", "", ""])

    return headers, data, total_actual


def _build_time_blocks_export(user_id: int, date_from: str, date_to: str):
    """Legacy simple export — delegates to rich export."""
    headers, data, total = _build_rich_day_export(user_id, date_from, date_to)
    return headers, data, total


# ─── Periodenabschluss-Verwaltung ────────────────────────────────────────────


def _export_date_range(user_id: int = 0):
    """Return (date_from_iso, date_to_iso) clamped to user's tracking_start_date."""
    today = datetime.date.today()
    df = request.args.get("from") or f"{today.year}-01-01"
    dt = request.args.get("to")   or f"{today.year}-12-31"
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', df):
        df = f"{today.year}-01-01"
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', dt):
        dt = f"{today.year}-12-31"
    if user_id:
        start = _get_tracking_start(user_id)
        if start:
            df = max(df, start)
    return df, dt


def _export_filename(prefix: str, date_from: str, date_to: str) -> str:
    return f"{prefix}_{date_from}_{date_to}.csv"


# -------------------------
# Admin: Benutzer
# -------------------------


@admin_bp.get("/admin/users")
@sysadmin_required
def admin_users():
    from app import bootstrap, flash_html, layout, _fmt_date_de
    bootstrap()
    u = current_user()
    db = connect()
    users = db.execute(
        "SELECT id, username, display_name, is_admin, is_active, vacation_carryover_exception, "
        "contouring_enabled, contouring_start_date, created_at FROM users ORDER BY username"
    ).fetchall()
    db.close()

    trs = ""
    for r in users:
        display = r["display_name"] or r["username"]
        sub = r["username"] if r["display_name"] else ""
        flags = []
        if r["is_admin"]:
            flags.append("Admin")
        if not r["is_active"]:
            flags.append("inaktiv")
        fl = (" <span class='small'>· " + ", ".join(flags) + "</span>") if flags else ""
        sub_html = f" <span class='small' style='color:var(--mu);'>({sub})</span>" if sub else ""
        delete_btn = ""
        if r["id"] != u["id"]:
            safe_name = display.replace("'", "\\'")
            delete_btn = (
                f'<form method="post" action="/admin/users/{r["id"]}/delete" style="display:inline;margin-left:8px;" '
                f'onsubmit="return confirm(\'Nutzer {safe_name} und alle zugehörigen Daten unwiderruflich löschen?\')">'
                f'<button class="btn danger btn-sm" type="submit">Löschen</button></form>'
            )
        impersonate_btn = ""
        if not r["is_admin"] and r["is_active"] and r["id"] != u["id"]:
            impersonate_btn = (
                f'<form method="post" action="/admin/impersonate/{r["id"]}" style="display:inline;margin-left:8px;">'
                f'<button class="btn btn-sm" type="submit" title="{t("admin.identity_btn")}">{t("admin.identity_btn")}</button></form>'
            )
        carryover_exc_badge = ""
        if r["vacation_carryover_exception"]:
            carryover_exc_badge = " <span class='small' style='color:#d97706;'>Übertrag⚡</span>"
        contouring_on = int(r["contouring_enabled"]) if r["contouring_enabled"] is not None else 1
        csd = str(r["contouring_start_date"] or "")[:10]
        if contouring_on:
            c_badge = f" <span class='small' style='color:var(--ok);'>Kontierung aktiv{(' ab ' + _fmt_date_de(csd)) if csd else ''}</span>"
        else:
            c_badge = " <span class='small' style='color:var(--mu);'>Kontierung deaktiviert</span>"
        trs += (
            f'<tr>'
            f'<td>{display}{sub_html}{fl}{carryover_exc_badge}{c_badge}</td>'
            f'<td class="small">{(r["created_at"] or "")[:10]}</td>'
            f'<td style="white-space:nowrap;">'
            f'<a href="/admin/users/{r["id"]}/edit">Bearbeiten</a>'
            f'<a href="/admin/users/{r["id"]}/vacation-carryover" style="margin-left:8px;">Urlaubsübertrag</a>'
            f'<a href="/admin/users/{r["id"]}/presets" style="margin-left:8px;">{t("settings.presets")}</a>'
            f'{impersonate_btn}{delete_btn}</td>'
            f'</tr>'
        )

    body = f'''
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Benutzer</h3>
        <a class="btn" href="/admin/users/new">+ Benutzer</a>
      </div>
      <table>
        <thead><tr><th>Name</th><th>Angelegt</th><th></th></tr></thead>
        <tbody>{trs}</tbody>
      </table>
      <p class="small">Benutzernamen sind nicht änderbar. Eigener Account kann nicht gelöscht werden.</p>
    </div>
    '''
    return render_template_string(layout(f"{t('admin.title')}: {t('admin.users_title')}", body, u, APP_VERSION))


@admin_bp.get("/admin/users/new")
@sysadmin_required
def admin_users_new():
    from app import bootstrap, flash_html, layout, FORM_ASSETS_JS, _date_input
    bootstrap()
    u = current_user()
    today_iso = datetime.date.today().isoformat()
    body = f'''
    {flash_html()}
    {FORM_ASSETS_JS}
    <div class="card">
      <h3>Benutzer anlegen</h3>
      <p class="small">Das Passwort ist temporär – der Nutzer wird beim ersten Login durch den Einrichtungs-Wizard geführt.</p>
      <form method="post" action="/admin/users/new" autocomplete="off">
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;">
          <div><label>Username</label><br><input name="username" required autocomplete="off"></div>
          <div><label>Temporäres Passwort</label><br><input type="password" name="password" required autocomplete="new-password"></div>
          <div><label>{t('admin.email')}</label><br><input type="email" name="user_email" placeholder="name@firma.de"></div>
        </div>
        <div style="margin-bottom:10px;">
          <label>Erfassung ab <span class="small">(leer = ab Jahresbeginn)</span></label><br>
          {_date_input("tracking_start_date", today_iso)}
        </div>
        <label><input type="checkbox" name="is_admin" value="1"> Admin</label><br>
        <label><input type="checkbox" name="is_active" value="1" checked> aktiv</label><br><br>
        <button class="btn primary" type="submit">Anlegen</button>
        <a class="btn" href="/admin/users">Abbrechen</a>
      </form>
    </div>
    '''
    return render_template_string(layout(f"{t('admin.title')}: {t('admin.new_user')}", body, u, APP_VERSION))


@admin_bp.post("/admin/users/new")
@sysadmin_required
def admin_users_new_post():
    from app import bootstrap, add_flash, _date_input, _parse_date_input, _generate_password, _send_mail_simple
    bootstrap()
    u = current_user()
    username = (request.form.get("username") or "").strip()
    new_role = (request.form.get("admin_role") or "").strip()
    if new_role not in ("", "timemanager", "sysadmin", "hr"):
        new_role = ""
    is_admin = new_role in ("timemanager", "sysadmin", "hr")
    is_active = (request.form.get("is_active") or "0") == "1"
    admin_only_val = 1 if (request.form.get("admin_only") or "0") == "1" and is_admin else 0
    tracking_start_date = _parse_date_input(request.form.get("tracking_start_date") or "")
    send_pw_email = (request.form.get("send_pw_email") or "0") == "1"

    if send_pw_email:
        password = _generate_password()
    else:
        password = (request.form.get("password") or "").strip()

    if not username or not password:
        add_flash(t("flash.error.credentials_required"), "error")
        return redirect(url_for("admin.admin_users_new"))

    try:
        new_id = create_user(
            username,
            password,
            is_admin=is_admin,
            is_active=is_active,
            tracking_start_date=tracking_start_date,
            onboarding_done=0,
        )
    except Exception:
        add_flash(t("flash.error.user_create_failed"), "error")
        return redirect(url_for("admin.admin_users_new"))

    # Set role, admin_only, must_change_password, email
    user_email = (request.form.get("user_email") or "").strip()
    db = connect()
    db.execute(
        "UPDATE users SET admin_role=?, admin_only=?, must_change_password=1, email=?, updated_at=datetime('now') WHERE id=?",
        (new_role or None, admin_only_val, user_email or None, new_id),
    )
    db.commit()
    db.close()

    if send_pw_email:
        _edb = connect()
        _erow = _edb.execute("SELECT email FROM users WHERE id=?", (new_id,)).fetchone()
        _edb.close()
        email = (_erow["email"] or "").strip() if _erow else ""
        if email:
            try:
                _send_mail_simple(
                    email,
                    "Zeiterfassung: Dein Zugangsdaten",
                    f"Hallo {username},\n\nDein Konto wurde angelegt.\n\n"
                    f"Benutzername: {username}\nTemporäres Passwort: {password}\n\n"
                    f"Bitte ändere das Passwort nach dem ersten Login.\n\nDein Zeiterfassung-Team",
                )
                add_flash(t("flash.success.user_created_mail").format(email=_html.escape(email)), "success")
            except Exception:
                add_flash(t("flash.success.user_created_mail_failed").format(password=_html.escape(password)), "success")
        else:
            add_flash(t("flash.success.user_created_noemail").format(password=_html.escape(password)), "success")
    else:
        add_flash(t("flash.success.user_created"), "success")
    return redirect("/admin#acc-user")


@admin_bp.get("/admin/users/<int:user_id>/edit")
@admin_required
def admin_users_edit(user_id: int):
    from app import bootstrap, flash_html, layout, FORM_ASSETS_JS, _date_input, _fmt_date_de, _fmt_minutes, _region_picker, _sched_form_html, _normalize_schedule, _get_user_schedules_all, _get_user_schedule_for_day, _vacation_calc, _STANDARD_TYPE_NAMES
    bootstrap()
    u = current_user()
    db = connect()
    r = db.execute("SELECT id, username, is_admin, is_active, tracking_start_date, admin_role, holiday_region, admin_only, enabled_absence_types, is_approver, approval_required_types, approver_id, team_restriction, end_date, balance_rollover, is_apprentice FROM users WHERE id=?", (user_id,)).fetchone()
    _all_approvers = db.execute("SELECT id, username, display_name FROM users WHERE is_approver=1 AND is_active=1 ORDER BY username").fetchall()
    _all_teams_edit = db.execute("SELECT id, name FROM teams ORDER BY name").fetchall()
    _entitlements = db.execute("SELECT * FROM user_vacation_entitlement WHERE user_id=? ORDER BY valid_from DESC", (user_id,)).fetchall()
    _voc_admin_entries = db.execute(
        "SELECT * FROM vocational_school WHERE user_id=? ORDER BY schedule_type, weekday, date_from", (user_id,)
    ).fetchall()
    db.close()
    if not r:
        abort(404)

    active_checked = "checked" if r["is_active"] else ""
    admin_only_checked = "checked" if r["admin_only"] else ""
    tsd_val = str(r["tracking_start_date"] or "")[:10]
    cur_holiday_region = r["holiday_region"] or ""
    _can_edit_role = is_sysadmin(u) and user_id != u["id"]

    # Load absence type settings for this user
    _eat_str = r["enabled_absence_types"] or ""
    _eat_ids = {int(x) for x in _eat_str.split(",") if x.strip().isdigit()} if _eat_str else None
    _db2 = connect()
    _all_abs_types = _db2.execute("SELECT id, name FROM absence_types WHERE active=1 ORDER BY name").fetchall()
    _db2.close()
    _type_by_name: dict[str, int] = {t["name"]: t["id"] for t in _all_abs_types}

    def _eat_checked(type_name: str) -> str:
        tid = _type_by_name.get(type_name)
        if not tid:
            return ""
        if _eat_ids is None:
            return "checked" if type_name in _STANDARD_TYPE_NAMES else ""
        return "checked" if tid in _eat_ids else ""

    _flextag_id = _type_by_name.get("Flextag")
    _verdi_id = _type_by_name.get("Verdi")
    _sonstige_id_eat = _type_by_name.get("Sonstige")
    _verdi_row = f"""<label style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">
      <input type="checkbox" name="at_verdi" value="1" {_eat_checked("Verdi")}{"" if _verdi_id else " disabled"}>
      <span>Verdi</span>
    </label>""" if _verdi_id else ""

    _absence_types_html = f"""
        <div style="margin-bottom:14px;">
          <label style="font-size:12px;font-weight:600;">Abwesenheitstypen</label>
          <div class="small" style="color:var(--mu);margin-bottom:6px;">Urlaub und Krank sind immer aktiv.</div>
          <div style="display:flex;flex-direction:column;gap:4px;">
            <label style="display:flex;align-items:center;gap:6px;">
              <input type="checkbox" checked disabled> Urlaub
            </label>
            <label style="display:flex;align-items:center;gap:6px;">
              <input type="checkbox" checked disabled> Krank
            </label>
            <label style="display:flex;align-items:center;gap:6px;margin-bottom:2px;">
              <input type="checkbox" name="at_flextag" value="1" {_eat_checked("Flextag")}{"" if _flextag_id else " disabled"}>
              <span>Flextag</span>
            </label>
            {_verdi_row}
            <label style="display:flex;align-items:center;gap:6px;">
              <input type="checkbox" name="at_sonstige" value="1" {_eat_checked("Sonstige")}{"" if _sonstige_id_eat else " disabled"}>
              <span>Sonstige</span>
            </label>
          </div>
        </div>"""

    # role options for sysadmin dropdown
    def _role_opt(val, label, cur):
        sel = "selected" if cur == val else ""
        return f'<option value="{val}" {sel}>{label}</option>'
    cur_role = r["admin_role"] or ""
    _cur_team_restriction = r["team_restriction"] or ""
    _cur_tr_ids = {int(x) for x in _cur_team_restriction.split(",") if x.strip().isdigit()}
    _team_restriction_checks = "".join(
        f'<label style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
        f'<input type="checkbox" name="tr_{_te["id"]}" value="1" {"checked" if _te["id"] in _cur_tr_ids else ""}>'
        f'<span>{_html.escape(_te["name"])}</span></label>'
        for _te in _all_teams_edit
    )
    _team_restriction_hidden = "".join(
        f'<input type="hidden" name="_tr_team_{_te["id"]}" value="{_te["id"]}">'
        for _te in _all_teams_edit
    )
    role_dropdown = f"""
        <div style="margin-bottom:12px;">
          <label>Rolle</label>
          <select name="admin_role" style="font-size:13px;padding:5px 8px;width:auto;">
            {_role_opt("","Keine Adminrechte",cur_role)}
            {_role_opt("timemanager","📋 Zeitmanager",cur_role)}
            {_role_opt("hr","👤 HR",cur_role)}
            {_role_opt("sysadmin","🔧 Systemadmin",cur_role)}
          </select>
        </div>
        <div style="margin-bottom:12px;">
          <label style="font-size:12px;font-weight:600;">{t('admin.team_restriction')}</label>
          <div class="small" style="color:var(--mu);margin-bottom:6px;">{t('admin.team_restriction_auto')}</div>
          <div style="display:flex;flex-direction:column;gap:4px;">
            {_team_restriction_checks if _team_restriction_checks else '<span class="small" style="color:var(--mu);">Keine Teams vorhanden</span>'}
          </div>
          <input type="hidden" name="_tr_submitted" value="1">
        </div>""" if _can_edit_role else ""
    admin_only_field = f"""
        <div style="margin-bottom:12px;">
          <label style="font-weight:400;"><input type="checkbox" name="admin_only" value="1" {admin_only_checked}>
          Nur Admin (kein eigenes Zeitkonto)</label>
          <div class="small" style="color:var(--mu);margin-top:2px;">Aktivieren für Admins ohne eigene Zeiterfassung.</div>
        </div>""" if _can_edit_role else ""

    # Approver settings
    _cur_is_approver = bool(r["is_approver"])
    _cur_approver_id = r["approver_id"]
    _cur_art_str = r["approval_required_types"] or ""
    _cur_art_ids = {int(x) for x in _cur_art_str.split(",") if x.strip().isdigit()} if _cur_art_str else set()

    def _art_checked(tid) -> str:
        return "checked" if tid and tid in _cur_art_ids else ""

    _approver_opts = '<option value="">' + t("admin.approval_none") + '</option>'
    for _apr in _all_approvers:
        _apr_sel = "selected" if _cur_approver_id and _cur_approver_id == _apr["id"] else ""
        _apr_lbl = _html.escape(_apr["display_name"] or _apr["username"])
        _approver_opts += f'<option value="{_apr["id"]}" {_apr_sel}>{_apr_lbl}</option>'

    _approval_type_checks = ""
    for _abt in _all_abs_types:
        _approval_type_checks += (
            f'<label style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
            f'<input type="checkbox" name="art_{_abt["id"]}" value="1" {_art_checked(_abt["id"])}>'
            f'<span>{_html.escape(_abt["name"])}</span></label>'
        )

    _approver_section = f"""
        <div style="margin-bottom:14px;border-top:1px solid var(--bd);padding-top:12px;margin-top:4px;">
          <div style="font-size:12px;font-weight:600;margin-bottom:8px;">{t('admin.is_approver')} / {t('admin.approval_types')}</div>
          <label style="display:flex;align-items:center;gap:6px;margin-bottom:8px;font-weight:400;">
            <input type="checkbox" name="is_approver" value="1" {"checked" if _cur_is_approver else ""}>
            <span>{t('admin.is_approver')}</span>
          </label>
          <div style="margin-bottom:8px;">
            <label style="font-size:12px;">{t('admin.approver')}</label>
            <select name="approver_id" style="font-size:13px;padding:4px 8px;margin-top:4px;display:block;">
              {_approver_opts}
            </select>
          </div>
          <div>
            <div style="font-size:12px;margin-bottom:4px;">{t('admin.approval_types')}:</div>
            {_approval_type_checks}
          </div>
        </div>"""

    # Schedule list for this user
    all_scheds = _get_user_schedules_all(user_id)
    today_iso = datetime.date.today().isoformat()
    cur_year = datetime.date.today().year
    cur_sched = _get_user_schedule_for_day(user_id, today_iso)
    cur_id = (cur_sched or {}).get("id")

    # Extra user data: overtime limits + carryover + new fields
    _ex_db = connect()
    _ex_row = _ex_db.execute(
        "SELECT overtime_limit_plus, overtime_limit_minus, "
        "vacation_carryover_exception, end_date, balance_rollover FROM users WHERE id=?", (user_id,)
    ).fetchone()
    # Active schedule for inline edit
    _act_sched = _ex_db.execute(
        "SELECT * FROM user_schedules WHERE user_id=? AND valid_from<=? "
        "ORDER BY valid_from DESC LIMIT 1", (user_id, today_iso)
    ).fetchone()
    _ex_db.close()
    _ot_plus      = str(_ex_row["overtime_limit_plus"]  or "") if _ex_row else ""
    _ot_minus     = str(_ex_row["overtime_limit_minus"] or "") if _ex_row else ""
    _co_exc       = str(_ex_row["vacation_carryover_exception"] or "") if _ex_row else ""
    _end_date_val = str(_ex_row["end_date"] or "") if _ex_row else ""
    _rollover_val = str(_ex_row["balance_rollover"] or "manual") if _ex_row else "manual"
    _act_sched_id  = _act_sched["id"]  if _act_sched else None
    _act_sched_vf  = _act_sched["valid_from"] if _act_sched else today_iso
    _act_allow_self = int(_act_sched["allow_self_edit"] or 1) if _act_sched else 1

    # Vacation summary
    _vc = _vacation_calc(user_id, cur_year)
    _vac_html = (
        f"<div style='display:flex;gap:20px;flex-wrap:wrap;font-size:13px;margin-bottom:10px;'>"
        f"<span><b>{t('settings.vac_entitlement')}:</b> {_vc['entitlement']} Tage</span>"
        f"<span><b>{t('settings.vac_used')}:</b> {_vc['used_total']} Tage</span>"
        f"<span><b>{t('settings.vac_remaining')}:</b> {_vc['remaining_total']} Tage</span>"
        f"</div>"
    )

    # Balance adjustments (last 5)
    _ba_db = connect()
    _ba_rows = _ba_db.execute(
        "SELECT ba.*, u2.username as by_name FROM balance_adjustments ba "
        "LEFT JOIN users u2 ON u2.id=ba.created_by "
        "WHERE ba.user_id=? ORDER BY ba.adjustment_date DESC LIMIT 5",
        (user_id,)
    ).fetchall()
    _ba_db.close()
    _ba_trs = "".join(
        f"<tr><td style='font-size:12px;white-space:nowrap;'>{_fmt_date_de(b['adjustment_date'])}</td>"
        f"<td style='font-size:13px;'>{_fmt_minutes(b['minutes'])}</td>"
        f"<td style='font-size:12px;color:var(--mu);'>{_html.escape(b['reason'] or '')}</td></tr>"
        for b in _ba_rows
    ) or f"<tr><td colspan='3' style='color:var(--mu);font-size:13px;'>–</td></tr>"
    sched_rows = ""
    for s in all_scheds:
        sid = s.get("id")
        vf = s.get("valid_from") or ""
        mode = (s.get("mode") or "weekly").lower()
        if mode == "daily":
            dp = []
            for dk, lbl in [("mon_minutes","Mo"),("tue_minutes","Di"),("wed_minutes","Mi"),
                             ("thu_minutes","Do"),("fri_minutes","Fr"),("sat_minutes","Sa"),("sun_minutes","So")]:
                v = int(s.get(dk) or 0)
                if v:
                    dp.append(f"{lbl}:{_fmt_minutes(v)}")
            soll = " ".join(dp) if dp else "–"
        else:
            wm = int(s.get("weekly_minutes") or 0)
            soll = f"{wm/60:g} h/Woche" if wm else "–"
        try:
            if sid and cur_id and int(sid) == int(cur_id):
                badge = "<span class='badge' style='background:#0a7;color:#fff;'>Aktuell</span>"
            elif vf and vf > today_iso:
                badge = "<span class='badge' style='background:#888;color:#fff;'>Zukünftig</span>"
            else:
                badge = "<span class='badge' style='background:#ddd;'>Historie</span>"
        except Exception:
            badge = ""
        del_form = (f"<form method='post' action='/admin/schedule/{user_id}/delete/{sid}' style='display:inline;'"
                    f" onsubmit=\"return confirm('Zeitschema ab {_fmt_date_de(vf)} löschen?');\">"
                    f"<button class='btn danger' style='padding:3px 8px;font-size:12px;'>Löschen</button></form>") if sid else ""
        edit_link = f"<a href='/admin/schedule/{user_id}/edit/{sid}' style='font-size:12px;'>Bearb.</a>" if sid else ""
        sched_rows += (
            f"<tr><td style='white-space:nowrap;'><b>{_fmt_date_de(vf) if vf else '–'}</b></td>"
            f"<td>{badge}</td><td class='small'>{soll}</td>"
            f"<td style='white-space:nowrap;'>{edit_link} {del_form}</td></tr>"
        )
    if not sched_rows:
        sched_rows = "<tr><td colspan='4' class='small' style='color:#666;'>Noch kein Zeitschema vorhanden.</td></tr>"

    # Entitlement table rows
    _ent_rows = "".join(
        f"<tr>"
        f"<td style='font-size:13px;'>{e['days']} {t('common.days')}</td>"
        f"<td style='font-size:13px;'>{_fmt_date_de(e['valid_from'])}</td>"
        f"<td style='font-size:13px;color:var(--mu);'>{_html.escape(e['note'] or '')}</td>"
        f"<td>"
        f"<form method='post' action='/admin/users/{user_id}/edit' style='display:inline;'>"
        f"<input type='hidden' name='_section' value='del_entitlement'>"
        f"<input type='hidden' name='entitlement_id' value='{e['id']}'>"
        f"<button class='btn btn-sm danger' type='submit' style='padding:2px 8px;'>×</button>"
        f"</form>"
        f"</td>"
        f"</tr>"
        for e in _entitlements
    ) or f"<tr><td colspan='4' style='color:var(--mu);font-size:13px;'>–</td></tr>"

    # Rollover select
    def _ro(val, label):
        sel = "selected" if _rollover_val == val else ""
        return f'<option value="{val}" {sel}>{label}</option>'
    _rollover_select = f"""
        <select name="balance_rollover" style="display:block;margin-top:4px;font-size:13px;padding:5px 8px;">
          {_ro('manual', t('admin.rollover_manual'))}
          {_ro('keep', t('admin.rollover_keep'))}
          {_ro('forfeit', t('admin.rollover_forfeit'))}
        </select>"""

    def _section(icon, title_key, content):
        return (
            f'<div style="border:1px solid var(--bd);border-radius:8px;margin-bottom:16px;overflow:hidden;">'
            f'<div style="background:var(--sf);padding:10px 14px;font-weight:700;font-size:14px;'
            f'border-bottom:1px solid var(--bd);">{icon} {t(title_key)}</div>'
            f'<div style="padding:14px;">{content}</div>'
            f'</div>'
        )

    body = f'''
    {flash_html()}
    {FORM_ASSETS_JS}
    <div style="margin-bottom:12px;">
      <a href="/admin" class="btn btn-sm">← {t('nav.admin')}</a>
      <span style="font-weight:700;font-size:16px;margin-left:10px;">👤 {_html.escape(r["username"])}</span>
    </div>

    <!-- BEREICH 1+4+2-limits+5: Haupt-Formular -->
    <form method="post" action="/admin/users/{user_id}/edit" id="main-edit-form">

      {_section("📋", "admin.section_basedata", f"""
        <label style='display:flex;align-items:center;gap:6px;margin-bottom:10px;'>
          <input type='checkbox' name='is_active' value='1' {active_checked}> {t('admin.active')}
        </label>
        <div style='display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px;'>
          <div>
            <label style='font-size:12px;color:var(--mu);'>{t('admin.tracking_start_col')}</label>
            {_date_input("tracking_start_date", tsd_val)}
            <div class='small' style='color:var(--mu);margin-top:2px;'>Kein Eintrag vor diesem Datum möglich.</div>
          </div>
          <div>
            <label style='font-size:12px;color:var(--mu);'>{t('admin.end_date')}</label>
            <input type='date' name='end_date' value='{_end_date_val}'
                   style='display:block;margin-top:4px;'>
            <div class='small' style='color:var(--mu);margin-top:2px;'>{t('admin.end_date_hint')}</div>
          </div>
        </div>
        <div style='margin-bottom:10px;'>
          <label style='font-size:12px;color:var(--mu);'>{t('admin.new_password_optional')}</label>
          <input type='password' name='new_password'
                 placeholder='{t('admin.pw_empty_hint')}'
                 style='display:block;margin-top:4px;'>
        </div>
      """)}

      {_section("📅", "admin.section_absences", f"""
        <div style='margin-bottom:12px;'>
          <label style='font-size:12px;color:var(--mu);'>Region <span style='font-weight:400;'>(leer = Standard)</span></label>
          <div style='margin-top:4px;'>{_region_picker("holiday_region", cur_holiday_region, include_default=True)}</div>
        </div>
        {_absence_types_html}
      """)}

      {_section("🕐", "admin.section_worktime", f"""
        <div style='display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;'>
          <div>
            <label style='font-size:12px;color:var(--mu);'>{t('admin.overtime_limit_plus')}</label>
            <input type='number' name='overtime_limit_plus' value='{_ot_plus}'
                   placeholder='{t('admin.no_limit')}'
                   style='display:block;margin-top:4px;width:110px;'>
          </div>
          <div>
            <label style='font-size:12px;color:var(--mu);'>{t('admin.overtime_limit_minus')}</label>
            <input type='number' name='overtime_limit_minus' value='{_ot_minus}'
                   placeholder='{t('admin.no_limit')}'
                   style='display:block;margin-top:4px;width:110px;'>
          </div>
          <div>
            <label style='font-size:12px;color:var(--mu);'>{t('admin.balance_rollover')}</label>
            {_rollover_select}
            <div class='small' style='color:var(--mu);margin-top:2px;'>{t('admin.balance_rollover_hint')}</div>
          </div>
        </div>
        <label style='display:flex;align-items:center;gap:6px;font-size:13px;'>
          <input type='checkbox' name='is_apprentice' value='1' {'checked' if r['is_apprentice'] else ''}>
          🎓 Auszubildende/r (Berufsschule sichtbar)
        </label>
      """)}

      {"" if not (_can_edit_role or is_timemanager(u)) else _section("⚙", "admin.section_admin", f"""
        {role_dropdown}
        {admin_only_field}
        {_approver_section}
      """)}

      <div style='display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;'>
        <button class='btn primary' type='submit'>{t('btn.save')}</button>
        <a class='btn' href='/admin'>{t('btn.back')}</a>
        <form method='post' action='/admin/users/{user_id}/reset-password' style='display:inline;'>
          <button class='btn btn-sm' type='submit'>🔑 {t('admin.pw_reset_btn')}</button>
        </form>
      </div>
    </form>

    <!-- Berufsschule -->
    <div class="card" id="vocational">
      <h3 style="margin-top:0;">🎓 Berufsschule</h3>
      {"".join(
        f"<div style='font-size:13px;padding:6px 10px;background:var(--sf);border:1px solid var(--bd);"
        f"border-radius:6px;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;'>"
        f"<span>{'Wöchentlich: ' + ['Mo','Di','Mi','Do','Fr','Sa','So'][int(e['weekday'])] if e['schedule_type']=='weekly' else 'Block: '+str(e['date_from'])+'–'+str(e['date_to'])}"
        f"{(' | Halbtag Arbeit: '+str(e['work_time_from'])[:5]+'–'+str(e['work_time_to'])[:5]) if e['work_time_from'] else ''}"
        f"{(' | '+e['note']) if e['note'] else ''}</span>"
        f"<form method='post' action='/admin/users/{user_id}/vocational/delete' style='display:inline;' onsubmit=\"return confirm('{t('confirm.delete_vocational')}');\">"
        f"<input type='hidden' name='entry_id' value='{e['id']}'>"
        f"<button class='btn btn-sm danger' type='submit' style='padding:2px 8px;'>×</button></form></div>"
        for e in _voc_admin_entries
      ) or f"<p style='color:var(--mu);font-size:13px;'>Noch keine Einträge.</p>"}
      <!-- Wöchentlich hinzufügen -->
      <details style="margin-top:10px;">
        <summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--ac);">+ Wöchentlichen Tag hinzufügen</summary>
        <form method="post" action="/admin/users/{user_id}/vocational/add" style="margin-top:10px;padding:10px;background:var(--sf);border:1px solid var(--bd);border-radius:8px;">
          <input type="hidden" name="schedule_type" value="weekly">
          <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
            <div>
              <label style="font-size:12px;color:var(--mu);">Wochentag</label>
              <select name="weekday" style="display:block;margin-top:4px;font-size:13px;">
                {"".join(f'<option value="{i}">{["Mo","Di","Mi","Do","Fr","Sa","So"][i]}</option>' for i in range(7))}
              </select>
            </div>
            <div>
              <label style="font-size:12px;color:var(--mu);">Typ</label>
              <select name="voc_type" style="display:block;margin-top:4px;font-size:13px;"
                      onchange="this.closest('form').querySelector('#voc-adm-half').style.display=this.value==='half'?'flex':'none'">
                <option value="full">Ganztag</option><option value="half">Halbtag</option>
              </select>
            </div>
            <div id="voc-adm-half" style="display:none;gap:8px;flex-wrap:wrap;">
              <div>
                <label style="font-size:12px;color:var(--mu);">Arbeit von – bis</label>
                <div style="display:flex;gap:4px;margin-top:4px;">
                  <input type="time" name="work_time_from" step="900" style="width:96px;">
                  <input type="time" name="work_time_to" step="900" style="width:96px;">
                </div>
              </div>
            </div>
            <div><label style="font-size:12px;color:var(--mu);">Gültig ab</label>{_date_input("valid_from", "")}</div>
            <div><label style="font-size:12px;color:var(--mu);">Gültig bis</label>{_date_input("valid_to", "")}</div>
            <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
          </div>
        </form>
      </details>
      <!-- Blockunterricht hinzufügen -->
      <details style="margin-top:6px;">
        <summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--ac);">+ Blockunterricht hinzufügen</summary>
        <form method="post" action="/admin/users/{user_id}/vocational/add" style="margin-top:10px;padding:10px;background:var(--sf);border:1px solid var(--bd);border-radius:8px;">
          <input type="hidden" name="schedule_type" value="block">
          <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
            <div><label style="font-size:12px;color:var(--mu);">Von</label>{_date_input("date_from", "")}</div>
            <div><label style="font-size:12px;color:var(--mu);">Bis</label>{_date_input("date_to", "")}</div>
            <div style="flex:1;min-width:120px;">
              <label style="font-size:12px;color:var(--mu);">Notiz</label>
              <input type="text" name="note" maxlength="80" placeholder="z.B. Block 1"
                     style="display:block;margin-top:4px;width:100%;">
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
          </div>
        </form>
      </details>
    </div>

    <!-- BEREICH 2: Zeitschema -->
    <div class="card" id="schedule">
      <h3 style="margin-top:0;">🕐 {t('admin.acc_schedules')}</h3>
      <form method="post" action="/admin/users/{user_id}/edit" style="margin-bottom:10px;">
        <input type="hidden" name="_section" value="allow_self_edit">
        <label style="font-size:13px;display:flex;align-items:center;gap:6px;cursor:pointer;">
          <input type="checkbox" name="allow_self_edit" value="1"
                 {"checked" if _act_allow_self else ""}
                 onchange="this.form.submit()">
          {t('admin.schedule_allow_self_edit')}
        </label>
      </form>
      {_sched_form_html(
          dict(_act_sched) if _act_sched else _normalize_schedule({}),
          f"/admin/schedule/{user_id}/edit/{_act_sched_id or 'new'}",
          f"/admin/users/{user_id}/edit#schedule"
      )}
      <a class="btn btn-sm" href="/admin/schedule/{user_id}/edit/new"
         style="margin-top:6px;display:inline-block;">
        + {t('settings.sched_add_new')}
      </a>
      <hr style="margin:12px 0;">
      <h4 style="margin:0 0 8px;font-size:13px;">{t('settings.badge_history')}</h4>
      <table style="width:100%;">
        <thead><tr><th>{t('settings.schedule_valid')}</th><th>{t('common.status')}</th><th>Soll</th><th></th></tr></thead>
        <tbody>{sched_rows}</tbody>
      </table>
    </div>

    <!-- BEREICH 3: Urlaub -->
    <div class="card" id="vacation">
      <h3 style="margin-top:0;">🏖 {t('admin.section_vacation')} {cur_year}</h3>
      {_vac_html}

      <!-- Urlaubsanspruch -->
      <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--bd);">
        <h4 style="margin:0 0 8px;">{t('admin.vacation_entitlement')}</h4>
        <div class="table-scroll" style="margin-bottom:10px;">
          <table style="width:100%;font-size:13px;">
            <thead><tr>
              <th>{t('admin.entitlement_days')}</th>
              <th>{t('admin.entitlement_valid_from')}</th>
              <th>{t('admin.entitlement_note')}</th>
              <th></th>
            </tr></thead>
            <tbody>{_ent_rows}</tbody>
          </table>
        </div>
        <form method="post" action="/admin/users/{user_id}/edit">
          <input type="hidden" name="_section" value="add_entitlement">
          <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;">
            <div>
              <label style="font-size:12px;color:var(--mu);">{t('admin.entitlement_days')}</label>
              <input type="number" name="entitlement_days" min="0" max="365" step="0.5"
                     placeholder="30"
                     style="display:block;margin-top:4px;width:80px;">
            </div>
            <div>
              <label style="font-size:12px;color:var(--mu);">{t('admin.entitlement_valid_from')}</label>
              <input type="date" name="entitlement_valid_from"
                     value="{datetime.date.today().isoformat()}"
                     style="display:block;margin-top:4px;">
            </div>
            <div style="flex:1;min-width:120px;">
              <label style="font-size:12px;color:var(--mu);">{t('admin.entitlement_note')}</label>
              <input type="text" name="entitlement_note" maxlength="100"
                     placeholder="{t('admin.entitlement_note_hint')}"
                     style="display:block;margin-top:4px;width:100%;">
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
          </div>
        </form>
      </div>

      <!-- Urlaubsübertrag -->
      <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--bd);">
        <h4 style="margin:0 0 8px;">{t('admin.vacation_carryover')}</h4>
        <form method="post" action="/admin/users/{user_id}/edit">
          <input type="hidden" name="_section" value="carryover">
          <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;">
            <div>
              <label style="font-size:12px;color:var(--mu);">{t('admin.carryover_days')}</label>
              <input type="number" name="vacation_carryover_exception"
                     value="{_co_exc}"
                     placeholder="{t('admin.system_default')}"
                     style="display:block;margin-top:4px;width:100px;" step="0.5" min="0">
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
            <a class="btn btn-sm" href="/admin/users/{user_id}/vacation-carryover">{t('admin.carryover_manage_btn')}</a>
          </div>
        </form>
      </div>
    </div>

    <!-- Gleitzeitkonto Korrekturen -->
    <div class="card" id="balance">
      <h3 style="margin-top:0;">⚖ {t('balance.title')}</h3>
      <table style="width:100%;">
        <thead><tr>
          <th style="font-size:12px;">{t('balance.date')}</th>
          <th style="font-size:12px;">Minuten</th>
          <th style="font-size:12px;">{t('balance.adjustment_reason')}</th>
        </tr></thead>
        <tbody>{_ba_trs}</tbody>
      </table>
    </div>

    <!-- Standardzeiten -->
    <div class="card" id="presets">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px;">
        <h3 style="margin:0;">⏱ {t('settings.presets')}</h3>
        <a class="btn btn-sm" href="/admin/users/{user_id}/presets">{t('btn.edit')}</a>
      </div>
    </div>
    '''
    return render_template_string(layout(f"{t('admin.title')}: {t('admin.edit_user')}", body, u, APP_VERSION))


@admin_bp.post("/admin/users/<int:user_id>/edit")
@admin_required
def admin_users_edit_post(user_id: int):
    from app import bootstrap, add_flash, _date_input, _parse_date_input, _STANDARD_TYPE_NAMES
    bootstrap()
    u = current_user()

    # Early-return sections (must come before the main form processing)
    _sec = request.form.get("_section", "")

    if _sec == "add_entitlement":
        try:
            _days = float(request.form.get("entitlement_days") or 0)
            _vf   = (request.form.get("entitlement_valid_from") or "").strip()
            _note = (request.form.get("entitlement_note") or "").strip()
            if _days > 0 and _vf:
                db = connect()
                db.execute(
                    "INSERT INTO user_vacation_entitlement(user_id, days, valid_from, note) VALUES(?,?,?,?)",
                    (user_id, _days, _vf, _note)
                )
                db.commit()
                db.close()
                add_flash(t("admin.user_saved"), "success")
        except Exception:
            add_flash(t("flash.error"), "error")
        return redirect(f"/admin/users/{user_id}/edit#vacation")

    if _sec == "del_entitlement":
        try:
            _eid = int(request.form.get("entitlement_id") or 0)
            if _eid:
                db = connect()
                db.execute(
                    "DELETE FROM user_vacation_entitlement WHERE id=? AND user_id=?",
                    (_eid, user_id)
                )
                db.commit()
                db.close()
                add_flash(t("admin.user_saved"), "success")
        except Exception:
            add_flash(t("flash.error"), "error")
        return redirect(f"/admin/users/{user_id}/edit#vacation")

    is_active = (request.form.get("is_active") or "0") == "1"
    set_active(user_id, is_active)

    # Role change: only sysadmin, only for other users
    if is_sysadmin(u) and user_id != u["id"] and "admin_role" in request.form:
        new_role = (request.form.get("admin_role") or "").strip() or None
        if new_role not in (None, "sysadmin", "timemanager", "hr"):
            new_role = None
        # Guard: don't demote last sysadmin
        if new_role != "sysadmin":
            db = connect()
            sysadmin_count = db.execute(
                "SELECT COUNT(*) FROM users WHERE admin_role='sysadmin' AND is_active=1"
            ).fetchone()[0]
            target_is_sysadmin = db.execute(
                "SELECT admin_role FROM users WHERE id=?", (user_id,)
            ).fetchone()
            db.close()
            if (target_is_sysadmin and target_is_sysadmin["admin_role"] == "sysadmin"
                    and sysadmin_count <= 1):
                add_flash(t("flash.error.last_sysadmin"), "error")
                return redirect(f"/admin/users/{user_id}/edit")
        set_admin_role(user_id, new_role)

    tsd = _parse_date_input(request.form.get("tracking_start_date") or "")
    if tsd:
        db = connect()
        db.execute("UPDATE users SET tracking_start_date=?, updated_at=datetime('now') WHERE id=?", (tsd, user_id))
        db.commit()
        db.close()

    new_pw = (request.form.get("new_password") or "").strip()
    if new_pw:
        set_password(user_id, new_pw)

    new_region = (request.form.get("holiday_region") or "").strip()
    if new_region and new_region not in ALL_REGIONS:
        new_region = ""
    db = connect()
    db.execute(
        "UPDATE users SET holiday_region=?, updated_at=datetime('now') WHERE id=?",
        (new_region or None, user_id),
    )
    db.commit()
    db.close()

    # Absence types: save enabled_absence_types
    _db3 = connect()
    _abt = _db3.execute("SELECT id, name FROM absence_types WHERE active=1").fetchall()
    _db3.close()
    _tbyn = {t["name"]: t["id"] for t in _abt}
    _always = {_tbyn[n] for n in ("Urlaub", "Krank") if n in _tbyn}
    _eat_set = set(_always)
    for _at_name, _field in (("Flextag", "at_flextag"), ("Verdi", "at_verdi"), ("Sonstige", "at_sonstige")):
        if request.form.get(_field) and _tbyn.get(_at_name):
            _eat_set.add(_tbyn[_at_name])
    # Store NULL if it matches the standard set exactly, else store explicit list
    _std_ids = {_tbyn[n] for n in _STANDARD_TYPE_NAMES if n in _tbyn}
    _new_eat = None if _eat_set == _std_ids else ",".join(str(i) for i in sorted(_eat_set))
    _db4 = connect()
    _db4.execute("UPDATE users SET enabled_absence_types=?, updated_at=datetime('now') WHERE id=?",
                 (_new_eat, user_id))
    _db4.commit()
    _db4.close()

    # admin_only: sysadmin only, not self
    if is_sysadmin(u) and user_id != u["id"]:
        new_admin_only = 1 if request.form.get("admin_only") == "1" else 0
        db = connect()
        db.execute(
            "UPDATE users SET admin_only=?, updated_at=datetime('now') WHERE id=?",
            (new_admin_only, user_id),
        )
        db.commit()
        db.close()

    # Approver settings (sysadmin or timemanager)
    if is_sysadmin(u) or is_timemanager(u):
        new_is_approver = 1 if request.form.get("is_approver") == "1" else 0
        new_approver_id_raw = (request.form.get("approver_id") or "").strip()
        new_approver_id = int(new_approver_id_raw) if new_approver_id_raw.isdigit() else None

        # Collect approval_required_types from checkboxes named art_{id}
        _adb = connect()
        _abt_ids = [r["id"] for r in _adb.execute("SELECT id FROM absence_types WHERE active=1").fetchall()]
        _adb.close()
        _new_art_ids = [str(tid) for tid in _abt_ids if request.form.get(f"art_{tid}") == "1"]
        new_art = ",".join(_new_art_ids) if _new_art_ids else None

        db = connect()
        db.execute(
            "UPDATE users SET is_approver=?, approver_id=?, approval_required_types=?, updated_at=datetime('now') WHERE id=?",
            (new_is_approver, new_approver_id, new_art, user_id),
        )
        db.commit()
        db.close()

    # team_restriction: sysadmin can set for timemanager/hr users
    if is_sysadmin(u) and user_id != u["id"] and "_tr_submitted" in request.form:
        _tr_db = connect()
        _all_team_ids = [r["id"] for r in _tr_db.execute("SELECT id FROM teams").fetchall()]
        _tr_db.close()
        _tr_ids = [str(tid) for tid in _all_team_ids if request.form.get(f"tr_{tid}") == "1"]
        _tr_val = ",".join(_tr_ids) or None
        db = connect()
        db.execute(
            "UPDATE users SET team_restriction=?, updated_at=datetime('now') WHERE id=?",
            (_tr_val, user_id),
        )
        db.commit()
        db.close()

    # Overtime limits + end_date + balance_rollover + is_apprentice
    lim_plus      = request.form.get("overtime_limit_plus", "").strip() or None
    lim_minus     = request.form.get("overtime_limit_minus", "").strip() or None
    end_date_val  = request.form.get("end_date", "").strip() or None
    rollover_val  = request.form.get("balance_rollover", "manual").strip()
    if rollover_val not in ("manual", "keep", "forfeit"):
        rollover_val = "manual"
    is_apprentice_val = 1 if request.form.get("is_apprentice") == "1" else 0
    db = connect()
    db.execute(
        "UPDATE users SET overtime_limit_plus=?, overtime_limit_minus=?, "
        "end_date=?, balance_rollover=?, is_apprentice=?, updated_at=datetime('now') WHERE id=?",
        (lim_plus, lim_minus, end_date_val, rollover_val, is_apprentice_val, user_id)
    )
    db.commit()
    db.close()

    # allow_self_edit toggle for active schedule
    if request.form.get("_section") == "allow_self_edit":
        allow = 1 if request.form.get("allow_self_edit") else 0
        db = connect()
        db.execute(
            "UPDATE user_schedules SET allow_self_edit=? "
            "WHERE user_id=? AND id=("
            "SELECT id FROM user_schedules WHERE user_id=? "
            "AND valid_from<=? ORDER BY valid_from DESC LIMIT 1)",
            (allow, user_id, user_id, datetime.date.today().isoformat())
        )
        db.commit()
        db.close()
        return redirect(f"/admin/users/{user_id}/edit#schedule")

    # Vacation carryover exception (via _section=carryover)
    if request.form.get("_section") == "carryover":
        co_val = request.form.get("vacation_carryover_exception", "").strip()
        try:
            co_num = float(co_val) if co_val else None
        except ValueError:
            co_num = None
        db = connect()
        db.execute(
            "UPDATE users SET vacation_carryover_exception=?, updated_at=datetime('now') WHERE id=?",
            (co_num, user_id)
        )
        db.commit()
        db.close()
        add_flash(t("admin.user_saved"), "success")
        return redirect(f"/admin/users/{user_id}/edit#vacation")

    add_flash(t("admin.user_saved"), "success")
    return redirect(f"/admin/users/{user_id}/edit")


@admin_bp.post("/admin/users/<int:user_id>/delete")
@sysadmin_required
def admin_users_delete(user_id: int):
    from app import bootstrap, add_flash
    bootstrap()
    u = current_user()

    if user_id == u["id"]:
        add_flash(t("admin.cant_delete_own"), "error")
        return redirect(url_for("admin.admin_users"))

    db = connect()
    target = db.execute(
        "SELECT id, username, display_name, is_admin FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if not target:
        db.close()
        abort(404)

    # Prevent deleting the last admin
    if target["is_admin"]:
        admin_count = db.execute("SELECT COUNT(*) FROM users WHERE is_admin=1 AND is_active=1").fetchone()[0]
        if admin_count <= 1:
            db.close()
            add_flash(t("flash.error.last_admin"), "error")
            return redirect(url_for("admin.admin_users"))

    display = target["display_name"] or target["username"]
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    db.close()
    add_flash(t("flash.success.user_deleted").format(name=display), "success")
    return redirect(url_for("admin.admin_users"))


@admin_bp.post("/admin/users/<int:user_id>/reset-password")
@timemanager_required
def admin_users_reset_password(user_id: int):
    from app import bootstrap, add_flash, _generate_password, _send_mail_simple
    bootstrap()
    u = current_user()

    db = connect()
    target = db.execute(
        "SELECT id, username, display_name, email, admin_role, is_admin FROM users WHERE id=?", (user_id,)
    ).fetchone()
    db.close()
    if not target:
        abort(404)

    # Timemanagers may not reset sysadmin passwords
    if not is_sysadmin(u) and target["admin_role"] == "sysadmin":
        add_flash(t("flash.error.sysadmin_pw_reset"), "error")
        return redirect("/admin")

    new_pw = _generate_password()
    set_password(user_id, new_pw)
    set_must_change_password(user_id, True)

    display = target["display_name"] or target["username"]
    email = (target["email"] or "").strip()
    mail_sent = False
    if email:
        try:
            _send_mail_simple(
                email,
                "Zeiterfassung: Passwort zurückgesetzt",
                f"Hallo {display},\n\nDein Passwort wurde zurückgesetzt.\n\n"
                f"Neues Passwort: {new_pw}\n\n"
                f"Bitte ändere es nach dem Login unter Einstellungen → Passwort.\n\n"
                f"Dein Zeiterfassung-Team",
            )
            mail_sent = True
        except Exception:
            mail_sent = False

    if mail_sent:
        add_flash(t("flash.success.pw_reset_mail").format(name=display, email=_html.escape(email)), "success")
    else:
        _reason = t("flash.success.pw_reset_no_email_reason") if not email else t("flash.success.pw_reset_fail_reason")
        add_flash(t("flash.success.pw_reset_nomail").format(name=display, reason=_reason, password=_html.escape(new_pw)), "success")
    return redirect(f"/admin/users/{user_id}/edit")


@admin_bp.post("/admin/users/<int:user_id>/unlock")
@timemanager_required
def admin_users_unlock(user_id: int):
    from app import bootstrap, add_flash
    bootstrap()
    unlock_account(user_id)
    add_flash(t("auth.unlocked"), "success")
    return redirect("/admin")


@admin_bp.route("/admin/user/<int:uid>/schedule", methods=["GET", "POST"])
@timemanager_required
def admin_user_schedule(uid: int):
    from app import bootstrap, add_flash, flash_html, layout, _sched_daily_blocks_html, _normalize_schedule, _parse_sched_blocks_from_form, _sched_save_blocks, _sched_save_exceptions_from_form
    bootstrap()
    u = current_user()
    db = connect()
    target = db.execute("SELECT id, username, display_name FROM users WHERE id=?", (uid,)).fetchone()
    if not target:
        db.close()
        abort(404)
    display = target["display_name"] or target["username"]

    if request.method == "POST":
        allow_self = 1 if request.form.get("allow_self_edit") else 0
        valid_from = (request.form.get("valid_from") or "").strip() or datetime.date.today().isoformat()
        blocks = _parse_sched_blocks_from_form(request.form)
        mask = sum(1 << wd for wd in blocks.keys()) if blocks else 0
        existing = db.execute(
            "SELECT id FROM user_schedules WHERE user_id=? AND mode='daily' ORDER BY valid_from DESC LIMIT 1",
            (uid,)
        ).fetchone()
        if existing:
            sched_id = existing["id"]
            db.execute(
                "UPDATE user_schedules SET valid_from=?, workdays_mask=?, allow_self_edit=? WHERE id=?",
                (valid_from, mask, allow_self, sched_id)
            )
            db.commit()
        else:
            db.execute(
                "INSERT INTO user_schedules (user_id, valid_from, mode, workdays_mask, weekly_minutes, allow_self_edit) "
                "VALUES (?, ?, 'daily', ?, 0, ?)",
                (uid, valid_from, mask, allow_self)
            )
            db.commit()
            sched_id = db.execute(
                "SELECT id FROM user_schedules WHERE user_id=? AND mode='daily' ORDER BY id DESC LIMIT 1",
                (uid,)
            ).fetchone()["id"]
        if blocks:
            _sched_save_blocks(sched_id, blocks)
        _sched_save_exceptions_from_form(sched_id, request.form)
        db.close()
        add_flash(t("success.schedule_saved"), "success")
        return redirect(f"/admin/user/{uid}/schedule")

    # GET: lade bestehendes daily-Schema
    existing = db.execute(
        "SELECT * FROM user_schedules WHERE user_id=? AND mode='daily' ORDER BY valid_from DESC LIMIT 1",
        (uid,)
    ).fetchone()
    sched_id = existing["id"] if existing else None
    sched = _normalize_schedule(dict(existing)) if existing else _normalize_schedule({})
    allow_self = int(existing["allow_self_edit"] or 1) if existing else 1
    db.close()

    blocks_html = _sched_daily_blocks_html(sched_id, "daily")
    vf = sched.get("valid_from") or datetime.date.today().isoformat()
    body = f"""
    {flash_html()}
    <div style="max-width:700px;margin:1.5rem auto;">
      <div style="margin-bottom:1rem;">
        <a href="/admin/users/{uid}/edit" class="btn btn-sm">← {_html.escape(display)}</a>
      </div>
      <h2 style="margin-bottom:1rem;">{t('settings.sched_section')} – {_html.escape(display)}</h2>
      <form method="post" action="/admin/user/{uid}/schedule">
        <div style="margin-bottom:12px;">
          <label style="font-size:12px;color:var(--mu);">{t('settings.schedule_valid')}</label><br>
          <input type="date" name="valid_from" value="{vf}" required style="margin-top:4px;">
        </div>
        {blocks_html}
        <div style="margin-top:12px;display:flex;gap:12px;align-items:center;">
          <label style="display:flex;align-items:center;gap:6px;font-size:13px;">
            <input type="checkbox" name="allow_self_edit" value="1"{"checked" if allow_self else ""}>
            {t('admin.schedule_allow_self_edit')}
          </label>
        </div>
        <div style="margin-top:16px;display:flex;gap:8px;">
          <button class="btn primary" type="submit">{t('btn.save')}</button>
          <a class="btn" href="/admin/users/{uid}/edit">{t('btn.cancel')}</a>
        </div>
      </form>
    </div>"""
    return render_template_string(layout(t("settings.sched_section"), body, u, APP_VERSION))


@admin_bp.route("/admin/users/<int:user_id>/presets", methods=["GET", "POST"])
@timemanager_required
def admin_user_presets(user_id: int):
    from app import bootstrap, add_flash, flash_html, layout
    bootstrap()
    u = current_user()
    db = connect()
    target = db.execute(
        "SELECT id, username, display_name FROM users WHERE id=?", (user_id,)
    ).fetchone()
    if not target:
        db.close()
        abort(404)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            count = db.execute(
                "SELECT COUNT(*) as c FROM user_time_presets WHERE user_id=?", (user_id,)
            ).fetchone()["c"]
            if count < 3:
                label    = (request.form.get("label") or "").strip()[:30]
                time_in  = (request.form.get("time_in") or "").strip()
                time_out = (request.form.get("time_out") or "").strip()
                brk      = int(request.form.get("break_minutes") or 0)
                if label and time_in and time_out:
                    db.execute(
                        "INSERT INTO user_time_presets (user_id, label, time_in, time_out, break_minutes, sort_order) "
                        "VALUES (?,?,?,?,?,?)",
                        (user_id, label, time_in, time_out, brk, count)
                    )
                    db.commit()
                    add_flash(t("settings.preset_saved"), "success")
                else:
                    add_flash(t("settings.preset_max"), "warning")
        elif action == "delete":
            pid = int(request.form.get("preset_id") or 0)
            db.execute("DELETE FROM user_time_presets WHERE id=? AND user_id=?", (pid, user_id))
            db.commit()
            add_flash(t("settings.preset_deleted"), "success")
        db.close()
        return redirect(f"/admin/users/{user_id}/presets")

    presets = db.execute(
        "SELECT * FROM user_time_presets WHERE user_id=? ORDER BY sort_order", (user_id,)
    ).fetchall()
    db.close()
    display = target["display_name"] or target["username"]

    presets_rows = "".join(
        f"<tr><td style='padding:6px 10px;'>{_html.escape(p['label'])}</td>"
        f"<td style='padding:6px 10px;'>{p['time_in']}</td>"
        f"<td style='padding:6px 10px;'>{p['time_out']}</td>"
        f"<td style='padding:6px 10px;'>{p['break_minutes']}</td>"
        f"<td style='padding:6px 10px;'>"
        f"<form method='post' style='display:inline;'>"
        f"<input type='hidden' name='action' value='delete'>"
        f"<input type='hidden' name='preset_id' value='{p['id']}'>"
        f"<button class='btn btn-sm' type='submit' style='color:#dc2626;'>{t('btn.delete')}</button>"
        f"</form></td></tr>"
        for p in presets
    )
    add_form = (
        f"<p style='color:var(--mu);'>{t('settings.preset_max')}</p>"
        if len(presets) >= 3 else
        f"<form method='post' style='display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;'>"
        f"<input type='hidden' name='action' value='add'>"
        f"<div><label style='font-size:12px;'>{t('settings.preset_label')}</label><br>"
        f"<input name='label' maxlength='30' required placeholder='Früh'></div>"
        f"<div><label style='font-size:12px;'>{t('day.time_in')}</label><br>"
        f"<input type='time' name='time_in' required style='width:110px;font-size:1rem;padding:5px 8px;border-radius:6px;'></div>"
        f"<div><label style='font-size:12px;'>{t('day.time_out')}</label><br>"
        f"<input type='time' name='time_out' required style='width:110px;font-size:1rem;padding:5px 8px;border-radius:6px;'></div>"
        f"<div><label style='font-size:12px;'>{t('day.break_min')}</label><br>"
        f"<input type='number' name='break_minutes' value='0' min='0' style='width:70px;font-size:1rem;padding:5px 8px;border-radius:6px;'></div>"
        f"<button class='btn primary btn-sm' type='submit' style='align-self:flex-end;'>{t('btn.add')}</button>"
        f"</form>"
    )
    table = (
        f"<table style='width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px;'>"
        f"<thead><tr style='border-bottom:1px solid var(--br);'>"
        f"<th style='padding:4px 10px;text-align:left;'>{t('settings.preset_label')}</th>"
        f"<th style='padding:4px 10px;text-align:left;'>{t('day.time_in')}</th>"
        f"<th style='padding:4px 10px;text-align:left;'>{t('day.time_out')}</th>"
        f"<th style='padding:4px 10px;text-align:left;'>{t('day.break_min')}</th>"
        f"<th></th></tr></thead><tbody>{presets_rows}</tbody></table>"
        if presets else f"<p style='color:var(--mu);font-size:13px;margin-bottom:12px;'>{t('settings.preset_hint')}</p>"
    )
    body = f"""
    {flash_html()}
    <div style='max-width:700px;margin:1.5rem auto;'>
      <div style='margin-bottom:1rem;'>
        <a href='/admin/users/{user_id}/edit' class='btn btn-sm'>← {_html.escape(display)}</a>
      </div>
      <h2 style='margin-bottom:1rem;'>{t('settings.presets')} – {_html.escape(display)}</h2>
      {table}
      {add_form}
    </div>"""
    return render_template_string(layout(t("settings.presets"), body, u, APP_VERSION))


@admin_bp.get("/admin/users/<int:user_id>/vacation-carryover")
@admin_required
def admin_vacation_carryover(user_id: int):
    from app import bootstrap, flash_html, layout, _date_input, _vacation_calc, _get_all_vacation_carryover_overrides
    bootstrap()
    u = current_user()
    db = connect()
    target = db.execute(
        "SELECT id, username, display_name, vacation_carryover_exception FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    db.close()
    if not target:
        abort(404)

    display = target["display_name"] or target["username"]
    exception_on = int(target["vacation_carryover_exception"] or 0)
    overrides = _get_all_vacation_carryover_overrides(user_id)
    cur_year = datetime.date.today().year
    vc = _vacation_calc(user_id, cur_year)
    prefill_days = vc["carryover"]

    override_rows = ""
    for ov in overrides:
        ov_year = ov["year"]
        override_rows += (
            f"<tr>"
            f"<td>{ov_year}</td>"
            f"<td>{ov['carryover_days']:.1f}</td>"
            f"<td>{ov['valid_until'] or '–'}</td>"
            f"<td class='small'>{_html.escape(ov['comment'] or '')}</td>"
            f"<td>"
            f"<form method='post' action='/admin/users/{user_id}/vacation-carryover/delete/{ov_year}' style='display:inline;'>"
            f"<button class='btn danger' type='submit' style='padding:3px 8px;font-size:12px;'>Löschen</button></form>"
            f"</td>"
            f"</tr>"
        )
    override_table = (
        f"<table><thead><tr><th>Jahr</th><th>Tage</th><th>Gültig bis</th><th>Kommentar</th><th></th></tr></thead>"
        f"<tbody>{override_rows}</tbody></table>"
    ) if overrides else "<p class='small'>Noch keine Übertrag-Ausnahmen konfiguriert.</p>"

    checked = "checked" if exception_on else ""
    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;">
        <h3 style="margin:0;">Urlaubsübertrag-Ausnahme · {_html.escape(display)}</h3>
        <a class="btn" href="/admin/users">← Zurück</a>
      </div>

      <p class="small">
        Standardregel: Übertrag verfällt am 31.03. des Folgejahres.<br>
        Ausnahme: Übertrag bleibt unbegrenzt gültig – Betrag aus der Tabelle unten wird verwendet.
      </p>

      <h3 style="margin-top:14px;">Bestehende Ausnahmen</h3>
      {override_table}

      <hr style="margin:18px 0;">
      <h3 style="margin-top:0;">Einstellung & Eintrag speichern</h3>
      <form method="post" action="/admin/users/{user_id}/vacation-carryover">
        <div style="margin-bottom:12px;">
          <label style="display:flex;align-items:center;gap:8px;font-weight:600;cursor:pointer;">
            <input type="checkbox" name="exception" value="1" {checked} id="exc-cb"
              onchange="document.getElementById('exc-fields').style.display=this.checked?'block':'none';">
            Ausnahme gilt (kein Verfall am 31.03.)
          </label>
        </div>
        <div id="exc-fields" style="display:{'block' if exception_on else 'none'};border-left:3px solid #f59e0b;padding-left:14px;margin-bottom:14px;">
          <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:end;">
            <div>
              <label>Jahr</label><br>
              <input name="year" type="number" min="2020" max="2099" value="{cur_year}" style="width:90px;" required>
            </div>
            <div>
              <label>Übertragstage (Ausnahme)</label><br>
              <input name="carryover_days" type="number" step="0.5" min="0" value="{prefill_days}" style="width:100px;">
            </div>
            <div>
              <label>Gültig bis <span class="small">(optional)</span></label><br>
              {_date_input("valid_until", "")}
            </div>
          </div>
          <div style="margin-top:10px;">
            <label>Kommentar <span class="small">(optional)</span></label><br>
            <input name="comment" style="width:100%;max-width:400px;">
          </div>
        </div>
        <button class="btn primary" type="submit">Speichern</button>
      </form>
    </div>
    """
    return render_template_string(layout(f"{t('admin.title')}: {t('admin.carryover_tab')}", body, u, APP_VERSION))


@admin_bp.post("/admin/users/<int:user_id>/vacation-carryover")
@admin_required
def admin_vacation_carryover_post(user_id: int):
    from app import bootstrap, add_flash, _set_vacation_carryover_exception, _upsert_vacation_carryover_override
    bootstrap()
    db = connect()
    target = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    if not target:
        abort(404)

    exception_on = 1 if request.form.get("exception") == "1" else 0
    _set_vacation_carryover_exception(user_id, exception_on)

    if exception_on and request.form.get("carryover_days") is not None:
        try:
            year = int(request.form.get("year") or datetime.date.today().year)
            carryover_days = float(request.form.get("carryover_days") or 0)
            valid_until = (request.form.get("valid_until") or "").strip() or None
            comment = (request.form.get("comment") or "").strip()
            _upsert_vacation_carryover_override(user_id, year, carryover_days, valid_until, comment)
        except (ValueError, TypeError):
            add_flash(t("flash.error.invalid_carryover"), "error")
            return redirect(url_for("admin.admin_vacation_carryover", user_id=user_id))

    add_flash(t("flash.success.carryover_saved"), "success")
    return redirect(url_for("admin.admin_vacation_carryover", user_id=user_id))


@admin_bp.post("/admin/users/<int:user_id>/vacation-carryover/delete/<int:year>")
@admin_required
def admin_vacation_carryover_delete(user_id: int, year: int):
    from app import bootstrap, add_flash, _delete_vacation_carryover_override
    bootstrap()
    _delete_vacation_carryover_override(user_id, year)
    add_flash(t("flash.success.carryover_deleted").format(year=year), "success")
    return redirect(url_for("admin.admin_vacation_carryover", user_id=user_id))


@admin_bp.post("/admin/impersonate/<int:user_id>")
@timemanager_required
def admin_impersonate(user_id: int):
    from app import bootstrap, add_flash
    bootstrap()
    u = current_user()
    db = connect()
    target = db.execute(
        "SELECT id, username, is_admin, is_active FROM users WHERE id=?", (user_id,)
    ).fetchone()
    db.close()
    if not target:
        abort(404)
    if target["is_admin"]:
        add_flash(t("flash.error.impersonate_admin"), "error")
        return redirect(url_for("admin.admin_home"))
    if not target["is_active"]:
        add_flash(t("flash.error.impersonate_inactive"), "error")
        return redirect(url_for("admin.admin_home"))
    session["impersonator_id"] = u["id"]
    session.permanent = True
    session["user_id"] = user_id
    return redirect("/")


@admin_bp.post("/admin/impersonate/stop")
def admin_impersonate_stop():
    impersonator_id = session.get("impersonator_id")
    if not impersonator_id:
        return redirect("/")
    session.permanent = True
    session["user_id"] = impersonator_id
    session.pop("impersonator_id", None)
    session.pop("lang", None)  # reload admin's own language on next request
    session.modified = True
    return redirect(url_for("admin.admin_home"))


# ─── Admin: Zeitschema bearbeiten / löschen ──────────────────────────────────


@admin_bp.get("/admin/schedule/<int:user_id>/edit/<schedule_id>")
@admin_required
def admin_schedule_edit(user_id: int, schedule_id: str):
    from app import bootstrap, flash_html, layout, FORM_ASSETS_JS, _sched_daily_blocks_html, _normalize_schedule
    bootstrap()
    u = current_user()
    db = connect()
    target = db.execute("SELECT id, username FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    if not target:
        abort(404)

    if schedule_id == "new":
        sched = _normalize_schedule({})
        is_new = True
    else:
        try:
            sid = int(schedule_id)
        except ValueError:
            abort(404)
        db = connect()
        row = db.execute("SELECT * FROM user_schedules WHERE id=? AND user_id=?", (sid, user_id)).fetchone()
        db.close()
        if not row:
            abort(404)
        sched = _normalize_schedule(dict(row))
        is_new = False

    title = (f"Neues Zeitschema – {target['username']}" if is_new
             else f"Zeitschema bearbeiten – {target['username']} (ab {sched.get('valid_from','')})")
    action = f"/admin/schedule/{user_id}/edit/{schedule_id}"
    back = f"/admin/users/{user_id}/edit"

    sid_val = None if is_new else (int(schedule_id) if schedule_id != "new" else None)
    allow_edit = int(sched.get("allow_self_edit") or 1)
    vf = sched.get("valid_from") or datetime.date.today().isoformat()

    body = f"""
    {flash_html()}
    {FORM_ASSETS_JS}
    <div style="margin-bottom:12px;">
      <a href="{back}" class="btn btn-sm">← {t('btn.back')}</a>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">{title}</h3>
      <form method="post" action="{action}">
        <div style="margin-bottom:12px;">
          <label style="font-size:12px;color:var(--mu);">{t('settings.schedule_valid')}</label>
          <input type="date" name="valid_from" value="{vf}"
                 style="margin-left:8px;font-size:13px;padding:4px 8px;border-radius:4px;">
        </div>
        {_sched_daily_blocks_html(sid_val, "daily")}
        <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--br);">
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;">
            <input type="checkbox" name="allow_self_edit" value="1"
                   {"checked" if allow_edit else ""}>
            {t('admin.schedule_allow_self_edit')}
          </label>
        </div>
        <div style="margin-top:16px;display:flex;gap:8px;">
          <button class="btn primary" type="submit">{t('btn.save')}</button>
          <a class="btn" href="{back}">{t('btn.cancel')}</a>
        </div>
      </form>
    </div>
    """
    return render_template_string(layout(title, body, u, APP_VERSION))


@admin_bp.post("/admin/schedule/<int:user_id>/edit/<schedule_id>")
@admin_required
def admin_schedule_edit_post(user_id: int, schedule_id: str):
    from app import bootstrap, add_flash, _parse_sched_blocks_from_form, _sched_save_blocks, _sched_save_exceptions_from_form
    bootstrap()
    db = connect()
    target = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    db.close()
    if not target:
        abort(404)

    valid_from = (request.form.get("valid_from") or "").strip() or datetime.date.today().isoformat()
    allow_self = 1 if request.form.get("allow_self_edit") else 0
    blocks = _parse_sched_blocks_from_form(request.form)
    mask = sum(1 << wd for wd in blocks.keys()) if blocks else 0

    db = connect()
    if schedule_id != "new":
        try:
            sid = int(schedule_id)
            db.execute(
                "UPDATE user_schedules SET valid_from=?, workdays_mask=?, allow_self_edit=? WHERE id=? AND user_id=?",
                (valid_from, mask, allow_self, sid, user_id)
            )
            db.commit()
        except (ValueError, Exception):
            db.close()
            add_flash(t("flash.error.invalid_date"), "error")
            return redirect(f"/admin/schedule/{user_id}/edit/{schedule_id}")
    else:
        db.execute(
            "INSERT INTO user_schedules (user_id, valid_from, mode, workdays_mask, weekly_minutes, allow_self_edit) "
            "VALUES (?, ?, 'daily', ?, 0, ?)",
            (user_id, valid_from, mask, allow_self)
        )
        db.commit()
        sid = db.execute(
            "SELECT id FROM user_schedules WHERE user_id=? AND mode='daily' ORDER BY id DESC LIMIT 1",
            (user_id,)
        ).fetchone()["id"]

    _sched_save_blocks(sid, blocks)
    _sched_save_exceptions_from_form(sid, request.form)
    db.close()
    add_flash(t("success.schedule_saved"), "success")
    return redirect(f"/admin/users/{user_id}/edit")


@admin_bp.post("/admin/schedule/<int:user_id>/delete/<int:schedule_id>")
@admin_required
def admin_schedule_delete(user_id: int, schedule_id: int):
    from app import bootstrap, add_flash, _fmt_date_de
    bootstrap()
    db = connect()
    row = db.execute(
        "SELECT id, valid_from FROM user_schedules WHERE id=? AND user_id=?",
        (schedule_id, user_id),
    ).fetchone()
    if row:
        db.execute("DELETE FROM user_schedules WHERE id=?", (schedule_id,))
        db.commit()
        add_flash(t("flash.success.schedule_deleted").format(date=_fmt_date_de(row["valid_from"])), "success")
    else:
        add_flash(t("flash.error.schedule_not_found"), "error")
    db.close()
    return redirect(f"/admin/users/{user_id}/edit")


@admin_bp.get("/admin/periods")
@admin_required
def admin_periods():
    from app import bootstrap, flash_html, layout, _t_month_short
    bootstrap()
    u = current_user()
    today = datetime.date.today()

    try:
        sel_year = int(request.args.get("y") or today.year)
    except (ValueError, TypeError):
        sel_year = today.year

    db = connect()
    try:
        all_users = db.execute("SELECT id, username FROM users WHERE is_active=1 ORDER BY username").fetchall()
        locks_raw = db.execute(
            "SELECT pl.*, u.username AS locked_by_name FROM period_locks pl "
            "LEFT JOIN users u ON u.id=pl.locked_by WHERE pl.year=? ORDER BY pl.user_id, pl.period_type, pl.month",
            (sel_year,),
        ).fetchall()
    finally:
        db.close()

    # Group locks by user_id
    locks_by_user: dict = {}
    for r in locks_raw:
        uid = r["user_id"]
        locks_by_user.setdefault(uid, {})
        if r["period_type"] == "year":
            locks_by_user[uid]["year"] = dict(r)
        else:
            locks_by_user[uid][f"{sel_year}-{r['month']:02d}"] = dict(r)

    available_years = list(range(max(today.year - 5, 2020), today.year + 1))
    year_opts = "".join(
        f'<option value="{y}" {"selected" if y == sel_year else ""}>{y}</option>'
        for y in reversed(available_years)
    )

    trs = ""
    for usr in all_users:
        uid = usr["id"]
        ulocks = locks_by_user.get(uid, {})
        year_lk = "year" in ulocks
        locked_months = [
            m for m in range(1, 13)
            if year_lk or f"{sel_year}-{m:02d}" in ulocks
        ]
        n_locked = len(locked_months)
        if n_locked == 0:
            status_txt = "<span class='small' style='color:var(--mu);'>Keine Abschlüsse</span>"
        elif n_locked == 12 or year_lk:
            status_txt = "<span style='color:var(--ok);'>🔒 Jahr abgeschlossen</span>"
        else:
            names = ", ".join(_t_month_short(m) for m in locked_months)
            status_txt = f"<span style='color:var(--ok);'>🔒 {n_locked} Monate ({names})</span>"

        unlock_form = (
            f"<form method='post' action='/admin/periods/unlock' style='display:inline;'>"
            f"<input type='hidden' name='target_user_id' value='{uid}'>"
            f"<input type='hidden' name='year' value='{sel_year}'>"
            f"<button class='btn danger btn-sm' >Alle entsperren</button>"
            f"</form>"
        ) if ulocks else ""

        detail_link = f"<a class='btn btn-sm' href='/periods?y={sel_year}' >Details</a>" if uid == u["id"] else ""

        trs += f"<tr><td><b>{usr['username']}</b></td><td>{status_txt}</td><td style='white-space:nowrap;'>{detail_link} {unlock_form}</td></tr>"

    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Admin: Abschlüsse</h3>
        <form method="get" style="display:flex;gap:8px;align-items:end;">
          <div><label>Jahr</label><br><select name="y">{year_opts}</select></div>
          <button class="btn" type="submit">Anzeigen</button>
        </form>
      </div>
      <table style="margin-top:12px;">
        <thead><tr><th>Benutzer</th><th>Status {sel_year}</th><th></th></tr></thead>
        <tbody>{trs}</tbody>
      </table>
    </div>
    """
    return render_template_string(layout(f"{t('admin.title')}: {t('periods.title')}", body, u, APP_VERSION))


@admin_bp.post("/admin/periods/unlock")
@admin_required
def admin_periods_unlock():
    from app import bootstrap, add_flash
    bootstrap()
    try:
        target_uid = int(request.form.get("target_user_id") or 0)
        year = int(request.form.get("year") or 0)
    except (ValueError, TypeError):
        add_flash(t("flash.invalid_input"), "error")
        return redirect("/admin/periods")

    db = connect()
    try:
        db.execute("DELETE FROM period_locks WHERE user_id=? AND year=?", (target_uid, year))
        db.commit()
    finally:
        db.close()
    add_flash(t("flash.success.year_unlocked").format(year=year), "success")
    return redirect(f"/admin?y={year}#acc-abschl")


@admin_bp.get("/admin")
@admin_required
def admin_home():
    from app import bootstrap, flash_html, layout, _date_input, _fmt_minutes, _get_user_schedule_for_day, _get_visible_user_ids, _feature_enabled, _get_timezone, _t_month_short, _fmt_backup_size, _get_backup_config, _get_mail_config, _REGION_LABEL, _render_per_user_settings_section, _render_admin_overtime_section, _render_admin_absences_section, _render_appearance_section, _render_regional_section, _render_backup_section, _render_bot_section, _render_update_section, _render_overtime_defaults_section, _render_features_section, _render_school_holidays_section, _render_admin_teams_inline, _render_admin_staffing_inline
    bootstrap()
    u = current_user()
    today = datetime.date.today()
    today_iso = today.isoformat()

    try:
        sel_year = int(request.args.get("y") or today.year)
    except (ValueError, TypeError):
        sel_year = today.year

    # ── fetch all data ─────────────────────────────────────────────────────────
    db = connect()
    all_users = db.execute(
        "SELECT id, username, display_name, is_admin, is_active, admin_role, "
        "vacation_carryover_exception, contouring_enabled, created_at, holiday_region, "
        "email, admin_only, login_locked_until, login_attempts FROM users ORDER BY username"
    ).fetchall()
    locks_raw = db.execute(
        "SELECT pl.*, u.username AS locked_by_name FROM period_locks pl "
        "LEFT JOIN users u ON u.id=pl.locked_by WHERE pl.year=? ORDER BY pl.user_id, pl.period_type, pl.month",
        (sel_year,),
    ).fetchall()
    teams = db.execute(
        "SELECT t.*, COUNT(ut.user_id) as member_count "
        "FROM teams t LEFT JOIN user_teams ut ON ut.team_id=t.id "
        "GROUP BY t.id ORDER BY t.name"
    ).fetchall()
    _tm_rows = db.execute("SELECT team_id, user_id FROM user_teams").fetchall()
    team_members: dict = {}
    for _r in _tm_rows:
        team_members.setdefault(_r["team_id"], []).append(_r["user_id"])
    if _feature_enabled("staffing"):
        plans = db.execute(
            "SELECT sp.*, t.name as team_name FROM staffing_plans sp "
            "JOIN teams t ON t.id=sp.team_id ORDER BY t.name, sp.name"
        ).fetchall()
        slots = db.execute(
            "SELECT ss.*, sp.name as plan_name FROM staffing_slots ss "
            "JOIN staffing_plans sp ON sp.id=ss.plan_id "
            "ORDER BY ss.plan_id, COALESCE(ss.time_from,'99:99'), ss.sort_order"
        ).fetchall()
        all_assignments = db.execute("SELECT * FROM staffing_assignments").fetchall()
    else:
        plans = slots = all_assignments = []
    db.close()

    mail_cfg = _get_mail_config()
    pw_set = bool(mail_cfg.get("mail_password"))

    locks_by_user: dict = {}
    for r in locks_raw:
        uid = r["user_id"]
        locks_by_user.setdefault(uid, {})
        if r["period_type"] == "year":
            locks_by_user[uid]["year"] = dict(r)
        else:
            locks_by_user[uid][f"{sel_year}-{r['month']:02d}"] = dict(r)

    # ── Section 1+2+3: build user table rows ──────────────────────────────────
    _is_sysadm = is_sysadmin(u)
    if not _is_sysadm:
        _vis_ids = _get_visible_user_ids(u)
        if _vis_ids is not None:
            _vis_id_set = set(_vis_ids)
            all_users = [r for r in all_users if r["id"] in _vis_id_set]
    user_trs = ""
    sched_trs = ""
    vac_trs = ""
    tm_user_trs = ""
    for r in all_users:
        uid = r["id"]
        display = r["display_name"] or r["username"]
        sub = r["username"] if r["display_name"] else ""
        sub_html = f" <span class='small' style='color:var(--mu);'>({sub})</span>" if sub else ""
        # Role badge
        role = r["admin_role"]
        if role == "sysadmin":
            role_badge = f" <span class='small' style='color:#6366f1;'>{t('admin.role_sysadmin_badge')}</span>"
        elif role == "timemanager":
            role_badge = f" <span class='small' style='color:#0891b2;'>{t('admin.role_tm_badge')}</span>"
        elif role == "hr":
            role_badge = f" <span class='small' style='color:#059669;'>{t('admin.role_hr_badge')}</span>"
        else:
            role_badge = ""
        inact_badge = f" <span class='small' style='color:var(--mu);'>· {t('admin.inactive_badge')}</span>" if not r["is_active"] else ""
        admin_only_badge = f" <span class='small' style='color:#7c3aed;'>{t('admin.admin_only_badge')}</span>" if r["admin_only"] else ""
        _hr = r["holiday_region"] or ""
        _bl_label = _REGION_LABEL.get(_hr, "")
        bl_badge = (f" <span class='small' style='color:var(--mu);'>📍 {_html.escape(_bl_label)}</span>"
                    if _hr and _bl_label else "")

        # Locked badge
        _locked_until_str = r["login_locked_until"] if r["login_locked_until"] else ""
        _is_locked = False
        if _locked_until_str:
            try:
                _lu = datetime.datetime.fromisoformat(_locked_until_str)
                if _lu.tzinfo is None:
                    _lu = _lu.replace(tzinfo=datetime.timezone.utc)
                _is_locked = _lu > datetime.datetime.now(tz=_get_timezone())
            except Exception:
                pass
        locked_badge = (f" <span class='small' style='color:var(--danger);font-weight:600;'>🔒 {t('auth.too_many_attempts')}</span>"
                        if _is_locked else "")

        # delete / impersonate buttons (sysadmin only for delete)
        del_btn = ""
        if _is_sysadm and uid != u["id"]:
            safe = display.replace("'", "\\'")
            del_btn = (
                f'<form method="post" action="/admin/users/{uid}/delete" style="display:contents;" '
                f'onsubmit="return confirm(\'Nutzer {safe} unwiderruflich löschen?\')">'
                f'<button class="btn danger btn-sm" type="submit">Löschen</button></form>'
            )
        imp_btn = ""
        if not r["is_admin"] and r["is_active"] and uid != u["id"]:
            imp_btn = (
                f'<form method="post" action="/admin/impersonate/{uid}" style="display:contents;">'
                f'<button class="btn btn-sm" type="submit">{t("admin.identity_btn")}</button></form>'
            )
        unlock_btn = ""
        if _is_locked:
            unlock_btn = (
                f'<form method="post" action="/admin/users/{uid}/unlock" style="display:contents;">'
                f'<button class="btn btn-sm" type="submit" style="color:var(--danger);">&#128275; {t("auth.admin_unlock_btn")}</button></form>'
            )
        _search_key = _html.escape((r["username"] + " " + (r["display_name"] or "")).lower())
        user_trs += (
            f'<tr data-search="{_search_key}">'
            f'<td>{display}{sub_html}{role_badge}{inact_badge}{admin_only_badge}{bl_badge}{locked_badge}</td>'
            f'<td class="small">{(r["created_at"] or "")[:10]}</td>'
            f'<td><div style="display:flex;gap:4px;flex-wrap:wrap;">'
            f'<a class="btn btn-sm" href="/admin/users/{uid}/edit">{t("btn.edit")}</a>'
            f'{imp_btn}{unlock_btn}{del_btn}</div></td>'
            f'</tr>'
        )

        # Timemanager user list row
        email_disp = _html.escape(r["email"] or "")
        email_html = f'<span class="small" style="color:var(--mu);">{email_disp}</span>' if email_disp else '<span class="small" style="color:var(--mu);">–</span>'
        pw_reset_btn = ""
        if uid != u["id"]:
            pw_reset_btn = (
                f'<form method="post" action="/admin/users/{uid}/reset-password" style="display:contents;">'
                f'<button class="btn btn-sm" type="submit" title="{t("admin.pw_reset_title")}">{t("admin.pw_reset_btn")}</button></form>'
            )
        imp_tm_btn = ""
        if not r["is_admin"] and r["is_active"] and uid != u["id"]:
            imp_tm_btn = (
                f'<form method="post" action="/admin/impersonate/{uid}" style="display:contents;">'
                f'<button class="btn btn-sm" type="submit" title="{t("admin.identity_btn")}">{t("admin.identity_btn")}</button></form>'
            )
        unlock_tm_btn = ""
        if _is_locked and uid != u["id"]:
            unlock_tm_btn = (
                f'<form method="post" action="/admin/users/{uid}/unlock" style="display:contents;">'
                f'<button class="btn btn-sm" type="submit" style="color:var(--danger);">&#128275; {t("auth.admin_unlock_btn")}</button></form>'
            )
        tm_user_trs += (
            f'<tr>'
            f'<td>{display}{sub_html}{role_badge}{inact_badge}{admin_only_badge}{locked_badge}</td>'
            f'<td>{email_html}</td>'
            f'<td style="white-space:nowrap;"><div style="display:flex;gap:4px;flex-wrap:wrap;">{imp_tm_btn}{unlock_tm_btn}{pw_reset_btn}</div></td>'
            f'</tr>'
        )

        # Schedule row
        sched = _get_user_schedule_for_day(uid, today_iso) or {}
        mode = (sched.get("mode") or "weekly").lower()
        if mode == "daily":
            dp = []
            for dk, lbl in [("mon_minutes",t("schedule.mo")),("tue_minutes",t("schedule.tu")),
                             ("wed_minutes",t("schedule.we")),("thu_minutes",t("schedule.th")),
                             ("fri_minutes",t("schedule.fr")),("sat_minutes",t("schedule.sa")),
                             ("sun_minutes",t("schedule.su"))]:
                v = int(sched.get(dk) or 0)
                if v: dp.append(f"{lbl}:{_fmt_minutes(v)}")
            soll_str = " ".join(dp) if dp else "–"
        else:
            wm = int(sched.get("weekly_minutes") or 0)
            soll_str = f"{wm/60:g} {t('schedule.hours_week')}" if wm else "–"
        sched_trs += (
            f'<tr><td>{display}{sub_html}</td>'
            f'<td class="small">{soll_str}</td>'
            f'<td><a class="btn btn-sm" href="/admin/users/{uid}/edit#schedule">{t("btn.edit")}</a></td></tr>'
        )

        # Vacation row
        exc_on = int(r["vacation_carryover_exception"] or 0)
        exc_badge = f" <span class='small' style='color:#d97706;'>{t('admin.carryover_exception_badge')}</span>" if exc_on else ""
        vac_trs += (
            f'<tr><td>{display}{sub_html}{exc_badge}</td>'
            f'<td><a class="btn btn-sm" href="/admin/users/{uid}/edit#vacation">{t("btn.edit")}</a></td></tr>'
        )

    # ── Section 4: Periods ────────────────────────────────────────────────────
    available_years = list(range(max(today.year - 5, 2020), today.year + 1))
    year_opts = "".join(
        f'<option value="{y}" {"selected" if y == sel_year else ""}>{y}</option>'
        for y in reversed(available_years)
    )
    periods_trs = ""
    for usr in all_users:
        uid = usr["id"]
        display = usr["display_name"] or usr["username"]
        ulocks = locks_by_user.get(uid, {})
        year_lk = "year" in ulocks
        locked_months = [m for m in range(1, 13) if year_lk or f"{sel_year}-{m:02d}" in ulocks]
        n = len(locked_months)
        if n == 0:
            status = f"<span class='small' style='color:var(--mu);'>{t('admin.no_periods')}</span>"
        elif n == 12 or year_lk:
            status = f"<span style='color:var(--ok);'>{t('periods.year_closed_status')}</span>"
        else:
            names = ", ".join(_t_month_short(m) for m in locked_months)
            status = f"<span style='color:var(--ok);'>🔒 {n} {t('periods.months')} ({names})</span>"
        unlock_form = (
            f"<form method='post' action='/admin/periods/unlock' style='display:contents;'>"
            f"<input type='hidden' name='target_user_id' value='{uid}'>"
            f"<input type='hidden' name='year' value='{sel_year}'>"
            f"<button class='btn danger btn-sm'>{t('periods.unlock')}</button></form>"
        ) if ulocks else ""
        periods_trs += (
            f"<tr><td><b>{display}</b></td><td>{status}</td>"
            f"<td><div style='display:flex;gap:4px;'>{unlock_form}"
            f"<a class='btn btn-sm' href='/admin/users/{uid}/edit#balance'>{t('btn.edit')}</a>"
            f"</div></td></tr>"
        )

    # ── Section 5: Mail ───────────────────────────────────────────────────────
    mail_status_row = lambda k, v: (
        f"<tr><td style='color:var(--mu);font-size:12px;'>{k}</td><td style='font-size:13px;'>{v}</td></tr>"
    )
    mail_status_html = (
        f"<table style='width:auto;margin-bottom:12px;'>"
        f"{mail_status_row(t('admin.smtp_host'), mail_cfg.get('mail_server') or '–')}"
        f"{mail_status_row(t('admin.smtp_port'), mail_cfg.get('mail_port') or '587')}"
        f"{mail_status_row(t('admin.smtp_user'), mail_cfg.get('mail_username') or '–')}"
        f"{mail_status_row(t('admin.smtp_pass'), '<span style=\"color:var(--ok);\">' + t('admin.set_hint') + '</span>' if pw_set else '<span style=\"color:var(--danger);\">' + t('admin.empty_hint') + '</span>')}"
        f"{mail_status_row(t('admin.smtp_from'), mail_cfg.get('mail_from') or '–')}"
        f"</table>"
    )

    admin_email = u.get("email") or ""

    # pre-render helper sections with data-tab attribute injected
    def _tab(html: str, tab: str) -> str:
        return html.replace('<div class="acc"', f'<div class="acc" data-tab="{tab}"', 1)

    _is_timemgr = is_timemanager(u)
    _is_approver = bool(u.get("is_approver"))

    _html_per_user  = _render_per_user_settings_section()
    _html_overtime  = _tab(_render_admin_overtime_section(u), "reporting")
    _html_absences  = _tab(_render_admin_absences_section(u), "reporting")
    _html_appearance = _tab(_render_appearance_section(), "system") if _is_sysadm else ""
    _html_regional  = _tab(_render_regional_section(), "system") if _is_sysadm else ""
    _html_backup    = _tab(_render_backup_section(), "system") if _is_sysadm else ""

    # User-Export/Import Dropdowns (für acc-user benötigt)
    _ue_db = connect()
    _ue_users = _ue_db.execute(
        "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY username"
    ).fetchall()
    _ue_db.close()
    user_export_opts = "".join(
        f'<option value="{_uu["id"]}">{_html.escape(_uu["display_name"] or _uu["username"])}</option>'
        for _uu in _ue_users
    )
    user_import_opts = user_export_opts
    _html_bot       = _tab(_render_bot_section(), "system") if _is_sysadm else ""
    _html_update    = _tab(_render_update_section(), "system") if _is_sysadm else ""
    _html_ot_defs   = _tab(_render_overtime_defaults_section(), "system") if _is_sysadm else ""
    _html_features  = _tab(_render_features_section(), "system") if _is_sysadm else ""
    _html_schoolhols = _tab(_render_school_holidays_section(), "system") if _is_sysadm else ""
    _new_user_btn   = f'<button class="btn primary btn-sm" type="button" onclick="toggleNewUser()">{t("admin.new_user_btn")}</button>' if _is_sysadm else ""

    # 4-Tab-Struktur
    _tabs = []
    if _is_sysadm:
        _tabs.append(("system", t("admin.tab_system")))
    if _is_sysadm or _is_timemgr:
        _tabs.append(("users", t("admin.tab_users")))
        _tabs.append(("reporting", t("admin.tab_reporting")))
    if _is_sysadm or _is_timemgr or _is_approver:
        _tabs.append(("planning", t("admin.tab_planning")))
    _tab_html = "".join(
        f'<button class="tab-btn" data-tab="{tid}" type="button" onclick="switchTab(\'{tid}\')">{tlabel}</button>'
        for tid, tlabel in _tabs
    )
    _default_tab = _tabs[0][0] if _tabs else "system"

    _staffing_js = ""
    if _feature_enabled("staffing"):
        _staffing_js = f"""<script>
function toggleSlotType(sel,pid){{
  var n=document.getElementById('wd-normal-'+pid);
  var s=document.getElementById('wd-special-'+pid);
  if(!n||!s)return;
  if(sel.value==='special'){{n.style.display='none';s.style.display='block';}}
  else{{n.style.display='block';s.style.display='none';}}
}}
function toggleSlotEdit(sid){{
  var el=document.getElementById('slot-edit-'+sid);
  if(!el)return;
  el.style.display=el.style.display==='none'?'block':'none';
}}
function slotFormInit(details){{
  var s=details.querySelector('select[name=slot_type]');
  if(!s)return;
  var oc=s.getAttribute('onchange')||'';
  var i1=oc.indexOf("'")+1;
  var i2=oc.lastIndexOf("'");
  if(i1>0&&i2>i1){{toggleSlotType(s,oc.substring(i1,i2));}}
}}
function allowDrop(e){{e.preventDefault();}}
function drag(e){{e.dataTransfer.setData("userId",e.target.dataset.userId);}}
function drop(e,slotId,target){{
  e.preventDefault();
  var uid=e.dataTransfer.getData("userId");
  var card=document.querySelector('[data-user-id="'+uid+'"]');
  if(card)e.currentTarget.appendChild(card);
  e.currentTarget.classList.remove("dragover");
}}
function toggleLead(btn){{
  var card=btn.closest('.user-card');
  var isLead=card.dataset.isLead==='1';
  card.dataset.isLead=isLead?'0':'1';
  btn.textContent=isLead?'○':'👑';
  btn.style.color=isLead?'var(--mu)':'#eab308';
}}
function saveAssignments(slotId){{
  var assigned=document.querySelectorAll("#assigned-"+slotId+" .user-card");
  var userIds=[].map.call(assigned,function(c){{return c.dataset.userId;}});
  var leadIds=[].map.call(assigned,function(c){{return c.dataset.isLead==='1'?c.dataset.userId:null;}}).filter(Boolean);
  var form=document.createElement("form");
  form.method="POST";form.action="/admin/staffing";
  [["action","save_assignments"],["slot_id",slotId]].forEach(function(p){{
    var i=document.createElement("input");i.type="hidden";i.name=p[0];i.value=p[1];form.appendChild(i);
  }});
  userIds.forEach(function(uid){{
    var i=document.createElement("input");i.type="hidden";i.name="user_ids";i.value=uid;form.appendChild(i);
  }});
  leadIds.forEach(function(uid){{
    var i=document.createElement("input");i.type="hidden";i.name="lead_user_ids";i.value=uid;form.appendChild(i);
  }});
  document.body.appendChild(form);form.submit();
}}
function deleteSlot(slotId){{
  if(!confirm("{t('confirm.delete')}"))return;
  var form=document.createElement("form");
  form.method="POST";form.action="/admin/staffing";
  [["action","delete_slot"],["slot_id",slotId]].forEach(function(p){{
    var i=document.createElement("input");i.type="hidden";i.name=p[0];i.value=p[1];form.appendChild(i);
  }});
  document.body.appendChild(form);form.submit();
}}
document.addEventListener('change',function(e){{
  if(e.target.name&&e.target.name.startsWith('wd_')){{
    var f=e.target.closest('form');if(!f)return;
    var pEl=f.querySelector('[name=plan_id]');
    var sEl=f.querySelector('[name=slot_id]');
    var hid_id=pEl?('wd-val-'+pEl.value):(sEl?('wd-val-edit-'+sEl.value):null);
    if(!hid_id)return;
    var c=[];
    f.querySelectorAll('[name^="wd_"]').forEach(function(cb){{if(cb.checked)c.push(cb.value);}});
    var h=document.getElementById(hid_id);if(h)h.value=c.join(',');
  }}
  if(e.target.name&&e.target.name.startsWith('nth_w_')){{
    var f=e.target.closest('form');if(!f)return;
    var pEl=f.querySelector('[name=plan_id]');
    var sEl=f.querySelector('[name=slot_id]');
    var hid_id=pEl?('nth-val-'+pEl.value):(sEl?('nth-val-edit-'+sEl.value):null);
    if(!hid_id)return;
    var c=[];
    f.querySelectorAll('[name^="nth_w_"]').forEach(function(cb){{if(cb.checked)c.push(cb.value);}});
    var h=document.getElementById(hid_id);if(h)h.value=c.join(',');
  }}
}});
document.addEventListener('DOMContentLoaded',function(){{
  document.querySelectorAll(".droptarget").forEach(function(el){{
    el.addEventListener("dragover",function(e){{e.preventDefault();el.classList.add("dragover");}});
    el.addEventListener("dragleave",function(){{el.classList.remove("dragover");}});
  }});
}});
</script>"""

    _all_active_users = [r for r in all_users if r["is_active"]]
    _html_teams_accordion = f"""
    <div class="acc" data-tab="planning" id="acc-teams">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-teams-body')">
        <span>👥 {t('admin.teams')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-teams-body">
        <div class="acc-inner">
          {_render_admin_teams_inline(teams, _all_active_users, team_members)}
        </div>
      </div>
    </div>"""
    _html_staffing_accordion = ""
    if _feature_enabled("staffing"):
        _html_staffing_accordion = f"""
    <div class="acc" data-tab="planning" id="acc-staffing">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-staffing-body')">
        <span>📋 {t('admin.staffing')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-staffing-body">
        <div class="acc-inner">
          {_render_admin_staffing_inline(teams, plans, slots, all_assignments, u)}
        </div>
      </div>
    </div>"""

    body = f"""
    {flash_html()}
<style>
.acc{{border:1px solid var(--bd);border-radius:var(--r);margin-bottom:10px;overflow:hidden;background:var(--bg);}}
.acc-hdr{{width:100%;display:flex;justify-content:space-between;align-items:center;
  padding:12px 16px;background:var(--sf);border:none;cursor:pointer;
  font-size:15px;font-weight:600;color:var(--tx);text-align:left;gap:10px;}}
.acc-hdr:hover{{background:var(--bd);}}
.acc-hdr.open{{border-bottom:1px solid var(--bd);}}
.acc-arr{{font-size:12px;flex-shrink:0;color:var(--mu);}}
.acc-body{{max-height:0;overflow:hidden;transition:max-height .28s ease;}}
.acc-body.open{{max-height:8000px;}}
.acc-inner{{padding:14px 16px;}}
.tab-bar{{display:flex;gap:6px;margin-bottom:14px;border-bottom:2px solid var(--bd);padding-bottom:0;}}
.tab-btn{{padding:8px 16px;border:none;background:none;cursor:pointer;font-size:14px;font-weight:600;
  color:var(--mu);border-bottom:2px solid transparent;margin-bottom:-2px;transition:color .12s,border-color .12s;}}
.tab-btn:hover{{color:var(--tx);}}
.tab-btn.active{{color:var(--ac);border-bottom-color:var(--ac);}}
</style>
<script>
function accToggle(id){{
  var b=document.getElementById(id);
  var h=b.previousElementSibling;
  var a=h.querySelector('.acc-arr');
  var op=b.classList.contains('open');
  b.classList.toggle('open',!op);
  h.classList.toggle('open',!op);
  if(a)a.textContent=op?'▼':'▲';
}}
function toggleNewUser(){{
  var p=document.getElementById('new-user-panel');
  if(!p)return;
  p.style.display=(p.style.display==='none'||!p.style.display)?'block':'none';
}}
function nuRoleChange(){{
  var role=document.getElementById('nu-role').value;
  var aoRow=document.getElementById('nu-admin-only-row');
  if(aoRow)aoRow.style.display=(role==='sysadmin'||role==='timemanager')?'':'none';
}}
function nuSendChange(){{
  var send=document.getElementById('nu-send');
  var pwWrap=document.getElementById('nu-pw-wrap');
  var pw=document.getElementById('nu-pw');
  if(!send||!pw)return;
  pw.required=!send.checked;
  if(pwWrap)pwWrap.style.opacity=send.checked?'0.4':'1';
}}
var _TAB_MAP={{
  'acc-mail':'system','acc-bot':'system',
  'acc-appearance':'system','acc-regional':'system',
  'acc-backup':'system','acc-update':'system','acc-features':'system','acc-schoolhols':'system',
  'acc-user':'users','acc-tm-users':'users',
  'acc-per-user-settings':'users',
  'acc-overtime':'reporting',
  'acc-absoverview':'reporting',
  'acc-teams':'planning','acc-staffing':'planning'
}};
var _DEFAULT_TAB='{_default_tab}';
function switchTab(tab){{
  document.querySelectorAll('.acc[data-tab]').forEach(function(el){{
    el.style.display=el.dataset.tab===tab?'':'none';
  }});
  document.querySelectorAll('.tab-btn').forEach(function(btn){{
    btn.classList.toggle('active',btn.dataset.tab===tab);
  }});
  sessionStorage.setItem('adminTab',tab);
}}
window.addEventListener('DOMContentLoaded',function(){{
  var h=(window.location.hash||'').replace('#','');
  var tab=sessionStorage.getItem('adminTab')||_DEFAULT_TAB;
  if(h&&_TAB_MAP[h])tab=_TAB_MAP[h];
  if(!tab)tab=_DEFAULT_TAB;
  switchTab(tab);
  var ss=sessionStorage.getItem('openAcc');
  if(ss)sessionStorage.removeItem('openAcc');
  var toOpen=h?('#'+h):(ss?('#'+ss):null);
  if(toOpen){{
    var el=document.querySelector(toOpen+' .acc-body');
    var hd=document.querySelector(toOpen+' .acc-hdr');
    var ar=document.querySelector(toOpen+' .acc-arr');
    if(el){{el.classList.add('open');if(hd)hd.classList.add('open');if(ar)ar.textContent='▲';}}
  }}
}});
function filterUserTable(query){{
  query=query.toLowerCase().trim();
  document.querySelectorAll('tr[data-search]').forEach(function(tr){{
    var match=!query||tr.getAttribute('data-search').indexOf(query)!==-1;
    tr.style.display=match?'':'none';
  }});
}}
function filterVacTable(query){{
  query=query.toLowerCase().trim();
  document.querySelectorAll('#acc-absoverview-body tr[data-search]').forEach(function(tr){{
    var match=!query||tr.getAttribute('data-search').indexOf(query)!==-1;
    tr.style.display=match?'':'none';
  }});
}}
</script>

<div class="tab-bar">{_tab_html}</div>{_staffing_js}

    <!-- Section 1: Benutzerverwaltung -->
    <div class="acc" id="acc-user" data-tab="users">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-user-body')">
        <span>{t('admin.acc_user_mgmt')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-user-body">
        <div class="acc-inner">
          <div style="margin-bottom:10px;">
            <input type="text" id="user-search-input"
                   placeholder="{t('admin.search_users_placeholder')}"
                   oninput="filterUserTable(this.value)"
                   style="width:100%;max-width:320px;padding:7px 10px;border-radius:6px;font-size:13px;">
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
            <span class="small">{len(all_users)} {t('admin.users_title')}</span>
            {_new_user_btn}
          </div>

          <div id="new-user-panel" style="display:none;border:1px solid var(--bd);border-radius:var(--rs);padding:12px;margin-bottom:12px;background:var(--sf);">
            <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.new_user_title')}</div>
            <form method="post" action="/admin/users/new" id="nu-form" autocomplete="off">
              <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;">
                <div><label style="font-size:12px;">{t('admin.user_name')}</label><br><input name="username" required autocomplete="off" style="font-size:13px;padding:5px 8px;" id="nu-user"></div>
                <div id="nu-pw-wrap"><label style="font-size:12px;">{t('admin.temp_password')}</label><br><input type="password" name="password" id="nu-pw" autocomplete="new-password" style="font-size:13px;padding:5px 8px;"></div>
                <div><label style="font-size:12px;">{t('admin.email')}</label><br><input type="email" name="user_email" placeholder="name@firma.de" style="font-size:13px;padding:5px 8px;"></div>
                <div><label style="font-size:12px;">{t('admin.tracking_start_col')}</label><br>{_date_input("tracking_start_date", today_iso)}</div>
              </div>
              <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;align-items:flex-end;">
                <div>
                  <label style="font-size:12px;">{t('admin.role')}</label>
                  <select name="admin_role" id="nu-role" onchange="nuRoleChange()" style="font-size:13px;padding:5px 8px;width:auto;">
                    <option value="">{t('admin.role_user')}</option>
                    <option value="timemanager">{t('admin.role_tm_badge')}</option>
                    <option value="hr">{t('admin.role_hr_badge')}</option>
                    <option value="sysadmin">{t('admin.role_sysadmin_badge')}</option>
                  </select>
                </div>
                <label style="font-size:13px;font-weight:400;"><input type="checkbox" name="is_active" value="1" checked> {t('admin.active')}</label>
              </div>
              <div id="nu-admin-only-row" style="display:none;margin-bottom:8px;">
                <label style="font-size:13px;font-weight:400;"><input type="checkbox" name="admin_only" value="1" id="nu-ao"> {t('admin.admin_only_label')}</label>
              </div>
              <div style="margin-bottom:8px;">
                <label style="font-size:13px;font-weight:400;"><input type="checkbox" name="send_pw_email" value="1" id="nu-send" onchange="nuSendChange()"> {t('admin.send_pw_email_label')}</label>
              </div>
              <div style="display:flex;gap:6px;">
                <button class="btn primary btn-sm" type="submit">{t('admin.create_btn')}</button>
                <button class="btn btn-sm" type="button" onclick="toggleNewUser()">{t('btn.cancel')}</button>
              </div>
              <div class="small" style="margin-top:6px;color:var(--mu);">{t('admin.onboarding_hint')}</div>
            </form>
          </div>

          <div class="table-scroll">
            <table>
              <thead><tr><th>{t('admin.users_title')}</th><th>{t('admin.col_created')}</th><th></th></tr></thead>
              <tbody>{user_trs}</tbody>
            </table>
          </div>
          <div class="small" style="color:var(--mu);margin-top:6px;">{t('admin.cant_delete_own')}</div>

          <hr style="margin:16px 0;">
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.backup_user_title')}</div>
          <p class="small" style="color:var(--mu);margin-bottom:10px;">{t('admin.backup_user_hint')}</p>
          <div style="font-size:13px;font-weight:600;margin-bottom:6px;">{t('admin.backup_user_export_title')}</div>
          <form method="get" action="/admin/backup/user/export" style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:18px;">
            <div>
              <label style="font-size:12px;">{t('admin.users_title')}</label><br>
              <select name="uid" style="font-size:13px;padding:4px 8px;">{user_export_opts}</select>
            </div>
            <button class="btn btn-sm" type="submit">&#11015; {t('btn.export')} (.json)</button>
          </form>
          <div style="font-size:13px;font-weight:600;margin-bottom:6px;">{t('admin.backup_user_import_title')}</div>
          <p class="small" style="color:var(--mu);margin-bottom:8px;">{t('admin.backup_user_import_hint')}</p>
          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;">
            <div>
              <label style="font-size:12px;">{t('admin.backup_user_file_label')}</label><br>
              <input type="file" id="user-import-file" accept=".json" style="font-size:13px;">
            </div>
            <div>
              <label style="font-size:12px;">{t('admin.backup_user_target')}</label><br>
              <select id="user-import-target" style="font-size:13px;padding:4px 8px;">{user_import_opts}</select>
            </div>
            <div style="padding-top:18px;">
              <button class="btn btn-sm" type="button" onclick="userImportPreview()">{t('admin.backup_preview_btn')}</button>
            </div>
          </div>
          <div id="user-import-preview" style="display:none;background:var(--sf);border:1px solid var(--bd);border-radius:var(--rs);padding:10px;margin-bottom:10px;font-size:13px;"></div>
          <form method="post" action="/admin/backup/user/import" enctype="multipart/form-data" id="user-import-form">
            <input type="hidden" name="target_uid" id="user-import-target-hidden">
            <input type="file" name="user_file" id="user-import-file-hidden" style="display:none;" accept=".json">
            <button class="btn primary btn-sm" type="submit" id="user-import-confirm" style="display:none;" onclick="return prepareUserImport()">&#11014; {t('btn.import')}</button>
          </form>
        </div>
      </div>
    </div>

    <!-- Section: Teams -->
    {_html_teams_accordion}

    <!-- Section: Staffing -->
    {_html_staffing_accordion}

    <!-- Section 5: Maileinstellungen -->
    <div class="acc" id="acc-mail" data-tab="system">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-mail-body')">
        <span>{t('admin.acc_mail')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-mail-body">
        <div class="acc-inner">
          {mail_status_html}
          <form method="post" action="/admin/mail-settings" style="margin-bottom:16px;" autocomplete="off">
            <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;">
              <div style="flex:2;min-width:180px;">
                <label style="font-size:12px;">{t('admin.smtp_host')}</label>
                <input type="text" name="mail_server" value="{mail_cfg.get('mail_server','')}" placeholder="mail.beispiel.de" required style="font-size:13px;padding:5px 8px;">
              </div>
              <div style="flex:0 0 90px;">
                <label style="font-size:12px;">{t('admin.smtp_port')}</label>
                <input type="number" name="mail_port" value="{mail_cfg.get('mail_port','587')}" min="1" max="65535" required style="width:80px;font-size:13px;padding:5px 8px;">
              </div>
            </div>
            <div style="margin-bottom:8px;">
              <label style="font-size:12px;">{t('admin.smtp_user')}</label>
              <input type="text" name="mail_username" value="{mail_cfg.get('mail_username','')}" placeholder="user@beispiel.de" required autocomplete="off" data-lpignore="true" style="font-size:13px;padding:5px 8px;">
            </div>
            <div style="margin-bottom:8px;">
              <label style="font-size:12px;">{t('admin.smtp_pass')} {"<span style='font-weight:400;color:var(--mu);'>(" + t('admin.smtp_pass_hint') + ")</span>" if pw_set else ""}</label>
              <input type="password" name="mail_password" value="" placeholder="{'••••••••' if pw_set else t('admin.smtp_pass')}" autocomplete="new-password" data-lpignore="true" style="font-size:13px;padding:5px 8px;">
            </div>
            <div style="margin-bottom:10px;">
              <label style="font-size:12px;">{t('admin.smtp_from')}</label>
              <input type="text" name="mail_from" value="{mail_cfg.get('mail_from','')}" placeholder="Zeiterfassung &lt;noreply@beispiel.de&gt;" style="font-size:13px;padding:5px 8px;">
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
          </form>
          <hr style="margin:12px 0;">
          <div style="font-size:13px;font-weight:600;margin-bottom:8px;">{t('admin.smtp_test')}</div>
          <form method="post" action="/admin/mail-settings/test">
            <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;">
              <div>
                <label style="font-size:12px;">{t('admin.smtp_test_recipient')}</label>
                <input type="email" name="test_recipient" value="{admin_email}" placeholder="admin@beispiel.de" required style="font-size:13px;padding:5px 8px;">
              </div>
              <button class="btn btn-sm" type="submit">{t('admin.smtp_test')}</button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- Section 7: Gleitzeitkonto Übersicht -->
    {_html_overtime}

    <!-- Section 6: Urlaubsübersicht -->
    {_html_absences}

    <!-- Section 8: Erscheinungsbild -->
    {_html_appearance}

    <!-- Section 8b: Regionale Einstellungen -->
    {_html_regional}

    <!-- Section 9: Überstunden-Defaults -->
    {_html_ot_defs}

    <!-- Section 9b: Features -->
    {_html_features}

    <!-- Section 9c: Schulferien -->
    {_html_schoolhols}

    <!-- Section 10: Backup & Restore -->
    {_html_backup}

    <!-- Section 11: Telegram Bot -->
    {_html_bot}

    <!-- Section 12: System Update -->
    {_html_update}
    """
    return render_template_string(layout(t("admin.title"), body, u, APP_VERSION))


def _render_backup_section() -> str:
    from backup import list_local_backups
    cfg = _get_backup_config()
    last_ts = cfg.get("last_backup_time") or ""
    auto_on = cfg.get("auto_backup_enabled", "0") == "1"
    auto_time = cfg.get("auto_backup_time") or "02:00"
    auto_checked = "checked" if auto_on else ""
    auto_enc_on = cfg.get("auto_encrypt_enabled", "0") == "1"
    auto_enc_checked = "checked" if auto_enc_on else ""
    auto_enc_pw_set = bool(cfg.get("auto_encrypt_password", ""))

    # Local full backups list
    backups = list_local_backups()
    backup_rows = ""
    for b in backups:
        safe = b["name"].replace("'", "\\'")
        mtime_str = b["mtime"].strftime("%d.%m.%Y %H:%M")
        size_str = _fmt_backup_size(b["size"])
        enc_badge = " <span style='font-size:10px;color:#6366f1;font-weight:600;'>🔒</span>" if b.get("encrypted") else ""
        backup_rows += (
            f"<tr>"
            f"<td style='font-size:12px;'>{mtime_str}</td>"
            f"<td style='font-size:12px;'>{size_str}</td>"
            f"<td style='font-size:12px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--mu);'>{b['name']}{enc_badge}</td>"
            f"<td style='white-space:nowrap;'>"
            f"<a class='btn btn-sm' href='/admin/backup/local/{b['name']}'>&#11123;</a>"
            f"<form method='post' action='/admin/backup/delete/{b['name']}' style='display:inline;margin-left:4px;'"
            f" onsubmit=\"return confirm('Backup {safe} löschen?')\">"
            f"<button class='btn danger btn-sm' type='submit'>✕</button></form>"
            f"</td>"
            f"</tr>"
        )
    if not backup_rows:
        backup_rows = f"<tr><td colspan='4' style='color:var(--mu);font-size:13px;'>{t('admin.backup_none_local')}</td></tr>"

    # Users for export/import dropdowns
    _db = connect()
    _all_users = _db.execute(
        "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY username"
    ).fetchall()
    _db.close()
    user_export_opts = "".join(
        f'<option value="{u["id"]}">{u["display_name"] or u["username"]}</option>'
        for u in _all_users
    )
    user_import_opts = "".join(
        f'<option value="{u["id"]}">{u["display_name"] or u["username"]}</option>'
        for u in _all_users
    )

    _auto_enc_pw_hint = f" <span style='color:var(--mu);font-size:11px;'>({t('settings.saved')})</span>" if auto_enc_pw_set else ""
    _restore_confirm = t('admin.backup_restore_confirm')
    return f"""
    <div class="acc" data-tab="system" id="acc-backup">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-backup-body')">
        <span>{t('admin.acc_backup')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-backup-body">
        <div class="acc-inner">

          <!-- ── 1. Vollständiges Backup ── -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.backup_full_title')}</div>
          <p class="small" style="color:var(--mu);margin-bottom:10px;">{t('admin.backup_full_hint')}</p>

          <!-- Download-Formular mit optionaler Verschlüsselung -->
          <form method="post" action="/admin/backup/download" style="margin-bottom:12px;">
            <div style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap;margin-bottom:8px;">
              <div>
                <label style="font-size:13px;font-weight:400;display:flex;align-items:center;gap:6px;">
                  <input type="checkbox" id="dl-enc-toggle" name="encrypt" value="1"
                         onchange="bkDlToggle()"> {t('backup.encrypt')}
                </label>
              </div>
              <div class="small" style="color:var(--mu);padding-top:3px;">
                {t('admin.backup_last') + " <b>" + last_ts + "</b>" if last_ts else t('admin.backup_none')}
              </div>
            </div>
            <div id="dl-enc-fields" style="display:none;margin-bottom:8px;background:var(--sf);border:1px solid var(--bd);border-radius:var(--rs);padding:10px;">
              <p class="small" style="color:#6366f1;margin-bottom:8px;">&#128274; {t('backup.encrypt_hint')}</p>
              <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <div>
                  <label style="font-size:12px;">{t('backup.password')}</label><br>
                  <input type="password" name="password" id="dl-enc-pw" autocomplete="new-password"
                         style="font-size:13px;padding:4px 8px;width:180px;">
                </div>
                <div>
                  <label style="font-size:12px;">{t('backup.password_confirm')}</label><br>
                  <input type="password" name="password_confirm" id="dl-enc-pw2" autocomplete="new-password"
                         style="font-size:13px;padding:4px 8px;width:180px;">
                </div>
              </div>
            </div>
            <button class="btn primary btn-sm" type="submit">&#11015; {t('admin.backup_download_btn')}</button>
          </form>

          <!-- Auto-Backup + Auto-Verschlüsselung -->
          <form method="post" action="/admin/backup/auto-config" style="margin-bottom:12px;">
            <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
              <label style="font-size:13px;font-weight:400;display:flex;align-items:center;gap:6px;">
                <input type="checkbox" name="auto_enabled" value="1" {auto_checked}> {t('admin.backup_auto')}
              </label>
              <div>
                <label style="font-size:12px;">{t('common.time')}</label>
                <input type="time" name="auto_time" value="{auto_time}" style="font-size:13px;padding:4px 8px;width:110px;">
              </div>
            </div>
            <div style="margin-top:8px;">
              <label style="font-size:13px;font-weight:400;display:flex;align-items:center;gap:6px;">
                <input type="checkbox" id="auto-enc-toggle" name="auto_encrypt_enabled" value="1"
                       {auto_enc_checked} onchange="autoEncToggle()"> {t('backup.auto_encrypt')}
              </label>
            </div>
            <div id="auto-enc-fields" style="display:{'block' if auto_enc_on else 'none'};margin-top:8px;background:var(--sf);border:1px solid var(--bd);border-radius:var(--rs);padding:10px;">
              <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <div>
                  <label style="font-size:12px;">{t('backup.auto_encrypt_password')}{_auto_enc_pw_hint}</label><br>
                  <input type="password" name="auto_encrypt_password" autocomplete="new-password"
                         placeholder="{'••••••••' if auto_enc_pw_set else ''}"
                         style="font-size:13px;padding:4px 8px;width:180px;">
                </div>
                <div>
                  <label style="font-size:12px;">{t('backup.password_confirm')}</label><br>
                  <input type="password" name="auto_encrypt_password_confirm" autocomplete="new-password"
                         style="font-size:13px;padding:4px 8px;width:180px;">
                </div>
              </div>
            </div>
            <div style="margin-top:8px;">
              <button class="btn btn-sm" type="submit">{t('btn.save')}</button>
            </div>
            <p class="small" style="margin-top:6px;color:var(--mu);">{t('admin.backup_keep_hint')}</p>
          </form>

          <!-- Restore -->
          <div style="font-size:13px;font-weight:600;margin-bottom:6px;">{t('admin.backup_restore_title')}</div>
          <form method="post" action="/admin/backup/restore" enctype="multipart/form-data"
                onsubmit="return confirm('{_restore_confirm}');" id="restore-form">
            <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:6px;">
              <div>
                <label style="font-size:12px;">{t('admin.backup_file_label')} / {t('backup.encrypted_file')}</label>
                <input type="file" name="backup_file" accept=".db,.db.gz,.gz,.enc"
                       required style="font-size:13px;display:block;margin-top:2px;"
                       onchange="restoreEncDetect(this)">
              </div>
              <button class="btn danger btn-sm" type="submit">&#11014; {t('btn.import')}</button>
            </div>
            <div id="restore-enc-field" style="display:none;margin-bottom:6px;">
              <label style="font-size:12px;">&#128274; {t('backup.password')}</label><br>
              <input type="password" name="enc_password" id="restore-enc-pw"
                     style="font-size:13px;padding:4px 8px;width:200px;" autocomplete="current-password">
            </div>
          </form>
          <p class="small" style="color:var(--mu);margin-bottom:12px;">{t('admin.backup_restore_hint')}</p>

          <!-- Lokale Backups Liste -->
          <div style="font-size:13px;font-weight:600;margin-bottom:6px;">{t('admin.backup_local_title')} ({len(backups)})</div>
          <div class="table-scroll" style="margin-bottom:0;">
            <table>
              <thead><tr><th>{t('common.date')}</th><th>{t('admin.backup_size')}</th><th>{t('admin.backup_filename')}</th><th></th></tr></thead>
              <tbody>{backup_rows}</tbody>
            </table>
          </div>

          <hr style="margin:20px 0;">

          <!-- ── 2. Einstellungen-Backup ── -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.backup_settings_title')}</div>
          <p class="small" style="color:var(--mu);margin-bottom:10px;">{t('admin.backup_settings_hint')}</p>
          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;">
            <a class="btn btn-sm" href="/admin/backup/settings/export">&#11015; {t('admin.backup_settings_export_btn')}</a>
          </div>
          <div style="font-size:13px;font-weight:600;margin-bottom:6px;">{t('admin.backup_settings_import_title')}</div>
          <form method="post" action="/admin/backup/settings/import" enctype="multipart/form-data">
            <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:6px;">
              <div>
                <label style="font-size:12px;">{t('admin.backup_settings_file_label')}</label>
                <input type="file" name="settings_file" accept=".json" required style="font-size:13px;">
              </div>
              <button class="btn btn-sm" type="submit">&#11014; {t('btn.import')}</button>
            </div>
          </form>
          <p class="small" style="color:var(--mu);">{t('admin.backup_settings_import_hint')}</p>

        </div>
      </div>
    </div>
<script>
function bkDlToggle(){{
  var on=document.getElementById('dl-enc-toggle').checked;
  document.getElementById('dl-enc-fields').style.display=on?'block':'none';
  var pw=document.getElementById('dl-enc-pw');
  if(pw) pw.required=on;
}}
function autoEncToggle(){{
  var on=document.getElementById('auto-enc-toggle').checked;
  document.getElementById('auto-enc-fields').style.display=on?'block':'none';
}}
function restoreEncDetect(inp){{
  var fname=(inp.value||'').toLowerCase();
  var isEnc=fname.endsWith('.enc');
  document.getElementById('restore-enc-field').style.display=isEnc?'block':'none';
  var pw=document.getElementById('restore-enc-pw');
  if(pw) pw.required=isEnc;
}}
function userImportPreview(){{
  var fi=document.getElementById('user-import-file');
  if(!fi||!fi.files||!fi.files[0]){{alert('Bitte zuerst eine Datei auswählen.');return;}}
  var fr=new FileReader();
  fr.onload=function(e){{
    try{{
      var d=JSON.parse(e.target.result);
      if(d._type!=='zeiterfassung_user_export'){{alert('Ungültige User-Export-Datei.');return;}}
      var u=(d.user||{{}});
      var tb=(d.time_blocks||[]).length;
      var ab=(d.absences||[]).length;
      var bt=(d.business_trips||[]).length;
      var sc=(d.user_schedules||[]).length;
      var pr=document.getElementById('user-import-preview');
      pr.style.display='block';
      pr.innerHTML='<b>Export von: '+_esc(u.username||'?')+'</b>'
        +(u.display_name?' <span style="color:var(--mu);">('+_esc(u.display_name)+')</span>':'')+'<br>'
        +'<span style="color:var(--mu);font-size:12px;">Exportiert: '+_esc(d._exported_at||'')+'</span>'
        +'<div style="margin-top:8px;">Zeitblöcke: <b>'+tb+'</b> &nbsp;·&nbsp; '
        +'Abwesenheiten: <b>'+ab+'</b> &nbsp;·&nbsp; '
        +'Dienstreisen: <b>'+bt+'</b> &nbsp;·&nbsp; '
        +'Zeitschemas: <b>'+sc+'</b></div>';
      document.getElementById('user-import-confirm').style.display='inline-block';
    }}catch(ex){{alert('Fehler beim Lesen der Datei: '+ex);}}
  }};
  fr.readAsText(fi.files[0],'utf-8');
}}
function prepareUserImport(){{
  var fi=document.getElementById('user-import-file');
  var fh=document.getElementById('user-import-file-hidden');
  var tgt=document.getElementById('user-import-target');
  var th=document.getElementById('user-import-target-hidden');
  if(!fi||!fi.files||!fi.files[0]){{alert('Keine Datei ausgewählt.');return false;}}
  var dt=new DataTransfer();
  dt.items.add(fi.files[0]);
  fh.files=dt.files;
  th.value=tgt.value;
  return true;
}}
function _esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
</script>"""


@admin_bp.post("/admin/backup/download")
@sysadmin_required
def admin_backup_download():
    from app import bootstrap, add_flash, _record_last_backup
    bootstrap()
    from backup import create_backup_gz, encrypt_backup
    import io as _io

    encrypt = bool(request.form.get("encrypt"))
    password = (request.form.get("password") or "").strip()
    password_confirm = (request.form.get("password_confirm") or "").strip()

    if encrypt:
        if not password:
            add_flash(t("flash.error.backup_password_required"), "error")
            return redirect("/admin#acc-backup")
        if password != password_confirm:
            add_flash(t("backup.password_mismatch"), "error")
            return redirect("/admin#acc-backup")

    buf, fname = create_backup_gz()
    _record_last_backup()
    raw = buf.getvalue()

    if encrypt:
        raw = encrypt_backup(raw, password)
        fname = fname + ".enc"
        mimetype = "application/octet-stream"
    else:
        mimetype = "application/gzip"

    return send_file(
        _io.BytesIO(raw),
        mimetype=mimetype,
        as_attachment=True,
        download_name=fname,
    )


@admin_bp.post("/admin/backup/restore")
@sysadmin_required
def admin_backup_restore():
    from app import bootstrap, add_flash
    bootstrap()
    from backup import restore_from_bytes, decrypt_backup
    import threading

    f = request.files.get("backup_file")
    if not f or not f.filename:
        add_flash(t("flash.error.no_file"), "error")
        return redirect("/admin#acc-backup")

    fname = f.filename.lower()
    is_enc = fname.endswith(".enc")
    base_fname = fname[:-4] if is_enc else fname

    if not (base_fname.endswith(".db") or base_fname.endswith(".db.gz") or base_fname.endswith(".gz")):
        add_flash(t("flash.error.invalid_db_file"), "error")
        return redirect("/admin#acc-backup")

    data = f.read()

    if is_enc:
        password = (request.form.get("enc_password") or "").strip()
        if not password:
            add_flash(t("flash.error.backup_password_required"), "error")
            return redirect("/admin#acc-backup")
        try:
            data = decrypt_backup(data, password)
        except Exception:
            add_flash(t("backup.wrong_password"), "error")
            return redirect("/admin#acc-backup")
        base_fname = fname[:-4]

    is_gz = base_fname.endswith(".gz")

    try:
        pre_path = restore_from_bytes(data, is_gz)
    except Exception as e:
        add_flash(t("flash.error.restore_failed").format(error=e), "error")
        return redirect("/admin#acc-backup")

    add_flash(t("flash.success.restore_done"), "success")

    def _restart():
        import time, os
        time.sleep(1.5)
        os.system(os.environ.get("RESTART_CMD", "systemctl restart zeiterfassung"))

    threading.Thread(target=_restart, daemon=True).start()
    return redirect("/admin#acc-backup")


@admin_bp.post("/admin/backup/auto-config")
@sysadmin_required
def admin_backup_auto_config():
    from app import bootstrap, add_flash, _save_backup_config
    bootstrap()
    enabled = bool(request.form.get("auto_enabled"))
    _t = (request.form.get("auto_time") or "02:00").strip()
    import re as _re
    if not _re.match(r"^\d{2}:\d{2}$", _t):
        _t = "02:00"
    auto_enc = bool(request.form.get("auto_encrypt_enabled"))
    auto_enc_pw = (request.form.get("auto_encrypt_password") or "").strip()
    auto_enc_pw_confirm = (request.form.get("auto_encrypt_password_confirm") or "").strip()
    if auto_enc and auto_enc_pw and auto_enc_pw != auto_enc_pw_confirm:
        add_flash(t("backup.password_mismatch"), "error")
        return redirect("/admin#acc-backup")
    _save_backup_config(enabled, _t, auto_enc, auto_enc_pw)
    add_flash(t("settings.saved"), "success")
    return redirect("/admin#acc-backup")


@admin_bp.get("/admin/backup/local/<filename>")
@sysadmin_required
def admin_backup_download_local(filename: str):
    from app import bootstrap
    bootstrap()
    from backup import BACKUPS_DIR
    import re as _re
    if not _re.match(r'^[\w\-\.]+\.db\.gz(\.enc)?$', filename):
        abort(400)
    path = BACKUPS_DIR / filename
    if not path.exists():
        abort(404)
    mimetype = "application/octet-stream" if filename.endswith(".enc") else "application/gzip"
    return send_file(str(path), mimetype=mimetype, as_attachment=True, download_name=filename)


@admin_bp.post("/admin/backup/delete/<filename>")
@sysadmin_required
def admin_backup_delete(filename: str):
    from app import bootstrap, add_flash
    bootstrap()
    from backup import BACKUPS_DIR
    import re as _re
    if not _re.match(r'^[\w\-\.]+\.db\.gz(\.enc)?$', filename):
        abort(400)
    path = BACKUPS_DIR / filename
    if path.exists():
        path.unlink()
        add_flash(t("flash.success.backup_deleted").format(filename=filename), "success")
    else:
        add_flash(t("flash.error.file_not_found"), "error")
    return redirect("/admin#acc-backup")


@admin_bp.get("/admin/backup/settings/export")
@sysadmin_required
def admin_backup_settings_export():
    from app import bootstrap
    bootstrap()
    import io as _io
    from backup import export_settings
    data, fname = export_settings()
    return send_file(
        _io.BytesIO(data),
        mimetype="application/json",
        as_attachment=True,
        download_name=fname,
    )


@admin_bp.post("/admin/backup/settings/import")
@sysadmin_required
def admin_backup_settings_import():
    from app import bootstrap, add_flash
    bootstrap()
    from backup import import_settings
    f = request.files.get("settings_file")
    if not f or not f.filename:
        add_flash(t("flash.error.no_file"), "error")
        return redirect("/admin#acc-backup")
    if not f.filename.lower().endswith(".json"):
        add_flash(t("flash.error.invalid_json_file"), "error")
        return redirect("/admin#acc-backup")
    try:
        counts = import_settings(f.read())
        add_flash(t("flash.success.settings_imported").format(mail=counts["mail"], bot=counts["bot"]), "success")
    except Exception as e:
        add_flash(t("flash.error.import_failed").format(error=e), "error")
    return redirect("/admin#acc-backup")


@admin_bp.get("/admin/backup/user/export")
@sysadmin_required
def admin_backup_user_export():
    from app import bootstrap, add_flash
    bootstrap()
    import io as _io
    from backup import export_user_data
    try:
        uid = int(request.args.get("uid") or 0)
    except (ValueError, TypeError):
        abort(400)
    try:
        data, fname = export_user_data(uid)
    except ValueError as e:
        add_flash(str(e), "error")
        return redirect("/admin#acc-backup")
    return send_file(
        _io.BytesIO(data),
        mimetype="application/json",
        as_attachment=True,
        download_name=fname,
    )


@admin_bp.post("/admin/backup/user/import")
@sysadmin_required
def admin_backup_user_import():
    from app import bootstrap, add_flash, _get_bot_config, _bot_service_status, _bot_service_exists, _git_last_commit_info, _service_started_at, _render_bot_section, _render_update_section, _live_app_version
    bootstrap()
    from backup import import_user_data
    f = request.files.get("user_file")
    if not f or not f.filename:
        add_flash(t("flash.error.no_file"), "error")
        return redirect("/admin#acc-backup")
    if not f.filename.lower().endswith(".json"):
        add_flash(t("flash.error.invalid_json_file"), "error")
        return redirect("/admin#acc-backup")
    target_raw = (request.form.get("target_uid") or "").strip()
    if not target_raw:
        add_flash(t("flash.error.no_target_user"), "error")
        return redirect("/admin#acc-backup")
    try:
        target_uid = int(target_raw)
    except ValueError:
        add_flash(t("flash.error.invalid_target_user"), "error")
        return redirect("/admin#acc-backup")
    try:
        s = import_user_data(f.read(), target_uid)
        _skipped_str = t("flash.success.user_imported_skipped").format(count=s["skipped"]) if s["skipped"] else ""
        add_flash(
            t("flash.success.user_imported").format(
                time_blocks=s["time_blocks"],
                absences=s["absences"],
                trips=s["business_trips"],
                schedules=s["schedules"],
                skipped=_skipped_str,
            ),
            "success",
        )
    except Exception as e:
        add_flash(t("flash.error.import_failed").format(error=e), "error")
    return redirect("/admin#acc-backup")


# ── Bot section ────────────────────────────────────────────────────────────────

def _render_bot_section() -> str:
    import html as _h
    cfg = _get_bot_config()
    tok_set = bool(cfg.get("bot_token"))
    api_set = bool(cfg.get("anthropic_api_key"))
    admin_ids = cfg.get("admin_telegram_ids") or ""

    status = _bot_service_status()
    svc_exists = _bot_service_exists()

    if status == "active":
        status_badge = f"<span style='color:var(--ok);font-weight:600;'>● {t('admin.bot_running')}</span>"
    elif status in ("inactive", "failed", "activating"):
        status_badge = f"<span style='color:var(--danger);font-weight:600;'>● {status.capitalize()}</span>"
    elif status == "not-found":
        status_badge = f"<span style='color:var(--mu);font-weight:600;'>{t('admin.bot_not_configured')}</span>"
    else:
        status_badge = f"<span style='color:var(--mu);'>● {_h.escape(status)}</span>"

    setup_btn = ""
    if not svc_exists:
        setup_btn = f"""
          <form method="post" action="/admin/bot/setup-service" style="display:inline;">
            <button class="btn btn-sm" type="submit">{t('admin.bot_setup_service_btn')}</button>
          </form>"""

    tok_hint = f"<span style='color:var(--ok);font-size:11px;'>{t('admin.set_hint')}</span>" if tok_set else f"<span style='color:var(--mu);font-size:11px;'>{t('admin.empty_hint')}</span>"
    api_hint = f"<span style='color:var(--ok);font-size:11px;'>{t('admin.set_hint')}</span>" if api_set else f"<span style='color:var(--mu);font-size:11px;'>{t('admin.empty_hint')}</span>"

    return f"""
    <div class="acc" data-tab="system" id="acc-bot">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-bot-body')">
        <span>{t('admin.acc_bot')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-bot-body">
        <div class="acc-inner">

          <div style="font-size:13px;font-weight:700;margin-bottom:10px;">{t('admin.bot_config')}</div>
          <form method="post" action="/admin/bot-config/save" style="margin-bottom:18px;">
            <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;">
              <div style="flex:1;min-width:220px;">
                <label style="font-size:12px;">{t('admin.bot_token')} {tok_hint}</label>
                <input type="password" name="bot_token" value="" placeholder="{'**' if tok_set else 'Token von @BotFather'}" autocomplete="new-password" style="font-size:13px;padding:5px 8px;width:100%;">
                <div class="small" style="color:var(--mu);margin-top:3px;">{t('admin.bot_token_hint')}</div>
              </div>
              <div style="flex:1;min-width:220px;">
                <label style="font-size:12px;">{t('admin.anthropic_api_key')} {api_hint}</label>
                <input type="password" name="anthropic_api_key" value="" placeholder="{'**' if api_set else 'sk-ant-...'}" autocomplete="new-password" style="font-size:13px;padding:5px 8px;width:100%;">
                <div class="small" style="color:var(--mu);margin-top:3px;">{t('admin.api_key_hint')}</div>
              </div>
            </div>
            <div style="margin-bottom:10px;">
              <label style="font-size:12px;">{t('admin.admin_tg_ids')}</label>
              <input type="text" name="admin_telegram_ids" value="{_h.escape(admin_ids)}" placeholder="z.B. 123456789, 987654321" style="font-size:13px;padding:5px 8px;min-width:280px;">
              <div class="small" style="color:var(--mu);margin-top:3px;">{t('admin.admin_tg_ids_hint')}</div>
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
          </form>

          <hr style="margin:12px 0;">

          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.bot_status')}</div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
            <div>{t('admin.bot_status')}: {status_badge}</div>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <form method="post" action="/admin/bot/control" style="display:inline;">
              <input type="hidden" name="action" value="start">
              <button class="btn btn-sm" type="submit">{t('admin.bot_start_btn')}</button>
            </form>
            <form method="post" action="/admin/bot/control" style="display:inline;">
              <input type="hidden" name="action" value="stop">
              <button class="btn btn-sm" type="submit">{t('admin.bot_stop_btn')}</button>
            </form>
            <form method="post" action="/admin/bot/control" style="display:inline;">
              <input type="hidden" name="action" value="restart">
              <button class="btn btn-sm" type="submit">{t('admin.bot_restart_btn')}</button>
            </form>
            {setup_btn}
          </div>

        </div>
      </div>
    </div>"""


# ── Update section ─────────────────────────────────────────────────────────────

def _live_app_version() -> str:
    try:
        import re as _re
        with open("/opt/zeiterfassung/app.py", "r", encoding="utf-8") as _f:
            for _line in _f:
                _m = _re.match(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', _line)
                if _m:
                    return _m.group(1)
    except Exception:
        pass
    return APP_VERSION


def _render_update_section() -> str:
    import sys as _sys, platform as _plat
    import html as _h
    last_commit = _h.escape(_git_last_commit_info())
    started_web = _h.escape(_service_started_at("zeiterfassung"))
    started_bot = _h.escape(_service_started_at("zeiterfassung-bot"))
    py_ver = _h.escape(_sys.version.split()[0])
    os_info = _h.escape(_plat.platform())
    live_version = _h.escape(_live_app_version())

    _check_btn_lbl = t('admin.update_check_btn')
    _checking_lbl = t('admin.update_checking')
    _up_to_date_lbl = t('admin.update_up_to_date')
    _avail_lbl = t('admin.update_available_js')
    _update_confirm = t('admin.update_confirm')
    return f"""
    <div class="acc" data-tab="system" id="acc-update">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-update-body')">
        <span>{t('admin.acc_update')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-update-body">
        <div class="acc-inner">

          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.update_current_state')}</div>
          <table style="width:auto;margin-bottom:12px;">
            <tr><td style="color:var(--mu);font-size:12px;padding-right:14px;">{t('admin.update_version')}</td><td style="font-size:13px;">{live_version}</td></tr>
            <tr><td style="color:var(--mu);font-size:12px;">{t('admin.update_last_commit')}</td><td style="font-size:12px;font-family:monospace;">{last_commit}</td></tr>
          </table>

          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px;">
            <button class="btn btn-sm" type="button" onclick="checkUpdates(this)">{_check_btn_lbl}</button>
            <span id="update-check-result" style="font-size:13px;"></span>
          </div>

          <hr style="margin:12px 0;">

          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.update_section')}</div>
          <p class="small" style="color:var(--mu);">{t('admin.update_hint')}</p>
          <form method="post" action="/admin/update/run"
                onsubmit="return confirm('{_update_confirm}');">
            <button class="btn primary btn-sm" type="submit">{t('admin.update_run_btn')}</button>
          </form>

          <hr style="margin:12px 0;">

          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.update_sys_info')}</div>
          <table style="width:auto;">
            <tr><td style="color:var(--mu);font-size:12px;padding-right:14px;">{t('admin.update_python')}</td><td style="font-size:12px;">{py_ver}</td></tr>
            <tr><td style="color:var(--mu);font-size:12px;">{t('admin.update_os')}</td><td style="font-size:12px;">{os_info}</td></tr>
            <tr><td style="color:var(--mu);font-size:12px;">{t('admin.update_web_since')}</td><td style="font-size:12px;">{started_web}</td></tr>
            <tr><td style="color:var(--mu);font-size:12px;">{t('admin.update_bot_since')}</td><td style="font-size:12px;">{started_bot}</td></tr>
          </table>

        </div>
      </div>
    </div>
    <script>
    var _UPD_CHECK_LBL = {repr(_check_btn_lbl)};
    var _UPD_CHECKING_LBL = {repr(_checking_lbl)};
    var _UPD_OK_LBL = {repr(_up_to_date_lbl)};
    var _UPD_AVAIL_LBL = {repr(_avail_lbl)};
    function checkUpdates(btn) {{
      btn.disabled = true;
      btn.textContent = _UPD_CHECKING_LBL;
      var el = document.getElementById('update-check-result');
      el.textContent = '';
      fetch('/admin/update/check')
        .then(function(r){{return r.json();}})
        .then(function(d){{
          btn.disabled = false;
          btn.textContent = _UPD_CHECK_LBL;
          if(d.error) {{el.textContent = '⚠ ' + d.error; el.style.color='var(--danger)';}}
          else if(d.count === 0) {{el.textContent = _UPD_OK_LBL; el.style.color='var(--ok)';}}
          else {{el.innerHTML = '<b style="color:var(--danger);">' + d.count + ' ' + _UPD_AVAIL_LBL + '</b>: ' + d.commits.slice(0,3).map(function(c){{return '<code>'+c+'</code>';}}).join(', ');}}
        }})
        .catch(function(){{btn.disabled=false;btn.textContent=_UPD_CHECK_LBL;el.textContent='⚠ Fehler';el.style.color='var(--danger)';}});
    }}
    </script>"""


@admin_bp.post("/admin/bot-config/save")
@sysadmin_required
def admin_bot_config_save():
    from app import bootstrap, add_flash, _get_bot_config, _save_bot_config
    bootstrap()
    tok = (request.form.get("bot_token") or "").strip()
    api = (request.form.get("anthropic_api_key") or "").strip()
    ids = (request.form.get("admin_telegram_ids") or "").strip()
    cfg = _get_bot_config()
    if not tok:
        tok = cfg.get("bot_token") or ""
    if not api:
        api = cfg.get("anthropic_api_key") or ""
    _save_bot_config(tok, api, ids)
    add_flash(t("flash.success.bot_saved"), "success")
    return redirect("/admin#acc-bot")


@admin_bp.post("/admin/bot/control")
@sysadmin_required
def admin_bot_control():
    from app import bootstrap, add_flash
    bootstrap()
    action = request.form.get("action", "").strip()
    if action not in ("start", "stop", "restart"):
        abort(400)
    import subprocess
    r = subprocess.run(
        ["systemctl", action, "zeiterfassung-bot"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0:
        add_flash(t("flash.success.bot_action").format(action=action), "success")
    else:
        add_flash(t("flash.error.general_detail").format(detail=r.stderr.strip() or r.stdout.strip()), "error")
    return redirect("/admin#acc-bot")


@admin_bp.post("/admin/bot/setup-service")
@sysadmin_required
def admin_bot_setup_service():
    from app import bootstrap, add_flash
    bootstrap()
    import subprocess
    svc = """\
[Unit]
Description=Zeiterfassung Telegram Bot
After=network.target

[Service]
WorkingDirectory=/opt/zeiterfassung
ExecStart=/opt/zeiterfassung/.venv/bin/python3 /opt/zeiterfassung/bot.py
Restart=always
RestartSec=10
Environment="ZEITERFASSUNG_DB=/opt/zeiterfassung/zeiterfassung.db"

[Install]
WantedBy=multi-user.target
"""
    try:
        with open("/etc/systemd/system/zeiterfassung-bot.service", "w") as f:
            f.write(svc)
        subprocess.run(["systemctl", "daemon-reload"], timeout=10)
        subprocess.run(["systemctl", "enable", "--now", "zeiterfassung-bot"], timeout=15)
        add_flash(t("flash.success.bot_setup"), "success")
    except Exception as e:
        add_flash(t("flash.error.setup_failed").format(error=e), "error")
    return redirect("/admin#acc-bot")


@admin_bp.get("/admin/update/check")
@sysadmin_required
def admin_update_check():
    from app import bootstrap, _git_pending_commits
    bootstrap()
    commits = _git_pending_commits()
    if commits is None:
        return jsonify({"error": t("admin.update_fetch_failed")})
    if isinstance(commits, str) and commits.startswith("ERROR:"):
        return jsonify({"error": commits[6:]})
    return jsonify({"count": len(commits), "commits": commits[:5]})


@admin_bp.post("/admin/update/run")
@sysadmin_required
def admin_update_run():
    from app import bootstrap, add_flash, _run_update
    bootstrap()
    import threading
    success, lines = _run_update()
    output = "\n".join(lines)
    if success:
        add_flash(t("flash.success.update_done").format(output=output), "success")
    else:
        add_flash(t("flash.error.update_failed").format(output=output), "error")

    def _restart():
        import time
        time.sleep(1.5)
        os.system("systemctl restart zeiterfassung")
        os.system("systemctl restart zeiterfassung-bot 2>/dev/null || true")

    if success:
        threading.Thread(target=_restart, daemon=True).start()

    return redirect("/admin#acc-update")


@admin_bp.get("/admin/mail-settings")
@sysadmin_required
def admin_mail_settings():
    from app import bootstrap, flash_html, layout, _get_mail_config
    bootstrap()
    u = current_user()
    cfg = _get_mail_config()
    pw_set = bool(cfg.get("mail_password"))

    body = f"""
    {flash_html()}
    <div class="card">
      <h3 style="margin-top:0;">Mailserver-Einstellungen</h3>
      <p class="small">Einstellungen werden in der Datenbank gespeichert und überschreiben Umgebungsvariablen.</p>
      <form method="post" action="/admin/mail-settings" autocomplete="off">
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
          <div style="flex:2;min-width:200px;">
            <label>Mailserver (SMTP)</label>
            <input type="text" name="mail_server" value="{cfg.get('mail_server','')}" placeholder="mail.beispiel.de" required>
          </div>
          <div style="flex:0 0 100px;">
            <label>Port</label>
            <input type="number" name="mail_port" value="{cfg.get('mail_port','587')}" min="1" max="65535" required style="width:90px;">
          </div>
        </div>
        <div style="margin-bottom:10px;">
          <label>Benutzername (Login)</label>
          <input type="text" name="mail_username" value="{cfg.get('mail_username','')}" placeholder="user@beispiel.de" required autocomplete="off" data-lpignore="true">
        </div>
        <div style="margin-bottom:10px;">
          <label>Passwort {"<span class='small' style='color:var(--mu);font-weight:400;'>(leer lassen = unverändert)</span>" if pw_set else ""}</label>
          <input type="password" name="mail_password" value="" placeholder="{'••••••••' if pw_set else 'Passwort eingeben'}" autocomplete="new-password" data-lpignore="true">
        </div>
        <div style="margin-bottom:14px;">
          <label>Absender (Anzeigename &lt;adresse@domain&gt;)</label>
          <input type="text" name="mail_from" value="{cfg.get('mail_from','')}" placeholder="Zeiterfassung &lt;noreply@beispiel.de&gt;">
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn primary" type="submit">Speichern</button>
        </div>
      </form>
    </div>

    <div class="card">
      <h3 style="margin-top:0;">Verbindung testen</h3>
      <p class="small">Sendet eine Test-E-Mail an deine Admin-Adresse (<b>{u.get('email') or u.get('username')}</b>).</p>
      <form method="post" action="/admin/mail-settings/test">
        <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;">
          <div>
            <label>Test-Empfänger</label>
            <input type="email" name="test_recipient" value="{u.get('email') or ''}" placeholder="admin@beispiel.de" required>
          </div>
          <button class="btn" type="submit">Test-Mail senden</button>
        </div>
      </form>
    </div>

    <div class="card">
      <h3 style="margin-top:0;">Aktuelle Konfiguration</h3>
      <table>
        <tr><th>Key</th><th>Wert</th></tr>
        <tr><td>Mailserver</td><td>{cfg.get('mail_server') or '<span style="color:var(--mu);">–</span>'}</td></tr>
        <tr><td>Port</td><td>{cfg.get('mail_port') or '587'}</td></tr>
        <tr><td>Benutzername</td><td>{cfg.get('mail_username') or '<span style="color:var(--mu);">–</span>'}</td></tr>
        <tr><td>Passwort</td><td>{'<span style="color:var(--ok);">gesetzt</span>' if pw_set else '<span style="color:var(--danger);">nicht gesetzt</span>'}</td></tr>
        <tr><td>Absender</td><td>{cfg.get('mail_from') or '<span style="color:var(--mu);">–</span>'}</td></tr>
      </table>
    </div>
    """
    return render_template_string(layout(f"{t('admin.title')}: {t('admin.mail_settings')}", body, u, APP_VERSION))


@admin_bp.post("/admin/mail-settings")
@sysadmin_required
def admin_mail_settings_save():
    from app import bootstrap, add_flash, _get_mail_config, _save_mail_config
    bootstrap()
    mail_server   = (request.form.get("mail_server") or "").strip()
    mail_port     = (request.form.get("mail_port") or "587").strip()
    mail_username = (request.form.get("mail_username") or "").strip()
    mail_password = (request.form.get("mail_password") or "").strip()
    mail_from     = (request.form.get("mail_from") or "").strip()

    if not mail_server or not mail_username:
        add_flash(t("flash.error.smtp_required"), "error")
        return redirect("/admin/mail-settings")

    # If no new password entered, persist the currently-effective password to DB
    # (covers env-var passwords that were never in the DB and would be missing from backups)
    if not mail_password:
        mail_password = _get_mail_config().get("mail_password") or ""
    update_pw = bool(mail_password)
    _save_mail_config(mail_server, mail_port, mail_username, mail_password, mail_from, update_pw)
    add_flash(t("admin.smtp_saved"), "success")
    return redirect("/admin#acc-mail")


@admin_bp.post("/admin/mail-settings/test")
@sysadmin_required
def admin_mail_settings_test():
    from app import bootstrap, add_flash, _date_input, _fmt_date_de, _fmt_minutes_signed, _fmt_vac_days, _send_mail, _build_csv_bytes, _region_picker, _vacation_calc, _vacation_used_days, _count_absence_workdays, _get_visible_user_ids, _calc_balance_end_at, _feature_enabled, _get_app_config, _render_admin_overtime_section, _render_admin_absences_section, _render_overtime_defaults_section, _render_features_section, _render_school_holidays_section, _render_admin_teams_inline, _render_admin_staffing_inline
    bootstrap()
    recipient = (request.form.get("test_recipient") or "").strip()
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', recipient):
        add_flash(t("flash.error.invalid_email"), "error")
        return redirect("/admin/mail-settings")
    try:
        _send_mail(
            to=recipient,
            subject="Zeiterfassung – Test-Mail",
            body_text="Dies ist eine Test-Mail von Zeiterfassung.\nWenn du diese Mail erhältst, funktioniert die SMTP-Konfiguration korrekt.\n",
            attachment_name="test.csv",
            attachment_bytes=_build_csv_bytes(["test"], [["OK"]]),
        )
        add_flash(t("flash.success.smtp_test").format(recipient=recipient), "success")
    except Exception as exc:
        add_flash(t("flash.error.smtp_fail").format(error=exc), "error")
    return redirect("/admin#acc-mail")


def _render_admin_absences_section(u=None) -> str:
    today = datetime.date.today()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()

    # --- year for vacation status ---
    try:
        abs_year = int(request.args.get("abs_year") or today.year)
    except (ValueError, TypeError):
        abs_year = today.year
    year_start = f"{abs_year}-01-01"
    year_end = f"{abs_year}-12-31"

    available_years = list(range(max(today.year - 3, 2020), today.year + 2))
    year_opts = "".join(
        f'<option value="{y}" {"selected" if y == abs_year else ""}>{y}</option>'
        for y in reversed(available_years)
    )

    db = connect()
    active_users = db.execute(
        "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY display_name, username"
    ).fetchall()
    db.close()
    if u and not is_sysadmin(u):
        _vis = _get_visible_user_ids(u)
        if _vis is not None:
            _vis_set = set(_vis)
            active_users = [r for r in active_users if r["id"] in _vis_set]

    # --- Section 1: vacation status all users ---
    vac_rows = ""
    for u_row in active_users:
        uid = u_row["id"]
        name = _html.escape(u_row["display_name"] or u_row["username"])
        vc = _vacation_calc(uid, abs_year)
        entitlement = vc["entitlement"]
        eff_carry = vc["effective_carryover"]
        total = entitlement + eff_carry
        used_total = vc["used_total"]
        genommen = _vacation_used_days(uid, abs_year, date_to_limit=yesterday)
        geplant = max(0.0, used_total - genommen)
        remaining = vc["remaining_total"]
        if remaining > 0:
            rem_col = "var(--ok)"
        elif remaining == 0:
            rem_col = "var(--mu)"
        else:
            rem_col = "var(--danger)"
        _vac_search_key = _html.escape((u_row["username"] + " " + (u_row["display_name"] or "")).lower())
        vac_rows += (
            f"<tr data-search='{_vac_search_key}'><td>{name}</td>"
            f"<td style='text-align:center;'>{_fmt_vac_days(entitlement)}</td>"
            f"<td style='text-align:center;'>{_fmt_vac_days(eff_carry)}</td>"
            f"<td style='text-align:center;font-weight:600;'>{_fmt_vac_days(total)}</td>"
            f"<td style='text-align:center;'>{_fmt_vac_days(genommen)}</td>"
            f"<td style='text-align:center;'>{_fmt_vac_days(geplant)}</td>"
            f"<td style='text-align:center;font-weight:600;color:{rem_col};'>{_fmt_vac_days(remaining)}</td>"
            f"</tr>"
        )

    # --- Section 2: per-user absences ---
    abs_from = (request.args.get("abs_from") or year_start).strip()
    abs_to = (request.args.get("abs_to") or year_end).strip()
    sel_uid_str = (request.args.get("abs_uid") or "").strip()
    sel_uid = int(sel_uid_str) if sel_uid_str.isdigit() else (active_users[0]["id"] if active_users else None)

    user_opts = "".join(
        f'<option value="{u_row["id"]}" {"selected" if u_row["id"] == sel_uid else ""}>'
        f'{_html.escape(u_row["display_name"] or u_row["username"])}</option>'
        for u_row in active_users
    )

    detail_rows = ""
    if sel_uid:
        db = connect()
        abs_list = db.execute(
            """SELECT a.date_from, a.date_to, a.is_half_day, a.comment, t.name AS type_name
               FROM absences a JOIN absence_types t ON a.type_id = t.id
               WHERE a.user_id = ? AND a.date_to >= ? AND a.date_from <= ?
               ORDER BY a.date_from""",
            (sel_uid, abs_from, abs_to),
        ).fetchall()
        db.close()
        type_sums: dict[str, float] = {}
        for row in abs_list:
            df = str(row["date_from"])[:10]
            dt = str(row["date_to"])[:10]
            half = int(row["is_half_day"] or 0)
            cmt = (row["comment"] or "").strip()
            tname = row["type_name"]
            disp_type = cmt if (tname == "Sonstige" and cmt) else tname
            days = _count_absence_workdays(sel_uid, df, dt, half)
            type_sums[disp_type] = type_sums.get(disp_type, 0.0) + days
            detail_rows += (
                f"<tr>"
                f"<td style='font-size:12px;'>{_fmt_date_de(df)}</td>"
                f"<td style='font-size:12px;'>{_fmt_date_de(dt)}</td>"
                f"<td style='font-size:12px;'>{_html.escape(disp_type)}</td>"
                f"<td style='text-align:center;font-size:12px;'>{_fmt_vac_days(days)}</td>"
                f"<td style='font-size:12px;color:var(--mu);'>{_html.escape(cmt) if tname != 'Sonstige' else ''}</td>"
                f"</tr>"
            )
        if type_sums:
            sum_parts = " &nbsp;·&nbsp; ".join(
                f"<b>{_html.escape(tk)}:</b> {_fmt_vac_days(tv)}"
                for tk, tv in sorted(type_sums.items())
            )
            detail_rows += (
                f"<tr><td colspan='5' style='font-size:12px;font-weight:600;"
                f"border-top:2px solid var(--bd);padding-top:8px;'>Summe: {sum_parts}</td></tr>"
            )
    if not detail_rows:
        detail_rows = f"<tr><td colspan='5' style='color:var(--mu);font-size:13px;'>{t('admin.no_data')}</td></tr>"

    # --- Section 3: compact overview all users ---
    db = connect()
    all_abs = db.execute(
        """SELECT a.user_id, a.date_from, a.date_to, a.is_half_day, a.comment, t.name AS type_name
           FROM absences a JOIN absence_types t ON a.type_id = t.id
           WHERE a.date_to >= ? AND a.date_from <= ?""",
        (abs_from, abs_to),
    ).fetchall()
    db.close()

    user_type_sums: dict[int, dict[str, float]] = {
        u_row["id"]: {"Urlaub": 0.0, "Krank": 0.0, "Flextag": 0.0, "Verdi": 0.0, "Sonstige": 0.0}
        for u_row in active_users
    }
    for ab in all_abs:
        uid_ab = ab["user_id"]
        if uid_ab not in user_type_sums:
            continue
        df = str(ab["date_from"])[:10]
        dt = str(ab["date_to"])[:10]
        half = int(ab["is_half_day"] or 0)
        cmt = (ab["comment"] or "").strip().lower()
        tname = ab["type_name"]
        days = _count_absence_workdays(uid_ab, df, dt, half)
        if tname == "Urlaub":
            user_type_sums[uid_ab]["Urlaub"] += days
        elif tname == "Krank":
            user_type_sums[uid_ab]["Krank"] += days
        elif tname == "Flextag" or (tname == "Sonstige" and cmt == "flextag"):
            user_type_sums[uid_ab]["Flextag"] += days
        elif tname == "Verdi" or (tname == "Sonstige" and cmt == "verdi"):
            user_type_sums[uid_ab]["Verdi"] += days
        else:
            user_type_sums[uid_ab]["Sonstige"] += days

    overview_rows = ""
    for u_row in active_users:
        uid_ov = u_row["id"]
        s = user_type_sums.get(uid_ov, {})
        cells = "".join(
            f"<td style='text-align:center;font-size:12px;'>"
            f"{'–' if s.get(k, 0.0) == 0 else _fmt_vac_days(s[k])}</td>"
            for k in ("Urlaub", "Krank", "Flextag", "Verdi", "Sonstige")
        )
        overview_rows += f"<tr><td style='font-size:12px;'>{_html.escape(u_row['display_name'] or u_row['username'])}</td>{cells}</tr>"

    export_url = f"/admin/absences/export?uid={sel_uid or ''}&from={abs_from}&to={abs_to}"

    _no_users_row = f"<tr><td colspan='7' style='color:var(--mu);'>{t('admin.no_users')}</td></tr>"
    _no_data_row = f"<tr><td colspan='6' style='color:var(--mu);'>{t('admin.no_data')}</td></tr>"
    return f"""
    <div class="acc" data-tab="reporting" id="acc-absoverview">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-absoverview-body')">
        <span>{t('admin.acc_absences')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-absoverview-body">
        <div class="acc-inner">

          <!-- Urlaubsstatus alle User -->
          <form method="get" action="/admin" onsubmit="sessionStorage.setItem('openAcc','acc-absoverview')" style="display:flex;gap:8px;align-items:flex-end;margin-bottom:12px;flex-wrap:wrap;">
            <input type="hidden" name="abs_uid" value="{_html.escape(sel_uid_str)}">
            <input type="hidden" name="abs_from" value="{_html.escape(abs_from)}">
            <input type="hidden" name="abs_to" value="{_html.escape(abs_to)}">
            <div><label style="font-size:12px;">{t('admin.vac_status_year')}</label><br>
              <select name="abs_year" style="font-size:13px;padding:4px 8px;">{year_opts}</select>
            </div>
            <button class="btn btn-sm" type="submit">{t('periods.show_btn')}</button>
          </form>
          <div style="margin-bottom:8px;">
            <input type="text" id="vac-search-input"
                   placeholder="{t('admin.search_users_placeholder')}"
                   oninput="filterVacTable(this.value)"
                   style="width:100%;max-width:320px;padding:7px 10px;border-radius:6px;font-size:13px;">
          </div>
          <div class="table-scroll" style="margin-bottom:16px;">
            <table>
              <thead><tr>
                <th>{t('common.name')}</th>
                <th style="text-align:center;">{t('admin.vac_entitlement')}</th>
                <th style="text-align:center;">{t('admin.vac_carryover')}</th>
                <th style="text-align:center;">{t('admin.vac_total')}</th>
                <th style="text-align:center;">{t('admin.vac_taken')}</th>
                <th style="text-align:center;">{t('admin.vac_planned')}</th>
                <th style="text-align:center;">{t('admin.vac_available')}</th>
              </tr></thead>
              <tbody>{vac_rows or _no_users_row}</tbody>
            </table>
          </div>

          <hr style="margin:14px 0;">

          <!-- Abwesenheiten je User -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.abs_per_user')}</div>
          <form method="get" action="/admin" onsubmit="sessionStorage.setItem('openAcc','acc-absoverview')" style="display:flex;gap:8px;align-items:flex-end;margin-bottom:10px;flex-wrap:wrap;">
            <input type="hidden" name="abs_year" value="{abs_year}">
            <div><label style="font-size:12px;">{t('admin.users_title')}</label><br>
              <select name="abs_uid" style="font-size:13px;padding:4px 8px;">{user_opts}</select>
            </div>
            <div><label style="font-size:12px;">{t('absences.from')}</label><br>
              {_date_input("abs_from", abs_from)}
            </div>
            <div><label style="font-size:12px;">{t('absences.to')}</label><br>
              {_date_input("abs_to", abs_to)}
            </div>
            <div style="padding-bottom:2px;display:flex;gap:6px;align-items:flex-end;">
              <button class="btn btn-sm" type="submit">{t('periods.show_btn')}</button>
              <a class="btn btn-sm" href="{_html.escape(export_url)}">CSV ↓</a>
            </div>
          </form>
          <div class="table-scroll" style="margin-bottom:16px;">
            <table>
              <thead><tr><th>{t('absences.from')}</th><th>{t('absences.to')}</th><th>{t('absences.type')}</th><th style="text-align:center;">{t('common.days')}</th><th>{t('absences.comment')}</th></tr></thead>
              <tbody>{detail_rows}</tbody>
            </table>
          </div>

          <hr style="margin:14px 0;">

          <!-- Kompakte Übersicht alle User -->
          <div style="font-size:13px;font-weight:700;margin-bottom:6px;">
            {t('admin.abs_all_users')}
            <span style="font-size:11px;font-weight:400;color:var(--mu);">{_fmt_date_de(abs_from)} – {_fmt_date_de(abs_to)}</span>
          </div>
          <div class="table-scroll">
            <table>
              <thead><tr>
                <th>{t('common.name')}</th>
                <th style="text-align:center;">Urlaub</th>
                <th style="text-align:center;">Krank</th>
                <th style="text-align:center;">Flextag</th>
                <th style="text-align:center;">Verdi</th>
                <th style="text-align:center;">Sonstige</th>
              </tr></thead>
              <tbody>{overview_rows or _no_data_row}</tbody>
            </table>
          </div>

        </div>
      </div>
    </div>"""


def _render_admin_teams(teams, all_users, team_members) -> str:
    _WD_LABELS = [t('wd.mon'), t('wd.tue'), t('wd.wed'), t('wd.thu'), t('wd.fri'), t('wd.sat'), t('wd.sun')]
    team_rows = ""
    for tm in teams:
        tid = tm["id"]
        color = _html.escape(tm["color"] or "#4a9eff")
        name  = _html.escape(tm["name"])
        desc  = _html.escape(tm["description"] or "")
        cnt   = tm["member_count"]
        member_ids = team_members.get(tid, [])
        checkboxes = "".join(
            f'<label style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
            f'<input type="checkbox" name="user_ids" value="{u["id"]}"'
            f'{" checked" if u["id"] in member_ids else ""}>'
            f'{_html.escape(u["display_name"] or u["username"])}</label>'
            for u in all_users
        )
        team_rows += f"""
        <div class="acc" style="margin-bottom:8px;">
          <button class="acc-hdr" type="button"
                  onclick="accToggle('tm-body-{tid}')"
                  style="background:none;border:1px solid var(--br);border-radius:8px;">
            <span style="display:flex;align-items:center;gap:8px;">
              <span style="width:14px;height:14px;border-radius:50%;
                           background:{color};display:inline-block;flex-shrink:0;"></span>
              <strong>{name}</strong>
              <span style="color:var(--mu);font-size:12px;">{cnt} {t('admin.team_members')}</span>
              {('<span style="color:var(--mu);font-size:12px;">' + desc + '</span>') if desc else ''}
            </span>
            <span class="acc-arr">▼</span>
          </button>
          <div class="acc-body" id="tm-body-{tid}" style="display:none;">
            <div class="acc-inner">
              <form method="post" action="/admin/teams">
                <input type="hidden" name="action" value="members">
                <input type="hidden" name="team_id" value="{tid}">
                <p style="font-size:13px;font-weight:600;margin-bottom:8px;">{t('admin.team_members')}</p>
                {checkboxes}
                <div style="margin-top:12px;">
                  <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
                </div>
              </form>
              <div style="margin-top:8px;">
                <form method="post" action="/admin/teams" style="margin:0;"
                      onsubmit="return confirm('{t('confirm.delete')}')">
                  <input type="hidden" name="action" value="delete">
                  <input type="hidden" name="team_id" value="{tid}">
                  <button class="btn btn-sm" type="submit"
                          style="color:#dc2626;">{t('btn.delete')}</button>
                </form>
              </div>
              <hr style="border:none;border-top:1px solid var(--br);margin:12px 0;">
              <p style="font-size:13px;font-weight:600;margin-bottom:8px;">{t('admin.edit_team')}</p>
              <form method="post" action="/admin/teams">
                <input type="hidden" name="action" value="edit">
                <input type="hidden" name="team_id" value="{tid}">
                <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;">
                  <div>
                    <label style="font-size:12px;">{t('admin.team_name')}</label>
                    <input type="text" name="name" value="{name}"
                           required maxlength="60"
                           style="display:block;margin-top:4px;min-width:160px;">
                  </div>
                  <div>
                    <label style="font-size:12px;">{t('admin.team_color')}</label>
                    <input type="color" name="color" value="{color}"
                           style="display:block;margin-top:4px;width:48px;height:34px;padding:2px;">
                  </div>
                  <div style="flex:1;min-width:140px;">
                    <label style="font-size:12px;">{t('admin.team_description')}</label>
                    <input type="text" name="description" value="{desc}"
                           maxlength="120"
                           style="display:block;margin-top:4px;width:100%;">
                  </div>
                  <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
                </div>
              </form>
            </div>
          </div>
        </div>"""

    return f"""
    <div style="max-width:700px;margin:1.5rem auto;">
      <div style="margin-bottom:1rem;">
        <a href="/admin" class="btn btn-sm">← {t('nav.admin')}</a>
      </div>
      <h2 style="margin-bottom:1.5rem;">{t('admin.teams')}</h2>

      <!-- Neues Team -->
      <div style="background:var(--ca);border:1px solid var(--br);border-radius:10px;
                  padding:16px;margin-bottom:1.5rem;">
        <h3 style="margin:0 0 12px;">{t('admin.add_team')}</h3>
        <form method="post" action="/admin/teams">
          <input type="hidden" name="action" value="create">
          <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;">
            <div>
              <label style="font-size:12px;">{t('admin.team_name')} *</label>
              <input type="text" name="name" required maxlength="60"
                     style="display:block;margin-top:4px;min-width:180px;">
            </div>
            <div>
              <label style="font-size:12px;">{t('admin.team_color')}</label>
              <input type="color" name="color" value="#4a9eff"
                     style="display:block;margin-top:4px;width:48px;height:34px;padding:2px;">
            </div>
            <div style="flex:1;min-width:160px;">
              <label style="font-size:12px;">Beschreibung</label>
              <input type="text" name="description" maxlength="120"
                     style="display:block;margin-top:4px;width:100%;">
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
          </div>
        </form>
      </div>

      <!-- Teams Liste -->
      {team_rows if team_rows else f'<p style="color:var(--mu);">{t("admin.no_teams")}</p>'}

    </div>
    <script>
    function accToggle(id) {{
      var el = document.getElementById(id);
      if (!el) return;
      var isHidden = el.style.display === 'none' || el.style.display === '';
      el.style.display = isHidden ? 'block' : 'none';
      var btn = el.previousElementSibling;
      if (btn) {{
        var arr = btn.querySelector('.acc-arr');
        if (arr) arr.textContent = isHidden ? '▲' : '▼';
      }}
    }}
    </script>"""


def _render_admin_teams_inline(teams, all_users, team_members) -> str:
    team_rows = ""
    for tm in teams:
        tid = tm["id"]
        color = _html.escape(tm["color"] or "#4a9eff")
        name  = _html.escape(tm["name"])
        desc  = _html.escape(tm["description"] or "")
        cnt   = tm["member_count"]
        cur_region = tm["holiday_region"] or "" if "holiday_region" in tm.keys() else ""
        member_ids = team_members.get(tid, [])
        checkboxes = "".join(
            f'<label style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">'
            f'<input type="checkbox" name="user_ids" value="{u["id"]}"'
            f'{" checked" if u["id"] in member_ids else ""}>'
            f'{_html.escape(u["display_name"] or u["username"])}</label>'
            for u in all_users
        )
        team_rows += f"""
        <div class="acc" style="margin-bottom:8px;">
          <button class="acc-hdr" type="button"
                  onclick="accToggle('tm-body-{tid}')"
                  style="background:none;border:1px solid var(--br);border-radius:8px;">
            <span style="display:flex;align-items:center;gap:8px;">
              <span style="width:14px;height:14px;border-radius:50%;
                           background:{color};display:inline-block;flex-shrink:0;"></span>
              <strong>{name}</strong>
              <span style="color:var(--mu);font-size:12px;">{cnt} {t('admin.team_members')}</span>
              {('<span style="color:var(--mu);font-size:12px;">' + desc + '</span>') if desc else ''}
            </span>
            <span class="acc-arr">▼</span>
          </button>
          <div class="acc-body" id="tm-body-{tid}">
            <div class="acc-inner">
              <form method="post" action="/admin/teams">
                <input type="hidden" name="action" value="members">
                <input type="hidden" name="team_id" value="{tid}">
                <p style="font-size:13px;font-weight:600;margin-bottom:8px;">{t('admin.team_members')}</p>
                {checkboxes}
                <div style="margin-top:12px;">
                  <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
                </div>
              </form>
              <div style="margin-top:8px;">
                <form method="post" action="/admin/teams" style="margin:0;"
                      onsubmit="return confirm('{t('confirm.delete')}')">
                  <input type="hidden" name="action" value="delete">
                  <input type="hidden" name="team_id" value="{tid}">
                  <button class="btn btn-sm" type="submit"
                          style="color:#dc2626;">{t('btn.delete')}</button>
                </form>
              </div>
              <hr style="border:none;border-top:1px solid var(--br);margin:12px 0;">
              <p style="font-size:13px;font-weight:600;margin-bottom:8px;">{t('admin.edit_team')}</p>
              <form method="post" action="/admin/teams">
                <input type="hidden" name="action" value="edit">
                <input type="hidden" name="team_id" value="{tid}">
                <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;">
                  <div>
                    <label style="font-size:12px;">{t('admin.team_name')}</label>
                    <input type="text" name="name" value="{name}"
                           required maxlength="60"
                           style="display:block;margin-top:4px;min-width:160px;">
                  </div>
                  <div>
                    <label style="font-size:12px;">{t('admin.team_color')}</label>
                    <input type="color" name="color" value="{color}"
                           style="display:block;margin-top:4px;width:48px;height:34px;padding:2px;">
                  </div>
                  <div style="flex:1;min-width:140px;">
                    <label style="font-size:12px;">{t('admin.team_description')}</label>
                    <input type="text" name="description" value="{desc}"
                           maxlength="120"
                           style="display:block;margin-top:4px;width:100%;">
                  </div>
                  <div>
                    <label style="font-size:12px;">{t('admin.team_region')}</label>
                    <div style="margin-top:4px;">{_region_picker(f'team_hr_{tid}', cur_region, include_default=True)}</div>
                    <input type="hidden" name="holiday_region" id="team_hr_{tid}_val">
                  </div>
                  <button class="btn primary btn-sm" type="submit"
                          onclick="document.getElementById('team_hr_{tid}_val').value=document.getElementById('team_hr_{tid}_r').value">{t('btn.save')}</button>
                </div>
              </form>
            </div>
          </div>
        </div>"""

    return f"""
      <!-- Neues Team -->
      <div style="background:var(--ca);border:1px solid var(--br);border-radius:10px;
                  padding:16px;margin-bottom:1.5rem;">
        <h3 style="margin:0 0 12px;">{t('admin.add_team')}</h3>
        <form method="post" action="/admin/teams">
          <input type="hidden" name="action" value="create">
          <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;">
            <div>
              <label style="font-size:12px;">{t('admin.team_name')} *</label>
              <input type="text" name="name" required maxlength="60"
                     style="display:block;margin-top:4px;min-width:180px;">
            </div>
            <div>
              <label style="font-size:12px;">{t('admin.team_color')}</label>
              <input type="color" name="color" value="#4a9eff"
                     style="display:block;margin-top:4px;width:48px;height:34px;padding:2px;">
            </div>
            <div style="flex:1;min-width:160px;">
              <label style="font-size:12px;">{t('admin.team_description')}</label>
              <input type="text" name="description" maxlength="120"
                     style="display:block;margin-top:4px;width:100%;">
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
          </div>
        </form>
      </div>
      <!-- Teams Liste -->
      {team_rows if team_rows else f'<p style="color:var(--mu);">{t("admin.no_teams")}</p>'}"""


def _render_admin_staffing_inline(teams, plans, slots, all_assignments, u) -> str:
    assigned = {}
    assigned_lead = {}
    for a in all_assignments:
        assigned.setdefault(a["slot_id"], set()).add(a["user_id"])
        if int(a["is_lead"] or 0):
            assigned_lead.setdefault(a["slot_id"], set()).add(a["user_id"])

    slots_by_plan = {}
    for s in slots:
        slots_by_plan.setdefault(s["plan_id"], []).append(s)

    _WD_MAP = {0: t('wd.mon'), 1: t('wd.tue'), 2: t('wd.wed'),
               3: t('wd.thu'), 4: t('wd.fri'), 5: t('wd.sat'), 6: t('wd.sun')}
    _STYPE = {"vm": t('staffing.slot_vm'), "nm": t('staffing.slot_nm'),
              "special": t('staffing.slot_special')}

    def _wd_label(slot):
        if slot["slot_type"] == "special":
            wd = _WD_MAP.get(int(slot["special_weekday"] or 0), "")
            weeks = slot["nth_week"] or ""
            return f"{wd} ({weeks}. Wo.)"
        days = [_WD_MAP.get(int(x), "") for x in str(slot["weekdays"]).split(",")]
        return ", ".join(days)

    plan_html = ""
    plans_by_team = {}
    for p in plans:
        plans_by_team.setdefault(p["team_id"], []).append(p)

    for tm in teams:
        tid = tm["id"]
        team_plans = plans_by_team.get(tid, [])
        team_color = _html.escape(tm["color"] or "#4a9eff")

        db_tmp = connect()
        team_user_rows = db_tmp.execute(
            "SELECT u.id, u.username, u.display_name FROM users u "
            "JOIN user_teams ut ON ut.user_id=u.id "
            "WHERE ut.team_id=? AND u.is_active=1 ORDER BY u.display_name",
            (tid,)
        ).fetchall()
        db_tmp.close()

        plans_html = ""
        for p in team_plans:
            pid = p["id"]
            pname = _html.escape(p["name"])
            plan_slots = slots_by_plan.get(pid, [])

            slots_html = ""
            for s in plan_slots:
                sid = s["id"]
                slabel = _html.escape(s["label"])
                stype_label = _STYPE.get(s["slot_type"], s["slot_type"])
                wd_str = _wd_label(s)
                assigned_ids = assigned.get(sid, set())

                available_cards   = ""
                assigned_cards    = ""
                assigned_lead_ids = assigned_lead.get(sid, set())
                for tu in team_user_rows:
                    uname = _html.escape(tu["display_name"] or tu["username"])
                    if tu["id"] in assigned_ids:
                        is_u_lead  = tu["id"] in assigned_lead_ids
                        lead_icon  = "👑" if is_u_lead else "○"
                        lead_style = "color:#eab308;" if is_u_lead else "color:var(--mu);"
                        card = (
                            f'<div class="user-card" draggable="true" data-user-id="{tu["id"]}" '
                            f'data-is-lead="{1 if is_u_lead else 0}" ondragstart="drag(event)">'
                            f'<span class="user-dot" style="background:{team_color}"></span>'
                            f'<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;'
                            f'white-space:nowrap;">{uname}</span>'
                            f'<button type="button" onclick="toggleLead(this)" '
                            f'style="border:none;background:none;cursor:pointer;font-size:13px;'
                            f'padding:0 2px;{lead_style}flex-shrink:0;" '
                            f'title="{t("staffing.is_lead")}">{lead_icon}</button></div>'
                        )
                        assigned_cards += card
                    else:
                        card = (
                            f'<div class="user-card" draggable="true" data-user-id="{tu["id"]}" '
                            f'ondragstart="drag(event)">'
                            f'<span class="user-dot" style="background:{team_color}"></span>'
                            f'{uname}</div>'
                        )
                        available_cards += card

                no_members = f'<p style="font-size:12px;color:var(--mu);">{t("admin.no_team_members")}</p>' if not team_user_rows else ""

                _srole       = s["slot_role"] or "staff"
                _plan_lead_label2 = (p["lead_label"] if p["lead_label"] else "Leiter") if "lead_label" in p.keys() else "Leiter"
                _srole_label = _html.escape(_plan_lead_label2) if _srole == "lead" else t("staffing.role_staff")
                _srole_bg    = "#eab308" if _srole == "lead" else "var(--ca)"
                _srole_color = "#000"    if _srole == "lead" else "var(--tx)"
                _s_wd_checks2 = "".join(
                    f'<label style="font-size:12px;display:flex;align-items:center;gap:3px;">'
                    f'<input type="checkbox" name="wd_{i}" value="{i}"'
                    f'{" checked" if s["weekdays"] and str(i) in str(s["weekdays"]).split(",") else ""}>'
                    f' {_WD_MAP[i]}</label>'
                    for i in range(7)
                )
                _s_nth_checks2 = "".join(
                    f'<label style="font-size:12px;display:flex;align-items:center;gap:3px;">'
                    f'<input type="checkbox" name="nth_w_{i}" value="{i}"'
                    f'{" checked" if s["nth_week"] and str(i) in str(s["nth_week"]).split(",") else ""}>'
                    f' {i}.</label>'
                    for i in range(1, 6)
                )
                _s_spwd_opts2 = "".join(
                    f'<option value="{i}" {"selected" if s["special_weekday"] is not None and int(s["special_weekday"])==i else ""}>{_WD_MAP[i]}</option>'
                    for i in range(7)
                )
                slots_html += f"""
                <div class="slot-card" data-slot-id="{sid}">
                  <div class="slot-header">
                    <span class="slot-label"><strong>{slabel}</strong></span>
                    <span class="slot-type-badge" style="font-size:11px;background:var(--ca);
                          border-radius:4px;padding:2px 6px;">{stype_label}</span>
                    <span style="font-size:11px;background:{_srole_bg};color:{_srole_color};
                          border-radius:4px;padding:2px 6px;">{_srole_label}</span>
                    <span class="slot-days" style="font-size:12px;color:var(--mu);">{wd_str}</span>
                    {f'<span style="font-size:12px;color:var(--ac);">{s["time_from"]}–{s["time_to"]}</span>' if s["time_from"] and s["time_to"] else ""}
                    <span class="slot-min" style="font-size:12px;color:var(--mu);">Min: {s["min_staff"]}</span>
                    {f'<span style="font-size:12px;color:#eab308;">👑≥{s["min_lead"]}</span>' if (s["min_lead"] or 0) > 0 else ""}
                    <button class="btn btn-sm" style="margin-left:auto;padding:2px 8px;"
                            onclick="toggleSlotEdit({sid})">✏</button>
                    <button class="btn btn-sm" style="color:#dc2626;padding:2px 8px;"
                            onclick="deleteSlot({sid})">×</button>
                  </div>
                  <div id="slot-edit-{sid}" style="display:none;margin-bottom:12px;padding:12px;background:var(--ca);border-radius:8px;border:1px solid var(--bd);">
                    <form method="post" action="/admin/staffing">
                      <input type="hidden" name="action" value="edit_slot">
                      <input type="hidden" name="slot_id" value="{sid}">
                      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
                        <div>
                          <label style="font-size:12px;">{t('staffing.slot_label')} *</label>
                          <input type="text" name="label" required maxlength="60"
                                 value="{_html.escape(s['label'])}"
                                 style="display:block;margin-top:4px;min-width:120px;">
                        </div>
                        <div>
                          <label style="font-size:12px;">{t('staffing.slot_type')}</label>
                          <select name="slot_type" style="display:block;margin-top:4px;"
                                  onchange="toggleSlotType(this,'edit-{sid}')">
                            <option value="vm" {"selected" if s["slot_type"]=="vm" else ""}>{t('staffing.slot_vm')}</option>
                            <option value="nm" {"selected" if s["slot_type"]=="nm" else ""}>{t('staffing.slot_nm')}</option>
                            <option value="special" {"selected" if s["slot_type"]=="special" else ""}>{t('staffing.slot_special')}</option>
                          </select>
                        </div>
                        <div>
                          <label style="font-size:12px;">{t('staffing.min_staff')}</label>
                          <input type="number" name="min_staff" value="{s['min_staff']}" min="1" max="99"
                                 style="display:block;margin-top:4px;width:70px;">
                        </div>
                        <div>
                          <label style="font-size:12px;">{t('staffing.slot_role')}</label>
                          <select name="slot_role" style="display:block;margin-top:4px;">
                            <option value="staff" {"selected" if (s["slot_role"] or "staff")=="staff" else ""}>{t('staffing.role_staff')}</option>
                            <option value="lead" {"selected" if s["slot_role"]=="lead" else ""}>{t('staffing.role_lead')}</option>
                          </select>
                        </div>
                        <div>
                          <label style="font-size:12px;">{t('staffing.min_lead')}</label>
                          <input type="number" name="min_lead" value="{s['min_lead'] or 0}" min="0" max="99"
                                 style="display:block;margin-top:4px;width:70px;">
                        </div>
                        <div>
                          <label style="font-size:12px;">Von – Bis</label>
                          <div style="display:flex;align-items:center;gap:4px;margin-top:4px;">
                            <input type="time" name="time_from" step="900" value="{s['time_from'] or ''}" style="width:96px;">
                            <span>–</span>
                            <input type="time" name="time_to" step="900" value="{s['time_to'] or ''}" style="width:96px;">
                          </div>
                        </div>
                      </div>
                      <div id="wd-normal-edit-{sid}" style="margin-top:8px;{"display:none;" if s["slot_type"]=="special" else ""}">
                        <label style="font-size:12px;display:block;margin-bottom:4px;">{t('staffing.weekdays')}</label>
                        <div style="display:flex;gap:10px;flex-wrap:wrap;">{_s_wd_checks2}</div>
                        <input type="hidden" name="weekdays" id="wd-val-edit-{sid}" value="{s['weekdays'] or '0,1,2,3,4'}">
                      </div>
                      <div id="wd-special-edit-{sid}" style="margin-top:8px;{"" if s["slot_type"]=="special" else "display:none;"}">
                        <div style="display:flex;gap:12px;flex-wrap:wrap;">
                          <div>
                            <label style="font-size:12px;">{t('wd.weekday')}</label>
                            <select name="special_weekday" style="display:block;margin-top:4px;">{_s_spwd_opts2}</select>
                          </div>
                          <div>
                            <label style="font-size:12px;">{t('staffing.nth_week')}</label>
                            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px;">{_s_nth_checks2}</div>
                            <input type="hidden" name="nth_week" id="nth-val-edit-{sid}" value="{s['nth_week'] or ''}">
                          </div>
                        </div>
                      </div>
                      <div style="margin-top:10px;display:flex;gap:8px;">
                        <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
                        <button class="btn btn-sm" type="button" onclick="toggleSlotEdit({sid})">{t('btn.cancel')}</button>
                      </div>
                      <script>(function(){{
                        var _div=document.getElementById('slot-edit-{sid}');
                        if(!_div)return;
                        var _sel=_div.querySelector('select[name="slot_type"]');
                        if(!_sel)return;
                        function doToggle(){{
                          var n=document.getElementById('wd-normal-edit-{sid}');
                          var s=document.getElementById('wd-special-edit-{sid}');
                          if(!n||!s)return;
                          if(_sel.value==='special'){{n.style.display='none';s.style.display='';}}
                          else{{n.style.display='';s.style.display='none';}}
                        }}
                        _sel.addEventListener('change',doToggle);
                      }})();</script>
                    </form>
                  </div>
                  {no_members}
                  <div class="slot-body">
                    <div class="assign-col">
                      <h6>{t('staffing.available')}</h6>
                      <div class="droptarget" id="available-{sid}"
                           ondragover="allowDrop(event)"
                           ondrop="drop(event,{sid},'available')">
                        {available_cards}
                      </div>
                    </div>
                    <div class="assign-col">
                      <h6>{t('staffing.assigned')}</h6>
                      <div class="droptarget" id="assigned-{sid}"
                           ondragover="allowDrop(event)"
                           ondrop="drop(event,{sid},'assigned')">
                        {assigned_cards}
                      </div>
                    </div>
                  </div>
                  <button class="btn primary btn-sm" style="margin-top:8px;"
                          onclick="saveAssignments({sid})">{t('btn.save')}</button>
                </div>"""

            wd_checkboxes = "".join(
                f'<label style="font-size:12px;display:flex;align-items:center;gap:4px;">'
                f'<input type="checkbox" name="wd_{i}" value="{i}" checked> {_WD_MAP[i]}</label>'
                for i in range(5)
            )
            _plan_lead_lbl2 = _html.escape(
                (p["lead_label"] if "lead_label" in p.keys() and p["lead_label"] else None) or "Leiter"
            )
            plans_html += f"""
            <div style="background:var(--bg);border:1px solid var(--br);border-radius:10px;
                         padding:14px;margin-bottom:12px;">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap;">
                <strong style="font-size:15px;">{pname}</strong>
                <span style="font-size:12px;color:var(--mu);">{p["description"] or ""}</span>
                <form method="post" action="/admin/staffing"
                      style="display:flex;align-items:center;gap:6px;margin-left:auto;">
                  <input type="hidden" name="action" value="edit_plan">
                  <input type="hidden" name="plan_id" value="{pid}">
                  <label style="font-size:12px;color:var(--mu);">{t("staffing.lead_label")}:</label>
                  <input type="text" name="lead_label" value="{_plan_lead_lbl2}"
                         maxlength="30" placeholder="Leiter"
                         style="font-size:12px;padding:3px 6px;border-radius:4px;width:120px;">
                  <button class="btn btn-sm" type="submit"
                          style="font-size:12px;padding:3px 8px;">{t("btn.save")}</button>
                </form>
              </div>
              {slots_html if slots_html else f'<p style="font-size:12px;color:var(--mu);margin-bottom:8px;">{t("staffing.no_slots")}</p>'}
              <details style="margin-top:8px;" ontoggle="if(this.open)slotFormInit(this);">
                <summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--ac);">
                  + {t('staffing.add_slot')}
                </summary>
                <form method="post" action="/admin/staffing"
                      style="margin-top:10px;padding:12px;background:var(--ca);
                             border-radius:8px;border:1px solid var(--br);">
                  <input type="hidden" name="action" value="create_slot">
                  <input type="hidden" name="plan_id" value="{pid}">
                  <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
                    <div>
                      <label style="font-size:12px;">{t('staffing.slot_label')} *</label>
                      <input type="text" name="label" required maxlength="60"
                             placeholder="{t('staffing.slot_vm')}"
                             style="display:block;margin-top:4px;min-width:140px;">
                    </div>
                    <div>
                      <label style="font-size:12px;">{t('staffing.slot_type')}</label>
                      <select name="slot_type" style="display:block;margin-top:4px;"
                              onchange="toggleSlotType(this,'{pid}')">
                        <option value="vm">{t('staffing.slot_vm')}</option>
                        <option value="nm">{t('staffing.slot_nm')}</option>
                        <option value="special">{t('staffing.slot_special')}</option>
                      </select>
                    </div>
                    <div>
                      <label style="font-size:12px;">{t('staffing.min_staff')}</label>
                      <input type="number" name="min_staff" value="1" min="1" max="99"
                             style="display:block;margin-top:4px;width:70px;">
                    </div>
                    <div>
                      <label style="font-size:12px;">{t('staffing.slot_role')}</label>
                      <select name="slot_role" style="display:block;margin-top:4px;">
                        <option value="staff">{t('staffing.role_staff')}</option>
                        <option value="lead">{t('staffing.role_lead')}</option>
                      </select>
                    </div>
                    <div>
                      <label style="font-size:12px;">{t('staffing.min_lead')}</label>
                      <input type="number" name="min_lead" value="0" min="0" max="99"
                             style="display:block;margin-top:4px;width:70px;">
                      <div style="font-size:10px;color:var(--mu);margin-top:2px;">{t('staffing.min_lead_hint')}</div>
                    </div>
                    <div>
                      <label style="font-size:12px;">Von – Bis</label>
                      <div style="display:flex;align-items:center;gap:4px;margin-top:4px;">
                        <input type="time" name="time_from" step="900" style="width:96px;">
                        <span style="color:var(--mu);">–</span>
                        <input type="time" name="time_to" step="900" style="width:96px;">
                      </div>
                    </div>
                  </div>
                  <div id="wd-normal-{pid}" style="margin-bottom:10px;">
                    <label style="font-size:12px;display:block;margin-bottom:4px;">{t('staffing.weekdays')}</label>
                    <div style="display:flex;gap:10px;flex-wrap:wrap;">{wd_checkboxes}</div>
                    <input type="hidden" name="weekdays" id="wd-val-{pid}" value="0,1,2,3,4">
                  </div>
                  <div id="wd-special-{pid}" style="display:none;margin-bottom:10px;">
                    <div style="display:flex;gap:12px;flex-wrap:wrap;">
                      <div>
                        <label style="font-size:12px;">{t('wd.weekday')}</label>
                        <select name="special_weekday" style="display:block;margin-top:4px;">
                          {"".join(f'<option value="{i}">{_WD_MAP[i]}</option>' for i in range(7))}
                        </select>
                      </div>
                      <div>
                        <label style="font-size:12px;">{t('staffing.nth_week')}</label>
                        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px;">
                          {"".join(f'<label style="font-size:12px;display:flex;align-items:center;gap:3px;"><input type="checkbox" name="nth_w_{i}" value="{i}"> {i}.</label>' for i in range(1,6))}
                        </div>
                        <input type="hidden" name="nth_week" id="nth-val-{pid}" value="">
                      </div>
                    </div>
                  </div>
                  <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
                </form>
              </details>
            </div>"""

        plan_html += f"""
        <div style="margin-bottom:1.5rem;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
            <span style="width:12px;height:12px;border-radius:50%;
                         background:{team_color};display:inline-block;"></span>
            <strong style="font-size:16px;">{_html.escape(tm["name"])}</strong>
          </div>
          {plans_html if plans_html else f'<p style="font-size:13px;color:var(--mu);margin-bottom:8px;">{t("staffing.no_plans")}</p>'}
          <details>
            <summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--ac);margin-bottom:4px;">
              + {t('staffing.add_plan')}
            </summary>
            <form method="post" action="/admin/staffing"
                  style="margin-top:8px;padding:12px;background:var(--ca);
                         border-radius:8px;border:1px solid var(--br);">
              <input type="hidden" name="action" value="create_plan">
              <input type="hidden" name="team_id" value="{tid}">
              <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;">
                <div>
                  <label style="font-size:12px;">{t('staffing.plan_name')} *</label>
                  <input type="text" name="name" required maxlength="80"
                         style="display:block;margin-top:4px;min-width:160px;">
                </div>
                <div style="flex:1;min-width:140px;">
                  <label style="font-size:12px;">Beschreibung</label>
                  <input type="text" name="description" maxlength="120"
                         style="display:block;margin-top:4px;width:100%;">
                </div>
                <div>
                  <label style="font-size:12px;">{t('staffing.default_min_staff')}</label>
                  <input type="number" name="default_min_staff" value="2" min="1" max="99"
                         style="display:block;margin-top:4px;width:70px;">
                </div>
                <div style="display:flex;align-items:flex-end;padding-bottom:6px;">
                  <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;">
                    <input type="checkbox" name="require_lead" value="1">
                    {t('staffing.require_lead')}
                  </label>
                </div>
                <div>
                  <label style="font-size:12px;">{t('staffing.lead_label')}</label>
                  <input type="text" name="lead_label" value="Leiter" maxlength="30"
                         placeholder="z.B. Arzt, Leiter, Supervisor"
                         style="display:block;margin-top:4px;width:180px;">
                  <small style="color:var(--mu);">{t('staffing.lead_label_hint')}</small>
                </div>
                <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
              </div>
            </form>
          </details>
        </div>"""

    no_teams_hint = f'<p style="color:var(--mu);">{t("admin.no_teams")}</p>' if not teams else ""

    return f"""
    <style>
    .slot-card{{border:1px solid var(--br);border-radius:8px;padding:1rem;margin-bottom:1rem;}}
    .slot-header{{display:flex;gap:8px;align-items:center;margin-bottom:.75rem;flex-wrap:wrap;}}
    .slot-body{{display:grid;grid-template-columns:1fr 1fr;gap:1rem;}}
    @media(max-width:500px){{.slot-body{{grid-template-columns:1fr;}}}}
    .assign-col h6{{font-size:12px;color:var(--mu);margin-bottom:6px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;}}
    .droptarget{{min-height:80px;background:var(--ca);border:2px dashed var(--br);border-radius:6px;padding:8px;transition:border-color .15s,background .15s;}}
    .droptarget.dragover{{border-color:var(--ac);background:color-mix(in srgb,var(--ac) 10%,var(--ca));}}
    .user-card{{background:var(--bg);border:1px solid var(--br);border-radius:4px;padding:4px 8px;margin-bottom:4px;cursor:grab;display:flex;align-items:center;gap:6px;font-size:13px;user-select:none;}}
    .user-card:hover{{opacity:.85;}}
    .user-card:active{{cursor:grabbing;}}
    .user-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0;}}
    </style>
    {no_teams_hint}
    {plan_html}"""


_DE_STATES = [
    ("DE-BW", "BW", "Baden-Württemberg"),
    ("DE-BY", "BY", "Bayern"),
    ("DE-BE", "BE", "Berlin"),
    ("DE-BB", "BB", "Brandenburg"),
    ("DE-HB", "HB", "Bremen"),
    ("DE-HH", "HH", "Hamburg"),
    ("DE-HE", "HE", "Hessen"),
    ("DE-MV", "MV", "Mecklenburg-Vorpommern"),
    ("DE-NI", "NI", "Niedersachsen"),
    ("DE-NW", "NW", "Nordrhein-Westfalen"),
    ("DE-RP", "RP", "Rheinland-Pfalz"),
    ("DE-SL", "SL", "Saarland"),
    ("DE-SN", "SN", "Sachsen"),
    ("DE-ST", "ST", "Sachsen-Anhalt"),
    ("DE-SH", "SH", "Schleswig-Holstein"),
    ("DE-TH", "TH", "Thüringen"),
]


def _render_school_holidays_section() -> str:
    db = connect()
    entries = db.execute(
        "SELECT * FROM school_holidays ORDER BY region, date_from"
    ).fetchall()
    db.close()

    rows_by_region: dict = {}
    for e in entries:
        rows_by_region.setdefault(e["region"], []).append(e)

    trs = ""
    for region, hols in sorted(rows_by_region.items()):
        state_name = next((name for rcode, _, name in _DE_STATES if rcode == region), region)
        for h in hols:
            trs += (
                f"<tr>"
                f"<td style='font-size:12px;color:var(--mu);'>{_html.escape(region)}</td>"
                f"<td style='font-size:13px;'>{_html.escape(h['name'])}</td>"
                f"<td style='font-size:13px;'>{h['date_from']}</td>"
                f"<td style='font-size:13px;'>{h['date_to']}</td>"
                f"<td><form method='post' action='/admin/school-holidays/delete' style='display:inline;'"
                f" onsubmit=\"if(!confirm('{t('confirm.delete_school_holiday')}'))return false;sessionStorage.setItem('openAcc','acc-schoolhols')\">"
                f"<input type='hidden' name='entry_id' value='{h['id']}'>"
                f"<button class='btn btn-sm danger' type='submit' style='padding:2px 7px;'>×</button>"
                f"</form></td>"
                f"</tr>"
            )
    if not trs:
        trs = f"<tr><td colspan='5' style='color:var(--mu);'>Noch keine Schulferien importiert.</td></tr>"

    state_opts = "".join(
        f'<option value="{api}">{name} ({api})</option>'
        for _, api, name in _DE_STATES
    )
    clear_opts = "".join(
        f'<option value="{rcode}">{name}</option>'
        for rcode, _, name in _DE_STATES
    )
    cur_year = datetime.date.today().year
    year_opts = "".join(
        f'<option value="{y}" {"selected" if y == cur_year else ""}>{y}</option>'
        for y in range(cur_year - 1, cur_year + 3)
    )

    return f"""
    <div class="acc" data-tab="system" id="acc-schoolhols">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-schoolhols-body')">
        <span>🎓 Schulferien</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-schoolhols-body">
        <div class="acc-inner">
          <p class="small" style="color:var(--mu);margin-bottom:14px;">
            Schulferien werden bei wöchentlichen Berufsschultagen automatisch berücksichtigt.
            Quelle: <a href="https://ferien-api.de" target="_blank">ferien-api.de</a>
          </p>

          <!-- Fetch von API -->
          <div style="border:1px solid var(--bd);border-radius:8px;padding:14px;margin-bottom:14px;background:var(--sf);">
            <div style="font-weight:600;font-size:14px;margin-bottom:10px;">🌐 Online-Import (ferien-api.de)</div>
            <form method="post" action="/admin/school-holidays/fetch"
                  onsubmit="sessionStorage.setItem('openAcc','acc-schoolhols')">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
                <div>
                  <label style="font-size:12px;color:var(--mu);">Bundesland</label>
                  <select name="state_code" style="display:block;margin-top:4px;font-size:13px;">{state_opts}</select>
                </div>
                <div>
                  <label style="font-size:12px;color:var(--mu);">Jahr</label>
                  <select name="year" style="display:block;margin-top:4px;font-size:13px;">{year_opts}</select>
                </div>
                <div style="display:flex;gap:6px;align-items:flex-end;">
                  <button class="btn primary btn-sm" type="submit">⬇ Importieren</button>
                  <label style="font-size:12px;display:flex;align-items:center;gap:4px;cursor:pointer;">
                    <input type="checkbox" name="replace" value="1"> Vorhandene ersetzen
                  </label>
                </div>
              </div>
            </form>
          </div>

          <!-- Manuell hinzufügen -->
          <div style="border:1px solid var(--bd);border-radius:8px;padding:14px;margin-bottom:14px;background:var(--sf);">
            <div style="font-weight:600;font-size:14px;margin-bottom:10px;">✏ Manuell hinzufügen</div>
            <form method="post" action="/admin/school-holidays/add"
                  onsubmit="sessionStorage.setItem('openAcc','acc-schoolhols')">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
                <div>
                  <label style="font-size:12px;color:var(--mu);">Region</label>
                  <select name="region" style="display:block;margin-top:4px;font-size:13px;">{clear_opts}</select>
                </div>
                <div style="flex:1;min-width:140px;">
                  <label style="font-size:12px;color:var(--mu);">Name</label>
                  <input type="text" name="name" required maxlength="80" placeholder="Sommerferien"
                         style="display:block;margin-top:4px;">
                </div>
                <div>
                  <label style="font-size:12px;color:var(--mu);">Von</label>
                  <input type="date" name="date_from" required style="display:block;margin-top:4px;">
                </div>
                <div>
                  <label style="font-size:12px;color:var(--mu);">Bis</label>
                  <input type="date" name="date_to" required style="display:block;margin-top:4px;">
                </div>
                <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
              </div>
            </form>
          </div>

          <!-- Vorhandene Einträge -->
          <div style="font-weight:600;font-size:14px;margin-bottom:8px;">Eingetragene Schulferien ({len(entries)})</div>
          <div class="table-scroll" style="margin-bottom:12px;">
            <table style="width:100%;font-size:13px;">
              <thead><tr><th>Region</th><th>Name</th><th>Von</th><th>Bis</th><th></th></tr></thead>
              <tbody>{trs}</tbody>
            </table>
          </div>

          <!-- Alle löschen für Region -->
          <form method="post" action="/admin/school-holidays/clear"
                onsubmit="return confirm('Alle Schulferien für diese Region löschen?')&&(sessionStorage.setItem('openAcc','acc-schoolhols'),true)">
            <div style="display:flex;gap:8px;align-items:flex-end;">
              <div>
                <label style="font-size:12px;color:var(--mu);">Region leeren</label>
                <select name="region" style="display:block;margin-top:4px;font-size:13px;">{clear_opts}</select>
              </div>
              <button class="btn danger btn-sm" type="submit">🗑 Region löschen</button>
            </div>
          </form>
        </div>
      </div>
    </div>"""


def _render_features_section() -> str:
    checked = 'checked' if _feature_enabled('staffing') else ''
    return f"""
    <div class="acc" data-tab="system" id="acc-features">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-features-body')">
        <span>{t('admin.features')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-features-body">
        <div class="acc-inner">
          <form method="post" action="/admin/features" onsubmit="sessionStorage.setItem('openAcc','acc-features')">
            <div style="margin-bottom:16px;">
              <label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer;">
                <input type="checkbox" name="feature_staffing" {checked} style="margin-top:3px;">
                <div>
                  <div style="font-weight:600;font-size:14px;">{t('admin.feature_staffing')}</div>
                  <div style="font-size:12px;color:var(--mu);margin-top:2px;">{t('admin.feature_staffing_hint')}</div>
                </div>
              </label>
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
          </form>
        </div>
      </div>
    </div>"""


def _render_overtime_defaults_section() -> str:
    cfg = _get_app_config()
    def_plus_h  = cfg.get("overtime_default_limit_plus") or ""
    def_minus_h = cfg.get("overtime_default_limit_minus") or ""
    return f"""
    <div class="acc" id="acc-overtime-defaults">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-overtime-defaults-body')">
        <span>{t('admin.acc_ot_defaults')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-overtime-defaults-body">
        <div class="acc-inner">
          <p class="small" style="color:var(--mu);margin-bottom:12px;">{t('admin.ot_defaults_hint')}</p>
          <form method="post" action="/admin/overtime/save-defaults" onsubmit="sessionStorage.setItem('openAcc','acc-overtime-defaults')">
            <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin-bottom:12px;">
              <div>
                <label style="font-size:12px;">{t('admin.ot_default_plus')}</label>
                <input type="number" name="def_plus" value="{_html.escape(def_plus_h)}" placeholder="–" step="0.5"
                  style="width:80px;font-size:13px;padding:4px 8px;">
              </div>
              <div>
                <label style="font-size:12px;">{t('admin.ot_default_minus')}</label>
                <input type="number" name="def_minus" value="{_html.escape(def_minus_h)}" placeholder="–" step="0.5"
                  style="width:80px;font-size:13px;padding:4px 8px;">
              </div>
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
          </form>
        </div>
      </div>
    </div>"""


def _render_admin_overtime_section(u=None) -> str:
    today_iso = datetime.date.today().isoformat()

    cfg = _get_app_config()
    def_plus_h  = cfg.get("overtime_default_limit_plus") or ""
    def_minus_h = cfg.get("overtime_default_limit_minus") or ""

    db = connect()
    active_users = db.execute(
        "SELECT id, username, display_name, email, supervisor_email, "
        "overtime_limit_plus, overtime_limit_minus, "
        "overtime_notify_enabled, overtime_notify_interval, overtime_last_notified "
        "FROM users WHERE is_active=1 ORDER BY display_name, username"
    ).fetchall()
    _adj_users = db.execute(
        "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY display_name, username"
    ).fetchall()
    if u and not is_sysadmin(u):
        _vis = _get_visible_user_ids(u)
        if _vis is not None:
            _vis_set = set(_vis)
            active_users = [r for r in active_users if r["id"] in _vis_set]
            _adj_users = [r for r in _adj_users if r["id"] in _vis_set]
    _adj_rows = db.execute("""
        SELECT ba.*, u.display_name as uname, u.username,
               cb.display_name as cname
        FROM balance_adjustments ba
        JOIN users u ON u.id=ba.user_id
        LEFT JOIN users cb ON cb.id=ba.created_by
        ORDER BY ba.adjustment_date DESC
        LIMIT 50
    """).fetchall()
    db.close()

    def _fmt_adj_h(m):
        h = m / 60
        sign = "+" if m >= 0 else ""
        return f"{sign}{h:.2f}h".replace(".00h","h")

    _adj_trs = ""
    for _a in _adj_rows:
        _udisp = _html.escape(_a["uname"] or _a["username"] or "?")
        _cdisp = _html.escape(_a["cname"] or "–")
        _hdisp = _fmt_adj_h(int(_a["minutes"]))
        _clr   = "#16a34a" if int(_a["minutes"]) >= 0 else "#dc2626"
        _adj_trs += (
            f"<tr>"
            f"<td style='padding:4px 6px;font-size:12px;'>{_a['adjustment_date']}</td>"
            f"<td style='padding:4px 6px;font-size:12px;'>{_udisp}</td>"
            f"<td style='padding:4px 6px;font-size:12px;font-weight:600;color:{_clr};'>{_hdisp}</td>"
            f"<td style='padding:4px 6px;font-size:12px;'>{_html.escape(_a['reason'])}</td>"
            f"<td style='padding:4px 6px;font-size:12px;color:var(--mu);'>{_cdisp}</td>"
            f"<td style='padding:4px 6px;'>"
            f"<form method='post' action='/admin/balance-adjustment' style='margin:0;'>"
            f"<input type='hidden' name='action' value='delete'>"
            f"<input type='hidden' name='adj_id' value='{_a['id']}'>"
            f"<button class='btn btn-sm' type='submit' style='color:#dc2626;font-size:11px;padding:1px 6px;'"
            + f" onclick=\"return confirm('{t('confirm.delete')}')\">×</button>"
            f"</form></td>"
            f"</tr>"
        )
    _adj_table = ""
    if _adj_trs:
        _adj_table = f"""
        <div class="table-scroll" style="margin-top:12px;">
          <table style="font-size:12px;">
            <thead><tr>
              <th>Datum</th><th>{t('common.name')}</th>
              <th>Stunden</th><th>{t('balance.adjustment_reason')}</th>
              <th>Erstellt von</th><th></th>
            </tr></thead>
            <tbody>{_adj_trs}</tbody>
          </table>
        </div>"""

    def _mins_to_h(m) -> str:
        if m is None:
            return ""
        m = int(m)
        sign = "-" if m < 0 else ""
        m = abs(m)
        return f"{sign}{m // 60}" if m % 60 == 0 else f"{sign}{m / 60:.2f}".rstrip("0").rstrip(".")

    def _h_to_mins(s: str):
        s = s.strip()
        if not s:
            return None
        try:
            return int(float(s) * 60)
        except ValueError:
            return None

    # Balances
    balances: dict[int, int] = {}
    for u_row in active_users:
        balances[u_row["id"]] = _calc_balance_end_at(u_row["id"], today_iso)

    # --- Table rows ---
    def_plus_mins  = _h_to_mins(def_plus_h)
    def_minus_mins = _h_to_mins(def_minus_h)

    saldo_rows = ""
    for u_row in active_users:
        uid  = u_row["id"]
        name = _html.escape(u_row["display_name"] or u_row["username"])
        saldo = balances[uid]
        saldo_str = _fmt_minutes_signed(saldo)

        lp = u_row["overtime_limit_plus"]
        lm = u_row["overtime_limit_minus"]
        eff_lp = lp if lp is not None else def_plus_mins
        eff_lm = lm if lm is not None else def_minus_mins

        if eff_lp is not None and saldo > eff_lp:
            status = f"<span style='color:var(--danger);font-weight:600;'>{t('admin.ot_over_plus')}</span>"
            row_bg = "background:rgba(220,38,38,.04);"
        elif eff_lm is not None and saldo < -(eff_lm):
            status = f"<span style='color:var(--danger);font-weight:600;'>{t('admin.ot_over_minus')}</span>"
            row_bg = "background:rgba(220,38,38,.04);"
        elif eff_lp is not None and saldo > eff_lp * 0.9:
            status = f"<span style='color:#d97706;'>{t('admin.ot_near_plus')}</span>"
            row_bg = "background:rgba(251,191,36,.05);"
        elif eff_lm is not None and saldo < -(eff_lm) * 0.9:
            status = f"<span style='color:#d97706;'>{t('admin.ot_near_minus')}</span>"
            row_bg = "background:rgba(251,191,36,.05);"
        else:
            status = "<span style='color:var(--ok);'>✓ OK</span>"
            row_bg = ""

        lp_str = _mins_to_h(eff_lp) + (" h" if eff_lp is not None else "")
        lm_str = _mins_to_h(eff_lm) + (" h" if eff_lm is not None else "")
        saldo_color = "var(--ok)" if saldo >= 0 else "var(--danger)"

        saldo_rows += (
            f"<tr style='{row_bg}'>"
            f"<td style='font-size:12px;'>{name}</td>"
            f"<td style='text-align:center;font-weight:600;color:{saldo_color};font-size:12px;'>{saldo_str}</td>"
            f"<td style='text-align:center;font-size:12px;color:var(--mu);'>{'+' + lp_str if eff_lp is not None else '–'}</td>"
            f"<td style='text-align:center;font-size:12px;color:var(--mu);'>{'-' + lm_str if eff_lm is not None else '–'}</td>"
            f"<td style='font-size:12px;'>{status}</td>"
            f"</tr>"
        )

    # --- Limits + Notify form rows ---
    form_rows = ""
    for u_row in active_users:
        uid  = u_row["id"]
        name = _html.escape(u_row["display_name"] or u_row["username"])
        lp   = _mins_to_h(u_row["overtime_limit_plus"])
        lm   = _mins_to_h(u_row["overtime_limit_minus"])
        sup  = _html.escape(u_row["supervisor_email"] or "")
        en   = "checked" if int(u_row["overtime_notify_enabled"] or 0) else ""
        iv   = u_row["overtime_notify_interval"] or "once"

        def _iv_sel(val):
            opts = [("once",t("admin.ot_once")),("daily",t("admin.ot_daily")),("weekly",t("admin.ot_weekly"))]
            return "".join(
                f'<option value="{v}" {"selected" if v==val else ""}>{l}</option>'
                for v, l in opts
            )

        form_rows += f"""
        <tr>
          <td style="font-size:12px;">{name}</td>
          <td><input type="number" name="lp_{uid}" value="{lp}" placeholder="–" step="0.5"
            style="width:70px;font-size:12px;padding:3px 6px;" title="{t('admin.ot_limits_hint')}"></td>
          <td><input type="number" name="lm_{uid}" value="{lm}" placeholder="–" step="0.5"
            style="width:70px;font-size:12px;padding:3px 6px;" title="{t('admin.ot_limits_hint')}"></td>
          <td style="text-align:center;"><input type="checkbox" name="en_{uid}" value="1" {en}></td>
          <td><select name="iv_{uid}" style="font-size:12px;padding:3px 5px;">{_iv_sel(iv)}</select></td>
          <td><input type="email" name="sup_{uid}" value="{sup}" placeholder="{t('admin.supervisor_email')}"
            style="font-size:12px;padding:3px 6px;width:200px;"></td>
        </tr>"""

    _no_users_ot = f"<tr><td colspan='5' style='color:var(--mu);'>{t('admin.no_users')}</td></tr>"
    return f"""
    <div class="acc" data-tab="reporting" id="acc-overtime">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-overtime-body')">
        <span>{t('admin.acc_balance')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-overtime-body">
        <div class="acc-inner">

          <!-- Salden alle User -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.balance_current_title')}</div>
          <div class="table-scroll" style="margin-bottom:16px;">
            <table>
              <thead><tr>
                <th>{t('common.name')}</th>
                <th style="text-align:center;">{t('admin.col_saldo')}</th>
                <th style="text-align:center;">{t('admin.col_limit_plus')}</th>
                <th style="text-align:center;">{t('admin.col_limit_minus')}</th>
                <th>{t('common.status')}</th>
              </tr></thead>
              <tbody>{saldo_rows or _no_users_ot}</tbody>
            </table>
          </div>

          <hr style="margin:14px 0;">

          <!-- Limits + Benachrichtigungen konfigurieren -->
          <div style="font-size:13px;font-weight:700;margin-bottom:6px;">{t('admin.ot_limits_notify')}</div>
          <p class="small" style="color:var(--mu);margin-bottom:10px;">{t('admin.ot_limits_hint')}</p>

          <form method="post" action="/admin/overtime/save" onsubmit="sessionStorage.setItem('openAcc','acc-overtime')">
            <div class="table-scroll" style="margin-bottom:12px;">
              <table>
                <thead><tr>
                  <th>{t('common.name')}</th>
                  <th style="text-align:center;">{t('admin.ot_plus_limit')}</th>
                  <th style="text-align:center;">{t('admin.ot_minus_limit')}</th>
                  <th style="text-align:center;">{t('admin.ot_notify')}</th>
                  <th>{t('admin.ot_interval')}</th>
                  <th>{t('admin.supervisor_email')}</th>
                </tr></thead>
                <tbody>{form_rows}</tbody>
              </table>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
              <button class="btn btn-sm" type="submit" formaction="/admin/overtime/check"
                onclick="sessionStorage.setItem('openAcc','acc-overtime')">
                {t('admin.ot_check_now')}
              </button>
            </div>
          </form>

          <hr style="margin:14px 0;">

          <!-- Manuelle Korrekturen -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('balance.add_adjustment')}</div>
          <form method="post" action="/admin/balance-adjustment"
                onsubmit="sessionStorage.setItem('openAcc','acc-overtime')"
                style="margin-bottom:16px;">
            <input type="hidden" name="action" value="create">
            <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
              <div>
                <label style="font-size:12px;">{t('common.name')}</label>
                <select name="user_id" style="display:block;margin-top:4px;min-width:140px;">
                  {"".join('<option value="' + str(u2["id"]) + '">' + _html.escape(u2["display_name"] or u2["username"]) + '</option>' for u2 in _adj_users)}
                </select>
              </div>
              <div>
                <label style="font-size:12px;">Datum</label>
                <input type="date" name="date" required style="display:block;margin-top:4px;">
              </div>
              <div>
                <label style="font-size:12px;">{t('balance.adjustment_hours')}</label>
                <input type="number" name="hours" step="0.25" required
                       placeholder="{t('balance.adjustment_hint')}"
                       style="display:block;margin-top:4px;width:130px;">
              </div>
              <div style="flex:1;min-width:150px;">
                <label style="font-size:12px;">{t('balance.adjustment_reason')}</label>
                <input type="text" name="reason" required maxlength="120"
                       style="display:block;margin-top:4px;width:100%;">
              </div>
              <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
            </div>
          </form>
          {_adj_table}

        </div>
      </div>
    </div>"""


@admin_bp.post("/admin/balance-adjustment")
@timemanager_required
def admin_balance_adjustment():
    from app import bootstrap, add_flash
    bootstrap()
    u = current_user()
    action = request.form.get("action")
    db = connect()
    if action == "create":
        user_id = int(request.form.get("user_id", 0))
        try:
            hours = float((request.form.get("hours") or "0").replace(",", "."))
        except ValueError:
            hours = 0.0
        minutes = int(round(hours * 60))
        reason  = request.form.get("reason", "").strip()
        date    = request.form.get("date", "").strip()
        if user_id and reason and date:
            db.execute(
                "INSERT INTO balance_adjustments "
                "(user_id, minutes, reason, adjustment_date, created_by) VALUES (?,?,?,?,?)",
                (user_id, minutes, reason, date, u["id"])
            )
            db.commit()
            add_flash(t("success.adjustment_created"), "success")
    elif action == "delete":
        adj_id = int(request.form.get("adj_id", 0))
        db.execute("DELETE FROM balance_adjustments WHERE id=?", (adj_id,))
        db.commit()
        add_flash(t("success.adjustment_deleted"), "success")
    db.close()
    return redirect("/admin#acc-overtime")


@admin_bp.post("/admin/overtime/save")
@admin_required
def admin_overtime_save():
    from app import bootstrap, add_flash
    bootstrap()
    db = connect()
    try:
        active_users = db.execute(
            "SELECT id FROM users WHERE is_active=1"
        ).fetchall()

        def_plus_h  = (request.form.get("def_plus") or "").strip()
        def_minus_h = (request.form.get("def_minus") or "").strip()

        def _h_to_mins(s: str):
            s = s.strip()
            if not s:
                return None
            try:
                return int(float(s) * 60)
            except ValueError:
                return None

        for key, val in [
            ("overtime_default_limit_plus",  str(_h_to_mins(def_plus_h)  or "") ),
            ("overtime_default_limit_minus", str(_h_to_mins(def_minus_h) or "") ),
        ]:
            db.execute(
                "INSERT OR REPLACE INTO app_config(key, value, updated_at) VALUES(?, ?, datetime('now'))",
                (key, val),
            )

        for u_row in active_users:
            uid = u_row["id"]
            lp  = _h_to_mins(request.form.get(f"lp_{uid}") or "")
            lm  = _h_to_mins(request.form.get(f"lm_{uid}") or "")
            en  = 1 if request.form.get(f"en_{uid}") == "1" else 0
            iv  = request.form.get(f"iv_{uid}") or "once"
            if iv not in ("once", "daily", "weekly"):
                iv = "once"
            sup = (request.form.get(f"sup_{uid}") or "").strip()
            db.execute(
                "UPDATE users SET overtime_limit_plus=?, overtime_limit_minus=?, "
                "supervisor_email=?, overtime_notify_enabled=?, overtime_notify_interval=? "
                "WHERE id=?",
                (lp, lm, sup or None, en, iv, uid),
            )

        db.commit()
    finally:
        db.close()
    add_flash(t("flash.success.ot_limits_saved"), "success")
    return redirect("/admin#acc-overtime")


@admin_bp.post("/admin/overtime/save-defaults")
@sysadmin_required
def admin_overtime_save_defaults():
    from app import bootstrap, add_flash
    bootstrap()
    def _h_to_mins(s: str):
        s = (s or "").strip()
        if not s:
            return None
        try:
            return int(float(s) * 60)
        except ValueError:
            return None

    def_plus_h  = (request.form.get("def_plus") or "").strip()
    def_minus_h = (request.form.get("def_minus") or "").strip()
    db = connect()
    try:
        for key, val in [
            ("overtime_default_limit_plus",  str(_h_to_mins(def_plus_h)  or "")),
            ("overtime_default_limit_minus", str(_h_to_mins(def_minus_h) or "")),
        ]:
            db.execute(
                "INSERT OR REPLACE INTO app_config(key, value, updated_at) VALUES(?, ?, datetime('now'))",
                (key, val),
            )
        db.commit()
    finally:
        db.close()
    from flask import g as _g
    if hasattr(_g, "_app_config_cache"):
        del _g._app_config_cache
    add_flash(t("flash.success.ot_defaults_saved"), "success")
    return redirect("/admin#acc-overtime-defaults")


@admin_bp.post("/admin/overtime/check")
@admin_required
def admin_overtime_check():
    from app import bootstrap, add_flash, _fmt_minutes_signed, _send_mail_simple, _region_picker, _calc_balance_end_at, _get_app_config, _STANDARD_TYPE_NAMES, _REGION_LABEL, _render_per_user_settings_section, _render_regional_section, _run_overtime_notifications
    bootstrap()
    sent, errors = _run_overtime_notifications()
    if sent:
        add_flash(t("flash.success.ot_notify_sent").format(count=sent), "success")
    if errors:
        add_flash(t("flash.error.ot_notify_failed").format(count=errors), "error")
    if not sent and not errors:
        add_flash(t("flash.success.ot_notify_none"), "success")
    return redirect("/admin#acc-overtime")


def _run_overtime_notifications() -> tuple[int, int]:
    """Run overtime limit checks and send notifications. Returns (sent, errors)."""
    today_iso = datetime.date.today().isoformat()
    cfg = _get_app_config()

    def _h_to_mins(s):
        s = (s or "").strip()
        if not s:
            return None
        try:
            return int(float(s) * 60)
        except ValueError:
            return None

    def_plus  = _h_to_mins(cfg.get("overtime_default_limit_plus"))
    def_minus = _h_to_mins(cfg.get("overtime_default_limit_minus"))

    db = connect()
    users = db.execute(
        "SELECT id, username, display_name, email, supervisor_email, "
        "overtime_limit_plus, overtime_limit_minus, overtime_notify_enabled, "
        "overtime_notify_interval, overtime_last_notified "
        "FROM users WHERE is_active=1 AND overtime_notify_enabled=1"
    ).fetchall()
    db.close()

    sent = 0
    errors = 0
    for u_row in users:
        uid   = u_row["id"]
        lp    = u_row["overtime_limit_plus"] if u_row["overtime_limit_plus"] is not None else def_plus
        lm    = u_row["overtime_limit_minus"] if u_row["overtime_limit_minus"] is not None else def_minus
        if lp is None and lm is None:
            continue

        saldo = _calc_balance_end_at(uid, today_iso)
        over_plus  = lp is not None and saldo > lp
        over_minus = lm is not None and saldo < -(lm)
        if not over_plus and not over_minus:
            continue

        interval      = u_row["overtime_notify_interval"] or "once"
        last_notified = u_row["overtime_last_notified"]
        should = False
        if interval == "once" and not last_notified:
            should = True
        elif interval == "daily":
            should = not last_notified or last_notified < today_iso
        elif interval == "weekly":
            if not last_notified:
                should = True
            else:
                diff = (datetime.date.today() - datetime.date.fromisoformat(last_notified)).days
                should = diff >= 7
        if not should:
            continue

        name = u_row["display_name"] or u_row["username"]
        saldo_str = _fmt_minutes_signed(saldo)
        if over_plus and lp:
            limit_str = f"+{lp // 60:02d}:{lp % 60:02d}"
            reason = "Plus-Limit (Überstunden)"
        else:
            limit_str = f"-{abs(lm) // 60:02d}:{abs(lm) % 60:02d}"
            reason = "Minus-Limit (Minderstunden)"

        body = (
            f"Hallo {name},\n\n"
            f"dein Gleitzeitkonto hat das eingestellte Limit überschritten.\n\n"
            f"Aktueller Saldo: {saldo_str}\n"
            f"Limit ({reason}): {limit_str}\n\n"
            f"Bitte stimme das weitere Vorgehen mit deinem Vorgesetzten ab.\n"
        )
        subject = f"Gleitzeitkonto Hinweis – {name}"

        recipients = [r for r in [u_row["email"] or "", u_row["supervisor_email"] or ""] if r]
        for recipient in recipients:
            try:
                _send_mail_simple(recipient, subject, body)
                sent += 1
            except Exception:
                errors += 1

        db2 = connect()
        db2.execute(
            "UPDATE users SET overtime_last_notified=? WHERE id=?",
            (today_iso, uid),
        )
        db2.commit()
        db2.close()

    return sent, errors


# Flat label lookup: region code → display label (for badges etc.)
_REGION_LABEL: dict[str, str] = {
    code: label
    for _, _, entries in REGION_GROUPS
    for code, label in entries
}

# Standard types available to all users by default (everything except Verdi)
_STANDARD_TYPE_NAMES = {"Urlaub", "Krank", "Flextag", "Sonstige"}


def _get_user_enabled_absence_type_ids(user_id: int) -> list[int]:
    """Return absence type IDs enabled for this user.
    NULL enabled_absence_types = standard set (all active except Verdi)."""
    db = connect()
    try:
        user_row = db.execute(
            "SELECT enabled_absence_types FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if user_row and user_row["enabled_absence_types"]:
            return [int(x) for x in user_row["enabled_absence_types"].split(",") if x.strip().isdigit()]
        rows = db.execute(
            "SELECT id FROM absence_types WHERE active=1 AND name != 'Verdi' ORDER BY id"
        ).fetchall()
        return [r["id"] for r in rows]
    finally:
        db.close()


def _region_country_key(entries: list) -> str:
    """Derive the JS country key from a REGION_GROUPS entries list."""
    c = entries[0][0]
    return c.split("-")[0] if "-" in c else c


def _region_picker(field_name: str, current: str, include_default: bool = False) -> str:
    """Two-step country → region picker. Submits region code as field_name."""
    # Find which group the current region belongs to
    current_country = ""
    for _, _, entries in REGION_GROUPS:
        if any(code == current for code, _ in entries):
            current_country = _region_country_key(entries)
            break

    # Build JS region data {country_key: [[code, label], ...]}
    data: dict = {}
    for _, _, entries in REGION_GROUPS:
        ck = _region_country_key(entries)
        data[ck] = [[c, l] for c, l in entries]
    regions_json = _json.dumps(data, ensure_ascii=False)

    # Build country dropdown
    country_opts = ""
    if include_default:
        sel = " selected" if not current else ""
        country_opts += f'<option value=""{sel}>— Standard verwenden —</option>'
    for flag, group_label, entries in REGION_GROUPS:
        ck = _region_country_key(entries)
        sel = " selected" if ck == current_country and current else ""
        country_opts += f'<option value="{ck}"{sel}>{_html.escape(flag + " " + group_label)}</option>'

    # Build initial region dropdown options for current country
    region_opts = ""
    region_display = "none" if (include_default and not current) else ""
    if current_country:
        for _, _, entries in REGION_GROUPS:
            if _region_country_key(entries) == current_country:
                if include_default:
                    sel = " selected" if not current else ""
                    region_opts += f'<option value=""{sel}>— Standard verwenden —</option>'
                for code, label in entries:
                    sel = " selected" if code == current else ""
                    region_opts += f'<option value="{code}"{sel}>{_html.escape(label)}</option>'
                break

    # Unique JS function name (replace non-alphanumeric with _)
    uniq = re.sub(r'[^a-zA-Z0-9]', '_', field_name)
    inc_default_js = "true" if include_default else "false"
    cur_js = _json.dumps(current)

    return (
        f'<select id="{uniq}_c" style="font-size:13px;padding:5px 8px;" '
        f'onchange="_rp_{uniq}(this.value)">{country_opts}</select>'
        f'<br><select name="{field_name}" id="{uniq}_r" '
        f'style="font-size:13px;padding:5px 8px;margin-top:6px;display:{region_display};">'
        f'{region_opts}</select>'
        f'<script>(function(){{'
        f'var _d={regions_json};'
        f'var _inc={inc_default_js};'
        f'var _cur={cur_js};'
        f'window["_rp_{uniq}"]=function(c){{'
        f'var r=document.getElementById("{uniq}_r");'
        f'if(!c){{r.style.display="none";r.innerHTML="";return;}}'
        f'var opts="";'
        f'if(_inc)opts+=\'<option value="">— Standard verwenden —</option>\';'
        f'(_d[c]||[]).forEach(function(e){{'
        f'var s=e[0]===_cur?" selected":"";'
        f'opts+=\'<option value="\'+e[0]+\'"\'+s+\'>\'+e[1]+\'</option>\';}});'
        f'r.innerHTML=opts;r.style.display="";'
        f'if(!r.value&&r.options.length>0)r.selectedIndex=0;'
        f'}};'
        f'_rp_{uniq}(document.getElementById("{uniq}_c").value);'
        f'}})();</script>'
    )


def _bundesland_select(name: str, current: str, include_default: bool = False) -> str:
    html = f'<select name="{name}" style="font-size:13px;padding:5px 8px;">'
    if include_default:
        sel = " selected" if not current else ""
        html += f'<option value=""{sel}>— Standard verwenden —</option>'
    for flag, group_label, entries in REGION_GROUPS:
        html += f'<optgroup label="{_html.escape(flag + " " + group_label)}">'
        for code, label in entries:
            sel = " selected" if code == current else ""
            html += f'<option value="{_html.escape(code)}"{sel}>{_html.escape(label)}</option>'
        html += "</optgroup>"
    html += "</select>"
    return html


def _render_regional_section() -> str:
    cfg = _get_app_config()
    default_region = cfg.get("default_holiday_region") or "DE-NW"
    base_url_val   = _html.escape(cfg.get("base_url") or "")
    current_tz     = cfg.get("timezone") or "Europe/Berlin"
    return f"""
    <div class="acc" data-tab="system" id="acc-regional">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-regional-body')">
        <span>{t('admin.acc_regional')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-regional-body">
        <div class="acc-inner">

          <form method="post" action="/admin/server-config" style="margin-bottom:20px;">
            <div style="font-size:13px;font-weight:700;margin-bottom:10px;">{t('admin.server_config')}</div>
            <div style="margin-bottom:10px;">
              <label style="font-size:12px;">{t('admin.base_url')}</label>
              <input type="url" name="base_url" value="{base_url_val}"
                     placeholder="https://zeiten.firma.de"
                     style="width:100%;max-width:400px;margin-top:4px;">
              <div class="small" style="color:var(--mu);margin-top:3px;">{t('admin.base_url_hint')}</div>
            </div>
            <div style="margin-bottom:10px;">
              <label style="font-size:12px;">{t('admin.timezone')}</label>
              {_timezone_select("timezone", current_tz)}
              <div class="small" style="color:var(--mu);margin-top:3px;">{t('admin.timezone_hint')}</div>
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
          </form>

          <hr style="margin:0 0 16px 0;border:none;border-top:1px solid var(--bd);">

          <form method="post" action="/admin/regional">
            <div style="font-size:13px;font-weight:700;margin-bottom:12px;">{t('admin.regional_holidays')}</div>
            <div style="margin-bottom:14px;">
              <label style="font-size:12px;">{t('admin.regional_default_label')}
                <span style="font-weight:400;color:var(--mu);">{t('admin.regional_default_hint')}</span>
              </label><br>
              <div style="margin-top:6px;">{_region_picker("default_holiday_region", default_region, include_default=False)}</div>
            </div>
            <div>
              <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    """


def _render_per_user_settings_section() -> str:
    """Accordion: per-user region and absence type configuration."""
    cfg = _get_app_config()
    default_region_code = cfg.get("default_holiday_region") or "DE-NW"
    default_region_label = _REGION_LABEL.get(default_region_code, default_region_code)

    db = connect()
    active_users = db.execute(
        "SELECT id, username, display_name, holiday_region, enabled_absence_types "
        "FROM users WHERE is_active=1 ORDER BY display_name, username"
    ).fetchall()
    all_types = db.execute(
        "SELECT id, name FROM absence_types WHERE active=1 ORDER BY name"
    ).fetchall()
    db.close()

    _tbyn = {t["name"]: t["id"] for t in all_types}
    _has_verdi = bool(_tbyn.get("Verdi"))
    _has_flextag = bool(_tbyn.get("Flextag"))

    # --- Per-user region rows ---
    region_rows = ""
    for urow in active_users:
        uid = urow["id"]
        uname = _html.escape(urow["display_name"] or urow["username"])
        cur_r = urow["holiday_region"] or ""
        cur_label = _REGION_LABEL.get(cur_r, "—")
        flag_txt = ""
        for fla, _, entries in REGION_GROUPS:
            if any(c == cur_r for c, _ in entries):
                flag_txt = fla + " "
                break
        region_rows += (
            f"<tr>"
            f"<td style='font-size:13px;'>{uname}</td>"
            f"<td style='font-size:12px;color:var(--mu);'>"
            f"{t('admin.regional_standard') + ' (' + _html.escape(default_region_label) + ')' if not cur_r else flag_txt + _html.escape(cur_label)}"
            f"</td>"
            f"<td><a class='btn btn-sm' href='/admin/users/{uid}/edit'>{t('btn.edit')}</a></td>"
            f"</tr>"
        )

    # --- Per-user absence types rows ---
    at_headers = "<th>Urlaub</th><th>Krank</th>"
    if _has_flextag:
        at_headers += "<th>Flextag</th>"
    if _has_verdi:
        at_headers += "<th>Verdi</th>"
    at_headers += "<th>Sonstige</th>"

    at_rows = ""
    for urow in active_users:
        uid = urow["id"]
        uname = _html.escape(urow["display_name"] or urow["username"])
        eat_str = urow["enabled_absence_types"] or ""
        eat_ids = {int(x) for x in eat_str.split(",") if x.strip().isdigit()} if eat_str else None

        def _chk(name: str) -> str:
            tid = _tbyn.get(name)
            if not tid:
                return "<td>–</td>"
            if name in ("Urlaub", "Krank"):
                return f"<td style='text-align:center;'>✓</td>"
            if eat_ids is None:
                checked = "checked" if name in _STANDARD_TYPE_NAMES else ""
            else:
                checked = "checked" if tid in eat_ids else ""
            field_id = f"eat_{uid}_{name.lower()}"
            return (f"<td style='text-align:center;'>"
                    f"<input type='checkbox' name='eat_{uid}_{name.lower()}' value='1' {checked}>"
                    f"</td>")

        at_rows += f"<tr><td style='font-size:13px;'>{uname}</td>"
        at_rows += f"<td style='text-align:center;'>✓</td><td style='text-align:center;'>✓</td>"
        if _has_flextag:
            at_rows += _chk("Flextag")
        if _has_verdi:
            at_rows += _chk("Verdi")
        at_rows += _chk("Sonstige")
        at_rows += "</tr>"

    _no_users_row = f"<tr><td colspan='3' style='color:var(--mu);'>{t('admin.no_users')}</td></tr>"
    _no_users_at  = f"<tr><td colspan='6' style='color:var(--mu);'>{t('admin.no_users')}</td></tr>"
    return f"""
    <div class="acc" data-tab="users" id="acc-per-user-settings">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-per-user-settings-body')">
        <span>{t('admin.acc_per_user')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-per-user-settings-body">
        <div class="acc-inner">

          <!-- Default region info -->
          <div style="font-size:12px;color:var(--mu);margin-bottom:16px;">
            {t('admin.regional_default_label')} <b>{_html.escape(default_region_label)}</b>
          </div>

          <!-- Per-user regions -->
          <div style="font-size:13px;font-weight:700;margin-bottom:8px;">{t('admin.regional_per_user')}</div>
          <div class="table-scroll" style="margin-bottom:20px;">
            <table>
              <thead><tr><th>{t('admin.users_title')}</th><th>{t('admin.regional')}</th><th></th></tr></thead>
              <tbody>{region_rows or _no_users_row}</tbody>
            </table>
          </div>

          <!-- Per-user absence types -->
          <div style="font-size:13px;font-weight:700;margin-bottom:4px;">{t('admin.abs_types_per_user')}</div>
          <div class="small" style="color:var(--mu);margin-bottom:8px;">{t('admin.abs_types_always')}</div>
          <form method="post" action="/admin/batch/absence-types">
            <div class="table-scroll" style="margin-bottom:10px;">
              <table>
                <thead><tr><th>{t('admin.users_title')}</th>{at_headers}</tr></thead>
                <tbody>{at_rows or _no_users_at}</tbody>
              </table>
            </div>
            <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
          </form>

        </div>
      </div>
    </div>"""


@admin_bp.post("/admin/batch/absence-types")
@admin_required
def admin_batch_absence_types():
    from app import bootstrap, add_flash, _get_app_config, _STANDARD_TYPE_NAMES, _render_appearance_section
    bootstrap()
    db = connect()
    active_users = db.execute(
        "SELECT id FROM users WHERE is_active=1"
    ).fetchall()
    all_types = db.execute("SELECT id, name FROM absence_types WHERE active=1").fetchall()
    db.close()
    _tbyn = {t["name"]: t["id"] for t in all_types}
    _std_ids = {_tbyn[n] for n in _STANDARD_TYPE_NAMES if n in _tbyn}

    for urow in active_users:
        uid = urow["id"]
        _always = {_tbyn[n] for n in ("Urlaub", "Krank") if n in _tbyn}
        _eat_set = set(_always)
        for _at_name, _field_sfx in (("Flextag", "flextag"), ("Verdi", "verdi"), ("Sonstige", "sonstige")):
            if request.form.get(f"eat_{uid}_{_field_sfx}") and _tbyn.get(_at_name):
                _eat_set.add(_tbyn[_at_name])
        _new_eat = None if _eat_set == _std_ids else ",".join(str(i) for i in sorted(_eat_set))
        _db = connect()
        _db.execute("UPDATE users SET enabled_absence_types=?, updated_at=datetime('now') WHERE id=?",
                    (_new_eat, uid))
        _db.commit()
        _db.close()

    add_flash(t("flash.success.absence_types_saved"), "success")
    return redirect("/admin#acc-per-user-settings")


def _render_appearance_section() -> str:
    cfg = _get_app_config()
    accent    = cfg.get("accent_color") or "#2563eb"
    nav_color = cfg.get("nav_color") or ""
    app_label = (cfg.get("app_label") or "")[:10]
    lbl_color = cfg.get("app_label_color") or "#f59e0b"

    lbl_preview = (
        f'<span style="background:{_html.escape(lbl_color)};color:#fff;'
        f'font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;'
        f'letter-spacing:.07em;text-transform:uppercase;" id="lbl-preview">'
        f'{_html.escape(app_label) or "PREVIEW"}</span>'
    )

    return f"""
    <div class="acc" data-tab="system" id="acc-appearance">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-appearance-body')">
        <span>{t('admin.acc_appearance')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-appearance-body">
        <div class="acc-inner">
          <form method="post" action="/admin/appearance" id="appearance-form">

            <!-- App-Farben -->
            <div style="font-size:13px;font-weight:700;margin-bottom:12px;">{t('admin.appearance_colors')}</div>

            <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;">
              <div>
                <label style="font-size:12px;">{t('admin.appearance_accent')}</label>
                <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
                  <input type="color" name="accent_color" id="inp-accent" value="{_html.escape(accent)}"
                    style="width:44px;height:36px;padding:2px;border-radius:6px;cursor:pointer;border:1px solid var(--bd);"
                    oninput="applyPreview()">
                  <input type="text" id="inp-accent-txt" value="{_html.escape(accent)}"
                    style="width:90px;font-size:13px;padding:5px 8px;"
                    oninput="syncColor('inp-accent','inp-accent-txt')">
                </div>
              </div>
              <div>
                <label style="font-size:12px;">{t('admin.appearance_nav')}</label>
                <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
                  <input type="color" name="nav_color" id="inp-nav" value="{_html.escape(nav_color) or '#f9fafb'}"
                    style="width:44px;height:36px;padding:2px;border-radius:6px;cursor:pointer;border:1px solid var(--bd);"
                    oninput="applyPreview()">
                  <input type="text" id="inp-nav-txt" value="{_html.escape(nav_color)}"
                    style="width:90px;font-size:13px;padding:5px 8px;"
                    placeholder="{t('admin.appearance_preset_default')}"
                    oninput="syncColor('inp-nav','inp-nav-txt')">
                </div>
              </div>
            </div>

            <!-- Schnellauswahl -->
            <div style="margin-bottom:14px;">
              <label style="font-size:12px;margin-bottom:6px;display:block;">{t('admin.appearance_presets')}</label>
              <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <button type="button" class="btn btn-sm"
                  onclick="setPreset('#2563eb','','','#f59e0b')"
                  style="border-left:4px solid #2563eb;">{t('admin.appearance_preset_default')}</button>
                <button type="button" class="btn btn-sm"
                  onclick="setPreset('#16a34a','#f0fdf4','PROD','#16a34a')"
                  style="border-left:4px solid #16a34a;">{t('admin.appearance_preset_prod')}</button>
                <button type="button" class="btn btn-sm"
                  onclick="setPreset('#ea580c','#fff7ed','DEV','#ea580c')"
                  style="border-left:4px solid #ea580c;">{t('admin.appearance_preset_dev')}</button>
                <button type="button" class="btn btn-sm"
                  onclick="setPreset('#7c3aed','#faf5ff','TEST','#7c3aed')"
                  style="border-left:4px solid #7c3aed;">{t('admin.appearance_preset_test')}</button>
              </div>
            </div>

            <hr style="margin:14px 0;">

            <!-- App-Label -->
            <div style="font-size:13px;font-weight:700;margin-bottom:12px;">{t('admin.appearance_label_section')}</div>
            <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-end;margin-bottom:12px;">
              <div>
                <label style="font-size:12px;">{t('admin.appearance_label_text')} <span style="font-weight:400;color:var(--mu);">{t('admin.appearance_label_hint')}</span></label>
                <input type="text" name="app_label" id="inp-label" maxlength="10"
                  value="{_html.escape(app_label)}"
                  placeholder="z. B. DEV, TEST, STAGING"
                  style="font-size:13px;padding:5px 8px;"
                  oninput="updateLabelPreview()">
              </div>
              <div>
                <label style="font-size:12px;">{t('admin.appearance_label_color')}</label>
                <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
                  <input type="color" name="app_label_color" id="inp-lbl-color"
                    value="{_html.escape(lbl_color)}"
                    style="width:44px;height:36px;padding:2px;border-radius:6px;cursor:pointer;border:1px solid var(--bd);"
                    oninput="updateLabelPreview()">
                  <input type="text" id="inp-lbl-color-txt" value="{_html.escape(lbl_color)}"
                    style="width:90px;font-size:13px;padding:5px 8px;"
                    oninput="syncColor('inp-lbl-color','inp-lbl-color-txt');updateLabelPreview()">
                </div>
              </div>
              <div style="padding-bottom:4px;">
                <label style="font-size:12px;">{t('admin.appearance_preview')}</label>
                <div style="margin-top:6px;background:var(--nav-bg);border:1px solid var(--bd);border-radius:6px;padding:6px 10px;display:inline-flex;align-items:center;gap:8px;">
                  <span style="font-size:13px;font-weight:700;">Zeiterfassung</span>
                  {lbl_preview}
                </div>
              </div>
            </div>

            <hr style="margin:14px 0;">

            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
              <button class="btn btn-sm" type="button"
                onclick="setPreset('#2563eb','','','#f59e0b');document.getElementById('inp-label').value='';updateLabelPreview();document.getElementById('appearance-form').submit();">
                {t('admin.appearance_reset')}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
<script>
function applyPreview(){{
  var ac=document.getElementById('inp-accent');
  var nav=document.getElementById('inp-nav');
  if(ac)document.getElementById('inp-accent-txt').value=ac.value;
  if(nav)document.getElementById('inp-nav-txt').value=nav.value;
  if(ac)document.documentElement.style.setProperty('--ac',ac.value);
  if(nav)document.documentElement.style.setProperty('--nav-bg',nav.value||'var(--sf)');
}}
function syncColor(pickerId,textId){{
  var txt=document.getElementById(textId);
  var m=txt.value.match(/^#[0-9a-fA-F]{{3,8}}$/);
  if(m){{document.getElementById(pickerId).value=txt.value.slice(0,7);}}
  applyPreview();
}}
function setPreset(accent,nav,label,lblColor){{
  var ai=document.getElementById('inp-accent');
  var ni=document.getElementById('inp-nav');
  var li=document.getElementById('inp-label');
  var lc=document.getElementById('inp-lbl-color');
  if(ai){{ai.value=accent;document.getElementById('inp-accent-txt').value=accent;}}
  if(ni){{ni.value=nav||'#f9fafb';document.getElementById('inp-nav-txt').value=nav;}}
  if(li)li.value=label||'';
  if(lc){{lc.value=lblColor;document.getElementById('inp-lbl-color-txt').value=lblColor;}}
  applyPreview();
  updateLabelPreview();
}}
function updateLabelPreview(){{
  var txt=document.getElementById('inp-label');
  var clr=document.getElementById('inp-lbl-color');
  var prev=document.getElementById('lbl-preview');
  if(!prev)return;
  var label=(txt?txt.value:'').trim().toUpperCase()||'VORSCHAU';
  prev.textContent=label;
  if(clr)prev.style.background=clr.value;
}}
</script>"""


@admin_bp.get("/admin/absences")
@admin_required
def admin_absences():
    from app import bootstrap, flash_html, layout, _render_admin_absences_section
    bootstrap()
    u = current_user()
    today = datetime.date.today()
    year = today.year
    try:
        year = int(request.args.get("abs_year") or year)
    except (ValueError, TypeError):
        pass
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"
    abs_from = (request.args.get("abs_from") or year_start).strip()
    abs_to = (request.args.get("abs_to") or year_end).strip()
    sel_uid_str = (request.args.get("abs_uid") or "").strip()

    db = connect()
    active_users = db.execute(
        "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY display_name, username"
    ).fetchall()
    db.close()

    sel_uid = int(sel_uid_str) if sel_uid_str.isdigit() else (active_users[0]["id"] if active_users else None)
    sel_user_name = next(
        ((_html.escape(r["display_name"] or r["username"])) for r in active_users if r["id"] == sel_uid), "–"
    )
    body = f"{flash_html()}{_render_admin_absences_section()}"
    return render_template_string(layout(f"{t('admin.title')}: {t('periods.title')}", body, u, APP_VERSION))


@admin_bp.get("/admin/absences/export")
@admin_required
def admin_absences_export():
    from app import bootstrap, _fmt_vac_days, _count_absence_workdays
    bootstrap()
    today = datetime.date.today()
    year = today.year
    try:
        year = int(request.args.get("abs_year") or year)
    except (ValueError, TypeError):
        pass
    year_start = f"{year}-01-01"
    year_end = f"{year}-12-31"
    abs_from = (request.args.get("from") or year_start).strip()
    abs_to = (request.args.get("to") or year_end).strip()
    uid_str = (request.args.get("uid") or "").strip()

    db = connect()
    if uid_str.isdigit():
        users = db.execute(
            "SELECT id, username, display_name FROM users WHERE id=? AND is_active=1", (int(uid_str),)
        ).fetchall()
    else:
        users = db.execute(
            "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY display_name, username"
        ).fetchall()

    rows_out = []
    for u_row in users:
        uid = u_row["id"]
        name = u_row["display_name"] or u_row["username"]
        abs_list = db.execute(
            """SELECT a.date_from, a.date_to, a.is_half_day, a.comment, t.name AS type_name
               FROM absences a JOIN absence_types t ON a.type_id = t.id
               WHERE a.user_id = ? AND a.date_to >= ? AND a.date_from <= ?
               ORDER BY a.date_from""",
            (uid, abs_from, abs_to),
        ).fetchall()
        for row in abs_list:
            df = str(row["date_from"])[:10]
            dt = str(row["date_to"])[:10]
            half = int(row["is_half_day"] or 0)
            cmt = (row["comment"] or "").strip()
            tname = row["type_name"]
            disp_type = cmt if (tname == "Sonstige" and cmt) else tname
            days = _count_absence_workdays(uid, df, dt, half)
            rows_out.append((name, df, dt, disp_type, _fmt_vac_days(days), cmt if tname != "Sonstige" else ""))
    db.close()

    import io as _io
    buf = _io.BytesIO()
    buf.write(b"\xef\xbb\xbf")  # UTF-8 BOM for Excel
    header = "Name;Datum Von;Datum Bis;Typ;Arbeitstage;Bemerkung\r\n"
    buf.write(header.encode("utf-8"))
    for cols in rows_out:
        line = ";".join(c.replace(";", ",") for c in cols) + "\r\n"
        buf.write(line.encode("utf-8"))
    buf.seek(0)
    fname = f"abwesenheiten_{abs_from}_{abs_to}.csv"
    return send_file(buf, mimetype="text/csv", as_attachment=True, download_name=fname)


@admin_bp.post("/admin/appearance")
@sysadmin_required
def admin_appearance_save():
    from app import bootstrap, add_flash, _HEX_COLOR_RE
    bootstrap()
    accent    = (request.form.get("accent_color") or "").strip()
    nav_color = (request.form.get("nav_color") or "").strip()
    app_label = (request.form.get("app_label") or "").strip()[:10]
    lbl_color = (request.form.get("app_label_color") or "").strip()
    db = connect()
    for key, val in [
        ("accent_color", accent if _HEX_COLOR_RE.match(accent) else "#2563eb"),
        ("nav_color",    nav_color if (_HEX_COLOR_RE.match(nav_color) if nav_color else True) else ""),
        ("app_label",    app_label),
        ("app_label_color", lbl_color if _HEX_COLOR_RE.match(lbl_color) else "#f59e0b"),
    ]:
        db.execute(
            "INSERT OR REPLACE INTO app_config(key, value, updated_at) VALUES(?, ?, datetime('now'))",
            (key, val),
        )
    db.commit()
    db.close()
    add_flash(t("flash.success.appearance_saved"), "success")
    return redirect("/admin#acc-appearance")


@admin_bp.post("/admin/server-config")
@sysadmin_required
def admin_server_config_save():
    from app import bootstrap, add_flash, _COMMON_TIMEZONES
    bootstrap()
    base_url = (request.form.get("base_url") or "").strip().rstrip("/")
    chosen_tz = (request.form.get("timezone") or "Europe/Berlin").strip()
    if chosen_tz not in [v for v, _ in _COMMON_TIMEZONES]:
        chosen_tz = "Europe/Berlin"
    db = connect()
    db.execute(
        "INSERT OR REPLACE INTO app_config(key, value, updated_at) VALUES(?, ?, datetime('now'))",
        ("base_url", base_url),
    )
    db.execute(
        "INSERT OR REPLACE INTO app_config(key, value, updated_at) VALUES(?, ?, datetime('now'))",
        ("timezone", chosen_tz),
    )
    db.commit()
    db.close()
    from flask import g as _g
    if hasattr(_g, "_app_config_cache"):
        del _g._app_config_cache
    add_flash(t("settings.saved"), "success")
    return redirect("/admin#acc-regional")


@admin_bp.post("/admin/regional")
@sysadmin_required
def admin_regional_save():
    from app import bootstrap, add_flash
    bootstrap()
    region = (request.form.get("default_holiday_region") or "DE-NW").strip()
    if region not in ALL_REGIONS:
        region = "DE-NW"
    db = connect()
    db.execute(
        "INSERT OR REPLACE INTO app_config(key, value, updated_at) VALUES(?, ?, datetime('now'))",
        ("default_holiday_region", region),
    )
    db.commit()
    db.close()
    from flask import g as _g
    if hasattr(_g, "_app_config_cache"):
        del _g._app_config_cache
    add_flash(t("flash.success.regional_saved"), "success")
    return redirect("/admin#acc-regional")


@admin_bp.route("/admin/teams", methods=["GET", "POST"])
@timemanager_required
def admin_teams():
    from app import bootstrap, add_flash, layout, _send_mail_simple, _feature_enabled
    bootstrap()
    db = connect()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            name  = request.form.get("name", "").strip()
            desc  = request.form.get("description", "").strip()
            color = request.form.get("color", "#4a9eff").strip()
            if name:
                db.execute(
                    "INSERT INTO teams (name, description, color) VALUES (?,?,?)",
                    (name, desc, color)
                )
                db.commit()
                add_flash(t("success.team_created"), "success")
        elif action == "delete":
            tid = int(request.form.get("team_id", 0))
            db.execute("DELETE FROM teams WHERE id=?", (tid,))
            db.commit()
            add_flash(t("success.team_deleted"), "success")
        elif action == "edit":
            tid           = int(request.form.get("team_id", 0))
            name          = request.form.get("name", "").strip()
            desc          = request.form.get("description", "").strip()
            color         = request.form.get("color", "#4a9eff").strip()
            holiday_region = request.form.get("holiday_region", "").strip() or None
            if tid and name:
                db.execute(
                    "UPDATE teams SET name=?, description=?, color=?, holiday_region=? WHERE id=?",
                    (name, desc, color, holiday_region, tid)
                )
                db.commit()
                add_flash(t("success.team_updated"), "success")
        elif action == "members":
            tid = int(request.form.get("team_id", 0))
            user_ids = request.form.getlist("user_ids")
            db.execute("DELETE FROM user_teams WHERE team_id=?", (tid,))
            for uid in user_ids:
                db.execute(
                    "INSERT OR IGNORE INTO user_teams (user_id, team_id) VALUES (?,?)",
                    (int(uid), tid)
                )
            db.commit()
            add_flash(t("success.team_updated"), "success")
        db.close()
        return redirect(url_for("admin.admin_home") + "#acc-teams")

    db.close()
    return redirect(url_for("admin.admin_home") + "?tab=users")


_MONTH_NAMES = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
                "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _get_staffing_week_data(plan_id: int) -> dict:
    today    = datetime.date.today()
    week_arg = request.args.get("week", "")
    try:
        monday = datetime.date.fromisoformat(week_arg) if week_arg else None
    except ValueError:
        monday = None
    if monday is None:
        monday = today - datetime.timedelta(days=today.weekday())

    days = [monday + datetime.timedelta(days=i) for i in range(5)]

    db = connect()
    slots = db.execute(
        "SELECT * FROM staffing_slots WHERE plan_id=? ORDER BY COALESCE(time_from,'99:99'), sort_order",
        (plan_id,)
    ).fetchall()
    assignments = db.execute("""
        SELECT sa.*, u.username, u.display_name
        FROM staffing_assignments sa
        JOIN users u ON u.id = sa.user_id
        WHERE sa.slot_id IN (SELECT id FROM staffing_slots WHERE plan_id=?)
    """, (plan_id,)).fetchall()

    assign_map = {}
    for a in assignments:
        assign_map.setdefault(a["slot_id"], []).append(a)

    user_ids = list({a["user_id"] for a in assignments})
    absences = []
    if user_ids:
        ph     = ",".join("?" * len(user_ids))
        d_from = days[0].isoformat()
        d_to   = days[-1].isoformat()
        absences = db.execute(
            f"SELECT user_id, date_from, date_to FROM absences "
            f"WHERE user_id IN ({ph}) AND date_from <= ? AND date_to >= ?",
            (*user_ids, d_to, d_from)
        ).fetchall()
    try:
        _plan_row = db.execute("SELECT lead_label FROM staffing_plans WHERE id=?", (plan_id,)).fetchone()
        lead_label = (_plan_row["lead_label"] if _plan_row and _plan_row["lead_label"] else None) or "Leiter"
    except Exception:
        lead_label = "Leiter"
    db.close()

    _voc_cache_w: dict = {}

    def is_absent(uid, iso):
        if any(
            ab["user_id"] == uid and ab["date_from"] <= iso <= ab["date_to"]
            for ab in absences
        ):
            return True
        key = (uid, iso)
        if key not in _voc_cache_w:
            voc = _get_vocational_school_entry(uid, iso)
            is_voc_active = False
            if voc and not _is_holiday(iso, uid):
                if voc["schedule_type"] == "weekly" and _is_school_holiday(iso, uid):
                    is_voc_active = False  # Schulferien → Berufsschule entfällt
                else:
                    is_voc_active = True
            _voc_cache_w[key] = bool(
                is_voc_active and not (voc.get("work_time_from") and voc.get("work_time_to"))
            )
        return _voc_cache_w[key]

    result = {"monday": monday, "days": days, "slots": [], "lead_label": lead_label}
    for slot in slots:
        slot_days = []
        tf = slot["time_from"]
        tt = slot["time_to"]
        for day in days:
            iso = day.isoformat()
            if not _slot_applies_on_date(slot, iso, plan_id=plan_id):
                slot_days.append(None)
                continue
            assigned_list = assign_map.get(slot["id"], [])
            present = []
            absent  = []
            for a in assigned_list:
                uid = a["user_id"]
                if is_absent(uid, iso):
                    absent.append(a)
                elif tf and tt:
                    if _user_works_in_slot(uid, iso, tf, tt):
                        present.append(a)
                else:
                    present.append(a)
            count         = len(present)
            min_s         = slot["min_staff"]
            min_l         = int(slot["min_lead"] or 0)
            lead_present  = [a for a in present if int(a["is_lead"] or 0)]
            staff_present = [a for a in present if not int(a["is_lead"] or 0)]
            lead_missing  = (min_l > 0 and len(lead_present) == 0)
            lead_ok       = len(lead_present) >= min_l if min_l > 0 else True
            status        = "ok" if (count >= min_s and lead_ok) else ("warn" if count > 0 else "empty")
            slot_days.append({
                "present":       present,
                "lead_present":  lead_present,
                "staff_present": staff_present,
                "absent":        absent,
                "count":         count,
                "min_staff":     min_s,
                "min_lead":      min_l,
                "lead_missing":  lead_missing,
                "status":        status,
                "slot_role":     slot["slot_role"] or "staff",
            })
        result["slots"].append({"slot": slot, "days": slot_days})
    return result


def _get_staffing_month_data(plan_id: int) -> dict:
    today = datetime.date.today()
    year  = request.args.get("y", type=int, default=today.year)
    month = request.args.get("m", type=int, default=today.month)

    days_in_month = calendar.monthrange(year, month)[1]
    days = [datetime.date(year, month, d) for d in range(1, days_in_month + 1)]

    db = connect()
    slots = db.execute(
        "SELECT * FROM staffing_slots WHERE plan_id=? ORDER BY COALESCE(time_from,'99:99'), sort_order",
        (plan_id,)
    ).fetchall()
    assignments = db.execute("""
        SELECT sa.*, u.username, u.display_name
        FROM staffing_assignments sa
        JOIN users u ON u.id = sa.user_id
        WHERE sa.slot_id IN (SELECT id FROM staffing_slots WHERE plan_id=?)
    """, (plan_id,)).fetchall()

    assign_map = {}
    for a in assignments:
        assign_map.setdefault(a["slot_id"], []).append(a)

    user_ids = list({a["user_id"] for a in assignments})
    absences = []
    if user_ids:
        ph     = ",".join("?" * len(user_ids))
        d_from = days[0].isoformat()
        d_to   = days[-1].isoformat()
        absences = db.execute(
            f"SELECT user_id, date_from, date_to FROM absences "
            f"WHERE user_id IN ({ph}) AND date_from <= ? AND date_to >= ?",
            (*user_ids, d_to, d_from)
        ).fetchall()
    # Accepted dates – query before closing connection
    try:
        _acc_rows = db.execute(
            "SELECT iso_date FROM staffing_day_accepted WHERE plan_id=? "
            "AND iso_date BETWEEN ? AND ?",
            (plan_id, days[0].isoformat(), days[-1].isoformat())
        ).fetchall()
        accepted_dates = {r["iso_date"] for r in _acc_rows}
    except Exception:
        accepted_dates = set()
    try:
        _plan_row_m = db.execute("SELECT lead_label FROM staffing_plans WHERE id=?", (plan_id,)).fetchone()
        lead_label_m = (_plan_row_m["lead_label"] if _plan_row_m and _plan_row_m["lead_label"] else None) or "Leiter"
    except Exception:
        lead_label_m = "Leiter"
    db.close()

    _voc_cache_m: dict = {}

    def is_absent(uid, iso):
        if any(
            ab["user_id"] == uid and ab["date_from"] <= iso <= ab["date_to"]
            for ab in absences
        ):
            return True
        key = (uid, iso)
        if key not in _voc_cache_m:
            voc = _get_vocational_school_entry(uid, iso)
            is_voc_active = False
            if voc and not _is_holiday(iso, uid):
                if voc["schedule_type"] == "weekly" and _is_school_holiday(iso, uid):
                    is_voc_active = False  # Schulferien → Berufsschule entfällt
                else:
                    is_voc_active = True
            _voc_cache_m[key] = bool(
                is_voc_active and not (voc.get("work_time_from") and voc.get("work_time_to"))
            )
        return _voc_cache_m[key]

    result = {"year": year, "month": month, "days": [], "accepted_dates": accepted_dates,
              "lead_label": lead_label_m}
    for day in days:
        iso = day.isoformat()
        day_slots = []
        has_warning = False
        for slot in slots:
            if not _slot_applies_on_date(slot, iso, plan_id=plan_id):
                continue
            assigned_list = assign_map.get(slot["id"], [])
            tf = slot["time_from"]
            tt = slot["time_to"]
            present_count = 0
            lead_count    = 0
            for a in assigned_list:
                uid = a["user_id"]
                if is_absent(uid, iso):
                    continue
                if tf and tt:
                    if _user_works_in_slot(uid, iso, tf, tt):
                        present_count += 1
                        if int(a["is_lead"] or 0):
                            lead_count += 1
                else:
                    present_count += 1
                    if int(a["is_lead"] or 0):
                        lead_count += 1
            min_s        = slot["min_staff"]
            min_l        = int(slot["min_lead"] or 0)
            lead_missing = (min_l > 0 and lead_count == 0)
            lead_ok      = lead_count >= min_l if min_l > 0 else True
            status       = "ok" if (present_count >= min_s and lead_ok) else ("warn" if present_count > 0 else "empty")
            if status != "ok" or lead_missing:
                has_warning = True
            day_slots.append({"label": slot["label"], "count": present_count,
                               "min_staff": min_s, "status": status,
                               "time_from": slot["time_from"], "time_to": slot["time_to"],
                               "slot_role": slot["slot_role"] or "staff",
                               "lead_missing": lead_missing})
        result["days"].append({"date": day, "iso": iso,
                                "slots": day_slots, "has_warning": has_warning})
    return result


def _render_staffing_week(data: dict, plan_id: int) -> str:
    monday = data["monday"]
    days   = data["days"]
    today  = datetime.date.today()
    lead_label = data.get("lead_label", "Leiter")

    prev_mon = (monday - datetime.timedelta(days=7)).isoformat()
    next_mon = (monday + datetime.timedelta(days=7)).isoformat()
    this_mon = (today - datetime.timedelta(days=today.weekday())).isoformat()
    kw       = monday.isocalendar()[1]
    d_from   = monday.strftime("%d.%m")
    d_to     = (monday + datetime.timedelta(days=4)).strftime("%d.%m.%Y")

    nav = (
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;flex-wrap:wrap;">'
        f'<a href="/staffing?plan_id={plan_id}&view=week&week={prev_mon}" class="btn btn-sm">◀</a>'
        f'<strong>KW {kw} &nbsp;{d_from}–{d_to}</strong>'
        f'<a href="/staffing?plan_id={plan_id}&view=week&week={next_mon}" class="btn btn-sm">▶</a>'
        f'<a href="/staffing?plan_id={plan_id}&view=week&week={this_mon}" class="btn btn-sm">Heute</a>'
        f'</div>'
    )

    _WD = ["Mo", "Di", "Mi", "Do", "Fr"]
    _SI = {"ok": "✅", "warn": "⚠️", "empty": "❌"}
    _SC = {"ok": "#16a34a", "warn": "#d97706", "empty": "#dc2626"}

    th = "<th style='padding:6px 10px;text-align:left;border-bottom:2px solid rgba(128,128,128,0.5);background:var(--ca);'></th>"
    _hol_cache = {day.isoformat(): _is_holiday_for_plan(day.isoformat(), plan_id) for day in days}
    _hol_names = {}
    try:
        _hdb = connect()
        _hregion = _get_team_holiday_region(plan_id)
        for _d in days:
            _iso = _d.isoformat()
            _hr = _hdb.execute(
                "SELECT name FROM calendar_days WHERE day=? AND region=? AND is_holiday=1",
                (_iso, _hregion)
            ).fetchone()
            if _hr:
                _hol_names[_iso] = _hr["name"]
        _hdb.close()
    except Exception:
        pass
    for day in days:
        _day_iso = day.isoformat()
        _is_hol = _hol_cache.get(_day_iso, False)
        if _is_hol:
            today_bg = "background:color-mix(in srgb,#dc2626 8%,var(--ca));"
            _date_style = "color:#dc2626;font-weight:700;"
            _hol_hint = f"<div style='font-size:10px;color:#dc2626;'>{_html.escape(_hol_names.get(_day_iso,'Feiertag'))}</div>"
        elif day == today:
            today_bg = "background:color-mix(in srgb,var(--ac) 12%,var(--ca));"
            _date_style = ""
            _hol_hint = ""
        else:
            today_bg = "background:var(--ca);"
            _date_style = ""
            _hol_hint = ""
        th += (f"<th style='padding:6px 10px;text-align:center;white-space:nowrap;"
               f"border-bottom:2px solid rgba(128,128,128,0.5);border-left:2px solid rgba(128,128,128,0.35);cursor:pointer;{today_bg}' "
               f"onclick=\"location.href='/staffing/day?date={_day_iso}&plan_id={plan_id}'\">"
               f"<span style='{_date_style}'>{_WD[day.weekday()]} {day.strftime('%d.%m')}</span>{_hol_hint}</th>")

    rows = ""
    for slot_idx, entry in enumerate(data["slots"]):
        slot = entry["slot"]
        row_bg = "background:var(--bg);" if slot_idx % 2 == 0 else "background:color-mix(in srgb,var(--ca) 50%,var(--bg));"
        _slot_time_div = (
            f"<div style='font-size:10px;color:var(--mu);margin-top:2px;'>{slot['time_from']}–{slot['time_to']}</div>"
            if slot["time_from"] and slot["time_to"] else ""
        )
        _min_lead_hint = (
            f'<span style="font-size:10px;color:#eab308;margin-left:4px;" '
            f'title="{_html.escape(lead_label)}">♦≥{slot["min_lead"]}</span>'
            if int(slot["min_lead"] or 0) > 0 else ""
        )
        cells = (
            f"<td style='padding:6px 10px;font-size:13px;"
            f"border-right:2px solid var(--br);min-width:120px;background:var(--ca);'>"
            f"<div><strong>{_html.escape(slot['label'])}</strong>{_min_lead_hint}</div>"
            f"{_slot_time_div}"
            f"<div style='font-size:11px;color:var(--mu);'>{slot['slot_type'].upper()}</div></td>"
        )
        for di, day_data in enumerate(entry["days"]):
            day_iso   = days[di].isoformat()
            _r_border = "" if di == 4 else "border-right:2px solid rgba(128,128,128,0.35);"
            _hol_bg   = "background:color-mix(in srgb,#6b7280 15%,var(--bg));" if _hol_cache.get(day_iso) else row_bg
            if day_data is None:
                cells += (f"<td style='padding:6px 10px;{_hol_bg}{_r_border}cursor:pointer;'"
                          f" onclick=\"location.href='/staffing/day?date={day_iso}&plan_id={plan_id}'\"></td>")
                continue
            status    = day_data["status"]
            color     = "#dc2626" if day_data.get("lead_missing") else _SC[status]
            _badge_bg = {"ok": "#16a34a", "warn": "#d97706", "empty": "#dc2626"}[status]
            lead_html = " ".join(
                f'<span style="background:#eab308;color:#000;border-radius:3px;'
                f'padding:1px 5px;font-size:11px;white-space:nowrap;"'
                f' title="{_html.escape(lead_label)}: {_html.escape((a["display_name"] or a["username"] or "?"))}">'
                f'♦ {_html.escape((a["display_name"] or a["username"] or "?")[:8])}</span>'
                for a in day_data.get("lead_present", [])
            )
            staff_html = " ".join(
                f'<span style="background:#16a34a;color:#fff;border-radius:3px;'
                f'padding:1px 5px;font-size:11px;white-space:nowrap;">'
                f'{_html.escape((a["display_name"] or a["username"] or "?")[:10])}</span>'
                for a in day_data.get("staff_present", [])
            )
            def _absent_badge(a):
                return (
                    f'<span style="background:#dc2626;color:#fff;border-radius:3px;'
                    f'padding:1px 5px;font-size:11px;text-decoration:line-through;white-space:nowrap;">'
                    f'{_html.escape((a["display_name"] or a["username"] or "?")[:10])}</span>'
                )
            lead_absent_html = " ".join(
                _absent_badge(a) for a in day_data["absent"]
                if int(a["is_lead"] or 0)
            )
            staff_absent_html = " ".join(
                _absent_badge(a) for a in day_data["absent"]
                if not int(a["is_lead"] or 0)
            )
            _lead_warn = (
                f'<div style="font-size:11px;color:#dc2626;margin-top:2px;">'
                f'⚠️ Kein {_html.escape(lead_label)} anwesend</div>'
                if day_data.get("lead_missing") else ""
            )
            _lead_row = (
                f'<div style="display:flex;flex-wrap:wrap;gap:3px;">'
                f'{lead_html}{lead_absent_html}</div>'
                if (lead_html or lead_absent_html) else ""
            )
            _staff_row = (
                f'<div style="display:flex;flex-wrap:wrap;gap:3px;margin-top:2px;">'
                f'{staff_html}{staff_absent_html}</div>'
                if (staff_html or staff_absent_html) else ""
            )
            cells += (
                f"<td style='padding:6px 10px;border-left:3px solid {color};{_r_border}{_hol_bg}cursor:pointer;'"
                f" onclick=\"location.href='/staffing/day?date={day_iso}&plan_id={plan_id}'\">"
                f'<div style="display:inline-block;background:{_badge_bg};color:#fff;'
                f'border-radius:4px;padding:1px 7px;font-size:12px;font-weight:700;margin-bottom:4px;">'
                f'{day_data["count"]}/{day_data["min_staff"]} {_SI[status]}</div>'
                f'{_lead_row}{_staff_row}'
                f'{_lead_warn}'
                f'</td>'
            )
        rows += f"<tr style='border-bottom:1px solid rgba(128,128,128,0.2);'>{cells}</tr>"

    if not rows:
        rows = f"<tr><td colspan='6' style='padding:1rem;color:var(--mu);'>{t('staffing.no_slots')}</td></tr>"

    return f"""{nav}
    <div style="overflow-x:auto;">
      <div style="border:2px solid rgba(128,128,128,0.35);border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <thead><tr>{th}</tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>"""


def _render_staffing_month(data: dict, plan_id: int) -> str:
    year  = data["year"]
    month = data["month"]
    today = datetime.date.today()
    lead_label = data.get("lead_label", "Leiter")

    prev_y, prev_m = (year, month - 1) if month > 1 else (year - 1, 12)
    next_y, next_m = (year, month + 1) if month < 12 else (year + 1, 1)

    nav = (
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">'
        f'<a href="/staffing?plan_id={plan_id}&view=month&y={prev_y}&m={prev_m}" class="btn btn-sm">◀</a>'
        f'<strong>{_MONTH_NAMES[month]} {year}</strong>'
        f'<a href="/staffing?plan_id={plan_id}&view=month&y={next_y}&m={next_m}" class="btn btn-sm">▶</a>'
        f'</div>'
    )

    wd_headers = "".join(
        f'<th style="padding:4px 6px;font-size:12px;color:var(--mu);text-align:center;'
        f'font-weight:600;">{d}</th>'
        for d in ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    )

    first_wd = data["days"][0]["date"].weekday()
    tds = ["<td></td>"] * first_wd
    accepted_dates = data.get("accepted_dates", set())

    _SI = {"ok": "✅", "warn": "⚠️", "empty": "❌"}

    def _slot_badge_color(status):
        if status == "ok":   return "#16a34a"
        if status == "warn": return "#d97706"
        return "#dc2626"

    for day_data in data["days"]:
        day  = day_data["date"]
        iso  = day_data["iso"]
        is_we     = day.weekday() >= 5
        is_today  = day == today
        warn      = day_data["has_warning"]
        is_accepted = iso in accepted_dates
        if warn and not is_accepted:
            any_empty = any(s["status"] == "empty" or s.get("lead_missing") for s in day_data["slots"])
            border = "border:2px solid #dc2626;background:rgba(220,38,38,0.05);" if any_empty \
                     else "border:2px solid #d97706;background:rgba(217,119,6,0.05);"
        elif is_accepted and warn:
            border = "border:1px solid #16a34a;background:rgba(22,163,74,0.04);"
        else:
            border = "border:1px solid var(--br);"
        bg        = "background:var(--ca);" if is_we else ""
        today_ol  = "outline:2px solid var(--ac);outline-offset:-2px;" if is_today else ""
        accepted_badge = '<span style="float:right;font-size:9px;color:#16a34a;font-weight:700;">✓</span>' if is_accepted else ""

        slot_lines = ""
        for s in day_data["slots"]:
            slot_lines += (
                f'<div style="font-size:10px;line-height:1.6;white-space:nowrap;'
                f'color:{_slot_badge_color(s["status"])};font-weight:600;">'
                f'{_html.escape(s["label"])} '
                f'{s["count"]}/{s["min_staff"]} {_SI[s["status"]]}'
                f'</div>'
            )
            if s.get("lead_missing"):
                slot_lines += (
                    f'<div style="font-size:9px;color:#dc2626;white-space:nowrap;">'
                    f'⚠️ Kein {_html.escape(lead_label)}</div>'
                )
        tds.append(
            f'<td style="padding:4px;vertical-align:top;cursor:pointer;{border}{bg}{today_ol}'
            f"min-width:72px;\" onclick=\"location.href='/staffing/day?date={iso}&plan_id={plan_id}'\">"
            f'<div style="font-size:11px;font-weight:700;margin-bottom:2px;">'
            f'{day.day}{accepted_badge}</div>'
            f'{slot_lines}</td>'
        )

    # Pad to full weeks and build rows
    while len(tds) % 7:
        tds.append("<td style='background:var(--ca);'></td>")

    rows = ""
    for i in range(0, len(tds), 7):
        rows += "<tr>" + "".join(tds[i:i+7]) + "</tr>"

    return f"""{nav}
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;table-layout:fixed;">
        <thead><tr>{wd_headers}</tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


def _render_staffing_view(plans, plan_id, view, data, u) -> str:
    plan_opts = "".join(
        f'<option value="{p["id"]}"{"  selected" if p["id"] == plan_id else ""}>'
        f'{_html.escape(p["team_name"])} – {_html.escape(p["name"])}</option>'
        for p in plans
    )
    plan_selector = (
        f'<form method="get" action="/staffing" style="display:inline-flex;gap:6px;align-items:center;">'
        f'<select name="plan_id" onchange="this.form.submit()" style="font-size:13px;">'
        f'{plan_opts}</select>'
        f'<input type="hidden" name="view" value="{view}">'
        f'</form>'
    ) if plans else ""

    view_btns = (
        f'<a href="/staffing?plan_id={plan_id or ""}&view=week" '
        f'class="btn btn-sm{"  primary" if view=="week" else ""}">{t("staffing.week_view")}</a> '
        f'<a href="/staffing?plan_id={plan_id or ""}&view=month" '
        f'class="btn btn-sm{"  primary" if view=="month" else ""}">{t("staffing.month_view")}</a>'
    )

    if not plans:
        body_html = f'<p style="color:var(--mu);margin-top:1rem;">{t("staffing.no_plans")}</p>'
    elif view == "week":
        body_html = _render_staffing_week(data, plan_id)
    else:
        body_html = _render_staffing_month(data, plan_id)

    manage_link = ""
    if u.get("admin_role") in ("sysadmin", "timemanager", "hr"):
        manage_link = (
            f'<a href="/admin/staffing" class="btn btn-sm" style="margin-left:8px;">'
            f'⚙ {t("staffing.manage_plans")}</a>'
        )

    _is_readonly = u.get("admin_role") not in ("sysadmin", "timemanager", "hr") and not u.get("is_approver")
    readonly_hint = (
        f'<div class="small" style="color:var(--mu);margin-bottom:8px;">'
        f'ℹ {t("staffing.readonly_hint")}</div>'
    ) if _is_readonly else ""

    return f"""
    <div style="max-width:960px;margin:1rem auto;">
      <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:1.25rem;">
        <h2 style="margin:0;">{t('nav.staffing')}</h2>
        {plan_selector}
        <div style="display:flex;gap:4px;">{view_btns}</div>
        {manage_link}
      </div>
      {readonly_hint}
      {body_html}
    </div>"""


def _render_staffing_day(iso_date, d, plan, plan_id, slot_data,
                          team_users, absent_ids, absences,
                          overrides, accepted, u) -> str:
    _WD_NAMES = [t("wd.mon"), t("wd.tue"), t("wd.wed"), t("wd.thu"),
                 t("wd.fri"), t("wd.sat"), t("wd.sun")]
    prev_d   = (d - datetime.timedelta(days=1)).isoformat()
    next_d   = (d + datetime.timedelta(days=1)).isoformat()
    wd_name  = _WD_NAMES[d.weekday()]
    date_str = d.strftime("%d.%m.%Y")

    lead_label = (plan["lead_label"] if plan and "lead_label" in plan.keys() and plan["lead_label"] else "Leiter")

    # Pre-resolve all t() calls — avoids issues inside nested f-strings
    _lbl_present   = t("staffing.present")
    _lbl_absent    = t("staffing.absent")
    _lbl_override  = t("staffing.override_title")
    _lbl_assign    = t("staffing.override_assign")
    _lbl_request   = t("staffing.override_request")
    _lbl_confirm   = t("staffing.override_require_confirm")
    _lbl_note      = t("staffing.override_note")
    _lbl_dates     = t("staffing.override_dates")
    _lbl_accept    = t("staffing.accept_day")
    _lbl_acpt_note = t("staffing.accept_note")
    _lbl_acpt_bdg  = t("staffing.accepted_badge")

    def _row_name(a):
        return a["display_name"] or a["username"] or "?"

    def _row_uid(a):
        try:
            return a["user_id"]
        except (IndexError, KeyError):
            return None

    def _row_has(a, key):
        try:
            return bool(a[key])
        except (IndexError, KeyError):
            return False

    accepted_html = ""
    if accepted:
        note_txt = _html.escape(accepted["note"] or "")
        accepted_html = (
            f'<span style="background:#16a34a;color:#fff;border-radius:4px;'
            f'padding:2px 10px;font-size:12px;font-weight:600;">'
            f'{_lbl_acpt_bdg}'
            f'{(" – " + note_txt) if note_txt else ""}</span>'
        )
    else:
        has_warn = any(s["status"] != "ok" for s in slot_data)
        if has_warn:
            accepted_html = (
                f'<form method="post" action="/staffing/day/accept" style="display:inline;">'
                f'<input type="hidden" name="date" value="{iso_date}">'
                f'<input type="hidden" name="plan_id" value="{plan_id}">'
                f'<input type="text" name="note" placeholder="{_lbl_acpt_note}"'
                f' style="font-size:12px;padding:3px 8px;margin-right:4px;width:180px;">'
                f'<button class="btn btn-sm" type="submit"'
                f' style="background:#d97706;color:#fff;">{_lbl_accept}</button>'
                f'</form>'
            )

    absence_map = {}
    for ab in absences:
        absence_map[ab["user_id"]] = _html.escape(ab["typ"])

    _SI = {"ok": "✅", "warn": "⚠️", "empty": "❌"}
    _BC = {"ok": "#16a34a", "warn": "#d97706", "empty": "#dc2626"}

    slots_html = ""
    for sd in slot_data:
        slot     = sd["slot"]
        status   = sd["status"]
        count    = sd["count"]
        min_s    = sd["min_staff"]
        sid      = slot["id"]
        badge_bg = _BC[status]
        time_str = (f" {slot['time_from']}–{slot['time_to']}"
                    if slot["time_from"] and slot["time_to"] else "")

        present_rows = "".join(
            '<div style="padding:3px 0;display:flex;align-items:center;gap:6px;">'
            '<span style="background:#16a34a;color:#fff;border-radius:3px;'
            'padding:1px 6px;font-size:11px;">✓</span>'
            + _html.escape(_row_name(a))
            + (' <span style="font-size:10px;color:#a855f7;">⭐ Sonder</span>'
               if _row_has(a, "iso_date") else "")
            + '</div>'
            for a in sd["present"]
        ) or '<div style="color:var(--mu);font-size:12px;">–</div>'

        absent_rows = "".join(
            '<div style="padding:3px 0;display:flex;align-items:center;gap:6px;">'
            '<span style="background:#dc2626;color:#fff;border-radius:3px;'
            'padding:1px 6px;font-size:11px;">✗</span>'
            + _html.escape(_row_name(a))
            + f'<span style="font-size:10px;color:var(--mu);">'
              f'{absence_map.get(_row_uid(a) or 0, "")}</span>'
            + '</div>'
            for a in sd["absent"]
        ) if sd["absent"] else ""

        override_form = ""
        if status != "ok":
            present_uids = {_row_uid(a) for a in sd["present"]}
            avail_users = [
                u2 for u2 in team_users
                if u2["id"] not in absent_ids and u2["id"] not in present_uids
            ]
            user_opts = "".join(
                '<option value="' + str(u2["id"]) + '">'
                + _html.escape(u2["display_name"] or u2["username"]) + '</option>'
                for u2 in avail_users
            )
            day_checks = "".join(
                f'<label style="font-size:12px;display:flex;align-items:center;gap:3px;margin-right:6px;">'
                f'<input type="checkbox" name="dates"'
                f' value="{(d + datetime.timedelta(days=i)).isoformat()}"'
                f'{" checked" if i == 0 else ""}>'
                f'{_WD_NAMES[(d.weekday() + i) % 7]}'
                f' {(d + datetime.timedelta(days=i)).strftime("%d.%m")}'
                f'</label>'
                for i in range(7)
            )
            if avail_users:
                override_form = (
                    f'<div class="staff-section" style="margin-top:10px;padding-top:10px;'
                    f'border-top:1px solid var(--br);">'
                    f'<div style="font-size:11px;color:var(--mu);font-weight:600;margin-bottom:6px;">'
                    f'➕ {_lbl_override}</div>'
                    f'<form method="post" action="/staffing/day/override">'
                    f'<input type="hidden" name="date" value="{iso_date}">'
                    f'<input type="hidden" name="plan_id" value="{plan_id}">'
                    f'<input type="hidden" name="slot_id" value="{sid}">'
                    f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;align-items:flex-end;">'
                    f'<div><label style="font-size:11px;color:var(--mu);">Mitarbeiter</label>'
                    f'<select name="user_id" style="display:block;margin-top:3px;font-size:13px;">'
                    f'{user_opts}</select></div>'
                    f'<div><label style="font-size:11px;color:var(--mu);">{_lbl_note}</label>'
                    f'<input type="text" name="note" maxlength="120"'
                    f' style="display:block;margin-top:3px;font-size:13px;min-width:160px;"></div>'
                    f'</div>'
                    f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;">'
                    f'<span style="font-size:11px;color:var(--mu);margin-right:4px;">{_lbl_dates}:</span>'
                    f'{day_checks}</div>'
                    f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">'
                    f'<label style="font-size:12px;display:flex;align-items:center;gap:4px;">'
                    f'<input type="checkbox" name="require_confirm" value="1"'
                    f' id="req-{sid}" onchange="(function(c){{'
                    f'var b=document.getElementById(\'ob-{sid}\');'
                    f'if(b)b.textContent=c.checked?\'{_lbl_request}\':\'{_lbl_assign}\';}}'
                    f')(this)">'
                    f'{_lbl_confirm}</label>'
                    f'<button class="btn primary btn-sm" type="submit"'
                    f' id="ob-{sid}">{_lbl_assign}</button>'
                    f'</div></form></div>'
                )

        absent_section = (
            f'<div class="staff-section">'
            f'<div class="staff-section-hdr">🏖 {_lbl_absent}</div>'
            f'{absent_rows}</div>'
        ) if absent_rows else ""

        slots_html += (
            f'<div class="slot-day-card status-{status}">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;">'
            f'<strong style="font-size:14px;">{_html.escape(slot["label"])}</strong>'
            f'<span style="font-size:12px;color:var(--mu);">{time_str}</span>'
            f'<span style="background:{badge_bg};color:#fff;border-radius:4px;'
            f'padding:1px 8px;font-size:12px;font-weight:700;margin-left:auto;">'
            f'{count}/{min_s} {_SI[status]}</span></div>'
            f'<div class="staff-section">'
            f'<div class="staff-section-hdr">✅ {_lbl_present} ({count})</div>'
            f'{present_rows}</div>'
            f'{absent_section}'
            f'{override_form}'
            f'</div>'
        )

    return f"""
    <style>
    .slot-day-card{{border-radius:8px;padding:1rem;margin-bottom:1rem;border:2px solid;}}
    .slot-day-card.status-ok   {{border-color:#16a34a;background:rgba(22,163,74,.05);}}
    .slot-day-card.status-warn {{border-color:#d97706;background:rgba(217,119,6,.05);}}
    .slot-day-card.status-empty{{border-color:#dc2626;background:rgba(220,38,38,.05);}}
    .staff-section{{margin-top:.5rem;font-size:13px;}}
    .staff-section-hdr{{font-size:11px;color:var(--mu);margin-bottom:4px;font-weight:600;text-transform:uppercase;}}
    </style>
    <div style="max-width:700px;margin:1rem auto;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:1rem;flex-wrap:wrap;">
        <a href="/staffing/day?date={prev_d}&plan_id={plan_id}" class="btn btn-sm">◀</a>
        <div>
          <strong style="font-size:16px;">{wd_name}, {date_str}</strong>
          <span style="font-size:13px;color:var(--mu);margin-left:8px;">{_html.escape(plan['name'])}</span>
        </div>
        <a href="/staffing/day?date={next_d}&plan_id={plan_id}" class="btn btn-sm">▶</a>
        <a href="/staffing?plan_id={plan_id}&view=month" class="btn btn-sm" style="margin-left:4px;">↩</a>
        <div style="margin-left:auto;">{accepted_html}</div>
      </div>
      {slots_html if slots_html else f'<p style="color:var(--mu);">{t("staffing.no_slots")}</p>'}
    </div>"""


def _render_override_respond(pending, u) -> str:
    if not pending:
        return f'<div style="max-width:600px;margin:1rem auto;"><p style="color:var(--mu);">{t("staffing.no_pending_overrides")}</p></div>'

    rows = ""
    for o in pending:
        rows += f"""
        <div style="border:1px solid var(--br);border-radius:8px;padding:14px;margin-bottom:12px;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">
            <div>
              <strong>{_html.escape(o["plan_name"])}</strong>
              <span style="color:var(--mu);font-size:13px;margin-left:8px;">
                {_html.escape(o["team_name"])}
              </span><br>
              <span style="font-size:13px;">{o["iso_date"]} · {_html.escape(o["slot_label"])}</span>
              {('<br><span style="font-size:12px;color:var(--mu);">' + _html.escape(o["note"]) + '</span>') if o["note"] else ""}
            </div>
            <div style="display:flex;gap:6px;">
              <form method="post" action="/staffing/override/respond">
                <input type="hidden" name="override_id" value="{o['id']}">
                <input type="hidden" name="action" value="confirm">
                <button class="btn primary btn-sm" type="submit">✓ {t('staffing.override_confirmed')}</button>
              </form>
              <form method="post" action="/staffing/override/respond">
                <input type="hidden" name="override_id" value="{o['id']}">
                <input type="hidden" name="action" value="decline">
                <button class="btn btn-sm" type="submit" style="color:#dc2626;">✗ {t('staffing.override_declined')}</button>
              </form>
            </div>
          </div>
        </div>"""

    return f"""
    <div style="max-width:600px;margin:1rem auto;">
      <h2 style="margin-bottom:1rem;">{t('staffing.my_overrides')}</h2>
      {rows}
    </div>"""


@admin_bp.route("/admin/staffing", methods=["GET", "POST"])
@timemanager_required
def admin_staffing():
    from app import bootstrap, add_flash, _feature_enabled
    bootstrap()
    if not _feature_enabled("staffing"):
        abort(404)
    u = current_user()
    db = connect()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create_plan":
            name          = request.form.get("name", "").strip()
            team_id       = int(request.form.get("team_id", 0))
            desc          = request.form.get("description", "").strip()
            default_min_s = max(1, int(request.form.get("default_min_staff", 2) or 2))
            require_lead  = 1 if request.form.get("require_lead") else 0
            lead_label    = request.form.get("lead_label", "").strip() or "Leiter"
            if name and team_id:
                db.execute(
                    "INSERT INTO staffing_plans (team_id, name, description, "
                    "default_min_staff, require_lead, lead_label) VALUES (?,?,?,?,?,?)",
                    (team_id, name, desc, default_min_s, require_lead, lead_label)
                )
                db.commit()
                add_flash(t("success.plan_created"), "success")

        elif action == "edit_plan":
            _ep_pid        = int(request.form.get("plan_id", 0))
            _ep_lead_label = request.form.get("lead_label", "").strip() or "Leiter"
            if _ep_pid:
                db.execute(
                    "UPDATE staffing_plans SET lead_label=? WHERE id=?",
                    (_ep_lead_label, _ep_pid)
                )
                db.commit()
                add_flash(t("success.plan_updated"), "success")

        elif action == "create_slot":
            plan_id    = int(request.form.get("plan_id", 0))
            label      = request.form.get("label", "").strip()
            stype      = request.form.get("slot_type", "vm")
            weekdays   = request.form.get("weekdays", "0,1,2,3,4")
            nth_week   = request.form.get("nth_week", "") or None
            special_wd = request.form.get("special_weekday", "") or None
            min_staff  = int(request.form.get("min_staff", 1))
            time_from  = request.form.get("time_from", "").strip() or None
            time_to    = request.form.get("time_to", "").strip() or None
            slot_role  = request.form.get("slot_role", "staff")
            if slot_role not in ("staff", "lead"):
                slot_role = "staff"
            min_lead   = max(0, int(request.form.get("min_lead", 0) or 0))
            if plan_id and label:
                db.execute(
                    "INSERT INTO staffing_slots "
                    "(plan_id, label, slot_type, weekdays, nth_week, special_weekday, min_staff, time_from, time_to, slot_role, min_lead) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (plan_id, label, stype, weekdays, nth_week, special_wd, min_staff, time_from, time_to, slot_role, min_lead)
                )
                db.commit()
                add_flash(t("success.slot_created"), "success")

        elif action == "delete_slot":
            slot_id = int(request.form.get("slot_id", 0))
            db.execute("DELETE FROM staffing_slots WHERE id=?", (slot_id,))
            db.commit()

        elif action == "edit_slot":
            sid       = int(request.form.get("slot_id", 0))
            label     = request.form.get("label", "").strip()
            stype     = request.form.get("slot_type", "vm")
            weekdays  = request.form.get("weekdays", "0,1,2,3,4")
            nth_week  = request.form.get("nth_week", "") or None
            special_wd = request.form.get("special_weekday", "") or None
            min_staff = max(1, int(request.form.get("min_staff", 1) or 1))
            time_from = request.form.get("time_from", "").strip() or None
            time_to   = request.form.get("time_to", "").strip() or None
            slot_role = request.form.get("slot_role", "staff")
            if slot_role not in ("staff", "lead"):
                slot_role = "staff"
            min_lead  = max(0, int(request.form.get("min_lead", 0) or 0))
            if sid and label:
                db.execute("""UPDATE staffing_slots SET
                    label=?, slot_type=?, weekdays=?, nth_week=?,
                    special_weekday=?, min_staff=?, time_from=?,
                    time_to=?, slot_role=?, min_lead=?
                    WHERE id=?""",
                    (label, stype, weekdays, nth_week, special_wd,
                     min_staff, time_from, time_to, slot_role, min_lead, sid))
                db.commit()
                add_flash(t("success.slot_updated"), "success")

        elif action == "save_assignments":
            slot_id  = int(request.form.get("slot_id", 0))
            user_ids = request.form.getlist("user_ids")
            lead_ids = set(int(x) for x in request.form.getlist("lead_user_ids") if x.isdigit())
            db.execute("DELETE FROM staffing_assignments WHERE slot_id=?", (slot_id,))
            for uid_str in user_ids:
                uid     = int(uid_str)
                is_lead = 1 if uid in lead_ids else 0
                db.execute(
                    "INSERT OR REPLACE INTO staffing_assignments (slot_id, user_id, is_lead) VALUES (?,?,?)",
                    (slot_id, uid, is_lead)
                )
            db.commit()
            add_flash(t("success.assignments_saved"), "success")

        db.close()
        return redirect(url_for("admin.admin_home") + "#acc-staffing")

    db.close()
    return redirect(url_for("admin.admin_home") + "?tab=users")


@admin_bp.post("/admin/features")
@sysadmin_required
def admin_features_save():
    from app import bootstrap, add_flash
    bootstrap()
    val = "1" if request.form.get("feature_staffing") else "0"
    db = connect()
    db.execute(
        "INSERT OR REPLACE INTO app_config (key, value, updated_at) VALUES (?, ?, datetime('now'))",
        ("feature_staffing", val),
    )
    db.commit()
    db.close()
    from flask import g as _g
    if hasattr(_g, "_app_config_cache"):
        del _g._app_config_cache
    add_flash(t("success.settings_saved"), "success")
    return redirect("/admin#acc-features")


# ── Schulferien Admin ──────────────────────────────────────────────────────────
