"""Generic Ramadan blocks: Suhoor, Iftar and Tarawih."""

from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from dir3 import RamadanSettings, iftar, ramadan_events, suhoor, tarawih

RAMADAN_DAY = date(2027, 2, 9)
SCHED = SimpleNamespace(
    fajr=time(5, 30),
    sunrise=time(7, 0),
    maghrib=time(17, 45),
    isha=time(19, 15),
)


def test_ramadan_events_anchor_to_prayer_times():
    events = ramadan_events(RAMADAN_DAY, SCHED)

    assert [(task.name, task.start, task.duration) for _, task in events] == [
        ("Suhoor", time(5, 0), timedelta(minutes=30)),
        ("Iftar", time(17, 45), timedelta(minutes=45)),
        ("Tarawih", time(19, 25), timedelta(minutes=60)),
    ]


def test_ramadan_events_are_empty_outside_ramadan():
    assert ramadan_events(date(2027, 3, 9), SCHED) == []


def test_ramadan_blocks_can_be_configured_and_selected():
    settings = RamadanSettings(
        suhoor_minutes=20,
        iftar_delay=15,
        iftar_minutes=30,
        tarawih_delay=5,
        tarawih_minutes=40,
        include_tarawih=False,
        suhoor_name="Suhur",
        iftar_name="Breakfast",
    )

    events = ramadan_events(RAMADAN_DAY, SCHED, settings)

    assert [(task.name, task.start, task.duration) for _, task in events] == [
        ("Suhur", time(5, 10), timedelta(minutes=20)),
        ("Breakfast", time(18, 0), timedelta(minutes=30)),
    ]


def test_individual_helpers_return_minute_and_task():
    minute, suhoor_task = suhoor(SCHED)
    assert minute == 5 * 60
    assert suhoor_task.until is None

    minute, iftar_task = iftar(SCHED)
    assert minute == 17 * 60 + 45
    assert iftar_task.name == "Iftar"

    minute, tarawih_task = tarawih(SCHED)
    assert minute == 19 * 60 + 25
    assert tarawih_task.name == "Tarawih"

    minute, tarawih_task = tarawih(SCHED, start=20 * 60 + 30)
    assert minute == 20 * 60 + 30
    assert tarawih_task.start == time(20, 30)


def test_ramadan_settings_validate_their_values():
    with pytest.raises(ValueError):
        RamadanSettings(suhoor_minutes=0)
    with pytest.raises(ValueError):
        RamadanSettings(tarawih_delay=-1)
    with pytest.raises(ValueError):
        RamadanSettings(iftar_name=" ")
