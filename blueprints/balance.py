"""
Blueprint: Gleitzeitkonto und Salden.
"""
from flask import Blueprint, request, redirect, url_for, render_template_string, Response
from db import connect
from auth import login_required, admin_required, current_user
from translations import t

balance_bp = Blueprint("balance", __name__)

@balance_bp.get("/balance")
@login_required
def balance_view():
    from app import bootstrap, flash_html, layout, APP_VERSION, _actual_minutes_for_day, _expected_minutes_for_day, _iter_days, _get_start_balance_minutes, _fetch_flextag_ranges, _is_flextag, _scheduled_minutes_ignoring_absence, _get_tracking_start, _fmt_minutes_signed, _balance_color, _fmt_minutes, _fmt_date_de, _get_user_holiday_region, _feature_enabled, _render_absence_summary_card, _days_with_any_entry, _t_month
    import datetime, calendar, html as _html
    bootstrap()
    u = current_user()
    if u and u.get("admin_only"):
        return redirect("/admin")
    today = datetime.date.today()

    try:
        sel_year = int(request.args.get("y") or today.year)
    except (ValueError, TypeError):
        sel_year = today.year
    try:
        sel_month = int(request.args.get("m") if request.args.get("m") is not None else today.month)
    except (ValueError, TypeError):
        sel_month = today.month
    only = (request.args.get("only") or "").strip()

    # Available years: from earliest data entry to current year
    db = connect()
    try:
        row = db.execute("""
            SELECT MIN(y) AS min_y FROM (
                SELECT CAST(SUBSTR(day,1,4) AS INTEGER) AS y FROM time_blocks WHERE user_id=?
                UNION ALL
                SELECT CAST(SUBSTR(date_from,1,4) AS INTEGER) AS y FROM absences WHERE user_id=?
            ) t
        """, (u["id"], u["id"])).fetchone()
        min_year = int(row["min_y"]) if row and row["min_y"] else today.year
    except Exception:
        min_year = today.year
    db.close()
    min_year = min(min_year, today.year)
    available_years = list(range(min_year, today.year + 1))
    if sel_year not in available_years:
        sel_year = today.year
    if sel_month not in range(0, 13):
        sel_month = today.month

    # ── Kumulativer Saldo ab 01.01 des gewählten Jahres ──────────────────
    year_start = datetime.date(sel_year, 1, 1).isoformat()
    year_end   = min(datetime.date(sel_year, 12, 31), today).isoformat()
    # Respect tracking_start_date
    if u.get("tracking_start_date"):
        year_start = max(year_start, u["tracking_start_date"])
    today_iso  = today.isoformat()
    start_minutes = _get_start_balance_minutes(u["id"])
    flextag_ranges = _fetch_flextag_ranges(u["id"])
    running = int(start_minutes)
    all_rows: list[dict] = []
    for iso in _iter_days(year_start, year_end):
        expected = int(_expected_minutes_for_day(u["id"], iso) or 0)
        actual   = int(_actual_minutes_for_day(u["id"], iso) or 0)
        flextag_min = 0
        if iso < today_iso and expected == 0 and _is_flextag(iso, flextag_ranges):
            flextag_min = _scheduled_minutes_ignoring_absence(u["id"], iso)
        delta    = actual - expected - flextag_min
        running += delta
        all_rows.append({"day": iso, "expected": expected, "actual": actual,
                         "delta": delta, "running": running, "flextag_min": flextag_min})

    # ── Manuelle Korrekturen einmischen ──────────────────────────────────
    try:
        _db_adj = connect()
        _adjustments = _db_adj.execute(
            "SELECT ba.*, u.display_name as creator_name "
            "FROM balance_adjustments ba "
            "LEFT JOIN users u ON u.id=ba.created_by "
            "WHERE ba.user_id=? AND ba.adjustment_date BETWEEN ? AND ? "
            "ORDER BY ba.adjustment_date",
            (u["id"], year_start, year_end)
        ).fetchall()
        _db_adj.close()
        for _adj in _adjustments:
            _adj_iso = _adj["adjustment_date"]
            _adj_min = int(_adj["minutes"])
            _insert_at = len(all_rows)
            for _i, _row in enumerate(all_rows):
                if _row["day"] > _adj_iso:
                    _insert_at = _i
                    break
            _prev_running = all_rows[_insert_at - 1]["running"] if _insert_at > 0 else int(start_minutes)
            _new_running = _prev_running + _adj_min
            _adj_row = {
                "day": _adj_iso, "expected": 0, "actual": 0,
                "delta": _adj_min, "running": _new_running, "flextag_min": 0,
                "_type": "adjustment", "_reason": _adj["reason"],
            }
            all_rows.insert(_insert_at, _adj_row)
            for _r in all_rows[_insert_at + 1:]:
                _r["running"] += _adj_min
    except Exception:
        pass

    # ── Anzeigebereich bestimmen ─────────────────────────────────────────
    if sel_month == 0:
        display_start = year_start
        display_end   = year_end
        period_label  = f"{t('month.whole_year')} {sel_year}"
        period_start_balance = start_minutes
    else:
        m_last_day    = calendar.monthrange(sel_year, sel_month)[1]
        display_start = datetime.date(sel_year, sel_month, 1).isoformat()
        display_end   = datetime.date(sel_year, sel_month, m_last_day).isoformat()
        prior = [r for r in all_rows if r["day"] < display_start]
        period_start_balance = prior[-1]["running"] if prior else start_minutes
        period_label = f"{_t_month(sel_month)} {sel_year}"

    display_rows_full = [r for r in all_rows if display_start <= r["day"] <= display_end]

    if only == "1":
        entry_days = _days_with_any_entry(u["id"], display_start, display_end)
        display_rows = [r for r in display_rows_full if r["day"] in entry_days]
    else:
        display_rows = display_rows_full

    period_end_balance = display_rows_full[-1]["running"] if display_rows_full else period_start_balance

    # ── Dropdowns ────────────────────────────────────────────────────────
    year_opts = "".join(
        f'<option value="{y}" {"selected" if y == sel_year else ""}>{y}</option>'
        for y in reversed(available_years)
    )
    month_opts = f'<option value="0" {"selected" if sel_month == 0 else ""}>{t("month.whole_year")}</option>'
    for mi in range(1, 13):
        month_opts += f'<option value="{mi}" {"selected" if mi == sel_month else ""}>{_t_month(mi)}</option>'

    # ── Status-Badges (Abwesenheiten + Feiertage) für den Anzeigebereich ────
    _day_status: dict[str, list[tuple[str, str]]] = {}
    _db2 = connect()
    for _ab in _db2.execute(
        """SELECT a.date_from, a.date_to, t.name AS type_name, t.color AS type_color
           FROM absences a JOIN absence_types t ON t.id=a.type_id
           WHERE a.user_id=? AND NOT (a.date_to < ? OR a.date_from > ?)""",
        (u["id"], display_start, display_end),
    ).fetchall():
        _d0 = datetime.date.fromisoformat(_ab["date_from"])
        _d1 = datetime.date.fromisoformat(_ab["date_to"])
        _cur = _d0
        while _cur <= _d1:
            _iso = _cur.isoformat()
            if display_start <= _iso <= display_end:
                _day_status.setdefault(_iso, []).append((_ab["type_name"], _ab["type_color"] or "#6c757d"))
            _cur += datetime.timedelta(days=1)
    # Sonderschichten (staffing_overrides) für diesen User
    if _feature_enabled("staffing"):
        _db2_so = connect()
        try:
            _overrides = _db2_so.execute("""
                SELECT so.iso_date, ss.label as slot_label,
                       ss.time_from, ss.time_to,
                       sp.name as plan_name
                FROM staffing_overrides so
                JOIN staffing_slots ss ON ss.id = so.slot_id
                JOIN staffing_plans sp ON sp.id = so.plan_id
                WHERE so.user_id = ?
                AND so.status IN ('assigned', 'confirmed')
                AND so.iso_date BETWEEN ? AND ?
            """, (u["id"], display_start, display_end)).fetchall()
            for _ov in _overrides:
                _iso = str(_ov["iso_date"])[:10]
                _time_str = ""
                if _ov["time_from"] and _ov["time_to"]:
                    _time_str = f' {_ov["time_from"]}-{_ov["time_to"]}'
                _label = f'⭐ {_ov["slot_label"]}{_time_str}'
                _day_status.setdefault(_iso, []).append(
                    (_label, "#f59e0b")
                )
        finally:
            _db2_so.close()
    _holiday_days: set = set()
    _bal_region = _get_user_holiday_region(u["id"])
    for _hol in _db2.execute(
        "SELECT day, holiday_name FROM calendar_days WHERE is_holiday=1 AND region=? AND day BETWEEN ? AND ?",
        (_bal_region, display_start, display_end),
    ).fetchall():
        _iso_hol = str(_hol["day"])[:10]
        _holiday_days.add(_iso_hol)
        _day_status.setdefault(_iso_hol, []).append((_hol["holiday_name"], "var(--danger)"))
    _db2.close()

    # ── Zeitblöcke (Beginn/Ende/Pause) für Mobile – alle Blöcke pro Tag ─
    _all_blocks_map: dict = {}  # day -> [{t_in, t_out, brk}, ...]
    _db3 = connect()
    for _blk in _db3.execute(
        "SELECT day, time_in, time_out, break_minutes"
        " FROM time_blocks WHERE user_id=? AND day BETWEEN ? AND ?"
        " ORDER BY day, time_in",
        (u["id"], display_start, display_end),
    ).fetchall():
        _day_key = str(_blk["day"])[:10]
        _all_blocks_map.setdefault(_day_key, []).append({
            "t_in": str(_blk["time_in"] or "")[:5],
            "t_out": str(_blk["time_out"] or "")[:5],
            "brk": int(_blk["break_minutes"] or 0),
        })
    _db3.close()

    # ── Mobile Navigation ────────────────────────────────────────────────
    def _mob_nav_btn(url, lbl):
        if url:
            return f"<a href='{url}' class='btn btn-sm'>{lbl}</a>"
        return f"<span class='btn btn-sm' style='opacity:.28;cursor:not-allowed;'>{lbl}</span>"

    mob_prev_year_url = f"/balance?y={sel_year - 1}&m={sel_month}" if sel_year > min_year else None
    mob_next_year_url = f"/balance?y={sel_year + 1}&m={sel_month}" if sel_year < today.year else None

    if sel_month == 0:
        _pm_y, _pm_m = sel_year - 1, 12
        _nm_y, _nm_m = sel_year, 1
        mob_month_label = t("month.whole_year")
    else:
        _pm_y = sel_year - 1 if sel_month == 1 else sel_year
        _pm_m = 12 if sel_month == 1 else sel_month - 1
        _nm_y = sel_year + 1 if sel_month == 12 else sel_year
        _nm_m = 1 if sel_month == 12 else sel_month + 1
        mob_month_label = _t_month(sel_month)

    mob_prev_month_url = f"/balance?y={_pm_y}&m={_pm_m}" if _pm_y >= min_year else None
    mob_next_month_url = f"/balance?y={_nm_y}&m={_nm_m}" if _nm_y <= today.year else None

    mob_yr_prev = _mob_nav_btn(mob_prev_year_url, "&#9664;")
    mob_yr_next = _mob_nav_btn(mob_next_year_url, "&#9654;")
    mob_mo_prev = _mob_nav_btn(mob_prev_month_url, "&#9664;")
    mob_mo_next = _mob_nav_btn(mob_next_month_url, "&#9654;")

    # ── Mobile Tabellenzeilen ────────────────────────────────────────────
    mob_trs = ""

    # ── Desktop Tabellenzeilen ───────────────────────────────────────────
    _wd_names = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    trs = ""
    for r in display_rows:
        if r.get("_type") == "adjustment":
            _adj_clr = "#a855f7"
            _adj_min = r["delta"]
            _adj_sign = "+" if _adj_min >= 0 else ""
            _adj_h = f"{_adj_sign}{_fmt_minutes_signed(_adj_min)}"
            _run_clr = _balance_color(r["running"])
            _td = "style='padding:8px 6px;vertical-align:middle;'"
            _td_r = "style='padding:8px 6px;vertical-align:middle;text-align:right;'"
            trs += (
                f"<tr style='border-bottom:1px solid var(--bd);"
                f"background:color-mix(in srgb,{_adj_clr} 6%,var(--bg));'>"
                f"<td {_td} style='padding:8px 6px;color:{_adj_clr};'>📋</td>"
                f"<td {_td} style='padding:8px 6px;color:{_adj_clr};font-size:12px;'>"
                f"{_fmt_date_de(r['day'])}</td>"
                f"<td {_td} colspan='6' style='padding:8px 6px;font-size:12px;"
                f"color:{_adj_clr};'>{t('balance.adjustment')}: "
                f"{_html.escape(r.get('_reason',''))}</td>"
                f"<td {_td_r}><b style='color:{_adj_clr};'>{_adj_h}</b></td>"
                f"<td {_td_r}><b style='color:{_run_clr};'>{_fmt_minutes_signed(r['running'])}</b></td>"
                f"</tr>"
            )
            continue
        _d_obj    = datetime.date.fromisoformat(r["day"])
        _wd_lbl   = _wd_names[_d_obj.weekday()]
        _blocks_d = _all_blocks_map.get(r["day"], [])
        _statuses = _day_status.get(r["day"], [])
        _is_today_d   = r["day"] == today_iso
        _is_holiday_d = r["day"] in _holiday_days
        _is_off_d     = (r["expected"] == 0 and r["actual"] == 0 and not _statuses) or _is_holiday_d
        _is_missing_d = r["expected"] > 0 and r["actual"] == 0 and not _statuses and r["day"] < today_iso
        delta_clr   = _balance_color(r["delta"])
        running_clr = _balance_color(r["running"])
        _delta_str_d   = _fmt_minutes_signed(r["delta"]) if (r["delta"] != 0 or r["actual"] > 0) else ""
        _running_str_d = _fmt_minutes_signed(r["running"])
        _date_str_d    = _fmt_date_de(r["day"])
        _soll_str_d    = _fmt_minutes(r["expected"]) if r["expected"] else ""

        # Build status badge HTML (absence + flextag)
        _status_html = ""
        for _label, _color in _statuses[:2]:
            if _color.startswith("#"):
                _bg = _color + "22"
            elif _color == "var(--danger)":
                _bg = "rgba(220,38,38,.15)"
            else:
                _bg = "rgba(0,0,0,.07)"
            _status_html += (
                f"<span style='font-size:10px;padding:1px 5px;border-radius:4px;"
                f"background:{_bg};color:{_color};white-space:nowrap;font-weight:600;'>"
                f"{_label}</span> "
            )
        if r.get("flextag_min"):
            _status_html += (
                f"<span style='font-size:10px;padding:1px 5px;border-radius:4px;"
                f"background:rgba(37,99,235,.1);color:var(--ac);white-space:nowrap;'>"
                f"Flextag&nbsp;−{_fmt_minutes(r['flextag_min'])}</span>"
            )

        # Row base style
        if _is_missing_d:
            _base_d = "background:rgba(220,38,38,.08);"
        elif _is_today_d:
            _base_d = "background:rgba(37,99,235,.09);border-left:3px solid var(--ac);"
        elif _is_holiday_d:
            # Color-dim only: badge keeps its explicit color (var(--danger) overrides inherited color)
            _base_d = "color:var(--mu);"
        elif _is_off_d:
            _base_d = "opacity:.38;"
        else:
            _base_d = ""

        _td = "style='padding:8px 6px;vertical-align:middle;'"
        _td_r = "style='padding:8px 6px;vertical-align:middle;text-align:right;'"

        # Single row (no blocks or absence-only day)
        if not _blocks_d:
            trs += (
                f"<tr style='cursor:pointer;border-bottom:1px solid var(--bd);{_base_d}'"
                f" onclick=\"location.href='/day/{r['day']}'\">"
                f"<td {_td} style='padding:8px 6px;color:var(--mu);white-space:nowrap;'>{_wd_lbl}</td>"
                f"<td {_td} style='padding:8px 6px;white-space:nowrap;'>"
                f"<a href='/day/{r['day']}' style='text-decoration:none;color:inherit;'>{_date_str_d}"
                f"<span style='font-size:11px;opacity:.35;margin-left:3px;'>&#8599;</span></a></td>"
                f"<td {_td}>{_status_html}</td>"
                f"<td {_td}></td><td {_td}></td>"
                f"<td {_td_r}></td>"
                f"<td {_td_r}></td>"
                f"<td {_td_r} style='padding:8px 6px;text-align:right;color:var(--mu);'>{_soll_str_d}</td>"
                f"<td {_td_r}><b style='color:{delta_clr};'>{_delta_str_d}</b></td>"
                f"<td {_td_r}><b style='color:{running_clr};'>{_running_str_d}</b></td>"
                f"</tr>"
            )
            continue

        # Multi-block rows
        _total_brk_d = sum(b["brk"] for b in _blocks_d)
        _ist_str_d = _fmt_minutes(r["actual"]) if r["actual"] > 0 else ""
        for _bi, _blk_i in enumerate(_blocks_d):
            _is_first = _bi == 0
            _is_last  = _bi == len(_blocks_d) - 1
            _border = "border-bottom:1px solid var(--bd);" if _is_last else "border-bottom:1px solid rgba(128,128,128,.13);"
            _t_in  = _blk_i["t_in"]

            if _is_first:
                _disp_t_out   = _blocks_d[-1]["t_out"]
                _disp_pause   = str(_total_brk_d) if _total_brk_d else ""
                _disp_ist     = _ist_str_d
                _wd_cell    = f"<td {_td} style='padding:8px 6px;color:var(--mu);white-space:nowrap;'>{_wd_lbl}</td>"
                _date_cell  = (
                    f"<td {_td} style='padding:8px 6px;white-space:nowrap;'>"
                    f"<a href='/day/{r['day']}' style='text-decoration:none;color:inherit;'>{_date_str_d}"
                    f"<span style='font-size:11px;opacity:.35;margin-left:3px;'>&#8599;</span></a></td>"
                )
                _stat_cell  = f"<td {_td}>{_status_html}</td>"
                _ist_cell   = f"<td {_td_r}>{_disp_ist}</td>"
                _soll_cell  = f"<td {_td_r} style='padding:8px 6px;text-align:right;color:var(--mu);'>{_soll_str_d}</td>"
                _delta_cell = f"<td {_td_r}><b style='color:{delta_clr};'>{_delta_str_d}</b></td>"
                _run_cell   = f"<td {_td_r}><b style='color:{running_clr};'>{_running_str_d}</b></td>"
            else:
                _disp_t_out   = _blk_i["t_out"]
                _disp_pause   = ""
                _wd_cell    = f"<td {_td}></td>"
                _date_cell  = f"<td {_td}></td>"
                _stat_cell  = f"<td {_td}></td>"
                _ist_cell   = f"<td {_td_r}></td>"
                _soll_cell  = f"<td {_td_r}></td>"
                _delta_cell = f"<td {_td}></td>"
                _run_cell   = f"<td {_td}></td>"

            trs += (
                f"<tr style='cursor:pointer;{_base_d}{_border}'"
                f" onclick=\"location.href='/day/{r['day']}'\">"
                f"{_wd_cell}{_date_cell}{_stat_cell}"
                f"<td {_td}>{_t_in}</td>"
                f"<td {_td}>{_disp_t_out}</td>"
                f"<td {_td_r}>{_disp_pause}</td>"
                f"{_ist_cell}"
                f"{_soll_cell}{_delta_cell}{_run_cell}"
                f"</tr>"
            )

    # ── Mobile Tabellenzeilen (Schleife) ────────────────────────────────
    for r in display_rows:
        _d_obj_m      = datetime.date.fromisoformat(r["day"])
        _wd_m         = _wd_names[_d_obj_m.weekday()]
        _blocks_m     = _all_blocks_map.get(r["day"], [])
        _stat_m       = _day_status.get(r["day"], [])
        _is_today_m   = r["day"] == today_iso
        _is_holiday_m = r["day"] in _holiday_days
        _is_off_m     = (r["expected"] == 0 and r["actual"] == 0 and not _stat_m) or _is_holiday_m
        _is_missing_m = r["expected"] > 0 and r["actual"] == 0 and not _stat_m and r["day"] < today_iso
        _delta_clr_m  = _balance_color(r["delta"])
        _delta_str_m  = _fmt_minutes_signed(r["delta"]) if (r["delta"] != 0 or r["actual"] > 0) else ""
        _date_str_m   = f"{_d_obj_m.day:02d}.{_d_obj_m.month:02d}."
        _soll_str_m   = _fmt_minutes(r["expected"]) if r["expected"] else ""

        # Base style for all rows of this day
        if _is_missing_m:
            _base_style = "background:rgba(220,38,38,.08);"
        elif _is_today_m:
            _base_style = "background:rgba(37,99,235,.09);border-left:3px solid var(--ac);"
        elif _is_holiday_m:
            # Color-dim only: badge keeps its explicit color (var(--danger) overrides inherited color)
            _base_style = "color:var(--mu);"
        elif _is_off_m:
            _base_style = "opacity:.38;"
        else:
            _base_style = ""

        # Absence days: single row with badge spanning time columns
        if _stat_m:
            _abs_label = _stat_m[0][0]
            _abs_color = _stat_m[0][1]
            if _abs_color.startswith("#"):
                _abs_bg = _abs_color + "22"
            elif _abs_color == "var(--danger)":
                _abs_bg = "rgba(220,38,38,.15)"
            else:
                _abs_bg = "rgba(0,0,0,.07)"
            mob_trs += (
                f"<tr style='cursor:pointer;border-bottom:1px solid var(--bd);{_base_style}'"
                f" onclick=\"location.href='/day/{r['day']}'\">"
                f"<td style='padding:4px 4px;color:var(--mu);font-size:12px;'>{_wd_m}</td>"
                f"<td style='padding:4px 2px;font-weight:500;white-space:nowrap;'>{_date_str_m}</td>"
                f"<td style='padding:4px 2px;'>"
                f"<span style='font-size:10px;padding:1px 5px;border-radius:3px;"
                f"background:{_abs_bg};color:{_abs_color};font-weight:600;white-space:nowrap;'>{_abs_label}</span>"
                f"</td>"
                f"<td></td><td></td><td></td><td></td>"
                f"</tr>"
            )
            continue

        # No blocks: single empty row (missing or off day)
        if not _blocks_m:
            mob_trs += (
                f"<tr style='cursor:pointer;border-bottom:1px solid var(--bd);{_base_style}'"
                f" onclick=\"location.href='/day/{r['day']}'\">"
                f"<td style='padding:4px 4px;color:var(--mu);font-size:12px;'>{_wd_m}</td>"
                f"<td style='padding:4px 2px;font-weight:500;white-space:nowrap;'>{_date_str_m}</td>"
                f"<td style='padding:4px 2px;'></td>"
                f"<td style='padding:4px 2px;'></td>"
                f"<td style='padding:4px 2px;'></td>"
                f"<td style='padding:4px 2px;text-align:right;color:var(--mu);font-size:12px;'>{_soll_str_m}</td>"
                f"<td style='padding:4px 4px;text-align:right;font-weight:700;white-space:nowrap;"
                f"color:{_delta_clr_m};'>{_delta_str_m}</td>"
                f"</tr>"
            )
            continue

        # One or more blocks: one row per block
        _total_brk_m = sum(b["brk"] for b in _blocks_m)
        _ist_str_m = _fmt_minutes(r["actual"]) if r["actual"] > 0 else ""
        for _bi, _blk_i in enumerate(_blocks_m):
            _is_first = _bi == 0
            _is_last  = _bi == len(_blocks_m) - 1
            _border = "border-bottom:1px solid var(--bd);" if _is_last else "border-bottom:1px solid rgba(128,128,128,.13);"
            _t_in  = _blk_i["t_in"]
            if _is_first:
                _t_out_m    = _blocks_m[-1]["t_out"]
                _disp_brk_m = str(_total_brk_m) if _total_brk_m else ""
                _disp_ist_m = _ist_str_m
                _wd_cell    = f"<td style='padding:4px 4px;color:var(--mu);font-size:12px;'>{_wd_m}</td>"
                _date_cell  = f"<td style='padding:4px 2px;font-weight:500;white-space:nowrap;'>{_date_str_m}</td>"
                _soll_cell_m = f"<td style='padding:4px 2px;text-align:right;color:var(--mu);font-size:12px;'>{_soll_str_m}</td>"
                _delta_cell = (
                    f"<td style='padding:4px 4px;text-align:right;font-weight:700;white-space:nowrap;"
                    f"color:{_delta_clr_m};'>{_delta_str_m}</td>"
                )
            else:
                _t_out_m    = _blk_i["t_out"]
                _disp_brk_m = ""
                _disp_ist_m = ""
                _wd_cell     = "<td style='padding:4px 4px;'></td>"
                _date_cell   = "<td style='padding:4px 2px;'></td>"
                _soll_cell_m = "<td style='padding:4px 2px;'></td>"
                _delta_cell  = "<td style='padding:4px 4px;'></td>"
            mob_trs += (
                f"<tr style='cursor:pointer;{_base_style}{_border}'"
                f" onclick=\"location.href='/day/{r['day']}'\">"
                f"{_wd_cell}"
                f"{_date_cell}"
                f"<td style='padding:4px 2px;white-space:nowrap;font-size:12px;'>{_t_in}–{_t_out_m}</td>"
                f"<td style='padding:4px 2px;text-align:right;color:var(--mu);font-size:12px;'>{_disp_brk_m}</td>"
                f"<td style='padding:4px 2px;text-align:right;font-size:12px;'>{_disp_ist_m}</td>"
                f"{_soll_cell_m}"
                f"{_delta_cell}"
                f"</tr>"
            )

    start_hhmm        = _fmt_minutes_signed(start_minutes)
    period_start_hhmm = _fmt_minutes_signed(period_start_balance)
    period_end_hhmm   = _fmt_minutes_signed(period_end_balance)
    period_start_clr  = _balance_color(period_start_balance)
    period_end_clr    = _balance_color(period_end_balance)

    body = f"""
    {flash_html()}
    <style>
    .bal-mob{{display:none;}}
    @media(max-width:768px){{
      .bal-desk{{display:none!important;}}
      .bal-mob{{display:block!important;}}
    }}
    .mob-bal-tbl{{width:100%;table-layout:fixed;border-collapse:collapse;font-size:13px;}}
    @media(max-width:480px){{
      .mob-bal-tbl{{font-size:11px;}}
      .mob-bal-tbl td,.mob-bal-tbl th{{padding-left:1px!important;padding-right:1px!important;}}
    }}
    </style>
    <div class="bal-desk">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Gleitzeitkonto</h3>
        <div class="small">{period_label}</div>
      </div>

      <form method="get" style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-top:12px;">
        <div><label>Jahr</label><br><select name="y">{year_opts}</select></div>
        <div><label>Monat</label><br><select name="m">{month_opts}</select></div>
        <div class="small" style="padding-bottom:4px;">
          <label><input type="checkbox" name="only" value="1" {"checked" if only == "1" else ""}> nur Tage mit Einträgen</label>
        </div>
        <div><button class="btn" type="submit">Anzeigen</button></div>
      </form>

      <div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:14px;">
        <div style="flex:1;min-width:160px;">
          <div class="small">Saldo zu Periodenbeginn</div>
          <div style="font-size:22px;color:{period_start_clr};"><b>{period_start_hhmm}</b></div>
        </div>
        <div style="flex:1;min-width:160px;">
          <div class="small">Saldo zum Periodenende</div>
          <div style="font-size:22px;color:{period_end_clr};"><b>{period_end_hhmm}</b></div>
        </div>
      </div>

      <hr>

      <p class="small">Delta = Ist − Soll. Wochenenden, Feiertage und Abwesenheitstage zählen als Soll = 0. Flextage werden zusätzlich vom Gleitzeitkonto abgezogen.</p>
      <table style="border-collapse:collapse;width:100%;">
        <thead>
          <tr>
            <th style="padding:6px 6px;text-align:left;width:32px;">Tag</th>
            <th style="padding:6px 6px;text-align:left;">Datum</th>
            <th style="padding:6px 6px;text-align:left;">Status</th>
            <th style="padding:6px 6px;text-align:left;">Beginn</th>
            <th style="padding:6px 6px;text-align:left;">Ende</th>
            <th style="padding:6px 6px;text-align:right;width:44px;">Pause</th>
            <th style="padding:6px 6px;text-align:right;width:54px;">Ist</th>
            <th style="padding:6px 6px;text-align:right;width:54px;">Soll</th>
            <th style="padding:6px 6px;text-align:right;width:70px;">Delta</th>
            <th style="padding:6px 6px;text-align:right;width:70px;">Saldo</th>
          </tr>
        </thead>
        <tbody>{trs}</tbody>
      </table>
      {("<p class='small'><i>Keine Tage im Zeitraum.</i></p>" if not display_rows else "")}
    </div>
    {_render_absence_summary_card(u["id"], display_start, display_end)}
    </div>

    <div class="bal-mob card" style="padding:0;overflow:hidden;">
      <div style="position:sticky;top:0;z-index:20;background:var(--sf);border-bottom:2px solid var(--bd);padding:10px 12px 8px;">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
          <div style="display:flex;align-items:center;gap:2px;">
            {mob_yr_prev}
            <b style="font-size:14px;min-width:42px;text-align:center;">{sel_year}</b>
            {mob_yr_next}
          </div>
          <div style="display:flex;align-items:center;gap:2px;flex:1;justify-content:center;">
            {mob_mo_prev}
            <b style="font-size:14px;min-width:66px;text-align:center;">{mob_month_label}</b>
            {mob_mo_next}
          </div>
          <a href="/balance?y={sel_year}&m=0" class="btn" style="font-size:11px;padding:4px 8px;{'background:var(--accent);color:#fff;' if sel_month == 0 else ''}">Ganzes Jahr</a>
        </div>
        <div style="font-size:30px;font-weight:700;letter-spacing:-.02em;color:{period_end_clr};line-height:1.1;">{period_end_hhmm}</div>
        <div style="font-size:11px;color:var(--mu);margin-top:2px;">Saldo {period_label}</div>
      </div>
      <table class="mob-bal-tbl">
        <colgroup>
          <col style="width:22px;">
          <col style="width:42px;">
          <col>
          <col style="width:30px;">
          <col style="width:38px;">
          <col style="width:38px;">
          <col style="width:42px;">
        </colgroup>
        <thead>
          <tr style="background:var(--sf);">
            <th style="padding:5px 4px;text-align:left;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Tag</th>
            <th style="padding:5px 2px;text-align:left;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Dat.</th>
            <th style="padding:5px 2px;text-align:left;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Zeit</th>
            <th style="padding:5px 2px;text-align:right;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Pse</th>
            <th style="padding:5px 2px;text-align:right;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Ist</th>
            <th style="padding:5px 2px;text-align:right;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Soll</th>
            <th style="padding:5px 2px;text-align:right;font-size:10px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bd);">Δ</th>
          </tr>
        </thead>
        <tbody>{mob_trs}</tbody>
      </table>
      {("<p class='small' style='padding:8px 12px;color:var(--mu);'><i>Keine Tage im Zeitraum.</i></p>" if not display_rows else "")}
    </div>
    """
    return render_template_string(layout(t("balance.title"), body, u, APP_VERSION))




@balance_bp.post("/balance/expected")
@login_required
def balance_set_expected_override():
    from app import bootstrap, add_flash, _set_expected_override_minutes, _minutes_from_hhmm
    import re
    bootstrap()
    u = current_user()

    day = (request.form.get("day") or "").strip()
    val = (request.form.get("expected") or "").strip()
    y   = (request.form.get("y") or "").strip()
    m   = (request.form.get("m") or "").strip()
    back = f"/balance?y={y}&m={m}" if y and m else "/balance"

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        add_flash(t("flash.error.invalid_date"), "error")
        return redirect(back)

    if not val:
        _set_expected_override_minutes(u["id"], day, None)
        add_flash(t("flash.success.target_override_removed"), "success")
        return redirect(back)

    try:
        mins = _minutes_from_hhmm(val)
    except Exception:
        add_flash(t("flash.error.target_format"), "error")
        return redirect(back)

    _set_expected_override_minutes(u["id"], day, int(mins))
    add_flash(t("flash.success.target_saved"), "success")
    return redirect(back)



@balance_bp.post("/balance/start")
@login_required
def balance_set_start():
    from app import bootstrap, add_flash, _set_start_balance_minutes, _parse_signed_hhmm_to_minutes
    bootstrap()
    u = current_user()

    start_balance_raw = (request.form.get("start_balance") or "").strip()
    back_param = (request.form.get("back") or "").strip()
    y = (request.form.get("y") or "").strip()
    m = (request.form.get("m") or "").strip()
    back = back_param if back_param else (f"/balance?y={y}&m={m}" if y and m else "/balance")

    try:
        mins = _parse_signed_hhmm_to_minutes(start_balance_raw)
    except Exception:
        add_flash(t("flash.error.balance_format"), "error")
        return redirect(back)

    _set_start_balance_minutes(u["id"], mins)
    add_flash(t("flash.success.balance_saved"), "success")
    return redirect(back)

def _month_start_end(year: int, month: int):
    first = datetime.date(year, month, 1)
    last = datetime.date(year, month, calendar.monthrange(year, month)[1])
    return first.isoformat(), last.isoformat()


def _calc_balance_end_at(user_id: int, end_iso: str) -> int:
    """Saldo bis zu einem Datum (inkl.) – identische Logik wie balance_view (_iter_days)."""
    d = datetime.date.fromisoformat(end_iso)
    year_start = datetime.date(d.year, 1, 1).isoformat()
    tracking_start = _get_tracking_start(user_id)
    if tracking_start:
        year_start = max(year_start, tracking_start)

    start_minutes = _get_start_balance_minutes(user_id)
    try:
        _rdb = connect()
        _rrow = _rdb.execute("SELECT balance_rollover FROM users WHERE id=?", (user_id,)).fetchone()
        _rdb.close()
        _rollover = (_rrow["balance_rollover"] or "manual") if _rrow else "manual"
    except Exception:
        _rollover = "manual"
    running = 0 if _rollover == "forfeit" else int(start_minutes)
    today_iso = datetime.date.today().isoformat()
    flextag_ranges = _fetch_flextag_ranges(user_id)

    for iso in _iter_days(year_start, end_iso):
        expected = int(_expected_minutes_for_day(user_id, iso) or 0)
        actual = int(_actual_minutes_for_day(user_id, iso) or 0)
        flextag_min = 0
        if iso < today_iso and expected == 0 and _is_flextag(iso, flextag_ranges):
            flextag_min = _scheduled_minutes_ignoring_absence(user_id, iso)
        running += int(actual - expected - flextag_min)

    # Manuelle Korrekturen einrechnen
    try:
        _db_adj = connect()
        _adj = _db_adj.execute(
            "SELECT COALESCE(SUM(minutes),0) AS total FROM balance_adjustments "
            "WHERE user_id=? AND adjustment_date BETWEEN ? AND ?",
            (user_id, year_start, end_iso)
        ).fetchone()
        _db_adj.close()
        running += int(_adj["total"] or 0)
    except Exception:
        pass

    return int(running)


@balance_bp.get("/balance/monthly")
@login_required
def balance_monthly():
    from app import bootstrap, flash_html, layout, APP_VERSION, _calc_balance, _month_start_end, _fmt_minutes_signed
    import datetime
    bootstrap()
    u = current_user()

    today = datetime.date.today()
    year = int(request.args.get("y") or today.year)

    rows = []
    for m in range(1, 13):
        m_from, m_to = _month_start_end(year, m)
        if year == today.year and m > today.month:
            continue
        calc = _calc_balance(u["id"], m_from, m_to)
        rows.append({
            "month": f"{year}-{m:02d}",
            "from": m_from,
            "to": m_to,
            "delta": int(calc["end_minutes"] - calc["start_minutes"]),
            "end": int(calc["end_minutes"]),
        })

    trs = ""
    for r in rows:
        trs += (
            "<tr>"
            f"<td><a href='/balance?from={r['from']}&to={r['to']}'>{r['month']}</a></td>"
            f"<td style='text-align:right;'><b>{_fmt_minutes_signed(r['delta'])}</b></td>"
            f"<td style='text-align:right;'>{_fmt_minutes_signed(r['end'])}</td>"
            "</tr>"
        )

    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Monatsabschluss</h3>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <a class="btn" href="/balance/monthly?y={year-1}">◀︎ {year-1}</a>
          <a class="btn" href="/balance/monthly?y={today.year}">{today.year}</a>
          <a class="btn" href="/balance/monthly?y={year+1}">{year+1} ▶︎</a>
          <a class="btn" href="/balance/monthly.csv?y={year}">CSV Export</a>
        </div>
      </div>
      <p class="small">Delta = Summe(Ist-Soll) im Monat. Endsaldo = Startsaldo + Deltas seit Jahresbeginn.</p>
      <table>
        <thead><tr><th>Monat</th><th style="text-align:right;">Delta</th><th style="text-align:right;">Endsaldo</th></tr></thead>
        <tbody>{trs}</tbody>
      </table>
    </div>
    """
    return render_template_string(layout(t("balance.monthly"), body, u, APP_VERSION))



@balance_bp.get("/balance/monthly.csv")
@login_required
def balance_monthly_csv():
    from app import bootstrap, _calc_balance, _month_start_end
    import datetime, calendar
    bootstrap()
    u = current_user()

    today = datetime.date.today()
    year = int(request.args.get("y") or today.year)

    lines = ["month,from,to,delta_minutes,end_minutes"]
    for m in range(1, 13):
        m_from, m_to = _month_start_end(year, m)
        if year == today.year and m > today.month:
            continue
        calc = _calc_balance(u["id"], m_from, m_to)
        delta = int(calc["end_minutes"] - calc["start_minutes"])
        endm = int(calc["end_minutes"])
        lines.append(f"{year}-{m:02d},{m_from},{m_to},{delta},{endm}")

    csv_text = "\n".join(lines) + "\n"
    from flask import Response
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=gleitzeit_{year}.csv"},
    )

