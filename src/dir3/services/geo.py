"""Geolocation: where are we, and in which timezone.

Resolution order:
1. explicit latitude/longitude/timezone from the **planfile** (``location = (...)``);
2. auto-detection via ``ipapi.co`` when ``use_geolocation`` is enabled (default);
3. a clear error, never a silently guessed city.

The resolved location is printed by the CLI, so a guess is never mistaken for
your real city.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as _timezone

import requests

from ..config import Dir3Config, LocationSettings

IPAPI_URL = "https://ipapi.co/json/"
#: ipapi.co rejects empty/native clients with HTTP 429 - a UA makes it work everywhere.
IPAPI_USER_AGENT = "dir3/0.1 (soft-planning-cli)"

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
    def __init__(self, config: Dir3Config, timeout: float = 8.0) -> None:
        self.config = config
        self._timeout = timeout
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
        try:
            response = requests.get(
                IPAPI_URL,
                timeout=self._timeout,
                headers={"User-Agent": IPAPI_USER_AGENT},
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:  # pragma: no cover - network
            return None
        except ValueError:  # pragma: no cover - bad json
            return None
        try:
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
        except (KeyError, TypeError, ValueError):  # pragma: no cover - bad payload
            return None
        return GeoLocation(
            latitude=latitude,
            longitude=longitude,
            timezone=payload.get("timezone") or _system_tz(),
            city=payload.get("city") or "",
            country=payload.get("country_name") or payload.get("country") or "",
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
