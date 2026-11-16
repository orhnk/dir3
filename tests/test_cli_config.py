"""Central --config file: shared location/prayer/gcal for lean day planfiles."""
from datetime import date
from types import SimpleNamespace

import pytest

from dir3 import cli
from dir3.config import Dir3Config

PLAN = """\
from datetime import time, timedelta
from dir3 import day, task, week

location = (40.7992, 29.4305, "Europe/Istanbul")


@day
def sample(ctx):
    return [task("X", start=time(9, 0), duration=timedelta(minutes=30))]


plan = week(mon=sample, tue=sample, wed=sample, thu=sample,
            fri=sample, sat=sample, sun=sample)
"""

PLAN_WITH_GCAL = PLAN + """\
from dir3 import GoogleCalendar

gcal = GoogleCalendar(
    client_id="cid-plan",
    client_secret="cs",
    refresh_token="rt",
    calendar_id="primary",
)
"""

CENTRAL_GCAL_NO_IMPORT = """\
gcal = GoogleCalendar(
    client_id="cid-central",
    client_secret="cs",
    refresh_token="rt",
    calendar_id="primary",
)
"""

CENTRAL_LOCATION = """\
location = (40.7992, 29.4305, "Europe/Istanbul")
"""

PLAN_SYNC_DEFAULTS = PLAN + """\
sync = {
    "config": "calendar.py",
    "until": 2,
    "from": "2026-11-14",
    "offline": True,
}
"""


def _write(path, content: str):
    path.write_text(content, encoding="utf-8")
    return str(path)


def _fake_gcal(monkeypatch, recorded: dict):
    def fake_syncer(settings, **kwargs):
        recorded["settings"] = settings
        return object()

    def fake_run(syncer, plan, *, timezone_name, dry_run):
        recorded["tz"] = timezone_name
        recorded["plan"] = plan
        return "ok"

    monkeypatch.setattr(cli, "GoogleCalendarSyncer", fake_syncer)
    monkeypatch.setattr(cli, "run_sync", fake_run)


def test_central_gcal_enables_sync_without_planfile_import(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path / "plan.py", PLAN)
    central = _write(tmp_path / "calendar.py", CENTRAL_GCAL_NO_IMPORT)
    recorded: dict = {}
    _fake_gcal(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1", "--sync-gcal",
                     "--config", central]) == 0
    assert recorded["settings"].client_id == "cid-central"
    assert recorded["tz"] == "Europe/Istanbul"
    capsys.readouterr()


def test_planfile_gcal_wins_over_central(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path / "plan.py", PLAN_WITH_GCAL)
    central = _write(tmp_path / "calendar.py", CENTRAL_GCAL_NO_IMPORT)
    recorded: dict = {}
    _fake_gcal(monkeypatch, recorded)
    assert cli.main([planfile, "--offline", "--until", "1", "--sync-gcal",
                     "--config", central]) == 0
    assert recorded["settings"].client_id == "cid-plan"
    capsys.readouterr()


def test_central_location_used_when_planfile_has_none(tmp_path, capsys):
    planfile = _write(tmp_path / "plan.py", PLAN)
    central = _write(tmp_path / "calendar.py", CENTRAL_LOCATION)
    assert cli.main([planfile, "--offline", "--until", "1", "--compile",
                     "--config", central]) == 0
    assert "Europe/Istanbul" in capsys.readouterr().out


def test_missing_config_file_errors(tmp_path):
    planfile = _write(tmp_path / "plan.py", PLAN)
    with pytest.raises(SystemExit) as exc:
        cli.main([planfile, "--offline", "--config", str(tmp_path / "nope.py")])
    assert exc.value.code == 2


def test_overlay_precedence_without_files():
    central = SimpleNamespace(location=(1.0, 2.0, "UTC"), prayer="aladhan")
    plan = SimpleNamespace(prayer="offline")
    config = Dir3Config().overlay(central).overlay(plan)
    assert config.location.latitude == 1.0
    assert config.location.timezone == "UTC"
    assert config.prayer.provider == "offline"
    assert config.calendar is None


def test_overlay_sync_defaults_accepts_from_and_config():
    module = SimpleNamespace(
        sync={"from": "2026-11-14", "until": 7, "offline": True, "config": "calendar.py"}
    )
    config = Dir3Config().overlay(module)
    assert config.sync.start == date(2026, 11, 14)
    assert config.sync.until == 7
    assert config.sync.offline is True
    assert config.sync.config == "calendar.py"


def test_overlay_sync_rejects_unknown_option():
    module = SimpleNamespace(sync={"bogus": 1})
    with pytest.raises(ValueError, match="bogus"):
        Dir3Config().overlay(module)


def test_planfile_sync_defaults_used_without_flags(tmp_path, monkeypatch, capsys):
    planfile = _write(tmp_path / "plan.py", PLAN_SYNC_DEFAULTS)
    _write(tmp_path / "calendar.py", CENTRAL_GCAL_NO_IMPORT)
    recorded: dict = {}
    _fake_gcal(monkeypatch, recorded)

    assert cli.main([planfile, "--sync"]) == 0
    assert recorded["settings"].client_id == "cid-central"
    assert recorded["tz"] == "Europe/Istanbul"
    assert recorded["plan"].start == date(2026, 11, 14)
    assert len(recorded["plan"].days) == 2
    capsys.readouterr()


def test_explicit_until_overrides_planfile_default(tmp_path, monkeypatch, capsys):
    planfile = _write(
        tmp_path / "plan.py",
        PLAN + 'sync = {"config": "calendar.py", "until": 2, "offline": True}\n',
    )
    _write(tmp_path / "calendar.py", CENTRAL_GCAL_NO_IMPORT)
    recorded: dict = {}
    _fake_gcal(monkeypatch, recorded)

    assert cli.main([planfile, "--sync", "--until", "3"]) == 0
    assert len(recorded["plan"].days) == 3
    capsys.readouterr()


def test_explicit_config_overrides_planfile_sync_config(tmp_path, monkeypatch, capsys):
    planfile = _write(
        tmp_path / "plan.py",
        PLAN + 'sync = {"config": "calendar.py", "offline": True}\n',
    )
    _write(tmp_path / "calendar.py", CENTRAL_GCAL_NO_IMPORT)
    other = _write(
        tmp_path / "other.py",
        'gcal = GoogleCalendar(client_id="cid-other", client_secret="cs", '
        'refresh_token="rt")\n',
    )
    recorded: dict = {}
    _fake_gcal(monkeypatch, recorded)

    assert cli.main([planfile, "--sync", "--config", other]) == 0
    assert recorded["settings"].client_id == "cid-other"
    capsys.readouterr()


def test_unknown_sync_option_is_a_friendly_error(tmp_path, capsys):
    planfile = _write(tmp_path / "plan.py", PLAN + 'sync = {"bogus": 1}\n')
    assert cli.main([planfile, "--offline", "--until", "1", "--compile"]) == 1
    assert "unbekannte sync-Option" in capsys.readouterr().err
