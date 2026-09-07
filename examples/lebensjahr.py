"""Dein ganzes Jahr ist EINE Funktion.

Das ist der rote Faden: statt dutzender Kalenderbausteine "programmierst du
dein Leben" als eine einzige (date) -> Tag Funktion. Jeder Kalendereintrag ist
ein Code-Zweig:

    * Schultage           nach Wochentag;
    * Wochenende          nach Wochentag;
    * Freie Tage          durch einen einfachen Set-Ueberlauf;
    * Pruefungen          an konkreten Daten -> erscheinen automatisch;
    * Feiertage/Geburtstage -> weiche, unvergessliche Bausteine.

Alles ist Python. Willst du einen neuen Feiertag? Eine neue Prüfung?
Einfach eine Zeile ändern - das ganze Jahr passt sich neu zusammen.
"""
from datetime import date, time

from dir3 import anchor, day, task
from dir3 import calendar as _calendar

# --- Kalender-Fakten (aus den deiner Welt) ----------------------------------
FEIERTAGE = {
    date(2026, 12, 24): "Heiligabend",
    date(2026, 1, 1): "Neujahr",
    date(2026, 3, 20): "Tuerkischer Befreiungstag",
}

PRUEFUNGEN = {
    date(2026, 3, 12): "Zwischenklausur Analysis",
    date(2026, 7, 8): "Muedliche Pruefung",
    date(2026, 8, 25): "Nachpruefung Statistik",
}

GEBURTSTAGE = {
    date(2026, 9, 15): "Aylin",
    date(2026, 12, 2): "Mama",
}

FREIE_TAGE = {date(2026, 6, 29), date(2026, 9, 21)}

PA_FREI = frozenset(date(2026, m, 1) for m in range(1, 13))  # 1. des Monats


@anchor
def morgen(ctx):
    return time(6, 30)


@anchor
def pausetastisch(ctx):
    return time(12, 30)


@day(name="Schultag")
def schul(ctx):
    return [
        task("Frühstück & Rucksack", start=morgen, duration="30m"),
        task("Schule", start=time(8, 0), until=time(13, 0), flex=True),
        task("Hausaufgaben", start=time(15, 0), duration="1h30m", flex=True),
        task("Freizeit/Familie", duration="2h", flex=True),
    ]


@day(name="Pa-Tag")
def freitag(ctx):
    return [
        task("Schule bis Mittag", start=time(8, 0), until=time(12, 0), flex=True),
        task("Freitagspause", start=pausetastisch, duration="2h"),
        task("Fragen an die Familie", start=time(15, 0), duration="1h"),
        task("Abend & Familie", duration="3h", flex=True),
    ]


@day(name="Wochenende")
def wochenende(ctx):
    return [
        task("Ausschlafen", start=time(9, 0), duration="2h"),
        task("Familienzeit", start=time(11, 0), duration="3h", flex=True),
        task("Freizeit & Hobby", duration="2h", flex=True),
    ]


@day(name="Prüfung")
def pruefung(ctx):
    return [
        task("Ruhiger Kopf", start=morgen, duration="45m"),
        task("PRÜFUNG", start=time(10, 0), duration="2h", flex=False),
        task("Durchatmen & Feiern", start=pausetastisch, duration="2h"),
    ]


def _feiertag(geben_date):
    return [
        task(anlass, start=time(11, 0), duration="2h", flex=True)
        for anlass in [FEIERTAGE.get(geben_date), GEBURTSTAGE.get(geben_date)]
        if anlass
    ]


@_calendar
def lebensjahr(today):
    """Eine Funktion = dein ganzes Jahr."""
    if today in PRUEFUNGEN:
        return pruefung
    if today in FREIE_TAGE:
        return None  # bewusst freier Tag
    if today in FEIERTAGE or today in GEBURTSTAGE:
        @day(name=FEIERTAGE[today] if today in FEIERTAGE else "Geburtstag")
        def fest(ctx):
            return _feiertag(today) + [
                task("Feiern & Geniessen", start=time(14, 0), duration="3h", flex=True),
            ]
        return fest
    if today.weekday() >= 5:  # Sa / So
        return wochenende
    if today.weekday() == 4:  # Freitag
        return freitag
    if today.day == 1:
        @day(name="Fragen-Tag")
        def monatsanfang(ctx):
            return [
                task("Fragen-Block", start=morgen, duration="1h30m"),
                task("Monatsplan bauen", start=pausetastisch, duration="1h"),
            ]
        return monatsanfang
    return schul


def make_plan():
    return lebensjahr


__title__ = "Dein erstes ganzes Jahr"
