"""Reusable Qurban (Eid al-Adha) blocks.

The first Qurban day combines the Eid prayer after sunrise, the sacrifice and
the distribution of the meat.  The sacrifice itself may also be offered on the
following Tashreeq days; use :func:`qurban_sacrifice` for those.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .core import Task, task
from .islamic import is_eid_al_adha
from .timeutils import time_from_minutes, to_minutes


@dataclass(frozen=True, slots=True)
class QurbanSettings:
    """Times and names for the Qurban blocks."""

    eid_prayer_offset: int = 15
    eid_prayer_minutes: int = 30
    sacrifice_delay: int = 15
    sacrifice_minutes: int = 60
    distribution_delay: int = 0
    distribution_minutes: int = 45
    eid_prayer_name: str = "Eid al-Adha prayer"
    sacrifice_name: str = "Qurban"
    distribution_name: str = "Meat distribution"

    def __post_init__(self) -> None:
        for name in (
            "eid_prayer_offset",
            "eid_prayer_minutes",
            "sacrifice_delay",
            "sacrifice_minutes",
            "distribution_delay",
            "distribution_minutes",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        if self.eid_prayer_minutes <= 0:
            raise ValueError("eid_prayer_minutes must be positive")
        if self.sacrifice_minutes <= 0:
            raise ValueError("sacrifice_minutes must be positive")
        if self.distribution_minutes <= 0:
            raise ValueError("distribution_minutes must be positive")
        for name in ("eid_prayer_name", "sacrifice_name", "distribution_name"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")


def eid_prayer(
    sched: object,
    settings: QurbanSettings | None = None,
) -> tuple[int, Task]:
    """The Eid prayer after sunrise."""
    settings = settings or QurbanSettings()
    start = to_minutes(getattr(sched, "sunrise")) + settings.eid_prayer_offset
    return start, task(
        settings.eid_prayer_name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.eid_prayer_minutes),
        flex=False,
        overlap=True,
    )


def qurban_sacrifice(
    sched: object,
    settings: QurbanSettings | None = None,
) -> tuple[int, Task]:
    """The sacrifice after the Eid prayer."""
    settings = settings or QurbanSettings()
    start = (
        to_minutes(getattr(sched, "sunrise"))
        + settings.eid_prayer_offset
        + settings.eid_prayer_minutes
        + settings.sacrifice_delay
    )
    return start, task(
        settings.sacrifice_name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.sacrifice_minutes),
        flex=False,
        overlap=True,
    )


def qurban_distribution(
    sched: object,
    settings: QurbanSettings | None = None,
) -> tuple[int, Task]:
    """Distribution of the Qurban meat after the sacrifice."""
    settings = settings or QurbanSettings()
    start = (
        to_minutes(getattr(sched, "sunrise"))
        + settings.eid_prayer_offset
        + settings.eid_prayer_minutes
        + settings.sacrifice_delay
        + settings.sacrifice_minutes
        + settings.distribution_delay
    )
    return start, task(
        settings.distribution_name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=settings.distribution_minutes),
        flex=False,
        overlap=True,
    )


def qurban_events(
    day: date,
    sched: object,
    settings: QurbanSettings | None = None,
) -> list[tuple[int, Task]]:
    """Return Eid prayer, sacrifice and distribution on Eid al-Adha.

    On the other Qurban days the list is empty; call :func:`qurban_sacrifice`
    directly when the sacrifice is offered later.
    """
    if not is_eid_al_adha(day):
        return []
    settings = settings or QurbanSettings()
    return [
        eid_prayer(sched, settings),
        qurban_sacrifice(sched, settings),
        qurban_distribution(sched, settings),
    ]
