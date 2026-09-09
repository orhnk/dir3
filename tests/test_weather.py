"""Weather is tied to the *plan's* city - never a hardcoded default."""
from datetime import date

from dir3.services.geo import GeoLocation
from dir3.services.weather import WeatherService

DAY = date(2026, 9, 7)


def _is_rainy_response(url, params=None, timeout=None, headers=None):
    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "weather": [
                    {
                        "date": DAY.isoformat(),
                        "hourly": [{"chanceofrain": "80"}, {"chanceofrain": "10"}],
                    }
                ]
            }

    return _Response()


def _no_rainy_response(url, params=None, timeout=None, headers=None):
    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "weather": [
                    {
                        "date": DAY.isoformat(),
                        "hourly": [{"chanceofrain": "10"}],
                    }
                ]
            }

    return _Response()


def test_weather_uses_plan_city(monkeypatch, tmp_path):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        return _is_rainy_response(url)

    monkeypatch.setattr("dir3.services.weather.requests.get", fake_get)
    gebze = GeoLocation(40.7992, 29.4305, "Europe/Istanbul", "Gebze", "Türkiye")
    service = WeatherService(location_getter=lambda: gebze,
                             cache_path=tmp_path / "weather.json")
    assert service.is_rainy(DAY) is True
    assert "Gebze" in captured["url"]


def test_weather_no_city_returns_none_without_network(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("network must not be touched")

    monkeypatch.setattr("dir3.services.weather.requests.get", boom)
    service = WeatherService(cache_path=tmp_path / "weather.json")
    assert service.is_rainy(DAY) is None


def test_weather_explicit_city_overrides_location(monkeypatch, tmp_path):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        return _no_rainy_response(url)

    monkeypatch.setattr("dir3.services.weather.requests.get", fake_get)
    elsewhere = GeoLocation(52.52, 13.405, "Europe/Berlin", "Berlin", "Deutschland")
    service = WeatherService(location_getter=lambda: elsewhere,
                             cache_path=tmp_path / "weather.json")
    assert service.is_rainy(DAY, "Gebze") is False
    assert "Gebze" in captured["url"]


def test_weather_network_failure_returns_none(monkeypatch, tmp_path):
    import requests

    def fail(*args, **kwargs):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr("dir3.services.weather.requests.get", fail)
    gebze = GeoLocation(40.7992, 29.4305, "Europe/Istanbul", "Gebze", "Türkiye")
    service = WeatherService(location_getter=lambda: gebze,
                             cache_path=tmp_path / "weather.json")
    assert service.is_rainy(DAY) is None
