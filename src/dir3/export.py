"""Compile a plan into the phone-friendly JSON document.

``dir3 export`` and ``dir3 serve`` share this module.  The JSON is deliberately
small and provider-neutral: absolute ISO timestamps, a hex colour, an icon and
a flat list of resolved alarms.  The Android app only has to render it and
hand the alarms to Android's ``AlarmManager``.

The document is stable: event and alarm ids are derived from the event's
date/name/start, so recompiling the same plan yields the same ids and the
phone updates alarms instead of duplicating them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .alarm import Alarm, coerce_alarm
from .color import DefaultIconPolicy, name_slot, to_gcal_color_id
from .config import Dir3Config
from .engine import Plan, PlannedEvent, compile_pattern
from .services import Services

SCHEMA = 1

#: Google Calendar's fixed palette as hex, so the phone looks like the PC.
GCAL_HEX = {
    "1": "#a4bdfc",  # Lavender
    "2": "#7ae7bf",  # Sage
    "3": "#dbadff",  # Grape
    "4": "#ff887c",  # Flamingo
    "5": "#fbd75b",  # Banana
    "6": "#ffb878",  # Tangerine
    "7": "#46d6db",  # Peacock
    "8": "#e1e1e1",  # Graphite
    "9": "#5484ed",  # Blueberry
    "10": "#51b749",  # Basil
    "11": "#dc2127",  # Tomato
}

_PRAYER_WORDS = {"fajr", "sunrise", "dhuhr", "duhr", "jumuah", "asr", "maghrib", "isha"}
_WAKE_WORDS = ("fajr", "tahajjud", "tehecc", "suhoor", "sahur", "imsak", "qiyam", "seher")
_MEAL_WORDS = (
    "frühstück", "fruehstueck", "abendessen", "abendsessen", "suhoor", "sahur",
    "iftar", "essen", "breakfast", "dinner", "lunch", "meal",
)
_SLEEP_WORDS = ("schlaf", "sleep", "kayl", "qaylulah", "kaylûle")
_TRAVEL_WORDS = ("weg:", "weg ", "commute", "fahrt", "transit")
_FOCUS_WORDS = ("deep work", "lernen", "study", "coding", "arbeit", "work")


def timezone_of(services: Services) -> tuple[Any, str]:
    """Resolve the plan timezone; falls back to UTC without a network."""
    name = getattr(services.config.location, "timezone", None)
    try:
        location = services.geo.detect()
        name = name or location.timezone
    except Exception:  # pragma: no cover - geolocation unavailable
        pass
    name = name or "UTC"
    try:
        return ZoneInfo(name), name
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC"), "UTC"


def _aware(moment: datetime | None, tz) -> datetime | None:
    if moment is None:
        return None
    return moment.replace(tzinfo=tz) if moment.tzinfo is None else moment.astimezone(tz)


def _category(name: str) -> str:
    plain = name.lower()
    if any(word in plain for word in _WAKE_WORDS):
        return "wake"
    head = plain.replace("🕌", " ").replace("🧍", " ").split(" ")[0]
    if head in _PRAYER_WORDS or "jumuah" in plain:
        return "prayer"
    if any(word in plain for word in _MEAL_WORDS):
        return "meal"
    if any(word in plain for word in _SLEEP_WORDS):
        return "sleep"
    if any(word in plain for word in _TRAVEL_WORDS):
        return "travel"
    if any(word in plain for word in _FOCUS_WORDS):
        return "focus"
    return "other"


def _hex_color(value: object, name: str) -> tuple[str, str]:
    color_id = to_gcal_color_id(value)
    if color_id is None:
        color_id = to_gcal_color_id(name_slot(name)) or "1"
    return GCAL_HEX.get(color_id, "#a4bdfc"), color_id


def _event_id(day: date, name: str, start: datetime | None, position: int) -> str:
    payload = f"{day.isoformat()}|{name}|{start.isoformat() if start else ''}|{position}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def _resolved_alarms(
    spec: Alarm,
    *,
    event_id: str,
    event_name: str,
    start: datetime | None,
    end: datetime | None,
) -> list[dict[str, Any]]:
    if not spec.enabled:
        return []
    trigger = spec.trigger(start, end)
    if trigger is None:
        return []
    doc = spec.to_dict()
    doc.update(
        {
            "id": spec.identify(event_id),
            "event_id": event_id,
            "event_name": event_name,
            "trigger": trigger.isoformat(),
            "label": spec.label or event_name,
        }
    )
    if spec.pre_notify_minutes:
        doc["pre_trigger"] = (
            trigger - timedelta(minutes=spec.pre_notify_minutes)
        ).isoformat()
    return [doc]


def plan_event_to_doc(
    event: PlannedEvent,
    *,
    day: date,
    tz,
    index: int,
    color_policy: object | None,
    icon_policy: object | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """One compiled event plus its resolved alarms."""
    start = _aware(event.start, tz)
    end = _aware(event.end, tz)
    event_id = _event_id(day, event.name, start, index)
    icon = ""
    if icon_policy is not None:
        try:
            icon = icon_policy.icon_for(event.name, index) or ""
        except Exception:  # pragma: no cover - custom policies
            icon = ""
    color = None
    if color_policy is not None:
        try:
            color = color_policy.color_for(event.name, index)
        except Exception:  # pragma: no cover - custom policies
            color = None
    hex_color, color_id = _hex_color(color, event.name)
    alarms: list[dict[str, Any]] = []
    for spec in getattr(event, "alarms", ()):
        alarms.extend(
            _resolved_alarms(
                spec,
                event_id=event_id,
                event_name=event.name,
                start=start,
                end=end,
            )
        )
    if not event.active:
        return None, alarms
    return (
        {
            "id": event_id,
            "source": "plan",
            "name": event.name,
            "title": f"{icon} {event.name}".strip(),
            "icon": icon,
            "date": day.isoformat(),
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "all_day": False,
            "color": hex_color,
            "color_id": color_id,
            "category": _category(event.name),
            "carry": bool(event.carry),
            "open": bool(event.open_),
            "alarm_ids": [item["id"] for item in alarms],
        },
        alarms,
    )


def phone_event_to_doc(
    item: dict[str, Any],
    *,
    tz,
    color_policy: object | None = None,
    icon_policy: object | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Normalise a manually created phone event (one-off, not compiled)."""
    title = str(item.get("title") or item.get("name") or "").strip()
    if not title:
        return None, []
    day = str(item.get("date") or "")
    try:
        event_date = date.fromisoformat(day)
    except ValueError:
        return None, []
    start_clock = _parse_clock(item.get("start"))
    end_clock = _parse_clock(item.get("end"))
    if start_clock is None:
        return None, []
    start = datetime.combine(event_date, start_clock, tzinfo=tz)
    if end_clock is None:
        end = start + timedelta(hours=1)
    else:
        end = datetime.combine(event_date, end_clock, tzinfo=tz)
        if end <= start:
            end += timedelta(days=1)
    event_id = str(item.get("id") or "") or _event_id(event_date, title, start, 0)
    raw_alarms = item.get("alarms", item.get("alarm"))
    parsed = coerce_alarm(raw_alarms) or ()
    alarms: list[dict[str, Any]] = []
    for spec in parsed:
        alarms.extend(
            _resolved_alarms(
                spec,
                event_id=event_id,
                event_name=title,
                start=start,
                end=end,
            )
        )
    if color_policy is not None:
        color_value = color_policy.color_for(title, 0)
        hex_color, color_id = _hex_color(color_value, title)
    else:
        hex_color, color_id = _hex_color(None, title)
    hex_color = str(item.get("color") or hex_color)
    icon = ""
    if icon_policy is not None:
        try:
            icon = icon_policy.icon_for(title, 0) or ""
        except Exception:  # pragma: no cover
            icon = ""
    return (
        {
            "id": event_id,
            "source": "phone",
            "name": title,
            "title": f"{icon} {title}".strip(),
            "icon": icon,
            "date": event_date.isoformat(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "all_day": False,
            "color": hex_color,
            "color_id": color_id,
            "category": _category(title),
            "carry": end.date() > event_date,
            "open": False,
            "notes": str(item.get("notes") or ""),
            "alarm_ids": [alarm["id"] for alarm in alarms],
        },
        alarms,
    )


def _parse_clock(value: object) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Ungueltige Uhrzeit {value!r} (HH:MM erwartet)")


def plan_to_dict(
    plan: Plan,
    *,
    timezone_name: str,
    tz=None,
    title: str | None = None,
    source: str | None = None,
    icon_policy: object | None = None,
    color_policy: object | None = None,
    phone_events: list[dict[str, Any]] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the complete phone document for ``plan``."""
    tz = tz or ZoneInfo("UTC")
    icon_policy = icon_policy if icon_policy is not None else DefaultIconPolicy()
    events: list[dict[str, Any]] = []
    alarms: list[dict[str, Any]] = []
    for pday in plan.days:
        for index, event in enumerate(pday.events):
            doc, resolved = plan_event_to_doc(
                event,
                day=pday.date,
                tz=tz,
                index=index,
                color_policy=color_policy,
                icon_policy=icon_policy,
            )
            if doc is not None:
                events.append(doc)
            alarms.extend(resolved)
    for item in phone_events or ():
        doc, resolved = phone_event_to_doc(
            item, tz=tz, color_policy=color_policy, icon_policy=icon_policy
        )
        if doc is not None:
            events.append(doc)
            alarms.extend(resolved)
    events.sort(key=lambda item: (item["start"] or "", item["title"]))
    alarms.sort(key=lambda item: item["trigger"])
    now = generated_at or datetime.now(tz)
    return {
        "schema": SCHEMA,
        "generator": "dir3",
        "generated_at": now.isoformat(),
        "title": title or plan.title,
        "source": {
            "planfile": source,
            "timezone": timezone_name,
            "start": plan.start.isoformat(),
            "days": len(plan.days),
        },
        "events": events,
        "alarms": alarms,
    }


@dataclass(slots=True)
class Runtime:
    """A loaded planfile plus its config and services."""

    planfile: Path
    module: Any
    config: Dir3Config
    services: Services
    pattern: Any


def load_runtime(
    planfile: Path | str,
    *,
    config_path: Path | str | None = None,
    offline: bool = False,
) -> Runtime:
    """Load a planfile exactly like the CLI does (central config first)."""
    from .cli import _extract_pattern, _load_module

    path = Path(planfile).resolve()
    module = _load_module(path)
    plan_config = Dir3Config().overlay(module)
    resolved_config = Path(config_path) if config_path is not None else None
    if resolved_config is None and plan_config.sync.config is not None:
        resolved_config = Path(plan_config.sync.config)
    if resolved_config is not None and not resolved_config.is_absolute():
        resolved_config = path.resolve().parent / resolved_config

    config = Dir3Config()
    if resolved_config is not None:
        if not resolved_config.exists():
            raise FileNotFoundError(f"Config-Datei existiert nicht: {resolved_config}")
        from .cli import _CONFIG_SEED

        central = _load_module(
            resolved_config,
            name="dir3_central_config",
            seed=_CONFIG_SEED,
            what="Config-Datei",
        )
        config.overlay(central)
    config.overlay(module)
    if offline or config.sync.offline:
        config.prayer.provider = "offline"
    services = Services(config=config)
    pattern = _extract_pattern(module)
    if pattern is None:
        raise ValueError(f"{path} definiert weder 'plan' noch 'make_plan()'")
    return Runtime(path, module, config, services, pattern)


def compile_runtime(
    runtime: Runtime,
    *,
    until: int | None = None,
    start: date | None = None,
    no_alarms: bool = False,
) -> Plan:
    horizon = until if until is not None else runtime.config.sync.until
    start_date = start
    if start_date is None and runtime.config.sync.start is not None:
        value = runtime.config.sync.start
        start_date = value if isinstance(value, date) else date.fromisoformat(str(value))
    settings = runtime.config.alarms
    previous = settings.enabled
    if no_alarms:
        settings.enabled = False
    try:
        return compile_pattern(
            runtime.pattern,
            until=horizon,
            start_date=start_date,
            title=getattr(runtime.module, "__title__", None)
            or getattr(runtime.module, "__name__", "dir3"),
            services=runtime.services,
        )
    finally:
        # A cached Runtime is reused by `dir3 serve`; one request must not
        # silence alarms for every later request.
        settings.enabled = previous


def runtime_document(
    runtime: Runtime,
    *,
    until: int | None = None,
    start: date | None = None,
    no_alarms: bool = False,
    phone_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    plan = compile_runtime(runtime, until=until, start=start, no_alarms=no_alarms)
    tz, tz_name = timezone_of(runtime.services)
    return plan_to_dict(
        plan,
        tz=tz,
        timezone_name=tz_name,
        title=getattr(runtime.module, "__title__", None),
        source=str(runtime.planfile),
        icon_policy=runtime.config.icon_policy,
        color_policy=runtime.config.color_policy,
        phone_events=phone_events,
    )


def export_main(argv: list[str] | None = None) -> int:
    """``dir3 export <planfile> [-o plan.json]``."""
    parser = argparse.ArgumentParser(
        prog="dir3 export",
        description="Kompiliert den Plan als JSON fuer die Android-App / dir3 serve.",
    )
    parser.add_argument("planfile", type=Path)
    parser.add_argument("--until", type=int, default=None, help="Horizont in Tagen")
    parser.add_argument("--from", dest="start", default=None, help="Startdatum YYYY-MM-DD")
    parser.add_argument("--offline", action="store_true", help="Gebetszeiten offline")
    parser.add_argument("--config", type=Path, default=None, help="Zentrale Config-Datei")
    parser.add_argument("--no-alarms", action="store_true", help="Automatische Alarme aus")
    parser.add_argument(
        "--phone-events",
        type=Path,
        default=None,
        help="JSON-Datei mit manuell erstellten Phone-Events",
    )
    parser.add_argument("-o", "--output", type=Path, default=None, help="Zieldatei (sonst stdout)")
    args = parser.parse_args(argv)

    if not args.planfile.exists():
        parser.error(f"Planfile existiert nicht: {args.planfile}")
    start = date.fromisoformat(args.start) if args.start else None
    runtime = load_runtime(
        args.planfile, config_path=args.config, offline=args.offline
    )
    phone_events = None
    if args.phone_events is not None:
        phone_events = json.loads(args.phone_events.read_text(encoding="utf-8"))
        if isinstance(phone_events, dict):
            phone_events = phone_events.get("events", [])
    document = runtime_document(
        runtime,
        until=args.until,
        start=start,
        no_alarms=args.no_alarms,
        phone_events=phone_events,
    )
    text = json.dumps(document, ensure_ascii=False, indent=2)
    if args.output is None:
        print(text)
    else:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(
            f"{len(document['events'])} Events, "
            f"{len(document['alarms'])} Alarme -> {args.output}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(export_main())
