"""
Blueprint: Schulferien-Verwaltung (POST-Routen).

add_flash und bootstrap werden lokal in jeder Route importiert, um den
zirkulären Import (app.py → blueprint → app.py) zu vermeiden. Der lokale
Import greift erst beim ersten Aufruf, wenn app.py vollständig geladen ist.
"""
import datetime

from flask import Blueprint, request, redirect
from db import connect
from auth import sysadmin_required
from translations import t

school_holidays_bp = Blueprint("school_holidays", __name__)


@school_holidays_bp.post("/admin/school-holidays/fetch")
@sysadmin_required
def admin_school_holidays_fetch():
    from app import add_flash, bootstrap
    import urllib.request as _ur
    import json as _json
    bootstrap()
    state_code = (request.form.get("state_code") or "").strip().upper()
    try:
        year = int(request.form.get("year") or datetime.date.today().year)
    except ValueError:
        year = datetime.date.today().year
    replace = request.form.get("replace") == "1"

    if not state_code or len(state_code) > 4:
        add_flash("Ungültiger Bundesland-Code.", "error")
        return redirect("/admin#acc-schoolhols")

    region = f"DE-{state_code}"

    try:
        url = f"https://ferien-api.de/api/v1/holidays/{state_code}/{year}"
        req = _ur.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Zeiterfassung)",
            "Accept": "application/json",
        })
        with _ur.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
    except Exception as e:
        add_flash(f"API-Fehler: {e}", "error")
        return redirect("/admin#acc-schoolhols")

    db = connect()
    if replace:
        db.execute(
            "DELETE FROM school_holidays WHERE region=? AND date_from LIKE ?",
            (region, f"{year}%")
        )
    imported = 0
    for item in data:
        try:
            name = item.get("name") or item.get("slug") or "Ferien"
            start = str(item.get("start") or "")[:10]
            end_raw = str(item.get("end") or "")[:10]
            if not start or not end_raw:
                continue
            # ferien-api: end is exclusive → subtract 1 day
            end_dt = datetime.date.fromisoformat(end_raw) - datetime.timedelta(days=1)
            start_dt = datetime.date.fromisoformat(start)
            if end_dt < start_dt:
                end_dt = start_dt
            end = end_dt.isoformat()
            db.execute(
                "INSERT INTO school_holidays(region, name, date_from, date_to) VALUES(?,?,?,?)",
                (region, name, start, end)
            )
            imported += 1
        except Exception:
            continue
    db.commit()
    db.close()
    add_flash(f"{imported} Schulferien-Einträge für {region} {year} importiert.", "success")
    return redirect("/admin#acc-schoolhols")


@school_holidays_bp.post("/admin/school-holidays/add")
@sysadmin_required
def admin_school_holidays_add():
    from app import add_flash, bootstrap
    bootstrap()
    region    = (request.form.get("region") or "").strip()
    name      = (request.form.get("name") or "").strip()
    date_from = (request.form.get("date_from") or "").strip()
    date_to   = (request.form.get("date_to") or "").strip()
    if region and name and date_from and date_to:
        db = connect()
        db.execute(
            "INSERT INTO school_holidays(region, name, date_from, date_to) VALUES(?,?,?,?)",
            (region, name, date_from, date_to)
        )
        db.commit()
        db.close()
        add_flash(t("admin.user_saved"), "success")
    return redirect("/admin#acc-schoolhols")


@school_holidays_bp.post("/admin/school-holidays/delete")
@sysadmin_required
def admin_school_holidays_delete():
    from app import bootstrap
    bootstrap()
    entry_id = int(request.form.get("entry_id") or 0)
    if entry_id:
        db = connect()
        db.execute("DELETE FROM school_holidays WHERE id=?", (entry_id,))
        db.commit()
        db.close()
    return redirect("/admin#acc-schoolhols")


@school_holidays_bp.post("/admin/school-holidays/clear")
@sysadmin_required
def admin_school_holidays_clear():
    from app import add_flash, bootstrap
    bootstrap()
    region = (request.form.get("region") or "").strip()
    if region:
        db = connect()
        db.execute("DELETE FROM school_holidays WHERE region=?", (region,))
        db.commit()
        db.close()
        add_flash(f"Alle Schulferien für {region} gelöscht.", "success")
    return redirect("/admin#acc-schoolhols")
