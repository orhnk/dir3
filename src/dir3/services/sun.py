"""Sun events (daylight anchors) - sunrise and sunset.

These delegate to the prayer service because its offline calculator produces a
consistent sunrise/sunset with the prayer times, so ``sun.sunset`` and
``prayer.maghrib`` can never disagree.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from .geo import GeoLocation
from .prayer import PrayerService


@dataclass(frozen=True, slots=True)
class SunTimes:
    sunrise: time
    sunset: time


class SunService:
    def __init__(self, prayer: PrayerService) -> None:
        self.prayer = prayer

    def get(self, day: date, location: GeoLocation | None = None) -> SunTimes:
        schedule = self.prayer.get(day, location)
        return SunTimes(sunrise=schedule.sunrise, sunset=schedule.sunset)
