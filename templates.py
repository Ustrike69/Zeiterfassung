def layout(title: str, body: str, user=None, app_version: str = "v2.12.11") -> str:
    nav = ""
    if user:
        items = [("/", "Übersicht"), ("/absences", "Abwesenheiten"), ("/calendar", "Kalender"), ("/settings", "Einstellungen"), ("/export", "Export")]
        if user.get("is_admin"):
            items.append(("/admin/users", "Admin: Benutzer"))
            items.append(("/admin/absence-types", "Admin: Abwesenheitsarten"))
            items.append(("/admin/key-types", "Admin: Schlüsseltypen"))
        items.append(("/logout", "Logout"))
        links = " ".join([f'<a class="btn" href="{u}">{t}</a>' for u, t in items])
        nav = f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin:12px 0;">{links}</div>'

    html = f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<style>
  body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:20px;
       padding-left: env(safe-area-inset-left);
       padding-right: env(safe-area-inset-right);
       padding-top: env(safe-area-inset-top);
       padding-bottom: env(safe-area-inset-bottom);
  }}
  .card{{border:1px solid #e5e5e5;border-radius:12px;padding:12px;margin:10px 0;}}
  table{{border-collapse:collapse;width:100%;}}
  th,td{{border-bottom:1px solid #eee;padding:8px;text-align:left;vertical-align:top;}}
  .small{{color:#666;font-size:12px;}}
  .btn{{display:inline-block;padding:8px 12px;border-radius:10px;border:1px solid #ddd;background:#fafafa;cursor:pointer;text-decoration:none;color:inherit;}}
  .btn:hover{{background:#f0f0f0;}}
  input,select,textarea{{padding:6px 8px;border:1px solid #ddd;border-radius:8px;}}
  textarea{{width:100%;}}
  .danger{{color:#b00020;}}
  .success{{color:#0b6b2f;}}
  .flash{{padding:10px 12px;border-radius:10px;margin:10px 0;border:1px solid #eee;background:#fafafa;}}
  .flash.error{{border-color:#ffccd0;background:#fff5f5;}}
  .flash.success{{border-color:#bfe6c9;background:#f3fff6;}}
</style>
</head>
<body>
<div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
  <div><b>{title}</b> <span class="small">Zeiterfassung {app_version}</span></div>
</div>
{nav}
{body}
</body>
</html>"""
    return html
