import requests
from dir3 import task, next_day_start
from datetime import datetime, timedelta, date, time
from dateutil.relativedelta import relativedelta

# by default all plans are lazy-loaded. That means, the weather will be calculated, in the Morning 00:00 at that day! If it is not declared different in the dir3.py config

get_up = time(5,0)

day = [
    task("Go Out", from=get_up, duration=timedelta(hours=4), unless=(its_rainy(), no_task())),
    task("Eat Food" duration=timedelta(minutes=30)), # from parameter is not needed here, because we just want the event to come right after the one before. If we want a space in between, we can use the parameter `space=time(1,0)` or `from=get_up+time(1,0)`, if there is no event before, as it is conditioned, this will be the first event of the day!
    task("Hang Around", until=get_sunset_time()-timedelta(hours=1)),
    task("Return Home", duration=time(1,0), unless=(its_rainy(), no_task())), # if today is rainy, we're not going outside.
    task("Read Books" duration=time(2,0)),
    task("Sleep", until=next_day_start())
]




def no_task():
    return None

def its_rainy(city="Berlin"):
    url = f"https://wttr.in/{city}?format=j1"
    response = requests.get(url)
    data = response.json()
    
    # Hole die stündlichen Regenwahrscheinlichkeiten für heute
    hourly = data['weather'][0]['hourly']
    
    # Prüfe, ob in irgendeiner Stunde die Regenwahrscheinlichkeit > 50% ist
    will_rain = any(int(h['chanceofrain']) > 50 for h in hourly)
    
    return will_rain


import geocoder
from datetime import datetime, time
from astral import LocationInfo
from astral.sun import sun
import pytz  # falls du Zeitzonen korrekt handhaben willst

def get_sunset_time():
    """
    Ermittelt automatisch den aktuellen Standort (per IP) und gibt die 
    Sonnenuntergangszeit für heute als time-Objekt zurück.
    
    Rückgabe: datetime.time (oder None bei Fehler)
    """
    # 1. Standort automatisch ermitteln
    g = geocoder.ip('me')
    if not g.ok:
        print("❌ Standort konnte nicht ermittelt werden.")
        return None
    
    lat, lon = g.latlng
    city = g.city or "Unbekannt"
    country = g.country or "Unbekannt"
    print(f"📍 Standort: {city}, {country} ({lat:.4f}, {lon:.4f})")
    
    # 2. Zeitzone des Ortes herausfinden (für korrekte lokale Zeit)
    # Dafür nutzen wir die Zeitzone aus den Geolokalisierungsdaten (falls vorhanden)
    # Oder wir nehmen die Systemzeitzone – besser: wir nutzen die Zeitzone aus der IP
    timezone_str = g.timezone or "UTC"
    try:
        tz = pytz.timezone(timezone_str)
    except:
        tz = pytz.UTC  # Fallback
    
    # 3. Sonnenuntergang mit astral berechnen
    city_info = LocationInfo(city, country, timezone_str, lat, lon)
    today = datetime.now().date()
    
    # sun() liefert ein dict mit sunrise, sunset, dawn, dusk etc.
    s = sun(city_info.observer, date=today, tzinfo=tz)
    sunset_dt = s['sunset']  # das ist ein datetime mit Zeitzone
    
    # 4. Nur die Uhrzeit (time) extrahieren
    sunset_time = sunset_dt.time()
    
    print(f"🌅 Sonnenuntergang heute: {sunset_time.strftime('%H:%M:%S')} ({timezone_str})")
    return sunset_time


# ---------- TEST ----------
if __name__ == "__main__":
    uhrzeit = get_sunset_time()
    if uhrzeit:
        print(f"Ergebnis als time-Objekt: {uhrzeit}")






