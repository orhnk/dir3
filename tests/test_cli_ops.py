"""CLI operations: --compile/--sync/--clear/--gcal + provider inference."""

import pytest

from dir3 import cli
from dir3.services.gcal import GCalClearReport, GCalSyncReport

PLAN = """\
from datetime import time, timedelta
from dir3 import GoogleCalendar, day, task
from dir3.core import week

location = (40.7992, 29.4305, "Europe/Istanbul")
gcal = GoogleCalendar(client_id="c", client_secret="s", refresh_token="r")

@day
def sample(ctx):
    return [task("X", start=time(9, 0), duration=timedelta(minutes=30))]

plan = week(mon=sample, tue=sample, wed=sample, thu=sample,
            fri=sample, sat=sample, sun=sample)
"""

PLAN_NO_PROVIDER = """\
from datetime import time, timedelta
from dir3.core import day, task, week

location = (40.7992, 29.4305, "Europe/Istanbul")

@day
def sample(ctx):
    return [task("X", start=time(9, 0), duration=timedelta(minutes=30))]

plan = week(mon=sample, tue=sample, wed=sample, thu=sample,
            fri=sample, sat=sample, sun=sample)
"""


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _fake_ops(monkeypatch, recorded):
    def fake_syncer(settings, **kwargs):
        recorded["settings"] = settings
        return object()

    def fake_run(syncer, plan, *, timezone_name, dry_run):
        recorded["synced"] = True
        recorded["dry"] = dry_run
        return GCalSyncReport(total=1, created=1, updated=0, dry_run=dry_run)

    def fake_clear(syncer, *, dry_run, nuke=False):
        recorded["cleared"] = True
        recorded["nuke"] = nuke
        return GCalClearReport(deleted=1, dry_run=dry_run)

    monkeypatch.setattr(cli, "GoogleCalendarSyncer", fake_syncer)
    monkeypatch.setattr(cli, "run_sync", fake_run)
    monkeypatch.setattr(cli, "run_clear", fake_clear)


def test_compile_prints_without_sync(tmp_path, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN_NO_PROVIDER)
    assert cli.main([planfile, "--offline", "--until", "1", "--compile"]) == 0
    out = capsys.readouterr().out
    assert "Standort:" in out
    assert "  X" in out  # event printed...
    assert "GCal:" not in out  # ...but nothing synced


def test_bare_syncs_by_default(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1"]) == 0
    assert recorded.get("synced") is True
    out = capsys.readouterr().out
    assert "synchronisiert" in out
    assert "Standort:" not in out  # kein Plan-Print ohne --compile/--dry-run


def test_bare_without_provider_errors(tmp_path):
    planfile = _write(tmp_path, "plan.py", PLAN_NO_PROVIDER)
    with pytest.raises(SystemExit) as exc:
        cli.main([planfile, "--offline", "--until", "1"])
    assert exc.value.code == 2


def test_dry_run_prints_plan_without_writing(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Standort:" in out
    assert recorded.get("dry") is True


def test_sync_infers_gcal(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1", "--compile", "--sync"]) == 0
    assert recorded.get("synced") is True
    assert recorded["settings"].is_configured
    assert "synchronisiert" in capsys.readouterr().out


def test_gcal_alone_syncs(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1", "--gcal"]) == 0
    assert recorded.get("synced") is True
    capsys.readouterr()


def test_compile_gcal_syncs(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1", "--compile", "--gcal"]) == 0
    assert recorded.get("synced") is True
    capsys.readouterr()


def test_sync_without_provider_errors(tmp_path):
    planfile = _write(tmp_path, "plan.py", PLAN_NO_PROVIDER)
    with pytest.raises(SystemExit) as exc:
        cli.main([planfile, "--offline", "--until", "1", "--sync"])
    assert exc.value.code == 2


def test_explicit_gcal_without_config_errors(tmp_path):
    planfile = _write(tmp_path, "plan.py", PLAN_NO_PROVIDER)
    with pytest.raises(SystemExit) as exc:
        cli.main([planfile, "--offline", "--until", "1", "--gcal"])
    assert exc.value.code == 2


def test_ambiguous_providers_require_choice(tmp_path, monkeypatch):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    monkeypatch.setattr(
        cli, "_available_providers", lambda config: {"gcal": object(), "other": object()}
    )
    with pytest.raises(SystemExit) as exc:
        cli.main([planfile, "--offline", "--until", "1", "--sync"])
    assert exc.value.code == 2
    assert recorded.get("synced") is None


def test_legacy_sync_gcal_still_works(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1", "--sync-gcal"]) == 0
    assert recorded.get("synced") is True
    capsys.readouterr()


def test_clear_infers_provider(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1", "--clear"]) == 0
    assert recorded.get("cleared") is True
    assert "geloescht" in capsys.readouterr().out


def test_gcal_clear_combo(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1", "--gcal", "--clear"]) == 0
    assert recorded.get("cleared") is True
    capsys.readouterr()


def test_sync_and_clear_rejected(tmp_path):
    planfile = _write(tmp_path, "plan.py", PLAN)
    with pytest.raises(SystemExit) as exc:
        cli.main([planfile, "--offline", "--until", "1", "--sync", "--clear"])
    assert exc.value.code == 2


def test_dry_run_alias(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1", "--sync", "--dry-run"]) == 0
    assert recorded.get("dry") is True
    capsys.readouterr()


def test_nuke_needs_yes(tmp_path):
    planfile = _write(tmp_path, "plan.py", PLAN)
    with pytest.raises(SystemExit) as exc:
        cli.main([planfile, "--offline", "--until", "1", "--clear", "--nuke"])
    assert exc.value.code == 2


def test_nuke_implies_clear_and_passes_through(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1", "--nuke", "--yes"]) == 0
    assert recorded.get("cleared") is True
    assert recorded.get("nuke") is True
    capsys.readouterr()


def test_nuke_dry_run_lists_without_deleting(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path, "plan.py", PLAN)
    recorded = {}
    _fake_ops(monkeypatch, recorded)
    assert cli.main(
        [planfile, "--offline", "--until", "1", "--clear", "--nuke", "--yes", "--dry-run"]
    ) == 0
    assert recorded.get("cleared") is True
    assert recorded.get("nuke") is True
    capsys.readouterr()
