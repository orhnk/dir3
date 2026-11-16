"""Public-transport travel times via a HAFAS REST endpoint.

The default endpoint is the community VBB API for Berlin/Brandenburg:
https://v6.vbb.transport.rest (no API key required).  A plan can point
``transit`` at another HAFAS-REST-compatible instance; the response parser is
kept small and provider-agnostic.

The service is deliberately best-effort: stop lookups and journeys return
``None``/empty lists on network errors, so a plan can still compile with an
offline fallback.  Stops are cached on disk because their IDs rarely change.
"""

from __future__ import annotations

import json
import time as _time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from json import JSONDecodeError
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from ..config import DEFAULT_CACHE_DIR, Dir3Config
from .geo import GeoLocation

USER_AGENT = "dir3/0.1 (soft-planning-cli)"
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
#: HAFAS endpoints rank by "best" (usually fastest).  Pinned routes can be
#: slower and therefore fall outside the first few results, so allow a larger
#: page when a plan asks for it.
MAX_RESULTS = 20


@dataclass(frozen=True, slots=True)
class TransitStop:
    """A stop/station resolved from a name, coordinates or an ID."""

    id: str
    name: str
    latitude: float | None = None
    longitude: float | None = None
    distance: int | None = None


@dataclass(frozen=True, slots=True)
class TransitLeg:
    """One leg of a journey: walk or a single transit line."""

    mode: str
    line: str
    direction: str
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    distance: int | None = None
    platform: str | None = None

    @property
    def duration(self) -> timedelta:
        return self.arrival - self.departure

    @property
    def is_walk(self) -> bool:
        return self.mode == "walk"


@dataclass(frozen=True, slots=True)
class TransitJourney:
    """A complete journey with all legs (walking legs included)."""

    departure: datetime
    arrival: datetime
    legs: tuple[TransitLeg, ...]
    provider: str = "vbb"

    @property
    def duration(self) -> timedelta:
        return self.arrival - self.departure

    @property
    def transfers(self) -> int:
        rides = sum(1 for leg in self.legs if not leg.is_walk)
        return max(0, rides - 1)

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(leg.line for leg in self.legs if not leg.is_walk and leg.line)

    @property
    def summary(self) -> str:
        return " → ".join(self.lines) if self.lines else "Fußweg"

    def uses(self, lines: Sequence[str]) -> bool:
        """True when the journey contains the requested lines in order."""
        return _matches_lines(self, _normalize_lines(lines))


TransitPlace = str | GeoLocation | tuple[float, float] | TransitStop


def _normalize_lines(lines: Sequence[str] | None) -> tuple[str, ...]:
    if not lines:
        return ()
    normalized = (str(line).strip().casefold() for line in lines)
    return tuple(line for line in normalized if line)


def _matches_lines(journey: TransitJourney, wanted: tuple[str, ...]) -> bool:
    if not wanted:
        return True
    position = 0
    for line in journey.lines:
        if position < len(wanted) and line.casefold() == wanted[position]:
            position += 1
    return position == len(wanted)


def _sort_journeys(journeys: Sequence[TransitJourney]) -> list[TransitJourney]:
    """Fewest transfers first, then the earliest departure."""
    return sorted(
        journeys,
        key=lambda journey: (journey.transfers, journey.departure, journey.duration),
    )


class TransitService:
    """Resolve stops and query journeys from a HAFAS REST endpoint."""

    def __init__(
        self,
        config: Dir3Config | None = None,
        *,
        timeout: float | None = None,
        cache_path: str | Path | None = None,
    ) -> None:
        self.config = config or Dir3Config()
        self.settings = self.config.transit
        self.timeout = timeout if timeout is not None else self.settings.timeout
        self.cache_path = Path(cache_path or DEFAULT_CACHE_DIR / "transit.json")
        self._tz = ZoneInfo(self.settings.timezone)
        self._stops: dict[str, TransitStop | None] = {}
        self._journeys: dict[tuple, list[TransitJourney]] = {}
        self._cache = self._load_cache()

    @property
    def tzinfo(self) -> ZoneInfo:
        return self._tz

    # -- public API ------------------------------------------------------

    def stop(self, place: TransitPlace) -> TransitStop | None:
        """Resolve a stop name, coordinates, ``GeoLocation`` or ``TransitStop``."""
        if isinstance(place, TransitStop):
            return place
        key = self._place_key(place)
        if key in self._stops:
            return self._stops[key]
        cached = self._cached_stop(key)
        if cached is not None:
            self._stops[key] = cached
            return cached

        if isinstance(place, str):
            query = place.strip()
            if not query:
                return None
            payload = self._get("/locations", {"query": query, "results": 1})
        elif isinstance(place, GeoLocation):
            payload = self._get(
                "/locations/nearby",
                {
                    "latitude": place.latitude,
                    "longitude": place.longitude,
                    "results": 1,
                },
            )
        elif isinstance(place, (tuple, list)) and len(place) >= 2:
            payload = self._get(
                "/locations/nearby",
                {
                    "latitude": float(place[0]),
                    "longitude": float(place[1]),
                    "results": 1,
                },
            )
        else:
            raise TypeError("transit place must be a name, (lat, lon), GeoLocation or TransitStop")

        found = payload[0] if isinstance(payload, list) and payload else None
        stop = self._parse_stop(found)
        self._stops[key] = stop
        if stop is not None:
            self._store_stop(key, stop)
        return stop

    def journeys(
        self,
        origin: TransitPlace,
        destination: TransitPlace,
        *,
        departure: datetime | None = None,
        arrival: datetime | None = None,
        results: int | None = None,
        lines: Sequence[str] | None = None,
        fewest_transfers: bool = False,
    ) -> list[TransitJourney]:
        """Return journeys between two places.

        Pass either ``departure`` or ``arrival``.  Without both, the query
        starts now (local endpoint timezone).  ``lines`` keeps only journeys
        that use the given transit lines in order; walking legs are ignored.
        This lets a plan pin the user's route instead of accepting the
        provider's fastest alternative.  ``fewest_transfers`` orders the
        matches by transfers first, so a slower direct connection wins over
        a faster connection with extra changes.
        """
        if departure is not None and arrival is not None:
            raise ValueError("departure and arrival are mutually exclusive")

        wanted = _normalize_lines(lines)
        origin_stop = self.stop(origin)
        destination_stop = self.stop(destination)
        if origin_stop is None or destination_stop is None:
            return []

        count = max(1, min(int(results or self.settings.results), MAX_RESULTS))
        if departure is not None:
            when = self._iso(departure)
            key = (origin_stop.id, destination_stop.id, "departure", when, count, wanted)
            params = {"departure": when}
        else:
            if arrival is None:
                arrival = datetime.now(self._tz)
            when = self._iso(arrival)
            key = (origin_stop.id, destination_stop.id, "arrival", when, count, wanted)
            params = {"arrival": when}

        if key in self._journeys:
            cached = self._journeys[key]
            return _sort_journeys(cached) if fewest_transfers else list(cached)

        params.update(
            {
                "from": origin_stop.id,
                "to": destination_stop.id,
                "results": count,
                "stopovers": "false",
                "remarks": "false",
            }
        )
        payload = self._get("/journeys", params)
        raw_journeys = payload.get("journeys") if isinstance(payload, dict) else None
        if not isinstance(raw_journeys, list):
            return []
        parsed = [
            journey for raw in raw_journeys if (journey := self._parse_journey(raw)) is not None
        ]
        if wanted:
            parsed = [journey for journey in parsed if _matches_lines(journey, wanted)]
        if parsed:
            self._journeys[key] = parsed
        return _sort_journeys(parsed) if fewest_transfers else parsed

    def journey(
        self,
        origin: TransitPlace,
        destination: TransitPlace,
        *,
        departure: datetime | None = None,
        arrival: datetime | None = None,
        results: int | None = None,
        lines: Sequence[str] | None = None,
        fewest_transfers: bool = False,
    ) -> TransitJourney | None:
        """Return the first matching journey, or ``None``."""
        journeys = self.journeys(
            origin,
            destination,
            departure=departure,
            arrival=arrival,
            results=results,
            lines=lines,
            fewest_transfers=fewest_transfers,
        )
        return journeys[0] if journeys else None

    def duration(
        self,
        origin: TransitPlace,
        destination: TransitPlace,
        *,
        departure: datetime | None = None,
        arrival: datetime | None = None,
        lines: Sequence[str] | None = None,
        fewest_transfers: bool = False,
    ) -> timedelta | None:
        """Travel time for the first matching journey, or ``None``."""
        journey = self.journey(
            origin,
            destination,
            departure=departure,
            arrival=arrival,
            lines=lines,
            fewest_transfers=fewest_transfers,
        )
        return journey.duration if journey is not None else None

    # -- HTTP ------------------------------------------------------------

    def _get(self, path: str, params: dict) -> dict | list | None:
        url = f"{self.settings.endpoint.rstrip('/')}{path}"
        for attempt in range(3):
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    headers={"User-Agent": USER_AGENT},
                )
            except requests.RequestException:
                return None

            status = getattr(response, "status_code", 200)
            if status in _RETRYABLE_STATUS and attempt < 2:
                _time.sleep(0.5 * (attempt + 1))
                continue
            if status >= 400:
                return None
            try:
                payload = response.json()
            except (ValueError, JSONDecodeError):
                return None
            return payload if isinstance(payload, (dict, list)) else None
        return None

    def _iso(self, when: datetime) -> str:
        aware = when.replace(tzinfo=self._tz) if when.tzinfo is None else when
        return aware.isoformat()

    # -- parsing ---------------------------------------------------------

    def _parse_stop(self, payload: object) -> TransitStop | None:
        if not isinstance(payload, dict):
            return None
        stop_id = payload.get("id")
        name = payload.get("name")
        if not stop_id or not name:
            return None
        location = payload.get("location")
        location = location if isinstance(location, dict) else {}
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        distance = payload.get("distance")
        return TransitStop(
            id=str(stop_id),
            name=str(name),
            latitude=self._float_or_none(latitude),
            longitude=self._float_or_none(longitude),
            distance=self._int_or_none(distance),
        )

    def _parse_journey(self, payload: object) -> TransitJourney | None:
        if not isinstance(payload, dict):
            return None
        raw_legs = payload.get("legs")
        if not isinstance(raw_legs, list):
            return None
        legs = [leg for raw in raw_legs if (leg := self._parse_leg(raw)) is not None]
        if not legs:
            return None
        return TransitJourney(
            departure=legs[0].departure,
            arrival=legs[-1].arrival,
            legs=tuple(legs),
            provider=self._provider_name,
        )

    def _parse_leg(self, payload: object) -> TransitLeg | None:
        if not isinstance(payload, dict):
            return None
        departure = self._parse_datetime(payload.get("departure"))
        arrival = self._parse_datetime(payload.get("arrival"))
        if departure is None or arrival is None:
            return None
        line = payload.get("line")
        line = line if isinstance(line, dict) else {}
        walk = bool(payload.get("walking")) or not line
        mode = "walk" if walk else str(line.get("mode") or line.get("product") or "transit")
        distance = payload.get("distance")
        platform = payload.get("departurePlatform") or payload.get("plannedDeparturePlatform")
        return TransitLeg(
            mode=mode,
            line="" if walk else str(line.get("name") or line.get("id") or ""),
            direction="" if walk else str(payload.get("direction") or ""),
            origin=self._stop_name(payload.get("origin")),
            destination=self._stop_name(payload.get("destination")),
            departure=departure,
            arrival=arrival,
            distance=self._int_or_none(distance),
            platform=str(platform) if platform else None,
        )

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _stop_name(value: object) -> str:
        if isinstance(value, dict):
            return str(value.get("name") or "")
        return str(value or "")

    @property
    def _provider_name(self) -> str:
        host = urlparse(self.settings.endpoint).hostname or "transit"
        parts = host.split(".")
        return parts[1] if len(parts) > 1 and parts[0] in {"v5", "v6"} else host

    # -- stop cache ------------------------------------------------------

    def _place_key(self, place: TransitPlace) -> str:
        if isinstance(place, str):
            return f"name:{place.strip().casefold()}"
        if isinstance(place, GeoLocation):
            return f"near:{place.latitude:.5f},{place.longitude:.5f}"
        if isinstance(place, (tuple, list)) and len(place) >= 2:
            return f"near:{float(place[0]):.5f},{float(place[1]):.5f}"
        raise TypeError("unsupported transit place")

    def _load_cache(self) -> dict:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, JSONDecodeError):
            return {"stops": {}}
        return data if isinstance(data, dict) else {"stops": {}}

    def _cached_stop(self, key: str) -> TransitStop | None:
        stops = self._cache.get("stops")
        entry = stops.get(key) if isinstance(stops, dict) else None
        if not isinstance(entry, dict):
            return None
        try:
            age = _time.time() - float(entry["at"])
        except (KeyError, TypeError, ValueError):
            return None
        if age < 0 or age > self.settings.stop_cache_ttl:
            return None
        return self._stop_from_dict(entry.get("stop"))

    def _store_stop(self, key: str, stop: TransitStop) -> None:
        stops = self._cache.setdefault("stops", {})
        if not isinstance(stops, dict):  # pragma: no cover - corrupted cache
            stops = {}
            self._cache["stops"] = stops
        stops[key] = {"at": _time.time(), "stop": self._stop_to_dict(stop)}
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except OSError:  # pragma: no cover - read-only cache dir
            pass

    @staticmethod
    def _stop_to_dict(stop: TransitStop) -> dict:
        return {
            "id": stop.id,
            "name": stop.name,
            "latitude": stop.latitude,
            "longitude": stop.longitude,
            "distance": stop.distance,
        }

    @staticmethod
    def _stop_from_dict(value: object) -> TransitStop | None:
        if not isinstance(value, dict):
            return None
        try:
            stop_id = str(value["id"])
            name = str(value["name"])
        except KeyError:
            return None
        latitude = value.get("latitude")
        longitude = value.get("longitude")
        distance = value.get("distance")
        try:
            return TransitStop(
                id=stop_id,
                name=name,
                latitude=float(latitude) if latitude is not None else None,
                longitude=float(longitude) if longitude is not None else None,
                distance=int(distance) if distance is not None else None,
            )
        except (TypeError, ValueError):
            return None
