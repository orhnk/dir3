"""Prayer-time calc (offline fallback) and caching, mirroring munazzim's layering."""
from datetime import date, time

from dir3.config import Dir3Config, LocationSettings, PrayerSettings
from dir3.services import PrayerService
from dir3.services.geo import GeoLocation
from dir3.services.prayer import ALADHAN_METHODS, IslamicCalculator, PrayerSchedule

BERLIN = GeoLocation(
    latitude=52.52,
    longitude=13.405,
    timezone="Europe/Berlin",
    city="Berlin",
    country="Deutschland",
)

WINTER = date(2026, 12, 15)
SUMMER = date(2026, 6, 15)


def test_offline_calculation_ordering_winter():
    # On a short winter day every prayer falls in chronological order without wrap.
    calc = IslamicCalculator(method="MWL", madhab="Shafi")
    schedule = calc.compute(WINTER, BERLIN)
    assert (
        schedule.fajr
        < schedule.sunrise
        < schedule.dhuhr
        < schedule.asr
        < schedule.maghrib
        < schedule.isha
    )


def test_offline_hours_reasonable_berlin_winter():
    calc = IslamicCalculator(method="Turkey", madhab="Hanafi")
    schedule = calc.compute(WINTER, BERLIN)
    # Berlin mid-December: dawn ~06:00, sunset ~15:55, isha ~17:40 (sys without wrap)
    assert time(5, 0) <= schedule.fajr <= time(7, 30)
    assert schedule.dhuhr.hour in (11, 12)
    assert time(15, 0) <= schedule.maghrib <= time(17, 0)
    assert time(16, 0) <= schedule.isha <= time(19, 30)
    assert schedule.fajr < schedule.maghrib


def test_madhab_changes_asr():
    shafi = IslamicCalculator(method="MWL", madhab="Shafi").compute(SUMMER, BERLIN)
    hanafi = IslamicCalculator(method="MWL", madhab="Hanafi").compute(SUMMER, BERLIN)
    # Hanafi asr is later (double shadow) than Shafi asr.
    assert hanafi.asr > shafi.asr


def test_service_offline_cache_roundtrip(tmp_path, monkeypatch):
    config = Dir3Config(
        location=LocationSettings(
            latitude=BERLIN.latitude, longitude=BERLIN.longitude, timezone=BERLIN.timezone
        ),
        prayer=PrayerSettings(provider="offline"),
    )
    monkeypatch.setattr("dir3.services.prayer.DEFAULT_CACHE_DIR", tmp_path)
    service = PrayerService(config)
    sched = service.get(WINTER)
    assert isinstance(sched, PrayerSchedule)
    # cached second call reads from disk cache fresh in a new instance
    service2 = PrayerService(config)
    assert service2.get(WINTER) == sched


def test_aladhan_method_mapping():
    assert ALADHAN_METHODS["MWL"] == 3
    assert "Turkey" in ALADHAN_METHODS


def test_prayer_schedule_dict_roundtrip():
    schedule = IslamicCalculator(method="MWL", madhab="Shafi").compute(SUMMER, BERLIN)
    restored = PrayerSchedule.from_dict(schedule.to_dict())
    assert restored == schedule
