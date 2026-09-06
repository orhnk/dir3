import requests
from dir3 import task, next_day_start, prayer
from datetime import timedelta, time

# by default all plans are lazy-loaded. That means, the weather will be calculated, in the Morning 00:00 at that day! If it is not declared different in the dir3.py config

get_up = time(4,0)

day = [
    task("Read", from=get_up, until=prayer.sunrise-timedelta(minutes=30)), # First element must have a from parameter!
    task("Fajr", until=prayer.sunrise), # First element must have a from parameter!
    task("Arabic Shi'r", duration=timedelta(minutes=51)),
    task("Breakfast", duration=timedelta(hours=1)),
    task("Read", until=prayer.dhuhr-timedelta(minutes=10)),
    task("Dhuhr", until=prayer.dhuhr+timedelta(minutes=30)),
    task("Research", space=timedelta(hours=1), until=prayer.asr-timedelta(minutes=10)), # if today is rainy, we're not going outside.
    task("Asr", until=prayer.asr+timedelta(minutes=20)), # if today is rainy, we're not going outside.
    task("Eat Food", duration=timedelta(hours=1, minutes=30)),
    task("Family Time", until=prayer.maghrib-timedelta(minutes=10)),
    task("Maghrib", until=prayer.maghrib+timedelta(minutes=20)),
    task("Isha", from=prayer.isha-timedelta(minutes=10), until=prayer.isha+timedelta(minutes=30)),
    task("Sleep", until=next_day_start())
]
