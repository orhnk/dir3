"""Geolocation: where are we, and in which timezone.

Resolution order:
1. explicit latitude/longitude/timezone from the **planfile** (``location = (...)``);
2. auto-detection via ``ipapi.co`` when ``use_geolocation`` is enabled (default);
3. a clear error, never a silently guessed city.

The auto-detected location is cached on disk (per machine, TTL-bound), so
repeated runs do not hammer ``ipapi.co`` and still work when the network is
gone.  The resolved location is printed by the CLI, so a guess is never
mistaken for your real city.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as _timezone
from json import JSONDecodeError

import requests

from ..config import DEFAULT_CACHE_DIR, Dir3Config, LocationSettings

IPAPI_URL = "https://ipapi.co/json/"
#: ipapi.co rejects empty/native clients with HTTP 429 - a UA makes it work everywhere.
IPAPI_USER_AGENT = "dir3/0.1 (soft-planning-cli)"

#: How long a cached auto-detected location stays fresh.
GEO_CACHE_TTL = timedelta(hours=6)

#: HTTP statuses worth retrying with backoff (rate limit / flaky upstream).
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

_FIXED_OFFSET = re.compile(r"^(?P<sign>[+-])(?P<h>\d{1,2})(?::?(?P<m>\d{2}))?$")


@dataclass(frozen=True, slots=True)
class GeoLocation:
    latitude: float
    longitude: float
    timezone: str | None = None
    city: str = ""
    country: str = ""

    @property
    def tzinfo(self):  # pragma: no cover - trivial accessor
        return _resolve_tz(self.timezone)


class GeoLocator:
    def __init__(
        self,
        config: Dir3Config,
        timeout: float = 8.0,
        cache_path=None,
    ) -> None:
        self.config = config
        self._timeout = timeout
        self._cache_path = cache_path or DEFAULT_CACHE_DIR / "geolocation.json"
        self._detected: GeoLocation | None = None

    def detect(self) -> GeoLocation:
        """Resolve the location once and memoize the resolution for the process."""
        if self._detected is not None:
            return self._detected
        self._detected = self._resolve()
        return self._detected

    def _resolve(self) -> GeoLocation:
        loc = self.config.location
        if loc.latitude is not None and loc.longitude is not None:
            return self._from_manual(loc)

        if loc.use_geolocation:
            detected = self._from_ip()
            if detected is not None:
                merged = self._merge(loc, detected)
                if merged is not None:
                    return merged

        raise RuntimeError(
            "Standort nicht bestimmbar. Bitte im Planfile Koordinaten setzen, "
            'z. B. location = (48.1374, 11.5754, "Europe/Berlin"), '
            "oder die Geolocation (ipapi.co) erreichbar machen."
        )

    @staticmethod
    def _from_manual(loc: LocationSettings) -> GeoLocation:
        return GeoLocation(
            latitude=loc.latitude or 0.0,
            longitude=loc.longitude or 0.0,
            timezone=loc.timezone or _system_tz(),
            city=loc.city,
            country=loc.country,
        )

    def _from_ip(self) -> GeoLocation | None:
        cached = self._load_cache()
        now = datetime.now(_timezone.utc)
        if self._cached_is_fresh(cached, now):
            return self._geo_from_cache(cached)
        try:
            payload = self._ipapi_payload()
        except requests.RequestException:  # pragma: no cover - network
            # Best effort: a stale location beats none (offline machines).
            return self._geo_from_cache(cached) if cached else None
        except ValueError:  # pragma: no cover - bad json
            return self._geo_from_cache(cached) if cached else None
        try:
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
        except (KeyError, TypeError, ValueError):  # pragma: no cover - bad payload
            return self._geo_from_cache(cached) if cached else None
        detected = GeoLocation(
            latitude=latitude,
            longitude=longitude,
            timezone=payload.get("timezone") or _system_tz(),
            city=payload.get("city") or "",
            country=payload.get("country_name") or payload.get("country") or "",
        )
        self._save_cache(detected, now=now)
        return detected

    def _ipapi_payload(self) -> dict:
        """ipapi.co with retries for rate limits (429) and flaky upstreams."""
        last: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.get(
                    IPAPI_URL,
                    timeout=self._timeout,
                    headers={"User-Agent": IPAPI_USER_AGENT},
                )
            except requests.RequestException as exc:
                last = exc
                if attempt < 2:
                    time.sleep(0.6 * (attempt + 1))
                    continue
                raise exc
            code = getattr(response, "status_code", None)
            if code in _RETRYABLE_STATUS and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.json()
        raise last  # pragma: no cover - defensive

    def _load_cache(self) -> dict | None:
        try:
            with open(self._cache_path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, JSONDecodeError):  # pragma: no cover - defensive
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _save_cache(self, location: GeoLocation, *, now: datetime) -> None:
        payload = {
            "fetched_at": now.isoformat(),
            "latitude": location.latitude,
            "longitude": location.longitude,
            "timezone": location.timezone or "",
            "city": location.city,
            "country": location.country,
        }
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._cache_path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
            os.replace(temp, self._cache_path)
        except OSError:  # pragma: no cover - read-only cache dir
            pass

    @staticmethod
    def _cached_is_fresh(cached: dict | None, now: datetime) -> bool:
        if not cached:
            return False
        try:
            fetched = datetime.fromisoformat(str(cached.get("fetched_at") or ""))
        except ValueError:  # pragma: no cover - defensive
            return False
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=_timezone.utc)
        return 0 <= (now - fetched).total_seconds() < GEO_CACHE_TTL.total_seconds()

    @staticmethod
    def _geo_from_cache(cached: dict | None) -> GeoLocation | None:
        if not cached:
            return None
        try:
            latitude = float(cached["latitude"])
            longitude = float(cached["longitude"])
        except (KeyError, TypeError, ValueError, OverflowError):  # pragma: no cover
            return None
        return GeoLocation(
            latitude=latitude,
            longitude=longitude,
            timezone=cached.get("timezone") or None,
            city=cached.get("city") or "",
            country=cached.get("country") or "",
        )

    @staticmethod
    def _merge(loc: LocationSettings, detected: GeoLocation) -> GeoLocation | None:
        latitude = loc.latitude if loc.latitude is not None else detected.latitude
        longitude = loc.longitude if loc.longitude is not None else detected.longitude
        if latitude is None or longitude is None:  # pragma: no cover - defensive
            return None
        return GeoLocation(
            latitude=latitude,
            longitude=longitude,
            timezone=loc.timezone or detected.timezone or _system_tz(),
            city=loc.city or detected.city,
            country=loc.country or detected.country,
        )


def _system_tz() -> str:
    try:
        tzinfo = datetime.now().astimezone().tzinfo
        key = getattr(tzinfo, "key", None)  # IANA name for ZoneInfo instances
        if key:
            return key
        name = tzinfo.tzname(None)  # type: ignore[union-attr]
        if name:
            return name
    except Exception:  # pragma: no cover - defensive
        pass
    return "UTC"


def _resolve_tz(name: str | None):
    from zoneinfo import ZoneInfo

    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            match = _FIXED_OFFSET.match(name)
            if match:
                hours = int(match.group("h"))
                minutes = int(match.group("m") or 0)
                offset = timedelta(hours=hours, minutes=minutes)
                if match.group("sign") == "-":
                    offset = -offset
                return _timezone(offset)
            if name in {"UTC", "GMT", "Z"}:
                return _timezone.utc
    return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")
