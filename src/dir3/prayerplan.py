"""Generic prayer-slot planner.

The planner takes prayer times and a day's lecture blocks, places every prayer
at (or as close as possible to) its Adhan, chooses mosque vs. alone, marks
shifted/critical/kerahat states, and returns the lecture breaks needed to fit.
All policy values live in :class:`PrayerPlanSettings`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from .intervals import gap_around, overlap, shift, subtract_blocks
from .timeutils import to_minutes

Block = tuple[int, int, str]
Slot = tuple[str, int, int]
MinuteBlock = tuple[int, int]


@dataclass(frozen=True, slots=True)
class FixedPrayer:
    """A prayer with a fixed block relative to a schedule anchor."""

    anchor: str
    lead: int
    duration: int
    title: str


@dataclass(frozen=True, slots=True)
class PrayerPlanSettings:
    """Policy knobs for :class:`PrayerPlanner`.

    Timing model: the Adhan is the anchor. Wudu and the prayer happen **after**
    the Adhan, so a prayer event's block includes wudu after it. Mosque travel
    happens before the Adhan and ends exactly at it, so a mosque prayer starts
    ``mosque_travel`` minutes before the Adhan (0 in free time) and
    ``mosque_travel_after_lecture`` minutes before when coming from a lecture.
    """

    wudu: int = 3
    min_per_rakat: int = 4
    full_rakats: Mapping[str, int] = field(
        default_factory=lambda: {
            "Fajr": 4,
            "Dhuhr": 10,
            "Asr": 8,
            "Maghrib": 5,
            "Isha": 13,
        }
    )
    fardh_rakats: Mapping[str, int] = field(
        default_factory=lambda: {
            "Fajr": 2,
            "Dhuhr": 4,
            "Asr": 4,
            "Maghrib": 3,
            "Isha": 4,
        }
    )
    mosque_travel: int = 10
    mosque_travel_after_lecture: int | None = None
    #: Minutes before an Adhan inspected to decide whether an event still
    #: occupies the person (no leisure) or the time is free.
    leisure_window: int = 15
    mosque_window: int = 30
    miss_buffer: int = 30
    start_buffer: int = 30
    kerahat_buffer: int = 45
    buffer_overrides: Mapping[str, int] = field(default_factory=dict)
    order: tuple[str, ...] = ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")
    azan_attr: Mapping[str, str] = field(
        default_factory=lambda: {
            "Fajr": "fajr",
            "Dhuhr": "dhuhr",
            "Asr": "asr",
            "Maghrib": "maghrib",
            "Isha": "isha",
        }
    )
    next_attr: Mapping[str, str] = field(
        default_factory=lambda: {
            "Fajr": "sunrise",
            "Dhuhr": "asr",
            "Asr": "maghrib",
            "Maghrib": "isha",
        }
    )
    deadline_label: Mapping[str, str] = field(
        default_factory=lambda: {
            "Fajr": "Sonnenaufgang",
            "Dhuhr": "Asr-Adhan",
            "Asr": "Maghrib-Adhan",
            "Maghrib": "Isha-Adhan",
            "Isha": "Fajr-Adhan",
        }
    )
    fixed_prayers: Mapping[str, FixedPrayer] = field(default_factory=dict)
    skip_weekday_prayers: Mapping[int, frozenset[str]] = field(default_factory=dict)
    #: Prayer -> weekdays on which it is prayed alone (never in the mosque).
    alone_prayers: Mapping[str, frozenset[int]] = field(default_factory=dict)
    not_before: Mapping[tuple[int, str], int] = field(default_factory=dict)
    lecture_end_buffer: int = 15
    lecture_start_grace: int = 5
    prayer_lecture_borrow: int = 5
    short_gap: int = 30


class PrayerPlanner:
    """Place prayers around fixed content using :class:`PrayerPlanSettings`."""

    def __init__(self, settings: PrayerPlanSettings | None = None) -> None:
        self.settings = settings or PrayerPlanSettings()

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _minute(value: int | str) -> int:
        return value if isinstance(value, int) else to_minutes(value)

    def _blocks(self, blocks: Iterable[Block]) -> list[Block]:
        return [(self._minute(start), self._minute(end), label) for start, end, label in blocks]

    def content_blocks(self, lectures: Iterable[Block]) -> list[Block]:
        """Lecture time without the start grace and the free end buffer."""
        return [
            (
                start + self.settings.lecture_start_grace,
                end - self.settings.lecture_end_buffer,
                label,
            )
            for start, end, label in self._blocks(lectures)
        ]

    def display_blocks(self, lectures: Iterable[Block]) -> list[Block]:
        """Displayed lecture blocks (the free end buffer is already removed)."""
        return [
            (start, end - self.settings.lecture_end_buffer, label)
            for start, end, label in self._blocks(lectures)
        ]

    def mosque_travel_for(self, target: int, lectures: Iterable[Block]) -> int:
        """Walking time to the mosque: longer when an event is still running.

        ``lectures`` are display blocks, i.e. their free end buffer is already
        removed.  The ``leisure_window`` minutes before the Adhan are inspected:
        if any block overlaps that window the person is not in leisure time and
        the longer travel applies.  With no event in the window the prayer
        starts directly at the Adhan (leisure).
        """
        settings = self.settings
        after_lecture = settings.mosque_travel_after_lecture
        if after_lecture is None:
            return settings.mosque_travel
        window_start = target - settings.leisure_window
        for start, end, _ in self._blocks(lectures):
            if start < target and end > window_start:
                return after_lecture
        return settings.mosque_travel

    def prayer_duration(
        self,
        name: str,
        *,
        mosque: bool = False,
        fardh: bool = False,
        travel: int | None = None,
    ) -> int:
        settings = self.settings
        lead = (settings.mosque_travel if travel is None else travel) if mosque else 0
        rakats = settings.fardh_rakats if fardh else settings.full_rakats
        return lead + settings.wudu + rakats[name] * settings.min_per_rakat

    def duration(self, name: str) -> int:
        """Full prayer duration at one place (no mosque travel)."""
        return self.prayer_duration(name)

    def lecture_taken(
        self,
        start: int,
        end: int,
        lectures: Iterable[Block],
    ) -> int:
        """Minutes a prayer takes from lectures after the start grace."""
        taken = 0
        for lecture_start, lecture_end, _ in self._blocks(lectures):
            grace_end = lecture_start + self.settings.lecture_start_grace
            content_end = lecture_end - self.settings.lecture_end_buffer
            taken += overlap(start, end, grace_end, content_end)
        return taken

    def azan_times(self, sched: object) -> dict[str, int]:
        settings = self.settings
        times: dict[str, int] = {}
        previous = -1
        for name in settings.order:
            azan = self._minute(getattr(sched, settings.azan_attr[name]))
            while azan <= previous:
                azan += 24 * 60
            times[name] = azan
            previous = azan
        return times

    def deadline_for(self, name: str, sched: object, azan: int) -> int:
        if name == "Isha":
            return self._minute(getattr(sched, "fajr")) + 24 * 60
        deadline = self._minute(getattr(sched, self.settings.next_attr[name]))
        while deadline <= azan:
            deadline += 24 * 60
        return deadline

    def slot_title(
        self,
        name: str,
        azan: int,
        start: int,
        end: int,
        deadline: int,
        taken: int,
        broken: Sequence[str] = (),
        impossible: bool = False,
        prayer_start: int | None = None,
        mode: str | None = None,
        fardh: bool = False,
    ) -> str:
        """Render a slot title; ``prayer_start`` is the actual start after wudu."""
        settings = self.settings
        if prayer_start is None:
            prayer_start = start + settings.wudu
        # Wudu happens after the Adhan, so the Adhan moment is the prayer
        # start minus the wudu time (travel, if any, is before the Adhan).
        adhan_at = prayer_start - settings.wudu
        shifted = adhan_at != azan
        remaining = deadline - end
        preferred = settings.buffer_overrides.get(name, settings.miss_buffer)
        parts: list[str] = []
        if broken or impossible:
            parts.append("⛓️‍💥")
        if mode == "mosque":
            parts.append("Moschee")
        elif mode == "nearby":
            parts.append("allein")
        if fardh:
            parts.append("Farz")
        kerahat = name == "Asr" and remaining < settings.kerahat_buffer
        if kerahat:
            if shifted:
                parts.append("verschoben")
            if remaining < 0:
                available = max(0, deadline - prayer_start)
                parts.append(f"Kerahat, nur {available} min bis {settings.deadline_label[name]}")
            else:
                parts.append(f"Kerahat, noch {remaining} min bis {settings.deadline_label[name]}")
        elif remaining < preferred:
            if shifted:
                parts.append("verschoben")
            if remaining < 0:
                available = max(0, deadline - prayer_start)
                parts.append(f"kritisch, nur {available} min bis {settings.deadline_label[name]}")
            else:
                parts.append(f"kritisch, noch {remaining} min bis {settings.deadline_label[name]}")
        elif shifted:
            parts.append(f"verschoben: Adhan {self._fmt(azan)} → {self._fmt(adhan_at)}")
        if taken > 0:
            parts.append(f"{taken} min von der Vorlesung")
        return name if not parts else f"{name} ({', '.join(parts)})"

    @staticmethod
    def _fmt(minutes: int) -> str:
        minutes %= 24 * 60
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def candidate(
        self,
        name: str,
        target: int,
        deadline: int,
        content: Iterable[MinuteBlock],
        taken: Iterable[MinuteBlock],
        *,
        mosque: bool,
        fardh: bool,
        natural: bool,
        travel: int | None = None,
    ) -> tuple[int, int, int, int] | None:
        settings = self.settings
        lead = (settings.mosque_travel if travel is None else travel) if mosque else 0
        duration = self.prayer_duration(name, mosque=mosque, fardh=fardh, travel=travel)
        # Travel ends exactly at the Adhan; wudu and prayer follow it.
        anchor = target - lead
        start = shift(anchor, taken if natural else [*content, *taken], duration)
        prayer_start = start + lead + settings.wudu
        end = start + duration
        preferred = settings.buffer_overrides.get(name, settings.miss_buffer)
        if end > deadline:
            return None
        if prayer_start > deadline - settings.start_buffer:
            return None
        if mosque and deadline - prayer_start < settings.mosque_window:
            return None
        if not fardh and name == "Asr" and deadline - end < settings.kerahat_buffer:
            return None
        if not fardh and deadline - end < preferred:
            return None
        return start, duration, lead, prayer_start

    def forced_candidate(
        self,
        name: str,
        target: int,
        taken: Iterable[MinuteBlock],
        *,
        fardh: bool = True,
    ) -> tuple[int, int, int, int]:
        settings = self.settings
        duration = self.prayer_duration(name, fardh=fardh)
        # The Adhan starts the block; wudu and prayer follow it.
        start = shift(target, taken, duration)
        return start, duration, 0, start + settings.wudu

    # -- main entry point ------------------------------------------------

    def slots(
        self,
        sched: object,
        day: date,
        *,
        lectures: Iterable[Block] = (),
        display_lectures: Iterable[Block] | None = None,
        extra_taken: Iterable[MinuteBlock] = (),
    ) -> tuple[list[Slot], list[Block]]:
        """Plan all prayers for ``day``; return ``(slots, breaks)``."""
        settings = self.settings
        lectures = self._blocks(lectures)
        content_labeled = self.content_blocks(lectures)
        azans = self.azan_times(sched)
        skipped = settings.skip_weekday_prayers.get(day.weekday(), frozenset())
        # Ein Bruch ist immer allein und nur Farz.
        broken_modes = ((False, True),)
        display_labeled = (
            self._blocks(display_lectures)
            if display_lectures is not None
            else self.display_blocks(lectures)
        )
        display = [(start, end) for start, end, _ in display_labeled]
        slots: list[Slot] = []
        taken = list(extra_taken)
        breaks: list[Block] = []
        for name in settings.order:
            if name in skipped:
                continue
            alone_here = day.weekday() in settings.alone_prayers.get(
                name, frozenset()
            )
            clean_modes = (
                ((False, False), (False, True))
                if alone_here
                else ((True, False), (False, False), (True, True), (False, True))
            )
            fixed = settings.fixed_prayers.get(name)
            if fixed is not None:
                start = self._minute(getattr(sched, fixed.anchor)) - fixed.lead
                end = start + fixed.duration
                slots.append((fixed.title, start, end))
                taken.append((start, end))
                continue
            azan = azans[name]
            target = azan
            floor = settings.not_before.get((day.weekday(), name))
            if floor is not None:
                target = max(target, floor)
            deadline = self.deadline_for(name, sched, azan)
            travel = self.mosque_travel_for(target, display_labeled)
            gap = gap_around(display, azan)
            if gap is not None:
                gap_start, gap_end = gap
            content = [(cs, ce) for cs, ce, _ in content_labeled]
            chosen = None
            modes = None
            broke = False
            for mosque, fardh in clean_modes:
                chosen = self.candidate(
                    name,
                    target,
                    deadline,
                    content,
                    taken,
                    mosque=mosque,
                    fardh=fardh,
                    natural=False,
                    travel=travel,
                )
                if chosen is not None:
                    modes = (mosque, fardh)
                    break
            if chosen is not None and name == "Asr":
                clean_start, clean_duration, _, _ = chosen
                clean_end = clean_start + clean_duration
                # Wartet Asr sonst bis in den Kerahat hinein, lieber die
                # Vorlesung allein und nur Farz unterbrechen - aber nur, wenn
                # der Bruch Kerahat tatsächlich vermeidet und früher liegt.
                if deadline - clean_end < settings.kerahat_buffer:
                    alternative = self.candidate(
                        name,
                        target,
                        deadline,
                        content,
                        taken,
                        mosque=False,
                        fardh=True,
                        natural=True,
                        travel=travel,
                    )
                    if alternative is not None:
                        alt_start, alt_duration, _, _ = alternative
                        alt_end = alt_start + alt_duration
                        breaks_lecture = any(
                            alt_start < content_end and alt_end > content_start
                            for content_start, content_end in content
                        )
                        if (
                            breaks_lecture
                            and alt_start < clean_start
                            and deadline - alt_end >= settings.kerahat_buffer
                        ):
                            chosen = alternative
                            modes = (False, True)
                            broke = True
            if chosen is None:
                for mosque, fardh in broken_modes:
                    chosen = self.candidate(
                        name,
                        target,
                        deadline,
                        content,
                        taken,
                        mosque=mosque,
                        fardh=fardh,
                        natural=True,
                        travel=travel,
                    )
                    if chosen is not None:
                        modes = (mosque, fardh)
                        broke = True
                        break
            impossible = chosen is None
            if chosen is None:
                modes = (False, True)
                chosen = self.forced_candidate(name, target, taken)
            mosque, fardh = modes
            start, duration, lead, prayer_start = chosen
            end = start + duration
            if (
                gap is not None
                and not broke
                and not impossible
                and start > gap_start
                and gap_end - gap_start <= settings.short_gap
                and end <= gap_end + settings.prayer_lecture_borrow
            ):
                start, duration = gap_start, end - gap_start
                chosen = (start, duration, lead, prayer_start)
                end = start + duration
            borrowed = 0
            if not broke and not impossible:
                for lecture_start, lecture_end, label in display_labeled:
                    minutes = overlap(start, end, lecture_start, lecture_end)
                    if minutes > 0:
                        borrowed += minutes
                        breaks.append((max(start, lecture_start), min(end, lecture_end), label))
            broken: list[str] = []
            if broke or impossible:
                broken = [label for cs, ce, label in content_labeled if start < ce and end > cs]
                for label in dict.fromkeys(broken):
                    breaks.append((start, end, label))
                content_labeled = subtract_blocks(content_labeled, start, end)
            taken.append((start, end))
            slots.append(
                (
                    self.slot_title(
                        name,
                        azan,
                        start,
                        end,
                        deadline,
                        borrowed,
                        broken,
                        impossible,
                        prayer_start=prayer_start,
                        mode="mosque" if mosque else "nearby",
                        fardh=fardh,
                    ),
                    start,
                    end,
                )
            )
        return slots, breaks
