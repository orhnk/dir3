"""Cross-platform robustness: every test here must pass on any OS/Python.

These tests simulate the failure modes that differ between machines
(Linux, macOS, Windows, slim containers): legacy console encodings,
missing system tzdb, read-only/corrupted cache directories and non-ASCII
planfiles.  The GitHub Actions matrix (``.github/workflows/ci.yml``) then
runs the whole suite on ubuntu/macos/windows and Python 3.10-3.14.
"""
from __future__ import annotations

import sys
import zoneinfo
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from dir3.cli import _force_utf8_stdout
from dir3.config import Dir3Config, LocationSettings, PrayerSettings
from dir3.core import day, task, week
from dir3.engine import compile_pattern
from dir3.render import render_plan
from dir3.services import Services
from dir3.services.geo import GeoLocation, GeoLocator, _resolve_tz, _system_tz
from dir3.services.prayer import PrayerService
from dir3.services.weather import WeatherService

D0 = date(2026, 9, 9)  # a Wednesday


def _services(tmp_path=None, cache_dir=None) -> Services:
    config = Dir3Config(
        location=LocationSettings(
            latitude=40.7992, longitude=29.4305, timezone="Europe/Istanbul"
        ),
        prayer=PrayerSettings(provider="offline"),
    )
    services = Services(config=config)
    if cache_dir is not None:
        services.prayer.cache_path = Path(cache_dir) / "prayer_times.json"
    return services


# ---------------------------------------------------------------------------
# Console / output encoding


def test_force_utf8_stdout_reconfigures_both_streams(monkeypatch):
    calls = []

    class FakeStream:
        name = "fake"

        def reconfigure(self, **kwargs):
            calls.append((self, kwargs))

    stdout, stderr = FakeStream(), FakeStream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    _force_utf8_stdout()

    assert len(calls) == 2
    for _, kwargs in calls:
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"


def test_force_utf8_stdout_ignores_streams_without_reconfigure(monkeypatch):
    class Dummy:
        pass

    monkeypatch.setattr(sys, "stdout", Dummy())
    monkeypatch.setattr(sys, "stderr", Dummy())
    _force_utf8_stdout()  # must not raise


def test_render_survives_legacy_ascii_sink(tmp_path):
    """Full rendered output stays encodable even on an ASCII-only console
    (with ``errors="replace"`` nobody crashes mid-print)."""
    services = _services(cache_dir=tmp_path)

    @day
    def morning(ctx):
        return [
            task("Fajr", start=ctx.prayer.fajr, until=ctx.prayer.sunrise),
            task("Frühstück", duration=timedelta(minutes=20)),
            task("Lesen ⚠", start=time(7, 0), duration=timedelta(hours=1)),
        ]

    plan = compile_pattern(week(wed=morning), days=1, start_date=D0, services=services)
    text = render_plan(plan)
    assert "Fajr" in text
    repaired = text.encode("ascii", "replace")
    assert isinstance(repaired, bytes)
    assert len(repaired) > 0


# ---------------------------------------------------------------------------
# Timezone resolution without system tzdb (slim containers / Windows)


def test_tzdata_dependency_installed():
    import tzdata

    assert isinstance(tzdata.__version__, str) and tzdata.__version__


def test_zoneinfo_resolves_without_system_tzdb():
    """Empty TZPATH must still resolve IANA zones via the tzdata package -
    this is exactly what slim containers with no /usr/share/zoneinfo hit."""
    original = zoneinfo.TZPATH
    zoneinfo.reset_tzpath(to=())
    try:
        assert zoneinfo.TZPATH == ()
        tz = zoneinfo.ZoneInfo("Europe/Istanbul")
        assert tz.utcoffset(datetime(2026, 6, 1, 12)) == timedelta(hours=3)
    finally:
        zoneinfo.reset_tzpath(to=original)


def test_resolve_tz_fixed_offsets():
    assert _resolve_tz("+03").utcoffset(None) == timedelta(hours=3)
    assert _resolve_tz("+3:00").utcoffset(None) == timedelta(hours=3)
    assert _resolve_tz("-04:30").utcoffset(None) == timedelta(hours=-4, minutes=-30)


def test_resolve_tz_utc_names_alias_to_utc():
    assert _resolve_tz("UTC").utcoffset(None) == timedelta(0)
    assert _resolve_tz("GMT").utcoffset(None) == timedelta(0)
    assert _resolve_tz("Z").utcoffset(None) == timedelta(0)


def test_resolve_tz_unknown_name_falls_back_to_local():
    tz = _resolve_tz("No/Such_Zone-That-Really-Exists")
    assert tz is not None
    assert tz is datetime.now().astimezone().tzinfo or tz.utcoffset(None) is not None


def test_system_tz_returns_nonempty():
    assert isinstance(_system_tz(), str) and _system_tz()


# ---------------------------------------------------------------------------
# Cache directory robustness


def test_cache_writes_survive_unwritable_dir(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    bad = blocked / "sub"

    prayer_svc = _services().prayer
    prayer_svc.cache_path = bad / "prayer_times.json"
    prayer_svc._cache = {"x": {"key": "v"}}
    prayer_svc._save_cache()  # must not raise

    geo = GeoLocator(Dir3Config(), cache_path=bad / "geolocation.json")
    geo._save_cache(GeoLocation(40.79, 29.43, "Europe/Istanbul"), now=datetime.now(timezone.utc))
    assert geo._load_cache() is None

    weather = WeatherService(cache_path=bad / "weather.json")
    weather._trend_cache = {"Gebze:2026-09-09": True}
    weather._save()  # must not raise


def test_cache_survives_corrupted_json(tmp_path):
    path = tmp_path / "prayer_times.json"
    path.write_text("{ definitely not json", encoding="utf-8")

    svc = _services().prayer
    svc.cache_path = path
    assert svc._load_cache() == {}

    schedule = svc.get(D0)
    assert schedule.fajr is not None


def test_prayer_cache_key_has_no_path_separators():
    key = PrayerService._key(
        "aladhan", D0, GeoLocation(40.7992, 29.4305, "Europe/Istanbul")
    )
    assert "/" not in key and "\\" not in key


# ---------------------------------------------------------------------------
# Planfile loading / source decoding


def test_planfile_examples_compile_as_utf8():
    """Planfiles contain umlauts/arrows; they must decode as UTF-8 on every
    platform (Python source defaults)."""
    examples = Path(__file__).resolve().parent.parent / "examples"
    for name, path in sorted((p.name, p) for p in examples.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        compile(path.read_bytes(), name, "exec")  # noqa: S102


def test_planfile_utf8_attributes_roundtrip():
    ns: dict = {}
    source = (
        'location = (40.7992, 29.4305, "Europe/Istanbul")\n'
        'NAME = "Köln→Türkiye ⚠"\n'
    )
    exec(compile(source, "planfile.py", "exec"), ns)  # noqa: S102
    assert ns["NAME"] == "Köln→Türkiye ⚠"
    assert ns["location"][2] == "Europe/Istanbul"
