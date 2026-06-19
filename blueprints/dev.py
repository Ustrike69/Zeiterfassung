"""
Blueprint: Entwickler-Hilfsmittel (nur sysadmin).
"""
from flask import Blueprint, request, redirect, url_for, session, render_template_string, abort
from db import connect
from auth import current_user

dev_bp = Blueprint("dev", __name__)

@dev_bp.get("/dev/users")
def dev_users():
    from app import IS_DEV, layout, APP_VERSION
    if not IS_DEV:
        abort(404)
    u = current_user()
    db = connect()
    users = db.execute(
        "SELECT id, username, display_name, admin_role, is_approver "
        "FROM users WHERE is_active=1 ORDER BY username"
    ).fetchall()
    db.close()
    rows = "".join(
        f'<tr>'
        f'<td>{usr["id"]}</td>'
        f'<td><strong>{usr["username"]}</strong>'
        f'{" · " + usr["display_name"] if usr["display_name"] else ""}</td>'
        f'<td>{"🔧 " + usr["admin_role"] if usr["admin_role"] else "–"}</td>'
        f'<td><a href="/dev/su/{usr["id"]}" class="btn btn-primary btn-sm">'
        f'Einloggen</a></td>'
        f'</tr>'
        for usr in users
    )
    body = f"""
    <div style="max-width:600px;margin:2rem auto">
      <div style="background:#dc2626;color:#fff;padding:12px 16px;
                  border-radius:8px;margin-bottom:1.5rem;font-weight:600">
        &#9888;&#65039; DEV MODE — Nur auf Entwicklungsumgebung!
      </div>
      <h2 style="margin-bottom:1rem">User wechseln</h2>
      <table class="table" style="width:100%">
        <thead>
          <tr>
            <th>ID</th>
            <th>Username</th>
            <th>Rolle</th>
            <th>Aktion</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """
    return render_template_string(layout(
        t('dev.users_title'),
        body, u, APP_VERSION
    ))



@dev_bp.get("/dev/su/<int:uid>")
def dev_su(uid):
    from app import IS_DEV
    if not IS_DEV:
        abort(404)
    db = connect()
    u = db.execute(
        "SELECT id FROM users WHERE id=? AND is_active=1", (uid,)
    ).fetchone()
    db.close()
    if not u:
        abort(404)
    session.permanent = True
    session["user_id"] = uid
    session.modified = True
    return redirect("/")



@dev_bp.get("/dev/su/stop")
def dev_su_stop():
    from app import IS_DEV
    if not IS_DEV:
        abort(404)
    session.clear()
    return redirect("/dev/users")


if __name__ == "__main__":
    app.run(debug=True)