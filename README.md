# Zeiterfassung v1.4.5

Mehrbenutzer-Zeiterfassungs-Web-App auf Basis von Flask + SQLite. Erfassung von Arbeitszeiten, Abwesenheiten und Dienstreisen mit automatischer Saldoberechnung, Kontierungsfunktion, CSV-Export per E-Mail, Telegram-Bot und einem umfassenden Admin-Bereich mit Rollentrennung.

---

## Installation

### Proxmox LXC / Debian / Ubuntu

```bash
curl -sL https://raw.githubusercontent.com/Ustrike69/Zeiterfassung-Deploy/main/proxmox/install.sh | bash
```

📖 **Ausführliche Installationsanleitung:** [PROXMOX_SETUP.md](https://github.com/Ustrike69/Zeiterfassung-Deploy/blob/main/PROXMOX_SETUP.md)

### Docker

```bash
docker run -d -p 5000:5000 -v ze_data:/data \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  ghcr.io/ustrike69/zeiterfassung:latest
```

📖 **Deploy-Repository:** [Ustrike69/Zeiterfassung-Deploy](https://github.com/Ustrike69/Zeiterfassung-Deploy)

---

## Inhaltsverzeichnis

1. [Erste Schritte](#erste-schritte)
2. [Übersicht (Startseite)](#übersicht-startseite)
3. [Zeiterfassung (Tagesansicht)](#zeiterfassung-tagesansicht)
4. [Kalender](#kalender)
5. [Gleitzeitkonto](#gleitzeitkonto)
6. [Abwesenheiten](#abwesenheiten)
7. [Dienstreisen](#dienstreisen)
8. [Kontierung](#kontierung)
9. [Einstellungen](#einstellungen)
10. [Export](#export)
11. [Monats- und Jahresabschluss](#monats--und-jahresabschluss)
12. [Admin-Bereich](#admin-bereich)
13. [Technischer Betrieb](#technischer-betrieb)
14. [Versionshistorie](#versionshistorie)

---

## Erste Schritte

### Login

Aufruf der App im Browser. Beim ersten Start wird ein Admin-Konto über `/setup` angelegt. Anmeldung unter `/login`.

### Einrichtungs-Wizard (Onboarding)

Neue Nutzer werden beim ersten Login durch einen 6-stufigen Wizard geführt (`/onboarding`).

| Schritt | Inhalt |
|---------|--------|
| 1 | **Passwort ändern** – Pflicht |
| 2 | **Profil** – Anzeigename und E-Mail |
| 3 | **Zeitschema** – Wochenstunden, Modus, Arbeitstage |
| 4 | **Urlaubskontingent** – Anspruch und Übertrag |
| 5 | **Startsaldo & Erfassung ab** – Gleitzeitguthaben und frühestes Erfassungsdatum |
| 6 | **Zusammenfassung** – Bestätigung |

### Sprache und Format

Vollständig auf Deutsch. Datum: **TT.MM.JJJJ**, Uhrzeiten: **HH:MM** (15-Minuten-Schritte). Die App ist ab **01.01.2026** ausgelegt – Einträge vor dem `tracking_start_date` eines Users sind nicht möglich.

---

## Übersicht (Startseite)

### Button-Leiste oben

- **Zeiterfassung** – Direktlink zur Tagesansicht heute
- **Kalender** – Direktlink zur Kalenderansicht

### Widgets (4er-Grid auf Desktop)

| Widget | Inhalt |
|--------|--------|
| **Gleitzeitkonto** | Aktueller Saldo. Grün = Plus, Rot = Minus. Button „Details" |
| **Resturlaub** | Verbleibende Urlaubstage + Übertrag-Hinweis. Button „Details" |
| **Fehlende Einträge** | Vergangene Arbeitstage ohne Zeiteintrag. Button „Details" |
| **Kontierung** | Unkontierte Tage + Datumsfeld + Button „Kontieren" |

### Abwesenheitskarte

Übersicht Urlaub / Krank / Flextag / Verdi. Button „Alle Abwesenheiten".

---

## Zeiterfassung (Tagesansicht)

Aufruf unter `/day/JJJJ-MM-TT`. Kompaktes 2-Spalten-Grid auf Desktop (Zeit links | Abwesenheit rechts).

### Header

Wochentag + Datum mit ◀ / ▶ Navigation. Soll / Ist / Δ-Badges direkt im Header.

### Zeitblöcke

Mehrere Zeitblöcke pro Tag möglich. Formular: Kommen + Gehen + Pause in einer Zeile, Speichern-Button direkt daneben. Alle Zeiteingaben in 15-Minuten-Schritten.

### Abwesenheit

Typ-Auswahl und ½-Tag-Checkbox in einer Zeile. Bestehende Abwesenheit wird nicht überschrieben.

### Wochenende / Feiertage

Erfassung standardmäßig blockiert. Kompakter Hinweisbanner mit „Ausnahme setzen"-Button direkt daneben.

### Dienstreise

Ort + Datum + Mehrtägig-Checkbox in einer Zeile. Zeiten (Abreise, Ziel, Rückreise, Zuhause) in einer Zeile.

---

## Kalender

Monatsansicht mit Navigation. Wechsel zwischen Monat- und Listen-Ansicht.

### Zelleninhalt

- Erfasste Stunden · Abwesenheits-Badge · Feiertagsname
- ✈ + Ort bei Dienstreisen · ✕ fehlender Eintrag · Bernstein-Punkt kontiert

### Kontextmenü (···)

Zeit erfassen · Abwesenheit eintragen · Als kontiert markieren / aufheben

---

## Gleitzeitkonto

Aufruf unter `/balance`. Tageweise Auflistung mit Jahr-/Monatsauswahl.

### Spalten

Tag | Datum | Beginn | Ende | Pause | Soll | Delta | (Desktop: kum. Saldo + Status)

- Mehrere Zeitblöcke: erste Zeile zeigt Tag + Datum, Folgezeilen leer
- Wochenenden + Feiertage: dezent (gedimmt)
- Urlaub/Krank/Feiertag: farbiges Badge
- Klick auf Zeile → Tages-Editor

### Saldo-Berechnung

Iteriert über alle Tage ab `tracking_start_date` bis heute. Flextag-Tage reduzieren den Saldo zusätzlich um die Sollzeit.

---

## Abwesenheiten

Aufruf unter `/absences`.

| Typ | Beschreibung |
|-----|-------------|
| **Urlaub** | Gegen Urlaubskontingent; Limit-Prüfung verhindert Überschreitung |
| **Krank** | Krankheitstage |
| **Sonstige** | Pflichtfeld Bemerkung (Flextag, Verdi, freie Eingabe) |

**Flextag:** Setzt Soll auf 0 und zieht Sollzeit zusätzlich vom Gleitzeitkonto ab.

**Urlaubslimit-Validierung:** Ist das Urlaubskontingent erschöpft, können normale User keinen weiteren Urlaub eintragen. Admins erhalten eine Warnung, können aber trotzdem eintragen.

---

## Dienstreisen

Zusätzliche Information zu einem Tag – Arbeitszeit separat erfassen.

| Feld | Pflicht |
|------|---------|
| Ort | ✓ |
| Startdatum | ✓ |
| Mehrtägig / Enddatum | – |
| Abreise/Rückreise Zeiten | – |
| Notizen | – |

---

## Kontierung

Separate Buchhaltungsfunktion: Zeiten als „kontiert" (gebucht) markieren.

- **Einzeln**: Kontextmenü (···) im Kalender
- **Bulk**: Startseite → Datum eingeben → „Kontieren"
- **Aktivierung**: In den Einstellungen mit Startdatum aktivieren/deaktivieren
- **Darstellung**: Bernsteinfarbener Punkt im Kalender

---

## Einstellungen

Aufruf unter `/settings`. 4 Accordion-Bereiche:

| Bereich | Inhalt |
|---------|--------|
| **Persönliche Einstellungen** | Name, E-Mail, Passwort, Geburtsdatum, Renteneintrittsalter, Telegram-ID |
| **Urlaub** | Jahresanspruch, Übertrag-Regelung (Standard 31.03. oder Ausnahme) |
| **Zeitschema** | Aktuelle + alle Schemas, Bearbeiten/Löschen/Neu anlegen |
| **Kontierung** | Aktivieren/Deaktivieren + Startdatum |

---

## Export

Aufruf unter `/export`.

### Download (CSV)

Zeitraum wählbar (Datepicker + Schnellwahl: Akt. Monat / Letzter Monat / Akt. Jahr / Letztes Jahr).

Verfügbare Exporte: Zeitblöcke · Abwesenheiten · Dienstreisen · Gleitzeitkonto · Feiertage · Benutzer (Systemadmin)

### CSV-Format (Zeitblöcke)

Spalten wie im Gleitzeitkonto: **Wochentag | Datum | Beginn | Ende | Pause (min) | Soll | Delta | Bemerkung**

- Bemerkung: Feiertagsname, Abwesenheitstyp, Dienstreise-Ort (kombinierbar mit `|`)
- Mehrere Blöcke pro Tag: erste Zeile mit Soll/Delta/Bemerkung, Folgezeilen nur Beginn/Ende/Pause
- Encoding: UTF-8 mit BOM (Excel-kompatibel), Trennzeichen: Semikolon

### Per E-Mail senden

Zeitraum aus dem Datepicker wird übernommen. Empfänger vorausgefüllt mit hinterlegter E-Mail. Exporttyp: Zeitblöcke oder Abwesenheiten. Admin kann Benutzer auswählen.

---

## Monats- und Jahresabschluss

Aufruf unter `/periods`.

- Abgeschlossene Monate sperren alle Einträge
- **Jahresabschluss**: Nur Monate ab `tracking_start_date` müssen abgeschlossen sein
- Entsperren: nur durch Admins (über Admin-Bereich → Benutzerübersichten → Abschlüsse)

---

## Admin-Bereich

Aufruf unter `/admin`. Accordion-Layout mit zwei Tabs.

### Admin-Rollen

| Rolle | Beschreibung |
|-------|-------------|
| **🔧 Systemadmin** (`admin_role='sysadmin'`) | Voller Zugriff auf beide Tabs. Benutzerverwaltung, Rollenvergabe, Maileinstellungen, Bot, Backup, Update, Erscheinungsbild |
| **📋 Zeitmanager** (`admin_role='timemanager'`) | Nur Tab „Benutzerübersichten". Urlaubsübersicht, Abwesenheiten, Gleitzeitkonto, Zeitschemas, Urlaubsübertrag-Ausnahmen, Identität annehmen (nur normale User) |

### Tab: ⚙ Systemeinstellungen (nur Systemadmin)

| Accordion | Inhalt |
|-----------|--------|
| **Benutzerverwaltung** | User anlegen, Rollen vergeben, löschen. Badges: 🔧 Systemadmin, 📋 Zeitmanager |
| **Maileinstellungen** | SMTP-Konfiguration; STARTTLS Port 587; Test-Mail senden |
| **Überstunden-Limits (Defaults)** | Globale Standard-Plus/Minus-Limits für alle User |
| **Erscheinungsbild** | Akzentfarbe, Navigationsfarbe, App-Label für Dev/Prod-Unterscheidung |
| **Backup & Restore** | Vollständig / Einstellungen / User-Daten; automatisches Backup mit Zeitplan |
| **Telegram Bot** | Bot-Token, API-Key, Admin-IDs; Service starten/stoppen |
| **System Update** | Git pull + Neustart direkt aus der App |

### Tab: 👥 Benutzerübersichten (beide Rollen)

| Accordion | Inhalt |
|-----------|--------|
| **Urlaubsübersicht** | Anspruch, Übertrag, Verbrauch, Resturlaub je User; CSV-Export |
| **Gleitzeitkonto Übersicht** | Salden aller User; individuelle Plus/Minus-Limits; Benachrichtigungen (E-Mail + Telegram); Intervall: einmalig/täglich/wöchentlich |
| **Zeitschemas** | Aktuelles Soll je User; Link zu Zeitschema-Verwaltung |
| **Urlaubsverwaltung** | Übertrag-Ausnahmen (31.03.-Regel) je User |
| **Abschlüsse** | Monats- und Jahresabschlüsse; Entsperren |

### Schutzregeln

- Eigener Account nicht löschbar
- Letzter aktiver Systemadmin nicht degradierbar
- Admins können keine andere Admin-Identität annehmen
- Sysadmin kann die eigene Rolle nicht selbst ändern

---

## Technischer Betrieb

### Voraussetzungen

- Python 3.x + virtualenv unter `/opt/zeiterfassung/.venv`
- SQLite-Datenbank (via `ZEITERFASSUNG_DB`, Standard: `zeiterfassung.db`)
- Gunicorn via systemd (`zeiterfassung`)
- Telegram-Bot via systemd (`zeiterfassung-bot`)

### Starten / Neustarten

```bash
systemctl restart zeiterfassung zeiterfassung-bot
systemctl status zeiterfassung zeiterfassung-bot
journalctl -u zeiterfassung -f
```

### Backup

Vollständiges Backup über den Admin-Bereich (Systemeinstellungen → Backup & Restore) oder manuell:

```bash
cp /opt/zeiterfassung/zeiterfassung.db /opt/zeiterfassung/zeiterfassung.db.bak
```

### SMTP-Konfiguration

Über den Admin-Bereich (Systemeinstellungen → Maileinstellungen) oder via Umgebungsvariablen in der systemd-Unit:

```
Environment="MAIL_SERVER=mail.beispiel.de"
Environment="MAIL_PORT=587"
Environment="MAIL_USERNAME=user@beispiel.de"
Environment="MAIL_PASSWORD=geheim"
Environment="MAIL_FROM=Zeiterfassung <user@beispiel.de>"
```

### Architektur

| Datei | Beschreibung |
|-------|-------------|
| `app.py` | Alle Routes und Business-Logik (~11.000 Zeilen) |
| `db.py` | Datenbankinitialisierung und Migrationen |
| `auth.py` | Session-basierte Authentifizierung, Rollen-Decorators |
| `templates.py` | HTML-Layout-Wrapper (f-strings) |
| `bot.py` | Telegram-Bot mit APScheduler |
| `backup.py` | Backup-Logik (full / settings / user) |
| `calendar_seed.py` | Import NRW-Feiertage 2026 |

---

## Versionshistorie

### v1.4.5
- Admin-Rollen: Systemadmin (voller Zugriff) und Zeitmanager (nur Benutzerübersichten)
- Rollenvergabe in Benutzerverwaltung; Schutz letzter Sysadmin
- Telegram-Bot: Admin-Befehle auch für Zeitmanager (DB-Rollenprüfung)
- Hilfe-Seite: Admin-Abschnitt rollenabhängig erweitert

### v1.4.4
- fix: SMTP `SMTPSenderRefused` behoben (`from_addr` → `username` als Envelope-Sender)
- feat: Admin-Seite in zwei Tabs aufgeteilt: „Systemeinstellungen" und „Benutzerübersichten"
- feat: Überstunden-Defaults separater Accordion im System-Tab

### v1.4.3
- Gleitzeitkonto-Übersicht für Admin: Salden, Limits, Benachrichtigungen
- E-Mail + Telegram-Benachrichtigung bei Limit-Überschreitung (einmalig/täglich/wöchentlich)
- APScheduler im Telegram-Bot: tägliche Prüfung um 08:00

### v1.4.2
- Urlaubslimit-Validierung: normale User können kein Urlaub über Kontingent eintragen
- Admin-Abwesenheitsübersicht: Urlaubsstatus, Detailansicht je User, CSV-Export

### v1.4.1
- Anpassbare App-Farben: Akzent, Navigation, Label für Dev/Prod-Unterscheidung
- Erscheinungsbild-Einstellungen in Admin-Bereich

### v1.4.0 und älter
- Admin-Bereich zusammengefasst: Accordion-Layout
- CSV-Export per E-Mail (Zeitblöcke + Abwesenheiten)
- Tagesansicht Redesign, kompaktes 2-Spalten-Grid
- Kontierungsfunktion, Admin-Identitätswechsel, Zeitschema-Verwaltung
- Urlaubsübertrag-Ausnahme, Wochenend-Ausnahmen

---

*Zeiterfassung v1.4.5 – Flask + SQLite – NRW*
