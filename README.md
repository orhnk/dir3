# dir3

> Arabisch درع (Rüstung, Panzer, Schild) — the tool for discipline.

**dir3 turns your life into a program.** You *time-program* your days: instead of
a rigid list of appointments, you write a Python function that *decides* what
happens — and everything is anchored to real events, soft and adjustable.

The red thread: **your life is a function.** Any function you write can become a
time anchor with `@anchor`. The engine then compiles your day/week/month or your
whole calendar into a concrete printable plan.

## Quickstart

```bash
# run a plan file
dir3 examples/pray_week.py                # a prayer-based week (weekday + weekend)
dir3 examples/dynamic_sleep.py            # next 30 days (default)
dir3 examples/sunnah_sleep.py --until 7    # season-aware night + Qaylulah
dir3 examples/complete_year.py --until 365   # one whole year
dir3 examples/complete_year.py --from 2026-03-01
dir3 examples/ramadan.py --offline        # prayer times offline, no network
dir3 examples/tahajjud_suhoor.py          # Suhoor (Mo/Do) + Tahajjud (Fr), anchored to Fajr
dir3 examples/public_holidays_week.py --until 14   # legal holidays + workdays (pip install holidays)
dir3 examples/simple.py --compile --sync         # + push the plan into Google Calendar
dir3 examples/pray_week.py --compile --sync      # prayer week live in your calendar
```

Python ≥ 3.10 ist nötig (ZoneInfo, Dataclass-Slots). Installation und Start:

```bash
# Variante 1 - pip (funktioniert auf jedem Rechner)
python -m venv .venv && . .venv/bin/activate
pip install -e .[dev]

# Variante 2 - Nix
nix develop                       # dev shell with all deps + PYTHONPATH=src
nix build                         # installs the `dir3` binary + runs the tests
```

Abhängigkeiten: `requests`, `httpx` (nur für den Google-Calendar-Sync),
`hijridate` (Hijri/Ayyam-al-Biyd) und `tzdata` (damit `ZoneInfo` auch ohne
System-tzdb auf Windows/Slim-Containern stabil ist). Wird der Standort nirgends gesetzt, ermittelt ihn dir3 per
Geolocation und cached das Ergebnis (TTL 6 h).

**Kein Config-File** — alles lebt im Python-Planfile. Generische
Planungslogik gehört nach `dir3` (`prayerplan`, `night`, `islamic`,
`intervals`); das Planfile bleibt klein und enthält nur Daten, Einstellungen
und die Tageskomposition. Der Standort bestimmt sich automatisch per
Geolocation (ipapi.co); optional überschreibst du ihn im Planfile, und zwar
nur so viel, wie nötig:

```python
location = (40.7992, 29.4305, "Europe/Istanbul")    # lat, lon, IANA-Zeitzone
prayer   = "auto"            # "auto" (Aladhan + offline fallback) | "offline"
# oder explicit: prayer = {"method": 13, "school": 0}  # Türkei/Diyanet, Shafi
#                prayer = {"method": 3, "school": 1, "method_auto": False}
```

- Standort nicht gesetzt → selbst bestimmt (funktioniert überall);
- `prayer = "auto"` (default) — Caelestia/Salat-Methode: Monats-Cache →
  Aladhan (`/calendar/{year}/{month}` mit `method`/`school`), offline
  Solar-Fallback bei Netzfehler; `method_auto=True` wählt die nächste
  Autorität aus der live `/v1/methods`-Tabelle per Haversine (Fallback 13);
- `prayer = {"method": 13, "school": 0}` — explizite Methode (Aladhan-ID) und
  Schule (`0`=Shafi, `1`=Hanafi); explizite Methode setzt `method_auto=False`;
- `prayer = "offline"` — niemals Netzwerk; `--offline` auf der CLI ist das Kürzel.

## Android-App (dir3 phone)

> **Hızlı kurulum (Türkçe):** Bilgisayarda `pip install -e .` ve
> `dir3 serve gebetsplan.py` çalıştır; çıktıdaki URL + token'ı telefonda
> *Ayarlar*'a gir. APK'yı GitHub Actions artifact'ından (`dir3-phone-debug`)
> indir veya `cd android && ./gradlew assembleDebug` ile üret. Ayrıntılar
> aşağıda.

Die App ist eine kleine native Kotlin-Huelle um **dieselbe Web-Oberflaeche, die
`dir3 serve` ausliefert**: Google-Calendar-artige Monats-/Wochen-/Tagesansicht,
Python-Editor, CLI-Panel und echte Android-Alarme. Der PC kompiliert weiterhin
den Python-Plan — das Telefon zeigt ihn nur an. Dadurch bleiben Gebetszeiten,
Transit, Ramadan-Logik und alle Python-Features exakt gleich, und die App muss
keinen zweiten Planer mitschleppen.

```
PC:  gebetsplan.py  --dir3 compile-->  Plan  --dir3 serve-->  JSON + Code + CLI
                                                              |  WLAN
Telefon: WebView-Kalender <-- PlanRepository -- AlarmManager <--+
```

Die Kalenderoberflaeche basiert auf **[Toast UI Calendar](https://github.com/nhn/tui.calendar)**
(MIT), der Editor auf **[CodeMirror](https://codemirror.net/5/)** (MIT). Die
Alarm-Engine ist an **[BlackyHawky/Clock](https://github.com/BlackyHawky/Clock)**
(GPL-3.0) angelehnt: exakte Alarme, Vollbild-Wecken, Snooze, Crescendo,
Vibrationsmuster, Mathe-/Flip-/Shake-/Swipe-Dismiss, eigener Ton oder
Sprachausgabe des Event-Namens. Der Quelltext der App liegt unter `android/`.

### 1. Server auf dem PC starten

```bash
pip install -e .                 # einmalig
dir3 serve gebetsplan.py
```

Die Ausgabe enthaelt Token und alle LAN-URLs:

```
dir3 serve - /pfad/gebetsplan.py
Token: 3Jk...
  http://192.168.1.20:8765/?token=3Jk...
  http://127.0.0.1:8765/?token=3Jk...
```

Optionen: `--host 0.0.0.0` (Default), `--port 8765`, `--token …`,
`--no-auth` (nur im eigenen Netz), `--offline`, `--config plan/calendar.py`,
`--debug`. Der Server bindet absichtlich ans LAN; setze `--host 127.0.0.1`,
wenn nur der PC zugreifen soll. Er ist **kein Cloud-Dienst**: keine Daten
verlassen dein Netz.

### 2. APK bauen und installieren

**Variante A — GitHub Actions (kein Android Studio noetig):**

1. Repo zu GitHub pushen (oder den vorhandenen Branch pushen).
2. *Actions → Android APK → Run workflow*.
3. Das Artifact **`dir3-phone-debug`** herunterladen und die `.apk` aufs
   Telefon kopieren (Dateien-App → Installieren; „Unbekannte Quellen“ erlauben).

Der Workflow liegt in `.github/workflows/android.yml`.

**Variante B — lokal mit Android Studio / SDK:**

```bash
cd android
./gradlew assembleDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Voraussetzungen: JDK 17+, Android SDK 35 (`ANDROID_HOME` setzen oder
`android/local.properties` mit `sdk.dir=…` anlegen). MinSdk ist 26
(Android 8), TargetSdk 35.

### 3. App mit dem Server verbinden

Beim ersten Start *Ayarlar* (Einstellungen) oeffnen, **Sunucu adresi**
(`http://192.168.1.20:8765`) und **Token** eintragen, *Kaydet ve bağlan*.
Alternativ die vom Server gedruckte URL mit `?token=…` im Browser oeffnen —
die App uebernimmt den Token dann einmalig.

Danach zeigt die App den Plan, auch wenn der PC aus ist: der zuletzt
erfolgreiche Stand liegt lokal, und alle Alarme bleiben gestellt. Ein
`JobScheduler`-Job aktualisiert alle 15 Minuten, sobald WLAN da ist.

### 4. Plan-Code vom Telefon

*Kod* listet den Planfile, `plan/`, `examples/`, `days/`, `weeks/` und
`templates/`. Antippen, editieren, **Kaydet**. Jeder Speichervorgang geht per
`PUT /api/file` an den PC, wird atomar geschrieben und vorher nach
`.dir3/backups/` gesichert. Umgekehrt reicht auf dem PC ein normales
Speichern/`git pull`; die App holt die Aenderung beim naechsten *Yenile* oder
Sync. `src/` und `tests/` sind bewusst nicht editierbar.

### 5. CLI auf dem Telefon

Der Tab *Çalıştır* bildet die wichtigsten CLI-Aufrufe ab und zeigt die echte
Ausgabe:

| Knopf | Befehl auf dem PC |
|-------|-------------------|
| Planı derle | `dir3 plan.py --compile` |
| Senkronize et | `dir3 plan.py --sync` |
| Deneme | `… --compile --dry-run` |
| Temizle | `dir3 plan.py --clear --yes` |

Horizont (`Gün`), Startdatum und `--offline` lassen sich direkt setzen. Der
Server fuehrt nur diese Whitelist aus (kein Shell), mit 240-s-Timeout.

### 6. Einmalige Events vom Telefon

Im Kalender auf eine freie Zeit tippen (oder **+**) → Titel, Datum, Zeit,
Farbe, Notiz und Alarm. Diese Events landen in `.dir3/phone_events.json`,
erscheinen sofort im Plan und im Kalender und koennen geloescht werden. Sie
sind **nicht** Teil des Python-Plans und werden daher nicht nach Google
Calendar gespiegelt — dafuer den Event als `task(...)` in den Plan schreiben
(das Telefon kann den Planfile editieren).

### 7. Widget auf dem Home-Screen

Ein Kalender-Widget im Stil des Google-Calendar-Widgets, gefuellt aus dem
lokalen Plan-Cache (funktioniert also auch, wenn der PC aus ist):

* 4×2 Zellen, frei verkleiner- und vergroesserbar (bis ~10 Zeilen).
* Kopfzeile: Wochentag + Datum, rechts `↻` fuer einen Hintergrund-Sync.
* Zeilen: Uhrzeit, Farbbalken, Event-Name; ein `⏰` markiert Events, die
  tatsaechlich klingeln. Bereits beendete Events werden gedimmt.
* Fusszeile: naechster Alarm (`⏰ 05:33 Fajr`) oder der letzte Sync.
* Tippen auf eine Zeile oeffnet die App direkt an diesem Tag; Tippen auf
  die Kopfzeile oeffnet den heutigen Tag.
* Aktualisiert sich alle 30 Minuten, nach jedem Sync und nach jeder
  Alarm-Neuberechnung.

Hinzufuegen: Home-Screen lange druecken → *Widgets* → *dir3* → Widget ziehen.

### 8. Alarm-Rechte

Beim ersten Start fragt die App nach Benachrichtigungen und Kamera (Taschenlampe).
Zusaetzlich in *Ayarlar → Alarm izinleri*:

* **Kesin alarm ayarı** — `SCHEDULE_EXACT_ALARM`; ohne das darf Android den
  Alarm verzoegern.
* **Pil optimizasyonu** — Akku-Optimierung fuer dir3 deaktivieren; sonst
  schlafen manche Hersteller (Xiaomi, Huawei, Samsung) die App ein.
* **Tam ekran bildirim** — auf Android 14+ ggf. separat erlauben.
* **Alarm sesi seç** — optionaler eigener Alarmton; im Plan mit
  `alarm(sound="app")` referenzieren.

Die App nutzt `AlarmManager.setAlarmClock`: exakt, Doze-fest und mit dem
System-Wecker-Symbol. Ohne exakte Rechte faellt sie auf
`setAndAllowWhileIdle` zurueck, statt den Alarm still zu verlieren.

### 9. Eigene Alarmtoene

Audio-Dateien nach `android/app/src/main/assets/sounds/` legen und im Plan
referenzieren:

```python
task("Fajr", start=prayer.fajr, duration="30m",
     alarm=alarm(sound="adhan.mp3", speak=True))
```

`sound="random"` + `sounds=(...)` spielt zufaellig einen der Toene (wie in
Clock). `sound="app"` nimmt den Ton, den du in der App unter *Ayarlar →
Alarm sesi seç* ausgewaehlt hast (praktisch, ohne APK-Neubau);
`content://…`-URIs funktionieren ebenfalls. Ohne Treffer faellt die App auf
den System-Alarmton zurueck. Fuer die Sprachausgabe nutzt sie die
Android-TTS-Stimme (Systemsprache; eigene Sprache ueber
`Prefs.ttsLanguage`, aktuell noch ohne UI-Feld).

### 10. Grenzen

* **Timer, Stoppuhr, Weltuhr** aus Clock sind keine Plan-Events und daher
  nicht Teil von dir3. Alle *Alarm*-Funktionen (Label, Ton, Zufallston, TTS,
  Crescendo, Vibration, Snooze-Limit, Dismiss-Challenges, Vollbild,
  Hintergrundfarbe, Taschenlampe, Pre-Notification, Skip-next) sind es.
* Der **Power-Knopf** laesst sich von Apps nicht abfangen; `dismiss=("power",)`
  wird auf die Lautstaerketasten abgebildet (die funktionieren immer).
* Der Server spricht **HTTP ohne TLS** im LAN. Nicht ins Internet stellen;
  Token geheim halten.
* Manche Hersteller beenden Hintergrunddienste aggressiv. Die App zeigt die
  noetigen Schalter, kann sie aber nicht erzwingen.

### 11. JSON-Export ohne App

`dir3 export` ist derselbe Plan, den `dir3 serve` liefert:

```bash
dir3 export gebetsplan.py --until 7 --offline -o plan.json
```

Das Dokument enthaelt `events` (absolute ISO-Zeiten, Hex-Farbe, Icon,
Kategorie) und eine flache `alarms`-Liste mit `trigger`. Damit kann jede
andere Uhr/Anzeige die Alarme uebernehmen.

## Verkehrsmittelzeiten (Transit)

`ctx.transit` liefert echte ÖPNV-Verbindungen über eine HAFAS-REST-API. Der
Default ist die Community-VBB-API für **Berlin/Brandenburg** (kein API-Key);
für andere Regionen lässt sich ein kompatibler Endpoint setzen:

```python
transit = {
    "endpoint": "https://v6.vbb.transport.rest",
    "timezone": "Europe/Berlin",
    "timeout": 10,
    "results": 3,
}
```

Im Plan fragst du Reisezeit oder eine konkrete Verbindung ab:

```python
from datetime import time

from dir3 import day, task

@day
def freitag(ctx):
    journey = ctx.transit.journey("Mertensstr.", "Galenstr.", at=time(12, 15))
    if journey is None:
        return []
    return [
        task(
            f"Weg: {journey.summary}",
            start=journey.departure.time(),
            duration=journey.duration,
        )
    ]
```

- `ctx.transit.journey(origin, destination, at=...)` — erste Verbindung;
  `arrival=...` fragt „komme bis … an“ statt „fahre ab …“.
- `ctx.transit.journeys(...)` — alle Treffer; `ctx.transit.duration(...)` —
  nur die Reisezeit; `ctx.transit.from_here(...)` — Start ist der Plan-Standort.
- `lines=(...)` pinnt eine vorgegebene Linienfolge; `fewest_transfers=True`
  sortiert die Treffer nach Umstiegen (dann Abfahrt), damit eine langsamere
  direkte Verbindung nicht von einer schnelleren mit mehr Umstiegen verdrängt
  wird. Mit `results=20` kommen auch Routen in die Auswahl, die der Provider
  nicht unter den ersten „schnellsten“ Treffern liefert.
- `origin`/`destination` dürfen ein Haltestellenname, `(lat, lon)`,
  `GeoLocation` oder `TransitStop` sein. Koordinaten werden auf die nächste
  Haltestelle abgebildet; `TransitStop.distance` nennt den Fußweg dorthin.
- `TransitJourney` enthält `departure`, `arrival`, `duration`, `transfers`,
  `summary` und `legs`; jeder `TransitLeg` hat `mode`, `line`, `direction`,
  `origin`, `destination`, `departure`, `arrival`, `platform` und `distance`.
- Netzwerkfehler liefern `None`/`[]` — Pläne bleiben offline kompilierbar.
  Haltestellen werden auf Platte gecacht (`~/.cache/dir3/transit.json`).

Für geplante Wege gibt es `route_way`: Der Plan liefert Haltestellen, Linien
und den vollständigen Event-Titel; dir3 wählt die Verbindung, hängt Fußwege
per `lead`/`extra` an und liefert `None`, wenn nichts passt:

```python
from dir3 import Route, route_way

ROUTE = Route("S+U Rathaus Spandau", "Galenstr.", ("671",))
way = route_way(
    ctx,
    "Weg: Bibliothek → Moschee",
    ROUTE,
    start=12 * 60,
    deadline=12 * 60 + 30,
    origin="Bibliothek",
    destination="Moschee",
)
```

Mit `deadline` wird rückwärts ab Ankunft gesucht; ohne Deadline ab `start`.
`TravelSettings` bündelt `results`, `retry_step`, `retry_attempts` und
`query_windows`. `route_end(way)` berechnet die Ankunftsminute.

### Fasting, Ramadan and Qurban

`is_voluntary_fast(day, weekdays=..., ayyam_al_biyd=True)` erkennt freiwillige
Fastentage (standardmäßig Mo/Do plus Ayyam al-Biyd), aber **nicht** Ramadan
und **nicht** Eid-/Qurban-Tage. Für die Frage „wird heute gefastet?“ nimm
`is_fasting_day(...)`; sie schließt ganz Ramadan ein und lässt Eid al-Fitr
sowie die Qurban-Tage aus.

```python
from dir3 import (
    is_ramadan,
    is_eid_al_fitr,
    is_eid_al_adha,
    is_day_of_arafah,
    is_qurban,
    is_fasting_day,
)

if is_fasting_day(ctx.plan_date):
    ...  # kein Frühstück; Iftar/Suhoor einplanen
```

`RamadanSettings` und `ramadan_events(day, sched, settings)` liefern Suhoor
(bis Fajr), Iftar (ab Maghrib) und Tarawih (nach Isha). Namen und Dauer kommen
aus den Settings. Suhoor lässt sich auch über `NightSettings` planen, damit
Tahajjud und Witr davor passen:

```python
NightSettings(
    force_suhoor=True,          # auch an Ramadan-Tagen
    include_tahajjud=False,     # Tahajjud separat/Qiyam
    suhoor_name=RAMADAN.suhoor_name,
    suhoor_minutes=RAMADAN.suhoor_minutes,
)
```

Die Einzelbausteine `ramadan.suhoor`, `iftar` und `tarawih` sind ebenfalls
öffentlich; `tarawih(..., start=...)` setzt den Beginn nach Hitam oder einem
späten Rückweg.

```python
from dir3 import RamadanSettings, ramadan_events

events.extend(ramadan_events(ctx.plan_date, ctx.prayer.schedule(ctx), RamadanSettings()))
```

`QurbanSettings` und `qurban_events(day, sched, settings)` planen am ersten
Qurban-Tag (`is_eid_al_adha`) Eid-Gebet, Opfer und Fleischverteilung. An den
Tashreeq-Tagen 11–13 Dhu al-Hijjah kann `qurban_sacrifice(...)` separat
eingeplant werden; `is_qurban(day)` erkennt alle vier Tage.

### Sunnah events

`dir3.sunnah` bündelt die zeitgebundenen Sunnah-Handlungen. Jeder Helfer
liefert `(minute, Task)` oder eine Liste davon (wie `night_events` und
`ramadan_events`); im `@day` werden daraus die Tasks extrahiert. Die Zeiten
sind an Gebets- und Sonnenzeiten geankert; Anzahl der Rak'ah, Dauer und Namen
sind konfigurierbar.

| Helfer | Zeitfenster |
|--------|-------------|
| `rawatib_events(sched, settings)` | 2 vor Fajr; 4 vor + 2 nach Dhuhr; 2 nach Maghrib; 2 nach Isha; optional 4 vor Asr sowie 2 vor Maghrib/Isha |
| `witr(sched, settings, start=...)` | nach Isha oder nach Tahajjud, vor Fajr |
| `awwabin(sched, settings)` | freiwilliges Gebet zwischen Maghrib und Isha |
| `duha(sched, settings)` | ab Sonnenaufgang + 15 min bis kurz vor Dhuhr; `at_best_time=True` nimmt die Mitte zwischen Sonnenaufgang und Dhuhr |
| `adhkar_events(sched, settings)` | Morgen-Adhkar nach Fajr, Abend-Adhkar nach Asr |
| `quran(sched, settings)` | standardmäßig nach Fajr; `anchor=` und `delay=` verschieben das Fenster |
| `itikaf(day, sched, settings)` | I'tikaf ab dem Abend des Plan-Tags bis zum nächsten Fajr; für die Nächte vor den letzten zehn Ramadan-Tagen |
| `qiyam(sched, settings)` | Qiyam al-Layl im letzten Nachtdrittel |
| `laylat_al_qadr_qiyam(day, sched, settings)` | Qiyam nur an den ungeraden Nächten 21/23/25/27/29 Ramadan |
| `eid_fitr_events(day, sched, settings)` | Eid-al-Fitr-Gebet nach Sonnenaufgang |

`night_events` platziert optional auch Witr (`include_witr=True`,
`witr_minutes`, `witr_gap`, `witr_name`) zwischen Tahajjud und Suhoor.
`include_tahajjud=False` behält Suhoor bei; `force_suhoor=True` erzwingt
Suhoor auch an Ramadan-Tagen. So bleiben alle Nachtzeiten in Settings statt
im Plan verdrahtet.

```python
from dir3 import (
    AwwabinSettings,
    DuhaSettings,
    RawatibSettings,
    WitrSettings,
    adhkar_events,
    awwabin,
    day,
    duha,
    quran,
    rawatib_events,
    witr,
)

RAWATIB = RawatibSettings(
    asr_before=4,      # die nicht betonten Blöcke sind optional
    maghrib_before=2,
    isha_before=2,
)


@day(name="Sunnah-Tag")
def sunnah_day(ctx):
    sched = ctx.prayer.schedule(ctx)
    blocks = [
        *rawatib_events(sched, RAWATIB),
        duha(sched, DuhaSettings(at_best_time=True)),
        awwabin(sched, AwwabinSettings()),
        *adhkar_events(sched),
        quran(sched),
        witr(sched, WitrSettings()),
    ]
    blocks.sort(key=lambda block: block[0])
    return [block_task for _, block_task in blocks]
```

Wenn Tahajjud eingeplant ist, sollte Witr die letzte Nacht-Prayer sein. Dafür
den expliziten Start verwenden, zum Beispiel `witr(sched, start=4 * 60 + 30)`.
Die Blöcke werden vor der Rückgabe nach `minute` sortiert. Kombinierst du sie
mit `night_events`, müssen Suhoor, Fajr-Sunnah, Morgen-Adhkar und Schlaf
zusammenpassen; dafür `suhoor_before_fajr`, `fajr_minutes` und `after_delay`
justieren. I'tikaf ist ein Aufenthalt und darf bewusst mit Nachtblöcken
überlappen.

#### Freiwillige Fasten

`SunnahFastSettings` beschreibt, welche freiwilligen Fasten erkannt werden.
Standardmäßig sind Mo/Do, Ayyam al-Biyd, Ashura, Tasu'a und Arafah aktiv.
Weitere Fasten sind bewusst opt-in, weil sie viele Tage abdecken oder eine
persönliche Auswahl brauchen:

```python
from datetime import date

from dir3 import (
    SunnahFastSettings,
    is_fasting_day,
    is_sunnah_fast,
    sunnah_fast_name,
)

fasts = SunnahFastSettings(
    first_nine_dhul_hijjah=True,
    shawwal_days=frozenset({2, 9, 16, 23, 24, 25}),
    shaban=True,
    dawud_start=date(2027, 1, 1),
)

if is_sunnah_fast(ctx.plan_date, fasts):
    ...  # kein Frühstück; Suhoor über NightSettings(fasts=fasts)

label = sunnah_fast_name(ctx.plan_date, fasts)  # z. B. "Ashura", "Arafah", "Shawwal"
is_fasting_day(ctx.plan_date, sunnah_fasts=fasts)  # schließt Ramadan ein
```

`shawwal_days` sind Hijri-Tage im Shawwal; die sechs Tage dürfen frei gewählt
werden. `dawud_start` markiert den ersten Fastentag für den alternierenden
Fastenrhythmus. Ramadan und Eid-/Qurban-Tage werden immer ausgeschlossen.

#### Ramadan und Laylat al-Qadr

`is_last_ten_nights(day)` erkennt 21 Ramadan bis zum Monatsende,
`is_laylat_al_qadr_candidate(day)` die ungeraden Nächte 21/23/25/27/29. Die
Nacht gehört jeweils zu den frühen Stunden des Plan-Tags (letztes Drittel vor
Fajr); der genaue Zeitpunkt von Laylat al-Qadr ist unbekannt. `itikaf(...)`
setzt einen Aufenthalt in der Moschee voraus und plant ab nach Isha am Plan-Tag
bis zum Fajr des Folgetags. Der Plan-Tag ist also der Abend, an dem I'tikaf
beginnt: für die Nacht vor dem 21. Ramadan den 20. Ramadan übergeben. So passt
der Block zu `laylat_al_qadr_qiyam` am Folgetag.

#### Abgrenzung

Nicht automatisch geplant werden Taten, die von einer Situation abhängen:
Istikharah, Tawbah, Hajah, Tasbih, Janazah, Istisqa und Khusuf. Auch
Freitags-Sunnah (Ghusl, Surah al-Kahf, Salawat) bleibt beim Plan, weil der
beste Platz von der lokalen Freitagsroutine abhängt. Diese Taten lassen sich
mit normalen `task(...)`-Blöcken ergänzen. Die Helfer sind keine Fatwa:
Rechtschule, Rak'ah-Zahlen und Zeiten können abweichen.

### Sünnet-Uyku-Plan (Nacht und Kaylûle)

`sleep_plan(day, sched, settings)` leitet aus den Gebetszeiten einen
vollständigen Schlafplan ab. Die Nacht ist Maghrib bis Fajr; ihre Länge
bestimmt die Saison und damit die Sunnah-Blöcke:

| Nacht | Kaylûle | Tahajjud | Witr |
|-------|---------|----------|------|
| `SHORT` (< 7 h) | 25 min | entfällt | vor dem Schlafen |
| `BALANCED` (7–13 h) | 20 min | 18 min | nach Tahajjud |
| `LONG` (> 13 h) | 25 min | 22 min | nach Tahajjud |

- **Nach Fajr wird nicht geschlafen.** Der Morgen gehört dem Tag; der eine
erlaubte Schlaf am Tag ist die Kaylûle.
- `can_wake=False` (Schicht, Krankheit, kleine Kinder) streicht Tahajjud und
  legt Witr vor den Schlaf.
- Die Nacht wird in zwei Blöcke geteilt: der erste endet kurz vor Tahajjud,
  der zweite beginnt nach Witr und endet `fajr_margin` vor Fajr. Der erste
  Block bekommt den restlichen Schlafbedarf, nachdem der zweite Block durch
  Witr und Fajr festliegt.
- Der Gesamtschlaf (Nacht + Kaylûle) bleibt zwischen `min_sleep_minutes` und
  `max_sleep_minutes`. Ist er zu lang, schrumpft zuerst die Kaylûle
  (`reduced_qaylulah`), erst zuletzt entfällt Tahajjud. Ist er zu kurz,
  entfällt Tahajjud ebenfalls.
- Die Kaylûle liegt in der natürlichen Nachmittagssenke um `qaylulah_target`
  (Standard 14:00), beginnt nie nach `qaylulah_latest` (Standard 15:00),
  dauert 20–30 min und ist nie länger als `max_qaylulah` (30 min). Reicht der
  Platz vor Asr nicht, rutscht sie früher; passt sie gar nicht, entfällt sie.
  Zwischen Asr und Maghrib wird nicht geschlafen. Die kurze Dauer folgt der
  Schlafforschung: 20–30 min erholen, ohne die Trägheit eines langen
  Nickerchens auszulösen.
- `sleep_plan(...)` liefert `(minute, Task)`-Paare wie `night_events` und
  lässt sich direkt in einem `@day` ausgeben:

```python
from dir3 import day, sleep_plan

@day(name="Sünnet-Uyku")
def sunnah_sleep(ctx):
    sched = ctx.prayer.schedule(ctx)
    return [block for _, block in sleep_plan(ctx.plan_date, sched)]
```

In Weißen Nächten (Potsdam etwa Ende Mai bis Mitte Juli) erreicht die Sonne
den 18°-Fajr/Isha-Winkel nicht. Dann die lokale Moschee-/Diyanet-Zeiten als
`sched` übergeben; `sleep_plan` rechnet ausschließlich mit den übergebenen
Zeiten und funktioniert damit an jedem Ort.

## Google Calendar sync

Der kompilierte Plan wird **standardmäßig nach Google Calendar geschrieben**
(`dir3 plan.py` syncs; `--compile` druckt nur, `--dry-run` druckt und zeigt den
Sync ohne zu schreiben). Die Credentials liegen — wie alles andere — im
Python-Planfile (oder in der `--config`-Datei):

```python
from dir3 import GoogleCalendar

gcal = GoogleCalendar(
    client_id="…",
    client_secret="…",
    refresh_token="…",
    calendar_id="primary",   # optional, default "primary"
)
```

### Synchronisieren

```bash
dir3 plan.py                       # Standardaktion: kompilieren + syncen
dir3 plan.py --sync                # dasselbe, explizit
dir3 plan.py --sync --dry-run      # Plan + Sync-Umfang zeigen, nichts schreiben
dir3 plan.py --clear               # nur von dir3 angelegte Events entfernen
dir3 plan.py --clear --nuke --yes  # ALLE Events im Kalender loeschen
```

`--until N` und `--from YYYY-MM-DD` begrenzen das Fenster, `--offline` verbietet
das Netz fuer die Gebetszeiten. Der Provider wird erkannt; `--gcal` ist nur
noetig, wenn mehrere Provider konfiguriert sind.

### Defaults im Planfile

Damit `dir3 plan.py --sync` ohne weitere Flags genau das tut, was der Plan
vorsieht, duerfen die Lauf-Parameter im Planfile stehen:

```python
sync = {
    "until": 7,                      # Horizont in Tagen (sonst 30)
    "from": "2026-11-14",            # Startdatum (ISO), sonst heute
    "offline": True,                 # Gebetszeiten rein offline
    "config": "plan/calendar.py",    # zentrale Config-Datei
}
```

Explizite CLI-Flags (`--until`, `--from`, `--offline`, `--config`) haben immer
Vorrang; ein relativer `config`-Pfad wird relativ zum Planfile aufgeloest.
`sync` ist optional - fehlt es, bleiben die bisherigen Defaults (30 Tage, Start
heute, `--config` nur per CLI).

- OAuth2: `refresh_token` + `client_id`/`client_secret` (Token wird pro Lauf
  frisch geholt) oder direkt ein `access_token`.
- Der Sync ist ein **Abgleich (Hot-Reload), kein Neuaufbau**: dir3 liest die
evorhandenen Events, diffed sie gegen den kompilierten Plan und schreibt nur
die echten Änderungen. Ein unveränderter Plan kostet null Schreibzugriffe
(statt wie früher alle Events erneut zu senden).
- Jedes Event trägt eine deterministische Custom-ID (plain SHA1 über
  Titel/Datum/Name/Zeiten) **und** einen stabilen Schlüssel `dir3key`
  (Titel/Datum/Name/Vorkommen) in den privaten `extendedProperties`.
  Verschiebt sich nur die Zeit, wird das bestehende Event an Ort und Stelle
  aktualisiert — es wird nicht gelöscht und neu angelegt.
- **Löschen nur nach Verifikation**: entfernt wird ein Event ausschließlich,
  wenn es den `dir3=1`-Marker trägt, zum selben Plan gehört (`dir3plan`) und
  sein Tag im aktuell kompilierten Planfenster liegt. Fremde Events, Events
  anderer Pläne und alles außerhalb des Fensters bleiben unangetastet.
- **Rate Limits**: Google antwortet bei zu schnellen Läufen mit `403`/`429`
  (`rateLimitExceeded`). Retries respektieren `Retry-After`, laufen mit
  exponentiellem Backoff plus Jitter und pausieren über eine gemeinsame
  Drossel *alle* parallelen Batches, sobald einmal gebremst wurde.
- Events werden in der **Plan-Zeitzone** angelegt (mit explizitem Offset und
  IANA-Label); Carry-Events (Schlaf bis `next_event`) enden am realen
  Folge-Morgen.
- `--dry-run` druckt den Plan und zeigt nur den Umfang (keine Änderungen).
- `dir3 plan.py --clear` entfernt alle von dir3 angelegten Events wieder
  aus dem Kalender (nur solche mit dem `private.dir3=1`-Marker; nichts anderes).
  Bereits verschwundene Events (404/410) zählen als erledigt statt den Lauf
  abzubrechen.
- `dir3 plan.py --clear --nuke --yes` löscht **alle** Events im Kalender, auch
  fremde (ohne Marker-Prüfung). Braucht zwingend `--yes`; `--dry-run` zeigt
  vorab nur die Anzahl.
- Der Provider wird **erkannt**: mit nur einem konfigurierten Provider reicht
  `--sync`/`--clear`; `--gcal` (bzw. künftig `--<provider>`) ist nur bei
  mehreren Providern nötig. Alte Flags `--sync-gcal`/`--gcal-clear`
  funktionieren weiter.
- Der GCal-Codepfad nutzt **`aiogoogle` (async)** statt der blocking-`requests`
  für den Rest von dir3.
- **Event-Farben** (Munazzim-Idee, als Trait portiert): Gebete sind standardmäßig
  gelb (Banana), alle anderen Events bekommen deterministisch aus ihrem Namen eine
  Farbe (Byte-Summe modulo 11 — gleicher Name, gleiche Farbe). Mit
  `color_policy = PrayerStatusColorPolicy()` werden exakte Gebete grün,
  verschobene Gebete gelb, Gebete mit Vorlesungszeit orange sowie kritische
  und Kerahat-Gebete rot. Die festen GCal-Farben sind als `GCalColor`
  built-in (`GCalColor.LAVENDER` … `GCalColor.TOMATO`) und tragen die
  GCal-Namen samt `colorId`; eigene Farben pro Event via
  `colors = {"Coding": GCalColor.BLUEBERRY}` oder numerisch
  `{"Coding": 9}`. Diese nutzerdefinierten `colors` überschreiben auch eine
  gesetzte `color_policy` für die genannten Events; eigene Policies
  implementieren einfach
  `color_for(name, index)` und dürfen Slots oder `GCalColor` zurückgeben
  (`from dir3 import ColorPolicy, GCalColor`).
- **Gebets-Statusfarben**: `color_policy = BasilPistazienColorPolicy()` färbt
  Gebete nach Zustand — Basilikum (am Adhan in der Moschee), Pistazie
  (verschoben in der Moschee), Flamingo (allein, auch verschoben), Tomate für
  dringende Gebete (Kritisch/Kerahat). Die Slots sind als
  `BASIL_SLOT`, `PISTACHIO_SLOT`, `FLAMINGO_SLOT`,
  `MANDARIN_SLOT`, `TOMATO_SLOT` exportiert; den Zustand liest die Policy aus
  den Markern im Event-Namen (`Moschee`, `allein`, `verschoben`, `Kerahat`,
  `kritisch`). Für feste Namen direkt `GCalColor.BASIL`,
  `GCalColor.SAGE`, `GCalColor.PEACOCK`, `GCalColor.BANANA`,
  `GCalColor.TANGERINE` oder `GCalColor.TOMATO` verwenden.
- **Event-Icons**: Terminal-Ausgabe **und Kalender-Titel** tragen Icons — 🕋
  für Gebete, 🕌 in der Moschee, 🧍‍♂️ allein, 🏫 für
  Vorlesungen/Übungen (Keyword oder Kursnummer wie `HE101`), 🛣️ für Wege,
  🌙 Schlafen, 🍳 Kochen, 🕸️ Netzwerken und 🍽️ Mahlzeiten. Bei 🕌/🧍‍♂️
  entfällt das redundante `Moschee`/`allein` in der Anzeige. Standard ist
  `DefaultIconPolicy`; Marker pro Planfile anpassbar:

  ```python
  from dir3 import DefaultIconPolicy
  icon_policy = DefaultIconPolicy(lectures="📚", mosque="🏛️")
  ```

  Eigene Logik implementiert einfach `icon_for(name, index) -> str`
  (`from dir3 import IconPolicy`), schichtbar mit `icon_policy_chain(...)`.
  `event_summary(name, policy)` liefert Icon + gekürzten Namen; die
  Namenverkürzung kompaktiert nur (`EN 732` → `EN732`, `Uebung` → `Ü`,
  `14:14 → 15:48` → `14:14→15:48`) und lässt Zeiten, Kurse und Statusinfos
  vollständig stehen. Dringende Gebete sind rot; nur-Farz-Gebete tragen
  `(Farz)` im Titel, unterbrochene Blöcke `⛓️‍💥`. Vorlesungsbrüche sind
  immer allein und nur Farz; würde Asr sonst in den Kerahat warten, bricht
  es die Vorlesung, wenn der Bruch Kerahat vermeidet.

### Aufgaben (Google Tasks, hybrid)

Google Calendar zeigt Aufgaben mit Startzeit und Dauer an — die öffentliche
API kann das aber nicht schreiben: Google Tasks speichert im `due`-Feld nur
ein Datum (die Uhrzeit wird verworfen), und die Calendar-API hat keinen
Event-Typ `task`. dir3 löst das **hybrid**:

```python
from datetime import time
from dir3 import Todo, task

task("Wucūbāt lesen", start=time(19, 45), duration="1h", task_list="Wucūbāt")

task(
    "Hitam", start=time(20, 29), duration="15m",
    task_list="Hitam",
    todos=(
        Todo("K", todo_position="end"),
        Todo("R", todo_position="end"),
        Todo("P", todo_position="end"),
    ),
)
```

- Der **getimte Kalender-Event** bleibt exakt wie bisher (Start, Ende, Dauer,
  Farbe, Icons).
- Zusätzlich entsteht ein **echter Google Task** in der Liste `Wucūbāt`
  (fehlende Listen legt dir3 an). Er ist abhakbar und erscheint am Plandatum.
- Die Notes des Tasks enthalten den Zeitblock (`19:45–20:45 · 1:00 h`) und den
  stabilen `dir3key`; darüber wird der Task beim nächsten Sync aktualisiert,
  statt doppelt angelegt zu werden.
- `todo_position="start"|"end"` legt den gespiegelten Task an den Anfang oder
  das Ende des Events. Das `due`-Datum folgt entsprechend dem Start- bzw.
  Enddatum (wichtig bei Events über Mitternacht); in den Notes steht
  „am Anfang“ bzw. „am Ende“.
- `todos=(Todo("K"), Todo("R"), Todo("P"))` hängt weitere Google Tasks an ein
  Event. Sie erzeugen **keine** eigenen Kalender-Events und landen in derselben
  `task_list`; jeder Todo kann seine eigene `todo_position` tragen. `todos`
  braucht deshalb immer eine `task_list`.
- Ohne `todo_position` und **mit** angehängten `todos` ist das Event nur deren
  Container: Es entsteht kein Google Task für den Event-Namen, nur die Todos
  (so bleibt z. B. „Hitam“ reiner Kalender-Event, K/R/P werden Tasks).
- Erledigte Tasks bleiben erledigt: dir3 überschreibt weder `status` noch
  fertige Aufgaben und löscht sie nicht.
- `--dry-run` zeigt die Aufgaben mit an. `--clear` entfernt markierte
  Google Tasks mit; `--nuke` bleibt bewusst auf Kalender-Events beschränkt.
- Ohne `task_list` ist eine Aufgabe weiterhin nur ein Event.
- Eine separate „Frist“ sowie Task-Farbe, Verfügbarkeit und Sichtbarkeit sind
  nicht Teil der öffentlichen Tasks-API; `due` ist das Plandatum, der Rest
  bleibt bei den Google-Defaults bzw. wird am Event gesetzt.

Voraussetzung: Die **Google Tasks API** muss im Cloud-Projekt aktiviert sein
und der Refresh-Token den Tasks-Scope enthalten. Ein alter Token ohne diesen
Scope funktioniert für Events weiter, der Aufgaben-Sync bricht aber mit einer
klaren Meldung ab. Token neu holen:

```bash
dir3-gcal-setup --client-id $CLIENT_ID --client-secret $CLIENT_SECRET
```

### GCal-Zugang einmalig einrichten

1. **Google Cloud Console**: Projekt anlegen, Google Calendar API **und**
   Google Tasks API aktivieren, OAuth-Berechtigungsdaten vom Typ
   „Desktopanwendung" erzeugen → `client_id` / `client_secret`.
2. Refresh-Token holen (öffnet einmal den Browser für den Consent):

   ```bash
   dir3-gcal-setup --client-id $CLIENT_ID --client-secret $CLIENT_SECRET
   ```

   Das Script startet einen Loopback-Redirect auf `127.0.0.1`, tauscht den Code
   gegen ein Refresh-Token und druckt den fertigen `gcal`-Block zum Einfügen.
3. Den Block in dein Planfile einfügen:

   ```python
   from dir3 import GoogleCalendar

   gcal = GoogleCalendar(
       client_id="…",
       client_secret="…",
       refresh_token="…",
       calendar_id="primary",
   )
   ```

   Alternativ — und **nicht Teil von dir3**: das Standalone-Skript
   `scripts/gcal_helper.py` (reine Standardbibliothek, kein Paket-Import)
   macht die Schritte 2–3 wie im Munazzim komplett im Browser und patcht das
   Planfile direkt:

   ```bash
   # Einmalig: client_secret.json (Desktopanwendung) aus der Cloud Console
   # in ~/Downloads legen - wird automatisch erkannt (sonst fragt der Helper
   # einmalig nach den Werten).
   python3 scripts/gcal_helper.py --planfile gebetsplan.py
   ```

   Es oeffnet den Browser, du loggst dich in dein Google-Konto ein — fertig.
   Das Refresh-Token wird unter `~/.gcal-helper/token.json` gespeichert
   (Wiederverwendung beim naechsten Lauf; `--force` erzwingt neuen
   Browser-Flow) und der fertige `gcal`-Block landet in deinem Planfile
   (inkl. `GoogleCalendar`-Import).
4. Synchronisieren: `dir3 <planfile> --compile --sync` — wiederholte Läufe
   schreiben nur noch die echten Änderungen (Abgleich per `dir3key`).

## Rezepte, Diät und Yemek planı

dir3 sammelt offen lizenzierte Rezepte aus aller Welt mit Zutatenmengen,
Portionen und Nährwerten (Kalorien, Protein, Fett, Kohlenhydrate) in einer
lokalen SQLite-Datenbank. Schwerpunkt sind die deutsche, türkische und
arabische Küche; alle anderen Küchen werden ebenfalls aufgenommen. Gefiltert
wird nur Haram (Schwein, Alkohol, Blut). Auf dieser Datenbasis baut der
Diätmotor auf: persönliches Profil, Wochenplan und Einkaufsliste.

### Bulk-Import

```bash
dir3-recipes fetch                 # alle Quellen
dir3-recipes fetch --source zenodo-culinary
dir3-recipes enrich                # fehlende Nährwerte/Portionen auffüllen
dir3-recipes stats
dir3-recipes search "mercimek" --region tr --max-calories 400
```

| Quelle | Inhalt | Lizenz |
|--------|--------|--------|
| `zenodo-culinary` | 50.510 Rezepte weltweit; alle Küchen | ODC-ODbL 1.0 |
| `turkish-recipes-175k` | 174.975 türkische Rezepte | Apache-2.0 |
| `unitools-recipes` | 501 kuratierte Weltrezepte; alle Länder | CC BY-SA 4.0 |

Der Download-Cache liegt unter `~/.cache/dir3/recipes/`. Die lokale Datenbank
liegt bevorzugt unter `data/recipes.db` im Projekt (ca. 512 MB, per
`.gitignore` vom Commit ausgeschlossen); existiert sie nicht, fällt dir3 auf
`~/.local/share/dir3/recipes.db` zurück. Mit `--db` oder `DIR3_DATA_DIR` lässt
sich der Pfad überschreiben. Wiederholte Importe sind idempotent (`source` +
`source_id`). Standardmäßig werden alle Küchen importiert; nur Haram-Rezepte
fallen raus. Wer den Import auf die drei Zielregionen begrenzen will, kann das
in der API mit `iter_source_recipes(..., regions=("de", "tr", "ar"))` tun.

### Eigene Rezepte über die API

```python
from dir3 import Ingredient, Recipe, RecipeBook

with RecipeBook.open() as book:
    book.add(Recipe(
        "Mercimek Çorbası",
        ingredients=(
            Ingredient("rote Linsen", 250, "g"),
            Ingredient("Zwiebel", 1, "Stück"),
        ),
        servings=4,
        calories=180,
        protein=9,
        fat=6,
        carbs=24,
        region="tr",
        instructions=("Kochen.", "Pürieren."),
    ))
    for recipe in book.recipes(region="tr", max_calories=400, limit=10):
        print(recipe.name, recipe.calories)
```

`Recipe.scaled(8)` skaliert die Zutatenmengen auf 8 Portionen (die Kalorien
bleiben pro Portion). `book.fill_missing_servings()` setzt fehlende Portionen
auf 1 und markiert sie mit `servings_estimated`;
`book.mark_unmeasured_ingredients()` markiert Zutaten ohne Menge als
`to_taste` („nach Bedarf“). `book.import_json(...)` und `book.import_jsonl(...)`
laden eigene Rezeptdateien; `book.add` lehnt haram-Rezepte mit
`HaramIngredientError` ab. Der Filter erkennt Schweinefleisch, Alkohol und
Blut in Namen, Zutaten und Anweisungen (deutsch/türkisch/arabisch/englisch),
ist aber keine Fatwa: unbekanntes Fleisch braucht weiterhin eine
vertrauenswürdige Quelle.

### Datenlücken schließen

`dir3-recipes enrich` schätzt fehlende Nährwerte aus den Zutaten und einer
lokalen Nährwerttabelle. Die Schätzung wird pro Rezept mit
`nutrition_estimated = 1` markiert; `servings_estimated = 1` markiert
aufgefüllte Portionen. Zutaten ohne Mengenangabe bekommen `scaling =
"to_taste"`, damit die Einkaufsliste sie als „nach Bedarf“ zeigt.

```bash
dir3-recipes enrich --limit 1000   # nur die ersten 1000 fehlenden Rezepte
```

Aktueller Stand der lokalen Datenbank:

| Feld | Wert |
|------|------|
| Rezepte gesamt | 213.195 |
| mit Kalorien | 190.234 |
| davon geschätzt | 144.194 |
| ohne Kalorien | 22.961 |
| fehlende Portionen | 0 (1.758 auf 1 gesetzt und markiert) |

Die Schätzung ist bewusst konservativ: Sie füllt nur, wenn mindestens 40 %
der Zutaten eine bekannte Menge/Einheit haben und mindestens zwei Zutaten
zuordenbar sind. Rezepte mit zu vielen ungemessenen Zutaten bleiben ohne
Kalorien, statt eine Scheingenauigkeit zu erzeugen. Schätzungen sind keine
medizinische Nährwertberatung.

Ursprünglich standen Kalorien nur dort, wo die Quelle sie liefert (Zenodo fast
vollständig, UniTools vollständig, Turkish-175K nur bei einem Teil).

### Diätmotor und Wochenplan

Das Profil beschreibt Körper, Ziel, Allergien und Vorlieben. `dir3-recipes
diet` berechnet daraus ein Kalorienziel (Mifflin-St Jeor × Aktivitätsfaktor,
plus 300 kcal beim Zunehmen bzw. minus 400 kcal beim Abnehmen), verteilt es
auf die Mahlzeiten und wählt passende Rezepte aus der Datenbank.

```json
{
  "weight_kg": 80,
  "height_cm": 180,
  "age": 30,
  "sex": "m",
  "activity": "moderate",
  "goal": "maintain",
  "allergies": ["lactose"],
  "avoid_ingredients": ["koriander"],
  "conditions": ["diabetes"],
  "favorites": ["mercimek", "linsen"]
}
```

`activity` akzeptiert auch `1.2`–`1.9`; `goal` ist `lose`, `maintain` oder
`gain` (deutsch: `abnehmen`, `halten`, `zunehmen`). `allergies` versteht
mindestens `gluten`, `lactose`, `nuts`, `egg`, `soy`, `fish`, `shellfish` und
`sesame`; `conditions` kennt grobe Regeln für `diabetes` (max. 60 g
Kohlenhydrate pro Mahlzeit) und `hypertension` (Salz-Zutaten meiden).

```bash
dir3-recipes diet --profile profil.json --days 7 --meals lunch,dinner \
  --mode mix --runs 2 --seed 42
```

`--mode balanced` nimmt das beste Kalorien-/Makro-Verhältnis, `favorites`
bevorzugt Rezepte aus `favorites`, `mix` mischt beides. `--people` und
`--servings` skalieren nur die Einkaufsmengen; das Kalorienziel bleibt pro
Person. `--runs 2` teilt die Woche in zwei Einkäufe (z. B. vier und drei Tage).

### Einkaufsliste und Einkaufs-Event

Die Einkaufsliste summiert gleiche Zutaten, rechnet `kg`/`g` und `l`/`ml` um
und behält Zeilen ohne Menge als „nach Bedarf“. Die Dauer des Einkaufs hängt
von der Artikelzahl ab:

```python
from dir3 import MealPlanSettings, RecipeBook, plan_meals, shopping_task

with RecipeBook.open() as book:
    plan = plan_meals(book, profile, MealPlanSettings(days=7, meals=("lunch", "dinner")))
    shopping = plan.shopping_list(runs=2)

print(plan.text())
print(shopping.text())
minute, block = shopping_task(
    shopping.runs[0],
    start="17:00",          # oder time(17, 0) / Minuten seit Mitternacht
)
```

`shopping_task` rechnet `base_minutes + minutes_per_item × Artikelzahl`
(Standard: 15 min + 1,5 min/Artikel, Deckel 120 min). Über
`ShoppingSettings(base_minutes=..., minutes_per_item=..., max_minutes=...)`
lässt sich das anpassen.

**Grenzen:** Die Nährwertdaten enthalten kein Natrium und keinen Zucker. Die
Krankheitsregeln sind deshalb keyword-/grenzwertbasiert und keine medizinische
Beratung; Allergene erkennt der Filter nur, wenn sie in den Zutatennamen
vorkommen. Rezepte ohne Kalorien werden übersprungen.

## The idea

Nothing is carved in stone. A plan is a **function** that answers *"what kind of
day is today?"* Tasks are soft: they chain, they compress when a day overflows,
they follow sun and prayer times, and they never break because a bus was late.

```python
from dir3 import anchor, day, task
from dir3 import week as _week

@anchor
def open_exchange(ctx):            # your own anchor: "when the market opens today"
    return time(9, 0)

@day(name="Exchange Day")
def trading_day(ctx):
    return [
        task("Review news", start=time(7, 30), duration="30m"),
        task("Order run", start=open_exchange, duration="2h", flex=True),
        task("Deep Work", start=time(12, 0), until=time(17, 0), flex=True),
        task("Evening reading", duration="1h", flex=True),
        task("Sleep", until=next_event),
    ]

def make_plan():
    return _week(mon=trading_day, tue=trading_day, wed=trading_day,
                 thu=trading_day, fri=trading_day, sat=trading_day, sun=trading_day)

__title__ = "My week"
```

## DSL

**Planfile-Konfiguration** (optional, als Modul-Attribute — sonst per Autodetect):

```python
location = (40.7992, 29.4305, "Europe/Istanbul")  # hier, im Planfile - keine TOML
prayer   = "auto"                  # Caelestia/Salat: auto (Aladhan+offline) | offline
provider = "auto"                  # Kurzform für `prayer`
# explicit: prayer = {"method": 13, "school": 0, "method_auto": False}
```

### Task

```python
task(name, *,
     start=None, until=None, duration=None, space=None,
     unless=None, flex=True, overlap=False,
     origin=None, destination=None, task_list=None,
     todo_position=None, todos=None, alarm=None)
```

| arg | meaning |
|-----|---------|
| `start` | anchor or plain `time` that starts the task |
| `until` | anchor or `time` that ends it (wraps across midnight) |
| `duration` | `timedelta`, or a string like `"1h30m"` / `"45m"` |
| `space` | gap left *before* this task when chaining |
| `unless` | predicate or tuple of predicates; `True` skips the task that day |
| `flex` | `True` (default) → the compiler *may* shrink this task to absorb overflow |
| `origin` / `destination` | places for a travel task; used by whereabouts to know where you are |
| `task_list` | Google-Tasks-Liste, in die diese Aufgabe gespiegelt wird (Hybrid, siehe Google-Calendar-Sync) |
| `todo_position` | `"start"` oder `"end"`: wo der gespiegelte Google Task relativ zum Event liegt; das `due`-Datum folgt diesem Rand. Zusammen mit `todos` steuert es, ob auch der Event-Name einen Task bekommt |
| `todos` | zusätzliche `Todo`-Einträge (oder Titel-Strings), die nur als Google Tasks angelegt werden; braucht `task_list` |
| `alarm` | ein `Alarm`, eine Liste davon oder eine Kurzform (`True`, `"start"`, `"end"`, `"-10m"`, `False`) — siehe [Alarme](#alarme) |

**Flex rules of thumb:**

- `flex=True` → compressible when the day overflows.
- `flex=False` → hard block; overflow is reported loudly.
- anchored tasks (`start=`/`until=` given) are **never** shrunk, regardless of
  `flex`.
- open tasks (`flex=True`, no `until`/`duration`) stretch as slack but are never
  trimmed themselves.

### Alarme

Jedes Event kann klingeln. Der Alarm ist Teil des Tasks, nicht der App — die
App fuehrt nur aus, was im Plan steht:

```python
from dir3 import alarm, task

task("Fajr", start=prayer.fajr, duration="30m",
     alarm=alarm(speak=True, sound="adhan.mp3"))

task("Deep Work", start=time(9), duration="2h",
     alarm=alarm(when="end", offset="-10m", label="Aufraeumen"))

task("Lernen", start=time(19), duration="1h",
     alarm=[alarm("start"), alarm("end", speak=True)])  # mehrere

task("Stiller Block", start=time(13), duration="1h", alarm=False)
```

Kurzformen: `alarm=True` / `"start"` (Standard), `"end"`, `"-10m"`,
`"start-15m"`, eine Liste oder ein Dict. `offset` ist relativ zum Anker;
ein negatives Vorzeichen klingelt **vor** dem Event.

| Feld | Bedeutung |
|------|-----------|
| `when` | `"start"` (Default) oder `"end"` |
| `offset` | `"-10m"`, `"1h30m"`, Minuten oder `timedelta` |
| `label` | Titel auf dem Alarm-Screen (Default: Eventname) |
| `sound` | `"system"`, Assetname (`"adhan.mp3"`), `content://…`, `"random"` |
| `sounds` | Pool fuer `sound="random"` |
| `speak` / `speak_text` | Eventname (oder eigener Text) per TTS vorlesen |
| `volume` | 0–100; `None` = Geraetelautstaerke |
| `crescendo` / `crescendo_seconds` | langsam lauter werden |
| `vibrate` / `vibration` | `default`, `short`, `long`, `heartbeat`, `off`, `custom:0,400,200` |
| `snooze_minutes` / `snooze_limit` | Snooze-Dauer und Anzahl (`0` = unbegrenzt) |
| `dismiss` | `button`, `swipe`, `math`, `flip`, `shake`, `power`, `volume` |
| `dismiss_math` | `easy`, `medium`, `hard` |
| `full_screen` | Vollbild-Wecken (Default `True`) |
| `pre_notify_minutes` | Vorab-Hinweis vor dem Alarm |
| `background` | `black`, `dark` oder `#rrggbb` |
| `flashlight` | Taschenlampe blinken (Kamera-Recht) |
| `silent_override` | auch im Stumm-/DND-Modus klingeln |
| `enabled` / `skip_next` | Alarm behalten, aber einmal aussetzen |
| `repeat` | Wochentage fuer Standalone-Alarme; Event-Alarme folgen dem Plan |

**Automatische Weck-Alarme.** Ohne eigenes `alarm=` klingeln Fajr, Tahajjud,
Suhoor/Sahur, Imsak und Qiyam automatisch an ihrem Start (05:00–12:00 bzw.
ab 21:00). Sind sie **hintereinander** (Tahajjud → Witr → Suhoor → Fajr),
klingelt nur der erste; eine echte Luecke startet einen neuen Alarm. Das ist
in `WakeAlarmPolicy` implementiert und laesst sich pro Planfile steuern:

```python
alarms = {"chain_gap_minutes": 45}      # laengere Nachtkette
alarms = False                           # keine Automatik
alarm_policy = WakeAlarmPolicy(template=alarm(speak=True, sound="adhan.mp3"))
```

`alarm=False` am Task schaltet einen einzelnen Event stumm, auch wenn die
Policy ihn wecken wuerde. Standard-`chain_gap_minutes` ist 30.

Die Android-App setzt diese Spezifikation in echte `AlarmManager`-Alarme um;
`dir3 export` loest sie in absolute `trigger`-Zeiten auf. Andere Senken
(Browser, Desktop) koennen dieselbe JSON-Datei lesen.

### Whereabouts - where am I?

A travel task carries `origin` and `destination`. `Whereabouts` replays those
trips and answers where you are at a given moment:

```python
from datetime import time, timedelta
from dir3 import Whereabouts, task

tasks = [
    task(
        "Weg: Zuhause → Uni",
        start=time(8, 0),
        duration=timedelta(minutes=30),
        origin="Zuhause",
        destination="Uni",
    ),
    task(
        "Weg: Uni → Zuhause",
        start=time(17, 0),
        duration=timedelta(minutes=30),
        origin="Uni",
        destination="Zuhause",
    ),
]

where = Whereabouts(tasks)
where.at(time(9, 0))            # "Uni"
where.is_at("Zuhause", time(9, 0))  # False
where.at(time(8, 15))           # None - in transit
where.in_transit_at(time(8, 15))    # True
where.trips_to("Zuhause")       # the homecoming trip(s)
```

dir3 does **not** assume that you are at a place just because a task happens
there. Only a trip with that `destination` moves you. The first travel marker's
`origin` is the starting place; a skipped trip does not move you. Pass
`ctx=ctx` when the trip times use anchors, or construct `Whereabouts` from a
compiled `PlanDay`. `where_am_i(tasks, at=...)` is a one-off shortcut.

### Homecoming routines

`shower_after_homecoming` and `dinner_after_homecoming` ask `Whereabouts` which
trips end at `HomeSettings.home_place` and insert their routine in the first
free slot after each arrival. Both are skipped when there is no trip home:

```python
from datetime import time, timedelta
from dir3 import HomeSettings, dinner_after_homecoming, shower_after_homecoming, task

HOME = HomeSettings(
    shower_minutes=15,
    latest_start=time(22, 30),
    home_place="Zuhause",
    dinner_minutes=30,
)

def my_day(ctx):
    tasks = [
        task("Arbeit", start=time(9, 0), duration=timedelta(hours=8)),
        task(
            "Weg: Arbeit → Zuhause",
            start=time(17, 0),
            duration=timedelta(minutes=30),
            origin="Arbeit",
            destination="Zuhause",
        ),
    ]
    tasks = shower_after_homecoming(tasks, HOME, ctx=ctx)
    return dinner_after_homecoming(tasks, HOME, ctx=ctx)
```

On fasting days pass Maghrib as `not_before`: dinner then waits until Maghrib
when you are already home, and otherwise follows the homecoming trip when it
arrives later. If the return event is skipped via `unless`, both routines
inherit the same predicates. A homecoming task needs a concrete `start` and a
`duration` or `until`; otherwise dir3 cannot know when the person arrived. The
homecoming module stays separate from `Whereabouts`: it only reacts to arriving
home, while `Whereabouts` is the general location API.

### Sıla-i Rahim (صلة الرحم)

`SilaRahimSettings` und `sila_rahim(sched, settings)` legen einen Block für
die Familienbande an. Der Standardname ist die lateinische Schreibweise
**„Sıla-i Rahim“**; mit `SilaRahimSettings(name="صلة الرحم")` erscheint wieder
die arabische Schrift. Ohne expliziten Start endet der Block mit Isha: ein
60-Minuten-Block beginnt also 60 Minuten vor dem Adhan.

```python
from dir3 import SilaRahimSettings, sila_rahim

minute, block = sila_rahim(sched, SilaRahimSettings(minutes=60))
tasks.append(block)
```

`start=` akzeptiert das geplante Isha (`isha[0] - 60`), ein `time`, `"HH:MM"`
oder Minuten seit Mitternacht. Der Block ist ein normaler `Task` und lässt
sich in jedem `@day` platzieren.

Für einzelne Anrufe gibt es eine Kontaktliste. `Relative` hält Name und
durchschnittliche Gesprächsdauer; `buffer_minutes` kommt pro Anruf für
Begrüßung, Nummer suchen und Verabschieden dazu. `sila_rahim_events` erzeugt
pro ausgewähltem Kontakt einen Task und legt die Anrufe hintereinander; ohne
`start` endet der letzte Anruf mit Isha.

```python
from dir3 import Relative, SilaRahimSettings, sila_rahim_events, under

settings = SilaRahimSettings(
    relatives=(
        Relative("Anne", 40),
        Relative("Baba", 30),
        Relative("Babanne", 10),
        Relative("Babadede", 5),
    ),
    buffer_minutes=10,
)
events = sila_rahim_events(sched, settings, whom=under("Babanne"))
tasks.extend(block for _, block in events)
```

`whom` wählt aus: `None` = alle, `"random"` = einer zufällig, ein Name oder
Tupel von Namen, ein Index/`range(0, 2)`/`slice`, `under("Babanne")` = alle
nach ihr in der Liste, oder eine eigene Funktion
`lambda relative, index: ...`. Die Auswahl ist nur ein Filter; **wann** die
Anrufe stattfinden, entscheidet weiterhin der Plan (z. B. samstags im
`@day`). Unbekannte Namen und Indizes werfen einen `ValueError`, damit ein
Tippfehler keinen Anruf stillschweigend verschluckt.

### Day, week, month — patterns

```python
day("Name", task(...), task(...), start=morning_anchor)   # builder
@day(name="Mein Tag", start=time(9, 0))                   # decorator (start also works)
def my_day(ctx): return [task(...), ...]

week(mon=..., tue=..., ..., sun=...)      # one pattern per weekday
month(week_1, week_2)                     # a repeating month unit
```

The `@day(start=…)` decorator pins the day's start anchor instead of chaining the
first task.

### Calendar — your whole life as one function

`@calendar` takes a `(date) -> day_pattern | None` function. `None` = free day.
Every calendar entry is just a branch in code:

```python
@calendar
def lebensjahr(today):
    if today in PRUEFUNGEN: return pruefung
    if today in FREIE_TAGE: return None
    if today.weekday() >= 5: return wochenende
    return schul
```

See `examples/complete_year.py` — a full year as *one* function.

### Anchors

- `@anchor` on your own function → `(ctx) -> time`; register it and use it in any
  task.
- `midnight` / `next_day_start` (end-of-day marker).
- `next_event` — the softest anchor of all: `task("Sleep", until=next_event)`
  runs until the **first event of the next active day** (free days are skipped,
  it carries past midnight, tracks the sun for e.g. `prayer.fajr`).
- `prayer.*` — `prayer.fajr/sunrise/dhuhr/asr/maghrib/isha` (module-level
  anchors). `sun.*` — `sun.sunrise/sunset`.
- `named_anchor(...)` / `register(...)` / `all_anchors()` for manual registration.

### Context

Day functions receive a `ctx` with the date, the prayer schedule, sun times,
weather data and `ctx.schedule(ctx)` helpers:

```python
@anchor
def iftar(ctx):
    return ctx.prayer.schedule(ctx).maghrib     # fast-break with the sun
```

Predicates for `unless`, e.g. `regnet(ctx)` → weather-driven days
(see `examples/autopilot.py`).

## Engine semantics

- **Chaining:** tasks line up after each other; `space` inserts a gap.
- **Overflow:** if everything does not fit until 24:00 the compiler trims
  `flex`/unanchored tasks **from the end backwards** (only `active`, non-open,
  `flex=True`, non-anchored tasks with a duration), then reports the remainder
  as `⚠ Überlauf`.
- **Carry:** a carried event (sleep `until=next_event`) intentionally runs into
  the next morning — that is not overflow.
- **Post-midnight:** early hours (e.g. Tahajjud) and late Isha roll to the next
  day instead of erroring.
- **Pinned events** (prayers, hard blocks) never move.

## Examples

| file | shows |
|------|-------|
| `examples/pray_week.py` | a whole prayer-based week: 5 Salawat (5 min before the Adhan, Rakat×4 min) plus Qaylulah, weekday & weekend variants |
| `examples/dynamic_sleep.py` | `until=next_event` — sleep until tomorrow's first event |
| `examples/tahajjud_suhoor.py` | night blocks anchored to Fajr: Suhoor on Mo/Th, Tahajjud on Fri |
| `examples/sunnah_sleep.py` | season-aware sleep plan: Tahajjud/Witr, morning sleep and Kaylûle |
| `examples/ramadan.py` | a day from sun/moon-derived anchors: `imsak`, `iftar` |
| `examples/autopilot.py` | data-driven plan: weather, energy log, gym hours, deadlines |
| `examples/complete_year.py` | one `@calendar` function for a whole year |
| `examples/simple.py` | one month composed from reusable week modules |
| `examples/public_holidays_week.py` | a `@calendar` timeline: legal holidays free, weekends lighter, Mon-Fri work |
| `examples/templates/public_holidays.py` | legal-holiday engine via the `holidays` library (country + subdivision, works offline) |
| `examples/templates/workday_templates.py` | workday / weekend templates — deep work that dissolves on public holidays via `unless=is_holiday` |
| `examples/templates/holiday_templates.py` | free-day template: a holiday follows sun & prayer, not the clock |

The usual plumbing lives under `examples/templates/` (reusable day factories:
`working`, `at_home`, `hang_out`, `pray_based_home_routine`) and
`examples/weeks/` (`routine_week`, `pray_based_week`); the runnable planfiles
above compose them.

```bash
dir3 examples/complete_year.py --until 365
pip install holidays
dir3 examples/public_holidays_week.py --offline --until 14
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .[dev]
python -m pytest tests/        # 420 tests
ruff check src tests examples
```

Cross-platform: `tests/test_portability.py` simulates the machine-dependent
failure modes (legacy console encodings, missing system tzdb, read-only/corrupt
cache dirs, non-ASCII planfiles) so they fail *before* hitting a real machine.
`.github/workflows/ci.yml` runs the whole suite on ubuntu/macOS/Windows and
Python 3.10/3.12/3.14 plus a full-offline CLI smoke test.

`flake.nix` runs the tests via `pytestCheckHook` in the sandboxed build. The
output forces UTF-8 (`errors="replace"`), so rendering never dies on legacy
consoles (Windows cp1252) - set `DIR3_DEBUG=1` to see full tracebacks instead
of the compact error message.