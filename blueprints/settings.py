"""
Blueprint: Benutzer-Einstellungen.
"""
from flask import Blueprint, request, redirect, url_for
from db import connect
from auth import login_required, admin_required, current_user
from auth import set_password, set_totp, disable_totp, get_totp_row, update_totp_backup_codes
from auth import set_language, authenticate, validate_password
from translations import t

settings_bp = Blueprint("settings", __name__)


@settings_bp.get("/settings")
@login_required
def settings_view():
    import datetime
    import html as _html
    from flask import render_template_string
    from app import (bootstrap, layout, flash_html, APP_VERSION, _html,
                      _fmt_date_de, _date_input, _workdays_str, _default_workdays_mask,
                      _get_user_schedule_current, _get_user_schedule_for_day,
                      _get_user_schedules_all, _vacation_calc,
                      _get_contouring_info, _get_pref_auto_breaks, _get_base_url,
                      _render_calendar_integration_section, _render_icloud_settings_section,
                      _render_security_accordion, _sched_form_html, _sched_daily_blocks_html,
                      _normalize_schedule, _get_user_holiday_region, _get_webcal_url,
                      _get_start_balance_minutes, _available_languages, _fmt_minutes_signed)
    bootstrap()
    u = current_user()
    sched = _get_user_schedule_current(u["id"])
    all_scheds = _get_user_schedules_all(u["id"])
    today_iso = datetime.date.today().isoformat()
    cur_sched = _get_user_schedule_for_day(u["id"], today_iso)
    cur_id = (cur_sched or {}).get("id")
    auto_breaks_enabled = _get_pref_auto_breaks(u["id"]) == 1

    # Urlaub (Inline in Einstellungen)
    vac_year = int(datetime.date.today().year)
    vc = _vacation_calc(u["id"], vac_year)
    vac_entitlement = vc["entitlement"]
    vac_carryover = vc["carryover"]
    vac_deadline = vc["deadline"]
    vac_used_total = vc["used_total"]
    vac_carryover_remaining = vc["carryover_remaining"]
    vac_entitlement_remaining = vc["entitlement_remaining"]
    vac_remaining_total = vc["remaining_total"]
    vac_carryover_forfeited = vc["carryover_forfeited"]
    vac_deadline_passed = vc["deadline_passed"]
    vac_carryover_exception = vc.get("carryover_exception", False)
    vac_effective_carryover = vc.get("effective_carryover", 0.0)

    # Build schedule list with validity dates
    sched_rows = ""
    _edit_forms = ""
    for s in all_scheds:
        sid = s.get("id")
        valid_from = s.get("valid_from") or ""
        mode = (s.get("mode") or "weekly").lower()
        weekly_minutes = s.get("weekly_minutes")
        weekly_hours_txt = ""
        if weekly_minutes is not None:
            try:
                weekly_hours_txt = f"{(int(weekly_minutes)/60):g}"
            except Exception:
                weekly_hours_txt = ""
        mask = int(s.get("workdays_mask") or _default_workdays_mask())
        workdays_txt = _workdays_str(mask)

        badge = ""
        try:
            if sid and cur_id and int(sid) == int(cur_id):
                badge = f"<span class='badge' style='background:#0a7;color:#fff;'>{t('settings.badge_current')}</span>"
            elif valid_from and valid_from > today_iso:
                badge = f"<span class='badge' style='background:#888;color:#fff;'>{t('settings.badge_upcoming')}</span>"
            else:
                badge = f"<span class='badge' style='background:#ddd;'>{t('settings.badge_history')}</span>"
        except Exception:
            badge = ""

        if mode == "weekly":
            mode_txt = t('schedule.mode_weekly')
        elif mode == "daily":
            mode_txt = t('schedule.mode_fixed')
        elif mode == "daily_hours":
            mode_txt = t('schedule.mode_daily')
        else:
            mode_txt = mode

        allow_self = int(s.get("allow_self_edit") if s.get("allow_self_edit") is not None else 1)
        locked_badge = (
            f"<span class='badge' style='background:#dc2626;color:#fff;margin-left:4px;'>{t('settings.schedule_locked')}</span>"
            if not allow_self else ""
        )

        if mode == "daily" and sid:
            try:
                _sb_db = connect()
                _sb_rows = _sb_db.execute(
                    "SELECT weekday, time_from, time_to FROM schedule_daily_blocks "
                    "WHERE schedule_id=? ORDER BY weekday, sort_order",
                    (sid,)
                ).fetchall()
                _sb_db.close()
                _WD_S = ["Mo","Di","Mi","Do","Fr","Sa","So"]
                _day_map: dict = {}
                for r in _sb_rows:
                    _day_map.setdefault(r["weekday"], []).append(f"{r['time_from']}–{r['time_to']}")
                soll_txt = " ".join(
                    f"<b>{_WD_S[wd]}:</b>{','.join(ts)}"
                    for wd, ts in sorted(_day_map.items())
                ) or "–"
            except Exception:
                soll_txt = "–"
        elif mode == "daily":
            soll_txt = "–"
        elif mode == "daily_hours":
            soll_txt = "–"
        else:
            soll_txt = f"{weekly_hours_txt} {t('schedule.hours_week')}" if weekly_hours_txt else "–"

        edit_btn = ""
        del_btn = ""
        if sid and allow_self:
            if mode == "daily":
                edit_btn = (
                    f"<button class='btn btn-sm' type='button' "
                    f"onclick=\"var el=document.getElementById('edit-sched-{sid}');"
                    f"el.style.display=el.style.display==='none'?'block':'none';\">"
                    f"{t('btn.edit')}</button> "
                )
                _edit_forms += f"""
                <div id="edit-sched-{sid}" style="display:none;margin-top:8px;padding:12px;
                     border:1px solid var(--br);border-radius:8px;background:var(--ca);">
                  <b style="font-size:13px;">{t('settings.sched_add_new')} – {_fmt_date_de(valid_from) if valid_from else valid_from}</b>
                  <form method="post" action="/settings/schedule/{sid}/edit" style="margin-top:10px;">
                    <div style="margin-bottom:8px;">
                      <label style="font-size:12px;color:var(--mu);">{t('settings.schedule_valid')}</label>
                      <input type="date" name="valid_from" value="{valid_from}"
                             style="margin-left:8px;font-size:13px;padding:4px 8px;border-radius:4px;">
                    </div>
                    {_sched_daily_blocks_html(sid, "daily")}
                    <div style="margin-top:12px;display:flex;gap:8px;">
                      <button class="btn primary btn-sm" type="submit">{t('btn.save')}</button>
                      <button class="btn btn-sm" type="button"
                              onclick="document.getElementById('edit-sched-{sid}').style.display='none';">{t('btn.cancel')}</button>
                    </div>
                  </form>
                </div>"""
            del_btn = (f"<form method='post' action='/settings/schedule/{sid}/delete' style='display:contents;'"
                       f" onsubmit=\"return confirm('Zeitschema ab {_fmt_date_de(valid_from) if valid_from else valid_from} löschen?');\">"
                       f"<button class='btn danger btn-sm'>Löschen</button></form>")

        sched_rows += f"""<tr>
            <td style='white-space:nowrap;'><b>{_fmt_date_de(valid_from) if valid_from else "-"}</b></td>
            <td>{badge}{locked_badge}</td>
            <td>{mode_txt}</td>
            <td class='small'>{soll_txt}</td>
            <td>{workdays_txt}</td>
            <td style='white-space:nowrap;'>{edit_btn}{del_btn}</td>
        </tr>"""


    profile_dn = u.get("display_name") or ""
    profile_em = u.get("email") or ""
    _prof_db = connect()
    try:
        _prof_row = _prof_db.execute(
            "SELECT birth_date, retirement_age FROM users WHERE id=?", (u["id"],)
        ).fetchone()
        profile_bd = (_prof_row["birth_date"] or "") if _prof_row else ""
        profile_ra = str(_prof_row["retirement_age"] or 67) if _prof_row else "67"
    finally:
        _prof_db.close()
    _tg_db = connect()
    try:
        _tg_row = _tg_db.execute(
            "SELECT telegram_id, wizard_enabled, reminder_time FROM telegram_users WHERE user_id=?",
            (u["id"],),
        ).fetchone()
        profile_tg = str(_tg_row["telegram_id"]) if _tg_row else ""
        wiz_enabled = bool(int(_tg_row["wizard_enabled"] or 0)) if _tg_row else False
        wiz_time = (_tg_row["reminder_time"] or "20:00") if _tg_row else "20:00"
        app.logger.info("settings_view: wizard_enabled=%s reminder_time=%s", wiz_enabled, wiz_time)
    finally:
        _tg_db.close()

    ci = _get_contouring_info(u["id"])
    today_iso_s = datetime.date.today().isoformat()
    default_start = datetime.date.today().replace(day=1).isoformat()
    contouring_enabled = ci["enabled"]
    contouring_start_label = _fmt_date_de(ci["start_date"]) if ci["start_date"] else "–"

    # Calendar integration settings
    _cal_db = connect()
    _cal_row = _cal_db.execute(
        "SELECT calendar_system, calendar_export_types, calendar_export_prefix, calendar_token, calendar_auth_mode FROM users WHERE id=?",
        (u["id"],),
    ).fetchone()
    _cal_db.close()
    cal_system    = (_cal_row["calendar_system"]      or "ical")           if _cal_row else "ical"
    cal_types     = (_cal_row["calendar_export_types"] or "urlaub,krank,flextag").split(",") if _cal_row else ["urlaub","krank","flextag"]
    cal_prefix    = (_cal_row["calendar_export_prefix"] or "")             if _cal_row else ""
    cal_token     = (_cal_row["calendar_token"]        or "")              if _cal_row else ""
    cal_auth_mode = (_cal_row["calendar_auth_mode"]    or "token")         if _cal_row else "token"
    _base_url = _get_base_url()
    if cal_token:
        _ical_url   = _base_url + f"/absences/calendar/{cal_token}.ics"
        _webcal_url = _get_webcal_url(cal_token)
    else:
        _ical_url   = ""
        _webcal_url = ""
    _basic_ical_url     = _base_url + "/absences/calendar/kalender.ics"
    _basic_webcal_url   = _basic_ical_url.replace("https://", "webcal://", 1).replace("http://", "webcal://", 1)
    _caldav_token_url   = (_base_url + f"/caldav/{cal_token}/") if cal_token else ""
    _caldav_basic_url   = _base_url + "/caldav/basic/"

    # iCloud settings
    _ic_db  = connect()
    _ic_row = _ic_db.execute(
        "SELECT icloud_enabled, icloud_apple_id, icloud_app_password, icloud_calendar_name, icloud_last_sync "
        "FROM users WHERE id=?",
        (u["id"],),
    ).fetchone()
    _ic_db.close()

    # Security / 2FA data
    _totp = get_totp_row(u["id"])
    _totp_enabled = bool(_totp.get("totp_enabled"))
    ic_enabled   = bool(int((_ic_row["icloud_enabled"] or 0))) if _ic_row else False
    ic_apple_id  = (_ic_row["icloud_apple_id"] or "")          if _ic_row else ""
    ic_has_pw    = bool((_ic_row["icloud_app_password"] or "")) if _ic_row else False
    ic_cal_name  = (_ic_row["icloud_calendar_name"] or "")      if _ic_row else ""
    ic_last_sync = (_ic_row["icloud_last_sync"] or "")          if _ic_row else ""

    # allow_self_edit des aktuellen Schemas prüfen
    _can_self_edit = True
    try:
        _ase_db = connect()
        _ase_row = _ase_db.execute(
            "SELECT allow_self_edit FROM user_schedules WHERE user_id=? ORDER BY valid_from DESC LIMIT 1",
            (u["id"],)
        ).fetchone()
        _ase_db.close()
        if _ase_row and int(_ase_row["allow_self_edit"] or 1) == 0:
            _can_self_edit = False
    except Exception:
        pass

    # Presets für Settings-Seite laden
    _set_presets_db = connect()
    _set_presets = _set_presets_db.execute(
        "SELECT * FROM user_time_presets WHERE user_id=? ORDER BY sort_order",
        (u["id"],)
    ).fetchall()
    _set_presets_db.close()

    _presets_table_rows = "".join(
        f"<tr>"
        f"<td style='padding:6px 10px;'>{_html.escape(p['label'])}</td>"
        f"<td style='padding:6px 10px;'>{p['time_in']}</td>"
        f"<td style='padding:6px 10px;'>{p['time_out']}</td>"
        f"<td style='padding:6px 10px;'>{p['break_minutes']}</td>"
        f"<td style='padding:6px 10px;'>"
        f"<form method='post' action='/settings/presets/delete' style='display:inline;' onsubmit=\"return confirm('{t('confirm.delete_preset')}');\">"
        f"<input type='hidden' name='preset_id' value='{p['id']}'>"
        f"<button class='btn btn-sm' type='submit' style='color:#dc2626;'>{t('btn.delete')}</button>"
        f"</form></td>"
        f"</tr>"
        for p in _set_presets
    )
    _presets_table = (
        f"<table style='width:100%;border-collapse:collapse;font-size:13px;margin-bottom:12px;'>"
        f"<thead><tr style='border-bottom:1px solid var(--br);'>"
        f"<th style='padding:4px 10px;text-align:left;'>{t('settings.preset_label')}</th>"
        f"<th style='padding:4px 10px;text-align:left;'>{t('day.time_in')}</th>"
        f"<th style='padding:4px 10px;text-align:left;'>{t('day.time_out')}</th>"
        f"<th style='padding:4px 10px;text-align:left;'>{t('day.break_min')}</th>"
        f"<th></th></tr></thead>"
        f"<tbody>{_presets_table_rows}</tbody></table>"
    ) if _set_presets else f"<p style='color:var(--mu);font-size:13px;margin-bottom:12px;'>{t('settings.preset_hint')}</p>"

    _presets_add_form = (
        f"<div style='color:var(--mu);font-size:13px;'>{t('settings.preset_max')}</div>"
        if len(_set_presets) >= 3 else
        f"<form method='post' action='/settings/presets/add'>"
        f"<div style='display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;'>"
        f"<div><label style='font-size:12px;color:var(--mu);display:block;margin-bottom:3px;'>{t('settings.preset_label')}</label>"
        f"<input name='label' maxlength='30' required placeholder='Früh'>"
        f"</div>"
        f"<div><label style='font-size:12px;color:var(--mu);display:block;margin-bottom:3px;'>{t('day.time_in')}</label>"
        f"<input type='time' name='time_in' required style='width:110px;font-size:1rem;padding:5px 8px;border-radius:6px;'>"
        f"</div>"
        f"<div><label style='font-size:12px;color:var(--mu);display:block;margin-bottom:3px;'>{t('day.time_out')}</label>"
        f"<input type='time' name='time_out' required style='width:110px;font-size:1rem;padding:5px 8px;border-radius:6px;'>"
        f"</div>"
        f"<div><label style='font-size:12px;color:var(--mu);display:block;margin-bottom:3px;'>{t('day.break_min')}</label>"
        f"<input type='number' name='break_minutes' value='0' min='0' style='width:70px;font-size:1rem;padding:5px 8px;border-radius:6px;'>"
        f"</div>"
        f"<button class='btn primary btn-sm' type='submit' style='align-self:flex-end;'>{t('btn.add')}</button>"
        f"</div></form>"
    )

    if contouring_enabled:
        _kont_html = (
            f"<div style='margin-bottom:10px;'><span style='color:var(--ok);font-weight:600;'>{t('settings.kont_active')}</span>"
            f" <span style='color:var(--mu);font-size:13px;'>{t('settings.kont_since')} {contouring_start_label}</span></div>"
            f"<form method='post' action='/settings/contouring/toggle'"
            f" onsubmit=\"return confirm('{t('settings.kont_disable_confirm')}');\">"
            f"<button class='btn danger' type='submit'>{t('settings.contouring_off')}</button></form>"
        )
    else:
        _kont_html = (
            f"<div style='margin-bottom:12px;color:var(--mu);'>{t('settings.kont_disabled_msg')}</div>"
            f"<form method='post' action='/settings/contouring/toggle'>"
            f"<div style='margin-bottom:10px;'>"
            f"<label>{t('settings.kont_start_lbl')}</label><br>"
            f"{_date_input('contouring_start_date', default_start)}"
            f"<div class='small' style='color:var(--mu);margin-top:3px;'>{t('settings.kont_default_hint')}</div>"
            f"</div>"
            f"<button class='btn primary' type='submit'>{t('settings.kont_enable_btn')}</button>"
            f"</form>"
        )

    # Berufsschule-Daten laden
    _voc_db = connect()
    _voc_entries = _voc_db.execute(
        "SELECT * FROM vocational_school WHERE user_id=? ORDER BY schedule_type, weekday, date_from",
        (u["id"],)
    ).fetchall()
    _voc_region = _get_user_holiday_region(u["id"])
    _school_hols = _voc_db.execute(
        "SELECT * FROM school_holidays WHERE region=? ORDER BY date_from",
        (_voc_region,)
    ).fetchall()
    _voc_db.close()

    _WD_NAMES_VOC = [t("wd.mon"), t("wd.tue"), t("wd.wed"), t("wd.thu"),
                     t("wd.fri"), t("wd.sat"), t("wd.sun")]
    _voc_show = bool(_voc_entries) or bool(u.get("is_apprentice"))

    def _fmt_time_voc(s):
        return s[:5] if s else "–"

    _voc_weekly_rows = "".join(
        f"<tr>"
        f"<td style='font-size:13px;'>{_WD_NAMES_VOC[int(e['weekday'])] if e['weekday'] is not None else '–'}</td>"
        f"<td style='font-size:13px;'>{'Ganztag' if not e['school_time_from'] else _fmt_time_voc(e['school_time_from'])+' – '+_fmt_time_voc(e['school_time_to'])}</td>"
        f"<td style='font-size:13px;'>{'–' if not e['work_time_from'] else _fmt_time_voc(e['work_time_from'])+' – '+_fmt_time_voc(e['work_time_to'])}</td>"
        f"<td style='font-size:13px;'>{(e['valid_from'] or '–')+' – '+(e['valid_to'] or 'offen')}</td>"
        f"<td><form method='post' action='/settings/vocational/delete' style='display:inline;' onsubmit=\"return confirm('{t('confirm.delete_vocational')}');\">"
        f"<input type='hidden' name='entry_id' value='{e['id']}'>"
        f"<button class='btn btn-sm danger' type='submit' style='padding:2px 8px;'>×</button></form></td>"
        f"</tr>"
        for e in _voc_entries if e["schedule_type"] == "weekly"
    ) or f"<tr><td colspan='5' style='color:var(--mu);font-size:13px;'>–</td></tr>"

    _voc_block_rows = "".join(
        f"<tr>"
        f"<td style='font-size:13px;'>{_fmt_date_de(e['date_from'])}</td>"
        f"<td style='font-size:13px;'>{_fmt_date_de(e['date_to'])}</td>"
        f"<td style='font-size:13px;'>{_html.escape(e['note'] or '')}</td>"
        f"<td><form method='post' action='/settings/vocational/delete' style='display:inline;' onsubmit=\"return confirm('{t('confirm.delete_vocational')}');\">"
        f"<input type='hidden' name='entry_id' value='{e['id']}'>"
        f"<button class='btn btn-sm danger' type='submit' style='padding:2px 8px;'>×</button></form></td>"
        f"</tr>"
        for e in _voc_entries if e["schedule_type"] == "block"
    ) or f"<tr><td colspan='4' style='color:var(--mu);font-size:13px;'>–</td></tr>"

    _wd_opts_voc = "".join(
        f'<option value="{i}">{_WD_NAMES_VOC[i]}</option>' for i in range(7)
    )
    _school_hols_rows = "".join(
        f"<tr><td style='font-size:13px;'>{_html.escape(h['name'])}</td>"
        f"<td style='font-size:13px;'>{_fmt_date_de(h['date_from'])}</td>"
        f"<td style='font-size:13px;'>{_fmt_date_de(h['date_to'])}</td></tr>"
        for h in _school_hols
    ) or f"<tr><td colspan='3' style='color:var(--mu);font-size:13px;'>Keine Schulferien für {_html.escape(_voc_region)}</td></tr>"

    _voc_accordion = f"""
    <div class="acc" id="acc-voc">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-voc-body')">
        <span>🎓 Berufsschule</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-voc-body">
        <div class="acc-inner">
          <p class="small" style="color:var(--mu);margin-bottom:14px;">
            An Berufsschultagen wird das Tagessoll automatisch auf 0 (Ganztag) oder die Arbeitszeit (Halbtag) gesetzt.
          </p>
          <h4 style="margin:0 0 8px;">A – Wöchentliche Berufsschultage</h4>
          <div class="table-scroll" style="margin-bottom:10px;">
            <table style="width:100%;"><thead><tr>
              <th>Wochentag</th><th>BS-Zeit</th><th>Arbeitszeit</th><th>Gültig ab/bis</th><th></th>
            </tr></thead><tbody>{_voc_weekly_rows}</tbody></table>
          </div>
          <form method="post" action="/settings/vocational/add" style="margin-bottom:16px;">
            <input type="hidden" name="schedule_type" value="weekly">
            <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
              <div>
                <label style="font-size:12px;color:var(--mu);">Wochentag</label>
                <select name="weekday" style="display:block;margin-top:4px;font-size:13px;">{_wd_opts_voc}</select>
              </div>
              <div>
                <label style="font-size:12px;color:var(--mu);">Typ</label>
                <select name="voc_type" style="display:block;margin-top:4px;font-size:13px;"
                        onchange="document.getElementById('voc-half').style.display=this.value==='half'?'flex':'none'">
                  <option value="full">Ganztag</option>
                  <option value="half">Halbtag</option>
                </select>
              </div>
              <div id="voc-half" style="display:none;gap:8px;flex-wrap:wrap;">
                <div>
                  <label style="font-size:12px;color:var(--mu);">BS von – bis</label>
                  <div style="display:flex;gap:4px;margin-top:4px;">
                    <input type="time" name="school_time_from" step="900" style="width:96px;">
                    <input type="time" name="school_time_to" step="900" style="width:96px;">
                  </div>
                </div>
                <div>
                  <label style="font-size:12px;color:var(--mu);">Arbeit von – bis</label>
                  <div style="display:flex;gap:4px;margin-top:4px;">
                    <input type="time" name="work_time_from" step="900" style="width:96px;">
                    <input type="time" name="work_time_to" step="900" style="width:96px;">
                  </div>
                </div>
              </div>
              <div>
                <label style="font-size:12px;color:var(--mu);">Gültig ab</label>
                {_date_input("valid_from", "")}
              </div>
              <div>
                <label style="font-size:12px;color:var(--mu);">Gültig bis</label>
                {_date_input("valid_to", "")}
              </div>
              <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
            </div>
          </form>
          <h4 style="margin:0 0 8px;">B – Blockunterricht</h4>
          <div class="table-scroll" style="margin-bottom:10px;">
            <table style="width:100%;"><thead><tr>
              <th>Von</th><th>Bis</th><th>Notiz</th><th></th>
            </tr></thead><tbody>{_voc_block_rows}</tbody></table>
          </div>
          <form method="post" action="/settings/vocational/add" style="margin-bottom:16px;">
            <input type="hidden" name="schedule_type" value="block">
            <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;">
              <div><label style="font-size:12px;color:var(--mu);">Von</label>
                {_date_input("date_from", "")}</div>
              <div><label style="font-size:12px;color:var(--mu);">Bis</label>
                {_date_input("date_to", "")}</div>
              <div style="flex:1;min-width:120px;">
                <label style="font-size:12px;color:var(--mu);">Notiz</label>
                <input type="text" name="note" maxlength="80" placeholder="z.B. Block 1"
                       style="display:block;margin-top:4px;width:100%;">
              </div>
              <button class="btn primary btn-sm" type="submit">{t('btn.add')}</button>
            </div>
          </form>
          <h4 style="margin:0 0 8px;">C – Schulferien ({_html.escape(_voc_region)})</h4>
          <p class="small" style="color:var(--mu);margin-bottom:8px;">An Ferientagen entfällt die Berufsschule automatisch.</p>
          <div class="table-scroll">
            <table style="width:100%;"><thead><tr><th>Name</th><th>Von</th><th>Bis</th></tr></thead>
            <tbody>{_school_hols_rows}</tbody></table>
          </div>
        </div>
      </div>
    </div>""" if _voc_show else ""

    # Startsaldo + Jahreswechsel für Settings-Karte
    _cur_year = datetime.date.today().year
    _sb_minutes = _get_start_balance_minutes(u["id"])
    _sb_txt = _fmt_minutes_signed(_sb_minutes)
    try:
        _ro_db = connect()
        _ro_row = _ro_db.execute("SELECT balance_rollover FROM users WHERE id=?", (u["id"],)).fetchone()
        _ro_db.close()
        _rollover_mode = str(_ro_row["balance_rollover"] or "manual") if _ro_row else "manual"
    except Exception:
        _rollover_mode = "manual"
    _rollover_label_map = {
        "manual":  t("admin.rollover_manual"),
        "keep":    t("admin.rollover_keep"),
        "forfeit": t("admin.rollover_forfeit"),
    }
    _rollover_lbl = _rollover_label_map.get(_rollover_mode, _rollover_mode)

    body = f"""
    {flash_html()}
<style>
.acc{{border:1px solid var(--bd);border-radius:var(--r);margin-bottom:10px;overflow:hidden;background:var(--bg);}}
.acc-hdr{{width:100%;display:flex;justify-content:space-between;align-items:center;
  padding:14px 16px;background:var(--sf);border:none;cursor:pointer;
  font-size:15px;font-weight:600;color:var(--tx);text-align:left;gap:10px;}}
.acc-hdr:hover{{background:var(--bd);}}
.acc-hdr.open{{border-bottom:1px solid var(--bd);}}
.acc-arr{{font-size:12px;flex-shrink:0;color:var(--mu);}}
.acc-body{{max-height:0;overflow:hidden;transition:max-height .28s ease;}}
.acc-body.open{{max-height:4000px;}}
.acc-inner{{padding:16px;}}
.acc-sub{{border-top:1px solid var(--bd);margin-top:16px;padding-top:16px;}}
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
function wizToggle(cb){{
  var row=document.getElementById('wiz-time-row');
  var inp=document.getElementById('wiz-time');
  if(cb.checked){{row.style.opacity='1';inp.disabled=false;}}
  else{{row.style.opacity='0.5';inp.disabled=true;}}
}}
function wizValidate(e){{
  var t=document.getElementById('wiz-time');
  if(t&&!t.disabled){{
    var parts=t.value.split(':');
    var h=parseInt(parts[0]||0,10);
    if(h<15||h>23){{e.preventDefault();alert('{t("settings.reminder_time_error")}');return false;}}
  }}
}}
</script>

    <h2 style="margin:0 0 14px 0;font-size:18px;">{t('settings.title')}</h2>

    <!-- 1. Persönliche Einstellungen -->
    <div class="acc">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-profil')">
        <span>{t('settings.personal_section')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-profil">
        <div class="acc-inner">
          <form method="post" action="/settings/profile" style="display:flex;flex-direction:column;gap:10px;max-width:400px;">
            <div>
              <label>{t('settings.display_name')}</label><br>
              <input name="display_name" value="{profile_dn}" placeholder="{u['username']}">
              <div class="small" style="color:var(--mu);margin-top:3px;">{t('settings.display_name_hint')}</div>
            </div>
            <div>
              <label>{t('settings.email')}</label><br>
              <input type="email" name="email" value="{profile_em}" placeholder="max@example.com">
            </div>
            <div>
              <label>{t('settings.birth_date')}</label><br>
              <input type="date" name="birth_date" value="{profile_bd}" style="width:180px;">
              <div class="small" style="color:var(--mu);margin-top:3px;">{t('settings.birth_date_hint')}</div>
            </div>
            <div>
              <label>{t('settings.retire_age')}</label><br>
              <input type="number" name="retirement_age" value="{profile_ra}"
                     min="60" max="72" step="1" inputmode="numeric"
                     style="width:100px;">
              <div class="small" style="color:var(--mu);margin-top:3px;">{t('settings.retire_age_hint')}</div>
            </div>
            <div><button class="btn" type="submit">{t('settings.save_profile_btn')}</button></div>
          </form>

          <div class="acc-sub">
            <b style="font-size:14px;">{t('settings.telegram')}</b>
            <form method="post" action="/settings/telegram" style="display:flex;flex-direction:column;gap:10px;max-width:400px;margin-top:10px;">
              <div>
                <label>Telegram-ID</label><br>
                <input type="text" name="telegram_id" value="{profile_tg}" placeholder="z.B. 123456789" pattern="[0-9]*" inputmode="numeric" style="width:200px;">
                <div class="small" style="color:var(--mu);margin-top:3px;">{t('settings.tg_hint')}</div>
              </div>
              <div><button class="btn" type="submit">{t('settings.tg_save')}</button></div>
            </form>
          </div>

          <div class="acc-sub">
            <b style="font-size:14px;">{t('settings.reminder_section')}</b>
            {'<div class="small" style="color:var(--mu);margin-top:8px;margin-bottom:4px;">' + t('settings.reminder_need_tg') + '</div>' if not profile_tg else ''}
            <form method="post" action="/settings/reminder" onsubmit="wizValidate(event)" style="display:flex;flex-direction:column;gap:12px;max-width:400px;margin-top:10px;">
              <div style="{'opacity:0.5;' if not profile_tg else ''}">
                <label style="display:flex;align-items:center;gap:8px;cursor:{'pointer' if profile_tg else 'default'};">
                  <input type="checkbox" name="wizard_enabled" value="1" id="wiz-toggle"
                    {"checked" if (profile_tg and wiz_enabled) else ""}
                    {"" if profile_tg else "disabled"}
                    onchange="wizToggle(this)">
                  <span>{t('settings.reminder_active')}</span>
                  <span title="Der Bot fragt dich abends ob du deine Zeiten erfasst hast" style="cursor:help;color:var(--mu);font-size:13px;">ⓘ</span>
                </label>
              </div>
              <div id="wiz-time-row" style="{'opacity:1;' if (profile_tg and wiz_enabled) else 'opacity:0.5;'}">
                <label>{t('settings.reminder_time_lbl')}</label><br>
                <input type="time" name="reminder_time" id="wiz-time"
                  value="{wiz_time}" step="900" style="width:140px;"
                  {"" if (profile_tg and wiz_enabled) else "disabled"}>
                <div class="small" style="color:var(--mu);margin-top:3px;">{t('settings.reminder_time_hint')}</div>
              </div>
              <div><button class="btn" type="submit" {"" if profile_tg else "disabled"}>{t('settings.reminder_save')}</button></div>
            </form>
          </div>

          <div class="acc-sub">
            <b style="font-size:14px;">{t("settings.language")}</b>
            <form method="post" action="/settings/language" style="display:flex;flex-direction:column;gap:10px;max-width:300px;margin-top:10px;">
              <div>
                <label>{t("settings.language")}</label><br>
                <select name="language">
                  {"".join(f'<option value="{code}" {"selected" if (u.get("language") or "de") == code else ""}>{label}</option>' for code, label in _available_languages())}
                </select>
              </div>
              <div><button class="btn" type="submit">{t("btn.save")}</button></div>
            </form>
          </div>

          <div class="acc-sub">
            <div class="small" style="color:var(--mu);">{t('settings.tracking_start_lbl')}</div>
            <div style="font-size:14px;font-weight:600;margin-top:2px;">{_fmt_date_de(u.get("tracking_start_date")) or "–"}</div>
            <div class="small" style="color:var(--mu);margin-top:2px;">{t('settings.tracking_start_hint')}</div>
          </div>

          {f"""<div class="acc-sub">
            <b style="font-size:14px;">{t('settings.time_mode_section')}</b>
            <p class="small" style="margin-top:6px;margin-bottom:10px;">{t('settings.time_mode_desc')}</p>
            <form method="post" action="/settings/admin-only"
                  onsubmit="return !this.dataset.ao||confirm('Zeiterfassungs-Funktionen wirklich {"deaktivieren" if not u.get("admin_only") else "aktivieren"}?');"
                  data-ao="1">
              {"<span style='color:var(--ok);font-weight:600;'>" + t('settings.time_active') + "</span><div class='small' style='color:var(--mu);margin:6px 0 10px;'>" + t('settings.time_active_desc') + "</div><button class='btn btn-sm danger' type='submit' name='admin_only' value='1'>" + t('settings.time_disable_btn') + "</button>" if not u.get("admin_only") else "<span style='color:var(--mu);font-weight:600;'>" + t('settings.time_disabled') + "</span><div class='small' style='color:var(--mu);margin:6px 0 10px;'>" + t('settings.time_disabled_desc') + "</div><button class='btn btn-sm primary' type='submit' name='admin_only' value='0'>" + t('settings.time_enable_btn') + "</button>"}
            </form>
          </div>""" if is_sysadmin(u) else ""}
        </div>
      </div>
    </div>

    <!-- 2. Sicherheit -->
    {_render_security_accordion(u, _totp_enabled)}

    <!-- 3. Urlaub -->
    <div class="acc">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-urlaub')">
        <span>{t('settings.vac_section')} – {vac_year}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-urlaub">
        <div class="acc-inner">
          {"<div style='background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:13px;color:#92400e;'><b>" + t('settings.vac_exc_note') + "</b> – " + f"{vac_effective_carryover:.1f} Tage übertragen (verfallen nicht am 31.03.)</div>" if vac_carryover_exception else ""}
          <p class="small" style="margin-bottom:12px;">
            {t('settings.vac_workdays_note')}
            {"Übertrag-Frist: " + vac_deadline + " <b style='color:#d97706;'>(Ausnahme gilt – kein Verfall)</b>." if vac_carryover_exception else ("<b style='color:var(--danger);'>Übertrag verfällt am " + vac_deadline + " (Urlaubsbeginn muss ≤ " + vac_deadline + " liegen).</b>" if not vac_deadline_passed and vac_carryover > 0 else ("Übertrag verfallen am " + vac_deadline + "." if vac_deadline_passed and vac_carryover_forfeited > 0 else "Übertrag-Frist: " + vac_deadline + "."))}
          </p>
          <form method="post" action="/settings/vacation/save" style="display:flex;gap:12px;flex-wrap:wrap;align-items:end;margin-bottom:14px;">
            <input type="hidden" name="year" value="{vac_year}">
            <div>
              <label>{t('settings.vac_entitlement_lbl')}</label><br>
              <input name="entitlement_days" type="number" step="0.5" min="0" value="{vac_entitlement}" required style="width:120px;">
            </div>
            <div>
              <label>{t('settings.vac_carryover_lbl')}</label><br>
              <input name="carryover_days" type="number" step="0.5" min="0" value="{vac_carryover}" required style="width:120px;">
            </div>
            <div><button class="btn" type="submit">{t('btn.save')}</button></div>
          </form>
          <div style="display:flex;gap:18px;flex-wrap:wrap;">
            <div><div class="small">{t('settings.vac_used')}</div><div style="font-size:22px;font-weight:700;">{vac_used_total:.1f}</div></div>
            <div><div class="small">{t('settings.vac_remaining_total')}</div><div style="font-size:22px;font-weight:700;">{vac_remaining_total:.1f}</div></div>
            <div><div class="small">{t('settings.vac_carryover_exc') if vac_carryover_exception else t('settings.vac_carryover_open')}</div><div style="font-size:22px;font-weight:700;{"color:#d97706;" if vac_carryover_exception else ""}">{vac_carryover_remaining:.1f}</div></div>
            <div><div class="small">{t('settings.vac_entitlement')} {vac_year} offen</div><div style="font-size:22px;font-weight:700;">{vac_entitlement_remaining:.1f}</div></div>
            {"<div><div class='small' style='color:var(--danger);'>" + t('settings.vac_forfeited') + "</div><div style='font-size:22px;font-weight:700;color:var(--danger);'>" + f"{vac_carryover_forfeited:.1f}" + "</div></div>" if vac_carryover_forfeited > 0 else ""}
          </div>
        </div>
      </div>
    </div>

    <!-- 3. Zeitschema -->
    <div class="acc">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-zeit')">
        <span>{t('settings.sched_section')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-zeit">
        <div class="acc-inner">
          <p class="small" style="margin-bottom:12px;">{t('settings.sched_weekend_note')}</p>
          <div class="table-scroll" style="margin-bottom:16px;">
            <table style="min-width:500px;">
              <thead><tr>
                <th>{t('settings.schedule_valid')}</th><th>{t('common.status')}</th><th>{t('settings.sched_mode_col')}</th><th>{t('settings.sched_target_col')}</th><th>{t('settings.schedule_mask')}</th><th></th>
              </tr></thead>
              <tbody>{sched_rows if sched_rows else f"<tr><td colspan='6' style='color:var(--mu);'>{t('settings.sched_none')}</td></tr>"}</tbody>
            </table>
          </div>
          {_edit_forms}
          {"" if not _can_self_edit else f'''<div class="acc-sub">
            <b style="font-size:14px;">{t('settings.sched_add_new')}</b>
            <div style="margin-top:10px;">
              {_sched_form_html(
                  _normalize_schedule({}),
                  "/settings/schedule/add",
                  url_for("settings.settings_view") + "#acc-zeit",
                  show_auto_breaks=True,
                  auto_breaks_enabled=auto_breaks_enabled
              )}
            </div>
          </div>'''}
        </div>
      </div>
    </div>

    <!-- 4. Gleitzeitkonto -->
    <div class="acc">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-gleit')">
        <span>⏱ Gleitzeitkonto</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-gleit">
        <div class="acc-inner">
          <form method="post" action="/balance/start" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;">
            <div>
              <label style="font-size:12px;color:var(--mu);">Jahresstart-Saldo {_cur_year}</label><br>
              <input name="start_balance" placeholder="+00:00 / -01:30" value="{_sb_txt}" style="min-width:160px;" required>
              <div class="small" style="color:var(--mu);margin-top:3px;">Format: +HH:MM oder -HH:MM</div>
            </div>
            <input type="hidden" name="back" value="/settings">
            <div><button class="btn" type="submit">{t('btn.save')}</button></div>
          </form>
          <div class="acc-sub">
            <div class="small" style="color:var(--mu);">{t('admin.balance_rollover')}</div>
            <div style="font-size:14px;font-weight:600;margin-top:2px;">{_rollover_lbl}</div>
            <div class="small" style="color:var(--mu);margin-top:2px;">{t('admin.balance_rollover_hint')}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 5. Kontierung -->
    <div class="acc">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-kont')">
        <span>{t('settings.kont_section')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-kont">
        <div class="acc-inner">
          {_kont_html}
        </div>
      </div>
    </div>

    <!-- 6. Standardzeiten / Vorlagen -->
    <div class="acc" id="acc-presets">
      <button class="acc-hdr" type="button" onclick="accToggle('acc-presets-body')">
        <span>{t('settings.presets')}</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body" id="acc-presets-body">
        <div class="acc-inner">
          {_presets_table}
          {_presets_add_form}
        </div>
      </div>
    </div>

    <!-- 7. Berufsschule -->
    {_voc_accordion}

    <!-- 8. Kalender-Integration -->
    {_render_calendar_integration_section(
        cal_system, cal_types, cal_prefix, cal_token, _webcal_url, _ical_url,
        cal_auth_mode, _basic_webcal_url, _basic_ical_url,
        _caldav_token_url, _caldav_basic_url
    )}

    <!-- 6. Apple Kalender -->
    {_render_icloud_settings_section(ic_enabled, ic_apple_id, ic_has_pw, ic_cal_name, ic_last_sync)}
    """
    return render_template_string(layout(t("settings.title"), body, u, APP_VERSION))




@settings_bp.get("/settings/2fa/enable")
@login_required
def settings_2fa_enable():
    from flask import render_template_string, session
    import html as _html
    from app import bootstrap, layout, flash_html, APP_VERSION, _generate_totp_secret, _PW_STRENGTH_JS
    bootstrap()
    u = current_user()
    import pyotp, io as _io, qrcode as _qr, base64 as _b64
    secret = _generate_totp_secret()
    session["pending_totp_secret"] = secret
    totp_uri = pyotp.TOTP(secret).provisioning_uri(
        name=u.get("email") or u.get("username") or "user",
        issuer_name="Zeiterfassung",
    )
    qr_img = _qr.make(totp_uri)
    buf = _io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_b64 = _b64.b64encode(buf.getvalue()).decode()
    body = f"""
    {flash_html()}
    <div class="card" style="max-width:480px;">
      <h3>&#128274; {t('settings.enable_2fa')}</h3>
      <p class="small" style="margin-bottom:12px;">{t('settings.totp_scan_hint')}</p>
      <div style="margin-bottom:16px;">
        <img src="data:image/png;base64,{qr_b64}" alt="QR Code"
             style="width:200px;height:200px;border:1px solid var(--bd);border-radius:8px;">
      </div>
      <p class="small" style="color:var(--mu);margin-bottom:12px;word-break:break-all;">
        {t('settings.totp_confirm_label')}: <code>{secret}</code>
      </p>
      <form method="post" action="/settings/2fa/enable">
        <div style="margin-bottom:12px;">
          <label>{t('settings.totp_confirm_label')}</label><br>
          <input type="text" name="code" inputmode="numeric" autocomplete="one-time-code"
                 maxlength="6" style="font-size:18px;letter-spacing:4px;width:120px;" required autofocus>
        </div>
        <div style="display:flex;gap:8px;">
          <button class="btn primary" type="submit">{t('settings.totp_activate_btn')}</button>
          <a class="btn" href="/settings#acc-security">{t('btn.cancel')}</a>
        </div>
      </form>
    </div>
    """
    return render_template_string(layout(t("settings.enable_2fa"), body, u, APP_VERSION))




@settings_bp.post("/settings/2fa/enable")
@login_required
def settings_2fa_enable_post():
    from flask import session
    from app import bootstrap, add_flash, _generate_backup_codes, _totp_encrypt
    bootstrap()
    u = current_user()
    code = (request.form.get("code") or "").strip()
    secret = session.get("pending_totp_secret")
    if not secret:
        add_flash(t("settings.totp_code_invalid"), "error")
        return redirect("/settings/2fa/enable")

    import pyotp, json as _j
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        add_flash(t("settings.totp_code_invalid"), "error")
        return redirect("/settings/2fa/enable")

    backup_codes = _generate_backup_codes()
    secret_enc = _totp_encrypt(secret)
    codes_enc = _totp_encrypt(_j.dumps(backup_codes))
    set_totp(u["id"], secret_enc, codes_enc)
    session.pop("pending_totp_secret", None)

    codes_html = " ".join(f"<code style='margin:2px;padding:2px 6px;background:var(--sf);border:1px solid var(--bd);border-radius:4px;font-size:13px;'>{c}</code>" for c in backup_codes)
    add_flash(t("settings.totp_enabled_ok"), "success")
    body = f"""
    {flash_html()}
    <div class="card" style="max-width:480px;">
      <h3>&#128274; {t('settings.backup_codes')}</h3>
      <p style="color:var(--danger);font-weight:600;margin-bottom:10px;">&#9888; {t('settings.totp_save_codes')}</p>
      <p class="small" style="margin-bottom:12px;">{t('settings.backup_codes_hint')}</p>
      <div style="margin-bottom:16px;line-height:2;">{codes_html}</div>
      <a class="btn primary" href="/settings#acc-security">{t('btn.save')}</a>
    </div>
    """
    return render_template_string(layout(t("settings.backup_codes"), body, u, APP_VERSION))




@settings_bp.post("/settings/2fa/disable")
@login_required
def settings_2fa_disable():
    from app import bootstrap, add_flash
    bootstrap()
    u = current_user()
    disable_totp(u["id"])
    add_flash(t("settings.totp_disabled"), "success")
    return redirect("/settings#acc-security")




@settings_bp.post("/settings/2fa/backup-codes")
@login_required
def settings_2fa_backup_codes():
    from flask import render_template_string
    import html as _html
    from app import bootstrap, add_flash, layout, flash_html, APP_VERSION, _generate_backup_codes, _totp_encrypt, _PW_STRENGTH_JS
    bootstrap()
    u = current_user()
    import json as _j
    totp_row = get_totp_row(u["id"])
    if not totp_row.get("totp_enabled"):
        return redirect("/settings#acc-security")
    new_codes = _generate_backup_codes()
    codes_enc = _totp_encrypt(_j.dumps(new_codes))
    update_totp_backup_codes(u["id"], codes_enc)
    codes_html = " ".join(f"<code style='margin:2px;padding:2px 6px;background:var(--sf);border:1px solid var(--bd);border-radius:4px;font-size:13px;'>{c}</code>" for c in new_codes)
    add_flash(t("settings.totp_codes_regenerated"), "success")
    body = f"""
    {flash_html()}
    <div class="card" style="max-width:480px;">
      <h3>&#128274; {t('settings.backup_codes')}</h3>
      <p style="color:var(--danger);font-weight:600;margin-bottom:10px;">&#9888; {t('settings.totp_save_codes')}</p>
      <p class="small" style="margin-bottom:12px;">{t('settings.backup_codes_hint')}</p>
      <div style="margin-bottom:16px;line-height:2;">{codes_html}</div>
      <a class="btn primary" href="/settings#acc-security">{t('btn.save')}</a>
    </div>
    """
    return render_template_string(layout(t("settings.backup_codes"), body, u, APP_VERSION))




@settings_bp.get("/settings/password")
@login_required
def settings_password():
    import html as _html
    from flask import render_template_string
    from app import bootstrap, layout, flash_html, APP_VERSION, _PW_STRENGTH_JS
    bootstrap()
    u = current_user()
    uname = _html.escape(u.get("username") or "")
    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Passwort ändern</h3>
        <a class="btn" href="/settings">← Zurück</a>
      </div>
      <form method="post" action="/settings/password" style="margin-top:12px;max-width:380px;">
        <div style="margin-bottom:10px;">
          <label>Aktuelles Passwort</label>
          <input type="password" name="current_password" required autocomplete="current-password">
        </div>
        <div style="margin-bottom:10px;">
          <label>Neues Passwort</label>
          <input type="password" name="new_password" id="spw-inp" required autocomplete="new-password"
                 oninput="_pwUpdate('spw-inp','spw-chk','{uname}')">
          <div id="spw-chk" style="margin-top:6px;padding:8px;background:var(--sf);border-radius:var(--rs);border:1px solid var(--bd);line-height:1.7;"></div>
        </div>
        <div style="margin-bottom:14px;">
          <label>Neues Passwort (Wiederholung)</label>
          <input type="password" name="new_password_confirm" required autocomplete="new-password">
        </div>
        <button class="btn primary" type="submit">Passwort speichern</button>
        <a class="btn" href="/settings">Abbrechen</a>
      </form>
    </div>
    {_PW_STRENGTH_JS}
    """
    return render_template_string(layout(t("settings.password"), body, u, APP_VERSION))




@settings_bp.post("/settings/profile")
@login_required
def settings_profile_save():
    import datetime
    from app import bootstrap, add_flash
    bootstrap()
    u = current_user()
    display_name = (request.form.get("display_name") or "").strip() or None
    email = (request.form.get("email") or "").strip() or None
    birth_date_raw = (request.form.get("birth_date") or "").strip()
    try:
        birth_date = datetime.date.fromisoformat(birth_date_raw).isoformat() if birth_date_raw else None
    except ValueError:
        birth_date = None
    try:
        retirement_age = max(60, min(72, int(request.form.get("retirement_age") or 67)))
    except (ValueError, TypeError):
        retirement_age = 67
    db = connect()
    db.execute(
        "UPDATE users SET display_name=?, email=?, birth_date=?, retirement_age=?, updated_at=datetime('now') WHERE id=?",
        (display_name, email, birth_date, retirement_age, u["id"]),
    )
    db.commit()
    db.close()
    add_flash(t("settings.profile_saved"), "success")
    return redirect("/settings")




@settings_bp.post("/settings/telegram")
@login_required
def settings_telegram_save():
    from app import bootstrap, add_flash
    bootstrap()
    u = current_user()
    raw = (request.form.get("telegram_id") or "").strip()

    if raw == "":
        db = connect()
        db.execute("DELETE FROM telegram_users WHERE user_id=?", (u["id"],))
        db.commit()
        db.close()
        add_flash(t("flash.success.telegram_removed"), "success")
        return redirect("/settings")

    if not raw.isdigit() or not (5 <= len(raw) <= 15):
        add_flash(t("flash.error.telegram_invalid"), "error")
        return redirect("/settings")

    tg_id = int(raw)
    db = connect()
    try:
        conflict = db.execute(
            "SELECT user_id FROM telegram_users WHERE telegram_id=? AND user_id!=?",
            (tg_id, u["id"]),
        ).fetchone()
        if conflict:
            add_flash(t("flash.error.telegram_taken"), "error")
            return redirect("/settings")
        db.execute(
            "INSERT OR REPLACE INTO telegram_users(telegram_id, user_id, created_at) VALUES(?,?,datetime('now'))",
            (tg_id, u["id"]),
        )
        db.commit()
    finally:
        db.close()
    add_flash(t("flash.success.telegram_saved"), "success")
    return redirect("/settings")




@settings_bp.post("/settings/reminder")
@login_required
def settings_reminder_save():
    import re
    from app import bootstrap, add_flash
    bootstrap()
    u = current_user()
    wizard_enabled = 1 if request.form.get("wizard_enabled") else 0
    reminder_time = request.form.get("reminder_time", "20:00").strip()
    if not re.match(r"^\d{2}:\d{2}$", reminder_time):
        reminder_time = "20:00"

    m = re.match(r"^(\d{2}):(\d{2})$", reminder_time)
    h, mi = int(m.group(1)), int(m.group(2))
    if not (15 <= h <= 23) or not (0 <= mi <= 59):
        add_flash(t("flash.error.reminder_time_invalid"), "error")
        return redirect("/settings")

    db = connect()
    try:
        tg_row = db.execute(
            "SELECT telegram_id FROM telegram_users WHERE user_id=?", (u["id"],)
        ).fetchone()
        if not tg_row:
            add_flash(t("flash.error.telegram_required"), "error")
            return redirect("/settings")
        db.execute(
            "UPDATE telegram_users SET wizard_enabled=?, reminder_time=? WHERE user_id=?",
            (wizard_enabled, reminder_time, u["id"]),
        )
        db.commit()
    finally:
        db.close()
    add_flash(t("flash.success.reminder_saved"), "success")
    return redirect("/settings")




@settings_bp.post("/settings/schedule/<int:sid>/edit")
@login_required
def settings_schedule_edit(sid: int):
    import datetime
    from app import (bootstrap, add_flash, _parse_sched_blocks_from_form,
                      _sched_save_blocks, _sched_save_exceptions_from_form)
    bootstrap()
    u = current_user()
    db = connect()
    row = db.execute(
        "SELECT id, allow_self_edit FROM user_schedules WHERE id=? AND user_id=?",
        (sid, u["id"])
    ).fetchone()
    if not row or int(row["allow_self_edit"] or 1) == 0:
        db.close()
        add_flash(t("settings.schedule_readonly"), "warning")
        return redirect(url_for("settings.settings_view") + "#acc-zeit")
    valid_from = (request.form.get("valid_from") or "").strip() or datetime.date.today().isoformat()
    blocks = _parse_sched_blocks_from_form(request.form)
    mask = sum(1 << wd for wd in blocks.keys()) if blocks else 0
    db.execute(
        "UPDATE user_schedules SET valid_from=?, workdays_mask=? WHERE id=? AND user_id=?",
        (valid_from, mask, sid, u["id"])
    )
    db.commit()
    _sched_save_blocks(sid, blocks)
    _sched_save_exceptions_from_form(sid, request.form)
    db.close()
    add_flash(t("success.schedule_saved"), "success")
    return redirect(url_for("settings.settings_view") + "#acc-zeit")




@settings_bp.post("/settings/schedule/add")
@login_required
def settings_schedule_add():
    from app import (bootstrap, add_flash, _parse_sched_form, _parse_sched_blocks_from_form,
                      _sched_save_blocks, _sched_save_exceptions_from_form,
                      _sched_save_to_db, _set_pref_auto_breaks)
    bootstrap()
    u = current_user()
    db = connect()
    existing = db.execute(
        "SELECT allow_self_edit FROM user_schedules WHERE user_id=? ORDER BY valid_from DESC LIMIT 1",
        (u["id"],)
    ).fetchone()
    if existing and int(existing["allow_self_edit"] or 1) == 0:
        add_flash(t("settings.schedule_readonly"), "warning")
        db.close()
        return redirect(url_for("settings.settings_view") + "#acc-zeit")
    sched = _parse_sched_form(request.form)
    if not sched["valid_from"]:
        add_flash(t("flash.error.date_format"), "error")
        db.close()
        return redirect(url_for("settings.settings_view") + "#acc-zeit")
    db.close()
    _set_pref_auto_breaks(u["id"], 1 if (request.form.get("auto_breaks") or "") == "1" else 0)
    sched_id = _sched_save_to_db(u["id"], sched)
    if sched["mode"] == "daily" or request.form.get("use_daily_blocks"):
        blocks = _parse_sched_blocks_from_form(request.form)
        _sched_save_blocks(sched_id, blocks)
        if sched["mode"] == "daily":
            _sched_save_exceptions_from_form(sched_id, request.form)
    add_flash(t("success.schedule_saved"), "success")
    return redirect(url_for("settings.settings_view") + "#acc-zeit")




@settings_bp.post("/settings/presets/add")
@login_required
def settings_preset_add():
    from app import bootstrap, add_flash
    bootstrap()
    u = current_user()
    db = connect()
    count = db.execute(
        "SELECT COUNT(*) as c FROM user_time_presets WHERE user_id=?",
        (u["id"],)
    ).fetchone()["c"]
    if count >= 3:
        add_flash(t("settings.preset_max"), "warning")
        db.close()
        return redirect(url_for("settings.settings_view") + "#acc-presets")
    label    = (request.form.get("label") or "").strip()[:30]
    time_in  = (request.form.get("time_in") or "").strip()
    time_out = (request.form.get("time_out") or "").strip()
    brk      = int(request.form.get("break_minutes") or 0)
    if label and time_in and time_out:
        db.execute(
            "INSERT INTO user_time_presets (user_id, label, time_in, time_out, break_minutes, sort_order) "
            "VALUES (?,?,?,?,?,?)",
            (u["id"], label, time_in, time_out, brk, count)
        )
        db.commit()
        add_flash(t("settings.preset_saved"), "success")
    db.close()
    return redirect(url_for("settings.settings_view") + "#acc-presets")




@settings_bp.post("/settings/presets/delete")
@login_required
def settings_preset_delete():
    from app import bootstrap, add_flash
    bootstrap()
    u = current_user()
    pid = int(request.form.get("preset_id") or 0)
    db = connect()
    db.execute(
        "DELETE FROM user_time_presets WHERE id=? AND user_id=?",
        (pid, u["id"])
    )
    db.commit()
    db.close()
    add_flash(t("settings.preset_deleted"), "success")
    return redirect(url_for("settings.settings_view") + "#acc-presets")




@settings_bp.post("/settings/password")
@login_required
def settings_password_post():
    from app import bootstrap, add_flash
    bootstrap()
    u = current_user()
    current_password = (request.form.get("current_password") or "").strip()
    new_password = (request.form.get("new_password") or "").strip()
    new_password_confirm = (request.form.get("new_password_confirm") or "").strip()

    if not current_password:
        add_flash(t("flash.error.current_password_required"), "error")
        return redirect("/settings/password")

    _, _pw_err = authenticate(u["username"], current_password)
    if _pw_err:
        add_flash(t("settings.password_wrong"), "error")
        return redirect("/settings/password")

    errs = validate_password(new_password, u.get("username") or "")
    if errs:
        add_flash(t("flash.error.password_invalid").format(errors="; ".join(errs)), "error")
        return redirect("/settings/password")

    if new_password != new_password_confirm:
        add_flash(t("settings.password_mismatch"), "error")
        return redirect("/settings/password")

    set_password(u["id"], new_password)
    add_flash(t("settings.password_saved"), "success")
    return redirect("/settings")




@settings_bp.post("/settings/icloud")
@login_required
def settings_icloud_post():
    from app import bootstrap, add_flash, _icloud_encrypt
    bootstrap()
    u = current_user()
    ic_enabled  = 1 if request.form.get("icloud_enabled") == "1" else 0
    ic_apple_id = (request.form.get("icloud_apple_id") or "").strip()
    ic_raw_pw   = (request.form.get("icloud_app_password") or "").strip()
    ic_cal_name = (request.form.get("icloud_calendar_name") or "").strip()
    db = connect()
    if ic_raw_pw:
        enc_pw = _icloud_encrypt(ic_raw_pw)
        db.execute(
            "UPDATE users SET icloud_enabled=?, icloud_apple_id=?, icloud_app_password=?, "
            "icloud_calendar_name=? WHERE id=?",
            (ic_enabled, ic_apple_id, enc_pw, ic_cal_name, u["id"]),
        )
    else:
        db.execute(
            "UPDATE users SET icloud_enabled=?, icloud_apple_id=?, icloud_calendar_name=? WHERE id=?",
            (ic_enabled, ic_apple_id, ic_cal_name, u["id"]),
        )
    db.commit()
    db.close()
    add_flash(t("settings.saved"), "success")
    return redirect("/settings#acc-icloud")




@settings_bp.get("/settings/icloud/test")
@login_required
def settings_icloud_test():
    from flask import jsonify, session
    from app import bootstrap, _icloud_decrypt
    bootstrap()
    u = current_user()
    lang = session.get("lang", "en")
    try:
        import caldav as _caldav_lib
        db = connect()
        row = db.execute(
            "SELECT icloud_apple_id, icloud_app_password, icloud_calendar_name FROM users WHERE id=?",
            (u["id"],),
        ).fetchone()
        db.close()
        apple_id = (row["icloud_apple_id"] or "").strip() if row else ""
        enc_pw   = (row["icloud_app_password"] or "").strip() if row else ""
        cal_name = (row["icloud_calendar_name"] or "").strip() if row else ""
        if not apple_id or not enc_pw:
            return jsonify(ok=False, error=t("error.icloud_auth", lang=lang))
        password = _icloud_decrypt(enc_pw)
        client   = _caldav_lib.DAVClient(url="https://caldav.icloud.com", username=apple_id, password=password, timeout=10)
        cals     = client.principal().calendars()
        cal_names = [c.name for c in cals if c.name]
        if cal_name and cal_name not in cal_names:
            return jsonify(ok=False, error=t("error.icloud_calendar_not_found", lang=lang))
        msg = t("success.icloud_connected", lang=lang)
        if cal_names:
            msg += f": {', '.join(cal_names[:8])}"
        return jsonify(ok=True, message=msg, calendars=cal_names)
    except Exception as e:
        err_str = str(e).lower()
        if "401" in err_str or "auth" in err_str or "unauthorized" in err_str or "forbidden" in err_str:
            return jsonify(ok=False, error=t("error.icloud_auth", lang=lang))
        return jsonify(ok=False, error=str(e))




@settings_bp.post("/settings/icloud/sync-all")
@login_required
def settings_icloud_sync_all():
    import datetime
    from flask import jsonify, session
    from app import bootstrap, _icloud_decrypt, _icloud_update_sync_time, _ical_escape
    bootstrap()
    u = current_user()
    lang = session.get("lang", "en")
    try:
        import caldav as _caldav_lib
        db = connect()
        row = db.execute(
            "SELECT icloud_apple_id, icloud_app_password, icloud_calendar_name, "
            "calendar_export_prefix FROM users WHERE id=?",
            (u["id"],),
        ).fetchone()
        if not row or not row["icloud_apple_id"] or not row["icloud_app_password"]:
            db.close()
            return jsonify(ok=False, error=t("error.icloud_auth", lang=lang))
        apple_id = row["icloud_apple_id"].strip()
        enc_pw   = row["icloud_app_password"].strip()
        cal_name = (row["icloud_calendar_name"] or "").strip()
        prefix   = (row["calendar_export_prefix"] or "").strip()
        if not cal_name:
            db.close()
            return jsonify(ok=False, error=t("error.icloud_calendar_not_found", lang=lang))
        password = _icloud_decrypt(enc_pw)
        absences = db.execute(
            "SELECT a.id, a.date_from, a.date_to, a.comment, at.name AS type_name "
            "FROM absences a JOIN absence_types at ON a.type_id=at.id "
            "WHERE a.user_id=? ORDER BY a.date_from",
            (u["id"],),
        ).fetchall()
        db.close()
        _lmap = {
            "Urlaub":   t("absence_type.urlaub",   lang=lang),
            "Krank":    t("absence_type.krank",     lang=lang),
            "Flextag":  t("absence_type.flextag",   lang=lang),
            "Sonstige": t("absence_type.sonstige",  lang=lang),
        }
        client    = _caldav_lib.DAVClient(url="https://caldav.icloud.com", username=apple_id, password=password, timeout=10)
        principal = client.principal()
        cal       = next((c for c in principal.calendars() if c.name == cal_name), None)
        if not cal:
            return jsonify(ok=False, error=t("error.icloud_calendar_not_found", lang=lang))
        # Delete existing Zeiterfassung events
        uid_prefix = f"zeiterfassung-{u['id']}-"
        try:
            for ev in cal.events():
                try:
                    uid_val = ev.vobject_instance.vevent.uid.value or ""
                    if uid_val.startswith(uid_prefix):
                        ev.delete()
                except Exception:
                    pass
        except Exception:
            pass
        # Create all absences
        count = 0
        dtstamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        for ab in absences:
            try:
                type_name = ab["type_name"] or ""
                remark    = (ab["comment"] or "").strip()
                label     = remark if (type_name == "Sonstige" and remark) else _lmap.get(type_name, type_name)
                summary   = f"{prefix} {label}".strip() if prefix else label
                try:
                    dtend = (datetime.date.fromisoformat(ab["date_to"]) + datetime.timedelta(days=1)).strftime("%Y%m%d")
                except Exception:
                    dtend = ab["date_to"].replace("-", "") + "01"
                dtstart = ab["date_from"].replace("-", "")
                uid_ev  = f"zeiterfassung-{u['id']}-{ab['id']}@ustrike"
                desc    = _ical_escape(remark) if remark else ""
                ev_lines = [
                    "BEGIN:VCALENDAR", "VERSION:2.0",
                    "PRODID:-//Zeiterfassung//DE", "CALSCALE:GREGORIAN",
                    "BEGIN:VEVENT",
                    f"UID:{uid_ev}",
                    f"DTSTART;VALUE=DATE:{dtstart}",
                    f"DTEND;VALUE=DATE:{dtend}",
                    f"SUMMARY:{_ical_escape(summary)}",
                    f"DTSTAMP:{dtstamp}",
                    "STATUS:CONFIRMED", "TRANSP:TRANSPARENT",
                ]
                if desc:
                    ev_lines.append(f"DESCRIPTION:{desc}")
                ev_lines += ["END:VEVENT", "END:VCALENDAR"]
                cal.save_event("\r\n".join(ev_lines) + "\r\n")
                count += 1
            except Exception as _ev_e:
                app.logger.warning("iCloud sync-all skip ab %s: %s", ab["id"], _ev_e)
        _icloud_update_sync_time(u["id"])
        return jsonify(ok=True, message=f"{count} Events synchronisiert", count=count)
    except Exception as e:
        err_str = str(e).lower()
        if "401" in err_str or "auth" in err_str or "unauthorized" in err_str:
            return jsonify(ok=False, error=t("error.icloud_auth", lang=lang))
        return jsonify(ok=False, error=str(e))




@settings_bp.post("/settings/calendar")
@login_required
def settings_calendar_post():
    from app import bootstrap, add_flash
    bootstrap()
    u = current_user()
    cal_system    = (request.form.get("calendar_system") or "ical").strip()
    cal_prefix    = (request.form.get("calendar_export_prefix") or "").strip()[:20]
    cal_auth_mode = (request.form.get("calendar_auth_mode") or "token").strip()
    if cal_auth_mode not in ("token", "basic"):
        cal_auth_mode = "token"
    # build export_types from checkboxes
    chosen = []
    for key in ("urlaub", "krank", "flextag", "sonstige"):
        if request.form.get(f"type_{key}"):
            chosen.append(key)
    cal_types = ",".join(chosen) if chosen else "urlaub"
    db = connect()
    db.execute(
        "UPDATE users SET calendar_system=?, calendar_export_types=?, calendar_export_prefix=?, calendar_auth_mode=? WHERE id=?",
        (cal_system, cal_types, cal_prefix, cal_auth_mode, u["id"]),
    )
    db.commit()
    db.close()
    add_flash(t("settings.saved"), "success")
    return redirect("/settings#acc-cal-int")




@settings_bp.post("/settings/calendar/reset-token")
@login_required
def settings_calendar_reset_token():
    from app import bootstrap, add_flash
    bootstrap()
    import uuid as _uuid
    u = current_user()
    db = connect()
    db.execute("UPDATE users SET calendar_token=? WHERE id=?", (str(_uuid.uuid4()), u["id"]))
    db.commit()
    db.close()
    add_flash(t("settings.calendar_token_reset_warning"), "success")
    return redirect("/settings#acc-cal-int")




@settings_bp.post("/settings/language")
@login_required
def settings_language_post():
    from flask import session
    from app import bootstrap, add_flash, _al
    bootstrap()
    u = current_user()
    from translations import available_languages as _al
    valid_langs = [code for code, _ in _al()]
    lang = (request.form.get("language") or "de").strip()
    if lang not in valid_langs:
        lang = "de"
    set_language(u["id"], lang)
    session["lang"] = lang
    add_flash(t("settings.language_saved"), "success")
    return redirect("/settings")




@settings_bp.get("/settings/vacation")
@login_required
def settings_vacation():
    import datetime
    from flask import render_template_string
    import html as _html
    from app import bootstrap, layout, flash_html, APP_VERSION, _vacation_calc, _fmt_date_de
    bootstrap()
    u = current_user()
    year = int(request.args.get("y") or datetime.date.today().year)

    vc = _vacation_calc(u["id"], year)
    entitlement = vc["entitlement"]
    carryover = vc["carryover"]
    deadline = vc["deadline"]
    deadline_passed = vc["deadline_passed"]
    used_total = vc["used_total"]
    carryover_remaining = vc["carryover_remaining"]
    entitlement_remaining = vc["entitlement_remaining"]
    remaining_total = vc["remaining_total"]
    carryover_forfeited = vc["carryover_forfeited"]
    effective_carryover = vc["effective_carryover"]
    carryover_exception = vc.get("carryover_exception", False)

    if carryover_exception:
        deadline_notice = f"Übertrag-Frist: {deadline}. <b style='color:#d97706;'>Ausnahme gilt – Übertrag verfällt nicht am 31.03.</b>"
    elif not deadline_passed and carryover > 0:
        deadline_notice = f"<b style='color:var(--danger);'>Übertrag verfällt am {deadline} – Urlaubsbeginn muss ≤ {deadline} liegen.</b>"
    elif deadline_passed and carryover_forfeited > 0:
        deadline_notice = f"Übertrag-Frist war {deadline}. <b style='color:var(--danger);'>{carryover_forfeited:.1f} Tage Übertrag verfallen.</b>"
    else:
        deadline_notice = f"Übertrag-Frist: {deadline}."

    exception_banner = ""
    if carryover_exception:
        exception_banner = (
            f"<div style='background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;"
            f"padding:8px 12px;margin-bottom:12px;font-size:13px;color:#92400e;'>"
            f"<b>Urlaubsübertrag: Ausnahme gilt</b> – {effective_carryover:.1f} Tage "
            f"übertragen (verfallen nicht am 31.03.)</div>"
        )

    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Urlaub – {year}</h3>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <a class="btn" href="/settings">← Zurück</a>
          <a class="btn" href="/settings/vacation?y={year-1}">◀︎ {year-1}</a>
          <a class="btn" href="/settings/vacation?y={datetime.date.today().year}">Heute</a>
          <a class="btn" href="/settings/vacation?y={year+1}">{year+1} ▶︎</a>
        </div>
      </div>

      {exception_banner}
      <p class="small">{deadline_notice}</p>

      <form method="post" action="/settings/vacation/save" style="display:flex;gap:12px;flex-wrap:wrap;align-items:end;">
        <input type="hidden" name="year" value="{year}">
        <div>
          <label>Urlaubsanspruch (Tage)</label><br>
          <input name="entitlement_days" type="number" step="0.5" min="0" value="{entitlement}" required>
        </div>
        <div>
          <label>Übertrag Vorjahr (Tage)</label><br>
          <input name="carryover_days" type="number" step="0.5" min="0" value="{carryover}" required>
        </div>
        <div>
          <button class="btn" type="submit">Speichern</button>
        </div>
      </form>

      <hr>

      <div style="display:flex;gap:18px;flex-wrap:wrap;">
        <div><div class="small">Genommen (gesamt)</div><div style="font-size:22px;"><b>{used_total:.1f}</b></div></div>
        <div><div class="small">Rest gesamt</div><div style="font-size:22px;"><b>{remaining_total:.1f}</b></div></div>
        <div style="opacity:.6;">|</div>
        <div><div class="small">{"Übertrag (Ausnahme)" if carryover_exception else "Übertrag offen"}</div><div style="font-size:22px;{'color:#d97706;' if carryover_exception else ''}"><b>{carryover_remaining:.1f}</b></div></div>
        <div><div class="small">Anspruch {year} offen</div><div style="font-size:22px;"><b>{entitlement_remaining:.1f}</b></div></div>
        {"<div><div class='small' style='color:var(--danger);'>Übertrag verfallen</div><div style='font-size:22px;color:var(--danger);'><b>" + f"{carryover_forfeited:.1f}" + "</b></div></div>" if carryover_forfeited > 0 else ""}
      </div>

      <p class="small" style="margin-top:10px;">
        Urlaub wird nur an <b>Arbeitstagen</b> gezählt (gemäß Zeitschema + Wochenenden/Feiertage).
        {"Effektiver Übertrag: <b>" + f"{effective_carryover:.1f}" + " Tage</b> (Ausnahme, konfiguriert: " + f"{carryover:.1f}" + ")." if carryover_exception else "Effektiver Übertrag: <b>" + f"{effective_carryover:.1f}" + "</b> Tage (konfiguriert: " + f"{carryover:.1f}" + ", davon bis " + deadline + " angetreten: " + f"{vc['carryover_started']:.1f}" + ")."}
      </p>
    </div>
    """
    return render_template_string(layout(t("settings.vacation"), body, u, APP_VERSION))




@settings_bp.post("/settings/vacation/save")
@login_required
def settings_vacation_save():
    import datetime
    from app import bootstrap, add_flash, _set_vacation_year
    bootstrap()
    u = current_user()
    year = int(request.form.get("year") or datetime.date.today().year)
    try:
        entitlement = float(request.form.get("entitlement_days") or 0)
        carryover = float(request.form.get("carryover_days") or 0)
        if entitlement < 0 or carryover < 0:
            raise ValueError()
    except Exception:
        add_flash(t("flash.error.invalid_days"), "error")
        return redirect("/settings#urlaub")

    _set_vacation_year(u["id"], year, entitlement, carryover)
    add_flash(t("flash.success.vacation_saved"), "success")
    return redirect("/settings#urlaub")






@settings_bp.post("/settings/save")
@login_required
def settings_save():
    import html as _html
    from flask import render_template_string
    from app import (bootstrap, add_flash, layout, flash_html, APP_VERSION, _fmt_date_de,
                      _parse_sched_form, _parse_sched_blocks_from_form,
                      _sched_save_blocks, _sched_save_exceptions_from_form,
                      _sched_save_to_db, _set_pref_auto_breaks)
    bootstrap()
    u = current_user()

    _set_pref_auto_breaks(u["id"], 1 if (request.form.get("auto_breaks") or "") == "1" else 0)

    # allow_self_edit check
    try:
        _chk_db = connect()
        _chk_row = _chk_db.execute(
            "SELECT allow_self_edit FROM user_schedules WHERE user_id=? ORDER BY valid_from DESC LIMIT 1",
            (u["id"],)
        ).fetchone()
        _chk_db.close()
        if _chk_row and int(_chk_row["allow_self_edit"] or 1) == 0:
            add_flash(t("settings.schedule_readonly"), "warning")
            return redirect(url_for("settings.settings_view") + "#acc-zeit")
    except Exception:
        pass

    sched = _parse_sched_form(request.form)
    if not sched["valid_from"]:
        add_flash(t("flash.error.date_format"), "error")
        return redirect("/settings")

    # Overlap check: warn if a newer schema exists that would override this one
    if request.form.get("confirm_overlap") != "1":
        db = connect()
        overlap_rows = db.execute(
            "SELECT id, valid_from FROM user_schedules WHERE user_id=? AND valid_from > ? ORDER BY valid_from",
            (u["id"], sched["valid_from"]),
        ).fetchall()
        db.close()
        if overlap_rows:
            dates_str = ", ".join(_fmt_date_de(r["valid_from"]) for r in overlap_rows)
            # Render confirmation page with all form data as hidden fields
            hidden = "\n".join(
                f'<input type="hidden" name="{_html.escape(k)}" value="{_html.escape(v)}">'
                for k, v in request.form.items()
                if k != "confirm_overlap"
            )
            warn_body = f"""
            {flash_html()}
            <div class="card" style="border-left:4px solid #f59e0b;">
              <h3 style="margin-top:0;">⚠ Überschneidung mit vorhandenem Zeitschema</h3>
              <p>Es existiert/existieren bereits neuere Zeitschemata (<b>{dates_str}</b>),
                 die für Daten ab diesem Datum weiterhin gelten und das neue Schema überschreiben.</p>
              <p>Das neue Schema ab <b>{_fmt_date_de(sched["valid_from"])}</b> wird ab dem nächsten neueren Schema
                 (<b>{dates_str}</b>) durch dieses ersetzt.</p>
              <p class="small">Zum vollständigen Ersetzen: zuerst das neuere Schema löschen (Einstellungen → Zeitschemata → Löschen),
                 dann erneut speichern.</p>
              <form method="post" action="/settings/save">
                {hidden}
                <input type="hidden" name="confirm_overlap" value="1">
                <button class="btn primary" type="submit">Trotzdem anlegen</button>
                <a class="btn" href="/settings">Abbrechen</a>
              </form>
            </div>
            """
            return render_template_string(layout("Zeitschema – Überschneidung", warn_body, u, APP_VERSION))

    sid = _sched_save_to_db(u["id"], sched)
    if sched["mode"] == "daily" or request.form.get("use_daily_blocks"):
        _sched_save_blocks(sid, _parse_sched_blocks_from_form(request.form))
        if sched["mode"] == "daily":
            _sched_save_exceptions_from_form(sid, request.form)
    else:
        _sched_save_blocks(sid, {})
    add_flash(t("settings.schedule_saved"), "success")
    return redirect("/settings")




@settings_bp.post("/settings/schedule/<int:schedule_id>/delete")
@login_required
def settings_schedule_delete(schedule_id: int):
    from app import bootstrap, add_flash, _fmt_date_de
    bootstrap()
    u = current_user()
    db = connect()
    row = db.execute(
        "SELECT id, valid_from FROM user_schedules WHERE id=? AND user_id=?",
        (schedule_id, u["id"]),
    ).fetchone()
    if not row:
        db.close()
        add_flash(t("flash.error.schedule_not_found"), "error")
        return redirect("/settings")
    count = db.execute("SELECT COUNT(*) FROM user_schedules WHERE user_id=?", (u["id"],)).fetchone()[0]
    if count <= 1:
        db.close()
        add_flash(t("flash.error.schedule_last"), "error")
        return redirect("/settings")
    db.execute("DELETE FROM user_schedules WHERE id=?", (schedule_id,))
    db.commit()
    db.close()
    add_flash(t("flash.success.schedule_deleted").format(date=_fmt_date_de(row["valid_from"])), "success")
    return redirect("/settings")






@settings_bp.post("/settings/contouring/toggle")
@login_required
def settings_contouring_toggle():
    import datetime
    from app import bootstrap, add_flash, _get_contouring_info, _parse_date_input, _fmt_date_de
    bootstrap()
    u = current_user()
    ci = _get_contouring_info(u["id"])
    db = connect()
    if ci["enabled"]:
        db.execute(
            "UPDATE users SET contouring_enabled=0, contouring_start_date=NULL, updated_at=datetime('now') WHERE id=?",
            (u["id"],),
        )
        db.commit()
        db.close()
        add_flash(t("flash.success.booking_disabled"), "success")
    else:
        start_date = _parse_date_input(request.form.get("contouring_start_date") or "")
        if not start_date:
            today = datetime.date.today()
            start_date = datetime.date(today.year, today.month, 1).isoformat()
        db.execute(
            "UPDATE users SET contouring_enabled=1, contouring_start_date=?, updated_at=datetime('now') WHERE id=?",
            (start_date, u["id"]),
        )
        db.commit()
        db.close()
        add_flash(t("flash.success.booking_enabled").format(date=_fmt_date_de(start_date)), "success")
    return redirect("/settings")


