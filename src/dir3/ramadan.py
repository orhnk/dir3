"""Reusable Ramadan blocks: Suhoor, Iftar and Tarawih.

The schedule stays anchored to the real prayer times: Suhoor ends at Fajr,
Iftar starts at Maghrib, and Tarawih follows Isha.  Plan files only choose
names and durations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .core import Task, task
from .islamic import is_ramadan
from .timeutils import time_from_minutes, to_minutes


@dataclass(frozen=True, slots=True)
class RamadanSettings:
    """Times and names for the Ramadan meal and night blocks."""

    suhoor_minutes: int = 30
    iftar_delay: int = 0
    iftar_minutes: int = 45
    tarawih_delay: int = 10
    tarawih_minutes: int = 60
    include_suhoor: bool = True
    include_iftar: bool = True
    include_tarawih: bool = True
    suhoor_name: str = "Suhoor"
    iftar_name: str = "Iftar"
    tarawih_name: str = "Tarawih"

    def __post_init__(self) -> None:
        for name in ("suhoor_minutes", "iftar_minutes", "tarawih_minutes"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("iftar_delay", "tarawih_delay"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        for name in ("suhoor_name", "iftar_name", "tarawih_name"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")


def suhoor(
    sched: object,
    settings: RamadanSettings | None = None,
) -> tuple[int, Task]:
    """Suhoor ending at Fajr."""
    settings = settings or RamadanSettings()
    end = to_minutes(getattr(sched, "fajr"))
    start = end - settings.suhoor_minutes
    return start, task(
        settings.suhoor_name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.suhoor_minutes),
        flex=False,
        overlap=True,
    )


def iftar(
    sched: object,
    settings: RamadanSettings | None = None,
) -> tuple[int, Task]:
    """Iftar beginning at Maghrib (plus an optional delay)."""
    settings = settings or RamadanSettings()
    start = to_minutes(getattr(sched, "maghrib")) + settings.iftar_delay
    return start, task(
        settings.iftar_name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.iftar_minutes),
        flex=False,
        overlap=True,
    )


def tarawih(
    sched: object,
    settings: RamadanSettings | None = None,
    *,
    start: int | None = None,
) -> tuple[int, Task]:
    """Tarawih beginning after Isha (plus an optional delay).

    Pass ``start`` to compose it around other evening blocks, for example
    after Hitam or a later return home; the delay is then not applied.
    """
    settings = settings or RamadanSettings()
    minute = (
        start
        if start is not None
        else to_minutes(getattr(sched, "isha")) + settings.tarawih_delay
    )
    minute %= 24 * 60
    return minute, task(
        settings.tarawih_name,
        start=time_from_minutes(minute),
        duration=timedelta(minutes=settings.tarawih_minutes),
        flex=False,
        overlap=True,
    )


def ramadan_events(
    day: date,
    sched: object,
    settings: RamadanSettings | None = None,
) -> list[tuple[int, Task]]:
    """Return Suhoor, Iftar and Tarawih for a Ramadan day.

    On other days the list is empty.  The individual helpers stay public so a
    plan can compose only the blocks it needs.
    """
    settings = settings or RamadanSettings()
    if not is_ramadan(day):
        return []

    events: list[tuple[int, Task]] = []
    if settings.include_suhoor:
        events.append(suhoor(sched, settings))
    if settings.include_iftar:
        events.append(iftar(sched, settings))
    if settings.include_tarawih:
        events.append(tarawih(sched, settings))
    return events
