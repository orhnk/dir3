"""Per-day prayer times.

Three sources, mirroring munazzim's layering:

* **aladhan** - Aladhan API (``https://api.aladhan.com/v1/timings/...``), cached
  on disk so a recompile on the same day is deterministic and offline-safe;
* **ezanvakti** (alias ``diyanet``) - official Turkish Presidency of Religious
  Affairs per-district times via ``ezanvakti.imsakiyem.com``; the district is
  resolved from the location and a whole horizon is fetched in one request;
* **offline** - a pure-Python Islamic calculator with the classic hour-angle
  method (declination + equation of time + per-method Fajr/Isha angles and the
  shadow-factor Asr rule), so prayer times work with no network at all.

``provider = "auto"`` (the default) tries Aladhan first and falls back to the
calculator.  Set ``provider = "ezanvakti"``/``"diyanet"`` to use Diyanet
official times, or ``"offline"`` to never touch the network.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from json import JSONDecodeError
from math import acos, atan, cos, degrees, pi, radians, sin, tan

import requests

from ..config import DEFAULT_CACHE_DIR, Dir3Config
from ..timeutils import format_time
from .geo import GeoLocation, GeoLocator

ALADHAN_API = "https://api.aladhan.com/v1/timings/{day}"
EZANVAKTI_API = "https://ezanvakti.imsakiyem.com/api"
ALADHAN_METHODS = {
    "MWL": 3,
    "ISNA": 2,
    "Egypt": 5,
    "Karachi": 1,
    "Turkey": 13,
    "Diyanet": 13,
    "Tehran": 7,
    "Jafari": 7,
    "UMQ": 4,
    "UmmAlQura": 4,
    "Umm al-Qura": 4,
    "MWL2": 3,
}

# fajr / isha angles (degrees below horizon), isha_interval measured as
# minutes after maghrib (used by Umm al-Qura instead of an angle).
NAMED_METHODS: dict[str, tuple[float, float, int | None]] = {
    "MWL": (18.0, 17.0, None),
    "Karachi": (18.0, 18.0, None),
    "ISNA": (15.0, 15.0, None),
    "Egypt": (19.5, 17.5, None),
    "Turkey": (18.0, 17.0, None),
    "Diyanet": (18.0, 17.0, None),
    "Umm al-Qura": (18.5, 0.0, 90),
    "UmmAlQura": (18.5, 0.0, 90),
    "UMQ": (18.5, 0.0, 90),
    "Kemenag": (20.0, 18.0, None),
    "Singapore": (20.0, 18.0, None),
}

DEFAULT_METHOD_ANGLES = (18.0, 17.0, None)
SUNRISE_SUNSET_ANGLE = 0.833

#: EzanVakti (Diyanet) time field -> dir3 schedule field.
EZANVAKTI_TIME_KEYS = {
    "imsak": "fajr",
    "gunes": "sunrise",
    "ogle": "dhuhr",
    "ikindi": "asr",
    "aksam": "maghrib",
    "yatsi": "isha",
}


@dataclass(frozen=True, slots=True)
class PrayerSchedule:
    fajr: time
    sunrise: time
    dhuhr: time
    asr: time
    maghrib: time
    isha: time

    @property
    def sunset(self) -> time:
        """Sunset equals maghrib - the sun service maps both to the same value."""
        return self.maghrib

    def to_dict(self) -> dict[str, str]:
        return {key: format_time(getattr(self, key)) for key in PRAYER_KEYS}

    @classmethod
    def from_dict(cls, values: dict[str, str]) -> PrayerSchedule:
        from ..timeutils import parse_hhmm

        return cls(
            fajr=parse_hhmm(values["fajr"]),
            sunrise=parse_hhmm(values.get("sunrise", _same_or_after(values["fajr"]))),
            dhuhr=parse_hhmm(values["dhuhr"]),
            asr=parse_hhmm(values["asr"]),
            maghrib=parse_hhmm(values["maghrib"]),
            isha=parse_hhmm(values["isha"]),
        )


PRAYER_KEYS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")


def _same_or_after(_fajr: str) -> str:  # pragma: no cover - trivial fallback
    return _fajr


def _parse_hhmm(value: str) -> time:
    from ..timeutils import parse_hhmm

    return parse_hhmm(value.strip().split(" ")[0])


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _minutes_to_time(total_minutes: float) -> time:
    total_minutes %= 1440
    if total_minutes < 0:  # pragma: no cover - defensive wrap
        total_minutes += 1440
    hour = int(total_minutes // 60)
    minute = int(round(total_minutes % 60))
    if minute == 60:  # pragma: no cover - rounding edge
        minute = 0
        hour += 1
    hour %= 24
    return time(hour=hour, minute=minute)


class IslamicCalculator:
    """Classic hour-angle prayer time calculator (pure Python)."""

    def __init__(self, method: str = "MWL", madhab: str = "Shafi") -> None:
        self.fajr_angle, self.isha_angle, self.isha_interval = NAMED_METHODS.get(
            method, DEFAULT_METHOD_ANGLES  # type: ignore[arg-type]
        )
        self.asr_factor = 2 if madhab.lower() == "hanafi" else 1

    def compute(self, day: date, location: GeoLocation) -> PrayerSchedule:
        lat_rad = radians(location.latitude)
        lon = location.longitude

        tz = _tz_for(location.timezone)
        offset = tz.utcoffset(datetime(day.year, day.month, day.day, 12))
        tz_hours = (offset.total_seconds() / 3600.0) if offset else 0.0

        n = day.timetuple().tm_yday
        decl_rad = radians(-23.44 * cos(2 * pi * (n + 10) / 365.25))
        b = 2 * pi * (n - 81) / 364
        eot = 9.87 * sin(2 * b) - 7.53 * cos(b) - 1.5 * sin(b)  # minutes

        merid = 15.0 * tz_hours
        transit = 720.0 - eot - 4.0 * (lon - merid)  # minutes since local midnight

        def hour_offset(altitude_deg: float) -> float:
            a_rad = radians(altitude_deg)
            cos_h = _clamp(
                (sin(a_rad) - sin(lat_rad) * sin(decl_rad))
                / (cos(lat_rad) * cos(decl_rad))
            )
            return degrees(acos(cos_h)) * 4.0  # minutes

        # Asr: sun altitude where shadow = factor * (noon shadow length)
        zenith = abs(degrees(lat_rad) - degrees(decl_rad))
        asr_altitude = degrees(atan(1.0 / (tan(radians(zenith)) + self.asr_factor)))

        sunrise_off = hour_offset(-SUNRISE_SUNSET_ANGLE)
        sunset_off = sunrise_off
        fajr_off = hour_offset(-self.fajr_angle)
        isha_off = hour_offset(-self.isha_angle) if self.isha_angle else None

        dhuhr = _minutes_to_time(transit)
        sunrise = _minutes_to_time(transit - sunrise_off)
        sunset = _minutes_to_time(transit + sunset_off)
        fajr = _minutes_to_time(transit - fajr_off)
        maghrib = sunset
        if isha_off is not None:
            isha = _minutes_to_time(transit + isha_off)
        else:
            isha = _minutes_to_time((transit + sunset_off) + (self.isha_interval or 90))
        asr = _minutes_to_time(transit + hour_offset(asr_altitude))

        return PrayerSchedule(
            fajr=fajr, sunrise=sunrise, dhuhr=dhuhr, asr=asr, maghrib=maghrib, isha=isha
        )


class AladhanProvider:
    """Fetches prayer times from the Aladhan API (like munazzim)."""

    name = "aladhan"

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def fetch(self, day: date, location: GeoLocation, config: Dir3Config) -> PrayerSchedule:
        method = ALADHAN_METHODS.get(config.prayer.method, 3)
        school = 1 if config.prayer.madhab.lower() == "hanafi" else 0
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "method": method,
            "school": school,
        }
        url = ALADHAN_API.format(day=day.isoformat())
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        data = response.json().get("data", {}).get("timings", {})
        times = {
            key.lower(): _parse_hhmm(t)
            for key, t in data.items()
            if key.lower() in PRAYER_KEYS
        }
        if "sunrise" not in times:
            raise ValueError("Aladhan response missing sunrise")
        from ..timeutils import parse_hhmm

        return PrayerSchedule(
            fajr=times.get("fajr", parse_hhmm("05:00")),
            sunrise=times["sunrise"],
            dhuhr=times.get("dhuhr", parse_hhmm("12:30")),
            asr=times.get("asr", parse_hhmm("15:30")),
            maghrib=times.get("maghrib", parse_hhmm("18:05")),
            isha=times.get("isha", parse_hhmm("19:45")),
        )


class EzanVaktiProvider:
    """Diyanet-backed per-district prayer times via the EzanVakti API.

    EzanVakti (``ezanvakti.imsakiyem.com``) publishes the official Turkish
    Presidency of Religious Affairs (Diyanet) times, so no calculation method
    or madhab applies.  The district is resolved from the location's
    city/country and memoized per instance.  The ``/range`` endpoint returns
    one entry per day, so a whole compile horizon is fetched in a single
    request.
    """

    name = "ezanvakti"

    #: How many days a single ``/range`` request covers (cached per start day).
    WINDOW_DAYS = 30

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self._windows: dict[date, dict[date, PrayerSchedule]] = {}
        self._district_ids: dict[tuple[str, str], str | None] = {}

    def fetch(self, day: date, location: GeoLocation, config: Dir3Config) -> PrayerSchedule:
        schedule = self._times(day, location).get(day)
        if schedule is None:
            raise RuntimeError(f"EzanVakti returned no times for {day.isoformat()}")
        return schedule

    def _times(self, day: date, location: GeoLocation) -> dict[date, PrayerSchedule]:
        for start, schedules in self._windows.items():
            if start <= day < start + timedelta(days=self.WINDOW_DAYS):
                return schedules
        end = day + timedelta(days=self.WINDOW_DAYS - 1)
        schedules = self._fetch_range(day, end, location)
        self._windows = {day: schedules}
        return schedules

    def _fetch_range(
        self, start: date, end: date, location: GeoLocation
    ) -> dict[date, PrayerSchedule]:
        district_id = self._district_id(location)
        if not district_id:
            raise ValueError("EzanVakti: no district found for this location")
        payload = _ezanvakti_get(
            f"/prayer-times/{district_id}/range",
            {"startDate": start.isoformat(), "endDate": end.isoformat()},
            timeout=self.timeout,
        )
        entries = payload if isinstance(payload, list) else []
        schedules: dict[date, PrayerSchedule] = {}
        for entry in entries:
            raw = str(entry.get("date", ""))
            try:
                entry_day = date.fromisoformat(raw[:10])
            except (ValueError, TypeError):  # pragma: no cover - defensive
                continue
            schedule = _from_ezanvakti_entry(entry)
            if schedule is not None:
                schedules[entry_day] = schedule
        return schedules

    def _district_id(self, location: GeoLocation) -> str | None:
        key = (location.city or "", location.country or "")
        if key not in self._district_ids:
            self._district_ids[key] = _lookup_ezanvakti_district_id(
                location, timeout=self.timeout
            )
        return self._district_ids[key]


def _from_ezanvakti_entry(entry: dict) -> PrayerSchedule | None:
    times = entry.get("times") or {}
    values: dict[str, time] = {}
    for src, dst in EZANVAKTI_TIME_KEYS.items():
        raw = (times.get(src) or "").strip()
        if not raw:
            return None
        values[dst] = _parse_hhmm(raw)
    return PrayerSchedule(**values)


def _normalize_ezanvakti_name(value: str) -> str:
    return re.sub(r"[^\w]+", "", value.casefold())


def _ezanvakti_get(path: str, params: dict[str, object] | None = None, *, timeout: float = 10.0):
    response = requests.get(EZANVAKTI_API + path, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("success") is False:
        raise ValueError(payload.get("message") or "EzanVakti request failed")
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def _ezanvakti_country_id(country: str, *, timeout: float = 10.0) -> str | None:
    if not (country or "").strip():
        return None
    countries = _ezanvakti_get("/locations/countries", timeout=timeout)
    if not isinstance(countries, list):
        return None
    needle = _normalize_ezanvakti_name(country)
    for entry in countries:
        for field in ("name", "name_en"):
            name = _normalize_ezanvakti_name(str(entry.get(field, "")))
            if needle == name or needle in name:
                return str(entry.get("_id"))
    return None


def _lookup_ezanvakti_district_id(location: GeoLocation, *, timeout: float = 10.0) -> str | None:
    query = (location.city or "").strip()
    if not query:
        return None
    results = _ezanvakti_get("/locations/search/districts", {"q": query}, timeout=timeout)
    if not isinstance(results, list) or not results:
        return None
    country_filter = _ezanvakti_country_id(location.country, timeout=timeout)
    if country_filter:
        results = [entry for entry in results if str(entry.get("country_id")) == country_filter]
    if not results:
        return None
    needle = _normalize_ezanvakti_name(query)
    for entry in results:
        if needle in {
            _normalize_ezanvakti_name(str(entry.get("name", ""))),
            _normalize_ezanvakti_name(str(entry.get("name_en", ""))),
        }:
            return str(entry.get("_id"))
    return str(results[0].get("_id"))


class PrayerService:
    def __init__(self, config: Dir3Config, geolocator: GeoLocator | None = None) -> None:
        self.config = config
        self.geolocator = geolocator or GeoLocator(config)
        self.calculator = IslamicCalculator(
            method=config.prayer.method, madhab=config.prayer.madhab
        )
        ezanvakti = EzanVaktiProvider()
        self.providers = {
            "aladhan": AladhanProvider(),
            "ezanvakti": ezanvakti,
            "diyanet": ezanvakti,
        }
        self.cache_path = DEFAULT_CACHE_DIR / "prayer_times.json"
        self._cache = self._load_cache()

    def _load_cache(self) -> dict[str, dict[str, str]]:
        if not self.cache_path.exists():
            return {}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (JSONDecodeError, OSError):  # pragma: no cover - defensive
            return {}

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._cache, indent=1), encoding="utf-8")
        except OSError:  # pragma: no cover - read-only cache dir
            pass

    @staticmethod
    def _key(provider: str, day: date, location: GeoLocation) -> str:
        return (
            f"{provider}:{day.isoformat()}:"
            f"{location.latitude:.4f}:{location.longitude:.4f}"
        )

    def get(
        self,
        day: date,
        location: GeoLocation | None = None,
        *,
        use_online: bool | None = None,
    ) -> PrayerSchedule:
        loc = location or self.geolocator.detect()
        provider_setting = (self.config.prayer.provider or "auto").lower().strip()
        if provider_setting == "offline":
            online_chain: list[str] = []
        elif provider_setting in self.providers:
            online_chain = [provider_setting]
        else:  # "auto"/"online"/unknown -> Aladhan first, then the calculator
            online_chain = ["aladhan"]

        if use_online is not False and online_chain:
            for name in online_chain:
                provider = self.providers[name]
                cache_key = self._key(provider.name, day, loc)
                cached = self._cache.get(cache_key)
                if cached:
                    return PrayerSchedule.from_dict(cached)
                try:
                    schedule = provider.fetch(day, loc, self.config)
                except (requests.RequestException, ValueError, RuntimeError):
                    continue
                self._cache[cache_key] = schedule.to_dict()
                self._save_cache()
                return schedule

        cache_key = self._key("offline", day, loc)
        cached = self._cache.get(cache_key)
        if cached:
            return PrayerSchedule.from_dict(cached)
        schedule = self.calculator.compute(day, loc)
        self._cache[cache_key] = schedule.to_dict()
        self._save_cache()
        return schedule


def _tz_for(name: str | None):
    from .geo import _resolve_tz

    return _resolve_tz(name)
