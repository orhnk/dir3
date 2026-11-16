"""Alarm specs: parsing, validation and the automatic wake-up policy."""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest

from dir3 import alarm, task, week
from dir3.alarm import (
    Alarm,
    AlarmError,
    AlarmSettings,
    coerce_alarm,
    parse_offset,
)
from dir3.config import Dir3Config, LocationSettings
from dir3.engine import compile_pattern
from dir3.services import Services


def test_offset_parsing():
    assert parse_offset("10") == timedelta(minutes=10)
    assert parse_offset("-10m") == timedelta(minutes=-10)
    assert parse_offset("1h30m") == timedelta(minutes=90)
    assert parse_offset("-1h30m") == timedelta(minutes=-90)
    assert parse_offset(timedelta(seconds=45)) == timedelta(seconds=45)


def test_alarm_defaults_and_aliases():
    spec = alarm(at="end", offset="-5m", sound="adhan.mp3", label="Wake")
    assert spec.when == "end"
    assert spec.offset_seconds == -300
    assert spec.sound == "adhan.mp3"
    assert spec.label == "Wake"


def test_alarm_dict_aliases():
    spec = coerce_alarm(
        {"when": "start", "snooze": 10, "ringtone": "x.ogg", "math": "hard"}
    )[0]
    assert spec.snooze_minutes == 10
    assert spec.sound == "x.ogg"
    assert spec.dismiss_math == "hard"


def test_alarm_validation():
    with pytest.raises(AlarmError):
        Alarm(volume=101)
    with pytest.raises(AlarmError):
        Alarm(when="middle")
    with pytest.raises(AlarmError):
        Alarm(dismiss=("teleport",))
    with pytest.raises(AlarmError):
        Alarm(background="red")


def test_coerce_shorthands():
    assert coerce_alarm(None) == ()
    assert coerce_alarm(False) is None
    assert coerce_alarm("off") is None
    assert coerce_alarm("end")[0].when == "end"
    assert coerce_alarm("-15m")[0].offset_seconds == -900
    assert coerce_alarm("start-10m")[0].offset == timedelta(minutes=-10)
    assert len(coerce_alarm([alarm(), alarm(when="end")])) == 2


def test_task_carries_alarm_and_opt_out():
    spec = alarm(when="end", offset="-10m")
    assert task("X", start=time(9), duration="1h", alarm=spec).alarms == (spec,)
    assert task("Y", start=time(9), duration="1h", alarm=False).alarm_opt_out
    assert task("Z", start=time(9), duration="1h").alarms == ()


def _compile(tasks, *, alarms: AlarmSettings | None = None):
    config = Dir3Config(
        alarms=alarms or AlarmSettings(),
        location=LocationSettings(latitude=52.52, longitude=13.405, timezone="Europe/Berlin"),
    )

    def day_fn(ctx):
        return tasks

    return compile_pattern(week(mon=day_fn), days=1, start_date=date(2026, 11, 16),
                           services=Services(config=config)).days[0]


def test_wake_policy_rings_once_for_a_chain():
    pday = _compile(
        [
            task("Tahajjud", start=time(3, 0), duration="30m"),
            task("Witr", start=time(3, 30), duration="10m"),
            task("Suhoor", start=time(3, 40), duration="30m"),
            task("Fajr", start=time(4, 20), duration="30m"),
        ]
    )
    alarmed = [event.name for event in pday.events if event.alarms]
    assert alarmed == ["Tahajjud"]
    spec = pday.events[0].alarms[0]
    assert spec.speak
    assert spec.label == "Tahajjud"


def test_wake_policy_breaks_on_real_gap():
    pday = _compile(
        [
            task("Suhoor", start=time(4, 0), duration="20m"),
            task("Breakfast", start=time(6, 0), duration="30m"),
            task("Fajr", start=time(7, 0), duration="30m"),
        ]
    )
    alarmed = [event.name for event in pday.events if event.alarms]
    assert alarmed == ["Suhoor", "Fajr"]


def test_explicit_alarm_and_opt_out_win():
    pday = _compile(
        [
            task("Tahajjud", start=time(3, 0), duration="30m",
                 alarm=alarm(when="end", offset="-2m")),
            task("Fajr", start=time(5, 0), duration="30m", alarm=False),
        ]
    )
    by_name = {event.name: event for event in pday.events}
    assert by_name["Fajr"].alarms == ()
    assert by_name["Tahajjud"].alarms[0].when == "end"
    assert by_name["Tahajjud"].alarms[0].offset_seconds == -120


def test_policy_can_be_disabled():
    pday = _compile(
        [task("Fajr", start=time(5, 0), duration="30m")],
        alarms=AlarmSettings(enabled=False),
    )
    assert pday.events[0].alarms == ()


def test_night_window_excludes_evening():
    pday = _compile([task("Fajr (Moschee)", start=time(19, 0), duration="30m")])
    assert pday.events[0].alarms == ()


def test_serialisation_roundtrip():
    spec = alarm(when="end", offset="-10m", speak=True, sounds=("a.ogg", "b.ogg"),
                 dismiss=("math", "flip"), pre_notify_minutes=15)
    doc = spec.to_dict()
    assert doc["offset_seconds"] == -600
    # The phone-side dict uses offset_seconds; coerce it back like the app does.
    restored = coerce_alarm([doc])[0]
    assert restored.when == spec.when
    assert restored.offset == spec.offset
    assert restored.dismiss == spec.dismiss
