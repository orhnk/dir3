"""A timeline that knows the law: workdays Mon-Fri, free days on holidays.

Uses Python's ``holidays`` library (``pip install holidays``) to list public
holidays for your country + subdivision.  On a public holiday the calendar
runs the free-day template, weekends get a lighter weekend template, and
Mon-Fri the workday template.

    dir3 examples/public_holidays_week.py --offline --until 14

Configure country / subdivision in ``public_holidays.py``.
"""
from holiday_templates import holiday
from public_holidays import holiday_name, is_legal_holiday
from workday_templates import weekend, workday

from dir3 import calendar as _calendar
from dir3 import day

# --- location (same convention as the other examples) -----------------------
location = (40.7992, 29.4305, "Europe/Istanbul")


@_calendar
def make_year(today):
    """One function = a whole timeline of work, weekend & legal holidays."""
    if is_legal_holiday(today):
        @day(name=f"Public Holiday - {holiday_name(today)}")
        def free_day(ctx):
            return holiday(ctx)
        return free_day
    if today.weekday() >= 5:
        return weekend
    return workday


def make_plan():
    return make_year


__title__ = "Public holidays & workdays"
