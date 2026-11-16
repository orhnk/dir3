"""`dir3 serve`: plan API, file editor, phone events and the CLI runner."""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from dir3.export import load_runtime
from dir3.server import Dir3Server

PLAN = '''\
from datetime import time
from dir3 import day, task, week

location = (52.52, 13.40, "Europe/Berlin")
prayer = "offline"


@day
def workday(ctx):
    return [
        task("Fajr", start=time(5, 0), duration="30m"),
        task("Deep Work", start=time(9, 0), duration="2h", alarm="end-10m"),
    ]


plan = week(mon=workday, tue=workday, wed=workday, thu=workday,
            fri=workday, sat=workday, sun=workday)
__title__ = "Testplan"
'''


@pytest.fixture()
def server(tmp_path: Path):
    planfile = tmp_path / "plan.py"
    planfile.write_text(PLAN, encoding="utf-8")
    (tmp_path / "plan").mkdir()
    (tmp_path / "plan" / "extra.py").write_text("# extra\n", encoding="utf-8")
    (tmp_path / "plan" / "calendar.py").write_text(
        'gcal = {"refresh_token": "secret"}\n', encoding="utf-8"
    )
    (tmp_path / "NOTES.md").write_text("# notes\n", encoding="utf-8")
    runtime = load_runtime(planfile, offline=True)
    srv = Dir3Server(("127.0.0.1", 0), runtime=runtime, token="secret")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def request(srv, method: str, path: str, body=None, token: str | None = "secret"):
    connection = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Dir3-Token"] = token
    payload = json.dumps(body).encode() if body is not None else None
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read().decode()
    connection.close()
    return response.status, (json.loads(raw) if raw else {})


def test_requires_token(server):
    status, body = request(server, "GET", "/api/plan", token=None)
    assert status == 401
    assert body["ok"] is False


def test_status_and_plan(server):
    status, body = request(server, "GET", "/api/status")
    assert status == 200
    assert body["planfile"].endswith("plan.py")

    status, plan = request(server, "GET", "/api/plan?until=1")
    assert status == 200
    assert plan["title"] == "Testplan"
    assert plan["source"]["timezone"] == "Europe/Berlin"
    assert plan["events"]
    assert plan["alarms"]
    assert any(alarm["event_name"] == "Fajr" for alarm in plan["alarms"])


def test_file_list_read_write_and_backup(server):
    status, listing = request(server, "GET", "/api/files")
    assert status == 200
    paths = [item["path"] for item in listing["files"]]
    assert "plan.py" in paths
    assert "plan/extra.py" in paths
    assert "NOTES.md" in paths
    assert "plan/calendar.py" not in paths

    # Root-level text files are listed, so they must be readable too.
    status, notes = request(server, "GET", "/api/file?path=NOTES.md")
    assert status == 200 and notes["text"] == "# notes\n"

    status, blocked = request(server, "GET", "/api/file?path=plan/calendar.py")
    assert status == 400
    assert "Zugangsdaten" in blocked["error"]

    status, content = request(server, "GET", "/api/file?path=plan/extra.py")
    assert status == 200 and content["text"] == "# extra\n"

    status, saved = request(
        server, "PUT", "/api/file",
        {"path": "plan/extra.py", "text": "# changed\n"},
    )
    assert status == 200
    assert saved["backup"]
    assert (server.base / "plan" / "extra.py").read_text() == "# changed\n"
    backup = server.base / ".dir3" / "backups" / saved["backup"]
    assert backup.read_text() == "# extra\n"


def test_path_traversal_is_rejected(server):
    status, body = request(server, "GET", "/api/file?path=../../etc/passwd")
    assert status == 400
    assert body["ok"] is False


def test_phone_event_create_and_delete(server):
    status, created = request(
        server, "POST", "/api/events",
        {
            "title": "Spor",
            "date": "2026-11-16",
            "start": "18:30",
            "end": "19:30",
            "alarms": [{"when": "start", "offset_seconds": -300, "speak": True}],
        },
    )
    assert status == 200
    event = created["event"]
    assert event["alarms"][0]["offset_seconds"] == -300

    status, plan = request(server, "GET", "/api/plan?until=1&refresh=1")
    phone = [item for item in plan["events"] if item["source"] == "phone"]
    assert [item["name"] for item in phone] == ["Spor"]
    assert any(alarm["event_name"] == "Spor" for alarm in plan["alarms"])

    status, listing = request(server, "GET", "/api/events")
    assert status == 200 and len(listing["events"]) == 1

    status, _ = request(server, "DELETE", f"/api/events?id={event['id']}")
    assert status == 200
    status, listing = request(server, "GET", "/api/events")
    assert listing["events"] == []


def test_cli_runner(server):
    status, result = request(
        server, "POST", "/api/run",
        {"action": "compile", "until": 1, "offline": True},
    )
    assert status == 200
    assert result["ok"] is True, result.get("output")
    assert "Fajr" in result["output"]


def test_unknown_action_rejected(server):
    status, body = request(server, "POST", "/api/run", {"action": "rm -rf /"})
    assert status == 400
    assert body["ok"] is False
