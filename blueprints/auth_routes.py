"""
Blueprint: Login, Logout, 2FA, Passwort-Änderung.
"""
from flask import Blueprint, request, redirect, url_for, session, render_template_string
from db import connect
from auth import current_user, login_required
from translations import t

auth_routes_bp = Blueprint("auth_routes", __name__)


@auth_routes_bp.get("/login")
def login():
    from app import bootstrap, flash_html, layout, APP_VERSION, _get_app_config
    from auth import has_users
    bootstrap()
    if not has_users():
        return redirect(url_for("core.setup"))
    _login_lang = _get_app_config().get("default_language") or "de"
    nxt = request.args.get("next") or "/"
    body = f'''
    {flash_html()}
    <div class="card">
      <h3>{t("login.title", _login_lang)}</h3>
      <form method="post" action="/login" id="login-form" autocomplete="on">
        <input type="hidden" name="next" value="{nxt}">
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          <div><label>{t("login.username", _login_lang)}</label><br>
            <input type="text" name="username" id="login-user" required autocomplete="username"
                   oninput="loginLockCheck()"></div>
          <div><label>{t("login.password", _login_lang)}</label><br>
            <input type="password" name="password" required autocomplete="current-password"></div>
        </div><br>
        <button class="btn" type="submit">{t("login.submit", _login_lang)}</button>
      </form>
    </div>
    '''
    return render_template_string(layout("Login", body, None, APP_VERSION))


@auth_routes_bp.post("/login")
def login_post():
    from app import bootstrap, add_flash, _get_app_config, _get_timezone
    from auth import authenticate, get_lockout_until, get_totp_row
    bootstrap()
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    nxt = request.form.get("next") or "/"
    _login_lang = _get_app_config().get("default_language") or "de"

    # Try to get user language for auth messages before authentication
    _user_lang = _login_lang
    try:
        _uldb = connect()
        _ulrow = _uldb.execute(
            "SELECT language FROM users WHERE LOWER(username)=?", (username.lower(),)
        ).fetchone()
        _uldb.close()
        if _ulrow and _ulrow["language"]:
            _user_lang = _ulrow["language"]
    except Exception:
        pass

    u, err = authenticate(username, password)
    if err == "locked":
        locked_until = get_lockout_until(username)
        if locked_until:
            local_until = locked_until.astimezone(_get_timezone())
            until_str = local_until.strftime("%H:%M")
            add_flash(t("auth.account_locked", _user_lang).replace("{time}", until_str), "error")
        else:
            add_flash(t("auth.account_locked_no_email", _user_lang), "error")
        return redirect(url_for("auth_routes.login", next=nxt))
    if err or not u:
        add_flash(t("login.failed"), "error")
        return redirect(url_for("auth_routes.login", next=nxt))

    # Set language from user preference
    from db import connect as _db_connect
    _ldb = _db_connect()
    _lrow = _ldb.execute("SELECT language FROM users WHERE id=?", (u["id"],)).fetchone()
    _ldb.close()
    _lang = (_lrow["language"] if _lrow and _lrow["language"] else "de") or "de"

    # 2FA check
    totp_row = get_totp_row(u["id"])
    if totp_row.get("totp_enabled"):
        session.clear()
        session["awaiting_2fa"] = True
        session["pre_2fa_user_id"] = u["id"]
        session["pre_2fa_lang"] = _lang
        session["pre_2fa_next"] = nxt
        return redirect(url_for("auth_routes.login_2fa"))

    session.permanent = True
    session["user_id"] = u["id"]
    session["lang"] = _lang
    return redirect(nxt)


@auth_routes_bp.get("/login/2fa")
def login_2fa():
    from app import bootstrap, flash_html, layout, APP_VERSION
    bootstrap()
    if not session.get("awaiting_2fa"):
        return redirect(url_for("auth_routes.login"))
    _lang = session.get("pre_2fa_lang") or "de"
    body = f"""
    {flash_html()}
    <div class="card" style="max-width:400px;">
      <h3>&#128274; {t("settings.two_factor", _lang)}</h3>
      <p class="small" style="margin-bottom:14px;">{t("auth.enter_totp_hint", _lang)}</p>
      <form method="post" action="/login/2fa">
        <div style="margin-bottom:10px;">
          <label>{t("auth.totp_code", _lang)}</label>
          <input type="text" name="code" inputmode="numeric" autocomplete="one-time-code"
                 maxlength="8" style="font-size:18px;letter-spacing:4px;width:140px;" required autofocus>
        </div>
        <button class="btn primary" type="submit">{t("login.submit", _lang)}</button>
        <a class="btn" href="/login" style="margin-left:8px;">{t("btn.cancel", _lang)}</a>
      </form>
    </div>
    """
    return render_template_string(layout("2FA", body, None, APP_VERSION))


@auth_routes_bp.post("/login/2fa")
def login_2fa_post():
    from app import bootstrap, add_flash, _verify_totp, _check_backup_code
    from auth import get_totp_row, update_totp_backup_codes
    bootstrap()
    if not session.get("awaiting_2fa"):
        return redirect(url_for("auth_routes.login"))
    user_id = session.get("pre_2fa_user_id")
    _lang = session.get("pre_2fa_lang") or "de"
    nxt = session.get("pre_2fa_next") or "/"
    if not user_id:
        session.clear()
        return redirect(url_for("auth_routes.login"))

    code = (request.form.get("code") or "").strip()
    totp_row = get_totp_row(user_id)

    valid = False
    if totp_row.get("totp_secret"):
        valid = _verify_totp(totp_row["totp_secret"], code)
    if not valid and totp_row.get("totp_backup_codes"):
        ok, updated_codes = _check_backup_code(totp_row["totp_backup_codes"], code)
        if ok:
            import json as _j
            update_totp_backup_codes(user_id, updated_codes)
            valid = True

    if not valid:
        add_flash(t("auth.totp_invalid", _lang), "error")
        return redirect(url_for("auth_routes.login_2fa"))

    from db import connect as _db_connect
    _ldb = _db_connect()
    _lrow = _ldb.execute("SELECT language FROM users WHERE id=?", (user_id,)).fetchone()
    _ldb.close()
    _final_lang = (_lrow["language"] if _lrow and _lrow["language"] else "de") or "de"

    session.clear()
    session.permanent = True
    session["user_id"] = user_id
    session["lang"] = _final_lang
    return redirect(nxt)


@auth_routes_bp.get("/login/unlock/<token>")
def login_unlock(token: str):
    from app import bootstrap, add_flash, _get_app_config
    from auth import validate_unlock_token, unlock_account
    bootstrap()
    _login_lang = _get_app_config().get("default_language") or "de"
    row = validate_unlock_token(token)
    if not row:
        add_flash(t("auth.unlock_invalid", _login_lang), "error")
        return redirect(url_for("auth_routes.login"))
    unlock_account(row["id"])
    add_flash(t("auth.unlocked", _login_lang), "success")
    return redirect(url_for("auth_routes.login"))


@auth_routes_bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth_routes.login"))


@auth_routes_bp.get("/change-password")
@login_required
def change_password():
    from app import bootstrap, flash_html, layout, APP_VERSION, _PW_STRENGTH_JS
    import html as _html
    bootstrap()
    u = current_user()
    uname = _html.escape(u.get("username") or "")
    not_compliant = not u.get("password_compliant") and not u.get("must_change_password")
    hint = ""
    if not_compliant:
        hint = f'<div style="background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:13px;color:#92400e;">{t("settings.password_compliant_hint")}</div>'
    body = f"""
    {flash_html()}
    <div class="card" style="max-width:420px;">
      <h3>{t("change_pw.title")}</h3>
      {hint}
      <p class="small" style="margin-bottom:14px;">{t("change_pw.info")}</p>
      <form method="post" action="/change-password">
        <div style="margin-bottom:10px;">
          <label>{t("change_pw.new")}</label>
          <input type="password" name="new_password" id="cpw-inp" required autocomplete="new-password"
                 oninput="_pwUpdate('cpw-inp','cpw-chk','{uname}')">
          <div id="cpw-chk" style="margin-top:6px;padding:8px;background:var(--sf);border-radius:var(--rs);border:1px solid var(--bd);line-height:1.7;"></div>
        </div>
        <div style="margin-bottom:14px;">
          <label>{t("change_pw.confirm")}</label>
          <input type="password" name="new_password_confirm" required autocomplete="new-password">
        </div>
        <button class="btn primary" type="submit">{t("change_pw.submit")}</button>
      </form>
    </div>
    {_PW_STRENGTH_JS}
    """
    return render_template_string(layout(t("change_pw.title"), body, u, APP_VERSION, show_back=False))


@auth_routes_bp.post("/change-password")
@login_required
def change_password_post():
    from app import bootstrap, add_flash
    from auth import validate_password, set_password
    bootstrap()
    u = current_user()
    new_password = (request.form.get("new_password") or "").strip()
    new_password_confirm = (request.form.get("new_password_confirm") or "").strip()

    errs = validate_password(new_password, u.get("username") or "")
    if errs:
        add_flash(t("flash.error.password_invalid").format(errors="; ".join(errs)), "error")
        return redirect("/change-password")

    if new_password != new_password_confirm:
        add_flash(t("settings.password_mismatch"), "error")
        return redirect("/change-password")

    set_password(u["id"], new_password)
    add_flash(t("settings.password_saved"), "success")
    if not u.get("onboarding_done"):
        return redirect("/onboarding?step=2")
    return redirect("/")
