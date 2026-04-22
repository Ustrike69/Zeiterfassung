def layout(title: str, body: str, user=None, app_version: str = "v2.12.11") -> str:
    nav_html = ""
    if user:
        items = [("/", "Übersicht"), ("/absences", "Abwesenheiten"), ("/business_trips", "Dienstreisen"), ("/calendar", "Kalender"), ("/settings", "Einstellungen"), ("/export", "Export")]
        if user.get("is_admin"):
            items.append(("/admin/users", "Admin: Benutzer"))
        items.append(("/logout", "Logout"))
        li = "".join([f'<li><a class="nav-link" href="{u}">{t}</a></li>' for u, t in items])
        nav_html = f"""<nav class="app-nav">
  <input type="checkbox" id="nav-cb" class="nav-cb">
  <label for="nav-cb" class="hamburger" aria-label="Menü">
    <span></span><span></span><span></span>
  </label>
  <ul class="nav-menu">{li}</ul>
</nav>"""

    html = f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#f9fafb" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f172a" media="(prefers-color-scheme: dark)">
<title>{title}</title>
<style>
  :root{{
    --bg:#ffffff;--sf:#f9fafb;--bd:#e5e7eb;
    --tx:#111827;--mu:#6b7280;
    --ac:#2563eb;--ac-fg:#ffffff;
    --danger:#dc2626;--ok:#16a34a;
    --r:12px;--rs:8px;
    --fn:system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;
  }}
  @media(prefers-color-scheme:dark){{
    :root{{
      --bg:#0f172a;--sf:#1e293b;--bd:#334155;
      --tx:#f1f5f9;--mu:#94a3b8;
      --ac:#3b82f6;
    }}
  }}
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  body{{
    font-family:var(--fn);background:var(--bg);color:var(--tx);
    padding-left:env(safe-area-inset-left,0px);
    padding-right:env(safe-area-inset-right,0px);
    padding-bottom:env(safe-area-inset-bottom,0px);
    min-height:100vh;
  }}
  /* ---- Header ---- */
  .app-header{{
    display:flex;justify-content:space-between;align-items:center;gap:12px;
    padding:12px 16px;
    padding-top:calc(12px + env(safe-area-inset-top,0px));
    background:var(--sf);border-bottom:1px solid var(--bd);
    position:sticky;top:0;z-index:100;
  }}
  .hdr-title{{font-weight:700;font-size:16px;line-height:1.2;}}
  .hdr-sub{{color:var(--mu);font-size:11px;margin-top:1px;}}
  /* ---- Main content ---- */
  .main{{padding:14px 16px;max-width:960px;margin:0 auto;}}
  /* ---- Hamburger nav ---- */
  .app-nav{{position:relative;flex-shrink:0;}}
  .nav-cb{{display:none;}}
  .hamburger{{
    display:flex;flex-direction:column;gap:5px;cursor:pointer;
    padding:7px 6px;border-radius:var(--rs);
    -webkit-tap-highlight-color:transparent;
  }}
  .hamburger:hover{{background:var(--bd);}}
  .hamburger span{{
    display:block;width:22px;height:2px;
    background:var(--tx);border-radius:2px;
    transition:transform .2s ease,opacity .2s ease;
  }}
  .nav-cb:checked~label.hamburger span:nth-child(1){{transform:translateY(7px) rotate(45deg);}}
  .nav-cb:checked~label.hamburger span:nth-child(2){{opacity:0;transform:scaleX(0);}}
  .nav-cb:checked~label.hamburger span:nth-child(3){{transform:translateY(-7px) rotate(-45deg);}}
  .nav-menu{{
    display:none;position:absolute;right:0;top:calc(100% + 6px);
    background:var(--sf);border:1px solid var(--bd);
    border-radius:var(--r);box-shadow:0 8px 32px rgba(0,0,0,.18);
    min-width:220px;list-style:none;padding:6px 0;z-index:200;
  }}
  .nav-cb:checked~.nav-menu{{display:block;}}
  .nav-link{{
    display:block;padding:12px 18px;color:var(--tx);text-decoration:none;
    font-size:15px;transition:background .1s;
  }}
  .nav-link:hover,.nav-link:active{{background:var(--bd);color:var(--ac);}}
  .nav-menu li:not(:last-child){{border-bottom:1px solid var(--bd);}}
  /* ---- Card ---- */
  .card{{background:var(--sf);border:1px solid var(--bd);border-radius:var(--r);padding:16px;margin:12px 0;}}
  /* ---- Table ---- */
  table{{border-collapse:collapse;width:100%;}}
  th,td{{border-bottom:1px solid var(--bd);padding:10px 8px;text-align:left;vertical-align:top;}}
  th{{color:var(--mu);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;}}
  .table-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch;}}
  /* ---- Buttons ---- */
  .btn{{
    display:inline-flex;align-items:center;justify-content:center;
    padding:9px 14px;border-radius:var(--rs);
    border:1px solid var(--bd);background:var(--sf);color:var(--tx);
    cursor:pointer;text-decoration:none;font-size:15px;font-family:var(--fn);
    transition:background .12s;-webkit-tap-highlight-color:transparent;white-space:nowrap;
    line-height:1.2;
  }}
  .btn:hover{{background:var(--bd);}}
  .btn:active{{opacity:.75;}}
  .btn.primary{{background:var(--ac);color:var(--ac-fg);border-color:var(--ac);}}
  .btn.primary:hover{{opacity:.9;background:var(--ac);}}
  /* ---- Forms ---- */
  input,select,textarea{{
    padding:10px 12px;border:1px solid var(--bd);border-radius:var(--rs);
    background:var(--bg);color:var(--tx);font-family:var(--fn);font-size:16px;
    max-width:100%;
  }}
  input[type=text],input[type=password],input[type=date],input[type=email],
  input[type=search],select,textarea{{width:100%;}}
  input[type=number]{{width:90px;}}
  input[type=time]{{width:auto;min-width:110px;}}
  input[type=checkbox]{{width:auto;font-size:inherit;}}
  textarea{{width:100%;resize:vertical;}}
  label{{font-weight:600;font-size:14px;color:var(--tx);display:block;margin-bottom:4px;}}
  /* ---- Misc ---- */
  .small{{color:var(--mu);font-size:12px;}}
  .danger,.btn.danger{{color:var(--danger);}}
  .success{{color:var(--ok);}}
  .flash{{padding:12px 16px;border-radius:var(--rs);margin:8px 0;border:1px solid var(--bd);background:var(--sf);}}
  .flash.error{{border-color:#fca5a5;background:#fef2f2;color:#991b1b;}}
  .flash.success{{border-color:#86efac;background:#f0fdf4;color:#166534;}}
  @media(prefers-color-scheme:dark){{
    .flash.error{{background:#450a0a;border-color:#991b1b;color:#fca5a5;}}
    .flash.success{{background:#052e16;border-color:#166534;color:#86efac;}}
  }}
  h3{{font-size:18px;color:var(--tx);}}
  a{{color:var(--ac);}}
  hr{{border:none;border-top:1px solid var(--bd);margin:14px 0;}}
</style>
</head>
<body>
<header class="app-header">
  <div>
    <div class="hdr-title">{title}</div>
    <div class="hdr-sub">Zeiterfassung {app_version}</div>
  </div>
  {nav_html}
</header>
<div class="main">
{body}
</div>
</body>
</html>"""
    return html
