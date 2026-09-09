"""Google Calendar sync - asynchron (httpx) statt blocking-requests.

Der Sync schiebt einen kompilierten :class:`Plan` als Events in Google
Calendar.  Credentials liegen im Python-Planfile (``gcal = GoogleCalendar(...)``)
- gleiche Philosophie wie der Rest von dir3.

Idempotenz: jedes Event bekommt eine deterministische Custom-ID
(``dir3<sha1-hex>``), abgeleitet aus Titel/Tag/Name/Zeiten.  Ein erneuter Lauf
desselben Plans aktualisiert dann (POST -> 409 -> PUT) statt zu duplizieren.

Auth (OAuth2):
  * ``refresh_token`` + ``client_id``/``client_secret`` -> Token-Endpunkt,
  * oder ein bereits ausgestelltes ``access_token`` wird direkt benutzt.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from ..config import GoogleCalendar
from .geo import _resolve_tz

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"


@dataclass(frozen=True, slots=True)
class StagedEvent:
    event_id: str
    summary: str
    body: dict[str, object]
    when: str


@dataclass(frozen=True, slots=True)
class GCalSyncReport:
    total: int
    created: int
    updated: int
    dry_run: bool

    def __str__(self) -> str:
        verb = "geplant" if self.dry_run else "synchronisiert"
        noun = "Event" if self.total == 1 else "Events"
        parts = [f"GCal: {self.total} {noun} {verb}"]
        if not self.dry_run:
            parts.append(f"{self.created} neu, {self.updated} aktualisiert")
        return " · ".join(parts)


@dataclass(frozen=True, slots=True)
class GCalClearReport:
    deleted: int
    dry_run: bool

    def __str__(self) -> str:
        noun = "Event" if self.deleted == 1 else "Events"
        if self.dry_run:
            return f"GCal: wuerde {self.deleted} {noun} loeschen"
        return f"GCal: {self.deleted} {noun} geloescht"


class GoogleCalendarSyncer:
    def __init__(self, settings: GoogleCalendar, *, transport=None, timeout: float = 10.0) -> None:
        self.settings = settings
        self._transport = transport  # httpx.MockTransport in Tests
        self.timeout = timeout
        self._access_token: str | None = None

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=self.timeout)

    async def access_token(self) -> str:
        """Kurzlebiges Access-Token holen und für den Lauf merken."""
        if self.settings.access_token:
            return self.settings.access_token
        if self._access_token:
            return self._access_token
        async with self._new_client() as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret,
                    "refresh_token": self.settings.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            self._access_token = response.json()["access_token"]
            return self._access_token

    def stage(self, plan, *, timezone_name: str) -> list[StagedEvent]:
        """Alle aktiven Events als GCal-Payloads aufbauen (rein, kein Netzwerk).

        Der Engine arbeitet in Plan-Wanduhrzeit (naive datetimes); hier wird die
        Plan-Zeitzone attachiert, damit GCal absolute Zeitpunkte bekommt.
        """
        tz = _resolve_tz(timezone_name or "UTC")
        tz_label = getattr(tz, "key", None) or "UTC"
        staged: list[StagedEvent] = []
        for day_ in plan.days:
            if not day_.active:
                continue
            for ev in day_.events:
                if not ev.active:
                    continue
                start = _aware(ev.start, tz)
                end = _aware(ev.end, tz)
                fingerprint = "|".join(
                    (plan.title, day_.date.isoformat(), ev.name, start.isoformat(), end.isoformat())
                )
                event_id = "dir3" + hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()
                body = {
                    "summary": ev.name,
                    "start": {"dateTime": start.isoformat(), "timeZone": tz_label},
                    "end": {"dateTime": end.isoformat(), "timeZone": tz_label},
                    "description": f"dir3 · {plan.title}",
                    "extendedProperties": {"private": {"dir3": "1"}},
                }
                staged.append(
                    StagedEvent(
                        event_id=event_id,
                        summary=ev.name,
                        body=body,
                        when=start.isoformat(),
                    )
                )
        staged.sort(key=lambda event: event.when)
        return staged

    async def sync(
        self,
        plan,
        *,
        timezone_name: str,
        dry_run: bool = False,
    ) -> GCalSyncReport:
        staged = self.stage(plan, timezone_name=timezone_name)
        if dry_run or not staged:
            return GCalSyncReport(total=len(staged), created=0, updated=0, dry_run=dry_run)

        token = await self.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        calendar = quote(self.settings.calendar_id, safe="")
        created = updated = 0
        async with self._new_client() as client:
            for event in staged:
                url = f"{API_BASE}/calendars/{calendar}/events"
                response = await client.post(url, json=event.body, headers=headers)
                if response.status_code == 409:
                    response = await client.put(
                        f"{url}/{quote(event.event_id, safe='')}",
                        json=event.body,
                        headers=headers,
                    )
                    updated += 1
                else:
                    created += 1
                response.raise_for_status()
        return GCalSyncReport(total=len(staged), created=created, updated=updated, dry_run=False)

    async def list_dir3_event_ids(self) -> list[str]:
        """Alle Events, die dir3 angelegt hat (Marker ``private.dir3=1``)."""
        token = await self.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        calendar = quote(self.settings.calendar_id, safe="")
        ids: list[str] = []
        page_token = None
        async with self._new_client() as client:
            while True:
                params = {
                    "maxResults": "2500",
                    "singleEvents": "true",
                    "privateExtendedProperty": "dir3=1",
                    "fields": "nextPageToken,items(id)",
                }
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get(
                    f"{API_BASE}/calendars/{calendar}/events", params=params, headers=headers
                )
                response.raise_for_status()
                data = response.json()
                ids.extend(item["id"] for item in data.get("items", []) if item.get("id"))
                page_token = data.get("nextPageToken")
                if not page_token:
                    return ids

    async def clear(self, *, dry_run: bool = False) -> GCalClearReport:
        ids = await self.list_dir3_event_ids()
        if dry_run or not ids:
            return GCalClearReport(deleted=len(ids), dry_run=dry_run)
        token = await self.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        calendar = quote(self.settings.calendar_id, safe="")
        deleted = 0
        async with self._new_client() as client:
            for event_id in ids:
                response = await client.delete(
                    f"{API_BASE}/calendars/{calendar}/events/{quote(event_id, safe='')}",
                    headers=headers,
                )
                response.raise_for_status()
                deleted += 1
        return GCalClearReport(deleted=deleted, dry_run=False)


def run_sync(syncer: GoogleCalendarSyncer, plan, *, timezone_name: str, dry_run: bool = False):
    """Sync-Wrapper für den synchronen CLI-Pfad."""
    return asyncio.run(syncer.sync(plan, timezone_name=timezone_name, dry_run=dry_run))


def run_clear(syncer: GoogleCalendarSyncer, *, dry_run: bool = False):
    """Clear-Wrapper für den synchronen CLI-Pfad."""
    return asyncio.run(syncer.clear(dry_run=dry_run))


def _aware(dt, tz):
    return dt.astimezone(tz) if dt.tzinfo is not None else dt.replace(tzinfo=tz)
