"""Generic Tahajjud/Witr/Suhoor night blocks."""

from datetime import date, time
from types import SimpleNamespace

from dir3 import NightSettings, night_events

SCHED = SimpleNamespace(
    fajr=time(5, 0),
    sunrise=time(7, 0),
    maghrib=time(16, 30),
    isha=time(18, 10),
)


def _events(day, sched=SCHED):
    return [
        (task.name, task.start, task.until) for _, task in night_events(day, sched, NightSettings())
    ]


def test_monday_has_tahajjud_suhoor_and_sleep():
    assert _events(date(2026, 11, 2)) == [
        ("Tahajjud", time(4, 0), time(4, 30)),
        ("Suhoor", time(4, 30), time(5, 0)),
        ("Schlafen", time(5, 0), time(6, 15)),
    ]


def test_friday_has_tahajjud_but_no_regular_suhoor():
    # Without Suhoor Tahajjud opens the last third instead of waiting for a
    # Suhoor window that does not exist.
    assert _events(date(2026, 11, 6)) == [
        ("Tahajjud", time(0, 50), time(1, 20)),
        ("Schlafen", time(1, 20), time(6, 15)),
    ]


def test_ayyam_al_biyd_adds_tahajjud_and_suhoor_on_saturday():
    assert _events(date(2026, 10, 24)) == [
        ("Tahajjud", time(4, 0), time(4, 30)),
        ("Suhoor 🌕️", time(4, 30), time(5, 0)),
        ("Schlafen", time(5, 0), time(6, 15)),
    ]


def test_ayyam_al_biyd_renames_monday_suhoor():
    assert _events(date(2026, 10, 26)) == [
        ("Tahajjud", time(4, 0), time(4, 30)),
        ("Suhoor 🌕️", time(4, 30), time(5, 0)),
        ("Schlafen", time(5, 0), time(6, 15)),
    ]


def test_ayyam_al_biyd_adds_suhoor_on_friday():
    assert _events(date(2027, 1, 22)) == [
        ("Tahajjud", time(4, 0), time(4, 30)),
        ("Suhoor 🌕️", time(4, 30), time(5, 0)),
        ("Schlafen", time(5, 0), time(6, 15)),
    ]


def test_regular_tuesday_has_no_night_blocks():
    assert _events(date(2026, 11, 3)) == []


def test_no_night_blocks_when_isha_reaches_fajr():
    no_night = SimpleNamespace(
        fajr=time(1, 7),
        sunrise=time(4, 43),
        maghrib=time(21, 31),
        isha=time(1, 7),
    )
    assert _events(date(2026, 6, 15), no_night) == []


def test_tahajjud_follows_the_last_third_in_summer():
    summer = SimpleNamespace(
        fajr=time(2, 30),
        sunrise=time(4, 45),
        maghrib=time(21, 30),
        isha=time(23, 15),
    )
    assert _events(date(2026, 6, 15), summer) == [
        ("Tahajjud", time(1, 30), time(2, 0)),
        ("Suhoor", time(2, 0), time(2, 30)),
        ("Schlafen", time(2, 30), time(4, 0)),
    ]


def test_witr_follows_tahajjud_and_leaves_the_suhoor_window_free():
    settings = NightSettings(include_witr=True, witr_minutes=6, witr_gap=4)
    events = [
        (task.name, task.start, task.until)
        for _, task in night_events(date(2026, 11, 2), SCHED, settings)
    ]
    assert events == [
        ("Tahajjud", time(3, 50), time(4, 20)),
        ("Witr", time(4, 24), time(4, 30)),
        ("Suhoor", time(4, 30), time(5, 0)),
        ("Schlafen", time(5, 0), time(6, 15)),
    ]


def test_suhoor_stays_when_tahajjud_is_disabled():
    settings = NightSettings(include_tahajjud=False)
    events = [
        (task.name, task.start, task.until)
        for _, task in night_events(date(2026, 11, 2), SCHED, settings)
    ]
    assert events == [
        ("Suhoor", time(4, 30), time(5, 0)),
        ("Schlafen", time(5, 0), time(6, 15)),
    ]


def test_forced_suhoor_uses_its_own_name_and_duration_on_ramadan():
    settings = NightSettings(
        include_tahajjud=False,
        force_suhoor=True,
        suhoor_minutes=20,
        suhoor_name="Suhur",
    )
    events = [
        (task.name, task.start, task.until)
        for _, task in night_events(date(2027, 2, 8), SCHED, settings)
    ]
    assert events == [
        ("Suhur", time(4, 40), time(5, 0)),
        ("Schlafen", time(5, 0), time(6, 15)),
    ]


def test_suhoor_ends_at_fajr_even_with_a_fixed_tahajjud_start():
    settings = NightSettings(tahajjud_start=2 * 60)
    events = [
        (task.name, task.start, task.until)
        for _, task in night_events(date(2026, 11, 2), SCHED, settings)
    ]
    assert events == [
        ("Tahajjud", time(2, 0), time(2, 30)),
        ("Schlafen", time(2, 30), time(4, 30)),
        ("Suhoor", time(4, 30), time(5, 0)),
        ("Schlafen", time(5, 0), time(6, 15)),
    ]
