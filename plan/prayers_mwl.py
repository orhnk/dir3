"""Prayer-only plan: the five daily prayers per Muslim World League.

Calculation is Caelestia/Salat method with an explicit MWL method, so the
Caelestia auto-pick can never override it:

    method = 3 (Muslim World League: Fajr 18°, Isha 17°)
    school = 0 (Shafi Asr: single shadow factor)
    method_auto = False (explicit choice wins over nearest-authority auto-pick)

Location is auto-detected per Geolocation (ipapi.co); pin it by uncommenting
the ``location`` line. The day functions use ``ctx.prayer`` (not the
module-level ``prayer`` name, which holds the config above). Run it with:

    dir3 plan/prayers_mwl.py --until 7 --compile
    dir3 plan/prayers_mwl.py --until 30 --offline --compile
"""

from datetime import timedelta

from dir3 import day, task, week

# --- Location (optional) -----------------------------------------------------
# lat, lon, IANA timezone. Commented out: dir3 auto-detects via Geolocation.
# location = (40.7992, 29.4305, "Europe/Istanbul")

# --- Prayer calculation: Muslim World League, explicit -----------------------
# Aladhan method id 3 (Fajr 18°, Isha 17°), Shafi school, no auto-pick.
prayer = {"method": 3, "school": 0, "method_auto": False}


@day(name="Prayers (MWL)")
def prayer_day(ctx):
    p = ctx.prayer
    return [
        task("Fajr", start=p.sunrise - timedelta(minutes=30), duration=timedelta(minutes=20)),
        task("Dhuhr", start=p.dhuhr, duration=timedelta(minutes=15)),
        task("Asr", start=p.asr, duration=timedelta(minutes=15)),
        task("Maghrib", start=p.maghrib, duration=timedelta(minutes=15)),
        task("Isha", start=p.isha, duration=timedelta(minutes=20)),
    ]


def make_plan():
    return week(
        mon=prayer_day,
        tue=prayer_day,
        wed=prayer_day,
        thu=prayer_day,
        fri=prayer_day,
        sat=prayer_day,
        sun=prayer_day,
    )


__title__ = "Prayers (Muslim World League)"
