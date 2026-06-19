"""
Blueprint: Abwesenheiten.
"""
from flask import Blueprint, request, redirect, url_for, current_app
from db import connect
from auth import login_required, admin_required, current_user
from translations import t

absences_bp = Blueprint("absences", __name__)


@absences_bp.get("/absences")
@login_required
def absences_list():
    from app import bootstrap, layout, flash_html, FORM_ASSETS_JS, _date_input, _get_tracking_start, APP_VERSION
    from flask import render_template_string
    import datetime
    import html as _html
    bootstrap()
    u = current_user()
    if u and u.get("admin_only"):
        return redirect("/admin")

    q_from = (request.args.get("from") or "").strip()
    q_to = (request.args.get("to") or "").strip()
    user_start = _get_tracking_start(u["id"])

    db = connect()
    rows_sql = """
      SELECT a.id, a.date_from, a.date_to, a.is_half_day, a.comment,
             t.name AS type_name, t.color AS type_color,
             aa.status AS approval_status, aa.comment AS rejection_reason,
             apr.display_name AS approver_display, apr.username AS approver_username
      FROM absences a
      JOIN absence_types t ON t.id = a.type_id
      LEFT JOIN absence_approvals aa ON aa.absence_id = a.id
      LEFT JOIN users apr ON apr.id = aa.approver_id
      WHERE a.user_id = ?
    """
    params = [u["id"]]
    effective_from = q_from or user_start or ""
    if effective_from:
        rows_sql += " AND a.date_to >= ?"
        params.append(effective_from)
    if q_to:
        rows_sql += " AND a.date_from <= ?"
        params.append(q_to)
    rows_sql += " ORDER BY a.date_from DESC, a.id DESC"
    absences = db.execute(rows_sql, params).fetchall()
    db.close()

    def _fmt_iso(iso_val) -> str:
        try:
            d = datetime.date.fromisoformat(str(iso_val)[:10])
            return d.strftime("%d.%m.%Y")
        except Exception:
            return str(iso_val)

    trs = ""
    for a in absences:
        color = a["type_color"] or "#999"
        scope = t("absences.half_day") if a["is_half_day"] else t("absences.full_day")
        bemerkung = (a["comment"] or "") if a["type_name"] == "Sonstige" else ""
        _apst = a["approval_status"]
        _approver_name = _html.escape(a["approver_display"] or a["approver_username"] or "") if a["approval_status"] else ""
        if _apst == "pending":
            _hint = f" – {t('absence.waiting_approval')}" + (f" ({_approver_name})" if _approver_name else "")
            status_badge = f"<span style='font-size:11px;background:#fef3c7;color:#92400e;border-radius:3px;padding:2px 6px;white-space:nowrap;'>⏳ {t('absence.status_pending')}{_hint}</span>"
        elif _apst == "rejected":
            _reason = _html.escape(a["rejection_reason"] or "")
            _reason_hint = f": {_reason}" if _reason else ""
            status_badge = f"<span style='font-size:11px;background:#fee2e2;color:#991b1b;border-radius:3px;padding:2px 6px;white-space:nowrap;'>✗ {t('absence.status_rejected')}{_reason_hint}</span>"
        elif _apst == "approved":
            status_badge = f"<span style='font-size:11px;background:#dcfce7;color:#166534;border-radius:3px;padding:2px 6px;white-space:nowrap;'>✅ {t('absence.status_approved')}</span>"
        else:
            status_badge = ""
        _is_pending = _apst == "pending"
        trs += f"""
        <tr>
          <td><span style='display:inline-block;width:10px;height:10px;background:{color};border-radius:2px;margin-right:6px;'></span>{a["type_name"]}</td>
          <td>{_fmt_iso(a["date_from"])}</td>
          <td>{_fmt_iso(a["date_to"])}</td>
          <td>{scope}</td>
          <td>{bemerkung}</td>
          <td>{status_badge}</td>
          <td style="white-space:nowrap;">
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              {"" if _is_pending else f'<a class="btn btn-sm" href="/absences/{a["id"]}/edit">{t("btn.edit")}</a>'}
              <form method="post" action="/absences/{a["id"]}/delete" style="display:contents;" onsubmit="return confirm('{t("absences.confirm_delete")}');">
                <button class="btn danger btn-sm" type="submit">{t("btn.delete")}</button>
              </form>
            </div>
          </td>
        </tr>
        """
    body = f"""
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">{t("absences.title")}</h3>
        <a class="btn" href="/absences/new">{t("btn.new")}</a>
      </div>
      <form method="get" style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-top:10px;">
        {FORM_ASSETS_JS}
        <div><label>{t("absences.from")}</label><br>{_date_input("from", q_from)}</div>
        <div><label>{t("absences.to")}</label><br>{_date_input("to", q_to)}</div>
        <div><button class="btn" type="submit">{t("btn.filter")}</button> <a class="btn" href="/absences">{t("btn.reset")}</a></div>
      </form>
      <hr>
      <table>
        <thead><tr><th>{t("absences.type")}</th><th>{t("absences.from")}</th><th>{t("absences.to")}</th><th>{t("absences.scope")}</th><th>{t("absences.comment")}</th><th>{t("absence.approval_required")}</th><th></th></tr></thead>
        <tbody>{trs}</tbody>
      </table>
      {(f"<p class='small'><i>{t('absences.no_entries')}</i></p>" if not absences else "")}
    </div>
    """
    return render_template_string(layout(t("absences.title"), body, u, APP_VERSION))


@absences_bp.get("/absences/new")
@login_required
def absences_new():
    from app import bootstrap, layout, flash_html, FORM_ASSETS_JS, _date_input, _get_user_enabled_absence_type_ids, APP_VERSION
    from flask import render_template_string
    bootstrap()
    u = current_user()
    enabled_ids = _get_user_enabled_absence_type_ids(u["id"])
    db = connect()
    placeholders = ",".join("?" * len(enabled_ids)) if enabled_ids else "0"
    types = db.execute(
        f"SELECT id, name, color FROM absence_types WHERE active=1 AND id IN ({placeholders}) ORDER BY name",
        enabled_ids
    ).fetchall()
    db.close()

    options = "".join([f'<option value="{t["id"]}">{t["name"]}</option>' for t in types])
    sonstige_id = next((t["id"] for t in types if t["name"] == "Sonstige"), 0)

    body = f"""
    {flash_html()}
    {FORM_ASSETS_JS}
<script>
function syncBemerkung(sel, sonstigeId) {{
  var isSonstige = String(sel.value) === String(sonstigeId);
  var row = document.getElementById('remark_row');
  var inp = row.querySelector('input[name="comment"]');
  row.style.display = isSonstige ? '' : 'none';
  if (inp) inp.required = isSonstige;
}}
</script>
    <div class="card">
      <h3>Abwesenheit anlegen</h3>
      <form method="post" action="/absences/new">
        <div><label>Typ</label><br>
          <select name="type_id" id="absence_type_sel" required onchange="syncBemerkung(this,{sonstige_id})">{options}</select>
        </div><br>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <div><label>Von</label><br>{_date_input("date_from", required=True, min_target="date_to")}</div>
          <div><label>Bis</label><br>{_date_input("date_to", required=True)}</div>
        </div><br>
        <label><input type="checkbox" name="is_half_day" value="1"> Halber Tag (nur wenn Von=Bis)</label><br><br>
        <div id="remark_row" style="display:none;">
          <label>Bemerkung <span style="color:var(--danger);">*</span></label><br>
          <input type="text" name="comment" placeholder="Bemerkung eingeben …" style="width:100%;">
        </div><br>
        <button class="btn" type="submit">Speichern</button>
        <a class="btn" href="/absences">Abbrechen</a>
      </form>
    </div>
<script>syncBemerkung(document.getElementById('absence_type_sel'),{sonstige_id});</script>
    """
    return render_template_string(layout(t("absences.new"), body, u, APP_VERSION))


@absences_bp.post("/absences/new")
@login_required
def absences_new_post():
    from app import (bootstrap, add_flash, _parse_date_input, _resolve_comment_from_form,
                     _validate_absence_dates, _is_range_locked, _range_before_start_date,
                     _get_user_enabled_absence_type_ids, _vacation_limit_check, _fmt_vac_days,
                     _has_overlap, _send_approval_request_mail, _sync_to_icloud, app)
    from flask import session
    bootstrap()
    u = current_user()
    type_id = int(request.form.get("type_id") or 0)
    date_from = _parse_date_input(request.form.get("date_from") or "") or ""
    date_to = _parse_date_input(request.form.get("date_to") or "") or ""
    is_half_day = 1 if request.form.get("is_half_day") == "1" else 0
    comment = _resolve_comment_from_form()

    err = _validate_absence_dates(date_from, date_to, is_half_day)
    if err:
        add_flash(err, "error")
        return redirect(url_for("absences.absences_new"))

    if date_from and date_to and _is_range_locked(u["id"], date_from, date_to):
        add_flash(t("flash.error.period_locked"), "error")
        return redirect(url_for("absences.absences_new"))
    if date_from:
        sd_err = _range_before_start_date(u["id"], date_from, date_to or date_from)
        if sd_err:
            add_flash(sd_err, "error")
            return redirect(url_for("absences.absences_new"))

    _enabled_ids = _get_user_enabled_absence_type_ids(u["id"])
    if type_id not in _enabled_ids:
        add_flash(t("flash.error.invalid_absence_type"), "error")
        return redirect(url_for("absences.absences_new"))
    db = connect()
    type_row = db.execute("SELECT name FROM absence_types WHERE id=?", (type_id,)).fetchone()
    type_name = type_row["name"] if type_row else ""
    if type_name == "Sonstige" and not comment:
        db.close()
        add_flash(t("flash.error.sonstige_comment_required"), "error")
        return redirect(url_for("absences.absences_new"))

    if type_name == "Urlaub" and not u.get("is_admin"):
        chk = _vacation_limit_check(u["id"], date_from, date_to, is_half_day)
        if chk is not None:
            available, requested = chk
            if requested > available:
                db.close()
                add_flash(
                    t("flash.error.vacation_limit").format(available=_fmt_vac_days(available), requested=_fmt_vac_days(requested)),
                    "error",
                )
                return redirect(url_for("absences.absences_new"))
    elif type_name == "Urlaub" and session.get("impersonator_id"):
        chk = _vacation_limit_check(u["id"], date_from, date_to, is_half_day)
        if chk is not None:
            available, requested = chk
            if requested > available:
                add_flash(
                    t("flash.error.vacation_limit_admin").format(available=_fmt_vac_days(available), requested=_fmt_vac_days(requested)),
                    "error",
                )

    if _has_overlap(db, u["id"], date_from, date_to):
        db.close()
        add_flash(t("flash.error.absence_overlap"), "error")
        return redirect(url_for("absences.absences_new"))

    # Check if approval is required for this type
    _urow = db.execute(
        "SELECT approval_required_types, approver_id FROM users WHERE id=?", (u["id"],)
    ).fetchone()
    _art_str = (_urow["approval_required_types"] or "") if _urow else ""
    _art_ids = {int(x) for x in _art_str.split(",") if x.strip().isdigit()} if _art_str else set()
    _needs_approval = type_id in _art_ids
    _approver_id = (_urow["approver_id"] if _urow else None) if _needs_approval else None

    cur = db.execute(
        "INSERT INTO absences(user_id,type_id,date_from,date_to,is_half_day,comment) VALUES(?,?,?,?,?,?)",
        (u["id"], type_id, date_from, date_to, is_half_day, comment),
    )
    new_id = cur.lastrowid
    if type_name == "Sonstige" and comment:
        db.execute("INSERT OR IGNORE INTO absence_remarks(user_id,remark) VALUES(?,?)", (u["id"], comment))

    if _needs_approval and _approver_id:
        db.execute(
            "INSERT INTO absence_approvals(absence_id, approver_id, status, created_at, updated_at) "
            "VALUES(?, ?, 'pending', datetime('now'), datetime('now'))",
            (new_id, _approver_id),
        )

    db.commit()
    db.close()

    if _needs_approval and _approver_id:
        _send_approval_request_mail(new_id, u, type_name, date_from, date_to, _approver_id)
        add_flash(t("absences.saved_pending"), "success")
    else:
        try:
            _sync_to_icloud(u["id"], new_id, "create")
        except Exception as _e:
            current_app.logger.error("iCloud Sync Fehler (new): %s", _e)
        add_flash(t("absences.saved"), "success")
    return redirect(url_for("absences.absences_list"))


@absences_bp.get("/absences/<int:absence_id>/edit")
@login_required
def absences_edit(absence_id: int):
    from app import bootstrap, layout, flash_html, FORM_ASSETS_JS, _date_input, _get_user_enabled_absence_type_ids, APP_VERSION
    from flask import render_template_string, abort
    import html as _html
    bootstrap()
    u = current_user()
    db = connect()
    row = db.execute(
        "SELECT id, type_id, date_from, date_to, is_half_day, comment FROM absences WHERE id=? AND user_id=?",
        (absence_id, u["id"]),
    ).fetchone()
    if not row:
        db.close()
        abort(404)

    enabled_ids = _get_user_enabled_absence_type_ids(u["id"])
    placeholders = ",".join("?" * len(enabled_ids)) if enabled_ids else "0"
    types = db.execute(
        f"SELECT id, name FROM absence_types WHERE active=1 AND id IN ({placeholders}) ORDER BY name",
        enabled_ids
    ).fetchall()
    db.close()

    options = ""
    for typ in types:
        sel = "selected" if typ["id"] == row["type_id"] else ""
        options += f'<option value="{typ["id"]}" {sel}>{typ["name"]}</option>'

    sonstige_id = next((typ["id"] for typ in types if typ["name"] == "Sonstige"), 0)
    current_type_name = next((typ["name"] for typ in types if typ["id"] == row["type_id"]), "")
    is_sonstige_now = current_type_name == "Sonstige"
    checked = "checked" if row["is_half_day"] else ""
    comment = row["comment"] or ""
    remark_display = "" if is_sonstige_now else "none"
    comment_val = _html.escape(comment) if is_sonstige_now else ""

    body = f"""
    {flash_html()}
    {FORM_ASSETS_JS}
<script>
function syncBemerkung(sel, sonstigeId) {{
  var isSonstige = String(sel.value) === String(sonstigeId);
  var row = document.getElementById('remark_row');
  var inp = row.querySelector('input[name="comment"]');
  row.style.display = isSonstige ? '' : 'none';
  if (inp) inp.required = isSonstige;
}}
</script>
    <div class="card">
      <h3>Abwesenheit bearbeiten</h3>
      <form method="post" action="/absences/{absence_id}/edit">
        <div><label>Typ</label><br>
          <select name="type_id" id="absence_type_sel" required onchange="syncBemerkung(this,{sonstige_id})">{options}</select>
        </div><br>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <div><label>Von</label><br>{_date_input("date_from", str(row["date_from"]), required=True, min_target="date_to")}</div>
          <div><label>Bis</label><br>{_date_input("date_to", str(row["date_to"]), required=True)}</div>
        </div><br>
        <label><input type="checkbox" name="is_half_day" value="1" {checked}> Halber Tag (nur wenn Von=Bis)</label><br><br>
        <div id="remark_row" style="display:{remark_display};">
          <label>Bemerkung <span style="color:var(--danger);">*</span></label><br>
          <input type="text" name="comment" value="{comment_val}" placeholder="Bemerkung eingeben …" style="width:100%;">
        </div><br>
        <button class="btn" type="submit">Aktualisieren</button>
        <a class="btn" href="/absences">Abbrechen</a>
      </form>
    </div>
<script>syncBemerkung(document.getElementById('absence_type_sel'),{sonstige_id});</script>
    """
    return render_template_string(layout(t("absences.edit"), body, u, APP_VERSION))


@absences_bp.post("/absences/<int:absence_id>/edit")
@login_required
def absences_edit_post(absence_id: int):
    from app import (bootstrap, add_flash, _parse_date_input, _resolve_comment_from_form,
                     _validate_absence_dates, _is_range_locked, _range_before_start_date,
                     _get_user_enabled_absence_type_ids, _vacation_limit_check, _fmt_vac_days,
                     _has_overlap, _sync_to_icloud, app)
    from flask import session, abort
    bootstrap()
    u = current_user()

    type_id = int(request.form.get("type_id") or 0)
    date_from = _parse_date_input(request.form.get("date_from") or "") or ""
    date_to = _parse_date_input(request.form.get("date_to") or "") or ""
    is_half_day = 1 if request.form.get("is_half_day") == "1" else 0
    comment = _resolve_comment_from_form()

    err = _validate_absence_dates(date_from, date_to, is_half_day)
    if err:
        add_flash(err, "error")
        return redirect(f"/absences/{absence_id}/edit")

    _enabled_ids = _get_user_enabled_absence_type_ids(u["id"])
    if type_id not in _enabled_ids:
        add_flash(t("flash.error.invalid_absence_type"), "error")
        return redirect(f"/absences/{absence_id}/edit")
    db = connect()
    type_row = db.execute("SELECT name FROM absence_types WHERE id=?", (type_id,)).fetchone()
    type_name = type_row["name"] if type_row else ""
    if type_name == "Sonstige" and not comment:
        db.close()
        add_flash(t("flash.error.sonstige_comment_required"), "error")
        return redirect(f"/absences/{absence_id}/edit")

    row = db.execute(
        "SELECT id, date_from AS df, date_to AS dt FROM absences WHERE id=? AND user_id=?",
        (absence_id, u["id"]),
    ).fetchone()
    if not row:
        db.close()
        abort(404)

    if _is_range_locked(u["id"], row["df"], row["dt"]) or (
        date_from and date_to and _is_range_locked(u["id"], date_from, date_to)
    ):
        db.close()
        add_flash(t("flash.error.period_locked"), "error")
        return redirect(f"/absences/{absence_id}/edit")
    if date_from:
        sd_err = _range_before_start_date(u["id"], date_from, date_to or date_from)
        if sd_err:
            db.close()
            add_flash(sd_err, "error")
            return redirect(f"/absences/{absence_id}/edit")

    if type_name == "Urlaub" and not u.get("is_admin"):
        chk = _vacation_limit_check(u["id"], date_from, date_to, is_half_day, exclude_id=absence_id)
        if chk is not None:
            available, requested = chk
            if requested > available:
                db.close()
                add_flash(
                    t("flash.error.vacation_limit").format(available=_fmt_vac_days(available), requested=_fmt_vac_days(requested)),
                    "error",
                )
                return redirect(f"/absences/{absence_id}/edit")
    elif type_name == "Urlaub" and session.get("impersonator_id"):
        chk = _vacation_limit_check(u["id"], date_from, date_to, is_half_day, exclude_id=absence_id)
        if chk is not None:
            available, requested = chk
            if requested > available:
                add_flash(
                    t("flash.error.vacation_limit_admin").format(available=_fmt_vac_days(available), requested=_fmt_vac_days(requested)),
                    "error",
                )

    if _has_overlap(db, u["id"], date_from, date_to, exclude_id=absence_id):
        db.close()
        add_flash(t("flash.error.absence_overlap"), "error")
        return redirect(f"/absences/{absence_id}/edit")

    db.execute(
        "UPDATE absences SET type_id=?, date_from=?, date_to=?, is_half_day=?, comment=?, updated_at=datetime('now') "
        "WHERE id=? AND user_id=?",
        (type_id, date_from, date_to, is_half_day, comment, absence_id, u["id"]),
    )
    if type_name == "Sonstige" and comment:
        db.execute("INSERT OR IGNORE INTO absence_remarks(user_id,remark) VALUES(?,?)", (u["id"], comment))
    db.commit()
    db.close()
    try:
        _sync_to_icloud(u["id"], absence_id, "update")
    except Exception as _e:
        current_app.logger.error("iCloud Sync Fehler (edit): %s", _e)
    add_flash(t("absences.updated"), "success")
    return redirect(url_for("absences.absences_list"))


@absences_bp.post("/absences/<int:absence_id>/delete")
@login_required
def absences_delete(absence_id: int):
    from app import bootstrap, add_flash, _is_range_locked, _sync_to_icloud, app
    bootstrap()
    u = current_user()
    db = connect()
    row = db.execute(
        "SELECT date_from, date_to FROM absences WHERE id=? AND user_id=?",
        (absence_id, u["id"]),
    ).fetchone()
    if row and _is_range_locked(u["id"], row["date_from"], row["date_to"]):
        db.close()
        add_flash(t("flash.error.period_locked"), "error")
        return redirect(url_for("absences.absences_list"))
    db.close()
    try:
        _sync_to_icloud(u["id"], absence_id, "delete")
    except Exception as _e:
        current_app.logger.error("iCloud Sync Fehler (delete): %s", _e)
    db2 = connect()
    db2.execute("DELETE FROM absences WHERE id=? AND user_id=?", (absence_id, u["id"]))
    db2.commit()
    db2.close()
    add_flash(t("absences.deleted"), "success")
    return redirect(url_for("absences.absences_list"))


@absences_bp.get("/absences/export/calendar")
@login_required
def absences_export_calendar():
    from app import bootstrap, _build_ical_for_user
    from flask import session, Response as _Resp
    import datetime
    bootstrap()
    u = current_user()
    lang = session.get("lang", "en")
    db = connect()
    row = db.execute("SELECT calendar_export_types FROM users WHERE id=?", (u["id"],)).fetchone()
    db.close()
    period = request.args.get("period", "all")
    ical_data = _build_ical_for_user(u["id"], lang, period)
    filename = f"absences_{u['username']}_{datetime.date.today().year}.ics"
    return _Resp(
        ical_data,
        mimetype="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@absences_bp.get("/absences/calendar/<token>.ics")
def absences_calendar_token(token: str):
    from app import bootstrap, _ical_response
    from flask import abort
    bootstrap()
    db = connect()
    row = db.execute(
        "SELECT id, language FROM users WHERE calendar_token=? AND is_active=1",
        (token,),
    ).fetchone()
    db.close()
    if not row:
        abort(404)
    return _ical_response(row["id"], row["language"] or "en")


@absences_bp.get("/absences/calendar/kalender.ics")
def absences_calendar_basic():
    from app import bootstrap, _ical_response
    from flask import make_response as _make_response
    from auth import authenticate
    bootstrap()
    auth = request.authorization
    if not auth:
        resp = _make_response("Unauthorized", 401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="Zeiterfassung Kalender"'
        return resp
    user, _auth_err = authenticate(auth.username, auth.password)
    if not user or _auth_err:
        resp = _make_response("Unauthorized", 401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="Zeiterfassung Kalender"'
        return resp
    db = connect()
    row = db.execute("SELECT language FROM users WHERE id=?", (user["id"],)).fetchone()
    db.close()
    lang = (row["language"] or "en") if row else "en"
    return _ical_response(user["id"], lang)


@absences_bp.post("/day/<day>/absence/add")
@login_required
def day_absence_add(day: str):
    from app import (bootstrap, add_flash, _is_day_locked, _before_start_date,
                     _resolve_comment_from_form, _vacation_limit_check, _fmt_vac_days,
                     _sync_to_icloud, app)
    from flask import session
    bootstrap()
    u = current_user()
    if _is_day_locked(u["id"], day):
        add_flash(t("flash.error.period_locked"), "error")
        return redirect(f"/day/{day}")
    sd_err = _before_start_date(u["id"], day)
    if sd_err:
        add_flash(sd_err, "error")
        return redirect(f"/day/{day}")
    type_id = int(request.form.get("type_id") or 0)
    is_half_day = 1 if (request.form.get("is_half_day") == "1") else 0
    comment = _resolve_comment_from_form()

    db = connect()
    type_row = db.execute("SELECT name FROM absence_types WHERE id=?", (type_id,)).fetchone()
    type_name = type_row["name"] if type_row else ""
    if type_name == "Sonstige" and not comment:
        db.close()
        add_flash(t("flash.error.sonstige_comment_required"), "error")
        return redirect(f"/day/{day}")

    if type_name == "Urlaub" and not u.get("is_admin"):
        chk = _vacation_limit_check(u["id"], day, day, is_half_day)
        if chk is not None:
            available, requested = chk
            if requested > available:
                db.close()
                add_flash(
                    t("flash.error.vacation_limit").format(available=_fmt_vac_days(available), requested=_fmt_vac_days(requested)),
                    "error",
                )
                return redirect(f"/day/{day}")
    elif type_name == "Urlaub" and session.get("impersonator_id"):
        chk = _vacation_limit_check(u["id"], day, day, is_half_day)
        if chk is not None:
            available, requested = chk
            if requested > available:
                add_flash(
                    t("flash.error.vacation_limit_admin").format(available=_fmt_vac_days(available), requested=_fmt_vac_days(requested)),
                    "error",
                )

    overlap = db.execute(
        """
        SELECT 1 FROM absences
        WHERE user_id=?
          AND NOT (date_to < ? OR date_from > ?)
        LIMIT 1
        """,
        (u["id"], day, day),
    ).fetchone()
    if overlap:
        db.close()
        add_flash(t("flash.error.absence_exists"), "error")
        return redirect(f"/day/{day}")

    cur = db.execute(
        "INSERT INTO absences(user_id, type_id, date_from, date_to, is_half_day, comment, updated_at) VALUES(?,?,?,?,?,?,datetime('now'))",
        (u["id"], type_id, day, day, is_half_day, comment),
    )
    new_id = cur.lastrowid
    if type_name == "Sonstige" and comment:
        db.execute("INSERT OR IGNORE INTO absence_remarks(user_id,remark) VALUES(?,?)", (u["id"], comment))
    db.commit()
    db.close()
    try:
        _sync_to_icloud(u["id"], new_id, "create")
    except Exception as _e:
        current_app.logger.error("iCloud Sync Fehler (day): %s", _e)
    add_flash(t("absences.saved"), "success")
    return redirect(f"/day/{day}")
