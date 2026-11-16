"""Generic breakfast blocks."""

from datetime import time, timedelta
from types import SimpleNamespace

from dir3 import MealSettings, breakfast

SCHED = SimpleNamespace(sunrise=time(6, 52))


def test_breakfast_starts_at_sunrise_and_runs_45_minutes():
    minute, event = breakfast(SCHED)
    assert minute == 6 * 60 + 52
    assert event.name == "Frühstück"
    assert event.start == time(6, 52)
    assert event.duration == timedelta(minutes=45)


def test_breakfast_can_be_configured():
    settings = MealSettings(breakfast_minutes=30, breakfast_name="Morgenessen")
    _, event = breakfast(SCHED, settings)
    assert event.name == "Morgenessen"
    assert event.duration == timedelta(minutes=30)


def test_breakfast_stretches_to_a_departure_inside_the_window():
    _, event = breakfast(SCHED, end_minutes=7 * 60 + 35)  # 43 min after sunrise
    assert event.start == time(6, 52)
    assert event.duration == timedelta(minutes=43)


def test_breakfast_keeps_default_outside_the_window():
    _, event = breakfast(SCHED, end_minutes=8 * 60 + 10)  # 78 min after sunrise
    assert event.duration == timedelta(minutes=45)

    settings = MealSettings(breakfast_min_minutes=30, breakfast_max_minutes=60)
    _, event = breakfast(SCHED, settings, end_minutes=7 * 60 + 57)  # 65 min
    assert event.duration == timedelta(minutes=45)
