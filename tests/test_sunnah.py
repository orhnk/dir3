"""Sunnah event helpers: Rawatib, Witr, Duha, Adhkar, Quran and seasonal acts."""

from datetime import date, time, timedelta
from types import SimpleNamespace

from dir3 import (
    AdhkarSettings,
    AwwabinSettings,
    DuhaSettings,
    EidFitrSettings,
    NightSettings,
    QiyamSettings,
    QuranSettings,
    RawatibSettings,
    SunnahFastSettings,
    WitrSettings,
    adhkar_events,
    awwabin,
    duha,
    eid_fitr_events,
    eid_fitr_prayer,
    is_fasting_day,
    is_first_nine_dhul_hijjah,
    is_last_ten_nights,
    is_laylat_al_qadr_candidate,
    is_sunnah_fast,
    itikaf,
    itikaf_events,
    laylat_al_qadr_qiyam,
    night_events,
    qiyam,
    quran,
    rawatib_events,
    sunnah_fast_name,
    witr,
)

SCHED = SimpleNamespace(
    fajr=time(5, 0),
    sunrise=time(7, 0),
    dhuhr=time(12, 30),
    asr=time(15, 30),
    maghrib=time(18, 0),
    isha=time(19, 30),
)

EID_FITR = date(2027, 3, 9)
RAMADAN_21 = date(2027, 2, 28)
RAMADAN_20 = date(2027, 2, 27)


def test_rawatib_blocks_cover_the_twelve_sunnah_rakahs():
    events = [
        (task.name, task.start, task.duration) for _, task in rawatib_events(SCHED)
    ]

    assert events == [
        ("Rawatib Fajr (2)", time(4, 50), timedelta(minutes=10)),
        ("Rawatib Dhuhr vor (4)", time(12, 10), timedelta(minutes=20)),
        ("Rawatib Dhuhr nach (2)", time(12, 45), timedelta(minutes=10)),
        ("Rawatib Maghrib nach (2)", time(18, 15), timedelta(minutes=10)),
        ("Rawatib Isha nach (2)", time(19, 45), timedelta(minutes=10)),
    ]


def test_rawatib_can_add_the_non_emphasised_blocks():
    settings = RawatibSettings(asr_before=4, maghrib_before=2, isha_before=2)
    events = [
        (task.name, task.start, task.duration)
        for _, task in rawatib_events(SCHED, settings)
    ]

    assert ("Rawatib Asr vor (4)", time(15, 10), timedelta(minutes=20)) in events
    assert ("Rawatib Maghrib vor (2)", time(17, 50), timedelta(minutes=10)) in events
    assert ("Rawatib Isha vor (2)", time(19, 20), timedelta(minutes=10)) in events


def test_witr_defaults_after_isha_and_accepts_explicit_start():
    minute, block = witr(SCHED)
    assert (minute, block.start, block.duration) == (
        19 * 60 + 55,
        time(19, 55),
        timedelta(minutes=10),
    )

    minute, block = witr(SCHED, WitrSettings(minutes=15), start=4 * 60 + 30)
    assert (minute, block.start, block.duration) == (
        4 * 60 + 30,
        time(4, 30),
        timedelta(minutes=15),
    )


def test_awwabin_sits_between_maghrib_and_isha():
    minute, block = awwabin(SCHED)
    assert (minute, block.start, block.duration) == (
        18 * 60 + 25,
        time(18, 25),
        timedelta(minutes=20),
    )

    minute, block = awwabin(SCHED, AwwabinSettings(delay=10, minutes=15, name="Awwabin"))
    assert (minute, block.start) == (18 * 60 + 10, time(18, 10))


def test_duha_starts_after_sunrise_and_can_use_the_best_time():
    minute, block = duha(SCHED)
    assert (minute, block.start) == (7 * 60 + 15, time(7, 15))

    minute, block = duha(SCHED, DuhaSettings(at_best_time=True))
    assert (minute, block.start) == (9 * 60 + 45, time(9, 45))


def test_adhkar_are_after_fajr_and_after_asr():
    events = [
        (task.name, task.start, task.duration)
        for _, task in adhkar_events(SCHED, AdhkarSettings())
    ]

    assert events == [
        ("Morgen-Adhkar", time(5, 5), timedelta(minutes=15)),
        ("Abend-Adhkar", time(15, 35), timedelta(minutes=15)),
    ]


def test_quran_uses_its_anchor():
    minute, block = quran(SCHED)
    assert (minute, block.start) == (5 * 60 + 20, time(5, 20))

    minute, block = quran(SCHED, QuranSettings(anchor="isha", delay=0, minutes=30))
    assert (minute, block.start, block.duration) == (
        19 * 60 + 30,
        time(19, 30),
        timedelta(minutes=30),
    )


def test_eid_fitr_prayer_is_only_on_eid_day():
    assert eid_fitr_events(date(2027, 3, 10), SCHED) == []

    events = eid_fitr_events(EID_FITR, SCHED, EidFitrSettings())
    assert [(task.name, task.start, task.duration) for _, task in events] == [
        ("Eid al-Fitr prayer", time(7, 15), timedelta(minutes=30)),
    ]


def test_eid_fitr_individual_helper_returns_minute_and_task():
    minute, block = eid_fitr_prayer(SCHED)
    assert minute == 7 * 60 + 15
    assert block.name == "Eid al-Fitr prayer"


def test_itikaf_runs_from_the_evening_into_the_last_ten_nights():
    before = RAMADAN_20 - timedelta(days=1)
    assert itikaf(before, SCHED) is None
    assert itikaf_events(before, SCHED) == []

    minute, block = itikaf(RAMADAN_20, SCHED)
    assert (minute, block.name, block.start, block.until) == (
        19 * 60 + 40,
        "I'tikaf",
        time(19, 40),
        time(5, 0),
    )
    assert is_last_ten_nights(RAMADAN_20 + timedelta(days=1))
    assert not is_last_ten_nights(RAMADAN_20)


def test_qiyam_sits_in_the_last_third_and_laylat_al_qadr_is_conditional():
    minute, block = qiyam(SCHED, QiyamSettings(minutes=30, before_fajr=60))
    assert (minute, block.start, block.until) == (3 * 60 + 30, time(3, 30), time(4, 0))

    assert laylat_al_qadr_qiyam(RAMADAN_20, SCHED) is None
    assert laylat_al_qadr_qiyam(RAMADAN_21, SCHED) is not None
    assert is_laylat_al_qadr_candidate(RAMADAN_21)
    assert not is_laylat_al_qadr_candidate(RAMADAN_20)


def test_sunnah_fast_predicates_cover_specific_and_recurring_days():
    settings = SunnahFastSettings()
    assert sunnah_fast_name(date(2027, 6, 15), settings) == "Ashura"
    assert sunnah_fast_name(date(2027, 6, 14), settings) == "Tasu'a"
    assert sunnah_fast_name(date(2027, 5, 15), settings) == "Arafah"
    assert sunnah_fast_name(date(2026, 10, 24), settings) == "Ayyam al-Biyd"
    assert sunnah_fast_name(date(2026, 11, 2), settings) == "Montag/Donnerstag"
    assert sunnah_fast_name(date(2027, 2, 9), settings) is None  # Ramadan
    assert sunnah_fast_name(date(2027, 3, 9), settings) is None  # Eid al-Fitr


def test_sunnah_fast_settings_can_select_dhul_hijjah_shawwal_and_dawud():
    first_nine = SunnahFastSettings(first_nine_dhul_hijjah=True)
    assert sunnah_fast_name(date(2027, 5, 7), first_nine) == "Dhul-Hijjah"
    assert sunnah_fast_name(date(2027, 5, 7), SunnahFastSettings()) is None

    shawwal = SunnahFastSettings(shawwal_days=frozenset({2}))
    assert sunnah_fast_name(date(2027, 3, 10), shawwal) == "Shawwal"

    dawud = SunnahFastSettings(
        monday_thursday=False,
        ayyam_al_biyd=False,
        ashura=False,
        tasua=False,
        arafah=False,
        dawud_start=date(2027, 1, 1),
    )
    assert sunnah_fast_name(date(2027, 1, 1), dawud) == "Dawud"
    assert sunnah_fast_name(date(2027, 1, 2), dawud) is None
    assert sunnah_fast_name(date(2027, 1, 3), dawud) == "Dawud"
    assert sunnah_fast_name(date(2026, 12, 31), dawud) is None


def test_is_sunnah_fast_and_fasting_day_include_seasonal_days():
    settings = SunnahFastSettings()
    assert is_sunnah_fast(date(2027, 6, 15), settings)
    assert is_fasting_day(date(2027, 6, 15), sunnah_fasts=settings)
    assert not is_fasting_day(date(2027, 3, 9), sunnah_fasts=settings)


def test_first_nine_dhul_hijjah_predicate_covers_arafah():
    assert is_first_nine_dhul_hijjah(date(2027, 5, 7))
    assert is_first_nine_dhul_hijjah(date(2027, 5, 15))
    assert not is_first_nine_dhul_hijjah(date(2027, 5, 16))


def test_night_events_add_suhoor_on_a_seasonal_fast():
    night_sched = SimpleNamespace(
        fajr=time(5, 0),
        sunrise=time(7, 0),
        maghrib=time(16, 30),
        isha=time(18, 10),
    )
    settings = NightSettings(fasts=SunnahFastSettings())

    events = [
        (task.name, task.start, task.until)
        for _, task in night_events(date(2027, 6, 15), night_sched, settings)
    ]

    assert events == [
        ("Suhoor", time(4, 30), time(5, 0)),
        ("Schlafen", time(5, 0), time(6, 15)),
    ]
