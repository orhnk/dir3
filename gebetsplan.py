"""Studienwoche (TU Berlin): Vorlesungen/Tutorien fest, Gebete passend dazu.

Gebete: Der Adhan ist der Anker; Wudu 3 min danach, dann 4 min pro Rakah.
Voll (nicht kritisch) nach Hanafi: Fajr 4, Dhuhr 10, Asr 8, Maghrib 5, Isha
13 Rakats (Sunnah + Fardh + Witr, ohne Nafl). In kritischen Zeiten nur Fardh:
2/4/4/3/4. Liegt in den 15 min vor dem Adhan kein Event, gilt das als Freizeit
und das Gebet beginnt direkt am Adhan (0 min Weg); ueberlappt ein Event dieses
Fenster, ist es keine Freizeit und es gelten 10 min Weg zur Moschee; passt das
nicht, wird allein gebetet. Unter 30 min verfuegbarem Fenster gibt es immer
keine Moschee.

Vorlesungen: Der offizielle 2-h-Block wird als 1 h 45 angezeigt, die letzten
15 min bleiben frei. Die ersten 5 min duerfen fuer Gebete genutzt werden;
ein Gebet darf sich dafuer bis zu 5 min in den Vorlesungsanfang hineinziehen,
die Vorlesung beginnt dann entsprechend spaeter (kein Ueberlappen). Wuerde
ein Gebet sonst in den letzten 30 min vor der naechsten Grenze starten, wird
die Vorlesung an dieser Stelle unterbrochen, das Gebet dort platziert und mit
"⛓️‍💥" markiert. Vorlesungsbrueche sind immer allein und nur Farz. Asr wird
in den letzten 45 min vor Maghrib nur als Farz gebetet und nennt zusaetzlich
"Kerahat"; wuerde Asr sonst bis in den Kerahat warten, bricht es die Vorlesung,
wenn der Bruch Kerahat vermeidet.

Fajr: fester Block 45 min vor Sonnenaufgang, 30 min lang. Schlaf ist
grundsaetzlich zwischen 23:00 (bzw. nach Isha und den Abendroutinen) und dem
ersten Event des Folgetags. Nach Fajr wird nicht geschlafen; der Tag beginnt
mit Fruehstueck und Weg. Die Nacht (Maghrib bis Fajr-Adhan) bestimmt die
Saison: SHORT (< 7 h), BALANCED (7-13 h) oder LONG (> 13 h). Tahajjud gibt es
in jeder Nacht ausser SHORT im letzten Drittel, so spaet wie moeglich vor dem
Suhoor; Dauer, Witr und Suhoor kommen aus den Settings. In SHORT-Naechten
entfaellt Tahajjud, Witr liegt direkt vor dem Schlafen. An Ayyam al-Biyd
(13.-15. Hijri) gibt es Suhoor an jedem Wochentag; der Suhoor heisst dann
"Suhoor 🌕️" und wird mango-orange (GCal Tangerine) gefaerbt. Die Kaylûle
(20-25 min, nie ueber 30) liegt in der fruehen Nachmittagssenke um 14:00 und
nie nach Asr; gibt es keinen Platz vor Asr, entfaellt sie. An
Nicht-Fastentagen gibt es ab Sonnenaufgang 40-50 min Fruehstueck, passend zur
Abfahrt des vorgegebenen Busses; Suhoor und Fruehstueck tragen das
Besteck-Icon 🍽️.

Wochenroutine: Montag bis Donnerstag (ausser Mittwoch) nach dem Fruehstueck
zur Uni und spaetestens nach dem Maghrib-Gebet bzw. dem letzten
Vorlesungsende von der Uni nach Hause. Isha wird in der Moschee gebetet. Mittwochs
vereinigt ein Event
"Weg & Einkaufen" Rueckweg und Einkauf (30 min laenger), so dass es um 17:00
zuhause ist. Faellt ein Adhan in die Zeit dafuer und waere das Gebet beim
Einkaufen mehr als 30 min zu spaet dran, wird es puenktlich an der Uni
gebetet und erst danach gegangen; sonst bleibt es bei 17:00. Zuhause folgt
1 h Kochen - kochen ist brechbar: Gebete an ihrem Adhan brechen es ab und
der Rest laeuft danach weiter. Das Abendsessen liegt sofort nach dem Kochen
und vor Isha; wird Isha puenktlich (unter 30 min nach Adhan) waehrend des
Essens erwartet, kommt das Gebet zuerst. Montag folgt 1 h Aufräumen nach
Isha. Samstags und sonntags gibt es keine Wege-Events; an beiden
Tagen entfaellt auch das Abendessen. Samstags wird stattdessen vor dem
Isha-Gebet geduscht. Sonntags bleibt das Netzwerken 18:00-22:30 (ohne Weg).
Freitag entfaellt der Weg zur Bibliothek: Nach dem Fruehstueck folgt das
Jumuah-Duschen (25 min), danach "Persoenliche Hygiene" (15 min); erst dann
beginnt "GldP Selbstlernen" zuhause. Jumuah beginnt mit dem Bus 45 min
vorher, nach dem Gebet geht es 45 min zurueck. Isha beginnt an jedem Tag um
20:00, wenn der Adhan davor liegt; ruft der Adhan spaeter, dann puenktlich
zum Adhan. Nach Isha folgt (ausser sonntags) 15 min Hitam; K, R und P werden
als Google Tasks am Hitam-Ende angelegt. Nach jedem Rueckweg nach Hause folgt
Duschen (15 min) im ersten freien Platz, spaetestens um 22:30, danach
Abendessen (30 min). An Fastentagen beginnt das Abendessen nicht vor Maghrib;
kommt der Rueckweg spaeter, direkt danach. Der Schlaf beginnt erst nach diesen
Abendroutinen.

Wege: Start, Ziel und Linienfolge stehen im Plan; Abfahrt, Ankunft und Dauer
kommen live aus ``ctx.transit``. Es gibt keine festen Reisezeiten. Findet die
API keine Verbindung, entfaellt der Weg.

Fastentage (Mo/Do und Ayyam al-Biyd) haben kein Fruehstueck. Suhoor bleibt.
In Ramadan fastet jeder Tag: Suhoor vor Fajr, Iftar nach Maghrib, Tarawih
nach Isha bzw. Hitam; Tahajjud und Witr werden in der Nacht ebenfalls
geplant, an Laylat al-Qadr ersetzt Qiyam das Tahajjud. Das normale
Abendessen entfaellt. An Eid al-Fitr und den
Qurban-Tagen wird nicht gefastet. Am ersten Qurban-Tag kommen Eid-Gebet,
Opfer und Fleischverteilung dazu.

Freitag: Dhuhr heisst Jumuah und dauert 60 min. Die Zeit ist 12:30 in der
Winterzeit (CET) und 13:30 in der Sommerzeit (CEST); 45 min vorher faehrt
der Bus zur Moschee (45 min), nach dem Gebet geht es 45 min zurueck.

Sonntag: 18:00-22:30 Netzwerken in der Moschee, ohne Wegevent. Isha folgt
erst nach dem Netzwerken (22:30), sofern der Adhan nicht spaeter liegt; sonst
bleibt es beim Adhan. Danach geht es (ohne eigenes Wegevent) nach Hause.

Farben: Am-Adhan-Moschee Basilikum, verschoben-Moschee Pistazie, allein
(ob am Adhan oder verschoben) Flamingo, dringend (Kerahat/kritisch) Tomate.
AnalinA, ROBS, IaD und GldP haben je eine eigene Farbe; Weg ist Graphit,
Netzwerken Mandarin.

Gebetszeiten: Muslim World League (method 3, Shafi-Asr), Standort gepinnt (Berlin).

    dir3 gebetsplan.py                 # syncen (Config + Horizont stehen unten)
    dir3 gebetsplan.py --compile       # nur drucken
    dir3 gebetsplan.py --clear         # von dir3 angelegte Events entfernen

Die GCal-Credentials liegen in ``plan/calendar.py`` (nicht eingecheckt).
``--config``/``--until`` sind im ``sync``-Block hinterlegt und koennen per
CLI-Flag ueberschrieben werden.
"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

from dir3 import (
    BasilPistazienColorPolicy,
    FixedPrayer,
    HomeSettings,
    MealSettings,
    NightSettings,
    PrayerPlanner,
    PrayerPlanSettings,
    QiyamSettings,
    QurbanSettings,
    RamadanSettings,
    Route,
    SilaRahimSettings,
    SleepPlanSettings,
    Todo,
    Whereabouts,
    WitrSettings,
    breakfast,
    classify_night,
    cleanup_after_dinner,
    day,
    dinner_after_homecoming,
    is_eid_al_adha,
    is_fasting_day,
    is_ramadan,
    laylat_al_qadr_qiyam,
    next_event,
    night_events,
    qurban_events,
    ramadan_events,
    route_end,
    route_way,
    shower_after_homecoming,
    shower_before,
    sila_rahim,
    tarawih,
    task,
    week,
    witr,
)
from dir3.color import BASIL_SLOT, PRAYER_NAMES, GCalColor, name_slot, normalize_event_name
from dir3.intervals import shift, split_blocks
from dir3.timeutils import format_minutes, time_from_minutes, to_minutes

_mins = to_minutes
_fmt = format_minutes
_at = time_from_minutes

# Muslim World League (method 3), Shafi-Asr: Fajr 18°, Isha 17°
prayer = {"method": 3, "school": 0, "method_auto": False}

# Standort fest gepinnt (Berlin), damit die Zeiten nicht mit der IP-Geolocation driften
location = (52.5323, 13.3846, "Europe/Berlin")

# Defaults für den Sync-Lauf: `dir3 gebetsplan.py --sync` reicht.
# Die Config-Datei (OAuth-Credentials) wird relativ zum Planfile aufgelöst.
sync = {"config": "plan/calendar.py", "until": 7}

# Alarme: Fajr (der feste Block vor Sonnenaufgang), Tahajjud und Suhoor wecken
# automatisch. Die Nachtkette Tahajjud -> Witr -> Suhoor -> Fajr klingelt nur
# einmal, beim ersten Event. Die App liest das ueber `dir3 serve`.
alarms = {"chain_gap_minutes": 30}

# Einmaliger Sıla-i-Rahim-Termin (60 min vor Isha). Datum anpassen oder den
# Block in einer anderen @day-Funktion einbauen; die Bibliotheks-Option ist
# ``sila_rahim`` mit ``SilaRahimSettings``.
SILA_RAHIM_DATE = date(2026, 11, 14)
SILA_RAHIM = SilaRahimSettings(minutes=60)


# Farben: alle Gebete/Jumuah Basil; jede Vorlesungsmodul-Familie eine eigene
# Farbe; Weg und Netzwerken eigene Farben. Andere Events nie Basil.
class GebetsplanColorPolicy:
    """Gebete nach Status (Basilikum/Pistazie/Flamingo/Tomate),
    Modulgruppen und Wege mit festen Farben."""

    prayer_policy = BasilPistazienColorPolicy()

    def color_for(self, name, index):
        normalized = normalize_event_name(name)
        head = normalized.split(" ", 1)[0]
        if "🌕" in normalized or "eyyam" in normalized or "ayyam" in normalized:
            return GCalColor.TANGERINE
        if normalized.startswith("witr"):
            return GCalColor.BASIL
        if normalized.startswith("kayl"):
            return GCalColor.LAVENDER
        if head in PRAYER_NAMES:
            return self.prayer_policy.color_for(name, index)
        if normalized.startswith("weg"):
            return GCalColor.GRAPHITE
        if "analina" in normalized:
            return GCalColor.PEACOCK
        if "robs" in normalized:
            return GCalColor.TOMATO
        if "iad" in normalized:
            return GCalColor.BLUEBERRY
        if "gldp" in normalized:
            return GCalColor.GRAPE
        if "netzwerken" in normalized:
            return GCalColor.TANGERINE
        slot = name_slot(normalized)
        return GCalColor.LAVENDER if slot == BASIL_SLOT else slot


color_policy = GebetsplanColorPolicy()

# Vorlesungen je Wochentag (0 = Montag ...): Start, Ende, Raum + Kurs
LECTURES = {
    0: [
        ("14:00", "16:00", "HE101 AnalinA (Winkert)"),
        ("16:00", "18:00", "A053 ROBS"),
    ],
    1: [
        ("10:00", "12:00", "HE101 AnalinA (Keiper)"),
        # auskommentiert (Ueberschneidung mit AnalinA):
        # ("10:15", "12:00", "EB 301 GldP (Vorlesung)"),
        ("16:00", "18:00", "A151 IaD"),
    ],
    2: [
        ("10:00", "12:00", "MA 751 IaD (Uebung)"),
        ("12:00", "14:00", "E-N732 GldP (Uebung)"),
    ],
    3: [
        ("10:00", "12:00", "EN 732 ROBS (Uebung, Marvin)"),
        ("12:00", "14:00", "HE101 AnalinA (Keiper)"),
        ("16:00", "18:00", "HE101 AnalinA (Uebung)"),
    ],
    # Freitag: kein Weg zur Bibliothek. GldP Selbstlernen beginnt nach dem
    # Fruehstueck (siehe _lectures_for).
}

# AnalinA Space: Wenn du eine Frage bei den Aufgaben nicht verstanden hast,
# schau dir die Wissensimpulse an.

# Ausnahmen: AnalinA-Uebung am 22.10. und 29.10. von 18:00-20:00
AUSNAHMEN = {
    "2026-10-22": (("16:00", "18:00"), ("18:00", "20:00")),
    "2026-10-29": (("16:00", "18:00"), ("18:00", "20:00")),
}

# Freitag: Dhuhr ist Jumuah. 12:30 in der Winterzeit (CET, Dhuhr "frueh"),
# 13:30 in der Sommerzeit (CEST, Dhuhr "spaet"). Dauer und Route sind
# Konstanten, damit sich der Weg zur Moschee leicht anpassen laesst.
JUMUAH_EARLY = 12 * 60 + 30
JUMUAH_LATE = 13 * 60 + 30
JUMUAH_DURATION = 60
JUMUAH_TRAVEL = 45

# Wege: Abfahrt, Ankunft und Dauer kommen ausschliesslich aus der
# Verkehrsmittel-API (ctx.transit). Die Suche wird nur zeitlich gestreut, um
# leere Antworten des Providers abzufangen; es gibt keine festen Fahrzeiten.
BREAKFAST = MealSettings(breakfast_min_minutes=40, breakfast_max_minutes=50)
PLACE_HOME = "Zuhause"
PLACE_UNI = "Uni"
PLACE_MOSQUE = "Moschee"
HOME = HomeSettings(home_place=PLACE_HOME)
SHOPPING_EXTRA = 30
COOKING_MINUTES = 60
WEDNESDAY_HOME = 17 * 60  # Zuhause um 17:00, danach Kochen
WEDNESDAY_WAY = "Weg & Einkaufen: TU → Zuhause (136/M45)"
NETWORK_END = 22 * 60 + 30
#: Isha starts at 20:00 when the Adhan is earlier; a later Adhan wins.
ISHA_AT = 20 * 60
JUMUAH_SHOWER_MINUTES = 25
PERSONAL_HYGIENE_MINUTES = 15
PERSONAL_HYGIENE_NAME = "Persönliche Hygiene"
HITAM_MINUTES = 15

# Vom User vorgegebene Routen: Start, Ziel, Linien in Reihenfolge.
# Feste Wegzeiten (Minuten): zwischen Uni, Haus und Moschee gelten feste
# Verbindungen, die nicht mehr beim Provider angefragt werden - die Dauer
# steht fest, Start/Ankunft rechnen sich.
UNI_ROUTE = Route("Mertensstr.", "Ernst-Reuter-Platz", ("136", "M45"), 55)
UNI_HOME_ROUTE = Route("Ernst-Reuter-Platz", "Mertensstr.", ("M45", "136"), 50)
JUMUAH_ROUTE = Route(
    "Mertensstr./Goltzstr.", "Galenstr.", ("X36", "671"), JUMUAH_TRAVEL
)
JUMUAH_HOME_ROUTE = Route(
    "Galenstr.", "Mertensstr./Goltzstr.", ("671", "X36"), JUMUAH_TRAVEL
)

PRAYER_PLAN = PrayerPlanSettings(
    mosque_travel=0,
    mosque_travel_after_lecture=10,
    buffer_overrides={"Maghrib": 20},
    fixed_prayers={"Fajr": FixedPrayer("sunrise", 45, 30, "Fajr (Moschee)")},
    skip_weekday_prayers={4: frozenset({"Dhuhr"})},
    # Isha an jedem Tag um 20:00, wenn der Adhan davor liegt; ein spaeterer
    # Adhan bleibt der Anker (dann direkt nach dem Adhan). Sonntags folgt Isha
    # erst nach dem Netzwerken (22:30).
    not_before={
        (weekday, "Isha"): NETWORK_END if weekday == 6 else ISHA_AT
        for weekday in range(7)
    },
)
PLANNER = PrayerPlanner(PRAYER_PLAN)
NIGHT = NightSettings(
    fajr_lead=PRAYER_PLAN.fixed_prayers["Fajr"].lead,
    regular_weekdays=frozenset(range(7)),
)
SLEEP = SleepPlanSettings()
WITR = WitrSettings(minutes=SLEEP.witr_minutes, name=SLEEP.witr_name)
QIYAM = QiyamSettings(minutes=45, before_fajr=60, name="Qiyam al-Layl")
QAYLULAH_NAME = "Kaylûle"
LECTURE_BUFFER = 10
FRIDAY_SELF_STUDY_MINUTES = 120
# Suhoor and Tarawih are placed by the generic night helpers below; only
# Iftar remains a Ramadan-specific block.
RAMADAN = RamadanSettings(
    iftar_delay=15,
    include_suhoor=False,
    include_tarawih=False,
)
QURBAN = QurbanSettings(
    eid_prayer_name="Eid-Gebet",
    sacrifice_name="Qurban",
    distribution_name="Fleisch verteilen",
)


def _is_fasting(day):
    return is_fasting_day(
        day,
        weekdays=NIGHT.suhoor_weekdays,
        ayyam_al_biyd=NIGHT.ayyam_al_biyd,
    )


def _friday_morning_end(sched, fasting):
    """Ende von Fruehstueck, Duschen und Hygiene (Minuten)."""
    start = _mins(sched.sunrise)
    if not fasting:
        start += BREAKFAST.breakfast_minutes
    return start + JUMUAH_SHOWER_MINUTES + PERSONAL_HYGIENE_MINUTES


def _season(sched):
    """Season and its sleep constants, derived from the Maghrib-Fajr night."""
    night = (_mins(sched.fajr) - _mins(sched.maghrib)) % (24 * 60)
    season = classify_night(night, SLEEP)
    return season, getattr(SLEEP, season.lower())


def _lectures_for(day, sched=None):
    if day.weekday() == 4:
        # Freitag: erst Fruehstueck, Jumuah-Duschen und Persoenliche Hygiene,
        # dann GldP Selbstlernen zuhause.
        start = (
            10 * 60
            if sched is None
            else _friday_morning_end(sched, _is_fasting(day))
        )
        return [(_fmt(start), _fmt(start + 120), "GldP Selbstlernen")]
    rows = list(LECTURES.get(day.weekday(), []))
    swap = AUSNAHMEN.get(day.isoformat())
    if swap:
        old, new = swap
        rows = [(new[0], new[1], label) if (s, e) == old else (s, e, label) for s, e, label in rows]
    return rows


def _display_lectures(day, sched=None):
    """Event-Zeiten: 1 h 45, die letzten 15 min des 2-h-Blocks bleiben frei."""
    return [
        (_fmt(start), _fmt(end), label)
        for start, end, label in PLANNER.display_blocks(_lectures_for(day, sched))
    ]


def _uni_way(ctx, day, sched, *, breakfast_today=True):
    """Nach dem Fruehstueck (oder direkt nach Fajr) zur Uni.

    An Essenstagen wird ab ``Sonnenaufgang + 40 min`` gesucht, damit das
    Fruehstueck je nach Busabfahrt 40-50 min dauern kann.  An Fastentagen
    faellt nur das Essen weg; der Weg startet mit Sonnenaufgang.
    """
    if breakfast_today:
        start = _mins(sched.sunrise) + BREAKFAST.breakfast_minutes
        query_start = _mins(sched.sunrise) + BREAKFAST.breakfast_min_minutes
    else:
        # Kein Fruehstueck: direkt nach dem Fajr-Block, der 15 min vor
        # Sonnenaufgang endet.
        start = _mins(sched.sunrise)
        query_start = start
    way = route_way(
        ctx,
        "Weg: Mertensstr. → TU (136/M45)",
        UNI_ROUTE,
        start,
        query_start=query_start,
        origin=PLACE_HOME,
        destination=PLACE_UNI,
    )
    if way is None:
        return query_start, None
    return _mins(way.start), way


def _jumuah_start(day, tzinfo):
    """12:30 in der Winterzeit, 13:30 in der Sommerzeit."""
    noon = datetime.combine(day, time(12), tzinfo=tzinfo)
    return JUMUAH_LATE if noon.dst() else JUMUAH_EARLY


def _jumuah_events(ctx, sched):
    day = ctx.plan_date
    start = _jumuah_start(day, ctx.location.tzinfo)
    azan = _mins(sched.dhuhr)
    jumuah = task(
        f"Jumuah (verschoben: Adhan {_fmt(azan)} → {_fmt(start)})",
        start=_at(start),
        duration=timedelta(minutes=JUMUAH_DURATION),
        flex=False,
        overlap=True,
    )
    back_start = start + JUMUAH_DURATION
    way = route_way(
        ctx,
        "Weg: Zuhause → Moschee (X36/671)",
        JUMUAH_ROUTE,
        start,
        deadline=start,
        origin=PLACE_HOME,
        destination=PLACE_MOSQUE,
    )
    back = route_way(
        ctx,
        "Weg: Moschee → Zuhause (671/X36)",
        JUMUAH_HOME_ROUTE,
        back_start,
        origin=PLACE_MOSQUE,
        destination=PLACE_HOME,
    )
    events = [(_mins(jumuah.start), jumuah)]
    if way is not None:
        events.insert(0, (_mins(way.start), way))
    if back is not None:
        events.append((_mins(back.start), back))
    return events


def _hitam_events(day, isha):
    """Hitam direkt nach Isha (nicht sonntags); K/R/P als Google Tasks.

    Hitam selbst ist nur der Eventname - es entsteht kein eigener Google
    Task fuer das Event, wohl aber die drei Aufgaben an seinem Ende.
    """
    if day.weekday() == 6 or isha is None:
        return []
    start = isha[1]
    return [
        (
            start,
            task(
                "📚 Hitam",
                start=_at(start),
                duration=timedelta(minutes=HITAM_MINUTES),
                flex=False,
                task_list="Hitam",
                todos=(
                    Todo("K", todo_position="end"),
                    Todo("R", todo_position="end"),
                    Todo("P", todo_position="end"),
                ),
            ),
        )
    ]


def _netzwerken_events(end=NETWORK_END):
    """Netzwerken am Sonntag von 18:00 bis ``end`` (Isha folgt danach)."""
    netzwerken = task(
        "Netzwerken",
        start=_at(18 * 60),
        until=_at(end),
        flex=False,
        overlap=True,
    )
    return [(_mins(netzwerken.start), netzwerken)]


def _punctual_slot_title(name, sched, slot_start, slot_end, azan):
    """Titel fuer ein Gebet, das genau zum Adhan gebetet wird (ohne Verschiebung)."""
    deadline = PLANNER.deadline_for(name, sched, azan)
    return PLANNER.slot_title(
        name,
        azan,
        slot_start,
        slot_end,
        deadline,
        0,
        prayer_start=azan + PLANNER.settings.wudu,
        mode="nearby",
    )


def _transit_prayers(sched, way_start, way_end):
    """Gebete, deren Slot (Adhan bis Beten) in den Rueckweg hineinragt.

    ``way_start``/``way_end`` sind Minuten; zurueck kommen (Name, Adhan) fuer
    Gebete, die beim Weg nach Hause zu spaet waeren und deshalb an der Uni
    puenktlich gebetet werden.
    """
    result = []
    uni_dur = {name: PLANNER.prayer_duration(name) for name in PLANNER.settings.order}
    for name, azan in PLANNER.azan_times(sched).items():
        if azan >= way_end:
            continue
        if azan + uni_dur[name] <= way_start:
            continue  # Slot endet vor der Abfahrt - puenktlich an der Uni
        delay = way_end + PLANNER.settings.wudu - azan
        if delay < PRAYER_PLAN.miss_buffer:
            continue  # unter 30 Minuten - Gebet zuhause beim Ankommen
        result.append((name, azan))
    return result


def _wednesday_commute(ctx, sched):
    """Mittwoch: Rueckweg + Einkauf in einem Event, Zuhause um 17:00.

    Faellt ein Adhan in die Fahrt und waere das Gebet beim Ankommen mehr als
    30 min zu spaet, wird es puenktlich an der Uni gebetet (Slot von Adhan
    bis Beten) und erst danach gegangen - der Weg startet dann spaeter und
    die Ankunft verschiebt sich accordingly.
    """
    way = route_way(
        ctx,
        WEDNESDAY_WAY,
        UNI_HOME_ROUTE,
        _mins(sched.asr) + PLANNER.prayer_duration("Asr"),  # fruehester Abfahrt-Anker
        deadline=WEDNESDAY_HOME - SHOPPING_EXTRA,
        extra=SHOPPING_EXTRA,
        origin=PLACE_UNI,
        destination=PLACE_HOME,
    )
    if way is None:
        return None, ()
    way_start = _mins(way.start)
    way_end = route_end(way)
    catch = []
    for name, azan in _transit_prayers(sched, way_start, way_end):
        uni_end = azan + PLANNER.prayer_duration(name)
        slot_start = azan
        title = _punctual_slot_title(name, sched, slot_start, uni_end, azan)
        catch.append((name, slot_start, uni_end, title))
    if not catch:
        return way, catch
    rerouted = route_way(
        ctx,
        WEDNESDAY_WAY,
        UNI_HOME_ROUTE,
        catch[-1][2],
        extra=SHOPPING_EXTRA,
        origin=PLACE_UNI,
        destination=PLACE_HOME,
    )
    if rerouted is None:
        return way, ()  # keine Anschlussfahrt: Gebet bleibt beim Ankommen
    return rerouted, catch


def _chronological(tasks):
    """Sort a day's tasks, keeping post-midnight events at the end.

    In summer Isha can fall after midnight.  Its ``time`` is then small again
    (01:07), so a naive sort would put it before the evening routines.  The
    cutoff is the earliest regular morning event of the day (Tahajjud, Suhoor
    or the Fajr block); everything earlier belongs to the previous night.
    Isha additionally rolls when it falls before the Fajr block, even if an
    earlier night event (Tahajjud/Suhoor) makes the cutoff smaller.
    """
    evening_markers = (
        "Isha",
        "Schlafen",
        "Witr",
        "Tarawih",
        "Hitam",
        "Duschen",
        "Abendessen",
    )
    morning = [
        _mins(item.start)
        for item in tasks
        if isinstance(item.start, time)
        and not any(marker in item.name for marker in evening_markers)
    ]
    cutoff = min(morning, default=0)
    fajr = min(
        (
            _mins(item.start)
            for item in tasks
            if isinstance(item.start, time) and item.name.startswith("Fajr")
        ),
        default=cutoff,
    )

    def key(item):
        if not isinstance(item.start, time):
            return 24 * 60 + 1
        minutes = _mins(item.start)
        if item.name.startswith("Isha") and minutes < fajr:
            return minutes + 24 * 60
        return minutes + 24 * 60 if minutes < cutoff else minutes

    return sorted(tasks, key=key)


def _cooking_parts(start, minutes, blocked):
    """Kochen in Teilstuecken: Gebete (``blocked``) brechen es ab, die
    Gesamtzeit bleibt gleich - nach dem Gebet geht es weiter."""
    parts = []
    cursor = start
    need = minutes
    for block_start, block_end in sorted(blocked):
        if need <= 0 or block_end <= cursor or block_start >= cursor + need:
            continue
        part_end = min(block_start, cursor + need)
        if part_end > cursor:
            parts.append((cursor, part_end))
            need -= part_end - cursor
        cursor = max(cursor, block_end)
    if need > 0:
        parts.append((cursor, cursor + need))
    return [(part_start, part_end) for part_start, part_end in parts if part_end > part_start]


def _event_intervals(events):
    """Concrete (start, end) minutes of all timed events."""
    intervals = []
    for _, item in events:
        if not isinstance(item.start, time):
            continue
        start = _mins(item.start)
        if isinstance(item.until, time):
            end = _mins(item.until)
            if end <= start:
                end += 24 * 60
        elif item.duration is not None:
            end = start + int(item.duration.total_seconds() // 60)
        else:
            continue
        intervals.append((start, end))
    return intervals


def _cook_after_asr_start(tasks, asr_end, ctx=None):
    """When to start Sunday cooking: after Asr if home, else after the return."""
    where = Whereabouts(tasks, ctx=ctx)
    if where.is_at(PLACE_HOME, _at(asr_end)) or (
        where.initial is None and not where.trips
    ):
        return asr_end
    arrivals = [
        trip.end_minutes
        for trip in where.trips_to(PLACE_HOME)
        if trip.end_minutes >= asr_end
    ]
    return min(arrivals) if arrivals else None


def _qaylulah_event(events, slots, sched, cfg):
    """Kaylûle after Dhuhr, only if a free gap before Asr exists."""
    duration = min(cfg.qaylulah, SLEEP.max_qaylulah)
    if duration <= 0:
        return None
    dhuhr_end = next(
        (end for title, _, end in slots if title.split(" ")[0] == "Dhuhr"),
        None,
    )
    if dhuhr_end is None:
        jumuah = next(
            (item for _, item in events if item.name.startswith("Jumuah")),
            None,
        )
        if (
            jumuah is not None
            and isinstance(jumuah.start, time)
            and jumuah.duration is not None
        ):
            dhuhr_end = _mins(jumuah.start) + int(
                jumuah.duration.total_seconds() // 60
            )
    if dhuhr_end is None:
        dhuhr_end = _mins(sched.dhuhr)
    asr = next(
        (start for title, start, _ in slots if title.split(" ")[0] == "Asr"),
        None,
    )
    deadline = asr if asr is not None else _mins(sched.maghrib)
    blocked = _event_intervals(events)
    # Bevorzugt in der fruehen Nachmittagssenke um 14:00; nur wenn Asr
    # frueher kommt, rutscht die Kaylûle direkt hinter Dhuhr.
    start = shift(max(dhuhr_end + 10, SLEEP.qaylulah_target), blocked, duration)
    if start + duration > deadline - 5:
        start = shift(dhuhr_end + 10, blocked, duration)
    if start + duration > deadline - 5:
        return None
    return (
        start,
        task(
            QAYLULAH_NAME,
            start=_at(start),
            duration=timedelta(minutes=duration),
            flex=False,
            overlap=True,
        ),
    )


def _studienplan(ctx):
    day = ctx.plan_date
    weekday = day.weekday()
    sched = ctx.prayer.schedule(ctx)
    fasting = _is_fasting(day)
    season, season_cfg = _season(sched)
    extra_taken = []
    planner = PLANNER
    wednesday_way = None
    wednesday_catch = ()
    if weekday == 2:
        wednesday_way, wednesday_catch = _wednesday_commute(ctx, sched)
        if wednesday_way is not None and wednesday_catch:
            # Gebet puenktlich an der Uni statt zu spaet zuhause: der Weg
            # weicht aus, das Gebet wird vom Planner nicht nochmal versetzt.
            extra_taken.extend((start, end) for _, start, end, _ in wednesday_catch)
            skip_map = dict(PRAYER_PLAN.skip_weekday_prayers)
            skip_map[2] = frozenset(name for name, _, _, _ in wednesday_catch)
            planner = PrayerPlanner(replace(PRAYER_PLAN, skip_weekday_prayers=skip_map))
    if wednesday_way is not None:
        extra_taken.append((to_minutes(wednesday_way.start), route_end(wednesday_way)))
    if weekday == 4:
        jumuah_start = _jumuah_start(day, ctx.location.tzinfo)
        # Jumuah plus der 45-min-Rueckweg direkt danach blockieren die Zeit.
        extra_taken.append(
            (
                jumuah_start,
                jumuah_start + JUMUAH_DURATION + JUMUAH_TRAVEL,
            )
        )
    display_lectures = _display_lectures(day, sched)

    def plan_slots():
        return planner.slots(
            sched,
            day,
            lectures=_lectures_for(day, sched),
            display_lectures=display_lectures,
            extra_taken=extra_taken,
        )

    slots, breaks = plan_slots()
    if wednesday_catch:
        catch_slots = [(title, start, end) for _, start, end, title in wednesday_catch]
        slots = sorted([*slots, *catch_slots], key=lambda slot: slot[1])
    isha = next(
        ((start, end) for title, start, end in slots if title.split(" ")[0] == "Isha"),
        None,
    )
    events = []
    lectures = [(_mins(s), _mins(e), label) for s, e, label in display_lectures]
    for s, e, label in split_blocks(lectures, breaks):
        events.append(
            (
                s,
                task(
                    label,
                    start=_at(s),
                    until=_at(e),
                    flex=False,
                    overlap=True,
                ),
            )
        )
    for name, t, end in slots:
        events.append(
            (
                t,
                task(
                    name,
                    start=_at(t),
                    duration=timedelta(minutes=end - t),
                    flex=False,
                    overlap=True,
                ),
            )
        )
    night_blocks = []
    if is_ramadan(day):
        # Suhoor comes from night_events (every Ramadan day); only Iftar is
        # left to the Ramadan helper.
        events.extend(ramadan_events(day, sched, RAMADAN))
    night_sched = SimpleNamespace(
        fajr=sched.fajr,
        sunrise=sched.sunrise,
        maghrib=sched.maghrib,
        isha=time_from_minutes(isha[1]) if isha is not None else sched.isha,
    )
    night_settings = replace(
        NIGHT,
        tahajjud_minutes=season_cfg.tahajjud,
        include_tahajjud=season != "SHORT",
        include_witr=True,
        witr_minutes=SLEEP.witr_minutes,
        witr_gap=SLEEP.witr_gap,
        witr_name=SLEEP.witr_name,
        fajr_margin=SLEEP.fajr_margin,
    )
    if is_ramadan(day):
        night_settings = replace(
            night_settings,
            suhoor_weekdays=frozenset(range(7)),
            ayyam_al_biyd=False,
            force_suhoor=True,
            suhoor_minutes=RAMADAN.suhoor_minutes,
            suhoor_name=RAMADAN.suhoor_name,
        )
    qiyam_block = None
    if is_ramadan(day) and season != "SHORT":
        try:
            qiyam_block = laylat_al_qadr_qiyam(day, night_sched, QIYAM)
        except ValueError:
            qiyam_block = None
    if qiyam_block is not None:
        # On Laylat al-Qadr the Qiyam replaces Tahajjud; Witr follows it.
        night_settings = replace(
            night_settings, include_tahajjud=False, include_witr=False
        )
    night_blocks = night_events(day, night_sched, night_settings)
    events.extend(night_blocks)
    has_witr = any(
        block_task.name == SLEEP.witr_name for _, block_task in night_blocks
    )
    if qiyam_block is not None:
        events.append(qiyam_block)
        qiyam_start = qiyam_block[0]
        qiyam_end = _mins(qiyam_block[1].until)
        if qiyam_end <= qiyam_start:
            qiyam_end += 24 * 60
        witr_minute, witr_task = witr(
            night_sched, WITR, start=qiyam_end + SLEEP.witr_gap
        )
        events.append((witr_minute, witr_task))
        has_witr = True

    start = None
    way = None
    if weekday in (0, 1, 2, 3):
        start, way = _uni_way(
            ctx,
            day,
            sched,
            breakfast_today=not fasting,
        )
    if not fasting and not is_eid_al_adha(day):
        events.append(
            breakfast(
                sched,
                BREAKFAST,
                start_minutes=_mins(sched.sunrise),
                end_minutes=start,
            )
        )
    if way is not None:
        events.append((start, way))
    if weekday == 4:
        # Jumuah: erst Duschen (25 min), dann Persoenliche Hygiene (15 min).
        shower_start = (
            _friday_morning_end(sched, fasting)
            - JUMUAH_SHOWER_MINUTES
            - PERSONAL_HYGIENE_MINUTES
        )
        events.append(
            (
                shower_start,
                task(
                    HOME.shower_name,
                    start=_at(shower_start),
                    duration=timedelta(minutes=JUMUAH_SHOWER_MINUTES),
                    flex=False,
                ),
            )
        )
        hygiene_start = shower_start + JUMUAH_SHOWER_MINUTES
        events.append(
            (
                hygiene_start,
                task(
                    PERSONAL_HYGIENE_NAME,
                    start=_at(hygiene_start),
                    duration=timedelta(minutes=PERSONAL_HYGIENE_MINUTES),
                    flex=False,
                ),
            )
        )

    hitam_events = _hitam_events(day, isha)
    hitam_end = hitam_events[-1][0] + HITAM_MINUTES if hitam_events else 0
    tarawih_end = 0
    maghrib_end = next(
        (end for title, _, end in slots if title.split(" ")[0] == "Maghrib"),
        0,
    )
    last_lecture_end = max((e for _, e, _ in lectures), default=0)
    return_end = None
    if wednesday_way is not None:
        events.append((_mins(wednesday_way.start), wednesday_way))
        # Kochen startet beim Ankommen; Gebete brechen es ab und die
        # restliche Zeit laeuft nach dem Gebet weiter (60 min insgesamt).
        cook_start = route_end(wednesday_way)
        blocked = [
            (slot_start, slot_end)
            for _, slot_start, slot_end in slots
            if slot_end > cook_start and slot_start < cook_start + COOKING_MINUTES
        ]
        # Auch Hitam unterbricht das Kochen, damit es nicht ueberlappt.
        blocked.extend(
            (start, start + HITAM_MINUTES) for start, _ in hitam_events
        )
        cook_parts = _cooking_parts(cook_start, COOKING_MINUTES, blocked)
        cook_end = cook_parts[-1][1]
        for part_start, part_end in cook_parts:
            events.append(
                (
                    part_start,
                    task(
                        "Kochen",
                        start=_at(part_start),
                        until=_at(part_end),
                        flex=False,
                        overlap=True,
                    ),
                )
            )
        return_end = cook_end
        if not is_ramadan(day):
            # Abendsessen direkt nach dem Kochen, bevor das Essen kalt wird -
            # vor Isha, solange Isha nicht (unter 30 min nach Adhan) mitten
            # ins Essen faellt; dann kommt das Gebet zuerst.
            dinner_start = cook_end
            if (
                isha is not None
                and dinner_start < isha[1]
                and dinner_start + HOME.dinner_minutes > isha[0]
            ):
                dinner_start = isha[1]
            if fasting:
                dinner_start = max(dinner_start, _mins(sched.maghrib))
            events.append(
                (
                    dinner_start,
                    task(
                        HOME.dinner_name,
                        start=_at(dinner_start),
                        duration=timedelta(minutes=HOME.dinner_minutes),
                        flex=False,
                        overlap=True,
                    ),
                )
            )
    elif weekday in (0, 1, 3):
        # Zuhause spaetestens zum Maghrib-Gebet bzw. nach dem letzten
        # Vorlesungsende; Isha folgt dann um 20:00 in der Moschee.
        way = route_way(
            ctx,
            "Weg: TU → Zuhause (136/M45)",
            UNI_HOME_ROUTE,
            max(maghrib_end, last_lecture_end),
            origin=PLACE_UNI,
            destination=PLACE_HOME,
        )
        if way is not None:
            events.append((_mins(way.start), way))
            return_end = route_end(way)

    if isha is not None:
        # Hitam direkt nach Isha - oder nach dem Rueckweg, falls dieser
        # laenger als Isha dauert.
        hitam_start = max(isha[1], return_end or 0)
        if hitam_start != isha[1]:
            hitam_events = _hitam_events(day, (isha[0], hitam_start))
            hitam_end = (
                hitam_events[-1][0] + HITAM_MINUTES if hitam_events else 0
            )
    events.extend(hitam_events)
    if is_ramadan(day) and isha is not None:
        tarawih_start = max(
            isha[1] + RAMADAN.tarawih_delay, hitam_end, return_end or 0
        )
        tarawih_minute, tarawih_task = tarawih(
            sched, RAMADAN, start=tarawih_start
        )
        events.append((tarawih_minute, tarawih_task))
        tarawih_end = tarawih_start + RAMADAN.tarawih_minutes

    if weekday == 4:
        events.extend(_jumuah_events(ctx, sched))
    events.extend(qurban_events(day, sched, QURBAN))
    if weekday == 6:
        # Sonntag: Netzwerken am Stueck; Isha folgt erst danach.
        events.extend(_netzwerken_events())
        # Nach Asr wird gekocht - zuhause sofort, sonst nach der Heimkehr.
        asr_end = next(
            (end for title, _, end in slots if title.split(" ")[0] == "Asr"),
            _mins(sched.asr),
        )
        cook_start = _cook_after_asr_start(
            [item for _, item in events], asr_end, ctx
        )
        if cook_start is not None:
            blocked = [
                interval
                for interval in _event_intervals(events)
                if interval[1] > cook_start
                and interval[0] < cook_start + COOKING_MINUTES
            ]
            for part_start, part_end in _cooking_parts(
                cook_start, COOKING_MINUTES, blocked
            ):
                events.append(
                    (
                        part_start,
                        task(
                            "Kochen",
                            start=_at(part_start),
                            until=_at(part_end),
                            flex=False,
                            overlap=True,
                        ),
                    )
                )
    qaylulah = _qaylulah_event(events, slots, sched, season_cfg)
    if qaylulah is not None:
        events.append(qaylulah)
    events.sort(key=lambda item: item[0])
    tasks = [item[1] for item in events]

    if day == SILA_RAHIM_DATE and isha is not None:
        # Beginnt 60 min vor dem geplanten Isha (nicht vor dem Adhan) und
        # endet mit dem Gebet; die Dusche rutscht dadurch nach vorne.
        _, sila_block = sila_rahim(
            sched, SILA_RAHIM, start=isha[0] - SILA_RAHIM.minutes
        )
        tasks.append(sila_block)

    if weekday != 4:
        # Freitag hat sein Jumuah-Duschen bereits nach dem Fruehstueck.
        tasks = shower_after_homecoming(tasks, HOME, ctx=ctx)
    if weekday == 5 and isha is not None:
        # Samstag ohne Weg: duschen trotzdem vor dem Isha-Gebet.
        tasks = shower_before(tasks, _at(isha[0]), HOME, ctx=ctx)
    if not is_ramadan(day):
        if weekday not in (2, 5, 6):
            tasks = dinner_after_homecoming(
                tasks,
                HOME,
                ctx=ctx,
                not_before=sched.maghrib if fasting else None,
            )
        if weekday == 0:
            # Montag: nach dem Abendsessen eine Stunde aufraeumen; Isha und
            # Hitam haben Vorrang, danach wird aufgeraeumt.
            cleanup_floor = max(isha[1] if isha is not None else 0, hitam_end)
            tasks = cleanup_after_dinner(
                tasks,
                HOME,
                ctx=ctx,
                not_before=_at(cleanup_floor),
            )

    # Schlaf zwischen 23:00 und dem ersten Event des Folgetags (Tahajjud oder
    # Fajr). An Tagen mit spaeter Isha/Rueckweg oder Abendroutinen beginnt der
    # Schlaf danach.
    routine_names = {HOME.shower_name, HOME.dinner_name, HOME.cleanup_name}
    routine_end = max(
        (
            _mins(item.start) + int(item.duration.total_seconds() // 60)
            for item in tasks
            if item.name in routine_names
            and isinstance(item.start, time)
            and item.duration is not None
        ),
        default=0,
    )
    isha_end = isha[1] if isha is not None else 0
    sleep_start = max(
        23 * 60, return_end or 0, routine_end, tarawih_end, isha_end, hitam_end
    )
    if not has_witr:
        _, witr_task = witr(sched, WITR, start=sleep_start)
        tasks.append(witr_task)
        sleep_start += SLEEP.witr_minutes
    sleep_task = task(
        "Schlafen",
        start=_at(sleep_start),
        until=next_event,
        flex=True,
        overlap=True,
    )
    tasks.append(sleep_task)
    ordered = _chronological(tasks)
    # Die grosse Nachtschlaf-Aufgabe schliesst den Tag ab - auch wenn Isha
    # nach Mitternacht liegt und ihre Uhrzeit vor dem Morgenblock steht.
    return [item for item in ordered if item is not sleep_task] + [sleep_task]


@day(name="Studien-Tag")
def studientag(ctx):
    return _studienplan(ctx)


@day(name="Freier Tag")
def freiertag(ctx):
    return _studienplan(ctx)


@day(name="Sonntag")
def sonntag(ctx):
    return _studienplan(ctx)


def make_plan():
    return week(
        mon=studientag,
        tue=studientag,
        wed=studientag,
        thu=studientag,
        fri=studientag,
        sat=freiertag,
        sun=sonntag,
    )


__title__ = "Gebetsplan (Vorlesungen + Gebete)"
