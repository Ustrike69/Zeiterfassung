"""
Blueprint: Besetzungsplanung.
"""
from flask import Blueprint, request, redirect, url_for, jsonify
from db import connect
from auth import login_required, admin_required, current_user, timemanager_required
from translations import t

staffing_bp = Blueprint("staffing", __name__)


@staffing_bp.get("/staffing/day")
@login_required
def staffing_day_view():
    import datetime
    import html as _html
    from flask import render_template_string, abort
    from app import bootstrap, layout, APP_VERSION, _feature_enabled, _user_has_team_plan, _slot_applies_on_date, _user_works_in_slot, _render_staffing_day
    bootstrap()
    if not _feature_enabled("staffing"):
        abort(404)
    u = current_user()
    if not (u.get("admin_role") in ("sysadmin", "timemanager", "hr")
            or u.get("is_approver") or _user_has_team_plan(u["id"])):
        abort(403)
    iso_date = request.args.get("date", "")
    try:
        d = datetime.date.fromisoformat(iso_date)
    except ValueError:
        return redirect("/staffing")

    plan_id = request.args.get("plan_id", type=int)
    if not plan_id:
        return redirect("/staffing")

    db = connect()
    try:
        plan = db.execute(
            "SELECT sp.*, t.name as team_name, t.id as team_id "
            "FROM staffing_plans sp JOIN teams t ON t.id=sp.team_id WHERE sp.id=?",
            (plan_id,)
        ).fetchone()
        if not plan:
            abort(404)

        slots = db.execute(
            "SELECT * FROM staffing_slots WHERE plan_id=? "
            "ORDER BY COALESCE(time_from,'99:99'), sort_order",
            (plan_id,)
        ).fetchall()

        team_users = db.execute("""
            SELECT u.id, u.username, u.display_name
            FROM users u JOIN user_teams ut ON ut.user_id=u.id
            WHERE ut.team_id=? AND u.is_active=1 ORDER BY u.display_name
        """, (plan["team_id"],)).fetchall()

        assignments = db.execute("""
            SELECT sa.*, u.username, u.display_name
            FROM staffing_assignments sa JOIN users u ON u.id=sa.user_id
            WHERE sa.slot_id IN (SELECT id FROM staffing_slots WHERE plan_id=?)
        """, (plan_id,)).fetchall()
        assign_map = {}
        for a in assignments:
            assign_map.setdefault(a["slot_id"], []).append(a)

        user_ids = [u2["id"] for u2 in team_users]
        absences = []
        if user_ids:
            ph = ",".join("?" * len(user_ids))
            absences = db.execute(
                f"SELECT a.user_id, a.date_from, a.date_to, at.name as typ "
                f"FROM absences a JOIN absence_types at ON at.id=a.type_id "
                f"WHERE a.user_id IN ({ph}) AND a.date_from<=? AND a.date_to>=?",
                (*user_ids, iso_date, iso_date)
            ).fetchall()
        absent_ids = {a["user_id"] for a in absences}

        overrides = db.execute("""
            SELECT so.*, u.username, u.display_name, ss.label as slot_label
            FROM staffing_overrides so
            JOIN users u ON u.id=so.user_id
            JOIN staffing_slots ss ON ss.id=so.slot_id
            WHERE so.plan_id=? AND so.iso_date=?
        """, (plan_id, iso_date)).fetchall()

        accepted = db.execute(
            "SELECT * FROM staffing_day_accepted WHERE plan_id=? AND iso_date=?",
            (plan_id, iso_date)
        ).fetchone()
    finally:
        db.close()

    slot_data = []
    for slot in slots:
        if not _slot_applies_on_date(slot, iso_date, plan_id=plan_id):
            continue
        assigned = assign_map.get(slot["id"], [])
        override_users = [o for o in overrides
                          if o["slot_id"] == slot["id"]
                          and o["status"] in ("assigned", "confirmed")]
        _tf, _tt = slot["time_from"], slot["time_to"]
        present = [a for a in assigned
                   if a["user_id"] not in absent_ids
                   and (not (_tf and _tt) or _user_works_in_slot(a["user_id"], iso_date, _tf, _tt))
                  ] + list(override_users)
        absent_in_slot = [a for a in assigned if a["user_id"] in absent_ids]
        count = len(present)
        min_s = slot["min_staff"]
        status = "ok" if count >= min_s else ("warn" if count > 0 else "empty")
        slot_data.append({
            "slot": slot, "present": present, "absent": absent_in_slot,
            "overrides": override_users, "count": count,
            "min_staff": min_s, "status": status,
        })

    body = _render_staffing_day(
        iso_date, d, plan, plan_id, slot_data,
        team_users, absent_ids, absences, overrides, accepted, u
    )
    return render_template_string(layout(
        f"{d.strftime('%d.%m.%Y')} – {_html.escape(plan['name'])}",
        body, u, APP_VERSION
    ))




@staffing_bp.post("/staffing/day/accept")
@timemanager_required
def staffing_day_accept():
    from flask import abort
    from app import bootstrap, add_flash, _feature_enabled
    bootstrap()
    if not _feature_enabled("staffing"):
        abort(404)
    iso_date = request.form.get("date", "")
    plan_id  = int(request.form.get("plan_id", 0))
    note     = request.form.get("note", "").strip()
    u = current_user()
    db = connect()
    db.execute(
        "INSERT OR REPLACE INTO staffing_day_accepted (plan_id, iso_date, accepted_by, note) "
        "VALUES (?,?,?,?)",
        (plan_id, iso_date, u["id"], note)
    )
    db.commit()
    db.close()
    add_flash(t("staffing.day_accepted"), "success")
    return redirect(f"/staffing/day?date={iso_date}&plan_id={plan_id}")




@staffing_bp.post("/staffing/day/override")
@timemanager_required
def staffing_override_create():
    from flask import abort
    from app import bootstrap, add_flash, _feature_enabled, _get_base_url, _send_mail_simple
    bootstrap()
    if not _feature_enabled("staffing"):
        abort(404)
    iso_date = request.form.get("date", "")
    plan_id  = int(request.form.get("plan_id", 0))
    slot_id  = int(request.form.get("slot_id", 0))
    user_id  = int(request.form.get("user_id", 0))
    dates    = request.form.getlist("dates")
    require = 1 if request.form.get("require_confirm") else 0
    note    = request.form.get("note", "").strip()
    u = current_user()

    if not (plan_id and slot_id and user_id and dates):
        add_flash(t("flash.error.missing_fields"), "error")
        return redirect(f"/staffing/day?date={iso_date}&plan_id={plan_id}")

    db = connect()
    for dt in dates:
        db.execute(
            "INSERT OR IGNORE INTO staffing_overrides "
            "(plan_id, slot_id, user_id, iso_date, require_confirm, status, note, created_by) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (plan_id, slot_id, user_id, dt, require,
             "pending" if require else "assigned", note, u["id"])
        )

    if require:
        target = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if target and target["email"]:
            try:
                dates_str = ", ".join(dates)
                _target_lang = target["language"] or "de"
                _send_mail_simple(
                    target["email"],
                    t("mail.override_request_subject", _target_lang),
                    t("mail.override_request_body", _target_lang).format(
                        dates=dates_str, note=note or "–",
                        url=f"{_get_base_url()}/staffing/override/respond"
                    )
                )
            except Exception as e:
                app.logger.error(f"Override mail error: {e}")

    db.commit()
    db.close()
    add_flash(t("staffing.override_sent") if require else t("staffing.override_assigned"), "success")
    return redirect(f"/staffing/day?date={iso_date}&plan_id={plan_id}")




@staffing_bp.route("/staffing/override/respond", methods=["GET", "POST"])
@login_required
def staffing_override_respond():
    import datetime
    from flask import render_template_string
    from app import bootstrap, add_flash, layout, APP_VERSION, _render_override_respond
    bootstrap()
    u = current_user()
    db = connect()

    if request.method == "POST":
        oid    = int(request.form.get("override_id", 0))
        action = request.form.get("action")
        status = "confirmed" if action == "confirm" else "declined"
        db.execute(
            "UPDATE staffing_overrides SET status=?, confirmed_at=? WHERE id=? AND user_id=?",
            (status, datetime.datetime.now().isoformat(), oid, u["id"])
        )
        db.commit()
        db.close()
        add_flash(
            t("staffing.override_confirmed") if status == "confirmed"
            else t("staffing.override_declined"), "success"
        )
        return redirect("/staffing/override/respond")

    pending = db.execute("""
        SELECT so.*, ss.label as slot_label, sp.name as plan_name, t.name as team_name
        FROM staffing_overrides so
        JOIN staffing_slots ss ON ss.id=so.slot_id
        JOIN staffing_plans sp ON sp.id=so.plan_id
        JOIN teams t ON t.id=sp.team_id
        WHERE so.user_id=? AND so.status='pending'
        ORDER BY so.iso_date
    """, (u["id"],)).fetchall()
    db.close()

    body = _render_override_respond(pending, u)
    return render_template_string(layout(t("staffing.my_overrides"), body, u, APP_VERSION))




@staffing_bp.get("/staffing")
@login_required
def staffing_view():
    from flask import render_template_string, abort
    from app import bootstrap, layout, APP_VERSION, _feature_enabled, _user_has_team_plan, _get_staffing_week_data, _get_staffing_month_data, _render_staffing_view
    bootstrap()
    if not _feature_enabled("staffing"):
        abort(404)
    u = current_user()
    _can_see_staffing = (
        u.get("admin_role") in ("sysadmin", "timemanager", "hr")
        or u.get("is_approver")
        or _user_has_team_plan(u["id"])
    )
    if not _can_see_staffing:
        abort(403)

    view    = request.args.get("view", "week")
    plan_id = request.args.get("plan_id", type=int)

    db = connect()
    _is_admin_role = u.get("admin_role") in ("sysadmin", "timemanager", "hr")
    if _is_admin_role or u.get("is_approver"):
        plans = db.execute("""
            SELECT sp.*, t.name as team_name
            FROM staffing_plans sp
            JOIN teams t ON t.id = sp.team_id
            WHERE sp.active = 1
            ORDER BY t.name, sp.name
        """).fetchall()
    else:
        plans = db.execute("""
            SELECT sp.*, t.name as team_name
            FROM staffing_plans sp
            JOIN teams t ON t.id = sp.team_id
            JOIN user_teams ut ON ut.team_id = sp.team_id
            WHERE sp.active = 1 AND ut.user_id = ?
            ORDER BY t.name, sp.name
        """, (u["id"],)).fetchall()
    db.close()

    if not plan_id and plans:
        plan_id = plans[0]["id"]

    data = {}
    if plan_id:
        data = _get_staffing_week_data(plan_id) if view == "week" else _get_staffing_month_data(plan_id)

    body = _render_staffing_view(plans, plan_id, view, data, u)
    return render_template_string(layout(t("nav.staffing"), body, u, APP_VERSION))


