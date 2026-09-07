"""Configuration loading for dir3.

Reads ``~/.config/dir3/config.toml`` (auto-created on first run) mirroring the
approach used by munazzim.  The file is purely user-managed; dir3 never rewrites
it.

[location]
city = "Berlin"
country = "Deutschland"
latitude = 52.52
longitude = 13.405
timezone = "Europe/Berlin"
use_geolocation = true        # auto-detect via ipapi.co when coords are missing

[prayer]
provider = "auto"             # "auto" | "online" (Aladhan) | "offline"
method = "MWL"                # MWL | ISNA | Egypt | Karachi | Turkey | ...
madhab = "Shafi"              # Shafi | Hanafi  (affects Asr)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tomllib

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "dir3" / "config.toml"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "dir3"


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
    provider: str = "auto"  # auto | online | offline
    method: str = "MWL"
    madhab: str = "Shafi"


@dataclass(slots=True)
class Dir3Config:
    location: LocationSettings = field(default_factory=LocationSettings)
    prayer: PrayerSettings = field(default_factory=PrayerSettings)

    def to_dict(self) -> dict[str, object]:
        loc = self.location
        return {
            "location": {
                "city": loc.city,
                "country": loc.country,
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "timezone": loc.timezone or "",
                "use_geolocation": loc.use_geolocation,
            },
            "prayer": {
                "provider": self.prayer.provider,
                "method": self.prayer.method,
                "madhab": self.prayer.madhab,
            },
        }


class ConfigManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_CONFIG_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dir3Config:
        if not self.path.exists():
            config = Dir3Config()
            self._write(config)
            return config

        try:
            with self.path.open("rb") as handle:
                raw = tomllib.load(handle)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            raise RuntimeError(f"Invalid config {self.path}: {exc}") from exc

        location_raw = raw.get("location", {})
        prayer_raw = raw.get("prayer", {})

        def _float(value: object) -> float | None:
            if value in (None, "", "nan"):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):  # pragma: no cover - defensive
                return None

        def _str(value: object) -> str | None:
            if value in (None, ""):
                return None
            return str(value)

        return Dir3Config(
            location=LocationSettings(
                city=str(location_raw.get("city") or ""),
                country=str(location_raw.get("country") or ""),
                latitude=_float(location_raw.get("latitude")),
                longitude=_float(location_raw.get("longitude")),
                timezone=_str(location_raw.get("timezone")),
                use_geolocation=bool(location_raw.get("use_geolocation", True)),
            ),
            prayer=PrayerSettings(
                provider=str(prayer_raw.get("provider") or "auto").lower(),
                method=str(prayer_raw.get("method") or "MWL"),
                madhab=str(prayer_raw.get("madhab") or "Shafi"),
            ),
        )

    @staticmethod
    def _fmt(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _write(self, config: Dir3Config) -> None:
        lines = [
            "# dir3 Konfiguration - alles optional, alles dein Bereich.",
            "",
            "[location]",
            f'city = "{config.location.city}"',
            f'country = "{config.location.country}"',
        ]
        if config.location.latitude is not None:
            lines.append(f"latitude = {config.location.latitude}")
        if config.location.longitude is not None:
            lines.append(f"longitude = {config.location.longitude}")
        lines += [
            f'timezone = "{config.location.timezone or ""}"',
            f"use_geolocation = {str(config.location.use_geolocation).lower()}",
            "",
            "[prayer]",
            f'provider = "{config.prayer.provider}"',
            f'method = "{config.prayer.method}"',
            f'madhab = "{config.prayer.madhab}"',
            "",
        ]
        self.path.write_text("\n".join(lines), encoding="utf-8")
