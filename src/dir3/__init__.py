"""dir3 - das Leben zeitlich programmieren, weich und anker-basiert.

Public API::

    from dir3 import anchor, task, day, week, month, compile, prayer, sun,
                      midnight, next_day_start

Declare *your own* time anchors with ``@anchor``, build days as functions
receiving a per-day context, bundle weeks/months and compile softly.
"""
from __future__ import annotations

from .anchor import (
    Anchor,
    DerivedAnchor,
    FixedAnchor,
    FunctionAnchor,
    NamedAnchor,
    all_anchors,
    anchor,
    midnight,
    named_anchor,
    next_event,
    register,
)
from .config import Dir3Config, LocationSettings, PrayerSettings
from .context import DayContext, PrayerGate, SunGate
from .core import (
    CalendarPattern,
    Day,
    DayFactory,
    Month,
    PlanError,
    Task,
    Week,
    calendar,
    day,
    month,
    next_day_start,
    task,
    week,
)
from .engine import Plan, PlanDay, PlannedEvent
from .engine import compile_pattern as compile
from .render import render_plan
from .services import Services
from .services.weather import rains
from .timeutils import (
    add_time,
    format_duration,
    format_time,
    parse_duration,
    parse_hhmm,
    subtract_time,
)


class _PrayerProviderProxy:
    """Module-level prayer anchors usable inside day definitions.

    ``prayer.dhuhr`` is an :class:`Anchor`; ``ctx.prayer.dhuhr`` inside a day
    function is a fresh anchor too. Both resolve through the day context, so
    they are per-day and cached.
    """

    def __getattr__(self, name: str) -> Anchor:
        allowed = {"fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"}
        if name not in allowed:
            raise AttributeError(f"Unknown prayer anchor '{name}'")
        from .anchor import NamedAnchor

        return NamedAnchor(f"prayer.{name}", _prayer_resolver(name))


class _SunProviderProxy:
    def __getattr__(self, name: str) -> Anchor:
        allowed = {"sunrise", "sunset"}
        if name not in allowed:
            raise AttributeError(f"Unknown sun anchor '{name}'")
        from .anchor import NamedAnchor

        return NamedAnchor(f"sun.{name}", _sun_resolver(name))


def _prayer_resolver(name: str):
    def resolve(ctx: DayContext):
        schedule = ctx.prayer.schedule(ctx)
        return getattr(schedule, name)

    return resolve


def _sun_resolver(name: str):
    def resolve(ctx: DayContext):
        times = ctx.sun._times(ctx)  # noqa: SLF001 - internal reuse in same package
        return getattr(times, name)

    return resolve


#: The module-level prayer anchor group (``prayer.fajr``, ``prayer.dhuhr``, ...).
prayer = _PrayerProviderProxy()
#: The module-level sun anchor group (``sun.sunrise``, ``sun.sunset``).
sun = _SunProviderProxy()

__all__ = [
    "Anchor",
    "DerivedAnchor",
    "FixedAnchor",
    "FunctionAnchor",
    "NamedAnchor",
    "DayContext",
    "PrayerGate",
    "SunGate",
    "PlanError",
    "Task",
    "Day",
    "DayFactory",
    "Week",
    "Month",
    "CalendarPattern",
    "Plan",
    "PlanDay",
    "PlannedEvent",
    "Services",
    "Dir3Config",
    "LocationSettings",
    "PrayerSettings",
    "rains",
    "anchor",
    "register",
    "all_anchors",
    "named_anchor",
    "next_event",
    "task",
    "day",
    "week",
    "month",
    "calendar",
    "compile",
    "prayer",
    "sun",
    "midnight",
    "next_day_start",
    "render_plan",
    "parse_hhmm",
    "parse_duration",
    "format_time",
    "format_duration",
    "add_time",
    "subtract_time",
]
