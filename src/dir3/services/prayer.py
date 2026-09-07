"""Per-day prayer times.

Two sources, mirroring munazzim's approach:

* **online** - Aladhan API (``https://api.aladhan.com/v1/timings/...``), cached
  on disk so a recompile on the same day is deterministic and offline-safe;
* **offline** - a pure-Python Islamic calculator with the classic hour-angle
  method (declination + equation of time + per-method Fajr/Isha angles and the
  shadow-factor Asr rule), so prayer times work with no network at all.

``provider = "auto"`` tries Aladhan first and falls back to the calculator.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from json import JSONDecodeError
from math import acos, atan, cos, degrees, pi, radians, sin, tan

import requests

from ..config import DEFAULT_CACHE_DIR, Dir3Config
from ..timeutils import format_time
from .geo import GeoLocation, GeoLocator

ALADHAN_API = "https://api.aladhan.com/v1/timings/{day}"
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


class PrayerService:
    def __init__(self, config: Dir3Config, geolocator: GeoLocator | None = None) -> None:
        self.config = config
        self.geolocator = geolocator or GeoLocator(config)
        self.calculator = IslamicCalculator(
            method=config.prayer.method, madhab=config.prayer.madhab
        )
        self.aladhan = AladhanProvider()
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
    def _key(day: date, location: GeoLocation) -> str:
        return f"{day.isoformat()}:{location.latitude:.4f}:{location.longitude:.4f}"

    def get(
        self,
        day: date,
        location: GeoLocation | None = None,
        *,
        use_online: bool | None = None,
    ) -> PrayerSchedule:
        loc = location or self.geolocator.detect()
        cache_key = self._key(day, loc)
        cached = self._cache.get(cache_key)
        if cached:
            return PrayerSchedule.from_dict(cached)

        provider = (self.config.prayer.provider or "auto").lower()
        attempt_online = (provider in {"auto", "online"}) and use_online is not False
        schedule = None
        if attempt_online and not (provider == "offline"):
            try:
                schedule = self.aladhan.fetch(day, loc, self.config)
            except requests.RequestException:
                schedule = None
        if schedule is None:
            schedule = self.calculator.compute(day, loc)

        self._cache[cache_key] = schedule.to_dict()
        self._save_cache()
        return schedule


def _tz_for(name: str | None):
    from .geo import _resolve_tz

    return _resolve_tz(name)
