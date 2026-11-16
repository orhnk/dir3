"""Plan-specific rules: 1h45 lectures, prayer modes, breaks, Sunday rules."""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import gebetsplan
from dir3 import Whereabouts, add_time, going
from dir3.color import to_gcal_color_id


class _FakeTransit:
    def __init__(self, by_lines):
        self.by_lines = by_lines

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
        items = self.by_lines.get(tuple(lines or ()), [])
        if at is not None:
            items = [j for j in items if j.departure.time() >= at]
        if arrival is not None:
            items = [j for j in items if j.arrival.time() <= arrival]
        if fewest_transfers:
            items = sorted(
                items,
                key=lambda j: (getattr(j, "transfers", 0), j.departure),
            )
        return items


class _SyntheticTransit:
    """Test double that answers every route with a deterministic journey."""

    _ROUTES = {
        ("Mertensstr.", "Ernst-Reuter-Platz", ("136", "M45")): (5, 43),
        ("Ernst-Reuter-Platz", "Mertensstr.", ("M45", "136")): (0, 44),
        ("Mertensstr./Goltzstr.", "S+U Rathaus Spandau", ("X36",)): (0, 17),
        ("S+U Rathaus Spandau", "Galenstr.", ("671",)): (0, 14),
        ("S Tiergarten", "Galenstr.", ("S3",)): (0, 36),
        ("Galenstr.", "Mertensstr./Goltzstr.", ("X36",)): (0, 32),
    }

    def __init__(self):
        self.calls = []

    def journeys(
        self,
        origin,
        destination,
        *,
        at=None,
        arrival=None,
        lines=None,
        fewest_transfers=False,
        results=None,
    ):
        key = (origin, destination, tuple(lines or ()))
        self.calls.append((key, at, arrival))
        try:
            offset, duration = self._ROUTES[key]
        except KeyError:
            return []

        anchor = arrival if arrival is not None else at
        if anchor is None:
            return []
        minutes = anchor.hour * 60 + anchor.minute
        departure = minutes - duration if arrival is not None else minutes + offset
        dep = datetime.combine(date(2026, 1, 1), time()) + timedelta(minutes=departure)
        arr = dep + timedelta(minutes=duration)
        return [SimpleNamespace(departure=dep, arrival=arr, transfers=0)]


_DEFAULT_TRANSIT = _SyntheticTransit()


def _by_name(slots):
    return {title.split(" ")[0]: (title, start, end) for title, start, end in slots}


def _plan_slots(sched, day, extra_taken=()):
    return gebetsplan.PLANNER.slots(
        sched,
        day,
        lectures=gebetsplan._lectures_for(day, sched),
        display_lectures=gebetsplan._display_lectures(day, sched),
        extra_taken=extra_taken,
    )


def _prayer_slots(sched, day, extra_taken=()):
    return _plan_slots(sched, day, extra_taken)[0]


def test_robs_exercise_is_on_thursday_morning():
    thursday = gebetsplan._display_lectures(date(2026, 11, 5))
    assert ("10:00", "11:45", "EN 732 ROBS (Uebung, Marvin)") in thursday
    official = gebetsplan._lectures_for(date(2026, 11, 5))
    assert ("10:00", "12:00", "EN 732 ROBS (Uebung, Marvin)") in official
    tuesday = gebetsplan._lectures_for(date(2026, 11, 3))
    assert all("ROBS" not in label for _, _, label in tuesday)


def test_lectures_are_1h45_and_keep_official_block_for_overlap():
    monday = gebetsplan._lectures_for(date(2026, 11, 2))
    assert ("14:00", "16:00", "HE101 AnalinA (Winkert)") in monday
    display = gebetsplan._display_lectures(date(2026, 11, 2))
    assert ("14:00", "15:45", "HE101 AnalinA (Winkert)") in display
    assert ("16:00", "17:45", "A053 ROBS") in display


def test_prayer_durations_use_hanafi_rakats_and_wudu():
    assert gebetsplan.PRAYER_PLAN.wudu == 3
    assert gebetsplan.PLANNER.duration("Fajr") == 3 + 4 * 4
    assert gebetsplan.PLANNER.duration("Dhuhr") == 3 + 10 * 4
    assert gebetsplan.PLANNER.duration("Isha") == 3 + 13 * 4
    assert gebetsplan.PLANNER.prayer_duration("Fajr", mosque=True) == 3 + 4 * 4
    assert gebetsplan.PLANNER.prayer_duration("Isha", fardh=True) == 3 + 4 * 4
    assert gebetsplan.PLANNER.prayer_duration("Dhuhr", mosque=True, fardh=True) == 3 + 4 * 4


def test_mosque_travel_is_longer_when_coming_from_a_lecture():
    lectures = gebetsplan.PLANNER.display_blocks([("10:00", "12:00", "Test")])

    assert gebetsplan.PLANNER.mosque_travel_for(11 * 60 + 30, lectures) == 10
    assert gebetsplan.PLANNER.mosque_travel_for(11 * 60 + 45, lectures) == 10
    assert gebetsplan.PLANNER.mosque_travel_for(11 * 60 + 50, lectures) == 10
    assert gebetsplan.PLANNER.mosque_travel_for(14 * 60 + 18, lectures) == 0


def test_leisure_window_looks_fifteen_minutes_before_the_adhan():
    lectures = gebetsplan.PLANNER.display_blocks([("10:00", "12:00", "Test")])

    # Ein Event in den letzten 15 min vor dem Adhan = keine Freizeit.
    assert gebetsplan.PLANNER.mosque_travel_for(11 * 60 + 59, lectures) == 10
    # Genau 15 min nach dem Event ist die Zeit frei = Freizeit.
    assert gebetsplan.PLANNER.mosque_travel_for(12 * 60, lectures) == 0
    # Vor dem Event bleibt Freizeit.
    assert gebetsplan.PLANNER.mosque_travel_for(9 * 60 + 55, lectures) == 0


def test_mosque_travel_end_at_adhan_and_wudu_comes_after():
    chosen = gebetsplan.PLANNER.candidate(
        "Fajr",
        5 * 60,
        7 * 60,
        [],
        [],
        mosque=True,
        fardh=False,
        natural=False,
        travel=10,
    )

    assert chosen == (4 * 60 + 50, 29, 10, 5 * 60 + 3)
    start, _, lead, prayer_start = chosen
    assert start + lead == 5 * 60
    assert prayer_start == 5 * 60 + gebetsplan.PRAYER_PLAN.wudu


def test_forced_prayer_starts_at_adhan_and_wudu_comes_after():
    assert gebetsplan.PLANNER.forced_candidate("Isha", 22 * 60, ()) == (
        22 * 60,
        19,
        0,
        22 * 60 + 3,
    )


def test_lecture_overlap_ignores_first_five_minutes():
    lectures = [("10:00", "12:00", "Test")]
    assert gebetsplan.PLANNER.lecture_taken(9 * 60 + 55, 10 * 60 + 9, lectures) == 4
    assert gebetsplan.PLANNER.lecture_taken(10 * 60 + 5, 10 * 60 + 18, lectures) == 13
    assert gebetsplan.PLANNER.lecture_taken(10 * 60 + 20, 10 * 60 + 33, lectures) == 13
    assert gebetsplan.PLANNER.lecture_taken(11 * 60 + 50, 12 * 60 + 3, lectures) == 0


def test_slot_titles_mark_shift_critical_and_overlap():
    assert (
        gebetsplan.PLANNER.slot_title(
            "Asr", 14 * 60 + 14, 15 * 60 + 45, 15 * 60 + 53, 16 * 60 + 44, 0
        )
        == "Asr (verschoben: Adhan 14:14 → 15:45)"
    )
    assert (
        gebetsplan.PLANNER.slot_title(
            "Asr", 14 * 60 + 14, 14 * 60 + 30, 14 * 60 + 43, 16 * 60 + 44, 15
        )
        == "Asr (verschoben: Adhan 14:14 → 14:30, 15 min von der Vorlesung)"
    )
    assert (
        gebetsplan.PLANNER.slot_title(
            "Maghrib", 17 * 60 + 50, 17 * 60 + 45, 17 * 60 + 51, 18 * 60 + 5, 0
        )
        == "Maghrib (verschoben, kritisch, noch 14 min bis Isha-Adhan)"
    )
    assert gebetsplan.PLANNER.slot_title(
        "Maghrib", 16 * 60 + 40, 16 * 60 + 45, 16 * 60 + 56, 17 * 60 + 10, 8
    ) == ("Maghrib (verschoben, kritisch, noch 14 min bis Isha-Adhan, 8 min von der Vorlesung)")
    assert gebetsplan.PLANNER.slot_title(
        "Maghrib", 16 * 60 + 40, 16 * 60 + 45, 16 * 60 + 56, 16 * 60 + 50, 8
    ) == ("Maghrib (verschoben, kritisch, nur 2 min bis Isha-Adhan, 8 min von der Vorlesung)")


def test_slot_titles_mark_mosque_alone_fardh_and_breaks():
    assert (
        gebetsplan.PLANNER.slot_title(
            "Fajr",
            5 * 60,
            4 * 60 + 47,
            5 * 60 + 8,
            7 * 60,
            0,
            prayer_start=5 * 60 + 3,
            mode="mosque",
        )
        == "Fajr (Moschee)"
    )
    assert (
        gebetsplan.PLANNER.slot_title(
            "Isha",
            18 * 60,
            17 * 60 + 47,
            18 * 60 + 13,
            24 * 60,
            0,
            prayer_start=18 * 60 + 3,
            mode="nearby",
            fardh=True,
        )
        == "Isha (allein, Farz)"
    )
    assert (
        gebetsplan.PLANNER.slot_title(
            "Maghrib",
            16 * 60 + 25,
            16 * 60 + 22,
            16 * 60 + 35,
            18 * 60,
            0,
            broken=("A053 ROBS",),
            prayer_start=16 * 60 + 25 + 3,
            mode="nearby",
            fardh=True,
        )
        == "Maghrib (⛓️‍💥, allein, Farz)"
    )
    assert (
        gebetsplan.PLANNER.slot_title(
            "Isha",
            18 * 60,
            18 * 60,
            18 * 60 + 8,
            18 * 60 + 20,
            0,
            impossible=True,
            prayer_start=18 * 60 + 3,
            mode="nearby",
            fardh=True,
        )
        == "Isha (⛓️‍💥, allein, Farz, kritisch, noch 12 min bis Fajr-Adhan)"
    )


def test_gebeteslots_choose_mosque_fardh_and_break_when_needed():
    sched = SimpleNamespace(
        fajr=time(5, 24),
        sunrise=time(7, 16),
        dhuhr=time(11, 56),
        asr=time(14, 1),
        maghrib=time(16, 25),
        isha=time(18, 10),
    )
    slots, breaks = _plan_slots(sched, date(2026, 11, 12))
    by_name = _by_name(slots)

    assert by_name["Dhuhr"] == (
        "Dhuhr (⛓️‍💥, allein, Farz)",
        11 * 60 + 56,
        12 * 60 + 15,
    )
    assert by_name["Asr"] == (
        "Asr (Moschee)",
        14 * 60 + 1,
        14 * 60 + 36,
    )
    assert by_name["Maghrib"] == (
        "Maghrib (⛓️‍💥, allein, Farz)",
        16 * 60 + 25,
        16 * 60 + 40,
    )
    assert breaks == [
        (11 * 60 + 56, 12 * 60 + 15, "HE101 AnalinA (Keiper)"),
        (16 * 60 + 25, 16 * 60 + 40, "HE101 AnalinA (Uebung)"),
    ]


def test_maghrib_after_lecture_uses_longer_walk_and_mosque():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 20),
        maghrib=time(16, 42),
        isha=time(18, 25),
    )
    slots = _prayer_slots(sched, date(2026, 11, 2))
    by_name = _by_name(slots)

    assert by_name["Maghrib"] == (
        "Maghrib (allein, Farz, verschoben: Adhan 16:42 → 17:45)",
        17 * 60 + 45,
        18 * 60,
    )


def test_maghrib_in_long_gap_starts_at_adhan_not_at_gap_start():
    # 22.10.: Die Uebung wurde auf 18:00-20:00 verschoben, zwischen 13:45 und
    # 18:00 liegt also eine lange Luecke. Maghrib darf nicht ab 13:45 laufen.
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 50),
        asr=time(15, 21),
        maghrib=time(17, 52),
        isha=time(19, 40),
    )
    slots = _prayer_slots(sched, date(2026, 10, 22))
    by_name = _by_name(slots)

    assert by_name["Maghrib"] == (
        "Maghrib (⛓️‍💥, allein, Farz)",
        17 * 60 + 52,
        18 * 60 + 7,
    )


def test_candidate_enforces_last_30_minutes_rule():
    assert (
        gebetsplan.PLANNER.candidate(
            "Fajr",
            16 * 60,
            16 * 60 + 33,
            [],
            [],
            mosque=False,
            fardh=True,
            natural=False,
        )
        is not None
    )
    assert (
        gebetsplan.PLANNER.candidate(
            "Fajr",
            16 * 60,
            16 * 60 + 32,
            [],
            [],
            mosque=False,
            fardh=True,
            natural=False,
        )
        is None
    )


def test_asr_kerahat_forces_fardh():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(16, 10),
        maghrib=time(17, 0),
        isha=time(18, 30),
    )
    slots = _prayer_slots(sched, date(2026, 11, 7))
    by_name = _by_name(slots)

    assert by_name["Asr"] == (
        "Asr (Moschee, Farz, Kerahat, noch 31 min bis Maghrib-Adhan)",
        16 * 60 + 10,
        16 * 60 + 29,
    )


def test_kerahat_breaks_lecture_instead_of_waiting_in_kerahat():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(15, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    slots, breaks = _plan_slots(sched, date(2026, 11, 2))
    by_name = _by_name(slots)

    assert by_name["Asr"] == (
        "Asr (⛓️‍💥, allein, Farz)",
        15 * 60,
        15 * 60 + 19,
    )
    assert (15 * 60, 15 * 60 + 19, "HE101 AnalinA (Winkert)") in breaks


def test_studienplan_splits_lecture_at_broken_prayer():
    sched = SimpleNamespace(
        fajr=time(5, 24),
        sunrise=time(7, 16),
        dhuhr=time(11, 56),
        asr=time(14, 1),
        maghrib=time(16, 25),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 12),
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
    )
    tasks = gebetsplan._studienplan(ctx)
    lecture_parts = [
        (task.start, task.until) for task in tasks if task.name == "HE101 AnalinA (Uebung)"
    ]
    assert lecture_parts == [(time(16, 0), time(16, 25)), (time(16, 40), time(17, 45))]
    maghrib = next(task for task in tasks if task.name.startswith("Maghrib"))
    assert (maghrib.start, maghrib.duration) == (
        time(16, 25),
        timedelta(minutes=15),
    )


def test_jumuah_time_switches_with_daylight_saving():
    tz = ZoneInfo("Europe/Berlin")
    assert gebetsplan._jumuah_start(date(2026, 11, 6), tz) == 12 * 60 + 30
    assert gebetsplan._jumuah_start(date(2026, 7, 3), tz) == 13 * 60 + 30


def test_friday_skips_library_way_and_uses_45_minute_jumuah_bus():
    tz = ZoneInfo("Europe/Berlin")
    sched = SimpleNamespace(
        fajr=time(5, 30),
        sunrise=time(7, 20),
        dhuhr=time(11, 50),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 6),
        location=SimpleNamespace(tzinfo=tz),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=_DEFAULT_TRANSIT,
    )

    tasks = gebetsplan._studienplan(ctx)
    by_name = {task.name: task for task in tasks}
    assert "Dhuhr" not in by_name
    assert not any("Bibliothek" in name for name in by_name)
    # GldP Selbstlernen beginnt erst nach Duschen (25) + Hygiene (15).
    gldp = by_name["GldP Selbstlernen"]
    # Fruehstueck (45) + Jumuah-Duschen (25) + Hygiene (15).
    assert (gldp.start, gldp.until) == (time(8, 45), time(10, 30))
    travel = by_name["Weg: Zuhause → Moschee (X36/671)"]
    # 45 min Bus, 45 min vor der Jumuah.
    assert (travel.start, travel.duration) == (time(11, 45), timedelta(minutes=45))
    back = by_name["Weg: Moschee → Zuhause (671/X36)"]
    assert (back.start, back.duration) == (time(13, 30), timedelta(minutes=45))
    jumuah = by_name["Jumuah (verschoben: Adhan 11:50 → 12:30)"]
    assert jumuah.start == time(12, 30)
    assert jumuah.duration == timedelta(minutes=60)


def test_friday_asr_does_not_overlap_jumuah():
    tz = ZoneInfo("Europe/Berlin")
    sched = SimpleNamespace(
        fajr=time(5, 30),
        sunrise=time(7, 20),
        dhuhr=time(12, 5),
        asr=time(13, 41),
        maghrib=time(15, 46),
        isha=time(17, 52),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 12, 11),
        location=SimpleNamespace(tzinfo=tz),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
    )

    tasks = gebetsplan._studienplan(ctx)
    jumuah = next(task for task in tasks if task.name.startswith("Jumuah"))
    asr = next(task for task in tasks if task.name.startswith("Asr"))
    back = next(task for task in tasks if task.name.startswith("Weg: Moschee →"))
    assert (jumuah.start, jumuah.duration) == (
        time(12, 30),
        timedelta(minutes=60),
    )
    assert (back.start, back.duration) == (time(13, 30), timedelta(minutes=45))
    # Asr weicht dem 45-min-Rueckweg aus und wird danach zuhause/Moschee gebetet.
    assert asr.start == time(14, 15)
    assert asr.name == "Asr (Moschee, verschoben: Adhan 13:41 → 14:15)"


def test_friday_jumuah_moves_late_in_summer():
    tz = ZoneInfo("Europe/Berlin")
    sched = SimpleNamespace(
        fajr=time(2, 45),
        sunrise=time(4, 45),
        dhuhr=time(13, 10),
        asr=time(17, 30),
        maghrib=time(21, 30),
        isha=time(23, 15),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 7, 3),
        location=SimpleNamespace(tzinfo=tz),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=_DEFAULT_TRANSIT,
    )

    tasks = {task.name: task for task in gebetsplan._studienplan(ctx)}
    travel = tasks["Weg: Zuhause → Moschee (X36/671)"]
    # 45 min Bus, 45 min vor der Jumuah (Sommerzeit).
    assert (travel.start, travel.duration) == (time(12, 45), timedelta(minutes=45))
    jumuah = tasks["Jumuah (verschoben: Adhan 13:10 → 13:30)"]
    assert jumuah.start == time(13, 30)
    back = tasks["Weg: Moschee → Zuhause (671/X36)"]
    assert (back.start, back.duration) == (time(14, 30), timedelta(minutes=45))


def _ctx_with_transit(plan_date, sched, transit):
    return SimpleNamespace(
        plan_date=plan_date,
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=transit,
    )


def test_morning_way_departs_after_breakfast_and_lands_55_minutes_later():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    for day in (date(2026, 11, 3), date(2026, 11, 10)):
        ctx = _ctx_with_transit(day, sched, _DEFAULT_TRANSIT)

        tasks = gebetsplan._studienplan(ctx)
        way = next(task for task in tasks if task.name.startswith("Weg: Mertensstr."))
        meal = next(task for task in tasks if task.name == "Frühstück")

        # Fruehstueck (45 min) ab Sonnenaufgang, danach der feste Weg.
        assert (way.start, way.duration) == (time(7, 45), timedelta(minutes=55))
        assert (meal.start, meal.duration) == (time(7, 0), timedelta(minutes=45))


def test_morning_way_has_no_30_minutes_todo():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = _ctx_with_transit(date(2026, 11, 3), sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    assert all(task.name != "⏰ 30 Minuten?" for task in tasks)


def test_friday_has_no_morning_way_todo():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(11, 50),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = _ctx_with_transit(date(2026, 11, 6), sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    assert all(task.name != "⏰ 30 Minuten?" for task in tasks)


def test_hitam_follows_isha_except_on_sunday():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )

    for plan_date in (date(2026, 11, 2), date(2026, 11, 3)):
        ctx = _ctx_with_transit(plan_date, sched, _DEFAULT_TRANSIT)
        tasks = gebetsplan._studienplan(ctx)
        isha = next(task for task in tasks if task.name.startswith("Isha"))
        hitam = next(task for task in tasks if task.name == "📚 Hitam")
        assert (hitam.start, hitam.duration) == (
            add_time(isha.start, isha.duration),
            timedelta(minutes=15),
        )
        # Hitam bleibt reiner Eventname: kein eigener Google Task, nur K/R/P.
        assert hitam.task_list == "Hitam"
        assert hitam.todo_position is None
        assert [(todo.title, todo.todo_position) for todo in hitam.todos] == [
            ("K", "end"),
            ("R", "end"),
            ("P", "end"),
        ]

    sunday = _ctx_with_transit(date(2026, 11, 8), sched, _DEFAULT_TRANSIT)
    assert all(task.name != "📚 Hitam" for task in gebetsplan._studienplan(sunday))


def test_friday_self_study_starts_after_shower_and_hygiene():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(11, 50),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = _ctx_with_transit(date(2026, 11, 6), sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    by_name = {task.name: task for task in tasks}
    assert not any("Bibliothek" in name for name in by_name)
    breakfast = by_name["Frühstück"]
    shower = by_name["Duschen"]
    hygiene = by_name["Persönliche Hygiene"]
    gldp = by_name["GldP Selbstlernen"]
    # Fruehstueck 07:00-07:45, dann Duschen + Hygiene (kein Morgenschlaf).
    assert (breakfast.start, breakfast.duration) == (time(7, 0), timedelta(minutes=45))
    assert (shower.start, shower.duration) == (time(7, 45), timedelta(minutes=25))
    assert (hygiene.start, hygiene.duration) == (time(8, 10), timedelta(minutes=15))
    assert (gldp.start, gldp.until) == (time(8, 25), time(10, 10))


def test_sunday_has_no_travel_events():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    transit = _SyntheticTransit()
    ctx = _ctx_with_transit(date(2026, 11, 1), sched, transit)

    tasks = gebetsplan._studienplan(ctx)

    assert all(not task.name.startswith("Weg") for task in tasks)
    assert not any(task.name == "Abendessen" for task in tasks)
    assert not any(task.name == "Duschen" for task in tasks)
    assert transit.calls == []


def test_sunday_cooks_after_asr_when_home():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = _ctx_with_transit(date(2026, 11, 15), sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    asr = next(task for task in tasks if task.name.startswith("Asr"))
    cooking = next(task for task in tasks if task.name == "Kochen")

    assert (cooking.start, cooking.until) == (
        add_time(asr.start, asr.duration),
        add_time(add_time(asr.start, asr.duration), timedelta(minutes=60)),
    )
    assert (cooking.start, cooking.until) == (time(14, 35), time(15, 35))


def test_sunday_cooking_waits_for_homecoming():
    tasks = [
        gebetsplan.task(
            "Weg: Uni → Zuhause",
            start=time(17, 0),
            duration=timedelta(minutes=30),
            origin="Uni",
            destination="Zuhause",
        )
    ]

    assert gebetsplan._cook_after_asr_start(tasks, 14 * 60 + 35) == 17 * 60 + 30


def test_sunday_cooking_is_skipped_when_away_without_return():
    tasks = [
        gebetsplan.task(
            "Weg: Zuhause → Uni",
            start=time(13, 0),
            duration=timedelta(minutes=30),
            origin="Zuhause",
            destination="Uni",
        )
    ]

    assert gebetsplan._cook_after_asr_start(tasks, 14 * 60 + 35) is None


def test_going_couples_way_before_event():
    event = gebetsplan.task("Netzwerken", start=time(18, 0), until=time(22, 0), flex=False)
    way = gebetsplan.task("Weg", duration=timedelta(minutes=45), flex=False)

    tasks = going(event, way)

    assert [task.name for task in tasks] == ["Weg", "Netzwerken"]
    assert tasks[0].start == time(17, 15)
    assert tasks[0].duration == timedelta(minutes=45)
    assert tasks[1] is event


def test_asr_kerahat_title():
    kerahat = gebetsplan.PLANNER.slot_title(
        "Asr",
        14 * 60,
        13 * 60 + 57,
        14 * 60 + 8,
        14 * 60 + 50,
        0,
        prayer_start=14 * 60 + 3,
    )
    assert kerahat == "Asr (Kerahat, noch 42 min bis Maghrib-Adhan)"
    assert (
        gebetsplan.PLANNER.slot_title(
            "Asr",
            14 * 60,
            13 * 60 + 57,
            14 * 60 + 8,
            15 * 60,
            0,
            prayer_start=14 * 60 + 3,
        )
        == "Asr"
    )


def test_sunday_isha_follows_the_network_until_2230():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    slots = _prayer_slots(sched, date(2026, 11, 1))
    by_name = _by_name(slots)

    assert by_name["Isha"] == (
        "Isha (Moschee, verschoben: Adhan 18:10 → 22:30)",
        22 * 60 + 30,
        23 * 60 + 25,
    )


def test_late_adhan_after_2000_is_used_without_shifting():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 34),
        isha=time(20, 34),
    )
    slots = _prayer_slots(sched, date(2026, 10, 24))
    by_name = _by_name(slots)

    assert by_name["Isha"] == (
        "Isha (Moschee)",
        20 * 60 + 34,
        21 * 60 + 29,
    )


def test_other_days_pray_isha_in_mosque_at_20():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    slots = _prayer_slots(sched, date(2026, 11, 7))
    by_name = _by_name(slots)

    assert by_name["Isha"] == (
        "Isha (Moschee, verschoben: Adhan 18:10 → 20:00)",
        20 * 60,
        20 * 60 + 55,
    )


def test_isha_uses_a_late_adhan_in_mosque_instead_of_20():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(22, 10),
    )
    slots = _prayer_slots(sched, date(2026, 11, 7))
    by_name = _by_name(slots)

    assert by_name["Isha"] == ("Isha (Moschee)", 22 * 60 + 10, 23 * 60 + 5)


def test_sunday_netzwerken_runs_until_isha_afterward():
    tz = ZoneInfo("Europe/Berlin")
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 1),
        location=SimpleNamespace(tzinfo=tz),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=_DEFAULT_TRANSIT,
    )

    tasks = gebetsplan._studienplan(ctx)
    assert all(not task.name.startswith("Weg") for task in tasks)
    netzwerken = [(task.start, task.until) for task in tasks if task.name == "Netzwerken"]
    assert netzwerken == [(time(18, 0), time(22, 30))]
    isha = next(task for task in tasks if task.name.startswith("Isha"))
    assert (isha.start, isha.duration) == (
        time(22, 30),
        timedelta(minutes=55),
    )
    assert all(task.name != "📚 Hitam" for task in tasks)
    assert not any(task.name == "Duschen" for task in tasks)
    assert not any(task.name == "Abendessen" for task in tasks)
    sleep = next(
        task for task in tasks if task.name == "Schlafen" and task.start == time(23, 25)
    )
    assert sleep.start == time(23, 25)


def test_color_policy_prayers_use_status_colors_and_module_groups():
    policy = gebetsplan.color_policy
    status_colors = {
        "Fajr (Moschee)": "10",
        "Dhuhr (Moschee, Farz)": "10",
        "Dhuhr (allein, Farz)": "4",
        "Asr (Kerahat)": "11",
        "Jumuah (verschoben: Adhan 11:55 → 12:30)": "2",
        "Isha (Moschee)": "10",
        "Isha (Moschee, verschoben: Adhan 18:10 → 20:00)": "2",
        "Maghrib (⛓️‍💥, allein, Farz)": "4",
        "Maghrib (allein, verschoben: Adhan 16:42 → 17:48)": "4",
        "Maghrib (verschoben, kritisch, noch 14 min bis Isha-Adhan)": "11",
    }
    assert {
        name: to_gcal_color_id(policy.color_for(name, 0)) for name in status_colors
    } == status_colors

    assert to_gcal_color_id(policy.color_for("Weg: Mertensstr. → Berlin", 0)) == "8"
    assert to_gcal_color_id(policy.color_for("Netzwerken", 0)) == "6"
    assert to_gcal_color_id(policy.color_for("Suhoor 🌕️", 0)) == "6"
    assert to_gcal_color_id(policy.color_for("Witr", 0)) == "10"
    assert to_gcal_color_id(policy.color_for("Kaylûle", 0)) == "1"

    module_colors = {
        "HE101 AnalinA (Winkert)": "7",
        "A053 ROBS": "11",
        "MA 751 IaD (Uebung)": "9",
        "E-N732 GldP (Uebung)": "3",
    }
    assert {
        name: to_gcal_color_id(policy.color_for(name, 0)) for name in module_colors
    } == module_colors
    assert len(set(module_colors.values())) == 4
    assert "10" not in module_colors.values()

    assert to_gcal_color_id(policy.color_for("x", 0)) == "1"


def test_fajr_block_is_fixed_45_minutes_before_sunrise():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    slots = _prayer_slots(sched, date(2026, 11, 2))
    by_name = _by_name(slots)

    assert by_name["Fajr"] == ("Fajr (Moschee)", 6 * 60 + 15, 6 * 60 + 45)


def test_evening_sleep_runs_from_2300_until_next_event():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 3),
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
    )

    tasks = gebetsplan._studienplan(ctx)
    sleeps = [task for task in tasks if task.name == "Schlafen" and task.start == time(23, 0)]
    assert len(sleeps) == 1
    assert sleeps[0].until is gebetsplan.next_event


def test_breakfast_is_after_sunrise_on_non_fasting_days():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 3),
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=_DEFAULT_TRANSIT,
    )

    tasks = gebetsplan._studienplan(ctx)
    breakfast = next(task for task in tasks if task.name == "Frühstück")
    assert (breakfast.start, breakfast.duration) == (time(7, 0), timedelta(minutes=45))


def test_fasting_day_has_no_breakfast():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 2),
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=_DEFAULT_TRANSIT,
    )

    names = [task.name for task in gebetsplan._studienplan(ctx)]
    assert "Frühstück" not in names
    morning = next(name for name in names if name.startswith("Weg: Mertensstr."))
    assert morning == "Weg: Mertensstr. → TU (136/M45)"


def test_fasting_day_leaves_right_after_fajr():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    transit = _FakeTransit(
        {
            ("136", "M45"): [
                SimpleNamespace(
                    departure=datetime(2026, 11, 2, 7, 2),
                    arrival=datetime(2026, 11, 2, 7, 47),
                    transfers=1,
                )
            ]
        }
    )
    ctx = _ctx_with_transit(date(2026, 11, 2), sched, transit)

    tasks = gebetsplan._studienplan(ctx)
    way = next(task for task in tasks if task.name.startswith("Weg: Mertensstr."))

    # Fastentag: kein Fruehstueck, der Weg startet direkt nach Fajr.
    assert (way.start, way.duration) == (time(7, 0), timedelta(minutes=55))


def test_chronological_rolls_post_midnight_isha_before_fajr():
    tasks = [
        SimpleNamespace(name="Suhoor", start=time(0, 37)),
        SimpleNamespace(name="Isha", start=time(1, 4)),
        SimpleNamespace(name="Fajr (Moschee)", start=time(3, 58)),
        SimpleNamespace(name="Abendessen", start=time(22, 31)),
    ]

    assert [item.name for item in gebetsplan._chronological(tasks)] == [
        "Suhoor",
        "Fajr (Moschee)",
        "Abendessen",
        "Isha",
    ]


def test_tahajjud_is_at_4_and_suhoor_follows():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 2),  # Montag
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
    )

    tasks = gebetsplan._studienplan(ctx)
    tahajjud = next(task for task in tasks if task.name == "Tahajjud")
    suhoor = next(task for task in tasks if task.name == "Suhoor")
    sleep = next(
        task for task in tasks if task.name == "Schlafen" and task.start == time(5, 0)
    )

    witr = next(task for task in tasks if task.name == "Witr")
    assert (tahajjud.start, tahajjud.until) == (time(4, 2), time(4, 20))
    assert (witr.start, witr.until) == (time(4, 25), time(4, 30))
    assert (suhoor.start, suhoor.until) == (time(4, 30), time(5, 0))
    assert (sleep.start, sleep.until) == (time(5, 0), time(6, 5))


def test_no_morning_sleep_before_a_1000_lecture():
    sched = SimpleNamespace(
        fajr=time(5, 30),
        sunrise=time(7, 30),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = _ctx_with_transit(date(2026, 11, 3), sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    by_name = {task.name: task for task in tasks}
    assert "Morgenschlaf" not in by_name
    breakfast = by_name["Frühstück"]
    assert (breakfast.start, breakfast.duration) == (
        time(7, 30),
        timedelta(minutes=45),
    )
    way = next(task for task in tasks if task.name.startswith("Weg: Mertensstr."))
    assert (way.start, way.duration) == (time(8, 15), timedelta(minutes=55))


def test_kaylule_is_skipped_when_lecture_leaves_no_gap():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = _ctx_with_transit(date(2026, 11, 4), sched, _DEFAULT_TRANSIT)

    names = [task.name for task in gebetsplan._studienplan(ctx)]
    assert "Kaylûle" not in names


def test_short_summer_night_places_witr_before_sleep_without_tahajjud():
    sched = SimpleNamespace(
        fajr=time(2, 45),
        sunrise=time(4, 45),
        dhuhr=time(13, 10),
        asr=time(17, 30),
        maghrib=time(21, 30),
        isha=time(23, 15),
    )
    ctx = _ctx_with_transit(date(2026, 7, 4), sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    names = [task.name for task in tasks]
    assert "Tahajjud" not in names
    witr = next(task for task in tasks if task.name == "Witr")
    sleep = next(task for task in tasks if task.name == "Schlafen")
    assert (witr.start, witr.duration) == (time(0, 25), timedelta(minutes=5))
    assert sleep.start == add_time(witr.start, witr.duration)
    assert "Morgenschlaf" not in names


def test_short_fasting_night_keeps_suhoor_without_tahajjud():
    sched = SimpleNamespace(
        fajr=time(2, 45),
        sunrise=time(4, 45),
        dhuhr=time(13, 10),
        asr=time(17, 30),
        maghrib=time(21, 30),
        isha=time(23, 15),
    )
    ctx = _ctx_with_transit(date(2026, 7, 2), sched, _DEFAULT_TRANSIT)

    names = [task.name for task in gebetsplan._studienplan(ctx)]
    assert "Suhoor" in names
    assert "Tahajjud" not in names


def test_weekday_return_goes_from_tu():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    plan_date = date(2026, 11, 2)
    ctx = _ctx_with_transit(plan_date, sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    # Montag: letztes Vorlesungsende 17:45, Maghrib schon gebetet.
    home = next(task for task in tasks if task.name == "Weg: TU → Zuhause (136/M45)")
    assert (home.start, home.duration) == (time(17, 45), timedelta(minutes=50))
    assert (home.origin, home.destination) == (
        gebetsplan.PLACE_UNI,
        gebetsplan.PLACE_HOME,
    )
    assert not any(task.name == "Weg: Moschee → Zuhause (X36)" for task in tasks)


def test_hitam_waits_for_return_when_way_overlaps_isha():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 50),
        asr=time(15, 21),
        maghrib=time(17, 52),
        isha=time(19, 40),
    )
    ctx = _ctx_with_transit(date(2026, 10, 22), sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    home = next(task for task in tasks if task.name == "Weg: TU → Zuhause (136/M45)")
    isha = next(task for task in tasks if task.name.startswith("Isha"))
    hitam = next(task for task in tasks if task.name == "📚 Hitam")

    assert (home.start, home.duration) == (time(19, 45), timedelta(minutes=50))
    assert isha.start == time(20, 0)
    assert hitam.start == add_time(isha.start, isha.duration) == time(20, 55)


def test_saturday_has_no_travel_and_showers_before_isha_without_dinner():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    plan_date = date(2026, 10, 31)
    ctx = _ctx_with_transit(plan_date, sched, _SyntheticTransit())

    tasks = gebetsplan._studienplan(ctx)
    assert all(not task.name.startswith("Weg") for task in tasks)
    assert not any(task.name == "Abendessen" for task in tasks)
    shower = next(task for task in tasks if task.name == "Duschen")
    isha = next(task for task in tasks if task.name.startswith("Isha"))
    assert (shower.start, shower.duration) == (time(19, 45), timedelta(minutes=15))
    assert add_time(shower.start, shower.duration) == isha.start


def test_friday_return_stays_from_mosque():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(11, 50),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 6),
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=_DEFAULT_TRANSIT,
    )

    tasks = gebetsplan._studienplan(ctx)
    home = next(task for task in tasks if task.name == "Weg: Moschee → Zuhause (671/X36)")
    assert (home.start, home.duration) == (time(13, 30), timedelta(minutes=45))
    assert (home.origin, home.destination) == (
        gebetsplan.PLACE_MOSQUE,
        gebetsplan.PLACE_HOME,
    )
    assert not any(task.name == "Weg: TU → Zuhause (136/M45)" for task in tasks)


def test_weekday_return_is_followed_by_shower():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    plan_date = date(2026, 11, 2)
    transit = _FakeTransit(
        {
            ("136", "M45"): [
                SimpleNamespace(
                    departure=datetime.combine(plan_date, time(7, 45)),
                    arrival=datetime.combine(plan_date, time(8, 28)),
                    transfers=0,
                )
            ],
            ("M45", "136"): [
                SimpleNamespace(
                    departure=datetime.combine(plan_date, time(19, 10)),
                    arrival=datetime.combine(plan_date, time(20, 0)),
                    transfers=1,
                )
            ],
        }
    )
    ctx = _ctx_with_transit(plan_date, sched, transit)

    tasks = gebetsplan._studienplan(ctx)
    home = next(task for task in tasks if task.name == "Weg: TU → Zuhause (136/M45)")
    shower = next(task for task in tasks if task.name == "Duschen")
    dinner = next(task for task in tasks if task.name == "Abendessen")

    assert home.origin == gebetsplan.PLACE_UNI
    assert home.destination == gebetsplan.PLACE_HOME
    assert (home.start, home.duration) == (time(17, 45), timedelta(minutes=50))
    assert (shower.start, shower.duration) == (time(18, 35), timedelta(minutes=15))
    assert (dinner.start, dinner.duration) == (time(18, 50), timedelta(minutes=30))

    where = Whereabouts(tasks)
    assert where.initial == gebetsplan.PLACE_HOME
    assert where.at(time(12, 0)) == gebetsplan.PLACE_UNI
    assert where.at(time(20, 0)) == gebetsplan.PLACE_HOME


def test_wednesday_shower_follows_dinner_before_late_isha():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 4),
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=_DEFAULT_TRANSIT,
    )

    tasks = gebetsplan._studienplan(ctx)
    shower = next(task for task in tasks if task.name == "Duschen")
    dinner = next(task for task in tasks if task.name == "Abendessen")
    isha = next(task for task in tasks if task.name.startswith("Isha"))

    assert shower.start == time(19, 43)
    assert (dinner.start, dinner.duration) == (time(19, 13), timedelta(minutes=30))
    assert isha.start == time(20, 0)


def _wednesday_plan(ctx):
    tasks = gebetsplan._studienplan(ctx)
    by_name = {task.name: task for task in tasks}
    return tasks, by_name


def test_wednesday_catches_maghrib_at_uni_and_cooks_after():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 4),
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=_DEFAULT_TRANSIT,
    )

    tasks, by_name = _wednesday_plan(ctx)
    # Zuhause um 17:00 waere Maghrib 33 min zu spaet: das Gebet wird
    # puenktlich an der Uni gebetet (16:30), erst danach geht es los.
    shopping = by_name["Weg & Einkaufen: TU → Zuhause (136/M45)"]
    assert shopping.start == time(16, 53)
    assert shopping.duration == timedelta(minutes=80)
    maghrib = by_name["Maghrib (allein)"]
    assert (maghrib.start, maghrib.duration) == (time(16, 30), timedelta(minutes=23))
    # Kochen (60 min) ab Ankunft; Isha liegt um 20:00, bricht nicht ab.
    cooking = sorted((task.start, task.until) for task in tasks if task.name == "Kochen")
    assert cooking == [(time(18, 13), time(19, 13))]
    isha = next(task for task in tasks if task.name.startswith("Isha"))
    assert isha.start == time(20, 0)
    dinner = next(task for task in tasks if task.name == "Abendessen")
    # Abendsessen direkt nach dem Kochen - Isha ist erst um 20:00.
    assert (dinner.start, dinner.duration) == (time(19, 13), timedelta(minutes=30))


def test_wednesday_home_prayer_when_arrival_delay_stays_under_30():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 45),
        isha=time(18, 20),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 18),
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=_DEFAULT_TRANSIT,
    )

    tasks, by_name = _wednesday_plan(ctx)
    # Unter 30 min Verspaetung (17:05 statt 16:45 - 20 min) bleibt es beim
    # 17:00-Heimkommen und das Gebet wird zuhause beim Ankommen gebetet.
    shopping = by_name["Weg & Einkaufen: TU → Zuhause (136/M45)"]
    assert (shopping.start, shopping.duration) == (time(15, 40), timedelta(minutes=80))
    maghrib = next(task for task in tasks if task.name.startswith("Maghrib"))
    assert maghrib.start == time(17, 0)
    # Kochen landet als ein Stueck (60 min) hinter dem Gebet.
    cooking = sorted((task.start, task.until) for task in tasks if task.name == "Kochen")
    assert cooking == [(time(17, 23), time(18, 23))]
    isha = next(task for task in tasks if task.name.startswith("Isha"))
    assert isha.start == time(20, 0)
    # Abendsessen nach dem Kochen, Isha ist erst um 20:00.
    dinner = next(task for task in tasks if task.name == "Abendessen")
    assert (dinner.start, dinner.duration) == (time(18, 23), timedelta(minutes=30))
    shower = next(task for task in tasks if task.name == "Duschen")
    assert shower.start == time(18, 53)


def test_monday_cleanup_follows_isha():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 2),
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=_DEFAULT_TRANSIT,
    )

    tasks = gebetsplan._studienplan(ctx)
    shower = next(task for task in tasks if task.name == "Duschen")
    dinner = next(task for task in tasks if task.name == "Abendessen")
    cleanup = next(task for task in tasks if task.name == "Aufräumen")
    sleep = next(
        task for task in tasks if task.name == "Schlafen" and task.start == time(23, 0)
    )

    assert (shower.start, shower.duration) == (time(18, 35), timedelta(minutes=15))
    assert (dinner.start, dinner.duration) == (time(18, 50), timedelta(minutes=30))
    hitam = next(task for task in tasks if task.name == "📚 Hitam")
    # Montag: eine Stunde aufraeumen, aber erst nach Isha und Hitam.
    assert (cleanup.start, cleanup.duration) == (time(21, 10), timedelta(minutes=60))
    assert cleanup.start == add_time(hitam.start, hitam.duration)
    assert sleep.start == time(23, 0)


def test_tuesday_has_no_cleanup():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = SimpleNamespace(
        plan_date=date(2026, 11, 3),
        location=SimpleNamespace(tzinfo=ZoneInfo("Europe/Berlin")),
        prayer=SimpleNamespace(schedule=lambda ctx: sched),
        transit=_DEFAULT_TRANSIT,
    )

    tasks = gebetsplan._studienplan(ctx)
    assert all(task.name != "Aufräumen" for task in tasks)


def test_wednesday_return_uses_m45_and_136_from_tu():
    sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    transit = _FakeTransit(
        {
            ("M45", "136"): [
                SimpleNamespace(
                    departure=datetime(2026, 11, 4, 15, 55),
                    arrival=datetime(2026, 11, 4, 16, 29),
                    transfers=1,
                ),
                SimpleNamespace(
                    departure=datetime(2026, 11, 4, 16, 43),
                    arrival=datetime(2026, 11, 4, 17, 25),
                    transfers=1,
                ),
            ]
        }
    )
    ctx = _ctx_with_transit(date(2026, 11, 4), sched, transit)

    tasks = gebetsplan._studienplan(ctx)
    shopping = next(
        task for task in tasks if task.name == "Weg & Einkaufen: TU → Zuhause (136/M45)"
    )
    # Ankunft waere 17:00 (Maghrib 30 min zu spaet): Gebet puenktlich an der
    # Uni (16:27-16:43), dann der zweite Weg mit 50 min Fahrt + 30 min
    # Einkaufen.
    assert (shopping.start, shopping.duration) == (time(16, 53), timedelta(minutes=80))
    maghrib = next(task for task in tasks if task.name.startswith("Maghrib"))
    assert maghrib.name == "Maghrib (allein)"
    assert (maghrib.start, maghrib.duration) == (time(16, 30), timedelta(minutes=23))


def test_ramadan_day_has_suhoor_iftar_and_tarawih_without_breakfast():
    sched = SimpleNamespace(
        fajr=time(5, 30),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = _ctx_with_transit(date(2027, 2, 8), sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    names = [task.name for task in tasks]
    assert "Suhoor" in names
    assert "Iftar" in names
    assert "Tarawih" in names
    assert "Frühstück" not in names
    assert "Abendessen" not in names

    iftar = next(task for task in tasks if task.name == "Iftar")
    tarawih = next(task for task in tasks if task.name == "Tarawih")
    isha = next(task for task in tasks if task.name.startswith("Isha"))
    assert iftar.start == time(16, 45)
    assert tarawih.start > isha.start


def test_laylat_al_qadr_uses_qiyam_instead_of_tahajjud_with_witr_and_suhoor():
    sched = SimpleNamespace(
        fajr=time(5, 30),
        sunrise=time(7, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    ctx = _ctx_with_transit(date(2027, 2, 28), sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    names = [task.name for task in tasks]
    assert "Qiyam al-Layl" in names
    assert "Tahajjud" not in names
    assert "Witr" in names
    assert "Suhoor" in names
    assert "Tarawih" in names

    qiyam = next(task for task in tasks if task.name == "Qiyam al-Layl")
    witr = next(task for task in tasks if task.name == "Witr")
    suhoor = next(task for task in tasks if task.name == "Suhoor")
    assert qiyam.start < witr.start < suhoor.start


def test_eid_al_adha_has_eid_prayer_qurban_and_no_breakfast():
    sched = SimpleNamespace(
        fajr=time(4, 30),
        sunrise=time(6, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(19, 0),
        isha=time(21, 0),
    )
    ctx = _ctx_with_transit(date(2027, 5, 16), sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    names = [task.name for task in tasks]
    assert "Eid-Gebet" in names
    assert "Qurban" in names
    assert "Fleisch verteilen" in names
    assert "Frühstück" not in names

    prayer = next(task for task in tasks if task.name == "Eid-Gebet")
    sacrifice = next(task for task in tasks if task.name == "Qurban")
    assert prayer.start == time(6, 15)
    assert sacrifice.start > prayer.start


def test_qurban_days_after_the_first_are_not_fasting_days():
    sched = SimpleNamespace(
        fajr=time(4, 30),
        sunrise=time(6, 0),
        dhuhr=time(12, 0),
        asr=time(14, 0),
        maghrib=time(19, 0),
        isha=time(21, 0),
    )
    ctx = _ctx_with_transit(date(2027, 5, 17), sched, _DEFAULT_TRANSIT)

    tasks = gebetsplan._studienplan(ctx)
    names = [task.name for task in tasks]
    assert "Frühstück" in names
    assert "Qurban" not in names
    assert "Suhoor" not in names
