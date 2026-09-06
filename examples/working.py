import requests
from dir3 import task, next_day_start
from datetime import timedelta, time

get_up = time(5,0)

day = [
    task("Morning Routine", from=get_up, until=work_start_for_today()-timedelta(hours=1)), # First element must have a from parameter!
    task("Go to Work", duration=timedelta(hours=1)),
    task("Job", until=work_end_for_today()), # if today is rainy, we're not going outside.
    task("Go to Home", duration=timedelta(hours=1)),
    task("Family Time", duration=timedelta(hours=1, minutes=30)),
    task("Eat Food", duration=timedelta(hours=1, minutes=30)),
    task("Sleep", until=next_day_start())
]
