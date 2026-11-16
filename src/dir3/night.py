"""Generic night blocks: Tahajjud, Witr, Suhoor and sleep until the Fajr block.

The Sunnah places Tahajjud in the last third of the night and delays Suhoor
until just before Fajr.  The night is measured from Maghrib to Fajr, so the
last third begins at ``maghrib + 2/3 * (fajr - maghrib)``.

Ramadan has its own helpers in :mod:`dir3.ramadan`: Suhoor ends at Fajr there,
and Iftar/Tarawih are included as well.  A plan that wants the same night
blocks in Ramadan can enable Suhoor every day and set ``suhoor_name`` /
``suhoor_minutes`` from its :class:`~dir3.ramadan.RamadanSettings`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .core import Task, task
from .islamic import (
    SunnahFastSettings,
    is_ayyam_al_biyd,
    is_sunnah_fast,
    is_voluntary_fast,
)
from .timeutils import time_from_minutes, to_minutes


@dataclass(frozen=True, slots=True)
class NightSettings:
    """Times and weekdays for the optional Tahajjud/Witr/Suhoor blocks.

    ``tahajjud_start`` is a fixed minute since midnight when set.  ``None``
    (the default) places Tahajjud in the last third of the night, as late as
    possible while keeping the Suhoor window before Fajr.

    ``suhoor_before_fajr`` is the safety margin before Fajr; ``0`` means
    Suhoor ends exactly at Fajr.

    ``fasts`` optionally adds Suhoor on the seasonal Sunnah fasts configured
    in :class:`~dir3.islamic.SunnahFastSettings` (Ashura, Arafah, chosen
    Shawwal days, ...).  The weekday and Ayyam al-Biyd rules stay active.

    ``ayyam_al_biyd`` adds Tahajjud and Suhoor on the 13th-15th Hijri day,
    regardless of the weekday. On those days the Suhoor is named
    ``ayyam_name`` (for example ``"Suhoor 🌕️"``) and can therefore get its
    own color in a plan policy.

    ``include_tahajjud`` / ``include_witr`` switch the night prayer and its
    closing Witr independently of the weekday rules; Suhoor stays available
    when Tahajjud is disabled (for example on short summer nights).  Witr is
    placed ``witr_gap`` minutes after Tahajjud and is only added when it still
    ends before Suhoor, so the plan never overlaps the meal.
    """

    tahajjud_start: int | None = None
    tahajjud_minutes: int = 30
    include_tahajjud: bool = True
    include_witr: bool = False
    #: Add Suhoor even on days that are not voluntary fasts (Ramadan).
    force_suhoor: bool = False
    witr_minutes: int = 5
    witr_gap: int = 5
    witr_name: str = "Witr"
    suhoor_minutes: int = 30
    suhoor_before_fajr: int = 0
    regular_weekdays: frozenset[int] = field(default_factory=lambda: frozenset({0, 3, 4}))
    suhoor_weekdays: frozenset[int] = field(default_factory=lambda: frozenset({0, 3}))
    ayyam_al_biyd: bool = True
    suhoor_name: str = "Suhoor"
    ayyam_name: str = "Suhoor 🌕️"
    fajr_lead: int = 45
    #: Keep this many minutes free between the last night block and Fajr block.
    fajr_margin: int = 0
    fasts: SunnahFastSettings | None = None

    def __post_init__(self) -> None:
        for name in (
            "tahajjud_minutes",
            "witr_minutes",
            "witr_gap",
            "suhoor_minutes",
            "suhoor_before_fajr",
            "fajr_lead",
            "fajr_margin",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        for name in ("witr_name", "suhoor_name", "ayyam_name"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")


def night_events(
    day: date,
    sched: object,
    settings: NightSettings | None = None,
) -> list[tuple[int, Task]]:
    """Build ``(minute, task)`` night blocks for ``day``.

    Tahajjud sits in the last third of the night, ending before the Suhoor
    window.  Witr follows Tahajjud when ``include_witr`` is set.  Suhoor is
    delayed to the end of the night and ends at Fajr (or
    ``suhoor_before_fajr`` minutes earlier).  Sleep fills the remaining time
    up to the Fajr block.
    """
    settings = settings or NightSettings()
    weekday = day.weekday()
    ayyam = settings.ayyam_al_biyd and is_ayyam_al_biyd(day)
    tahajjud_day = settings.include_tahajjud and (
        weekday in settings.regular_weekdays or ayyam
    )
    wants_suhoor = (
        settings.force_suhoor
        or is_voluntary_fast(
            day,
            weekdays=settings.suhoor_weekdays,
            ayyam_al_biyd=settings.ayyam_al_biyd,
        )
        or (settings.fasts is not None and is_sunnah_fast(day, settings.fasts))
    )
    if not tahajjud_day and not wants_suhoor:
        return []

    fajr = to_minutes(getattr(sched, "fajr"))
    maghrib = to_minutes(getattr(sched, "maghrib"))
    isha = to_minutes(getattr(sched, "isha", getattr(sched, "fajr")))
    fajr_block = to_minutes(getattr(sched, "sunrise")) - settings.fajr_lead

    # Work in minutes since Maghrib so the night can cross midnight without
    # comparing clock times that wrap around.
    night_minutes = (fajr - maghrib) % (24 * 60)
    last_third = (2 * night_minutes) // 3
    isha_offset = (isha - maghrib) % (24 * 60)
    fajr_block_offset = (fajr_block - maghrib) % (24 * 60)

    suhoor_end = night_minutes - settings.suhoor_before_fajr
    suhoor_start = (
        suhoor_end - settings.suhoor_minutes if wants_suhoor else None
    )
    if isha_offset >= night_minutes:
        # Isha reaches Fajr (white nights): no room for night blocks.
        return []
    if suhoor_start is not None and isha_offset >= suhoor_start:
        # No usable window after Isha before the Suhoor end (e.g. Berlin
        # summer nights where Isha and Fajr almost coincide).
        return []
    tahajjud = None
    if tahajjud_day:
        if settings.tahajjud_start is None:
            # As late as possible in the last third, while leaving the Witr
            # and Suhoor windows free before Fajr.  Tahajjud must follow Isha.
            latest_end = last_third + settings.tahajjud_minutes
            if suhoor_start is not None:
                latest_end = suhoor_start
                if settings.include_witr:
                    latest_end -= settings.witr_minutes + settings.witr_gap
            tahajjud_start = max(
                last_third, isha_offset, latest_end - settings.tahajjud_minutes
            )
            tahajjud_end = min(latest_end, tahajjud_start + settings.tahajjud_minutes)
        else:
            tahajjud_start = max(
                (settings.tahajjud_start - maghrib) % (24 * 60), isha_offset
            )
            tahajjud_end = tahajjud_start + settings.tahajjud_minutes
        if tahajjud_start < tahajjud_end <= night_minutes:
            tahajjud = (tahajjud_start, tahajjud_end)

    events: list[tuple[int, Task]] = []

    def add(name: str, start: int, end: int) -> None:
        events.append(
            (
                (maghrib + start) % (24 * 60),
                task(
                    name,
                    start=time_from_minutes(maghrib + start),
                    until=time_from_minutes(maghrib + end),
                    flex=False,
                    overlap=True,
                ),
            )
        )

    sleep_start = None
    if tahajjud is not None:
        add("Tahajjud", *tahajjud)
        sleep_start = tahajjud[1]
        if settings.include_witr:
            witr_start = tahajjud[1] + settings.witr_gap
            witr_end = witr_start + settings.witr_minutes
            latest_witr = suhoor_start if suhoor_start is not None else night_minutes
            if witr_start < witr_end <= latest_witr:
                add(settings.witr_name, witr_start, witr_end)
                sleep_start = witr_end
    if wants_suhoor and (tahajjud is None or sleep_start <= suhoor_start):
        if sleep_start is not None and sleep_start < suhoor_start:
            add("Schlafen", sleep_start, suhoor_start)
        add(settings.ayyam_name if ayyam else settings.suhoor_name, suhoor_start, suhoor_end)
        sleep_start = suhoor_end
    sleep_end = fajr_block_offset - settings.fajr_margin
    if sleep_start is not None and sleep_start < sleep_end:
        add("Schlafen", sleep_start, sleep_end)
    return events
