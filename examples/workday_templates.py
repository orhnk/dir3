"""Workday template: deep work between prayer, dissolves on holidays.

The heavy blocks carry ``unless=is_holiday`` so they simply disappear on a
legal holiday (the free slots stay light).  Drive the whole day with a
calendar instead - ``public_holidays_week.py`` - or force a single day:

    @day
    def monday(ctx):
        return workday(ctx)
"""
from datetime import time

from public_holidays import is_holiday

from dir3 import day, next_event, prayer, sun, task


@day(name="Workday")
def workday(ctx):
    return [
        task("Fajr", start=prayer.fajr, duration="15m"),
        task("Morning routine", duration="45m"),
        task("Commute to office", duration="45m"),
        task("Deep work", until=time(12, 0), flex=True, unless=is_holiday),
        task("Dhuhr & lunch", start=prayer.dhuhr, duration="1h"),
        task("Afternoon work", duration="1h45m", flex=True, unless=is_holiday),
        task("Asr & coffee", start=prayer.asr, duration="30m", unless=is_holiday),
        task("Wrap up & emails", duration="45m", flex=True, unless=is_holiday),
        task("Commute home", duration="45m"),
        task("Dinner with family", start=prayer.maghrib, duration="1h"),
        task("Evening reading", duration="1h", flex=True),
        task("Sleep", until=next_event),
    ]


@day(name="Weekend")
def weekend(ctx):
    return [
        task("Slow morning", start=sun.sunrise, duration="1h30m"),
        task("Market & errands", start=time(10, 0), duration="1h30m", flex=True),
        task("Lunch", start=prayer.dhuhr, duration="45m"),
        task("Family / excursion", duration="3h", flex=True),
        task("Dinner", start=prayer.maghrib, duration="1h"),
        task("Games & wind down", duration="1h", flex=True),
        task("Sleep", until=next_event),
    ]
