"""
Blueprint: Abwesenheits-Genehmigungen.
"""
from flask import Blueprint, request, redirect, url_for, render_template_string, abort
from db import connect
from auth import login_required, admin_required, current_user
from translations import t

approvals_bp = Blueprint("approvals", __name__)

@approvals_bp.get("/approvals")
@login_required
def approvals_view():
    from app import bootstrap, flash_html, layout, APP_VERSION, _fmt_iso_short
    import datetime, html as _html
    bootstrap()
    u = current_user()
    if not u.get("is_approver"):
        abort(403)

    db = connect()
    try:
        pending = db.execute("""
            SELECT aa.id AS approval_id, aa.status, aa.created_at,
                   a.id AS absence_id, a.date_from, a.date_to, a.is_half_day,
                   at.name AS typ, at.color AS typ_color,
                   usr.username, usr.display_name
            FROM absence_approvals aa
            JOIN absences a ON a.id = aa.absence_id
            JOIN absence_types at ON at.id = a.type_id
            JOIN users usr ON usr.id = a.user_id
            WHERE aa.approver_id = ? AND aa.status = 'pending'
            ORDER BY aa.created_at DESC
        """, (u["id"],)).fetchall()

        history = db.execute("""
            SELECT aa.id AS approval_id, aa.status, aa.comment,
                   aa.updated_at, a.date_from, a.date_to, a.is_half_day,
                   at.name AS typ, at.color AS typ_color,
                   usr.username, usr.display_name
            FROM absence_approvals aa
            JOIN absences a ON a.id = aa.absence_id
            JOIN absence_types at ON at.id = a.type_id
            JOIN users usr ON usr.id = a.user_id
            WHERE aa.approver_id = ? AND aa.status != 'pending'
            ORDER BY aa.updated_at DESC
            LIMIT 50
        """, (u["id"],)).fetchall()
    finally:
        db.close()

    def _uname(row):
        return _html.escape(row["display_name"] or row["username"])

    def _days(row):
        try:
            d1 = datetime.date.fromisoformat(str(row["date_from"])[:10])
            d2 = datetime.date.fromisoformat(str(row["date_to"])[:10])
            return "0.5" if row["is_half_day"] else str((d2 - d1).days + 1)
        except Exception:
            return "?"

    def _typ_badge(row):
        color = _html.escape(row["typ_color"] or "#999")
        name = _html.escape(row["typ"])
        return f'<span style="display:inline-block;width:9px;height:9px;background:{color};border-radius:2px;margin-right:4px;"></span>{name}'

    reject_reason_label = t("approvals.reject_reason")
    reject_reason_req   = t("approvals.reject_reason_required")
    btn_approve  = t("btn.approve")
    btn_reject   = t("btn.reject")
    btn_cancel   = t("btn.cancel")

    pending_rows = ""
    for p in pending:
        mid = f"m{p['approval_id']}"
        pending_rows += (
            f"<tr>"
            f"<td>{_uname(p)}</td>"
            f"<td>{_typ_badge(p)}</td>"
            f"<td>{_fmt_iso_short(p['date_from'])}</td>"
            f"<td>{_fmt_iso_short(p['date_to'])}</td>"
            f"<td>{_days(p)}</td>"
            f"<td class='small'>{_fmt_iso_short(p['created_at'])}</td>"
            f"<td style='white-space:nowrap;'>"
            f"<div style='display:flex;gap:4px;flex-wrap:wrap;'>"
            f"<form method='post' action='/approvals/{p['approval_id']}/approve' style='display:contents;'>"
            f"<button class='btn btn-sm primary' type='submit'>{btn_approve}</button></form>"
            f"<button class='btn btn-sm danger' type='button' "
            f"onclick=\"document.getElementById('{mid}').style.display='table-row'\">{btn_reject}</button>"
            f"</div></td></tr>"
            f"<tr id='{mid}' style='display:none;background:var(--sf);'>"
            f"<td colspan='7' style='padding:10px;'>"
            f"<form method='post' action='/approvals/{p['approval_id']}/reject' "
            f"style='display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;'>"
            f"<div style='flex:1;min-width:200px;'>"
            f"<label style='font-size:12px;'>{reject_reason_label} *</label>"
            f"<input type='text' name='comment' required style='font-size:13px;padding:6px 10px;margin-top:4px;'></div>"
            f"<button class='btn btn-sm danger' type='submit'>{btn_reject}</button>"
            f"<button class='btn btn-sm' type='button' "
            f"onclick=\"document.getElementById('{mid}').style.display='none'\">{btn_cancel}</button>"
            f"</form></td></tr>"
        )
    if not pending_rows:
        pending_rows = f"<tr><td colspan='7' class='small' style='color:var(--mu);'>{t('approvals.no_pending')}</td></tr>"

    history_rows = ""
    for h in history:
        if h["status"] == "approved":
            st = f"<span style='color:var(--ok);font-weight:600;'>✅ {t('absence.status_approved')}</span>"
        else:
            st = f"<span style='color:var(--danger);font-weight:600;'>✗ {t('absence.status_rejected')}</span>"
        history_rows += (
            f"<tr>"
            f"<td>{_uname(h)}</td>"
            f"<td>{_typ_badge(h)}</td>"
            f"<td>{_fmt_iso_short(h['date_from'])}</td>"
            f"<td>{_fmt_iso_short(h['date_to'])}</td>"
            f"<td>{st}</td>"
            f"<td class='small'>{_fmt_iso_short(h['updated_at'])}</td>"
            f"<td class='small'>{_html.escape(h['comment'] or '')}</td>"
            f"</tr>"
        )
    if not history_rows:
        history_rows = f"<tr><td colspan='7' class='small' style='color:var(--mu);'>{t('approvals.no_history')}</td></tr>"

    col_user = t("approvals.col_user")
    col_type = t("approvals.col_type")
    col_from = t("absences.from")
    col_to   = t("absences.to")
    col_days = t("approvals.col_days")
    col_req  = t("approvals.col_requested")
    col_dec  = t("approvals.col_decided")
    col_cmt  = t("approvals.col_comment")
    pt       = t("approvals.pending_title")
    ht       = t("approvals.history_title")

    body = (
        flash_html() +
        f'<div class="card">'
        f'<h3>{pt}</h3>'
        f'<div class="table-scroll"><table>'
        f'<thead><tr><th>{col_user}</th><th>{col_type}</th><th>{col_from}</th>'
        f'<th>{col_to}</th><th>{col_days}</th><th>{col_req}</th><th></th></tr></thead>'
        f'<tbody>{pending_rows}</tbody></table></div></div>'
        f'<div class="card">'
        f'<h3>{ht}</h3>'
        f'<div class="table-scroll"><table>'
        f'<thead><tr><th>{col_user}</th><th>{col_type}</th><th>{col_from}</th>'
        f'<th>{col_to}</th><th>Status</th><th>{col_dec}</th><th>{col_cmt}</th></tr></thead>'
        f'<tbody>{history_rows}</tbody></table></div></div>'
    )
    return render_template_string(layout(pt, body, u, APP_VERSION))



@approvals_bp.post("/approvals/<int:approval_id>/approve")
@login_required
def approvals_approve(approval_id: int):
    from app import bootstrap, add_flash, _notify_absence_decision
    bootstrap()
    u = current_user()
    if not u.get("is_approver"):
        abort(403)
    db = connect()
    try:
        aa = db.execute(
            "SELECT aa.id, a.user_id, a.date_from, a.date_to, at.name AS type_name "
            "FROM absence_approvals aa "
            "JOIN absences a ON a.id = aa.absence_id "
            "JOIN absence_types at ON at.id = a.type_id "
            "WHERE aa.id=? AND aa.approver_id=? AND aa.status='pending'",
            (approval_id, u["id"]),
        ).fetchone()
        if not aa:
            abort(404)
        db.execute(
            "UPDATE absence_approvals SET status='approved', updated_at=datetime('now') WHERE id=?",
            (approval_id,),
        )
        db.commit()
        req = db.execute(
            "SELECT id, email, language FROM users WHERE id=?", (aa["user_id"],)
        ).fetchone()
    finally:
        db.close()
    if req:
        _notify_absence_decision(
            user_id=aa["user_id"], email=req["email"] or "",
            lang=req["language"] or "de",
            type_name=aa["type_name"], date_from=aa["date_from"], date_to=aa["date_to"],
            approved=True, reason="",
        )
    add_flash(t("approvals.approved_flash"), "success")
    return redirect(url_for("approvals.approvals_view"))



@approvals_bp.post("/approvals/<int:approval_id>/reject")
@login_required
def approvals_reject(approval_id: int):
    from app import bootstrap, add_flash, _notify_absence_decision
    bootstrap()
    u = current_user()
    if not u.get("is_approver"):
        abort(403)
    comment = (request.form.get("comment") or "").strip()
    if not comment:
        add_flash(t("approvals.reject_reason_required"), "error")
        return redirect(url_for("approvals.approvals_view"))
    db = connect()
    try:
        aa = db.execute(
            "SELECT aa.id, a.user_id, a.date_from, a.date_to, at.name AS type_name "
            "FROM absence_approvals aa "
            "JOIN absences a ON a.id = aa.absence_id "
            "JOIN absence_types at ON at.id = a.type_id "
            "WHERE aa.id=? AND aa.approver_id=? AND aa.status='pending'",
            (approval_id, u["id"]),
        ).fetchone()
        if not aa:
            abort(404)
        db.execute(
            "UPDATE absence_approvals SET status='rejected', comment=?, updated_at=datetime('now') WHERE id=?",
            (comment, approval_id),
        )
        db.commit()
        req = db.execute(
            "SELECT id, email, language FROM users WHERE id=?", (aa["user_id"],)
        ).fetchone()
    finally:
        db.close()
    if req:
        _notify_absence_decision(
            user_id=aa["user_id"], email=req["email"] or "",
            lang=req["language"] or "de",
            type_name=aa["type_name"], date_from=aa["date_from"], date_to=aa["date_to"],
            approved=False, reason=comment,
        )
    add_flash(t("approvals.rejected_flash"), "success")
    return redirect(url_for("approvals.approvals_view"))


