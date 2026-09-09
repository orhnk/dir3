"""Ein Zuhause-Tag: weich, anker- und wetterbewusst.

Alle Pläne werden lazy pro Tag ausgewertet - das Wetter und die Gebetszeiten
werden erst am jeweiligen Tag angefragt, nicht beim Import.
"""
from datetime import time, timedelta

from dir3 import day as _day
from dir3 import next_day_start, rains, task


@_day(name="Zu Hause")
def day(ctx):
    return [
        # Das erste Element muss einen Start-Anker haben (hier eine feste Zeit).
        task("Read", start=time(5, 0), duration=timedelta(hours=3)),
        # Ohne `start` fließt der Task direkt nach dem vorherigen.
        task("Eat Food", duration=timedelta(minutes=50)),
        task("Family Time", duration=timedelta(hours=2)),
        # `space` lässt eine Lücke; `unless=rains()` lässt den Task aus, wenn Regen droht.
        task("Web", space=timedelta(hours=1), duration=timedelta(hours=2), unless=rains()),
        task("Eat Food", duration=timedelta(hours=1, minutes=30)),
        # `next_day_start` schiebt den Schlaf bis Mitternacht.
        task("Sleep", until=next_day_start),
    ]
