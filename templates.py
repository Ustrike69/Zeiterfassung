def layout(title: str, body: str, user=None, app_version: str = "v1.4.4", impersonation_banner: str = "", show_back: bool = True, extra_root_css: str = "", app_label: str = "", app_label_color: str = "#f59e0b") -> str:
    nav_html = ""
    if user:
        items = [("/", "Übersicht"), ("/absences", "Abwesenheiten"), ("/business_trips", "Dienstreisen"), ("/calendar", "Kalender"), ("/periods", "Abschlüsse"), ("/settings", "Einstellungen"), ("/export", "Export"), ("/help", "❓ Hilfe")]
        if user.get("is_admin"):
            items.append(("/admin", "Admin"))
        items.append(("/logout", "Logout"))
        li = "".join([f'<li><a class="nav-link" href="{u}">{t}</a></li>' for u, t in items])
        nav_html = f"""<nav class="app-nav">
  <input type="checkbox" id="nav-cb" class="nav-cb">
  <label for="nav-cb" class="hamburger" aria-label="Menü">
    <span></span><span></span><span></span>
  </label>
  <ul class="nav-menu">{li}</ul>
</nav>"""

    user_display = ""
    if user:
        user_display = (user.get("display_name") or user.get("username") or "").strip()

    html = f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Zeiterfassung">
<meta name="theme-color" content="#1a1f2e">
<link rel="apple-touch-icon" href="/static/icons/icon-180.png">
<link rel="icon" type="image/png" sizes="32x32" href="/static/icons/icon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/static/icons/icon-16.png">
<link rel="manifest" href="/manifest.json">
<title>{title}</title>
<style>
  :root{{
    --bg:#ffffff;--sf:#f9fafb;--bd:#e5e7eb;
    --tx:#111827;--mu:#6b7280;
    --ac:#2563eb;--ac-fg:#ffffff;
    --danger:#dc2626;--ok:#16a34a;
    --r:12px;--rs:8px;
    --fn:system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;
    --nav-bg:var(--sf);
  }}
  @media(prefers-color-scheme:dark){{
    :root{{
      --bg:#0f172a;--sf:#1e293b;--bd:#334155;
      --tx:#f1f5f9;--mu:#94a3b8;
      --ac:#3b82f6;
    }}
  }}
  {f":root{{ {extra_root_css} }}" if extra_root_css else ""}
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
    background:var(--nav-bg);border-bottom:1px solid var(--bd);
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
    display:inline-flex;align-items:center;justify-content:center;gap:4px;
    padding:8px 14px;border-radius:var(--rs);
    border:1px solid var(--bd);background:var(--sf);color:var(--tx);
    cursor:pointer;text-decoration:none;font-size:14px;font-family:var(--fn);
    font-weight:500;line-height:1.25;
    transition:background .12s,opacity .12s;-webkit-tap-highlight-color:transparent;white-space:nowrap;
  }}
  .btn:hover{{background:var(--bd);}}
  .btn:active{{opacity:.75;}}
  .btn.primary,.btn-primary{{background:var(--ac);color:var(--ac-fg);border-color:var(--ac);}}
  .btn.primary:hover,.btn-primary:hover{{opacity:.9;background:var(--ac);}}
  .btn.danger,.btn-danger{{background:rgba(220,38,38,.09);color:var(--danger);border-color:rgba(220,38,38,.3);}}
  .btn.danger:hover,.btn-danger:hover{{background:rgba(220,38,38,.18);}}
  .btn-sm{{padding:4px 10px;font-size:13px;}}
  .btn-lg{{padding:11px 18px;font-size:15px;font-weight:600;}}
  /* ---- Forms ---- */
  input,select,textarea{{
    padding:10px 12px;border:1px solid var(--bd);border-radius:var(--rs);
    background:var(--bg);color:var(--tx);font-family:var(--fn);font-size:16px;
    max-width:100%;
  }}
  input[type=text],input[type=password],input[type=date],input[type=email],
  input[type=search],select,textarea{{width:100%;}}
  input[type=number]{{width:90px;}}
  input[type=time]{{width:auto;min-width:110px;cursor:pointer;}}
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
  /* ---- Date input ---- */
  .dt-wrap{{position:relative;display:inline-flex;align-items:stretch;width:160px;}}
  .dt-text{{width:100%!important;padding-right:34px!important;box-sizing:border-box;}}
  .dt-pick{{position:absolute!important;right:0;top:0;bottom:0;width:36px!important;min-width:0!important;padding:0!important;opacity:0;cursor:pointer;z-index:2;border:none!important;background:transparent!important;color:transparent!important;overflow:hidden;}}
  .dt-wrap::after{{content:'';position:absolute;right:8px;top:50%;transform:translateY(-50%);width:15px;height:15px;pointer-events:none;z-index:1;background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='4' width='18' height='18' rx='2'/%3E%3Cline x1='16' y1='2' x2='16' y2='6'/%3E%3Cline x1='8' y1='2' x2='8' y2='6'/%3E%3Cline x1='3' y1='10' x2='21' y2='10'/%3E%3C/svg%3E") no-repeat center;background-size:contain;}}
  @media(prefers-color-scheme:dark){{.dt-wrap::after{{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='4' width='18' height='18' rx='2'/%3E%3Cline x1='16' y1='2' x2='16' y2='6'/%3E%3Cline x1='8' y1='2' x2='8' y2='6'/%3E%3Cline x1='3' y1='10' x2='21' y2='10'/%3E%3C/svg%3E");}}}}
  /* ---- Time input: 15-min snapping via JS ---- */
</style>
</head>
<body>
<header class="app-header">
  <div style="display:flex;align-items:center;gap:8px;min-width:0;flex:1;">
    {"" if not (user and show_back) else '<button onclick="goBack()" class="btn btn-sm">&#8592; Zurück</button>'}
    <div style="min-width:0;">
      <div class="hdr-title" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{title}</div>
      <div class="hdr-sub">Zeiterfassung {app_version}{" · " + user_display if user_display else ""}</div>
    </div>
    {f'<span style="background:{app_label_color};color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;letter-spacing:.07em;flex-shrink:0;text-transform:uppercase;">{app_label}</span>' if app_label else ""}
  </div>
  {nav_html}
</header>
{impersonation_banner}
<div class="main">
{body}
</div>
<script>
  function goBack(){{if(history.length>1){{history.back();}}else{{location.href='/';}}}}
  function setBreak(el,mins){{
    try{{var f=el.closest('form');var inp=f.querySelector('input[name="break_minutes"]');if(inp)inp.value=String(mins);}}catch(e){{}}
    return false;
  }}
  function syncTimeMin(tin){{
    try{{
      var f=tin.closest('form');
      var tout=f.querySelector('input[name="time_out"]');
      if(tout){{tout.min=tin.value||'';if(tout.value&&tin.value&&tout.value<=tin.value)tout.value='';}}
    }}catch(e){{}}
  }}
  document.addEventListener('input',function(ev){{
    if(ev.target&&ev.target.classList&&ev.target.classList.contains('tin'))syncTimeMin(ev.target);
  }});
  function dt_text(inp){{
    try{{
      var m=inp.value.match(/^(\\d{{1,2}})\\.(\\d{{1,2}})\\.(\\d{{4}})$/);
      var p=inp.parentElement.querySelector('.dt-pick');
      var iso='';
      if(m){{iso=m[3]+'-'+m[2].padStart(2,'0')+'-'+m[1].padStart(2,'0');if(p)p.value=iso;}}
      else{{if(p)p.value='';}}
      var mt=inp.getAttribute('data-min-target');
      if(mt){{var ti=document.querySelector('[name="'+mt+'"]');if(ti){{var tp=ti.parentElement.querySelector('.dt-pick');if(tp)tp.min=iso;}}}}
    }}catch(e){{}}
  }}
  function dt_pick(inp){{
    try{{
      var m=inp.value.match(/^(\\d{{4}})-(\\d{{2}})-(\\d{{2}})$/);
      var t=inp.parentElement.querySelector('.dt-text');
      if(!t)return;
      var iso='';
      if(m){{iso=inp.value;t.value=m[3]+'.'+m[2]+'.'+m[1];}}
      var mt=t.getAttribute('data-min-target');
      if(mt){{var ti=document.querySelector('[name="'+mt+'"]');if(ti){{var tp=ti.parentElement.querySelector('.dt-pick');if(tp)tp.min=iso;}}}}
    }}catch(e){{}}
  }}
  function snapTo15(inp){{
    try{{
      if(!inp.value)return;
      var p=inp.value.split(':');if(p.length<2)return;
      var h=parseInt(p[0],10),m=parseInt(p[1],10);
      var r=Math.round(m/15)*15;
      if(r===60){{r=0;h=(h+1)%24;}}
      inp.value=String(h).padStart(2,'0')+':'+String(r).padStart(2,'0');
    }}catch(e){{}}
  }}
  document.addEventListener('change',function(ev){{
    var el=ev.target;
    if(el&&el.type==='time')snapTo15(el);
  }});
  function toggleMultiday(cb){{
    try{{var wrap=cb.closest('form').querySelector('.multiday-fields');if(wrap)wrap.style.display=cb.checked?'':'none';}}catch(e){{}}
  }}
  document.addEventListener('DOMContentLoaded',function(){{
    document.querySelectorAll('.dt-text.dfrom').forEach(function(inp){{dt_text(inp);}});
  }});
</script>
</body>
</html>"""
    return html
