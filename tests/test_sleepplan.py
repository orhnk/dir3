"""Season-aware Sunnah sleep plan."""

from datetime import date, time
from types import SimpleNamespace

import pytest

from dir3 import (
    BALANCED,
    LONG,
    SHORT,
    SeasonSettings,
    SleepPlanSettings,
    classify_night,
    sleep_plan,
)

LONG_NIGHT = SimpleNamespace(
    fajr=time(6, 10),
    dhuhr=time(12, 10),
    asr=time(14, 10),
    maghrib=time(15, 53),
    isha=time(17, 20),
)
BALANCED_NIGHT = SimpleNamespace(
    fajr=time(4, 40),
    dhuhr=time(12, 20),
    asr=time(15, 20),
    maghrib=time(18, 20),
    isha=time(19, 50),
)
SHORT_NIGHT = SimpleNamespace(
    fajr=time(2, 15),
    dhuhr=time(13, 10),
    asr=time(18, 0),
    maghrib=time(21, 33),
    isha=time(23, 0),
)


def _events(sched, settings=None):
    return [
        (block.name, block.start, block.until)
        for _, block in sleep_plan(date(2026, 12, 21), sched, settings)
    ]


def _sleep_minutes(events):
    total = 0
    for name, start, until in events:
        if name not in ("Schlafen", "Kaylûle"):
            continue
        minutes = (until.hour * 60 + until.minute) - (start.hour * 60 + start.minute)
        total += minutes % (24 * 60)
    return total


def test_seasons_follow_the_night_length():
    assert classify_night(6 * 60) == SHORT
    assert classify_night(7 * 60 - 1) == SHORT
    assert classify_night(7 * 60) == BALANCED
    assert classify_night(13 * 60) == BALANCED
    assert classify_night(13 * 60 + 1) == LONG


def test_long_night_splits_the_night_around_tahajjud():
    assert _events(LONG_NIGHT) == [
        ("Tahajjud", time(1, 24), time(1, 46)),
        ("Witr", time(1, 51), time(1, 56)),
        ("Schlafen", time(2, 6), time(6, 0)),
        ("Kaylûle", time(13, 45), time(14, 10)),
        ("Schlafen", time(17, 35), time(20, 46)),
    ]
    assert _sleep_minutes(_events(LONG_NIGHT)) == 450


def test_balanced_night_keeps_the_total_inside_the_bounds():
    events = _events(BALANCED_NIGHT)
    assert events == [
        ("Tahajjud", time(1, 13), time(1, 31)),
        ("Witr", time(1, 36), time(1, 41)),
        ("Schlafen", time(1, 51), time(4, 30)),
        ("Kaylûle", time(14, 0), time(14, 20)),
        ("Schlafen", time(20, 5), time(0, 36)),
    ]
    assert _sleep_minutes(events) == 450


def test_short_night_places_witr_before_sleep_and_skips_tahajjud():
    events = _events(SHORT_NIGHT)
    assert events == [
        ("Kaylûle", time(14, 0), time(14, 25)),
        ("Witr", time(23, 30), time(23, 35)),
        ("Schlafen", time(23, 45), time(1, 45)),
    ]


def test_cannot_wake_moves_witr_before_sleep():
    events = _events(BALANCED_NIGHT, SleepPlanSettings(can_wake=False))
    names = [name for name, _, _ in events]
    assert "Tahajjud" not in names
    assert names.count("Schlafen") == 1  # the whole night in one block
    assert ("Witr", time(20, 20), time(20, 25)) in events
    assert _sleep_minutes(events) == 475


def test_qaylulah_is_never_longer_than_thirty_minutes():
    settings = SleepPlanSettings(short=SeasonSettings(120, 15))
    events = _events(SHORT_NIGHT, settings)
    qaylulah = next(event for event in events if event[0] == "Kaylûle")
    assert qaylulah == ("Kaylûle", time(14, 0), time(14, 30))


def test_qaylulah_stops_before_asr():
    sched = SimpleNamespace(
        fajr=time(4, 40),
        dhuhr=time(12, 20),
        asr=time(13, 0),
        maghrib=time(18, 20),
        isha=time(19, 50),
    )
    settings = SleepPlanSettings(balanced=SeasonSettings(60, 18))
    events = _events(sched, settings)
    qaylulah = next(event for event in events if event[0] == "Kaylûle")
    assert qaylulah == ("Kaylûle", time(12, 50), time(13, 0))


def test_no_sleep_before_isha_and_none_past_the_fajr_margin():
    for sched in (LONG_NIGHT, BALANCED_NIGHT, SHORT_NIGHT):
        events = _events(sched)
        for name, start, until in events:
            if name != "Schlafen":
                continue
            if start.hour >= 12:
                assert start >= sched.isha
            start_minutes = start.hour * 60 + start.minute
            until_minutes = until.hour * 60 + until.minute
            fajr = sched.fajr.hour * 60 + sched.fajr.minute
            # Night sleep never runs past Fajr - 10 minutes.
            if until_minutes <= fajr:
                assert until_minutes <= fajr - 10
            assert start_minutes != until_minutes


def test_white_night_never_adds_a_morning_sleep():
    sched = SimpleNamespace(
        fajr=time(1, 7),
        dhuhr=time(13, 7),
        asr=time(18, 0),
        maghrib=time(21, 31),
        isha=time(1, 7),
    )
    assert _events(sched) == [("Kaylûle", time(14, 0), time(14, 25))]


def test_equal_fajr_and_maghrib_produces_no_plan():
    sched = SimpleNamespace(
        fajr=time(12, 0),
        dhuhr=time(12, 0),
        asr=time(12, 0),
        maghrib=time(12, 0),
        isha=time(12, 0),
    )
    assert _events(sched) == []


def test_settings_are_validated():
    with pytest.raises(ValueError):
        SleepPlanSettings(min_sleep_minutes=500)
    with pytest.raises(ValueError):
        SleepPlanSettings(max_sleep_minutes=400)
    with pytest.raises(ValueError):
        SleepPlanSettings(short_night=800, long_night=700)
    with pytest.raises(ValueError):
        SleepPlanSettings(qaylulah_target=-1)
    with pytest.raises(ValueError):
        SleepPlanSettings(qaylulah_latest=13 * 60)
    with pytest.raises(ValueError):
        SeasonSettings(-1, 18)
