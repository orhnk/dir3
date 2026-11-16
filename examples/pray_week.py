"""Gebets-Woche: jeder Tag um die fünf Gebete herum gebaut.

Jeder Tag startet 5 Minuten vor dem Adhan mit dem Gebet, jede Rakat dauert
4 Minuten. Dazu kommt taeglich eine kurze Qaylulah (Mittagsruhe nach Dhuhr).

Unter der Woche: 2h Lesen, 2h Coding, 1h Fruehstueck, 1h Dinner.
Am Wochenende:  Rausgehen, Familie (mittags & abends), mehr Lesen (3h),
mehr Coding (3h).

    dir3 examples/pray_week.py --until 7          # eine Woche
    dir3 examples/pray_week.py --until 360        # ein ganzes Jahr
"""

from datetime import timedelta

from dir3 import day, next_event, prayer, task
from dir3 import week as _week

# --- Standort (dein Ort, hier im Planfile) ----------------------------------
# lat, lon, IANA-Zeitzone. Ohne diese Zeile bestimmt dir3 ihn per Geolocation.
location = (40.7992, 29.4305, "Europe/Istanbul")

# --- Gebete: (Name, Adhan-Anker, Rakat-Zahl) --------------------------------
# Start je 5 Minuten vor dem Adhan; jede Rakat dauert 4 Minuten.
SALAWAT = [
    ("Fajr", prayer.fajr, 2),
    ("Dhuhr", prayer.dhuhr, 4),
    ("Asr", prayer.asr, 4),
    ("Maghrib", prayer.maghrib, 3),
    ("Isha", prayer.isha, 4),
]


def _salawat():
    return [
        task(
            name,
            start=adhan - timedelta(minutes=5),
            duration=timedelta(minutes=rakats * 4),
        )
        for name, adhan, rakats in SALAWAT
    ]


@day(name="Gebets-Tag")
def werktag(ctx):
    fajr, dhuhr, asr, maghrib, isha = _salawat()
    return [
        fajr,
        task("Lesen", duration=timedelta(hours=2), flex=True),
        task("Frühstück", duration=timedelta(hours=1), flex=True),
        task("Coding", duration=timedelta(hours=2), flex=True),
        dhuhr,
        task("Qaylulah", duration=timedelta(minutes=25)),
        asr,
        task("Dinner", duration=timedelta(hours=1), flex=True),
        maghrib,
        isha,
        task("Schlafen", until=next_event),
    ]


@day(name="Familien-Tag")
def familientag(ctx):
    fajr, dhuhr, asr, maghrib, isha = _salawat()
    return [
        fajr,
        task("Rausgehen", duration=timedelta(minutes=90)),
        task("Familienzeit", duration=timedelta(hours=2)),
        task("Lesen", duration=timedelta(hours=3), flex=True),
        dhuhr,
        task("Qaylulah", duration=timedelta(minutes=25)),
        asr,
        task(
            "Coding",
            until=prayer.maghrib - timedelta(minutes=5),
            flex=True,
        ),
        maghrib,
        task("Familienzeit", duration=timedelta(hours=1), flex=True),
        isha,
        task("Schlafen", until=next_event),
    ]


def make_plan():
    return _week(
        mon=werktag,
        tue=werktag,
        wed=werktag,
        thu=werktag,
        fri=werktag,
        sat=familientag,
        sun=familientag,
    )


# --- Google Calendar (optional) ----------------------------------------------
# Credentials gehoeren NICHT ins Beispiel: entweder in ein privates Planfile
# oder eine zentrale Config-Datei (``--config plan/calendar.py``), die per
# ``dir3-gcal-setup`` erzeugt wird:
#
#   dir3 examples/pray_week.py --until 7 --config plan/calendar.py --sync-gcal

__title__ = "Gebets-Woche"
