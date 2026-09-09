"""Ein Arbeitstag: eigene Funktions-Anker für Arbeitsbeginn und -ende.

Das ist die Kernidee von dir3: *jede eigene Funktion* darf ein Zeitanchor
sein, indem du sie mit `@anchor` deklarierst.
"""
from datetime import time, timedelta

from dir3 import anchor, next_day_start, task
from dir3 import day as _day


@anchor
def work_start(ctx):
    return time(8, 30)


@anchor
def work_end(ctx):
    return time(17, 0)


@_day(name="Arbeiten")
def day(ctx):
    return [
        task("Morning Routine", start=time(5, 0), until=work_start - timedelta(hours=1)),
        task("Go to Work", duration=timedelta(hours=1)),
        task("Job", until=work_end),
        task("Go to Home", duration=timedelta(hours=1)),
        task("Family Time", duration=timedelta(hours=1, minutes=30)),
        task("Eat Food", duration=timedelta(hours=1, minutes=30)),
        task("Sleep", until=next_day_start),
    ]
