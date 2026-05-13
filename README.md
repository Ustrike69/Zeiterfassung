# Zeiterfassung v4.6.6

Mehrbenutzer-Zeiterfassungs-Web-App auf Basis von Flask + SQLite. Erfassung von Arbeitszeiten, Abwesenheiten und Dienstreisen mit automatischer Saldoberechnung, Kontierungsfunktion und Admin-Benutzerverwaltung.

---

## Inhaltsverzeichnis

1. [Erste Schritte](#erste-schritte)
2. [Übersicht (Startseite)](#übersicht-startseite)
3. [Zeiterfassung](#zeiterfassung)
4. [Kalender](#kalender)
5. [Gleitzeitkonto](#gleitzeitkonto)
6. [Abwesenheiten](#abwesenheiten)
7. [Dienstreisen](#dienstreisen)
8. [Kontierung](#kontierung)
9. [Einstellungen](#einstellungen)
10. [Monats- und Jahresabschluss](#monats--und-jahresabschluss)
11. [Admin-Bereich](#admin-bereich)
12. [Technischer Betrieb](#technischer-betrieb)
13. [Versionshistorie](#versionshistorie)

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

## Zeiterfassung

### Tagesansicht (`/day/JJJJ-MM-TT`)

**Reihenfolge der Sektionen:**
1. Zeitblock hinzufügen
2. Vorhandene Zeitblöcke
3. Abwesenheit hinzufügen
4. Vorhandene Abwesenheiten
5. Dienstreise

Mehrere Zeitblöcke pro Tag möglich. Gehen-Zeit ist Pflichtfeld. Alle Zeiteingaben in 15-Minuten-Schritten.

### Wochenende / Feiertage

Erfassung standardmäßig blockiert. „Ausnahme setzen"-Button ermöglicht trotzdem speichern.

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

Tag | Datum | Beginn | Ende | Pause | Soll | Delta | (Desktop: kum. Saldo)

- Mehrere Zeitblöcke: nur erste Zeile zeigt Tag + Datum
- Wochenenden + Feiertage: dezent (gedimmt)
- Urlaub/Krank/Feiertag: farbiges Badge
- Klick auf Zeile → Tages-Editor

### Saldo-Berechnung

Iteriert über alle Tage ab `tracking_start_date` bis heute. Identisch mit der Detailansicht. Flextag-Tage reduzieren den Saldo zusätzlich um die Sollzeit.

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

## Monats- und Jahresabschluss

Aufruf unter `/periods`.

- Abgeschlossene Monate sperren alle Einträge
- **Jahresabschluss**: Nur Monate ab `tracking_start_date` müssen abgeschlossen sein – Monate vor Arbeitsbeginn blockieren nicht
- Entsperren: nur durch Admins

---

## Admin-Bereich

Aufruf unter `/admin`.

### Benutzerverwaltung

- Neue User anlegen (mit Arbeitsbeginn-Datum)
- Passwörter zurücksetzen · Admin-Rechte · Deaktivieren/Löschen
- **Identität annehmen**: Als anderer User agieren (oranger Banner + „Zurück zu Admin")
- Zeitschema-Verwaltung pro User (Bearbeiten/Löschen/Überlappungswarnung)
- Urlaubsübertrag-Ausnahme pro User

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

### Architektur

| Datei | Beschreibung |
|-------|-------------|
| `app.py` | Alle Routes und Business-Logik (~6.300 Zeilen) |
| `db.py` | Datenbankinitialisierung und Migrationen |
| `auth.py` | Session-basierte Authentifizierung |
| `templates.py` | HTML-Layout-Wrapper (f-strings) |
| `calendar_seed.py` | Import NRW-Feiertage 2026 |

---

## Versionshistorie

### v4.6.6
- Wochenende-Widget an kompaktes Zeiterfassungs-Design angepasst

### v4.6.5
- Zeiterfassung Redesign: kompakteres Layout, Widgets nebeneinander (Desktop)

### v4.6.4
- Einstellungen Redesign: 4 Accordion-Bereiche

### v4.6.3
- Dienstreisen: Datum-Link entfernt, Button-Design angepasst

### v4.6.2
- Kontieren-Button vereinheitlicht, Soll-Spalte im Gleitzeitkonto, Feiertage dezent

### v4.6.1
- Alle Buttons vereinheitlicht (.btn-primary/.btn-secondary/.btn-danger)

### v4.6.0
- Kritischer Server-Error behoben, globale Button-Vereinheitlichung

### v4.5.9
- Zurück-Button auf allen Seiten

### v4.5.8
- Desktop Übersicht: 4er-Grid, Kontierung kompakt

### v4.5.7
- Übersicht Redesign: Buttons oben, Links→Buttons, kompaktere Salden

### v4.5.6
- Mobile Timepicker: nur 15-Minuten-Schritte

### v4.5.5
- Fix Gehen-Feld Validierungs-Bug Mobile

### v4.5.4
- Tages-Editor: Sektionen-Reihenfolge + Zurück-Button

### v4.5.3
- Desktop Gleitzeitübersicht: einheitliches Layout mit Mobile

### v4.5.2
- Mobile Gleitzeitübersicht: mehrere Zeitblöcke pro Tag

### v4.5.1
- Mobile Gleitzeitübersicht: kompaktes Spalten-Layout

### v4.5.0
- Kontierung aktivieren/deaktivieren mit Startdatum

### v4.4.9
- Urlaub-Übertrag Ausnahme-Regelung pro User

### v4.4.8
- Admin Identitätswechsel (Impersonation)

### v4.4.7
- Dashboard-Saldo identisch mit Details (_iter_days)

### v4.4.6
- Gleitzeitkonto: Wochentag, farbige Werte, Link zur Zeiterfassung

### v4.4.5
- Zeitschema-Verwaltung: Bearbeiten + Löschen

### v4.4.4
- Gleitzeitkonto: Status-Badges, dezente Zeilen

### v4.4.3
- Gleitzeitkonto: Wochentag eingeblendet

### v4.4.2
- Gleitzeitkonto: positive grün, negative rot

### v4.4.1
- Zeitschema bearbeiten/löschen

### v4.4.0
- Zeitraum-Filterung nach Arbeitsbeginn, Jahresabschluss-Fix

### v4.3.9
- Anfangsdatum-Validierung

### v4.3.8
- Ausnahme-Funktion Wochenende/Feiertag

### v4.3.7
- Kalender-Layout: Urlaub auf gleicher Höhe

### v4.3.0 – v4.3.6
- Kontierungsfunktion eingeführt und verfeinert

### v4.2.0 – v4.2.1
- Einheitlicher Timepicker, 15-Minuten-Schritte, Bugfixes

---

*Zeiterfassung v4.6.6 – Flask + SQLite – NRW*
