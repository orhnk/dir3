"""Generic homecoming routines (shower after returning home)."""

from datetime import time, timedelta
from types import SimpleNamespace

import pytest

from dir3 import (
    FixedAnchor,
    HomeSettings,
    add_time,
    dinner_after_homecoming,
    shower_after_homecoming,
    shower_before,
    task,
)
from dir3.core import PlanError


def _return(start=time(17, 0), minutes=30, **kwargs):
    return task(
        "Weg: Arbeit >> Zuhause",
        start=start,
        duration=timedelta(minutes=minutes),
        origin="Arbeit",
        destination="home",
        **kwargs,
    )


def test_adds_shower_after_homecoming():
    tasks = [
        task("Arbeit", start=time(9, 0), duration=timedelta(hours=8)),
        _return(),
    ]

    result = shower_after_homecoming(tasks)

    assert [item.name for item in result] == ["Arbeit", "Weg: Arbeit >> Zuhause", "Duschen"]
    shower = result[-1]
    assert shower.start == time(17, 30)
    assert shower.duration == timedelta(minutes=15)
    assert shower.flex is False


def test_without_homecoming_nothing_is_added():
    tasks = [task("Arbeit", start=time(9, 0), duration=timedelta(hours=8))]

    result = shower_after_homecoming(tasks)

    assert result == tasks


def test_destination_marks_a_homecoming():
    tasks = [
        task(
            "Weg: Uni >> Zuhause",
            start=time(17, 0),
            duration=timedelta(minutes=30),
            origin="Uni",
            destination="home",
        )
    ]

    result = shower_after_homecoming(tasks)

    assert result[-1].name == "Duschen"
    assert result[-1].start == time(17, 30)


def test_non_home_trip_does_not_add_a_shower():
    tasks = [
        task(
            "Weg: Zuhause >> Uni",
            start=time(8, 0),
            duration=timedelta(minutes=30),
            origin="Zuhause",
            destination="Uni",
        )
    ]

    result = shower_after_homecoming(tasks)

    assert result == tasks


def test_skipped_home_trip_adds_no_shower():
    def skip(ctx):
        return True

    tasks = [
        task(
            "Weg: Uni >> Zuhause",
            start=time(17, 0),
            duration=timedelta(minutes=30),
            origin="Uni",
            destination="Zuhause",
            unless=skip,
        )
    ]

    result = shower_after_homecoming(
        tasks,
        HomeSettings(home_place="Zuhause"),
        ctx=SimpleNamespace(),
    )

    assert not any(item.name == "Duschen" for item in result)


def test_custom_home_place():
    tasks = [
        task(
            "Weg: Uni >> Zuhause",
            start=time(17, 0),
            duration=timedelta(minutes=30),
            origin="Uni",
            destination="Zuhause",
        )
    ]

    result = shower_after_homecoming(tasks, HomeSettings(home_place="Zuhause"))

    assert result[-1].name == "Duschen"


def test_shower_waits_for_a_fixed_block_that_overlaps_the_arrival():
    tasks = [
        _return(start=time(17, 0), minutes=30),
        task("Gebet", start=time(17, 30), duration=timedelta(minutes=30)),
        task("Schlafen", start=time(23, 0), duration=timedelta(hours=1)),
    ]

    result = shower_after_homecoming(tasks)

    shower = next(item for item in result if item.name == "Duschen")
    assert shower.start == time(18, 0)


def test_latest_start_is_inclusive_and_skips_later_returns():
    at_cutoff = shower_after_homecoming([_return(start=time(22, 15), minutes=15)])
    assert next(item for item in at_cutoff if item.name == "Duschen").start == time(22, 30)

    too_late = shower_after_homecoming([_return(start=time(22, 16), minutes=15)])
    assert not any(item.name == "Duschen" for item in too_late)


def test_custom_settings():
    settings = HomeSettings(shower_minutes=10, shower_name="Kurz duschen")

    result = shower_after_homecoming([_return()], settings)

    shower = result[-1]
    assert shower.name == "Kurz duschen"
    assert shower.duration == timedelta(minutes=10)


def test_homecoming_must_have_a_known_end():
    with pytest.raises(PlanError):
        shower_after_homecoming(
            [
                task(
                    "Weg: Arbeit >> Zuhause",
                    start=time(17, 0),
                    origin="Arbeit",
                    destination="home",
                )
            ]
        )


def test_anchors_can_be_resolved_with_a_context():
    ctx = SimpleNamespace(resolve=lambda value: value.resolve(ctx))
    homecoming = task(
        "Weg: Arbeit >> Zuhause",
        start=FixedAnchor(time(18, 0)),
        duration=timedelta(minutes=30),
        origin="Arbeit",
        destination="home",
    )

    result = shower_after_homecoming([homecoming], ctx=ctx)

    assert result[-1].start == time(18, 30)


def test_shower_inherits_unless_predicates():
    def predicate(ctx):
        return True

    homecoming = _return(unless=predicate)

    result = shower_after_homecoming([homecoming])

    assert result[-1].unless == (predicate,)


def test_shower_before_ends_at_the_given_time():
    tasks = [task("Gebet", start=time(21, 0), duration=timedelta(minutes=30))]

    result = shower_before(tasks, time(21, 0))

    shower = next(item for item in result if item.name == "Duschen")
    assert (shower.start, shower.duration) == (time(20, 45), timedelta(minutes=15))
    assert add_time(shower.start, shower.duration) == time(21, 0)


def test_shower_before_moves_ahead_of_an_occupied_slot():
    tasks = [
        task("Kochen", start=time(20, 30), duration=timedelta(minutes=30)),
        task("Gebet", start=time(21, 0), duration=timedelta(minutes=30)),
    ]

    result = shower_before(tasks, time(21, 0))

    shower = next(item for item in result if item.name == "Duschen")
    assert (shower.start, shower.duration) == (time(20, 15), timedelta(minutes=15))


def test_adds_dinner_after_homecoming():
    result = dinner_after_homecoming([_return()])

    assert [item.name for item in result] == ["Weg: Arbeit >> Zuhause", "Abendessen"]
    dinner = result[-1]
    assert dinner.start == time(17, 30)
    assert dinner.duration == timedelta(minutes=30)
    assert dinner.flex is False


def test_dinner_waits_for_not_before():
    result = dinner_after_homecoming([_return()], not_before=time(18, 0))

    assert result[-1].start == time(18, 0)


def test_late_homecoming_wins_over_not_before():
    result = dinner_after_homecoming(
        [_return(start=time(18, 30), minutes=20)],
        not_before=time(18, 0),
    )

    assert result[-1].start == time(18, 50)


def test_dinner_waits_for_an_existing_shower():
    tasks = [
        _return(),
        task("Duschen", start=time(17, 30), duration=timedelta(minutes=15)),
    ]

    result = dinner_after_homecoming(tasks)

    dinner = next(item for item in result if item.name == "Abendessen")
    assert dinner.start == time(17, 45)


def test_dinner_inherits_unless_predicates():
    def predicate(ctx):
        return True

    result = dinner_after_homecoming([_return(unless=predicate)])

    assert result[-1].unless == (predicate,)


def test_custom_dinner_settings():
    settings = HomeSettings(dinner_minutes=20, dinner_name="Nachtmahl")

    result = dinner_after_homecoming([_return()], settings)

    dinner = result[-1]
    assert dinner.name == "Nachtmahl"
    assert dinner.duration == timedelta(minutes=20)


def test_without_homecoming_no_dinner_is_added():
    tasks = [task("Arbeit", start=time(9, 0), duration=timedelta(hours=8))]

    assert dinner_after_homecoming(tasks) == tasks
