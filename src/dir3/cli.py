"""Command line: ``dir3 <planfile> [--until N] [--from DATE]``.

The planfile is a plain Python module - the single source of everything: it
defines the schedule (``day``/``week``/``month``), the optional location
(``location = (lat, lon, tz)``) and optional prayer source (``prayer = "..."``).
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

from .config import Dir3Config
from .core import Month, Week
from .engine import compile_pattern
from .render import render_plan
from .services import Services


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("dir3_planfile", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Kann Planfile nicht laden: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.resolve().parent))
    try:
        spec.loader.exec_module(module)
    except Exception:
        traceback.print_exc()
        raise SystemExit("Fehler beim Laden des Planfiles.")
    return module


def _extract_pattern(module) -> object | None:
    for name in ("plan", "month"):
        value = getattr(module, name, None)
        if isinstance(value, (Month, Week)):
            return value
        if callable(value) and name == "month":
            continue
    factory = getattr(module, "make_plan", None)
    if callable(factory):
        return factory()
    return None


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dir3",
        description="Das Leben zeitlich programmieren (weich, anker-basiert).",
    )
    parser.add_argument(
        "planfile", type=Path, help="Python-Modul mit dem Plan (z. B. examples/dir3.py)"
    )
    parser.add_argument("--until", type=int, default=None, help="Anzahl Tage (Standard: 30)")
    parser.add_argument(
        "--from", dest="start", type=_parse_date, default=None, help="Startdatum YYYY-MM-DD"
    )
    parser.add_argument(
        "--offline", action="store_true", help="Gebetszeiten rein offline berechnen"
    )
    args = parser.parse_args(argv)

    if not args.planfile.exists():
        parser.error(f"Planfile existiert nicht: {args.planfile}")

    module = _load_module(args.planfile)
    config = Dir3Config.from_planfile(module)
    if args.offline:
        config.prayer.provider = "offline"
    services = Services(config=config)

    pattern = _extract_pattern(module)
    if pattern is None:
        parser.error(f"{args.planfile} definiert weder 'plan' noch 'make_plan()'")

    plan = compile_pattern(
        pattern,
        until=args.until,
        start_date=args.start,
        title=getattr(module, "__title__", None) or getattr(module, "__name__", "dir3"),
        services=services,
    )
    location = services.geo.detect()
    location_text = " · ".join(
        part
        for part in (
            location.city or None,
            f"{location.latitude:.4f},{location.longitude:.4f}",
            location.timezone or None,
        )
        if part
    )
    print(f"Standort: {location_text}")
    print(render_plan(plan))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
