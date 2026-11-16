"""Season-aware Sunnah sleep plan: night sleep, Tahajjud, Witr and Qaylulah.

The plan is derived from prayer times only, so it adapts to any location:

* the night is measured from Maghrib to Fajr and classified as ``SHORT``
  (under seven hours), ``BALANCED`` or ``LONG`` (over thirteen hours);
* there is **no sleep after Fajr**.  The morning belongs to the day; the one
  sanctioned nap is the Qaylulah;
* the Qaylulah sits in the early-afternoon circadian dip, around 14:00, lasts
  20-30 minutes (longer naps cause sleep inertia) and never runs into Asr;
* each season has its own Qaylulah and Tahajjud duration;
* on short nights - or when the person cannot wake up - Witr is prayed before
  going to sleep; otherwise it follows Tahajjud in the last third;
* the night is split into a first sleep block (until shortly before Tahajjud)
  and a second one (after Witr until Fajr);
* the total sleep is kept between ``min_sleep_minutes`` and
  ``max_sleep_minutes``; if it is too long, Qaylulah shrinks first, then
  Tahajjud is dropped;
* sleep never falls between Asr and Maghrib, never before Isha, and Qaylulah
  never exceeds ``max_qaylulah`` minutes.

The early-afternoon timing follows the usual sleep-research guidance: a short
nap of roughly 20-30 minutes in the natural circadian dip (early afternoon,
not late in the day) refreshes without the grogginess of deep-sleep waking.
See Mayo Clinic, "Napping: Do's and don'ts for healthy adults" (2024) and the
sleep-review literature on afternoon naps and sleep inertia.

The returned blocks use the same ``(minute, Task)`` shape as
:func:`dir3.night_events`, so a day function can simply extend its task list.
Pass a location-specific prayer schedule; in white-night latitudes the local
mosque/Diyanet calendar is the right source, because the 18° Fajr/Isha angle
does not exist there in midsummer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .core import Task, task
from .timeutils import time_from_minutes, to_minutes

_DAY = 24 * 60

SHORT = "SHORT"
BALANCED = "BALANCED"
LONG = "LONG"

#: Witr before going to sleep (short nights / no night waking).
BEFORE_SLEEP = "before_sleep"
#: Witr after Tahajjud in the last third of the night.
AFTER_TAHAJJUD = "after_tahajjud"


@dataclass(frozen=True, slots=True)
class SeasonSettings:
    """Qaylulah and Tahajjud durations for one night-length class."""

    qaylulah: int
    tahajjud: int

    def __post_init__(self) -> None:
        for name in ("qaylulah", "tahajjud"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class SleepPlanSettings:
    """Policy knobs for :func:`sleep_plan`.

    ``sleep_minutes`` is the personal sleep need; ``min_sleep_minutes`` and
    ``max_sleep_minutes`` bound the accepted total.  The season constants
    follow the usual Sunnah pattern: a short Qaylulah in every season and a
    Tahajjud block in the last third whenever the person can wake up for it.

    ``qaylulah_target`` is the early-afternoon minute (default 14:00) in which
    the circadian dip peaks.  The nap is moved earlier only when Asr leaves no
    room, and it is skipped when even that does not fit.
    """

    sleep_minutes: int = 450
    min_sleep_minutes: int = 390
    max_sleep_minutes: int = 510
    can_wake: bool = True

    short_night: int = 7 * 60
    long_night: int = 13 * 60
    short: SeasonSettings = field(default_factory=lambda: SeasonSettings(25, 15))
    balanced: SeasonSettings = field(default_factory=lambda: SeasonSettings(20, 18))
    long: SeasonSettings = field(default_factory=lambda: SeasonSettings(25, 22))

    #: First sleep block starts this many minutes after Isha.
    isha_delay: int = 15
    #: Witr before sleep starts this many minutes after Isha.
    witr_delay: int = 30
    #: Witr duration and the gap after Tahajjud before Witr.
    witr_minutes: int = 5
    witr_gap: int = 5
    #: Safety gap between the first sleep block and Tahajjud.
    tahajjud_gap: int = 15
    #: Gap after Witr before the second sleep block starts.
    second_sleep_gap: int = 10
    #: The night sleep ends at least this many minutes before Fajr.
    fajr_margin: int = 10
    #: With a single night block, leave this many minutes before Fajr.
    single_night_margin: int = 30
    #: Earliest start of the Qaylulah, this many minutes after Dhuhr.
    qaylulah_delay: int = 30
    #: Early-afternoon minute (since midnight) with the highest sleep pressure.
    qaylulah_target: int = 14 * 60
    #: Naps later than this can disturb the night sleep, so they are skipped.
    qaylulah_latest: int = 15 * 60
    #: Qaylulah is never longer than this (the Sunnah maximum).
    max_qaylulah: int = 30
    #: Reduction target when the total sleep is too long.
    reduced_qaylulah: int = 20
    #: Upper bound for the night sleep itself, in minutes before Fajr.
    night_reserve: int = 60
    min_night_sleep: int = 4 * 60

    night_name: str = "Schlafen"
    tahajjud_name: str = "Tahajjud"
    witr_name: str = "Witr"
    qaylulah_name: str = "Kaylûle"

    def __post_init__(self) -> None:
        for name in (
            "sleep_minutes",
            "min_sleep_minutes",
            "max_sleep_minutes",
            "short_night",
            "long_night",
            "isha_delay",
            "witr_delay",
            "witr_minutes",
            "witr_gap",
            "tahajjud_gap",
            "second_sleep_gap",
            "fajr_margin",
            "single_night_margin",
            "qaylulah_delay",
            "qaylulah_target",
            "qaylulah_latest",
            "max_qaylulah",
            "reduced_qaylulah",
            "night_reserve",
            "min_night_sleep",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if self.min_sleep_minutes > self.sleep_minutes:
            raise ValueError("min_sleep_minutes must not exceed sleep_minutes")
        if self.sleep_minutes > self.max_sleep_minutes:
            raise ValueError("sleep_minutes must not exceed max_sleep_minutes")
        if self.short_night >= self.long_night:
            raise ValueError("short_night must be below long_night")
        if self.qaylulah_latest < self.qaylulah_target:
            raise ValueError("qaylulah_latest must not be before qaylulah_target")
        for name in ("night_name", "tahajjud_name", "witr_name", "qaylulah_name"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")


@dataclass(slots=True)
class _Layout:
    """One computed plan, with all blocks as offsets from Maghrib."""

    season: str
    witr_place: str
    qaylulah: int
    first_sleep: tuple[int, int] | None
    qaylulah_block: tuple[int, int] | None
    tahajjud: tuple[int, int] | None
    witr: tuple[int, int] | None
    second_sleep: tuple[int, int] | None

    @property
    def total(self) -> int:
        """Sleep minutes only - Tahajjud and Witr are waking time."""
        blocks = (self.first_sleep, self.qaylulah_block, self.second_sleep)
        return sum(
            end - start for block in blocks if block is not None for start, end in (block,)
        )


def classify_night(
    night_minutes: int,
    settings: SleepPlanSettings | None = None,
) -> str:
    """Classify a Maghrib-to-Fajr night (in minutes) as SHORT/BALANCED/LONG."""
    settings = settings or SleepPlanSettings()
    if night_minutes < settings.short_night:
        return SHORT
    if night_minutes > settings.long_night:
        return LONG
    return BALANCED


def _night_sleep(
    settings: SleepPlanSettings,
    qaylulah: int,
    night: int,
) -> int:
    target = settings.sleep_minutes - qaylulah
    target = max(target, settings.min_night_sleep)
    return min(target, night - settings.night_reserve)


def _qaylulah_block(
    settings: SleepPlanSettings,
    dhuhr_offset: int,
    asr_offset: int | None,
    qaylulah: int,
    target_offset: int,
) -> tuple[int, int] | None:
    """Place the Qaylulah in the early-afternoon circadian dip.

    The preferred start is ``qaylulah_target`` (14:00), expressed as an offset
    from Maghrib.  Only when Asr comes earlier is the nap pulled forward; it
    never runs into Asr, never starts after ``qaylulah_latest`` and never gets
    longer than ``max_qaylulah``.
    """
    duration = min(qaylulah, settings.max_qaylulah)
    if duration <= 0:
        return None
    latest = target_offset + (settings.qaylulah_latest - settings.qaylulah_target)
    earliest = dhuhr_offset + settings.qaylulah_delay
    start = max(earliest, target_offset)
    if asr_offset is not None:
        start = max(earliest, min(target_offset, asr_offset - duration))
        duration = min(duration, asr_offset - start)
    if duration <= 0 or start >= latest:
        return None
    return (start, start + duration)


def _layout(
    settings: SleepPlanSettings,
    cfg: SeasonSettings,
    season: str,
    night: int,
    isha_offset: int,
    dhuhr_offset: int,
    asr_offset: int | None,
    qaylulah_target_offset: int,
    *,
    tahajjud: bool,
    qaylulah: int,
) -> _Layout:
    """Place the blocks for one configuration.

    If the Tahajjud/second-sleep window does not fit before Fajr, the layout
    silently falls back to a single night block with Witr before sleep.
    """
    last_third = (2 * night) // 3
    qaylulah_block = _qaylulah_block(
        settings, dhuhr_offset, asr_offset, qaylulah, qaylulah_target_offset
    )
    qaylulah = (
        qaylulah_block[1] - qaylulah_block[0] if qaylulah_block is not None else 0
    )
    night_sleep = _night_sleep(settings, qaylulah, night)
    witr_place = AFTER_TAHAJJUD if tahajjud else BEFORE_SLEEP

    tahajjud_block: tuple[int, int] | None = None
    witr_block: tuple[int, int] | None = None
    second_sleep: tuple[int, int] | None = None
    first_sleep: tuple[int, int] | None = None

    if tahajjud:
        start = max(last_third, isha_offset + settings.isha_delay)
        end = start + cfg.tahajjud
        witr_start = end + settings.witr_gap
        witr_end = witr_start + settings.witr_minutes
        second_start = witr_end + settings.second_sleep_gap
        second_end = night - settings.fajr_margin
        if end <= second_start <= second_end and start < end:
            tahajjud_block = (start, end)
            witr_block = (witr_start, witr_end)
            second_sleep = (second_start, second_end)
            # The second block is fixed by Witr and Fajr; the first block gets
            # the rest of the night's sleep need.
            first_start = isha_offset + settings.isha_delay
            first_end = min(
                start - settings.tahajjud_gap,
                first_start + night_sleep - (second_end - second_start),
            )
            if first_end > first_start:
                first_sleep = (first_start, first_end)
        else:
            # No room for the split night: fall back to one block.
            tahajjud = False
            witr_place = BEFORE_SLEEP

    if not tahajjud:
        witr_start = isha_offset + settings.witr_delay
        witr_end = witr_start + settings.witr_minutes
        if witr_end <= night - settings.fajr_margin:
            witr_block = (witr_start, witr_end)
        first_start = max(isha_offset + settings.isha_delay, witr_end + settings.second_sleep_gap)
        first_end = night - settings.single_night_margin
        if first_end > first_start:
            first_sleep = (first_start, first_end)

    return _Layout(
        season=season,
        witr_place=witr_place,
        qaylulah=qaylulah,
        first_sleep=first_sleep,
        qaylulah_block=qaylulah_block,
        tahajjud=tahajjud_block,
        witr=witr_block,
        second_sleep=second_sleep,
    )


def _trim(layout: _Layout, maximum: int) -> None:
    """Trim sleep blocks until the total fits ``maximum`` (defensive edge case)."""
    excess = layout.total - maximum
    if excess <= 0:
        return
    for attribute in ("qaylulah_block", "second_sleep", "first_sleep"):
        if excess <= 0:
            break
        block = getattr(layout, attribute)
        if block is None:
            continue
        start, end = block
        cut = min(excess, end - start)
        setattr(layout, attribute, (start, end - cut) if end - cut > start else None)
        excess -= cut


def sleep_plan(
    day: date,
    sched: object,
    settings: SleepPlanSettings | None = None,
) -> list[tuple[int, Task]]:
    """Build the Sunnah sleep blocks for ``day``.

    ``sched`` needs ``fajr``, ``dhuhr``, ``maghrib`` and ``isha`` (the same
    schedule object used by the prayer anchors).  ``asr`` is used, when
    present, to keep Qaylulah out of the Asr-Maghrib no-sleep window.

    Returns ``(minute, task)`` pairs sorted by clock time, like
    :func:`dir3.night_events`.  The day itself is only used for API symmetry;
    the season follows the night length, not the weekday.
    """
    del day  # season and configuration depend on the night, not the weekday
    settings = settings or SleepPlanSettings()

    maghrib = to_minutes(sched.maghrib)
    fajr = to_minutes(sched.fajr)
    isha = to_minutes(getattr(sched, "isha", fajr))
    dhuhr = to_minutes(sched.dhuhr)
    asr_value = getattr(sched, "asr", None)
    asr = to_minutes(asr_value) if asr_value is not None else None

    night = (fajr - maghrib) % _DAY
    if night <= 0:
        return []

    season = classify_night(night, settings)
    cfg = getattr(settings, season.lower())
    isha_offset = (isha - maghrib) % _DAY
    dhuhr_offset = dhuhr - maghrib
    asr_offset = asr - maghrib if asr is not None else None
    qaylulah_target_offset = settings.qaylulah_target - maghrib

    wants_tahajjud = settings.can_wake and season != SHORT
    layout = _layout(
        settings,
        cfg,
        season,
        night,
        isha_offset,
        dhuhr_offset,
        asr_offset,
        qaylulah_target_offset,
        tahajjud=wants_tahajjud,
        qaylulah=cfg.qaylulah,
    )

    # Not enough sleep: drop Tahajjud and move Witr before sleeping (once).
    if layout.total < settings.min_sleep_minutes and layout.tahajjud is not None:
        layout = _layout(
            settings,
            cfg,
            season,
            night,
            isha_offset,
            dhuhr_offset,
            asr_offset,
            qaylulah_target_offset,
            tahajjud=False,
            qaylulah=cfg.qaylulah,
        )

    # Too much sleep: Qaylulah first, then Tahajjud, last the sleep blocks.
    if (
        layout.total > settings.max_sleep_minutes
        and layout.qaylulah > settings.reduced_qaylulah
    ):
        layout = _layout(
            settings,
            cfg,
            season,
            night,
            isha_offset,
            dhuhr_offset,
            asr_offset,
            qaylulah_target_offset,
            tahajjud=layout.tahajjud is not None,
            qaylulah=settings.reduced_qaylulah,
        )
    if layout.total > settings.max_sleep_minutes and layout.tahajjud is not None:
        layout = _layout(
            settings,
            cfg,
            season,
            night,
            isha_offset,
            dhuhr_offset,
            asr_offset,
            qaylulah_target_offset,
            tahajjud=False,
            qaylulah=layout.qaylulah,
        )
    if layout.total > settings.max_sleep_minutes:
        _trim(layout, settings.max_sleep_minutes)

    named: list[tuple[str, tuple[int, int]]] = []
    if layout.first_sleep is not None:
        named.append((settings.night_name, layout.first_sleep))
    if layout.tahajjud is not None:
        named.append((settings.tahajjud_name, layout.tahajjud))
    if layout.witr is not None:
        named.append((settings.witr_name, layout.witr))
    if layout.second_sleep is not None:
        named.append((settings.night_name, layout.second_sleep))
    if layout.qaylulah_block is not None:
        named.append((settings.qaylulah_name, layout.qaylulah_block))

    blocks = [
        (
            (maghrib + start) % _DAY,
            task(
                name,
                start=time_from_minutes(maghrib + start),
                until=time_from_minutes(maghrib + end),
                flex=False,
                overlap=True,
            ),
        )
        for name, (start, end) in named
    ]
    blocks.sort(key=lambda block: block[0])
    return blocks
