#!/opt/zeiterfassung/.venv/bin/python3
"""
Isoliertes Test-Skript für kritische Berechnungsfunktionen.
Läuft gegen eine temporäre SQLite-Testdatenbank – NIEMALS gegen die echte zeiterfassung.db.
"""
import os
import sys
import tempfile

# ─── Temporäre Test-DB anlegen, BEVOR irgendwas importiert wird ───────────────
_tf = tempfile.NamedTemporaryFile(suffix='.db', delete=False, prefix='test_zeiterfassung_')
_tf.close()
TEST_DB = _tf.name
os.environ["ZEITERFASSUNG_DB"] = TEST_DB

sys.path.insert(0, '/opt/zeiterfassung')

import db as zdb
import app as zapp

# ─── Flask-g-Abhängigkeit in _get_app_config umgehen ──────────────────────────
def _mock_app_config():
    try:
        _db = zdb.connect()
        rows = _db.execute("SELECT key, value FROM app_config").fetchall()
        _db.close()
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {"default_holiday_region": "DE-NW"}

zapp._get_app_config = _mock_app_config

# ─── Test-Infrastruktur ────────────────────────────────────────────────────────
_passed = 0
_failed = 0

def check(name, condition):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✓ {name}")
    else:
        _failed += 1
        print(f"  ✗ {name} FEHLGESCHLAGEN")

def fresh_db():
    return zdb.connect()

def create_user(db, username, region='DE-NW', tracking_start='2026-01-01'):
    cur = db.execute(
        "INSERT INTO users (username, password_hash, tracking_start_date, holiday_region) "
        "VALUES (?, 'x', ?, ?)",
        (username, tracking_start, region)
    )
    db.commit()
    return cur.lastrowid

def insert_weekly_schedule(db, user_id, weekly=2400, mask=31,
                           mon=480, tue=480, wed=480, thu=480, fri=480,
                           block=1, valid_from='2026-01-01'):
    cur = db.execute(
        "INSERT INTO user_schedules "
        "(user_id, valid_from, mode, weekly_minutes, workdays_mask, "
        "mon_minutes, tue_minutes, wed_minutes, thu_minutes, fri_minutes, "
        "sat_minutes, sun_minutes, block_weekends_holidays) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,0,0,?)",
        (user_id, valid_from, 'weekly', weekly, mask, mon, tue, wed, thu, fri, block)
    )
    db.commit()
    return cur.lastrowid

def insert_daily_schedule(db, user_id, valid_from='2026-01-01', block=1):
    cur = db.execute(
        "INSERT INTO user_schedules "
        "(user_id, valid_from, mode, weekly_minutes, workdays_mask, "
        "mon_minutes, tue_minutes, wed_minutes, thu_minutes, fri_minutes, "
        "sat_minutes, sun_minutes, block_weekends_holidays) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,0,0,?)",
        (user_id, valid_from, 'daily', 2400, 31, 480, 480, 480, 480, 480, block)
    )
    db.commit()
    return cur.lastrowid


try:
    # ─── Schema initialisieren ─────────────────────────────────────────────────
    zdb.init_db()
    zdb.seed_defaults()
    # schedule_daily_blocks + schedule_exceptions werden nur hier erzeugt:
    zapp._ensure_user_schedules_schema()

    # ══════════════════════════════════════════════════════════════════════════
    # 1. _expected_minutes_for_day
    # ══════════════════════════════════════════════════════════════════════════
    print("\n=== _expected_minutes_for_day ===")

    # Basis-User: Mo-Fr, 2400 min/Woche (=480 min/Tag)
    db = fresh_db()
    u_base = create_user(db, 'u_base')
    insert_weekly_schedule(db, u_base)
    db.close()

    # a) Normaler Werktag – Montag 2026-06-15
    check("a) Werktag Mo (2026-06-15): 2400/5 = 480 min",
          zapp._expected_minutes_for_day(u_base, '2026-06-15') == 480)

    # b) Wochenende – Samstag 2026-06-13
    check("b) Samstag (2026-06-13) → 0 min",
          zapp._expected_minutes_for_day(u_base, '2026-06-13') == 0)

    # c) Feiertag (in calendar_days eingetragen)
    db = fresh_db()
    db.execute(
        "INSERT OR REPLACE INTO calendar_days (day, region, is_holiday, is_weekend) "
        "VALUES ('2026-10-03', 'DE-NW', 1, 0)"
    )
    db.commit()
    db.close()
    check("c) Feiertag 2026-10-03 (is_holiday=1) → 0 min",
          zapp._expected_minutes_for_day(u_base, '2026-10-03') == 0)

    # d) Urlaub eingetragen – Montag 2026-06-15
    db = fresh_db()
    u_urlaub = create_user(db, 'u_urlaub')
    insert_weekly_schedule(db, u_urlaub)
    urlaub_id = db.execute("SELECT id FROM absence_types WHERE name='Urlaub'").fetchone()["id"]
    db.execute(
        "INSERT INTO absences (user_id, type_id, date_from, date_to, is_half_day) "
        "VALUES (?, ?, '2026-06-15', '2026-06-15', 0)", (u_urlaub, urlaub_id)
    )
    db.commit()
    db.close()
    check("d) Urlaub 2026-06-15 eingetragen → 0 min",
          zapp._expected_minutes_for_day(u_urlaub, '2026-06-15') == 0)

    # e) Berufsschule Ganztag (weekly Mi, kein work_time)
    db = fresh_db()
    u_bs_voll = create_user(db, 'u_bs_voll')
    insert_weekly_schedule(db, u_bs_voll)
    db.execute(
        "INSERT INTO vocational_school (user_id, schedule_type, weekday, note) "
        "VALUES (?, 'weekly', 2, 'BS-Ganztag')", (u_bs_voll,)
    )
    db.commit()
    db.close()
    # 2026-06-17 ist Mittwoch (weekday=2)
    check("e) BS Ganztag wöchentl. Mi (2026-06-17) → 0 min",
          zapp._expected_minutes_for_day(u_bs_voll, '2026-06-17') == 0)

    # f) Berufsschule Halbtag (work_time 13:00-17:00 = 240 min)
    db = fresh_db()
    u_bs_halb = create_user(db, 'u_bs_halb')
    insert_weekly_schedule(db, u_bs_halb)
    db.execute(
        "INSERT INTO vocational_school "
        "(user_id, schedule_type, weekday, work_time_from, work_time_to, note) "
        "VALUES (?, 'weekly', 2, '13:00', '17:00', 'BS-Halbtag')", (u_bs_halb,)
    )
    db.commit()
    db.close()
    check("f) BS Halbtag 13:00-17:00 (Mi 2026-06-17) → 240 min",
          zapp._expected_minutes_for_day(u_bs_halb, '2026-06-17') == 240)

    # g) Berufsschule + Feiertag an selben Tag → Feiertag (0 min), kein Fehler
    # 2026-10-05 ist Montag (Oct 3 = Sa, Oct 4 = So, Oct 5 = Mo)
    db = fresh_db()
    u_bs_fei = create_user(db, 'u_bs_fei')
    insert_weekly_schedule(db, u_bs_fei)
    db.execute(
        "INSERT INTO vocational_school (user_id, schedule_type, weekday, note) "
        "VALUES (?, 'weekly', 0, 'BS-Mo')", (u_bs_fei,)
    )
    db.execute(
        "INSERT OR REPLACE INTO calendar_days (day, region, is_holiday, is_weekend) "
        "VALUES ('2026-10-05', 'DE-NW', 1, 0)"
    )
    db.commit()
    db.close()
    check("g) BS + Feiertag 2026-10-05 (Mo): Feiertag hat Vorrang → 0 min",
          zapp._expected_minutes_for_day(u_bs_fei, '2026-10-05') == 0)

    # h) Berufsschule während Schulferien → normale Sollzeit (BS entfällt)
    # u_bs_voll hat BS weekly Mi; Schulferien 2026-06-29..2026-07-31
    # 2026-07-01 ist Mittwoch und liegt in Schulferien
    db = fresh_db()
    db.execute(
        "INSERT INTO school_holidays (region, name, date_from, date_to) "
        "VALUES ('DE-NW', 'Sommerferien-Test', '2026-06-29', '2026-07-31')"
    )
    db.commit()
    db.close()
    check("h) BS (weekly Mi) während Schulferien (2026-07-01) → normale Sollzeit 480 min",
          zapp._expected_minutes_for_day(u_bs_voll, '2026-07-01') == 480)

    # i) schedule_exceptions: 1./3. Mi mit Ausnahme-Zeit
    # Normale Blöcke Mi: 07:30-12:30 = 300 min
    # Ausnahme 1.+3. Mi:  07:00-12:30 = 330 min
    # 1. Mi Juni 2026 = 2026-06-03 → week_num=(3-1)//7+1=1 → Ausnahme
    # 2. Mi Juni 2026 = 2026-06-10 → week_num=(10-1)//7+1=2 → normal
    db = fresh_db()
    u_exc = create_user(db, 'u_exc')
    sched_id = insert_daily_schedule(db, u_exc)
    db.execute(
        "INSERT INTO schedule_daily_blocks (schedule_id, weekday, time_from, time_to, sort_order) "
        "VALUES (?, 2, '07:30', '12:30', 0)", (sched_id,)
    )
    db.execute(
        "INSERT INTO schedule_exceptions (schedule_id, weekday, nth_weeks, time_from, time_to) "
        "VALUES (?, 2, '1,3', '07:00', '12:30')", (sched_id,)
    )
    db.commit()
    db.close()
    check("i) 1. Mittwoch (2026-06-03): schedule_exception greift → 330 min",
          zapp._expected_minutes_for_day(u_exc, '2026-06-03') == 330)
    check("i) 2. Mittwoch (2026-06-10): kein Ausnahme → normale Blöcke → 300 min",
          zapp._expected_minutes_for_day(u_exc, '2026-06-10') == 300)

    # ══════════════════════════════════════════════════════════════════════════
    # 2. _slot_applies_on_date
    # ══════════════════════════════════════════════════════════════════════════
    print("\n=== _slot_applies_on_date ===")

    # a) Slot typ='vm', weekdays='0,1,2,3,4'
    slot_vm = {"weekdays": "0,1,2,3,4", "slot_type": "vm",
               "special_weekday": None, "nth_week": None}
    check("a) vm-Slot Mo-Fr: Montag 2026-06-15 → True",
          zapp._slot_applies_on_date(slot_vm, '2026-06-15') is True)
    check("a) vm-Slot Mo-Fr: Samstag 2026-06-13 → False",
          zapp._slot_applies_on_date(slot_vm, '2026-06-13') is False)

    # b) Slot typ='special', special_weekday=2 (Mi), nth_week='1,3'
    slot_sp = {"weekdays": "2", "slot_type": "special",
               "special_weekday": 2, "nth_week": "1,3"}
    check("b) special Mi 1./3.Woche: 1. Mi 2026-06-03 → True",
          zapp._slot_applies_on_date(slot_sp, '2026-06-03') is True)
    check("b) special Mi 1./3.Woche: 2. Mi 2026-06-10 → False",
          zapp._slot_applies_on_date(slot_sp, '2026-06-10') is False)

    # c) Plan mit Team-Feiertags-Region; Feiertag blockiert Slot
    # 2026-10-26 ist Montag (Oct 5=Mo + 3 Wochen = Oct 26=Mo)
    db = fresh_db()
    team_id = db.execute(
        "INSERT INTO teams (name, holiday_region) VALUES ('Testteam', 'DE-NW')"
    ).lastrowid
    plan_id = db.execute(
        "INSERT INTO staffing_plans (team_id, name, active) VALUES (?, 'Testplan', 1)",
        (team_id,)
    ).lastrowid
    db.execute(
        "INSERT OR REPLACE INTO calendar_days (day, region, is_holiday, is_weekend) "
        "VALUES ('2026-10-26', 'DE-NW', 1, 0)"
    )
    db.commit()
    db.close()
    slot_plan = {"weekdays": "0,1,2,3,4", "slot_type": "vm",
                 "special_weekday": None, "nth_week": None}
    check("c) plan_id: Feiertag-Mo 2026-10-26 in Team-Region DE-NW → False",
          zapp._slot_applies_on_date(slot_plan, '2026-10-26', plan_id=plan_id) is False)
    check("c) plan_id: normaler Mo 2026-06-15 → True",
          zapp._slot_applies_on_date(slot_plan, '2026-06-15', plan_id=plan_id) is True)

    # ══════════════════════════════════════════════════════════════════════════
    # 3. _calc_balance_end_at
    # ══════════════════════════════════════════════════════════════════════════
    print("\n=== _calc_balance_end_at ===")

    # a) Startsaldo=0, Ist > Soll → positiver Saldo
    # Mo 2026-06-15: expected=480, actual=09:00-17:30=510 → delta=+30
    db = fresh_db()
    u_bal1 = create_user(db, 'u_bal1', tracking_start='2026-06-15')
    insert_weekly_schedule(db, u_bal1)
    db.execute(
        "INSERT INTO time_blocks (user_id, day, time_in, time_out, break_minutes) "
        "VALUES (?, '2026-06-15', '09:00', '17:30', 0)", (u_bal1,)
    )
    db.commit()
    db.close()
    check("a) Ist(510)>Soll(480): Saldo = +30 min",
          zapp._calc_balance_end_at(u_bal1, '2026-06-15') == 30)

    # b) Mit balance_adjustment: Saldo = 30 + (-480) = -450
    db = fresh_db()
    db.execute(
        "INSERT INTO balance_adjustments (user_id, minutes, reason, adjustment_date) "
        "VALUES (?, -480, 'Auszahlung Test', '2026-06-15')", (u_bal1,)
    )
    db.commit()
    db.close()
    check("b) balance_adjustment -480 min: Saldo = 30 - 480 = -450 min",
          zapp._calc_balance_end_at(u_bal1, '2026-06-15') == -450)

    # c) start_balance berücksichtigt
    # Tracking-Start = So 2026-06-14 (Wochenende): expected=0, actual=0 → delta=0
    # Saldo = start_balance (120) + delta (0) = 120
    db = fresh_db()
    u_bal2 = create_user(db, 'u_bal2', tracking_start='2026-06-14')
    insert_weekly_schedule(db, u_bal2)
    db.commit()
    db.close()
    zapp._set_start_balance_minutes(u_bal2, 120)
    check("c) start_balance=120, Sonntag (delta=0): Saldo = 120 min",
          zapp._calc_balance_end_at(u_bal2, '2026-06-14') == 120)

    # ══════════════════════════════════════════════════════════════════════════
    # Ergebnis
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{_passed} bestanden, {_failed} fehlgeschlagen")

finally:
    try:
        os.unlink(TEST_DB)
    except Exception:
        pass

sys.exit(1 if _failed > 0 else 0)
