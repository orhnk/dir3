"""Generic Qurban (Eid al-Adha) blocks."""

from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest

from dir3 import (
    QurbanSettings,
    eid_prayer,
    qurban_distribution,
    qurban_events,
    qurban_sacrifice,
)

EID_DAY = date(2027, 5, 16)
SCHED = SimpleNamespace(sunrise=time(5, 10))


def test_qurban_events_anchor_to_sunrise():
    events = qurban_events(EID_DAY, SCHED)

    assert [(task.name, task.start, task.duration) for _, task in events] == [
        ("Eid al-Adha prayer", time(5, 25), timedelta(minutes=30)),
        ("Qurban", time(6, 10), timedelta(minutes=60)),
        ("Meat distribution", time(7, 10), timedelta(minutes=45)),
    ]


def test_qurban_events_are_empty_on_other_qurban_days():
    assert qurban_events(date(2027, 5, 17), SCHED) == []
    assert qurban_events(date(2027, 5, 20), SCHED) == []


def test_qurban_blocks_can_be_configured():
    settings = QurbanSettings(
        eid_prayer_offset=20,
        eid_prayer_minutes=20,
        sacrifice_delay=10,
        sacrifice_minutes=30,
        distribution_delay=5,
        distribution_minutes=20,
        eid_prayer_name="Eid-Gebet",
        sacrifice_name="Opfer",
        distribution_name="Fleisch verteilen",
    )

    events = qurban_events(EID_DAY, SCHED, settings)

    assert [(task.name, task.start, task.duration) for _, task in events] == [
        ("Eid-Gebet", time(5, 30), timedelta(minutes=20)),
        ("Opfer", time(6, 0), timedelta(minutes=30)),
        ("Fleisch verteilen", time(6, 35), timedelta(minutes=20)),
    ]


def test_individual_helpers_return_minute_and_task():
    minute, prayer = eid_prayer(SCHED)
    assert minute == 5 * 60 + 25
    assert prayer.name == "Eid al-Adha prayer"

    minute, sacrifice = qurban_sacrifice(SCHED)
    assert minute == 6 * 60 + 10
    assert sacrifice.name == "Qurban"

    minute, distribution = qurban_distribution(SCHED)
    assert minute == 7 * 60 + 10
    assert distribution.name == "Meat distribution"


def test_qurban_settings_validate_their_values():
    with pytest.raises(ValueError):
        QurbanSettings(eid_prayer_minutes=0)
    with pytest.raises(ValueError):
        QurbanSettings(sacrifice_delay=-1)
    with pytest.raises(ValueError):
        QurbanSettings(sacrifice_name=" ")
