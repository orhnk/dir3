"""Human-readable output: the compiled plan, printed softly."""
from __future__ import annotations

from datetime import timedelta

from .engine import Plan, PlanDay, PlannedEvent
from .timeutils import format_duration, format_time

WEEKDAY_LABELS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def weekday_label(plan_date) -> str:  # datetime.date
    return WEEKDAY_LABELS[plan_date.weekday()]


def render_plan(plan: Plan) -> str:
    lines: list[str] = []
    header = f"dir3 — {plan.title}  ({plan.start.isoformat()} → +{len(plan.days)} Tage)"
    lines.append(header)
    lines.append("=" * len(header))
    for idx, day in enumerate(plan.days):
        lines.append(_render_day(idx, day))
    summary = plan.summary()
    lines.append("-" * max(len(header), 20))
    lines.append(
        f"{summary['planned_days']} geplante Tage · "
        f"TO PLAN gesamt {format_duration(summary['total_slack'])} · "
        f"trimmed {summary['trimmed']} Events"
    )
    if (summary["total_overflow"]) > timedelta(0):
        lines.append(
            f"⚠  {format_duration(summary['total_overflow'])} passen nicht "
            "(auch nach Kompensation) - Plan kürzen."
        )
    return "\n".join(lines)


def _render_day(index: int, day: PlanDay) -> str:
    date_str = f"{weekday_label(day.date)} {day.date.isoformat()}"
    if not day.active:
        return f"{date_str}  [frei]"
    events = [ev for ev in day.events]
    lines = [f"{date_str}  ·  {day.name}"]
    for ev in events:
        lines.append("  " + _render_event(ev))
    notes: list[str] = []
    if day.skipped_count:
        notes.append(f"{day.skipped_count} übersprungen")
    if day.trimmed_total > timedelta(0):
        notes.append(f"trimmed {format_duration(day.trimmed_total)}")
    flags = " · ".join(notes)
    slack_text = f"TO PLAN {format_duration(day.slack)}" if day.slack > timedelta(0) else "voll"
    line = f"      [{slack_text}]"
    if flags:
        line += f" | {flags}"
    if day.overflow > timedelta(0):
        line += f" | ⚠ Überlauf {format_duration(day.overflow)}"
    lines.append(line)
    return "\n".join(lines)


def _render_event(ev: PlannedEvent) -> str:
    if ev.skipped:
        return f"⏭  {ev.name}   (entfällt)"
    start_text = format_time(ev.start.time()) if ev.start else "--:--"
    end_text = format_time(ev.end.time()) if ev.end else "offen"
    body = f"{start_text} – {end_text}   {ev.name}"
    if ev.open_:
        body += "   (offen)"
    if ev.carry:
        body += "   (läuft ins Folgetag)"
    if ev.trimmed > timedelta(0):
        body += f"   [gestaucht -{format_duration(ev.trimmed)}]"
    return body
