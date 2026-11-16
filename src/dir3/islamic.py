"""Islamic calendar helpers: Hijri dates, Ramadan, Qurban and fasting days."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date

from hijridate import Gregorian

#: Monday and Thursday, the common weekly voluntary fast days.
DEFAULT_VOLUNTARY_FAST_WEEKDAYS = frozenset({0, 3})


@dataclass(frozen=True, slots=True)
class HijriDate:
    """A date in the Umm al-Qura Hijri calendar."""

    year: int
    month: int
    day: int

    @property
    def is_ayyam_al_biyd(self) -> bool:
        """True on the white days (13th, 14th and 15th of the month)."""
        return 13 <= self.day <= 15


def hijri_date(day: date) -> HijriDate:
    """Convert a Gregorian date to its Umm al-Qura Hijri date."""
    hijri = Gregorian.fromdate(day).to_hijri()
    return HijriDate(year=hijri.year, month=hijri.month, day=hijri.day)


def _hijri_or_none(day: date) -> HijriDate | None:
    try:
        return hijri_date(day)
    except (ValueError, OverflowError):
        return None


def is_ayyam_al_biyd(day: date) -> bool:
    """True when ``day`` is one of the three white days."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.is_ayyam_al_biyd


def is_ashura(day: date) -> bool:
    """True on 10 Muharram, the day of Ashura."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 1 and hijri.day == 10


def is_tasu_a(day: date) -> bool:
    """True on 9 Muharram, the day before Ashura (Tasu'a)."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 1 and hijri.day == 9


def is_muharram(day: date) -> bool:
    """True anywhere in Muharram, the first Hijri month."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 1


def is_shaban(day: date) -> bool:
    """True anywhere in Sha'ban, the month before Ramadan."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 8


def is_first_nine_dhul_hijjah(day: date) -> bool:
    """True on 1-9 Dhu al-Hijjah, the first nine days of the month."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 12 and 1 <= hijri.day <= 9


def is_shawwal(day: date) -> bool:
    """True anywhere in Shawwal, the month after Ramadan."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 10


def is_ramadan(day: date) -> bool:
    """True on any day of Ramadan (the 9th Hijri month)."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 9


def is_eid_al_fitr(day: date) -> bool:
    """True on 1 Shawwal, the first day of Eid al-Fitr."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 10 and hijri.day == 1


def is_day_of_arafah(day: date) -> bool:
    """True on 9 Dhu al-Hijjah, the Day of Arafah."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 12 and hijri.day == 9


def is_eid_al_adha(day: date) -> bool:
    """True on 10 Dhu al-Hijjah, the first day of Eid al-Adha."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 12 and hijri.day == 10


def is_tashreeq(day: date) -> bool:
    """True on 11-13 Dhu al-Hijjah, the days of Tashreeq."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 12 and 11 <= hijri.day <= 13


def is_qurban(day: date) -> bool:
    """True on the four Qurban days (10-13 Dhu al-Hijjah).

    The sacrifice may be offered on any of these days.  Use
    :func:`is_eid_al_adha` for the first day only.
    """
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 12 and 10 <= hijri.day <= 13


def is_fasting_forbidden(day: date) -> bool:
    """True on Eid al-Fitr and the Qurban days, when fasting is forbidden."""
    return is_eid_al_fitr(day) or is_qurban(day)


def is_last_ten_nights(day: date) -> bool:
    """True from 21 Ramadan to the end of the month (the last ten days)."""
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 9 and hijri.day >= 21


def is_laylat_al_qadr_candidate(day: date) -> bool:
    """True on an odd night of the last ten Ramadan nights.

    The candidate nights are 21, 23, 25, 27 and 29 Ramadan.  When used for a
    plan day, this refers to the night *before that day's Fajr*: the plan day
    whose early hours contain the last third.  The exact night is unknown, so
    this is only a reminder for Qiyam and du'a.
    """
    hijri = _hijri_or_none(day)
    return hijri is not None and hijri.month == 9 and hijri.day in {21, 23, 25, 27, 29}


@dataclass(frozen=True, slots=True)
class SunnahFastSettings:
    """Which optional fasts :func:`sunnah_fast_name` should recognise.

    Monday/Thursday and Ayyam al-Biyd are on by default, as are the specific
    annual fasts Ashura, Tasu'a and Arafah.  Broad periods (Muharram, Sha'ban,
    the first nine days of Dhu al-Hijjah) are opt-in because they overlap with
    the specific days and can cover many days at once.

    The six days of Shawwal are a personal choice; set ``shawwal_days`` to the
    Hijri day numbers you want to fast, for example ``frozenset({2, 9, 16})``.
    An empty set disables Shawwal fasting here.

    ``dawud_start`` turns on the fast of Dawud (alternate days); the given date
    is treated as a fasting day.
    """

    monday_thursday: bool = True
    ayyam_al_biyd: bool = True
    ashura: bool = True
    tasua: bool = True
    arafah: bool = True
    first_nine_dhul_hijjah: bool = False
    shawwal_days: frozenset[int] = field(default_factory=frozenset)
    muharram: bool = False
    shaban: bool = False
    dawud_start: date | None = None


def sunnah_fast_name(
    day: date,
    settings: SunnahFastSettings | None = None,
) -> str | None:
    """Return the most specific Sunnah-fast label for ``day``, or ``None``.

    Ramadan and the days on which fasting is forbidden always return ``None``.
    When several labels apply, the more specific one wins (for example Ashura
    over a Monday, or Arafah over the general first nine days).
    """
    settings = settings or SunnahFastSettings()
    if is_ramadan(day) or is_fasting_forbidden(day):
        return None
    hijri = _hijri_or_none(day)
    if hijri is None:
        return None

    if settings.ashura and hijri.month == 1 and hijri.day == 10:
        return "Ashura"
    if settings.tasua and hijri.month == 1 and hijri.day == 9:
        return "Tasu'a"
    if settings.arafah and hijri.month == 12 and hijri.day == 9:
        return "Arafah"
    if settings.first_nine_dhul_hijjah and hijri.month == 12 and 1 <= hijri.day <= 9:
        return "Dhul-Hijjah"
    if settings.shawwal_days and hijri.month == 10 and hijri.day in settings.shawwal_days:
        return "Shawwal"
    if settings.ayyam_al_biyd and hijri.is_ayyam_al_biyd:
        return "Ayyam al-Biyd"
    if settings.muharram and hijri.month == 1:
        return "Muharram"
    if settings.shaban and hijri.month == 8:
        return "Sha'ban"
    if (
        settings.dawud_start is not None
        and day >= settings.dawud_start
        and (day - settings.dawud_start).days % 2 == 0
    ):
        return "Dawud"
    if settings.monday_thursday and day.weekday() in {0, 3}:
        return "Montag/Donnerstag"
    return None


def is_sunnah_fast(
    day: date,
    settings: SunnahFastSettings | None = None,
) -> bool:
    """True when ``day`` matches any configured Sunnah fast."""
    return sunnah_fast_name(day, settings) is not None


def is_voluntary_fast(
    day: date,
    *,
    weekdays: Collection[int] = DEFAULT_VOLUNTARY_FAST_WEEKDAYS,
    ayyam_al_biyd: bool = True,
) -> bool:
    """True on a configured optional fast day.

    ``weekdays`` uses Monday=0, matching :meth:`datetime.date.weekday`.
    Ayyam al-Biyd (13th-15th Hijri) are included when ``ayyam_al_biyd`` is
    true.  Ramadan is obligatory, and Eid days are days on which fasting is
    forbidden, so neither counts as a voluntary fast here.
    """
    if is_ramadan(day) or is_fasting_forbidden(day):
        return False
    return day.weekday() in weekdays or (ayyam_al_biyd and is_ayyam_al_biyd(day))


def is_fasting_day(
    day: date,
    *,
    weekdays: Collection[int] = DEFAULT_VOLUNTARY_FAST_WEEKDAYS,
    ayyam_al_biyd: bool = True,
    sunnah_fasts: SunnahFastSettings | None = None,
) -> bool:
    """True when the day is a Ramadan or configured voluntary fast day.

    Use this instead of :func:`is_voluntary_fast` when deciding whether to
    schedule breakfast or a fast-breaking meal: it includes all of Ramadan.

    Pass ``sunnah_fasts`` to include seasonal fasts (Ashura, Arafah, chosen
    Shawwal days, ...).  Without it the old Monday/Thursday + Ayyam behaviour
    is unchanged.
    """
    if is_ramadan(day):
        return True
    if sunnah_fasts is not None:
        return is_sunnah_fast(day, sunnah_fasts)
    return is_voluntary_fast(
        day,
        weekdays=weekdays,
        ayyam_al_biyd=ayyam_al_biyd,
    )
