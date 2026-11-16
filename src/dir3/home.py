"""Generic routines after coming home.

A travel task that ends at home carries ``destination`` equal to the
configured ``home_place``.  The helpers :func:`shower_after_homecoming` and
:func:`dinner_after_homecoming` ask :class:`~dir3.whereabouts.Whereabouts`
for those arrivals, then insert a shower or dinner after each one in the first
free slot.  If there is no such trip, nothing is inserted - no return event
means the person is not at home.  :func:`cleanup_after_dinner` appends a
cleanup block after every dinner (optional, via ``HomeSettings.cleanup_minutes``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time, timedelta
from typing import TYPE_CHECKING

from .anchor import Anchor
from .core import PlanError, Task, task
from .timeutils import add_time, time_from_minutes, to_minutes
from .whereabouts import Whereabouts

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import DayContext

_DAY_MINUTES = 24 * 60


@dataclass(frozen=True, slots=True)
class HomeSettings:
    """Configuration for homecoming routines.

    A trip is a homecoming when its ``destination`` equals ``home_place``.
    ``latest_start`` is inclusive: a shower may start at 22:30, but not at
    22:31.  Set it to ``None`` to disable the cutoff.  Dinner has no cutoff;
    it always follows the homecoming trip.
    """

    shower_minutes: int = 15
    shower_name: str = "Duschen"
    latest_start: time | None = time(22, 30)
    home_place: str = "home"
    dinner_minutes: int = 30
    dinner_name: str = "Abendessen"
    #: minute length of the cleanup block after a dinner (0 disables it)
    cleanup_minutes: int = 60
    cleanup_name: str = "Aufräumen"

    def __post_init__(self) -> None:
        if self.shower_minutes <= 0:
            raise ValueError("shower_minutes must be positive")
        if self.dinner_minutes <= 0:
            raise ValueError("dinner_minutes must be positive")
        if self.cleanup_minutes < 0:
            raise ValueError("cleanup_minutes must not be negative")
        if self.cleanup_minutes > 0 and not self.cleanup_name:
            raise ValueError("cleanup_name must not be empty")
        if self.latest_start is not None and not isinstance(self.latest_start, time):
            raise TypeError("latest_start must be a time or None")
        if not self.home_place:
            raise ValueError("home_place must not be empty")


def shower_after_homecoming(
    tasks: Sequence[Task],
    settings: HomeSettings | None = None,
    *,
    ctx: DayContext | None = None,
) -> list[Task]:
    """Insert a shower after every arrival at ``settings.home_place``.

    The arrivals come from :class:`~dir3.whereabouts.Whereabouts`: a trip is
    a homecoming when its ``destination`` matches ``settings.home_place``.

    The shower starts in the first free slot after arrival, but never after
    ``settings.latest_start``.  Existing anchored tasks are respected, so the
    shower is placed after a prayer or another fixed block that overlaps the
    arrival.

    ``ctx`` is optional and only needed when the tasks use anchors instead of
    plain ``time`` values.  A homecoming task must have a resolvable start and
    a ``duration`` or ``until``; otherwise a ``PlanError`` is raised because
    the arrival time would be unknown.

    If the homecoming task is skipped via ``unless``, the generated shower is
    skipped by the same predicates.  The returned list stays ordered by start
    time.
    """
    settings = settings or HomeSettings()
    return _after_homecoming(
        tasks,
        settings,
        name=settings.shower_name,
        minutes=settings.shower_minutes,
        latest_start=settings.latest_start,
        ctx=ctx,
    )


def shower_before(
    tasks: Sequence[Task],
    before: time | Anchor,
    settings: HomeSettings | None = None,
    *,
    ctx: DayContext | None = None,
) -> list[Task]:
    """Insert a shower in the last free slot that ends at ``before``.

    This is the counterpart to :func:`shower_after_homecoming` for days
    without a homecoming trip: the shower is anchored to a later event (for
    example Isha) instead of an arrival.  The returned list stays ordered by
    start time.
    """
    settings = settings or HomeSettings()
    result = list(tasks)
    limit = _resolve(before, ctx)
    if limit is None:
        raise PlanError("shower_before() needs a resolvable time")
    intervals = [
        interval
        for item in result
        if (interval := _task_interval(item, ctx)) is not None
    ]
    start = _last_free_slot(to_minutes(limit), settings.shower_minutes, intervals)
    if start is None:
        return result
    new_task = task(
        settings.shower_name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.shower_minutes),
        flex=False,
    )
    _insert_by_start(result, new_task, ctx)
    return result


def dinner_after_homecoming(
    tasks: Sequence[Task],
    settings: HomeSettings | None = None,
    *,
    ctx: DayContext | None = None,
    not_before: time | Anchor | None = None,
) -> list[Task]:
    """Insert dinner after every arrival at ``settings.home_place``.

    Dinner starts in the first free slot after the homecoming trip.  Pass
    Maghrib as ``not_before`` on fasting days: if the person is already home,
    dinner waits until Maghrib; if the return trip arrives later, dinner
    follows the trip.  The generated dinner inherits the trip's ``unless``
    predicates, just like the shower.
    """
    settings = settings or HomeSettings()
    return _after_homecoming(
        tasks,
        settings,
        name=settings.dinner_name,
        minutes=settings.dinner_minutes,
        latest_start=None,
        not_before=not_before,
        ctx=ctx,
    )


def cleanup_after_dinner(
    tasks: Sequence[Task],
    settings: HomeSettings | None = None,
    *,
    ctx: DayContext | None = None,
    not_before: time | Anchor | None = None,
) -> list[Task]:
    """Insert a cleanup block directly after each dinner.

    The cleanup starts at the dinner's end (or at ``not_before`` when that is
    later) and lasts ``settings.cleanup_minutes``; ``cleanup_minutes == 0``
    disables the block.  The returned list stays ordered by start time, so the
    cleanup lands between dinner and whatever follows (the shower keeps its
    first-free-slot placement).
    """
    settings = settings or HomeSettings()
    if settings.cleanup_minutes <= 0:
        return list(tasks)
    result = list(tasks)
    earliest = _resolve(not_before, ctx)
    for dinner in [item for item in result if item.name == settings.dinner_name]:
        start = _resolve(dinner.start, ctx)
        if start is None or dinner.duration is None:
            raise PlanError(f"'{dinner.name}' needs a start and a duration for cleanup")
        end = add_time(start, dinner.duration)
        if earliest is not None and to_minutes(earliest) > to_minutes(end):
            end = earliest
        cleanup = task(
            settings.cleanup_name,
            start=end,
            duration=timedelta(minutes=settings.cleanup_minutes),
            flex=False,
        )
        _insert_by_start(result, cleanup, ctx)
    return result


def _after_homecoming(
    tasks: Sequence[Task],
    settings: HomeSettings,
    *,
    name: str,
    minutes: int,
    latest_start: time | None,
    ctx: DayContext | None,
    not_before: time | Anchor | None = None,
) -> list[Task]:
    result = list(tasks)
    whereabouts = Whereabouts(result, ctx=ctx)
    earliest_limit = _resolve(not_before, ctx)
    earliest_minutes = to_minutes(earliest_limit) if earliest_limit is not None else None

    for trip in whereabouts.trips_to(settings.home_place):
        source = trip.source if isinstance(trip.source, Task) else None
        unless = source.unless if source is not None else ()
        intervals = [
            interval
            for item in result
            if item is not source and (interval := _task_interval(item, ctx)) is not None
        ]
        earliest = trip.end_minutes
        if earliest_minutes is not None:
            earliest = max(earliest, earliest_minutes)
        start = _first_free_slot(earliest, minutes, intervals, latest_start)
        if start is None:
            continue
        new_task = task(
            name,
            start=time_from_minutes(start),
            duration=timedelta(minutes=minutes),
            unless=unless,
            flex=False,
        )
        _insert_by_start(result, new_task, ctx)
    return result


def _resolve(value: time | Anchor | None, ctx: DayContext | None) -> time | None:
    if isinstance(value, time):
        return value
    if value is None:
        return None
    resolve = getattr(ctx, "resolve", None) if ctx is not None else None
    if resolve is None:
        return None
    resolved = resolve(value)
    return resolved if isinstance(resolved, time) else None


def _task_interval(item: Task, ctx: DayContext | None) -> tuple[int, int] | None:
    start = _resolve(item.start, ctx)
    if start is None:
        return None
    start_minutes = to_minutes(start)
    until = _resolve(item.until, ctx)
    if until is not None:
        end_minutes = to_minutes(until)
        if end_minutes <= start_minutes:
            end_minutes += _DAY_MINUTES
    elif item.duration is not None:
        end_minutes = start_minutes + _duration_minutes(item.duration)
    else:
        end_minutes = _DAY_MINUTES
    return start_minutes, max(end_minutes, start_minutes)


def _duration_minutes(duration: timedelta) -> int:
    return int(duration.total_seconds() // 60)


def _first_free_slot(
    earliest: int,
    minutes: int,
    intervals: Sequence[tuple[int, int]],
    latest_start: time | None,
) -> int | None:
    candidate = earliest
    for start, end in sorted(intervals):
        if end <= candidate:
            continue
        if start >= candidate + minutes:
            break
        candidate = max(candidate, end)
    if candidate + minutes > _DAY_MINUTES:
        return None
    if latest_start is not None and candidate > to_minutes(latest_start):
        return None
    return candidate


def _last_free_slot(
    latest_end: int,
    minutes: int,
    intervals: Sequence[tuple[int, int]],
) -> int | None:
    candidate = latest_end - minutes
    while candidate >= 0:
        blocking = [
            (start, end)
            for start, end in intervals
            if start < candidate + minutes and end > candidate
        ]
        if not blocking:
            return candidate
        candidate = min(start for start, _ in blocking) - minutes
    return None


def _insert_by_start(tasks: list[Task], new_task: Task, ctx: DayContext | None) -> None:
    new_start = _resolve(new_task.start, ctx)
    if new_start is None:
        tasks.append(new_task)
        return
    new_minutes = to_minutes(new_start)
    for index, item in enumerate(tasks):
        start = _resolve(item.start, ctx)
        if start is not None and to_minutes(start) > new_minutes:
            tasks.insert(index, new_task)
            return
    tasks.append(new_task)
