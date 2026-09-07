"""Core scheduling behavior: soft days, anchors, compensation, patterns."""
from datetime import date, time, timedelta

import pytest

from dir3 import prayer
from dir3.anchor import all_anchors, next_event
from dir3.config import Dir3Config, LocationSettings, PrayerSettings
from dir3.core import PlanError, day, month, task, week
from dir3.engine import PlanDay, compile_pattern
from dir3.services import Services


def _services():
    config = Dir3Config(
        location=LocationSettings(
            latitude=52.52, longitude=13.405, timezone="Europe/Berlin",
        ),
        prayer=PrayerSettings(provider="offline"),
    )
    return Services(config=config)


D0 = date(2026, 6, 15)  # a Monday


def _names(pday: PlanDay) -> list[str]:
    return [ev.name for ev in pday.events if not ev.skipped]


def _active(pday: PlanDay) -> list[tuple[str, time, time]]:
    out = []
    for ev in pday.events:
        if ev.skipped:
            continue
        out.append((ev.name, ev.start.time(), ev.end.time()))
    return out


# ---------------------------------------------------------------------------


def test_chained_tasks_flow_sequentially():
    wake = time(5, 0)

    @day
    def workday(ctx):
        return [
            task("Wudu", start=wake, duration=timedelta(minutes=30)),
            task("Read", duration=timedelta(hours=1)),
            task("Sleep", until=ctx.midnight, flex=False),
        ]

    plan = compile_pattern(workday, days=1, start_date=D0, services=_services())
    day0 = _active(plan.days[0])
    assert day0 == [
        ("Wudu", time(5, 0), time(5, 30)),
        ("Read", time(5, 30), time(6, 30)),
        ("Sleep", time(6, 30), time(0, 0)),
    ]


def test_space_gap_before_task():
    @day
    def d(ctx):
        return [
            task("A", start=time(8, 0), duration=timedelta(minutes=30)),
            task("B", space=timedelta(hours=1), duration=timedelta(minutes=20)),
        ]

    plan = compile_pattern(d, days=1, start_date=D0, services=_services())
    assert _active(plan.days[0]) == [
        ("A", time(8, 0), time(8, 30)),
        ("B", time(9, 30), time(9, 50)),
    ]


def test_until_anchor_is_authoritative():
    services = _services()

    @day
    def d(ctx):
        return [
            task("Morning", start=ctx.prayer.fajr, until=ctx.prayer.sunrise),
        ]

    plan = compile_pattern(d, days=1, start_date=D0, services=services)
    ev = plan.days[0].events[0]
    schedule = services.prayer.get(D0)
    assert ev.start.time() == schedule.fajr
    assert ev.end.time() == schedule.sunrise


def test_first_task_requires_start():
    @day
    def bad(ctx):
        return [task("Rogue", duration=timedelta(minutes=10))]

    with pytest.raises(PlanError):
        compile_pattern(bad, days=1, start_date=D0, services=_services())


def test_anchor_resolution_is_cached_within_a_day():
    cache_sizes = []

    @day
    def d(ctx):
        a = ctx.resolve(ctx.prayer.dhuhr)
        b = ctx.resolve(ctx.prayer.dhuhr)
        assert a == b
        cache_sizes.append(len(ctx._resolve_cache))
        return [task("Noon", start=ctx.prayer.dhuhr, until=ctx.prayer.asr)]

    plan = compile_pattern(d, days=5, start_date=D0, services=_services())
    for pday in plan.days:
        noon = pday.events[0].start.time()
        assert time(11, 30) <= noon <= time(14, 0)
    # cache holds exactly one entry per anchor name, not per call
    assert cache_sizes == [1] * 5  # dhuhr cached once, second resolve is cache hit


def test_unless_skips_task_for_a_day():
    called_on: list = []

    def holiday(ctx):
        return ctx.date.weekday() == 4  # friday

    @day
    def d(ctx):
        called_on.append(ctx.date)
        return [
            task("Work", start=time(9, 0), duration=timedelta(hours=6), unless=holiday, flex=False),
            task("Sleep", start=time(20, 0), until=ctx.midnight, flex=False),
        ]

    plan = compile_pattern(d, days=7, start_date=D0, services=_services())
    for pday in plan.days:
        names = _names(pday)
        if pday.date.weekday() == 4:
            assert "Work" not in names
            assert pday.skipped_count == 1
        else:
            assert "Work" in names
    assert len(called_on) == 7  # evaluated once per day, not once at import


def test_soft_day_keeps_slack():
    @day
    def d(ctx):
        return [
            task("Read", start=time(6, 0), until=time(7, 0), flex=False),
            task("Deep Work", start=time(9, 0), duration=timedelta(hours=2)),
        ]

    plan = compile_pattern(d, days=1, start_date=D0, services=_services())
    pday = plan.days[0]
    assert pday.slack == timedelta(hours=13)
    assert pday.overflow == timedelta()


def test_compensation_trims_flex_events():
    @day
    def overflow_day(ctx):
        return [
            task("Flexible A", start=time(8, 0), duration=timedelta(hours=10)),
            task("Flexible B", duration=timedelta(hours=10)),
        ]

    plan = compile_pattern(overflow_day, days=1, start_date=D0, services=_services())
    pday = plan.days[0]
    assert pday.overflow == timedelta()
    assert sum(((ev.trimmed or timedelta()) for ev in pday.events), timedelta()) > timedelta()


def test_unrecoverable_overflow_is_reported():
    @day
    def d(ctx):
        return [
            task("Fixed Marathon", start=time(6, 0), duration=timedelta(hours=20), flex=False),
        ]

    plan = compile_pattern(d, days=1, start_date=D0, services=_services())
    assert plan.days[0].overflow == timedelta(hours=2)


def test_week_pattern_weekdays():
    @day
    def work(ctx):
        return [task("Job", start=time(9, 0), duration=timedelta(hours=8))]

    @day
    def off(ctx):
        return [task("Family", start=time(10, 0), duration=timedelta(hours=2))]

    w = week(mon=work, tue=work, wed=work, thu=work, fri=work, sat=off, sun=off)
    plan = compile_pattern(w, days=7, start_date=D0, services=_services())
    assert _names(plan.days[0]) == ["Job"]  # Monday
    assert _names(plan.days[4]) == ["Job"]  # Friday
    assert _names(plan.days[5]) == ["Family"]  # Saturday
    assert _names(plan.days[6]) == ["Family"]  # Sunday


def test_month_pattern_repeats():
    @day
    def work(ctx):
        return [task("Job", start=time(9, 0), duration=timedelta(hours=8))]

    @day
    def study(ctx):
        return [task("Study", start=time(9, 0), duration=timedelta(hours=8))]

    w1 = week(mon=work, tue=work, wed=work, thu=work, fri=work, sat=work, sun=work)
    w2 = week(mon=study, tue=study, wed=study, thu=study, fri=study, sat=study, sun=study)
    m = month(w1, w2)

    plan = compile_pattern(m, days=14, start_date=D0, services=_services())
    assert all(_names(plan.days[i]) == ["Job"] for i in range(7))
    assert all(_names(plan.days[i]) == ["Study"] for i in range(7, 14))


def test_overrides_apply_per_date():
    @day
    def work(ctx):
        return [task("Job", start=time(9, 0), duration=timedelta(hours=8))]

    @day
    def festival(ctx):
        return [task("Eid", start=time(8, 0), duration=timedelta(hours=2))]

    plan = compile_pattern(
        work,
        days=3,
        start_date=D0,
        overrides={"2026-06-16": festival},
        services=_services(),
    )
    assert _names(plan.days[0]) == ["Job"]
    assert _names(plan.days[1]) == ["Eid"]
    assert _names(plan.days[2]) == ["Job"]


def test_conditional_anchor_none_falls_back_to_duration():
    """'until' anchor resolving to None makes the task use its duration."""
    skipped_days = {D0}

    @day
    def d(ctx):
        return [
            task(
                "Work",
                start=time(9, 0),
                until=time(17, 0) if ctx.date not in skipped_days else None,
                duration=timedelta(hours=6),
            )
        ]

    plan = compile_pattern(d, days=2, start_date=D0, services=_services())
    # D0 (None anchor) -> falls back to duration 09:00-15:00
    assert plan.days[0].events[0].end.time() == time(15, 0)
    # D1 -> uses until anchor
    assert plan.days[1].events[0].end.time() == time(17, 0)


def test_calendar_pattern_whole_year_as_one_function():
    """calendar() lets a single date->day function drive the whole plan."""

    @day
    def school(ctx):
        return [task("Uni", start=time(9, 0), duration=timedelta(hours=4))]

    @day
    def weekend(ctx):
        return [task("Freizeit", start=time(11, 0), duration=timedelta(hours=3))]

    from dir3.core import calendar

    @calendar
    def lebensjahr(today):
        if today.weekday() >= 5:
            return weekend
        if today == date(2026, 6, 16):
            return None  # free day
        return school

    plan = compile_pattern(
        lebensjahr, days=7, start_date=D0, services=_services()
    )
    assert _names(plan.days[0]) == ["Uni"]  # Mon
    assert plan.days[1].active is False  # Tue = free day
    assert _names(plan.days[2]) == ["Uni"]  # Wed
    assert _names(plan.days[5]) == ["Freizeit"]  # Sat
    assert _names(plan.days[6]) == ["Freizeit"]  # Sun


def test_post_midnight_anchor_rolls_to_next_day():
    """A pinned start >20h before an earlier pinned block is a post-midnight
    moment (Berlin summer night, Tahajjud, night shift) and rolls over."""

    @day
    def nacht(ctx):
        return [
            task("Abendblock", start=time(18, 0), until=time(21, 0)),
            task("Spaetgebet", start=time(1, 0), duration=timedelta(minutes=10)),
        ]

    plan = compile_pattern(nacht, days=1, start_date=D0, services=_services())
    ev = plan.days[0].events[1]
    assert ev.start.date() == D0 + timedelta(days=1)
    assert ev.start.time() == time(1, 0)


def test_post_midnight_wrap_still_rejects_real_overlap():
    """A truly misordered start (12:00 after a 13:00 block) still raises."""

    @day
    def kaputt(ctx):
        return [
            task("Mittagspause", start=time(12, 0), until=time(13, 0)),
            task("Mittagsmehr", start=time(10, 0), duration=timedelta(hours=1)),
        ]

    with pytest.raises(PlanError):
        compile_pattern(kaputt, days=1, start_date=D0, services=_services())


def test_day_decorator_start_kwarg_plain_time():
    """@day(name=..., start=...) pins the first task to the day start."""

    @day(name="Mein Tag", start=time(9, 0))
    def strukturtag(ctx):
        return [task("Tee", duration=timedelta(minutes=30))]

    plan = compile_pattern(strukturtag, days=1, start_date=D0, services=_services())
    ev = plan.days[0].events[0]
    assert ev.start.time() == time(9, 0)
    assert ev.end.time() == time(9, 30)


def test_day_decorator_start_kwarg_anchor():
    """Day start can be a prayer anchor; it moves with the season."""

    @day(name="Fajr-Tag", start=prayer.fajr)
    def frueh(ctx):
        return [task("Stille", duration=timedelta(minutes=15))]

    plan = compile_pattern(frueh, days=1, start_date=D0, services=_services())
    start = plan.days[0].events[0].start.time()
    # Berlin, June: fajr is just past midnight (01:07)
    assert start.hour == 1


def test_day_start_fallback_when_first_task_start_none():
    """A day-level start also kicks in when the first task has no own start."""

    @day(name="Ohne Pins", start=time(10, 0))
    def frei(ctx):
        return [task("Sport", duration=timedelta(hours=1), flex=True)]

    plan = compile_pattern(frei, days=1, start_date=D0, services=_services())
    assert plan.days[0].events[0].start.time() == time(10, 0)


def test_next_event_until_sleep():
    """until=next_event ends the task at the next active day's first event."""

    @day
    def abend(ctx):
        return [task("Schlafen", start=time(23, 0), until=next_event)]

    @day
    def morgen(ctx):
        return [task("Aufstehen", start=time(6, 0), duration=timedelta(hours=1))]

    plan = compile_pattern(week(mon=abend, tue=morgen), days=2, start_date=D0,
                           services=_services())
    sleep = plan.days[0].events[-1]
    assert sleep.start.time() == time(23, 0)
    assert sleep.end.time() == time(6, 0)
    assert sleep.end.date() == D0 + timedelta(days=1)
    assert sleep.carry
    assert plan.days[0].overflow == timedelta(0)
    assert plan.days[0].slack == timedelta(0)


def test_next_event_skips_free_days():
    """next_event scans forward over free (inactive) days."""

    @day
    def abend(ctx):
        return [task("Schlafen", start=time(23, 0), until=next_event)]

    @day
    def morgen(ctx):
        return [task("Aufstehen", start=time(6, 0), duration=timedelta(hours=1))]

    plan = compile_pattern(week(mon=abend, wed=morgen), days=3, start_date=D0,
                           services=_services())
    assert not plan.days[1].active  # Tue is free
    sleep = plan.days[0].events[-1]
    assert sleep.end.date() == D0 + timedelta(days=2)  # lands on Wednesday
    assert sleep.end.time() == time(6, 0)


def test_next_event_last_horizon_day_falls_back():
    """Without a successor the task stays open until the end of the day."""

    @day
    def abend(ctx):
        return [task("Schlafen", start=time(23, 0), until=next_event)]

    plan = compile_pattern(abend, days=1, start_date=D0, services=_services())
    sleep = plan.days[0].events[0]
    assert sleep.open_
    assert not sleep.carry


def test_next_event_derived_offset_rolls():
    """A shifted next_event (``- timedelta``) wraps across midnight, too."""

    @day
    def abend(ctx):
        return [task("Schlafen", start=time(22, 0),
                     until=next_event - timedelta(minutes=45))]

    @day
    def morgen(ctx):
        return [task("Aufstehen", start=time(6, 0), duration=timedelta(hours=1))]

    plan = compile_pattern(week(mon=abend, tue=morgen), days=2, start_date=D0,
                           services=_services())
    sleep = plan.days[0].events[-1]
    assert sleep.end.date() == D0 + timedelta(days=1)
    assert sleep.end.time() == time(5, 15)
    assert sleep.carry


def test_next_event_is_registered():
    assert "next_event" in all_anchors()
