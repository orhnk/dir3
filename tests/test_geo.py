"""Planfile-Konfiguration (keine TOML) und Geolocation."""
from types import SimpleNamespace as _M

import pytest

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
    assert config.prayer.provider == "ezanvakti"
    assert config.prayer.method == "MWL"


def test_planfile_provider_shortcut():
    config = Dir3Config.from_planfile(_M(provider="offline"))
    assert config.prayer.provider == "offline"


def test_planfile_prayer_dict():
    config = Dir3Config.from_planfile(_M(prayer={"provider": "aladhan", "madhab": "Hanafi"}))
    assert config.prayer.provider == "aladhan"
    assert config.prayer.madhab == "Hanafi"


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


def test_geo_ip_detect_sends_user_agent(monkeypatch):
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
    location = GeoLocator(Dir3Config()).detect()
    assert "User-Agent" in captured["headers"]
    assert location == GeoLocation(40.8, 29.43, "Europe/Istanbul", "Gebze", "Türkiye")
