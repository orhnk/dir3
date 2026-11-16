"""Reusable Sunnah blocks: Rawatib, Witr, Duha, Adhkar, Quran and seasonal acts.

The helpers only place time blocks.  They do not rule on legal details, and
they deliberately keep the number of rak'ahs and the exact wording out of the
scheduler - a plan chooses names, durations and which blocks it wants.

Timing follows the usual Sunni practice:

* Rawatib: 2 before Fajr, 4 before and 2 after Dhuhr, 2 after Maghrib and
  2 after Isha.  The non-emphasised blocks before Asr, Maghrib and Isha are
  optional (``asr_before=4``, ``maghrib_before=2``, ``isha_before=2``).
* Witr: after Isha, or after Tahajjud when that is planned; before Fajr.
* Awwabin: a voluntary block between Maghrib and Isha.
* Duha/Ishraq: from about 15 minutes after sunrise until shortly before
  Dhuhr; the best time is halfway between sunrise and Dhuhr.
* Morning Adhkar: after Fajr until sunrise.  Evening Adhkar: after Asr until
  Maghrib.
* Quran: configurable anchor (default after Fajr).
* I'tikaf: the last ten Ramadan nights, from after Isha until Fajr.
* Qiyam on the odd nights of the last ten (Laylat al-Qadr candidates).
* Eid al-Fitr prayer after sunrise.  Eid al-Adha lives in :mod:`dir3.qurban`.

Not every Sunnah is a calendar event.  Istikharah, Tawbah, Hajah, Tasbih,
Janazah, Istisqa and Khusuf depend on a situation; compose them with ``task``
or call the prayer directly.  Friday-specific acts (Ghusl, Surah al-Kahf,
Salawat) are likewise left to the plan, because their best placement depends
on the local Friday routine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .core import Task, task
from .islamic import (
    is_eid_al_fitr,
    is_last_ten_nights,
    is_laylat_al_qadr_candidate,
)
from .timeutils import time_from_minutes, to_minutes


def _non_negative(settings: object, *names: str) -> None:
    for name in names:
        if getattr(settings, name) < 0:
            raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class RawatibSettings:
    """The regular Sunnah prayers around the five obligatory prayers.

    The counts are only used to build the event names and to decide whether a
    block is included.  Durations are explicit because the library does not
    know how long the obligatory prayer or the user's recitation takes.
    ``after_delay`` leaves room for the Fard prayer before the after-Sunnah.
    """

    fajr_before: int = 2
    dhuhr_before: int = 4
    dhuhr_after: int = 2
    maghrib_after: int = 2
    isha_after: int = 2
    #: Optional non-emphasised (ghair mu'akkadah) blocks; 0 disables them.
    asr_before: int = 0
    maghrib_before: int = 0
    isha_before: int = 0
    fajr_minutes: int = 10
    dhuhr_before_minutes: int = 20
    dhuhr_after_minutes: int = 10
    maghrib_after_minutes: int = 10
    isha_after_minutes: int = 10
    asr_before_minutes: int = 20
    maghrib_before_minutes: int = 10
    isha_before_minutes: int = 10
    after_delay: int = 15
    name_prefix: str = "Rawatib"

    def __post_init__(self) -> None:
        _non_negative(
            self,
            "fajr_before",
            "dhuhr_before",
            "dhuhr_after",
            "maghrib_after",
            "isha_after",
            "asr_before",
            "maghrib_before",
            "isha_before",
            "fajr_minutes",
            "dhuhr_before_minutes",
            "dhuhr_after_minutes",
            "maghrib_after_minutes",
            "isha_after_minutes",
            "asr_before_minutes",
            "maghrib_before_minutes",
            "isha_before_minutes",
            "after_delay",
        )
        if not self.name_prefix.strip():
            raise ValueError("name_prefix must not be empty")


@dataclass(frozen=True, slots=True)
class WitrSettings:
    """Witr after Isha (or at an explicit start after Tahajjud).

    The default delay leaves room for the two Sunnah rak'ahs after Isha; set
    ``delay`` or pass an explicit ``start`` when composing differently.
    """

    delay: int = 25
    minutes: int = 10
    name: str = "Witr"

    def __post_init__(self) -> None:
        _non_negative(self, "delay", "minutes")
        if not self.name.strip():
            raise ValueError("name must not be empty")


@dataclass(frozen=True, slots=True)
class AwwabinSettings:
    """The voluntary prayer between Maghrib and Isha (Awwabin)."""

    #: Default leaves room for the two Rawatib rak'ahs after Maghrib.
    delay: int = 25
    minutes: int = 20
    name: str = "Awwabin"

    def __post_init__(self) -> None:
        _non_negative(self, "delay", "minutes")
        if self.minutes <= 0:
            raise ValueError("minutes must be positive")
        if not self.name.strip():
            raise ValueError("name must not be empty")


@dataclass(frozen=True, slots=True)
class DuhaSettings:
    """The forenoon prayer (Duha/Ishraq)."""

    after_sunrise: int = 15
    before_dhuhr: int = 10
    minutes: int = 15
    #: Start halfway between sunrise and Dhuhr, the narrated best time.
    at_best_time: bool = False
    name: str = "Duha"

    def __post_init__(self) -> None:
        _non_negative(self, "after_sunrise", "before_dhuhr", "minutes")
        if self.minutes <= 0:
            raise ValueError("minutes must be positive")
        if not self.name.strip():
            raise ValueError("name must not be empty")


@dataclass(frozen=True, slots=True)
class AdhkarSettings:
    """Morning and evening remembrance blocks."""

    morning_delay: int = 5
    morning_minutes: int = 15
    evening_delay: int = 5
    evening_minutes: int = 15
    morning_name: str = "Morgen-Adhkar"
    evening_name: str = "Abend-Adhkar"

    def __post_init__(self) -> None:
        _non_negative(
            self,
            "morning_delay",
            "morning_minutes",
            "evening_delay",
            "evening_minutes",
        )
        for name in ("morning_name", "evening_name"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True, slots=True)
class QuranSettings:
    """A Quran recitation block anchored to a prayer or the sunrise."""

    anchor: str = "fajr"
    delay: int = 20
    minutes: int = 20
    name: str = "Quran"

    def __post_init__(self) -> None:
        if self.anchor not in {"fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"}:
            raise ValueError(
                "anchor must be one of fajr, sunrise, dhuhr, asr, maghrib, isha"
            )
        _non_negative(self, "delay", "minutes")
        if self.minutes <= 0:
            raise ValueError("minutes must be positive")
        if not self.name.strip():
            raise ValueError("name must not be empty")


@dataclass(frozen=True, slots=True)
class EidFitrSettings:
    """The Eid al-Fitr prayer after sunrise."""

    prayer_offset: int = 15
    prayer_minutes: int = 30
    prayer_name: str = "Eid al-Fitr prayer"

    def __post_init__(self) -> None:
        _non_negative(self, "prayer_offset")
        if self.prayer_minutes <= 0:
            raise ValueError("prayer_minutes must be positive")
        if not self.prayer_name.strip():
            raise ValueError("prayer_name must not be empty")


@dataclass(frozen=True, slots=True)
class ItikafSettings:
    """I'tikaf on the last ten Ramadan nights."""

    delay: int = 10
    name: str = "I'tikaf"

    def __post_init__(self) -> None:
        _non_negative(self, "delay")
        if not self.name.strip():
            raise ValueError("name must not be empty")


@dataclass(frozen=True, slots=True)
class QiyamSettings:
    """A Qiyam block in the last third of the night."""

    minutes: int = 30
    #: Leave this much room before Fajr for Suhoor and the Fajr prayer.
    before_fajr: int = 60
    name: str = "Qiyam al-Layl"

    def __post_init__(self) -> None:
        _non_negative(self, "before_fajr")
        if self.minutes <= 0:
            raise ValueError("minutes must be positive")
        if not self.name.strip():
            raise ValueError("name must not be empty")


def rawatib_events(
    sched: object,
    settings: RawatibSettings | None = None,
) -> list[tuple[int, Task]]:
    """Return the configured Rawatib blocks in chronological order."""
    settings = settings or RawatibSettings()
    fajr = to_minutes(getattr(sched, "fajr"))
    dhuhr = to_minutes(getattr(sched, "dhuhr"))
    asr = to_minutes(getattr(sched, "asr"))
    maghrib = to_minutes(getattr(sched, "maghrib"))
    isha = to_minutes(getattr(sched, "isha"))

    events: list[tuple[int, Task]] = []

    def add(label: str, count: int, start: int, minutes: int) -> None:
        if count <= 0 or minutes <= 0:
            return
        events.append(
            (
                start,
                task(
                    f"{settings.name_prefix} {label} ({count})",
                    start=time_from_minutes(start),
                    duration=timedelta(minutes=minutes),
                    flex=False,
                    overlap=True,
                ),
            )
        )

    add("Fajr", settings.fajr_before, fajr - settings.fajr_minutes, settings.fajr_minutes)
    add(
        "Dhuhr vor",
        settings.dhuhr_before,
        dhuhr - settings.dhuhr_before_minutes,
        settings.dhuhr_before_minutes,
    )
    add(
        "Dhuhr nach",
        settings.dhuhr_after,
        dhuhr + settings.after_delay,
        settings.dhuhr_after_minutes,
    )
    add(
        "Asr vor",
        settings.asr_before,
        asr - settings.asr_before_minutes,
        settings.asr_before_minutes,
    )
    add(
        "Maghrib vor",
        settings.maghrib_before,
        maghrib - settings.maghrib_before_minutes,
        settings.maghrib_before_minutes,
    )
    add(
        "Maghrib nach",
        settings.maghrib_after,
        maghrib + settings.after_delay,
        settings.maghrib_after_minutes,
    )
    add(
        "Isha vor",
        settings.isha_before,
        isha - settings.isha_before_minutes,
        settings.isha_before_minutes,
    )
    add(
        "Isha nach",
        settings.isha_after,
        isha + settings.after_delay,
        settings.isha_after_minutes,
    )
    events.sort(key=lambda item: item[0])
    return events


def witr(
    sched: object,
    settings: WitrSettings | None = None,
    *,
    start: int | None = None,
) -> tuple[int, Task]:
    """Witr after Isha, or at ``start`` (for example after Tahajjud)."""
    settings = settings or WitrSettings()
    minute = (
        start
        if start is not None
        else to_minutes(getattr(sched, "isha")) + settings.delay
    )
    minute %= 24 * 60
    return minute, task(
        settings.name,
        start=time_from_minutes(minute),
        duration=timedelta(minutes=settings.minutes),
        flex=False,
        overlap=True,
    )


def awwabin(
    sched: object,
    settings: AwwabinSettings | None = None,
) -> tuple[int, Task]:
    """A voluntary block after Maghrib, normally before Isha."""
    settings = settings or AwwabinSettings()
    start = to_minutes(getattr(sched, "maghrib")) + settings.delay
    return start, task(
        settings.name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.minutes),
        flex=False,
        overlap=True,
    )


def duha(
    sched: object,
    settings: DuhaSettings | None = None,
) -> tuple[int, Task]:
    """Duha (Ishraq) in its valid window, optionally at the best time."""
    settings = settings or DuhaSettings()
    sunrise = to_minutes(getattr(sched, "sunrise"))
    dhuhr = to_minutes(getattr(sched, "dhuhr"))
    earliest = sunrise + settings.after_sunrise
    latest = dhuhr - settings.before_dhuhr - settings.minutes
    if latest < earliest:
        raise ValueError("Duha window is too short for the configured duration")

    if settings.at_best_time:
        start = sunrise + (dhuhr - sunrise) // 2
    else:
        start = earliest
    start = max(earliest, min(start, latest))
    return start, task(
        settings.name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.minutes),
        flex=False,
        overlap=True,
    )


def morning_adhkar(
    sched: object,
    settings: AdhkarSettings | None = None,
) -> tuple[int, Task]:
    """Morning remembrance after Fajr."""
    settings = settings or AdhkarSettings()
    start = to_minutes(getattr(sched, "fajr")) + settings.morning_delay
    return start, task(
        settings.morning_name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.morning_minutes),
        flex=False,
        overlap=True,
    )


def evening_adhkar(
    sched: object,
    settings: AdhkarSettings | None = None,
) -> tuple[int, Task]:
    """Evening remembrance after Asr."""
    settings = settings or AdhkarSettings()
    start = to_minutes(getattr(sched, "asr")) + settings.evening_delay
    return start, task(
        settings.evening_name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.evening_minutes),
        flex=False,
        overlap=True,
    )


def adhkar_events(
    sched: object,
    settings: AdhkarSettings | None = None,
) -> list[tuple[int, Task]]:
    """Morning and evening Adhkar (disabled blocks with zero minutes are skipped)."""
    settings = settings or AdhkarSettings()
    events: list[tuple[int, Task]] = []
    if settings.morning_minutes > 0:
        events.append(morning_adhkar(sched, settings))
    if settings.evening_minutes > 0:
        events.append(evening_adhkar(sched, settings))
    return events


def quran(
    sched: object,
    settings: QuranSettings | None = None,
) -> tuple[int, Task]:
    """A Quran block anchored to a prayer time or sunrise."""
    settings = settings or QuranSettings()
    start = to_minutes(getattr(sched, settings.anchor)) + settings.delay
    return start, task(
        settings.name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.minutes),
        flex=False,
        overlap=True,
    )


def eid_fitr_prayer(
    sched: object,
    settings: EidFitrSettings | None = None,
) -> tuple[int, Task]:
    """The Eid al-Fitr prayer after sunrise."""
    settings = settings or EidFitrSettings()
    start = to_minutes(getattr(sched, "sunrise")) + settings.prayer_offset
    return start, task(
        settings.prayer_name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.prayer_minutes),
        flex=False,
        overlap=True,
    )


def eid_fitr_events(
    day: date,
    sched: object,
    settings: EidFitrSettings | None = None,
) -> list[tuple[int, Task]]:
    """Return the Eid al-Fitr prayer on Eid day, otherwise an empty list."""
    if not is_eid_al_fitr(day):
        return []
    return [eid_fitr_prayer(sched, settings)]


def itikaf(
    day: date,
    sched: object,
    settings: ItikafSettings | None = None,
) -> tuple[int, Task] | None:
    """I'tikaf from after Isha on ``day`` until the next Fajr.

    The block belongs to the night that *starts* on the plan day, so pass the
    evening on which I'tikaf begins (the evening before a day in the last ten
    nights).  This is why the check looks at ``day + 1`` and agrees with
    :func:`laylat_al_qadr_qiyam` for that following day.
    """
    if not is_last_ten_nights(day + timedelta(days=1)):
        return None
    settings = settings or ItikafSettings()
    start = (to_minutes(getattr(sched, "isha")) + settings.delay) % (24 * 60)
    end = to_minutes(getattr(sched, "fajr"))
    return start, task(
        settings.name,
        start=time_from_minutes(start),
        until=time_from_minutes(end),
        flex=False,
        overlap=True,
    )


def itikaf_events(
    day: date,
    sched: object,
    settings: ItikafSettings | None = None,
) -> list[tuple[int, Task]]:
    """List form of :func:`itikaf`."""
    block = itikaf(day, sched, settings)
    return [block] if block is not None else []


def qiyam(
    sched: object,
    settings: QiyamSettings | None = None,
) -> tuple[int, Task]:
    """Qiyam al-Layl in the last third, ending before the Fajr window."""
    settings = settings or QiyamSettings()
    fajr = to_minutes(getattr(sched, "fajr"))
    maghrib = to_minutes(getattr(sched, "maghrib"))
    night = (fajr - maghrib) % (24 * 60)
    last_third = (2 * night) // 3
    latest_end = night - settings.before_fajr
    start = max(last_third, latest_end - settings.minutes)
    end = min(latest_end, start + settings.minutes)
    if end <= start:
        raise ValueError("night is too short for the configured Qiyam block")
    return (maghrib + start) % (24 * 60), task(
        settings.name,
        start=time_from_minutes(maghrib + start),
        until=time_from_minutes(maghrib + end),
        flex=False,
        overlap=True,
    )


def laylat_al_qadr_qiyam(
    day: date,
    sched: object,
    settings: QiyamSettings | None = None,
) -> tuple[int, Task] | None:
    """Qiyam on an odd night of the last ten Ramadan nights, else ``None``."""
    if not is_laylat_al_qadr_candidate(day):
        return None
    return qiyam(sched, settings)
