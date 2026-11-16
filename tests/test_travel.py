"""Generic travel-task planning on top of the transit API."""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from dir3 import PlanError, Route, TravelSettings, route_end, route_way, task

DAY = date(2026, 11, 2)


def _journey(departure, arrival, transfers=0):
    return SimpleNamespace(
        departure=datetime.combine(DAY, departure),
        arrival=datetime.combine(DAY, arrival),
        transfers=transfers,
    )


class _FakeTransit:
    def __init__(self, batches):
        self.batches = [list(batch) for batch in batches]
        self.calls = []

    def journeys(
        self,
        origin,
        destination,
        *,
        at=None,
        arrival=None,
        lines=None,
        results=None,
        fewest_transfers=False,
    ):
        self.calls.append(
            {
                "origin": origin,
                "destination": destination,
                "at": at,
                "arrival": arrival,
                "lines": lines,
                "results": results,
                "fewest_transfers": fewest_transfers,
            }
        )
        items = self.batches.pop(0) if self.batches else []
        if at is not None:
            items = [journey for journey in items if journey.departure.time() >= at]
        if arrival is not None:
            items = [journey for journey in items if journey.arrival.time() <= arrival]
        if fewest_transfers:
            items = sorted(items, key=lambda journey: (journey.transfers, journey.departure))
        return items


def test_route_way_builds_task_with_lead_extra_and_place_names():
    gate = _FakeTransit([[_journey(time(7, 50), time(8, 33))]])
    ctx = SimpleNamespace(transit=gate)

    way = route_way(
        ctx,
        "Weg: Home >> Uni",
        Route("Mertensstr.", "TU", ("136",)),
        time(7, 40),
        lead=2,
        extra=1,
        origin="Home",
        destination="Uni",
    )

    assert way is not None
    assert way.name == "Weg: Home >> Uni"
    assert (way.start, way.duration) == (time(7, 48), timedelta(minutes=46))
    assert (way.origin, way.destination) == ("Home", "Uni")
    assert gate.calls[0]["lines"] == ("136",)
    assert gate.calls[0]["results"] == 20
    assert gate.calls[0]["fewest_transfers"] is True


def test_route_way_without_transit_returns_none():
    ctx = SimpleNamespace()

    assert route_way(ctx, "Weg", Route("A", "B"), time(8, 0)) is None


def test_route_way_without_journeys_returns_none():
    ctx = SimpleNamespace(transit=_FakeTransit([[]]))

    assert route_way(ctx, "Weg", Route("A", "B"), time(8, 0)) is None


def test_deadline_prefers_latest_feasible_with_fewest_transfers():
    gate = _FakeTransit(
        [
            [
                _journey(time(9, 0), time(9, 30), transfers=1),
                _journey(time(9, 5), time(9, 35)),
                _journey(time(9, 15), time(9, 40)),
                _journey(time(9, 20), time(9, 50)),
            ]
        ]
    )
    ctx = SimpleNamespace(transit=gate)

    way = route_way(ctx, "Weg", Route("A", "B"), time(9, 0), deadline=time(9, 40))

    assert way is not None
    assert way.start == time(9, 15)


def test_empty_answers_are_retried_by_the_configured_step():
    gate = _FakeTransit([[], [_journey(time(8, 5), time(8, 35))]])
    ctx = SimpleNamespace(transit=gate)

    way = route_way(
        ctx,
        "Weg",
        Route("A", "B"),
        time(8, 0),
        settings=TravelSettings(retry_step=5),
    )

    assert way is not None
    assert way.start == time(8, 5)
    assert [call["at"] for call in gate.calls] == [time(8, 0), time(8, 5)]


def test_route_end_uses_start_and_duration():
    way = task("Weg", start=time(10, 0), duration=timedelta(minutes=30))

    assert route_end(way) == 10 * 60 + 30


def test_route_end_requires_concrete_times():
    with pytest.raises(PlanError):
        route_end(task("Weg", start=time(10, 0)))


def test_travel_settings_validate_their_values():
    with pytest.raises(ValueError):
        TravelSettings(results=0)
    with pytest.raises(ValueError):
        TravelSettings(query_windows=(-1,))
