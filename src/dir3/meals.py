"""Generic meal blocks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .core import Task, task
from .timeutils import time_from_minutes, to_minutes


@dataclass(frozen=True, slots=True)
class MealSettings:
    """Times and names for meal blocks."""

    breakfast_minutes: int = 45
    breakfast_name: str = "Frühstück"
    breakfast_anchor: str = "sunrise"
    #: Allowed window when the end is derived from a following departure.
    breakfast_min_minutes: int = 40
    breakfast_max_minutes: int = 50


def breakfast(
    sched: object,
    settings: MealSettings | None = None,
    *,
    start_minutes: int | None = None,
    end_minutes: int | None = None,
) -> tuple[int, Task]:
    """Breakfast at the configured anchor (default: sunrise) or ``start_minutes``.

    ``start_minutes`` overrides the anchor, for example when a morning sleep
    block delays breakfast.  When ``end_minutes`` is given (for example the
    departure of the bus the person wants to catch), breakfast
    stretches/shrinks to that time as long as it stays inside
    ``breakfast_min_minutes`` .. ``breakfast_max_minutes``.  Otherwise the
    configured ``breakfast_minutes`` (45 by default) is used.
    """
    settings = settings or MealSettings()
    start = (
        to_minutes(getattr(sched, settings.breakfast_anchor))
        if start_minutes is None
        else start_minutes
    )
    minutes = settings.breakfast_minutes
    if end_minutes is not None:
        gap = end_minutes - start
        if settings.breakfast_min_minutes <= gap <= settings.breakfast_max_minutes:
            minutes = gap
    return start, task(
        settings.breakfast_name,
        start=time_from_minutes(start),
        duration=timedelta(minutes=minutes),
        flex=False,
        overlap=True,
    )
