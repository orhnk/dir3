"""Timeout tests for dir3."""
from datetime import date, time, timedelta

import pytest

from dir3.anchor import (
    FixedAnchor,
    FunctionAnchor,
    all_anchors,
    anchor,
    midnight,
    named_anchor,
    register,
)
from dir3.context import DayContext
from dir3.services import Services


def _services():
    from dir3.config import Dir3Config, LocationSettings, PrayerSettings

    config = Dir3Config(
        location=LocationSettings(
            latitude=52.52, longitude=13.405, timezone="Europe/Berlin",
        ),
        prayer=PrayerSettings(provider="offline"),
    )
    return Services(config=config)


def _ctx(day: date | None = None) -> DayContext:
    return DayContext(plan_date=day or date(2026, 6, 15), services=_services())


def test_fixed_anchor_resolves():
    anchor = FixedAnchor(time(7, 0), name="wake")
    assert _ctx().resolve(anchor) == time(7, 0)


def test_derived_anchor_algebra():
    base = FixedAnchor(time(18, 0), name="end")
    minus = base - timedelta(hours=1)
    plus = base + timedelta(minutes=30)
    ctx = _ctx()
    assert ctx.resolve(minus) == time(17, 0)
    assert ctx.resolve(plus) == time(18, 30)


def test_function_anchor_none_propagates():
    anchor = FunctionAnchor(lambda ctx: None, name="holiday_start")
    assert _ctx().resolve(anchor) is None


def test_anchor_decorator_registers():
    @anchor
    def work_end(ctx):
        return time(17, 0)

    assert named_anchor("work_end") is work_end
    assert _ctx().resolve(work_end) == time(17, 0)


def test_anchor_decorator_with_name():
    @anchor(name="curfew")
    def home_latest(ctx):
        return time(23, 0)

    assert named_anchor("curfew") is home_latest


def test_midnight_is_registered():
    assert named_anchor("midnight") is midnight
    assert _ctx().resolve(midnight) == time(0, 0)


def test_all_anchors_contains_builtins():
    names = set(all_anchors())
    assert "midnight" in names


def test_register_manual():
    a = FixedAnchor(time(6, 30), name="early_rise")
    register(a)
    assert named_anchor("early_rise") is a


def test_prayer_anchor_is_per_day():
    ctx = _ctx()
    first = ctx.resolve(ctx.prayer.fajr)
    assert isinstance(first, time)
    # deterministic within the day (cached)
    assert ctx.resolve(ctx.prayer.fajr) == first


def test_plain_time_resolves_as_itself():
    assert _ctx().resolve(time(8, 15)) == time(8, 15)


def test_anchor_plus_is_not_implemented_for_time():
    a = FixedAnchor(time(8, 0))
    with pytest.raises(TypeError):
        _ = a + time(1, 0)
    with pytest.raises(TypeError):
        _ = time(1, 0) - a


def test_context_rejects_non_anchor():
    with pytest.raises(TypeError):
        _ctx().resolve(12345)
