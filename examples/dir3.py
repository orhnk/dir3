"""Das zentrale und feste Planfile: kombiniert Wochen zu einem Monat.

Der Standort bestimmt sich automatisch per Geolocation (oder via
``location = (lat, lon, "zone")`` im Planfile), Gebete kommen aus Aladhan
mit Offline-Fallback - keine Konfig-Datei nötig:

    dir3 examples/dir3.py --until 360
"""
import pray_based_week
import routine_week

from dir3 import month

# --- Standort (dein Ort, hier im Planfile) ----------------------------------
# lat, lon, IANA-Zeitzone. Ohne diese Zeile bestimmt dir3 ihn per Geolocation.
location = (40.7992, 29.4305, "Europe/Istanbul")

# Monat: 3 Raster-Wochen nach routine_week, 1 Gebets-Woche nach pray_based_week.
plan = month(
    routine_week.week,
    routine_week.week,
    routine_week.week,
    pray_based_week.week,
)
