"""
Blueprint: API-Endpunkte.
"""
from flask import Blueprint, request, jsonify
from db import connect
from auth import login_required, current_user
from translations import t

api_bp = Blueprint("api", __name__)


@api_bp.post("/api/contour")
@login_required
def api_contour():
    import re
    from flask import jsonify
    from app import _get_contouring_info
    u = current_user()
    ci = _get_contouring_info(u["id"])
    if not ci["enabled"]:
        return jsonify({"ok": False, "error": "Kontierung ist für diesen Account deaktiviert"}), 403
    data = request.get_json(force=True) or {}
    day = str(data.get("day") or "").strip()[:10]
    action = str(data.get("action") or "mark")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        return jsonify({"ok": False, "error": "Ungültiges Datum"}), 400
    if ci["start_date"] and day < ci["start_date"]:
        return jsonify({"ok": False, "error": "Tag liegt vor dem Kontierungsstartdatum"}), 400
    db = connect()
    try:
        if action == "mark":
            # Nur kontieren wenn Zeiteintrag oder Abwesenheit vorhanden
            has_block = db.execute(
                "SELECT 1 FROM time_blocks WHERE user_id=? AND day=? LIMIT 1", (u["id"], day)
            ).fetchone()
            has_absence = db.execute(
                "SELECT 1 FROM absences WHERE user_id=? AND date_from<=? AND date_to>=? LIMIT 1",
                (u["id"], day, day)
            ).fetchone()
            if not has_block and not has_absence:
                return jsonify({"ok": False, "error": "Kein Eintrag für diesen Tag"}), 400
            db.execute(
                "INSERT OR IGNORE INTO contoured_days(user_id, day) VALUES(?,?)",
                (u["id"], day),
            )
        else:
            db.execute("DELETE FROM contoured_days WHERE user_id=? AND day=?", (u["id"], day))
        db.commit()
    finally:
        db.close()
    return jsonify({"ok": True})




@api_bp.post("/api/contour-until")
@login_required
def api_contour_until():
    import re
    import datetime
    from flask import jsonify
    from app import _get_contouring_info, _days_with_any_entry
    u = current_user()
    ci = _get_contouring_info(u["id"])
    if not ci["enabled"]:
        return jsonify({"ok": False, "error": "Kontierung ist für diesen Account deaktiviert"}), 403
    data = request.get_json(force=True) or {}
    until = str(data.get("until") or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", until):
        return jsonify({"ok": False, "error": "Ungültiges Datum"}), 400
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    until = min(until, yesterday)

    db = connect()
    try:
        r = db.execute("SELECT tracking_start_date FROM users WHERE id=?", (u["id"],)).fetchone()
        tracking_start = r["tracking_start_date"] if r else None
    finally:
        db.close()

    year_start = f"{datetime.date.today().year}-01-01"
    if tracking_start:
        year_start = max(year_start, tracking_start)
    if ci["start_date"]:
        year_start = max(year_start, ci["start_date"])

    if until < year_start:
        return jsonify({"ok": True, "marked": 0})

    # Validate: until must not be before the user's first time_block entry
    db_check = connect()
    try:
        fb = db_check.execute(
            "SELECT MIN(day) AS d FROM time_blocks WHERE user_id=?", (u["id"],)
        ).fetchone()
        first_entry = str(fb["d"])[:10] if fb and fb["d"] else None
    finally:
        db_check.close()
    if first_entry and until < first_entry:
        return jsonify({"ok": False, "error": "Datum liegt vor dem ersten Eintrag"}), 400

    days_with = _days_with_any_entry(u["id"], year_start, until)
    db = connect()
    try:
        count = 0
        for iso in days_with:
            if year_start <= iso <= until:
                db.execute(
                    "INSERT OR IGNORE INTO contoured_days(user_id, day) VALUES(?,?)",
                    (u["id"], iso),
                )
                count += 1
        db.commit()
    finally:
        db.close()
    return jsonify({"ok": True, "marked": count})




@api_bp.get("/api/contoured-days")
@login_required
def api_contoured_days_route():
    import datetime
    from flask import jsonify
    from app import _get_contouring_info, _get_contoured_days, _get_max_contoured_day
    u = current_user()
    ci = _get_contouring_info(u["id"])
    if not ci["enabled"]:
        return jsonify({"ok": False, "error": "Kontierung ist für diesen Account deaktiviert"}), 403
    year = int(request.args.get("year") or datetime.date.today().year)
    start_iso = f"{year}-01-01"
    end_iso = f"{year}-12-31"
    days = sorted(_get_contoured_days(u["id"], start_iso, end_iso))
    max_day = _get_max_contoured_day(u["id"])
    return jsonify({"days": days, "max_day": max_day})




@api_bp.post("/api/set-exception")
@login_required
def api_set_exception():
    import re
    from app import bootstrap, add_flash, _set_weekend_exception
    bootstrap()
    u = current_user()
    day = (request.form.get("day") or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        add_flash(t("flash.error.invalid_date"), "error")
        return redirect("/calendar")
    note = (request.form.get("note") or "").strip()[:200]
    _set_weekend_exception(u["id"], day, note)
    add_flash(t("flash.success.exception_added").format(day=day), "success")
    return redirect(f"/day/{day}")




@api_bp.post("/api/remove-exception")
@login_required
def api_remove_exception():
    import re
    from app import bootstrap, add_flash, _remove_weekend_exception
    bootstrap()
    u = current_user()
    day = (request.form.get("day") or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        add_flash(t("flash.error.invalid_date"), "error")
        return redirect("/calendar")
    _remove_weekend_exception(u["id"], day)
    add_flash(t("flash.success.exception_removed").format(day=day), "success")
    return redirect(f"/day/{day}")


