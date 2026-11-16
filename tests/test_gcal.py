"""Google Calendar sync via aiogoogle, against a fake client.

The fake mimics exactly the aiogoogle surface dir3 uses (``discover`` +
``as_user`` with ``calendar.events.*`` requests), so no test touches the
network.  ``asyncio.run`` via :func:`run_sync`/:func:`run_clear` keeps the
tests plain-sync.
"""
from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from dir3 import DefaultIconPolicy, GoogleCalendar, cli, week
from dir3.config import Dir3Config, LocationSettings, PrayerSettings
from dir3.core import Todo, day, task
from dir3.engine import compile_pattern
from dir3.services import Services
from dir3.services.gcal import (
    GCalClearReport,
    GCalSyncReport,
    GoogleCalendarSyncer,
    _creds_for,
    run_clear,
    run_sync,
)

D0 = "2026-09-09"
EVENT_ID = re.compile(r"^[0-9a-f]{40}$")


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


# ---------------------------------------------------------------------------
# Fake aiogoogle client (discover + as_user + calendar.events.*)


class _Conflict(Exception):
    """Stub for errors surfaced via ``Response.raise_for_status()``."""

    def __init__(self, status: int = 409) -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status


class _FakeResponse:
    """Stub shaped like ``aiogoogle.models.Response`` (status + raiser)."""

    def __init__(self, status_code: int, json=None, headers=None) -> None:
        self.status_code = status_code
        self.json = json
        self.data = ""
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise _Conflict(self.status_code)


class _FakeEvents:
    """Mirrors aiogoogle's Method surface: JSON body goes via ``json=``."""

    def __init__(self, fake: _FakeAiogoogle) -> None:
        self._fake = fake

    def insert(self, **kwargs):
        assert "body" not in kwargs, "aiogoogle takes json=, not body="
        return SimpleNamespace(kind="insert", kwargs=kwargs)

    def update(self, **kwargs):
        assert "body" not in kwargs, "aiogoogle takes json=, not body="
        return SimpleNamespace(kind="update", kwargs=kwargs)

    def patch(self, **kwargs):
        assert "body" not in kwargs, "aiogoogle takes json=, not body="
        return SimpleNamespace(kind="patch", kwargs=kwargs)

    def list(self, **kwargs):
        return SimpleNamespace(kind="list", kwargs=kwargs)

    def delete(self, **kwargs):
        return SimpleNamespace(kind="delete", kwargs=kwargs)


class _FakeTasklists:
    def __init__(self, fake: _FakeAiogoogle) -> None:
        self._fake = fake

    def list(self, **kwargs):
        return SimpleNamespace(kind="tasklists.list", kwargs=kwargs)

    def insert(self, **kwargs):
        assert "body" not in kwargs, "aiogoogle takes json=, not body="
        return SimpleNamespace(kind="tasklists.insert", kwargs=kwargs)


class _FakeTasksResource:
    def __init__(self, fake: _FakeAiogoogle) -> None:
        self._fake = fake

    def list(self, **kwargs):
        return SimpleNamespace(kind="tasks.list", kwargs=kwargs)

    def insert(self, **kwargs):
        assert "body" not in kwargs, "aiogoogle takes json=, not body="
        return SimpleNamespace(kind="tasks.insert", kwargs=kwargs)

    def patch(self, **kwargs):
        assert "body" not in kwargs, "aiogoogle takes json=, not body="
        return SimpleNamespace(kind="tasks.patch", kwargs=kwargs)

    def delete(self, **kwargs):
        return SimpleNamespace(kind="tasks.delete", kwargs=kwargs)


class _FakeTasksApi:
    def __init__(self, fake: _FakeAiogoogle) -> None:
        self.tasklists = _FakeTasklists(fake)
        self.tasks = _FakeTasksResource(fake)


class _FakeCalendar:
    def __init__(self, fake: _FakeAiogoogle) -> None:
        self.events = _FakeEvents(fake)


RATE_LIMIT_JSON = {
    "error": {
        "errors": [{"reason": "rateLimitExceeded"}],
        "message": "Rate Limit Exceeded",
    }
}


class _FakeAiogoogle:
    def __init__(
        self, *, conflict: bool = False, ids=None, events=None, pages: int = 1,
        error_status=None, gone_ids=(), strict_ids: bool = True,
        fail_first_batches: int = 0, fail_status: int = 429, fail_json=None,
        retry_after: str | None = None, tasklists=None, tasks=None,
        task_error_status: int | None = None,
    ) -> None:
        self.calls = {
            "token": 0, "insert": 0, "update": 0, "patch": 0, "list": 0, "delete": 0,
            "tasklists.list": 0, "tasklists.insert": 0, "tasks.list": 0,
            "tasks.insert": 0, "tasks.patch": 0, "tasks.delete": 0,
        }
        if events is not None:
            self.store = {item["id"]: dict(item) for item in events}
        else:
            default_ids = ids if ids is not None else [f"{n:040x}" for n in range(4)]
            self.store = {i: {"id": i} for i in default_ids}
        self.tasklists = {
            item["id"]: dict(item) for item in (tasklists or [])
        }
        self.tasks = {item["id"]: dict(item) for item in (tasks or [])}
        self.task_bodies: list = []
        self._next_task_id = 1
        self._next_list_id = 1
        self.task_error_status = task_error_status
        self.retry_after = retry_after
        self.batches: list = []
        self.bodies: list = []
        self.list_kwargs: list = []
        self.conflict = conflict
        self.error_status = error_status
        self.gone_ids = set(gone_ids)
        self.strict_ids = strict_ids
        self.fail_first_batches = fail_first_batches
        self.fail_status = fail_status
        self.fail_json = fail_json
        self._full_res_calls = 0
        self.pages = pages
        self._token_taken = False
        self.in_flight = 0
        self.max_in_flight = 0

    async def discover(self, api_name, api_version=None, **kwargs):
        if (api_name, api_version) == ("calendar", "v3"):
            return _FakeCalendar(self)
        if (api_name, api_version) == ("tasks", "v1"):
            return _FakeTasksApi(self)
        raise AssertionError(f"unexpected API {api_name} {api_version}")

    async def as_user(self, *requests, full_res=False, raise_for_status=True, **kwargs):
        if not self._token_taken:
            # aiogoogle refreshes creds once per client, on first use
            self._token_taken = True
            self.calls["token"] += 1
        if full_res:
            self.batches.append(len(requests))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)  # anderen Day-Tasks die Chance zum Interleaven geben
        finally:
            self.in_flight -= 1
        if full_res:
            self._full_res_calls += 1
            if self._full_res_calls <= self.fail_first_batches:
                responses = [
                    _FakeResponse(
                        self.fail_status,
                        json=self.fail_json,
                        headers=self._retry_headers(),
                    )
                    for _ in requests
                ]
            else:
                responses = [self._respond(request) for request in requests]
            if raise_for_status:
                for res in responses:
                    res.raise_for_status()
        else:
            responses = [self._content(request) for request in requests]
        return responses[0] if len(responses) == 1 else responses

    def _retry_headers(self) -> dict:
        return {"Retry-After": self.retry_after} if self.retry_after is not None else {}

    def _respond(self, request):
        kind = request.kind
        self.calls[kind] += 1
        if kind == "insert":
            body = request.kwargs["json"]
            self.bodies.append(body)
            if self.error_status is not None:
                return _FakeResponse(self.error_status)
            if self.conflict or body["id"] in self.store:
                return _FakeResponse(409)
            self.store[body["id"]] = dict(body)
            return _FakeResponse(201)
        if kind in ("update", "patch"):
            event_id = request.kwargs["eventId"]
            current = self.store.setdefault(event_id, {"id": event_id})
            current.update(
                {k: v for k, v in request.kwargs["json"].items() if k != "id"}
            )
            current["id"] = event_id
            return _FakeResponse(200)
        if kind == "delete":
            if self.strict_ids:
                assert GCAL_EVENT.match(request.kwargs["eventId"])
            if request.kwargs["eventId"] in self.gone_ids:
                return _FakeResponse(410)
            self.store.pop(request.kwargs["eventId"], None)
            return _FakeResponse(204)
        if kind == "list":
            return _FakeResponse(200)
        if kind == "tasklists.insert":
            if self.error_status is not None:
                return _FakeResponse(self.error_status)
            body = request.kwargs["json"]
            list_id = f"list-{self._next_list_id}"
            self._next_list_id += 1
            self.tasklists[list_id] = {"id": list_id, "title": body["title"]}
            return _FakeResponse(200, json=self.tasklists[list_id])
        if kind == "tasks.insert":
            if self.error_status is not None:
                return _FakeResponse(self.error_status)
            item = self._new_task(request.kwargs["tasklist"], request.kwargs["json"])
            return _FakeResponse(200, json=item)
        if kind == "tasks.patch":
            if self.error_status is not None:
                return _FakeResponse(self.error_status)
            task_id = request.kwargs["task"]
            current = self.tasks.setdefault(task_id, {"id": task_id})
            current.update(
                {k: v for k, v in request.kwargs["json"].items() if k != "id"}
            )
            current["id"] = task_id
            return _FakeResponse(200, json=current)
        if kind == "tasks.delete":
            task_id = request.kwargs["task"]
            if task_id in self.gone_ids:
                return _FakeResponse(410)
            self.tasks.pop(task_id, None)
            return _FakeResponse(204)
        raise AssertionError(f"unexpected call {kind}")

    def _new_task(self, tasklist: str, body: dict) -> dict:
        task_id = f"task-{self._next_task_id}"
        self._next_task_id += 1
        item = {
            "id": task_id,
            "tasklist": tasklist,
            "title": body.get("title", ""),
            "notes": body.get("notes", ""),
            "due": body.get("due", ""),
            "status": "needsAction",
        }
        self.task_bodies.append(body)
        self.tasks[task_id] = item
        return item

    def _content(self, request):
        kind = request.kind
        self.calls[kind] += 1
        if kind == "list":
            self.list_kwargs.append(request.kwargs)
            items = list(self.store.values())
            if request.kwargs.get("pageToken") == "t1":
                return {"items": items[-1:]}
            if self.pages > 1:
                return {"nextPageToken": "t1", "items": items[:-1]}
            return {"items": items}
        if kind == "update":
            return {}
        if kind == "delete":
            if self.strict_ids:
                assert GCAL_EVENT.match(request.kwargs["eventId"])
            return None
        if kind == "tasklists.list":
            if self.task_error_status is not None:
                raise _Conflict(self.task_error_status)
            return {"items": list(self.tasklists.values())}
        if kind == "tasklists.insert":
            if self.task_error_status is not None:
                raise _Conflict(self.task_error_status)
            body = request.kwargs["json"]
            list_id = f"list-{self._next_list_id}"
            self._next_list_id += 1
            self.tasklists[list_id] = {"id": list_id, "title": body["title"]}
            return self.tasklists[list_id]
        if kind == "tasks.list":
            if self.task_error_status is not None:
                raise _Conflict(self.task_error_status)
            tasklist = request.kwargs["tasklist"]
            return {
                "items": [
                    task for task in self.tasks.values() if task.get("tasklist") == tasklist
                ]
            }
        if kind == "tasks.insert":
            return self._new_task(request.kwargs["tasklist"], request.kwargs["json"])
        if kind == "tasks.patch":
            task_id = request.kwargs["task"]
            current = self.tasks.setdefault(task_id, {"id": task_id})
            current.update(
                {k: v for k, v in request.kwargs["json"].items() if k != "id"}
            )
            current["id"] = task_id
            return current
        if kind == "tasks.delete":
            self.tasks.pop(request.kwargs["task"], None)
            return None
        raise AssertionError(f"unexpected call {kind}")


def _factory(fake: _FakeAiogoogle):
    @asynccontextmanager
    async def open_client(settings, timeout):
        yield fake, await fake.discover("calendar", "v3")

    return open_client


def _syncer(fake: _FakeAiogoogle, **settings_kwargs):
    settings = GoogleCalendar(
        client_id="cid", client_secret="cs", refresh_token="rt", calendar_id="primary"
    )
    for key, value in settings_kwargs.items():
        setattr(settings, key, value)
    return GoogleCalendarSyncer(settings, client_factory=_factory(fake))


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


def test_creds_for_refresh_and_access_token():
    user_creds, client_creds = _creds_for(
        GoogleCalendar(client_id="a", client_secret="b", refresh_token="c")
    )
    assert user_creds["refresh_token"] == "c"
    assert client_creds["client_id"] == "a"

    user_creds, client_creds = _creds_for(GoogleCalendar(access_token="x"))
    assert user_creds["access_token"] == "x"
    assert user_creds.get("expires_at") is not None
    assert client_creds is None


# ---------------------------------------------------------------------------
# Staging (pure): payloads, determinismus, Zeitzonen, cutoffs


def test_stage_builds_deterministic_payloads(tmp_path):
    plan = _plan(tmp_path)
    plan.title = "Mein Plan"

    staged = _syncer(_FakeAiogoogle()).stage(plan, timezone_name="Europe/Istanbul")

    assert len(staged) == 3
    assert all(EVENT_ID.match(e.event_id) for e in staged)
    assert [e.summary for e in staged] == ["🕋 Fajr", "Lesen", "🌙 Schlafen"]
    first = staged[0]
    assert first.body["id"] == first.event_id
    assert first.body["start"]["dateTime"].endswith("+03:00")
    assert first.body["start"]["timeZone"] == "Europe/Istanbul"
    assert first.body["description"] == "dir3 · Mein Plan"
    assert first.body["extendedProperties"] == {
        "private": {
            "dir3": "1",
            "dir3plan": "Mein Plan",
            "dir3key": "Mein Plan|2026-09-09|Fajr|1",
        }
    }
    # Stabiler Schluessel: unabhaengig von den Zeiten
    assert first.key == "Mein Plan|2026-09-09|Fajr|1"
    shifted = _syncer(_FakeAiogoogle()).stage(plan, timezone_name="Europe/Istanbul")
    assert [e.key for e in shifted] == [
        "Mein Plan|2026-09-09|Fajr|1",
        "Mein Plan|2026-09-09|Lesen|1",
        "Mein Plan|2026-09-09|Schlafen|1",
    ]
    # Carry/next-day event lands on the real end moment
    sleep = staged[-1]
    assert sleep.body["end"]["dateTime"].startswith("2026-09-10T00:00:00")


def test_stage_uses_icon_policy_for_titles(tmp_path):
    plan = _plan(tmp_path)
    settings = GoogleCalendar(
        client_id="cid", client_secret="cs", refresh_token="rt", calendar_id="primary"
    )
    syncer = GoogleCalendarSyncer(
        settings,
        client_factory=_factory(_FakeAiogoogle()),
        icon_policy=DefaultIconPolicy(prayers="☪"),
    )
    staged = syncer.stage(plan, timezone_name="Europe/Istanbul")
    assert [e.summary for e in staged] == ["☪ Fajr", "Lesen", "🌙 Schlafen"]
    # Die Event-ID hängt am Roh-Namen - Titel-/Icon-Änderungen bleiben Updates.
    assert staged[0].body["id"] == staged[0].event_id


def test_stage_is_idempotent(tmp_path):
    plan_a = _plan(tmp_path)
    plan_b = _plan(tmp_path)
    syncer = _syncer(_FakeAiogoogle())
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
    staged = _syncer(_FakeAiogoogle()).stage(plan, timezone_name="Europe/Istanbul")
    # skipped + open (no end) tasks never reach the calendar
    assert staged == []


def _plan_with_google_task(tmp_path, *, start=None, task_list="Wucūbāt", title="Plan"):
    from datetime import date, time, timedelta

    services = _services(tmp_path)
    start = start or time(19, 45)

    @day
    def sample(ctx):
        return [
            task(
                "Wucūbāt lesen",
                start=start,
                duration=timedelta(hours=1),
                task_list=task_list,
            )
        ]

    return compile_pattern(
        week(mon=sample, tue=sample, wed=sample, thu=sample, fri=sample, sat=sample, sun=sample),
        days=1,
        start_date=date.fromisoformat(D0),
        services=services,
        title=title,
    )


def test_stage_tasks_datetime_due_notes_and_event_unchanged(tmp_path):
    syncer = _syncer(_FakeAiogoogle())
    plain = _plan_with_google_task(tmp_path, task_list=None)
    hybrid = _plan_with_google_task(tmp_path)

    events = syncer.stage(hybrid, timezone_name="Europe/Istanbul")
    tasks = syncer.stage_tasks(hybrid, timezone_name="Europe/Istanbul")

    assert events[0].body == syncer.stage(plain, timezone_name="Europe/Istanbul")[0].body
    assert len(tasks) == 1
    staged = tasks[0]
    assert staged.title == "Wucūbāt lesen"
    assert staged.list_name == "Wucūbāt"
    assert staged.due == D0
    assert staged.key == events[0].key
    assert "19:45–20:45 · 1:00 h" in staged.notes
    assert f"dir3key: {staged.key}" in staged.notes
    assert "dir3plan: Plan" in staged.notes


def test_stage_attached_todos_are_task_only_at_event_end(tmp_path):
    from datetime import date, time, timedelta

    services = _services(tmp_path)

    @day
    def sample(ctx):
        return [
            task(
                "Hitam",
                start=time(20, 29),
                duration=timedelta(minutes=15),
                task_list="Hitam",
                todos=(
                    Todo("K", todo_position="end"),
                    Todo("R", todo_position="end"),
                    Todo("P", todo_position="end"),
                ),
            )
        ]

    plan = compile_pattern(
        week(mon=sample, tue=sample, wed=sample, thu=sample, fri=sample, sat=sample, sun=sample),
        days=1,
        start_date=date.fromisoformat(D0),
        services=services,
        title="Plan",
    )
    syncer = _syncer(_FakeAiogoogle())

    events = syncer.stage(plan, timezone_name="Europe/Istanbul")
    tasks = syncer.stage_tasks(plan, timezone_name="Europe/Istanbul")

    # K, R and P are Google Tasks only - no separate calendar events and no
    # parent task for the Hitam event name.
    assert len(events) == 1
    assert events[0].summary == "Hitam"
    assert len(tasks) == 3

    children = {task.title: task for task in tasks}
    assert set(children) == {"K", "R", "P"}
    for child in children.values():
        assert child.list_name == "Hitam"
        assert child.due == D0
        assert "20:29–20:44 · 15 min" in child.notes
        assert "Todo: Hitam · am Ende" in child.notes
        assert "dir3todo: end" in child.notes
        assert child.key.endswith(f"|todo|end|{child.title}")


def test_sync_creates_attached_todos_once(tmp_path):
    from datetime import date, time, timedelta

    services = _services(tmp_path)

    @day
    def sample(ctx):
        return [
            task(
                "Hitam",
                start=time(20, 29),
                duration=timedelta(minutes=15),
                task_list="Hitam",
                todos=(Todo("K"), Todo("R"), Todo("P")),
            )
        ]

    plan = compile_pattern(
        week(mon=sample, tue=sample, wed=sample, thu=sample, fri=sample, sat=sample, sun=sample),
        days=1,
        start_date=date.fromisoformat(D0),
        services=services,
        title="Plan",
    )
    fake = _FakeAiogoogle()
    syncer = _syncer(fake)

    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul")
    assert (report.tasks_total, report.tasks_created) == (3, 3)
    assert len(fake.tasks) == 3

    writes = sum(
        fake.calls[key] for key in ("tasks.insert", "tasks.patch", "tasks.delete")
    )
    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul")
    assert (report.tasks_created, report.tasks_updated, report.tasks_deleted) == (0, 0, 0)
    assert report.tasks_unchanged == 3
    assert sum(
        fake.calls[key] for key in ("tasks.insert", "tasks.patch", "tasks.delete")
    ) == writes
    assert len(fake.tasks) == 3


def test_stage_todo_position_uses_event_end_date_across_midnight(tmp_path):
    from datetime import date, time, timedelta

    services = _services(tmp_path)

    @day
    def sample(ctx):
        return [
            task(
                "Nachtlesen",
                start=time(23, 50),
                duration=timedelta(minutes=30),
                task_list="Nacht",
                todo_position="end",
            )
        ]

    plan = compile_pattern(
        week(mon=sample, tue=sample, wed=sample, thu=sample, fri=sample, sat=sample, sun=sample),
        days=1,
        start_date=date.fromisoformat(D0),
        services=services,
        title="Plan",
    )
    task_ = _syncer(_FakeAiogoogle()).stage_tasks(
        plan, timezone_name="Europe/Istanbul"
    )[0]

    assert task_.due == "2026-09-10"
    assert "23:50–00:20" in task_.notes
    assert "Todo: Nachtlesen · am Ende" in task_.notes


# ---------------------------------------------------------------------------
# Async sync gegen Fake-Client


def test_auth_token_fetched_once_per_run(tmp_path):
    fake = _FakeAiogoogle()
    syncer = _syncer(fake)
    plan = _plan(tmp_path)

    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul")

    assert report.total == 3
    assert fake.calls["token"] == 1  # ein Refresh, dann gecacht


def test_sync_creates_events(tmp_path):
    fake = _FakeAiogoogle()
    syncer = _syncer(fake)
    plan = _plan(tmp_path)

    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul")

    assert report == GCalSyncReport(total=3, created=3, updated=0, dry_run=False)
    assert fake.calls["token"] == 1
    assert fake.calls["insert"] == 3
    assert fake.calls["update"] == 0
    # die deterministische ID steht im Body - sonst waere 409 nie erreichbar
    staged = syncer.stage(plan, timezone_name="Europe/Istanbul")
    assert [b["id"] for b in fake.bodies] == [e.event_id for e in staged]


def test_sync_creates_event_and_google_task(tmp_path):
    fake = _FakeAiogoogle()
    plan = _plan_with_google_task(tmp_path)

    report = run_sync(_syncer(fake), plan, timezone_name="Europe/Istanbul")

    assert (report.total, report.created) == (1, 1)
    assert (report.tasks_total, report.tasks_created) == (1, 1)
    assert fake.calls["insert"] == 1
    assert fake.calls["tasks.insert"] == 1
    assert fake.calls["tasklists.insert"] == 1  # Liste fehlte und wurde angelegt
    assert fake.tasklists["list-1"]["title"] == "Wucūbāt"
    task = next(iter(fake.tasks.values()))
    assert task["title"] == "Wucūbāt lesen"
    assert task["tasklist"] == "list-1"
    assert task["due"].startswith(D0)
    assert "dir3key: Plan|2026-09-09|Wucūbāt lesen|1" in task["notes"]


def test_sync_second_run_sends_no_task_writes(tmp_path):
    fake = _FakeAiogoogle()
    syncer = _syncer(fake)
    plan = _plan_with_google_task(tmp_path)

    run_sync(syncer, plan, timezone_name="Europe/Istanbul")
    writes = sum(fake.calls[key] for key in ("tasks.insert", "tasks.patch", "tasks.delete"))
    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul")

    assert report.tasks_created == 0
    assert report.tasks_updated == 0
    assert report.tasks_deleted == 0
    assert report.tasks_unchanged == 1
    assert sum(fake.calls[key] for key in ("tasks.insert", "tasks.patch", "tasks.delete")) == writes
    assert len(fake.tasks) == 1


def test_sync_updates_google_task_in_place_when_time_shifts(tmp_path):
    from datetime import time

    fake = _FakeAiogoogle()
    syncer = _syncer(fake)
    run_sync(
        syncer, _plan_with_google_task(tmp_path), timezone_name="Europe/Istanbul"
    )
    task_id = next(iter(fake.tasks))

    report = run_sync(
        syncer,
        _plan_with_google_task(tmp_path, start=time(20, 0)),
        timezone_name="Europe/Istanbul",
    )

    assert (report.tasks_created, report.tasks_updated) == (0, 1)
    assert list(fake.tasks) == [task_id]
    assert "20:00–21:00" in fake.tasks[task_id]["notes"]
    assert fake.calls["tasks.insert"] == 1  # kein zweiter Insert


def test_sync_deletes_only_verified_stale_google_tasks(tmp_path):
    def task_item(task_id, *, title, key="", plan="Plan", due=D0, status="needsAction"):
        notes = f"dir3key: {key}\ndir3plan: {plan}" if key else "fremder Task"
        return {
            "id": task_id,
            "tasklist": "list-1",
            "title": title,
            "notes": notes,
            "due": f"{due}T00:00:00.000Z",
            "status": status,
        }

    fake = _FakeAiogoogle(
        ids=[],
        tasklists=[{"id": "list-1", "title": "Wucūbāt"}],
        tasks=[
            task_item("task-stale", title="Alt", key="Plan|2026-09-09|Alt|1"),
            task_item("task-foreign", title="Fremd"),
            task_item(
                "task-completed",
                title="Fertig",
                key="Plan|2026-09-09|Fertig|1",
                status="completed",
            ),
            task_item(
                "task-outside",
                title="Ausserhalb",
                key="Plan|2027-01-05|Ausserhalb|1",
                due="2027-01-05",
            ),
        ],
    )

    report = run_sync(
        _syncer(fake), _plan_with_google_task(tmp_path), timezone_name="Europe/Istanbul"
    )

    assert (report.tasks_created, report.tasks_deleted) == (1, 1)
    assert "task-stale" not in fake.tasks
    assert {"task-foreign", "task-completed", "task-outside"} <= set(fake.tasks)


def test_sync_leaves_completed_google_task_alone(tmp_path):
    fake = _FakeAiogoogle(tasklists=[{"id": "list-1", "title": "Wucūbāt"}])
    syncer = _syncer(fake)
    plan = _plan_with_google_task(tmp_path)
    staged = syncer.stage_tasks(plan, timezone_name="Europe/Istanbul")[0]
    fake.tasks["task-9"] = {
        "id": "task-9",
        "tasklist": "list-1",
        "title": "Alt",
        "notes": staged.notes,
        "due": f"{staged.due}T00:00:00.000Z",
        "status": "completed",
    }

    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul")

    assert (report.tasks_created, report.tasks_updated, report.tasks_deleted) == (0, 0, 0)
    assert fake.tasks["task-9"]["title"] == "Alt"


def test_sync_missing_tasks_scope_aborts_before_event_writes(tmp_path):
    fake = _FakeAiogoogle(task_error_status=403)
    plan = _plan_with_google_task(tmp_path)

    with pytest.raises(RuntimeError) as exc:
        run_sync(_syncer(fake), plan, timezone_name="Europe/Istanbul")

    assert "Google Tasks" in str(exc.value)
    assert "dir3-gcal-setup" in str(exc.value)
    assert fake.calls["insert"] == 0  # Events erst nach erfolgreichem Task-Abgleich


def test_sync_dry_run_counts_google_tasks_without_network(tmp_path):
    @asynccontextmanager
    async def open_client(settings, timeout):
        raise AssertionError("dry run darf keinen Client oeffnen")
        yield None  # pragma: no cover

    settings = GoogleCalendar(client_id="c", client_secret="s", refresh_token="r")
    syncer = GoogleCalendarSyncer(settings, client_factory=open_client)
    report = run_sync(
        syncer,
        _plan_with_google_task(tmp_path),
        timezone_name="Europe/Istanbul",
        dry_run=True,
    )

    assert report.tasks_total == 1
    assert report.tasks_unchanged == 0
    assert "1 Aufgabe geplant" in str(report)


def test_report_str_with_google_tasks():
    assert str(
        GCalSyncReport(
            total=1,
            created=1,
            updated=0,
            dry_run=False,
            tasks_total=1,
            tasks_created=1,
            tasks_updated=0,
        )
    ) == "GCal: 1 Event synchronisiert · 1 neu, 0 aktualisiert · Aufgaben: 1 neu, 0 aktualisiert"


def test_sync_updates_on_409(tmp_path):
    fake = _FakeAiogoogle(conflict=True)
    syncer = _syncer(fake)
    plan = _plan(tmp_path)

    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul")

    assert report == GCalSyncReport(total=3, created=0, updated=3, dry_run=False)
    assert fake.calls["insert"] == 3
    assert fake.calls["update"] == 3


def test_sync_reraises_non_conflict_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("dir3.services.gcal._RETRY_BASE_DELAY", 0)
    fake = _FakeAiogoogle(error_status=500)
    syncer = _syncer(fake)
    plan = _plan(tmp_path)

    with pytest.raises(_Conflict):
        run_sync(syncer, plan, timezone_name="Europe/Istanbul")
    assert fake.calls["update"] == 0


def test_sync_retries_rate_limit_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("dir3.services.gcal._RETRY_BASE_DELAY", 0)
    fake = _FakeAiogoogle(fail_first_batches=1, fail_status=429)
    syncer = _syncer(fake)
    plan = _plan(tmp_path)

    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul")

    assert report == GCalSyncReport(total=3, created=3, updated=0, dry_run=False)
    assert fake.batches == [3, 3]  # ein Retry, dann Erfolg


def test_sync_retries_403_rate_limit_but_not_auth_403(tmp_path, monkeypatch):
    import dir3.services.gcal as gcal_module

    monkeypatch.setattr(gcal_module, "_RETRY_BASE_DELAY", 0)
    limited = _FakeAiogoogle(
        fail_first_batches=1, fail_status=403, fail_json=RATE_LIMIT_JSON
    )
    report = run_sync(_syncer(limited), _plan(tmp_path), timezone_name="Europe/Istanbul")
    assert report.created == 3
    assert limited.batches == [3, 3]

    denied = _FakeAiogoogle(error_status=403)
    with pytest.raises(_Conflict):
        run_sync(_syncer(denied), _plan(tmp_path), timezone_name="Europe/Istanbul")
    assert denied.batches == [3]  # kein Retry bei Auth-403


def test_sync_exhausted_retries_raise(tmp_path, monkeypatch):
    import dir3.services.gcal as gcal_module

    monkeypatch.setattr(gcal_module, "_RETRY_BASE_DELAY", 0)
    fake = _FakeAiogoogle(fail_first_batches=99, fail_status=503)
    with pytest.raises(_Conflict):
        run_sync(_syncer(fake), _plan(tmp_path), timezone_name="Europe/Istanbul")
    assert fake.batches == [3] * gcal_module._MAX_TRIES


def test_sync_sends_one_batch(tmp_path):
    fake = _FakeAiogoogle()
    syncer = _syncer(fake)
    plan = _plan(tmp_path)

    run_sync(syncer, plan, timezone_name="Europe/Istanbul")

    assert fake.batches == [3]  # alle Inserts gleichzeitig, nicht einzeln


def test_sync_chunks_large_plans(tmp_path):
    from datetime import date, time, timedelta

    from dir3.services.gcal import BATCH_SIZE

    services = _services(tmp_path)

    @day
    def sample(ctx):
        return [task("X", start=time(9, 0), duration=timedelta(minutes=30))]

    plan = compile_pattern(
        week(mon=sample, tue=sample, wed=sample, thu=sample, fri=sample, sat=sample, sun=sample),
        days=2 * BATCH_SIZE + 5,
        start_date=date.fromisoformat(D0),
        services=services,
    )
    fake = _FakeAiogoogle()
    report = run_sync(_syncer(fake), plan, timezone_name="Europe/Istanbul")

    total = 2 * BATCH_SIZE + 5
    assert report == GCalSyncReport(total=total, created=total, updated=0, dry_run=False)
    # ein Event pro Tag -> ein 1er-Batch je Day-Task
    assert sorted(fake.batches) == [1] * total
    assert all(batch <= BATCH_SIZE for batch in fake.batches)


def _three_day_plan(tmp_path):
    from datetime import date, time, timedelta

    services = _services(tmp_path)

    @day
    def sample(ctx):
        return [task("X", start=time(9, 0), duration=timedelta(minutes=30))]

    return compile_pattern(
        week(mon=sample, tue=sample, wed=sample, thu=sample, fri=sample, sat=sample, sun=sample),
        days=3,
        start_date=date.fromisoformat(D0),
        services=services,
    )


def test_days_upload_concurrently(tmp_path):
    fake = _FakeAiogoogle()
    plan = _three_day_plan(tmp_path)

    report = run_sync(_syncer(fake), plan, timezone_name="Europe/Istanbul")

    assert report == GCalSyncReport(total=3, created=3, updated=0, dry_run=False)
    assert fake.max_in_flight > 1  # Day-Tasks liefen simultan, nicht nacheinander


def test_parallel_days_bound_is_respected(tmp_path):
    fake = _FakeAiogoogle()
    plan = _three_day_plan(tmp_path)

    settings = GoogleCalendar(client_id="c", client_secret="s", refresh_token="r")
    syncer = GoogleCalendarSyncer(settings, client_factory=_factory(fake), max_parallel_days=1)
    report = run_sync(syncer, plan, timezone_name="Europe/Istanbul")

    assert report.total == 3
    assert fake.max_in_flight == 1


def test_sync_dry_run_never_touches_network(tmp_path):
    @asynccontextmanager
    async def open_client(settings, timeout):
        raise AssertionError("dry run darf keinen Client oeffnen")
        yield None  # pragma: no cover

    settings = GoogleCalendar(client_id="c", client_secret="s", refresh_token="r")
    syncer = GoogleCalendarSyncer(settings, client_factory=open_client)
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
    assert str(GCalSyncReport(total=3, created=1, updated=1, deleted=1, dry_run=False)) == (
        "GCal: 3 Events synchronisiert · 1 neu, 1 aktualisiert, 1 geloescht"
    )
    assert str(GCalSyncReport(total=3, created=0, updated=0, deleted=0, dry_run=False)) == (
        "GCal: 3 Events synchronisiert · 0 neu, 0 aktualisiert · keine Aenderungen"
    )


# ---------------------------------------------------------------------------
# Abgleich (Hot-Reload): nur echte Aenderungen, Loeschen nur nach Verifikation


def _plan_with_task(tmp_path, start, *, title="Plan", days=1):
    from datetime import date, timedelta

    services = _services(tmp_path)

    @day
    def sample(ctx):
        return [task("X", start=start, duration=timedelta(minutes=30))]

    return compile_pattern(
        week(mon=sample, tue=sample, wed=sample, thu=sample, fri=sample, sat=sample, sun=sample),
        days=days,
        start_date=date.fromisoformat(D0),
        services=services,
        title=title,
    )


def _remote(body, *, event_id, key="fremd", plan="Plan", when=None, summary=None):
    """Kalender-Item im API-Format aus einem Staged-Body bauen."""
    item = {
        "id": event_id,
        "summary": summary or body["summary"],
        "start": when or body["start"],
        "end": body["end"],
        "description": f"dir3 · {plan}",
        "extendedProperties": {
            "private": {"dir3": "1", "dir3plan": plan, "dir3key": key}
        },
    }
    if "colorId" in body:
        item["colorId"] = body["colorId"]
    return item


def test_sync_second_run_sends_nothing(tmp_path):
    plan = _plan(tmp_path)
    fake = _FakeAiogoogle()
    syncer = _syncer(fake)

    first = run_sync(syncer, plan, timezone_name="Europe/Istanbul")
    writes_after_first = sum(fake.calls[k] for k in ("insert", "update", "delete"))
    second = run_sync(syncer, plan, timezone_name="Europe/Istanbul")

    assert first.created == 3
    assert writes_after_first == 3
    assert second == GCalSyncReport(
        total=3, created=0, updated=0, dry_run=False, deleted=0, unchanged=3
    )
    assert sum(fake.calls[k] for k in ("insert", "update", "delete")) == writes_after_first


def test_sync_updates_only_the_changed_event(tmp_path):
    from datetime import time

    fake = _FakeAiogoogle(events=[])
    syncer = _syncer(fake)
    run_sync(syncer, _plan_with_task(tmp_path, time(9, 0)), timezone_name="Europe/Istanbul")
    before = dict(next(iter(fake.store.values())))

    report = run_sync(
        syncer, _plan_with_task(tmp_path, time(10, 0)), timezone_name="Europe/Istanbul"
    )

    assert (report.created, report.updated, report.deleted) == (0, 1, 0)
    assert fake.calls["insert"] == 1  # kein zweiter Insert
    assert len(fake.store) == 1  # dasselbe Event, keine Dublette
    after = next(iter(fake.store.values()))
    assert after["id"] == before["id"]  # Event bleibt an Ort und Stelle
    assert after["start"]["dateTime"] != before["start"]["dateTime"]


def test_sync_deletes_only_verified_stale_events(tmp_path):
    from datetime import time

    plan = _plan_with_task(tmp_path, time(9, 0), title="Mein Plan")
    syncer = _syncer(_FakeAiogoogle())
    body = syncer.stage(plan, timezone_name="Europe/Istanbul")[0].body
    stale_id = "a" * 40
    foreign_id = "b" * 40
    outside_id = "c" * 40
    unmarked = _remote(
        body, event_id="e" * 40, key="alt", plan="Mein Plan", summary="Ohne Marker"
    )
    unmarked["extendedProperties"] = {"private": {}}  # kein dir3-Marker
    fake = _FakeAiogoogle(
        events=[
            # veraltet: eigener Plan, gleicher Tag, anderer Titel -> darf weg
            _remote(
                body, event_id=stale_id, key="alt", plan="Mein Plan", summary="Altes Event"
            ),
            # ohne dir3-Marker -> bleibt
            unmarked,
            # fremder Plan -> bleibt
            _remote(body, event_id=foreign_id, key="fremd", plan="Anderer Plan"),
            # eigener Plan, aber Tag ausserhalb des Fensters -> bleibt
            _remote(
                body,
                event_id=outside_id,
                key="alt",
                plan="Mein Plan",
                when={"dateTime": "2027-01-05T09:00:00+03:00", "timeZone": "Europe/Istanbul"},
            ),
        ]
    )

    report = run_sync(_syncer(fake), plan, timezone_name="Europe/Istanbul")

    assert (report.created, report.updated, report.deleted) == (1, 0, 1)
    assert stale_id not in fake.store
    assert foreign_id in fake.store
    assert outside_id in fake.store
    assert "e" * 40 in fake.store


def test_sync_without_prune_keeps_stale_events(tmp_path):
    from datetime import time

    plan = _plan_with_task(tmp_path, time(9, 0), title="Mein Plan")
    body = _syncer(_FakeAiogoogle()).stage(plan, timezone_name="Europe/Istanbul")[0].body
    stale_id = "a" * 40
    fake = _FakeAiogoogle(
        events=[
            _remote(body, event_id=stale_id, key="alt", plan="Mein Plan", summary="Altes Event")
        ]
    )

    report = run_sync(
        _syncer(fake), plan, timezone_name="Europe/Istanbul", prune=False
    )

    assert report.deleted == 0
    assert stale_id in fake.store


def _legacy(body, event_id="d" * 40):
    """Event aus einer dir3-Version ohne ``dir3key``/``dir3plan``."""
    item = {
        "id": event_id,
        "summary": body["summary"],
        "start": body["start"],
        "end": body["end"],
        "description": body["description"],
        "extendedProperties": {"private": {"dir3": "1"}},
    }
    if "colorId" in body:
        item["colorId"] = body["colorId"]
    return item


def test_sync_leaves_unchanged_legacy_events_alone(tmp_path):
    from datetime import time

    plan = _plan_with_task(tmp_path, time(9, 0))
    body = _syncer(_FakeAiogoogle()).stage(plan, timezone_name="Europe/Istanbul")[0].body
    fake = _FakeAiogoogle(events=[_legacy(body)])

    report = run_sync(_syncer(fake), plan, timezone_name="Europe/Istanbul")

    assert (report.created, report.updated, report.deleted) == (0, 0, 0)
    assert fake.calls["insert"] == 0 and fake.calls["update"] == 0


def test_sync_matches_legacy_event_in_place_when_times_shift(tmp_path):
    from datetime import time

    plan_a = _plan_with_task(tmp_path, time(9, 0))
    body = _syncer(_FakeAiogoogle()).stage(plan_a, timezone_name="Europe/Istanbul")[0].body
    fake = _FakeAiogoogle(events=[_legacy(body)])

    report = run_sync(
        _syncer(fake), _plan_with_task(tmp_path, time(10, 0)), timezone_name="Europe/Istanbul"
    )

    assert (report.created, report.updated, report.deleted) == (0, 1, 0)
    stored = fake.store["d" * 40]
    assert stored["start"]["dateTime"].startswith("2026-09-09T10:00")
    # das Update hat den stabilen Schluessel mitgebracht
    assert stored["extendedProperties"]["private"]["dir3key"]


def test_backoff_honours_retry_after():
    import dir3.services.gcal as gcal_module

    res = _FakeResponse(429, headers={"Retry-After": "42"})
    delay = gcal_module._backoff_delay(0, res)
    assert 42 <= delay <= gcal_module._MAX_RETRY_DELAY
    # ohne Header: exponentiell, gedeckelt
    assert gcal_module._backoff_delay(0) <= 5 * (1 + gcal_module._JITTER)
    assert gcal_module._backoff_delay(20) <= gcal_module._MAX_RETRY_DELAY
    assert gcal_module._retry_after(_FakeResponse(429, headers={})) is None


def test_rate_guard_holds_all_tasks_after_a_hit():
    import dir3.services.gcal as gcal_module

    async def scenario():
        guard = gcal_module._RateGuard(min_interval=0.05)
        loop = asyncio.get_running_loop()
        await guard.penalize(0.02)
        stamps = []

        async def worker():
            await guard.wait()
            stamps.append(loop.time())

        await asyncio.gather(*(worker() for _ in range(3)))
        return sorted(stamps)

    stamps = asyncio.run(scenario())
    gaps = [later - earlier for earlier, later in zip(stamps, stamps[1:])]
    assert all(gap >= 0.04 for gap in gaps), gaps


# ---------------------------------------------------------------------------
# Clear: alle dir3-Events aus dem Kalender entfernen

GCAL_EVENT = re.compile(r"^[0-9a-f]{40}$")


def test_clear_deletes_dir3_events():
    fake = _FakeAiogoogle()
    report = run_clear(_syncer(fake))

    assert report == GCalClearReport(deleted=4, dry_run=False)
    assert fake.calls["delete"] == 4
    assert fake.calls["list"] == 1
    assert "4 Events geloescht" in str(report)


def test_clear_deletes_marked_google_tasks_but_keeps_foreign(tmp_path):
    fake = _FakeAiogoogle(
        ids=[],
        tasklists=[{"id": "list-1", "title": "Wucūbāt"}],
        tasks=[
            {
                "id": "task-owned",
                "tasklist": "list-1",
                "title": "Eigene",
                "notes": "dir3key: P|2026-09-09|Eigene|1\ndir3plan: P",
                "due": "2026-09-09T00:00:00.000Z",
                "status": "needsAction",
            },
            {
                "id": "task-foreign",
                "tasklist": "list-1",
                "title": "Fremd",
                "notes": "",
                "due": "2026-09-09T00:00:00.000Z",
                "status": "needsAction",
            },
            {
                "id": "task-done",
                "tasklist": "list-1",
                "title": "Fertig",
                "notes": "dir3key: P|2026-09-09|Fertig|1\ndir3plan: P",
                "due": "2026-09-09T00:00:00.000Z",
                "status": "completed",
            },
        ],
    )

    report = run_clear(_syncer(fake))

    assert report == GCalClearReport(deleted=0, dry_run=False, tasks_deleted=1)
    assert "task-owned" not in fake.tasks
    assert {"task-foreign", "task-done"} <= set(fake.tasks)
    assert "1 Aufgabe geloescht" in str(report)


def test_clear_ignores_calendar_creation_events():
    fake = _FakeAiogoogle()
    report = run_clear(_syncer(fake))
    assert report.deleted == 4
    assert fake.calls["insert"] == 0


def test_clear_paginates():
    fake = _FakeAiogoogle(pages=2)
    report = run_clear(_syncer(fake))

    assert report.deleted == 4
    assert fake.calls["list"] == 2
    assert fake.calls["delete"] == 4


def test_clear_dry_run_only_lists():
    fake = _FakeAiogoogle()
    report = run_clear(_syncer(fake), dry_run=True)

    assert report == GCalClearReport(deleted=4, dry_run=True)
    assert fake.calls["delete"] == 0
    assert "wuerde 4 Events loeschen" in str(report)


def test_clear_empty_list_no_deletes():
    fake = _FakeAiogoogle(ids=[])
    report = run_clear(_syncer(fake))
    assert report.deleted == 0


def test_clear_tolerates_already_gone_events():
    ids = [f"{i:040x}" for i in range(4)]
    fake = _FakeAiogoogle(ids=ids, gone_ids={ids[1]})
    report = run_clear(_syncer(fake))

    assert report == GCalClearReport(deleted=4, dry_run=False)
    assert fake.calls["delete"] == 4


def test_clear_reraises_real_errors():
    fake = _FakeAiogoogle(error_status=None)

    async def boom(*requests, **kwargs):
        raise _Conflict(500)

    fake.as_user = boom  # type: ignore[method-assign]
    with pytest.raises(_Conflict):
        run_clear(_syncer(fake))


def test_nuke_lists_everything_without_dir3_filter():
    fake = _FakeAiogoogle(ids=["abc123XYZ_", "85vi4euj00g1r10eemm6gt6af8"], strict_ids=False)
    report = run_clear(_syncer(fake), nuke=True)

    assert report == GCalClearReport(deleted=2, dry_run=False)
    assert fake.calls["delete"] == 2
    assert len(fake.list_kwargs) == 1
    assert "privateExtendedProperty" not in fake.list_kwargs[0]
    assert "singleEvents" not in fake.list_kwargs[0]


def test_nuke_dry_run_only_lists():
    fake = _FakeAiogoogle(ids=["abc123XYZ_"], strict_ids=False)
    report = run_clear(_syncer(fake), nuke=True, dry_run=True)

    assert report == GCalClearReport(deleted=1, dry_run=True)
    assert fake.calls["delete"] == 0


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

    def fake_syncer(settings, **kwargs):
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

    def fake_syncer(settings, **kwargs):
        recorded["settings"] = settings
        return object()

    def fake_run(syncer, *, dry_run, nuke=False):
        recorded["dry"] = dry_run
        recorded["nuke"] = nuke
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
