"""dir3 DSL: ``task``, ``day``, ``week``, ``month`` and their data models.

You program a day by returning a list of tasks from a function that receives the
per-day context.  ``week`` and ``month`` assemble patterns which ``compile``
expands into a concrete calendar.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import time, timedelta
from typing import TYPE_CHECKING, Any

from .anchor import Anchor, midnight

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_KEYS = frozenset(WEEKDAY_NAMES)


class PlanError(ValueError):
    """A plan/definition error: wrong day, missing anchor, overflow, ..."""


#: A predicate used in ``unless``: (ctx) -> True means "skip today".
Unless = Callable[[Any], bool]


@dataclass(slots=True)
class Task:
    name: str
    start: Anchor | time | None = None
    until: Anchor | time | None = None
    duration: timedelta | None = None
    space: timedelta | None = None
    unless: tuple[Unless, ...] = ()
    flex: bool = True

    @property
    def anchored(self) -> bool:
        """True when the task pins itself via start/until (not merely chained)."""
        return self.start is not None or self.until is not None

    def describe(self) -> str:
        bits = [self.name]
        if self.start is not None:
            bits.append(f"start={self.start!r}")
        if self.until is not None:
            bits.append(f"until={self.until!r}")
        if self.duration is not None:
            bits.append(f"{self.duration!s}")
        return " ".join(bits)


def task(
    name: str,
    *,
    start: Anchor | time | None = None,
    until: Anchor | time | None = None,
    duration: timedelta | str | None = None,
    space: timedelta | str | None = None,
    unless: Unless | tuple[Unless, ...] | None = None,
    flex: bool = True,
) -> Task:
    """Declare one task inside a day.

    * ``start``  - an anchor (or plain time) that starts the task;
    * ``until``  - an anchor (or time) that ends it (wraps across midnight);
    * ``duration`` - how long it lasts when no ``until`` is given;
    * ``space``  - a gap before the task (used when chaining);
    * ``unless`` - a predicate or tuple of predicates skipping the task for a day;
    * ``flex``   - whether the compiler may shrink this task to absorb overflow.
    """
    if not name.strip():
        raise PlanError("task() needs a name")

    duration_td = (
        duration
        if isinstance(duration, timedelta) or duration is None
        else _as_duration(duration)
    )
    space_td = (
        space if isinstance(space, timedelta) or space is None else _as_duration(space)
    )

    predicates: tuple[Unless, ...] = ()
    if unless is not None:
        predicates = unless if isinstance(unless, tuple) else (unless,)

    if until is None and duration_td is None and not flex:
        raise PlanError(f"task '{name}' needs an until anchor, a duration, or flex=True")

    return Task(
        name=name.strip(),
        start=start,
        until=until,
        duration=duration_td,
        space=space_td,
        unless=predicates,
        flex=flex,
    )


def _as_duration(value: str) -> timedelta:
    from .timeutils import parse_duration

    return parse_duration(value)


@dataclass(slots=True)
class Day:
    name: str
    tasks: list[Task] = field(default_factory=list)
    start: Anchor | time | None = None

    @classmethod
    def from_factory(cls, func: DayFactory) -> Day:
        return cls(name=func.name, start=getattr(func, "start", None))


class DayFactory:
    """Wraps a user day function ``(ctx) -> list[Task] | Day``."""

    def __init__(
        self,
        func: Callable[..., object],
        *,
        name: str | None = None,
        start: Anchor | time | None = None,
    ) -> None:
        self.func = func
        self.name = name or getattr(func, "__name__", "day") or "day"
        self.start = start
        self.__name__ = self.name  # type: ignore[attr-defined]
        self.__qualname__ = self.name  # type: ignore[attr-defined]

    def __call__(self, ctx: Any) -> object:
        return self.func(ctx)


def day(
    arg: Any = None,
    *tasks: Task,
    name: str | None = None,
    start: Anchor | time | None = None,
):
    """Build a ``Day``, or decorate a function as a day factory.

    Builder::

        day("Weekday", task(...), task(...), start=morning)

    Decorator (returns a :class:`DayFactory`). The day's ``start`` anchor can
    be given in the decorator itself instead of pinning the first task::

        @day
        def workday(ctx):
            return [task(...), ...]

        @day(name="Mein Tag", start=time(9, 0))
        def strukturtag(ctx):
            return [task(...), ...]  # chains on from 09:00
    """
    if arg is None and not tasks:
        # supports ``@day(name="Titel")`` and ``@day(start=...)`` decorator forms
        def decorate(factory: Callable[..., object]) -> DayFactory:
            return DayFactory(
                factory,
                name=name or getattr(factory, "__name__", None) or "day",
                start=start,
            )

        return decorate
    if callable(arg) and not tasks:
        factory = arg
        return DayFactory(
            factory,
            name=name or getattr(factory, "__name__", None) or "day",
            start=start,
        )
    if isinstance(arg, str):
        return Day(name=arg, tasks=list(tasks), start=start)
    raise PlanError("day() expects a name + tasks, or a single callable to decorate")


def week(**days: Any) -> Week:
    """A week: one day factory per weekday (``mon`` ... ``sun``)."""
    normalized: dict[str, Any] = {}
    for key, value in days.items():
        key_lower = key.strip().lower()
        if key_lower not in WEEKDAY_KEYS:
            raise PlanError(f"Unknown weekday {key!r} (use one of {', '.join(WEEKDAY_NAMES)})")
        normalized[key_lower] = value
    return Week(days=normalized)


@dataclass(slots=True)
class Week:
    days: dict[str, Any] = field(default_factory=dict)  # mon..sun -> DayFactory | Day | list

    def get(self, weekday_index: int) -> Any | None:
        return self.days.get(WEEKDAY_NAMES[weekday_index])


@dataclass(slots=True)
class Month:
    """A repeating unit of weeks (the pattern for one month)."""

    weeks: list[Week]

    def week_for(self, index_in_unit: int) -> Week | None:
        if not self.weeks:
            return None
        return self.weeks[index_in_unit % len(self.weeks)]


def month(*weeks: Week) -> Month:
    """Bundle weeks into one repeating month pattern."""
    return Month(weeks=list(weeks))


class CalendarPattern:
    """A plan as a single function: ``(date) -> day_factory | None``.

    ``None`` means a free day.  This is the ultimate escape hatch - the whole
    year can be *one* function that decides, per calendar date, what kind of
    day to run.
    """

    def __init__(self, func: Callable[[Any], Any | None]) -> None:
        self.func = func
        self.__name__ = getattr(func, "__name__", "calendar")  # type: ignore[attr-defined]

    def __call__(self, calendar_date: Any) -> Any | None:
        return self.func(calendar_date)


def calendar(_func: Callable[[Any], Any | None] | None = None) -> Any:
    """Decorate a ``(date) -> day_factory | None`` function as a whole-plan pattern.

    Use it to program a whole semester/year/life as one function::

        @calendar
        def lebensjahr(today):
            if is_ramadan(today):
                return ramadan_day
            if today.weekday() == 5:
                return weekend_day
            return work_day
    """
    if _func is None:
        raise PlanError("calendar() only works as a decorator: @calendar")
    return CalendarPattern(_func)


#: Convenient end-of-day anchor for "until next day start" tasks.
next_day_start = midnight
