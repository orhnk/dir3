"""Fastentag: Der Tag endet nie an der Uhr, sondern an der Sonne.

Alle Bausteine sind eigene Anker, die aus den Gebetszeiten abgeleitet werden.
Aendere die Stadt (config.toml) - *der ganze Tag verschiebt sich* mit dem
Sonnenlauf. Die Mahlzeiten richten sich nach den echten Gebetszeiten:

    Qiyam  ... freiwilliges Nachtgebet vor dem Morgengrauen
    imsak  ... letzte Gelegenheit zu essen (20 min vor Fajr)
    iftar  ... gebrochen wird erst beim Maghrib - die Sonne entscheidet
"""
from datetime import time, timedelta

from dir3 import anchor, day, prayer, subtract_time, task
from dir3 import week as _week


@anchor
def qiyam(ctx):
    """Ruhige Nacht — kurz vor dem Morgengrauen."""
    fajr = ctx.prayer.schedule(ctx).fajr
    return subtract_time(fajr, timedelta(hours=1))


@anchor
def imsak(ctx):
    """Letzte Essens-Marke: 20 Minuten bevor die Sonne den Tag beginnt."""
    return subtract_time(ctx.prayer.schedule(ctx).fajr, timedelta(minutes=20))


@anchor
def iftar(ctx):
    """Fastenbrechen genau beim Maghrib — keine abendliche Deadline, die Sonne."""
    return ctx.prayer.schedule(ctx).maghrib


@anchor
def beruf_endet(ctx):
    """Der Arbeitstag endet, wenn die Sonne sinkt (in der Fastenzeit)."""
    return subtract_time(ctx.prayer.schedule(ctx).maghrib, timedelta(minutes=30))


@day(name="Fastentag")
def fasten(ctx):
    return [
        task("Qiyam — stille Nacht", start=qiyam, duration="20m"),
        task("Suhoor & Vorbereitung", until=imsak),
        task("Fajr-Gebet", start=prayer.fajr, duration="15m"),
        task("Koran & Reflexion", duration="30m"),
        task("Schule/Arbeit", start=time(8, 30), until=beruf_endet, flex=True),
        task("Maghrib-Gebet", start=prayer.maghrib, duration="10m"),
        task("Fastenbrechen (Iftar)", duration="40m"),
        task("Isha-Gebet", start=prayer.isha, duration="10m"),
        task("Tarawih & Gemeinschaft", duration="45m", flex=True),
    ]


def make_plan():
    return _week(
        mon=fasten, tue=fasten, wed=fasten, thu=fasten,
        fri=fasten, sat=fasten, sun=fasten,
    )


__title__ = "Fastentag nach dem Sonnenlauf"
