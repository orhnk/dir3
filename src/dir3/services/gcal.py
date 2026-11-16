"""Google Calendar sync via aiogoogle (async).

Der Sync schiebt einen kompilierten :class:`Plan` als Events in Google
Calendar.  Credentials liegen im Python-Planfile (``gcal = GoogleCalendar(...)``)
- gleiche Philosophie wie der Rest von dir3.

Abgleich statt Neuaufbau (Hot-Reload): Der Kalender wird gelesen, der Plan
dagegen diffed und nur die echten Aenderungen geschickt - unveraenderte
Events kosten null Schreibzugriffe.  Jedes Event traegt neben der
deterministischen SHA1-ID (Titel/Tag/Name/Zeiten) einen stabilen
Schluessel ``dir3key`` (Titel/Tag/Name/Vorkommen) in den privaten
extendedProperties.  Aendern sich nur die Zeiten, wird das bestehende Event
an Ort und Stelle aktualisiert (ID bleibt), statt es zu loeschen und neu
anzulegen.

Loeschen ist nie blind: Ein Event wird nur entfernt, wenn es den dir3-Marker
traegt, zum selben Plan gehoert (``dir3plan``) und sein Tag im aktuell
kompilierten Planfenster liegt.  Fremde Events, Events anderer Plaene und
Events ausserhalb des Fensters bleiben unangetastet.

Rate Limits: Google antwortet bei zu schnellen Laeufen mit ``403``/``429``
``rateLimitExceeded``/``userRateLimitExceeded``.  Retries respektieren
``Retry-After``, laufen mit exponentiellem Backoff plus Jitter und blockieren
ueber die gemeinsame :class:`_RateGuard` alle parallelen Batches, sobald
einmal gebremst wurde - statt mit weiteren Anfragen das Limit zu halten.

Parallelitaet: Jeder Tag bekommt seine eigene Upload-Task - alle Tage laufen
gleichzeitig (``asyncio.gather``), begrenzt durch ``max_parallel_days``.
Innerhalb eines Tages fliegen die Aenderungen als aiogoogle-Batches
(``as_user(*requests)``, max. ``BATCH_SIZE`` pro Batch) gleichzeitig raus.

Auth (OAuth2, via aiogoogle):
  * ``refresh_token`` + ``client_id``/``client_secret`` -> automatischer
    Refresh beim ersten Request des Laufs;
  * oder ein bereits ausgestelltes ``access_token`` wird direkt benutzt.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from aiogoogle import Aiogoogle
from aiogoogle.auth.creds import ClientCreds, UserCreds

from ..color import (
    ColorPolicy,
    DefaultIconPolicy,
    PrayerColorPolicy,
    event_summary,
    to_gcal_color_id,
)
from ..config import GoogleCalendar
from ..timeutils import format_duration, format_time
from .geo import _resolve_tz

#: Calendar events plus Google Tasks (hybrid: timed event + date-only task).
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"
SCOPES = ["https://www.googleapis.com/auth/calendar.events", TASKS_SCOPE]

#: Direkt gegebenes Access-Token gilt für den (kurzen) Sync-Lauf als frisch,
#: damit aiogoogle keinen Refresh ohne Refresh-Token versucht.
_ACCESS_TOKEN_TTL = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class StagedEvent:
    event_id: str
    summary: str
    body: dict[str, object]
    when: str
    day: str = ""
    key: str = ""


@dataclass(frozen=True, slots=True)
class StagedTask:
    """Eine Aufgabe fuer die Google-Tasks-API (nur Datum, keine Uhrzeit)."""

    key: str
    title: str
    notes: str
    due: str
    list_name: str
    day: str
    when: str


@dataclass(frozen=True, slots=True)
class RemoteTask:
    """Eine bereits in Google Tasks liegende Aufgabe (nur Vergleichsfelder)."""

    task_id: str
    list_id: str
    list_name: str
    title: str
    notes: str
    due: str
    status: str
    key: str = ""
    plan_title: str = ""
    day: str = ""
    marked: bool = False


@dataclass(frozen=True, slots=True)
class RemoteEvent:
    """Ein bereits im Kalender liegendes Event (nur die Vergleichsfelder)."""

    event_id: str
    summary: str
    start: str
    end: str
    color_id: str | None = None
    description: str = ""
    day: str = ""
    key: str = ""
    plan_title: str = ""
    marked: bool = False


@dataclass(frozen=True, slots=True)
class SyncOps:
    """Was der Abgleich zu tun hat (rein, ohne Netzwerk)."""

    creates: tuple[StagedEvent, ...] = ()
    updates: tuple[tuple[str, StagedEvent], ...] = ()
    deletes: tuple[RemoteEvent, ...] = ()
    unchanged: int = 0

    @property
    def empty(self) -> bool:
        return not (self.creates or self.updates or self.deletes)


@dataclass(frozen=True, slots=True)
class TaskOps:
    """Was der Google-Tasks-Abgleich zu tun hat (rein, ohne Netzwerk)."""

    creates: tuple[StagedTask, ...] = ()
    #: ``(list_id, task_id, neue Aufgabe)``
    updates: tuple[tuple[str, str, StagedTask], ...] = ()
    deletes: tuple[RemoteTask, ...] = ()
    unchanged: int = 0

    @property
    def empty(self) -> bool:
        return not (self.creates or self.updates or self.deletes)


@dataclass(frozen=True, slots=True)
class GCalSyncReport:
    total: int
    created: int
    updated: int
    dry_run: bool
    deleted: int = 0
    unchanged: int = 0
    tasks_total: int = 0
    tasks_created: int = 0
    tasks_updated: int = 0
    tasks_deleted: int = 0
    tasks_unchanged: int = 0

    def __str__(self) -> str:
        verb = "geplant" if self.dry_run else "synchronisiert"
        noun = "Event" if self.total == 1 else "Events"
        parts = [f"GCal: {self.total} {noun} {verb}"]
        if not self.dry_run:
            changes = f"{self.created} neu, {self.updated} aktualisiert"
            if self.deleted:
                changes += f", {self.deleted} geloescht"
            parts.append(changes)
            if not (self.created or self.updated or self.deleted):
                parts.append("keine Aenderungen")
        if self.tasks_total:
            if self.dry_run:
                task_noun = "Aufgabe" if self.tasks_total == 1 else "Aufgaben"
                parts.append(f"{self.tasks_total} {task_noun} geplant")
            else:
                changes = f"{self.tasks_created} neu, {self.tasks_updated} aktualisiert"
                if self.tasks_deleted:
                    changes += f", {self.tasks_deleted} geloescht"
                parts.append(f"Aufgaben: {changes}")
        return " · ".join(parts)


@dataclass(frozen=True, slots=True)
class GCalClearReport:
    deleted: int
    dry_run: bool
    tasks_deleted: int = 0

    def __str__(self) -> str:
        noun = "Event" if self.deleted == 1 else "Events"
        task_noun = "Aufgabe" if self.tasks_deleted == 1 else "Aufgaben"
        if self.dry_run:
            text = f"GCal: wuerde {self.deleted} {noun} loeschen"
        else:
            text = f"GCal: {self.deleted} {noun} geloescht"
        if self.tasks_deleted:
            if self.dry_run:
                verb = "wuerde geloescht" if self.tasks_deleted == 1 else "wuerden geloescht"
            else:
                verb = "geloescht"
            text += f" · {self.tasks_deleted} {task_noun} {verb}"
        return text


def _creds_for(settings: GoogleCalendar) -> tuple[UserCreds, ClientCreds | None]:
    """aiogoogle-Credentials aus den Planfile-Einstellungen bauen."""
    if settings.access_token:
        user_creds = UserCreds(
            access_token=settings.access_token,
            expires_at=datetime.now(timezone.utc) + _ACCESS_TOKEN_TTL,
        )
        return user_creds, None
    user_creds = UserCreds(refresh_token=settings.refresh_token)
    client_creds = ClientCreds(
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        scopes=list(SCOPES),
    )
    return user_creds, client_creds


@asynccontextmanager
async def _open_client(
    settings: GoogleCalendar, timeout: float
) -> AsyncIterator[tuple[Aiogoogle, object]]:
    """Echte aiogoogle-Verbindung: Session + entdeckte Calendar-API liefern."""
    user_creds, client_creds = _creds_for(settings)
    async with Aiogoogle(user_creds=user_creds, client_creds=client_creds) as google:
        yield google, await google.discover("calendar", "v3")


#: Öffnet ``(aiogoogle, calendar_api)`` - in Tests durch einen Fake ersetzbar.
ClientFactory = Callable[[GoogleCalendar, float], object]

#: Max. Events pro aiogoogle-Batch - ein Batch fliegt parallel raus
#: (``as_user(*requests)``), Batches laufen nacheinander (API-Hoeflichkeit).
BATCH_SIZE = 11

#: Status, die einen Retry mit Backoff verdienen (Rate-Limits / flaky Server).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

#: Retry-Versuche pro Batch + Start-Delay (verdoppelt sich pro Versuch,
#: gedeckelt bei ``_MAX_RETRY_DELAY``, plus Jitter gegen Gleichlauf).
#: Googles Minuten-Quota braucht oft >60 s; 5/10/20/40/60 deckt das ab.
_MAX_TRIES = 6
_RETRY_BASE_DELAY = 5.0
_MAX_RETRY_DELAY = 60.0
_JITTER = 0.25


class _RateGuard:
    """Gemeinsame Drossel fuer alle parallelen Batches eines Sync-Laufs.

    Solange Google nicht bremst, laeuft alles ungebremst (kein kuenstliches
    Warten im Normalfall).  Sobald ein Batch ein Rate Limit sieht, pausieren
    *alle* Tasks bis zum Ende des Backoffs und senden danach nur noch im
    Mindestabstand - so haelt kein Task das Limit mit Nachschub am Leben.
    """

    def __init__(self, *, min_interval: float = 0.25) -> None:
        self.min_interval = min_interval
        self.hits = 0
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            start = max(now, self._next_at)
            spacing = self.min_interval if self.hits else 0.0
            self._next_at = start + spacing
        if start > now:
            await asyncio.sleep(start - now)

    async def penalize(self, delay: float) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            self._next_at = max(self._next_at, loop.time() + delay)
            self.hits += 1


def _is_rate_limited(res) -> bool:
    """True bei 403ern mit Rate-Limit-Grund (kein Auth-Problem)."""
    payload = getattr(res, "json", None) or {}
    if isinstance(payload, dict):
        error = payload.get("error") or {}
        details = error.get("errors") or []
        for detail in details:
            if not isinstance(detail, dict):
                continue
            if "ratelimit" in str(detail.get("reason", "")).lower():
                return True
        message = str(error.get("message", "")).lower()
        if "rate limit" in message or "ratelimit" in message:
            return True
    text = str(getattr(res, "data", "") or "").lower()
    return "rate limit" in text or "ratelimit" in text


def _response_kind(res) -> str:
    """``ok`` | ``conflict`` (409) | ``gone`` (404/410) | ``retry`` | ``fatal``."""
    code = res.status_code
    if 200 <= code < 300:
        return "ok"
    if code == 409:
        return "conflict"
    if code in (404, 410):
        return "gone"
    if code in _RETRYABLE_STATUS or (code == 403 and _is_rate_limited(res)):
        return "retry"
    return "fatal"


def _task_access_error(exc: Exception) -> RuntimeError | None:
    """403/401 der Tasks-API in eine klare Re-Auth-Anweisung uebersetzen."""
    res = getattr(exc, "res", None)
    status = getattr(res, "status_code", None) or getattr(exc, "status_code", None)
    if status not in (401, 403):
        return None
    if status == 403 and _is_rate_limited(res):
        return None
    return RuntimeError(
        f"Google Tasks verweigert den Zugriff (HTTP {status}). Aktiviere die Google "
        "Tasks API im Cloud-Projekt und hole den Refresh-Token mit dem Tasks-"
        "Scope neu: dir3-gcal-setup --client-id ... --client-secret ... "
        f"(Scope: {TASKS_SCOPE})."
    )


def _retry_after(res) -> float | None:
    """``Retry-After``-Header in Sekunden, falls Google einen mitschickt."""
    headers = getattr(res, "headers", None)
    if not headers:
        return None
    try:
        value = float(str(headers.get("Retry-After", "")).strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _backoff_delay(attempt: int, res=None) -> float:
    """Exponentielles Backoff mit Jitter; ``Retry-After`` gewinnt, wenn laenger."""
    base = min(_MAX_RETRY_DELAY, _RETRY_BASE_DELAY * (2**attempt))
    hinted = _retry_after(res)
    if hinted is not None:
        base = max(base, hinted)
    return min(_MAX_RETRY_DELAY, base * (1 + random.uniform(0, _JITTER)))


async def _send_requests(google, pairs, *, timeout, guard: _RateGuard | None = None) -> list:
    """``(item, request)``-Batch senden, mit Retry bei Rate-Limits.

    Gibt fertige ``(item, response)``-Paare zurück (409/404/410 sind normale
    Outcomes, kein Retry); fatale Fehler raisen via ``res.raise_for_status()``.
    """
    pending = list(pairs)
    if not pending:
        return []
    guard = guard or _RateGuard()
    finished = []
    for attempt in range(_MAX_TRIES):
        last = attempt == _MAX_TRIES - 1
        await guard.wait()
        responses = await google.as_user(
            *(req for _, req in pending),
            timeout=timeout,
            full_res=True,
            raise_for_status=False,
        )
        if not isinstance(responses, list):
            responses = [responses]
        still = []
        delays = []
        for (item, _req), res in zip(pending, responses):
            kind = _response_kind(res)
            if kind == "retry" and not last:
                still.append((item, _req))
                delays.append(_backoff_delay(attempt, res))
            elif kind == "fatal" or kind == "retry":
                res.raise_for_status()
            else:
                finished.append((item, res))
        pending = still
        if not pending:
            return finished
        # Alle Tasks pausieren mit - nicht nur der, der das Limit gesehen hat.
        await guard.penalize(max(delays))
    raise AssertionError("unerreichbar - letzter Versuch raist oder beendet immer")


def _chunks(items: list, size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _body_without_id(event: StagedEvent) -> dict[str, object]:
    """Payload fuer Updates: die ID steckt in der URL, nicht im Body."""
    return {key: value for key, value in event.body.items() if key != "id"}


def _description_title(description: str) -> str:
    """Plantitel aus ``dir3 · <Titel>`` (Fallback fuer Alt-Events)."""
    marker = "dir3 · "
    text = description or ""
    return text[len(marker) :] if text.startswith(marker) else ""


_TASK_KEY_PREFIX = "dir3key:"
_TASK_PLAN_PREFIX = "dir3plan:"


def _task_notes(
    plan_title: str,
    key: str,
    start: datetime,
    end: datetime,
    *,
    todo_position: str | None = None,
    event_title: str | None = None,
) -> str:
    """Notes tragen den stabilen Schluessel; sichtbar bleibt der Zeitblock."""
    span = f"{format_time(start.time())}–{format_time(end.time())}"
    if end > start:
        span += f" · {format_duration(end - start)}"
    lines = [span, f"dir3 · {plan_title}", ""]
    if todo_position and event_title:
        where = "am Anfang" if todo_position == "start" else "am Ende"
        lines.extend((f"Todo: {event_title} · {where}", ""))
    lines.extend(
        (
            f"{_TASK_KEY_PREFIX} {key}",
            f"{_TASK_PLAN_PREFIX} {plan_title}",
        )
    )
    if todo_position:
        lines.append(f"dir3todo: {todo_position}")
    lines.append("dir3: 1")
    return "\n".join(lines)


def _task_due(start: datetime, end: datetime, position: str | None) -> str:
    """Tasks speichern nur ein Datum: Anfang und Ende koennen verschiedene Tage sein."""
    moment = end if position == "end" else start
    return moment.date().isoformat()


def _task_marker(notes: str) -> tuple[str, str]:
    """``(dir3key, dir3plan)`` aus den Notes lesen (leer bei fremden Tasks)."""
    key = plan_title = ""
    for raw in (notes or "").splitlines():
        line = raw.strip()
        if line.startswith(_TASK_KEY_PREFIX):
            key = line[len(_TASK_KEY_PREFIX) :].strip()
        elif line.startswith(_TASK_PLAN_PREFIX):
            plan_title = line[len(_TASK_PLAN_PREFIX) :].strip()
    return key, plan_title


def _parse_remote_tasks(items, *, list_id: str, list_name: str) -> list[RemoteTask]:
    """Google-Tasks-Items zu :class:`RemoteTask` (nur markierte sind relevant)."""
    remote: list[RemoteTask] = []
    for item in items:
        task_id = item.get("id")
        if not task_id or item.get("deleted"):
            continue
        notes = item.get("notes") or ""
        key, plan_title = _task_marker(notes)
        parts = key.split("|")
        day = parts[1] if len(parts) > 1 else str(item.get("due") or "")[:10]
        remote.append(
            RemoteTask(
                task_id=task_id,
                list_id=list_id,
                list_name=list_name,
                title=item.get("title") or "",
                notes=notes,
                due=str(item.get("due") or "")[:10],
                status=item.get("status") or "needsAction",
                key=key,
                plan_title=plan_title,
                day=day,
                marked=bool(key or plan_title),
            )
        )
    return remote


def _needs_task_update(remote: RemoteTask, staged: StagedTask) -> bool:
    """Erledigte Aufgaben bleiben Geschichte und werden nicht umgeschrieben."""
    if remote.status == "completed":
        return False
    return (
        remote.title != staged.title
        or remote.due != staged.due
        or remote.notes != staged.notes
    )


def _task_deletable(remote: RemoteTask, days: set[str], title: str) -> bool:
    """Nur eigene, offene Aufgaben im aktuellen Planfenster entfernen."""
    return (
        remote.marked
        and remote.plan_title == title
        and remote.day in days
        and remote.status != "completed"
    )


def reconcile_tasks(
    staged: list[StagedTask],
    remote: list[RemoteTask],
    *,
    days: set[str],
    title: str,
    prune: bool = True,
) -> TaskOps:
    """Aufgabenplan gegen Google Tasks diffen (gleiche Semantik wie Events)."""
    by_key = {task.key: task for task in remote if task.key}
    # Fallback nur fuer eigene markierte Tasks (z. B. nach manuell geloeschter
    # ``dir3key``-Zeile) - fremde Tasks werden nie uebernommen.
    by_visual = {
        (task.due, task.title): task
        for task in remote
        if task.marked and task.plan_title == title
    }
    matched: set[str] = set()
    creates: list[StagedTask] = []
    updates: list[tuple[str, str, StagedTask]] = []
    for task in staged:
        hit = by_key.get(task.key)
        if hit is None or hit.task_id in matched:
            candidate = by_visual.get((task.due, task.title))
            if candidate is not None and candidate.task_id not in matched:
                hit = candidate
        if hit is None or hit.task_id in matched:
            creates.append(task)
            continue
        matched.add(hit.task_id)
        if _needs_task_update(hit, task):
            updates.append((hit.list_id, hit.task_id, task))
    deletes = (
        tuple(
            task
            for task in remote
            if task.task_id not in matched and _task_deletable(task, days, title)
        )
        if prune
        else ()
    )
    return TaskOps(
        creates=tuple(creates),
        updates=tuple(updates),
        deletes=deletes,
        unchanged=len(staged) - len(creates) - len(updates),
    )


def _task_body(task: StagedTask) -> dict[str, object]:
    """Tasks API kennt nur ein Datum; die Dauer steht in den Notes."""
    return {
        "title": task.title,
        "notes": task.notes,
        "due": f"{task.due}T00:00:00.000Z",
    }


def _parse_remote(items, tz) -> list[RemoteEvent]:
    """API-Items zu :class:`RemoteEvent` (Ganztags/fremd wird uebersprungen)."""
    remote: list[RemoteEvent] = []
    for item in items:
        event_id = item.get("id")
        start_raw = (item.get("start") or {}).get("dateTime")
        end_raw = (item.get("end") or {}).get("dateTime")
        if not event_id or not start_raw or not end_raw:
            continue
        try:
            start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        private = (item.get("extendedProperties") or {}).get("private") or {}
        description = item.get("description") or ""
        remote.append(
            RemoteEvent(
                event_id=event_id,
                summary=item.get("summary") or "",
                start=str(start_raw),
                end=str(end_raw),
                color_id=item.get("colorId") or None,
                description=description,
                day=start.astimezone(tz).date().isoformat(),
                key=str(private.get("dir3key") or ""),
                plan_title=str(private.get("dir3plan") or _description_title(description)),
                marked=str(private.get("dir3") or "") == "1",
            )
        )
    return remote


def _same_moment(left: str, right: str) -> bool:
    """Gleicher Zeitpunkt, auch wenn Google ``Z`` statt ``+00:00`` liefert."""
    try:
        a = datetime.fromisoformat(str(left).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(right).replace("Z", "+00:00"))
    except ValueError:
        return str(left) == str(right)
    return a == b


def _needs_update(remote: RemoteEvent, staged: StagedEvent) -> bool:
    """Nur sichtbare Unterschiede zaehlen - ein fehlender ``dir3key`` allein
    loest keinen Schreibzugriff aus (Alt-Events migrieren beim naechsten
    echten Update mit)."""
    body = staged.body
    if remote.summary != staged.summary:
        return True
    if (body.get("description") or "") != remote.description:
        return True
    if (body.get("colorId") or None) != remote.color_id:
        return True
    start = (body.get("start") or {}).get("dateTime", "")
    end = (body.get("end") or {}).get("dateTime", "")
    return not _same_moment(start, remote.start) or not _same_moment(end, remote.end)


def _deletable(remote: RemoteEvent, days: set[str], title: str) -> bool:
    """Verifikation vor dem Loeschen: eigenes Event, eigener Plan, Tag im Fenster."""
    return remote.marked and remote.plan_title == title and remote.day in days


def reconcile(
    staged: list[StagedEvent],
    remote: list[RemoteEvent],
    *,
    days: set[str],
    title: str,
    prune: bool = True,
) -> SyncOps:
    """Plan gegen Kalender diffen: nur echte Aenderungen bleiben uebrig."""
    by_key = {event.key: event for event in remote if event.key}
    by_id = {event.event_id: event for event in remote}
    # Fallback fuer Alt-Events ohne Schluessel: gleicher Tag, gleicher Titel im
    # selben Plan - so wird auch dort aktualisiert statt neu angelegt.
    by_visual: dict[tuple[str, str], RemoteEvent] = {
        (event.day, event.summary): event
        for event in remote
        if not event.plan_title or event.plan_title == title
    }
    matched: set[str] = set()
    creates: list[StagedEvent] = []
    updates: list[tuple[str, StagedEvent]] = []
    for event in staged:
        hit = by_key.get(event.key) or by_id.get(event.event_id)
        if hit is None or hit.event_id in matched:
            candidate = by_visual.get((event.day, event.summary))
            if candidate is not None and candidate.event_id not in matched:
                hit = candidate
        if hit is None or hit.event_id in matched:
            creates.append(event)
            continue
        matched.add(hit.event_id)
        if _needs_update(hit, event):
            updates.append((hit.event_id, event))
    deletes = tuple(
        event
        for event in remote
        if event.event_id not in matched and _deletable(event, days, title)
    ) if prune else ()
    return SyncOps(
        creates=tuple(creates),
        updates=tuple(updates),
        deletes=deletes,
        unchanged=len(staged) - len(creates) - len(updates),
    )


class GoogleCalendarSyncer:
    def __init__(
        self,
        settings: GoogleCalendar,
        *,
        client_factory: ClientFactory | None = None,
        timeout: float = 10.0,
        max_parallel_days: int = 8,
        color_policy: ColorPolicy | None = None,
        icon_policy: object | None = None,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory or _open_client
        self.timeout = timeout
        self.max_parallel_days = max_parallel_days
        self._color_policy = color_policy or PrayerColorPolicy()
        self._icon_policy = icon_policy or DefaultIconPolicy()

    def _stage(
        self, plan, *, timezone_name: str
    ) -> tuple[list[StagedEvent], list[StagedTask]]:
        """Aktive Events und ihre Google-Tasks-Spiegel aufbauen (rein, ohne Netzwerk).

        Der Engine arbeitet in Plan-Wanduhrzeit (naive datetimes); hier wird die
        Plan-Zeitzone attachiert, damit GCal absolute Zeitpunkte bekommt.  Jede
        Aufgabe mit ``task_list`` bekommt zusaetzlich einen Google-Task mit
        Datum (die Tasks-API verwirft die Uhrzeit) und den Zeitblock in den
        Notes - der getimte Kalender-Event bleibt unveraendert.
        """
        tz = _resolve_tz(timezone_name or "UTC")
        tz_label = getattr(tz, "key", None) or "UTC"
        staged: list[StagedEvent] = []
        tasks: list[StagedTask] = []
        for day_ in plan.days:
            if not day_.active:
                continue
            position = 0
            day_iso = day_.date.isoformat()
            seen: dict[str, int] = {}
            for ev in day_.events:
                if not ev.active:
                    continue
                start = _aware(ev.start, tz)
                end = _aware(ev.end, tz)
                fingerprint = "|".join(
                    (plan.title, day_iso, ev.name, start.isoformat(), end.isoformat())
                )
                event_id = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()
                # Stabiler Schluessel: ueberlebt Zeitverschiebungen, damit ein
                # geaenderter Plan das Event aktualisiert statt neu anzulegen.
                seen[ev.name] = seen.get(ev.name, 0) + 1
                key = "|".join((plan.title, day_iso, ev.name, str(seen[ev.name])))
                # Icons + kompaktierter Name; die ID bleibt am Roh-Namen
                # verankert, damit Titel-Updates idempotent sind.
                summary = event_summary(ev.name, self._icon_policy, position)
                body = {
                    "id": event_id,
                    "summary": summary,
                    "start": {"dateTime": start.isoformat(), "timeZone": tz_label},
                    "end": {"dateTime": end.isoformat(), "timeZone": tz_label},
                    "description": f"dir3 · {plan.title}",
                    "extendedProperties": {
                        "private": {"dir3": "1", "dir3plan": plan.title, "dir3key": key}
                    },
                }
                color_id = to_gcal_color_id(self._color_policy.color_for(ev.name, position))
                if color_id is not None:
                    body["colorId"] = color_id
                position += 1

                staged.append(
                    StagedEvent(
                        event_id=event_id,
                        summary=summary,
                        body=body,
                        when=start.isoformat(),
                        day=day_iso,
                        key=key,
                    )
                )
                if ev.task_list:
                    # Ohne todo_position und mit angehaengten Todos ist das
                    # Event nur deren Container (z. B. Hitam): kein eigener
                    # Google Task fuer den Event-Namen.
                    if ev.todo_position is not None or not ev.todos:
                        tasks.append(
                            StagedTask(
                                key=key,
                                title=ev.name,
                                notes=_task_notes(
                                    plan.title,
                                    key,
                                    start,
                                    end,
                                    todo_position=ev.todo_position,
                                    event_title=ev.name,
                                ),
                                due=_task_due(start, end, ev.todo_position),
                                list_name=ev.task_list,
                                day=day_iso,
                                when=start.isoformat(),
                            )
                        )
                    for todo in ev.todos:
                        child_key = f"{key}|todo|{todo.todo_position}|{todo.title}"
                        tasks.append(
                            StagedTask(
                                key=child_key,
                                title=todo.title,
                                notes=_task_notes(
                                    plan.title,
                                    child_key,
                                    start,
                                    end,
                                    todo_position=todo.todo_position,
                                    event_title=ev.name,
                                ),
                                due=_task_due(start, end, todo.todo_position),
                                list_name=ev.task_list,
                                day=day_iso,
                                when=(
                                    end if todo.todo_position == "end" else start
                                ).isoformat(),
                            )
                        )
        staged.sort(key=lambda event: event.when)
        tasks.sort(key=lambda task: (task.when, task.list_name, task.title))
        return staged, tasks

    def stage(self, plan, *, timezone_name: str) -> list[StagedEvent]:
        """Alle aktiven Events als GCal-Payloads (rein, kein Netzwerk)."""
        return self._stage(plan, timezone_name=timezone_name)[0]

    def stage_tasks(self, plan, *, timezone_name: str) -> list[StagedTask]:
        """Alle mit ``task_list`` markierten Aufgaben (rein, kein Netzwerk)."""
        return self._stage(plan, timezone_name=timezone_name)[1]

    async def sync(
        self,
        plan,
        *,
        timezone_name: str,
        dry_run: bool = False,
        prune: bool = True,
    ) -> GCalSyncReport:
        staged, staged_tasks = self._stage(plan, timezone_name=timezone_name)
        if dry_run or (not staged and not staged_tasks):
            return GCalSyncReport(
                total=len(staged),
                created=0,
                updated=0,
                dry_run=dry_run,
                unchanged=0,
                tasks_total=len(staged_tasks),
                tasks_unchanged=0,
            )

        calendar_id = self.settings.calendar_id
        tz = _resolve_tz(timezone_name or "UTC")
        guard = _RateGuard()
        async with self._client_factory(self.settings, self.timeout) as (google, calendar):
            remote = await self._list_remote(google, calendar, plan=plan, tz=tz)
            # Alle kompilierten Tage: auch ein bewusst freier Tag gehoert zum
            # Fenster - dort liegengebliebene dir3-Events duerfen weg.
            days = {day_.date.isoformat() for day_ in plan.days}
            ops = reconcile(staged, remote, days=days, title=plan.title, prune=prune)

            task_ops = TaskOps()
            task_counts = (0, 0, 0)
            if staged_tasks:
                try:
                    task_api = await google.discover("tasks", "v1")
                    list_ids = await self._task_list_ids(
                        google, task_api, {task.list_name for task in staged_tasks}
                    )
                    all_lists = await self._list_task_lists(google, task_api)
                    # Neu angelegte Listen enthalten noch keine Tasks; die
                    # vorhandenen Listen werden fuer den Abgleich gelesen.
                    all_lists.update(list_ids)
                    remote_tasks = await self._list_remote_tasks(google, task_api, all_lists)
                    task_ops = reconcile_tasks(
                        staged_tasks, remote_tasks, days=days, title=plan.title, prune=prune
                    )
                    task_counts = await self._apply_task_ops(
                        google, task_api, task_ops, list_ids, guard
                    )
                except Exception as exc:
                    hint = _task_access_error(exc)
                    if hint is not None:
                        raise hint from exc
                    raise

            creates_by_day: dict[str, list[StagedEvent]] = {}
            for event in ops.creates:
                creates_by_day.setdefault(event.day, []).append(event)
            updates_by_day: dict[str, list[tuple[str, StagedEvent]]] = {}
            for event_id, event in ops.updates:
                updates_by_day.setdefault(event.day, []).append((event_id, event))

            semaphore = asyncio.Semaphore(max(1, self.max_parallel_days))

            async def run_day(day_key: str) -> tuple[int, int]:
                async with semaphore:
                    made = changed = 0
                    for chunk in _chunks(updates_by_day.get(day_key, []), BATCH_SIZE):
                        pairs = [
                            (
                                event,
                                calendar.events.update(
                                    calendarId=calendar_id,
                                    eventId=event_id,
                                    json=_body_without_id(event),
                                ),
                            )
                            for event_id, event in chunk
                        ]
                        changed += len(
                            await _send_requests(
                                google, pairs, timeout=self.timeout, guard=guard
                            )
                        )
                    for chunk in _chunks(creates_by_day.get(day_key, []), BATCH_SIZE):
                        pairs = [
                            (
                                event,
                                calendar.events.insert(
                                    calendarId=calendar_id, json=dict(event.body)
                                ),
                            )
                            for event in chunk
                        ]
                        pending = []
                        for event, res in await _send_requests(
                            google, pairs, timeout=self.timeout, guard=guard
                        ):
                            if _response_kind(res) == "conflict":
                                pending.append(event)
                            else:
                                made += 1
                        if pending:
                            updates = [
                                (
                                    event,
                                    calendar.events.update(
                                        calendarId=calendar_id,
                                        eventId=event.event_id,
                                        json=_body_without_id(event),
                                    ),
                                )
                                for event in pending
                            ]
                            changed += len(
                                await _send_requests(
                                    google, updates, timeout=self.timeout, guard=guard
                                )
                            )
                    return made, changed

            day_keys = sorted(set(creates_by_day) | set(updates_by_day))
            results = list(await asyncio.gather(*(run_day(day) for day in day_keys)))
            created = sum(made for made, _ in results)
            updated = sum(changed for _, changed in results)

            # Loeschen erst nachdem alle Aenderungen geschrieben sind - ein
            # Abbruch laesst so nie Luecken zurueck.
            deleted = 0
            for chunk in _chunks(list(ops.deletes), BATCH_SIZE):
                pairs = [
                    (
                        remote_event.event_id,
                        calendar.events.delete(
                            calendarId=calendar_id, eventId=remote_event.event_id
                        ),
                    )
                    for remote_event in chunk
                ]
                deleted += len(
                    await _send_requests(google, pairs, timeout=self.timeout, guard=guard)
                )

        return GCalSyncReport(
            total=len(staged),
            created=created,
            updated=updated,
            dry_run=False,
            deleted=deleted,
            unchanged=ops.unchanged,
            tasks_total=len(staged_tasks),
            tasks_created=task_counts[0],
            tasks_updated=task_counts[1],
            tasks_deleted=task_counts[2],
            tasks_unchanged=task_ops.unchanged,
        )

    async def _list_task_lists(self, google, task_api) -> dict[str, str]:
        """Alle Google-Tasks-Listen als ``{Titel: listId}`` (erste gewinnt)."""
        titles: dict[str, str] = {}
        page_token = None
        while True:
            params = {"maxResults": 1000}
            if page_token:
                params["pageToken"] = page_token
            data = await google.as_user(
                task_api.tasklists.list(**params), timeout=self.timeout
            )
            for item in data.get("items", []):
                title = str(item.get("title") or "").strip()
                list_id = item.get("id")
                if title and list_id and title not in titles:
                    titles[title] = str(list_id)
            page_token = data.get("nextPageToken")
            if not page_token:
                return titles

    async def _task_list_ids(self, google, task_api, names: set[str]) -> dict[str, str]:
        """Listen-IDs aufloesen; fehlende Listen einmalig anlegen."""
        known = await self._list_task_lists(google, task_api)
        ids: dict[str, str] = {}
        for name in sorted(names):
            if name in known:
                ids[name] = known[name]
                continue
            created = await google.as_user(
                task_api.tasklists.insert(json={"title": name}), timeout=self.timeout
            )
            ids[name] = str(created["id"])
        return ids

    async def _list_remote_tasks(
        self, google, task_api, lists: dict[str, str]
    ) -> list[RemoteTask]:
        """Markierte und fremde Tasks aller Listen (inkl. erledigter)."""
        remote: list[RemoteTask] = []
        for list_name, list_id in lists.items():
            page_token = None
            while True:
                params = {
                    "tasklist": list_id,
                    "maxResults": 100,
                    "showCompleted": True,
                    "showHidden": True,
                }
                if page_token:
                    params["pageToken"] = page_token
                data = await google.as_user(
                    task_api.tasks.list(**params), timeout=self.timeout
                )
                remote.extend(
                    _parse_remote_tasks(
                        data.get("items", []), list_id=list_id, list_name=list_name
                    )
                )
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return remote

    async def _apply_task_ops(
        self, google, task_api, ops: TaskOps, list_ids: dict[str, str], guard: _RateGuard
    ) -> tuple[int, int, int]:
        """Creates/Updates/Deletes als Batches schreiben; ``(neu, geaendert, weg)``."""
        created = updated = deleted = 0
        for chunk in _chunks(list(ops.creates), BATCH_SIZE):
            pairs = [
                (
                    task,
                    task_api.tasks.insert(
                        tasklist=list_ids[task.list_name], json=_task_body(task)
                    ),
                )
                for task in chunk
            ]
            created += len(
                await _send_requests(google, pairs, timeout=self.timeout, guard=guard)
            )
        for chunk in _chunks(list(ops.updates), BATCH_SIZE):
            pairs = [
                (
                    (list_id, task_id, task),
                    task_api.tasks.patch(
                        tasklist=list_id, task=task_id, json=_task_body(task)
                    ),
                )
                for list_id, task_id, task in chunk
            ]
            updated += len(
                await _send_requests(google, pairs, timeout=self.timeout, guard=guard)
            )
        for chunk in _chunks(list(ops.deletes), BATCH_SIZE):
            pairs = [
                (
                    task,
                    task_api.tasks.delete(tasklist=task.list_id, task=task.task_id),
                )
                for task in chunk
            ]
            deleted += len(
                await _send_requests(google, pairs, timeout=self.timeout, guard=guard)
            )
        return created, updated, deleted

    async def _list_remote(self, google, calendar, *, plan, tz) -> list[RemoteEvent]:
        """Alle dir3-Events im Planfenster inkl. Marker/Schluessel einlesen."""
        calendar_id = self.settings.calendar_id
        time_min = datetime.combine(plan.days[0].date, time(0, 0), tzinfo=tz).isoformat()
        # +1 Tag: Events, die am letzten Plantag starten und nach Mitternacht enden
        time_max = datetime.combine(
            plan.days[-1].date + timedelta(days=1), time(0, 0), tzinfo=tz
        ).isoformat()
        remote: list[RemoteEvent] = []
        page_token = None
        while True:
            params = {
                "calendarId": calendar_id,
                "singleEvents": True,
                "maxResults": 2500,
                "privateExtendedProperty": "dir3=1",
                "timeMin": time_min,
                "timeMax": time_max,
                "fields": (
                    "nextPageToken,items(id,summary,start,end,colorId,description,"
                    "extendedProperties)"
                ),
            }
            if page_token:
                params["pageToken"] = page_token
            data = await google.as_user(calendar.events.list(**params), timeout=self.timeout)
            remote.extend(_parse_remote(data.get("items", []), tz))
            page_token = data.get("nextPageToken")
            if not page_token:
                return remote

    async def _list_ids(self, extra_params: dict) -> list[str]:
        """Event-IDs seitenweise einsammeln (Masters - direkt loeschbar)."""
        calendar_id = self.settings.calendar_id
        ids: list[str] = []
        page_token = None
        async with self._client_factory(self.settings, self.timeout) as (google, calendar):
            while True:
                params = {
                    "calendarId": calendar_id,
                    "maxResults": 2500,
                    "fields": "nextPageToken,items(id)",
                }
                params.update(extra_params)
                if page_token:
                    params["pageToken"] = page_token
                data = await google.as_user(calendar.events.list(**params), timeout=self.timeout)
                ids.extend(item["id"] for item in data.get("items", []) if item.get("id"))
                page_token = data.get("nextPageToken")
                if not page_token:
                    return ids

    async def list_dir3_event_ids(self) -> list[str]:
        """Alle Events, die dir3 angelegt hat (Marker ``private.dir3=1``)."""
        return await self._list_ids({"singleEvents": True, "privateExtendedProperty": "dir3=1"})

    async def list_all_event_ids(self) -> list[str]:
        """Alle Event-IDs im Kalender (fremde inklusive) - für ``--nuke``."""
        return await self._list_ids({})

    async def _list_dir3_tasks(self) -> list[RemoteTask]:
        """Alle offenen, von dir3 markierten Google Tasks (ohne Tasks-Scope: leer)."""
        try:
            async with self._client_factory(self.settings, self.timeout) as (google, _calendar):
                task_api = await google.discover("tasks", "v1")
                lists = await self._list_task_lists(google, task_api)
                remote = await self._list_remote_tasks(google, task_api, lists)
        except Exception as exc:
            if _task_access_error(exc) is not None:
                return []
            raise
        return [
            task for task in remote if task.marked and task.status != "completed"
        ]

    async def clear(self, *, dry_run: bool = False, nuke: bool = False) -> GCalClearReport:
        if nuke:
            ids = await self.list_all_event_ids()
            task_refs: list[RemoteTask] = []
        else:
            ids = await self.list_dir3_event_ids()
            task_refs = await self._list_dir3_tasks()
        if dry_run or (not ids and not task_refs):
            return GCalClearReport(
                deleted=len(ids), dry_run=dry_run, tasks_deleted=len(task_refs)
            )
        calendar_id = self.settings.calendar_id
        deleted = 0
        tasks_deleted = 0
        async with self._client_factory(self.settings, self.timeout) as (google, calendar):
            for chunk in _chunks(ids, BATCH_SIZE):
                pairs = [
                    (
                        event_id,
                        calendar.events.delete(calendarId=calendar_id, eventId=event_id),
                    )
                    for event_id in chunk
                ]
                # ok + gone (404/410, schon weg) zählen als erledigt
                deleted += len(await _send_requests(google, pairs, timeout=self.timeout))
            if task_refs:
                try:
                    task_api = await google.discover("tasks", "v1")
                    for chunk in _chunks(task_refs, BATCH_SIZE):
                        pairs = [
                            (
                                task,
                                task_api.tasks.delete(
                                    tasklist=task.list_id, task=task.task_id
                                ),
                            )
                            for task in chunk
                        ]
                        tasks_deleted += len(
                            await _send_requests(google, pairs, timeout=self.timeout)
                        )
                except Exception as exc:
                    if _task_access_error(exc) is None:
                        raise
        return GCalClearReport(
            deleted=deleted, dry_run=False, tasks_deleted=tasks_deleted
        )


def run_sync(
    syncer: GoogleCalendarSyncer,
    plan,
    *,
    timezone_name: str,
    dry_run: bool = False,
    prune: bool = True,
):
    """Sync-Wrapper für den synchronen CLI-Pfad."""
    return asyncio.run(
        syncer.sync(plan, timezone_name=timezone_name, dry_run=dry_run, prune=prune)
    )


def run_clear(syncer: GoogleCalendarSyncer, *, dry_run: bool = False, nuke: bool = False):
    """Clear-Wrapper für den synchronen CLI-Pfad."""
    return asyncio.run(syncer.clear(dry_run=dry_run, nuke=nuke))


def _aware(dt, tz):
    return dt.astimezone(tz) if dt.tzinfo is not None else dt.replace(tzinfo=tz)
