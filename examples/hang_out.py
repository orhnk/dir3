"""Ein Ausgeh-Tag: eigener Sonnenuntergang-Anker, wetterbedingte Sprünge.

Zeigt: eigene Anker per `@anchor` und abgeleitete Anker per Mathe
(`ctx.sun.sunset - timedelta(...)`).
"""
from datetime import time, timedelta

from dir3 import anchor, next_day_start, rains, task
from dir3 import day as _day


@anchor
def go_out_start(ctx):
    return time(8, 0)


@_day(name="Ausgehen")
def day(ctx):
    return [
        task("Go Out", start=go_out_start, duration=timedelta(hours=4), unless=rains()),
        task("Eat Food", duration=timedelta(hours=1)),
        # `ctx.sun.sunset` ist ein Anker; wir ziehen eine Stunde ab (weich deckelt).
        task("Hang Around", until=ctx.sun.sunset - timedelta(hours=1)),
        task("Return Home", duration=timedelta(hours=2), unless=rains()),
        task("Read Books", duration=timedelta(hours=2)),
        task("Sleep", until=next_day_start),
    ]
