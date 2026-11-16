"""Prayer times via Caelestia/Salat method (cache → Aladhan month → offline)."""
from datetime import date, time

from dir3.config import Dir3Config, LocationSettings, PrayerSettings
from dir3.services import PrayerService
from dir3.services.geo import GeoLocation
from dir3.services.prayer import (
    PrayerSchedule,
    angles_for,
    clean_time,
    haversine_km,
    month_cache_key,
    offline_compute,
    parse_minutes,
)

BERLIN = GeoLocation(
    latitude=52.52,
    longitude=13.405,
    timezone="Europe/Berlin",
    city="Berlin",
    country="Deutschland",
)

GEBZE = GeoLocation(
    latitude=40.7992,
    longitude=29.4305,
    timezone="Europe/Istanbul",
    city="Gebze",
    country="Türkiye",
)

WINTER = date(2026, 12, 15)
SUMMER = date(2026, 6, 15)


def _cfg(
    provider: str = "auto",
    method: int = 13,
    school: int = 0,
    method_auto: bool = False,
) -> Dir3Config:
    return Dir3Config(
        location=LocationSettings(
            latitude=GEBZE.latitude, longitude=GEBZE.longitude, timezone=GEBZE.timezone
        ),
        prayer=PrayerSettings(
            provider=provider, method=method, school=school, method_auto=method_auto
        ),
    )


def _use_tmp_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("dir3.services.prayer.DEFAULT_CACHE_DIR", tmp_path)


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


def _router(responses: dict[str, object]):
    """Return a requests.get stand-in that routes by URL prefix."""

    def fake_get(url, params=None, timeout=None):
        for prefix, payload in responses.items():
            if url.startswith(prefix):
                if isinstance(payload, Exception):
                    raise payload
                if callable(payload):
                    return _FakeResponse(payload(url, params))
                return _FakeResponse(payload)
        raise AssertionError(f"Unhandled URL: {url}")

    return fake_get


def requests_network_error():
    import requests

    return requests.RequestException("network down")


# --- offline solar fallback (Salat.offlineCompute) ---------------------------


def test_offline_calculation_ordering_winter():
    schedule = offline_compute(WINTER, BERLIN, method=3, school=0)
    assert (
        schedule.fajr
        < schedule.sunrise
        < schedule.dhuhr
        < schedule.asr
        < schedule.maghrib
        < schedule.isha
    )


def test_offline_hours_reasonable_berlin_winter():
    schedule = offline_compute(WINTER, BERLIN, method=13, school=1)
    assert time(5, 0) <= schedule.fajr <= time(7, 30)
    assert schedule.dhuhr.hour in (11, 12)
    assert time(15, 0) <= schedule.maghrib <= time(17, 0)
    assert time(16, 0) <= schedule.isha <= time(19, 30)
    assert schedule.fajr < schedule.maghrib


def test_school_changes_asr():
    shafi = offline_compute(SUMMER, BERLIN, method=3, school=0)
    hanafi = offline_compute(SUMMER, BERLIN, method=3, school=1)
    assert hanafi.asr > shafi.asr


def test_offline_isha_interval_for_makkah_style():
    params = {4: {"fajr": 18.5, "ishaAngle": None, "ishaInterval": 90}}
    schedule = offline_compute(SUMMER, GEBZE, method=4, school=0, method_params=params)
    assert schedule.isha > schedule.maghrib


def test_prayer_schedule_dict_roundtrip():
    schedule = offline_compute(SUMMER, BERLIN, method=3, school=0)
    assert PrayerSchedule.from_dict(schedule.to_dict()) == schedule


# --- Caelestia helpers -------------------------------------------------------


def test_parse_minutes():
    assert parse_minutes("90 min") == 90
    assert parse_minutes("77 min (test)") == 77
    assert parse_minutes("18") == -1
    assert parse_minutes(None) == -1


def test_clean_time_strips_suffix():
    assert clean_time("04:59 (EET)") == "04:59"
    assert clean_time("06:27") == "06:27"


def test_haversine_nearest():
    # Gebze is closer to Istanbul-anchored authority than to Berlin.
    assert haversine_km(40.8, 29.43, 41.0, 29.0) < haversine_km(40.8, 29.43, 52.5, 13.4)


def test_angles_for_fallback_table():
    assert angles_for(1, None) == (18.0, 18.0, -1)
    assert angles_for(2, None) == (15.0, 15.0, -1)
    assert angles_for(13, None) == (18.0, 17.0, -1)
    assert angles_for(999, None) == (18.0, 17.0, -1)


def test_angles_for_live_table_wins():
    params = {13: {"fajr": 18.0, "ishaAngle": None, "ishaInterval": 90}}
    assert angles_for(13, params) == (18.0, None, 90)


def test_month_cache_key_tags_method_school():
    key = month_cache_key(40.79925, 29.43054, 13, 0, 2026, 9)
    assert key == "40.7993,29.4305|m13s0|2026-9"
    assert month_cache_key(40.7992, 29.4305, 3, 0, 2026, 9) != key
    assert month_cache_key(40.7992, 29.4305, 13, 1, 2026, 9) != key


# --- methods table / auto pick ----------------------------------------------


def test_pick_method_for_loc_nearest_authority():
    service = PrayerService(_cfg(method_auto=True))
    service.method_list = [
        {"id": 3, "name": "MWL", "lat": 52.0, "lon": 13.0},
        {"id": 13, "name": "Turkey", "lat": 41.0, "lon": 29.0},
        {"id": 15, "name": "Moonsighting", "lat": None, "lon": None},
    ]
    assert service.pick_method_for_loc(40.8, 29.43) == 13
    assert service.pick_method_for_loc(52.5, 13.4) == 3


def test_pick_method_undecidable_returns_minus_one():
    service = PrayerService(_cfg(method_auto=True))
    service.method_list = [{"id": 15, "name": "X", "lat": None, "lon": None}]
    assert service.pick_method_for_loc(40.8, 29.43) == -1


def test_resolve_method_explicit_wins_without_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr("dir3.services.prayer.requests.get", boom)
    service = PrayerService(_cfg(method=3, method_auto=False))
    assert service.resolve_method(40.8, 29.43) == 3


def test_resolve_method_auto_falls_back_to_13_when_table_unavailable(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "dir3.services.prayer.requests.get", _router({"https://x": requests_network_error()})
    )
    # Point methods fetch at failing host by monkeypatching URL? Instead force
    # ensure_methods to fail by emptying cache and failing fetch.
    service = PrayerService(_cfg(method_auto=True))
    service.method_list = []
    monkeypatch.setattr(service, "fetch_methods", lambda: False)
    assert service.resolve_method(40.8, 29.43, use_network=False) == 13


def test_fetch_methods_parses_live_table(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)

    def methods_payload(url, params):
        return {
            "data": {
                "MWL": {
                    "id": 3,
                    "name": "Muslim World League",
                    "params": {"Fajr": 18, "Isha": 17},
                    "location": {"latitude": 51.5, "longitude": -0.12},
                },
                "Makkah": {
                    "id": 4,
                    "name": "Umm al-Qura",
                    "params": {"Fajr": 18.5, "Isha": "90 min"},
                    "location": {"latitude": 21.4, "longitude": 39.8},
                },
            }
        }

    monkeypatch.setattr(
        "dir3.services.prayer.requests.get",
        _router({"https://api.aladhan.com/v1/methods": methods_payload}),
    )
    service = PrayerService(_cfg(method_auto=True))
    assert service.fetch_methods() is True
    assert service.method_params[3] == {"fajr": 18.0, "ishaAngle": 17.0, "ishaInterval": -1}
    assert service.method_params[4] == {"fajr": 18.5, "ishaAngle": None, "ishaInterval": 90}
    assert service.pick_method_for_loc(51.5, -0.1) == 3


# --- service layering: cache → Aladhan month → offline -----------------------


def test_service_offline_cache_roundtrip(tmp_path, monkeypatch):
    _use_tmp_cache(monkeypatch, tmp_path)
    config = Dir3Config(
        location=LocationSettings(
            latitude=BERLIN.latitude, longitude=BERLIN.longitude, timezone=BERLIN.timezone
        ),
        prayer=PrayerSettings(provider="offline", method=3, school=0, method_auto=False),
    )
    service = PrayerService(config)
    sched = service.get(WINTER)
    assert isinstance(sched, PrayerSchedule)
    service2 = PrayerService(config)
    # Deterministic offline recompute (and cached month) → same times.
    assert service2.get(WINTER) == sched


def test_auto_provider_prefers_aladhan(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)

    def calendar_payload(url, params):
        assert params["method"] == 13
        assert params["school"] == 0
        return {
            "data": [
                {
                    "timings": {
                        "Fajr": "04:59 (EET)",
                        "Sunrise": "06:27 (EET)",
                        "Dhuhr": "13:05 (EET)",
                        "Asr": "16:43 (EET)",
                        "Maghrib": "19:33 (EET)",
                        "Isha": "20:55 (EET)",
                    },
                    "date": {"gregorian": {"date": "07-09-2026"}},
                }
            ]
        }

    monkeypatch.setattr(
        "dir3.services.prayer.requests.get",
        _router({"https://api.aladhan.com/v1/calendar/": calendar_payload}),
    )
    service = PrayerService(_cfg(provider="auto", method=13, school=0, method_auto=False))
    schedule = service.get(date(2026, 9, 7), GEBZE)
    assert schedule.fajr == time(4, 59)
    assert service.source == "aladhan"
    # Cached second call must not touch the network (same instance).
    def boom(*a, **k):
        raise AssertionError("network must not be touched on cache hit")

    monkeypatch.setattr("dir3.services.prayer.requests.get", boom)
    assert service.get(date(2026, 9, 7), GEBZE).fajr == time(4, 59)
    assert service.source == "cache"


def test_aladhan_fetches_one_calendar_request_for_whole_month(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    calls: list[str] = []

    def calendar_payload(url, params):
        month = int(url.rsplit("/", 1)[1])
        return {
            "data": [
                {
                    "timings": {
                        "Fajr": f"04:{(month + d) % 60:02d}",
                        "Sunrise": "06:27",
                        "Dhuhr": "13:00",
                        "Asr": "16:00",
                        "Maghrib": "19:00",
                        "Isha": "20:00",
                    },
                    "date": {"gregorian": {"date": f"{d:02d}-09-2026"}},
                }
                for d in range(1, 31)
            ]
        }

    def fake_get(url, params=None, timeout=None):
        calls.append(url)

        class _R:
            def raise_for_status(self):
                pass

            def json(self):
                return calendar_payload(url, params)

        return _R()

    monkeypatch.setattr("dir3.services.prayer.requests.get", fake_get)
    service = PrayerService(_cfg(provider="auto", method=13, school=0, method_auto=False))
    for day_num in (3, 17, 29):
        service.get(date(2026, 9, day_num), GEBZE)
    assert len(calls) == 1
    assert service.get(date(2026, 9, 17), GEBZE).fajr == time(4, 26)


def test_incomplete_aladhan_day_falls_back_to_offline(monkeypatch, tmp_path):
    """Days missing any of the six timings are discarded (no synthetic fill)."""
    _use_tmp_cache(monkeypatch, tmp_path)

    def calendar_payload(url, params):
        return {
            "data": [
                {
                    "timings": {"Fajr": "04:59", "Dhuhr": "13:05"},
                    "date": {"gregorian": {"date": "07-09-2026"}},
                }
            ]
        }

    monkeypatch.setattr(
        "dir3.services.prayer.requests.get",
        _router({"https://api.aladhan.com/v1/calendar/": calendar_payload}),
    )
    service = PrayerService(_cfg(provider="auto", method=13, school=0, method_auto=False))
    schedule = service.get(date(2026, 9, 7), GEBZE)
    assert isinstance(schedule, PrayerSchedule)
    assert service.source == "offline"
    # Offline fallback is chronological even when Aladhan gave garbage.
    assert schedule.fajr < schedule.sunrise < schedule.dhuhr


def test_auto_falls_back_to_offline_on_network_failure(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "dir3.services.prayer.requests.get",
        _router({"https://api.aladhan.com": requests_network_error()}),
    )
    service = PrayerService(_cfg(provider="auto", method=13, school=0, method_auto=False))
    schedule = service.get(SUMMER, GEBZE)
    assert isinstance(schedule, PrayerSchedule)
    assert service.source == "offline"


def test_method_school_scoped_cache_no_leak(monkeypatch, tmp_path):
    """Same day/location but different method/school must not share times."""
    _use_tmp_cache(monkeypatch, tmp_path)

    def calendar_payload(url, params):
        fajr = "04:00" if params["method"] == 13 else "05:00"
        return {
            "data": [
                {
                    "timings": {
                        "Fajr": fajr,
                        "Sunrise": "06:27",
                        "Dhuhr": "13:00",
                        "Asr": "16:00",
                        "Maghrib": "19:00",
                        "Isha": "20:00",
                    },
                    "date": {"gregorian": {"date": "15-12-2026"}},
                }
            ]
        }

    monkeypatch.setattr(
        "dir3.services.prayer.requests.get",
        _router({"https://api.aladhan.com/v1/calendar/": calendar_payload}),
    )
    s13 = PrayerService(_cfg(provider="auto", method=13, school=0, method_auto=False))
    s03 = PrayerService(_cfg(provider="auto", method=3, school=0, method_auto=False))
    assert s13.get(WINTER, GEBZE).fajr == time(4, 0)
    assert s03.get(WINTER, GEBZE).fajr == time(5, 0)
