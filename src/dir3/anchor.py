"""Anchors - the heart of dir3.

Anything that can pin a moment in the day is an :class:`Anchor`.  You may use
the built-ins (``prayer.*``, ``sun.*``, ``midnight``, ...) or declare *your own*
anchor simply by writing a function and decorating it::

    @anchor
    def work_end(ctx):
        return ctx.resolve(business.end) - OTHER_OFFSET ...

An anchor resolves to ``datetime.time`` for a given plan day - or to ``None``
if it has no meaning on that day (the scheduler then falls back to a ``duration``
or leaves the event flexible).

Anchors form a tiny algebra: ``work_end - timedelta(hours=1)`` returns a
derived anchor, and ``time + time`` is deliberately impossible.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import time, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import DayContext

#: An anchor resolves to a time for a given day, or None if inactive.
AnchorResolver = Callable[["DayContext"], time | None]


def _plain_time(value: Any) -> time | None:
    """Coerce ``time`` values; everything else is left to the caller."""
    return value if isinstance(value, time) else None


class Anchor:
    """Base class for every time anchor."""

    __slots__ = ("name",)

    def __init__(self, name: str | None = None) -> None:
        self.name = name

    def resolve(self, ctx: DayContext) -> time | None:  # pragma: no cover - abstract
        raise NotImplementedError

    def describe(self) -> str:
        return self.name or type(self).__name__

    # --- algebra ---------------------------------------------------------
    def __add__(self, other: object) -> Anchor:
        if isinstance(other, timedelta):
            return DerivedAnchor(self, other)
        return NotImplemented

    def __radd__(self, other: object) -> Anchor:
        if isinstance(other, timedelta):
            return DerivedAnchor(self, other)
        return NotImplemented

    def __sub__(self, other: object) -> Anchor:
        if isinstance(other, timedelta):
            return DerivedAnchor(self, -other)
        return NotImplemented

    def __rsub__(self, other: object) -> Anchor:
        # timedelta - anchor has no useful meaning; keep it impossible.
        return NotImplemented

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}({self.describe()!r})"


class FunctionAnchor(Anchor):
    """An anchor backed by a plain user function ``(ctx) -> time | None``."""

    __slots__ = ("func",)

    def __init__(self, func: AnchorResolver, *, name: str | None = None) -> None:
        super().__init__(name=name or getattr(func, "__name__", None) or "anchor")
        self.func = func

    def resolve(self, ctx: DayContext) -> time | None:
        result = self.func(ctx)
        if result is None or isinstance(result, time):
            return result
        raise TypeError(
            f"Anchor {self.describe()!r} returned {type(result).__name__}, expected time or None"
        )


class FixedAnchor(Anchor):
    """A constant point in time, e.g. ``midnight`` for the plan day's end."""

    __slots__ = ("_time",)

    def __init__(self, moment: time, *, name: str | None = None) -> None:
        super().__init__(name=name)
        self._time = moment

    def resolve(self, ctx: DayContext) -> time | None:
        return self._time


class NamedAnchor(Anchor):
    """An anchor resolved through the day context's services (e.g. ``prayer.fajr``).

    The resolver receives the context so the value is looked up once per day and
    kept deterministic through the context cache.
    """

    __slots__ = ("resolver",)

    def __init__(self, name: str, resolver: AnchorResolver) -> None:
        super().__init__(name=name)
        self.resolver = resolver

    def resolve(self, ctx: DayContext) -> time | None:
        return self.resolver(ctx)


@dataclass(frozen=True, slots=True)
class DerivedAnchor(Anchor):
    """``base + delta`` - a shifted anchor, wrapped modulo 24h."""

    base: Anchor
    delta: timedelta

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", f"{self.base.describe()} {self._sign()}")

    def _sign(self) -> str:
        total = int(self.delta.total_seconds())
        if total >= 0:
            return f"+{self.delta!s}"
        return str(self.delta)

    def resolve(self, ctx: DayContext) -> time | None:
        base_value = ctx.resolve(self.base)
        if base_value is None:
            return None
        from .timeutils import add_time

        return add_time(base_value, self.delta)

    def describe(self) -> str:
        return f"{self.base.describe()} {self._sign()}"


class NextEventAnchor(Anchor):
    """``until=next_event``: the start of the next concrete event.

    Resolves through the day context's look-ahead handle to the start time of
    the first event of the next *active* calendar day (free days are skipped).
    Returns ``None`` when no successor exists - the task then falls back to a
    duration or stays open until the day's end.
    """

    __slots__ = ()

    def resolve(self, ctx: DayContext) -> time | None:
        handle = getattr(ctx, "_next_event_handle", None)
        if handle is None:
            return None
        return handle.next_event_start()


# --- registry --------------------------------------------------------------

_NAMED: dict[str, Anchor] = {}


def register(anchor_value: Anchor, name: str | None = None) -> Anchor:
    if name is not None:
        anchor_value.name = name
    if anchor_value.name:
        _NAMED[anchor_value.name] = anchor_value
    return anchor_value


def named_anchor(name: str) -> Anchor | None:
    return _NAMED.get(name)


def all_anchors() -> dict[str, Anchor]:
    return dict(_NAMED)


def anchor(func: AnchorResolver | Anchor | None = None, *, name: str | None = None):
    """Declare a function as a reusable time anchor.

    Usable as a bare decorator or with a name override::

        @anchor
        def work_end(ctx): ...

        @anchor(name="curfew")
        def home_latest(ctx): ...
    """
    if func is None:
        return lambda f: anchor(f, name=name)

    if isinstance(func, Anchor):
        return register(func, name=name)

    if not callable(func):
        raise TypeError("anchor() expects a callable taking (ctx) -> time | None")

    wrapped = FunctionAnchor(func, name=name or getattr(func, "__name__", None) or "anchor")
    return register(wrapped)


# --- builtin constant anchors ----------------------------------------------

#: End of the plan day: resolves to 00:00, the compiler interprets an
#: `until` at or before the start as wrapping to the next calendar day.
midnight = register(FixedAnchor(time(hour=0, minute=0), name="midnight"), "midnight")

#: ``until=next_event`` - the first event of the next active calendar day.
next_event = register(NextEventAnchor(name="next_event"), "next_event")
