# Zeiterfassung v2.0.9

Mehrbenutzer-Zeiterfassungs-Web-App auf Basis von Flask + SQLite. Erfassung von Arbeitszeiten, Abwesenheiten und Dienstreisen mit automatischer Saldoberechnung, Kontierungsfunktion, CSV-Export per E-Mail, Telegram-Bot und einem umfassenden Admin-Bereich mit Rollentrennung.

Vollständig mehrsprachig (Deutsch / Englisch), europäische Feiertagsdatenbank für 20 Länder.

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

Aufruf der App im Browser. Beim ersten Start wird ein Admin-Konto über `/setup` angelegt – inklusive Sprach- und Regionsauswahl. Anmeldung unter `/login`.

### Einrichtungs-Wizard (Onboarding)

Neue Nutzer werden beim ersten Login durch einen Wizard geführt (`/onboarding`).

| Schritt | Inhalt |
|---------|--------|
| 0 | **Nutzungsart** – Zeitkonto oder nur Verwaltung (Systemadmin-Setup) |
| 1 | **Passwort ändern** – Pflicht |
| 2 | **Profil** – Anzeigename und E-Mail |
| 3 | **Zeitschema** – Wochenstunden, Modus, Arbeitstage |
| 4 | **Urlaubskontingent** – Anspruch und Übertrag |
| 5 | **Startsaldo & Erfassung ab** – Gleitzeitguthaben und frühestes Erfassungsdatum |
| 6 | **Zusammenfassung** – Bestätigung |

### Sprache

Die App unterstützt **Deutsch** (Standard) und **Englisch**. Die Sprache ist pro Nutzer in den Einstellungen wählbar. Administratoren können eine systemweite Standardsprache festlegen. Die Telegram-Bot-Nachrichten folgen ebenfalls der Nutzersprache.

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

Übersicht Urlaub / Krank / Flextag / Sonstige. Button „Alle Abwesenheiten".

---

## Zeiterfassung (Tagesansicht)

Aufruf unter `/day/JJJJ-MM-TT`. Kompaktes 2-Spalten-Grid auf Desktop (Zeit links | Abwesenheit rechts).

### Header

Wochentag + Datum mit ◀ / ▶ Navigation. Soll / Ist / Δ-Badges direkt im Header.

### Zeitblöcke

Mehrere Zeitblöcke pro Tag möglich. Formular: Kommen + Gehen + Pause in einer Zeile, Speichern-Button direkt daneben. Alle Zeiteingaben in 15-Minuten-Schritten.

### Abwesenheit

Typ-Auswahl (gefiltert nach nutzerindividuellen Abwesenheitstypen) und ½-Tag-Checkbox in einer Zeile. Bestehende Abwesenheit wird nicht überschrieben.

### Wochenende / Feiertage

Erfassung standardmäßig blockiert. Kompakter Hinweisbanner mit „Ausnahme setzen"-Button direkt daneben.

### Dienstreise

Ort + Datum + Mehrtägig-Checkbox in einer Zeile. Zeiten (Abreise, Ziel, Rückreise, Zuhause) in einer Zeile.

---

## Kalender

Monatsansicht mit Navigation. Wechsel zwischen Monat-, Listen- und Jahresansicht.

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

Iteriert über alle Tage ab `tracking_start_date` bis gestern (Stand gestern). Flextag-Tage reduzieren den Saldo zusätzlich um die Sollzeit.

---

## Abwesenheiten

Aufruf unter `/absences`.

| Typ | Beschreibung |
|-----|-------------|
| **Urlaub** | Gegen Urlaubskontingent; Limit-Prüfung verhindert Überschreitung |
| **Krank** | Krankheitstage |
| **Flextag** | Eigener Typ (blau); Setzt Soll auf 0 und zieht Sollzeit zusätzlich vom Gleitzeitkonto ab |
| **Sonstige** | Pflichtfeld Bemerkung (freie Eingabe) |

**Nutzerindividuelle Typen:** Pro Nutzer konfigurierbar, welche Abwesenheitstypen verfügbar sind (Urlaub und Krank immer aktiv).

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

Aufruf unter `/settings`. Accordion-Bereiche:

| Bereich | Inhalt |
|---------|--------|
| **Persönliche Einstellungen** | Name, E-Mail, Geburtsdatum, Renteneintrittsalter, Telegram-ID |
| **Passwort** | Passwortänderung mit Stärke-Anzeige |
| **Sprache** | Deutsch / Englisch wählbar |
| **Urlaub** | Jahresanspruch, Übertrag-Regelung (Standard 31.03. oder Ausnahme) |
| **Zeitschema** | Aktuelle + alle Schemas, Bearbeiten/Löschen/Neu anlegen |
| **Gleitzeitkonto** | Aktivieren/Deaktivieren + Startsaldo |
| **Kontierung** | Aktivieren/Deaktivieren + Startdatum |

---

## Export

Aufruf unter `/export`.

### Download (CSV)

Zeitraum wählbar (Datepicker + Schnellwahl: Akt. Monat / Letzter Monat / Akt. Jahr).

Verfügbare Exporte: Zeitblöcke · Abwesenheiten · Dienstreisen · Gleitzeitkonto · Feiertage · Benutzer (Systemadmin)

### CSV-Format (Zeitblöcke)

Spalten: **Wochentag | Datum | Beginn | Ende | Pause (min) | Soll | Delta | Bemerkung**

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
| **🔧 Systemadmin** (`admin_role='sysadmin'`) | Voller Zugriff auf beide Tabs; Benutzerverwaltung, Rollenvergabe, alle Systemeinstellungen |
| **📋 Zeitmanager** (`admin_role='timemanager'`) | Nur Tab „Benutzerübersichten"; Urlaubsübersicht, Abwesenheiten, Gleitzeitkonto, Zeitschemas, Abschlüsse, Identitätswechsel |

**Admin-Only-Nutzer:** Konten ohne Zeitkonto – ausschließlich im Admin-Bereich tätig. Kein Zugriff auf Kalender, Gleitzeitkonto oder Abwesenheitsseiten.

### Tab: ⚙ Systemeinstellungen (nur Systemadmin)

| Accordion | Inhalt |
|-----------|--------|
| **Benutzerverwaltung** | User anlegen (inkl. Rollen-Dropdown, Admin-Only-Flag, Passwort-Mail), bearbeiten, löschen |
| **Maileinstellungen** | SMTP-Konfiguration; STARTTLS Port 587; Test-Mail senden |
| **Überstunden-Limits (Defaults)** | Globale Standard-Plus/Minus-Limits für alle User |
| **Regionale Einstellungen** | Standard-Region (System) + zweistufige Länder/Region-Auswahl |
| **Erscheinungsbild** | Akzentfarbe, Navigationsfarbe, App-Label für Dev/Prod-Unterscheidung; Schnell-Presets |
| **Backup & Restore** | Vollständig (.db.gz) / Einstellungen (.json) / User-Daten (.json); automatisches Backup mit Zeitplan |
| **Telegram Bot** | Bot-Token, Anthropic API Key, Admin-IDs; Service starten/stoppen/neu starten direkt aus UI |
| **System Update** | Git pull + pip install + Neustart direkt aus der App; Commit-Info und System-Info |

### Tab: 👥 Benutzerübersichten (beide Rollen)

| Accordion | Inhalt |
|-----------|--------|
| **Benutzer & Passwort-Reset** | PW-Reset per Zufallspasswort + Mail; Identitätswechsel |
| **Urlaubsübersicht** | Anspruch, Übertrag, Verbrauch, Geplant, Resturlaub je User; CSV-Export |
| **Gleitzeitkonto Übersicht** | Salden aller User; individuelle Plus/Minus-Limits; E-Mail + Telegram-Benachrichtigungen; Intervall: einmalig/täglich/wöchentlich |
| **Zeitschemas** | Aktuelles Soll je User; Link zu Zeitschema-Verwaltung |
| **Urlaubsverwaltung** | Übertrag-Ausnahmen (31.03.-Regel) je User |
| **Abschlüsse** | Monats- und Jahresabschlüsse; Entsperren |
| **Abwesenheitstypen & Regionen** | Nutzerindividuelle Abwesenheitstypen; Region pro Nutzer |

### Schutzregeln

- Eigener Account nicht löschbar
- Letzter aktiver Systemadmin nicht degradierbar
- Admins können keine andere Admin-Identität annehmen
- Sysadmin kann die eigene Rolle nicht selbst ändern

---

## Technischer Betrieb

### Voraussetzungen

- Python 3.11+ + virtualenv unter `/opt/zeiterfassung/.venv`
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

### Feiertage / Regionen

20 Länder, 51 Regionen vorkonfiguriert (DE 16 Bundesländer, AT, CH, FR, NL, BE, LU, PL, CZ, IT, ES, PT, GB, IE, DK, SE, NO, FI, GR). Zweistufige Auswahl (Land → Region) in Nutzer- und Systemeinstellungen. Orthodoxes Ostern (GR), bewegliche Feiertage (Schweden, Finnland) werden korrekt berechnet.

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
| `app.py` | Alle Routes und Business-Logik (~12.000 Zeilen) |
| `db.py` | Datenbankinitialisierung und Migrationen |
| `auth.py` | Session-basierte Authentifizierung, Rollen-Decorators |
| `templates.py` | HTML-Layout-Wrapper (f-strings) |
| `translations.py` | i18n-Framework: DE/EN Übersetzungen, `t(key)` Hilfsfunktion |
| `bot.py` | Telegram-Bot mit APScheduler |
| `bot_translations.py` | Bot-spezifische Übersetzungen DE/EN |
| `backup.py` | Backup-Logik (full / settings / user) |
| `calendar_seed.py` | Feiertags-Seeding für 20 Länder / 51 Regionen |

---

## Versionshistorie

### v2.0.9
- **Abwesenheits-Genehmigung:** Neue Genehmiger-Rolle (`is_approver`); pro User konfigurierbar welche Abwesenheitstypen genehmigt werden müssen und wer genehmigt; Genehmigungsübersicht `/approvals` mit Pending / Vergangene Entscheidungen; Mail + Telegram-Benachrichtigung bei Anfrage und Entscheidung; Pending-Abwesenheiten werden nicht im Gleitzeitkonto berücksichtigt; Bot-Befehle `/genehmigungen`, `genehmigen <ID>`, `ablehnen <ID> <Grund>`
- **Zeitzone konfigurierbar:** Neue Einstellung `timezone` in `app_config`; wählbar bei Ersteinrichtung (`/setup`) und in Admin → Systemeinstellungen; alle Zeitanzeigen und Sperr-Uhrzeiten nutzen die konfigurierte Zeitzone (Standard: `Europe/Berlin`)
- **2FA (TOTP):** Aktivierung unter Einstellungen → Sicherheit; QR-Code-Scan mit Authenticator-App; 8 Backup-Codes; Bot-Unterstützung
- **Login-Sperre:** Nach 3 Fehlversuchen 30 Minuten Sperre; Entsperr-Link per Mail (in User-Sprache); Timezone-korrekte Anzeige der Sperrzeit; Admin-Entsperren manuell; Mail-Versand jetzt mit korrektem App-Kontext (Thread-Fix)
- **E-Mail bei Benutzererstellung:** Feld „E-Mail" im Formular „Neuer User" (Admin-Panel); wird direkt in `users.email` gespeichert
- **Flash Messages vollständig mehrsprachig:** Alle `add_flash()`-Aufrufe nutzen `t()`; ~130 neue `flash.error.*` / `flash.success.*` Schlüssel in DE + EN
- **Backup-Verschlüsselung:** Optionale AES/Fernet-Verschlüsselung beim Download; Passwort nicht gespeichert
- **Passwort-Compliance:** Bestehende Konten werden als nicht-konform markiert; Pflicht zur Änderung beim nächsten Login
- **DB-Pfad auf Login-Seite entfernt**

### v2.0.5
- **Kalender-Export:** .ics-Download und webcal://-Abonnement für alle Abwesenheiten; Präfix pro Nutzer konfigurierbar; Token-Reset macht alte Abos ungültig
- **CalDAV-Server:** PROPFIND/REPORT/GET-Routen für Home Assistant CalDAV-Integration; Token-Auth (`/caldav/<token>/`) und Basic Auth (`/caldav/basic/`); Authentifizierung wählbar (Token / HTTP Basic)
- **Apple iCloud Synchronisation (ausgehend):** Abwesenheiten werden automatisch in einen iCloud-Kalender geschrieben (Erstellen / Bearbeiten / Löschen); App-spezifisches Passwort Fernet-verschlüsselt gespeichert; Test-Verbindung und Alle-synchronisieren-Funktion in den Einstellungen; mehrere Nutzer können in denselben Kalender schreiben (Unterscheidung über Präfix)
- **Externe + Interne Server-URL** in den Systemeinstellungen für Kalender-Abo-Links und lokale Integrationen

### v2.0.0
- **Mehrsprachigkeit (DE/EN):** Vollständige i18n-Unterstützung in App und Telegram-Bot; Sprache pro Nutzer wählbar; systemweite Standardsprache konfigurierbar; `t(key)` Framework mit Fallback-Kette
- **Europäische Feiertage:** 20 Länder, 51 Regionen (DE alle 16 Bundesländer, AT, CH, FR, NL, BE, LU, PL, CZ, IT, ES, PT, GB 4 Regionen, IE, DK, SE, NO, FI, GR); zweistufige Länder/Region-Auswahl; orthodoxes Ostern; bewegliche Feiertage
- **Admin-Only-Modus:** Nutzerkonten ohne Zeitkonto für reine Verwaltungsaccounts; eingeschränkte Navigation
- **Passwort-Regeln:** Stärkeprüfung bei Vergabe; Passwortänderung erzwingen (`must_change_password`); Passwortgenerierung + Versand per Mail; Passwort-Reset durch Admin
- **Flextag als eigene Abwesenheitsart:** Eigener Typ (blau, #3b82f6); Nutzerindividuelle Aktivierung von Abwesenheitstypen
- **Gleitzeitkonto Limits + Benachrichtigungen:** Plus/Minus-Limits global und pro Nutzer; E-Mail + Telegram-Benachrichtigung bei Überschreitung; Intervall: einmalig/täglich/wöchentlich; manuelle Prüfung aus Admin-UI
- **Urlaubslimit-Validierung:** Normale User können nicht über ihr Kontingent hinaus buchen
- **Bot-Einrichtung über Admin-UI:** Token, API-Key, Admin-IDs; Service-Steuerung (Start/Stop/Restart) direkt aus dem Browser
- **System-Update über Admin-UI:** git pull + pip install + Service-Neustart; Commit-Info und System-Info direkt in der App
- **App-Farben + Umgebungs-Label:** Akzentfarbe, Navigationsfarbe, Umgebungsbezeichnung (z. B. DEV/TEST/PROD) mit Farbwahl; Schnell-Presets
- **Backup-Typen getrennt:** Vollständig (.db.gz) + Einstellungen (.json, ohne Passwörter) + User-Daten (.json) als separate Exports; automatisches Backup mit Zeitplan und lokalem Archiv (max. 7)
- **Weiterer Systemadmin anlegbar:** Rollenvergabe bei Neuanlage; Schutz des letzten aktiven Sysadmins

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

*Zeiterfassung v2.0.9 – Flask + SQLite – 20 Länder*
