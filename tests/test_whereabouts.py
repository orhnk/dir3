"""Whereabouts inferred from travel tasks."""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from dir3 import FixedAnchor, PlanError, Trip, Whereabouts, task, where_am_i
from dir3.engine import PlanDay, PlannedEvent


def _trip(name, start, minutes, origin, destination, **kwargs):
    return task(
        name,
        start=start,
        duration=timedelta(minutes=minutes),
        origin=origin,
        destination=destination,
        **kwargs,
    )


def _day():
    return [
        _trip("Weg: Zuhause >> Uni", time(8, 0), 30, "Zuhause", "Uni"),
        _trip("Weg: Uni >> Zuhause", time(17, 0), 30, "Uni", "Zuhause"),
    ]


def test_place_changes_only_after_a_trip():
    where = Whereabouts(_day())

    assert where.initial == "Zuhause"
    assert where.at(time(7, 59)) == "Zuhause"
    assert where.at(time(8, 15)) is None
    assert where.in_transit_at(time(8, 15)) is True
    assert where.at(time(8, 30)) == "Uni"
    assert where.at(time(16, 59)) == "Uni"
    assert where.at(time(17, 15)) is None
    assert where.at(time(17, 30)) == "Zuhause"


def test_trip_at_returns_the_active_journey():
    where = Whereabouts(_day())

    trip = where.trip_at(time(8, 15))

    assert trip is not None
    assert (trip.origin, trip.destination) == ("Zuhause", "Uni")
    assert trip.wraps_midnight is False
    assert (trip.start_minutes, trip.end_minutes) == (8 * 60, 8 * 60 + 30)


def test_midnight_trip_end_minutes_stay_ordered():
    trip = Trip("A", "B", time(23, 30), time(0, 15))

    assert trip.wraps_midnight is True
    assert trip.end_minutes == 24 * 60 + 15


def test_trips_to_filters_by_destination_and_keeps_the_source():
    where = Whereabouts(_day())

    home = where.trips_to("Zuhause")

    assert len(home) == 1
    assert home[0].origin == "Uni"
    assert home[0].destination == "Zuhause"
    assert home[0].source is not None
    assert home[0].source.name == "Weg: Uni >> Zuhause"
    assert where.trips_to("Moschee") == ()


def test_is_at_and_one_off_helper():
    where = Whereabouts(_day())

    assert where.is_at("Uni", time(9, 0)) is True
    assert where.is_at("Zuhause", time(9, 0)) is False
    assert where_am_i(_day(), time(18, 0)) == "Zuhause"


def test_places_include_initial_and_destinations():
    where = Whereabouts(_day())

    assert where.places == frozenset({"Zuhause", "Uni"})


def test_no_trips_means_unknown_place():
    where = Whereabouts([task("Arbeit", start=time(9, 0), duration=timedelta(hours=8))])

    assert where.initial is None
    assert where.at(time(10, 0)) is None
    assert where.places == frozenset()


def test_skipped_trip_does_not_move_you():
    def skip(ctx):
        return True

    tasks = [
        _trip("Hin", time(8, 0), 30, "Zuhause", "Uni", unless=skip),
        _trip("Zurueck", time(17, 0), 30, "Uni", "Zuhause"),
    ]
    where = Whereabouts(tasks, ctx=SimpleNamespace())

    assert where.at(time(9, 0)) == "Zuhause"


def test_missing_destination_is_an_error():
    with pytest.raises(PlanError):
        Whereabouts(
            [
                task(
                    "Weg",
                    start=time(8, 0),
                    duration=timedelta(minutes=30),
                    origin="Zuhause",
                )
            ]
        )


def test_trip_needs_known_times():
    with pytest.raises(PlanError):
        Whereabouts([_trip("Weg", None, 30, "Zuhause", "Uni")])


def test_anchors_resolve_with_context():
    ctx = SimpleNamespace(resolve=lambda value: value.resolve(ctx))
    tasks = [
        _trip("Hin", FixedAnchor(time(8, 0)), 30, "Zuhause", "Uni"),
    ]

    where = Whereabouts(tasks, ctx=ctx)

    assert where.at(time(8, 30)) == "Uni"


def test_compiled_plan_day_works_without_a_context():
    events = [
        PlannedEvent(
            "Hin",
            start=datetime(2026, 6, 15, 8, 0),
            end=datetime(2026, 6, 15, 8, 30),
            origin="Zuhause",
            destination="Uni",
        ),
        PlannedEvent(
            "Zurueck",
            start=datetime(2026, 6, 15, 17, 0),
            end=datetime(2026, 6, 15, 17, 30),
            origin="Uni",
            destination="Zuhause",
        ),
    ]
    plan_day = PlanDay(date=date(2026, 6, 15), name="Test", events=events)

    where = Whereabouts(plan_day)

    assert where.at(time(9, 0)) == "Uni"
    assert where.at(time(17, 15)) is None
    assert where.at(time(18, 0)) == "Zuhause"


def test_compiled_skipped_trip_keeps_the_initial_place():
    events = [
        PlannedEvent(
            "Hin",
            start=datetime(2026, 6, 15, 8, 0),
            end=datetime(2026, 6, 15, 8, 30),
            skipped=True,
            origin="Zuhause",
            destination="Uni",
        )
    ]
    plan_day = PlanDay(date=date(2026, 6, 15), name="Test", events=events)

    where = Whereabouts(plan_day)

    assert where.at(time(9, 0)) == "Zuhause"
