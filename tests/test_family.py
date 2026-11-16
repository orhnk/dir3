"""Sıla-i Rahim: family-ties blocks before Isha or at an explicit start."""

import random
from datetime import time, timedelta
from types import SimpleNamespace

import pytest

from dir3 import (
    Relative,
    SilaRahimSettings,
    select_relatives,
    sila_rahim,
    sila_rahim_events,
    under,
)

SCHED = SimpleNamespace(isha=time(18, 6))
RELATIVES = (
    Relative("Anne", 40),
    Relative("Baba", 30),
    Relative("Babanne", 10),
    Relative("Babadede", 5),
)


def test_default_block_ends_at_isha():
    minute, block = sila_rahim(SCHED)
    assert minute == 17 * 60 + 6
    assert block.name == "Sıla-i Rahim"
    assert block.start == time(17, 6)
    assert block.duration == timedelta(minutes=60)
    assert block.flex is False


def test_settings_change_duration_and_name():
    _, block = sila_rahim(
        SCHED, SilaRahimSettings(minutes=30, name="Verwandte anrufen", flex=True)
    )
    assert block.name == "Verwandte anrufen"
    assert block.start == time(17, 36)
    assert block.duration == timedelta(minutes=30)
    assert block.flex is True


def test_explicit_start_accepts_time_string_and_minutes():
    assert sila_rahim(SCHED, start=time(19, 0))[0] == 19 * 60
    assert sila_rahim(SCHED, start="19:00")[0] == 19 * 60
    assert sila_rahim(SCHED, start=19 * 60)[1].start == time(19, 0)


def test_missing_isha_needs_start():
    with pytest.raises(ValueError, match="isha"):
        sila_rahim(SimpleNamespace())


def test_invalid_settings_rejected():
    with pytest.raises(ValueError):
        SilaRahimSettings(minutes=0)
    with pytest.raises(ValueError):
        SilaRahimSettings(name="")
    with pytest.raises(ValueError):
        SilaRahimSettings(buffer_minutes=-1)
    with pytest.raises(ValueError):
        Relative("", 10)
    with pytest.raises(ValueError):
        Relative("Anne", 0)


def test_events_include_buffer_and_end_at_isha():
    settings = SilaRahimSettings(relatives=RELATIVES, buffer_minutes=10)
    events = sila_rahim_events(SCHED, settings)
    assert [block.name for _, block in events] == [
        "Sıla-i Rahim: Anne",
        "Sıla-i Rahim: Baba",
        "Sıla-i Rahim: Babanne",
        "Sıla-i Rahim: Babadede",
    ]
    assert [block.duration for _, block in events] == [
        timedelta(minutes=50),
        timedelta(minutes=40),
        timedelta(minutes=20),
        timedelta(minutes=15),
    ]
    assert events[0][0] == 16 * 60 + 1
    assert events[0][1].start == time(16, 1)
    assert events[-1][1].start == time(17, 51)
    assert (
        events[-1][1].start.hour * 60
        + events[-1][1].start.minute
        + int(events[-1][1].duration.total_seconds() // 60)
        == 18 * 60 + 6
    )


def test_gap_between_calls():
    settings = SilaRahimSettings(relatives=RELATIVES[:2], buffer_minutes=0)
    events = sila_rahim_events(SCHED, settings, gap_minutes=5, start="17:00")
    assert [block.start for _, block in events] == [time(17, 0), time(17, 45)]
    with pytest.raises(ValueError, match="gap_minutes"):
        sila_rahim_events(SCHED, settings, gap_minutes=-1)


def test_events_without_relatives_are_empty():
    assert sila_rahim_events(SCHED, SilaRahimSettings()) == []


def test_whom_after_uses_list_order():
    settings = SilaRahimSettings(relatives=RELATIVES, buffer_minutes=0)
    events = sila_rahim_events(SCHED, settings, whom=under("Babanne"))
    assert [block.name for _, block in events] == ["Sıla-i Rahim: Babadede"]
    assert events[0][1].start == time(18, 1)


def test_whom_accepts_indices_ranges_slices_and_names():
    assert [relative.name for relative in select_relatives(RELATIVES, 0)] == ["Anne"]
    assert [
        relative.name for relative in select_relatives(RELATIVES, range(0, 2))
    ] == ["Anne", "Baba"]
    assert [
        relative.name for relative in select_relatives(RELATIVES, slice(1, 3))
    ] == ["Baba", "Babanne"]
    assert [
        relative.name for relative in select_relatives(RELATIVES, ("Anne", "Babadede"))
    ] == ["Anne", "Babadede"]
    assert [
        relative.name for relative in select_relatives(RELATIVES, "babanne")
    ] == ["Babanne"]


def test_whom_callable_and_random(monkeypatch):
    even = select_relatives(RELATIVES, lambda relative, index: index % 2 == 0)
    assert [relative.name for relative in even] == ["Anne", "Babanne"]

    monkeypatch.setattr(random, "choice", lambda values: values[2])
    assert [relative.name for relative in select_relatives(RELATIVES, "random")] == [
        "Babanne"
    ]


def test_unknown_and_out_of_range_whom_raise():
    with pytest.raises(ValueError, match="unknown"):
        select_relatives(RELATIVES, "Onkel")
    with pytest.raises(ValueError, match="unknown"):
        select_relatives(RELATIVES, under("Onkel"))
    with pytest.raises(ValueError, match="out of range"):
        select_relatives(RELATIVES, 99)
    with pytest.raises(TypeError):
        select_relatives(RELATIVES, True)


def test_events_can_start_explicitly_and_skip_isha():
    settings = SilaRahimSettings(relatives=RELATIVES[:1], buffer_minutes=10)
    events = sila_rahim_events(SimpleNamespace(), settings, start="20:00")
    assert events[0][0] == 20 * 60
    assert events[0][1].duration == timedelta(minutes=50)
    with pytest.raises(ValueError, match="isha"):
        sila_rahim_events(SimpleNamespace(), settings)


def test_relatives_accept_dicts_in_settings():
    settings = SilaRahimSettings(
        relatives=({"name": "Anne", "minutes": 40},),
        buffer_minutes=0,
    )
    assert settings.relatives == (Relative("Anne", 40),)
    with pytest.raises(TypeError):
        SilaRahimSettings(relatives=("Anne",))
