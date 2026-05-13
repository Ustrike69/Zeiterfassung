# Zeiterfassung v1.0.0

Mehrbenutzer-Zeiterfassungs-Web-App auf Basis von Flask + SQLite. Erfassung von Arbeitszeiten, Abwesenheiten und Dienstreisen mit automatischer Saldoberechnung, Kontierungsfunktion, CSV-Export per E-Mail und einem umfassenden Admin-Bereich.

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
| **Urlaub** | Gegen Urlaubskontingent |
| **Krank** | Krankheitstage |
| **Sonstige** | Pflichtfeld Bemerkung (Flextag, Verdi, freie Eingabe) |

**Flextag:** Setzt Soll auf 0 und zieht Sollzeit zusätzlich vom Gleitzeitkonto ab.

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
| **Persönliche Einstellungen** | Name, E-Mail, Passwort |
| **Urlaub** | Jahresanspruch, Übertrag-Regelung (Standard 31.03. oder Ausnahme) |
| **Zeitschema** | Aktuelle + alle Schemas, Bearbeiten/Löschen/Neu anlegen |
| **Kontierung** | Aktivieren/Deaktivieren + Startdatum |

---

## Export

Aufruf unter `/export`.

### Download (CSV)

Zeitraum wählbar (Datepicker + Schnellwahl: Akt. Monat / Letzter Monat / Akt. Jahr / Letztes Jahr).

Verfügbare Exporte: Zeitblöcke · Abwesenheiten · Dienstreisen · Gleitzeitkonto · Feiertage · Benutzer (Admin)

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
- Entsperren: nur durch Admins (über Admin-Bereich)

---

## Admin-Bereich

Aufruf unter `/admin`. Accordion-Layout mit 5 Bereichen:

### 1. Benutzerverwaltung

- Neue User anlegen (inline, per Button einblenden)
- Passwörter zurücksetzen · Admin-Rechte · Deaktivieren/Löschen
- **Identität annehmen**: Als anderer User agieren (oranger Banner + „Zurück zu Admin")

### 2. Zeitschemas

- Übersicht aller User mit aktuellem Soll-Wert
- Link zu Zeitschema-Verwaltung pro User (Bearbeiten/Löschen/Neu anlegen)

### 3. Urlaubsverwaltung

- Übersicht aller User mit Ausnahme-Kennzeichnung
- Übertrag-Ausnahme: ob Resturlaub am 31.03. verfällt oder unbegrenzt gilt

### 4. Abschlüsse

- Monats- und Jahresabschlüsse aller User mit Jahr-Auswahl
- Status pro User (Keine / X Monate / Jahr abgeschlossen)
- Alle Abschlüsse eines Users für ein Jahr entsperren

### 5. Maileinstellungen

- SMTP-Konfiguration (Server, Port, Benutzername, Passwort, Absender)
- Einstellungen werden in der DB gespeichert (Fallback: Umgebungsvariablen)
- Test-Mail an beliebige Adresse senden

### Schutzregeln

- Eigener Account nicht löschbar
- Letzter aktiver Admin nicht löschbar
- Admin kann keine andere Admin-Identität annehmen

---

## Technischer Betrieb

### Voraussetzungen

- Python 3.x + virtualenv unter `/opt/zeiterfassung/.venv`
- SQLite-Datenbank (via `ZEITERFASSUNG_DB`, Standard: `zeiterfassung.db`)
- Gunicorn via systemd

### Starten / Neustarten

```bash
systemctl restart zeiterfassung
systemctl status zeiterfassung
journalctl -u zeiterfassung -f
```

### Backup

```bash
cp /opt/zeiterfassung/zeiterfassung.db /opt/zeiterfassung/zeiterfassung.db.bak
```

### SMTP-Konfiguration

Entweder über den Admin-Bereich (Maileinstellungen) oder via Umgebungsvariablen in der systemd-Unit:

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
| `app.py` | Alle Routes und Business-Logik (~8.000 Zeilen) |
| `db.py` | Datenbankinitialisierung und Migrationen |
| `auth.py` | Session-basierte Authentifizierung |
| `templates.py` | HTML-Layout-Wrapper (f-strings) |
| `calendar_seed.py` | Import NRW-Feiertage 2026 |

---

## Versionshistorie

### v1.0.0
- Admin-Bereich zusammengefasst: Accordion-Layout mit 5 Bereichen (Benutzer, Zeitschemas, Urlaub, Abschlüsse, Mail)
- CSV-Export per E-Mail (Zeitblöcke + Abwesenheiten)
- Neues CSV-Format: Wochentag|Datum|Beginn|Ende|Pause|Soll|Delta|Bemerkung
- Admin Maileinstellungen: SMTP-Konfiguration in DB gespeichert, Verbindungstest
- Tagesansicht Redesign: kompaktes 2-Spalten-Grid, Soll/Ist/Δ im Header
- Einstellungen als Accordion (4 Bereiche)
- Button-Design vereinheitlicht (btn, btn-primary, btn-danger, btn-sm, btn-lg)
- Zurück-Button auf allen Seiten
- Mobile Timepicker: 15-Minuten-Schritte erzwungen
- Soll-Spalte im Gleitzeitkonto, Feiertage dezent gedimmt
- Wochenende/Feiertag-Widget: kompakter Inline-Banner

### v4.6.x (Basis)
- v4.6.6: Wochenende-Widget angepasst
- v4.6.5: Zeiterfassung Redesign kompakt
- v4.6.4: Einstellungen Accordion
- v4.6.3: Dienstreisen Button-Fix
- v4.6.2: Soll-Spalte, Feiertage gedimmt
- v4.6.1: Button-Vereinheitlichung
- v4.6.0: Kritischer Bug behoben
- v4.5.x: Zurück-Button, Dashboard Grid, Timepicker-Fixes

### v4.4.x – v4.5.x (Vorarbeit)
- Kontierungsfunktion, Admin-Identitätswechsel, Gleitzeitkonto-Redesign, Zeitschema-Verwaltung, Urlaubsübertrag-Ausnahme, Wochenend-Ausnahmen

---

*Zeiterfassung v1.0.0 – Flask + SQLite – NRW*
