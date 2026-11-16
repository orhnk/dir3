"""Event colors as a trait-like policy, portable across providers.

Munazzim colors prayers fixed and cycles everything else (TUI-only there).
dir3 ports the *idea* to real calendar colors: a :class:`ColorPolicy` decides
*which* color family an event gets (as a neutral slot ``0..10``), each
provider renders the slot its own way (GCal: ``colorId`` ``"1".."11"``).

Rules (munazzim-inspired): the default policy keeps prayers yellow; the
optional status policy colors prayers at the Adhan green, shifted prayers
yellow, prayers that take lecture time orange, and critical prayers red.
Every other event gets a deterministic color from its name - same name, same
color.

Implement the trait for custom behavior - any object with
``color_for(name, index) -> int | None`` works, no inheritance needed::

    class MyColors:
        def color_for(self, name, index):
            return 10 if "sleep" in name.lower() else None
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class GCalColor(str, Enum):
    """Google Calendar's fixed color names and ``colorId`` values (``1``-``11``)."""

    LAVENDER = "1"
    SAGE = "2"
    GRAPE = "3"
    FLAMINGO = "4"
    BANANA = "5"
    TANGERINE = "6"
    PEACOCK = "7"
    GRAPHITE = "8"
    BLUEBERRY = "9"
    BASIL = "10"
    TOMATO = "11"


@runtime_checkable
class ColorPolicy(Protocol):
    """Trait: maps an event to a dir3 slot, a :class:`GCalColor`, or ``None``."""

    def color_for(self, name: str, index: int) -> int | GCalColor | None:
        """Color for the event with this name at this (per-day) position."""
        ...  # pragma: no cover - trait


#: Slot -> GCal ``colorId``. The slot order is dir3's stable hash order, not
#: GCal's numeric order; use :class:`GCalColor` for the fixed GCal names.
PALETTE = (
    GCalColor.GRAPE.value,
    GCalColor.TANGERINE.value,
    GCalColor.BANANA.value,
    GCalColor.PEACOCK.value,
    GCalColor.TOMATO.value,
    GCalColor.BLUEBERRY.value,
    GCalColor.LAVENDER.value,
    GCalColor.SAGE.value,
    GCalColor.FLAMINGO.value,
    GCalColor.GRAPHITE.value,
    GCalColor.BASIL.value,
)

#: Normalized prayer names - always rendered yellow (GCal Banana).
# lange Gebetsnamen -> kurze, informative Varianten für die Anzeige
SHORT_PRAYER_NAMES: dict[str, str] = {
    "fajr": "Fajr",
    "sunrise": "Sonnenaufgang",
    "dhuhr": "Dhuhr",
    "duhr": "Dhuhr",
    "jumuah": "Jumuah",
    "tahajjud": "Tahajjud",
    "tarawih": "Tarawih",
    "asr": "Asr",
    "maghrib": "Maghrib",
    "isha": "Isha",
    "sunset": "Sonnenuntergang",
}

PRAYER_NAMES = frozenset(
    {
        "fajr",
        "sunrise",
        "dhuhr",
        "duhr",
        "jumuah",
        "asr",
        "maghrib",
        "isha",
        "tahajjud",
        "tarawih",
    }
)

#: Slot rendering as yellow (GCal Banana ``"5"``) on every provider.
YELLOW_SLOT = 2

#: Slot rendering as green (GCal Sage ``"2"``) on every provider.
GREEN_SLOT = 7

#: Slot rendering as red (GCal Tomato ``"11"``) on every provider.
RED_SLOT = 4

#: Slot rendering as orange (GCal Tangerine ``"6"``) on every provider.
ORANGE_SLOT = 1

#: Markers a plan can put into a prayer name to describe its schedule state.
SHIFTED_MARKER = "verschoben"
CRITICAL_MARKER = "kritisch"
KERAHAT_MARKER = "kerahat"
ORANGE_MARKER = "von der vorlesung"

#: Prayer-status palette. The slot numbers are stable; ``PALETTE`` renders them
#: as GCal colors. The names are the semantic colors a plan can rely on:
BASIL_SLOT = 10  #: Am Adhan in der Moschee - GCal Basil ("10", green)
PISTACHIO_SLOT = GREEN_SLOT  #: Verschoben in der Moschee - Sage ("2")
AVOCADO_SLOT = 3  #: Am Adhan allein - Peacock ("7", dark green)
LEMON_SLOT = YELLOW_SLOT  #: Verschoben allein - Banana ("5", yellow)
MANDARIN_SLOT = ORANGE_SLOT  #: Orange slot for custom policies - Tangerine ("6")
MANGO_SLOT = ORANGE_SLOT  #: Eyyam-ı Biyd - Tangerine ("6", mango-orange)
TOMATO_SLOT = RED_SLOT  #: Dringend (kritisch/Kerahat) - Tomato ("11", red)
FLAMINGO_SLOT = 8  #: Allein gebetet - GCal Flamingo ("4", rot-pink)

#: Marks a lecture / exercise / seminar by keyword ...
_LECTURE_RE = re.compile(
    r"\b(?:übung|uebung|exercise|exercises|lab|labs|lecture|lectures|"
    r"seminar|seminare|vorlesung|vorlesungen|selbstlernen|tutorium)\b",
    re.IGNORECASE,
)
#: ... or by a course/room code such as ``HE101``, ``EN732`` or ``E-N732``.
_COURSE_CODE_RE = re.compile(r"\b[A-Z]{1,4}[-‐]?[A-Z]?\d{2,4}\b")
#: Travel / commute names, including the route arrow.
_TRAVEL_RE = re.compile(
    r"\b(?:weg|travel|trip|journey|fahrt|commute)\b|>>|->|→", re.IGNORECASE
)

_DEFAULT_PRAYER_ICON = "🕋"
_DEFAULT_MOSQUE_ICON = "🕌"
_DEFAULT_ALONE_ICON = "🧍‍♂️"
_DEFAULT_LECTURE_ICON = "🏫"
_DEFAULT_TRAVEL_ICON = "🛣️"
_DEFAULT_FOOD_ICON = "🍽️"
_DEFAULT_SLEEP_ICON = "🌙"
_DEFAULT_COOKING_ICON = "🍳"
_DEFAULT_NETWORK_ICON = "🕸️"
_DEFAULT_CLEANUP_ICON = "🧹"

_SPACE_RE = re.compile(r"[ \t]+")
_COMPACT_CODE_RE = re.compile(r"\b([A-Z]{1,4})\s+(\d{2,4})\b")
_TIME_ARROW_RE = re.compile(r"(\d{1,2}:\d{2})\s*(?:→|->)\s*(\d{1,2}:\d{2})")
_SHIFTED_PREFIX_RE = re.compile(r"verschoben:\s*Adhan\s+", re.IGNORECASE)
_ADHAN_SUFFIX_RE = re.compile(r"-Adhan\b", re.IGNORECASE)
_ABBREVIATION_RE = re.compile(
    r"\b(Uebung|Übung|Vorlesung|Vorlesungen|Seminar|Seminare|Exercises?|Labs?)\b",
    re.IGNORECASE,
)
_ABBREVIATIONS = {
    "uebung": "Ü",
    "übung": "Ü",
    "vorlesung": "V",
    "vorlesungen": "V",
    "seminar": "S",
    "seminare": "S",
    "exercise": "Ex",
    "exercises": "Ex",
    "lab": "Lab",
    "labs": "Lab",
}


def shorten_event_name(name: str | None) -> str:
    """Kürzt Event-Namen, ohne Information zu entfernen.

    Regeln (nur Kompaktierung, keine Inhalte werden gestrichen):

    * Leerraum normalisieren;
    * Kurs-/Raumcodes kompaktieren: ``EN 732`` → ``EN732``;
    * Zeitangaben kompaktieren: ``14:14 → 15:48`` → ``14:14→15:48``;
    * in Statusklammern das redundante Wort ``Adhan`` weglassen
      (``verschoben: Adhan 14:14 → 15:48`` → ``verschoben 14:14→15:48``);
    * Vorlesungsarten abkürzen: ``Uebung`` → ``Ü``, ``Vorlesung`` → ``V``,
      ``Seminar`` → ``S``, ``Exercises`` → ``Ex``;
    * den redundanten Zusatz ``-Adhan`` in ``Isha-Adhan`` entfernen.

    Adhan-Zeiten, Verschiebungen, Kerahat/Kritisch-Status, Moschee/allein,
    Farz-Info und Kursnamen bleiben vollständig erhalten.
    """
    if not name:
        return ""

    text = _SPACE_RE.sub(" ", str(name).strip())
    text = _COMPACT_CODE_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}", text)
    text = _TIME_ARROW_RE.sub(r"\1→\2", text)
    text = _SHIFTED_PREFIX_RE.sub("verschoben ", text)
    text = _ADHAN_SUFFIX_RE.sub("", text)
    text = _ABBREVIATION_RE.sub(lambda match: _ABBREVIATIONS[match.group(0).lower()], text)
    return text


_MODE_WORDS = frozenset({"moschee", "allein"})
_PAREN_RE = re.compile(r"\s*\(([^()]*)\)")


def _without_mode_words(text: str) -> str:
    """Entfernt Moschee/allein aus Klammern, wenn ein Modus-Icon sie ersetzt."""

    def repl(match: re.Match) -> str:
        parts = [part.strip() for part in match.group(1).split(",")]
        kept = [part for part in parts if part.casefold() not in _MODE_WORDS]
        return f" ({', '.join(kept)})" if kept else ""

    return _PAREN_RE.sub(repl, text)


def event_summary(name: str | None, icon_policy: object | None = None, index: int = 0) -> str:
    """Event-Name mit Icon und gekürztem Text für die Anzeige.

    Kombiniert:
    - :func:`shorten_event_name` für die Namensverkürzung
    - :meth:`icon_policy.icon_for` für das Icon (wenn vorhanden)

    Rückgabe: ``"🕋 Fajr"`` oder ``"🏫 EN732 ROBS (Ü)"`` etc.
    """
    if not name:
        return ""

    short = shorten_event_name(name)
    icon = ""
    if icon_policy is not None:
        icon_fn = getattr(icon_policy, "icon_for", None)
        if callable(icon_fn):
            icon = icon_fn(name, index) or ""

    if icon:
        mode_icons = {getattr(icon_policy, "mosque", None), getattr(icon_policy, "alone", None)}
        if icon in mode_icons:
            short = _without_mode_words(short)
        return f"{icon} {short}"
    return short


def normalize_event_name(name: object) -> str:
    return str(name or "").strip().casefold()


def name_slot(name: object) -> int:
    """Deterministic color slot from the event name.

    The name's bytes are summed as numbers, modulo the palette length -
    so the same name always yields the same slot on every provider::

        sum(b"coding") % 11 == 1
    """
    total = sum(normalize_event_name(name).encode("utf-8"))
    return total % len(PALETTE)


def to_gcal_color_id(slot: object) -> str | None:
    """Render a policy color as a GCal ``colorId`` (``None`` = default)."""
    if isinstance(slot, GCalColor):
        return slot.value
    try:
        index = int(slot)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if isinstance(slot, bool) or not 0 <= index <= 10:
        return None
    return PALETTE[index]


def _slot_from_color_id(value: object) -> int | None:
    """GCal ``colorId`` (``1``..``11``) or name -> palette slot."""
    if isinstance(value, GCalColor):
        return PALETTE.index(value.value)
    if isinstance(value, bool):
        return None
    try:
        text = str(int(str(value).strip()))
    except (TypeError, ValueError):
        if isinstance(value, str):
            member = GCalColor.__members__.get(value.strip().upper())
            if member is not None:
                return PALETTE.index(member.value)
        return None
    try:
        return PALETTE.index(text)
    except ValueError:
        return None


@dataclass
class PrayerColorPolicy:
    """Default trait impl: prayers yellow, everything else name-hashed."""

    def color_for(self, name: str, index: int) -> int | None:
        if normalize_event_name(name) in PRAYER_NAMES:
            return YELLOW_SLOT
        return name_slot(name)


@runtime_checkable
class IconPolicy(Protocol):
    """Trait: prefixes an event summary with one glyph.

    Icons are orthogonal to colors: :class:`ColorPolicy` picks the calendar
    fill, an :class:`IconPolicy` picks the inline marker that rendered output
    and calendar titles carry. Implement the trait for custom behavior - any
    object with ``icon_for(name, index) -> str`` works, no inheritance needed::

        class MyIcons:
            def icon_for(self, name, index):
                return "📚" if "lecture" in name.lower() else ""

    Use :func:`icon_policy_chain` to layer custom icons over the defaults.
    """

    def icon_for(self, name: str, index: int) -> str:
        """Icon marker for this event (empty string = no icon)."""
        ...  # pragma: no cover - trait


@dataclass
class DefaultIconPolicy:
    """Bundled icons for the common event kinds.

    ==========================  ==========
    Event                       Icon
    ==========================  ==========
    Gebet                       ``🕋``
    Gebet in der Moschee        ``🕌``
    Gebet allein                ``🧍‍♂️``
    Vorlesung/Übung             ``🏫``
    Weg                         ``🛣️``
    Mahlzeit                    ``🍽️``
    Schlafen                    ``🌙``
    Kochen                      ``🍳``
    Netzwerken                  ``🕸️``
    Aufräumen                   ``🧹``
    ==========================  ==========

    Marker lassen sich pro Planfile überschreiben::

        icon_policy = DefaultIconPolicy(lectures="📚", mosque="🏛️")

    ``index`` is the per-day position of the event, so a custom policy can
    vary the marker by position; the bundled policy is name-driven.
    """

    prayers: str = _DEFAULT_PRAYER_ICON
    lectures: str = _DEFAULT_LECTURE_ICON
    travel: str = _DEFAULT_TRAVEL_ICON
    food: str = _DEFAULT_FOOD_ICON
    mosque: str = _DEFAULT_MOSQUE_ICON
    alone: str = _DEFAULT_ALONE_ICON
    sleep: str = _DEFAULT_SLEEP_ICON
    cooking: str = _DEFAULT_COOKING_ICON
    networking: str = _DEFAULT_NETWORK_ICON
    cleanup: str = _DEFAULT_CLEANUP_ICON

    def icon_for(self, name: str, index: int) -> str:
        normalized = normalize_event_name(name)
        head = normalized.partition(" ")[0]
        if head in PRAYER_NAMES:
            if head == "jumuah" or "moschee" in normalized:
                return self.mosque
            if "allein" in normalized:
                return self.alone
            return self.prayers
        # Travel before lectures: route names may contain room/course codes.
        if _TRAVEL_RE.search(normalized):
            return self.travel
        if (
            normalized.startswith(
                (
                    "suhoor",
                    "iftar",
                    "frühstück",
                    "fruehstueck",
                    "abendessen",
                    "abendsessen",
                )
            )
            or "🌕" in normalized
            or "eyyam" in normalized
            or "ayyam" in normalized
        ):
            return self.food
        if normalized.startswith(("schlaf", "mittagsschlaf")):
            return self.sleep
        if normalized.startswith("kochen"):
            return self.cooking
        if normalized.startswith(("netzwerken", "networking")):
            return self.networking
        if normalized.startswith(("aufräum", "aufraeum")):
            return self.cleanup
        if _LECTURE_RE.search(normalized) or _COURSE_CODE_RE.search(str(name or "")):
            return self.lectures
        return ""


def icon_policy_chain(*policies: object) -> object:
    """Chain several icon policies: the first non-empty marker wins.

    Convenience for layering custom icons on top of the default policy
    without losing the dir3 defaults.  Returns an object with
    ``icon_for(name, index) -> str``; implement the whole trait yourself
    when you need control.
    """

    class _Chain:
        def __init__(self, chain):
            self._chain = chain
            for attr in ("mosque", "alone"):
                for policy in chain:
                    value = getattr(policy, attr, None)
                    if value:
                        setattr(self, attr, value)
                        break

        def icon_for(self, name: str, index: int) -> str:
            for policy in self._chain:
                candidate = getattr(policy, "icon_for", None)
                if callable(candidate):
                    marker = candidate(name, index)
                    if marker:
                        return marker
            return ""

    return _Chain(list(policies))


@dataclass
class PrayerStatusColorPolicy:
    """Prayers change color with their schedule state.

    ``critical`` and ``kerahat`` names are red, names that take time from a
    lecture are orange, exact Adhan-time prayers are green, and ``shifted``
    names are yellow. Everything else falls back to
    :class:`PrayerColorPolicy`.

    A planfile opts in with ``color_policy = PrayerStatusColorPolicy()`` and
    names its prayer events accordingly (e.g. ``Asr (verschoben: …)``,
    ``Maghrib (5 min von der Vorlesung)`` or
    ``Isha (kritisch, noch 20 min bis Fajr-Adhan)``).
    """

    fallback: ColorPolicy = field(default_factory=PrayerColorPolicy)

    def color_for(self, name: str, index: int) -> int | None:
        normalized = normalize_event_name(name)
        head, _, rest = normalized.partition(" ")
        if head in PRAYER_NAMES and (not rest.strip() or rest.lstrip().startswith("(")):
            if CRITICAL_MARKER in normalized or KERAHAT_MARKER in normalized:
                return RED_SLOT
            if ORANGE_MARKER in normalized:
                return ORANGE_SLOT
            if SHIFTED_MARKER in normalized:
                return YELLOW_SLOT
            return GREEN_SLOT
        return self.fallback.color_for(name, index)


@dataclass
class BasilPistazienColorPolicy:
    """Prayer-status colors in the user's chosen palette:

    ==========================  =============  ==============
    Zustand                     Farbe          GCal colorId
    ==========================  =============  ==============
    Am Adhan in der Moschee     Basilikum      ``10`` Basil
    Verschoben in der Moschee   Pistazie       ``2`` Sage
    Allein                      Flamingo       ``4`` Flamingo
    Dringend (Kritisch/Kerahat) Tomate         ``11`` Tomato
    ==========================  =============  ==============

    Jumuah zählt als Moschee-Gebet (der Weg dorthin steht im Plan). Die
    Status-Marker stehen im Event-Namen, z. B.
    ``"Asr (Moschee, verschoben: Adhan 14:14 → 15:48)"``.
    Alles, was kein Gebet ist, fällt auf den Namen-Hash zurück.
    """

    fallback: ColorPolicy = field(default_factory=PrayerColorPolicy)

    def color_for(self, name: str, index: int) -> int | None:
        normalized = normalize_event_name(name)
        head = normalized.partition(" ")[0]
        if head not in PRAYER_NAMES:
            return self.fallback.color_for(name, index)

        # Dringende Gebete (Kritisch/Kerahat) überstimmen Moschee/allein
        # und "verschoben".
        if CRITICAL_MARKER in normalized or KERAHAT_MARKER in normalized:
            return TOMATO_SLOT

        in_mosque = "moschee" in normalized or head == "jumuah"
        shifted = SHIFTED_MARKER in normalized
        if in_mosque:
            return PISTACHIO_SLOT if shifted else BASIL_SLOT
        return FLAMINGO_SLOT


@dataclass
class PlainPolicy:
    """Trait impl: no colors, everything keeps the calendar default."""

    def color_for(self, name: str, index: int) -> int | None:
        return None


@dataclass
class DictColorPolicy:
    """Trait impl: explicit ``{event name: colorId}`` mapping + fallback policy.

    Mapping values are GCal colorIds (``1``..``11`` as int or str),
    :class:`GCalColor` members or fixed names such as ``"Basil"``; invalid
    values are ignored and fall through to the fallback.
    """

    mapping: dict = field(default_factory=dict)
    fallback: ColorPolicy = field(default_factory=PrayerColorPolicy)

    def __post_init__(self) -> None:
        self.slots: dict[str, int] = {}
        for name, value in (self.mapping or {}).items():
            slot = _slot_from_color_id(value)
            if slot is not None:
                self.slots[normalize_event_name(name)] = slot

    def color_for(self, name: str, index: int) -> int | None:
        slot = self.slots.get(normalize_event_name(name))
        if slot is not None:
            return slot
        return self.fallback.color_for(name, index)
