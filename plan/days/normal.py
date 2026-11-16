"""Normaler Tag: Gebetsblöcke als Gerüst, alles dazwischen ist flexibel."""

from datetime import time, timedelta

from dir3 import day, next_event, task, week


def _core_day(ctx):
    """Normale Gebets- und Schlafblöcke, immer gleich."""
    fajr = ctx.prayer.fajr
    dhuhr = ctx.prayer.dhuhr
    asr = ctx.prayer.asr
    maghrib = ctx.prayer.maghrib
    isha = ctx.prayer.isha

    return [
        task("Nach Fajr", start=fajr - timedelta(minutes=15), until=dhuhr, flex=True),
        task("Dhuhr", start=dhuhr, duration=timedelta(minutes=15)),
        task("Nach Dhuhr", start=dhuhr + timedelta(minutes=15), until=asr, flex=True),
        task("Asr", start=asr, duration=timedelta(minutes=10)),
        task("Nach Asr", start=asr + timedelta(minutes=10), until=maghrib, flex=True),
        task("Maghrib", start=maghrib, duration=timedelta(minutes=10)),
        task("Isha", start=isha, duration=timedelta(minutes=15)),
        task("Schlafen", start=time(23, 0), until=next_event, flex=True),
    ]


@day(name="Normaler Tag")
def normaltag(ctx):
    return _core_day(ctx)


def make_plan():
    return week(
        mon=normaltag,
        tue=normaltag,
        wed=normaltag,
        thu=normaltag,
        fri=normaltag,
        sat=normaltag,
        sun=normaltag,
    )
