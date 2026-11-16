"""Public-holiday templates: the ``holidays`` library drives free days.

The example modules under ``examples/`` import the real ``holidays`` package
(an ``examples`` extra / dev dependency), so these tests exercise the actual
calendar logic: legal-holiday detection for Germany + Baden-Wuerttemberg,
the ``holidays_in`` range listing, the ``unless=is_holiday`` predicate, and a
full offline compile catching the Christmas window.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from dir3.config import Dir3Config, LocationSettings, PrayerSettings
from dir3.engine import compile_pattern
from dir3.services import Services

# Import the real ``dir3`` package *before* extending sys.path: the examples
# directory ships its own ``dir3.py`` that would otherwise shadow it.
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
sys.path.insert(0, str(EXAMPLES))
import public_holidays_week as demo  # noqa: E402
from templates import public_holidays as ph  # noqa: E402
from templates import workday_templates  # noqa: E402

pytest.importorskip("holidays")


def _services(tmp_path) -> Services:
    config = Dir3Config(
        location=LocationSettings(latitude=40.7992, longitude=29.4305, timezone="Europe/Istanbul"),
        prayer=PrayerSettings(provider="offline"),
    )
    services = Services(config=config)
    services.prayer.cache_path = tmp_path / "prayer_times.json"
    return services


def _plan(tmp_path, *, days=5, start_date=date(2026, 12, 24), overrides=None):
    return compile_pattern(
        demo.make_plan(),
        days=days,
        start_date=start_date,
        overrides=overrides,
        services=_services(tmp_path),
    )


def _days_by_date(plan):
    return {d.date: d for d in plan.days}


# ---------------------------------------------------------------------------
# Holiday detection (Germany / Baden-Wuerttemberg)


def test_is_legal_holiday_known_dates():
    assert ph.is_legal_holiday(date(2026, 1, 1))
    assert ph.is_legal_holiday(date(2026, 1, 6))  # Epiphany, only in BW
    assert ph.is_legal_holiday(date(2026, 12, 25))
    assert ph.is_legal_holiday(date(2026, 12, 26))
    assert not ph.is_legal_holiday(date(2026, 1, 2))
    assert not ph.is_legal_holiday(date(2026, 12, 24))


def test_holiday_name_known():
    assert ph.holiday_name(date(2026, 1, 1))
    assert ph.holiday_name(date(2026, 12, 25))
    assert ph.holiday_name(date(2026, 1, 2)) is None


@pytest.mark.parametrize("first,last,expected", [
    (date(2026, 12, 23), date(2026, 12, 28), [date(2026, 12, 25), date(2026, 12, 26)]),
    (date(2026, 7, 1), date(2026, 7, 31), []),  # no summer holiday in BW
])
def test_holidays_in_range(first, last, expected):
    entries = [(d, name) for d, name in ph.holidays_in(first, last)]
    assert [d for d, _ in entries] == expected
    assert all(name for _, name in entries)


def test_is_holiday_context_predicate():
    ctx = SimpleNamespace(date=date(2026, 12, 25))
    assert ph.is_holiday(ctx)
    ctx.date = date(2026, 12, 24)
    assert not ph.is_holiday(ctx)


# ---------------------------------------------------------------------------
# Calendar behaviour around the Christmas window


def test_calendar_runs_holiday_on_christmas(tmp_path):
    days = _days_by_date(_plan(tmp_path))

    christmas = days[date(2026, 12, 25)]
    assert "Public Holiday" in christmas.name
    summaries = [e.name for e in christmas.events if e.active]
    assert "Slow morning" in summaries
    assert "Outing / friends" in summaries
    assert "Deep work" not in summaries

    weekday = days[date(2026, 12, 24)]
    assert weekday.name == "Workday"
    labels = [e.name for e in weekday.events]
    assert "Deep work" in labels


def test_unless_is_holiday_drops_work_core(tmp_path):
    forced = _plan(tmp_path, overrides={date(2026, 12, 25).isoformat(): workday_templates.workday})
    summaries = [e.name for e in forced.days[1].events if e.active]
    assert "Deep work" not in summaries  # unless=is_holiday
    assert "Asr & coffee" not in summaries
    assert "Morning routine" in summaries
    assert "Deep work" in [e.name for e in forced.days[0].events if e.active]


def test_weekend_prefers_weekend_template(tmp_path):
    day_dec_26 = _days_by_date(_plan(tmp_path))[date(2026, 12, 26)]
    # The name comes from the installed ``holidays`` language data, which can
    # differ between environments; the plan must mirror the library verbatim.
    expected = ph.holiday_name(date(2026, 12, 26))
    assert expected
    assert day_dec_26.name == f"Public Holiday - {expected}"
