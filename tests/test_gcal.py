"""Google Calendar sync: async provider against mocked HTTP.

The GoogleCalendarSyncer speaks via ``httpx.AsyncClient`` (the async library
replacing blocking ``requests`` for GCal); tests inject an
``httpx.MockTransport`` so nothing touches the network.  ``asyncio.run`` keeps
the tests plain-sync.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import httpx
import pytest

from dir3 import GoogleCalendar, cli, week
from dir3.config import Dir3Config, LocationSettings, PrayerSettings
from dir3.core import day, task
from dir3.engine import compile_pattern
from dir3.services import Services
from dir3.services.gcal import (
    GCalClearReport,
    GCalSyncReport,
    GoogleCalendarSyncer,
    run_clear,
    run_sync,
)

D0 = "2026-09-09"
EVENT_ID = re.compile(r"^dir3[0-9a-f]{40}$")


def _services(tmp_path) -> Services:
    config = Dir3Config(
        location=LocationSettings(latitude=40.7992, longitude=29.4305, timezone="Europe/Istanbul"),
        prayer=PrayerSettings(provider="offline"),
    )
    services = Services(config=config)
    services.prayer.cache_path = tmp_path / "prayer_times.json"
    return services


def _plan(tmp_path, **compiler):
    from datetime import date, time, timedelta

    services = _services(tmp_path)

    @day
    def sample(ctx):
        return [
            task("Fajr", start=ctx.prayer.fajr, until=ctx.prayer.sunrise),
            task("Lesen", start=time(7, 0), duration=timedelta(hours=1)),
            task("Schlafen", start=time(23, 0), until=ctx.midnight),
        ]

    return compile_pattern(
        week(mon=sample, tue=sample, wed=sample, thu=sample, fri=sample, sat=sample, sun=sample),
        days=1,
        start_date=date.fromisoformat(D0),
        services=services,
        **compiler,
    )


def _syncer(transport):
    settings = GoogleCalendar(
        client_id="cid", client_secret="cs", refresh_token="rt", calendar_id="primary"
    )
    return GoogleCalendarSyncer(settings, transport=transport)


# ---------------------------------------------------------------------------
# Config: Planfile-Attribute


def test_from_planfile_google_calendar_instance():
    module = SimpleNamespace(
        gcal=GoogleCalendar(client_id="a", client_secret="b", refresh_token="c")
    )
    config = Dir3Config.from_planfile(module)
    assert config.calendar is not None
    assert config.calendar.is_configured
    assert config.calendar.access_token == ""


def test_from_planfile_google_calendar_dict_and_alias():
    module = SimpleNamespace(
        google_calendar={"client_id": "a", "client_secret": "b", "refresh_token": "c"}
    )
    assert Dir3Config.from_planfile(module).calendar.is_configured


def test_from_planfile_without_calendar():
    assert Dir3Config.from_planfile(SimpleNamespace()).calendar is None


def test_google_calendar_configured():
    assert not GoogleCalendar().is_configured
    assert GoogleCalendar(access_token="x").is_configured
    assert GoogleCalendar(client_id="a", client_secret="b", refresh_token="c").is_configured


# ---------------------------------------------------------------------------
# Staging (pure): payloads, determinismus, Zeitzonen, cutoffs


def test_stage_builds_deterministic_payloads(tmp_path):
    plan = _plan(tmp_path)
    plan.title = "Mein Plan"

    staged = _syncer(None).stage(plan, timezone_name="Europe/Istanbul")

    assert len(staged) == 3
    assert all(EVENT_ID.match(e.event_id) for e in staged)
    assert [e.summary for e in staged] == ["Fajr", "Lesen", "Schlafen"]
    first = staged[0]
    assert first.body["start"]["dateTime"].endswith("+03:00")
    assert first.body["start"]["timeZone"] == "Europe/Istanbul"
    assert first.body["description"] == "dir3 · Mein Plan"
    assert first.body["extendedProperties"] == {"private": {"dir3": "1"}}
    # Carry/next-day event lands on the real end moment
    sleep = staged[-1]
    assert sleep.body["end"]["dateTime"].startswith("2026-09-10T00:00:00")


def test_stage_is_idempotent(tmp_path):
    plan_a = _plan(tmp_path)
    plan_b = _plan(tmp_path)
    syncer = _syncer(None)
    a = syncer.stage(plan_a, timezone_name="Europe/Istanbul")
    b = syncer.stage(plan_b, timezone_name="Europe/Istanbul")
    assert [e.event_id for e in a] == [e.event_id for e in b]


def test_stage_skips_inactive_and_open_events(tmp_path):
    from datetime import date, time

    services = _services(tmp_path)

    @day
    def sundog(ctx):
        return [
            task("Skipped", start=time(9, 0), duration="1h", unless=lambda _ctx: True),
            task("Offen", start=time(10, 0)),
        ]

    plan = compile_pattern(
        week(mon=sundog), days=1, start_date=date.fromisoformat(D0), services=services
    )
    staged = _syncer(None).stage(plan, timezone_name="Europe/Istanbul")
    # skipped + open (no end) tasks never reach the calendar
    assert staged == []


# ---------------------------------------------------------------------------
# Async sync gegen MockTransport


def _transport(conflict=False):
    calls = {"token": 0, "post": 0, "put": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": "ya29.fake", "expires_in": 3600})
        if request.method == "PUT":
            calls["put"] += 1
            return httpx.Response(200, json={})
        calls["post"] += 1
        if conflict:
            return httpx.Response(409, json={})
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler), calls


def test_access_token_refresh_and_caching():
    transport, calls = _transport()
    syncer = _syncer(transport)

    token = __import__("asyncio").run(syncer.access_token())
    assert token == "ya29.fake"
    assert calls["token"] == 1

    token = __import__("asyncio").run(syncer.access_token())
    assert token == "ya29.fake"
    assert calls["token"] == 1  # cached, no second request


def test_sync_creates_events(tmp_path):
    transport, calls = _transport()
    syncer = _syncer(transport)
    plan = _plan(tmp_path)

    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul")

    assert report == GCalSyncReport(total=3, created=3, updated=0, dry_run=False)
    assert calls["token"] == 1
    assert calls["post"] == 3
    assert calls["put"] == 0


def test_sync_updates_on_409(tmp_path):
    transport, calls = _transport(conflict=True)
    syncer = _syncer(transport)
    plan = _plan(tmp_path)

    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul")

    assert report == GCalSyncReport(total=3, created=0, updated=3, dry_run=False)
    assert calls["post"] == 3
    assert calls["put"] == 3


def test_sync_dry_run_never_touches_network(tmp_path):
    def fail(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not fire
        raise AssertionError("dry run darf nicht ins Netzwerk")

    syncer = _syncer(httpx.MockTransport(fail))
    plan = _plan(tmp_path)
    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul", dry_run=True)

    assert report.dry_run
    assert report.total == 3
    assert report.created == 0 and report.updated == 0
    assert "geplant" in str(report)


def test_report_str():
    assert str(GCalSyncReport(total=1, created=1, updated=0, dry_run=False)) == (
        "GCal: 1 Event synchronisiert · 1 neu, 0 aktualisiert"
    )


# ---------------------------------------------------------------------------
# Clear: alle dir3-Events aus dem Kalender entfernen

GCAL_EVENT = re.compile(r"^dir3[0-9a-f]{40}$")


def _clear_transport(ids=None, pages=1):
    ids = ids or [f"dir3{'0'*38}{i:02d}" for i in range(4)]
    calls = {"token": 0, "get": 0, "delete": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": "ya29.fake", "expires_in": 3600})
        if request.method == "GET":
            calls["get"] += 1
            page_token = dict(request.url.params).get("pageToken")
            if page_token == "t1":
                return httpx.Response(200, json={"items": [{"id": ids[-1]}]})
            if pages > 1:
                rest = {"nextPageToken": "t1", "items": [{"id": i} for i in ids[:-1]]}
                return httpx.Response(200, json=rest)
            return httpx.Response(200, json={"items": [{"id": i} for i in ids]})
        calls["delete"] += 1
        assert GCAL_EVENT.match(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(204, json={})

    return httpx.MockTransport(handler), calls


def test_clear_deletes_dir3_events():
    transport, calls = _clear_transport()
    report = run_clear(_syncer(transport))

    assert report == GCalClearReport(deleted=4, dry_run=False)
    assert calls["delete"] == 4
    assert calls["get"] == 1
    assert "4 Events geloescht" in str(report)


def test_clear_ignores_calendar_creation_events():
    transport, calls = _clear_transport(pages=1)
    report = run_clear(_syncer(transport))
    assert report.deleted == 4
    # POST für ein Erstellen-zuerst-Event darf nicht passieren: nur DELETE
    assert "post" not in calls or calls.get("post", 0) == 0


def test_clear_paginates():
    transport, calls = _clear_transport(pages=2)
    report = run_clear(_syncer(transport))

    assert report.deleted == 4
    assert calls["get"] == 2
    assert calls["delete"] == 4


def test_clear_dry_run_only_lists():
    transport, calls = _clear_transport()
    report = run_clear(_syncer(transport), dry_run=True)

    assert report == GCalClearReport(deleted=4, dry_run=True)
    assert calls["delete"] == 0
    assert "wuerde 4 Events loeschen" in str(report)


def test_clear_empty_list_no_deletes():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ya29.fake", "expires_in": 3600})
        return httpx.Response(200, json={"items": []})

    transport = httpx.MockTransport(handler)
    report = run_clear(_syncer(transport))
    assert report.deleted == 0


# ---------------------------------------------------------------------------
# CLI-Verdrahtung


INTEGRATION_PLAN = '''
from datetime import time, timedelta
from dir3 import GoogleCalendar, day, task
from dir3.core import week

location = (40.7992, 29.4305, "Europe/Istanbul")
gcal = GoogleCalendar(client_id="cid", client_secret="cs", refresh_token="rt")

@day
def sample(ctx):
    return [task("SyncTest", start=time(9, 0), duration=timedelta(minutes=30))]

plan = week(mon=sample, tue=sample, wed=sample, thu=sample, fri=sample, sat=sample, sun=sample)
'''


def test_cli_sync_gcal_flag(tmp_path, monkeypatch, capsys):
    planfile = tmp_path / "gcal_plan.py"
    planfile.write_text(INTEGRATION_PLAN, encoding="utf-8")
    recorded = {}

    def fake_syncer(settings, *, transport=None, timeout=10.0):
        recorded["settings"] = settings
        return object()

    def fake_run(syncer, plan, *, timezone_name, dry_run):
        recorded["tz"] = timezone_name
        recorded["dry"] = dry_run
        return GCalSyncReport(total=7, created=7, updated=0, dry_run=False)

    monkeypatch.setattr(cli, "GoogleCalendarSyncer", fake_syncer)
    monkeypatch.setattr(cli, "run_sync", fake_run)

    assert cli.main([str(planfile), "--offline", "--until", "1", "--sync-gcal"]) == 0
    assert recorded["settings"].is_configured
    assert recorded["tz"] == "Europe/Istanbul"
    assert recorded["dry"] is False
    assert "GCal: 7 Events synchronisiert" in capsys.readouterr().out


def test_cli_sync_gcal_missing_credentials(tmp_path, monkeypatch):
    planfile = tmp_path / "no_gcal.py"
    planfile.write_text(
        "from datetime import time, timedelta\n"
        "from dir3.core import day, task\n\n"
        "location = (40.7992, 29.4305, 'Europe/Istanbul')\n\n"
        "@day\n"
        "def sample(ctx):\n"
        "    return [task('X', start=time(9, 0), duration=timedelta(minutes=30))]\n\n"
        "plan = day(sample)\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        cli.main([str(planfile), "--offline", "--sync-gcal"])
    assert exc.value.code == 2


def test_cli_gcal_clear_flag(tmp_path, monkeypatch, capsys):
    planfile = tmp_path / "gcal_plan.py"
    planfile.write_text(INTEGRATION_PLAN, encoding="utf-8")
    recorded = {}

    def fake_syncer(settings, *, transport=None, timeout=10.0):
        recorded["settings"] = settings
        return object()

    def fake_run(syncer, *, dry_run):
        recorded["dry"] = dry_run
        return GCalClearReport(deleted=3, dry_run=False)

    monkeypatch.setattr(cli, "GoogleCalendarSyncer", fake_syncer)
    monkeypatch.setattr(cli, "run_clear", fake_run)

    assert cli.main([str(planfile), "--offline", "--until", "1", "--gcal-clear"]) == 0
    assert recorded["settings"].is_configured
    assert recorded["dry"] is False
    assert "3 Events geloescht" in capsys.readouterr().out


def test_cli_gcal_clear_mutually_exclusive(tmp_path):
    planfile = tmp_path / "gcal_plan.py"
    planfile.write_text(INTEGRATION_PLAN, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.main([str(planfile), "--offline", "--sync-gcal", "--gcal-clear"])
    assert exc.value.code == 2
