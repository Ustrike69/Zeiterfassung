"""
Zeiterfassung Bot – translation framework.

Usage:
    from bot_translations import t_bot, BOT_TRANSLATIONS

    t_bot('bot.help', user_id=42)      # reads user language from DB
    t_bot('bot.help', lang='en')        # explicit lang
"""

BOT_TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        # ── General ───────────────────────────────────────────────────
        "bot.not_registered":   "⚠️ Dein Telegram-Account ist nicht mit Zeiterfassung verknüpft. Bitte hinterlege deine Telegram-ID in den Einstellungen.",
        "bot.not_found":        "❓ Ich habe das nicht verstanden.",
        "bot.error":            "⚠️ Fehler: {error}",
        "bot.help":             (
            "📋 *Zeiterfassung Bot*\n\n"
            "*Befehle:*\n"
            "/heute – Heutigen Eintrag anzeigen\n"
            "/woche – Wochenübersicht\n"
            "/saldo – Gleitzeitsaldo\n"
            "/urlaub – Urlaubsübersicht\n"
            "/fehlend – Fehlende Einträge\n"
            "/als \\<username\\> – Identität wechseln (Admin)\n"
            "/als ich – Zurück zum eigenen Konto\n"
            "/export – Monatsexport\n"
            "\nEinfach Sätze eingeben wie:\n"
            "• Heute von 7:30 bis 13:00 gearbeitet\n"
            "• Urlaub vom 1.7. bis 15.7.\n"
            "• Krank von 10.6. bis 12.6."
        ),
        "bot.help_en":          (
            "📋 *Time Tracking Bot*\n\n"
            "*Commands:*\n"
            "/heute – Today's entry\n"
            "/woche – Week overview\n"
            "/saldo – Flex time balance\n"
            "/urlaub – Vacation overview\n"
            "/fehlend – Missing entries\n"
            "/als \\<username\\> – Switch identity (admin)\n"
            "/als ich – Return to own account\n"
            "/export – Monthly export"
        ),

        # ── Today ─────────────────────────────────────────────────────
        "bot.today_no_entry":   "📅 *{date}* – Kein Eintrag vorhanden.",
        "bot.today_entry":      "📅 *{date}*\n{blocks}\nIst: *{actual}* | Soll: *{target}* | Δ *{delta}*",
        "bot.today_absence":    "📅 *{date}* – Abwesenheit: {type}",
        "bot.today_holiday":    "📅 *{date}* – Feiertag: {name}",
        "bot.today_weekend":    "📅 *{date}* – Wochenende",

        # ── Week ──────────────────────────────────────────────────────
        "bot.week_header":      "📆 *Woche {week} ({from} – {to})*",
        "bot.week_no_entries":  "Keine Einträge diese Woche.",
        "bot.week_total":       "Gesamt: *{actual}* | Soll: *{target}* | Δ *{delta}*",

        # ── Balance ───────────────────────────────────────────────────
        "bot.balance":          "⏱ *Gleitzeitsaldo*\nStand gestern ({date}): *{balance}*",
        "bot.balance_positive": "Du hast *{balance}* Plusstunden.",
        "bot.balance_negative": "Du hast *{balance}* Minusstunden.",

        # ── Vacation ──────────────────────────────────────────────────
        "bot.vacation":         (
            "🏖 *Urlaub {year}*\n"
            "Anspruch: {entitlement} Tage\n"
            "Übertrag: {carryover} Tage\n"
            "Genommen: {used} Tage\n"
            "Verbleibend: *{remaining} Tage*"
        ),

        # ── Missing entries ───────────────────────────────────────────
        "bot.missing_none":     "✅ Keine fehlenden Einträge.",
        "bot.missing_count":    "⚠️ *{count} fehlende Einträge:*\n{dates}",

        # ── Time entry (NLP) ──────────────────────────────────────────
        "bot.nlp_examples":     (
            "❓ Das habe ich nicht verstanden. Beispiele:\n"
            "• Heute von 7:30 bis 13:00 gearbeitet\n"
            "• Am 15.5. von 8 bis 16 Uhr\n"
            "• Urlaub vom 1.7. bis 15.7.\n"
            "• Am 3.8. Flextag\n"
            "• Krank von 10.6. bis 12.6."
        ),
        "bot.entry_saved":      "✅ Eintrag gespeichert: {date} {time_in}–{time_out} (Pause: {break} Min.)",
        "bot.entry_exists":     "ℹ️ Für {date} gibt es bereits einen Eintrag.",
        "bot.entry_updated":    "✅ Eintrag aktualisiert: {date}",
        "bot.absence_saved":    "✅ Abwesenheit gespeichert: {type} {from}–{to}",
        "bot.absence_confirm":  "Abwesenheit eintragen: {type} am {date}?",

        # ── Wizard ────────────────────────────────────────────────────
        "bot.wizard_ask":       "Hast du heute gearbeitet? ({date})",
        "bot.wizard_time_ask":  "Wann hast du angefangen und aufgehört? (z.B. 8:00 bis 16:30)",
        "bot.wizard_yes":       "Ja",
        "bot.wizard_no":        "Nein",
        "bot.wizard_skip":      "Überspringen",
        "bot.wizard_absence":   "Abwesenheit",

        # ── Impersonation ─────────────────────────────────────────────
        "bot.impersonate_ok":   "✅ Identität gewechselt: {username}",
        "bot.impersonate_self":  "✅ Zurück zum eigenen Konto.",
        "bot.impersonate_fail": "❌ Benutzer nicht gefunden: {username}",
        "bot.impersonate_deny": "❌ Keine Berechtigung für Identitätswechsel.",

        # ── Export ────────────────────────────────────────────────────
        "bot.export_sent":      "📎 Monatsexport für {month} gesendet.",
        "bot.export_empty":     "Keine Daten für {month}.",

        # ── Reminder ──────────────────────────────────────────────────
        "bot.reminder_msg":     "⏰ Hast du heute deine Zeiten erfasst?",
    },

    "en": {
        # ── General ───────────────────────────────────────────────────
        "bot.not_registered":   "⚠️ Your Telegram account is not linked to Time Tracking. Please add your Telegram ID in the settings.",
        "bot.not_found":        "❓ I didn't understand that.",
        "bot.error":            "⚠️ Error: {error}",
        "bot.help":             (
            "📋 *Time Tracking Bot*\n\n"
            "*Commands:*\n"
            "/heute – Today's entry\n"
            "/woche – Week overview\n"
            "/saldo – Flex time balance\n"
            "/urlaub – Vacation overview\n"
            "/fehlend – Missing entries\n"
            "/als \\<username\\> – Switch identity (admin)\n"
            "/als ich – Return to own account\n"
            "/export – Monthly export\n"
            "\nJust type sentences like:\n"
            "• Today worked from 7:30 to 13:00\n"
            "• Vacation from Jul 1 to Jul 15\n"
            "• Sick from Jun 10 to Jun 12"
        ),

        # ── Today ─────────────────────────────────────────────────────
        "bot.today_no_entry":   "📅 *{date}* – No entry found.",
        "bot.today_entry":      "📅 *{date}*\n{blocks}\nActual: *{actual}* | Target: *{target}* | Δ *{delta}*",
        "bot.today_absence":    "📅 *{date}* – Absence: {type}",
        "bot.today_holiday":    "📅 *{date}* – Public holiday: {name}",
        "bot.today_weekend":    "📅 *{date}* – Weekend",

        # ── Week ──────────────────────────────────────────────────────
        "bot.week_header":      "📆 *Week {week} ({from} – {to})*",
        "bot.week_no_entries":  "No entries this week.",
        "bot.week_total":       "Total: *{actual}* | Target: *{target}* | Δ *{delta}*",

        # ── Balance ───────────────────────────────────────────────────
        "bot.balance":          "⏱ *Flex Time Balance*\nAs of yesterday ({date}): *{balance}*",
        "bot.balance_positive": "You have *{balance}* surplus hours.",
        "bot.balance_negative": "You have *{balance}* deficit hours.",

        # ── Vacation ──────────────────────────────────────────────────
        "bot.vacation":         (
            "🏖 *Vacation {year}*\n"
            "Entitlement: {entitlement} days\n"
            "Carryover: {carryover} days\n"
            "Used: {used} days\n"
            "Remaining: *{remaining} days*"
        ),

        # ── Missing entries ───────────────────────────────────────────
        "bot.missing_none":     "✅ No missing entries.",
        "bot.missing_count":    "⚠️ *{count} missing entries:*\n{dates}",

        # ── Time entry (NLP) ──────────────────────────────────────────
        "bot.nlp_examples":     (
            "❓ I didn't understand that. Examples:\n"
            "• Today worked from 7:30 to 13:00\n"
            "• On May 15 from 8 to 16:00\n"
            "• Vacation from Jul 1 to Jul 15\n"
            "• Flex day on Aug 3\n"
            "• Sick from Jun 10 to Jun 12"
        ),
        "bot.entry_saved":      "✅ Entry saved: {date} {time_in}–{time_out} (break: {break} min.)",
        "bot.entry_exists":     "ℹ️ An entry already exists for {date}.",
        "bot.entry_updated":    "✅ Entry updated: {date}",
        "bot.absence_saved":    "✅ Absence saved: {type} {from}–{to}",
        "bot.absence_confirm":  "Log absence: {type} on {date}?",

        # ── Wizard ────────────────────────────────────────────────────
        "bot.wizard_ask":       "Did you work today? ({date})",
        "bot.wizard_time_ask":  "When did you start and finish? (e.g. 8:00 to 16:30)",
        "bot.wizard_yes":       "Yes",
        "bot.wizard_no":        "No",
        "bot.wizard_skip":      "Skip",
        "bot.wizard_absence":   "Absence",

        # ── Impersonation ─────────────────────────────────────────────
        "bot.impersonate_ok":   "✅ Identity switched: {username}",
        "bot.impersonate_self":  "✅ Returned to own account.",
        "bot.impersonate_fail": "❌ User not found: {username}",
        "bot.impersonate_deny": "❌ Not authorized to switch identity.",

        # ── Export ────────────────────────────────────────────────────
        "bot.export_sent":      "📎 Monthly export for {month} sent.",
        "bot.export_empty":     "No data for {month}.",

        # ── Reminder ──────────────────────────────────────────────────
        "bot.reminder_msg":     "⏰ Have you logged your hours today?",
    },
}


def _get_user_lang(user_id: int) -> str:
    """Read user language preference from DB. Falls back to 'de'."""
    try:
        from db import connect
        db = connect()
        row = db.execute("SELECT language FROM users WHERE id=?", (user_id,)).fetchone()
        db.close()
        lang = (row["language"] if row and row["language"] else "de") or "de"
        return lang if lang in BOT_TRANSLATIONS else "de"
    except Exception:
        return "de"


def t_bot(key: str, user_id: int | None = None, lang: str | None = None) -> str:
    """Return translated bot string. Resolves lang from user_id if not given."""
    if lang is None:
        lang = _get_user_lang(user_id) if user_id is not None else "de"
    d = BOT_TRANSLATIONS.get(lang)
    if d and key in d:
        return d[key]
    en = BOT_TRANSLATIONS.get("en", {})
    if key in en:
        return en[key]
    de = BOT_TRANSLATIONS.get("de", {})
    return de.get(key, key)
