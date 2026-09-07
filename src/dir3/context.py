"""The per-day context every user function receives.

Instead of hidden global state, dir3 hands every day/anchor function a fresh
:class:`DayContext` for the concrete plan day.  All anchor resolutions and
service lookups funnel through the context, which caches per day - so the whole
compilation is deterministic for a fixed date and location.

Example::

    @day
    def workday(ctx):
        return [
            task("Job", until=work_end - timedelta(hours=1)),
        ]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from typing import TYPE_CHECKING

from .anchor import Anchor, FixedAnchor, FunctionAnchor, NamedAnchor, midnight

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .services import Services


class PrayerGate:
    """Anchors for the five prayers (+ sunrise). Resolve through the context."""

    def __init__(self, services: Services) -> None:
        self._services = services

    def _schedule(self, ctx: DayContext):
        return self._services.prayer.get(ctx.plan_date, ctx.location)

    @property
    def fajr(self) -> Anchor:
        return NamedAnchor("prayer.fajr", lambda ctx: self._schedule(ctx).fajr)

    @property
    def sunrise(self) -> Anchor:
        return NamedAnchor("prayer.sunrise", lambda ctx: self._schedule(ctx).sunrise)

    @property
    def dhuhr(self) -> Anchor:
        return NamedAnchor("prayer.dhuhr", lambda ctx: self._schedule(ctx).dhuhr)

    @property
    def asr(self) -> Anchor:
        return NamedAnchor("prayer.asr", lambda ctx: self._schedule(ctx).asr)

    @property
    def maghrib(self) -> Anchor:
        return NamedAnchor("prayer.maghrib", lambda ctx: self._schedule(ctx).maghrib)

    @property
    def isha(self) -> Anchor:
        return NamedAnchor("prayer.isha", lambda ctx: self._schedule(ctx).isha)

    def schedule(self, ctx: DayContext):
        """The raw schedule for the given day (a PrayerSchedule)."""
        return self._schedule(ctx)


class SunGate:
    """Daylight anchors (sunrise / sunset), delegated to the prayer calculator."""

    def __init__(self, services: Services) -> None:
        self._services = services

    def _times(self, ctx: DayContext):
        return self._services.sun.get(ctx.plan_date, ctx.location)

    @property
    def sunrise(self) -> Anchor:
        return NamedAnchor("sun.sunrise", lambda ctx: self._times(ctx).sunrise)

    @property
    def sunset(self) -> Anchor:
        return NamedAnchor("sun.sunset", lambda ctx: self._times(ctx).sunset)


@dataclass(slots=True, init=False)
class DayContext:
    plan_date: date
    services: Services
    city: str | None = None
    _resolve_cache: dict[object, time | None] = field(default_factory=dict)
    #: engine-injected look-ahead for ``until=next_event`` (see engine.py)
    _next_event_handle: object | None = None

    def __init__(self, plan_date: date, services: Services) -> None:
        self.plan_date = plan_date
        self.services = services
        self.city = services.location.city or None
        self._resolve_cache = {}
        self._next_event_handle = None

    #: convenient access to prayer anchors and the raw schedule
    @property
    def prayer(self) -> PrayerGate:
        return PrayerGate(self.services)

    #: convenient access to daylight anchors
    @property
    def sun(self) -> SunGate:
        return SunGate(self.services)

    @property
    def weather(self):
        return self.services.weather

    #: the resolved location for the plan day
    @property
    def location(self):
        return self.services.location

    #: today's plan date, mirrors ``plan_date`` for short-form access in anchors
    @property
    def date(self) -> date:
        return self.plan_date

    def resolve(self, value: Anchor | time | None) -> time | None:
        """Resolve an anchor (or plain time) for this day, cached."""
        if value is None:
            return None
        if isinstance(value, time):
            return value
        if isinstance(value, Anchor):
            key = self._cache_key(value)
            if key in self._resolve_cache:
                return self._resolve_cache[key]
            resolved = value.resolve(self)
            self._resolve_cache[key] = resolved
            return resolved
        if callable(value):
            wrapped = FunctionAnchor(value)
            return self.resolve(wrapped)
        raise TypeError(f"Cannot resolve {value!r} as a time anchor")

    @staticmethod
    def _cache_key(anchor: Anchor) -> object:
        if isinstance(anchor, (NamedAnchor, FixedAnchor)) and anchor.name:
            return ("name", anchor.name)
        return ("id", id(anchor))

    #: end-of-day boundary anchor (start of the following day, 00:00)
    @property
    def midnight(self) -> Anchor:
        return midnight

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DayContext({self.plan_date.isoformat()})"
