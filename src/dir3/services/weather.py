"""Weather conditions, evaluated lazily per day (e.g. `ctx.weather.is_rainy()`).

Results are cached per (city, date) so that recompiling the same plan during a
single day stays deterministic.  The city comes from the *plan* (location) or
the detected location - never from a hardcoded default.
"""
from __future__ import annotations

import json
from datetime import date
from json import JSONDecodeError

import requests

from ..config import DEFAULT_CACHE_DIR
from .geo import GeoLocation

WTTR_API = "https://wttr.in/{city}?format=j1"


class WeatherService:
    def __init__(self, location_getter=None, timeout: float = 8.0, cache_path=None) -> None:
        self._location_getter = location_getter
        self.timeout = timeout
        self.cache_path = cache_path or DEFAULT_CACHE_DIR / "weather.json"
        self._trend_cache: dict[str, bool | None] = self._load()

    def _load(self) -> dict[str, bool | None]:
        if not self.cache_path.exists():
            return {}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (JSONDecodeError, OSError):  # pragma: no cover - defensive
            return {}

    def _city(self, city: str | None) -> str | None:
        name = (city or "").strip()
        if name:
            return name
        getter = self._location_getter
        if getter is not None:
            try:
                location: GeoLocation | None = getter()
                return (location.city or "").strip() or None
            except Exception:  # pragma: no cover - no location available
                return None
        return None

    def is_rainy(self, day: date, city: str | None = None) -> bool | None:
        """True when rain chance exceeds 50% in any hour of the given day.

        Returns ``None`` when the city is unknown or the forecast cannot be
        fetched (treated as "unknown / assume dry" by callers).
        """
        location = self._city(city)
        if not location:
            return None
        key = f"{location}:{day.isoformat()}"
        if key in self._trend_cache:
            return self._trend_cache[key]

        result = self._fetch(location, day)
        self._trend_cache[key] = result
        self._save()
        return result

    def _fetch(self, city: str, day: date) -> bool | None:
        try:
            response = requests.get(WTTR_API.format(city=city), timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (  # pragma: no cover - network
            requests.RequestException,
            ValueError,
            JSONDecodeError,
        ):
            return None
        try:
            weather = payload["weather"]
            target = day.isoformat()
            entry = next(
                (
                    row
                    for row in weather
                    if str(row.get("date", ""))[:10] == target
                ),
                weather[0],
            )
            hourly = entry.get("hourly", [])
        except (KeyError, IndexError, TypeError):  # pragma: no cover - bad payload
            return None
        chances = [int(h.get("chanceofrain") or 0) for h in hourly]
        if not chances:
            return None
        return max(chances) > 50

    def _save(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._trend_cache, indent=1), encoding="utf-8")
        except OSError:  # pragma: no cover - read-only cache dir
            pass


def rains(city: str | None = None):
    """Predicate factory for ``task(..., unless=rains())`` style conditions.

    Returns a callable ``(ctx) -> bool`` for use in ``unless`` tuples.
    """

    def predicate(ctx) -> bool:
        default_city = getattr(ctx, "city", None)
        return bool(ctx.weather.is_rainy(ctx.date, city or default_city))

    return predicate
