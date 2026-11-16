"""Bit-parity with caelestia-shell Salat.offlineCompute (+ prayer-fetch.sh).

``ref_offline`` below is transliterated line-by-line from
``services/Salat.qml`` (``offlineCompute``/``toTime``/``hourOffset``) with
``prayer-fetch.sh``'s naive day count, independently of
``dir3.services.prayer.offline_compute``. The grid covers latitudes,
a full year (including both EU DST transitions), all method shapes
(angle / interval / null-fajr) and both schools.
"""
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dir3.services.geo import GeoLocation
from dir3.services.prayer import (
    _js_round,
    angles_for,
    offline_compute,
)


def _ref_hour_offset(alt_deg: float, lat_r: float, decl_r: float) -> float:
    a_r = math.radians(alt_deg)
    num = math.sin(a_r) - math.sin(lat_r) * math.sin(decl_r)
    den = math.cos(lat_r) * math.cos(decl_r)
    cos_h = max(-1.0, min(1.0, num / den))
    return math.degrees(math.acos(cos_h)) * 4.0


def _ref_to_time(total: float) -> str:
    total = ((total % 1440) + 1440) % 1440
    h = math.floor(total / 60)
    m = math.floor((total % 60) + 0.5)
    if m == 60:
        m = 0
        h += 1
    return f"{int(h % 24):02d}:{int(m):02d}"


def ref_offline(day, lat, lon, tz_hours, fajr_angle, isha_angle, isha_interval, school):
    """Straight transliteration of Salat.offlineCompute."""
    if fajr_angle is None:
        fajr_angle = 18.0
    asr_factor = 2 if school == 1 else 1
    lat_r = math.radians(lat)
    # prayer-fetch.sh: naive (now - Dec 31 prev year).days
    n = (datetime(day.year, day.month, day.day) - datetime(day.year - 1, 12, 31)).days
    decl_r = math.radians(-23.44 * math.cos(2 * math.pi * (n + 10) / 365.25))
    b = 2 * math.pi * (n - 81) / 364
    eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    transit = 720 - eot - 4 * (lon - 15 * tz_hours)
    sun_off = _ref_hour_offset(-0.833, lat_r, decl_r)
    fajr_off = _ref_hour_offset(-fajr_angle, lat_r, decl_r)
    isha_off = _ref_hour_offset(-isha_angle, lat_r, decl_r) if isha_angle is not None else -1
    zenith = abs(lat - math.degrees(decl_r))
    asr_alt = math.degrees(math.atan(1 / (math.tan(math.radians(zenith)) + asr_factor)))
    maghrib_mins = transit + sun_off
    return {
        "fajr": _ref_to_time(transit - fajr_off),
        "sunrise": _ref_to_time(transit - sun_off),
        "dhuhr": _ref_to_time(transit),
        "asr": _ref_to_time(transit + _ref_hour_offset(asr_alt, lat_r, decl_r)),
        "maghrib": _ref_to_time(maghrib_mins),
        "isha": _ref_to_time(transit + isha_off)
        if isha_off >= 0
        else _ref_to_time(maghrib_mins + (isha_interval if isha_interval >= 0 else 90)),
    }


PLACES = [
    (-33.87, 151.21, "Australia/Sydney"),
    (21.42, 39.83, "Asia/Riyadh"),
    (40.80, 29.43, "Europe/Istanbul"),
    (52.52, 13.41, "Europe/Berlin"),
    (64.15, -21.94, "Atlantic/Reykjavik"),
]

# (fajr, ishaAngle, ishaInterval, school) — MWL, Egypt, ISNA, Makkah-style,
# France, null-fajr default, each for both schools via the school loop.
ANGLE_SETS = [
    (18.0, 17.0, -1),
    (19.5, 17.5, -1),
    (15.0, 15.0, -1),
    (18.5, None, 90),
    (12.0, 12.0, -1),
    (None, 15.0, -1),
]


def _midnight_tz_hours(day: date, tzname: str) -> float:
    offset = ZoneInfo(tzname).utcoffset(datetime(day.year, day.month, day.day, 0, 0))
    return (offset.total_seconds() / 3600.0) if offset else 0.0


def test_offline_matches_caelestia_over_full_year_grid():
    checked = 0
    day = date(2026, 1, 1)
    while day.year == 2026:
        if day.timetuple().tm_yday % 5 == 1:  # every 5th day incl. DST switches
            for lat, lon, tzname in PLACES:
                loc = GeoLocation(latitude=lat, longitude=lon, timezone=tzname)
                tz_hours = _midnight_tz_hours(day, tzname)
                for school in (0, 1):
                    for fajr, isha_angle, isha_interval in ANGLE_SETS:
                        spec = (fajr, isha_angle, isha_interval)
                        params = {
                            99: {
                                "fajr": fajr,
                                "ishaAngle": isha_angle,
                                "ishaInterval": isha_interval,
                            }
                        }
                        got = offline_compute(day, loc, 99, school, params).to_dict()
                        want = ref_offline(day, lat, lon, tz_hours, *spec, school)
                        assert got == want, (day, lat, lon, school, spec, got, want)
                        checked += 1
        day += timedelta(days=1)
    assert checked > 4000


def test_js_round_is_half_up_not_bankers():
    assert _js_round(2.5) == 3
    assert _js_round(3.5) == 4
    assert _js_round(22.5) == 23
    assert _js_round(0.5) == 1
    assert _js_round(1.49) == 1
    assert _js_round(1.5) == 2


def test_midnight_tz_on_dst_transition_day():
    """2026-10-25 Berlin: midnight is +02:00, noon is +01:00 (Salat uses midnight)."""
    day = date(2026, 10, 25)
    loc = GeoLocation(latitude=52.52, longitude=13.405, timezone="Europe/Berlin")
    midnight = ZoneInfo("Europe/Berlin").utcoffset(datetime(2026, 10, 25, 0, 0))
    noon = ZoneInfo("Europe/Berlin").utcoffset(datetime(2026, 10, 25, 12, 0))
    assert midnight == timedelta(hours=2)
    assert noon == timedelta(hours=1)
    got = offline_compute(day, loc, 3, 0, None).to_dict()
    assert got == ref_offline(day, 52.52, 13.405, 2.0, 18.0, 17.0, -1, 0)
    assert got != ref_offline(day, 52.52, 13.405, 1.0, 18.0, 17.0, -1, 0)


def test_methods_table_null_coercion_matches_qml(monkeypatch, tmp_path):
    """JS Number(null) is 0 (live), Number(undefined) is NaN (missing)."""
    import dir3.services.prayer as prayer_mod

    monkeypatch.setattr(prayer_mod, "DEFAULT_CACHE_DIR", tmp_path)

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "NullFajr": {
                        "id": 60,
                        "name": "Null",
                        "params": {"Fajr": None, "Isha": 15},
                        "location": {"latitude": 41.0, "longitude": 29.0},
                    },
                    "Missing": {
                        "id": "61",
                        "name": "Missing",
                        "params": {},
                        "location": {"latitude": 41.0, "longitude": 29.0},
                    },
                    "Bad": {"id": "xx", "name": "Bad", "params": {}, "location": {}},
                }
            }

    monkeypatch.setattr(prayer_mod.requests, "get", lambda *a, **k: _R())
    from dir3.config import Dir3Config
    from dir3.services.prayer import PrayerService

    service = PrayerService(Dir3Config())
    assert service.fetch_methods() is True
    # explicit null → JS Number(null) = 0 → live entry (like QML)
    assert service.method_params[60] == {"fajr": 0.0, "ishaAngle": 15.0, "ishaInterval": -1}
    assert angles_for(60, service.method_params) == (0.0, 15.0, -1)
    # missing → NaN → null → fallback table wins (like QML anglesFor)
    assert service.method_params[61] == {"fajr": None, "ishaAngle": None, "ishaInterval": -1}
    assert angles_for(61, service.method_params) == (18.0, 17.0, -1)
    assert "xx" not in str(service.method_params)
