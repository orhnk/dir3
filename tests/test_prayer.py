"""Prayer-time calc (offline fallback) and caching, mirroring munazzim's layering."""
from datetime import date, time, timedelta

from dir3.config import Dir3Config, LocationSettings, PrayerSettings
from dir3.services import PrayerService
from dir3.services.geo import GeoLocation
from dir3.services.prayer import (
    ALADHAN_METHODS,
    AladhanProvider,
    EzanVaktiProvider,
    IslamicCalculator,
    PrayerSchedule,
    _from_ezanvakti_entry,
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


# --- EzanVakti (Diyanet) provider --------------------------------------------


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


_EZANVAKTI_DOMAIN = "https://ezanvakti.imsakiyem.com/api"


def _ezv_range_payload(url, params):
    start = date.fromisoformat(params["startDate"])
    end = date.fromisoformat(params["endDate"])
    entries = []
    day = start
    while day <= end:
        hour = 5 + (day.day % 3)
        entries.append(
            {
                "date": f"{day.isoformat()}T00:00:00.000Z",
                "times": {
                    "imsak": f"{hour:02d}:00",
                    "gunes": f"{hour + 1:02d}:28",
                    "ogle": "13:05",
                    "ikindi": "16:42",
                    "aksam": "19:33",
                    "yatsi": "20:56",
                },
            }
        )
        day += timedelta(days=1)
    return {"success": True, "data": entries}


def _ezv_lookup_payload(url, params):
    if url.endswith("/locations/countries"):
        return {"success": True, "data": [{"_id": "2", "name": "TÜRKİYE", "name_en": "TÜRKİYE"}]}
    return {
        "success": True,
        "data": [{"_id": "9651", "name": "GEBZE", "name_en": "GEBZE", "country_id": "2"}],
    }


def _ezv_responses() -> dict[str, object]:
    return {
        _EZANVAKTI_DOMAIN + "/locations/countries": _ezv_lookup_payload,
        _EZANVAKTI_DOMAIN + "/locations/search/districts": _ezv_lookup_payload,
        _EZANVAKTI_DOMAIN + "/prayer-times/9651/range": _ezv_range_payload,
    }


def test_ezanvakti_time_mapping():
    entry = {
        "date": "2026-09-07T00:00:00.000Z",
        "times": {
            "imsak": "05:00",
            "gunes": "06:28",
            "ogle": "13:05",
            "ikindi": "16:42",
            "aksam": "19:33",
            "yatsi": "20:56",
        },
    }
    assert _from_ezanvakti_entry(entry) == PrayerSchedule(
        fajr=time(5, 0),
        sunrise=time(6, 28),
        dhuhr=time(13, 5),
        asr=time(16, 42),
        maghrib=time(19, 33),
        isha=time(20, 56),
    )


def test_ezanvakti_provider_one_range_request_for_whole_window(monkeypatch):
    calls: list[str] = []
    responses = _ezv_responses()

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        for prefix, payload in responses.items():
            if url.startswith(prefix):
                return _FakeResponse(payload(url, params))
        raise AssertionError(f"Unhandled URL: {url}")

    monkeypatch.setattr("dir3.services.prayer.requests.get", fake_get)
    provider = EzanVaktiProvider()
    first = provider.fetch(date(2026, 9, 7), GEBZE, _cfg())
    second = provider.fetch(date(2026, 9, 8), GEBZE, _cfg())
    assert first.fajr == time(6, 0)  # 09-07 -> hour 5 + (7 % 3)
    assert second.fajr == time(7, 0)  # 09-08 -> hour 5 + (8 % 3)
    # country + district lookup each once, and ONE range request for both days.
    assert sum("countries" in c for c in calls) == 1
    assert sum("search/districts" in c for c in calls) == 1
    assert sum("range" in c for c in calls) == 1


def test_auto_provider_prefers_aladhan(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    calls: list[str] = []

    def calendar_payload(url, params):
        calls.append(url)
        return {
            "data": [
                {
                    "timings": {
                        "Fajr": "04:59 (EET)", "Sunrise": "06:27 (EET)",
                        "Dhuhr": "13:05 (EET)", "Asr": "16:43 (EET)",
                        "Maghrib": "19:33 (EET)", "Isha": "20:55 (EET)",
                    },
                    "date": {"gregorian": {"date": "07-09-2026"}},
                }
            ]
        }

    responses = {"https://api.aladhan.com/v1/calendar/": calendar_payload}
    monkeypatch.setattr("dir3.services.prayer.requests.get", _router(responses))
    service = PrayerService(_cfg(provider="auto"))
    schedule = service.get(date(2026, 9, 7), GEBZE)
    assert schedule.fajr == time(4, 59)
    assert service._cache[PrayerService._key("aladhan", date(2026, 9, 7), GEBZE)]


def test_aladhan_fetches_one_calendar_request_for_whole_month(monkeypatch):
    def calendar_payload(url, params):
        month = int(url.rsplit("/", 1)[1])
        entries = []
        for d in range(1, 31):
            entries.append(
                {
                    "timings": {
                        "Fajr": f"04:{(month + d) % 60:02d}",
                        "Sunrise": "06:27", "Dhuhr": "13:00", "Asr": "16:00",
                        "Maghrib": "19:00", "Isha": "20:00",
                    },
                    "date": {"gregorian": {"date": f"{d:02d}-09-2026"}},
                }
            )
        return {"data": entries}

    calls: list[str] = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return _FakeResponse(calendar_payload(url, params))

    monkeypatch.setattr("dir3.services.prayer.requests.get", fake_get)
    provider = AladhanProvider()
    cfg = _cfg(provider="aladhan")
    for day_num in (3, 17, 29):
        provider.fetch(date(2026, 9, day_num), GEBZE, cfg)
    assert len(calls) == 1  # one calendar request serves the whole month
    assert provider.fetch(date(2026, 9, 17), GEBZE, cfg).fajr == time(4, 26)  # 04 + (9+17)%60


def test_explicit_ezanvakti_provider(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    monkeypatch.setattr("dir3.services.prayer.requests.get", _router(_ezv_responses()))
    service = PrayerService(_cfg(provider="ezanvakti"))
    schedule = service.get(WINTER, GEBZE)  # 12-15 -> fajr 05:00
    assert schedule.fajr == time(5, 0)
    assert schedule.maghrib == time(19, 33)
    assert service._cache[PrayerService._key("ezanvakti", WINTER, GEBZE)]


def test_diyanet_alias_uses_ezanvakti_provider(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    monkeypatch.setattr("dir3.services.prayer.requests.get", _router(_ezv_responses()))
    service = PrayerService(_cfg(provider="diyanet"))
    schedule = service.get(WINTER, GEBZE)
    assert schedule.fajr == time(5, 0)
    assert service._cache[PrayerService._key("ezanvakti", WINTER, GEBZE)]


def test_explicit_provider_falls_back_to_calculator_on_network_failure(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "dir3.services.prayer.requests.get",
        _router({_EZANVAKTI_DOMAIN: requests_network_error()}),
    )
    service = PrayerService(_cfg(provider="ezanvakti"))
    schedule = service.get(SUMMER, GEBZE)
    assert isinstance(schedule, PrayerSchedule)
    # fallback is stored under its own provider-scoped key
    assert service._cache[PrayerService._key("offline", SUMMER, GEBZE)]


def test_provider_scoped_cache_no_cross_provider_leak(monkeypatch, tmp_path):
    _use_tmp_cache(monkeypatch, tmp_path)
    # Seed a cache entry produced under the "aladhan" key...
    service = PrayerService(_cfg(provider="auto"))
    service._cache[PrayerService._key("aladhan", WINTER, GEBZE)] = {
        "fajr": "04:59", "sunrise": "06:27", "dhuhr": "13:05",
        "asr": "16:43", "maghrib": "19:33", "isha": "20:55",
    }
    service._save_cache()
    # ...and verify an "ezanvakti" request does not read it (it fetches instead).
    monkeypatch.setattr("dir3.services.prayer.requests.get", _router(_ezv_responses()))
    service2 = PrayerService(_cfg(provider="ezanvakti"))
    assert service2.get(WINTER, GEBZE).fajr == time(5, 0)
    assert service2.get(WINTER, GEBZE) != service.get(WINTER, GEBZE, use_online=False)


def _cfg(provider: str = "auto") -> Dir3Config:
    return Dir3Config(
        location=LocationSettings(
            latitude=GEBZE.latitude, longitude=GEBZE.longitude, timezone=GEBZE.timezone
        ),
        prayer=PrayerSettings(provider=provider),
    )


def _use_tmp_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("dir3.services.prayer.DEFAULT_CACHE_DIR", tmp_path)


def requests_network_error() -> Exception:
    import requests

    return requests.RequestException("network down")
