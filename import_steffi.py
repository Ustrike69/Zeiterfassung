#!/usr/bin/env python3
"""
Einmaliger Import von Steffis Zeitdaten aus Numbers-Datei in die Zeiterfassung-DB.
Ausführen: python3 import_steffi.py --db /opt/zeiterfassung/zeiterfassung.db --user steffi

Optionen:
  --db      Pfad zur SQLite-Datenbank (Pflicht)
  --user    Username von Steffi in der Zeiterfassung (Pflicht)
  --dry-run Nur anzeigen, was importiert würde (kein Schreiben)
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── Daten aus Numbers extrahiert ────────────────────────────────────────────
# Zeiteinträge: Datum, Kommen, Gehen, Pause in Minuten
ZEITEINTRAEGE = [
    {"datum": "2026-01-02", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-01-05", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-01-06", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-01-07", "kommen": "07:00", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-01-08", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-01-09", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-01-15", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-01-16", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-01-22", "kommen": "07:30", "gehen": "13:30", "pause_min": 0},
    {"datum": "2026-01-23", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-01-27", "kommen": "07:30", "gehen": "13:30", "pause_min": 0},
    {"datum": "2026-01-30", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-02-17", "kommen": "07:30", "gehen": "18:00", "pause_min": 0},
    {"datum": "2026-02-18", "kommen": "07:00", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-02-19", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-02-20", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-02-23", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-02-24", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-02-25", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-02-26", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-02-27", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-03-02", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-03-03", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-03-04", "kommen": "07:00", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-03-05", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-05-06", "kommen": "07:00", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-05-07", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-05-08", "kommen": "07:30", "gehen": "12:30", "pause_min": 0},
    {"datum": "2026-05-11", "kommen": "07:30", "gehen": "13:00", "pause_min": 0},
    {"datum": "2026-05-12", "kommen": "07:30", "gehen": "18:00", "pause_min": 0},
]

# Abwesenheiten: Datum, Typ (Urlaub/Krank)
ABWESENHEITEN = [
    # Krank
    {"datum": "2026-01-28", "typ": "Krank"},
    {"datum": "2026-01-29", "typ": "Krank"},
    {"datum": "2026-02-03", "typ": "Krank"},
    {"datum": "2026-02-04", "typ": "Krank"},
    {"datum": "2026-02-05", "typ": "Krank"},
    {"datum": "2026-02-06", "typ": "Krank"},
    {"datum": "2026-02-10", "typ": "Krank"},
    {"datum": "2026-02-11", "typ": "Krank"},
    {"datum": "2026-02-12", "typ": "Krank"},
    {"datum": "2026-02-13", "typ": "Krank"},
    {"datum": "2026-03-09", "typ": "Krank"},
    {"datum": "2026-03-10", "typ": "Krank"},
    {"datum": "2026-03-11", "typ": "Krank"},
    {"datum": "2026-03-12", "typ": "Krank"},
    {"datum": "2026-03-13", "typ": "Krank"},
    {"datum": "2026-03-16", "typ": "Krank"},
    {"datum": "2026-03-17", "typ": "Krank"},
    {"datum": "2026-03-18", "typ": "Krank"},
    {"datum": "2026-03-19", "typ": "Krank"},
    {"datum": "2026-03-20", "typ": "Krank"},
    {"datum": "2026-03-23", "typ": "Krank"},
    {"datum": "2026-03-24", "typ": "Krank"},
    {"datum": "2026-03-25", "typ": "Krank"},
    {"datum": "2026-03-26", "typ": "Krank"},
    {"datum": "2026-03-27", "typ": "Krank"},
    {"datum": "2026-03-30", "typ": "Krank"},
    {"datum": "2026-03-31", "typ": "Krank"},
    {"datum": "2026-04-01", "typ": "Krank"},
    {"datum": "2026-04-02", "typ": "Krank"},
    {"datum": "2026-04-07", "typ": "Krank"},
    {"datum": "2026-04-08", "typ": "Krank"},
    {"datum": "2026-04-09", "typ": "Krank"},
    {"datum": "2026-04-10", "typ": "Krank"},
    {"datum": "2026-04-13", "typ": "Krank"},
    {"datum": "2026-04-14", "typ": "Krank"},
    {"datum": "2026-04-15", "typ": "Krank"},
    {"datum": "2026-04-16", "typ": "Krank"},
    # Urlaub
    {"datum": "2026-04-28", "typ": "Urlaub"},
    {"datum": "2026-04-29", "typ": "Urlaub"},
    {"datum": "2026-04-30", "typ": "Urlaub"},
    {"datum": "2026-06-09", "typ": "Urlaub"},
    {"datum": "2026-06-10", "typ": "Urlaub"},
    {"datum": "2026-06-11", "typ": "Urlaub"},
    {"datum": "2026-06-12", "typ": "Urlaub"},
    {"datum": "2026-06-26", "typ": "Urlaub"},
    {"datum": "2026-06-30", "typ": "Urlaub"},
    {"datum": "2026-07-01", "typ": "Urlaub"},
    {"datum": "2026-07-02", "typ": "Urlaub"},
    {"datum": "2026-07-03", "typ": "Urlaub"},
    {"datum": "2026-07-07", "typ": "Urlaub"},
    {"datum": "2026-07-08", "typ": "Urlaub"},
    {"datum": "2026-07-09", "typ": "Urlaub"},
    {"datum": "2026-07-10", "typ": "Urlaub"},
    {"datum": "2026-08-25", "typ": "Urlaub"},
    {"datum": "2026-08-26", "typ": "Urlaub"},
    {"datum": "2026-08-27", "typ": "Urlaub"},
    {"datum": "2026-08-28", "typ": "Urlaub"},
    {"datum": "2026-09-01", "typ": "Urlaub"},
    {"datum": "2026-09-02", "typ": "Urlaub"},
    {"datum": "2026-09-03", "typ": "Urlaub"},
    {"datum": "2026-09-04", "typ": "Urlaub"},
]


def group_consecutive(dates: list[str]) -> list[tuple[str, str]]:
    """Gruppiert aufeinanderfolgende Daten zu Zeiträumen (date_from, date_to)."""
    if not dates:
        return []
    sorted_dates = sorted(dates)
    ranges = []
    start = sorted_dates[0]
    prev = sorted_dates[0]
    for d in sorted_dates[1:]:
        curr = datetime.strptime(d, "%Y-%m-%d")
        last = datetime.strptime(prev, "%Y-%m-%d")
        if (curr - last).days <= 3:  # Wochenenden überbrücken
            prev = d
        else:
            ranges.append((start, prev))
            start = d
            prev = d
    ranges.append((start, prev))
    return ranges


def run_import(db_path: str, username: str, dry_run: bool):
    if not Path(db_path).exists():
        print(f"FEHLER: Datenbank nicht gefunden: {db_path}")
        sys.exit(1)

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    # User prüfen
    user = db.execute("SELECT id, username FROM users WHERE username=?", (username,)).fetchone()
    if not user:
        users = db.execute("SELECT username FROM users").fetchall()
        print(f"FEHLER: User '{username}' nicht gefunden.")
        print(f"Vorhandene User: {[u['username'] for u in users]}")
        db.close()
        sys.exit(1)

    user_id = user["id"]
    print(f"✓ User gefunden: {username} (ID={user_id})")

    # Absence Types prüfen
    urlaub_type = db.execute("SELECT id FROM absence_types WHERE name='Urlaub'").fetchone()
    krank_type = db.execute("SELECT id FROM absence_types WHERE name='Krank'").fetchone()

    if not urlaub_type or not krank_type:
        types = db.execute("SELECT id, name FROM absence_types").fetchall()
        print(f"Verfügbare Abwesenheitstypen: {[(t['id'], t['name']) for t in types]}")
        if not urlaub_type:
            print("FEHLER: Absence-Type 'Urlaub' nicht gefunden!")
            db.close()
            sys.exit(1)
        if not krank_type:
            print("FEHLER: Absence-Type 'Krank' nicht gefunden!")
            db.close()
            sys.exit(1)

    urlaub_id = urlaub_type["id"]
    krank_id = krank_type["id"]
    print(f"✓ Absence Types: Urlaub={urlaub_id}, Krank={krank_id}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Zeiteinträge importieren ─────────────────────────────────────────────
    print(f"\n── Zeiteinträge ({len(ZEITEINTRAEGE)}) ──────────────────────────")
    te_inserted = 0
    te_skipped = 0
    tb_inserted = 0

    for e in ZEITEINTRAEGE:
        existing_te = db.execute(
            "SELECT id FROM time_entries WHERE user_id=? AND day=?",
            (user_id, e["datum"])
        ).fetchone()
        existing_tb = db.execute(
            "SELECT id FROM time_blocks WHERE user_id=? AND day=?",
            (user_id, e["datum"])
        ).fetchone()

        if existing_te or existing_tb:
            print(f"  SKIP {e['datum']} {e['kommen']}-{e['gehen']} (bereits vorhanden)")
            te_skipped += 1
            continue

        print(f"  ✓ {e['datum']} {e['kommen']}-{e['gehen']} Pause={e['pause_min']}min")

        if not dry_run:
            # time_entries (Legacy, 1 pro Tag)
            db.execute("""
                INSERT INTO time_entries (user_id, day, time_in, time_out, break_minutes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, e["datum"], e["kommen"], e["gehen"], e["pause_min"], now))

            # time_blocks (neues Modell)
            db.execute("""
                INSERT INTO time_blocks (user_id, day, time_in, time_out, break_minutes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, e["datum"], e["kommen"], e["gehen"], e["pause_min"], now))

        te_inserted += 1
        tb_inserted += 1

    # ── Abwesenheiten importieren ────────────────────────────────────────────
    print(f"\n── Abwesenheiten ({len(ABWESENHEITEN)}) ──────────────────────────")

    # Gruppiere nach Typ und dann nach aufeinanderfolgenden Tagen
    urlaub_tage = [a["datum"] for a in ABWESENHEITEN if a["typ"] == "Urlaub"]
    krank_tage = [a["datum"] for a in ABWESENHEITEN if a["typ"] == "Krank"]

    abs_inserted = 0
    abs_skipped = 0

    for typ, tage, type_id in [("Urlaub", urlaub_tage, urlaub_id), ("Krank", krank_tage, krank_id)]:
        ranges = group_consecutive(tage)
        print(f"\n  {typ}: {len(tage)} Tage → {len(ranges)} Zeiträume")
        for date_from, date_to in ranges:
            existing = db.execute("""
                SELECT id FROM absences
                WHERE user_id=? AND type_id=? AND date_from=? AND date_to=?
            """, (user_id, type_id, date_from, date_to)).fetchone()

            # Auch überlappende prüfen
            overlap = db.execute("""
                SELECT id FROM absences
                WHERE user_id=? AND type_id=?
                AND date_from <= ? AND date_to >= ?
            """, (user_id, type_id, date_to, date_from)).fetchone()

            if existing or overlap:
                print(f"    SKIP {date_from} → {date_to} (bereits vorhanden/überlappend)")
                abs_skipped += 1
                continue

            print(f"    ✓ {date_from} → {date_to}")
            if not dry_run:
                db.execute("""
                    INSERT INTO absences (user_id, type_id, date_from, date_to, is_half_day, created_at)
                    VALUES (?, ?, ?, ?, 0, ?)
                """, (user_id, type_id, date_from, date_to, now))
            abs_inserted += 1

    # ── Commit & Ergebnis ────────────────────────────────────────────────────
    if not dry_run:
        db.commit()
        print(f"\n✅ IMPORT ABGESCHLOSSEN")
    else:
        print(f"\n🔍 DRY-RUN (nichts gespeichert)")

    print(f"   Zeiteinträge: {te_inserted} importiert, {te_skipped} übersprungen")
    print(f"   Abwesenheiten: {abs_inserted} Zeiträume importiert, {abs_skipped} übersprungen")

    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Einmaliger Import von Steffis Zeitdaten")
    parser.add_argument("--db", required=True, help="Pfad zur SQLite-DB")
    parser.add_argument("--user", required=True, help="Username in der Zeiterfassung")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nicht speichern")
    args = parser.parse_args()

    run_import(args.db, args.user, args.dry_run)
