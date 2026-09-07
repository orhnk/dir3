"""Das zentrale und feste Planfile: kombiniert Wochen zu einem Monat.

Der Standort bestimmt sich automatisch per Geolocation (oder via
``location = (lat, lon, "zone")`` im Planfile), Gebete kommen aus Aladhan
mit Offline-Fallback - keine Konfig-Datei nötig:

    dir3 examples/dir3.py --until 360
"""
import pray_based_week
import routine_week

from dir3 import month

# Monat: 3 Raster-Wochen nach routine_week, 1 Gebets-Woche nach pray_based_week.
plan = month(
    routine_week.week,
    routine_week.week,
    routine_week.week,
    pray_based_week.week,
)
