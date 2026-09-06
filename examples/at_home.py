import requests
from dir3 import task, next_day_start
from datetime import timedelta, time

# by default all plans are lazy-loaded. That means, the weather will be calculated, in the Morning 00:00 at that day! If it is not declared different in the dir3.py config

get_up = time(5,0)

day = [
    task("Read", from=get_up, duration=timedelta(hours=3)), # First element must have a from parameter!
    task("Eat Food", duration=timedelta(minutes=50)), # from parameter is not needed here, because we just want the event to come right after the one before. If we want a space in between, we can use the parameter `space=time(1,0)` or `from=get_up+time(1,0)`, if there is no event before, as it is conditioned, this will be the first event of the day!
    task("Family Time", duration=timedelta(hours=2)),
    task("Web", space=timedelta(hours=1), duration=timedelta(hours=2)), # if today is rainy, we're not going outside.
    task("Eat Food", duration=timedelta(hours=1, minutes=30)),
    task("Sleep", until=next_day_start())
]
