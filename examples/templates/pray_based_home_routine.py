"""Ein Tag, der sich an den Gebetszeiten ausrichtet - der munazzim-Fall.

`ctx.prayer` liefert pro Kalendertag frische Anker (fajr, sunrise, dhuhr,
asr, maghrib, isha); davon lassen sich mit `- timedelta(...)` abgeleitete
Anker bauen. Alles wird pro Tag lazy aufgelöst.
"""
from datetime import time, timedelta

from dir3 import day as _day
from dir3 import next_day_start, task, week

# --- Standort (dein Ort, hier im Planfile) ----------------------------------
# lat, lon, IANA-Zeitzone. Ohne diese Zeile bestimmt dir3 ihn per Geolocation.
location = (40.7992, 29.4305, "Europe/Istanbul")


@_day(name="Gebets-Tag")
def day(ctx):
    p = ctx.prayer
    return [
        task("Read", start=time(4, 0), until=p.sunrise - timedelta(minutes=30)),
        task("Fajr", until=p.sunrise),
        task("Arabic Shi'r", duration=timedelta(minutes=51)),
        task("Breakfast", duration=timedelta(hours=1)),
        task("Read", until=p.dhuhr - timedelta(minutes=10)),
        task("Dhuhr", until=p.dhuhr + timedelta(minutes=30)),
        task("Research", space=timedelta(hours=1), until=p.asr - timedelta(minutes=10)),
        task("Asr", until=p.asr + timedelta(minutes=20)),
        task("Eat Food", duration=timedelta(hours=1, minutes=30)),
        task("Family Time", until=p.maghrib - timedelta(minutes=10)),
        task("Maghrib", until=p.maghrib + timedelta(minutes=20)),
        task("Isha", start=p.isha - timedelta(minutes=10), until=p.isha + timedelta(minutes=30)),
        task("Sleep", until=next_day_start),
    ]


def make_plan():
    """Rufe es direkt auf: `dir3 examples/templates/pray_based_home_routine.py --until 1`."""
    return week(mon=day, tue=day, wed=day, thu=day, fri=day, sat=day, sun=day)
