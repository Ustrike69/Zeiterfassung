"""
Blueprint: Berufsschule-Verwaltung (POST-Routen).

bootstrap, add_flash und _parse_date_input werden lokal in jeder Route
importiert, um den zirkulären Import (app.py → blueprint → app.py) zu
vermeiden. Der lokale Import greift erst beim ersten Aufruf, wenn app.py
vollständig geladen ist.
"""
from flask import Blueprint, request, redirect
from db import connect
from auth import login_required, admin_required, current_user
from translations import t

vocational_bp = Blueprint("vocational", __name__)


@vocational_bp.post("/settings/vocational/add")
@login_required
def settings_vocational_add():
    from app import bootstrap, add_flash, _parse_date_input
    bootstrap()
    u = current_user()
    stype    = request.form.get("schedule_type", "weekly")
    voc_type = request.form.get("voc_type", "full")
    weekday  = request.form.get("weekday")
    school_tf  = request.form.get("school_time_from", "").strip() or None
    school_tt  = request.form.get("school_time_to",   "").strip() or None
    work_tf    = request.form.get("work_time_from",    "").strip() or None
    work_tt    = request.form.get("work_time_to",      "").strip() or None
    date_from  = _parse_date_input(request.form.get("date_from")  or "")
    date_to    = _parse_date_input(request.form.get("date_to")    or "")
    valid_from = _parse_date_input(request.form.get("valid_from") or "")
    valid_to   = _parse_date_input(request.form.get("valid_to")   or "")
    note = (request.form.get("note") or "").strip()
    if stype == "weekly":
        if weekday is None:
            return redirect("/settings#acc-voc")
        if voc_type != "half":
            school_tf = school_tt = work_tf = work_tt = None
    elif stype == "block":
        if not date_from or not date_to:
            return redirect("/settings#acc-voc")
        weekday = None
    db = connect()
    db.execute(
        "INSERT INTO vocational_school(user_id, schedule_type, weekday, "
        "school_time_from, school_time_to, work_time_from, work_time_to, "
        "date_from, date_to, valid_from, valid_to, note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (u["id"], stype, int(weekday) if weekday is not None else None,
         school_tf, school_tt, work_tf, work_tt,
         date_from, date_to, valid_from, valid_to, note)
    )
    db.commit()
    db.close()
    add_flash(t("admin.user_saved"), "success")
    return redirect("/settings#acc-voc")


@vocational_bp.post("/settings/vocational/delete")
@login_required
def settings_vocational_delete():
    from app import bootstrap
    bootstrap()
    u = current_user()
    entry_id = int(request.form.get("entry_id") or 0)
    if entry_id:
        db = connect()
        db.execute("DELETE FROM vocational_school WHERE id=? AND user_id=?", (entry_id, u["id"]))
        db.commit()
        db.close()
    return redirect("/settings#acc-voc")


@vocational_bp.post("/admin/users/<int:user_id>/vocational/add")
@admin_required
def admin_vocational_add(user_id: int):
    from app import bootstrap, add_flash, _parse_date_input
    bootstrap()
    stype    = request.form.get("schedule_type", "weekly")
    voc_type = request.form.get("voc_type", "full")
    weekday  = request.form.get("weekday")
    work_tf    = request.form.get("work_time_from", "").strip() or None
    work_tt    = request.form.get("work_time_to",   "").strip() or None
    date_from  = _parse_date_input(request.form.get("date_from")  or "")
    date_to    = _parse_date_input(request.form.get("date_to")    or "")
    valid_from = _parse_date_input(request.form.get("valid_from") or "")
    valid_to   = _parse_date_input(request.form.get("valid_to")   or "")
    note = (request.form.get("note") or "").strip()
    if stype == "weekly" and voc_type != "half":
        work_tf = work_tt = None
    db = connect()
    db.execute(
        "INSERT INTO vocational_school(user_id, schedule_type, weekday, "
        "work_time_from, work_time_to, date_from, date_to, valid_from, valid_to, note) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user_id, stype,
         int(weekday) if weekday is not None and stype == "weekly" else None,
         work_tf, work_tt, date_from, date_to, valid_from, valid_to, note)
    )
    db.commit()
    db.close()
    add_flash(t("admin.user_saved"), "success")
    return redirect(f"/admin/users/{user_id}/edit#vocational")


@vocational_bp.post("/admin/users/<int:user_id>/vocational/delete")
@admin_required
def admin_vocational_delete(user_id: int):
    from app import bootstrap
    bootstrap()
    entry_id = int(request.form.get("entry_id") or 0)
    if entry_id:
        db = connect()
        db.execute("DELETE FROM vocational_school WHERE id=? AND user_id=?", (entry_id, user_id))
        db.commit()
        db.close()
    return redirect(f"/admin/users/{user_id}/edit#vocational")
