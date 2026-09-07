"""Schlafen bis zum naechsten Event - sogar im naechsten Tag.

``until=next_event`` ist der weichste Anker der Welt: Der Schlaf-Task läuft
genau bis zum ersten Event des naechsten A*k*tiven* Tages und endet mitten in
das, was als Naechstes kommt - freie Tage werden uebersprungen. Kein Wecker,
keine feste Zeit: Der Plan selbst sagt dir, wann morgen wieder Leben ist.

    Schlafen     23:00 – 06:00   (läuft ins Folgetag)

Haengt das erste Event von morgen an einem Anker (z. B. ``prayer.fajr``),
wird der Schlaf je nach Jahreszeit mit der Sonne kuerzer oder laenger -
der eine Endpunkt ist nie die Uhr, sondern "das nächste Leben".
"""

from datetime import time

from dir3 import day, next_event, prayer, task
from dir3 import week as _week

# --- Standort (dein Ort, hier im Planfile) ----------------------------------
# lat, lon, IANA-Zeitzone. Ohne diese Zeile bestimmt dir3 ihn per Geolocation.
location = (40.7992, 29.4305, "Europe/Istanbul")


@day(name="Mein Tag")
def alltag(ctx):
    return [
        task("Fajr-Gebet", start=prayer.fajr, duration="15m"),
        task("Frühstück", start=time(7, 0), duration="30m"),
        task("Arbeit & Lernen", start=time(8, 30), until=time(17, 0), flex=True),
        task("Isha-Gebet", start=prayer.isha, duration="10m"),
        task("Familie & runterfahren", duration="1h", flex=True),
        task("Schlafen", until=next_event),
    ]


def make_plan():
    return _week(
        mon=alltag,
        tue=alltag,
        wed=alltag,
        thu=alltag,
        fri=alltag,
        sat=alltag,
        sun=alltag,
    )


__title__ = "Schlafen bis zum nächsten Event"
