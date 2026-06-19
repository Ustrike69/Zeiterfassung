"""
Blueprint: Tagesdetail-Ansicht und Zeitblock-Aktionen.
"""
from flask import Blueprint, request, redirect, url_for
from db import connect
from auth import login_required, current_user
from translations import t

day_bp = Blueprint("day", __name__)


@day_bp.get("/day/<day>")
@login_required
def day_detail(day: str):
    import re
    import datetime
    import html as _html
    from flask import render_template_string, abort
    from app import (bootstrap, layout, flash_html, APP_VERSION, FORM_ASSETS_JS,
                      _exception_banner, _expected_minutes_for_day, _fmt_date_de,
                      _fmt_minutes, _fmt_minutes_signed, _get_user_schedule,
                      _get_weekend_exception, _is_day_locked, _is_holiday,
                      _is_weekend, _minutes_from_hhmm, _timepicker_datalist,
                      _date_input, _time_input, _WD_DE)
    bootstrap()
    u = current_user()
    if u and u.get("admin_only"):
        return redirect("/admin")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        abort(400)

    db = connect()
    blocks = db.execute(
        "SELECT id, time_in, time_out, break_minutes, comment FROM time_blocks WHERE user_id=? AND day=? ORDER BY time_in",
        (u["id"], day),
    ).fetchall()

    # existing absence (any overlap that day)
    abs_row = db.execute(
        """
        SELECT a.id, a.is_half_day, t.name AS type_name, t.color AS type_color, a.comment
        FROM absences a
        JOIN absence_types t ON t.id=a.type_id
        WHERE a.user_id=? AND NOT (a.date_to < ? OR a.date_from > ?)
        ORDER BY a.id DESC
        LIMIT 1
        """,
        (u["id"], day, day),
    ).fetchone()

    abs_types = db.execute("SELECT id, name FROM absence_types WHERE active=1 ORDER BY name").fetchall()
    abs_sonstige_id = next((t["id"] for t in abs_types if t["name"] == "Sonstige"), 0)
    trip = db.execute(
        "SELECT * FROM business_trips WHERE user_id=? AND start_date <= ? AND (end_date >= ? OR end_date IS NULL) ORDER BY id DESC LIMIT 1",
        (u["id"], day, day),
    ).fetchone()
    db.close()

    total = 0
    for b in blocks:
        total += (_minutes_from_hhmm(b["time_out"]) - _minutes_from_hhmm(b["time_in"]) - int(b["break_minutes"] or 0))

    expected_min = _expected_minutes_for_day(u["id"], day)
    delta_min = total - expected_min

    # exception banner data
    sched_day = _get_user_schedule(u["id"])
    is_blocked_day = (
        int(sched_day.get("block_weekends_holidays", 1)) == 1
        and (_is_weekend(day) or _is_holiday(day, u["id"]))
    )
    exc_row = _get_weekend_exception(u["id"], day) if is_blocked_day else None

    # prev/next navigation
    try:
        dcur = datetime.date.fromisoformat(day)
        prev_day = (dcur - datetime.timedelta(days=1)).isoformat()
        next_day = (dcur + datetime.timedelta(days=1)).isoformat()
    except Exception:
        prev_day = day
        next_day = day

    day_locked = _is_day_locked(u["id"], day)

    _WD_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    weekday_de = _WD_DE[dcur.weekday()]
    date_de = _fmt_date_de(day)

    # Soll/Ist/Delta badges
    soll_str = _fmt_minutes(expected_min) if expected_min else "–"
    ist_str  = _fmt_minutes(total) if total else "–"
    if expected_min == 0 and total == 0:
        delta_html = ""
    else:
        delta_str = _fmt_minutes_signed(delta_min)
        delta_cls = "pos" if delta_min >= 0 else "neg"
        delta_html = f"<span class='day-stat {delta_cls}'>Δ&thinsp;<b>{delta_str}</b></span>"

    # Existing time blocks — compact table rows
    blocks_rows = ""
    for b in blocks:
        mins = _minutes_from_hhmm(b["time_out"]) - _minutes_from_hhmm(b["time_in"]) - int(b["break_minutes"] or 0)
        cmt_td = f"<span class='day-cmt'>{b['comment']}</span>" if b["comment"] else ""
        if day_locked:
            act_td = ""
        else:
            act_td = (
                f"<a class='btn btn-sm' href='/day/{day}/block/{b['id']}/edit' style='padding:2px 7px;'>✎</a>"
                f"<form method='post' action='/day/{day}/block/delete' style='display:contents;'"
                f" onsubmit=\"return confirm('Zeitblock wirklich löschen?');\">"
                f"<input type='hidden' name='block_id' value='{b['id']}'>"
                f"<button class='btn danger btn-sm' type='submit' style='padding:2px 7px;'>✕</button></form>"
            )
        blocks_rows += (
            f"<tr>"
            f"<td>{b['time_in']}</td><td>{b['time_out']}</td>"
            f"<td style='color:var(--mu);'>{int(b['break_minutes'] or 0)}m</td>"
            f"<td><b>{_fmt_minutes(mins)}</b></td>"
            f"<td>{cmt_td}</td>"
            f"<td><div style='display:flex;gap:4px;'>{act_td}</div></td>"
            f"</tr>"
        )

    if blocks_rows:
        blocks_content = (
            f"<div class='table-scroll'><table class='day-ct'>"
            f"<colgroup><col><col><col><col style='min-width:52px'><col style='min-width:60px'><col></colgroup>"
            f"<thead><tr><th>Von</th><th>Bis</th><th>Pause</th><th>Netto</th><th>Notiz</th><th></th></tr></thead>"
            f"<tbody>{blocks_rows}</tbody></table></div>"
            f"<div class='day-total'>Gesamt: <b>{_fmt_minutes(total)}</b></div>"
        )
    else:
        blocks_content = "<div class='day-empty'>Keine Zeitblöcke erfasst.</div>"

    # Existing absence — compact info
    if abs_row:
        dot = f"<span style='display:inline-block;width:9px;height:9px;background:{abs_row['type_color'] or '#999'};border-radius:2px;margin-right:5px;vertical-align:middle;'></span>"
        half = " <span style='color:var(--mu);font-size:12px;'>(½ Tag)</span>" if abs_row['is_half_day'] else ""
        cmt_abs = f"<div style='font-size:12px;color:var(--mu);margin-top:3px;'>{abs_row['comment']}</div>" if abs_row['comment'] else ""
        abs_content = (
            f"<div style='display:flex;align-items:center;gap:6px;flex-wrap:wrap;'>"
            f"{dot}<b>{abs_row['type_name']}</b>{half}</div>"
            f"{cmt_abs}"
            f"<div style='font-size:11px;color:var(--mu);margin-top:5px;'>Änderungen über → Abwesenheiten</div>"
        )
    else:
        abs_content = "<div class='day-empty'>Keine Abwesenheit.</div>"

    abs_opts = "".join([f"<option value='{t['id']}'>{t['name']}</option>" for t in abs_types])
    abs_sonstige_id_js = abs_sonstige_id

    _lock_notice = (
        "<div class='day-lock'>🔒 <b>Monat abgeschlossen</b> – Dieser Zeitraum kann nicht mehr bearbeitet werden. "
        "<a href='/periods'>Abschlüsse verwalten</a></div>"
    ) if day_locked else ""

    # Presets laden
    _presets = []
    if not day_locked:
        _db_p = connect()
        _presets = _db_p.execute(
            "SELECT * FROM user_time_presets WHERE user_id=? ORDER BY sort_order",
            (u["id"],)
        ).fetchall()
        _db_p.close()

    # Sollzeiten aus Zeitschema für diesen Wochentag (inkl. nth-week Ausnahmen)
    _schedule_blocks = []
    if not day_locked:
        _db_sb = connect()
        _day_d = datetime.date.fromisoformat(day)
        _wd = _day_d.weekday()
        _week_num = (_day_d.day - 1) // 7 + 1
        _sched = _db_sb.execute("""
            SELECT us.id FROM user_schedules us
            WHERE us.user_id=? AND us.mode='daily'
            AND us.valid_from <= ?
            ORDER BY us.valid_from DESC LIMIT 1
        """, (u["id"], day)).fetchone()
        if _sched:
            _sid = _sched["id"]
            # Check nth-week exceptions first
            _exc_applied = False
            try:
                _excs = _db_sb.execute(
                    "SELECT nth_weeks, time_from, time_to FROM schedule_exceptions "
                    "WHERE schedule_id=? AND weekday=?",
                    (_sid, _wd)
                ).fetchall()
                for _exc in _excs:
                    _weeks = [int(w) for w in _exc["nth_weeks"].split(",") if w.strip()]
                    if _week_num in _weeks:
                        _schedule_blocks = [{"time_from": _exc["time_from"],
                                             "time_to": _exc["time_to"],
                                             "break_minutes": 0}]
                        _exc_applied = True
                        break
            except Exception:
                pass
            if not _exc_applied:
                _schedule_blocks = _db_sb.execute("""
                    SELECT time_from, time_to, 0 as break_minutes
                    FROM schedule_daily_blocks
                    WHERE schedule_id=? AND weekday=?
                    ORDER BY sort_order
                """, (_sid, _wd)).fetchall()
        _db_sb.close()

    _preset_opts = "".join(
        f'<option value="{p["time_in"]},{p["time_out"]},{p["break_minutes"]}">'
        f'{_html.escape(p["label"])} ({p["time_in"]}–{p["time_out"]})'
        f'</option>'
        for p in _presets
    )
    _sched_opts = ""
    for i, b in enumerate(_schedule_blocks):
        brk = b["break_minutes"] or 0
        if len(_schedule_blocks) > 1:
            _slabel = f'{t("day.preset_schedule")} {i+1}: {b["time_from"]}–{b["time_to"]}'
        else:
            _slabel = f'{t("day.preset_schedule")} ({b["time_from"]}–{b["time_to"]})'
        _sched_opts += (
            f'<option value="{b["time_from"]},{b["time_to"]},{brk}">'
            f'{_html.escape(_slabel)}</option>'
        )
    _sched_optgroup = (
        f'<optgroup label="{t("day.preset_schedule_group")}">{_sched_opts}</optgroup>'
        if _sched_opts else ""
    )
    _saved_optgroup = (
        f'<optgroup label="{t("day.preset_saved_group")}">{_preset_opts}</optgroup>'
        if _preset_opts else ""
    )
    _preset_select = f"""
    <div style="margin-bottom:10px;">
      <label style="font-size:11px;color:var(--mu);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px;">{t('day.preset')}</label>
      <select id="preset-select" onchange="applyPreset(this)"
              style="font-size:13px;padding:6px 8px;border-radius:6px;min-width:200px;">
        <option value="">{t('day.preset_choose')}</option>
        {_sched_optgroup}
        {_saved_optgroup}
      </select>
    </div>
    <script>
    function applyPreset(sel) {{
      if (!sel.value) return;
      var parts = sel.value.split(',');
      document.getElementById('tin_add').value  = parts[0];
      document.getElementById('tout_add').value = parts[1];
      document.getElementById('brk_day_add').value = parts[2] || '0';
      sel.value = '';
    }}
    </script>
    """ if (_presets or _schedule_blocks) else ""

    # Compact add-block form
    _add_block_form_html = "" if day_locked else f"""
      <form method="post" action="/day/{day}/block/add" id="block-add-form" novalidate onsubmit="return validateBlockForm(this)">
        {_preset_select}
        <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:nowrap;margin-bottom:12px;">
          <div>
            <label style="font-size:11px;color:var(--mu);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px;">{t('day.time_in')}</label>
            <input class="tin" id="tin_add" name="time_in" type="time"
                   list="time_suggestions" required
                   style="width:120px;font-size:1.2rem;padding:6px 8px;border-radius:6px;">
          </div>
          <div style="padding-bottom:6px;color:var(--mu);">–</div>
          <div>
            <label style="font-size:11px;color:var(--mu);text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px;">{t('day.time_out')}</label>
            <input id="tout_add" name="time_out" type="time"
                   list="time_suggestions" required
                   style="width:120px;font-size:1.2rem;padding:6px 8px;border-radius:6px;">
          </div>
        </div>
        <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin-bottom:8px;">
          <div style="min-width:100px;">
            <label style="font-size:12px;color:var(--mu);display:block;margin-bottom:4px;">{t('day.break_min')}</label>
            <input id="brk_day_add" name="break_minutes" type="number" min="0" value="0" required
                   style="width:70px;font-size:1.2rem;padding:6px 8px;border-radius:6px;">
            <div class="brk-btns" style="margin-top:4px;">
              <button class="btn btn-sm" type="button" onclick="document.getElementById('brk_day_add').value='30'">30</button>
              <button class="btn btn-sm" type="button" onclick="document.getElementById('brk_day_add').value='45'">45</button>
              <button class="btn btn-sm" type="button" onclick="document.getElementById('brk_day_add').value='60'">60</button>
            </div>
          </div>
          <div style="flex:1;min-width:140px;">
            <label style="font-size:12px;color:var(--mu);display:block;margin-bottom:4px;">{t('day.comment_optional')}</label>
            <input name="comment" placeholder="{t('day.comment_optional')}"
                   style="width:100%;font-size:13px;padding:8px;">
          </div>
          <button class="btn primary" type="submit"
                  style="align-self:flex-end;padding:10px 24px;font-size:1rem;font-weight:700;white-space:nowrap;">
            ✓ {t('btn.save')}
          </button>
        </div>
        <div id="block-add-err" style="display:none;margin-top:6px;padding:5px 9px;background:rgba(220,38,38,.1);border-radius:6px;color:var(--danger);font-size:12px;"></div>
      </form>
<script>
function validateBlockForm(form) {{
  var tin  = form.querySelector('[name="time_in"]');
  var tout = form.querySelector('[name="time_out"]');
  var err  = form.querySelector('[id$="-err"]') || form.querySelector('[id*="err"]');
  function showErr(msg) {{
    if (err) {{ err.textContent = msg; err.style.display = 'block'; }}
    else {{ alert(msg); }}
    return false;
  }}
  var tval = /^\\d{{2}}:\\d{{2}}$/;
  if (!tin.value || !tval.test(tin.value))  return showErr('Kommen fehlt oder ungültig (HH:MM).');
  if (!tout.value || !tval.test(tout.value)) return showErr('Gehen fehlt oder ungültig (HH:MM).');
  var s = parseInt(tin.value.replace(':',''),10);
  var e = parseInt(tout.value.replace(':',''),10);
  if (e <= s) return showErr('Gehen muss nach Kommen liegen.');
  if (err) err.style.display = 'none';
  return true;
}}
</script>"""

    # Compact add-absence form
    _add_absence_form_html = "" if day_locked else f"""
      <form method="post" action="/day/{day}/absence/add">
        <div style="display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:6px;">
          <div class="tb-field" style="flex:1;min-width:120px;">
            <label>Typ</label>
            <select name="type_id" id="day_type_sel" required onchange="syncDayBemerkung(this)">{abs_opts}</select>
          </div>
          <label style="font-size:13px;padding-bottom:6px;white-space:nowrap;font-weight:400;"><input type="checkbox" name="is_half_day" value="1"> ½ Tag</label>
          <button class="btn primary btn-sm" type="submit" style="white-space:nowrap;">+ Speichern</button>
        </div>
        <div id="d_remark_row" style="display:none;margin-top:6px;">
          <input type="text" name="comment" placeholder="Bemerkung …" style="width:100%;font-size:13px;">
        </div>
      </form>
      <div style="font-size:11px;color:var(--mu);margin-top:4px;">Bereits vorhandene Abwesenheit wird nicht überschrieben.</div>
<script>
function syncDayBemerkung(sel) {{
  var isSonstige = String(sel.value) === String({abs_sonstige_id_js});
  document.getElementById("d_remark_row").style.display = isSonstige ? "" : "none";
}}
syncDayBemerkung(document.getElementById("day_type_sel"));
</script>"""

    body = f"""
    {flash_html()}
    {FORM_ASSETS_JS}
    {_timepicker_datalist('time_suggestions')}
<style>
/* ── Day editor compact ── */
.day-hdr{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;padding:8px 0 10px;border-bottom:1px solid var(--bd);margin-bottom:10px;}}
.day-hdr-l{{display:flex;align-items:center;gap:6px;}}
.day-nav{{display:flex;align-items:center;gap:4px;}}
.day-title{{font-weight:700;font-size:17px;}}
.day-sub{{color:var(--mu);font-size:13px;margin-left:4px;}}
.day-hdr-r{{display:flex;align-items:center;gap:6px;flex-wrap:wrap;}}
.day-stat{{font-size:12px;padding:3px 7px;background:var(--sf);border:1px solid var(--bd);border-radius:5px;white-space:nowrap;}}
.day-stat.pos{{color:var(--ok);border-color:rgba(22,163,74,.35);background:rgba(22,163,74,.07);}}
.day-stat.neg{{color:var(--danger);border-color:rgba(220,38,38,.3);background:rgba(220,38,38,.06);}}
.day-grid{{display:grid;grid-template-columns:1fr;gap:10px;margin-bottom:10px;}}
@media(min-width:640px){{.day-grid{{grid-template-columns:1fr 1fr;}}}}
.day-col{{display:flex;flex-direction:column;gap:8px;}}
.day-sec{{background:var(--sf);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;}}
.day-sec-hdr{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--mu);padding:7px 12px;border-bottom:1px solid var(--bd);background:var(--bg);}}
.day-sec-body{{padding:10px 12px;}}
.day-ct td,.day-ct th{{padding:4px 6px;font-size:13px;}}
.day-ct th{{font-size:11px;}}
.day-ct tr:last-child td{{border-bottom:none;}}
.day-total{{font-size:13px;padding:5px 6px;color:var(--mu);border-top:1px solid var(--bd);margin-top:2px;}}
.day-empty{{font-size:13px;color:var(--mu);padding:4px 0;}}
.day-cmt{{font-size:11px;color:var(--mu);}}
.day-lock{{padding:9px 12px;background:var(--sf);border:1px solid var(--bd);border-radius:var(--rs);font-size:13px;margin-bottom:8px;}}
.tb-row{{display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;}}
.tb-field{{display:flex;flex-direction:column;gap:2px;}}
.tb-field label{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--mu);margin-bottom:0;}}
.tb-field input[type=time]{{min-width:90px;font-size:14px;padding:5px 7px;}}
.tb-field select{{font-size:14px;padding:5px 7px;}}
.brk-btns{{display:flex;gap:3px;margin-top:3px;}}
.brk-btns .btn{{padding:2px 6px;font-size:11px;}}
.day-trip{{margin-bottom:0;}}
.day-trip .day-sec-body label{{font-size:12px;margin-bottom:2px;}}
.day-trip .day-sec-body input,.day-trip .day-sec-body select,.day-trip .day-sec-body textarea{{font-size:13px;padding:5px 8px;}}
.exc-banner{{display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:8px 12px;border-radius:var(--rs);font-size:13px;margin-bottom:8px;border:1px solid;}}
.exc-ok{{border-color:#16a34a;background:rgba(22,163,74,.07);color:#15803d;}}
.exc-warn{{border-color:#f59e0b;background:rgba(245,158,11,.08);color:#b45309;}}
.exc-sub{{display:block;font-size:11px;opacity:.8;margin-top:1px;}}
@media(prefers-color-scheme:dark){{
  .exc-ok{{color:#4ade80;}}
  .exc-warn{{color:#fbbf24;}}
}}
</style>

    <!-- Day header -->
    <div class="day-hdr">
      <div class="day-hdr-l">
        <div class="day-nav">
          <a class="btn btn-sm" href="/day/{prev_day}" title="Vorheriger Tag">◀</a>
          <div style="margin:0 4px;">
            <span class="day-title">{weekday_de}</span>
            <span class="day-sub">{date_de}</span>
          </div>
          <a class="btn btn-sm" href="/day/{next_day}" title="Nächster Tag">▶</a>
        </div>
      </div>
      <div class="day-hdr-r">
        <span class="day-stat">Soll&thinsp;<b>{soll_str}</b></span>
        <span class="day-stat">Ist&thinsp;<b>{ist_str}</b></span>
        {delta_html}
        {f'<span style="background:{abs_row["type_color"] or "#6366f1"};color:#fff;border-radius:4px;padding:2px 8px;font-size:12px;">🏖 {_html.escape(abs_row["type_name"])}</span>' if abs_row else ""}
        <a class="btn btn-sm" href="/">← {t('nav.home')}</a>
        <a class="btn btn-sm" href="/absences?date={day}" title="{t('dashboard.absences')}">🏖</a>
        <a class="btn btn-sm" href="/business_trips" title="{t('dashboard.business_trips')}">✈</a>
        <a class="btn btn-sm" href="/calendar?y={day[:4]}&m={int(day[5:7])}">Kalender</a>
      </div>
    </div>

    {_exception_banner(day, is_blocked_day, exc_row, day_locked)}
    {_lock_notice}

    <!-- Zeitblöcke -->
    <style>
    @media (max-width:600px){{.day-two-col{{grid-template-columns:1fr !important;}}}}
    @media (orientation:landscape) and (max-width:900px){{.day-two-col{{grid-template-columns:1fr 1fr !important;}}}}
    </style>
    <div class="day-two-col" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start;">
      <div class="day-sec">
        <div id="new-block" class="day-sec-hdr">{t('day.add_block')}</div>
        <div class="day-sec-body">
          {_add_block_form_html if not day_locked else "<div class='day-empty'>Gesperrt.</div>"}
        </div>
      </div>
      <div class="day-sec">
        <div class="day-sec-hdr">{t('day.existing_blocks')}</div>
        <div class="day-sec-body" style="padding:8px 12px;">
          {blocks_content}
        </div>
      </div>
    </div>
    <script>
    (function() {{
      if (window.location.hash !== '#new-block') return;
      var el = document.getElementById('new-block');
      if (!el) return;
      el.scrollIntoView({{behavior: 'smooth', block: 'start'}});
      el.style.outline = '2px solid var(--ac)';
      el.style.borderRadius = '6px';
      setTimeout(function() {{ el.style.outline = ''; }}, 2000);
    }})();
    </script>
    """
    return render_template_string(layout(t("day.title"), body, u, APP_VERSION, show_back=True))




@day_bp.post("/day/<day>/block/add")
@login_required
def day_block_add(day: str):
    import re
    from app import (bootstrap, add_flash, _apply_auto_breaks_if_needed,
                      _before_start_date, _get_pref_auto_breaks, _get_user_schedule,
                      _has_weekend_exception, _is_day_locked, _is_holiday,
                      _is_weekend, _minutes_from_hhmm, _round_to_15,
                      _set_weekend_exception, _validate_block)
    bootstrap()
    u = current_user()
    # Normalize to YYYY-MM-DD so calendar and DB always match
    day = str(day).strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        add_flash(t("flash.error.invalid_date"), "error")
        return redirect("/calendar")
    if _is_day_locked(u["id"], day):
        add_flash(t("flash.error.period_locked"), "error")
        return redirect(f"/day/{day}")
    sd_err = _before_start_date(u["id"], day)
    if sd_err:
        add_flash(sd_err, "error")
        return redirect(f"/day/{day}")
    sched = _get_user_schedule(u['id'])
    if int(sched.get('block_weekends_holidays',1)) == 1:
        if _is_weekend(day) or _is_holiday(day, u['id']):
            if not _has_weekend_exception(u['id'], day):
                if request.form.get('override_nonwork'):
                    if request.form.get('save_exception'):
                        _set_weekend_exception(u['id'], day, (request.form.get('exception_note') or '').strip()[:200])
                else:
                    add_flash(t("flash.error.weekend_blocked"), "error")
                    return redirect(f"/day/{day}")
    time_in = _round_to_15((request.form.get("time_in") or "").strip())
    time_out = _round_to_15((request.form.get("time_out") or "").strip())
    break_minutes = int(request.form.get("break_minutes") or 0)
    comment = (request.form.get("comment") or "").strip()

    ok, msg = _validate_block(time_in, time_out, break_minutes)
    if not ok:
        add_flash(msg, "error")
        return redirect(f"/day/{day}")

    s = _minutes_from_hhmm(time_in)
    e = _minutes_from_hhmm(time_out)

    # automatische Pausen (optional)
    if _get_pref_auto_breaks(u["id"]) == 1:
        break_minutes = _apply_auto_breaks_if_needed(e - s, break_minutes)
        if break_minutes >= (e - s):
            add_flash(t("flash.error.break_too_large"), "error")
            return redirect(f"/day/{day}")

    db = connect()
    existing = db.execute("SELECT time_in, time_out FROM time_blocks WHERE user_id=? AND day=?", (u["id"], day)).fetchall()
    for r in existing:
        s2 = _minutes_from_hhmm(r["time_in"])
        e2 = _minutes_from_hhmm(r["time_out"])
        if not (e <= s2 or s >= e2):
            db.close()
            add_flash(t("flash.error.block_overlap"), "error")
            return redirect(f"/day/{day}")

    db.execute(
        "INSERT INTO time_blocks(user_id, day, time_in, time_out, break_minutes, comment, updated_at) VALUES(?,?,?,?,?,?,datetime('now'))",
        (u["id"], day, time_in, time_out, break_minutes, comment),
    )
    db.commit()
    db.close()
    add_flash(t("day.saved"), "success")
    return redirect(f"/day/{day}")




@day_bp.get("/day/<day>/block/<int:block_id>/edit")
@login_required
def day_block_edit(day: str, block_id: int):
    import re
    from flask import render_template_string, abort
    from app import bootstrap, add_flash, layout, flash_html, APP_VERSION, _is_day_locked, _timepicker_datalist
    bootstrap()
    u = current_user()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        abort(400)
    if _is_day_locked(u["id"], day):
        add_flash(t("flash.error.period_locked"), "error")
        return redirect(f"/day/{day}")

    db = connect()
    b = db.execute(
        "SELECT id, time_in, time_out, break_minutes, comment FROM time_blocks WHERE id=? AND user_id=? AND day=?",
        (int(block_id), int(u["id"]), day),
    ).fetchone()
    db.close()
    if not b:
        abort(404)

    body = f"""
    {flash_html()}

<script>
  function syncTimeMin(startId, endId){{
    try{{
      const s = document.getElementById(startId);
      const e = document.getElementById(endId);
      if(!s || !e) return;
      if(s.value){{
        e.min = s.value;
        if(e.value && e.value <= s.value){{ e.value = ''; }}
      }} else {{ e.min = ''; }}
    }}catch(_){{}}
  }}
  function setBreak(id, val){{
    const el = document.getElementById(id);
    if(!el) return;
    el.value = String(val);
  }}
</script>

    {_timepicker_datalist('time_suggestions')}
    <script>
      function setBreakBtn(btn, mins){{
        const f = btn.closest('form');
        if (!f) return false;
        const el = f.querySelector('.brk');
        if (el) el.value = String(mins);
        return false;
      }}
    </script>
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">Zeitblock bearbeiten – {day}</h3>
        <a class="btn" href="/day/{day}">Zurück</a>
      </div>

      <form method="post" action="/day/{day}/block/{block_id}/edit" style="margin-top:10px;" novalidate onsubmit="return validateBlockForm(this)">
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <div><label>Kommen</label><br><input class="tin" name="time_in" type="time" list="time_suggestions" placeholder="HH:MM" value="{b['time_in']}" required></div>
          <div><label>Gehen</label><br><input class="tout" name="time_out" type="time" list="time_suggestions" placeholder="HH:MM" value="{b['time_out']}" required></div>
          <div><label>Pause (min)</label><br><input id="brk_day_edit" class="brk" name="break_minutes" type="number" min="0" value="{int(b['break_minutes'] or 0)}" required>
<div style='margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;'><button class='btn btn-sm' type='button'  onclick="document.getElementById('brk_day_edit').value='30'">30</button><button class='btn btn-sm' type='button'  onclick="document.getElementById('brk_day_edit').value='45'">45</button><button class='btn btn-sm' type='button'  onclick="document.getElementById('brk_day_edit').value='60'">60</button></div></div>
          <div class='small' style='display:flex;gap:6px;align-items:center;margin-top:6px;'><span style='color:#777;'>Schnellwahl:</span><a href="#" class="btn btn-sm" onclick="return setBreak(this,30);">30</a><a href="#" class="btn btn-sm" onclick="return setBreak(this,45);">45</a><a href="#" class="btn btn-sm" onclick="return setBreak(this,60);">60</a><span style='color:#777;'>min</span></div>
        </div>
        <div style="margin-top:8px;"><label>Kommentar</label><br><input name="comment" value="{(b['comment'] or '')}" placeholder="optional" style="width:100%;"></div>
        <div id="block-edit-err" style="display:none;margin-top:8px;padding:6px 10px;background:rgba(220,38,38,.1);border-radius:6px;color:var(--danger);font-size:13px;"></div>
        <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;">
          <button class="btn" type="submit">Speichern</button>
          <a class="btn" href="/day/{day}">Abbrechen</a>
        </div>
      </form>
    </div>
<script>
function validateBlockForm(form) {{
  var tin  = form.querySelector('[name="time_in"]');
  var tout = form.querySelector('[name="time_out"]');
  var err  = form.querySelector('[id$="-err"]') || form.querySelector('[id*="err"]');
  function showErr(msg) {{
    if (err) {{ err.textContent = msg; err.style.display = 'block'; }}
    else {{ alert(msg); }}
    return false;
  }}
  var tval = /^\\d{{2}}:\\d{{2}}$/;
  if (!tin.value || !tval.test(tin.value))  return showErr('Bitte gültige Kommen-Zeit im Format HH:MM eingeben.');
  if (!tout.value || !tval.test(tout.value)) return showErr('Bitte gültige Gehen-Zeit im Format HH:MM eingeben.');
  var s = parseInt(tin.value.replace(':',''),10);
  var e = parseInt(tout.value.replace(':',''),10);
  if (e <= s) return showErr('Gehen muss nach Kommen liegen.');
  if (err) err.style.display = 'none';
  return true;
}}
</script>
    """
    return render_template_string(layout(t("day.edit_block"), body, u, APP_VERSION))




@day_bp.post("/day/<day>/block/<int:block_id>/edit")
@login_required
def day_block_edit_post(day: str, block_id: int):
    import re
    from flask import abort
    from app import (bootstrap, add_flash, _apply_auto_breaks_if_needed,
                      _before_start_date, _get_pref_auto_breaks, _get_user_schedule,
                      _has_weekend_exception, _is_day_locked, _is_holiday,
                      _is_weekend, _minutes_from_hhmm, _round_to_15,
                      _set_weekend_exception, _validate_block)
    bootstrap()
    u = current_user()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        abort(400)
    if _is_day_locked(u["id"], day):
        add_flash(t("flash.error.period_locked"), "error")
        return redirect(f"/day/{day}")
    sd_err = _before_start_date(u["id"], day)
    if sd_err:
        add_flash(sd_err, "error")
        return redirect(f"/day/{day}/block/{block_id}/edit")

    sched = _get_user_schedule(u['id'])
    if int(sched.get('block_weekends_holidays', 1)) == 1:
        if _is_weekend(day) or _is_holiday(day, u['id']):
            if not _has_weekend_exception(u['id'], day):
                if request.form.get('override_nonwork'):
                    if request.form.get('save_exception'):
                        _set_weekend_exception(u['id'], day, (request.form.get('exception_note') or '').strip()[:200])
                else:
                    add_flash(t("flash.error.weekend_blocked"), "error")
                    return redirect(f"/day/{day}/block/{block_id}/edit")

    time_in = _round_to_15((request.form.get("time_in") or "").strip())
    time_out = _round_to_15((request.form.get("time_out") or "").strip())
    try:
        break_minutes = int(request.form.get("break_minutes") or 0)
    except Exception:
        break_minutes = 0
    comment = (request.form.get("comment") or "").strip()

    ok, msg = _validate_block(time_in, time_out, break_minutes)
    if not ok:
        add_flash(msg, "error")
        return redirect(f"/day/{day}/block/{block_id}/edit")

    s = _minutes_from_hhmm(time_in)
    e = _minutes_from_hhmm(time_out)

    # automatische Pausen (optional)
    if _get_pref_auto_breaks(u["id"]) == 1:
        break_minutes = _apply_auto_breaks_if_needed(e - s, break_minutes)
        if break_minutes >= (e - s):
            add_flash(t("flash.error.break_too_large"), "error")
            return redirect(f"/day/{day}/block/{block_id}/edit")

    db = connect()
    # ensure block exists and belongs to user
    b = db.execute(
        "SELECT id FROM time_blocks WHERE id=? AND user_id=? AND day=?",
        (int(block_id), int(u["id"]), day),
    ).fetchone()
    if not b:
        db.close()
        abort(404)

    # overlap check excluding the current block
    existing = db.execute(
        "SELECT id, time_in, time_out FROM time_blocks WHERE user_id=? AND day=? AND id<>?",
        (u["id"], day, int(block_id)),
    ).fetchall()
    for r in existing:
        s2 = _minutes_from_hhmm(r["time_in"])
        e2 = _minutes_from_hhmm(r["time_out"])
        if not (e <= s2 or s >= e2):
            db.close()
            add_flash(t("flash.error.block_overlap"), "error")
            return redirect(f"/day/{day}/block/{block_id}/edit")

    db.execute(
        "UPDATE time_blocks SET time_in=?, time_out=?, break_minutes=?, comment=?, updated_at=datetime('now') WHERE id=? AND user_id=?",
        (time_in, time_out, int(break_minutes), comment, int(block_id), int(u["id"])),
    )
    db.commit()
    db.close()
    add_flash(t("day.updated"), "success")
    return redirect(f"/day/{day}")




@day_bp.post("/day/<day>/block/delete")
@login_required
def day_block_delete(day: str):
    from app import bootstrap, add_flash, _is_day_locked
    bootstrap()
    u = current_user()
    if _is_day_locked(u["id"], day):
        add_flash(t("flash.error.period_locked"), "error")
        return redirect(f"/day/{day}")
    block_id = int(request.form.get("block_id") or 0)
    db = connect()
    db.execute("DELETE FROM time_blocks WHERE id=? AND user_id=?", (block_id, u["id"]))
    db.commit()
    db.close()
    add_flash(t("day.deleted"), "success")
    return redirect(f"/day/{day}")
