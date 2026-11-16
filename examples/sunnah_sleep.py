"""Sünnet-Uyku-Plan: season-aware night and Qaylulah.

The block times come entirely from the prayer schedule, so the same plan
works at any location. The night length decides the season:

* SHORT   (< 7 h):  Witr before sleeping, no Tahajjud
* BALANCED (7-13 h): Tahajjud in the last third, Witr afterwards
* LONG    (> 13 h):  Tahajjud and Witr in the night

There is no sleep after Fajr. The Qaylulah sits in the early-afternoon
circadian dip (around 14:00), lasts 20-25 minutes and never runs into Asr.

In white-night latitudes (Potsdam in midsummer) the 18° Fajr/Isha angle does
not exist; pass the local mosque/Diyanet schedule instead of the solar
calculation.

    dir3 examples/sunnah_sleep.py --until 7 --compile
    dir3 examples/sunnah_sleep.py --until 30 --offline --compile
"""

from dir3 import day, sleep_plan, week

prayer = "auto"


@day(name="Sünnet-Uyku")
def sunnah_sleep(ctx):
    sched = ctx.prayer.schedule(ctx)
    return [block for _, block in sleep_plan(ctx.plan_date, sched)]


def make_plan():
    return week(
        mon=sunnah_sleep,
        tue=sunnah_sleep,
        wed=sunnah_sleep,
        thu=sunnah_sleep,
        fri=sunnah_sleep,
        sat=sunnah_sleep,
        sun=sunnah_sleep,
    )


__title__ = "Sünnet-Uyku (Ort-unabhängig)"
