# Zeiterfassung v3.1.0

Mehrbenutzer-Zeiterfassungs-Web-App auf Basis von Flask + SQLite. Erfassung von Arbeitszeiten, Abwesenheiten und Dienstreisen mit automatischer Saldoberechnung.

---

## Inhaltsverzeichnis

1. [Erste Schritte](#erste-schritte)
2. [Übersicht (Startseite)](#übersicht-startseite)
3. [Zeiterfassung](#zeiterfassung)
4. [Kalender](#kalender)
5. [Abwesenheiten](#abwesenheiten)
6. [Dienstreisen](#dienstreisen)
7. [Stundensaldo](#stundensaldo)
8. [Einstellungen](#einstellungen)
9. [Monats- und Jahresabschluss](#monats--und-jahresabschluss)
10. [Admin-Bereich](#admin-bereich)
11. [Technischer Betrieb](#technischer-betrieb)

---

## Erste Schritte

### Login

Aufruf der App im Browser. Beim ersten Start wird ein Admin-Konto über `/setup` angelegt.

Anmeldung mit Benutzername (Kleinschreibung) und Passwort unter `/login`.

### Sprache und Format

Die App ist vollständig auf Deutsch. Datumsangaben werden im Format **TT.MM.JJJJ** angezeigt und eingegeben. Uhrzeiten im Format **HH:MM**. Alle Datums- und Zeitfelder unterstützen sowohl direkte Texteingabe als auch die Auswahl per Kalender- bzw. Zeit-Picker.

---

## Übersicht (Startseite)

Die Startseite zeigt auf einen Blick die wichtigsten Informationen des aktuellen Jahres:

### Gleitzeitkonto
Aktueller Stundenssaldo (Über-/Unterstunden) in Stunden und Minuten. Grün = Plusstunden, Rot = Minusstunden. Link zu den Details führt zur Saldo-Ansicht.

### Resturlaub
Verbleibende Urlaubstage des aktuellen Jahres. Angezeigt wird die Anzahl der noch verfügbaren Tage sowie das Gesamtkontingent.

**Übertrag-Regel:** Urlaubstage aus dem Vorjahr müssen bis **31.03.** angetreten sein (Urlaubsbeginn ≤ 31.03.), können aber nach dem 31.03. noch enden. Nicht bis 31.03. angetretener Übertrag verfällt. Bis zum 31.03. wird ein Hinweis angezeigt.

### Fehlende Einträge
Anzahl vergangener Arbeitstage im aktuellen Jahr, für die noch kein Zeiteintrag vorhanden ist (kein Urlaub, kein Feiertag, keine Abwesenheit). Link führt direkt zum Kalender.

### Abwesenheitskarte
Kompakte Übersicht aller Abwesenheiten des aktuellen Jahres:

- **Urlaub:** Genommen / Geplant / Verfügbar
- **Krank:** Anzahl Tage (nur vergangene)
- **Verdi:** Genommen / Geplant
- **Flextag:** Genommen / Geplant

Nur Gruppen mit mindestens einem Eintrag werden angezeigt. Urlaub wird immer angezeigt.

### Button „Zeiterfassung heute"
Direktlink zur Tagesansicht des heutigen Tages.

---

## Zeiterfassung

### Tagesansicht (`/day/TT.MM.JJJJ`)

Aufruf über den Button auf der Startseite oder direkt über den Kalender. Pro Tag können mehrere Zeitblöcke erfasst werden (z. B. Vormittag und Nachmittag getrennt).

Jeder Zeitblock hat:
- **Startzeit** und **Endzeit**
- Optional: Pause

Die Summe aller Zeitblöcke ergibt die Ist-Zeit des Tages, die mit dem Soll-Wert (laut Arbeitszeitmodell) verglichen wird.

### Arbeitstage ohne Eintrag

Im Kalender werden vergangene Arbeitstage ohne Zeiteintrag mit einem kleinen roten **✕** unten rechts in der Tageszelle markiert. Die Anzahl wird auch auf der Startseite angezeigt.

---

## Kalender

Aufruf über die Navigation. Anzeige eines Monats mit Navigations-Pfeilen und „Heute"-Button.

### Zelleninhalt

Jede Tageszelle zeigt:
- Erfasste Stunden (Ist-Zeit des Tages)
- Abwesenheits-Badge (Urlaub, Krank, Sonstige)
- Feiertagsname (falls Feiertag)
- ✈ + Ort bei Dienstreisen
- ✕ bei vergangenen Arbeitstagen ohne Eintrag

### Legende

Am oberen Rand des Kalenders: Abwesenheit | Feiertag | ✕ fehlender Eintrag

### Abgeschlossene Monate

Abgeschlossene Monate zeigen ein 🔒-Symbol im Monatstitel. Einträge in gesperrten Monaten können nicht mehr bearbeitet werden.

---

## Abwesenheiten

Aufruf über die Navigation unter `/absences`.

### Typen

Es gibt drei fest definierte Abwesenheitstypen:

| Typ | Beschreibung |
|-----|-------------|
| **Urlaub** | Geplanter Urlaub, wird gegen das Urlaubskontingent gerechnet |
| **Krank** | Krankheitstage |
| **Sonstige** | Alle anderen Abwesenheiten, mit Pflichtfeld „Bemerkung" |

### Sonstige – Bemerkungen

Bei Typ „Sonstige" muss eine Bemerkung eingetragen werden. Vorbelegte Auswahlmöglichkeiten:
- **Verdi** (Gewerkschaftsveranstaltung)
- **Flextag** (Freizeitausgleich für Überstunden)
- **Neuer Eintrag** (freie Eingabe)

Alle selbst eingegebenen Bemerkungen werden gespeichert und stehen künftig als Vorauswahl zur Verfügung.

### Flextag-Logik

Ein Flextag gilt als genommener Ausgleich für angesammelte Plusstunden: Der Soll-Wert des Tages wird auf 0 gesetzt (kein Fehlzeitvormwurf) und zusätzlich vom Gleitzeitkonto abgezogen. Nur vergangene Flextage wirken sich auf den Saldo aus.

### Neue Abwesenheit anlegen

Button „+ Neu" oben rechts. Pflichtfelder: Typ, Von-Datum. Bis-Datum optional (bei eintägigen Abwesenheiten gleich dem Von-Datum).

### Übersicht

Tabelle mit allen Abwesenheiten, filterbar nach Zeitraum. Spalten: Typ, Von, Bis, Umfang, Kommentar (nur bei Sonstige). Datumformat: TT.MM.JJJJ.

---

## Dienstreisen

Dienstreisen sind **zusätzliche Informationen** zu einem Tag – die Arbeitszeit muss separat über die normale Zeiterfassung eingetragen werden.

### Neue Dienstreise anlegen

Über `/business_trips` → Button „+ Neue Dienstreise", oder direkt in der Tagesansicht über den Abschnitt „Dienstreise".

### Felder

| Feld | Pflicht | Beschreibung |
|------|---------|-------------|
| Ort | ✓ | Reiseziel |
| Startdatum | ✓ | Abreisedatum |
| Mehrtägig | – | Checkbox: aktiviert Enddatum-Feld |
| Enddatum | – | Nur bei mehrtägigen Reisen |
| Abreise Start | – | Uhrzeit Abfahrt |
| Abreise Ende | – | Uhrzeit Ankunft am Ziel |
| Rückreise Start | – | Uhrzeit Abfahrt Rückreise |
| Rückreise Ende | – | Uhrzeit Ankunft zuhause |
| Notizen | – | Freitext |

### Anzeige im Kalender

An Reisetagen wird ✈ + Ort in der Tageszelle angezeigt. Bei mehrtägigen Reisen erscheint das Symbol an jedem betroffenen Tag.

### Übersicht `/business_trips`

Tabelle aller Dienstreisen, sortiert nach Datum (neueste zuerst), filterbar nach Jahr. Bei mehrtägigen Reisen: Datumsbereich TT.MM. – TT.MM.JJJJ.

---

## Stundensaldo

Aufruf über die Navigation unter `/balance`.

### Zeitraum-Auswahl

Oben auf der Seite: Auswahl von **Jahr** und **Monat** (oder „Gesamtes Jahr"). Standard: aktueller Monat.

### Saldo-Tabelle

Tageweise Auflistung mit: Datum, Soll, Ist, Tagesdelta, kumulierter Saldo. Der Startsaldo des gewählten Monats wird oben ausgewiesen.

### Abwesenheits-Zusammenfassung

Unterhalb der Tabelle: Aufschlüsselung der Abwesenheitstage im gewählten Zeitraum, getrennt nach:

**Erfasst** (vergangene Tage):
- Urlaub, Krank, Sonstige (gruppiert nach Bemerkung)
- Flextage: mit Hinweis „(vom Gleitzeitkonto)"

**Geplant** (zukünftige Tage):
- Urlaub, Flextag, Verdi, Sonstige

---

## Einstellungen

Aufruf unter `/settings`.

### Arbeitszeitmodell

Zwei Modi:
- **Wöchentlich:** Gesamte Wochenstunden werden gleichmäßig auf Arbeitstage verteilt
- **Täglich:** Explizite Minutenziele pro Wochentag

Mehrere Arbeitszeitmodelle mit Gültigkeitsdaten möglich (z. B. bei Stundenreduzierung).

### Arbeitstage

Konfiguration per Bitmask (Mo–So). Feiertage und Wochenenden können das Soll blockieren.

### Urlaubskontingent

Jährliches Urlaubskontingent in Tagen. Übertrag aus dem Vorjahr wird separat erfasst.

---

## Monats- und Jahresabschluss

Aufruf unter `/periods`.

### Abschluss

Vergangene Monate können abgeschlossen werden. Ein abgeschlossener Monat sperrt alle Einträge (Zeitblöcke, Abwesenheiten, Dienstreisen) gegen weitere Bearbeitung.

Ein Jahresabschluss schließt automatisch alle noch offenen Monate des Jahres ab.

### Gesperrte Zeiträume

- Im Kalender: 🔒 im Monatstitel
- In der Tagesansicht: Hinweis „Monat abgeschlossen" statt Bearbeiten-Buttons
- Bei Versuch einer Bearbeitung: Fehlermeldung

### Entsperren

Nur Admins können Abschlüsse rückgängig machen. Der laufende Monat kann nicht abgeschlossen werden.

---

## Admin-Bereich

Aufruf unter `/admin`. Nur für Benutzer mit Admin-Rolle zugänglich.

### Benutzerverwaltung (`/admin/users`)

- Neue Benutzer anlegen
- Passwörter zurücksetzen
- Admin-Rechte vergeben/entziehen
- Benutzer deaktivieren

### Abwesenheits-Entsperrung

Admins können Periodenabschlüsse anderer Benutzer einsehen und entsperren.

### Feiertage

Feiertage werden automatisch über `calendar_seed.py` für NRW (DE-NW) importiert. Eine manuelle Bearbeitung ist nicht vorgesehen.

---

## Technischer Betrieb

### Voraussetzungen

- Python 3.x mit virtualenv unter `/opt/zeiterfassung/.venv`
- SQLite-Datenbank (Pfad via `ZEITERFASSUNG_DB` Umgebungsvariable, Standard: `zeiterfassung.db` im Arbeitsverzeichnis)

### Starten

```bash
# Entwicklung
cd /opt/zeiterfassung
.venv/bin/python app.py

# Produktion (Gunicorn via systemd)
systemctl start zeiterfassung
systemctl restart zeiterfassung
systemctl status zeiterfassung
```

### Datenbankmigrationen

Migrationen laufen automatisch beim Start über `db.py` (`init_db()`). Kein manueller Eingriff nötig.

### Logs

```bash
journalctl -u zeiterfassung -f
```

### Backup

Vor Updates empfiehlt sich ein Backup der Datenbankdatei:

```bash
cp /opt/zeiterfassung/zeiterfassung.db /opt/zeiterfassung/zeiterfassung.db.bak
```

### Architektur

| Datei | Beschreibung |
|-------|-------------|
| `app.py` | Alle Routes und Business-Logik (~4.500 Zeilen) |
| `db.py` | Datenbankinitialisierung und Migrationen |
| `auth.py` | Session-basierte Authentifizierung |
| `templates.py` | HTML-Layout-Wrapper |
| `calendar_seed.py` | Import NRW-Feiertage |

---

*Zeiterfassung v3.1.0 – Flask + SQLite – NRW*
