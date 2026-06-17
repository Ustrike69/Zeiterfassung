# Zeiterfassung – Test-Suite

Diese Tests laufen gegen eine **temporäre, isolierte SQLite-Datenbank** und verändern
**NICHT** die Produktions-/Dev-Datenbank (`zeiterfassung.db`).

## Ausführen

```bash
cd /opt/zeiterfassung && python3 tests/test_calculations.py
```

## Abgedeckte Funktionen

| Funktion | Test-Fälle |
|---|---|
| `_expected_minutes_for_day` | Werktag, Wochenende, Feiertag, Abwesenheit, BS-Ganztag, BS-Halbtag, BS+Feiertag, BS+Schulferien, schedule_exceptions |
| `_slot_applies_on_date` | vm-Slot Mo-Fr, special-Slot nth_week, plan_id mit Team-Feiertags-Region |
| `_calc_balance_end_at` | Ist>Soll, balance_adjustments, start_balance |

Vor jedem Prod-Push empfohlen.
