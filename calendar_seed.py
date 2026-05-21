"""Calendar seeding – European holiday regions.

Exports:
    get_holidays(year, region)      – list of (date, name_de, name_en)
    seed_holidays(year, region)     – write one year/region to calendar_days
    seed_all_regions(years)         – seed all regions for given years
    seed_all_regions_if_needed()    – idempotent seed (version-gated)
    seed_calendar_2026_nrw()        – backward-compat wrapper
    REGION_GROUPS                   – [(flag, group_label, [(code, label), ...]), ...]
    ALL_REGIONS                     – flat list of all region codes
"""

from __future__ import annotations

import calendar as _cal
from datetime import date, timedelta

from db import connect

# ── Increment whenever holiday definitions or seeded years change ─────────────
_SEED_VERSION = "2026-2027-v2"


# ═══════════════════════════════════════════════════════════════════════════════
# Region catalogue
# ═══════════════════════════════════════════════════════════════════════════════

REGION_GROUPS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("🇩🇪", "Deutschland", [
        ("DE-BW", "Baden-Württemberg"),
        ("DE-BY", "Bayern"),
        ("DE-BE", "Berlin"),
        ("DE-HB", "Bremen"),
        ("DE-HH", "Hamburg"),
        ("DE-HE", "Hessen"),
        ("DE-MV", "Mecklenburg-Vorpommern"),
        ("DE-NI", "Niedersachsen"),
        ("DE-NW", "Nordrhein-Westfalen"),
        ("DE-RP", "Rheinland-Pfalz"),
        ("DE-SL", "Saarland"),
        ("DE-SN", "Sachsen"),
        ("DE-ST", "Sachsen-Anhalt"),
        ("DE-SH", "Schleswig-Holstein"),
        ("DE-TH", "Thüringen"),
    ]),
    ("🇦🇹", "Österreich", [
        ("AT",   "Österreich (national)"),
        ("AT-1", "Burgenland"),
        ("AT-2", "Kärnten"),
        ("AT-3", "Niederösterreich"),
        ("AT-4", "Oberösterreich"),
        ("AT-5", "Salzburg"),
        ("AT-6", "Steiermark"),
        ("AT-7", "Tirol"),
        ("AT-8", "Vorarlberg"),
        ("AT-9", "Wien"),
    ]),
    ("🇨🇭", "Schweiz", [
        ("CH",    "Schweiz (national)"),
        ("CH-ZH", "Zürich"),
        ("CH-BE", "Bern"),
        ("CH-GE", "Genf"),
        ("CH-BS", "Basel-Stadt"),
        ("CH-AG", "Aargau"),
    ]),
    ("🇫🇷", "Frankreich", [
        ("FR", "Frankreich"),
    ]),
    ("🇳🇱", "Niederlande", [
        ("NL", "Niederlande"),
    ]),
    ("🇧🇪", "Belgien", [
        ("BE", "Belgien"),
    ]),
    ("🇱🇺", "Luxemburg", [
        ("LU", "Luxemburg"),
    ]),
    ("🇵🇱", "Polen", [
        ("PL", "Polen"),
    ]),
    ("🇨🇿", "Tschechien", [
        ("CZ", "Tschechien"),
    ]),
    ("🇮🇹", "Italien", [
        ("IT", "Italien"),
    ]),
    ("🇪🇸", "Spanien", [
        ("ES", "Spanien"),
    ]),
    ("🇵🇹", "Portugal", [
        ("PT", "Portugal"),
    ]),
    ("🇬🇧", "Großbritannien", [
        ("GB-ENG", "England"),
        ("GB-SCT", "Schottland"),
        ("GB-WLS", "Wales"),
        ("GB-NIR", "Nordirland"),
    ]),
    ("🇮🇪", "Irland", [
        ("IE", "Irland"),
    ]),
    ("🇩🇰", "Dänemark", [
        ("DK", "Dänemark"),
    ]),
    ("🇸🇪", "Schweden", [
        ("SE", "Schweden"),
    ]),
    ("🇳🇴", "Norwegen", [
        ("NO", "Norwegen"),
    ]),
    ("🇫🇮", "Finnland", [
        ("FI", "Finnland"),
    ]),
    ("🇬🇷", "Griechenland", [
        ("GR", "Griechenland"),
    ]),
]

ALL_REGIONS: list[str] = [code for _, _, entries in REGION_GROUPS for code, _ in entries]


# ═══════════════════════════════════════════════════════════════════════════════
# Easter calculations
# ═══════════════════════════════════════════════════════════════════════════════

def easter_date(year: int) -> date:
    """Return Gregorian (Catholic/Protestant) Easter Sunday via Gauss algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * m + 114) // 31
    day = ((h + ll - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def orthodox_easter_date(year: int) -> date:
    """Return Orthodox Easter Sunday (Gregorian calendar date)."""
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1
    julian = date(year, month, day)
    # Convert Julian → Gregorian (add 13 days for 1900–2099)
    return julian + timedelta(days=13)


# ═══════════════════════════════════════════════════════════════════════════════
# Calendar helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _first_weekday(year: int, month: int, weekday: int) -> date:
    """First occurrence of weekday (0=Mon … 6=Sun) in month."""
    d = date(year, month, 1)
    diff = (weekday - d.weekday()) % 7
    return d + timedelta(days=diff)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Last occurrence of weekday in month."""
    last = _cal.monthrange(year, month)[1]
    d = date(year, month, last)
    diff = (d.weekday() - weekday) % 7
    return d - timedelta(days=diff)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-based) occurrence of weekday in month."""
    first = _first_weekday(year, month, weekday)
    return first + timedelta(weeks=n - 1)


def _saturday_in_range(year: int, month: int, day_from: int, day_to: int) -> date:
    """First Saturday in month between day_from and day_to (inclusive)."""
    for day in range(day_from, day_to + 1):
        d = date(year, month, day)
        if d.weekday() == 5:  # Saturday
            return d
    return date(year, month, day_from)


def _buss_und_bettag(year: int) -> date:
    """Wednesday before November 22 (Sachsen)."""
    nov22 = date(year, 11, 22)
    days_back = (nov22.weekday() - 2) % 7
    return nov22 - timedelta(days=days_back)


def _nl_koningsdag(year: int) -> date:
    """King's Day NL: Apr 27, moved to Apr 26 if Sunday."""
    d = date(year, 4, 27)
    return d - timedelta(days=1) if d.weekday() == 6 else d


# ═══════════════════════════════════════════════════════════════════════════════
# Holiday name catalogue (de / en)
# ═══════════════════════════════════════════════════════════════════════════════

HOLIDAY_NAMES: dict[str, dict[str, str]] = {
    # ── Common ────────────────────────────────────────────────────────────────
    "new_year":          {"de": "Neujahr",                        "en": "New Year's Day"},
    "epiphany":          {"de": "Heilige Drei Könige",            "en": "Epiphany"},
    "womens_day":        {"de": "Internationaler Frauentag",      "en": "International Women's Day"},
    "good_friday":       {"de": "Karfreitag",                     "en": "Good Friday"},
    "holy_saturday":     {"de": "Karsamstag",                     "en": "Holy Saturday"},
    "easter_sunday":     {"de": "Ostersonntag",                   "en": "Easter Sunday"},
    "easter_monday":     {"de": "Ostermontag",                    "en": "Easter Monday"},
    "labour_day":        {"de": "Tag der Arbeit",                 "en": "Labour Day"},
    "ascension":         {"de": "Christi Himmelfahrt",            "en": "Ascension Day"},
    "whit_sunday":       {"de": "Pfingstsonntag",                 "en": "Whit Sunday"},
    "whit_monday":       {"de": "Pfingstmontag",                  "en": "Whit Monday"},
    "corpus_christi":    {"de": "Fronleichnam",                   "en": "Corpus Christi"},
    "assumption":        {"de": "Mariä Himmelfahrt",              "en": "Assumption of Mary"},
    "reformation":       {"de": "Reformationstag",                "en": "Reformation Day"},
    "all_saints":        {"de": "Allerheiligen",                  "en": "All Saints' Day"},
    "christmas":         {"de": "1. Weihnachtstag",               "en": "Christmas Day"},
    "st_stephens":       {"de": "2. Weihnachtstag",               "en": "St. Stephen's Day / Boxing Day"},
    # ── Germany ───────────────────────────────────────────────────────────────
    "german_unity":      {"de": "Tag der Deutschen Einheit",      "en": "German Unity Day"},
    "liberation_be":     {"de": "Tag der Befreiung",              "en": "Liberation Day"},
    "buss_bettag":       {"de": "Buß- und Bettag",               "en": "Day of Repentance"},
    "weltkindertag":     {"de": "Weltkindertag",                  "en": "World Children's Day"},
    # ── Austria ───────────────────────────────────────────────────────────────
    "at_national":       {"de": "Nationalfeiertag",               "en": "Austrian National Day"},
    "at_state":          {"de": "Staatsfeiertag",                 "en": "Austrian State Holiday"},
    "immaculate":        {"de": "Mariä Empfängnis",               "en": "Immaculate Conception"},
    # ── Switzerland ───────────────────────────────────────────────────────────
    "swiss_national":    {"de": "Bundesfeiertag",                 "en": "Swiss National Day"},
    "berchtoldstag":     {"de": "Berchtoldstag",                  "en": "Berchtold's Day"},
    # ── France ────────────────────────────────────────────────────────────────
    "bastille_day":      {"de": "Nationalfeiertag",               "en": "Bastille Day"},
    "victory_1945":      {"de": "Ende des 2. Weltkriegs",         "en": "Victory in Europe Day"},
    "armistice":         {"de": "Waffenstillstand",               "en": "Armistice Day"},
    "toussaint":         {"de": "Allerheiligen",                  "en": "All Saints' Day"},
    # ── Netherlands ───────────────────────────────────────────────────────────
    "koningsdag":        {"de": "Königstag",                      "en": "King's Day"},
    "liberation_nl":     {"de": "Befreiungstag",                  "en": "Liberation Day"},
    # ── Belgium ───────────────────────────────────────────────────────────────
    "be_national":       {"de": "Nationalfeiertag",               "en": "Belgian National Day"},
    # ── Luxembourg ────────────────────────────────────────────────────────────
    "lu_national":       {"de": "Nationalfeiertag",               "en": "Luxembourg National Day"},
    # ── Poland ────────────────────────────────────────────────────────────────
    "pl_independence":   {"de": "Unabhängigkeitstag",             "en": "Polish Independence Day"},
    "pl_constitution":   {"de": "Verfassungstag",                 "en": "Polish Constitution Day"},
    "pl_epiphany":       {"de": "Heilige Drei Könige",            "en": "Epiphany"},
    # ── Czech Republic ────────────────────────────────────────────────────────
    "cz_statehood":      {"de": "Tschechischer Staatsfeiertag",   "en": "Czech Statehood Day"},
    "cz_national":       {"de": "Tschechischer Nationalfeiertag", "en": "Czech National Day"},
    "cz_liberation":     {"de": "Befreiungstag",                  "en": "Liberation Day"},
    "cz_cyril":          {"de": "Kyrill und Method",              "en": "Sts. Cyril & Methodius"},
    "cz_hus":            {"de": "Jan-Hus-Tag",                    "en": "Jan Hus Day"},
    "cz_freedom":        {"de": "Freiheits- und Demokratietag",   "en": "Struggle for Freedom Day"},
    "christmas_eve":     {"de": "Heiligabend",                    "en": "Christmas Eve"},
    # ── Italy ─────────────────────────────────────────────────────────────────
    "it_liberation":     {"de": "Befreiungstag",                  "en": "Liberation Day"},
    "it_republic":       {"de": "Tag der Republik",               "en": "Republic Day"},
    "it_immaculate":     {"de": "Mariä Empfängnis",               "en": "Immaculate Conception"},
    # ── Spain ─────────────────────────────────────────────────────────────────
    "es_national":       {"de": "Spanischer Nationalfeiertag",    "en": "Spanish National Day"},
    "es_constitution":   {"de": "Verfassungstag",                 "en": "Constitution Day"},
    "es_immaculate":     {"de": "Mariä Empfängnis",               "en": "Immaculate Conception"},
    # ── Portugal ──────────────────────────────────────────────────────────────
    "pt_freedom":        {"de": "Freiheitstag",                   "en": "Freedom Day"},
    "pt_portugal":       {"de": "Portugal-Tag",                   "en": "Day of Portugal"},
    "pt_republic":       {"de": "Tag der Republik",               "en": "Republic Day"},
    "pt_independence":   {"de": "Restaurierungstag",              "en": "Restoration of Independence"},
    # ── United Kingdom ────────────────────────────────────────────────────────
    "early_may_bh":      {"de": "May Bank Holiday",               "en": "Early May Bank Holiday"},
    "spring_bh":         {"de": "Spring Bank Holiday",            "en": "Spring Bank Holiday"},
    "summer_bh_eng":     {"de": "Summer Bank Holiday",            "en": "Summer Bank Holiday"},
    "summer_bh_sct":     {"de": "Summer Bank Holiday",            "en": "Summer Bank Holiday"},
    "boxing_day":        {"de": "Boxing Day",                     "en": "Boxing Day"},
    "gb_new_year_2":     {"de": "2. Neujahr",                     "en": "2nd January"},
    "st_andrews":        {"de": "Andreastag",                     "en": "St. Andrew's Day"},
    "orangemens_day":    {"de": "Orangemens Day",                 "en": "Orangemen's Day"},
    # ── Ireland ───────────────────────────────────────────────────────────────
    "st_patricks":       {"de": "St. Patrick's Day",              "en": "St. Patrick's Day"},
    "st_brigid":         {"de": "St. Brigid's Day",               "en": "St. Brigid's Day"},
    "june_bh":           {"de": "Juni-Feiertag",                  "en": "June Bank Holiday"},
    "august_bh":         {"de": "August-Feiertag",                "en": "August Bank Holiday"},
    "october_bh":        {"de": "Oktober-Feiertag",               "en": "October Bank Holiday"},
    # ── Denmark ───────────────────────────────────────────────────────────────
    "dk_constitution":   {"de": "Grundlovsdag",                   "en": "Constitution Day"},
    "maundy_thursday":   {"de": "Gründonnerstag",                 "en": "Maundy Thursday"},
    # ── Sweden ────────────────────────────────────────────────────────────────
    "se_national":       {"de": "Schwedischer Nationalfeiertag",  "en": "Swedish National Day"},
    "midsummer_eve":     {"de": "Mittsommerabend",                "en": "Midsummer Eve"},
    "midsummer":         {"de": "Mittsommertag",                  "en": "Midsummer Day"},
    "all_saints_se":     {"de": "Allerheiligen",                  "en": "All Saints' Day"},
    # ── Norway ────────────────────────────────────────────────────────────────
    "no_constitution":   {"de": "Grunnlovsdag",                   "en": "Constitution Day"},
    # ── Finland ───────────────────────────────────────────────────────────────
    "fi_independence":   {"de": "Unabhängigkeitstag",             "en": "Independence Day"},
    "midsummer_fi":      {"de": "Mittsommertag (Juhannus)",       "en": "Midsummer Day"},
    "all_saints_fi":     {"de": "Allerheiligen",                  "en": "All Saints' Day"},
    # ── Greece ────────────────────────────────────────────────────────────────
    "gr_independence":   {"de": "Griechischer Unabhängigkeitstag","en": "Greek Independence Day"},
    "gr_ohi":            {"de": "Ohi-Tag",                        "en": "Ohi Day"},
    "clean_monday":      {"de": "Reiner Montag",                  "en": "Clean Monday"},
    "orthodox_friday":   {"de": "Orthodoxer Karfreitag",          "en": "Orthodox Good Friday"},
    "orthodox_easter":   {"de": "Orthodoxer Ostersonntag",        "en": "Orthodox Easter Sunday"},
    "orthodox_monday":   {"de": "Orthodoxer Ostermontag",         "en": "Orthodox Easter Monday"},
    "orthodox_whit":     {"de": "Orthodoxes Pfingstmontag",       "en": "Orthodox Whit Monday"},
}


def _hn(key: str, lang: str = "de") -> str:
    """Look up holiday name. lang: 'de' or 'en'."""
    entry = HOLIDAY_NAMES.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("de") or key


# ═══════════════════════════════════════════════════════════════════════════════
# Holiday calculation
# ═══════════════════════════════════════════════════════════════════════════════

def get_holidays(year: int, region: str) -> list[tuple[date, str, str]]:
    """Return list of (date, name_de, name_en) for given year and region code."""

    def h(d: date, key: str) -> tuple[date, str, str]:
        return (d, _hn(key, "de"), _hn(key, "en"))

    estr = easter_date(year)
    country = region.split("-")[0]  # e.g. "DE" from "DE-NW", "GB" from "GB-ENG"
    result: list[tuple[date, str, str]] = []

    # ── Germany ───────────────────────────────────────────────────────────────
    if country == "DE":
        result += [
            h(date(year, 1, 1), "new_year"),
            h(estr - timedelta(days=2), "good_friday"),
            h(estr, "easter_sunday"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(date(year, 5, 1), "labour_day"),
            h(estr + timedelta(days=39), "ascension"),
            h(estr + timedelta(days=49), "whit_sunday"),
            h(estr + timedelta(days=50), "whit_monday"),
            h(date(year, 10, 3), "german_unity"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]
        fronleichnam = estr + timedelta(days=60)
        reformationstag = date(year, 10, 31)
        allerheiligen = date(year, 11, 1)

        if region == "DE-BW":
            result += [h(date(year, 1, 6), "epiphany"), h(fronleichnam, "corpus_christi"), h(allerheiligen, "all_saints")]
        elif region == "DE-BY":
            result += [h(date(year, 1, 6), "epiphany"), h(fronleichnam, "corpus_christi"), h(date(year, 8, 15), "assumption"), h(allerheiligen, "all_saints")]
        elif region == "DE-BE":
            result.append(h(date(year, 3, 8), "womens_day"))
            if year >= 2025:
                result.append(h(date(year, 5, 8), "liberation_be"))
        elif region in ("DE-HB", "DE-HH", "DE-NI", "DE-SH"):
            result.append(h(reformationstag, "reformation"))
        elif region == "DE-HE":
            result.append(h(fronleichnam, "corpus_christi"))
        elif region == "DE-MV":
            result += [h(date(year, 3, 8), "womens_day"), h(reformationstag, "reformation")]
        elif region == "DE-NW":
            result += [h(fronleichnam, "corpus_christi"), h(allerheiligen, "all_saints")]
        elif region == "DE-RP":
            result += [h(fronleichnam, "corpus_christi"), h(allerheiligen, "all_saints")]
        elif region == "DE-SL":
            result += [h(fronleichnam, "corpus_christi"), h(date(year, 8, 15), "assumption"), h(allerheiligen, "all_saints")]
        elif region == "DE-SN":
            result += [h(reformationstag, "reformation"), h(_buss_und_bettag(year), "buss_bettag")]
        elif region == "DE-ST":
            result += [h(date(year, 1, 6), "epiphany"), h(reformationstag, "reformation")]
        elif region == "DE-TH":
            result += [h(fronleichnam, "corpus_christi"), h(reformationstag, "reformation"), h(date(year, 9, 20), "weltkindertag")]

    # ── Austria ───────────────────────────────────────────────────────────────
    elif country == "AT":
        result += [
            h(date(year, 1, 1),  "new_year"),
            h(date(year, 1, 6),  "epiphany"),
            h(estr + timedelta(days=1),  "easter_monday"),
            h(date(year, 5, 1),  "at_state"),
            h(estr + timedelta(days=39), "ascension"),
            h(estr + timedelta(days=50), "whit_monday"),
            h(estr + timedelta(days=60), "corpus_christi"),
            h(date(year, 8, 15), "assumption"),
            h(date(year, 10, 26), "at_national"),
            h(date(year, 11, 1),  "all_saints"),
            h(date(year, 12, 8),  "immaculate"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]
        # AT sub-regions have same national holidays; add regional if needed
        if region == "AT-9":  # Wien – same as national
            pass
        # Other AT regions have same public holidays as national

    # ── Switzerland ───────────────────────────────────────────────────────────
    elif country == "CH":
        # Most cantons share these
        result += [
            h(date(year, 1, 1),  "new_year"),
            h(estr - timedelta(days=2), "good_friday"),
            h(estr, "easter_sunday"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(estr + timedelta(days=39), "ascension"),
            h(estr + timedelta(days=49), "whit_sunday"),
            h(estr + timedelta(days=50), "whit_monday"),
            h(date(year, 8, 1),  "swiss_national"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]
        if region in ("CH", "CH-BE", "CH-ZH", "CH-AG"):
            result.append(h(date(year, 1, 2), "berchtoldstag"))
        if region == "CH-BE":
            result.append(h(date(year, 5, 1), "labour_day"))
        if region == "CH-BS":
            result.append(h(date(year, 5, 1), "labour_day"))
        if region == "CH-GE":
            # Jeûne genevois: Thursday after first Sunday in September
            sep1 = date(year, 9, 1)
            first_sun = sep1 + timedelta(days=(6 - sep1.weekday()) % 7)
            jeune = first_sun + timedelta(days=4)
            result.append((jeune, "Jeûne genevois", "Fast of Geneva"))

    # ── France ────────────────────────────────────────────────────────────────
    elif country == "FR":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(estr + timedelta(days=1),  "easter_monday"),
            h(date(year, 5, 1),   "labour_day"),
            h(date(year, 5, 8),   "victory_1945"),
            h(estr + timedelta(days=39), "ascension"),
            h(estr + timedelta(days=50), "whit_monday"),
            h(date(year, 7, 14),  "bastille_day"),
            h(date(year, 8, 15),  "assumption"),
            h(date(year, 11, 1),  "toussaint"),
            h(date(year, 11, 11), "armistice"),
            h(date(year, 12, 25), "christmas"),
        ]

    # ── Netherlands ───────────────────────────────────────────────────────────
    elif country == "NL":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(estr - timedelta(days=2), "good_friday"),
            h(estr, "easter_sunday"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(_nl_koningsdag(year), "koningsdag"),
            h(date(year, 5, 5),   "liberation_nl"),
            h(estr + timedelta(days=39), "ascension"),
            h(estr + timedelta(days=49), "whit_sunday"),
            h(estr + timedelta(days=50), "whit_monday"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]

    # ── Belgium ───────────────────────────────────────────────────────────────
    elif country == "BE":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(date(year, 5, 1),   "labour_day"),
            h(estr + timedelta(days=39), "ascension"),
            h(estr + timedelta(days=50), "whit_monday"),
            h(date(year, 7, 21),  "be_national"),
            h(date(year, 8, 15),  "assumption"),
            h(date(year, 11, 1),  "all_saints"),
            h(date(year, 11, 11), "armistice"),
            h(date(year, 12, 25), "christmas"),
        ]

    # ── Luxembourg ────────────────────────────────────────────────────────────
    elif country == "LU":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(date(year, 5, 1),   "labour_day"),
            h(estr + timedelta(days=39), "ascension"),
            h(estr + timedelta(days=50), "whit_monday"),
            h(date(year, 6, 23),  "lu_national"),
            h(date(year, 8, 15),  "assumption"),
            h(date(year, 11, 1),  "all_saints"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]

    # ── Poland ────────────────────────────────────────────────────────────────
    elif country == "PL":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(date(year, 1, 6),   "pl_epiphany"),
            h(estr, "easter_sunday"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(date(year, 5, 1),   "labour_day"),
            h(date(year, 5, 3),   "pl_constitution"),
            h(estr + timedelta(days=49), "whit_sunday"),
            h(estr + timedelta(days=60), "corpus_christi"),
            h(date(year, 8, 15),  "assumption"),
            h(date(year, 11, 1),  "all_saints"),
            h(date(year, 11, 11), "pl_independence"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]

    # ── Czech Republic ────────────────────────────────────────────────────────
    elif country == "CZ":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(estr - timedelta(days=2), "good_friday"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(date(year, 5, 1),   "labour_day"),
            h(date(year, 5, 8),   "cz_liberation"),
            h(date(year, 7, 5),   "cz_cyril"),
            h(date(year, 7, 6),   "cz_hus"),
            h(date(year, 9, 28),  "cz_statehood"),
            h(date(year, 10, 28), "cz_national"),
            h(date(year, 11, 17), "cz_freedom"),
            h(date(year, 12, 24), "christmas_eve"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]

    # ── Italy ─────────────────────────────────────────────────────────────────
    elif country == "IT":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(date(year, 1, 6),   "epiphany"),
            h(estr, "easter_sunday"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(date(year, 4, 25),  "it_liberation"),
            h(date(year, 5, 1),   "labour_day"),
            h(date(year, 6, 2),   "it_republic"),
            h(date(year, 8, 15),  "assumption"),
            h(date(year, 11, 1),  "all_saints"),
            h(date(year, 12, 8),  "it_immaculate"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]

    # ── Spain ─────────────────────────────────────────────────────────────────
    elif country == "ES":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(date(year, 1, 6),   "epiphany"),
            h(estr - timedelta(days=2), "good_friday"),
            h(date(year, 5, 1),   "labour_day"),
            h(date(year, 8, 15),  "assumption"),
            h(date(year, 10, 12), "es_national"),
            h(date(year, 11, 1),  "all_saints"),
            h(date(year, 12, 6),  "es_constitution"),
            h(date(year, 12, 8),  "es_immaculate"),
            h(date(year, 12, 25), "christmas"),
        ]

    # ── Portugal ──────────────────────────────────────────────────────────────
    elif country == "PT":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(estr - timedelta(days=2), "good_friday"),
            h(estr, "easter_sunday"),
            h(date(year, 4, 25),  "pt_freedom"),
            h(date(year, 5, 1),   "labour_day"),
            h(estr + timedelta(days=60), "corpus_christi"),
            h(date(year, 6, 10),  "pt_portugal"),
            h(date(year, 8, 15),  "assumption"),
            h(date(year, 10, 5),  "pt_republic"),
            h(date(year, 11, 1),  "all_saints"),
            h(date(year, 12, 1),  "pt_independence"),
            h(date(year, 12, 8),  "immaculate"),
            h(date(year, 12, 25), "christmas"),
        ]

    # ── United Kingdom ────────────────────────────────────────────────────────
    elif country == "GB":
        may_bh   = _first_weekday(year, 5, 0)   # first Monday May
        spring_bh = _last_weekday(year, 5, 0)   # last Monday May
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(estr - timedelta(days=2), "good_friday"),
            h(may_bh,  "early_may_bh"),
            h(spring_bh, "spring_bh"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "boxing_day"),
        ]
        if region == "GB-ENG" or region == "GB-WLS":
            result.append(h(estr + timedelta(days=1), "easter_monday"))
            result.append(h(_last_weekday(year, 8, 0), "summer_bh_eng"))
        elif region == "GB-SCT":
            result.append(h(date(year, 1, 2), "gb_new_year_2"))
            result.append(h(_first_weekday(year, 8, 0), "summer_bh_sct"))
            result.append(h(date(year, 11, 30), "st_andrews"))
        elif region == "GB-NIR":
            result.append(h(estr + timedelta(days=1), "easter_monday"))
            result.append(h(date(year, 3, 17), "st_patricks"))
            result.append(h(date(year, 7, 12), "orangemens_day"))
            result.append(h(_last_weekday(year, 8, 0), "summer_bh_eng"))

    # ── Ireland ───────────────────────────────────────────────────────────────
    elif country == "IE":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(date(year, 3, 17),  "st_patricks"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(_first_weekday(year, 5, 0), "early_may_bh"),
            h(_first_weekday(year, 6, 0), "june_bh"),
            h(_first_weekday(year, 8, 0), "august_bh"),
            h(_last_weekday(year, 10, 0), "october_bh"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]
        if year >= 2023:
            result.append(h(date(year, 2, 1), "st_brigid"))

    # ── Denmark ───────────────────────────────────────────────────────────────
    elif country == "DK":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(estr - timedelta(days=3), "maundy_thursday"),
            h(estr - timedelta(days=2), "good_friday"),
            h(estr, "easter_sunday"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(estr + timedelta(days=39), "ascension"),
            h(estr + timedelta(days=49), "whit_sunday"),
            h(estr + timedelta(days=50), "whit_monday"),
            h(date(year, 6, 5),   "dk_constitution"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]
        # Store Bededag abolished from 2024
        if year < 2024:
            result.append(h(estr + timedelta(days=26), "dk_constitution"))  # reuse key

    # ── Sweden ────────────────────────────────────────────────────────────────
    elif country == "SE":
        midsummer = _saturday_in_range(year, 6, 20, 26)
        all_saints_se = _saturday_in_range(year, 10, 31, 31) if date(year, 10, 31).weekday() == 5 else _saturday_in_range(year, 11, 1, 6)
        # All Saints: first Saturday between Oct 31 and Nov 6
        oct31 = date(year, 10, 31)
        if oct31.weekday() == 5:
            all_saints_se = oct31
        else:
            all_saints_se = _first_weekday(year, 11, 5)  # first Saturday Nov
            if all_saints_se > date(year, 11, 6):
                all_saints_se = date(year, 10, 31) + timedelta(days=(5 - date(year, 10, 31).weekday()) % 7)

        result += [
            h(date(year, 1, 1),   "new_year"),
            h(date(year, 1, 6),   "epiphany"),
            h(estr - timedelta(days=2), "good_friday"),
            h(estr, "easter_sunday"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(date(year, 5, 1),   "labour_day"),
            h(estr + timedelta(days=39), "ascension"),
            h(estr + timedelta(days=49), "whit_sunday"),
            h(date(year, 6, 6),   "se_national"),
            h(midsummer - timedelta(days=1), "midsummer_eve"),
            h(midsummer, "midsummer"),
            h(all_saints_se, "all_saints_se"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]

    # ── Norway ────────────────────────────────────────────────────────────────
    elif country == "NO":
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(estr - timedelta(days=3), "maundy_thursday"),
            h(estr - timedelta(days=2), "good_friday"),
            h(estr, "easter_sunday"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(date(year, 5, 1),   "labour_day"),
            h(date(year, 5, 17),  "no_constitution"),
            h(estr + timedelta(days=39), "ascension"),
            h(estr + timedelta(days=49), "whit_sunday"),
            h(estr + timedelta(days=50), "whit_monday"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]

    # ── Finland ───────────────────────────────────────────────────────────────
    elif country == "FI":
        midsummer_fi = _saturday_in_range(year, 6, 20, 26)
        # All Saints: first Saturday between Oct 31 and Nov 6
        oct31 = date(year, 10, 31)
        if oct31.weekday() == 5:
            all_saints_fi = oct31
        else:
            delta = (5 - oct31.weekday()) % 7
            all_saints_fi = oct31 + timedelta(days=delta)

        result += [
            h(date(year, 1, 1),   "new_year"),
            h(date(year, 1, 6),   "epiphany"),
            h(estr - timedelta(days=2), "good_friday"),
            h(estr, "easter_sunday"),
            h(estr + timedelta(days=1), "easter_monday"),
            h(date(year, 5, 1),   "labour_day"),
            h(estr + timedelta(days=39), "ascension"),
            h(estr + timedelta(days=49), "whit_sunday"),
            h(midsummer_fi, "midsummer_fi"),
            h(all_saints_fi, "all_saints_fi"),
            h(date(year, 12, 6),  "fi_independence"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]

    # ── Greece ────────────────────────────────────────────────────────────────
    elif country == "GR":
        oe = orthodox_easter_date(year)
        result += [
            h(date(year, 1, 1),   "new_year"),
            h(date(year, 1, 6),   "epiphany"),
            h(oe - timedelta(days=48), "clean_monday"),
            h(date(year, 3, 25),  "gr_independence"),
            h(oe - timedelta(days=2), "orthodox_friday"),
            h(oe, "orthodox_easter"),
            h(oe + timedelta(days=1), "orthodox_monday"),
            h(date(year, 5, 1),   "labour_day"),
            h(oe + timedelta(days=50), "orthodox_whit"),
            h(date(year, 8, 15),  "assumption"),
            h(date(year, 10, 28), "gr_ohi"),
            h(date(year, 12, 25), "christmas"),
            h(date(year, 12, 26), "st_stephens"),
        ]

    return sorted(result, key=lambda x: x[0])


# ═══════════════════════════════════════════════════════════════════════════════
# DB helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _ensure_calendar_days_schema(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS calendar_days (
            day TEXT NOT NULL,
            region TEXT NOT NULL DEFAULT 'DE-NW',
            is_weekend INTEGER DEFAULT 0,
            is_holiday INTEGER DEFAULT 0,
            holiday_name TEXT,
            is_school_holiday INTEGER DEFAULT 0,
            school_holiday_name TEXT,
            updated_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (day, region)
        )
    """)
    cols = {row[1] for row in db.execute("PRAGMA table_info(calendar_days)").fetchall()}
    for col_sql in (
        "holiday_name TEXT",
        "is_school_holiday INTEGER DEFAULT 0",
        "school_holiday_name TEXT",
        "region TEXT DEFAULT 'DE-NW'",
        "updated_at TEXT DEFAULT (datetime('now'))",
    ):
        col_name = col_sql.split()[0]
        if col_name not in cols:
            db.execute(f"ALTER TABLE calendar_days ADD COLUMN {col_sql}")


def seed_holidays(year: int, region: str) -> None:
    """Seed public holidays and weekend flags for one year and one region."""
    db = connect()
    _ensure_calendar_days_schema(db)

    holidays_list = get_holidays(year, region)
    # Build lookup: iso_date → name_de
    holiday_map: dict[str, str] = {d.isoformat(): name_de for d, name_de, _ in holidays_list}

    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        iso = d.isoformat()
        is_weekend = 1 if d.weekday() >= 5 else 0
        holiday_name = holiday_map.get(iso)
        is_holiday = 1 if holiday_name else 0
        db.execute(
            """
            INSERT INTO calendar_days (
                day, region, is_weekend, is_holiday, holiday_name,
                is_school_holiday, school_holiday_name, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, NULL, datetime('now'))
            ON CONFLICT(day, region) DO UPDATE SET
                is_weekend=excluded.is_weekend,
                is_holiday=excluded.is_holiday,
                holiday_name=excluded.holiday_name,
                updated_at=datetime('now')
            """,
            (iso, region, is_weekend, is_holiday, holiday_name),
        )
        d += timedelta(days=1)

    db.commit()
    db.close()


def seed_all_regions(years: list[int] | None = None) -> None:
    """Seed all supported regions for the given years (default: 2026, 2027)."""
    if years is None:
        years = [2026, 2027]
    for year in years:
        for region in ALL_REGIONS:
            seed_holidays(year, region)


def seed_all_regions_if_needed() -> None:
    """Run seed_all_regions only once per _SEED_VERSION."""
    try:
        db = connect()
        try:
            row = db.execute(
                "SELECT value FROM app_config WHERE key='calendar_seed_version'"
            ).fetchone()
            if row and row["value"] == _SEED_VERSION:
                return
        finally:
            db.close()
    except Exception:
        pass

    seed_all_regions([2026, 2027])

    try:
        db = connect()
        try:
            db.execute(
                "INSERT OR REPLACE INTO app_config(key, value, updated_at)"
                " VALUES('calendar_seed_version', ?, datetime('now'))",
                (_SEED_VERSION,),
            )
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def seed_calendar_2026_nrw() -> None:
    """Backward-compatible wrapper."""
    seed_holidays(2026, "DE-NW")


# Backward compat: keep old name
BUNDESLAENDER = [code for code, _ in REGION_GROUPS[0][2]]  # only DE states


if __name__ == "__main__":
    seed_all_regions()
    print(f"Seeded calendar_days for {len(ALL_REGIONS)} regions (2026, 2027)")
