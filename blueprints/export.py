"""
Blueprint: Export-Funktionen.
"""
from flask import Blueprint, request, redirect, url_for, make_response
from db import connect
from auth import login_required, admin_required, current_user, sysadmin_required
from translations import t

export_bp = Blueprint("export", __name__)


@export_bp.post("/export/mail")
@login_required
def export_mail():
    from app import (bootstrap, add_flash, _get_tracking_start, _build_time_blocks_export,
                     _build_csv_bytes, _fmt_minutes, _send_mail)
    import re
    import datetime
    bootstrap()
    u = current_user()
    today = datetime.date.today()

    date_from = (request.form.get("date_from") or "").strip()
    date_to   = (request.form.get("date_to") or "").strip()
    recipient = (request.form.get("recipient_email") or "").strip()
    export_type = (request.form.get("export_type") or "time_blocks").strip()

    # Admin can select another user
    target_uid = u["id"]
    target_name = u.get("display_name") or u.get("username") or "–"
    if u.get("is_admin"):
        uid_param = (request.form.get("user_id") or "").strip()
        if uid_param and uid_param.isdigit():
            db = connect()
            row = db.execute(
                "SELECT id, username, display_name FROM users WHERE id=? AND is_active=1",
                (int(uid_param),),
            ).fetchone()
            db.close()
            if row:
                target_uid = row["id"]
                target_name = row["display_name"] or row["username"]

    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_from):
        add_flash(t("flash.error.invalid_date_from"), "error")
        return redirect("/export")
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_to):
        add_flash(t("flash.error.invalid_date_to"), "error")
        return redirect("/export")
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', recipient):
        add_flash(t("flash.error.invalid_email"), "error")
        return redirect("/export")
    if date_from > date_to:
        add_flash(t("flash.error.date_range"), "error")
        return redirect("/export")

    # Clamp to user tracking start
    start = _get_tracking_start(target_uid)
    if start:
        date_from = max(date_from, start)

    # Build CSV
    if export_type == "absences":
        db = connect()
        rows = db.execute(
            "SELECT a.date_from, a.date_to, a.is_half_day, t.name AS type, a.comment "
            "FROM absences a JOIN absence_types t ON t.id=a.type_id "
            "WHERE a.user_id=? AND NOT (a.date_to < ? OR a.date_from > ?) ORDER BY a.date_from",
            (target_uid, date_from, date_to),
        ).fetchall()
        db.close()
        data = [[r["date_from"], r["date_to"], r["is_half_day"], r["type"], r["comment"] or ""] for r in rows]
        headers = ["date_from", "date_to", "is_half_day", "type", "comment"]
        total_min = 0
        entry_count = len(data)
        type_label = "Abwesenheiten"
        fname_pfx = "abwesenheiten"
    else:
        headers, data, total_min = _build_time_blocks_export(target_uid, date_from, date_to)
        entry_count = len(data)
        type_label = "Zeitblöcke"
        fname_pfx = "zeitbloecke"

    if not data:
        add_flash(t("flash.error.no_data_range").format(from_date=date_from, to_date=date_to), "error")
        return redirect("/export")

    attachment_name = f"{fname_pfx}_{target_name.lower().replace(' ','_')}_{date_from}_{date_to}.csv"
    csv_bytes = _build_csv_bytes(headers, data)

    body_text = (
        f"Zeiterfassung Export\n"
        f"{'─'*40}\n"
        f"Mitarbeiter: {target_name}\n"
        f"Typ:         {type_label}\n"
        f"Zeitraum:    {date_from} bis {date_to}\n"
        f"Einträge:    {entry_count}\n"
    )
    if total_min:
        body_text += f"Gesamtstunden: {_fmt_minutes(total_min)}\n"
    body_text += f"\nDieser Export wurde automatisch von Zeiterfassung generiert.\n"

    subject = f"Zeiterfassung Export – {target_name} – {date_from} bis {date_to}"

    try:
        _send_mail(recipient, subject, body_text, attachment_name, csv_bytes)
        add_flash(t("flash.success.export_sent").format(recipient=recipient), "success")
    except Exception as exc:
        add_flash(t("flash.error.mail_fail_detail").format(error=exc), "error")

    return redirect("/export")


@export_bp.get("/export")
@login_required
def export_home():
    from app import bootstrap, layout, flash_html, FORM_ASSETS_JS, _date_input, APP_VERSION
    from flask import render_template_string
    import datetime
    bootstrap()
    u = current_user()
    today = datetime.date.today()
    year = today.year
    default_from = f"{year}-01-01"
    default_to   = f"{year}-12-31"
    default_from_de = f"01.01.{year}"
    default_to_de   = f"31.12.{year}"
    user_email = u.get("email") or ""
    admin_btn = f'<button class="btn" type="button" onclick="dlExport(\'/export/users.csv\',false)">{t("export.admin_users_btn")}</button>' if u.get("is_admin") else ""

    # Admin: build user select options for mail form
    admin_user_select = ""
    if u.get("is_admin"):
        db = connect()
        all_users = db.execute(
            "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY username"
        ).fetchall()
        db.close()
        opts = "".join(
            f'<option value="{r["id"]}" {"selected" if r["id"] == u["id"] else ""}>'
            f'{r["display_name"] or r["username"]}</option>'
            for r in all_users
        )
        admin_user_select = (
            f'<div style="margin-bottom:10px;">'
            f'<label>{t("export.employee")}</label><br>'
            f'<select name="user_id" style="max-width:300px;">{opts}</select>'
            f'</div>'
        )

    _js_select_dates = t('export.select_dates')
    body = f"""
    {flash_html()}
    {FORM_ASSETS_JS}
    <div class="card">
      <h3 style="margin-top:0;">{t('export.period_label')}</h3>
      <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:end;margin-bottom:12px;">
        <div>
          <label>{t('common.from')}</label><br>
          <div class="dt-wrap">
            <input type="text" id="exp-from-txt" class="dt-text" placeholder="TT.MM.JJJJ"
                   value="{default_from_de}" maxlength="10" oninput="dt_text(this)">
            <input type="date" id="exp-from-iso" class="dt-pick" value="{default_from}"
                   onchange="dt_pick(this)">
          </div>
        </div>
        <div>
          <label>{t('common.to')}</label><br>
          <div class="dt-wrap">
            <input type="text" id="exp-to-txt" class="dt-text" placeholder="TT.MM.JJJJ"
                   value="{default_to_de}" maxlength="10" oninput="dt_text(this)">
            <input type="date" id="exp-to-iso" class="dt-pick" value="{default_to}"
                   onchange="dt_pick(this)">
          </div>
        </div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px;">
        <button class="btn" type="button" onclick="setExpRange('month')">{t('export.curr_month_btn')}</button>
        <button class="btn" type="button" onclick="setExpRange('lastmonth')">{t('export.last_month_btn')}</button>
        <button class="btn" type="button" onclick="setExpRange('year')">{t('export.curr_year_btn')}</button>
        <button class="btn" type="button" onclick="setExpRange('lastyear')">{t('export.last_year_btn')}</button>
      </div>
    </div>

    <div class="card">
      <h3 style="margin-top:0;">{t('export.download_title')}</h3>
      <p class="small">{t('export.csv_hint')}</p>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <button class="btn" type="button" onclick="dlExport('/export/time_blocks.csv',true)">{t('export.time_blocks')}</button>
        <button class="btn" type="button" onclick="dlExport('/export/absences.csv',true)">{t('export.absences')}</button>
        <button class="btn" type="button" onclick="dlExport('/export/trips.csv',true)">{t('export.trips')}</button>
        <button class="btn" type="button" onclick="dlExport('/export/balance.csv',true)">{t('export.balance')}</button>
        <button class="btn" type="button" onclick="dlExport('/export/calendar_days.csv',false)">{t('export.holidays_btn')}</button>
        {admin_btn}
      </div>
    </div>

    <div class="card">
      <h3 style="margin-top:0;">{t('export.send_mail')}</h3>
      <p class="small">{t('export.mail_hint')}</p>
      <form method="post" action="/export/mail" onsubmit="return injectMailDates(this)">
        <input type="hidden" name="date_from" id="mail-date-from" value="{default_from}">
        <input type="hidden" name="date_to"   id="mail-date-to"   value="{default_to}">
        {admin_user_select}
        <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;margin-bottom:10px;">
          <div style="flex:1;min-width:200px;">
            <label>{t('export.recipient')}</label><br>
            <input type="email" name="recipient_email" value="{user_email}"
                   placeholder="empfaenger@beispiel.de" required style="max-width:360px;width:100%;">
          </div>
          <div>
            <label>{t('export.type_label')}</label><br>
            <select name="export_type">
              <option value="time_blocks">{t('export.time_blocks')}</option>
              <option value="absences">{t('export.absences')}</option>
            </select>
          </div>
        </div>
        <button class="btn primary" type="submit">{t('export.send_btn')}</button>
      </form>
    </div>

    <script>
    function pad2(n){{return n<10?'0'+n:''+n;}}
    function lastDay(y,m){{return new Date(y,m,0).getDate();}}
    function isoToDE(s){{var p=s.split('-');return p[2]+'.'+p[1]+'.'+p[0];}}
    function setExpRange(preset){{
      var now=new Date(),y=now.getFullYear(),m=now.getMonth()+1,fy,fm,ty,tm;
      if(preset==='month'){{fy=y;fm=m;ty=y;tm=m;}}
      else if(preset==='lastmonth'){{var d=new Date(y,m-2,1);fy=d.getFullYear();fm=d.getMonth()+1;ty=fy;tm=fm;}}
      else if(preset==='year'){{fy=y;fm=1;ty=y;tm=12;}}
      else{{fy=y-1;fm=1;ty=y-1;tm=12;}}
      var from=fy+'-'+pad2(fm)+'-01';
      var to=ty+'-'+pad2(tm)+'-'+pad2(lastDay(ty,tm));
      document.getElementById('exp-from-txt').value=isoToDE(from);
      document.getElementById('exp-to-txt').value=isoToDE(to);
      document.getElementById('exp-from-iso').value=from;
      document.getElementById('exp-to-iso').value=to;
      syncMailDates(from,to);
    }}
    function syncMailDates(from,to){{
      var f=document.getElementById('mail-date-from');
      var tt=document.getElementById('mail-date-to');
      if(f)f.value=from||'';
      if(tt)tt.value=to||'';
    }}
    function dlExport(base,withRange){{
      if(!withRange){{window.location=base;return;}}
      var from=document.getElementById('exp-from-iso').value;
      var to=document.getElementById('exp-to-iso').value;
      if(!from||!to){{alert('{_js_select_dates}');return;}}
      window.location=base+'?from='+from+'&to='+to;
    }}
    function injectMailDates(form){{
      var from=document.getElementById('exp-from-iso').value;
      var to=document.getElementById('exp-to-iso').value;
      if(!from||!to){{alert('{_js_select_dates}');return false;}}
      document.getElementById('mail-date-from').value=from;
      document.getElementById('mail-date-to').value=to;
      return true;
    }}
    </script>
    """
    return render_template_string(layout(t("export.title"), body, u, APP_VERSION))


@export_bp.get("/export/absences.csv")
@login_required
def export_absences_csv():
    from app import bootstrap, _export_date_range, _csv_response, _export_filename
    bootstrap()
    u = current_user()
    date_from, date_to = _export_date_range(u["id"])
    db = connect()
    rows = db.execute(
        """
        SELECT a.id, t.name AS type, a.date_from, a.date_to, a.is_half_day, a.comment, a.created_at, a.updated_at
        FROM absences a
        JOIN absence_types t ON t.id = a.type_id
        WHERE a.user_id = ? AND NOT (a.date_to < ? OR a.date_from > ?)
        ORDER BY a.date_from, a.id
        """,
        (u["id"], date_from, date_to),
    ).fetchall()
    db.close()

    data = [[r["id"], r["type"], r["date_from"], r["date_to"], r["is_half_day"], r["comment"] or "", r["created_at"] or "", r["updated_at"] or ""] for r in rows]
    return _csv_response(
        _export_filename("abwesenheiten", date_from, date_to),
        ["id", "type", "date_from", "date_to", "is_half_day", "comment", "created_at", "updated_at"],
        data,
    )


@export_bp.get("/export/time_blocks.csv")
@login_required
def export_time_blocks_csv():
    from app import bootstrap, _export_date_range, _csv_response, _export_filename, _minutes_from_hhmm, _fmt_minutes
    bootstrap()
    u = current_user()
    date_from, date_to = _export_date_range(u["id"])
    db = connect()
    rows = db.execute(
        """
        SELECT day, time_in, time_out, break_minutes, comment, created_at, updated_at
        FROM time_blocks
        WHERE user_id = ? AND day BETWEEN ? AND ?
        ORDER BY day, time_in
        """,
        (u["id"], date_from, date_to),
    ).fetchall()
    db.close()

    data = []
    for r in rows:
        mins = _minutes_from_hhmm(r["time_out"]) - _minutes_from_hhmm(r["time_in"]) - int(r["break_minutes"] or 0)
        data.append([
            r["day"],
            r["time_in"],
            r["time_out"],
            int(r["break_minutes"] or 0),
            _fmt_minutes(mins),
            r["comment"] or "",
            r["created_at"] or "",
            r["updated_at"] or "",
        ])

    return _csv_response(
        _export_filename("zeitbloecke", date_from, date_to),
        ["day", "time_in", "time_out", "break_minutes", "net_hhmm", "comment", "created_at", "updated_at"],
        data,
    )


@export_bp.get("/export/month_summary.csv")
@login_required
def export_month_summary_csv():
    from app import bootstrap, _month_range, _csv_response, _minutes_from_hhmm, _fmt_minutes
    import datetime
    import calendar
    bootstrap()
    u = current_user()
    today = datetime.date.today()
    year = int(request.args.get("y") or today.year)
    month = int(request.args.get("m") or today.month)
    first_iso, last_iso = _month_range(year, month)

    db = connect()
    rows_tb = db.execute(
        """
        SELECT day, time_in, time_out, break_minutes
        FROM time_blocks
        WHERE user_id=? AND day BETWEEN ? AND ?
        """,
        (u["id"], first_iso, last_iso),
    ).fetchall()

    abs_rows = db.execute(
        """
        SELECT a.date_from, a.date_to, a.is_half_day, t.name AS type_name
        FROM absences a
        JOIN absence_types t ON t.id=a.type_id
        WHERE a.user_id=?
          AND NOT (a.date_to < ? OR a.date_from > ?)
        """,
        (u["id"], first_iso, last_iso),
    ).fetchall()
    db.close()

    totals = {}
    for b in rows_tb:
        day = b["day"]
        mins = _minutes_from_hhmm(b["time_out"]) - _minutes_from_hhmm(b["time_in"]) - int(b["break_minutes"] or 0)
        totals[day] = totals.get(day, 0) + mins

    abs_map = {}
    for a in abs_rows:
        d0 = datetime.date.fromisoformat(a["date_from"])
        d1 = datetime.date.fromisoformat(a["date_to"])
        cur = d0
        while cur <= d1:
            iso = cur.isoformat()
            label = a["type_name"]
            if a["is_half_day"] and a["date_from"] == a["date_to"]:
                label += " (1/2)"
            abs_map.setdefault(iso, []).append(label)
            cur += datetime.timedelta(days=1)

    last_day = calendar.monthrange(year, month)[1]
    data = []
    for d in range(1, last_day + 1):
        iso = datetime.date(year, month, d).isoformat()
        data.append([iso, _fmt_minutes(totals.get(iso, 0)), "; ".join(abs_map.get(iso, []))])

    return _csv_response(
        f"month_summary_{u['username']}_{year}-{month:02d}.csv",
        ["day", "net_hhmm", "absence"],
        data,
    )


@export_bp.get("/export/presence.csv")
@login_required
def export_presence_csv():
    from app import bootstrap, _csv_response
    import sqlite3
    bootstrap()
    u = current_user()
    db = connect()
    try:
        rows = db.execute(
            "SELECT p.day, p.comment, p.created_at, p.updated_at FROM daily_presence p WHERE p.user_id=? ORDER BY p.day",
            (u["id"],),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    db.close()
    data = [[r["day"], r["comment"] or "", r["created_at"] or "", r["updated_at"] or ""] for r in rows]
    return _csv_response(
        f"presence_{u['username']}.csv",
        ["day", "comment", "created_at", "updated_at"],
        data,
    )


@export_bp.get("/export/times.csv")
@login_required
def export_times_csv():
    from app import bootstrap, _export_date_range, _csv_response, _export_filename
    bootstrap()
    u = current_user()
    date_from, date_to = _export_date_range(u["id"])
    db = connect()
    rows = db.execute(
        """
        SELECT day, time_in, time_out, break_minutes, comment, created_at, updated_at
        FROM time_entries
        WHERE user_id = ? AND day BETWEEN ? AND ?
        ORDER BY day
        """,
        (u["id"], date_from, date_to),
    ).fetchall()
    db.close()
    data = [[r["day"], r["time_in"], r["time_out"], r["break_minutes"], r["comment"] or "", r["created_at"] or "", r["updated_at"] or ""] for r in rows]
    return _csv_response(
        _export_filename("zeiten", date_from, date_to),
        ["day", "time_in", "time_out", "break_minutes", "comment", "created_at", "updated_at"],
        data,
    )


@export_bp.get("/export/trips.csv")
@login_required
def export_trips_csv():
    from app import bootstrap, _export_date_range, _csv_response, _export_filename
    bootstrap()
    u = current_user()
    date_from, date_to = _export_date_range(u["id"])
    db = connect()
    rows = db.execute(
        """
        SELECT start_date, end_date, destination, departure_time, departure_end_time,
               return_time, return_end_time, notes, created_at
        FROM business_trips
        WHERE user_id = ? AND start_date BETWEEN ? AND ?
        ORDER BY start_date
        """,
        (u["id"], date_from, date_to),
    ).fetchall()
    db.close()
    data = [
        [r["start_date"], r["end_date"] or "", r["destination"],
         r["departure_time"] or "", r["departure_end_time"] or "",
         r["return_time"] or "", r["return_end_time"] or "",
         r["notes"] or "", r["created_at"] or ""]
        for r in rows
    ]
    return _csv_response(
        _export_filename("dienstreisen", date_from, date_to),
        ["start_date", "end_date", "destination", "departure_time", "departure_end_time",
         "return_time", "return_end_time", "notes", "created_at"],
        data,
    )


@export_bp.get("/export/balance.csv")
@login_required
def export_balance_csv():
    from app import (bootstrap, _export_date_range, _csv_response, _export_filename,
                     _get_start_balance_minutes, _fetch_flextag_ranges, _iter_days,
                     _expected_minutes_for_day, _actual_minutes_for_day, _is_flextag,
                     _scheduled_minutes_ignoring_absence, _fmt_minutes, _fmt_minutes_signed)
    import datetime
    bootstrap()
    u = current_user()
    date_from, date_to = _export_date_range(u["id"])
    today_iso = datetime.date.today().isoformat()
    date_to = min(date_to, today_iso)

    start_minutes = _get_start_balance_minutes(u["id"])
    flextag_ranges = _fetch_flextag_ranges(u["id"])
    running = int(start_minutes)
    data = []
    for iso in _iter_days(date_from, date_to):
        expected = int(_expected_minutes_for_day(u["id"], iso) or 0)
        actual   = int(_actual_minutes_for_day(u["id"], iso) or 0)
        flextag_min = 0
        if iso < today_iso and expected == 0 and _is_flextag(iso, flextag_ranges):
            flextag_min = _scheduled_minutes_ignoring_absence(u["id"], iso)
        delta = actual - expected - flextag_min
        running += delta
        if expected or actual:
            data.append([iso, _fmt_minutes(expected), _fmt_minutes(actual),
                         _fmt_minutes_signed(delta), _fmt_minutes_signed(running)])
    return _csv_response(
        _export_filename("gleitzeitkonto", date_from, date_to),
        ["day", "soll", "ist", "delta", "saldo"],
        data,
    )


@export_bp.get("/export/calendar_days.csv")
@login_required
def export_calendar_days_csv():
    from app import bootstrap, _csv_response
    bootstrap()
    db = connect()
    rows = db.execute(
        "SELECT day, is_holiday, holiday_name, is_school_holiday, school_holiday_name, region, updated_at FROM calendar_days ORDER BY day"
    ).fetchall()
    db.close()
    data = [[r["day"], r["is_holiday"], r["holiday_name"] or "", r["is_school_holiday"], r["school_holiday_name"] or "", r["region"] or "", r["updated_at"] or ""] for r in rows]
    return _csv_response(
        "calendar_days.csv",
        ["day", "is_holiday", "holiday_name", "is_school_holiday", "school_holiday_name", "region", "updated_at"],
        data,
    )


@export_bp.get("/export/users.csv")
@sysadmin_required
def export_users_csv():
    from app import bootstrap, _csv_response
    bootstrap()
    db = connect()
    rows = db.execute(
        "SELECT id, username, is_admin, is_active, created_at, updated_at FROM users ORDER BY username"
    ).fetchall()
    db.close()
    data = [[r["id"], r["username"], r["is_admin"], r["is_active"], r["created_at"] or "", r["updated_at"] or ""] for r in rows]
    return _csv_response(
        "users.csv",
        ["id", "username", "is_admin", "is_active", "created_at", "updated_at"],
        data,
    )
