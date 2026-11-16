"""The phone document: event ids, colors and resolved alarm triggers."""

from __future__ import annotations

from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from dir3 import alarm, task, week
from dir3.alarm import alarm_from_dict
from dir3.config import Dir3Config, LocationSettings
from dir3.engine import compile_pattern
from dir3.export import phone_event_to_doc, plan_to_dict
from dir3.services import Services


def _plan():
    def day_fn(ctx):
        return [
            task("Fajr", start=time(5, 0), duration="30m"),
            task("Deep Work", start=time(9, 0), duration="2h",
                 alarm=alarm(when="end", offset="-10m", speak=True)),
            task("Schlafen", start=time(23, 0), until=time(6, 0), flex=False),
        ]

    return compile_pattern(
        week(mon=day_fn), days=1, start_date=date(2026, 11, 16),
        services=Services(config=Dir3Config(
            location=LocationSettings(latitude=52.52, longitude=13.405, timezone="Europe/Berlin"),
        )),
    )


def test_document_shape_and_alarm_triggers():
    tz = ZoneInfo("Europe/Berlin")
    doc = plan_to_dict(_plan(), tz=tz, timezone_name="Europe/Berlin")
    assert doc["schema"] == 1
    assert doc["source"]["days"] == 1
    assert len(doc["events"]) == 3
    assert len(doc["alarms"]) == 2
    by_name = {item["event_name"]: item for item in doc["alarms"]}
    assert by_name["Fajr"]["trigger"] == "2026-11-16T05:00:00+01:00"
    assert by_name["Deep Work"]["trigger"] == "2026-11-16T10:50:00+01:00"
    assert by_name["Deep Work"]["offset_seconds"] == -600
    assert by_name["Deep Work"]["speak"] is True
    event = next(item for item in doc["events"] if item["name"] == "Deep Work")
    assert event["alarm_ids"] == [by_name["Deep Work"]["id"]]
    assert event["category"] == "focus"
    assert event["color"].startswith("#")


def test_ids_are_stable_across_compilations():
    tz = ZoneInfo("UTC")
    first = plan_to_dict(_plan(), tz=tz, timezone_name="UTC")
    second = plan_to_dict(_plan(), tz=tz, timezone_name="UTC")
    assert [item["id"] for item in first["events"]] == [item["id"] for item in second["events"]]
    assert [item["id"] for item in first["alarms"]] == [item["id"] for item in second["alarms"]]


def test_phone_event_roundtrip():
    tz = ZoneInfo("UTC")
    event, alarms = phone_event_to_doc(
        {
            "id": "abc",
            "title": "Spor",
            "date": "2026-11-16",
            "start": "18:30",
            "end": "19:30",
            "color": "#ff887c",
            "alarms": [
                alarm(when="start", offset="-5m", speak=True).to_dict(),
            ],
        },
        tz=tz,
    )
    assert event["source"] == "phone"
    assert event["start"] == "2026-11-16T18:30:00+00:00"
    assert alarms[0]["trigger"] == "2026-11-16T18:25:00+00:00"
    assert event["alarm_ids"] == [alarms[0]["id"]]
    restored = alarm_from_dict(alarms[0])
    assert restored.offset == timedelta(minutes=-5)


def test_phone_event_without_alarm():
    event, alarms = phone_event_to_doc(
        {"title": "Not", "date": "2026-11-16", "start": "08:00"},
        tz=ZoneInfo("UTC"),
    )
    assert alarms == []
    assert event["end"] == "2026-11-16T09:00:00+00:00"
