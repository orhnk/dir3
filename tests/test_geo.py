"""Planfile-Konfiguration (keine TOML) und Geolocation."""
import json
from datetime import datetime
from types import SimpleNamespace as _M

import pytest
import requests

from dir3 import Dir3Config, LocationSettings, PrayerSettings
from dir3.services.geo import GeoLocation, GeoLocator


def test_planfile_tuple_location_override():
    config = Dir3Config.from_planfile(_M(location=(48.1374, 11.5754, "Europe/Berlin")))
    assert config.location.latitude == 48.1374
    assert config.location.longitude == 11.5754
    assert config.location.timezone == "Europe/Berlin"
    assert config.location.use_geolocation is True


def test_planfile_prayer_override_string():
    config = Dir3Config.from_planfile(_M(prayer="ezanvakti"))
    # EzanVakti provider was removed; maps to explicit Turkey/Diyanet method.
    assert config.prayer.provider == "auto"
    assert config.prayer.method == 13
    assert config.prayer.method_auto is False


def test_planfile_provider_shortcut():
    config = Dir3Config.from_planfile(_M(provider="offline"))
    assert config.prayer.provider == "offline"


def test_planfile_prayer_dict():
    config = Dir3Config.from_planfile(_M(prayer={"provider": "aladhan", "madhab": "Hanafi"}))
    assert config.prayer.provider == "auto"
    assert config.prayer.school == 1


def test_planfile_prayer_legacy_method_name():
    config = Dir3Config.from_planfile(_M(prayer={"method": "MWL"}))
    assert config.prayer.method == 3
    assert config.prayer.method_auto is False


def test_planfile_prayer_explicit_caelestia():
    config = Dir3Config.from_planfile(_M(prayer={"method": 13, "school": 1}))
    assert config.prayer.method == 13
    assert config.prayer.school == 1
    assert config.prayer.method_auto is False


def test_planfile_settings_instances():
    location = LocationSettings(latitude=1, longitude=2, timezone="UTC", city="X")
    prayer = PrayerSettings(provider="diyanet")
    config = Dir3Config.from_planfile(_M(location=location, prayer=prayer))
    assert config.location is location
    assert config.prayer is prayer


def test_planfile_empty_defaults_to_auto_detect():
    config = Dir3Config.from_planfile(_M())
    assert config.location.use_geolocation is True
    assert config.prayer.provider == "auto"


def test_geo_uses_planfile_coords_without_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr("dir3.services.geo.requests.get", boom)
    config = Dir3Config.from_planfile(_M(location=(48.1374, 11.5754, "UTC")))
    location = GeoLocator(config).detect()
    assert location.latitude == 48.1374
    assert location.longitude == 11.5754


def test_geo_error_when_no_location_and_no_ip(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr("dir3.services.geo.requests.get", boom)
    config = Dir3Config(
        location=LocationSettings(use_geolocation=False),
    )
    with pytest.raises(RuntimeError, match="Standort nicht bestimmbar"):
        GeoLocator(config).detect()


def test_geo_ip_detect_sends_user_agent(monkeypatch, tmp_path):
    captured = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        captured["headers"] = headers
        class _Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"latitude": 40.8, "longitude": 29.43,
                        "timezone": "Europe/Istanbul", "city": "Gebze",
                        "country_name": "Türkiye"}

        return _Response()

    monkeypatch.setattr("dir3.services.geo.requests.get", fake_get)
    location = GeoLocator(Dir3Config(), cache_path=tmp_path / "geo.json").detect()
    assert "User-Agent" in captured["headers"]
    assert location == GeoLocation(40.8, 29.43, "Europe/Istanbul", "Gebze", "Türkiye")


def _ipapi_response(payload, *, status=200):
    class _Response:
        status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"{self.status_code}")

        def json(self):
            return payload

    return _Response()


def test_geo_result_is_cached_and_reused_offline(monkeypatch, tmp_path):
    payload = {"latitude": 40.8, "longitude": 29.43, "timezone": "Europe/Istanbul",
               "city": "Gebze", "country_name": "Türkiye"}
    cache = tmp_path / "geo.json"
    fresh = {"calls": 0}

    def fake_get(url, params=None, timeout=None, headers=None):
        fresh["calls"] += 1
        return _ipapi_response(payload)

    monkeypatch.setattr("dir3.services.geo.requests.get", fake_get)
    first = GeoLocator(Dir3Config(), cache_path=cache).detect()
    assert first == GeoLocation(40.8, 29.43, "Europe/Istanbul", "Gebze", "Türkiye")

    def offline_get(*args, **kwargs):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr("dir3.services.geo.requests.get", offline_get)
    second = GeoLocator(Dir3Config(), cache_path=cache).detect()
    assert second == first
    assert fresh["calls"] == 1


def test_geo_retries_rate_limit_then_succeeds(monkeypatch, tmp_path):
    payload = {"latitude": 40.8, "longitude": 29.43, "timezone": "Europe/Istanbul",
               "city": "Gebze", "country_name": "Türkiye"}
    attempts = {"n": 0}

    def fake_get(url, params=None, timeout=None, headers=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return _ipapi_response({}, status=429)
        return _ipapi_response(payload)

    monkeypatch.setattr("dir3.services.geo.requests.get", fake_get)
    monkeypatch.setattr("dir3.services.geo.time.sleep", lambda _: None)
    location = GeoLocator(Dir3Config(), cache_path=tmp_path / "geo.json").detect()
    assert location.city == "Gebze"
    assert attempts["n"] == 2


def test_geo_stale_cache_used_when_offline(monkeypatch, tmp_path):
    cache = tmp_path / "geo.json"
    cache.write_text(
        '{"fetched_at": "2020-01-01T00:00:00+00:00", "latitude": 40.8, '
        '"longitude": 29.43, "timezone": "Europe/Istanbul", "city": "Gebze", '
        '"country": "Türkiye"}',
        encoding="utf-8",
    )

    def offline_get(*args, **kwargs):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr("dir3.services.geo.requests.get", offline_get)
    location = GeoLocator(Dir3Config(), cache_path=cache).detect()
    assert location == GeoLocation(40.8, 29.43, "Europe/Istanbul", "Gebze", "Türkiye")


def test_geo_cache_refreshes_when_fresh_and_network_ok(monkeypatch, tmp_path):
    cache = tmp_path / "geo.json"
    cache.write_text(
        '{"fetched_at": "2020-01-01T00:00:00+00:00", "latitude": 40.8, '
        '"longitude": 29.43, "timezone": "Europe/Istanbul", "city": "Old", '
        '"country": "OL"}',
        encoding="utf-8",
    )
    payload = {"latitude": 48.1, "longitude": 11.5, "timezone": "Europe/Berlin",
               "city": "München", "country_name": "Deutschland"}

    def fake_get(url, params=None, timeout=None, headers=None):
        return _ipapi_response(payload)

    monkeypatch.setattr("dir3.services.geo.requests.get", fake_get)
    location = GeoLocator(Dir3Config(), cache_path=cache).detect()
    assert location.city == "München"  # stale cache was refreshed by the network
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["city"] == "München"
    assert datetime.fromisoformat(data["fetched_at"]).tzinfo is not None
