"""Legal holidays & workdays via Python's ``holidays`` library.

Install once::

    pip install holidays

Lists *public* (government-designated) holidays for a country and, if you
like, one federal state / region.  Pure calculation - fully offline - and
the holiday names come from the library (native language, no translation
is bundled for most countries).

Configure your country here::

    HOLIDAY_COUNTRY      ISO-3166-1 alpha-2 code, e.g. "DE" or "TR"
    HOLIDAY_SUBDIVISION  ISO-3166-2 subdivision, e.g. "BW" for
                         Baden-Wuerttemberg, or ``None`` for the whole country
    HOLIDAY_LANGUAGE     name language tag, e.g. "de", "tr" (where available);

Note on Turkey: the two religious feasts (Ramazan/Kurban Bayrami) are
government-announced and only approximated by the library; assume they are
correct up to ±1 day.
"""
from __future__ import annotations

from datetime import date

import holidays

HOLIDAY_COUNTRY = "DE"  # e.g. "DE", "TR"
HOLIDAY_SUBDIVISION = "BW"  # e.g. "BW", None for the whole country
HOLIDAY_LANGUAGE = "en"  # where available; most countries stay native

_holidays = holidays.country_holidays(
    HOLIDAY_COUNTRY,
    subdiv=HOLIDAY_SUBDIVISION,
    language=HOLIDAY_LANGUAGE,
)


def is_legal_holiday(today: date) -> bool:
    """True when ``today`` is a public holiday."""
    return today in _holidays


def holiday_name(today: date) -> str | None:
    """Name of the holiday on ``today`` (None on a normal day)."""
    return _holidays.get(today)


def is_holiday(ctx) -> bool:
    """dir3 day-context variant - drop single tasks on holidays:

    ``task("Work", ..., unless=is_holiday)``
    """
    return is_legal_holiday(ctx.date)


def holidays_in(first: date, last: date) -> list[tuple[date, str]]:
    """All public holidays in the range ``[(date, name), ...]``."""
    entries: dict[date, str] = {}
    for year in range(first.year, last.year + 1):
        calendar = holidays.country_holidays(
            HOLIDAY_COUNTRY,
            subdiv=HOLIDAY_SUBDIVISION,
            language=HOLIDAY_LANGUAGE,
            years=[year],
        )
        for day, name in calendar.items():
            if first <= day <= last:
                entries[day] = name
    return sorted(entries.items())


def print_year(year: int = date.today().year) -> None:
    """Quick check: print every public holiday of ``year``."""
    for day, name in holidays.country_holidays(
        HOLIDAY_COUNTRY,
        subdiv=HOLIDAY_SUBDIVISION,
        language=HOLIDAY_LANGUAGE,
        years=[year],
    ).items():
        print(f"{day.isoformat()}  {name}")
