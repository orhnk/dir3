import requests
from dir3 import week
import at_home, hang_out, working

week = week(
    working.day,
    working.day,
    working.day,
    working.day,
    working.day,
    at_home.day,
    hang_out.day
)
