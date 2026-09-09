"""Eine ganze Woche: jeden Tag derselbe Gebets-Routine-Tag."""
from templates import pray_based_home_routine as pray_based

from dir3 import week

week = week(
    mon=pray_based.day,
    tue=pray_based.day,
    wed=pray_based.day,
    thu=pray_based.day,
    fri=pray_based.day,
    sat=pray_based.day,
    sun=pray_based.day,
)
