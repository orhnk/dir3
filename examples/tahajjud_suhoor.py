"""Tahajjud + Suhoor mit Fajr-Anker.

Die Nachtblöcke hängen an ``prayer.fajr``: Suhoor endet 30 Minuten davor,
Tahajjud dauert 30 Minuten ab 03:00. Alles andere ist ein normaler Werktag.

Run: PYTHONPATH=src python examples/tahajjud_suhoor.py
"""

from datetime import time, timedelta

from dir3 import day, next_event, prayer, task, week

SUHOOR_MINUTES = 30
TAHAJJUD_START = time(3, 0)
TAHAJJUD_MINUTES = 30


def _night(ctx):
    """Suhoor (Mo/Do), Tahajjud (Fr) oder einfach durchschlafen bis Fajr."""
    wd = ctx.plan_date.weekday()  # Mon=0 .. Sun=6
    if wd in (0, 3):
        end = prayer.fajr - timedelta(minutes=SUHOOR_MINUTES)
        return [
            task(
                "Suhoor",
                start=end - timedelta(minutes=SUHOOR_MINUTES),
                until=end,
                flex=True,
            ),
            task("Schlafen", start=end, until=prayer.fajr, flex=True),
        ]
    if wd == 4:
        end = TAHAJJUD_START + timedelta(minutes=TAHAJJUD_MINUTES)
        return [
            task("Tahajjud", start=TAHAJJUD_START, until=end, flex=True),
            task("Schlafen", start=end, until=prayer.fajr, flex=True),
        ]
    return [task("Schlafen", start=time(0, 0), until=prayer.fajr, flex=True)]


def _daylight():
    """Fester Tagesablauf zwischen den fünf Gebeten."""
    return [
        task("Fajr", start=prayer.fajr, duration=timedelta(minutes=15)),
        task("Morning routine", duration=timedelta(minutes=30)),
        task("Arbeit / Studium", start=time(8, 0), until=prayer.dhuhr, flex=True),
        task("Dhuhr", start=prayer.dhuhr, duration=timedelta(minutes=10)),
        task(
            "Nachmittag",
            start=prayer.dhuhr + timedelta(minutes=10),
            until=prayer.asr,
            flex=True,
        ),
        task("Asr", start=prayer.asr, duration=timedelta(minutes=5)),
        task(
            "Abend",
            start=prayer.asr + timedelta(minutes=5),
            until=prayer.maghrib,
            flex=True,
        ),
        task("Maghrib", start=prayer.maghrib, duration=timedelta(minutes=10)),
        task("Isha", start=prayer.isha, duration=timedelta(minutes=15)),
        task("Schlafen", start=prayer.isha, until=next_event, flex=True, overlap=True),
    ]


@day(name="Werktag mit Tahajjud/Suhoor")
def werktag(ctx):
    return [*_night(ctx), *_daylight()]


@day(name="Freier Tag")
def freiertag(ctx):
    fajr, dhuhr = ctx.prayer.fajr, ctx.prayer.dhuhr
    return [
        task("Fajr", start=fajr, duration=timedelta(minutes=15)),
        task("Ausschlafen", start=fajr + timedelta(minutes=15), until=time(10, 0), flex=True),
        task("Frühstück", duration=timedelta(minutes=45), flex=True),
        task("Arbeit / Studium", start=time(11, 0), until=dhuhr, flex=True),
        task("Dhuhr", start=dhuhr, duration=timedelta(minutes=10)),
        task(
            "Nachmittag",
            start=dhuhr + timedelta(minutes=10),
            until=prayer.asr,
            flex=True,
        ),
        task("Asr", start=prayer.asr, duration=timedelta(minutes=5)),
        task("Abend", start=prayer.asr + timedelta(minutes=5), flex=True),
        task("Isha", start=prayer.isha, duration=timedelta(minutes=15)),
        task("Schlafen", start=prayer.isha, until=next_event, flex=True, overlap=True),
    ]


def make_plan():
    return week(
        mon=werktag,
        tue=werktag,
        wed=werktag,
        thu=werktag,
        fri=werktag,
        sat=freiertag,
        sun=freiertag,
    )


__title__ = "Tahajjud & Suhoor"
