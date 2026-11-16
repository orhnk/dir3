from datetime import timedelta

from dir3 import task

RAKAH_DUR = 2
WUDU_DUR = 5
BUF = 5


def rakat(miqdar):
    return timedelta(minutes=miqdar * RAKAH_DUR + BUF)


def _wudu():
    return timedelta(minutes=WUDU_DUR)


def _prayer(name, anchor, rakats):
    return task(name, start=anchor - _wudu(), duration=_wudu() + rakat(rakats))


prayers = {
    "fajr":    lambda ctx: _prayer("Fajr", ctx.prayer.sunrise-timedelta(WUDU_DUR+20), 4),
    "dhuhr":   lambda ctx: _prayer("Dhuhr", ctx.prayer.dhuhr, 10),
    "asr":     lambda ctx: _prayer("Asr", ctx.prayer.asr, 8),
    "maghrib": lambda ctx: _prayer("Maghrib", ctx.prayer.maghrib, 5),
    "isha":    lambda ctx: _prayer("Isha", ctx.prayer.isha, 13),

    "duha":     lambda ctx: task("Duha", duration=rakat(2)),
    "tahaccut": lambda ctx: task("Tahaccut", duration=rakat(2)),
}
