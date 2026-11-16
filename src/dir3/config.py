"""Planfile-Konfiguration - alle Daten leben im Python-Planfile, keine TOML-Dateien.

dir3 liest die Einstellungen direkt aus dem Planfile (analog zu ``day``/``week``):
kein ``config.toml`` wie bei munazzim. Optional können im Planfile stehen::

    # 1) Standort: Tupel (lat, lon, IANA-Zeitzone) - alternativ LocationSettings/Dict
    location = (40.7992, 29.4305, "Europe/Istanbul")

    # 2) Gebetsberechnung (Caelestia/Salat): Methode/Schule oder Dict
    prayer = {"method": 13, "school": 0}  # Türkei/Diyanet, Shafi
    #    provider: "auto" (Aladhan + offline fallback) | "offline"
    #    method: Aladhan-ID (int), school: 0=Shafi, 1=Hanafi
    #    method_auto: True = nächste Autorität aus der live methods-Tabelle

    # 3) Verkehrsmittelzeiten (optional): HAFAS-REST, Default VBB (Berlin/Brandenburg)
    transit = {"endpoint": "https://v6.vbb.transport.rest"}

    # 4) Google-Calendar-Sync (optional): Credentials im Planfile
    from dir3 import GoogleCalendar
    gcal = GoogleCalendar(
        client_id="…", client_secret="…", refresh_token="…",
        calendar_id="primary",
    )

    # 5) Defaults für den Sync-Lauf: dann reicht ``dir3 plan.py --sync``
    sync = {"until": 7, "from": "2026-11-14", "offline": True}

Nichts gesetzt? Dann bestimmt dir3 den Standort selbst per Geolocation
(``ipapi.co``, funktioniert überall) und nutzt standardmäßig Aladhan mit
offline berechneten Zeiten als Fallback. Kalender-Sync ist aus, bis das
Planfile ``gcal = GoogleCalendar(...)`` setzt.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .alarm import AlarmSettings

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "dir3"


def _default_data_dir() -> Path:
    override = os.environ.get("DIR3_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "dir3"


#: Persistent user data (recipe database) - not a throw-away cache.
DEFAULT_DATA_DIR = _default_data_dir()


@dataclass(slots=True)
class LocationSettings:
    city: str = ""
    country: str = ""
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    use_geolocation: bool = True


@dataclass(slots=True)
class PrayerSettings:
    """Caelestia/Salat-compatible prayer settings.

    Mirrors ``services/Salat.qml``: ``method`` is the Aladhan numeric id,
    ``school`` is 0=Shafi / 1=Hanafi, ``method_auto`` picks the nearest
    authority from the live ``GET /v1/methods`` table by location.
    ``provider`` only switches between ``auto`` (cache → Aladhan → offline)
    and ``offline`` (never touch the network).
    """

    provider: str = "auto"  # auto | offline (aladhan/online are aliases for auto)
    method: int = 13
    school: int = 0  # 0=Shafi, 1=Hanafi
    method_auto: bool = True


@dataclass(slots=True)
class SyncSettings:
    """Voreinstellungen für einen Sync-Lauf - direkt im Planfile.

    Im Planfile als Dict (oder als ``SyncSettings``)::

        sync = {"until": 7}                          # Horizont in Tagen
        sync = {"from": "2026-11-14"}                # Startdatum (ISO oder date)
        sync = {"offline": True}                     # Gebetszeiten ohne Netz
        sync = {"config": "plan/calendar.py"}        # zentrale Config-Datei

    Explizite CLI-Flags (``--until``, ``--from``, ``--offline``, ``--config``)
    haben immer Vorrang. Damit reicht ``dir3 plan.py --sync`` und der Lauf
    nutzt genau die im Planfile hinterlegten Parameter. Ein relativer
    ``config``-Pfad wird relativ zum Planfile aufgelöst.
    """

    until: int | None = None
    start: date | str | None = None
    offline: bool = False
    config: str | Path | None = None


def _coerce_sync_start(value: object) -> date | None:
    """``sync["from"]`` darf ``date``, ``datetime`` oder ISO-String sein."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            raise ValueError(
                f"sync['from'] braucht ein Datum im Format YYYY-MM-DD, nicht {value!r}"
            ) from None
    raise TypeError(f"sync['from'] braucht date oder ISO-String, nicht {type(value).__name__}")


@dataclass(slots=True)
class TransitSettings:
    """Public-transport travel times via a HAFAS REST endpoint.

    The default endpoint is the community VBB API for Berlin/Brandenburg
    (no API key). Other compatible HAFAS REST instances can be used by
    changing ``endpoint`` and ``timezone``.
    """

    endpoint: str = "https://v6.vbb.transport.rest"
    timezone: str = "Europe/Berlin"
    timeout: float = 10.0
    results: int = 3
    stop_cache_ttl: int = 7 * 24 * 60 * 60


#: Legacy dir3 method names → Aladhan ids. Kept only to migrate old
#: planfiles (``prayer={"method": "MWL"}``); the calculation itself is
#: Caelestia's (live methods table + fallback angles), not dir3's old table.
_LEGACY_METHOD_IDS = {
    "JAFARI": 0,
    "KARACHI": 1,
    "ISNA": 2,
    "MWL": 3,
    "MAKKAH": 4,
    "EGYPT": 5,
    "TEHRAN": 7,
    "GULF": 8,
    "KUWAIT": 9,
    "QATAR": 10,
    "SINGAPORE": 11,
    "FRANCE": 12,
    "TURKEY": 13,
    "RUSSIA": 14,
    "MOONSIGHTING": 15,
    "DUBAI": 16,
    "JAKIM": 17,
    "TUNISIA": 18,
    "ALGERIA": 19,
    "KEMENAG": 20,
    "MOROCCO": 21,
    "PORTUGAL": 22,
    "JORDAN": 23,
    "CUSTOM": 99,
    "DIYANET": 13,
    "UMQ": 4,
    "UMMALQURA": 4,
    "UMM-AL-QURA": 4,
    "UMM AL-QURA": 4,
    "MALAYSIA": 17,
    "INDONESIA": 20,
}


def _normalize_method_name(value: object) -> str:
    return re.sub(r"[\s_-]+", " ", str(value or "").strip()).upper()


def _coerce_method_id(value: object) -> int | None:
    """Legacy method value → Aladhan id, or None when not parseable."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    return _LEGACY_METHOD_IDS.get(_normalize_method_name(text))


def _coerce_school(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return 1 if value == 1 else 0
    text = str(value).strip().lower()
    if text in ("1", "hanafi"):
        return 1
    if text in ("0", "shafi", "shafii", "shafi'i"):
        return 0
    return None


def _apply_prayer_string(settings: PrayerSettings, value: str) -> None:
    """Apply a ``prayer = "<kürzel>"`` / ``provider = "<kürzel>"`` string."""
    text = value.strip().lower()
    if text in ("auto", "online", "aladhan"):
        settings.provider = "auto"
    elif text == "offline":
        settings.provider = "offline"
    elif text in ("ezanvakti", "diyanet"):
        # EzanVakti provider was removed; Aladhan method 13 (Diyanet/Turkey)
        # is the closest offline/online equivalent.
        settings.provider = "auto"
        settings.method = 13
        settings.method_auto = False
    else:
        method_id = _coerce_method_id(value)
        if method_id is not None:
            settings.method = method_id
            settings.method_auto = False
        else:
            # Unknown token: keep explicit so failures are visible, like
            # before (old code stored it as provider verbatim).
            settings.provider = value


def _apply_prayer_dict(settings: PrayerSettings, values: dict) -> None:
    provider = values.get("provider", values.get("source"))
    if isinstance(provider, str):
        _apply_prayer_string(settings, provider)
    # method / method_auto
    if "method" in values and values["method"] is not None:
        method_id = _coerce_method_id(values["method"])
        if method_id is not None:
            settings.method = method_id
            # Explicit method disables auto unless explicitly re-enabled,
            # mirroring Salat.methodAuto (explicit choice sets auto=false).
            if "method_auto" not in values and "methodAuto" not in values:
                settings.method_auto = False
    for key in ("method_auto", "methodAuto", "methodauto"):
        if key in values and values[key] is not None:
            settings.method_auto = bool(values[key])
    # school / madhab (legacy)
    school = None
    if "school" in values:
        school = _coerce_school(values["school"])
    if school is None and "madhab" in values:
        school = _coerce_school(values["madhab"])
    if school is not None:
        settings.school = school
    # legacy provider aliases inside dict that _apply_prayer_string missed
    # (e.g. provider="diyanet" already handled above).


@dataclass(slots=True)
class GoogleCalendar:
    """Google-Calendar-Sync-Credentials - direkt im Python-Planfile.

    OAuth2-Verfahren:
      * ``refresh_token`` + ``client_id``/``client_secret`` (empfohlen) oder
      * ein bereits ausgestelltes ``access_token`` (kurzlebig, wird direkt
        verwendet ohne Refresh-Token-Endpunkt).
    ``calendar_id`` ist der Zielkalender (Standard: ``primary``).
    Fuer den Hybrid-Sync (``task_list``) muss der Token neben
    ``calendar.events`` auch den Scope ``tasks`` umfassen; ohne ihn bleiben
    normale Events nutzbar, der Aufgaben-Sync meldet einen Re-Auth-Fehler.
    """

    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    access_token: str = ""
    calendar_id: str = "primary"

    @property
    def is_configured(self) -> bool:
        """True wenn ein Refresh-Token-Paar oder ein direktes Access-Token vorliegt."""
        if self.access_token:
            return True
        return bool(self.client_id and self.client_secret and self.refresh_token)


@dataclass(slots=True)
class Dir3Config:
    location: LocationSettings = field(default_factory=LocationSettings)
    prayer: PrayerSettings = field(default_factory=PrayerSettings)
    transit: TransitSettings = field(default_factory=TransitSettings)
    sync: SyncSettings = field(default_factory=SyncSettings)
    calendar: GoogleCalendar | None = field(default=None)
    #: Event-Name -> GCal-colorId (``1``..``11``), GCalColor oder Name,
    #: z. B. ``{"Coding": 9}`` oder ``{"Coding": GCalColor.BLUEBERRY}``.
    #: Diese nutzerdefinierten Farben überschreiben die ``color_policy``;
    #: alle übrigen Events fallen auf sie (bzw. die Standardfarbgebung) zurück.
    colors: dict = field(default_factory=dict)
    #: Eigenes ColorPolicy-Objekt (``color_for(name, index)``) aus dem Planfile.
    #: ``colors`` hat Vorrang davor.
    color_policy: object | None = None
    #: Eigenes IconPolicy-Objekt (``icon_for(name, index)``) aus dem Planfile,
    #: z. B. ``icon_policy = DefaultIconPolicy(lectures="📚")``.
    icon_policy: object | None = None
    #: Alarme auf Plan-Events: ``alarms = False`` schaltet die automatischen
    #: Weck-Alarme ab, ``alarm_policy = WakeAlarmPolicy(...)`` passt sie an.
    alarms: AlarmSettings = field(default_factory=AlarmSettings)

    @classmethod
    def from_planfile(cls, module) -> Dir3Config:
        """Baut die Konfiguration aus optionalen Planfile-Attributen.

        Unterstützte Attribute:
          ``location``  - (lat, lon, tz)-Tupel, LocationSettings oder Dict;
          ``prayer``    - Provider-Kürzel, PrayerSettings oder Dict;
          ``provider``  - Kurzform für ``prayer = "<kürzel>"``;
          ``transit``   - TransitSettings oder Dict (HAFAS-REST-Endpoint);
          ``sync``      - SyncSettings oder Dict (Defaults für ``--sync``).
        """
        return cls().overlay(module)

    def overlay(self, module) -> Dir3Config:
        """Overlays only the attributes the module actually defines.

        Missing attributes leave current values untouched - apply the central
        config file (``--config``) first, then the planfile (which wins).
        """
        location = getattr(module, "location", None)
        if isinstance(location, LocationSettings):
            self.location = location
        elif isinstance(location, dict):
            self.location = LocationSettings(**location)
        elif isinstance(location, (tuple, list)) and len(location) >= 2:
            self.location = LocationSettings(
                latitude=location[0],
                longitude=location[1],
                timezone=location[2] if len(location) > 2 else None,
                city=location[3] if len(location) > 3 else "",
                country=location[4] if len(location) > 4 else "",
            )

        prayer = getattr(module, "prayer", None)
        if isinstance(prayer, str):
            _apply_prayer_string(self.prayer, prayer)
        elif isinstance(prayer, PrayerSettings):
            self.prayer = prayer
        elif isinstance(prayer, dict):
            # Filter to known fields + legacy aliases; unknown keys are
            # ignored here and handled via _apply_prayer_dict so legacy
            # planfiles (method="MWL", madhab="Hanafi") keep working.
            settings = PrayerSettings(
                provider=self.prayer.provider,
                method=self.prayer.method,
                school=self.prayer.school,
                method_auto=self.prayer.method_auto,
            )
            _apply_prayer_dict(settings, prayer)
            self.prayer = settings
        elif isinstance(prayer, (tuple, list)):
            if prayer:
                _apply_prayer_string(self.prayer, str(prayer[0]))
                if len(prayer) > 1:
                    method_id = _coerce_method_id(prayer[1])
                    if method_id is not None:
                        self.prayer.method = method_id
                        self.prayer.method_auto = False

        provider = getattr(module, "provider", None)
        if isinstance(provider, str):
            _apply_prayer_string(self.prayer, provider)

        transit = getattr(module, "transit", None)
        if isinstance(transit, TransitSettings):
            self.transit = transit
        elif isinstance(transit, dict):
            self.transit = TransitSettings(**transit)

        sync = getattr(module, "sync", None)
        if isinstance(sync, SyncSettings):
            self.sync = sync
        elif isinstance(sync, dict):
            values = dict(sync)
            # ``from`` ist ein Python-Keyword - im Dict heißt der Schlüssel
            # so, das Dataclass-Feld aber ``start``.
            if "start" not in values and "from" in values:
                values["start"] = values.pop("from")
            start = values.pop("start", None)
            self.sync = SyncSettings(
                until=values.pop("until", None),
                start=_coerce_sync_start(start),
                offline=bool(values.pop("offline", False)),
                config=values.pop("config", None),
            )
            if values:
                unknown = ", ".join(sorted(values))
                raise ValueError(f"unbekannte sync-Option(en): {unknown}")

        calendar = getattr(module, "gcal", None)
        if calendar is None:
            calendar = getattr(module, "google_calendar", None)
        if isinstance(calendar, GoogleCalendar):
            self.calendar = calendar
        elif isinstance(calendar, dict):
            self.calendar = GoogleCalendar(**calendar)

        colors = getattr(module, "colors", None)
        if isinstance(colors, dict):
            merged = dict(self.colors)
            merged.update(colors)
            self.colors = merged

        color_policy = getattr(module, "color_policy", None)
        if callable(getattr(color_policy, "color_for", None)):
            self.color_policy = color_policy

        icon_policy = getattr(module, "icon_policy", None)
        if callable(getattr(icon_policy, "icon_for", None)):
            self.icon_policy = icon_policy

        alarms = getattr(module, "alarms", None)
        if isinstance(alarms, AlarmSettings):
            self.alarms = alarms
        elif isinstance(alarms, bool):
            self.alarms.enabled = alarms
        elif isinstance(alarms, dict):
            values = dict(alarms)
            # ``policy`` accepts a dict shorthand (alarm(...)-style).
            policy = values.pop("policy", None)
            settings = AlarmSettings(
                enabled=bool(values.pop("enabled", self.alarms.enabled)),
                policy=policy if policy is not None else self.alarms.policy,
                chain_gap_minutes=int(
                    values.pop("chain_gap_minutes", self.alarms.chain_gap_minutes)
                ),
            )
            if values:
                unknown = ", ".join(sorted(values))
                raise ValueError(f"unbekannte alarms-Option(en): {unknown}")
            self.alarms = settings
        elif alarms is not None:
            raise ValueError(
                "alarms muss True/False, ein Dict oder AlarmSettings sein, "
                f"nicht {type(alarms).__name__}"
            )

        alarm_policy = getattr(module, "alarm_policy", None)
        if alarm_policy is not None:
            self.alarms.policy = alarm_policy
        return self
