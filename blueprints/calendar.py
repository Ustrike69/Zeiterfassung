"""
Blueprint: Kalender und Perioden.
"""
from flask import Blueprint, request, redirect, url_for, render_template_string, abort
from db import connect
from auth import login_required, admin_required, current_user
from translations import t

calendar_routes_bp = Blueprint("calendar_routes", __name__)

@calendar_routes_bp.get("/calendar/year-list")
@login_required
def calendar_year_list():
    """Returns an HTML fragment with all 12 months of the given year for the mobile list view."""
    from app import bootstrap, _get_tracking_start, _get_user_holiday_region, _minutes_from_hhmm, _fmt_minutes, _iter_days, _get_contouring_info, _get_contoured_days, _get_missing_entry_days, _get_vocational_school_entry, _is_holiday, _is_school_holiday, _feature_enabled, _t_month
    import datetime, calendar
    bootstrap()
    u = current_user()
    uid = u["id"]
    try:
        year = int(request.args.get("y") or datetime.date.today().year)
    except (ValueError, TypeError):
        year = datetime.date.today().year

    today = datetime.date.today()
    user_start_date = _get_tracking_start(uid) or "2026-01-01"
    y_start = f"{year}-01-01"
    y_end   = f"{year}-12-31"

    db = connect()

    _cal_region = _get_user_holiday_region(uid)
    hol_rows = db.execute(
        "SELECT day, is_holiday, is_weekend, holiday_name FROM calendar_days"
        " WHERE region=? AND day>=? AND day<=?",
        (_cal_region, y_start, y_end),
    ).fetchall()
    hol_map = {str(r["day"])[:10]: r for r in hol_rows}

    totals: dict = {}
    for b in db.execute(
        "SELECT day, time_in, time_out, break_minutes FROM time_blocks"
        " WHERE user_id=? AND day BETWEEN ? AND ? ORDER BY day, time_in",
        (uid, y_start, y_end),
    ).fetchall():
        iso = str(b["day"])[:10]
        mins = _minutes_from_hhmm(b["time_out"]) - _minutes_from_hhmm(b["time_in"]) - int(b["break_minutes"] or 0)
        totals[iso] = totals.get(iso, 0) + mins
    for e in db.execute(
        "SELECT day, time_in, time_out, break_minutes FROM time_entries"
        " WHERE user_id=? AND day BETWEEN ? AND ?",
        (uid, y_start, y_end),
    ).fetchall():
        iso = str(e["day"])[:10]
        if iso not in totals:
            totals[iso] = _minutes_from_hhmm(e["time_out"]) - _minutes_from_hhmm(e["time_in"]) - int(e["break_minutes"] or 0)
    net_map = {d: _fmt_minutes(m) for d, m in totals.items()}

    abs_rows = db.execute(
        """SELECT a.date_from, a.date_to, a.is_half_day, a.comment, t.name AS type_name, t.color AS type_color
           FROM absences a JOIN absence_types t ON t.id = a.type_id
           WHERE a.user_id=? AND NOT (a.date_to < ? OR a.date_from > ?)""",
        (uid, y_start, y_end),
    ).fetchall()

    trip_map: dict = {}
    for r in db.execute(
        "SELECT start_date, end_date, destination FROM business_trips"
        " WHERE user_id=? AND start_date<=? AND (end_date>=? OR end_date IS NULL)",
        (uid, y_end, y_start),
    ).fetchall():
        for _td in _iter_days(str(r["start_date"])[:10], str(r["end_date"] or r["start_date"])[:10]):
            if y_start <= _td <= y_end:
                trip_map[_td] = r["destination"]

    lock_rows = db.execute(
        "SELECT year, month FROM period_locks WHERE user_id=? AND period_type='month' AND year=?",
        (uid, year),
    ).fetchall()
    locked_months = {r["month"] for r in lock_rows}
    year_locked = bool(db.execute(
        "SELECT 1 FROM period_locks WHERE user_id=? AND period_type='year' AND year=?",
        (uid, year),
    ).fetchone())
    db.close()

    cal_contouring = _get_contouring_info(uid)
    contoured_year = _get_contoured_days(uid, y_start, y_end)
    missing_all    = _get_missing_entry_days(uid, year)

    day_badges: dict = {}
    # Berufsschule-Badges
    try:
        _voc_db = connect()
        _voc_entries = _voc_db.execute(
            "SELECT * FROM vocational_school WHERE user_id=?", (uid,)
        ).fetchall()
        _voc_db.close()
        _cur = datetime.date.fromisoformat(y_start)
        _end = datetime.date.fromisoformat(y_end)
        while _cur <= _end:
            _iso = _cur.isoformat()
            _voc = _get_vocational_school_entry(uid, _iso)
            if _voc and not _is_holiday(_iso, uid):
                _skip = _voc["schedule_type"] == "weekly" and _is_school_holiday(_iso, uid)
                if not _skip:
                    _lbl = "🎓 BS Halbtag" if (_voc.get("work_time_from") and _voc.get("work_time_to")) else "🎓 Berufsschule"
                    day_badges.setdefault(_iso, []).append((_lbl, "#8b5cf6"))
            _cur += datetime.timedelta(days=1)
    except Exception:
        pass
    if _feature_enabled("staffing"):
        _db_so_y = connect()
        try:
            _so_rows_y = _db_so_y.execute("""
                SELECT so.iso_date, ss.label as slot_label,
                       ss.time_from, ss.time_to
                FROM staffing_overrides so
                JOIN staffing_slots ss ON ss.id = so.slot_id
                WHERE so.user_id = ?
                AND so.status IN ('assigned', 'confirmed')
                AND so.iso_date BETWEEN ? AND ?
            """, (uid, y_start, y_end)).fetchall()
            for _so in _so_rows_y:
                _iso = str(_so["iso_date"])[:10]
                _time_str = ""
                if _so["time_from"] and _so["time_to"]:
                    _time_str = f' {_so["time_from"]}-{_so["time_to"]}'
                _label = f'⭐ {_so["slot_label"]}{_time_str}'
                day_badges.setdefault(_iso, []).append((_label, "#f59e0b"))
        finally:
            _db_so_y.close()
    for a in abs_rows:
        d0  = datetime.date.fromisoformat(a["date_from"])
        d1  = datetime.date.fromisoformat(a["date_to"])
        cur = d0
        while cur <= d1:
            iso = cur.isoformat()
            txt = a["type_name"]
            if a["type_name"] == "Sonstige" and a["comment"]:
                txt += f": {a['comment']}"
            if a["is_half_day"] and a["date_from"] == a["date_to"]:
                txt += " (1/2)"
            day_badges.setdefault(iso, []).append((txt, a["type_color"] or "#999"))
            cur += datetime.timedelta(days=1)

    _wd = [t(f"weekday.short.{i}") for i in range(7)]
    rows = []

    for mo in range(1, 13):
        mo_locked = year_locked or mo in locked_months
        rows.append(
            f"<div style='font-size:12px;font-weight:700;text-transform:uppercase;"
            f"letter-spacing:.06em;color:var(--mu);padding:10px 4px 6px;"
            f"border-bottom:1px solid var(--bd);'>"
            f"{_t_month(mo)} {year}</div>"
        )
        d_it  = datetime.date(year, mo, 1)
        d_end = datetime.date(year, mo, calendar.monthrange(year, mo)[1])
        while d_it <= d_end:
            iso = d_it.isoformat()
            if iso < user_start_date:
                d_it += datetime.timedelta(days=1)
                continue
            hol      = hol_map.get(iso)
            is_hol   = bool(hol and hol["is_holiday"])
            is_off   = d_it.weekday() >= 5 or is_hol
            is_today = d_it == today
            badges   = day_badges.get(iso, [])
            net      = net_map.get(iso)
            trip     = trip_map.get(iso)
            is_miss  = iso in missing_all

            row_cls = "cal-lr" + (" cal-lr-today" if is_today else "") + (" cal-lr-off" if is_off else "")

            cp = ""
            if net:
                cp += f"<span class='cal-lr-h'>{net}</span>"
            for txt, col, *_ in badges:
                cp += f"<span class='cal-lr-b' style='border-left:3px solid {col};padding-left:5px;'>{txt}</span>"
            if is_hol:
                cp += f"<span class='cal-lr-hol'>{hol['holiday_name']}</span>"
            if trip:
                cp += f"<span class='cal-lr-trip'>✈ {trip}</span>"

            cal_contour_visible = (
                cal_contouring["enabled"]
                and (not cal_contouring["start_date"] or iso >= cal_contouring["start_date"])
            )
            ic = ""
            if is_miss:
                ic = "<span class='cal-lr-x' title='Fehlender Eintrag'>✕</span>"
            elif cal_contour_visible and iso in contoured_year:
                ic = "<span class='cal-lr-ok' title='Kontiert'>✓</span>"
            elif mo_locked:
                ic = "<span class='cal-lr-lock'>\U0001f512</span>"

            rows.append(
                f"<a href='/day/{iso}' class='{row_cls}'>"
                f"<div class='cal-lr-date'><span class='cal-lr-wd'>{_wd[d_it.weekday()]}</span>"
                f"<span class='cal-lr-dm'>{d_it.day:02d}.{mo:02d}.</span></div>"
                f"<div class='cal-lr-cnt'>{cp}</div>"
                f"<div class='cal-lr-ico'>{ic}</div>"
                f"</a>"
            )
            d_it += datetime.timedelta(days=1)

    return "".join(rows)



@calendar_routes_bp.get("/calendar")
@login_required
def calendar_view():
    from app import bootstrap, flash_html, layout, APP_VERSION, _get_tracking_start, _month_range, _minutes_from_hhmm, _fmt_minutes, _get_user_holiday_region, _iter_days, _get_contouring_info, _get_contoured_days, _get_weekend_exceptions_month, _get_missing_entry_days, _is_day_locked, _get_vocational_school_entry, _is_holiday, _is_school_holiday, _feature_enabled, _t_month, CALENDAR_DAYMENU_ASSETS
    import datetime, calendar
    bootstrap()
    u = current_user()
    if u and u.get("admin_only"):
        return redirect("/admin")

    today = datetime.date.today()
    user_start_date = _get_tracking_start(u["id"])
    _def_y, _def_m = today.year, today.month
    if user_start_date:
        _sd = datetime.date.fromisoformat(user_start_date)
        if today < _sd:
            _def_y, _def_m = _sd.year, _sd.month
    year  = int(request.args.get("y") or _def_y)
    month = int(request.args.get("m") or _def_m)

    first_iso, last_iso = _month_range(year, month)

    db = connect()

    totals = {}
    for b in db.execute(
        "SELECT day, time_in, time_out, break_minutes FROM time_blocks WHERE user_id=? AND day BETWEEN ? AND ?",
        (u["id"], first_iso, last_iso),
    ).fetchall():
        day_iso = str(b["day"]).strip()[:10]
        mins = _minutes_from_hhmm(b["time_out"]) - _minutes_from_hhmm(b["time_in"]) - int(b["break_minutes"] or 0)
        totals[day_iso] = totals.get(day_iso, 0) + mins
    net_map = {d: _fmt_minutes(m) for d, m in totals.items()}

    _cal2_region = _get_user_holiday_region(u["id"])
    hol_map = {
        str(r["day"]).strip()[:10]: r
        for r in db.execute(
            "SELECT day, is_holiday, holiday_name FROM calendar_days WHERE region=? AND day BETWEEN ? AND ?",
            (_cal2_region, first_iso, last_iso),
        ).fetchall()
    }

    abs_rows = db.execute(
        """SELECT a.date_from, a.date_to, a.is_half_day, a.comment, t.name AS type_name, t.color AS type_color
           FROM absences a JOIN absence_types t ON t.id = a.type_id
           WHERE a.user_id = ? AND NOT (a.date_to < ? OR a.date_from > ?)""",
        (u["id"], first_iso, last_iso),
    ).fetchall()

    trip_map = {}
    for r in db.execute(
        "SELECT start_date, end_date, destination FROM business_trips"
        " WHERE user_id=? AND start_date <= ? AND (end_date >= ? OR end_date IS NULL)",
        (u["id"], last_iso, first_iso),
    ).fetchall():
        s = str(r["start_date"])[:10]
        e = str(r["end_date"] or r["start_date"])[:10]
        for _td in _iter_days(s, e):
            if first_iso <= _td <= last_iso:
                trip_map[_td] = r["destination"]

    db.close()

    cal_contouring = _get_contouring_info(u["id"])
    contoured_month = _get_contoured_days(u["id"], first_iso, last_iso)
    exc_days_month = _get_weekend_exceptions_month(u["id"], first_iso, last_iso)

    day_badges = {}
    # Berufsschule-Badges für Monatsansicht
    try:
        _voc_cur = datetime.date.fromisoformat(first_iso)
        _voc_end = datetime.date.fromisoformat(last_iso)
        while _voc_cur <= _voc_end:
            _viso = _voc_cur.isoformat()
            _voc_e = _get_vocational_school_entry(u["id"], _viso)
            if _voc_e and not _is_holiday(_viso, u["id"]):
                _vskip = _voc_e["schedule_type"] == "weekly" and _is_school_holiday(_viso, u["id"])
                if not _vskip:
                    _lbl = "🎓 BS Halbtag" if (_voc_e.get("work_time_from") and _voc_e.get("work_time_to")) else "🎓 Berufsschule"
                    day_badges.setdefault(_viso, []).append((_lbl, "#8b5cf6", True, True))
            _voc_cur += datetime.timedelta(days=1)
    except Exception:
        pass
    if _feature_enabled("staffing"):
        _db_so = connect()
        try:
            _so_rows = _db_so.execute("""
                SELECT so.iso_date, ss.label as slot_label,
                       ss.time_from, ss.time_to
                FROM staffing_overrides so
                JOIN staffing_slots ss ON ss.id = so.slot_id
                WHERE so.user_id = ?
                AND so.status IN ('assigned', 'confirmed')
                AND so.iso_date BETWEEN ? AND ?
            """, (u["id"], first_iso, last_iso)).fetchall()
            for _so in _so_rows:
                _iso = str(_so["iso_date"])[:10]
                _time_str = ""
                if _so["time_from"] and _so["time_to"]:
                    _time_str = f' {_so["time_from"]}-{_so["time_to"]}'
                _label = f'⭐ {_so["slot_label"]}{_time_str}'
                day_badges.setdefault(_iso, []).append((_label, "#f59e0b", True, True))
        finally:
            _db_so.close()
    for a in abs_rows:
        d0 = datetime.date.fromisoformat(a["date_from"])
        d1 = datetime.date.fromisoformat(a["date_to"])
        cur = d0
        while cur <= d1:
            iso = cur.isoformat()
            txt = a["type_name"]
            if a["type_name"] == "Sonstige" and a["comment"]:
                txt += f": {a['comment']}"
            if a["is_half_day"] and a["date_from"] == a["date_to"]:
                txt += " (1/2)"
            vis_first = (cur == d0) or (cur.weekday() == 0)
            vis_last  = (cur == d1) or (cur.weekday() == 6)
            day_badges.setdefault(iso, []).append((txt, a["type_color"] or "#999", vis_first, vis_last))
            cur += datetime.timedelta(days=1)

    month_isos  = set(_iter_days(first_iso, last_iso))
    missing_days = _get_missing_entry_days(u["id"], year) & month_isos
    cal_locked  = _is_day_locked(u["id"], f"{year}-{month:02d}-01")
    lock_badge  = " \U0001f512" if cal_locked else ""

    _wd = [t(f"weekday.short.{i}") for i in range(7)]

    # ── Desktop grid ──────────────────────────────────────────────────────────
    def _badge_html(items):
        out = ""
        for item in items[:4]:
            txt, col, vis_first, vis_last = item
            bg = col + "22"
            if vis_first and vis_last:
                radius = "6px"
                w_extra = "width:100%;box-sizing:border-box;"
            elif vis_first:
                radius = "6px 0 0 6px"
                w_extra = "width:calc(100% + 8px);margin-right:-8px;box-sizing:border-box;"
            elif vis_last:
                radius = "0 6px 6px 0"
                w_extra = "width:calc(100% + 8px);margin-left:-8px;box-sizing:border-box;"
            else:
                radius = "0"
                w_extra = "width:calc(100% + 16px);margin-left:-8px;margin-right:-8px;box-sizing:border-box;"
            out += (
                f"<div style='height:22px;line-height:22px;padding:0 6px;border-radius:{radius};"
                f"background:{bg};color:var(--tx);font-size:11px;position:relative;z-index:1;"
                f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap;{w_extra}'>"
                f"{txt}</div>"
            )
        if len(items) > 4:
            out += f"<div style='padding:1px 5px;color:var(--mu);font-size:10px;'>+{len(items)-4} mehr…</div>"
        return out

    def _week_num(week_days):
        for d in week_days:
            if d != 0:
                return datetime.date(year, month, d).isocalendar()[1]
        return ""

    def _day_cell(daynum):
        if daynum == 0:
            return "<td></td>"
        d   = datetime.date(year, month, daynum)
        iso = d.isoformat()
        wd  = _wd[d.weekday()]
        if user_start_date and iso < user_start_date:
            return (
                f"<td class='daycell daycell-before' title='{t('calendar.before_start_title')}'>"
                f"<div class='dc-head'><b class='dc-num' style='opacity:.4;'>{daynum}</b></div>"
                f"</td>"
            )
        hol = hol_map.get(iso)
        badges = day_badges.get(iso, [])
        net   = net_map.get(iso)
        trip  = trip_map.get(iso)

        has_entry   = bool(net or badges)
        is_kontiert = (iso in contoured_month) and has_entry
        is_missing  = iso in missing_days

        # Fixed-height time row (26px header + 20px time = abs section always at offset 46px)
        if is_missing:
            nh_h = (
                f"<div id='nh_{iso}' class='dc-time' data-net='' data-has-net='0'"
                f" style='color:var(--danger);font-size:13px;font-weight:700;'"
                f" title='{t('calendar.missing_entry')}'>✕</div>"
            )
        elif net:
            clr = "#b45309" if is_kontiert else "var(--mu)"
            txt = f"· {net}" if is_kontiert else net
            nh_h = (
                f"<div id='nh_{iso}' class='dc-time' data-net='{net}' data-has-net='1'"
                f" style='color:{clr};'>{txt}</div>"
            )
        else:
            dot = "·" if is_kontiert else ""
            clr_style = " style='color:#b45309;'" if is_kontiert else ""
            nh_h = (
                f"<div id='nh_{iso}' class='dc-time' data-net='' data-has-net='0'{clr_style}>{dot}</div>"
            )

        hol_html = (
            f"<div class='dc-hol'>{hol['holiday_name']}</div>"
            if hol and hol["is_holiday"] else ""
        )
        trip_h = f"<div class='dc-trip'>✈ {trip}</div>" if trip else ""

        contour_allowed = (
            cal_contouring["enabled"]
            and (not cal_contouring["start_date"] or iso >= cal_contouring["start_date"])
        )
        if not contour_allowed:
            km_item = ""
        elif is_kontiert:
            km_item = f"  <a href='#' id='km_{iso}' onclick=\"return toggleKontiert('{iso}', event);\">{t('calendar.ctx_unbook')}</a>"
        elif has_entry:
            km_item = f"  <a href='#' id='km_{iso}' onclick=\"return toggleKontiert('{iso}', event);\">{t('calendar.ctx_book')}</a>"
        else:
            km_item = f"  <span style='display:block;padding:6px 8px;font-size:13px;color:var(--mu);'>{t('calendar.ctx_no_entry_book')}</span>"
        exc_badge = "<span class='dc-exc' title='Ausnahme aktiv'>⚡</span>" if iso in exc_days_month else ""
        return (
            f"<td class='daycell' title='{wd}, {daynum:02d}.{month:02d}.{year}'>"
            f"<div class='dc-head'>"
            f"<b class='dc-num'>{daynum}{exc_badge}</b>"
            f"<a href='#' class='addbtn' title='Aktionen' onclick=\"return toggleDayMenu('m_{iso}', event);\">&#8943;</a>"
            f"</div>"
            f"{nh_h}"
            f"<div class='dc-abs'>{_badge_html(badges)}</div>"
            f"{trip_h}{hol_html}"
            f"<div id='m_{iso}' class='daymenu' onclick='event.stopPropagation();'>"
            f"  <a href='/day/{iso}'>{t('calendar.ctx_time')}</a>"
            f"  <a href='/absences/new'>{t('calendar.ctx_absence')}</a>"
            f"{km_item}"
            f"</div>"
            f"</td>"
        )

    cal_obj  = calendar.Calendar(firstweekday=0)
    weeks    = cal_obj.monthdayscalendar(year, month)
    grid_head = (
        f"<tr><th class='kw-head'>{t('calendar.week_abbr')}</th>"
        + "".join(f"<th>{d}</th>" for d in _wd)
        + "</tr>"
    )
    grid_rows = "".join(
        f"<tr><td class='kw-cell'>{_week_num(w)}</td>"
        + "".join(_day_cell(d) for d in w)
        + "</tr>"
        for w in weeks
    )
    grid_html = f'<table style="margin-top:10px;table-layout:fixed;width:100%;"><thead>{grid_head}</thead><tbody>{grid_rows}</tbody></table>'

    # ── Mobile list ───────────────────────────────────────────────────────────
    list_rows = []
    d_it  = datetime.date(year, month, 1)
    d_end = datetime.date(year, month, calendar.monthrange(year, month)[1])
    while d_it <= d_end:
        iso      = d_it.isoformat()
        if user_start_date and iso < user_start_date:
            d_it += datetime.timedelta(days=1)
            continue
        wd       = _wd[d_it.weekday()]
        date_str = f"{d_it.day:02d}.{month:02d}."
        hol      = hol_map.get(iso)
        is_hol   = bool(hol and hol["is_holiday"])
        is_off   = d_it.weekday() >= 5 or is_hol
        is_today = d_it == today
        badges   = day_badges.get(iso, [])
        net      = net_map.get(iso)
        trip     = trip_map.get(iso)
        is_miss  = iso in missing_days

        row_cls = "cal-lr" + (" cal-lr-today" if is_today else "") + (" cal-lr-off" if is_off else "")

        cp = ""
        if net:
            cp += f"<span class='cal-lr-h'>{net}</span>"
        for txt, col, *_ in badges:
            cp += f"<span class='cal-lr-b' style='border-left:3px solid {col};padding-left:5px;'>{txt}</span>"
        if is_hol:
            cp += f"<span class='cal-lr-hol'>{hol['holiday_name']}</span>"
        if trip:
            cp += f"<span class='cal-lr-trip'>✈ {trip}</span>"

        cal_contour_visible = (
            cal_contouring["enabled"]
            and (not cal_contouring["start_date"] or iso >= cal_contouring["start_date"])
        )
        ic = ""
        if is_miss:
            ic = "<span class='cal-lr-x' title='Fehlender Eintrag'>✕</span>"
        elif cal_contour_visible and iso in contoured_month:
            ic = "<span class='cal-lr-ok' title='Kontiert'>✓</span>"
        elif cal_locked:
            ic = "<span class='cal-lr-lock'>\U0001f512</span>"

        list_rows.append(
            f"<a href='/day/{iso}' class='{row_cls}'>"
            f"<div class='cal-lr-date'><span class='cal-lr-wd'>{wd}</span><span class='cal-lr-dm'>{date_str}</span></div>"
            f"<div class='cal-lr-cnt'>{cp}</div>"
            f"<div class='cal-lr-ico'>{ic}</div>"
            f"</a>"
        )
        d_it += datetime.timedelta(days=1)

    list_html = "".join(list_rows)

    # ── Navigation ────────────────────────────────────────────────────────────
    prev_m, prev_y = (month - 1, year) if month > 1 else (12, year - 1)
    next_m, next_y = (month + 1, year) if month < 12 else (1, year + 1)
    month_label = f"{_t_month(month)} {year}"
    _prev_blocked = bool(
        user_start_date and
        datetime.date(prev_y, prev_m, 1) < datetime.date.fromisoformat(user_start_date).replace(day=1)
    )
    prev_nav_btn = (
        f"<span class='btn' style='padding:9px 14px;opacity:.35;cursor:not-allowed;'>&#9664;</span>"
        if _prev_blocked else
        f"<a class='btn' href='/calendar?y={prev_y}&m={prev_m}' style='padding:9px 14px;' onclick='calNavLeave()'>&#9664;</a>"
    )

    # ── Styles (plain strings – no f-string brace escaping needed) ────────────
    cal_css = """<style>
.cal-grid-wrap{display:block;}
.cal-list-wrap{display:none;border-top:1px solid var(--bd);margin-top:8px;}
.cal-year-wrap{display:none;border-top:1px solid var(--bd);margin-top:8px;}
@media(max-width:767px){
  .cal-grid-wrap{display:none;}
  .cal-list-wrap{display:block;}
}
[data-cal-view=month] .cal-grid-wrap{display:block!important;}
[data-cal-view=month] .cal-list-wrap{display:none!important;}
[data-cal-view=month] .cal-year-wrap{display:none!important;}
[data-cal-view=list]  .cal-grid-wrap{display:none!important;}
[data-cal-view=list]  .cal-list-wrap{display:block!important;}
[data-cal-view=list]  .cal-year-wrap{display:none!important;}
[data-cal-view=year]  .cal-grid-wrap{display:none!important;}
[data-cal-view=year]  .cal-list-wrap{display:none!important;}
[data-cal-view=year]  .cal-year-wrap{display:block!important;}
.cal-tb-year-btn{display:none!important;}
@media(max-width:767px){.cal-tb-year-btn{display:inline-flex!important;}}
.cal-lr{display:flex;align-items:center;gap:8px;padding:10px 4px;border-bottom:1px solid var(--bd);
  text-decoration:none;color:var(--tx);min-height:44px;-webkit-tap-highlight-color:transparent;}
.cal-lr:active{background:var(--bd);}
.cal-lr-today{background:rgba(37,99,235,.07);border-left:3px solid var(--ac);padding-left:5px;}
.cal-lr-off .cal-lr-wd,.cal-lr-off .cal-lr-dm{color:var(--mu);}
.cal-lr-date{min-width:64px;display:flex;flex-direction:column;line-height:1.3;flex-shrink:0;}
.cal-lr-wd{font-size:11px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;}
.cal-lr-dm{font-size:15px;font-weight:700;}
.cal-lr-cnt{flex:1;display:flex;flex-wrap:wrap;gap:4px 8px;align-items:center;min-width:0;}
.cal-lr-h{font-size:13px;font-weight:700;color:var(--ok);}
.cal-lr-b{font-size:12px;padding:2px 5px;background:var(--bg);border-radius:4px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px;}
.cal-lr-hol{font-size:12px;font-weight:700;color:var(--danger);}
.cal-lr-trip{font-size:12px;color:var(--ac);}
.cal-lr-ico{min-width:20px;text-align:right;flex-shrink:0;}
.cal-lr-x{color:var(--danger);font-size:14px;font-weight:700;}
.cal-lr-lock{font-size:13px;opacity:.55;}
.cal-lr-ok{color:var(--ok);font-size:14px;font-weight:700;}
th.kw-head{width:32px;font-size:10px;color:var(--mu);font-weight:600;text-align:center;padding:4px 2px;}
td.kw-cell{width:32px;font-size:10px;color:var(--mu);font-weight:600;text-align:center;vertical-align:middle;padding:2px;white-space:nowrap;}
</style>"""

    cal_js = """<script>
function setCalView(v){
  try{
    if(v==='year'&&window.innerWidth>=768){v='month';}
    localStorage.setItem('cal_view',v);
    var w=document.getElementById('cal-wrap');
    if(w) w.setAttribute('data-cal-view',v);
    var bm=document.getElementById('cal-tb-month');
    var bl=document.getElementById('cal-tb-list');
    var by=document.getElementById('cal-tb-year');
    if(bm) bm.classList.toggle('primary',v==='month');
    if(bl) bl.classList.toggle('primary',v==='list');
    if(by) by.classList.toggle('primary',v==='year');
    if(v==='year'){
      var yw=document.querySelector('.cal-year-wrap');
      if(yw&&!yw.dataset.loaded){
        var yr=w?w.dataset.year:'';
        yw.innerHTML='<div style="padding:16px;color:var(--mu);text-align:center;font-size:13px;">Wird geladen…</div>';
        fetch('/calendar/year-list?y='+yr)
          .then(function(r){return r.text();})
          .then(function(html){yw.innerHTML=html;yw.dataset.loaded='1';})
          .catch(function(){yw.innerHTML='<div style="padding:12px;color:var(--danger);">Fehler beim Laden.</div>';});
      }
    }
  }catch(e){}
}
function calNavLeave(){
  try{if(localStorage.getItem('cal_view')==='year')localStorage.setItem('cal_view','list');}catch(e){}
}
(function(){
  try{ var v=localStorage.getItem('cal_view'); if(v) setCalView(v); }catch(e){}
})();
</script>"""

    js_kontiert_arr = "[" + ",".join(f'"{d}"' for d in sorted(contoured_month)) + "]"
    contour_js = f"""<script>
var _kontiert=new Set({js_kontiert_arr});
function toggleKontiert(iso,ev){{
  if(ev){{ev.preventDefault();ev.stopPropagation();}}
  var isK=_kontiert.has(iso);
  fetch('/api/contour',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{day:iso,action:isK?'unmark':'mark'}})
  }}).then(function(r){{return r.json();}}).then(function(d){{
    if(!d.ok)return;
    var nh=document.getElementById('nh_'+iso);
    var km=document.getElementById('km_'+iso);
    var hasNet=nh&&nh.dataset.hasNet==='1';
    var netVal=nh?(nh.dataset.net||''):'';
    if(isK){{
      _kontiert.delete(iso);
      if(nh){{
        if(hasNet){{nh.style.color='var(--mu)';nh.textContent=netVal;}}
        else{{nh.textContent='';nh.style.color='';}}
      }}
      if(km)km.textContent='✓ Als kontiert markieren';
    }}else{{
      _kontiert.add(iso);
      if(nh){{
        if(hasNet){{nh.style.color='#b45309';nh.textContent='· '+netVal;}}
        else{{nh.textContent='·';nh.style.color='#b45309';}}
      }}
      if(km)km.textContent='✕ Kontierung aufheben';
    }}
  }}).catch(function(){{}});
  return false;
}}
</script>"""

    body = f"""
    {flash_html()}
    {CALENDAR_DAYMENU_ASSETS}
    {cal_css}
    {contour_js}

    <div id="cal-wrap" class="card" data-year="{year}">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
        <div style="display:flex;align-items:center;gap:4px;">
          {prev_nav_btn}
          <span style="font-size:16px;font-weight:700;padding:0 6px;white-space:nowrap;">{month_label}{lock_badge}</span>
          <a class="btn" href="/calendar?y={next_y}&m={next_m}" style="padding:9px 14px;" onclick="calNavLeave()">&#9654;</a>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          <a class="btn" href="/calendar?y={today.year}&m={today.month}" onclick="calNavLeave()">Heute</a>
          <button id="cal-tb-month" class="btn" type="button" onclick="setCalView('month')" style="font-size:13px;padding:8px 10px;">&#8862; Monat</button>
          <button id="cal-tb-list"  class="btn" type="button" onclick="setCalView('list')"  style="font-size:13px;padding:8px 10px;">&#9776; Liste</button>
          <button id="cal-tb-year"  class="btn cal-tb-year-btn" type="button" onclick="setCalView('year')"  style="font-size:13px;padding:8px 10px;">&#9783; Jahr</button>
        </div>
      </div>

      <div class="cal-grid-wrap">
        {grid_html}
      </div>

      <div class="cal-list-wrap">
        {list_html}
      </div>

      <div class="cal-year-wrap"></div>
    </div>

    {"" if not _feature_enabled("staffing") else f'<div style="font-size:11px;color:var(--mu);margin-top:6px;padding:4px 2px;"><span style="color:#f59e0b">⭐</span> {t("staffing.override_title")}</div>'}

    {cal_js}
    """
    return render_template_string(layout(t("calendar.title"), body, u, APP_VERSION))





# -------------------------
# Tages-Editor (Zeitblöcke + Abwesenheit) – v2.9.1
# -------------------------

def _round_to_15(hhmm: str) -> str:
    """Round HH:MM minutes to nearest 15; returns unchanged string if not HH:MM."""
    if not hhmm or not re.match(r"^\d{2}:\d{2}$", hhmm):
        return hhmm
    h, m = int(hhmm[:2]), int(hhmm[3:])
    r = round(m / 15) * 15
    if r == 60:
        r, h = 0, (h + 1) % 24
    return f"{h:02d}:{r:02d}"


def _validate_block(time_in: str, time_out: str, break_minutes: int) -> tuple[bool, str]:
    if not re.match(r"^\d{2}:\d{2}$", time_in) or not re.match(r"^\d{2}:\d{2}$", time_out):
        return False, t("flash.error.time_format")
    s = _minutes_from_hhmm(time_in)
    e = _minutes_from_hhmm(time_out)
    if e <= s:
        return False, t("flash.error.time_order")
    if break_minutes < 0:
        return False, t("flash.error.break_negative")
    if break_minutes >= (e - s):
        return False, t("flash.error.break_too_large")
    return True, ""


def _exception_banner(day: str, is_blocked_day: bool, exc_row, locked: bool) -> str:
    if not is_blocked_day:
        return ""
    if exc_row is not None:
        note = exc_row["note"] or ""
        note_part = f" &ndash; <i style='font-weight:400;'>{note}</i>" if note else ""
        remove_btn = "" if locked else (
            f"<form method='post' action='/api/remove-exception' style='display:contents;'>"
            f"<input type='hidden' name='day' value='{day}'>"
            f"<button class='btn danger btn-sm' type='submit'>Entfernen</button></form>"
        )
        return (
            f"<div class='exc-banner exc-ok'>"
            f"<span style='flex:1;min-width:0;'>⚡ <b>Ausnahme aktiv</b>{note_part}"
            f"<span class='exc-sub'>Zeitblöcke an diesem Wochenende/Feiertag sind erlaubt.</span></span>"
            f"{remove_btn}</div>"
        )
    set_form = "" if locked else (
        f"<form method='post' action='/api/set-exception' style='display:flex;gap:6px;align-items:center;flex-wrap:wrap;'>"
        f"<input type='hidden' name='day' value='{day}'>"
        f"<input name='note' placeholder='Grund (optional)' style='font-size:13px;padding:4px 8px;width:160px;'>"
        f"<button class='btn primary btn-sm' type='submit'>Ausnahme setzen</button>"
        f"</form>"
    )
    return (
        f"<div class='exc-banner exc-warn'>"
        f"<span style='flex:1;min-width:0;'>⚠ <b>Wochenende / Feiertag</b>"
        f"<span class='exc-sub'>Ausnahme erforderlich, um Zeitblöcke zu erfassen.</span></span>"
        f"{set_form}</div>"
    )


def _business_trip_section_compact(day: str, trip, locked: bool = False) -> str:
    """Compact Dienstreise card for the redesigned day editor."""
    t = dict(trip) if trip else {}
    trip_id   = t.get("id") or ""
    dest      = t.get("destination") or ""
    dep       = t.get("departure_time") or ""
    dep_e     = t.get("departure_end_time") or ""
    ret       = t.get("return_time") or ""
    ret_e     = t.get("return_end_time") or ""
    notes     = t.get("notes") or ""
    start_iso = str(t.get("start_date") or day)[:10]
    end_iso   = str(t.get("end_date") or start_iso)[:10]
    is_multi  = (start_iso != end_iso)
    multi_checked = "checked" if is_multi else ""
    multi_display = "" if is_multi else "none"

    delete_btn = ""
    if trip_id and not locked:
        delete_btn = (
            f"<form method='post' action='/day/{day}/business_trip/delete' style='display:contents;'"
            f" onsubmit=\"return confirm('Dienstreise löschen?');\">"
            f"<input type='hidden' name='trip_id' value='{trip_id}'>"
            f"<button class='btn danger btn-sm' type='submit'>Löschen</button></form>"
        )

    hdr_label = "Dienstreise bearbeiten" if trip else "Dienstreise hinzufügen"
    if locked:
        hdr_label = "Dienstreise (schreibgeschützt)"

    inner = "" if locked else f"""
      <form method="post" action="/day/{day}/business_trip/save">
        <input type="hidden" name="trip_id" value="{trip_id}">
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-bottom:8px;">
          <div class="tb-field" style="flex:1;min-width:160px;">
            <label>Ort *</label>
            <input name="destination" required value="{dest}" placeholder="Reiseziel" style="font-size:13px;padding:5px 8px;">
          </div>
          <div class="tb-field">
            <label>Startdatum *</label>
            {_date_input("start_date", start_iso, required=True)}
          </div>
          <div class="tb-field" style="justify-content:flex-end;padding-bottom:6px;">
            <label style="font-weight:400;font-size:13px;"><input type="checkbox" onchange="toggleMultiday(this)" {multi_checked}> Mehrtägig</label>
          </div>
        </div>
        <div class="multiday-fields" style="display:{multi_display};margin-bottom:8px;">
          <div class="tb-field" style="display:inline-flex;">
            <label>Enddatum</label>
            {_date_input("end_date", end_iso if is_multi else "")}
          </div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
          <div class="tb-field"><label>Abreise</label>{_time_input("departure_time", dep)}</div>
          <div class="tb-field"><label>Am Ziel</label>{_time_input("departure_end_time", dep_e)}</div>
          <div class="tb-field"><label>Rückreise</label>{_time_input("return_time", ret)}</div>
          <div class="tb-field"><label>Zuhause</label>{_time_input("return_end_time", ret_e)}</div>
        </div>
        <div style="margin-bottom:8px;">
          <textarea name="notes" rows="2" placeholder="Notizen (optional)" style="font-size:13px;padding:5px 8px;">{notes}</textarea>
        </div>
        <div style="display:flex;gap:6px;">
          <button class="btn primary btn-sm" type="submit">Dienstreise speichern</button>
          <div style="display:contents;">{delete_btn}</div>
        </div>
      </form>"""

    if locked and trip:
        inner = (
            f"<div style='font-size:13px;'><b>{dest}</b> · {_fmt_date_de(start_iso)}"
            f"{' – ' + _fmt_date_de(end_iso) if is_multi else ''}</div>"
            f"<div class='small' style='color:var(--mu);margin-top:4px;'>🔒 Schreibgeschützt</div>"
        )
    elif locked:
        inner = "<div class='day-empty'>Keine Dienstreise / gesperrt.</div>"

    return (
        f"<div class='day-sec-hdr'>✈ {hdr_label}</div>"
        f"<div class='day-sec-body'>{inner}</div>"
    )


def _business_trip_section(day: str, trip, locked: bool = False) -> str:
    """Render the Dienstreise card for the day editor."""
    t = dict(trip) if trip else {}
    trip_id   = t.get("id") or ""
    dest      = t.get("destination") or ""
    dep       = t.get("departure_time") or ""
    dep_e     = t.get("departure_end_time") or ""
    ret       = t.get("return_time") or ""
    ret_e     = t.get("return_end_time") or ""
    notes     = t.get("notes") or ""
    start_iso = str(t.get("start_date") or day)[:10]
    end_iso   = str(t.get("end_date") or start_iso)[:10]
    is_multi  = (start_iso != end_iso)
    multi_checked = "checked" if is_multi else ""
    multi_display = "" if is_multi else "none"

    delete_btn = ""
    if trip_id and not locked:
        delete_btn = f"""
        <form method="post" action="/day/{day}/business_trip/delete" style="display:inline;"
              onsubmit="return confirm('Dienstreise löschen?');">
          <input type="hidden" name="trip_id" value="{trip_id}">
          <button class="btn danger" type="submit" style="margin-left:8px;">Löschen</button>
        </form>"""

    heading = "✈ Dienstreise bearbeiten" if trip else "✈ Dienstreise hinzufügen"
    if locked:
        heading = "✈ Dienstreise (schreibgeschützt)"

    return f"""
    <h3 style="margin-top:14px;">Dienstreise</h3>
    <div class="card" style="margin-top:4px;">
      <h3 style="margin-top:0;">{heading}</h3>
      <form method="post" action="/day/{day}/business_trip/save">
        <input type="hidden" name="trip_id" value="{trip_id}">
        <div style="margin-bottom:8px;">
          <label>Ort *</label><br>
          <input name="destination" required value="{dest}" placeholder="Reiseziel" style="max-width:360px;">
        </div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:8px;align-items:flex-end;">
          <div>
            <label>Startdatum *</label><br>
            {_date_input("start_date", start_iso, required=True)}
          </div>
          <div>
            <label style="font-weight:400;"><input type="checkbox" onchange="toggleMultiday(this)" {multi_checked}> Mehrtägig</label>
          </div>
        </div>
        <div class="multiday-fields" style="display:{multi_display};margin-bottom:8px;">
          <label>Enddatum</label><br>
          {_date_input("end_date", end_iso if is_multi else "")}
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;">
          <div><label>Abreise</label><br>{_time_input("departure_time", dep)}</div>
          <div><label>Ankunft Ziel</label><br>{_time_input("departure_end_time", dep_e)}</div>
          <div><label>Rückreise Start</label><br>{_time_input("return_time", ret)}</div>
          <div><label>Ankunft Zuhause</label><br>{_time_input("return_end_time", ret_e)}</div>
        </div>
        <div style="margin-bottom:8px;">
          <label>Notizen</label><br>
          <textarea name="notes" rows="2" placeholder="optional">{notes}</textarea>
        </div>
        {"" if locked else '<button class="btn" type="submit">Dienstreise speichern</button>'}
        {delete_btn}
      {"</form>" if not locked else "<p class='small' style='margin-top:6px;'>🔒 Schreibgeschützt</p>"}
    </div>"""




def _contouring_settings_card(user_id: int) -> str:
    ci = _get_contouring_info(user_id)
    today = datetime.date.today()
    default_start = datetime.date(today.year, today.month, 1).isoformat()
    if ci["enabled"]:
        start_label = _fmt_date_de(ci["start_date"]) if ci["start_date"] else "–"
        return f"""
    <div class="card">
      <h3 style="margin-top:0;">Kontierung</h3>
      <div style="margin-bottom:10px;">
        <span style="color:var(--ok);font-weight:600;">&#10003; Kontierung aktiv</span>
        <span style="color:var(--mu);font-size:13px;margin-left:8px;">seit {start_label}</span>
      </div>
      <form method="post" action="/settings/contouring/toggle"
            onsubmit="return confirm('Kontierung wirklich deaktivieren? Bestehende Kontierungen bleiben erhalten.');">
        <button class="btn danger" type="submit">Kontierung deaktivieren</button>
      </form>
    </div>"""
    else:
        return f"""
    <div class="card">
      <h3 style="margin-top:0;">Kontierung</h3>
      <div style="margin-bottom:12px;color:var(--mu);">Kontierung ist deaktiviert.</div>
      <form method="post" action="/settings/contouring/toggle" id="contour-enable-form">
        <div style="margin-bottom:10px;">
          <label>Kontierung gilt ab:</label><br>
          {_date_input("contouring_start_date", default_start)}
          <div class="small" style="color:#777;margin-top:3px;">
            Standard: 1. des aktuellen Monats. Tage vor diesem Datum werden nicht zur Kontierung herangezogen.
          </div>
        </div>
        <button class="btn primary" type="submit">Aktivieren</button>
      </form>
    </div>"""


def _render_calendar_integration_section(
    cal_system: str,
    cal_types: "list[str]",
    cal_prefix: str,
    cal_token: str,
    webcal_url: str,
    ical_url: str,
    cal_auth_mode: str = "token",
    basic_webcal_url: str = "",
    basic_ical_url: str = "",
    caldav_token_url: str = "",
    caldav_basic_url: str = "",
) -> str:
    lang = session.get("lang", "en")

    # Radio buttons for calendar system
    def _sys_radio(val: str, lbl: str) -> str:
        chk = "checked" if cal_system == val else ""
        return (f"<label style='display:flex;align-items:center;gap:6px;margin-bottom:6px;cursor:pointer;'>"
                f"<input type='radio' name='calendar_system' value='{val}' {chk}> {lbl}</label>")

    # Radio buttons for auth mode
    def _auth_radio(val: str, lbl: str) -> str:
        chk = "checked" if cal_auth_mode == val else ""
        return (f"<label style='display:flex;align-items:center;gap:6px;margin-bottom:6px;cursor:pointer;'>"
                f"<input type='radio' name='calendar_auth_mode' value='{val}' {chk}> {lbl}</label>")

    # Checkboxes for absence types
    def _type_cb(key: str, lbl: str) -> str:
        chk = "checked" if key in cal_types else ""
        return (f"<label style='display:flex;align-items:center;gap:6px;margin-bottom:4px;cursor:pointer;'>"
                f"<input type='checkbox' name='type_{key}' value='1' {chk}> {lbl}</label>")

    # Preview text
    _prefix_escaped = _html.escape(cal_prefix)
    _preview_label  = _html.escape(t("absence_type.urlaub", lang=lang))
    _preview_text   = f"{_prefix_escaped} {_preview_label}".strip() if cal_prefix else _preview_label

    # Instructions per system
    _instructions = {
        "apple":   t("settings.calendar_instructions_apple",   lang=lang),
        "google":  t("settings.calendar_instructions_google",  lang=lang),
        "outlook": t("settings.calendar_instructions_outlook", lang=lang),
        "ical":    "",
    }.get(cal_system, "")

    _copy_lbl    = _html.escape(t("btn.copy", lang=lang))
    _dl_url_year = "/absences/export/calendar?period=year"
    _dl_url_all  = "/absences/export/calendar?period=all"

    # URL block — depends on auth mode
    if cal_auth_mode == "basic":
        _primary_url   = basic_webcal_url if cal_system == "apple" else basic_ical_url
        _secondary_url = basic_ical_url
        _caldav_url    = caldav_basic_url
        _ics_block = f"""
        <div class="acc-sub">
          <b style="font-size:13px;">{t('settings.calendar_token_label')}</b>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap;">
            <input id="cal-sub-url" type="text" value="{_html.escape(_primary_url)}" readonly
                   style="flex:1;min-width:200px;font-size:12px;font-family:monospace;">
            <button class="btn btn-sm" type="button"
                    onclick="navigator.clipboard.writeText(document.getElementById('cal-sub-url').value)">{_copy_lbl}</button>
          </div>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap;">
            <input id="cal-sub-url2" type="text" value="{_html.escape(_secondary_url)}" readonly
                   style="flex:1;min-width:200px;font-size:12px;font-family:monospace;">
            <button class="btn btn-sm" type="button"
                    onclick="navigator.clipboard.writeText(document.getElementById('cal-sub-url2').value)">{_copy_lbl}</button>
          </div>
          <div class="small" style="color:var(--mu);margin-top:4px;">{_html.escape(t('settings.calendar_auth_basic_hint', lang=lang))}</div>
          <div class="small" style="color:var(--mu);margin-top:4px;">{_html.escape(t('settings.calendar_ha_hint', lang=lang))}</div>
        </div>"""
    else:
        _sub_url   = webcal_url if cal_system == "apple" else ical_url
        _caldav_url = caldav_token_url
        _ics_block = ""
        if _sub_url:
            _ics_block = f"""
        <div class="acc-sub">
          <b style="font-size:13px;">{t('settings.calendar_token_label')}</b>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap;">
            <input id="cal-sub-url" type="text" value="{_html.escape(_sub_url)}" readonly
                   style="flex:1;min-width:200px;font-size:12px;font-family:monospace;">
            <button class="btn btn-sm" type="button"
                    onclick="navigator.clipboard.writeText(document.getElementById('cal-sub-url').value)">{_copy_lbl}</button>
          </div>
          <div class="small" style="color:var(--mu);margin-top:4px;">{t('settings.calendar_subscribe_hint')}</div>
          <form method="post" action="/settings/calendar/reset-token" style="margin-top:10px;"
                onsubmit="return confirm('{_html.escape(t('settings.calendar_token_reset_warning'))}');">
            <button class="btn btn-sm danger" type="submit">{t('settings.calendar_token_reset')}</button>
          </form>
        </div>"""

    _caldav_block = ""
    if _caldav_url:
        _caldav_block = f"""
        <div class="acc-sub">
          <b style="font-size:13px;">{_html.escape(t('settings.calendar_caldav_url', lang=lang))}</b>
          <div style="display:flex;gap:6px;align-items:center;margin-top:6px;flex-wrap:wrap;">
            <input id="cal-caldav-url" type="text" value="{_html.escape(_caldav_url)}" readonly
                   style="flex:1;min-width:200px;font-size:12px;font-family:monospace;">
            <button class="btn btn-sm" type="button"
                    onclick="navigator.clipboard.writeText(document.getElementById('cal-caldav-url').value)">{_copy_lbl}</button>
          </div>
          <div class="small" style="color:var(--mu);margin-top:4px;">{_html.escape(t('settings.calendar_caldav_hint', lang=lang))}</div>
        </div>"""

    _url_block = _ics_block + _caldav_block

    _instr_html = f"<p class='small' style='color:var(--mu);margin-bottom:10px;'>{_html.escape(_instructions)}</p>" if _instructions else ""

    return f"""
    <div class="acc" id="acc-cal-int">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-cal-int-body')">
        <span>{t('settings.calendar_integration')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-cal-int-body">
        <div class="acc-inner">
          <form method="post" action="/settings/calendar">

            <div class="acc-sub" style="margin-top:0;padding-top:0;border-top:none;">
              <b style="font-size:13px;display:block;margin-bottom:8px;">{t('settings.calendar_system')}</b>
              {_sys_radio('apple',   t('settings.calendar_apple'))}
              {_sys_radio('google',  t('settings.calendar_google'))}
              {_sys_radio('outlook', t('settings.calendar_outlook'))}
              {_sys_radio('ical',    t('settings.calendar_other'))}
            </div>

            <div class="acc-sub">
              <b style="font-size:13px;display:block;margin-bottom:8px;">{t('settings.calendar_auth_mode')}</b>
              {_auth_radio('token', t('settings.calendar_auth_none',  lang=lang))}
              {_auth_radio('basic', t('settings.calendar_auth_basic', lang=lang))}
            </div>

            <div class="acc-sub">
              <b style="font-size:13px;display:block;margin-bottom:8px;">{t('settings.calendar_entry_settings')}</b>
              <div style="margin-bottom:10px;">
                <label>{t('settings.calendar_prefix')}</label>
                <input type="text" name="calendar_export_prefix" value="{_prefix_escaped}"
                       maxlength="20" style="width:200px;margin-top:4px;" placeholder="ZE: ">
                <div class="small" style="color:var(--mu);margin-top:3px;">{t('settings.calendar_prefix_hint')}</div>
                <div class="small" style="margin-top:4px;">
                  <b>{t('settings.calendar_prefix_preview')}</b> {_html.escape(_preview_text)}
                </div>
              </div>
              <div>
                <label style="display:block;margin-bottom:6px;">{t('settings.calendar_export_types')}</label>
                {_type_cb('urlaub',  t('absence_type.urlaub',  lang=lang))}
                {_type_cb('krank',   t('absence_type.krank',   lang=lang))}
                {_type_cb('flextag', t('absence_type.flextag', lang=lang))}
                {_type_cb('sonstige',t('absence_type.sonstige',lang=lang))}
              </div>
            </div>

            <div class="acc-sub" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
              <button class="btn btn-sm" type="submit">{t('common.save')}</button>
            </div>
          </form>

          <div class="acc-sub">
            <b style="font-size:13px;display:block;margin-bottom:8px;">{t('settings.calendar_export')}</b>
            {_instr_html}
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
              <a class="btn btn-sm" href="{_dl_url_year}">{t('settings.calendar_download')} ({t('settings.calendar_period_year')})</a>
              <a class="btn btn-sm" href="{_dl_url_all}">{t('settings.calendar_download')} ({t('settings.calendar_period_all')})</a>
            </div>
          </div>

          {_url_block}
        </div>
      </div>
    </div>"""


def _render_security_accordion(u: dict, totp_enabled: bool) -> str:
    _totp_status = t('settings.two_factor_enabled') if totp_enabled else t('settings.two_factor_disabled')
    _totp_color  = "var(--ok)" if totp_enabled else "var(--mu)"
    _last_login  = (u.get("last_login") or "")[:16].replace("T", " ")
    _attempts    = int(u.get("login_attempts") or 0)
    _attempts_color = "var(--danger)" if _attempts > 0 else "var(--ok)"

    _totp_section = f"""
      <div class="acc-sub">
        <b style="font-size:14px;">{t('settings.two_factor')}</b>
        <div style="margin-top:8px;">
          <span style="color:{_totp_color};font-weight:600;">{_totp_status}</span>
        </div>
        {"" if not totp_enabled else f'''
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
          <form method="post" action="/settings/2fa/backup-codes">
            <button class="btn btn-sm" type="submit">{t('settings.regenerate_backup_codes')}</button>
          </form>
          <form method="post" action="/settings/2fa/disable"
                onsubmit="return confirm('{t('settings.totp_disable_confirm')}');">
            <button class="btn danger btn-sm" type="submit">{t('settings.disable_2fa')}</button>
          </form>
        </div>'''}
        {"" if totp_enabled else f'''
        <div style="margin-top:10px;">
          <a class="btn btn-sm primary" href="/settings/2fa/enable">{t('settings.enable_2fa')}</a>
        </div>'''}
        <p class="small" style="color:var(--mu);margin-top:6px;">{t('settings.backup_codes_hint')}</p>
      </div>
      <div class="acc-sub">
        <b style="font-size:14px;">{t('settings.login_activity')}</b>
        <div style="margin-top:8px;font-size:13px;">
          <div>{t('settings.last_login')}: <b>{_last_login or "–"}</b></div>
          <div style="margin-top:4px;">{t('settings.failed_attempts')}: <span style="color:{_attempts_color};font-weight:600;">{_attempts}</span></div>
        </div>
      </div>
    """

    return f"""
    <div class="acc" id="acc-security">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-security-body')">
        <span>&#128274; {t('settings.security')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-security-body">
        <div class="acc-inner">
          <div class="acc-sub" style="border-top:none;margin-top:0;padding-top:0;">
            <b style="font-size:14px;">{t('settings.pw_section')}</b>
            <form method="post" action="/settings/password" style="display:flex;flex-direction:column;gap:10px;max-width:400px;margin-top:10px;">
              <div>
                <label>{t('settings.password_old')}</label><br>
                <input type="password" name="current_password" required autocomplete="current-password">
              </div>
              <div>
                <label>{t('settings.password_new')}</label><br>
                <input type="password" name="new_password" id="spw-inp" required autocomplete="new-password" minlength="6"
                       oninput="_pwUpdate('spw-inp','spw-chk','{_html.escape(u.get('username') or '')}')">
                <div id="spw-chk" style="margin-top:6px;padding:8px;background:var(--sf);border-radius:var(--rs);border:1px solid var(--bd);line-height:1.7;"></div>
              </div>
              <div>
                <label>{t('settings.pw_confirm_repeat')}</label><br>
                <input type="password" name="new_password_confirm" required autocomplete="new-password">
              </div>
              <div><button class="btn" type="submit">{t('btn.change_pw')}</button></div>
            </form>
          </div>
          {_totp_section}
        </div>
      </div>
    </div>
    {_PW_STRENGTH_JS}
    """


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



@calendar_routes_bp.get("/periods")
@login_required
def periods_view():
    from app import bootstrap, flash_html, layout, APP_VERSION, _get_period_lock_status, _get_tracking_start, _t_month, _fmt_date_de
    import datetime, calendar
    bootstrap()
    u = current_user()
    today = datetime.date.today()

    try:
        sel_year = int(request.args.get("y") or today.year)
    except (ValueError, TypeError):
        sel_year = today.year

    locks = _get_period_lock_status(u["id"], sel_year)
    year_locked = "year" in locks
    user_start = _get_tracking_start(u["id"])

    # username cache for "locked_by"
    db = connect()
    try:
        users_map = {r["id"]: r["username"] for r in db.execute("SELECT id, username FROM users").fetchall()}
    finally:
        db.close()

    def _lock_who(lock_row: dict) -> str:
        by = lock_row.get("locked_by")
        name = users_map.get(by, f"#{by}") if by else "–"
        ts = (lock_row.get("locked_at") or "")[:16]
        return f"{ts} · {name}"

    trs = ""
    for m in range(1, 13):
        key = f"{sel_year}-{m:02d}"
        month_last_day = f"{sel_year}-{m:02d}-{calendar.monthrange(sel_year, m)[1]:02d}"
        if user_start and month_last_day < user_start:
            trs += (
                f"<tr><td style='color:var(--mu);'>{_t_month(m)} {sel_year}</td>"
                f"<td><span class='small' style='color:var(--mu);'>{t('periods.before_start_short')}</span></td>"
                f"<td></td></tr>"
            )
            continue

        month_locked = year_locked or (key in locks)
        lock_row = locks.get(key) or locks.get("year") if month_locked else None

        # determine if month is past (lockable)
        month_is_past = (sel_year < today.year) or (sel_year == today.year and m < today.month)

        if month_locked:
            status_html = f"<span style='color:var(--ok);'>{t('periods.status_closed')}</span>"
            if lock_row:
                status_html += f" <span class='small'>({_lock_who(lock_row)})</span>"
            action = ""
            if u.get("is_admin"):
                # Only allow unlocking individual month locks (not inherited year locks)
                if key in locks:
                    action = (
                        f"<form method='post' action='/periods/unlock' style='display:inline;'>"
                        f"<input type='hidden' name='year' value='{sel_year}'>"
                        f"<input type='hidden' name='month' value='{m}'>"
                        f"<button class='btn danger btn-sm' >{t('btn.unlock')}</button></form>"
                    )
                else:
                    action = f"<span class='small' style='color:var(--mu);'>{t('periods.via_year_lock')}</span>"
        elif month_is_past:
            status_html = f"<span style='color:var(--mu);'>{t('periods.open_status')}</span>"
            action = (
                f"<form method='post' action='/periods/lock' style='display:inline;'>"
                f"<input type='hidden' name='year' value='{sel_year}'>"
                f"<input type='hidden' name='month' value='{m}'>"
                f"<button class='btn btn-sm' >{t('periods.close_btn')}</button></form>"
            )
        else:
            status_html = "<span class='small' style='color:var(--mu);'>–</span>"
            action = ""

        trs += (
            f"<tr><td><a href='/balance?y={sel_year}&m={m}'>{_t_month(m)} {sel_year}</a></td>"
            f"<td>{status_html}</td><td>{action}</td></tr>"
        )

    # Year-level lock row
    year_is_past = sel_year < today.year
    year_before_start = bool(user_start and f"{sel_year}-12-31" < user_start)
    if year_before_start:
        yr_status = f"<span class='small' style='color:var(--mu);'>{t('periods.before_start_short')}</span>"
        yr_action = ""
    elif year_locked:
        yr_status = f"<span style='color:var(--ok);'>{t('periods.year_closed_status')}</span>"
        lr = locks.get("year")
        if lr:
            yr_status += f" <span class='small'>({_lock_who(lr)})</span>"
        yr_action = ""
        if u.get("is_admin") and "year" in locks:
            yr_action = (
                f"<form method='post' action='/periods/unlock' style='display:inline;'>"
                f"<input type='hidden' name='year' value='{sel_year}'>"
                f"<button class='btn danger btn-sm' >{t('periods.year_unlock_btn')}</button></form>"
            )
    elif year_is_past:
        yr_status = f"<span style='color:var(--mu);'>{t('periods.open_status')}</span>"
        yr_action = (
            f"<form method='post' action='/periods/lock' style='display:inline;'>"
            f"<input type='hidden' name='year' value='{sel_year}'>"
            f"<button class='btn btn-sm' >{t('periods.year_close_btn')}</button></form>"
        )
    else:
        yr_status = f"<span class='small' style='color:var(--mu);'>{t('periods.running_year')}</span>"
        yr_action = ""

    available_years = list(range(max(today.year - 5, 2020), today.year + 1))
    if user_start:
        _sy = int(user_start[:4])
        if _sy not in available_years:
            available_years = sorted(set(available_years) | {_sy})
    year_opts = "".join(
        f'<option value="{y}" {"selected" if y == sel_year else ""}>{y}</option>'
        for y in reversed(available_years)
    )

    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">{t('periods.title')}</h3>
        <form method="get" style="display:flex;gap:8px;align-items:end;">
          <div><label>{t('periods.year_label')}</label><br><select name="y">{year_opts}</select></div>
          <button class="btn" type="submit">{t('periods.show_btn')}</button>
        </form>
      </div>
      <p class="small" style="margin-top:8px;">{t('periods.info_text')}</p>
      <table style="margin-top:12px;">
        <thead><tr><th>{t('periods.month_col')}</th><th>{t('common.status')}</th><th></th></tr></thead>
        <tbody>{trs}</tbody>
      </table>
      <hr>
      <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;">
        <b>{t('periods.year_label')} {sel_year}:</b> {yr_status} {yr_action}
      </div>
    </div>
    """
    return render_template_string(layout(t("periods.title"), body, u, APP_VERSION))



@calendar_routes_bp.post("/periods/lock")
@login_required
def periods_lock():
    from app import bootstrap, add_flash, _get_tracking_start, _lock_period, _t_month, _fmt_date_de
    import datetime, calendar
    bootstrap()
    u = current_user()
    today = datetime.date.today()
    try:
        year = int(request.form.get("year") or 0)
        month_raw = request.form.get("month") or ""
        month = int(month_raw) if month_raw.strip() else None
    except (ValueError, TypeError):
        add_flash(t("flash.invalid_input"), "error")
        return redirect("/periods")

    # Guard: cannot lock current or future month
    if month is not None:
        lockable = (year < today.year) or (year == today.year and month < today.month)
        if not lockable:
            add_flash(t("periods.past_months_only"), "error")
            return redirect(f"/periods?y={year}")
    else:
        if year >= today.year:
            add_flash(t("periods.past_years_only"), "error")
            return redirect(f"/periods?y={year}")

    user_start = _get_tracking_start(u["id"])
    if user_start and month:
        period_last_day = f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
        if period_last_day < user_start:
            add_flash(t("periods.before_start_err").format(date=_fmt_date_de(user_start)), "error")
            return redirect(f"/periods?y={year}")
    _lock_period(u["id"], year, month, locked_by=u["id"])
    label = f"{_t_month(month)} {year}" if month else f"{t('periods.whole_year')} {year}"
    add_flash(t("flash.success.period_closed").format(label=label), "success")
    return redirect(f"/periods?y={year}")



@calendar_routes_bp.post("/periods/unlock")
@login_required
def periods_unlock():
    from app import bootstrap, add_flash, _unlock_period, _t_month
    import datetime
    bootstrap()
    u = current_user()
    if not u.get("is_admin"):
        abort(403)
    try:
        year = int(request.form.get("year") or 0)
        month_raw = request.form.get("month") or ""
        month = int(month_raw) if month_raw.strip() else None
    except (ValueError, TypeError):
        add_flash(t("flash.invalid_input"), "error")
        return redirect("/periods")

    _unlock_period(u["id"], year, month)
    label = f"{_t_month(month)} {year}" if month else f"{t('periods.whole_year')} {year}"
    add_flash(t("flash.success.period_unlocked").format(label=label), "success")
    return redirect(f"/periods?y={year}")



# -------------------------
# Admin: Benutzer
# -------------------------

