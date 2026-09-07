"""Lazy, cached services wired into the day context."""
from __future__ import annotations

from .geo import GeoLocation, GeoLocator
from .prayer import IslamicCalculator, PrayerSchedule, PrayerService
from .sun import SunService, SunTimes
from .weather import WeatherService, rains

__all__ = [
    "GeoLocation",
    "GeoLocator",
    "IslamicCalculator",
    "PrayerSchedule",
    "PrayerService",
    "SunService",
    "SunTimes",
    "WeatherService",
    "rains",
]


class Services:
    """A bundle of services shared by one compilation run."""

    def __init__(
        self,
        *,
        geo: GeoLocator | None = None,
        prayer: PrayerService | None = None,
        sun: SunService | None = None,
        weather: WeatherService | None = None,
        config=None,
    ) -> None:
        from ..config import Dir3Config

        self.config = config if config is not None else Dir3Config()
        self.geo = geo or GeoLocator(self.config)
        self.prayer = prayer or PrayerService(self.config, geolocator=self.geo)
        self.sun = sun or SunService(self.prayer)
        self.weather = weather or WeatherService()

    @property
    def location(self) -> GeoLocation:
        return self.geo.detect()
