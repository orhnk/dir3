"""Per-day prayer times (Caelestia/Salat method).

Mirrors ``caelestia-shell/services/Salat.qml`` (+ ``extras/prayer-fetch.sh``):

* **methods table** - live ``GET /v1/methods`` with ``{id, name, lat, lon}``
  plus ``{fajr, ishaAngle, ishaInterval}`` params; ``method_auto`` picks the
  nearest authority by haversine distance (entries without a location are
  skipped). Last resort fallback is method 13 (Turkey/Diyanet).
* **location** - explicit planfile coords or IP lookup (like ``GeoLocator``),
  normalized to 4 decimals for the cache key.
* **calendar month** - ``GET /v1/calendar/{year}/{month}?lat&lon&method&school``
  whole month in one request, cached under
  ``"loc|m<method>s<school>|YYYY-M"`` so stale timetables never survive a
  settings change.
* **offline** - pure-Python solar fallback (declination + equation of time +
  per-method Fajr/Isha angles and shadow-factor Asr rule), so prayer times
  work with no network at all.

``provider = "auto"`` (default) tries cache → Aladhan → offline.
``provider = "offline"`` never touches the network (``--offline`` CLI flag).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from json import JSONDecodeError
from math import acos, atan, cos, degrees, pi, radians, sin, tan
from time import monotonic, sleep

import requests

from ..config import DEFAULT_CACHE_DIR, Dir3Config
from ..timeutils import format_time
from .geo import GeoLocation, GeoLocator

#: Aladhan returns a whole month in ONE request (fewer calls, gentler on rate
#: limits/shared IPs than one request per day).
ALADHAN_CALENDAR = "https://api.aladhan.com/v1/calendar/{year}/{month}"
ALADHAN_METHODS_URL = "https://api.aladhan.com/v1/methods"

#: Minimal pause between two upstream requests (politeness / rate-limit guard,
#: mirrors Salat.fetchMonth 120ms pace).
_REQUEST_MIN_INTERVAL = 0.12
_last_request_at = 0.0

#: HTTP statuses worth retrying with backoff (mirrors Salat.retryableStatus).
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

#: Fallback Fajr/Isha angles per method id (Salat.methodAngles); live table
#: wins whenever it can be fetched. Default = MWL (18/17).
_METHOD_FALLBACK_ANGLES: dict[int, tuple[float, float]] = {
    1: (18.0, 18.0),
    2: (15.0, 15.0),
    3: (18.0, 17.0),
    5: (19.5, 17.5),
    7: (15.0, 15.0),
    13: (18.0, 17.0),
}
_DEFAULT_ANGLES = (18.0, 17.0)
SUNRISE_SUNSET_ANGLE = 0.833


def _pace() -> None:
    global _last_request_at
    now = monotonic()
    wait = _REQUEST_MIN_INTERVAL - (now - _last_request_at)
    if wait > 0:
        sleep(wait)
    _last_request_at = monotonic()


def _get_json(
    url: str,
    params: dict[str, object] | None = None,
    *,
    timeout: float = 10.0,
    retries: int = 2,
    backoff: float = 0.6,
):
    """GET with small retries for transient failures (rate limits / flaky nets)."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            code = getattr(response, "status_code", None)
            if code in _RETRYABLE_STATUS and attempt < retries:
                sleep(backoff * (attempt + 1))
                continue
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last = exc
            if attempt < retries:
                sleep(backoff * (attempt + 1))
                continue
            raise exc
    raise last  # pragma: no cover - defensive


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance, mirrors Salat.haversineKm."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _js_round(value: float) -> int:
    """JS ``Math.round`` (half-up), *not* Python ``round`` (banker's).

    Salat.qml rounds minute fractions with ``Math.round``; Python's
    banker's rounding differs on exact ``x.5`` fractions (e.g. ``round(2.5)``
    is ``2`` but ``Math.round(2.5)`` is ``3``), which shifted occasional
    prayer times by a minute. All call sites pass non-negative values.
    """
    return int(math.floor(float(value) + 0.5))


#: Distinguishes an absent payload field (JS ``undefined`` → ``NaN``) from an
#: explicit ``null`` (JS ``Number(null)`` → ``0``) when mirroring QML coercion.
_MISSING = object()


def _js_number(value: object) -> float:
    """JS ``Number()`` coercion for Aladhan payloads (Salat.fetchMethods).

    ``undefined``/missing → ``NaN``; ``null``/``""``/whitespace → ``0``;
    numbers and numeric strings → their value; anything else → ``NaN``.
    """
    if value is _MISSING:
        return float("nan")
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return float("nan")


def _js_finite_or_none(value: object) -> float | None:
    """``Number.isFinite(Number(v)) ? Number(v) : null`` (Salat.fetchMethods)."""
    number = _js_number(value)
    return number if math.isfinite(number) else None


def parse_minutes(raw: object) -> int:
    """Parse ``"90 min"`` style Isha interval, mirrors Salat.parseMinutes."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*min", str(raw or ""))
    return _js_round(float(m.group(1))) if m else -1


def clean_time(raw: object) -> str:
    """Strip Aladhan suffixes like ``"05:06 (EET)"`` → ``"05:06``."""
    return str(raw or "00:00").split(" ")[0]


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _minutes_to_time(total_minutes: float) -> time:
    """Minutes since local midnight → HH:MM, mirrors Salat.toTime."""
    total_minutes %= 1440
    if total_minutes < 0:  # pragma: no cover - defensive wrap
        total_minutes += 1440
    hour = int(total_minutes // 60)
    minute = _js_round(total_minutes % 60)
    if minute == 60:
        minute = 0
        hour += 1
    hour %= 24
    return time(hour=hour, minute=minute)


def loc_norm(latitude: float, longitude: float) -> str:
    """``LAT,LON`` normalized to 4 decimals (Salat.locKey, LC_NUMERIC=C)."""
    return f"{float(latitude):.4f},{float(longitude):.4f}"


def month_cache_key(
    latitude: float, longitude: float, method: int, school: int, year: int, month: int
) -> str:
    """``"loc|m<method>s<school>|YYYY-M"`` (Salat.cacheKey)."""
    return f"{loc_norm(latitude, longitude)}|m{int(method)}s{int(school)}|{year}-{month}"


def angles_for(
    method_id: int, method_params: dict[int, dict] | None
) -> tuple[float | None, float | None, int]:
    """``(fajr, ishaAngle|None, ishaInterval)`` (Salat.anglesFor).

    Live ``GET /v1/methods`` params win; otherwise the small fallback table.
    """
    if method_params:
        live = method_params.get(int(method_id))
        if live:
            fajr = live.get("fajr")
            isha_angle = live.get("ishaAngle")
            isha_interval = live.get("ishaInterval", -1)
            try:
                interval = int(isha_interval) if isha_interval is not None else -1
            except (TypeError, ValueError):
                interval = -1
            if fajr is not None or isha_angle is not None or interval >= 0:
                return fajr, isha_angle, interval
    fajr, isha = _METHOD_FALLBACK_ANGLES.get(int(method_id), _DEFAULT_ANGLES)
    return fajr, isha, -1


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
            sunrise=parse_hhmm(values.get("sunrise", values["fajr"])),
            dhuhr=parse_hhmm(values["dhuhr"]),
            asr=parse_hhmm(values["asr"]),
            maghrib=parse_hhmm(values["maghrib"]),
            isha=parse_hhmm(values["isha"]),
        )


PRAYER_KEYS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")


def _parse_hhmm(value: str) -> time:
    from ..timeutils import parse_hhmm

    return parse_hhmm(clean_time(value))


def offline_compute(
    day: date,
    location: GeoLocation,
    method: int,
    school: int,
    method_params: dict[int, dict] | None = None,
) -> PrayerSchedule:
    """Pure-Python fallback, mirrors ``Salat.offlineCompute``.

    Solar position (declination + equation of time) + per-method Fajr/Isha
    angles + shadow-factor Asr. Timezone comes from the plan *location*
    (generalized from Caelestia's system zone so remote planning stays correct),
    read at **midnight** like QML's ``new Date(y, m, d)`` — noon would pick the
    post-transition offset on DST changeover days and shift every prayer by an
    hour. Day number is the calendar ordinal, exactly like prayer-fetch.sh's
    naive ``(now - Dec 31).days``.
    """
    fajr_angle, isha_angle, isha_interval = angles_for(method, method_params)
    if fajr_angle is None:
        fajr_angle = 18.0
    asr_factor = 2 if int(school) == 1 else 1

    lat_rad = radians(location.latitude)
    lon = location.longitude

    tz = _tz_for(location.timezone)
    # Midnight, like QML `new Date(y, m, d)` / shell `datetime(y, m, d)`.
    offset = tz.utcoffset(datetime(day.year, day.month, day.day, 0, 0))
    tz_hours = (offset.total_seconds() / 3600.0) if offset else 0.0

    n = day.timetuple().tm_yday
    decl_rad = radians(-23.44 * cos(2 * pi * (n + 10) / 365.25))
    b = 2 * pi * (n - 81) / 364
    eot = 9.87 * sin(2 * b) - 7.53 * cos(b) - 1.5 * sin(b)

    transit = 720.0 - eot - 4.0 * (lon - 15.0 * tz_hours)

    def hour_offset(altitude_deg: float) -> float:
        a_rad = radians(altitude_deg)
        cos_h = _clamp(
            (sin(a_rad) - sin(lat_rad) * sin(decl_rad))
            / (cos(lat_rad) * cos(decl_rad))
        )
        return degrees(acos(cos_h)) * 4.0

    sun_off = hour_offset(-SUNRISE_SUNSET_ANGLE)
    fajr_off = hour_offset(-float(fajr_angle))
    isha_off = hour_offset(-float(isha_angle)) if isha_angle is not None else -1.0

    zenith = abs(degrees(lat_rad) - degrees(decl_rad))
    asr_altitude = degrees(atan(1.0 / (tan(radians(zenith)) + asr_factor)))

    maghrib_mins = transit + sun_off
    if isha_off >= 0:
        isha_mins = transit + isha_off
    else:
        isha_mins = maghrib_mins + (isha_interval if isha_interval >= 0 else 90)

    return PrayerSchedule(
        fajr=_minutes_to_time(transit - fajr_off),
        sunrise=_minutes_to_time(transit - sun_off),
        dhuhr=_minutes_to_time(transit),
        asr=_minutes_to_time(transit + hour_offset(asr_altitude)),
        maghrib=_minutes_to_time(maghrib_mins),
        isha=_minutes_to_time(isha_mins),
    )


class PrayerService:
    """Caelestia-style prayer service: cache → Aladhan month → offline."""

    def __init__(
        self,
        config: Dir3Config,
        geolocator: GeoLocator | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.config = config
        self.geolocator = geolocator or GeoLocator(config)
        self.timeout = timeout
        self.method = int(getattr(config.prayer, "method", 13) or 13)
        try:
            self.school = 1 if int(getattr(config.prayer, "school", 0)) == 1 else 0
        except (TypeError, ValueError):
            self.school = 0
        self.method_auto = bool(getattr(config.prayer, "method_auto", True))
        self.provider = str(getattr(config.prayer, "provider", "auto") or "auto")
        self.source = ""
        self.online_ok = False
        #: month cache key → {date → schedule} (in-memory mirror of disk).
        self._months: dict[str, dict[date, PrayerSchedule]] = {}
        #: method id → {fajr, ishaAngle, ishaInterval}; [{id,name,lat,lon}].
        self.method_params: dict[int, dict] = {}
        self.method_list: list[dict] = []
        self.cache_path = DEFAULT_CACHE_DIR / "prayer_times.json"
        self._cache: dict = self._load_cache()
        self._ingest_disk_cache()

    # -- disk cache (Caelestia salat.json shape) ---------------------------

    def _load_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (JSONDecodeError, OSError):  # pragma: no cover - defensive
            return {}

    def _ingest_disk_cache(self) -> None:
        data = self._cache if isinstance(self._cache, dict) else {}
        months = data.get("months") if isinstance(data, dict) else None
        if isinstance(months, dict):
            for key, days in months.items():
                if "|m" not in str(key) or not isinstance(days, dict):
                    continue  # drop legacy entries without method/school tag
                parsed: dict[date, PrayerSchedule] = {}
                for stamp, values in days.items():
                    try:
                        entry_day = datetime.strptime(str(stamp), "%d-%m-%Y").date()
                        schedule = PrayerSchedule.from_dict(
                            {k: clean_time(v) for k, v in dict(values).items()}
                        )
                    except (ValueError, TypeError, KeyError):
                        continue
                    if "sunrise" not in dict(values):
                        continue  # legacy entry without sunrise → refetch
                    parsed[entry_day] = schedule
                if parsed:
                    self._months[str(key)] = parsed
        methods = data.get("methods") if isinstance(data, dict) else None
        if isinstance(methods, list) and methods:
            params: dict[int, dict] = {}
            method_list: list[dict] = []
            for entry in methods:
                if not isinstance(entry, dict):
                    continue
                try:
                    mid = int(entry.get("id"))
                except (TypeError, ValueError):
                    continue
                params[mid] = {
                    "fajr": entry.get("fajr"),
                    "ishaAngle": entry.get("ishaAngle"),
                    "ishaInterval": entry.get("ishaInterval", -1),
                }
                lat = entry.get("lat")
                lon = entry.get("lon")
                method_list.append(
                    {
                        "id": mid,
                        "name": str(entry.get("name", mid)),
                        "lat": float(lat) if lat is not None else None,
                        "lon": float(lon) if lon is not None else None,
                    }
                )
            if params:
                self.method_params = params
                self.method_list = sorted(method_list, key=lambda m: m["id"])

    def _save_cache(self) -> None:
        try:
            months: dict[str, dict[str, dict[str, str]]] = {}
            for key, days in self._months.items():
                if "|m" not in str(key):
                    continue
                months[str(key)] = {
                    day.strftime("%d-%m-%Y"): sched.to_dict() for day, sched in days.items()
                }
            payload = {
                "method": self.method,
                "methodAuto": self.method_auto,
                "school": self.school,
                "months": months,
                "methods": [
                    {
                        "id": m["id"],
                        "name": m.get("name", m["id"]),
                        "lat": m.get("lat"),
                        "lon": m.get("lon"),
                        **self.method_params.get(m["id"], {}),
                    }
                    for m in self.method_list
                ],
            }
            # Preserve unknown legacy keys when _cache was externally seeded
            # (e.g. portability test writes {"x": ...} and expects no crash).
            # Merge only when _cache already holds non-month data.
            if isinstance(self._cache, dict):
                for key, value in self._cache.items():
                    if key not in payload:
                        payload[key] = value
            self._cache = payload
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self._cache, indent=1), encoding="utf-8")
        except OSError:  # pragma: no cover - read-only cache dir
            pass

    @staticmethod
    def _key(*args, **kwargs) -> str:
        """Month cache key (no path separators).

        New: ``_key(day, location, method=.., school=..)``.
        Legacy: ``_key(provider, day, location)`` (provider ignored, kept
        so old callers/tests don't crash; cache is method/school-scoped).
        """
        day = kwargs.get("day")
        location = kwargs.get("location")
        method = kwargs.get("method", 13)
        school = kwargs.get("school", 0)
        positional = list(args)
        if positional and isinstance(positional[0], str):
            positional.pop(0)  # legacy provider token, cache is method/school-scoped
        if day is None and positional:
            day = positional.pop(0)
        if location is None and positional:
            location = positional.pop(0) if positional else None
        if positional:
            # remaining: method, school
            if len(positional) >= 1:
                method = positional[0]
            if len(positional) >= 2:
                school = positional[1]
        if day is None or location is None:
            raise TypeError("_key needs (day, location[, method, school])")
        try:
            method_i = int(method)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            method_i = 13
        try:
            school_i = 1 if int(school) == 1 else 0  # type: ignore[arg-type]
        except (TypeError, ValueError):
            school_i = 0
        return month_cache_key(
            location.latitude, location.longitude, method_i, school_i, day.year, day.month
        )

    # -- methods table (Salat.fetchMethods / pickMethodForLoc) -------------

    def fetch_methods(self) -> bool:
        try:
            payload = _get_json(ALADHAN_METHODS_URL, None, timeout=self.timeout)
        except requests.RequestException:
            return False
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not data:
            return False
        params: dict[int, dict] = {}
        method_list: list[dict] = []
        for key, entry in data.items():
            if not isinstance(entry, dict):
                continue
            # `Number.isFinite(Number(entry.id)) ? Math.round(Number(entry.id))`
            entry_id = _js_number(entry.get("id", _MISSING))
            if not math.isfinite(entry_id):
                continue
            mid = int(math.floor(entry_id + 0.5))
            raw = entry.get("params")
            if not isinstance(raw, dict):
                raw = {}
            fajr = _js_finite_or_none(raw.get("Fajr", _MISSING))
            isha_angle = _js_finite_or_none(raw.get("Isha", _MISSING))
            interval = parse_minutes(raw.get("Isha"))
            params[mid] = {"fajr": fajr, "ishaAngle": isha_angle, "ishaInterval": interval}
            loc = entry.get("location")
            if not isinstance(loc, dict):
                loc = {}
            lat = _js_finite_or_none(loc.get("latitude", _MISSING))
            lon = _js_finite_or_none(loc.get("longitude", _MISSING))
            method_list.append(
                {"id": mid, "name": str(entry.get("name", key)), "lat": lat, "lon": lon}
            )
        if not params:
            return False
        self.method_params = params
        self.method_list = sorted(method_list, key=lambda m: m["id"])
        self._save_cache()
        return True

    def ensure_methods(self, *, use_network: bool = True) -> bool:
        if any(m.get("lat") is not None and m.get("lon") is not None for m in self.method_list):
            return True
        if use_network and self.fetch_methods():
            return any(
                m.get("lat") is not None and m.get("lon") is not None for m in self.method_list
            )
        return False

    def pick_method_for_loc(self, latitude: float, longitude: float) -> int:
        """Nearest authority by haversine; -1 when undecidable."""
        best = -1
        best_d = float("inf")
        for entry in self.method_list:
            lat, lon = entry.get("lat"), entry.get("lon")
            if lat is None or lon is None:
                continue
            try:
                d = haversine_km(float(latitude), float(longitude), float(lat), float(lon))
            except (TypeError, ValueError):
                continue
            if d < best_d:
                best_d = d
                best = int(entry["id"])
        return best

    def resolve_method(
        self, latitude: float, longitude: float, *, use_network: bool = True
    ) -> int:
        """Explicit method wins; auto picks nearest, fallback 13 (Salat)."""
        if not self.method_auto:
            return self.method
        if self.ensure_methods(use_network=use_network):
            pick = self.pick_method_for_loc(latitude, longitude)
            if pick >= 0:
                self.method = pick
                return pick
        self.method = 13
        return 13

    # -- calendar month (Salat.fetchMonth / applyDay) ----------------------

    def _apply_day(
        self, day: date, latitude: float, longitude: float, method: int, school: int
    ) -> PrayerSchedule | None:
        key = month_cache_key(latitude, longitude, method, school, day.year, day.month)
        entry = self._months.get(key, {}).get(day)
        if entry is None:
            return None
        return entry

    def fetch_month(
        self, year: int, month: int, latitude: float, longitude: float, method: int, school: int
    ) -> dict[date, PrayerSchedule]:
        key = month_cache_key(latitude, longitude, method, school, year, month)
        cached = self._months.get(key)
        if cached:
            return cached
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "method": int(method),
            "school": int(school),
        }
        url = ALADHAN_CALENDAR.format(year=year, month=month)
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                _pace()
                payload = _get_json(url, params, timeout=self.timeout, retries=0)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < 2:
                    sleep(0.6 * (attempt + 1))
                    continue
                raise
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list) or not data:
                last_exc = ValueError("Aladhan calendar response is empty")
                if attempt < 2:
                    sleep(0.6 * (attempt + 1))
                    continue
                raise last_exc
            schedules: dict[date, PrayerSchedule] = {}
            for item in data:
                greg = ((item.get("date") or {}).get("gregorian") or {}).get("date", "")
                if not re.fullmatch(r"\d{2}-\d{2}-\d{4}", str(greg)):
                    continue
                timings = item.get("timings") or {}
                lowered = {str(k).lower(): v for k, v in timings.items()}
                day_times: dict[str, str] = {}
                usable = True
                for name in PRAYER_KEYS:
                    raw = lowered.get(name)
                    if not raw:
                        usable = False
                        break
                    day_times[name] = clean_time(raw)
                if not usable:
                    continue
                try:
                    entry_day = datetime.strptime(str(greg), "%d-%m-%Y").date()
                    schedule = PrayerSchedule.from_dict(day_times)
                except (ValueError, TypeError, KeyError):
                    continue
                schedules[entry_day] = schedule
            if schedules:
                self._months[key] = schedules
                self._save_cache()
                return schedules
            last_exc = ValueError("Aladhan calendar response has no usable entries")
            if attempt < 2:
                sleep(0.6 * (attempt + 1))
        raise last_exc or ValueError("Aladhan calendar request failed")

    # -- public API ---------------------------------------------------------

    def get(
        self,
        day: date,
        location: GeoLocation | None = None,
        *,
        use_online: bool | None = None,
    ) -> PrayerSchedule:
        loc = location or self.geolocator.detect()
        offline_only = self.provider.strip().lower() == "offline" or use_online is False

        if offline_only:
            # Pure offline calculation, like Salat.offlineCompute: deterministic,
            # so nothing is read from or written to the month cache. The cache
            # only ever holds authoritative Aladhan months — persisting offline
            # approximations here once shadowed Aladhan with 4–5 min errors.
            method = self.resolve_method(loc.latitude, loc.longitude, use_network=False)
            schedule = offline_compute(day, loc, method, self.school, self.method_params or None)
            self.source = "offline"
            self.online_ok = False
            return schedule

        method = self.resolve_method(loc.latitude, loc.longitude, use_network=True)
        cached = self._apply_day(day, loc.latitude, loc.longitude, method, self.school)
        if cached is not None:
            self.source = "cache"
            self.online_ok = True
            return cached
        try:
            schedules = self.fetch_month(
                day.year, day.month, loc.latitude, loc.longitude, method, self.school
            )
        except (requests.RequestException, ValueError):
            # Mirror Salat.offlineCompute: do NOT persist the fallback, so the
            # next run retries Aladhan instead of sticking to offline forever.
            schedule = offline_compute(day, loc, method, self.school, self.method_params or None)
            self.source = "offline"
            self.online_ok = False
            return schedule
        schedule = schedules.get(day)
        if schedule is None:
            schedule = offline_compute(day, loc, method, self.school, self.method_params or None)
            self.source = "offline"
            self.online_ok = False
            return schedule
        self.source = "aladhan"
        self.online_ok = True
        return schedule


def _tz_for(name: str | None):
    from .geo import _resolve_tz

    return _resolve_tz(name)
