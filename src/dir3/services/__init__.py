"""Lazy, cached services wired into the day context."""

from __future__ import annotations

from .geo import GeoLocation, GeoLocator
from .prayer import PrayerSchedule, PrayerService
from .sun import SunService, SunTimes
from .transit import TransitJourney, TransitLeg, TransitService, TransitStop
from .weather import WeatherService, rains

__all__ = [
    "GeoLocation",
    "GeoLocator",
    "PrayerSchedule",
    "PrayerService",
    "SunService",
    "SunTimes",
    "TransitJourney",
    "TransitLeg",
    "TransitService",
    "TransitStop",
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
        transit: TransitService | None = None,
        weather: WeatherService | None = None,
        config=None,
    ) -> None:
        from ..config import Dir3Config

        self.config = config if config is not None else Dir3Config()
        self.geo = geo or GeoLocator(self.config)
        self.prayer = prayer or PrayerService(self.config, geolocator=self.geo)
        self.sun = sun or SunService(self.prayer)
        self.transit = transit or TransitService(self.config)
        self.weather = weather or WeatherService(location_getter=self.location)

    @property
    def location(self) -> GeoLocation:
        return self.geo.detect()
