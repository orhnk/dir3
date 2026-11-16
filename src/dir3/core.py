"""dir3 DSL: ``task``, ``day``, ``week``, ``month`` and their data models.

You program a day by returning a list of tasks from a function that receives the
per-day context.  ``week`` and ``month`` assemble patterns which ``compile``
expands into a concrete calendar.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import time, timedelta
from typing import TYPE_CHECKING, Any

from .alarm import Alarm, coerce_alarm
from .anchor import Anchor, midnight
from .timeutils import subtract_time

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_KEYS = frozenset(WEEKDAY_NAMES)


class PlanError(ValueError):
    """A plan/definition error: wrong day, missing anchor, overflow, ..."""


#: A predicate used in ``unless``: (ctx) -> True means "skip today".
Unless = Callable[[Any], bool]

#: Where an attached Google Task sits relative to its event.
TODO_POSITIONS = frozenset({"start", "end"})


@dataclass(frozen=True, slots=True)
class Todo:
    """A Google Task attached to an event (no separate calendar event).

    ``todo_position`` chooses whether the task is due at the event's start or
    end.  Google Tasks stores only a date, so the time remains in the notes.
    """

    title: str
    todo_position: str = "end"


@dataclass(slots=True)
class Task:
    name: str
    start: Anchor | time | None = None
    until: Anchor | time | None = None
    duration: timedelta | None = None
    space: timedelta | None = None
    unless: tuple[Unless, ...] = ()
    flex: bool = True
    overlap: bool = False
    #: place names for a travel task (used by whereabouts)
    origin: str | None = None
    destination: str | None = None
    #: Google Tasks list this task is mirrored into (None = event only)
    task_list: str | None = None
    #: where this task's own Google Task sits relative to the event
    todo_position: str | None = None
    #: extra Google Tasks attached to this event (no calendar events)
    todos: tuple[Todo, ...] = ()
    #: alarms the phone should ring for this event
    alarms: tuple[Alarm, ...] = ()
    #: explicitly silent - suppresses automatic wake-up alarms
    alarm_opt_out: bool = False

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
        if self.task_list is not None:
            bits.append(f"task_list={self.task_list!r}")
        if self.todo_position is not None:
            bits.append(f"todo_position={self.todo_position!r}")
        if self.todos:
            bits.append(f"todos={self.todos!r}")
        if self.alarms:
            bits.append(f"alarms={self.alarms!r}")
        if self.alarm_opt_out:
            bits.append("alarm=False")
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
    overlap: bool = False,
    origin: str | None = None,
    destination: str | None = None,
    task_list: str | None = None,
    todo_position: str | None = None,
    todos: Todo | str | Iterable[Todo | str] | None = None,
    alarm: Alarm | str | bool | int | float | timedelta | Iterable | None = None,
) -> Task:
    """Declare one task inside a day.

    * ``start``  - an anchor (or plain time) that starts the task;
    * ``until``  - an anchor (or time) that ends it (wraps across midnight);
    * ``duration`` - how long it lasts when no ``until`` is given;
    * ``space``  - a gap before the task (used when chaining);
    * ``unless`` - a predicate or tuple of predicates skipping the task for a day;
    * ``flex``   - whether the compiler may shrink this task to absorb overflow;
    * ``overlap`` - allow this pinned task to overlap earlier pinned blocks;
    * ``origin`` / ``destination`` - places for a travel task (whereabouts);
    * ``task_list`` - mirror this task into a Google Tasks list (hybrid:
      the timed calendar event stays as usual);
    * ``todo_position`` - for the mirrored task: ``"start"`` or ``"end"``
      of the event (Google Tasks keeps only the date, the time is in the
      notes);
    * ``todos`` - additional Google Tasks attached to this event.  They do
      not create calendar events and land in the same ``task_list``.  Without
      ``todo_position`` the event is only their container, so no task is
      created for the event name itself.
    * ``alarm`` - one or more :class:`~dir3.alarm.Alarm` specs; ``True`` /
      ``"start"`` uses the default alarm, ``"end"`` rings at the end,
      ``"-10m"`` ten minutes before the start, ``False`` silences the event
      even when the wake-up policy would ring it.
    """
    if not name.strip():
        raise PlanError("task() needs a name")

    duration_td = (
        duration if isinstance(duration, timedelta) or duration is None else _as_duration(duration)
    )
    space_td = space if isinstance(space, timedelta) or space is None else _as_duration(space)

    predicates: tuple[Unless, ...] = ()
    if unless is not None:
        predicates = unless if isinstance(unless, tuple) else (unless,)

    if until is None and duration_td is None and not flex:
        raise PlanError(f"task '{name}' needs an until anchor, a duration, or flex=True")

    task_list_name = task_list.strip() if isinstance(task_list, str) else None
    if task_list_name == "":
        raise PlanError(f"task '{name}': task_list must not be empty")

    alarms = coerce_alarm(alarm)
    position = _normalize_todo_position(todo_position, name)
    attached = _normalize_todos(todos, name)
    if (position is not None or attached) and task_list_name is None:
        raise PlanError(
            f"task '{name}': todo_position/todos need a task_list"
        )

    return Task(
        name=name.strip(),
        start=start,
        until=until,
        duration=duration_td,
        space=space_td,
        unless=predicates,
        flex=flex,
        overlap=overlap,
        origin=origin,
        destination=destination,
        task_list=task_list_name,
        todo_position=position,
        todos=attached,
        alarms=alarms or (),
        alarm_opt_out=alarms is None,
    )


def going(event: Task, way: Task) -> list[Task]:
    """Couple a travel task to an event: the way ends when the event starts."""
    if event.start is None or not isinstance(event.start, time):
        raise ValueError("going() braucht ein Event mit Uhrzeit")
    if way.duration is None:
        raise ValueError("going() braucht einen Weg mit Dauer")
    return [replace(way, start=subtract_time(event.start, way.duration)), event]


def _as_duration(value: str) -> timedelta:
    from .timeutils import parse_duration

    return parse_duration(value)


def _normalize_todo_position(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    position = str(value).strip().lower()
    if position not in TODO_POSITIONS:
        raise PlanError(
            f"task '{name}': todo_position must be 'start' or 'end', got {value!r}"
        )
    return position


def _normalize_todos(
    value: Todo | str | Iterable[Todo | str] | None, name: str
) -> tuple[Todo, ...]:
    if value is None:
        return ()
    items = (value,) if isinstance(value, (Todo, str)) else tuple(value)
    todos: list[Todo] = []
    for item in items:
        if isinstance(item, str):
            title = item.strip()
            todo = Todo(title=title, todo_position="end")
        elif isinstance(item, Todo):
            title = item.title.strip()
            todo = replace(item, title=title)
        else:
            raise PlanError(
                f"task '{name}': todos must contain Todo or str, got {item!r}"
            )
        if not title:
            raise PlanError(f"task '{name}': todo title must not be empty")
        _normalize_todo_position(todo.todo_position, name)
        todos.append(todo)
    return tuple(todos)


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
