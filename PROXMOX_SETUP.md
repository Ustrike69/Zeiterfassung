# Proxmox Setup – Zeiterfassung

Anleitung für die Installation von Zeiterfassung auf einem Proxmox LXC-Container (Debian/Ubuntu).

---

## Voraussetzungen

- Proxmox LXC mit Debian 12 oder Ubuntu 22.04
- Internetzugang (für git clone und pip)
- Port 5000 oder ein Reverse Proxy (nginx/Caddy)

---

## 1. System vorbereiten

```bash
apt update && apt install -y python3 python3-venv git curl sqlite3
```

---

## 2. App klonen und einrichten

```bash
cd /opt
git clone https://github.com/Ustrike69/Zeiterfassung.git zeiterfassung
cd zeiterfassung
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## 3. Datenbank initialisieren

```bash
.venv/bin/python -c "from db import init_db, seed_defaults; init_db(); seed_defaults(); print('OK')"
```

---

## 4. systemd-Services einrichten

### Web-App (zeiterfassung)

```ini
# /etc/systemd/system/zeiterfassung.service
[Unit]
Description=Zeiterfassung Web App
After=network.target

[Service]
User=root
WorkingDirectory=/opt/zeiterfassung
ExecStart=/opt/zeiterfassung/.venv/bin/gunicorn app:app \
    --bind unix:/run/zeiterfassung/zeiterfassung.sock \
    --workers 2 \
    --timeout 120
RuntimeDirectory=zeiterfassung
Environment=ZEITERFASSUNG_DB=/opt/zeiterfassung/zeiterfassung.db
Restart=always

[Install]
WantedBy=multi-user.target
```

### Telegram-Bot (zeiterfassung-bot)

```ini
# /etc/systemd/system/zeiterfassung-bot.service
[Unit]
Description=Zeiterfassung Telegram Bot
After=network.target

[Service]
User=root
WorkingDirectory=/opt/zeiterfassung
ExecStart=/opt/zeiterfassung/.venv/bin/python bot.py
Environment=ZEITERFASSUNG_DB=/opt/zeiterfassung/zeiterfassung.db
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now zeiterfassung zeiterfassung-bot
systemctl status zeiterfassung zeiterfassung-bot
```

---

## 5. Reverse Proxy (nginx)

```nginx
server {
    listen 80;
    server_name zeiterfassung.beispiel.de;

    location / {
        proxy_pass http://unix:/run/zeiterfassung/zeiterfassung.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 6. Erstkonfiguration in der App

1. `http://<IP>:5000/setup` aufrufen (oder via Reverse Proxy)
2. Admin-Account anlegen
3. **Admin → Systemeinstellungen → Maileinstellungen** — SMTP konfigurieren
4. **Admin → Systemeinstellungen → Telegram Bot** — Bot-Token und Anthropic-API-Key eintragen, Service starten

---

## 7. Admin-Rollen

Ab v1.4.5 gibt es zwei Admin-Rollen:

| Rolle | Beschreibung |
|-------|-------------|
| **🔧 Systemadmin** | Voller Zugriff. Benutzerverwaltung, Maileinstellungen, Backup, Update, Erscheinungsbild |
| **📋 Zeitmanager** | Nur Benutzerübersichten: Urlaub, Abwesenheiten, Gleitzeitkonto, Zeitschemas |

Rollenvergabe: **Admin → Benutzerübersichten → Benutzer bearbeiten → Rolle** (nur für Systemadmins).

Der erste angelegte Admin über `/setup` erhält automatisch die Rolle `sysadmin`.

---

## 8. Farbanpassung für Dev/Prod

Unter **Admin → Systemeinstellungen → Erscheinungsbild** können Akzentfarbe, Navigationsfarbe und ein farbiges Label (z.B. „DEV" in orange oder „PROD" in grün) konfiguriert werden. Damit ist Dev- und Produktivsystem auf einen Blick unterscheidbar.

---

## 9. Update über Admin-UI

Unter **Admin → Systemeinstellungen → System Update** kann direkt aus der App ein `git pull` mit anschließendem Neustart ausgeführt werden. Kein SSH-Zugang notwendig.

---

## 10. Backup

Unter **Admin → Systemeinstellungen → Backup & Restore**:

| Typ | Beschreibung |
|-----|-------------|
| Vollständiges Backup | Komplette SQLite-Datenbank |
| Einstellungen-Backup | Mail- und Bot-Konfiguration als JSON (ohne Passwörter) |
| User-Export/Import | Einzelne User mit Zeiteinträgen und Abwesenheiten übertragen |

Automatisches Backup kann mit Uhrzeit aktiviert werden. Backups werden lokal unter `/opt/zeiterfassung/backups/` gespeichert.

---

## 11. Feiertage / Kalender

NRW-Feiertage für 2026 sind vorbelegt. Für andere Jahre oder Bundesländer:

```bash
.venv/bin/python calendar_seed.py
```

---

## Nützliche Befehle

```bash
# Logs verfolgen
journalctl -u zeiterfassung -f
journalctl -u zeiterfassung-bot -f

# Datenbankzugriff
sqlite3 /opt/zeiterfassung/zeiterfassung.db ".tables"

# Dienste neu starten
systemctl restart zeiterfassung zeiterfassung-bot

# Version prüfen
curl -s --unix-socket /run/zeiterfassung/zeiterfassung.sock http://localhost/ | grep -o 'v[0-9.]*'
```
