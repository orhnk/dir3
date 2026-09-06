# Diese Datei ist das zentrale und feste "dir3.py". Sie enthält die letzendliche Logik, um dein Plan zu compilen.

# Das ist ein monatlicher Plan, es kann auch jährliche, wochentliche, tägliche und sogar leben-lange Planen geben.

import dir3
from dir3 import month
import routine_week, pray_based_week
from datetime import timedelta

cred = "Google-Calendar-API-1234567890123456789012345678901"


dir3.compile(
             month

             (
                   routine_week.week,
                   routine_week.week,
                   routine_week.week,
                   pray_based_week.week
             ),

             until=timedelta(days=360),
             credentials=cred
)
