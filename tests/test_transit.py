"""Transit journeys via a HAFAS-REST-compatible endpoint."""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import requests

from dir3.config import Dir3Config, LocationSettings, PrayerSettings, TransitSettings
from dir3.context import DayContext
from dir3.services import Services
from dir3.services.geo import GeoLocation
from dir3.services.transit import TransitJourney, TransitLeg, TransitService

TZ = ZoneInfo("Europe/Berlin")


def _config(endpoint: str = "https://vbb.test") -> Dir3Config:
    return Dir3Config(transit=TransitSettings(endpoint=endpoint, timezone="Europe/Berlin"))


def _stop(stop_id: str, name: str, lat: float, lon: float, distance: int | None = None):
    item = {
        "type": "stop",
        "id": stop_id,
        "name": name,
        "location": {"latitude": lat, "longitude": lon},
    }
    if distance is not None:
        item["distance"] = distance
    return item


STOPS = {
    "Mertensstr.": [_stop("900027254", "Mertensstr. (Berlin)", 52.56534, 13.209343)],
    "Galenstr.": [_stop("900029105", "Galenstr. (Berlin)", 52.535693, 13.194286)],
}

JOURNEYS = {
    "journeys": [
        {
            "type": "journey",
            "legs": [
                {
                    "origin": {"name": "Mertensstr. (Berlin)"},
                    "destination": {"name": "S+U Rathaus Spandau"},
                    "departure": "2026-10-27T12:20:00+01:00",
                    "arrival": "2026-10-27T12:25:00+01:00",
                    "walking": True,
                    "distance": 350,
                },
                {
                    "origin": {"name": "S+U Rathaus Spandau"},
                    "destination": {"name": "Galenstr. (Berlin)"},
                    "departure": "2026-10-27T12:26:00+01:00",
                    "arrival": "2026-10-27T12:35:00+01:00",
                    "line": {"name": "136", "mode": "bus", "product": "bus"},
                    "direction": "Galenstr.",
                    "departurePlatform": "B",
                },
            ],
        }
    ]
}


def _line_journey(*lines):
    start = datetime(2026, 10, 27, 7, 38, tzinfo=TZ)
    legs = []
    for line in lines:
        end = start + timedelta(minutes=5)
        legs.append(
            {
                "origin": {"name": "A"},
                "destination": {"name": "B"},
                "departure": start.isoformat(),
                "arrival": end.isoformat(),
                "line": {"name": line, "mode": "bus", "product": "bus"},
            }
        )
        start = end + timedelta(minutes=2)
    return {"type": "journey", "legs": legs}


def _fake_api(monkeypatch, *, journey_payload=JOURNEYS):
    calls: list[tuple[str, dict]] = []

    def fake_get(url, params=None, timeout=None, headers=None):
        params = dict(params or {})
        calls.append((url, params))

        class Response:
            status_code = 200

            def json(self):
                if url.endswith("/locations/nearby"):
                    return [_stop("near", "Nächste Haltestelle", 52.5, 13.4, 120)]
                if url.endswith("/locations"):
                    return STOPS.get(str(params.get("query")), [])
                if url.endswith("/journeys"):
                    return journey_payload
                return {}

        return Response()

    monkeypatch.setattr("dir3.services.transit.requests.get", fake_get)
    return calls


def test_journey_parses_walking_and_transit_legs(monkeypatch, tmp_path):
    _fake_api(monkeypatch)
    service = TransitService(_config(), cache_path=tmp_path / "transit.json")

    journey = service.journey(
        "Mertensstr.",
        "Galenstr.",
        departure=datetime(2026, 10, 27, 12, 15, tzinfo=TZ),
    )

    assert journey is not None
    assert journey.departure == datetime(2026, 10, 27, 12, 20, tzinfo=TZ)
    assert journey.arrival == datetime(2026, 10, 27, 12, 35, tzinfo=TZ)
    assert journey.duration == timedelta(minutes=15)
    assert journey.transfers == 0
    assert journey.summary == "136"
    assert [leg.mode for leg in journey.legs] == ["walk", "bus"]
    assert journey.legs[0].is_walk
    assert journey.legs[0].distance == 350
    assert journey.legs[1].line == "136"
    assert journey.legs[1].direction == "Galenstr."
    assert journey.legs[1].platform == "B"


def test_duration_uses_arrival_parameter(monkeypatch, tmp_path):
    calls = _fake_api(monkeypatch)
    service = TransitService(_config(), cache_path=tmp_path / "transit.json")

    duration = service.duration(
        "Mertensstr.",
        "Galenstr.",
        arrival=datetime(2026, 10, 27, 12, 35, tzinfo=TZ),
    )

    assert duration == timedelta(minutes=15)
    journey_calls = [params for url, params in calls if url.endswith("/journeys")]
    assert journey_calls == [
        {
            "arrival": "2026-10-27T12:35:00+01:00",
            "from": "900027254",
            "to": "900029105",
            "results": 3,
            "stopovers": "false",
            "remarks": "false",
        }
    ]


def test_coordinates_resolve_nearest_stop(monkeypatch, tmp_path):
    calls = _fake_api(monkeypatch)
    service = TransitService(_config(), cache_path=tmp_path / "transit.json")
    location = GeoLocation(52.5, 13.4, "Europe/Berlin", "Berlin", "Deutschland")

    stop = service.stop(location)

    assert stop is not None
    assert stop.name == "Nächste Haltestelle"
    assert stop.distance == 120
    nearby = [params for url, params in calls if url.endswith("/locations/nearby")]
    assert nearby == [{"latitude": 52.5, "longitude": 13.4, "results": 1}]


def test_stops_and_journeys_are_cached(monkeypatch, tmp_path):
    calls = _fake_api(monkeypatch)
    cache = tmp_path / "transit.json"
    service = TransitService(_config(), cache_path=cache)
    departure = datetime(2026, 10, 27, 12, 15, tzinfo=TZ)

    service.journey("Mertensstr.", "Galenstr.", departure=departure)
    before = len(calls)
    service.journey("Mertensstr.", "Galenstr.", departure=departure)
    assert len(calls) == before

    second = TransitService(_config(), cache_path=cache)
    second.stop("Mertensstr.")
    assert len(calls) == before


def test_network_failure_returns_none(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("dir3.services.transit.requests.get", fail)
    service = TransitService(_config(), cache_path=tmp_path / "transit.json")
    assert service.journey("Mertensstr.", "Galenstr.") is None


def test_empty_or_bad_journeys_return_empty(monkeypatch, tmp_path):
    for payload in ({}, {"journeys": []}, {"journeys": [{"legs": []}]}):
        _fake_api(monkeypatch, journey_payload=payload)
        service = TransitService(_config(), cache_path=tmp_path / "transit.json")
        assert service.journeys("Mertensstr.", "Galenstr.") == []


def test_departure_and_arrival_are_mutually_exclusive(monkeypatch, tmp_path):
    _fake_api(monkeypatch)
    service = TransitService(_config(), cache_path=tmp_path / "transit.json")
    with pytest.raises(ValueError):
        service.journeys(
            "Mertensstr.",
            "Galenstr.",
            departure=datetime(2026, 10, 27, 12, 0, tzinfo=TZ),
            arrival=datetime(2026, 10, 27, 12, 30, tzinfo=TZ),
        )


def test_journeys_filter_requested_lines_in_order(monkeypatch, tmp_path):
    payload = {
        "journeys": [
            _line_journey("139", "U7", "M45"),
            _line_journey("139", "U7", "U2"),
        ]
    }
    _fake_api(monkeypatch, journey_payload=payload)
    service = TransitService(_config(), cache_path=tmp_path / "transit.json")
    departure = datetime(2026, 10, 27, 7, 37, tzinfo=TZ)

    assert [
        j.summary
        for j in service.journeys("Mertensstr.", "Galenstr.", departure=departure)
    ] == [
        "139 → U7 → M45",
        "139 → U7 → U2",
    ]
    assert [
        j.summary
        for j in service.journeys(
            "Mertensstr.",
            "Galenstr.",
            departure=departure,
            lines=("139", "U7", "U2"),
        )
    ] == ["139 → U7 → U2"]


def test_fewest_transfers_wins_over_provider_order(monkeypatch, tmp_path):
    payload = {
        "journeys": [
            _line_journey("139", "U7", "U2"),
            _line_journey("139", "M45"),
        ]
    }
    _fake_api(monkeypatch, journey_payload=payload)
    cache = tmp_path / "transit.json"
    service = TransitService(_config(), cache_path=cache)
    departure = datetime(2026, 10, 27, 7, 37, tzinfo=TZ)

    fastest_order = service.journeys(
        "Mertensstr.",
        "Galenstr.",
        departure=departure,
        lines=("139",),
    )
    assert [j.summary for j in fastest_order] == ["139 → U7 → U2", "139 → M45"]

    # Also covers the in-memory cache: the same journeys are re-sorted on read.
    fewest = service.journeys(
        "Mertensstr.",
        "Galenstr.",
        departure=departure,
        lines=("139",),
        fewest_transfers=True,
    )
    assert [j.summary for j in fewest] == ["139 → M45", "139 → U7 → U2"]
    assert [j.transfers for j in fewest] == [1, 2]



def test_transit_summary_and_transfers():
    walk = TransitLeg(
        "walk", "", "", "A", "B", datetime(2026, 1, 1, 12), datetime(2026, 1, 1, 12, 5)
    )
    bus = TransitLeg(
        "bus", "136", "B", "B", "C", datetime(2026, 1, 1, 12, 6), datetime(2026, 1, 1, 12, 16)
    )
    tram = TransitLeg(
        "tram", "M1", "C", "C", "D", datetime(2026, 1, 1, 12, 18), datetime(2026, 1, 1, 12, 30)
    )
    journey = TransitJourney(walk.departure, tram.arrival, (walk, bus, tram))
    assert journey.transfers == 1
    assert journey.lines == ("136", "M1")
    assert journey.summary == "136 → M1"
    assert journey.uses(["136"])
    assert journey.uses(["136", "M1"])
    assert not journey.uses(["M1", "136"])


def test_config_overlay_transit():
    config = Dir3Config().overlay(
        SimpleNamespace(transit={"endpoint": "https://example.test", "results": 5})
    )
    assert config.transit.endpoint == "https://example.test"
    assert config.transit.results == 5


class _FakeTransit:
    def __init__(self):
        self.calls = []

    def journeys(self, origin, destination, *, departure=None, arrival=None):
        self.calls.append((origin, destination, departure, arrival))
        return []

    def journey(self, origin, destination, *, departure=None, arrival=None):
        return None

    def duration(self, origin, destination, *, departure=None, arrival=None):
        self.calls.append((origin, destination, departure, arrival))
        return timedelta(minutes=7)


def test_context_transit_gate_uses_plan_day_and_location():
    fake = _FakeTransit()
    config = Dir3Config(
        location=LocationSettings(latitude=52.5, longitude=13.4, timezone="Europe/Berlin"),
        prayer=PrayerSettings(provider="offline"),
    )
    services = Services(config=config, transit=fake)
    ctx = DayContext(date(2026, 10, 27), services)

    assert ctx.transit.duration("A", "B", at=time(12, 15)) == timedelta(minutes=7)
    origin, destination, departure, arrival = fake.calls[-1]
    assert (origin, destination) == ("A", "B")
    assert departure == datetime(2026, 10, 27, 12, 15)
    assert arrival is None

    ctx.transit.from_here("B", arrival=time(13, 0))
    origin, destination, departure, arrival = fake.calls[-1]
    assert origin is ctx.location
    assert departure is None
    assert arrival == datetime(2026, 10, 27, 13, 0)
