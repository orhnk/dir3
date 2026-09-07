"""Autopilot-Tag: liest Daten und plant sich selbst.

Dir3 ist hier dein Assistenzsystem. Der Tag kennt:

* dein Wetter-Block (ein Dict)      -> draussen oder drinnen;
* dein Energie-Log                  -> kurze oder lange Deep-Work-Session;
* die Oeffnungszeiten deines Gym    -> der Sport startet, wenn es aufsperrt;
* deine Projekt-Deadlines           -> tauchen automatisch als Countdown auf.

Aendere einen einzigen Wert weiter unten und der ganze Tag reagiert.
"""
from datetime import date, time

from dir3 import anchor, day, task

# --- Standort (dein Ort, hier im Planfile) ----------------------------------
# lat, lon, IANA-Zeitzone. Ohne diese Zeile bestimmt dir3 ihn per Geolocation.
location = (40.7992, 29.4305, "Europe/Istanbul")

# --- deine Daten (aendere einfach die Werte) -------------------------------
# Wetter pro Tag ("regen"/"sonnig"); unbekannte Tage gelten als "sonnig".
WETTER = {
    "2026-09-21": "regen",
    "2026-09-22": "regen",
    "2026-09-23": "sonnig",
}

# Energie-Log pro Tag des Monats (1=eher leer ... 3=voll). Fehlt ein Tag -> 3.
ENERGIE = {9: 1, 10: 2}

# Oeffnungszeiten des Gym pro Wochentag (Python: Montag=0 ... Sonntag=6).
GYM_ZEITEN = {
    0: (6, 22), 1: (6, 22), 2: (6, 22), 3: (6, 22), 4: (6, 22),
    5: (8, 14), 6: (8, 16),
}

# Projekt-Deadlines; der Plan zeigt automatisch den Countdown.
DEADLINES = [
    ("2026-09-25", "Thesis Kapitel 3"),
    ("2026-10-02", "Foliensatz Praesi"),
]


def regnet(ctx) -> bool:
    return WETTER.get(ctx.date.isoformat(), "sonnig") == "regen"


def energie_leer(ctx) -> bool:
    return ENERGIE.get(ctx.date.day, 3) <= 1


def gym_offen_um_sechs(ctx) -> bool:
    auf, zu = GYM_ZEITEN[ctx.date.weekday()]
    return auf <= 6 < zu


@anchor
def gym_oeffnet(ctx):
    """Eigenes Anker: das Gym öffnet (datengetrieben)."""
    hour = GYM_ZEITEN[ctx.date.weekday()][0]
    return time(hour, 0)


def _deadline_tasks(ctx):
    """Nahende Fristen tauchen einfach im Tagesplan auf."""
    nahende = []
    for iso, name in DEADLINES:
        rest = (date.fromisoformat(iso) - ctx.date).days
        if 0 <= rest <= 3:
            label = "HEUTE faellig" if rest == 0 else f"noch {rest} Tage"
            nahende.append(task(f"[Frist] {name} ({label})", duration="1h", flex=True))
    return nahende


@day(name="Autopilot-Tag")
def autopilot(ctx):
    lots = [
        # Der Sport startet, sobald dein Studio wirklich offen ist.
        task(
            "Fitness im Studio",
            start=gym_oeffnet,
            duration="45m",
            flex=True,
            unless=(lambda ctx: not gym_offen_um_sechs(ctx)),
        ),
        task("Morgenroutine & Duschen", start=time(6, 45), duration="45m"),
        # Deep Work skaliert mit deiner Energie von heute.
        task(
            "Deep Work",
            start=time(8, 0),
            duration="1h" if energie_leer(ctx) else "3h",
            flex=True,
        ),
        task("Pause & Herzlich", duration="15m", flex=False),
        task("Post & Kram", duration="45m", flex=True),
        task("Mittag", start=time(12, 30), duration="45m"),
    ]
    # Das Wetter entscheidet zwischen draußen und drinnen.
    if regnet(ctx):
        lots.append(task("Drinnen: Bücher & Tee", start=time(19, 0), duration="1h"))
    else:
        lots.append(task("Draußen: Radrunde", start=time(19, 0), duration="1h"))
    lots.extend(_deadline_tasks(ctx))
    return lots


def make_plan():
    from dir3 import week as _week

    return _week(mon=autopilot, tue=autopilot, wed=autopilot, thu=autopilot,
                 fri=autopilot, sat=autopilot, sun=autopilot)


__title__ = "Autopilot: Dein Tag kennt deine Daten"
