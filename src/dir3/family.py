"""Sıla-i Rahim (صلة الرحم) - a block for maintaining family ties.

The block is deliberately a plain task: it can be placed before a prayer (by
default: directly before Isha) or at any explicit start.  The plan decides
whether it is a one-off visit, a phone call or a recurring family evening.

The plan file owns the weekly placement.  This module only knows *who* is
called, for how long, and how the selected calls fill the block::

    from dir3 import Relative, SilaRahimSettings, sila_rahim_events, under

    settings = SilaRahimSettings(
        relatives=(
            Relative("Anne", 40),
            Relative("Baba", 30),
            Relative("Babanne", 10),
            Relative("Babadede", 5),
        ),
        buffer_minutes=10,
    )
    events = sila_rahim_events(sched, settings, whom=under("Babanne"))

``under("Babanne")`` means every contact after her in the list - the answer is
just a filter, the plan still decides on which day it runs.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import time, timedelta
from typing import TypeAlias

from .core import Task, task
from .timeutils import time_from_minutes, to_minutes


@dataclass(frozen=True, slots=True)
class Relative:
    """A person to call and the average length of that call."""

    name: str
    minutes: int

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        object.__setattr__(self, "name", name)
        if not name:
            raise ValueError("relative name must not be empty")
        if self.minutes <= 0:
            raise ValueError(f"minutes for {name!r} must be positive")


@dataclass(frozen=True, slots=True)
class SilaRahimSettings:
    """Duration, title, softness and the optional contact list.

    ``minutes`` is the fallback length for a generic block.  It also defines
    the distance to Isha when no explicit ``start`` is given.  When
    ``relatives`` is set, :func:`sila_rahim_events` uses each person's own
    ``minutes`` plus ``buffer_minutes`` (for greeting, finding the number,
    saying goodbye).  The default title is the Latin spelling; set
    ``name="صلة الرحم"`` if the Arabic script is wanted on the calendar.
    """

    minutes: int = 60
    name: str = "Sıla-i Rahim"
    flex: bool = False
    relatives: tuple[Relative, ...] = ()
    buffer_minutes: int = 10

    def __post_init__(self) -> None:
        if self.minutes <= 0:
            raise ValueError("minutes must be positive")
        if not self.name:
            raise ValueError("name must not be empty")
        if self.buffer_minutes < 0:
            raise ValueError("buffer_minutes must not be negative")
        relatives = self.relatives
        if isinstance(relatives, dict):
            relatives = tuple(relatives.values())
        if not isinstance(relatives, (tuple, list)):
            raise TypeError("relatives must be a tuple or list of Relative")
        normalized = []
        for item in relatives:
            if isinstance(item, Relative):
                normalized.append(item)
            elif isinstance(item, dict):
                normalized.append(Relative(**item))
            else:
                raise TypeError("relatives must contain Relative objects")
        object.__setattr__(self, "relatives", tuple(normalized))

    def call_minutes(self, relative: Relative) -> int:
        """Length of one call including the buffer."""
        return relative.minutes + self.buffer_minutes


@dataclass(frozen=True, slots=True)
class _After:
    name: str

    def select(self, relatives: Sequence[Relative]) -> list[Relative]:
        names = [relative.name.casefold() for relative in relatives]
        target = self.name.strip().casefold()
        if target not in names:
            raise ValueError(f"unknown relative {self.name!r}")
        return list(relatives[names.index(target) + 1 :])


def under(name: str) -> _After:
    """Select every contact listed *after* ``name`` (list order).

    ``under("Babanne")`` is not a rank or an age: it follows the order in
    ``SilaRahimSettings.relatives``.  The result is a selection object for
    :func:`select_relatives` and :func:`sila_rahim_events`.
    """
    return _After(name)


#: Accepted by ``whom``: a name, an index/range/slice, a tuple of names,
#: ``"random"``, :func:`under`, or a user-written predicate.
Whom: TypeAlias = (
    str | int | range | slice | Sequence[str | int] | _After | Callable[[Relative, int], bool]
)


def select_relatives(
    relatives: Sequence[Relative],
    whom: Whom | None = None,
) -> list[Relative]:
    """Return the contacts selected by ``whom``.

    ``None`` selects everybody.  Supported selectors:

    * a name (``"Anne"``) or a tuple of names,
    * an index (``0``), a range (``range(0, 2)``) or a slice (``slice(0, 2)``),
    * ``"random"`` for one random contact,
    * ``under("Babanne")`` for everybody after her in the list,
    * a callable ``lambda relative, index: ...`` for arbitrary rules.

    Unknown names and out-of-range indices raise ``ValueError`` so a typo in a
    plan does not silently drop a call.
    """
    relatives = tuple(relatives)
    if whom is None:
        return list(relatives)
    if isinstance(whom, _After):
        return whom.select(relatives)
    if isinstance(whom, str):
        if whom.strip().casefold() == "random":
            return [random.choice(relatives)] if relatives else []
        return [_by_name(relatives, whom)]
    if isinstance(whom, bool):
        raise TypeError("whom must not be a bool")
    if isinstance(whom, int):
        return [_by_index(relatives, whom)]
    if isinstance(whom, range):
        return [_by_index(relatives, index) for index in whom]
    if isinstance(whom, slice):
        return list(relatives[whom])
    if isinstance(whom, (tuple, list)):
        if all(isinstance(item, str) for item in whom):
            return [_by_name(relatives, item) for item in whom]
        if all(isinstance(item, int) and not isinstance(item, bool) for item in whom):
            return [_by_index(relatives, item) for item in whom]
        raise TypeError("a whom sequence must contain only names or only indices")
    if callable(whom):
        return [
            relative
            for index, relative in enumerate(relatives)
            if whom(relative, index)
        ]
    raise TypeError(f"unsupported whom selector: {whom!r}")


def _by_name(relatives: Sequence[Relative], name: str) -> Relative:
    target = str(name).strip().casefold()
    for relative in relatives:
        if relative.name.casefold() == target:
            return relative
    matches = [
        relative for relative in relatives if target in relative.name.casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(relative.name for relative in matches)
        raise ValueError(f"ambiguous relative {name!r}: {names}")
    raise ValueError(f"unknown relative {name!r}")


def _by_index(relatives: Sequence[Relative], index: int) -> Relative:
    try:
        return relatives[index]
    except IndexError as exc:
        raise ValueError(
            f"relative index {index} is out of range (0..{len(relatives) - 1})"
        ) from exc


def sila_rahim(
    sched: object,
    settings: SilaRahimSettings | None = None,
    *,
    start: int | time | str | None = None,
) -> tuple[int, Task]:
    """Return ``(minute, task)`` for a generic Sıla-i Rahim block.

    Without ``start`` the block ends at Isha: it begins ``settings.minutes``
    before the Isha time of ``sched``.  ``start`` overrides that and accepts
    minutes since midnight, a ``time`` or ``"HH:MM"``.

    For one event per selected contact use :func:`sila_rahim_events`.

    Example
    -------
    >>> minute, block = sila_rahim(sched)          # 60 min before Isha
    >>> tasks.append(block)
    """
    settings = settings or SilaRahimSettings()
    if start is None:
        isha = getattr(sched, "isha", None)
        if isha is None:
            raise ValueError("sila_rahim() needs sched.isha or an explicit start=")
        begin = to_minutes(isha) - settings.minutes
    elif isinstance(start, int):
        begin = start
    else:
        begin = to_minutes(start)
    return begin, task(
        settings.name,
        start=time_from_minutes(begin),
        duration=timedelta(minutes=settings.minutes),
        flex=settings.flex,
    )


def sila_rahim_events(
    sched: object,
    settings: SilaRahimSettings | None = None,
    *,
    whom: Whom | None = None,
    start: int | time | str | None = None,
    gap_minutes: int = 0,
) -> list[tuple[int, Task]]:
    """Return one ``(minute, task)`` per selected contact.

    The calls run back-to-back in list order, with ``gap_minutes`` between
    them.  Each call lasts ``relative.minutes + settings.buffer_minutes``.
    Without ``start`` the whole sequence ends at Isha, so the first call begins
    early enough to fit every selected contact before the Adhan.

    ``whom`` selects the contacts (see :func:`select_relatives`); ``None``
    means everybody in ``settings.relatives``.  With no relatives configured
    the result is empty - use :func:`sila_rahim` for a generic block.
    """
    settings = settings or SilaRahimSettings()
    if gap_minutes < 0:
        raise ValueError("gap_minutes must not be negative")
    selected = select_relatives(settings.relatives, whom)
    if not selected:
        return []
    durations = [settings.call_minutes(relative) for relative in selected]
    total = sum(durations) + gap_minutes * (len(selected) - 1)
    if start is None:
        isha = getattr(sched, "isha", None)
        if isha is None:
            raise ValueError(
                "sila_rahim_events() needs sched.isha or an explicit start="
            )
        begin = to_minutes(isha) - total
    elif isinstance(start, int):
        begin = start
    else:
        begin = to_minutes(start)

    events: list[tuple[int, Task]] = []
    cursor = begin
    for relative, minutes in zip(selected, durations, strict=True):
        events.append(
            (
                cursor,
                task(
                    f"{settings.name}: {relative.name}",
                    start=time_from_minutes(cursor),
                    duration=timedelta(minutes=minutes),
                    flex=settings.flex,
                ),
            )
        )
        cursor += minutes + gap_minutes
    return events
