"""Time helpers: parsing, formatting and safe time arithmetic.

All time arithmetic wraps modulo 24h (forward in time), e.g. "01:00 + 2h" -> "03:00".
A helper computing cross-midnight deltas is provided for prayer-bound spans.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta


class TimeFormatError(ValueError):
    pass


def parse_hhmm(value: str) -> time:
    """Parse '05:00' or '05.00' into a ``datetime.time``."""
    cleaned = value.strip()
    sep = ":" if ":" in cleaned else "."
    if sep not in cleaned:
        raise TimeFormatError(f"Unsupported time format: {value!r}")
    hour_s, minute_s = cleaned.split(sep, 1)
    try:
        hour = int(hour_s)
        minute = int(minute_s)
    except ValueError as exc:  # pragma: no cover - defensive
        raise TimeFormatError(f"Invalid time value: {value!r}") from exc
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise TimeFormatError(f"Invalid time value: {value!r}")
    return time(hour=hour, minute=minute)


def parse_duration(value: str | int) -> timedelta:
    """Parse '2h', '90m', '1:30', '1.30', '1h30m' or plain minutes.

    Compound forms like '1h30m' are allowed and combine to a single timedelta.
    """
    cleaned = str(value).strip().lower()
    if any(marker in cleaned for marker in ("h", "m")) and not cleaned.isdigit():
        total = timedelta()
        rest = cleaned
        matched = False
        for (unit, factor) in (("h", 60 * 60), ("m", 60)):
            if unit in rest:
                head, _, tail = rest.partition(unit)
                if head:
                    total += timedelta(seconds=float(head) * factor)
                    matched = True
                rest = tail
        if matched and not rest:
            return total
    if cleaned.endswith("m"):
        return timedelta(minutes=float(cleaned[:-1]))
    if cleaned.endswith("h"):
        return timedelta(hours=float(cleaned[:-1]))
    if ":" in cleaned:
        hours, minutes = cleaned.split(":", 1)
        return timedelta(hours=int(hours or 0), minutes=int(minutes or 0))
    if "." in cleaned:
        hours, minutes = cleaned.split(".", 1)
        return timedelta(hours=int(hours or 0), minutes=int(minutes or 0))
    if cleaned.isdigit():
        return timedelta(minutes=int(cleaned))
    raise TimeFormatError(f"Unsupported duration format: {value!r}")


def format_time(value: time) -> str:
    return value.strftime("%H:%M")


def format_duration(value: timedelta) -> str:
    total_minutes = int(value.total_seconds() // 60)
    hours, minutes = divmod(abs(total_minutes), 60)
    sign = "-" if total_minutes < 0 else ""
    if hours:
        return f"{sign}{hours}:{minutes:02d} h"
    return f"{sign}{minutes} min"


def combine(day: date, moment: time) -> datetime:
    return datetime.combine(day, moment)


def add_time_seconds(moment: time, seconds: int) -> time:
    """Shift a time by seconds, wrapping forward across midnight."""
    base = datetime.combine(date(2000, 1, 1), moment) + timedelta(seconds=seconds)
    return base.time()


def add_time(moment: time, delta: timedelta) -> time:
    return add_time_seconds(moment, int(delta.total_seconds()))


def subtract_time(moment: time, delta: timedelta) -> time:
    return add_time_seconds(moment, -int(delta.total_seconds()))


def span_between(start: time, end: time) -> timedelta:
    """Positive timedelta from start to end, wrapping if end is before start."""
    anchor = date(2000, 1, 1)
    start_dt = datetime.combine(anchor, start)
    end_dt = datetime.combine(anchor, end)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return end_dt - start_dt


def seconds_since_midnight(moment: time) -> int:
    return (moment.hour * 3600) + (moment.minute * 60) + moment.second
