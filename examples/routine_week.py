"""Eine Routine-Woche: Mo-Fr arbeiten, Sa zuhause, So draußen."""
import at_home
import hang_out
import working

from dir3 import week

week = week(
    mon=working.day,
    tue=working.day,
    wed=working.day,
    thu=working.day,
    fri=working.day,
    sat=at_home.day,
    sun=hang_out.day,
)
