"""Alarms on plan events - the phone rings because *the plan* says so.

dir3 treats an alarm as data of a task, not as a separate app feature::

    task("Fajr", start=prayer.fajr, duration="30m",
         alarm=alarm(speak=True, sound="adhan"))

    task("Deep Work", start=time(9), duration="2h",
         alarm=alarm(when="end", offset="-10m", label="Wrap up"))

    task("Wake", ..., alarm=True)          # default alarm at the start
    task("Silent block", ..., alarm=False)  # never ring, even for wake events

The specification is portable: the compiler keeps it, ``dir3 export`` resolves
it to absolute trigger times and the phone app (or any other sink) plays it.
Every alarm capability of the reference Clock app is represented here: custom
label, ringtone (single, random pool or URI), text-to-speech of the event
name, volume/crescendo, vibration patterns, snooze duration and limit,
dismiss challenges (button, swipe, math, flip, shake, power/volume button),
full-screen wake-up, background colour, flashlight and a pre-notification.

``WakeAlarmPolicy`` encodes the house rule: Fajr, Tahajjud and Suhoor are
wake-up events and ring by default; when such events are back to back (for
example Tahajjud -> Witr -> Suhoor) only the first one rings, so the phone
does not scream three times in a row.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

ZERO = timedelta(0)

WHEN_CHOICES = ("start", "end")

#: Dismissal challenges understood by the phone app.
DISMISS_CHOICES = ("button", "swipe", "math", "flip", "shake", "power", "volume")

#: Named vibration patterns (the app also accepts ``"custom:100,200,100"``).
VIBRATION_PATTERNS = ("default", "short", "long", "heartbeat", "off")

#: Keywords that mark an event as a wake-up event (case/punctuation tolerant).
WAKE_KEYWORDS = (
    "fajr",
    "tahajjud",
    "tehecc",
    "suhoor",
    "sahur",
    "imsak",
    "qiyam",
    "seher",
)

#: Events that may sit *inside* a wake-up chain without breaking it.
CHAIN_KEYWORDS = WAKE_KEYWORDS + ("witr",)


class AlarmError(ValueError):
    """An invalid alarm specification."""


_OFFSET_TOKEN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(weeks?|w|days?|d|hours?|h|minutes?|min|m|seconds?|s)?",
    re.I,
)
_UNIT_SECONDS = {
    "w": 7 * 86400,
    "week": 7 * 86400,
    "weeks": 7 * 86400,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "h": 3600,
    "hour": 3600,
    "hours": 3600,
    "m": 60,
    "min": 60,
    "minute": 60,
    "minutes": 60,
    "s": 1,
    "second": 1,
    "seconds": 1,
}
#: Bare numbers (``alarm(offset=10)``, ``"10"``) mean minutes - the unit a
#: human schedules with.  Use a suffix for anything else.
_BARE_NUMBER_UNIT = "m"


def parse_offset(value: object) -> timedelta:
    """Parse ``"-10m"``, ``"1h30m"``, ``"90"`` (minutes) or a timedelta.

    A leading ``-`` makes the alarm fire *before* the anchor, ``+`` after it.
    An alarm without a sign is relative to the event start, so it rings after
    it; use a negative offset for a reminder before the event.
    """
    if value is None:
        return ZERO
    if isinstance(value, timedelta):
        return value
    if isinstance(value, bool):
        raise AlarmError("offset needs a duration, not a bool")
    if isinstance(value, (int, float)):
        return timedelta(minutes=float(value))
    text = str(value).strip().lower()
    if not text:
        return ZERO
    if text in ("0", "none", "off"):
        return ZERO
    sign = -1 if text.startswith("-") else 1
    if text[0] in "+-":
        text = text[1:].strip()
    total = 0.0
    position = 0
    matched = False
    for match in _OFFSET_TOKEN.finditer(text):
        if match.start() != position:
            raise AlarmError(f"ungueltiger offset {value!r}")
        position = match.end()
        amount = float(match.group(1))
        unit = (match.group(2) or _BARE_NUMBER_UNIT).lower()
        if unit not in _UNIT_SECONDS:
            raise AlarmError(f"ungueltige offset-Einheit in {value!r}")
        total += amount * _UNIT_SECONDS[unit]
        matched = True
    if not matched or text[position:].strip():
        raise AlarmError(f"ungueltiger offset {value!r}")
    return timedelta(seconds=sign * total)


def _normalize_when(value: object) -> str:
    text = str(value or "start").strip().lower()
    aliases = {
        "start": "start",
        "begin": "start",
        "on": "start",
        "event": "start",
        "end": "end",
        "finish": "end",
        "after": "end",
    }
    if text not in aliases:
        raise AlarmError(f"alarm.when muss 'start' oder 'end' sein, nicht {value!r}")
    return aliases[text]


def _normalize_dismiss(value: object) -> tuple[str, ...]:
    if value is None:
        return ("button",)
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    else:
        items = [str(part).strip() for part in value]
    result: list[str] = []
    for item in items:
        key = item.lower()
        if key not in DISMISS_CHOICES:
            raise AlarmError(
                f"unbekannte dismiss-Methode {item!r} "
                f"(erlaubt: {', '.join(DISMISS_CHOICES)})"
            )
        if key not in result:
            result.append(key)
    if not result:
        result = ["button"]
    if "button" in result and len(result) > 1:
        # A plain button always works; keeping it next to challenges would
        # make the challenge pointless.
        result = [item for item in result if item != "button"]
    return tuple(result)


def _normalize_vibration(value: object) -> str:
    if value is None or value is True:
        return "default"
    if value is False:
        return "off"
    if isinstance(value, (list, tuple)):
        return "custom:" + ",".join(str(int(part)) for part in value)
    text = str(value).strip()
    if text.lower() in VIBRATION_PATTERNS or text.lower().startswith("custom:"):
        return text.lower()
    raise AlarmError(f"unbekanntes Vibrationsmuster {value!r}")


def _normalize_repeat(value: object) -> tuple[int, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        names = {
            "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
            "mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6,
        }
        items = [part.strip().lower() for part in value.split(",") if part.strip()]
        try:
            return tuple(sorted({names[item] for item in items}))
        except KeyError as exc:
            raise AlarmError(f"unbekannter Wochentag {exc.args[0]!r}") from None
    days = tuple(sorted({int(part) for part in value}))
    if any(day < 0 or day > 6 for day in days):
        raise AlarmError("repeat braucht Wochentage 0 (Mo) bis 6 (So)")
    return days


@dataclass(frozen=True, slots=True)
class Alarm:
    """One alarm attached to an event.

    The defaults are a normal, loud phone alarm: at the event start, system
    alarm sound, vibrating, crescendo, snooze every 5 minutes (3 times), a
    full-screen wake-up and a plain dismiss button.  Plans override only what
    they care about::

        alarm(speak=True)                       # read the event name aloud
        alarm(when="end", offset="-10m")        # 10 min before the end
        alarm(sound="adhan.mp3", backdrop="#000")
        alarm(dismiss=("math", "flip"))         # Clock-style challenges
    """

    when: str = "start"
    offset: timedelta = ZERO
    #: Text shown on the alarm screen; defaults to the event name.
    label: str | None = None
    #: ``"system"`` (default), an asset name, a ``content://`` URI, or
    #: ``"random"`` to pick one of ``sounds``.
    sound: str | None = None
    #: Pool for ``sound="random"`` (played in random order, Clock-style).
    sounds: tuple[str, ...] = ()
    speak: bool = False
    #: Spoken text; defaults to the event name without markers.
    speak_text: str | None = None
    #: 0..100; ``None`` keeps the device alarm volume.
    volume: int | None = None
    crescendo: bool = True
    crescendo_seconds: int = 30
    vibrate: bool = True
    vibration: str = "default"
    snooze_minutes: int = 5
    #: 0 = unlimited snoozes.
    snooze_limit: int = 3
    #: One or more of :data:`DISMISS_CHOICES`; the first one is primary.
    dismiss: tuple[str, ...] = ("button",)
    dismiss_math: str = "medium"
    full_screen: bool = True
    #: Show a heads-up reminder this many minutes before the alarm.
    pre_notify_minutes: int | None = None
    #: Alarm-screen background (``"black"`` or ``#rrggbb``).
    background: str | None = None
    flashlight: bool = False
    #: Ring even when the phone is in silent / Do-Not-Disturb mode.
    silent_override: bool = True
    enabled: bool = True
    #: Clock's "skip next": keep the alarm but do not ring this once.
    skip_next: bool = False
    #: Weekdays (0 = Monday) for standalone alarms; ``None`` = every
    #: occurrence of the event instance.
    repeat: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "when", _normalize_when(self.when))
        object.__setattr__(self, "offset", parse_offset(self.offset))
        object.__setattr__(self, "dismiss", _normalize_dismiss(self.dismiss))
        object.__setattr__(self, "vibration", _normalize_vibration(self.vibration))
        object.__setattr__(self, "repeat", _normalize_repeat(self.repeat))
        if self.sound is not None and not str(self.sound).strip():
            object.__setattr__(self, "sound", None)
        if self.sounds is None:
            object.__setattr__(self, "sounds", ())
        elif isinstance(self.sounds, str):
            object.__setattr__(self, "sounds", (self.sounds,))
        else:
            object.__setattr__(self, "sounds", tuple(str(item) for item in self.sounds))
        if self.volume is not None and not 0 <= int(self.volume) <= 100:
            raise AlarmError("alarm.volume muss zwischen 0 und 100 liegen")
        if self.volume is not None:
            object.__setattr__(self, "volume", int(self.volume))
        for name in ("crescendo_seconds", "snooze_minutes", "snooze_limit"):
            if int(getattr(self, name)) < 0:
                raise AlarmError(f"alarm.{name} darf nicht negativ sein")
        if self.pre_notify_minutes is not None and int(self.pre_notify_minutes) < 0:
            raise AlarmError("alarm.pre_notify_minutes darf nicht negativ sein")
        if self.dismiss_math not in ("easy", "medium", "hard"):
            raise AlarmError("alarm.dismiss_math muss easy, medium oder hard sein")
        if self.background is not None and not re.fullmatch(
            r"#[0-9a-fA-F]{6}|black|dark", str(self.background)
        ):
            raise AlarmError("alarm.background muss 'black', 'dark' oder #rrggbb sein")

    @property
    def offset_seconds(self) -> int:
        return int(self.offset.total_seconds())

    def trigger(self, start: datetime | None, end: datetime | None) -> datetime | None:
        """Absolute moment this alarm rings for one event instance."""
        base = end if self.when == "end" else start
        if base is None:
            return None
        return base + self.offset

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation (no datetime, no timedelta)."""
        return {
            "when": self.when,
            "offset_seconds": self.offset_seconds,
            "label": self.label,
            "sound": self.sound,
            "sounds": list(self.sounds),
            "speak": self.speak,
            "speak_text": self.speak_text,
            "volume": self.volume,
            "crescendo": self.crescendo,
            "crescendo_seconds": self.crescendo_seconds,
            "vibrate": self.vibrate,
            "vibration": self.vibration,
            "snooze_minutes": self.snooze_minutes,
            "snooze_limit": self.snooze_limit,
            "dismiss": list(self.dismiss),
            "dismiss_math": self.dismiss_math,
            "full_screen": self.full_screen,
            "pre_notify_minutes": self.pre_notify_minutes,
            "background": self.background,
            "flashlight": self.flashlight,
            "silent_override": self.silent_override,
            "enabled": self.enabled,
            "skip_next": self.skip_next,
            "repeat": list(self.repeat) if self.repeat is not None else None,
        }

    def identify(self, event_key: str = "") -> str:
        """Stable id for this alarm on this event (survives recompilation)."""
        payload = "|".join(
            (
                event_key,
                self.when,
                str(self.offset_seconds),
                self.label or "",
                str(self.speak),
                self.sound or "",
            )
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def alarm(
    when: str = "start",
    *,
    at: str | None = None,
    offset: object = ZERO,
    label: str | None = None,
    sound: str | None = None,
    sounds: Iterable[str] | str = (),
    speak: bool = False,
    speak_text: str | None = None,
    volume: int | None = None,
    crescendo: bool = True,
    crescendo_seconds: int = 30,
    vibrate: bool = True,
    vibration: object = "default",
    snooze_minutes: int = 5,
    snooze_limit: int = 3,
    dismiss: object = ("button",),
    dismiss_math: str = "medium",
    full_screen: bool = True,
    pre_notify_minutes: int | None = None,
    background: str | None = None,
    flashlight: bool = False,
    silent_override: bool = True,
    enabled: bool = True,
    skip_next: bool = False,
    repeat: object = None,
) -> Alarm:
    """Build an :class:`Alarm`.  ``at`` is an alias for ``when``."""
    return Alarm(
        when=at or when,
        offset=offset,
        label=label,
        sound=sound,
        sounds=tuple(sounds) if not isinstance(sounds, str) else (sounds,),
        speak=speak,
        speak_text=speak_text,
        volume=volume,
        crescendo=crescendo,
        crescendo_seconds=crescendo_seconds,
        vibrate=vibrate,
        vibration=vibration,
        snooze_minutes=snooze_minutes,
        snooze_limit=snooze_limit,
        dismiss=dismiss,
        dismiss_math=dismiss_math,
        full_screen=full_screen,
        pre_notify_minutes=pre_notify_minutes,
        background=background,
        flashlight=flashlight,
        silent_override=silent_override,
        enabled=enabled,
        skip_next=skip_next,
        repeat=repeat,
    )


_RESERVED_DICT_KEYS = frozenset(
    {
        "id",
        "event_id",
        "event_name",
        "trigger",
        "pre_trigger",
        "alarm_ids",
        "event",
        "title",
        "name",
    }
)

_ALIASES = {
    "at": "when",
    "for": "label",
    "for_": "label",
    "ringtone": "sound",
    "speak_as": "speak_text",
    "snooze": "snooze_minutes",
    "max_snooze": "snooze_limit",
    "background_color": "background",
    "dismiss_challenges": "dismiss",
    "math": "dismiss_math",
}


def _from_dict(values: dict[str, Any]) -> Alarm:
    data = {}
    for key, value in values.items():
        if key in (_RESERVED_DICT_KEYS):
            continue
        if key in ("offset_seconds", "offset_minutes"):
            seconds = float(value) * (60 if key == "offset_minutes" else 1)
            data["offset"] = timedelta(seconds=seconds)
            continue
        data[_ALIASES.get(key, key)] = value
    unknown = set(data) - set(Alarm.__dataclass_fields__)
    if unknown:
        raise AlarmError(f"unbekannte alarm-Option(en): {', '.join(sorted(unknown))}")
    return Alarm(**data)


def alarm_from_dict(values: dict[str, Any]) -> Alarm:
    """Rebuild an :class:`Alarm` from ``Alarm.to_dict()`` (or a shorthand)."""
    return _from_dict(dict(values))


def coerce_alarm(value: object) -> tuple[Alarm, ...] | None:
    """Normalise one ``alarm=`` value.

    Returns ``None`` for an explicit opt-out (``alarm=False``), otherwise the
    tuple of alarms.  ``alarm=True`` means "the default alarm", strings may be
    ``"start"``, ``"end"``, ``"start-10m"`` or just an offset.
    """
    if value is None:
        return ()
    if value is False:
        return None
    if value is True:
        return (Alarm(),)
    if isinstance(value, Alarm):
        return (value,)
    if isinstance(value, dict):
        return (_from_dict(value),)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("", "none", "off", "no", "false", "silent"):
            return None
        if text in ("on", "yes", "true", "start", "event", "begin"):
            return (Alarm(),)
        if text in ("end", "finish", "after"):
            return (Alarm(when="end"),)
        match = re.fullmatch(r"(start|end)([+-].+)", text)
        if match:
            return (Alarm(when=match.group(1), offset=parse_offset(match.group(2))),)
        return (Alarm(offset=parse_offset(text)),)
    if isinstance(value, (int, float, timedelta)):
        return (Alarm(offset=value),)
    if isinstance(value, Iterable):
        result: list[Alarm] = []
        for item in value:
            parsed = coerce_alarm(item)
            if parsed is None:
                return None
            result.extend(parsed)
        return tuple(result)
    raise AlarmError(f"alarm= kann {value!r} nicht lesen")


def _plain(text: str) -> str:
    """Event name without icons/punctuation, lower-cased, for matching."""
    cleaned = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]", " ", text)
    cleaned = cleaned.replace("_", " ").lower()
    return re.sub(r"[^a-z0-9]+", " ", cleaned)


def is_wake_name(name: str, keywords: Iterable[str] = WAKE_KEYWORDS) -> bool:
    plain = _plain(name)
    return any(keyword in plain for keyword in keywords)


def _spoken_name(name: str) -> str:
    """A short, speakable label: ``Fajr (Moschee)`` -> ``Fajr``."""
    cleaned = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]", "", name)
    cleaned = re.split(r"\s+[\(\[]", cleaned, maxsplit=1)[0]
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -–—:")
    return cleaned or name.strip()


@dataclass(frozen=True, slots=True)
class WakeAlarmPolicy:
    """Automatic alarms for night wake-up events.

    * Fajr, Tahajjud, Suhoor/Sahur, Imsak and Qiyam ring at their start.
    * Only events in the night window (21:00-12:00) qualify, so a "Fajr"
      event at 19:00 in an unusual plan is not mistaken for a morning alarm.
    * Back-to-back wake events share one alarm: Tahajjud -> Witr -> Suhoor ->
      Fajr rings once, at the first event.  A real break (a non-night event,
      or more than ``chain_gap_minutes`` of silence) starts a new alarm.
    """

    wake_keywords: tuple[str, ...] = WAKE_KEYWORDS
    chain_keywords: tuple[str, ...] = CHAIN_KEYWORDS
    #: Template for automatically created alarms.
    template: Alarm = field(default_factory=lambda: Alarm(speak=True))
    chain_gap_minutes: int = 30
    #: Wake events only qualify between 21:00 and noon; a "Fajr" event at
    #: 19:00 in a test plan is not a night wake-up.
    night_window: tuple[int, int] = (21, 12)

    def in_night_window(self, moment: datetime) -> bool:
        start_hour, end_hour = self.night_window
        hour = moment.hour
        return hour >= start_hour or hour < end_hour

    def matches_wake(self, name: str) -> bool:
        return is_wake_name(name, self.wake_keywords)

    def matches_chain(self, name: str) -> bool:
        return is_wake_name(name, self.chain_keywords)

    def apply(self, events: Iterable[Any]) -> list[str]:
        """Attach alarms to qualifying events; returns the alarmed names."""
        gap = timedelta(minutes=self.chain_gap_minutes)
        ordered = sorted(
            (event for event in events if getattr(event, "active", False)),
            key=lambda event: event.start,
        )
        last_wake_end: datetime | None = None
        alarmed: list[str] = []
        for event in ordered:
            name = getattr(event, "name", "")
            if not self.matches_chain(name):
                last_wake_end = None
                continue
            if not self.matches_wake(name):
                # Witr sits inside a chain but never starts one itself.
                continue
            if not self.in_night_window(event.start):
                last_wake_end = None
                continue
            if getattr(event, "alarm_opt_out", False):
                last_wake_end = event.end
                continue
            if getattr(event, "alarms", ()):
                last_wake_end = event.end
                continue
            end = event.end or event.start
            if last_wake_end is not None and event.start - last_wake_end <= gap:
                last_wake_end = end
                continue
            template = self.template
            event.alarms = (
                replace(
                    template,
                    label=template.label or _spoken_name(name),
                    speak_text=template.speak_text
                    or (_spoken_name(name) if template.speak else None),
                ),
            )
            alarmed.append(name)
            last_wake_end = end
        return alarmed


@dataclass(slots=True)
class AlarmSettings:
    """Planfile switches for automatic event alarms.

    In a planfile::

        alarms = True                       # wake-up policy on (default)
        alarms = False                      # no automatic alarms at all
        alarms = {"chain_gap_minutes": 45}  # longer night chain
        alarm_policy = WakeAlarmPolicy(template=alarm(speak=True, sound="adhan"))

    Explicit ``task(..., alarm=...)`` specs always win; ``alarm=False``
    silences one event without disabling the policy.
    """

    enabled: bool = True
    policy: Any | None = None
    chain_gap_minutes: int = 30

    def resolved_policy(self) -> WakeAlarmPolicy:
        if self.policy is None:
            return WakeAlarmPolicy(chain_gap_minutes=self.chain_gap_minutes)
        if isinstance(self.policy, WakeAlarmPolicy):
            if self.chain_gap_minutes == 30:
                return self.policy
            return replace(self.policy, chain_gap_minutes=self.chain_gap_minutes)
        if callable(getattr(self.policy, "apply", None)):
            return self.policy
        raise AlarmError(
            "alarm_policy braucht eine WakeAlarmPolicy oder ein Objekt mit apply(events)"
        )


def apply_wake_alarms(events: Iterable[Any], policy: WakeAlarmPolicy) -> list[str]:
    """Convenience wrapper used by the compiler."""
    return policy.apply(events)
