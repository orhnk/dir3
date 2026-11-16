"""The planner engine: expands a month/week/day pattern into concrete days.

The design goal is *not too strict*: a day is scheduled softly.

* anchored tasks (``start``/``until``) pin moments in the day;
* chained tasks flow after the previous one and may be shifted naturally;
* flexible tasks can be shrunk when the day overflows;
* leftover time is reported as *TO PLAN* slack instead of being force-filled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from .alarm import apply_wake_alarms
from .anchor import DerivedAnchor, NextEventAnchor, next_event
from .config import Dir3Config
from .context import DayContext
from .core import (
    WEEKDAY_NAMES,
    CalendarPattern,
    Day,
    DayFactory,
    Month,
    PlanError,
    Task,
    Todo,
    Week,
)
from .services import Services
from .timeutils import combine, format_time

ZERO = timedelta(0)
_DAY = timedelta(days=1)
#: pinned starts before this hour of day are candidate "post-midnight" moments
_DAWN_LIMIT = time(hour=4, minute=30)


@dataclass(slots=True)
class PlannedEvent:
    name: str
    start: datetime | None
    end: datetime | None
    skipped: bool = False
    open_: bool = False
    trimmed: timedelta = ZERO
    flexible: bool = True
    anchored: bool = False
    #: the event intentionally runs into the next calendar day
    #: (``until=next_event``, e.g. sleep until tomorrow's first event)
    carry: bool = False
    #: places for a travel event (used by whereabouts)
    origin: str | None = None
    destination: str | None = None
    #: Google Tasks list this event is mirrored into (None = event only)
    task_list: str | None = None
    #: where this event's own Google Task sits relative to the event
    todo_position: str | None = None
    #: additional Google Tasks attached to this event (no calendar events)
    todos: tuple[Todo, ...] = ()
    #: alarms the phone rings for this event
    alarms: tuple = ()
    #: explicit "no automatic alarm" marker
    alarm_opt_out: bool = False

    @property
    def active(self) -> bool:
        return not self.skipped and self.start is not None and self.end is not None


@dataclass(slots=True)
class PlanDay:
    date: date
    name: str
    events: list[PlannedEvent] = field(default_factory=list)
    slack: timedelta = ZERO
    overflow: timedelta = ZERO
    active: bool = True

    @property
    def skipped_count(self) -> int:
        return sum(1 for ev in self.events if ev.skipped)

    @property
    def open_count(self) -> int:
        return sum(1 for ev in self.events if ev.open_ and not ev.skipped)

    @property
    def trimmed_total(self) -> timedelta:
        return sum((ev.trimmed for ev in self.events), ZERO)


@dataclass(slots=True)
class Plan:
    title: str
    start: date
    days: list[PlanDay] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        total_slack = sum((day.slack for day in self.days), ZERO)
        total_over = sum((day.overflow for day in self.days), ZERO)
        planned_days = [d for d in self.days if d.active]
        return {
            "days": len(self.days),
            "planned_days": len(planned_days),
            "total_slack": total_slack,
            "total_overflow": total_over,
            "trimmed": sum(len([ev for ev in d.events if ev.trimmed > ZERO]) for d in planned_days),
        }


def compile_pattern(
    pattern: Month | Week | DayFactory | Any,
    *,
    until: timedelta | int | None = None,
    days: int | None = None,
    start_date: date | None = None,
    title: str | None = None,
    overrides: dict[str, Any] | None = None,
    services: Services | None = None,
    config: Dir3Config | None = None,
) -> Plan:
    """Compile a pattern into a concrete plan of ``days``.

    * ``pattern`` - a :class:`Month`, :class:`Week`, day factory or day callable;
    * ``until`` / ``days`` - horizon (``until=timedelta(days=360)``);
    * ``overrides`` - ``{"YYYY-MM-DD": day_factory}`}` - per-date exceptions;
    * ``services``/``config`` - optional, for tests / custom wiring.
    """
    total_days = _resolve_horizon(until, days)
    if total_days <= 0:
        raise PlanError("compilation horizon must be positive")
    services = services or Services(config=config)
    start = start_date or _plan_today(services)

    unit = _normalize_unit(pattern)
    day_overrides = dict(overrides or {})

    plan = Plan(title=title or "dir3 Plan", start=start)
    # Compile one day beyond the horizon: the last planned day then still
    # knows the first event of its successor, so ``until=next_event`` does not
    # fall back to midnight on that day.  The extra day is dropped afterwards.
    plan.days = [None] * (total_days + 1)
    # Compile from the last day backwards: each day learns its successor, so
    # ``until=next_event`` can reach across midnight into the next active day.
    for index in range(total_days, -1, -1):
        calendar = start + timedelta(days=index)
        day_def = _day_for(calendar, index, unit, day_overrides)
        if day_def is None:
            plan.days[index] = PlanDay(date=calendar, name="———", active=False)
            continue
        ctx = DayContext(plan_date=calendar, services=services)
        ctx._next_event_handle = _Lookahead(plan, index)
        day_model = _invoke_day(day_def, ctx)
        plan.days[index] = _compile_day(day_model, ctx)
        ctx._resolve_cache.clear()
    plan.days = plan.days[:total_days]
    return plan


def _plan_today(services: Services | None) -> date:
    """Today in the *plan's* timezone, not the machine's (portable planning).

    A developer whose machine dwells in another zone (server, CI, travel)
    still gets the correct day start for the planned location.  Falls back to
    the machine date when no location/zone can be resolved.
    """
    tz = None
    if services is not None:
        try:
            tz = services.location.tzinfo
        except Exception:  # pragma: no cover - no location resolvable
            tz = None
    try:
        now = datetime.now(tz) if tz is not None else datetime.now()
    except (ValueError, TypeError):  # pragma: no cover - defensive
        return date.today()
    return now.date()


def _resolve_horizon(until: timedelta | int | None, days: int | None) -> int:
    if days is not None:
        return int(days)
    if until is None:
        return 30
    if isinstance(until, timedelta):
        return max(1, int(until.total_seconds() // 86400))
    return int(until)


class _Lookahead:
    """Lets a day read its successor while being compiled.

    ``until=next_event`` resolves to the start of the first concrete event of
    the next *active* calendar day (free days are skipped), or ``None`` when
    the horizon ends.
    """

    def __init__(self, plan: Plan, index: int) -> None:
        self._plan = plan
        self._index = index

    def next_event_moment(self) -> datetime | None:
        """The absolute start of the first concrete event of the next active
        day, or ``None`` when the horizon ends."""
        for pday in self._plan.days[self._index + 1 :]:
            if pday is None or not pday.active:
                continue
            for event in pday.events:
                if event.active and event.start is not None:
                    return event.start
            return None
        return None

    def next_event_start(self) -> time | None:
        moment = self.next_event_moment()
        return moment.time() if moment is not None else None


def _next_event_based(until: object) -> bool:
    """True when ``until`` is ``next_event`` or a derived shift of it."""
    if until is next_event:
        return True
    return isinstance(until, DerivedAnchor) and isinstance(until.base, NextEventAnchor)


def _normalize_unit(pattern: Any) -> list[Week] | CalendarPattern:
    if isinstance(pattern, CalendarPattern):
        return pattern
    if isinstance(pattern, Month):
        if not pattern.weeks:
            raise PlanError("month() given no weeks")
        return list(pattern.weeks)
    if isinstance(pattern, Week):
        return [pattern]
    # a bare day factory / callable: repeat it on every weekday of the week
    if isinstance(pattern, (Day, DayFactory)) or callable(pattern):
        return [Week(days={name: pattern for name in WEEKDAY_NAMES})]
    raise PlanError(f"Cannot compile pattern {pattern!r}")


def _day_for(
    calendar: date, index: int, unit: Any, overrides: dict[str, Any]
):
    iso = calendar.isoformat()
    if iso in overrides:
        return overrides[iso]
    if isinstance(unit, CalendarPattern):
        return unit(calendar)
    week_index = (index // 7) % len(unit)
    week = unit[week_index]
    return week.get(calendar.weekday())


def _invoke_day(day_def: Any, ctx: DayContext) -> Day:
    result = day_def(ctx) if callable(day_def) else day_def
    if isinstance(result, Day):
        return result
    if isinstance(result, (list, tuple)):
        tasks = list(result)
        for item in tasks:
            if not isinstance(item, Task):
                raise PlanError(f"Day returned non-task element {item!r}")
        base_name = getattr(day_def, "name", None) or type(day_def).__name__
        return Day(
            name=str(base_name),
            tasks=tasks,
            start=getattr(day_def, "start", None),
        )
    if isinstance(day_def, Day):
        return day_def
    raise PlanError(f"Cannot use {day_def!r} as a day definition")


def _compile_day(day: Day, ctx: DayContext) -> PlanDay:
    cursor: datetime | None = None
    end_of_day = combine(ctx.plan_date + _DAY, time(hour=0, minute=0))
    events: list[PlannedEvent] = []
    anchored_end: datetime | None = None

    for item in day.tasks:
        if item.unless and any(pred(ctx) for pred in item.unless):
            events.append(
                PlannedEvent(
                    name=item.name,
                    start=None,
                    end=None,
                    skipped=True,
                    task_list=item.task_list,
                    todo_position=item.todo_position,
                    todos=item.todos,
                    alarm_opt_out=item.alarm_opt_out,
                )
            )
            continue

        start_dt = _resolve_start(item, day, ctx, cursor)
        if start_dt is None and cursor is None:
            raise PlanError(
                f"'{day.name}': task '{item.name}' (or the day) needs a start anchor"
            )
        if start_dt is None:
            start_dt = cursor
            if item.space:
                start_dt += item.space

        anchored = item.anchored
        if anchored and anchored_end is not None and start_dt < anchored_end:
            # A pinned start well before an earlier pinned end is a
            # post-midnight moment (Berlin nights in June, Tahajjud, night
            # shift): roll it into the next calendar day instead of crashing.
            gap = anchored_end - start_dt
            spans_a_full_block = gap >= timedelta(hours=20)
            deep_night = start_dt.time() < _DAWN_LIMIT and gap >= timedelta(hours=12)
            if spans_a_full_block or deep_night:
                start_dt += _DAY
            elif not item.overlap:
                raise PlanError(
                    f"'{day.name}': '{item.name}' at {format_time(start_dt.time())} "
                    f"overlaps a pinned block that ends at {format_time(anchored_end.time())}"
                )

        end_dt, open_task, via_next_event = _resolve_end(item, ctx, start_dt, end_of_day)

        carry = via_next_event and end_dt is not None and end_dt.date() > ctx.plan_date

        if anchored and end_dt is not None and (anchored_end is None or end_dt > anchored_end):
            anchored_end = end_dt  # for tasks without duration, use their span

        event = PlannedEvent(
            name=item.name,
            start=start_dt,
            end=end_dt,
            open_=open_task,
            flexible=item.flex,
            anchored=anchored,
            carry=carry,
            origin=item.origin,
            destination=item.destination,
            task_list=item.task_list,
            todo_position=item.todo_position,
            todos=item.todos,
            alarms=item.alarms,
            alarm_opt_out=item.alarm_opt_out,
        )
        events.append(event)
        if end_dt is not None:
            cursor = end_dt

    pday = _balance(PlanDay(date=ctx.plan_date, name=day.name, events=events), cursor, end_of_day)
    settings = getattr(getattr(ctx, "services", None), "config", None)
    alarm_settings = getattr(settings, "alarms", None)
    if alarm_settings is not None and alarm_settings.enabled:
        apply_wake_alarms(pday.events, alarm_settings.resolved_policy())
    return pday


def _resolve_start(
    item: Task, day: Day, ctx: DayContext, cursor: datetime | None
) -> datetime | None:
    if item.start is not None:
        value = ctx.resolve(item.start)
        if value is not None:
            return combine(ctx.plan_date, value)
    # the day may provide its own start (``@day(start=...)``) as a fallback
    # pinned before any task chains
    if cursor is None and day.start is not None:
        value = ctx.resolve(day.start)
        if value is not None:
            return combine(ctx.plan_date, value)
    return None


def _resolve_end(
    item: Task,
    ctx: DayContext,
    start_dt: datetime,
    end_of_day: datetime,
) -> tuple[datetime | None, bool, bool]:
    """Resolve the task's end. Returns ``(end, open_, from_next_event)``.

    ``from_next_event`` is True when the end came from the ``until=next_event``
    look-ahead (absolute date, so free days in between are honored).
    """
    if _next_event_based(item.until):
        handle = getattr(ctx, "_next_event_handle", None)
        if handle is not None:
            target = handle.next_event_moment()
            if target is not None:
                delta = (
                    item.until.delta  # type: ignore[union-attr]
                    if isinstance(item.until, DerivedAnchor)
                    else ZERO
                )
                end_dt = target + delta
                if item.duration is not None and end_dt - start_dt < item.duration:
                    raise PlanError(
                        f"'{item.name}': duration {item.duration!s} does not fit "
                        "before its 'next_event'"
                    )
                return end_dt, False, True
    if item.until is not None:
        value = ctx.resolve(item.until)
        if value is not None:
            end_dt = combine(ctx.plan_date, value)
            if end_dt <= start_dt:
                end_dt += _DAY
            if item.duration is not None and end_dt - start_dt < item.duration:
                raise PlanError(
                    f"'{item.name}': duration {item.duration!s} does not fit before its 'until'"
                )
            return end_dt, False, False
    if item.duration is not None:
        return start_dt + item.duration, False, False
    if item.flex:
        return end_of_day, True, False
    raise PlanError(f"Task '{item.name}' has neither until, duration nor flex=True")


def _balance(pday: PlanDay, cursor: datetime | None, end_of_day: datetime) -> PlanDay:
    """Compensate overflow by shrinking flexible tasks; report slack otherwise."""
    if cursor is None:
        pday.active = False
        return pday
    if cursor > end_of_day:
        if pday.events and pday.events[-1].carry:
            # a carried event (e.g. sleep ``until=next_event``) runs into the
            # next morning on purpose - that is not overflow, and the night
            # belongs to the plan.
            pday.slack = ZERO
        else:
            needed = cursor - end_of_day
            for event in reversed(pday.events):
                if needed <= ZERO:
                    break
                if not event.active or event.open_ or not event.flexible or event.anchored:
                    continue
                span = event.end - event.start
                if span <= ZERO:
                    continue
                trim = min(needed, span)
                event.end -= trim
                event.trimmed += trim
                needed -= trim
            pday.overflow = max(needed, ZERO)
    elif cursor < end_of_day:
        pday.slack = end_of_day - cursor
    return pday
