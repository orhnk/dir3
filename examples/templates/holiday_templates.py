"""Holiday template: a free day that follows the sun, not the clock.

Reuse this single day for every legal holiday (and any other free day).
The day is anchored to sunrise and the prayer times instead of a fixed
schedule, so it drifts naturally with the season.  The optional outing is
skipped automatically when rain is forecast: ``unless=rains()``.

Pair it with a calendar (see ``public_holidays_week.py``) or by hand:

    @day(name="May Day")   # or any fixed holiday
    def may_day(ctx):
        return holiday(ctx)
"""
from dir3 import day, next_event, prayer, rains, sun, task


@day(name="Holiday")
def holiday(ctx):
    return [
        task("Slow morning", start=sun.sunrise, duration="1h"),
        task("Breakfast & family", duration="1h"),
        task("Outing / friends", duration="2h", flex=True, unless=rains()),
        task("Lunch", start=prayer.dhuhr, duration="45m"),
        task("Nap or reading", duration="1h", flex=True),
        task("Hobbies & projects", duration="2h", flex=True),
        task("Dinner", start=prayer.maghrib, duration="45m"),
        task("Wind down", duration="1h", flex=True),
        task("Sleep", until=next_event),
    ]
