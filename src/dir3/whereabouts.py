"""Whereabouts - infer where you are from travel tasks.

A task with ``origin`` and ``destination`` is a trip.  During the trip the
person is in transit; after its end they are at the destination.  dir3 does
not assume that you are somewhere just because a task happens there - only a
trip to that place changes your whereabouts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import TYPE_CHECKING

from .anchor import Anchor
from .core import PlanError, Task
from .engine import PlanDay, PlannedEvent
from .timeutils import add_time, to_minutes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import DayContext

_DAY_MINUTES = 24 * 60


@dataclass(frozen=True, slots=True)
class Trip:
    """A journey from ``origin`` to ``destination``."""

    origin: str
    destination: str
    start: time
    end: time
    #: the task/event that declared this trip, when available
    source: Task | PlannedEvent | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    @property
    def wraps_midnight(self) -> bool:
        """True when the trip arrives on the next calendar day."""
        return self.end < self.start

    @property
    def start_minutes(self) -> int:
        """Start time as minutes after midnight."""
        return to_minutes(self.start)

    @property
    def end_minutes(self) -> int:
        """End time as minutes after midnight; may exceed 24h after midnight."""
        return self.start_minutes + _span_minutes(self)


class Whereabouts:
    """Replay the day's trips and answer where you are at a moment.

    ``source`` can be a list of :class:`Task` objects (the day definition) or
    a compiled :class:`PlanDay`.  For task lists, pass ``ctx`` when the times
    use anchors; compiled days already contain concrete times.

    The origin of the first travel marker is used as the starting place of the
    day.  After a trip, the destination stays current until the next trip
    starts.  During a trip, :meth:`at` returns ``None`` and
    :meth:`in_transit_at` is true.
    """

    def __init__(
        self,
        source: Sequence[Task] | PlanDay,
        *,
        ctx: DayContext | None = None,
    ) -> None:
        if isinstance(source, PlanDay):
            initial, trips = _trips_from_events(source.events)
        else:
            initial, trips = _trips_from_tasks(source, ctx)
        trips.sort(key=lambda trip: trip.start_minutes)
        self._initial = initial
        self._trips = tuple(trips)
        self._timeline = tuple((trip.start_minutes, trip.end_minutes, trip) for trip in self._trips)

    @property
    def trips(self) -> tuple[Trip, ...]:
        """All trips in chronological order."""
        return self._trips

    @property
    def initial(self) -> str | None:
        """The place at the beginning of the planned day, if known."""
        return self._initial

    def trips_to(self, place: str) -> tuple[Trip, ...]:
        """All trips that arrive at ``place``, in chronological order."""
        return tuple(trip for trip in self._trips if trip.destination == place)

    @property
    def places(self) -> frozenset[str]:
        """Every place mentioned by an origin or destination."""
        places = {trip.origin for trip in self._trips}
        places.update(trip.destination for trip in self._trips)
        if self._initial is not None:
            places.add(self._initial)
        return frozenset(places)

    def at(self, moment: time | datetime | None = None) -> str | None:
        """Return the current place, or ``None`` while travelling.

        ``moment`` defaults to the current local time.  A plain ``time`` is
        interpreted inside the planned day.
        """
        minutes = _moment_minutes(moment)
        if not self._timeline:
            return self._initial
        if minutes < self._timeline[0][0]:
            return self._initial
        current = None
        for start, end, trip in self._timeline:
            if start <= minutes < end:
                return None
            if minutes >= end:
                current = trip.destination
            else:
                break
        return current

    def is_at(self, place: str, moment: time | datetime | None = None) -> bool:
        """True when you are at ``place`` at ``moment``."""
        return self.at(moment) == place

    def in_transit_at(self, moment: time | datetime | None = None) -> bool:
        """True while a trip is in progress at ``moment``."""
        minutes = _moment_minutes(moment)
        return any(start <= minutes < end for start, end, _ in self._timeline)

    def trip_at(self, moment: time | datetime | None = None) -> Trip | None:
        """The active trip at ``moment``, if any."""
        minutes = _moment_minutes(moment)
        for start, end, trip in self._timeline:
            if start <= minutes < end:
                return trip
        return None


def where_am_i(
    source: Sequence[Task] | PlanDay,
    at: time | datetime | None = None,
    *,
    ctx: DayContext | None = None,
) -> str | None:
    """One-off convenience wrapper around :class:`Whereabouts`."""
    return Whereabouts(source, ctx=ctx).at(at)


def _moment_minutes(moment: time | datetime | None) -> int:
    if moment is None:
        moment = datetime.now().time()
    elif isinstance(moment, datetime):
        moment = moment.time()
    return to_minutes(moment)


def _span_minutes(trip: Trip) -> int:
    span = to_minutes(trip.end) - to_minutes(trip.start)
    return span + _DAY_MINUTES if span < 0 else span


def _trips_from_tasks(
    tasks: Sequence[Task],
    ctx: DayContext | None,
) -> tuple[str | None, list[Trip]]:
    trips: list[Trip] = []
    initial = None
    for item in tasks:
        if item.origin is None and item.destination is None:
            continue
        if item.origin is None or item.destination is None:
            raise PlanError(f"'{item.name}' needs both origin and destination")
        if initial is None:
            initial = item.origin
        if ctx is not None and item.unless and any(pred(ctx) for pred in item.unless):
            continue
        start = _resolve(item.start, ctx)
        end = _task_end(item, ctx)
        if start is None or end is None:
            raise PlanError(f"'{item.name}' needs a start and a duration/until for whereabouts")
        trips.append(Trip(item.origin, item.destination, start, end, item))
    return initial, trips


def _trips_from_events(events: Sequence[PlannedEvent]) -> tuple[str | None, list[Trip]]:
    trips: list[Trip] = []
    initial = None
    for event in events:
        if event.origin is None and event.destination is None:
            continue
        if event.origin is None or event.destination is None:
            raise PlanError(f"'{event.name}' needs both origin and destination")
        if initial is None:
            initial = event.origin
        if event.skipped:
            continue
        if event.start is None or event.end is None:
            raise PlanError(f"'{event.name}' needs concrete times for whereabouts")
        trips.append(
            Trip(
                event.origin,
                event.destination,
                event.start.time(),
                event.end.time(),
                event,
            )
        )
    return initial, trips


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


def _task_end(item: Task, ctx: DayContext | None) -> time | None:
    start = _resolve(item.start, ctx)
    if start is None:
        return None
    until = _resolve(item.until, ctx)
    if until is not None:
        return until
    if item.duration is None:
        return None
    return add_time(start, item.duration)
