"""
Blueprint: Kern-Routen (Index, Setup, Onboarding, Help, Manifest).
"""
from flask import Blueprint, request, redirect, url_for, session, render_template_string, jsonify, abort
from db import connect
from auth import login_required, current_user
from translations import t

core_bp = Blueprint("core", __name__)



@core_bp.get("/manifest.json")
def manifest():
    return jsonify({
        "name": "Zeiterfassung",
        "short_name": "Zeiterfassung",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1a1f2e",
        "theme_color": "#1a1f2e",
    })


@core_bp.get("/setup")
def setup():
    from app import bootstrap, flash_html, FORM_ASSETS_JS, layout, APP_VERSION, _timezone_select, _COMMON_TIMEZONES
    from auth import has_users
    from translations import _available_languages
    bootstrap()
    if has_users():
        return redirect(url_for("auth_routes.login"))
    # Allow language selection via query param before account is created
    setup_lang = (request.args.get("lang") or "en").strip()
    if setup_lang not in [code for code, _ in _available_languages()]:
        setup_lang = "en"
    lang_options = "".join(
        f'<option value="{code}" {"selected" if code == setup_lang else ""}>{label}</option>'
        for code, label in _available_languages()
    )
    body = f'''
    {flash_html()}
    {FORM_ASSETS_JS}

    <div class="card">
      <h3>{t("setup.title", setup_lang)}</h3>
      <form method="post" action="/setup" style="display:flex;flex-direction:column;gap:12px;max-width:400px;">
        <input type="hidden" name="lang" value="{setup_lang}">
        <div>
          <label>{t("setup.language_label", setup_lang)}</label>
          <select name="language_select" onchange="window.location.href='/setup?lang='+this.value">
            {lang_options}
          </select>
        </div>
        <div>
          <label>{t("setup.timezone", setup_lang)}</label>
          {_timezone_select("timezone", "Europe/Berlin")}
        </div>
        <div><label>{t("setup.username_label", setup_lang)}</label><input name="username" required></div>
        <div><label>{t("setup.password_label", setup_lang)}</label><input type="password" name="password" required autocomplete="new-password"></div>
        <div style="border:1px solid var(--bd);border-radius:var(--rs);padding:12px;">
          <div style="font-size:14px;font-weight:600;margin-bottom:8px;">{t("setup.usage_label", setup_lang)}</div>
          <label style="font-weight:400;display:flex;align-items:flex-start;gap:8px;margin-bottom:8px;">
            <input type="radio" name="admin_only" value="0" checked style="margin-top:3px;width:auto;">
            <span><b>{t("setup.usage_yes", setup_lang)}</b></span>
          </label>
          <label style="font-weight:400;display:flex;align-items:flex-start;gap:8px;">
            <input type="radio" name="admin_only" value="1" style="margin-top:3px;width:auto;">
            <span><b>{t("setup.usage_no", setup_lang)}</b></span>
          </label>
        </div>
        <div><button class="btn primary" type="submit">{t("setup.submit", setup_lang)}</button></div>
      </form>
    </div>
    '''
    return render_template_string(layout("Setup", body, None, APP_VERSION))



@core_bp.post("/setup")
def setup_post():
    from app import bootstrap, add_flash, layout, APP_VERSION, _COMMON_TIMEZONES
    from auth import has_users, create_user
    from translations import _available_languages
    bootstrap()
    if has_users():
        return redirect(url_for("auth_routes.login"))
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    chosen_lang = (request.form.get("lang") or "en").strip()
    if chosen_lang not in [code for code, _ in _available_languages()]:
        chosen_lang = "en"
    chosen_tz = (request.form.get("timezone") or "Europe/Berlin").strip()
    if chosen_tz not in [v for v, _ in _COMMON_TIMEZONES]:
        chosen_tz = "Europe/Berlin"
    if not username or not password:
        add_flash(t("flash.error.credentials_required"), "error")
        return redirect(url_for("setup", lang=chosen_lang))
    admin_only_val = 1 if (request.form.get("admin_only") or "0") == "1" else 0
    new_id = create_user(username, password, is_admin=True, is_active=True, onboarding_done=1)
    db = connect()
    db.execute(
        "UPDATE users SET admin_role='sysadmin', admin_only=?, language=?, updated_at=datetime('now') WHERE id=?",
        (admin_only_val, chosen_lang, new_id),
    )
    # Save default language and timezone to app_config
    db.execute(
        "INSERT OR REPLACE INTO app_config(key, value, updated_at) VALUES('default_language', ?, datetime('now'))",
        (chosen_lang,),
    )
    db.execute(
        "INSERT OR REPLACE INTO app_config(key, value, updated_at) VALUES('timezone', ?, datetime('now'))",
        (chosen_tz,),
    )
    db.commit()
    db.close()
    add_flash(t("setup.created", chosen_lang), "success")
    return redirect(url_for("auth_routes.login"))


@core_bp.get("/login")



@core_bp.get("/onboarding")
@login_required
def onboarding():
    from app import bootstrap, flash_html, FORM_ASSETS_JS, layout, APP_VERSION, _date_input, _PW_STRENGTH_JS, _get_user_schedule_current, _get_user_schedule_for_day, _fmt_minutes, _vacation_calc, _get_start_balance_minutes, _fmt_minutes_signed, _sched_daily_blocks_html, _fmt_date_de, _get_tracking_start
    from auth import is_sysadmin as _is_sysadmin_ob
    import datetime
    bootstrap()
    u = current_user()
    if u.get("onboarding_done"):
        return redirect(url_for("core.index"))

    _is_ob_sysadm = _is_sysadmin_ob(u)
    try:
        step = int(request.args.get("step") if "step" in request.args else (-1))
    except (ValueError, TypeError):
        step = -1
    if step == -1:
        step = 0 if _is_ob_sysadm else 1
    step = max(0 if _is_ob_sysadm else 1, min(6, step))

    today = datetime.date.today()
    indicator = _onboarding_step_indicator(step, show_step0=_is_ob_sysadm)

    if step == 0 and _is_ob_sysadm:
        cur_ao = 1 if u.get("admin_only") else 0
        body = f"""
        {flash_html()}
        {indicator}
        <div class="card">
          <h3>Schritt 0 – Nutzungsart</h3>
          <p class="small">Wie wirst du dieses System nutzen? Die Einstellung kann später unter <b>Einstellungen → Persönliche Einstellungen</b> geändert werden.</p>
          <form method="post" action="/onboarding?step=0" style="display:flex;flex-direction:column;gap:12px;max-width:420px;margin-top:14px;">
            <label style="font-weight:400;display:flex;align-items:flex-start;gap:10px;padding:12px;border:1px solid var(--bd);border-radius:var(--rs);cursor:pointer;">
              <input type="radio" name="admin_only" value="0" {"checked" if cur_ao == 0 else ""} style="margin-top:3px;width:auto;">
              <span><b>Ich erfasse meine Arbeitszeiten</b><br><span class="small" style="color:var(--mu);">Zugriff auf Zeiterfassung, Kalender und Gleitzeitkonto.</span></span>
            </label>
            <label style="font-weight:400;display:flex;align-items:flex-start;gap:10px;padding:12px;border:1px solid var(--bd);border-radius:var(--rs);cursor:pointer;">
              <input type="radio" name="admin_only" value="1" {"checked" if cur_ao == 1 else ""} style="margin-top:3px;width:auto;">
              <span><b>Ich bin nur für die Verwaltung zuständig</b><br><span class="small" style="color:var(--mu);">Kein eigenes Zeitkonto. Direktzugriff auf den Admin-Bereich nach dem Login.</span></span>
            </label>
            <div><button class="btn primary" type="submit">Weiter →</button></div>
          </form>
        </div>
        """

    elif step == 1:
        uname = _html.escape(u.get("username") or "")
        body = f"""
        {flash_html()}
        {FORM_ASSETS_JS}
        {indicator}
        <div class="card">
          <h3>Schritt 1 – Passwort ändern</h3>
          <p class="small">Bitte ändere dein temporäres Passwort. Das neue Passwort muss die Kennwortregeln erfüllen.</p>
          <form method="post" action="/onboarding?step=1" style="display:flex;flex-direction:column;gap:10px;max-width:360px;margin-top:12px;">
            <div><label>Aktuelles Passwort</label><input type="password" name="current_password" required autocomplete="current-password"></div>
            <div>
              <label>Neues Passwort</label>
              <input type="password" name="new_password" id="obpw-inp" required autocomplete="new-password"
                     oninput="_pwUpdate('obpw-inp','obpw-chk','{uname}')">
              <div id="obpw-chk" style="margin-top:6px;padding:8px;background:var(--sf);border-radius:var(--rs);border:1px solid var(--bd);line-height:1.7;"></div>
            </div>
            <div><label>Wiederholung</label><input type="password" name="new_password2" required autocomplete="new-password"></div>
            <div><button class="btn primary" type="submit">Weiter →</button></div>
          </form>
        </div>
        {_PW_STRENGTH_JS}
        """

    elif step == 2:
        dn = u.get("display_name") or ""
        em = u.get("email") or ""
        body = f"""
        {flash_html()}
        {indicator}
        <div class="card">
          <h3>Schritt 2 – Persönliche Daten</h3>
          <p class="small">Optional – kann jederzeit in den Einstellungen geändert werden.</p>
          <form method="post" action="/onboarding?step=2" style="display:flex;flex-direction:column;gap:10px;max-width:340px;margin-top:12px;">
            <div><label>Anzeigename</label><br><input name="display_name" value="{dn}" placeholder="Max Mustermann"></div>
            <div><label>E-Mail</label><br><input type="email" name="email" value="{em}" placeholder="max@example.com"></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary" type="submit">Weiter →</button>
              <a class="btn" href="/onboarding?step=3">Überspringen</a>
            </div>
          </form>
        </div>
        """

    elif step == 3:
        sched = _get_user_schedule_current(u["id"])

        def chk3(bit):
            return "checked" if (int(sched.get("workdays_mask", 31)) & bit) else ""

        def hm3(mins):
            return _fmt_minutes(int(mins or 0))

        cur_mode3 = sched.get("mode") or "weekly"
        sched_id3 = sched.get("id")

        body = f"""
        {flash_html()}
        {FORM_ASSETS_JS}
        {indicator}
        <div class="card">
          <h3>Schritt 3 – Zeitschema</h3>
          <p class="small">Dein Arbeitszeitmodell. Kann jederzeit in den Einstellungen angepasst werden.</p>
          <form method="post" action="/onboarding?step=3" style="margin-top:12px;">
            <div style="margin-bottom:10px;">
              <label><b>Gültig ab</b></label><br>
              {_date_input("valid_from", today.isoformat(), required=True)}
            </div>
            <div style="margin-bottom:10px;">
              <label><b>Modus</b></label><br>
              <label><input type="radio" name="mode" value="weekly" {"checked" if cur_mode3=="weekly" else ""}
                     onchange="switchSchedMode('weekly')"> Wochenarbeitszeit verteilen</label><br>
              <label><input type="radio" name="mode" value="daily_hours" {"checked" if cur_mode3=="daily_hours" else ""}
                     onchange="switchSchedMode('daily_hours')"> Sollstunden je Wochentag</label><br>
              <label><input type="radio" name="mode" value="daily" {"checked" if cur_mode3=="daily" else ""}
                     onchange="switchSchedMode('daily')"> {t('onboarding.sched_fixed')}</label>
            </div>
            <div id="sec-weekly">
              <div style="margin-bottom:10px;">
                <label><b>Wochenstunden</b></label><br>
                <input type="number" name="weekly_hours" min="0" step="0.25" value="{(int(sched.get('weekly_minutes',2400))/60):g}" style="width:120px;">
              </div>
              <div style="margin-bottom:10px;">
                <label><b>Arbeitstage</b></label><br>
                <label><input type="checkbox" name="wd_mon" value="1" {chk3(1)}> Mo</label>
                <label><input type="checkbox" name="wd_tue" value="1" {chk3(2)}> Di</label>
                <label><input type="checkbox" name="wd_wed" value="1" {chk3(4)}> Mi</label>
                <label><input type="checkbox" name="wd_thu" value="1" {chk3(8)}> Do</label>
                <label><input type="checkbox" name="wd_fri" value="1" {chk3(16)}> Fr</label>
                <label><input type="checkbox" name="wd_sat" value="1" {chk3(32)}> Sa</label>
                <label><input type="checkbox" name="wd_sun" value="1" {chk3(64)}> So</label>
              </div>
            </div>
            <div id="sec-daily-hours" style="display:none;">
              <div class="card" style="margin-bottom:10px;">
                <b>Sollstunden je Wochentag</b><br>
                <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;">
                  <div>Mo<br><input type="text" name="mon" value="{hm3(sched['mon_minutes'])}" style="width:90px;"></div>
                  <div>Di<br><input type="text" name="tue" value="{hm3(sched['tue_minutes'])}" style="width:90px;"></div>
                  <div>Mi<br><input type="text" name="wed" value="{hm3(sched['wed_minutes'])}" style="width:90px;"></div>
                  <div>Do<br><input type="text" name="thu" value="{hm3(sched['thu_minutes'])}" style="width:90px;"></div>
                  <div>Fr<br><input type="text" name="fri" value="{hm3(sched['fri_minutes'])}" style="width:90px;"></div>
                  <div>Sa<br><input type="text" name="sat" value="{hm3(sched['sat_minutes'])}" style="width:90px;"></div>
                  <div>So<br><input type="text" name="sun" value="{hm3(sched['sun_minutes'])}" style="width:90px;"></div>
                </div>
              </div>
            </div>
            <div id="sec-daily-blocks" style="display:none;">
              <p class="small" style="margin-bottom:8px;">{t('settings.schedule_blocks_hint')}</p>
              {_sched_daily_blocks_html(sched_id3, "daily",
                                       show_checkbox=False, always_visible=True)}
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary" type="submit">Weiter →</button>
              <a class="btn" href="/onboarding?step=4">Überspringen</a>
            </div>
          </form>
        </div>
        <script>
        function switchSchedMode(mode){{
          document.getElementById('sec-weekly').style.display = mode==='weekly' ? '' : 'none';
          document.getElementById('sec-daily-hours').style.display = mode==='daily_hours' ? '' : 'none';
          document.getElementById('sec-daily-blocks').style.display = mode==='daily' ? '' : 'none';
        }}
        document.querySelectorAll('input[name="mode"]').forEach(function(r){{
          r.addEventListener('change', function(){{ switchSchedMode(r.value); }});
        }});
        switchSchedMode('{cur_mode3}');
        </script>
        """

    elif step == 4:
        vc = _vacation_calc(u["id"], today.year)
        body = f"""
        {flash_html()}
        {indicator}
        <div class="card">
          <h3>Schritt 4 – Urlaubskontingent {today.year}</h3>
          <p class="small">Dein jährlicher Urlaubsanspruch und Übertrag aus dem Vorjahr. Kann jederzeit in den Einstellungen angepasst werden.</p>
          <form method="post" action="/onboarding?step=4" style="display:flex;flex-direction:column;gap:10px;max-width:340px;margin-top:12px;">
            <div><label>Urlaubsanspruch (Tage/Jahr)</label><br>
              <input type="number" name="entitlement_days" step="0.5" min="0" value="{vc['entitlement']}" required></div>
            <div><label>Übertrag Vorjahr</label><br>
              <input type="number" name="carryover_days" step="0.5" min="0" value="{vc['carryover']}" required></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary" type="submit">Weiter →</button>
              <a class="btn" href="/onboarding?step=5">Überspringen</a>
            </div>
          </form>
        </div>
        """

    elif step == 5:
        tracking_start = u.get("tracking_start_date") or ""
        start_balance_minutes = _get_start_balance_minutes(u["id"])
        start_balance_txt = _fmt_minutes_signed(start_balance_minutes)
        body = f"""
        {flash_html()}
        {FORM_ASSETS_JS}
        {indicator}
        <div class="card">
          <h3>Schritt 5 – Erfassung ab &amp; Startsaldo</h3>
          <p class="small">Ab wann soll die Zeiterfassung beginnen und welchen Stundensaldo bringst du mit?</p>
          <form method="post" action="/onboarding?step=5" style="display:flex;flex-direction:column;gap:12px;max-width:380px;margin-top:12px;">
            <div>
              <label>Erfassung ab <span class="small">(leer = ab Jahresbeginn)</span></label><br>
              {_date_input("tracking_start_date", tracking_start)}
              <div class="small" style="color:#777;margin-top:4px;">Ab diesem Datum werden fehlende Einträge und der Saldo berechnet.</div>
            </div>
            <div>
              <label>Startsaldo Gleitzeit</label><br>
              <input type="text" name="start_balance" value="{start_balance_txt}" placeholder="+00:00" style="width:120px;">
              <div class="small" style="color:#777;margin-top:4px;">Überstunden die du mitbringst (z. B. +12:30 oder -01:15).</div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn primary" type="submit">Weiter →</button>
              <a class="btn" href="/onboarding?step=6">Überspringen</a>
            </div>
          </form>
        </div>
        """

    elif step == 6:
        dn = u.get("display_name") or u.get("username") or ""
        if u.get("admin_only"):
            body = f"""
        {flash_html()}
        {indicator}
        <div class="card">
          <h3>Schritt 6 – Konto bereit!</h3>
          <p>Hallo <b>{dn}</b>, dein Konto ist konfiguriert.</p>
          <p class="small" style="margin-top:8px;">Als Admin-Benutzer ohne eigene Zeiterfassung hast du Zugriff auf den Admin-Bereich.</p>
          <form method="post" action="/onboarding?step=6" style="margin-top:14px;">
            <button class="btn primary" type="submit">Zur Übersicht →</button>
          </form>
        </div>
            """
        else:
            sched = _get_user_schedule_for_day(u["id"], today.isoformat()) or {}
            vc = _vacation_calc(u["id"], today.year)
            start_balance_minutes = _get_start_balance_minutes(u["id"])
            tracking_start = _fmt_date_de(u.get("tracking_start_date")) or "ab Jahresbeginn"
            mode_txt = "Wochenarbeitszeit" if sched.get("mode") == "weekly" else "Je Wochentag"
            weekly_h = f"{(int(sched.get('weekly_minutes', 0))/60):g}h" if sched.get("weekly_minutes") else "—"
            body = f"""
        {flash_html()}
        {indicator}
        <div class="card">
          <h3>Schritt 6 – Alles bereit!</h3>
          <p>Hallo <b>{dn}</b>, dein Konto ist konfiguriert.</p>
          <div style="display:flex;flex-direction:column;gap:6px;margin:14px 0;font-size:14px;">
            <div><b>Erfassung ab:</b> {tracking_start}</div>
            <div><b>Zeitschema:</b> {mode_txt}, {weekly_h}</div>
            <div><b>Urlaub {today.year}:</b> {vc['entitlement']:.1f} Tage + {vc['carryover']:.1f} Übertrag</div>
            <div><b>Startsaldo:</b> {_fmt_minutes_signed(start_balance_minutes)}</div>
          </div>
          <p class="small">Alle Einstellungen können jederzeit unter <b>Einstellungen</b> angepasst werden.</p>
          <form method="post" action="/onboarding?step=6" style="margin-top:14px;">
            <button class="btn primary" type="submit">Zeiterfassung starten →</button>
          </form>
        </div>
            """

    else:
        body = f"""<div class="card"><h3>Unbekannter Schritt</h3></div>"""

    return render_template_string(layout(t("onboarding.step6_title"), body, u, APP_VERSION))



@core_bp.post("/onboarding")
@login_required
def onboarding_post():
    from app import bootstrap, add_flash, _vacation_calc, _set_start_balance_minutes, _parse_signed_hhmm_to_minutes, _get_tracking_start, _get_start_balance_minutes, _fmt_minutes_signed, _parse_date_input, _workday_bit, _parse_sched_blocks_from_form, _sched_save_blocks, _sched_save_exceptions_from_form, _set_vacation_year, _coerce_minutes
    from auth import validate_password, set_password, authenticate as _auth_check
    import datetime, re
    bootstrap()
    u = current_user()
    if u.get("onboarding_done"):
        return redirect(url_for("core.index"))

    try:
        step = int(request.args.get("step") or 1)
    except (ValueError, TypeError):
        step = 1

    if step == 0:
        admin_only_val = 1 if (request.form.get("admin_only") or "0") == "1" else 0
        db = connect()
        db.execute(
            "UPDATE users SET admin_only=?, updated_at=datetime('now') WHERE id=?",
            (admin_only_val, u["id"]),
        )
        db.commit()
        db.close()
        return redirect("/onboarding?step=1")

    elif step == 1:
        current_password = request.form.get("current_password") or ""
        new_password = (request.form.get("new_password") or "").strip()
        new_password2 = (request.form.get("new_password2") or "").strip()

        from auth import authenticate as _auth_check
        _, _pw_err = _auth_check(u["username"], current_password)
        if _pw_err:
            add_flash(t("settings.password_wrong"), "error")
            return redirect("/onboarding?step=1")
        errs = validate_password(new_password, u.get("username") or "")
        if errs:
            add_flash(t("flash.error.password_invalid").format(errors="; ".join(errs)), "error")
            return redirect("/onboarding?step=1")
        if new_password != new_password2:
            add_flash(t("settings.password_mismatch"), "error")
            return redirect("/onboarding?step=1")
        set_password(u["id"], new_password)
        return redirect("/onboarding?step=2")

    elif step == 2:
        display_name = (request.form.get("display_name") or "").strip() or None
        email = (request.form.get("email") or "").strip() or None
        db = connect()
        db.execute(
            "UPDATE users SET display_name=?, email=?, updated_at=datetime('now') WHERE id=?",
            (display_name, email, u["id"]),
        )
        db.commit()
        db.close()
        u = current_user()
        if u and u.get("admin_only"):
            return redirect("/onboarding?step=6")
        return redirect("/onboarding?step=3")

    elif step == 3:
        valid_from = _parse_date_input(request.form.get("valid_from") or "") or ""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", valid_from):
            add_flash(t("flash.error.invalid_date"), "error")
            return redirect("/onboarding?step=3")
        mode = (request.form.get("mode") or "weekly").strip().lower()
        if mode not in ("weekly", "daily_hours", "daily"):
            mode = "weekly"
        weekly_hours_raw = (request.form.get("weekly_hours") or "0").strip().replace(",", ".")
        try:
            weekly_minutes = int(round(float(weekly_hours_raw) * 60))
        except Exception:
            weekly_minutes = 0
        mask = 0
        for i, key in enumerate(["wd_mon", "wd_tue", "wd_wed", "wd_thu", "wd_fri", "wd_sat", "wd_sun"]):
            if (request.form.get(key) or "") == "1":
                mask |= _workday_bit(i)
        if mode == "daily":
            blocks_3 = _parse_sched_blocks_from_form(request.form)
            mask = sum(1 << wd for wd in blocks_3.keys()) if blocks_3 else mask

        def _day_min(name):
            raw = (request.form.get(name) or "").strip()
            return _coerce_minutes(raw) if raw else 0

        row = {
            "user_id": int(u["id"]),
            "valid_from": valid_from,
            "mode": mode,
            "weekly_minutes": int(weekly_minutes),
            "workdays_mask": int(mask),
            "block_weekends_holidays": 1,
            "mon_minutes": _day_min("mon"),
            "tue_minutes": _day_min("tue"),
            "wed_minutes": _day_min("wed"),
            "thu_minutes": _day_min("thu"),
            "fri_minutes": _day_min("fri"),
            "sat_minutes": _day_min("sat"),
            "sun_minutes": _day_min("sun"),
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        db = connect()
        cols = [r["name"] for r in db.execute("PRAGMA table_info(user_schedules)").fetchall()]
        row = {k: v for k, v in row.items() if k in cols}
        db.execute("DELETE FROM user_schedules WHERE user_id=? AND valid_from=?", (row["user_id"], row["valid_from"]))
        col_list = ", ".join(row.keys())
        ph_list = ", ".join(["?"] * len(row))
        cur3 = db.execute(f"INSERT INTO user_schedules ({col_list}) VALUES ({ph_list})", list(row.values()))
        sid3 = cur3.lastrowid
        db.commit()
        db.close()
        if mode == "daily":
            _sched_save_blocks(sid3, blocks_3)
            _sched_save_exceptions_from_form(sid3, request.form)
        return redirect("/onboarding?step=4")

    elif step == 4:
        year = datetime.date.today().year
        try:
            entitlement = float(request.form.get("entitlement_days") or 0)
            carryover = float(request.form.get("carryover_days") or 0)
            if entitlement < 0 or carryover < 0:
                raise ValueError()
        except Exception:
            add_flash(t("flash.error.invalid_values"), "error")
            return redirect("/onboarding?step=4")
        _set_vacation_year(u["id"], year, entitlement, carryover)
        return redirect("/onboarding?step=5")

    elif step == 5:
        tracking_start_raw = (request.form.get("tracking_start_date") or "").strip()
        tracking_start_iso = _parse_date_input(tracking_start_raw) if tracking_start_raw else None
        start_balance_raw = (request.form.get("start_balance") or "").strip()
        try:
            start_minutes = _parse_signed_hhmm_to_minutes(start_balance_raw) if start_balance_raw else 0
        except Exception:
            add_flash(t("flash.error.balance_start_format"), "error")
            return redirect("/onboarding?step=5")
        _set_start_balance_minutes(u["id"], start_minutes)
        if tracking_start_iso:
            db = connect()
            db.execute(
                "UPDATE users SET tracking_start_date=?, updated_at=datetime('now') WHERE id=?",
                (tracking_start_iso, u["id"]),
            )
            db.commit()
            db.close()
        return redirect("/onboarding?step=6")

    elif step == 6:
        db = connect()
        db.execute("UPDATE users SET onboarding_done=1, updated_at=datetime('now') WHERE id=?", (u["id"],))
        db.commit()
        db.close()
        return redirect(url_for("core.index"))

    return redirect("/onboarding?step=1")


def _get_missing_entry_days(user_id: int, year: int) -> set:
    """Return ISO dates of past workdays in `year` with no entry and not a holiday."""
    today = datetime.date.today()
    year_start = datetime.date(year, 1, 1).isoformat()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()

    # Respect tracking_start_date: don't flag days before tracking began
    db = connect()
    try:
        r = db.execute("SELECT tracking_start_date FROM users WHERE id=?", (user_id,)).fetchone()
        tracking_start = r["tracking_start_date"] if r else None
    finally:
        db.close()
    if tracking_start:
        year_start = max(year_start, tracking_start)

    if yesterday < year_start:
        return set()
    days_with = _days_with_any_entry(user_id, year_start, yesterday)
    _region = _get_user_holiday_region(user_id)
    db = connect()
    try:
        hol_days = {
            str(r["day"])[:10]
            for r in db.execute(
                "SELECT day FROM calendar_days WHERE day BETWEEN ? AND ? AND is_holiday=1 AND region=?",
                (year_start, yesterday, _region),
            ).fetchall()
        }
    finally:
        db.close()
    missing = set()
    for iso in _iter_days(year_start, yesterday):
        if iso in days_with or iso in hol_days:
            continue
        if _is_workday_for_user(iso, _get_user_schedule_for_day(user_id, iso)):
            missing.add(iso)
    return missing


def _get_contoured_days(user_id: int, start_iso: str, end_iso: str) -> set:
    db = connect()
    try:
        return {
            str(r["day"])
            for r in db.execute(
                "SELECT day FROM contoured_days WHERE user_id=? AND day BETWEEN ? AND ?",
                (user_id, start_iso, end_iso),
            ).fetchall()
        }
    finally:
        db.close()


def _has_weekend_exception(user_id: int, day: str) -> bool:
    db = connect()
    try:
        return bool(db.execute(
            "SELECT 1 FROM weekend_exceptions WHERE user_id=? AND day=?", (user_id, day)
        ).fetchone())
    finally:
        db.close()


def _get_weekend_exception(user_id: int, day: str):
    db = connect()
    try:
        return db.execute(
            "SELECT note FROM weekend_exceptions WHERE user_id=? AND day=?", (user_id, day)
        ).fetchone()
    finally:
        db.close()


def _set_weekend_exception(user_id: int, day: str, note: str = "") -> None:
    db = connect()
    db.execute(
        "INSERT OR REPLACE INTO weekend_exceptions(user_id, day, note, created_at) VALUES(?,?,?,datetime('now'))",
        (user_id, day, note),
    )
    db.commit()
    db.close()


def _remove_weekend_exception(user_id: int, day: str) -> None:
    db = connect()
    db.execute("DELETE FROM weekend_exceptions WHERE user_id=? AND day=?", (user_id, day))
    db.commit()
    db.close()


def _get_weekend_exceptions_month(user_id: int, first_iso: str, last_iso: str) -> set:
    db = connect()
    try:
        return {
            str(r["day"])[:10]
            for r in db.execute(
                "SELECT day FROM weekend_exceptions WHERE user_id=? AND day BETWEEN ? AND ?",
                (user_id, first_iso, last_iso),
            ).fetchall()
        }
    finally:
        db.close()


def _get_tracking_start(user_id: int) -> "str | None":
    """Return user's tracking_start_date (ISO) or None."""
    db = connect()
    try:
        r = db.execute("SELECT tracking_start_date FROM users WHERE id=?", (user_id,)).fetchone()
        val = r["tracking_start_date"] if r else None
        return str(val)[:10] if val else None
    finally:
        db.close()


def _get_contouring_info(user_id: int) -> dict:
    """Return {'enabled': int, 'start_date': str|None} for user."""
    db = connect()
    try:
        r = db.execute(
            "SELECT contouring_enabled, contouring_start_date FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if r:
            return {
                "enabled": int(r["contouring_enabled"]) if r["contouring_enabled"] is not None else 1,
                "start_date": str(r["contouring_start_date"])[:10] if r["contouring_start_date"] else None,
            }
        return {"enabled": 1, "start_date": None}
    finally:
        db.close()


def _before_start_date(user_id: int, iso_day: str) -> "str | None":
    """Return error message if iso_day is before user's tracking_start_date, else None."""
    start = _get_tracking_start(user_id)
    if start and iso_day < start:
        return t("flash.error.before_start_date").format(date=_fmt_date_de(start))
    return None


def _range_before_start_date(user_id: int, date_from: str, date_to: str) -> "str | None":
    return _before_start_date(user_id, date_from)


def _get_max_contoured_day(user_id: int) -> "str | None":
    db = connect()
    try:
        r = db.execute(
            "SELECT MAX(day) AS m FROM contoured_days WHERE user_id=?", (user_id,)
        ).fetchone()
        return str(r["m"]) if r and r["m"] else None
    finally:
        db.close()


def _get_uncontoured_days(user_id: int, year: int) -> set:
    """Past days-with-entries in year that have not been contoured."""
    ci = _get_contouring_info(user_id)
    if not ci["enabled"]:
        return set()

    today = datetime.date.today()
    year_start = datetime.date(year, 1, 1).isoformat()
    yesterday = (today - datetime.timedelta(days=1)).isoformat()

    db = connect()
    try:
        r = db.execute("SELECT tracking_start_date FROM users WHERE id=?", (user_id,)).fetchone()
        tracking_start = r["tracking_start_date"] if r else None
    finally:
        db.close()
    if tracking_start:
        year_start = max(year_start, tracking_start)
    if ci["start_date"]:
        year_start = max(year_start, ci["start_date"])

    if yesterday < year_start:
        return set()

    days_with = _days_with_any_entry(user_id, year_start, yesterday)
    contoured = _get_contoured_days(user_id, year_start, yesterday)
    return {iso for iso in days_with if year_start <= iso <= yesterday and iso not in contoured}


# -------------------------
# Kontierung API
# -------------------------

def _calc_retirement(user_id: int):
    db = connect()
    try:
        row = db.execute("SELECT birth_date, retirement_age FROM users WHERE id=?", (user_id,)).fetchone()
    finally:
        db.close()
    if not row or not row["birth_date"]:
        return None
    try:
        bd = datetime.date.fromisoformat(row["birth_date"])
    except (ValueError, TypeError):
        return None
    age = int(row["retirement_age"] or 67)
    try:
        ret_date = bd.replace(year=bd.year + age)
    except ValueError:
        ret_date = bd.replace(year=bd.year + age, day=28)
    today = datetime.date.today()
    delta = ret_date - today
    cal_days = delta.days
    if cal_days <= 0:
        return {"retired": True, "retirement_date": ret_date.isoformat(), "age": age}
    weeks = cal_days // 7
    # count remaining full years and months
    years = 0
    months = 0
    d = today
    while True:
        try:
            nxt = d.replace(year=d.year + 1)
        except ValueError:
            nxt = d.replace(year=d.year + 1, day=28)
        if nxt > ret_date:
            break
        years += 1
        d = nxt
    while True:
        m = d.month + 1
        y = d.year + (1 if m > 12 else 0)
        m = m if m <= 12 else 1
        try:
            nxt = d.replace(year=y, month=m)
        except ValueError:
            nxt = d.replace(year=y, month=m, day=28)
        if nxt > ret_date:
            break
        months += 1
        d = nxt
    remaining_days = (ret_date - d).days
    full_weeks = cal_days // 7
    extra = cal_days % 7
    start_dow = today.weekday()
    net_workdays = full_weeks * 5
    for i in range(extra):
        if (start_dow + i) % 7 < 5:
            net_workdays += 1
    return {
        "retired": False,
        "retirement_date": ret_date.isoformat(),
        "age": age,
        "cal_days": cal_days,
        "weeks": weeks,
        "years": years,
        "months": months,
        "days": remaining_days,
        "net_workdays": net_workdays,
    }



@core_bp.get("/")
@login_required
def index():
    from app import bootstrap, flash_html, layout, APP_VERSION, _calc_balance_end_at, _fmt_minutes_signed, _vacation_calc, _get_missing_entry_days, _get_contouring_info, _get_uncontoured_days, _get_max_contoured_day, _get_contoured_days, _absence_summary_for_period, _get_tracking_start, _calc_retirement, _fmt_date_de, FORM_ASSETS_JS, _feature_enabled
    import datetime
    bootstrap()
    u = current_user()
    if u and u.get("admin_only"):
        return redirect("/admin")
    today = datetime.date.today()

    # Saldo (Stand Vortag)
    yesterday_balance = today - datetime.timedelta(days=1)
    balance_minutes = _calc_balance_end_at(u["id"], yesterday_balance.isoformat())
    balance_str = _fmt_minutes_signed(balance_minutes)
    balance_color = "var(--ok)" if balance_minutes >= 0 else "var(--danger)"
    balance_date_de = _fmt_date_de(yesterday_balance.isoformat())

    # Resturlaub
    year = today.year
    vc = _vacation_calc(u["id"], year)
    vac_hint = ""
    if vc.get("carryover_exception"):
        if vc["effective_carryover"] > 0:
            vac_hint = f" · <span style='color:#d97706;'>{vc['effective_carryover']:.1f} {t('dashboard.carryover_active')}</span>"
    elif not vc["deadline_passed"] and vc["carryover"] > 0:
        vac_hint = f" · <span style='color:var(--danger);'>{t('dashboard.carryover_expires')} {vc['deadline']}</span>"
    elif vc["deadline_passed"] and vc["carryover_forfeited"] > 0:
        vac_hint = f" · <span style='color:var(--mu);'>{vc['carryover_forfeited']:.1f} {t('dashboard.carryover_forfeited')}</span>"

    # Fehlende Einträge
    missing_count = len(_get_missing_entry_days(u["id"], year))
    missing_color = "var(--danger)" if missing_count > 0 else "var(--ok)"

    # Kontierung
    contouring_info = _get_contouring_info(u["id"])
    contouring_enabled = contouring_info["enabled"]
    contouring_start = contouring_info["start_date"]
    uncontoured_count = len(_get_uncontoured_days(u["id"], year))
    uc_color = "var(--danger)" if uncontoured_count > 0 else "var(--ok)"
    max_contoured = _get_max_contoured_day(u["id"])
    max_contoured_str = _fmt_date_de(max_contoured) if max_contoured else "–"
    yesterday_iso = (today - datetime.timedelta(days=1)).isoformat()
    yesterday_de = _fmt_date_de(yesterday_iso)
    _db_tmp = connect()
    try:
        _fb = _db_tmp.execute(
            "SELECT MIN(day) AS d FROM time_blocks WHERE user_id=?", (u["id"],)
        ).fetchone()
        first_entry_iso = str(_fb["d"])[:10] if _fb and _fb["d"] else yesterday_iso
    finally:
        _db_tmp.close()
    if contouring_start:
        first_entry_iso = max(first_entry_iso, contouring_start)
    kontier_has_range = first_entry_iso <= yesterday_iso

    # Abwesenheiten Jahresübersicht
    ab_sum = _absence_summary_for_period(u["id"], f"{year}-01-01", f"{year}-12-31")

    def _ci_get(d: dict, key: str) -> int:
        kl = key.lower()
        return sum(v for k, v in d.items() if k.lower() == kl)

    past_urlaub   = ab_sum["past"]["urlaub"]
    planned_urlaub = ab_sum["planned"]["urlaub"]
    past_krank    = ab_sum["past"]["krank"]
    past_verdi    = _ci_get(ab_sum["past"]["sonstige"], "verdi")
    planned_verdi = _ci_get(ab_sum["planned"]["sonstige"], "verdi")
    past_flextag  = _ci_get(ab_sum["past"]["sonstige"], "flextag")
    planned_flextag = _ci_get(ab_sum["planned"]["sonstige"], "flextag")
    vac_available = int(round(vc["remaining_total"]))

    def _ab_cell(label: str, rows: list) -> str:
        content = "".join(
            f"<div style='display:flex;justify-content:space-between;gap:12px;'>"
            f"<span style='color:var(--mu);'>{k}</span><b>{v}</b></div>"
            for k, v in rows
        )
        return (
            f"<div style='background:var(--bg);border:1px solid var(--bd);"
            f"border-radius:var(--rs);padding:10px 12px;'>"
            f"<div style='font-size:11px;font-weight:600;text-transform:uppercase;"
            f"letter-spacing:.04em;color:var(--mu);margin-bottom:6px;'>{label}</div>"
            f"<div style='display:flex;flex-direction:column;gap:3px;font-size:13px;'>{content}</div>"
            f"</div>"
        )

    ab_cells = _ab_cell(t("absence_type.urlaub"), [
        (t("absence_summary.taken"), past_urlaub),
        *([( t("absence_summary.planned"), planned_urlaub)] if planned_urlaub else []),
        (t("absence_summary.available"), vac_available),
    ])
    if past_krank:
        ab_cells += _ab_cell(t("absence_type.krank"), [(t("absence_summary.sick"), past_krank)])
    if past_verdi or planned_verdi:
        ab_cells += _ab_cell(t("absence_type.verdi"), [
            *([( t("absence_summary.taken"), past_verdi)] if past_verdi else []),
            *([( t("absence_summary.planned"), planned_verdi)] if planned_verdi else []),
        ])
    if past_flextag or planned_flextag:
        ab_cells += _ab_cell(t("absence_type.flextag"), [
            *([( t("absence_summary.taken"), past_flextag)] if past_flextag else []),
            *([("Geplant", planned_flextag)] if planned_flextag else []),
        ])

    if contouring_enabled:
        _kontiering_grid_card = f"""
      <div class="card" style="margin:0;">
        <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">{t("dashboard.booking")} {year}</div>
        {"" if not (contouring_start and contouring_start > today.isoformat()) else f"<div style='color:var(--mu);font-size:12px;margin-bottom:4px;'>ab <b style='color:var(--tx);'>{_fmt_date_de(contouring_start)}</b></div>"}
        <div style="font-size:2rem;font-weight:700;letter-spacing:-.02em;color:{uc_color};line-height:1.1;">{uncontoured_count} <span style="font-size:1rem;font-weight:400;color:var(--mu);">{t("common.days")}</span></div>
        <div class="small" style="margin-top:2px;margin-bottom:8px;">{t("dashboard.booking_until")}: <b style="color:var(--tx);">{max_contoured_str}</b></div>
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <div class="dt-wrap" style="flex:1;min-width:90px;max-width:140px;">
            <input type="text" id="kontier-dt-text" class="dt-text"
                   value="{yesterday_de}" placeholder="TT.MM.JJJJ" maxlength="10"
                   style="font-size:12px;"
                   oninput="kontierDtText(this)">
            <input type="date" id="kontier-dt-pick" class="dt-pick"
                   value="{yesterday_iso}" min="{first_entry_iso}" max="{yesterday_iso}"
                   onchange="kontierDtPick(this)">
          </div>
          <button id="kontier-btn" class="btn btn-sm" onclick="doKontieren()"
                  {"" if kontier_has_range else "disabled"}>{t("btn.booking")}</button>
        </div>
        <div id="kontier-toast" style="display:none;margin-top:8px;padding:6px 10px;
             background:var(--ok);color:#fff;border-radius:6px;font-size:12px;font-weight:600;"></div>
      </div>"""
    else:
        _kontiering_grid_card = f"""
      <div class="card" style="margin:0;opacity:.6;">
        <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">{t("dashboard.booking")}</div>
        <div style="font-size:15px;font-weight:600;color:var(--mu);">{t("dashboard.booking_off")}</div>
        <div style="margin-top:8px;">
          <a class="btn" href="/settings" >{t("nav.settings")}</a>
        </div>
      </div>"""

    retirement = _calc_retirement(u["id"])
    if retirement and not retirement["retired"]:
        _ret_de = _fmt_date_de(retirement["retirement_date"])
        _ret_widget = f"""
    <div class="card" style="margin-bottom:12px;">
      <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">{t("dashboard.retirement")} ({t("dashboard.age_label")} {retirement['age']})</div>
      <div style="font-size:1.6rem;font-weight:700;letter-spacing:-.02em;line-height:1.15;">{retirement['years']} <span style="font-size:.95rem;font-weight:400;color:var(--mu);">{t("dashboard.years_short")}</span> {retirement['months']} <span style="font-size:.95rem;font-weight:400;color:var(--mu);">{t("dashboard.months_short")}</span> {retirement['days']} <span style="font-size:.95rem;font-weight:400;color:var(--mu);">{t("dashboard.days_short")}</span></div>
      <div class="small" style="margin-top:6px;color:var(--mu);">{t("dashboard.retire_entry")}: <b style="color:var(--tx);">{_ret_de}</b> &nbsp;·&nbsp; {retirement['cal_days']:,} {t("dashboard.cal_days")} &nbsp;·&nbsp; {retirement['net_workdays']:,} {t("dashboard.workdays")} &nbsp;·&nbsp; {retirement['weeks']:,} {t("dashboard.weeks")}</div>
    </div>"""
    elif retirement and retirement["retired"]:
        _ret_widget = f"""
    <div class="card" style="margin-bottom:12px;">
      <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">{t("dashboard.retirement")}</div>
      <div style="font-size:1.1rem;font-weight:600;">{t("dashboard.retired")}</div>
    </div>"""
    else:
        _ret_widget = ""

    body = f'''
    {flash_html()}
<style>
.idx-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;margin-bottom:12px;}}
@media(min-width:1024px){{.idx-grid{{grid-template-columns:repeat(4,1fr);}}}}
</style>

    <div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;">
      <a class="btn btn-lg" href="/day/{today.isoformat()}#new-block"
         style="flex:1;text-align:center;min-width:140px;">
        {t("dashboard.time_tracking")}
      </a>
      <a class="btn btn-lg" href="/absences"
         style="flex:1;text-align:center;min-width:140px;">
        {t("dashboard.absences")}
      </a>
      <a class="btn btn-lg" href="/business_trips"
         style="flex:1;text-align:center;min-width:140px;">
        {t("dashboard.business_trips")}
      </a>
      <a class="btn btn-lg" href="/calendar"
         style="flex:1;text-align:center;min-width:140px;">
        {t("dashboard.calendar")}
      </a>
    </div>

    <div class="idx-grid">

      <div class="card" style="margin:0;">
        <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">{t("dashboard.balance")}</div>
        <div style="font-size:2rem;font-weight:700;letter-spacing:-.02em;color:{balance_color};line-height:1.1;">{balance_str}</div>
        <div style="margin-top:8px;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
          <span class="small">{t("dashboard.balance_as_of")} ({balance_date_de})</span>
          <a class="btn" href="/balance" >{t("btn.details")}</a>
        </div>
      </div>

      <div class="card" style="margin:0;">
        <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">{t("dashboard.vacation_left")} {year}</div>
        <div style="font-size:2rem;font-weight:700;letter-spacing:-.02em;line-height:1.1;">{vc["remaining_total"]:.1f} <span style="font-size:1rem;font-weight:400;color:var(--mu);">{t("common.days")}</span></div>
        <div style="margin-top:8px;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
          <span class="small">{t("common.from")} {vc["entitlement"] + vc["effective_carryover"]:.1f} {t("dashboard.vacation_avail")}{vac_hint}</span>
          <a class="btn" href="/settings/vacation" >{t("btn.details")}</a>
        </div>
      </div>

      <div class="card" style="margin:0;">
        <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;">{t("dashboard.missing")} {year}</div>
        <div style="font-size:2rem;font-weight:700;letter-spacing:-.02em;color:{missing_color};line-height:1.1;">{missing_count} <span style="font-size:1rem;font-weight:400;color:var(--mu);">{t("common.days")}</span></div>
        <div style="margin-top:8px;">
          <span class="small">{t("dashboard.missing_hint")}</span>
        </div>
      </div>

      {_kontiering_grid_card}

    </div>

    <script>
    function kontierDtText(inp){{
      var m=inp.value.match(/^(\\d{{1,2}})\\.(\\d{{1,2}})\\.(\\d{{4}})$/);
      var pick=document.getElementById('kontier-dt-pick');
      if(m){{pick.value=m[3]+'-'+m[2].padStart(2,'0')+'-'+m[1].padStart(2,'0');}}
      else{{pick.value='';}}
      _validateKontier();
    }}
    function kontierDtPick(inp){{
      var dt=document.getElementById('kontier-dt-text');
      if(inp.value&&inp.value.length===10){{dt.value=inp.value.slice(8)+'.'+inp.value.slice(5,7)+'.'+inp.value.slice(0,4);}}
      _validateKontier();
    }}
    function _validateKontier(){{
      var pick=document.getElementById('kontier-dt-pick');
      if(!pick)return;
      var v=pick.value;
      var ok=v&&v>='{first_entry_iso}'&&v<='{yesterday_iso}';
      var btn=document.getElementById('kontier-btn');
      if(btn)btn.disabled=!ok;
    }}
    function doKontieren(){{
      var pick=document.getElementById('kontier-dt-pick');
      var until=pick.value;
      if(!until)return;
      var btn=document.getElementById('kontier-btn');
      btn.disabled=true;btn.textContent='Wird kontiert…';
      fetch('/api/contour-until',{{method:'POST',headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{until:until}})
      }}).then(function(r){{return r.json();}})
      .then(function(d){{
        btn.textContent='{t("btn.booking")}';
        if(d.ok){{
          var dtxt=document.getElementById('kontier-dt-text').value;
          var toast=document.getElementById('kontier-toast');
          toast.textContent=(d.marked?d.marked+' {t("dashboard.days_booked")} '+dtxt+' {t("dashboard.booked_suffix")}':'{t("dashboard.all_booked")}');
          toast.style.display='block';
          setTimeout(function(){{location.reload();}},2200);
        }}else{{btn.disabled=false;}}
      }}).catch(function(){{btn.disabled=false;btn.textContent='{t("btn.booking")}';}});
    }}
    _validateKontier();
    </script>

    <div class="card" style="margin-bottom:12px;">
      <div style="color:var(--mu);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px;">{t("dashboard.absences")} {year}</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;">{ab_cells}</div>
      <div style="margin-top:10px;">
        <a class="btn" href="/absences" >{t("dashboard.all_absences")}</a>
      </div>
    </div>

    {_ret_widget}
    '''
    return render_template_string(layout(t("dashboard.title"), body, u, APP_VERSION, show_back=False))



# -------------------------
# Anwesenheit / Tagesstatus
# -------------------------


@core_bp.get("/presence")
@login_required
def presence_redirect():
    return redirect(url_for("balance.balance_view"))



@core_bp.get("/help")
@login_required
def help_page():
    from app import layout, APP_VERSION
    from auth import is_sysadmin, is_timemanager
    import html as _html
    u = current_user()
    lang = session.get('lang', 'de') if u else 'de'
    is_admin = bool(u and u.get("is_admin"))

    admin_section = ""
    _u_for_help = current_user()
    _is_sysadm_help = is_sysadmin(_u_for_help)
    if is_admin or is_timemanager(_u_for_help):
        _sysadmin_help = """
          <div class="help-entry">
            <b>🔧 Rollen: Systemadmin &amp; Zeitmanager</b>
            <p><b>Systemadmin</b> hat vollen Zugriff auf beide Admin-Bereiche. Kann Benutzer anlegen, löschen und Rollen vergeben. Zugriff auf Maileinstellungen, Bot, Backup, Update und Erscheinungsbild.</p>
            <p><b>Zeitmanager</b> hat Zugriff auf den Bereich <em>Benutzerübersichten</em>: Urlaubsübersicht, Abwesenheiten, Gleitzeitkonto, Zeitschemas, Urlaubsübertrag-Ausnahmen. Kann Identität normaler Nutzer annehmen (👤 Identität-Schaltfläche). Kein Zugriff auf Systemeinstellungen.</p>
            <p>Rollenvergabe: <em>Admin → Benutzerübersichten → Benutzer bearbeiten → Rolle</em> (nur Systemadmin). Beim Anlegen eines neuen Nutzers kann die Rolle direkt im Formular gewählt werden.</p>
          </div>
          <div class="help-entry">
            <b>👤 Admin ohne Zeiterfassung (Nur Verwaltung)</b>
            <p>Systemadmins und Zeitmanager können als <em>„Nur Verwaltung"</em> markiert werden. Diese Nutzer erfassen keine eigenen Arbeitszeiten: Die Übersicht, der Kalender und die Zeiterfassungs-Seiten sind für sie ausgeblendet – sie landen direkt im Admin-Bereich.</p>
            <p><b>Wo die Einstellung vorgenommen wird:</b></p>
            <ul>
              <li><b>Erstkonfiguration (Setup):</b> Beim allerersten Einrichten der App wird gefragt, ob der Systemadmin selbst Zeiten erfasst oder nur verwaltet.</li>
              <li><b>Onboarding (Schritt 0):</b> Wenn ein neuer Systemadmin das Onboarding durchläuft, erscheint als erster Schritt die Frage nach der Nutzungsart (Zeiterfassung oder Nur Verwaltung).</li>
              <li><b>Nachträglich:</b> Unter <em>Einstellungen → Admin-Einstellungen → Zeiterfassung aktiv/deaktiviert</em> (nur für den eigenen Account, nur Systemadmin). Für andere Nutzer: <em>Admin → Benutzerübersichten → Benutzer bearbeiten → „Nur Verwaltung"</em>.</li>
              <li><b>Beim Anlegen:</b> Im Formular „Neuer Nutzer" ist die Checkbox <em>„Nur Verwaltung"</em> verfügbar, sobald eine Admin-Rolle gewählt wird.</li>
            </ul>
          </div>
          <div class="help-entry">
            <b>Benutzerverwaltung (Systemadmin)</b>
            <p>Neue User anlegen, bestehende bearbeiten, Rollen vergeben und User löschen. Felder: Benutzername, Anzeigename, E-Mail, Rolle, Aktiv-Status, Arbeitsbeginn-Datum, Nur Verwaltung. Beim Anlegen kann direkt ein Passwort generiert und per E-Mail verschickt werden.</p>
          </div>
          <div class="help-entry">
            <b>Maileinstellungen (Systemadmin)</b>
            <p>SMTP-Server, Port, Absender und Anmeldedaten unter <em>Admin → Systemeinstellungen → Maileinstellungen</em>. Über <em>Test senden</em> prüfen.</p>
          </div>
          <div class="help-entry">
            <b>App-Label für Dev/Prod (Systemadmin)</b>
            <p>Unter <em>Admin → Systemeinstellungen → Erscheinungsbild</em> kann ein Label (z.B. „DEV" oder „PROD") mit Farbe gesetzt werden, das in der Kopfzeile angezeigt wird. Hilfreich um Dev- und Produktivsystem zu unterscheiden.</p>
          </div>
          <div class="help-entry">
            <b>Backup &amp; Restore (Systemadmin)</b>
            <p><b>Vollständiges Backup</b>: komplette Datenbank als SQLite-Datei.<br>
            <b>Einstellungen-Backup</b>: Mail- und Bot-Konfiguration als JSON (ohne Passwörter).<br>
            <b>User-Export/Import</b>: einzelne User mit Zeiteinträgen und Abwesenheiten übertragen.</p>
          </div>""" if _is_sysadm_help else ""

        admin_section = f"""
    <div class="acc help-acc">
      <button class="acc-hdr" type="button" onclick="haccToggle(this)">
        <span>🛠 Admin-Bereich</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body">
        <div class="acc-inner">
          {_sysadmin_help}
          <div class="help-entry">
            <b>Identität annehmen (Impersonation)</b>
            <p>Systemadmins und Zeitmanager können die Sicht eines normalen Nutzers übernehmen, um Einträge in dessen Namen zu prüfen oder zu erfassen.</p>
            <ul>
              <li><b>Systemadmin:</b> Im Admin-Bereich (<em>Benutzerverwaltung</em>-Tab) bei einem Nutzer auf <em>👤 Identität</em> klicken.</li>
              <li><b>Zeitmanager:</b> Im Bereich <em>Benutzerübersichten</em> bei einem normalen Nutzer auf <em>👤 Identität</em> klicken. Zeitmanager können nur Identitäten normaler Nutzer annehmen, nicht die anderer Admins.</li>
            </ul>
            <p>Alle Seiten werden dann aus Sicht dieses Nutzers angezeigt. Über den orangen Banner oben zurückwechseln.</p>
            <p>Im Telegram-Bot: <code>/als &lt;username&gt;</code> wechselt den Kontext, <code>/als ich</code> setzt zurück.</p>
          </div>
          <div class="help-entry">
            <b>Zeitschema-Verwaltung</b>
            <p>Pro User können mehrere Zeitschemata mit unterschiedlichen Gültig-ab-Daten hinterlegt werden. Unter <em>Admin → Benutzerübersichten → Zeitschemas → Bearbeiten</em>.</p>
          </div>
          <div class="help-entry">
            <b>Urlaubsübertrag-Ausnahme</b>
            <p>Unter <em>Admin → Benutzerübersichten → Urlaubsverwaltung</em> kann für einzelne User die 31.03.-Verfallsregel deaktiviert werden.</p>
          </div>
          <div class="help-entry">
            <b>Abschlüsse verwalten</b>
            <p>Gesperrte Perioden einsehen und entsperren unter <em>Admin → Benutzerübersichten → Abschlüsse</em>.</p>
          </div>
          <div class="help-entry">
            <b>Gleitzeitkonto Übersicht &amp; Limits</b>
            <p>Unter <em>Admin → Benutzerübersichten → Gleitzeitkonto</em> werden aktuelle Salden aller User angezeigt. Individuell können Plus- und Minus-Limits in Stunden sowie Benachrichtigungs-E-Mails konfiguriert werden.</p>
            <p>Intervalle: <b>Einmalig</b> (nur beim ersten Überschreiten), <b>Täglich</b>, <b>Wöchentlich</b>. Benachrichtigt wird der User selbst (E-Mail) und optional ein Vorgesetzter.</p>
          </div>
          <div class="help-entry">
            <b>Urlaubsübersicht &amp; Urlaubslimit</b>
            <p>Unter <em>Admin → Benutzerübersichten → Urlaubsübersicht</em> sind alle User mit Anspruch, Übertrag, Verbrauch und Resturlaub aufgelistet. Wenn Urlaubskontingent erschöpft ist, wird kein weiterer Urlaub eingetragen (Warn-Hinweis für Admin-Impersonation).</p>
          </div>
        </div>
      </div>
    </div>"""

    body = f"""
<style>
.acc{{border:1px solid var(--bd);border-radius:var(--r);margin-bottom:10px;overflow:hidden;background:var(--bg);}}
.acc-hdr{{width:100%;display:flex;justify-content:space-between;align-items:center;
  padding:14px 16px;background:var(--sf);border:none;cursor:pointer;
  font-size:15px;font-weight:600;color:var(--tx);text-align:left;gap:10px;}}
.acc-hdr:hover{{background:var(--bd);}}
.acc-hdr.open{{border-bottom:1px solid var(--bd);}}
.acc-arr{{font-size:12px;flex-shrink:0;color:var(--mu);}}
.acc-body{{max-height:0;overflow:hidden;transition:max-height .3s ease;}}
.acc-body.open{{max-height:99999px;}}
.acc-inner{{padding:16px;display:flex;flex-direction:column;gap:0;}}
.help-entry{{padding:12px 0;border-bottom:1px solid var(--bd);}}
.help-entry:last-child{{border-bottom:none;padding-bottom:0;}}
.help-entry b{{display:block;margin-bottom:4px;font-size:14px;}}
.help-entry p{{font-size:13px;color:var(--mu);margin:3px 0;line-height:1.5;}}
.help-entry code{{background:var(--bd);padding:1px 5px;border-radius:4px;font-size:12px;font-family:monospace;}}
.help-entry ul{{font-size:13px;color:var(--mu);padding-left:18px;margin:4px 0;line-height:1.6;}}
.info-box{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:13px;color:#1e40af;}}
.warn-box{{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:13px;color:#92400e;}}
@media(prefers-color-scheme:dark){{
  .info-box{{background:#1e3a5f;border-color:#1e40af;color:#93c5fd;}}
  .warn-box{{background:#3d2b00;border-color:#d97706;color:#fcd34d;}}
}}
</style>
<script>
function haccToggle(btn){{
  var body=btn.nextElementSibling;
  var arr=btn.querySelector('.acc-arr');
  var op=body.classList.contains('open');
  body.classList.toggle('open',!op);
  btn.classList.toggle('open',!op);
  if(arr)arr.textContent=op?'▼':'▲';
}}
function filterHelp(q){{
  q=q.toLowerCase().trim();
  document.querySelectorAll('.help-acc').forEach(function(acc){{
    var txt=acc.textContent.toLowerCase();
    var match=!q||txt.includes(q);
    acc.style.display=match?'':'none';
    if(q&&match){{
      var body=acc.querySelector('.acc-body');
      var btn=acc.querySelector('.acc-hdr');
      var arr=acc.querySelector('.acc-arr');
      if(body&&!body.classList.contains('open')){{
        body.classList.add('open');
        if(btn)btn.classList.add('open');
        if(arr)arr.textContent='▲';
      }}
    }}
  }});
}}
</script>

<h2 style="margin:0 0 14px 0;font-size:18px;">❓ Hilfe</h2>

<div style="margin-bottom:16px;">
  <input type="search" id="help-search" placeholder="Hilfe durchsuchen …"
         style="width:100%;max-width:420px;"
         oninput="filterHelp(this.value)">
</div>

<!-- 1. Übersicht -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>🏠 Übersicht (Startseite)</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Gleitzeitkonto-Widget</b>
        <p>Zeigt den aktuellen Gleitzeitsaldo: <b style="color:#16a34a;">grün</b> = Plusstunden, <b style="color:#dc2626;">rot</b> = Minusstunden. Der Saldo berechnet sich als Summe aller (Ist − Soll)-Tage seit Arbeitsbeginn im laufenden Jahr plus dem eingetragenen Startsaldo.</p>
      </div>
      <div class="help-entry">
        <b>Resturlaub</b>
        <p>Zeigt: Jahresanspruch + wirksamer Übertrag − bereits genommene Urlaubstage. Nur Arbeitstage zählen (Wochenenden und Feiertage werden nicht abgezogen).</p>
        <div class="warn-box">⚠️ <b>Übertrag-Regel:</b> Nicht genutzter Jahresurlaub verfällt am 31.03. des Folgejahres. Voraussetzung: Der Urlaub muss bis spätestens 31.03. <em>begonnen</em> haben. Ausnahmen können vom Admin eingerichtet werden.</div>
      </div>
      <div class="help-entry">
        <b>Fehlende Einträge</b>
        <p>Arbeitstage (laut Zeitschema), für die weder ein Zeiteintrag noch eine Abwesenheit vorhanden ist und die in der Vergangenheit liegen. Der heutige Tag zählt nicht als fehlend.</p>
      </div>
      <div class="help-entry">
        <b>Kontierung</b>
        <p>Zeigt, wie viele erfasste Arbeitstage noch nicht auf Projekte/Kostenstellen gebucht (kontiert) wurden. Nur sichtbar wenn Kontierung in den Einstellungen aktiviert ist.</p>
      </div>
      <div class="help-entry">
        <b>Abwesenheitskarte</b>
        <p>Kompakte Übersicht über laufende und bevorstehende Abwesenheiten (Urlaub, Krank, Flextag, Verdi usw.) im aktuellen Zeitraum.</p>
      </div>
      <div class="help-entry">
        <b>Rentencountdown</b>
        <p>Zeigt die verbleibende Zeit bis zum Renteneintritt (Jahre, Monate, Tage, Arbeitstage). Nur sichtbar wenn ein Geburtsdatum in den Einstellungen hinterlegt ist. Das Eintrittsalter ist in <em>Einstellungen → Persönliche Einstellungen</em> konfigurierbar (Standard: 67).</p>
      </div>
    </div>
  </div>
</div>

<!-- 2. Zeiterfassung -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>⏱ Zeiterfassung</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Tagesansicht aufrufen</b>
        <p>Im Kalender auf einen Tag klicken. Alternativ über die Übersicht-Kachel <em>Heute</em> oder direkt über den Telegram-Bot-Befehl <code>/heute</code>.</p>
      </div>
      <div class="help-entry">
        <b>Zeitblock erfassen</b>
        <p>In der Tagesansicht: <em>Kommen</em> (Beginn), <em>Gehen</em> (Ende) und optionale <em>Pause</em> in Minuten eintragen. Mehrere Blöcke pro Tag möglich (z.B. Kernzeit + Überstunden). Jeder Block wird separat gespeichert und im Gleitzeitkonto summiert.</p>
        <div class="info-box">ℹ️ Zeiten werden in <b>15-Minuten-Schritten</b> erfasst. Eingaben werden auf den nächsten Viertelstundenwert gerundet.</div>
      </div>
      <div class="help-entry">
        <b>Mehrere Zeitblöcke pro Tag</b>
        <p>Einfach einen weiteren Block hinzufügen. Das Delta und der Saldo im Bericht berechnen sich aus der <em>Summe aller Blöcke</em> des Tages abzüglich des Solls.</p>
      </div>
      <div class="help-entry">
        <b>Zeiten bearbeiten und löschen</b>
        <p>In der Tagesansicht neben dem Block auf das Bearbeiten-Symbol oder <em>Löschen</em> klicken. Im Kalender über das Kontextmenü (drei Punkte) des Tages.</p>
      </div>
      <div class="help-entry">
        <b>Wochenende / Feiertag</b>
        <p>Normalerweise kein Soll an Wochenenden und Feiertagen. Wenn dennoch gearbeitet wurde, kann ein Zeitblock erfasst werden – der Soll-Wert bleibt 0, das Delta entspricht den tatsächlichen Stunden.</p>
      </div>
    </div>
  </div>
</div>

<!-- 3. Kalender -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>📅 Kalender</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Navigation</b>
        <p>Mit den Pfeilen ‹ › zwischen Monaten wechseln. Auf den Monatsnamen klicken um direkt zu einem Monat zu springen.</p>
      </div>
      <div class="help-entry">
        <b>Listenansicht</b>
        <p>Wechsel zwischen Kachel- und Listenansicht über den Umschalter oben rechts. Die Listenansicht eignet sich besonders für lange Zeiträume.</p>
      </div>
      <div class="help-entry">
        <b>Farbkodierung und Symbole</b>
        <ul>
          <li>🟡 <b>Bernstein-Punkt</b> = Tag ist kontiert</li>
          <li>❌ <b>Rotes X</b> = fehlender Zeiteintrag (Arbeitstag ohne Erfassung)</li>
          <li>🟢 <b>Grünes Badge</b> = Urlaub</li>
          <li>✈ <b>Flugzeug</b> = Dienstreise eingetragen</li>
          <li>🟦 <b>Blauer Hintergrund</b> = heute</li>
        </ul>
      </div>
      <div class="help-entry">
        <b>Kontextmenü (drei Punkte)</b>
        <p>Klick auf die drei Punkte eines Tages öffnet ein Menü mit: Zeiteintrag erfassen, Abwesenheit anlegen, Dienstreise eintragen und (falls vorhanden) bestehende Einträge bearbeiten oder löschen.</p>
      </div>
    </div>
  </div>
</div>

<!-- 4. Gleitzeitkonto -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>📊 Gleitzeitkonto</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Saldo-Berechnung</b>
        <p>Saldo = Startsaldo + Summe aller (Ist − Soll) seit Arbeitsbeginn im laufenden Jahr. Der Saldo wird täglich fortgeschrieben. Zukünftige Tage fließen nicht ein.</p>
      </div>
      <div class="help-entry">
        <b>Spalten im Bericht</b>
        <ul>
          <li><b>Soll</b> = vertraglich vereinbarte Arbeitszeit laut Zeitschema</li>
          <li><b>Ist</b> = tatsächlich erfasste Zeit (Summe aller Blöcke)</li>
          <li><b>Delta</b> = Ist − Soll für diesen Tag (grün = Plus, rot = Minus)</li>
          <li><b>Saldo</b> = kumulierter Stand bis einschließlich dieses Tages</li>
        </ul>
      </div>
      <div class="help-entry">
        <b>Flextag-Abzug</b>
        <p>An einem Flextag ist das Soll = 0. Dennoch wird die <em>eigentlich geplante</em> Sollzeit vom Gleitzeitkonto abgezogen – der Flextag „verbraucht" Gleitzeit. Dadurch ist ein Flextag wirtschaftlich äquivalent zu einem Urlaubstag, belastet aber das Urlaubskonto nicht.</p>
      </div>
      <div class="help-entry">
        <b>Manuelle Korrekturen</b>
        <p>Zeitmanager können manuelle Gutschriften oder Abzüge anlegen – z.B. für Überstunden-Auszahlungen oder Korrekturbuchungen. Korrekturen erscheinen als eigene Zeile in der Gleitzeitkonto-Ansicht und fließen in den Saldo ein.</p>
        <p>Anlegen unter <em>Admin → Benutzerübersichten → Gleitzeitkonto → Korrekturen</em>. Jede Korrektur hat Datum, Betrag in Minuten und einen Freitext-Grund.</p>
      </div>
      <div class="help-entry">
        <b>Bericht als RTF-Datei</b>
        <p>Über den Telegram-Bot-Befehl <code>/bericht</code> bzw. <code>/bericht jahr</code> wird ein RTF-Dokument mit farbiger Darstellung (grün/rot) erzeugt und zugeschickt, sobald der Bericht länger als eine Bildschirmseite wäre.</p>
      </div>
    </div>
  </div>
</div>

<!-- 5. Abwesenheiten -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>🏖 Abwesenheiten</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Urlaub</b>
        <p>Zählt Arbeitstage gemäß Zeitschema (ohne Wochenenden und Feiertage). Wirkt sich auf das Urlaubskonto aus. Soll = 0, kein Gleitzeitabzug.</p>
        <div class="warn-box">⚠️ <b>Übertrag-Regel:</b> Nicht genutzter Übertrag aus dem Vorjahr verfällt am 31.03. Der Urlaub muss bis spätestens 31.03. begonnen haben.</div>
      </div>
      <div class="help-entry">
        <b>Krank</b>
        <p>Keine Auswirkung auf Gleitzeit oder Urlaubskonto. Soll = 0 für den Krankheitszeitraum.</p>
      </div>
      <div class="help-entry">
        <b>Flextag</b>
        <p>Freizeit aus dem Gleitzeitkonto. Soll = 0, aber die <em>eigentlich geplante</em> Arbeitszeit wird vom Gleitzeitkonto abgezogen. Kein Urlaubsverbrauch.</p>
        <div class="info-box">ℹ️ Flextag im Telegram-Bot: <code>/als ich</code> → Eingabe "Am 15.5. Flextag"</div>
      </div>
      <div class="help-entry">
        <b>Verdi / Sonstige</b>
        <p>Gewerkschaftstage (Verdi) oder andere Sonderabwesenheiten. Analog zu Krank: Soll = 0, keine Gleitzeitwirkung. Der Kommentar wird als Bezeichnung angezeigt.</p>
      </div>
      <div class="help-entry">
        <b>Neue Abwesenheit anlegen</b>
        <p>Über <em>Abwesenheiten → Neu</em> oder im Kalender über das Kontextmenü (drei Punkte) eines Tages. Alternativ per Telegram-Bot-Freitext: <em>"Urlaub vom 1.7. bis 15.7."</em></p>
      </div>
    </div>
  </div>
</div>

<!-- 6. Teams/Abteilungen -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>👥 Teams / Abteilungen</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Wozu dienen Teams?</b>
        <p>Teams / Abteilungen gruppieren Nutzer. Zeitmanager und Genehmiger können auf bestimmte Teams eingeschränkt werden, sodass sie nur die Mitglieder ihrer Teams sehen und verwalten.</p>
      </div>
      <div class="help-entry">
        <b>Team-Zuordnung</b>
        <p>Ein Nutzer kann mehreren Teams angehören. Das <b>Haupt-Team</b> wird im Kalender und in Übersichten angezeigt. Verwaltung unter <em>Admin → Benutzerübersichten → Teams-Zuordnung</em>.</p>
      </div>
      <div class="help-entry">
        <b>Team-Kalender</b>
        <p>Zeitmanager und Genehmiger sehen einen Team-Kalender: wer aus ihrem Team ist wann abwesend. Nützlich bei der Prüfung von Abwesenheitsanträgen.</p>
      </div>
      <div class="help-entry">
        <b>Einschränkung auf Teams</b>
        <p>Über <em>Admin → Benutzerübersichten → Benutzer bearbeiten → Team-Einschränkung</em> kann ein Zeitmanager oder Genehmiger auf bestimmte Teams begrenzt werden – er sieht dann nur die Mitglieder dieser Teams.</p>
      </div>
    </div>
  </div>
</div>

<!-- 7. Abwesenheits-Genehmigung -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>✅ Abwesenheits-Genehmigung</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Genehmiger-Rolle aktivieren</b>
        <p>In <em>Admin → Benutzerübersichten → Benutzer bearbeiten</em> kann ein Nutzer als Genehmiger markiert werden (<em>„Ist Genehmiger"</em>). Genehmiger erhalten Benachrichtigungen bei neuen Anträgen.</p>
      </div>
      <div class="help-entry">
        <b>Genehmigungspflicht pro User konfigurieren</b>
        <p>Pro Nutzer lässt sich festlegen: welcher Genehmiger zuständig ist und welche Abwesenheitstypen genehmigungspflichtig sind. Einstellung unter <em>Admin → Benutzerübersichten → Benutzer bearbeiten → Genehmigung</em>.</p>
      </div>
      <div class="help-entry">
        <b>Genehmigungsübersicht (/approvals)</b>
        <p>Genehmiger sehen unter <em>/approvals</em> alle offenen Anträge sowie vergangene Entscheidungen. Bei Klick auf einen Antrag ist der Team-Kalender sichtbar – inklusive Überschneidungswarnung wenn andere Teammitglieder im gleichen Zeitraum abwesend sind.</p>
      </div>
      <div class="help-entry">
        <b>Auswirkung auf Gleitzeitkonto</b>
        <p><b>Pending</b>-Abwesenheiten werden im Gleitzeitkonto <em>nicht</em> berücksichtigt. Erst nach Genehmigung ist die Abwesenheit wirksam und reduziert das Soll.</p>
        <div class="warn-box">⚠️ Abgelehnte oder ausstehende Abwesenheiten zählen nicht als Urlaubsverbrauch und beeinflussen den Saldo nicht.</div>
      </div>
      <div class="help-entry">
        <b>Benachrichtigungen</b>
        <p>Beim Einreichen eines Antrags: Mail + Telegram an den Genehmiger.<br>
        Bei Genehmigung oder Ablehnung: Mail + Telegram an den Antragsteller (mit Ablehnungsgrund).</p>
      </div>
      <div class="help-entry">
        <b>Telegram-Bot-Befehle (Genehmiger)</b>
        <ul>
          <li><code>/genehmigungen</code> — offene Anträge anzeigen</li>
          <li><code>genehmigen &lt;ID&gt;</code> — Antrag genehmigen</li>
          <li><code>ablehnen &lt;ID&gt; &lt;Grund&gt;</code> — Antrag ablehnen mit Begründung</li>
        </ul>
      </div>
    </div>
  </div>
</div>

<!-- 8. Besetzungsplanung -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>📋 Besetzungsplanung</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Feature aktivieren</b>
        <p>Die Besetzungsplanung ist ein optionales Feature. Aktivierung unter <em>Admin → Systemeinstellungen → Features → Besetzungsplanung</em>. Nach Aktivierung erscheint der Menüpunkt für Zeitmanager und Genehmiger.</p>
      </div>
      <div class="help-entry">
        <b>Pläne anlegen</b>
        <p>Pro Team können mehrere Besetzungspläne angelegt werden (z.B. „Regelbetrieb", „Sommerschicht"). Nur aktive Pläne werden in der Ansicht angezeigt.</p>
      </div>
      <div class="help-entry">
        <b>Slots definieren</b>
        <p>Ein Slot beschreibt einen Zeitraum mit Mindestbesetzung. Verfügbare Slot-Typen:</p>
        <ul>
          <li><b>Täglich</b> — gilt jeden Arbeitstag</li>
          <li><b>Wochentage</b> — gilt nur an bestimmten Wochentagen</li>
          <li><b>nth_weekday</b> — z.B. „1. Montag im Monat"</li>
          <li><b>Datum</b> — festes Einzeldatum</li>
        </ul>
        <p>Je Slot: Beginn- und Endzeit, Mindestbesetzung (<em>min_staff</em>), Mitarbeiter-Zuordnung.</p>
      </div>
      <div class="help-entry">
        <b>Wochenansicht</b>
        <p>Mini-Zeitleisten je Mitarbeiter für eine Woche. Zeigt auf einen Blick wer wann eingeplant ist. Anwesenheitszeiten werden aus dem Zeitschema des Mitarbeiters übernommen (wenn Sync aktiviert).</p>
      </div>
      <div class="help-entry">
        <b>Monatsansicht</b>
        <p>Zeigt pro Tag die tatsächliche Besetzungszahl je Slot. Tage mit Unterbesetzung (Ist &lt; min_staff) werden hervorgehoben. Klick auf einen Tag öffnet das Tagesdetail.</p>
      </div>
      <div class="help-entry">
        <b>Zeitschema-Sync</b>
        <p>In den Zeitschema-Einstellungen eines Users kann „Sync in Besetzungsplan" aktiviert werden. Die Arbeitszeiten des Schemas werden dann automatisch als Anwesenheit in den verknüpften Plan übernommen.</p>
      </div>
    </div>
  </div>
</div>

<!-- 9. Dienstreisen -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>✈ Dienstreisen</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Was ist eine Dienstreise?</b>
        <p>Ein Informationseintrag, der anzeigt, dass du an bestimmten Tagen auf Dienstreise warst. <b>Wichtig:</b> Die Arbeitszeit wird <em>nicht</em> automatisch erfasst – Zeitblöcke müssen separat eingetragen werden.</p>
      </div>
      <div class="help-entry">
        <b>Felder</b>
        <p>Von-/Bis-Datum und Reiseziel (Freitext). Das Reiseziel erscheint im Kalender als Tooltip beim ✈-Symbol.</p>
      </div>
      <div class="help-entry">
        <b>Darstellung im Kalender</b>
        <p>Tage mit Dienstreise werden mit einem ✈-Symbol markiert. Im Gleitzeitkonto-Bericht erscheint das Ziel in der Zeitspalte.</p>
      </div>
    </div>
  </div>
</div>

<!-- 10. Kontierung -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>📋 Kontierung</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Was bedeutet kontieren?</b>
        <p>Kontierung = Buchung der erfassten Arbeitszeit auf Projekte oder Kostenstellen. Erst nach der Kontierung gilt ein Arbeitstag als vollständig abgeschlossen.</p>
      </div>
      <div class="help-entry">
        <b>Einzeln kontieren</b>
        <p>In der Tagesansicht den Button <em>Kontieren</em> klicken. Der Tag erhält daraufhin den 🟡 Bernstein-Punkt im Kalender.</p>
      </div>
      <div class="help-entry">
        <b>Bulk-Kontierung</b>
        <p>Unter <em>Kontierung</em> mehrere Tage gleichzeitig auswählen und gemeinsam buchen. Praktisch nach Urlaub oder längeren Abwesenheiten.</p>
      </div>
      <div class="help-entry">
        <b>Aktivieren / Deaktivieren</b>
        <p>In den Einstellungen unter <em>Kontierung</em> kann die Funktion mit einem Startdatum aktiviert werden. Tage vor dem Startdatum werden nicht zur Kontierung angezeigt.</p>
      </div>
    </div>
  </div>
</div>

<!-- 11. Abschlüsse -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>🔒 Abschlüsse</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Monatsabschluss</b>
        <p>Sperrt alle Zeiteinträge und Abwesenheiten des Monats. Danach sind keine Änderungen mehr möglich. Der Saldo wird eingefroren.</p>
      </div>
      <div class="help-entry">
        <b>Jahresabschluss</b>
        <p>Sperrt alle Monate des Jahres auf einmal. Sinnvoll zum Jahresende nach vollständiger Prüfung.</p>
        <div class="info-box">ℹ️ Nur Monate ab dem eingestellten Arbeitsbeginn müssen abgeschlossen werden.</div>
      </div>
      <div class="help-entry">
        <b>Entsperren</b>
        <p>Nur Admins können gesperrte Perioden wieder öffnen. Unter <em>Admin → Abschlüsse</em> die gewünschte Periode entsperren.</p>
      </div>
    </div>
  </div>
</div>

<!-- 12. Einstellungen -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>⚙️ Einstellungen</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Persönliche Einstellungen</b>
        <p><b>Anzeigename</b>: erscheint im Header und in Berichten. Leer = Benutzername wird verwendet.<br>
        <b>E-Mail</b>: für Benachrichtigungen.<br>
        <b>Geburtsdatum</b>: Wenn hinterlegt, wird auf der Übersicht ein Rentencountdown angezeigt.<br>
        <b>Renteneintrittsalter</b>: Standard 67 Jahre. Bereich 60–72. Bestimmt das Zieldatum des Countdowns.<br>
        <b>Passwort</b>: Mindestlänge 6 Zeichen, aktuelles Passwort erforderlich.<br>
        <b>Telegram-ID</b>: Für den Bot-Zugriff (siehe Telegram-Bot-Bereich).</p>
      </div>
      <div class="help-entry">
        <b>Urlaub</b>
        <p><b>Jahresanspruch</b>: Gesamte Urlaubstage für das Jahr (auch halbe Tage möglich, z.B. 27.5).<br>
        <b>Übertrag</b>: Resturlaub aus dem Vorjahr. Verfällt am 31.03. sofern keine Admin-Ausnahme gilt.</p>
      </div>
      <div class="help-entry">
        <b>Zeitschema</b>
        <p><b>Wochenmodus</b>: Gleiche tägliche Soll-Zeit, verteilt auf alle Arbeitstage der Woche.<br>
        <b>Tagesmodus</b>: Unterschiedliche Soll-Zeit pro Wochentag (z.B. Mo–Do 8h, Fr 6h).<br>
        <b>Arbeitstage</b>: Welche Wochentage als Arbeitstage zählen (Standard: Mo–Fr).<br>
        <b>Gültig ab</b>: Mehrere Schemata mit unterschiedlichen Startdaten sind möglich – das zuletzt gültige wird je Tag angewendet.<br>
        <b>Mehrere Zeitblöcke pro Tag</b>: Pro Schema-Tag können beliebig viele Zeitblöcke hinterlegt werden (z.B. Kernzeit + Nachmittagsschicht).<br>
        <b>Sync in Besetzungsplan</b>: Optional – Zeitschema-Blöcke werden automatisch als Anwesenheit in den verknüpften Besetzungsplan übernommen.</p>
      </div>
      <div class="help-entry">
        <b>Schema bearbeiten (Nutzer)</b>
        <p>Wenn vom Admin freigegeben (<em>Selbst bearbeiten erlaubt</em>), kann der Nutzer sein Zeitschema unter <em>Einstellungen → Zeitschema</em> selbst anpassen.</p>
      </div>
      <div class="help-entry">
        <b>Kontierung</b>
        <p>Funktion aktivieren und ein Startdatum angeben. Tage ab diesem Datum müssen kontiert werden. Deaktivierung setzt alle unkontiertenTage zurück.</p>
      </div>
    </div>
  </div>
</div>

<!-- 13. Kalender-Integration -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>📅 Kalender-Integration</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Kalender-Export (.ics Download &amp; webcal-Abo)</b>
        <p>Unter <em>Einstellungen → Kalender-Integration</em> können Abwesenheiten als Kalender-Datei exportiert oder als Live-Abonnement eingerichtet werden.</p>
        <ul>
          <li><b>.ics herunterladen</b>: Einmalige Momentaufnahme. Öffnen importiert die Einträge in Apple Kalender, Google, Outlook usw.</li>
          <li><b>webcal:// abonnieren</b>: Kalender-App fragt regelmäßig neue Daten ab – Änderungen erscheinen automatisch.</li>
          <li><b>Präfix</b>: Optionaler Text vor jedem Eintrag, z.B. <code>Uwe:</code> oder <code>🏢</code>. Nützlich wenn mehrere Personen denselben Kalender nutzen.</li>
          <li><b>Token zurücksetzen</b>: Macht alle bestehenden Abonnements ungültig und generiert eine neue URL.</li>
        </ul>
        <div class="info-box">ℹ️ Unterstützte Kalender-Apps: Apple Kalender, Google Kalender, Outlook, sowie alle Apps mit iCal-Standard-Unterstützung.</div>
      </div>
      <div class="help-entry">
        <b>🍎 Apple iCloud Synchronisation</b>
        <p>Abwesenheiten werden automatisch in einen iCloud-Kalender geschrieben – beim Erstellen, Bearbeiten und Löschen.</p>
        <p><b>Voraussetzungen:</b></p>
        <ul>
          <li><b>Apple ID</b>: deine iCloud-E-Mail-Adresse</li>
          <li><b>App-spezifisches Passwort</b>: unter <a href="https://appleid.apple.com" target="_blank">appleid.apple.com</a> → Anmelden → Sicherheit → App-spezifische Passwörter → Neues Passwort generieren. <em>Nicht</em> dein normales Apple-Passwort verwenden.</li>
          <li><b>Kalender-Name</b>: exakter Name des iCloud-Kalenders (Groß-/Kleinschreibung beachten), z.B. <code>Arbeit</code></li>
        </ul>
        <p><b>Mehrere Nutzer</b>: Verschiedene Personen können in denselben Kalender schreiben – mit unterschiedlichem Präfix (z.B. <code>Uwe:</code> / <code>Steffi:</code>) sind Einträge klar zuzuordnen.</p>
        <p>Mit <em>Verbindung testen</em> wird die Verbindung zu iCloud geprüft und verfügbare Kalender angezeigt. <em>Alle synchronisieren</em> schreibt alle vorhandenen Abwesenheiten einmalig in den Kalender – sinnvoll bei der Ersteinrichtung.</p>
        <div class="warn-box">⚠️ Das App-Passwort wird verschlüsselt gespeichert. Leer lassen beim Speichern bedeutet: bestehendes Passwort bleibt unverändert.</div>
      </div>
      <div class="help-entry">
        <b>Home Assistant CalDAV</b>
        <p>Die CalDAV-URL aus den Einstellungen kann direkt in Home Assistant eingetragen werden.</p>
        <ul>
          <li>In HA: <em>Einstellungen → Integrationen → Kalender → CalDAV</em></li>
          <li><b>URL</b>: <code>https://zeiten.firma.de/caldav/TOKEN/</code> (aus Einstellungen kopieren)</li>
          <li>Kein Username/Passwort nötig – der Token übernimmt die Authentifizierung</li>
          <li>Alternativ: Basic Auth wählen (Einstellungen → Authentifizierung) und HA-Zugangsdaten eintragen</li>
        </ul>
        <div class="info-box">ℹ️ Die externe Server-URL muss unter <em>Admin → Systemeinstellungen → Regionale Einstellungen → Externe Server-URL</em> korrekt eingetragen sein, damit die CalDAV-URLs stimmen.</div>
      </div>
    </div>
  </div>
</div>

<!-- 14. Telegram-Bot -->
<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>🤖 Telegram-Bot</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body">
    <div class="acc-inner">
      <div class="help-entry">
        <b>Einrichtung</b>
        <p>1. In Telegram <b>@userinfobot</b> eine beliebige Nachricht schicken → Bot antwortet mit deiner Telegram-ID (eine rein numerische Zahl).<br>
        2. Diese ID unter <em>Einstellungen → Telegram-ID</em> eintragen.<br>
        3. Dem Bot eine Nachricht schicken (z.B. <code>/start</code>) – ab sofort sind alle Befehle verfügbar.</p>
      </div>
      <div class="help-entry">
        <b>Befehle</b>
        <ul>
          <li><code>/saldo</code> — aktueller Gleitzeitsaldo</li>
          <li><code>/urlaub</code> — Urlaubsübersicht mit Anspruch, Übertrag, Verbrauch</li>
          <li><code>/heute</code> — heutige Zeiteinträge und Tagessaldo</li>
          <li><code>/fehlend</code> — Liste fehlender Einträge im laufenden Jahr</li>
          <li><code>/kontierung</code> — unkontierte Tage und letzter Kontierungsstand</li>
          <li><code>/abwesenheiten</code> — Abwesenheitsliste aktuelles Jahr</li>
          <li><code>/abwesenheiten 2025</code> — Abwesenheitsliste für bestimmtes Jahr</li>
          <li><code>/bericht</code> — Gleitzeitkonto aktueller Monat (kurz: Textnachricht, lang: RTF-Datei)</li>
          <li><code>/bericht jahr</code> — Gleitzeitkonto ganzes Jahr als RTF</li>
          <li><code>/bericht 5</code> — Gleitzeitkonto Mai (beliebiger Monat 1–12)</li>
          <li><code>/bericht 5 2025</code> — Gleitzeitkonto Mai 2025</li>
          <li><code>/user</code> — aktuell aktiver Benutzer (relevant für Admins)</li>
        </ul>
      </div>
      <div class="help-entry">
        <b>Freitext-Eingabe</b>
        <p>Einfach schreiben – der Bot versteht natürlichsprachige Eingaben:</p>
        <ul>
          <li><em>"Heute von 7:30 bis 13 gearbeitet"</em></li>
          <li><em>"Am 15.5. von 8 bis 16 Uhr"</em></li>
          <li><em>"Urlaub vom 1.7. bis 15.7."</em></li>
          <li><em>"Urlaub 1.7.-15.7."</em></li>
          <li><em>"Am 3.8. Flextag"</em></li>
          <li><em>"Krank von 10.6. bis 12.6."</em></li>
        </ul>
        <p>Zeiten werden auf 15-Minuten-Schritte gerundet. Wenn für den Tag bereits ein Eintrag vorhanden ist, fragt der Bot nach Bestätigung (ja/nein).</p>
      </div>
      <div class="help-entry">
        <b>Abend-Erinnerung</b>
        <p>Der Bot schickt abends automatisch eine Nachricht, wenn für den heutigen Arbeitstag noch kein Zeiteintrag und keine Abwesenheit vorhanden ist.</p>
        <ul>
          <li><b>Voraussetzung:</b> Telegram-ID unter <em>Einstellungen → Telegram-ID</em> hinterlegt</li>
          <li><b>Aktivieren:</b> <em>Einstellungen → Persönliche Einstellungen → 📱 Telegram Erinnerung</em> → Toggle einschalten</li>
          <li><b>Uhrzeit:</b> Individuell einstellbar zwischen 15:00 und 23:00 Uhr (Standard: 20:00)</li>
          <li><b>Nur an echten Arbeitstagen</b> – keine Erinnerung an Wochenenden, Feiertagen oder gesperrten Perioden</li>
          <li><b>Kein Wizard</b> wenn bereits Zeiten oder eine Abwesenheit für heute eingetragen sind</li>
        </ul>
      </div>
      <div class="help-entry">
        <b>Wizard-Ablauf (Abend-Erinnerung)</b>
        <p>Nach Erhalt der Erinnerung läuft ein geführter Dialog:</p>
        <ul>
          <li>Bot fragt: <em>"Heute gearbeitet?"</em> → Buttons <b>✅ Ja, gearbeitet</b> oder <b>🏠 Nein</b></li>
          <li><b>Bei Ja:</b> Zeiten per Freitext eingeben, z.B. <em>"7:30 bis 16:00"</em> oder <em>"8 bis 13 Pause 30"</em> – genau wie die normale Bot-Eingabe</li>
          <li><b>Bei Nein:</b> Abwesenheitstyp auswählen:<br>
            🏖 Urlaub · 🤒 Krank · 💆 Flextag · 🔧 Verdi · ✈ Dienstreise · ❌ Abbrechen</li>
          <li><b>Bei Dienstreise:</b> Zielort als Freitext eingeben – wird in den Dienstreisen eingetragen</li>
          <li>Der Dialog läuft <b>2 Stunden</b>, danach kann direkt per Freitext eingetragen werden</li>
        </ul>
      </div>
      <div class="help-entry">
        <b>Erinnerung per Bot-Befehl steuern</b>
        <p>Alternativ zur App-Einstellung direkt im Bot-Chat:</p>
        <ul>
          <li><code>erinnerung</code> — aktuellen Status anzeigen</li>
          <li><code>erinnerung an</code> — aktivieren mit Standard 20:00 Uhr</li>
          <li><code>erinnerung aus</code> — deaktivieren</li>
          <li><code>erinnerung 19:30</code> — Uhrzeit ändern (und aktivieren)</li>
          <li><code>erinnerung an 18:00</code> — aktivieren mit individueller Uhrzeit</li>
        </ul>
        <div class="info-box">ℹ️ Uhrzeit-Änderungen gelten sofort – die Einstellung wird in der App unter <em>Einstellungen → Telegram Erinnerung</em> angezeigt.</div>
      </div>
      <div class="help-entry">
        <b>Admin-Befehle</b>
        <ul>
          <li><code>/als &lt;username&gt;</code> — Kontext zu anderem User wechseln (alle folgenden Befehle gelten für diesen User)</li>
          <li><code>/als ich</code> — eigenen Kontext wiederherstellen</li>
          <li><code>/users</code> — alle aktiven User auflisten</li>
          <li><code>/alssaldo &lt;username&gt;</code> — Saldo eines anderen Users</li>
          <li><code>/alsurlaub &lt;username&gt;</code> — Urlaub eines anderen Users</li>
          <li><code>/alsabw &lt;username&gt;</code> — Abwesenheiten eines anderen Users</li>
        </ul>
      </div>
    </div>
  </div>
</div>

{admin_section}
"""
    if lang == 'en':
        _sysadmin_help_en = ""
        if _is_sysadm_help:
            _sysadmin_help_en = """
          <div class="help-entry">
            <b>🔧 Roles: System Admin &amp; Time Manager</b>
            <p><b>System admin</b> has full access to both admin areas. Can create, delete and assign roles to users. Access to mail settings, bot, backup, update and appearance.</p>
            <p><b>Time manager</b> has access to the <em>User overviews</em> area: vacation overview, absences, flex time, schedules, carryover exceptions. Can impersonate regular users (👤 Impersonate). No access to system settings.</p>
            <p>Role assignment: <em>Admin → User overviews → Edit user → Role</em> (system admin only).</p>
          </div>
          <div class="help-entry">
            <b>👤 Admin without time tracking (Admin only)</b>
            <p>System admins and time managers marked as <em>"Admin only"</em> do not record their own hours: the overview, calendar and time tracking pages are hidden — they land directly in the admin area.</p>
          </div>
          <div class="help-entry">
            <b>User management (System admin)</b>
            <p>Create new users, edit existing ones, assign roles and delete users. When creating a user, a password can be generated and sent by e-mail directly.</p>
          </div>
          <div class="help-entry">
            <b>Mail settings (System admin)</b>
            <p>SMTP server, port, sender and credentials under <em>Admin → System settings → Mail settings</em>. Use <em>Send test</em> to verify.</p>
          </div>
          <div class="help-entry">
            <b>Backup &amp; Restore (System admin)</b>
            <p><b>Full backup</b>: complete database as SQLite file.<br>
            <b>Settings backup</b>: mail and bot configuration as JSON (without passwords).<br>
            <b>User export/import</b>: transfer individual users with time entries and absences.</p>
          </div>"""
        admin_section_en = ""
        if is_admin or is_timemanager(_u_for_help):
            admin_section_en = f"""
    <div class="acc help-acc">
      <button class="acc-hdr" type="button" onclick="haccToggle(this)">
        <span>🛠 Admin Area</span><span class="acc-arr">▼</span>
      </button>
      <div class="acc-body">
        <div class="acc-inner">
          {_sysadmin_help_en}
          <div class="help-entry">
            <b>Impersonation</b>
            <p>System admins and time managers can view the app from another user's perspective to check or record entries on their behalf.</p>
            <ul>
              <li><b>System admin:</b> In <em>Admin → User management</em>, click 👤 next to a user.</li>
              <li><b>Time manager:</b> In <em>User overviews</em>, click 👤 next to a regular user. Time managers cannot impersonate other admins.</li>
            </ul>
            <p>Use the orange banner at the top to switch back. In the bot: <code>/als &lt;username&gt;</code> / <code>/als ich</code>.</p>
          </div>
          <div class="help-entry">
            <b>Schedule management</b>
            <p>Multiple schedules with different valid-from dates per user. Under <em>Admin → User overviews → Schedules → Edit</em>.</p>
          </div>
          <div class="help-entry">
            <b>Vacation carryover exception</b>
            <p>Under <em>Admin → User overviews → Vacation</em>, disable the 31 March expiry rule for individual users.</p>
          </div>
          <div class="help-entry">
            <b>Flex time overview &amp; limits</b>
            <p>Under <em>Admin → User overviews → Flex Time</em>, current balances for all users are shown. Configure plus/minus limits and notification e-mails per user.</p>
          </div>
          <div class="help-entry">
            <b>Vacation overview &amp; limit</b>
            <p>Under <em>Admin → User overviews → Vacation</em>, all users are listed with entitlement, carryover, used and remaining vacation.</p>
          </div>
        </div>
      </div>
    </div>"""
        body = f"""
<style>
.acc{{border:1px solid var(--bd);border-radius:var(--r);margin-bottom:10px;overflow:hidden;background:var(--bg);}}
.acc-hdr{{width:100%;display:flex;justify-content:space-between;align-items:center;
  padding:14px 16px;background:var(--sf);border:none;cursor:pointer;
  font-size:15px;font-weight:600;color:var(--tx);text-align:left;gap:10px;}}
.acc-hdr:hover{{background:var(--bd);}}
.acc-hdr.open{{border-bottom:1px solid var(--bd);}}
.acc-arr{{font-size:12px;flex-shrink:0;color:var(--mu);}}
.acc-body{{max-height:0;overflow:hidden;transition:max-height .3s ease;}}
.acc-body.open{{max-height:99999px;}}
.acc-inner{{padding:16px;display:flex;flex-direction:column;gap:0;}}
.help-entry{{padding:12px 0;border-bottom:1px solid var(--bd);}}
.help-entry:last-child{{border-bottom:none;padding-bottom:0;}}
.help-entry b{{display:block;margin-bottom:4px;font-size:14px;}}
.help-entry p{{font-size:13px;color:var(--mu);margin:3px 0;line-height:1.5;}}
.help-entry code{{background:var(--bd);padding:1px 5px;border-radius:4px;font-size:12px;font-family:monospace;}}
.help-entry ul{{font-size:13px;color:var(--mu);padding-left:18px;margin:4px 0;line-height:1.6;}}
.info-box{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:13px;color:#1e40af;}}
.warn-box{{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:13px;color:#92400e;}}
@media(prefers-color-scheme:dark){{
  .info-box{{background:#1e3a5f;border-color:#1e40af;color:#93c5fd;}}
  .warn-box{{background:#3d2b00;border-color:#d97706;color:#fcd34d;}}
}}
</style>
<script>
function haccToggle(btn){{
  var body=btn.nextElementSibling;
  var arr=btn.querySelector('.acc-arr');
  var op=body.classList.contains('open');
  body.classList.toggle('open',!op);
  btn.classList.toggle('open',!op);
  if(arr)arr.textContent=op?'▼':'▲';
}}
function filterHelp(q){{
  q=q.toLowerCase().trim();
  document.querySelectorAll('.help-acc').forEach(function(acc){{
    var txt=acc.textContent.toLowerCase();
    var match=!q||txt.includes(q);
    acc.style.display=match?'':'none';
    if(q&&match){{
      var body=acc.querySelector('.acc-body');
      var btn=acc.querySelector('.acc-hdr');
      var arr=acc.querySelector('.acc-arr');
      if(body&&!body.classList.contains('open')){{
        body.classList.add('open');
        if(btn)btn.classList.add('open');
        if(arr)arr.textContent='▲';
      }}
    }}
  }});
}}
</script>

<h2 style="margin:0 0 14px 0;font-size:18px;">❓ Help</h2>
<div style="margin-bottom:16px;">
  <input type="search" id="help-search" placeholder="Search help …"
         style="width:100%;max-width:420px;"
         oninput="filterHelp(this.value)">
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>🏠 Overview (Home)</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>Flex Time Widget</b>
      <p>Shows your current flex time balance: <b style="color:#16a34a;">green</b> = surplus hours, <b style="color:#dc2626;">red</b> = deficit. Balance = sum of all (actual − target) days since your tracking start date plus your opening balance.</p>
    </div>
    <div class="help-entry">
      <b>Vacation remaining</b>
      <p>Annual entitlement + effective carryover − vacation days taken. Only working days count (weekends and public holidays are excluded).</p>
      <div class="warn-box">⚠️ <b>Carryover rule:</b> Unused annual leave expires on 31 March of the following year. Leave must have <em>started</em> by 31 March. Exceptions can be set by an admin.</div>
    </div>
    <div class="help-entry">
      <b>Missing entries</b>
      <p>Past working days (per your schedule) with neither a time entry nor an absence. Today is never counted as missing.</p>
    </div>
    <div class="help-entry">
      <b>Time booking</b>
      <p>Shows how many recorded working days have not yet been booked to a project or cost centre. Only visible if time booking is enabled in settings.</p>
    </div>
    <div class="help-entry">
      <b>Absence card</b>
      <p>Compact overview of current and upcoming absences (vacation, sick, flex day, other) in the current period.</p>
    </div>
    <div class="help-entry">
      <b>Retirement countdown</b>
      <p>Time remaining until retirement (years, months, days, working days). Only visible if a date of birth is stored in settings. Configurable under <em>Settings → Personal settings</em> (default age: 67).</p>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>⏱ Time Tracking</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>Opening the day view</b>
      <p>Click on a day in the calendar, use the Today tile on the overview, or use the bot command <code>/heute</code>.</p>
    </div>
    <div class="help-entry">
      <b>Logging a time block</b>
      <p>Enter <em>Start</em>, <em>End</em> and optional <em>Break</em> in minutes. Multiple blocks per day are supported. Each block is saved separately and summed in the flex time report.</p>
      <div class="info-box">ℹ️ Times are recorded in <b>15-minute steps</b>. Inputs are rounded to the nearest quarter hour.</div>
    </div>
    <div class="help-entry">
      <b>Multiple time blocks per day</b>
      <p>Simply add another block. The delta and balance are calculated from the <em>sum of all blocks</em> minus the target.</p>
    </div>
    <div class="help-entry">
      <b>Editing and deleting entries</b>
      <p>In the day view, click the edit icon or Delete next to a block. In the calendar, use the context menu (three dots) of the day.</p>
    </div>
    <div class="help-entry">
      <b>Weekend / public holiday</b>
      <p>No target hours on weekends and public holidays. If you worked anyway, a time block can be recorded – target stays 0 and delta equals actual hours.</p>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>📅 Calendar</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>Navigation</b>
      <p>Use the ‹ › arrows to switch months. Click the month name to jump directly to a month.</p>
    </div>
    <div class="help-entry">
      <b>List view</b>
      <p>Switch between tile and list view using the toggle at the top right. List view is best for longer periods.</p>
    </div>
    <div class="help-entry">
      <b>Colour coding and symbols</b>
      <ul>
        <li>🟡 <b>Amber dot</b> = day is booked</li>
        <li>❌ <b>Red X</b> = missing time entry</li>
        <li>🟢 <b>Green badge</b> = vacation</li>
        <li>✈ <b>Plane</b> = business trip recorded</li>
        <li>🟦 <b>Blue background</b> = today</li>
      </ul>
    </div>
    <div class="help-entry">
      <b>Context menu (three dots)</b>
      <p>Click the three dots of a day to log time, add an absence, log a business trip, or edit/delete existing entries.</p>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>📊 Flex Time</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>Balance calculation</b>
      <p>Balance = opening balance + sum of all (actual − target) since your tracking start date. The balance is updated daily; future days are not included.</p>
    </div>
    <div class="help-entry">
      <b>Report columns</b>
      <ul>
        <li><b>Target</b> = contractual hours per your schedule</li>
        <li><b>Actual</b> = recorded hours (sum of all blocks)</li>
        <li><b>Delta</b> = actual − target (green = plus, red = minus)</li>
        <li><b>Balance</b> = cumulative balance up to that day</li>
      </ul>
    </div>
    <div class="help-entry">
      <b>Flex day deduction</b>
      <p>On a flex day, target = 0 but the <em>originally planned</em> target hours are still deducted from flex time. A flex day is economically equivalent to a vacation day without affecting the vacation balance.</p>
    </div>
    <div class="help-entry">
      <b>RTF report via bot</b>
      <p>The bot command <code>/bericht</code> or <code>/bericht year</code> generates a colour-coded RTF report (green/red) when the report is longer than one screen page.</p>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>🏖 Absences</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>Vacation</b>
      <p>Counts working days per your schedule (excluding weekends and public holidays). Affects the vacation balance. Target = 0, no flex time deduction.</p>
      <div class="warn-box">⚠️ <b>Carryover rule:</b> Unused carryover from the previous year expires on 31 March. Leave must have started by 31 March.</div>
    </div>
    <div class="help-entry">
      <b>Sick</b>
      <p>No effect on flex time or vacation balance. Target = 0 for the sick period.</p>
    </div>
    <div class="help-entry">
      <b>Flex day</b>
      <p>Time off from the flex time balance. Target = 0, but the <em>originally planned</em> hours are deducted from flex time. No vacation consumption.</p>
      <div class="info-box">ℹ️ Flex day via bot: type "Flex day on Aug 3"</div>
    </div>
    <div class="help-entry">
      <b>Other</b>
      <p>Other special absences. Like sick: target = 0, no flex time effect. The comment is shown as the label.</p>
    </div>
    <div class="help-entry">
      <b>Adding a new absence</b>
      <p>Via <em>Absences → New</em>, the calendar context menu, or Telegram bot free text: <em>"Vacation from Jul 1 to Jul 15"</em></p>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>✈ Business Trips</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>What is a business trip?</b>
      <p>An informational entry showing you were on a business trip on certain days. <b>Important:</b> Working hours are <em>not</em> recorded automatically – time blocks must be entered separately.</p>
    </div>
    <div class="help-entry">
      <b>Fields</b>
      <p>From/to date and destination (free text). The destination appears in the calendar as a tooltip on the ✈ symbol.</p>
    </div>
    <div class="help-entry">
      <b>Display in calendar</b>
      <p>Days with a business trip are marked with ✈. In the flex time report the destination appears in the time column.</p>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>📋 Time Booking</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>What does booking mean?</b>
      <p>Posting recorded working hours to projects or cost centres. A working day is only fully closed once it has been booked.</p>
    </div>
    <div class="help-entry">
      <b>Book individually</b>
      <p>Click the <em>Book</em> button in the day view. The day then receives the 🟡 amber dot in the calendar.</p>
    </div>
    <div class="help-entry">
      <b>Bulk booking</b>
      <p>Under <em>Booking</em>, select multiple days at once. Practical after vacation or longer absences.</p>
    </div>
    <div class="help-entry">
      <b>Enable / Disable</b>
      <p>In settings under <em>Booking</em>, enable the feature with a start date. Days before the start date are not shown for booking.</p>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>🔒 Lock Periods</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>Monthly close</b>
      <p>Locks all time entries and absences for the month. No further changes are possible. The balance is frozen.</p>
    </div>
    <div class="help-entry">
      <b>Annual close</b>
      <p>Locks all months of the year at once. Recommended at year-end after a full review.</p>
      <div class="info-box">ℹ️ Only months from your tracking start date need to be closed.</div>
    </div>
    <div class="help-entry">
      <b>Unlock</b>
      <p>Only admins can unlock locked periods. Under <em>Admin → Lock Periods</em>.</p>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>⚙️ Settings</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>Personal settings</b>
      <p><b>Display name</b>: shown in the header and in reports.<br>
      <b>E-mail</b>: for notifications.<br>
      <b>Date of birth</b>: enables retirement countdown on the overview.<br>
      <b>Retirement age</b>: default 67, range 60–72.<br>
      <b>Telegram ID</b>: for bot access (see Telegram Bot section).</p>
    </div>
    <div class="help-entry">
      <b>Vacation</b>
      <p><b>Annual entitlement</b>: total vacation days for the year (half days possible, e.g. 27.5).<br>
      <b>Carryover</b>: remaining leave from the previous year. Expires 31 March unless an admin exception applies.</p>
    </div>
    <div class="help-entry">
      <b>Work schedule</b>
      <p><b>Weekly mode</b>: same daily target distributed across all working days.<br>
      <b>Daily mode</b>: different target per weekday (e.g. Mon–Thu 8h, Fri 6h).<br>
      <b>Valid from</b>: multiple schedules with different start dates – the most recently valid one applies.</p>
    </div>
    <div class="help-entry">
      <b>Time booking</b>
      <p>Enable the feature with a start date. Days from this date must be booked. Disabling resets all unbooked days.</p>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>📅 Calendar Integration</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>Calendar Export (.ics Download &amp; webcal subscription)</b>
      <p>Under <em>Settings → Calendar Integration</em>, absences can be exported as a calendar file or set up as a live subscription.</p>
      <ul>
        <li><b>Download .ics</b>: One-time snapshot. Opening it imports entries into Apple Calendar, Google, Outlook etc.</li>
        <li><b>Subscribe via webcal://</b>: Calendar apps regularly fetch new data – changes appear automatically.</li>
        <li><b>Prefix</b>: Optional text before each entry, e.g. <code>Uwe:</code> or <code>🏢</code>. Useful when multiple people share the same calendar.</li>
        <li><b>Reset token</b>: Invalidates all existing subscriptions and generates a new URL.</li>
      </ul>
      <div class="info-box">ℹ️ Supported apps: Apple Calendar, Google Calendar, Outlook, and any app with iCal standard support.</div>
    </div>
    <div class="help-entry">
      <b>🍎 Apple iCloud Sync</b>
      <p>Absences are automatically written to an iCloud calendar — on create, edit and delete.</p>
      <p><b>Requirements:</b></p>
      <ul>
        <li><b>Apple ID</b>: your iCloud e-mail address</li>
        <li><b>App-specific password</b>: generate at <a href="https://appleid.apple.com" target="_blank">appleid.apple.com</a> → Sign in → Security → App-Specific Passwords → Generate. <em>Do not</em> use your regular Apple password.</li>
        <li><b>Calendar name</b>: exact name of the iCloud calendar (case-sensitive), e.g. <code>Work</code></li>
      </ul>
      <p><b>Multiple users</b>: Different people can write to the same calendar — using different prefixes (e.g. <code>Uwe:</code> / <code>Steffi:</code>) keeps entries clearly attributed.</p>
      <p>Use <em>Test connection</em> to verify iCloud access and list available calendars. <em>Sync all</em> writes all existing absences to the calendar once — useful for initial setup.</p>
      <div class="warn-box">⚠️ The app password is stored encrypted. Leaving the field empty when saving keeps the existing password unchanged.</div>
    </div>
    <div class="help-entry">
      <b>Home Assistant CalDAV</b>
      <p>The CalDAV URL from settings can be entered directly in Home Assistant.</p>
      <ul>
        <li>In HA: <em>Settings → Integrations → Calendar → CalDAV</em></li>
        <li><b>URL</b>: <code>https://time.company.com/caldav/TOKEN/</code> (copy from settings)</li>
        <li>No username/password required — the token handles authentication</li>
        <li>Alternatively: select Basic Auth in settings and enter your Zeiterfassung credentials in HA</li>
      </ul>
      <div class="info-box">ℹ️ The external server URL must be set correctly under <em>Admin → System settings → Regional settings → External server URL</em> for CalDAV URLs to work.</div>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>🤖 Telegram Bot</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>Setup</b>
      <p>1. Send any message to <b>@userinfobot</b> in Telegram → it replies with your Telegram ID (a numeric number).<br>
      2. Enter this ID under <em>Settings → Telegram ID</em>.<br>
      3. Send the bot <code>/start</code> – all commands are now available.</p>
    </div>
    <div class="help-entry">
      <b>Commands</b>
      <ul>
        <li><code>/saldo</code> — current flex time balance</li>
        <li><code>/urlaub</code> — vacation overview</li>
        <li><code>/heute</code> — today's entries and daily balance</li>
        <li><code>/fehlend</code> — missing entries in the current year</li>
        <li><code>/kontierung</code> — unbooked days</li>
        <li><code>/abwesenheiten</code> — absence list current year</li>
        <li><code>/bericht</code> — flex time current month (text or RTF)</li>
        <li><code>/bericht jahr</code> — flex time whole year as RTF</li>
        <li><code>/bericht 5</code> — flex time May (any month 1–12)</li>
        <li><code>/user</code> — currently active user</li>
      </ul>
    </div>
    <div class="help-entry">
      <b>Free-text input</b>
      <p>Just type natural language:</p>
      <ul>
        <li><em>"Today worked from 7:30 to 13:00"</em></li>
        <li><em>"On May 15 from 8 to 16:00"</em></li>
        <li><em>"Vacation from Jul 1 to Jul 15"</em></li>
        <li><em>"Sick from Jun 10 to Jun 12"</em></li>
        <li><em>"Flex day on Aug 3"</em></li>
      </ul>
      <p>Times are rounded to 15-minute steps. If an entry exists, the bot asks for confirmation.</p>
    </div>
    <div class="help-entry">
      <b>Evening reminder</b>
      <p>The bot sends a message in the evening if no time entry or absence exists for today.</p>
      <ul>
        <li>Enable: <em>Settings → Personal settings → 📱 Telegram Reminder</em></li>
        <li>Time: configurable between 15:00 and 23:00 (default: 20:00)</li>
        <li>Only on actual working days – no reminders on weekends, holidays or locked periods</li>
      </ul>
    </div>
    <div class="help-entry">
      <b>Admin commands</b>
      <ul>
        <li><code>/als &lt;username&gt;</code> — switch context to another user</li>
        <li><code>/als ich</code> — return to your own context</li>
        <li><code>/users</code> — list all active users</li>
      </ul>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>✅ Absence Approval</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>What is absence approval?</b>
      <p>Certain absence types (e.g. vacation) can be configured to require approval before becoming active in the flex-time balance. Pending absences show a yellow ⏳ badge and do <em>not</em> affect the flex-time account until approved.</p>
    </div>
    <div class="help-entry">
      <b>Who can approve?</b>
      <p>Users with the <em>Approver</em> role. Approvers access their queue via the hamburger menu → <b>Approvals</b> (<code>/approvals</code>).</p>
    </div>
    <div class="help-entry">
      <b>Setup (Admin / Time Manager only)</b>
      <p>Under <em>Admin → User overviews → Edit user</em>, in the <em>Approval</em> section:</p>
      <ul>
        <li><b>Is Approver:</b> enable to allow this user to approve other people's absences.</li>
        <li><b>Approver:</b> select who approves <em>this</em> user's absences.</li>
        <li><b>Approval required for:</b> tick which absence types need approval (e.g. Vacation, Flex day).</li>
      </ul>
    </div>
    <div class="help-entry">
      <b>Workflow</b>
      <ul>
        <li>Employee submits absence → status <b>⏳ Pending</b> (not counted in flex time yet).</li>
        <li>Approver receives e-mail + Telegram notification.</li>
        <li>Approver opens <em>/approvals</em> → clicks <b>✅ Approve</b> or <b>✗ Reject</b> (rejection requires a reason).</li>
        <li>Employee receives e-mail + Telegram with the decision.</li>
        <li>Approved: absence becomes active and counts in the flex-time balance.</li>
        <li>Rejected: absence remains visible with a red ✗ badge and rejection reason; does not count.</li>
      </ul>
    </div>
    <div class="help-entry">
      <b>Bot commands (approvers only)</b>
      <p><code>/genehmigungen</code> — list pending requests &nbsp;·&nbsp; <code>genehmigen &lt;ID&gt;</code> — approve &nbsp;·&nbsp; <code>ablehnen &lt;ID&gt; &lt;reason&gt;</code> — reject</p>
    </div>
  </div></div>
</div>

<div class="acc help-acc">
  <button class="acc-hdr" type="button" onclick="haccToggle(this)">
    <span>🔒 Security</span><span class="acc-arr">▼</span>
  </button>
  <div class="acc-body"><div class="acc-inner">
    <div class="help-entry">
      <b>Two-Factor Authentication (2FA / TOTP)</b>
      <ul>
        <li>Enable under <em>Settings → Security → Activate 2FA</em>.</li>
        <li>Scan the QR code with Google Authenticator, Authy or any TOTP app.</li>
        <li>8 single-use backup codes are generated — store them safely offline.</li>
        <li>Lost authenticator: use a backup code at the 2FA prompt (each code works once).</li>
        <li>Admin can disable 2FA for any user: <em>Admin → User overviews → Edit user</em>.</li>
      </ul>
    </div>
    <div class="help-entry">
      <b>Login lock</b>
      <p>After <b>3 failed login attempts</b> the account is locked for <b>30 minutes</b>.</p>
      <ul>
        <li>An unlock link is sent to the e-mail address stored in the user profile.</li>
        <li>Clicking the link immediately unlocks the account (valid for 24 h).</li>
        <li>Admin / Time Manager can unlock manually: <em>Admin → User overviews → 🔓 Unlock</em>.</li>
        <li>No e-mail stored → only manual admin unlock is possible.</li>
      </ul>
    </div>
    <div class="help-entry">
      <b>Password rules</b>
      <ul>
        <li>Minimum <b>10 characters</b></li>
        <li>At least one <b>uppercase</b> and one <b>lowercase</b> letter</li>
        <li>At least one <b>digit</b></li>
        <li>Must not contain the username</li>
      </ul>
    </div>
    <div class="help-entry">
      <b>Backup encryption</b>
      <p>Full backups can be encrypted with a password (AES via Fernet). The password is <em>not stored</em> — if lost, the backup cannot be decrypted. Keep it separately from the backup file.</p>
    </div>
  </div></div>
</div>

{admin_section_en}
"""
    return render_template_string(layout(t("help.title"), body, u, APP_VERSION))


