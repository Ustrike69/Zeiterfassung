#!/usr/bin/env python3
"""
Initialisiert eine leere Zeiterfassungs-Datenbank.
Wird beim ersten Start (Docker/Proxmox) ausgeführt wenn keine DB vorhanden ist.
"""
import sys
from db import init_db, seed_defaults

try:
    from calendar_seed import seed_calendar_2026_nrw
    has_calendar_seed = True
except ImportError:
    has_calendar_seed = False

def main():
    print("Initialisiere Datenbank...")
    init_db()
    seed_defaults()
    if has_calendar_seed:
        seed_calendar_2026_nrw()
        print("NRW-Feiertage 2026 eingetragen.")
    print("Datenbank erfolgreich initialisiert.")
    print("Bitte /setup aufrufen um den ersten Admin-Account anzulegen.")

if __name__ == "__main__":
    main()
