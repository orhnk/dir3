"""Reusable travel-task planning on top of the transit API.

Plan files keep their stop names, line sequences and event titles.  This
module owns the reusable selection policy: query backwards from a deadline
when one is given, otherwise query forward, retry only empty provider answers,
and prefer journeys with fewer transfers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from typing import TYPE_CHECKING

from .core import PlanError, Task, task
from .timeutils import time_from_minutes, to_minutes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import DayContext


@dataclass(frozen=True, slots=True)
class Route:
    """A stop-to-stop route that must use the given lines in order.

    With ``duration`` (minutes) the leg time is pinned: :func:`route_way`
    then builds the task directly and never queries the transit provider.
    """

    origin: str
    destination: str
    lines: tuple[str, ...] = ()
    duration: int | None = None

    def __post_init__(self) -> None:
        if self.duration is not None and self.duration <= 0:
            raise ValueError("duration must be positive when set")


@dataclass(frozen=True, slots=True)
class TravelSettings:
    """Provider query policy for :func:`route_way`.

    ``results`` is intentionally larger than the transit service default so a
    pinned but slower route can still appear in the response.  Empty answers
    are retried in ``retry_step`` minute increments, and deadline queries fall
    back to departure searches ``query_windows`` minutes before the deadline.
    """

    results: int = 20
    retry_step: int = 5
    retry_attempts: int = 3
    query_windows: tuple[int, ...] = (90, 45)

    def __post_init__(self) -> None:
        if self.results <= 0:
            raise ValueError("results must be positive")
        if self.retry_step <= 0:
            raise ValueError("retry_step must be positive")
        if self.retry_attempts <= 0:
            raise ValueError("retry_attempts must be positive")
        if any(window < 0 for window in self.query_windows):
            raise ValueError("query_windows must not be negative")


def route_way(
    ctx: DayContext,
    name: str,
    route: Route,
    start: int | time,
    *,
    settings: TravelSettings | None = None,
    lead: int = 0,
    extra: int = 0,
    query_start: int | time | None = None,
    deadline: int | time | None = None,
    origin: str | None = None,
    destination: str | None = None,
) -> Task | None:
    """Return a concrete travel task for the best matching transit journey.

    ``name`` is the full event title; the library does not add a language-
    specific prefix.  ``start`` is the earliest useful minute after the
    previous activity, while ``query_start`` can be earlier (for example when
    breakfast may shrink to catch a bus).  With ``deadline`` the latest
    journey that arrives in time wins; otherwise the earliest suitable one.
    Routes with a fixed ``duration`` skip the provider entirely and build
    their task straight from ``start`` (forward mode) or ``deadline - duration``
    (deadline mode).

    ``lead`` minutes are added before departure and ``extra`` minutes after
    arrival (walking to/from the stop).  ``origin``/``destination`` are the
    place names used by :class:`~dir3.whereabouts.Whereabouts`.

    Returns ``None`` when no connection is available.
    """
    settings = settings or TravelSettings()
    start_minutes = _minutes(start)
    if route.duration is not None:
        return _fixed_way(
            route,
            name,
            start_minutes=start_minutes,
            deadline=None if deadline is None else _minutes(deadline),
            lead=lead,
            extra=extra,
            origin=origin,
            destination=destination,
        )
    query_minutes = start_minutes if query_start is None else _minutes(query_start)
    deadline_minutes = None if deadline is None else _minutes(deadline)
    journeys = _find_journeys(
        ctx,
        route,
        at=query_minutes,
        deadline=deadline_minutes,
        settings=settings,
    )
    chosen = _choose_journey(journeys, deadline_minutes)
    if chosen is None:
        return None

    actual_start = to_minutes(chosen.departure.time()) - lead
    actual_end = to_minutes(chosen.arrival.time()) + extra
    if actual_end <= actual_start:
        return None
    return task(
        name,
        start=time_from_minutes(actual_start),
        duration=timedelta(minutes=actual_end - actual_start),
        flex=False,
        overlap=True,
        origin=origin,
        destination=destination,
    )


def route_end(way: Task) -> int:
    """Return the end minute of a concrete travel task."""
    if not isinstance(way.start, time) or way.duration is None:
        raise PlanError("route_end() needs a task with a concrete start and duration")
    return to_minutes(way.start) + int(way.duration.total_seconds() // 60)


def _fixed_way(
    route: Route,
    name: str,
    *,
    start_minutes: int,
    deadline: int | None,
    lead: int,
    extra: int,
    origin: str | None,
    destination: str | None,
) -> Task | None:
    """Build a concrete travel task from a pinned duration.

    Forward mode departs at ``start_minutes``; deadline mode departs at
    ``deadline - duration`` so the arrival lands exactly on the deadline.
    """
    duration = int(route.duration)
    departure = start_minutes
    if deadline is not None:
        departure = deadline - duration
    actual_start = departure - lead
    actual_end = departure + duration + extra
    if actual_end <= actual_start:
        return None
    return task(
        name,
        start=time_from_minutes(actual_start),
        duration=timedelta(minutes=actual_end - actual_start),
        flex=False,
        overlap=True,
        origin=origin,
        destination=destination,
    )


def _minutes(value: int | time) -> int:
    if isinstance(value, time):
        return to_minutes(value)
    return int(value)


def _time(minutes: int) -> time:
    return time_from_minutes(minutes)


def _transit_journeys(
    ctx: DayContext,
    route: Route,
    *,
    at: int | None = None,
    arrival: int | None = None,
    settings: TravelSettings,
) -> list:
    gate = getattr(ctx, "transit", None)
    if gate is None:
        return []
    try:
        return gate.journeys(
            route.origin,
            route.destination,
            at=None if at is None else _time(at),
            arrival=None if arrival is None else _time(arrival),
            lines=route.lines,
            results=settings.results,
            fewest_transfers=True,
        )
    except (AttributeError, TypeError, ValueError):
        return []


def _find_journeys(
    ctx: DayContext,
    route: Route,
    *,
    at: int,
    deadline: int | None,
    settings: TravelSettings,
) -> list:
    """Query the provider, retrying only when the answer is empty."""
    if deadline is not None:
        journeys = _transit_journeys(
            ctx,
            route,
            arrival=deadline,
            settings=settings,
        )
        if journeys:
            return journeys
        found = []
        seen = set()
        for window in settings.query_windows:
            for journey in _transit_journeys(
                ctx,
                route,
                at=deadline - window,
                settings=settings,
            ):
                key = (journey.departure, journey.arrival)
                if key not in seen:
                    seen.add(key)
                    found.append(journey)
        return found

    for attempt in range(settings.retry_attempts):
        journeys = _transit_journeys(
            ctx,
            route,
            at=at + attempt * settings.retry_step,
            settings=settings,
        )
        if journeys:
            return journeys
    return []


def _choose_journey(journeys: list, deadline: int | None):
    if not journeys:
        return None
    if deadline is None:
        least = min(getattr(journey, "transfers", 0) for journey in journeys)
        candidates = [
            journey for journey in journeys if getattr(journey, "transfers", 0) == least
        ]
        return min(candidates, key=lambda journey: to_minutes(journey.departure.time()))

    eligible = [
        journey
        for journey in journeys
        if to_minutes(journey.arrival.time()) <= deadline
    ]
    if not eligible:
        return None
    least = min(getattr(journey, "transfers", 0) for journey in eligible)
    candidates = [
        journey for journey in eligible if getattr(journey, "transfers", 0) == least
    ]
    return max(candidates, key=lambda journey: to_minutes(journey.departure.time()))
