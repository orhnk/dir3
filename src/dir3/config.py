"""Planfile-Konfiguration - alle Daten leben im Python-Planfile, keine TOML-Dateien.

dir3 liest die Einstellungen direkt aus dem Planfile (analog zu ``day``/``week``):
kein ``config.toml`` wie bei munazzim. Optional können im Planfile stehen::

    # 1) Standort: Tupel (lat, lon, IANA-Zeitzone) - alternativ LocationSettings/Dict
    location = (40.7992, 29.4305, "Europe/Istanbul")

    # 2) Gebetsquelle: Kürzel, PrayerSettings oder Dict
    prayer = "ezanvakti"
    #    "auto" | "online" | "offline" | "aladhan" | "ezanvakti" | "diyanet"

Nichts gesetzt? Dann bestimmt dir3 den Standort selbst per Geolocation
(``ipapi.co``, funktioniert überall) und nutzt standardmäßig Aladhan mit
offline berechneten Zeiten als Fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "dir3"


@dataclass(slots=True)
class LocationSettings:
    city: str = ""
    country: str = ""
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    use_geolocation: bool = True


@dataclass(slots=True)
class PrayerSettings:
    provider: str = "auto"  # auto | online | offline | aladhan | ezanvakti | diyanet
    method: str = "MWL"
    madhab: str = "Shafi"


@dataclass(slots=True)
class Dir3Config:
    location: LocationSettings = field(default_factory=LocationSettings)
    prayer: PrayerSettings = field(default_factory=PrayerSettings)

    @classmethod
    def from_planfile(cls, module) -> Dir3Config:
        """Baut die Konfiguration aus optionalen Planfile-Attributen.

        Unterstützte Attribute:
          ``location``  - (lat, lon, tz)-Tupel, LocationSettings oder Dict;
          ``prayer``    - Provider-Kürzel, PrayerSettings oder Dict;
          ``provider``  - Kurzform für ``prayer = "<kürzel>"``.
        """
        config = cls()

        location = getattr(module, "location", None)
        if isinstance(location, LocationSettings):
            config.location = location
        elif isinstance(location, dict):
            config.location = LocationSettings(**location)
        elif isinstance(location, (tuple, list)) and len(location) >= 2:
            config.location = LocationSettings(
                latitude=location[0],
                longitude=location[1],
                timezone=location[2] if len(location) > 2 else None,
                city=location[3] if len(location) > 3 else "",
                country=location[4] if len(location) > 4 else "",
            )

        prayer = getattr(module, "prayer", None)
        if isinstance(prayer, str):
            config.prayer.provider = prayer
        elif isinstance(prayer, PrayerSettings):
            config.prayer = prayer
        elif isinstance(prayer, dict):
            config.prayer = PrayerSettings(**prayer)
        elif isinstance(prayer, (tuple, list)):
            config.prayer.provider = str(prayer[0])

        provider = getattr(module, "provider", None)
        if isinstance(provider, str):
            config.prayer.provider = provider
        return config
