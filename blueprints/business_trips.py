"""
Blueprint: Dienstreisen.
"""
from flask import Blueprint, request, redirect, url_for
from db import connect
from auth import login_required, admin_required, current_user
from translations import t

business_trips_bp = Blueprint("business_trips", __name__)


@business_trips_bp.post("/day/<day>/business_trip/save")
@login_required
def day_business_trip_save(day: str):
    from app import bootstrap, add_flash, _is_day_locked, _parse_date_input, _before_start_date, _round_to_15
    import re
    from flask import abort
    bootstrap()
    u = current_user()
    day = str(day).strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        abort(400)
    if _is_day_locked(u["id"], day):
        add_flash(t("flash.error.period_locked"), "error")
        return redirect(f"/day/{day}")
    destination = (request.form.get("destination") or "").strip()
    if not destination:
        add_flash(t("flash.error.location_required"), "error")
        return redirect(f"/day/{day}")
    start_date = _parse_date_input(request.form.get("start_date") or day)
    if not start_date:
        add_flash(t("flash.error.invalid_start_date"), "error")
        return redirect(f"/day/{day}")
    sd_err = _before_start_date(u["id"], start_date)
    if sd_err:
        add_flash(sd_err, "error")
        return redirect(f"/day/{day}")
    end_date_raw = (request.form.get("end_date") or "").strip()
    end_date = _parse_date_input(end_date_raw) if end_date_raw else start_date
    if end_date and end_date < start_date:
        end_date = start_date
    departure_time     = _round_to_15((request.form.get("departure_time") or "").strip()) or None
    departure_end_time = _round_to_15((request.form.get("departure_end_time") or "").strip()) or None
    return_time        = _round_to_15((request.form.get("return_time") or "").strip()) or None
    return_end_time    = _round_to_15((request.form.get("return_end_time") or "").strip()) or None
    notes              = (request.form.get("notes") or "").strip() or None
    trip_id            = (request.form.get("trip_id") or "").strip() or None
    db = connect()
    if trip_id:
        db.execute(
            """UPDATE business_trips SET
                 start_date=?, end_date=?, destination=?,
                 departure_time=?, departure_end_time=?,
                 return_time=?, return_end_time=?, notes=?, updated_at=datetime('now')
               WHERE id=? AND user_id=?""",
            (start_date, end_date, destination, departure_time, departure_end_time,
             return_time, return_end_time, notes, int(trip_id), u["id"]),
        )
    else:
        db.execute(
            """INSERT INTO business_trips
                   (user_id, start_date, end_date, destination, departure_time, departure_end_time,
                    return_time, return_end_time, notes, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(user_id, start_date) DO UPDATE SET
                 end_date=excluded.end_date,
                 destination=excluded.destination,
                 departure_time=excluded.departure_time,
                 departure_end_time=excluded.departure_end_time,
                 return_time=excluded.return_time,
                 return_end_time=excluded.return_end_time,
                 notes=excluded.notes,
                 updated_at=datetime('now')""",
            (u["id"], start_date, end_date, destination, departure_time, departure_end_time,
             return_time, return_end_time, notes),
        )
    db.commit()
    db.close()
    add_flash(t("trips.saved"), "success")
    return redirect(f"/day/{day}")


@business_trips_bp.post("/day/<day>/business_trip/delete")
@login_required
def day_business_trip_delete(day: str):
    from app import bootstrap, add_flash, _is_day_locked
    bootstrap()
    u = current_user()
    day = str(day).strip()[:10]
    if _is_day_locked(u["id"], day):
        add_flash(t("flash.error.period_locked"), "error")
        return redirect(f"/day/{day}")
    trip_id = (request.form.get("trip_id") or "").strip()
    db = connect()
    if trip_id:
        db.execute("DELETE FROM business_trips WHERE id=? AND user_id=?", (int(trip_id), u["id"]))
    else:
        db.execute("DELETE FROM business_trips WHERE user_id=? AND start_date=?", (u["id"], day))
    db.commit()
    db.close()
    add_flash(t("trips.deleted"), "success")
    return redirect(f"/day/{day}")


@business_trips_bp.get("/business_trips")
@login_required
def business_trips_list():
    from app import bootstrap, layout, flash_html, FORM_ASSETS_JS, _date_input, _time_input, _get_tracking_start, _fmt_date_de, _timepicker_datalist, APP_VERSION
    from flask import render_template_string
    import datetime
    bootstrap()
    u = current_user()
    if u and u.get("admin_only"):
        return redirect("/admin")
    today = datetime.date.today()
    year = int(request.args.get("y") or today.year)
    show_form = request.args.get("new") == "1"
    user_start = _get_tracking_start(u["id"])
    _trip_from = f"{year}-01-01"
    if user_start:
        _trip_from = max(_trip_from, user_start)

    db = connect()
    trips = db.execute(
        "SELECT * FROM business_trips WHERE user_id=? AND start_date BETWEEN ? AND ? ORDER BY start_date DESC",
        (u["id"], _trip_from, f"{year}-12-31"),
    ).fetchall()
    db.close()

    prev_year = year - 1
    next_year = year + 1
    _prev_year_blocked = bool(user_start and f"{prev_year}-12-31" < user_start)

    def fmt_time(v):
        return v if v else "–"

    def fmt_date_range(t):
        s = str(t["start_date"])[:10]
        e = str(t["end_date"] or s)[:10]
        sy = _fmt_date_de(s, omit_year=(int(s[:4]) == year))
        if s == e:
            return sy
        ey = _fmt_date_de(e, omit_year=(int(e[:4]) == year))
        return f"{sy} – {ey}"

    _lbl_edit = t('btn.edit')
    _lbl_del = t('btn.delete')
    _confirm_del = t('trips.confirm_delete')
    _no_trips = t('trips.no_entries')
    rows_html = ""
    if trips:
        for trip in trips:
            dest = trip['destination'] or ''
            notes = trip['notes'] or ''
            rows_html += (
                f"<tr>"
                f"<td style='white-space:nowrap;'>{fmt_date_range(trip)}</td>"
                f"<td style='max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'><b title='{dest}'>{dest}</b></td>"
                f"<td style='white-space:nowrap;'>{fmt_time(trip['departure_time'])}</td>"
                f"<td style='white-space:nowrap;'>{fmt_time(trip['departure_end_time'])}</td>"
                f"<td style='white-space:nowrap;'>{fmt_time(trip['return_time'])}</td>"
                f"<td style='white-space:nowrap;'>{fmt_time(trip['return_end_time'])}</td>"
                f"<td class='small' style='max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' title='{notes}'>{notes}</td>"
                f"<td style='white-space:nowrap;'>"
                f"<div style='display:flex;gap:6px;'>"
                f"<a class='btn btn-sm' href='/day/{trip['start_date']}'>{_lbl_edit}</a>"
                f"<form method='post' action='/business_trips/delete' style='display:contents;'"
                f" onsubmit=\"return confirm('{_confirm_del}');\">"
                f"<input type='hidden' name='trip_id' value='{trip['id']}'>"
                f"<input type='hidden' name='y' value='{year}'>"
                f"<button class='btn danger btn-sm' type='submit'>{_lbl_del}</button></form>"
                f"</div></td>"
                f"</tr>"
            )
    else:
        rows_html = f"<tr><td colspan='8' class='small' style='color:var(--mu);'>{_no_trips}</td></tr>"

    new_form_html = ""
    if show_form:
        new_form_html = f"""
        <div class="card" style="margin-top:12px;">
          <h3 style="margin-top:0;">+ {t('trips.new')}</h3>
          {FORM_ASSETS_JS}
          <form method="post" action="/business_trips/add">
            <input type="hidden" name="y" value="{year}">
            <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;align-items:flex-end;">
              <div>
                <label>{t('trips.location')} *</label><br>
                <input name="destination" required placeholder="{t('trips.destination')}" style="max-width:280px;">
              </div>
              <div>
                <label>{t('trips.date_from')} *</label><br>
                {_date_input("start_date", today.isoformat(), required=True)}
              </div>
              <div>
                <label style="font-weight:400;"><input type="checkbox" onchange="toggleMultiday(this)"> {t('trips.multiday')}</label>
              </div>
            </div>
            <div class="multiday-fields" style="display:none;margin-bottom:8px;">
              <label>{t('trips.date_to')}</label><br>
              {_date_input("end_date")}
            </div>
            <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;">
              <div><label>{t('trips.departure')}</label><br>{_time_input("departure_time")}</div>
              <div><label>{t('trips.arrival_dest')}</label><br>{_time_input("departure_end_time")}</div>
              <div><label>{t('trips.return_start')}</label><br>{_time_input("return_time")}</div>
              <div><label>{t('trips.arrival_home')}</label><br>{_time_input("return_end_time")}</div>
            </div>
            <div style="margin-bottom:8px;">
              <label>{t('trips.notes')}</label><br>
              <textarea name="notes" rows="2" placeholder="optional" style="max-width:500px;"></textarea>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary" type="submit">{t('btn.save')}</button>
              <a class="btn" href="/business_trips?y={year}">{t('btn.cancel')}</a>
            </div>
          </form>
        </div>"""

    body = f"""
    {_timepicker_datalist('time_suggestions')}
    {flash_html()}
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <h3 style="margin:0;">✈ {t('nav.trips')} – {year}</h3>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          {"<span class='btn' style='opacity:.35;cursor:not-allowed;'>◀︎ " + str(prev_year) + "</span>" if _prev_year_blocked else f"<a class='btn' href='/business_trips?y={prev_year}'>◀︎ {prev_year}</a>"}
          <a class="btn" href="/business_trips?y={today.year}">{t('common.today')}</a>
          <a class="btn" href="/business_trips?y={next_year}">{next_year} ▶︎</a>
          <a class="btn primary btn-sm" href="/business_trips?y={year}&new=1">{t('btn.new')}</a>
        </div>
      </div>
      <div class="table-scroll" style="margin-top:10px;">
        <table style="min-width:600px;">
          <thead>
            <tr>
              <th>{t('common.date')}</th><th>{t('trips.location')}</th>
              <th>{t('trips.departure')}</th><th>{t('trips.arrival_dest')}</th>
              <th>{t('trips.return_start')}</th><th>{t('trips.arrival_home')}</th>
              <th>{t('trips.notes')}</th><th></th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
      </div>
    </div>
    {new_form_html}
    """
    return render_template_string(layout(t("trips.title"), body, u, APP_VERSION))


@business_trips_bp.post("/business_trips/add")
@login_required
def business_trips_add():
    from app import bootstrap, add_flash, _parse_date_input, _is_range_locked, _before_start_date, _round_to_15
    import datetime
    bootstrap()
    u = current_user()
    year = (request.form.get("y") or str(datetime.date.today().year)).strip()
    destination = (request.form.get("destination") or "").strip()
    if not destination:
        add_flash(t("flash.error.location_required"), "error")
        return redirect(f"/business_trips?y={year}&new=1")
    start_date = _parse_date_input(request.form.get("start_date") or "")
    if not start_date:
        add_flash(t("flash.error.invalid_start_date"), "error")
        return redirect(f"/business_trips?y={year}&new=1")
    end_date_raw = (request.form.get("end_date") or "").strip()
    end_date = _parse_date_input(end_date_raw) if end_date_raw else start_date
    if end_date and end_date < start_date:
        end_date = start_date
    if _is_range_locked(u["id"], start_date, end_date or start_date):
        add_flash(t("flash.error.period_locked"), "error")
        return redirect(f"/business_trips?y={year}&new=1")
    sd_err = _before_start_date(u["id"], start_date)
    if sd_err:
        add_flash(sd_err, "error")
        return redirect(f"/business_trips?y={year}&new=1")
    departure_time     = _round_to_15((request.form.get("departure_time") or "").strip()) or None
    departure_end_time = _round_to_15((request.form.get("departure_end_time") or "").strip()) or None
    return_time        = _round_to_15((request.form.get("return_time") or "").strip()) or None
    return_end_time    = _round_to_15((request.form.get("return_end_time") or "").strip()) or None
    notes              = (request.form.get("notes") or "").strip() or None
    db = connect()
    db.execute(
        """INSERT INTO business_trips
               (user_id, start_date, end_date, destination, departure_time, departure_end_time,
                return_time, return_end_time, notes, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))
           ON CONFLICT(user_id, start_date) DO UPDATE SET
             end_date=excluded.end_date,
             destination=excluded.destination,
             departure_time=excluded.departure_time,
             departure_end_time=excluded.departure_end_time,
             return_time=excluded.return_time,
             return_end_time=excluded.return_end_time,
             notes=excluded.notes,
             updated_at=datetime('now')""",
        (u["id"], start_date, end_date, destination, departure_time, departure_end_time,
         return_time, return_end_time, notes),
    )
    db.commit()
    db.close()
    add_flash(t("trips.saved"), "success")
    return redirect(f"/business_trips?y={year}")


@business_trips_bp.post("/business_trips/delete")
@login_required
def business_trips_delete():
    from app import bootstrap, add_flash, _is_range_locked
    import datetime
    bootstrap()
    u = current_user()
    trip_id = (request.form.get("trip_id") or "").strip()
    year = (request.form.get("y") or str(datetime.date.today().year)).strip()
    if trip_id:
        db = connect()
        trip = db.execute(
            "SELECT start_date, end_date FROM business_trips WHERE id=? AND user_id=?",
            (int(trip_id), u["id"]),
        ).fetchone()
        if trip and _is_range_locked(u["id"], trip["start_date"], trip["end_date"] or trip["start_date"]):
            db.close()
            add_flash(t("flash.error.period_locked"), "error")
            return redirect(f"/business_trips?y={year}")
        db.execute("DELETE FROM business_trips WHERE id=? AND user_id=?", (int(trip_id), u["id"]))
        db.commit()
        db.close()
        add_flash(t("trips.deleted"), "success")
    return redirect(f"/business_trips?y={year}")
