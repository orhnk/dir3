"""Command line: ``dir3 <planfile> [--until N] [--from DATE]``.

The planfile is a plain Python module - the single source of everything: it
defines the schedule (``day``/``week``/``month``), the optional location
(``location = (lat, lon, tz)``) and optional prayer source (``prayer = "..."``).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

from .color import DefaultIconPolicy, DictColorPolicy, PrayerColorPolicy
from .config import Dir3Config, GoogleCalendar, LocationSettings, PrayerSettings
from .core import Month, Week
from .dayloader import list_day_candidates, load_day_spec
from .engine import _plan_today, compile_pattern
from .render import render_plan
from .services import Services
from .services.gcal import GoogleCalendarSyncer, run_clear, run_sync

#: Names pre-seeded into a central config file's namespace, so it needs no
#: imports of its own (e.g. bare ``gcal = GoogleCalendar(...)`` just works).
_CONFIG_SEED = {
    "GoogleCalendar": GoogleCalendar,
    "LocationSettings": LocationSettings,
    "PrayerSettings": PrayerSettings,
}


def _force_utf8_stdout() -> None:
    """Render output must not die on legacy consoles (e.g. Windows cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):  # not a text stream / unsupported
            pass


def _friendly_error(exc: Exception) -> int:
    if os.environ.get("DIR3_DEBUG"):
        raise exc
    print(f"Fehler: {exc}", file=sys.stderr)
    return 1


def _load_module(path: Path, *, name: str = "dir3_planfile", seed=None, what="Planfile"):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Kann {what} nicht laden: {path}")
    module = importlib.util.module_from_spec(spec)
    if seed:
        for key, value in seed.items():
            module.__dict__.setdefault(key, value)
    sys.path.insert(0, str(path.resolve().parent))
    try:
        spec.loader.exec_module(module)
    except Exception:
        traceback.print_exc()
        raise SystemExit(f"Fehler beim Laden ({what}).")
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


def _parse_on(value: str) -> tuple[date, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Format DATE=pfad[:day] erwartet")
    raw_date, _, day_spec = value.partition("=")
    try:
        target = _parse_date(raw_date.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(f"Ungültiges Datum {raw_date!r} (YYYY-MM-DD)")
    if not day_spec.strip():
        raise argparse.ArgumentTypeError("Day-Angabe nach '=' fehlt")
    return target, day_spec.strip()


def _describe_events(pday) -> str:
    active = [ev for ev in pday.events if ev.active]
    if not active:
        return "frei"
    names = ", ".join(ev.name for ev in active[:4])
    if len(active) > 4:
        names += f" +{len(active) - 4}"
    start = active[0].start.time().strftime("%H:%M") if active[0].start else "--:--"
    end = active[-1].end.time().strftime("%H:%M") if active[-1].end else "--:--"
    return f"'{pday.name}' ({len(active)} Events {start}-{end}: {names})"


#: Bekannte Sync-Provider (Namen). Neue Provider: hier eintragen, Handler in
#: _sync_with_provider/_clear_with_provider ergänzen + `--<name>`-Flag unten.
PROVIDERS = ("gcal",)


def _sync_with_provider(provider_name, provider_settings, plan, *, timezone_name, dry_run,
                         color_policy, icon_policy):
    """Sync ausführen - Handler werden beim Aufruf aufgelöst (mockbar)."""
    if provider_name == "gcal":
        return run_sync(
            GoogleCalendarSyncer(
                provider_settings,
                color_policy=color_policy,
                icon_policy=icon_policy,
            ),
            plan,
            timezone_name=timezone_name,
            dry_run=dry_run,
        )
    raise AssertionError(f"unbekannter Provider {provider_name!r}")


def _clear_with_provider(provider_name, provider_settings, *, dry_run, nuke=False):
    """Clear ausführen - Handler werden beim Aufruf aufgelöst (mockbar)."""
    if provider_name == "gcal":
        return run_clear(GoogleCalendarSyncer(provider_settings), dry_run=dry_run, nuke=nuke)
    raise AssertionError(f"unbekannter Provider {provider_name!r}")


def _available_providers(config) -> dict:
    """Konfigurierte Provider: Name -> Einstellungen (nur nutzbare)."""
    found = {}
    if config.calendar is not None and config.calendar.is_configured:
        found["gcal"] = config.calendar
    return found


def _resolve_provider(parser, config, explicit: str | None):
    """Provider bestimmen: explizit (`--gcal`) oder erkannt (genau einer)."""
    available = _available_providers(config)
    if explicit is not None:
        settings = available.get(explicit)
        if settings is None:
            parser.error(
                f"Provider '{explicit}' nicht konfiguriert: "
                "`gcal = GoogleCalendar(...)` im Planfile oder in der --config-Datei "
                "(client_id, client_secret, refresh_token oder access_token)."
            )
        return explicit, settings
    if not available:
        parser.error(
            "Sync braucht einen Provider: `gcal = GoogleCalendar(...)` "
            "im Planfile oder in der --config-Datei."
        )
    if len(available) > 1:
        names = ", ".join(f"--{name}" for name in sorted(available))
        parser.error(f"Mehrere Provider konfiguriert - bitte waehlen: {names}")
    return next(iter(available.items()))


#: Disk caches dropped by ``--recompile`` for a fully fresh run.
_CACHE_FILES = ("prayer_times.json", "geolocation.json")


def _clear_cache_files() -> list[str]:
    """Delete dir3's disk caches so the run refetches everything fresh."""
    from .config import DEFAULT_CACHE_DIR

    cleared = []
    for name in _CACHE_FILES:
        try:
            path = DEFAULT_CACHE_DIR / name
            if path.exists():
                path.unlink()
                cleared.append(name)
        except OSError:
            pass
    return cleared


def _confirm_replace(target: date, pday, replacement: str) -> bool | None:
    print(
        f"{target.isoformat()} belegt {_describe_events(pday)} - "
        f"durch '{replacement}' ersetzen? [y/N] ",
        end="",
        file=sys.stderr,
    )
    try:
        answer = input().strip().lower()
    except EOFError:
        return None
    if answer in ("y", "yes", "j", "ja"):
        return True
    if answer in ("", "n", "no", "nein"):
        return False
    return False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # ``dir3 serve`` / ``dir3 export`` are sub-commands; everything else keeps
    # the historical ``dir3 <planfile> [flags]`` form.
    if argv and argv[0] in ("serve", "export"):
        if argv[0] == "serve":
            from .server import serve_main

            return serve_main(argv[1:])
        from .export import export_main

        return export_main(argv[1:])
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(
        prog="dir3",
        description="Das Leben zeitlich programmieren (weich, anker-basiert).",
        epilog=(
            "Unterbefehle: 'dir3 serve <planfile>' (LAN-Server fuer die Android-App) "
            "und 'dir3 export <planfile> -o plan.json' (JSON fuer Telefon/andere Senken)."
        ),
    )
    parser.add_argument(
        "planfile", type=Path, help="Python-Modul mit dem Plan (z. B. examples/simple.py)"
    )
    parser.add_argument("--until", type=int, default=None, help="Anzahl Tage (Standard: 30)")
    parser.add_argument(
        "--from", dest="start", type=_parse_date, default=None, help="Startdatum YYYY-MM-DD"
    )
    parser.add_argument(
        "--offline", action="store_true", help="Gebetszeiten rein offline berechnen"
    )
    parser.add_argument(
        "--recompile",
        action="store_true",
        help="Cache loeschen und alles frisch holen (Gebet, Geolocation)",
    )
    parser.add_argument(
        "--config",
        metavar="CONFIG",
        type=Path,
        default=None,
        help="Zentrale Config-Datei (z. B. plan/calendar.py) für Standort, Gebet, GCal",
    )
    parser.add_argument(
        "--today",
        metavar="DAY",
        default=None,
        help="Heutigen Plan ersetzen (pfad[:day] oder free)",
    )
    parser.add_argument(
        "--on",
        metavar="DATE=DAY",
        type=_parse_on,
        action="append",
        default=[],
        help="Beliebigen Tag ersetzen, wiederholbar (YYYY-MM-DD=pfad[:day])",
    )
    parser.add_argument(
        "--free",
        metavar="DATE",
        type=_parse_date,
        action="append",
        default=[],
        help="Tag freigeben (YYYY-MM-DD), wiederholbar",
    )
    parser.add_argument(
        "--list-days",
        metavar="DAYFILE",
        nargs="?",
        const="",
        default=None,
        help="Verfügbare Days in Day-Datei (oder Planfile) auflisten",
    )
    overwrite_group = parser.add_mutually_exclusive_group()
    overwrite_group.add_argument(
        "--yes", "-y", action="store_true", help="Ersetzen ohne Rückfrage"
    )
    overwrite_group.add_argument(
        "--keep-existing",
        action="store_true",
        help="Belegte Tage nicht ersetzen (Abbruch statt Rückfrage)",
    )
    parser.add_argument(
        "--compile",
        action="store_true",
        help="Nur kompilieren und drucken (kein Sync)",
    )
    op_group = parser.add_mutually_exclusive_group()
    op_group.add_argument(
        "--sync",
        action="store_true",
        help="Kompilieren und zum Provider synchronisieren (Standardaktion)",
    )
    op_group.add_argument(
        "--clear",
        action="store_true",
        help="Alle dir3-Events beim Provider loeschen (Provider wird erkannt)",
    )
    parser.add_argument(
        "--gcal",
        action="store_true",
        help="Google Calendar als Provider waehlen (nur bei mehreren Providern noetig)",
    )
    parser.add_argument(
        "--nuke",
        action="store_true",
        help="ALLE Events im Kalender loeschen, auch fremde (braucht --clear und --yes)",
    )
    legacy_group = parser.add_mutually_exclusive_group()
    legacy_group.add_argument("--sync-gcal", action="store_true", help=argparse.SUPPRESS)
    legacy_group.add_argument("--gcal-clear", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--gcal-dry-run",
        "--dry-run",
        dest="gcal_dry_run",
        action="store_true",
        help="Plan drucken und Sync/Clear nur anzeigen (keine Änderungen)",
    )
    args = parser.parse_args(argv)

    if not args.planfile.exists():
        parser.error(f"Planfile existiert nicht: {args.planfile}")

    try:
        if args.recompile:
            cleared = _clear_cache_files()
            if cleared:
                print(f"Cache geleert ({', '.join(cleared)}), kompiliere frisch.",
                      file=sys.stderr)
            else:
                print("Kein Cache vorhanden, kompiliere frisch.", file=sys.stderr)
        module = _load_module(args.planfile)
        # Das Planfile darf seine zentrale Config-Datei selbst nennen:
        # ``sync = {"config": "plan/calendar.py"}`` -> ``dir3 plan.py --sync``.
        plan_config = Dir3Config().overlay(module)
        config_path = args.config
        if config_path is None and plan_config.sync.config is not None:
            config_path = Path(plan_config.sync.config)
            if not config_path.is_absolute():
                config_path = args.planfile.resolve().parent / config_path
        config = Dir3Config()
        if config_path is not None:
            if not config_path.exists():
                parser.error(f"Config-Datei existiert nicht: {config_path}")
            central = _load_module(
                config_path,
                name="dir3_central_config",
                seed=_CONFIG_SEED,
                what="Config-Datei",
            )
            config.overlay(central)
        config.overlay(module)

        # Defaultsyncenparameter aus dem Planfile; explizite Flags gewinnen.
        sync_defaults = config.sync
        if args.until is None and sync_defaults.until is not None:
            args.until = int(sync_defaults.until)
        if args.start is None and sync_defaults.start is not None:
            args.start = (
                sync_defaults.start
                if isinstance(sync_defaults.start, date)
                else _parse_date(str(sync_defaults.start))
            )
        if args.offline or sync_defaults.offline:
            config.prayer.provider = "offline"
        services = Services(config=config)

        if args.list_days is not None:
            if args.list_days:
                day_module = _load_module(Path(args.list_days))
                label = args.list_days
            else:
                day_module = module
                label = str(args.planfile)
            candidates = list_day_candidates(day_module)
            if not candidates:
                print(f"{label}: keine Days gefunden")
            else:
                for name in sorted(candidates):
                    print(f"{name}: {getattr(candidates[name], 'name', name)}")
            return 0

        pattern = _extract_pattern(module)
        if pattern is None:
            parser.error(f"{args.planfile} definiert weder 'plan' noch 'make_plan()'")

        base_dir = args.planfile.resolve().parent
        requested: dict[str, str] = {}
        if args.today is not None:
            today = args.start or _plan_today(services)
            requested[today.isoformat()] = args.today
        for target, day_spec in args.on:
            requested[target.isoformat()] = day_spec
        for target in args.free:
            requested[target.isoformat()] = "free"

        overrides: dict[str, object] = {}
        replaced: list[str] = []
        horizon = args.until if args.until is not None else 30
        effective_start = args.start or _plan_today(services)
        for iso, day_spec in requested.items():
            target = _parse_date(iso)
            day_def = load_day_spec(day_spec, base_dir)
            offset = (target - effective_start).days
            if offset < 0 or offset >= horizon:
                print(
                    f"Warnung: {iso} ausserhalb Horizont "
                    f"({effective_start.isoformat()} +{horizon} Tage) - trotzdem vorgemerkt",
                    file=sys.stderr,
                )
            else:
                probe = compile_pattern(
                    pattern, days=1, start_date=target, services=services
                ).days[0]
                occupied = probe.active and any(ev.active for ev in probe.events)
                if occupied:
                    if args.keep_existing:
                        parser.error(
                            f"{iso} bereits belegt {_describe_events(probe)} - "
                            "mit --yes ersetzen oder ohne --keep-existing fragen lassen"
                        )
                    elif not args.yes:
                        if not sys.stdin.isatty():
                            try:
                                answer = _confirm_replace(target, probe, day_spec)
                            except OSError:
                                answer = None
                            if answer is None:
                                print(
                                    f"Fehler: {iso} belegt {_describe_events(probe)} - "
                                    "--yes zum Ersetzen oder --keep-existing zum Behalten",
                                    file=sys.stderr,
                                )
                                return 2
                            if not answer:
                                print(f"{iso} behalten", file=sys.stderr)
                                continue
                        elif not _confirm_replace(target, probe, day_spec):
                            print(f"{iso} behalten", file=sys.stderr)
                            continue
                if occupied:
                    replaced.append(iso)
            overrides[iso] = day_def

        plan = compile_pattern(
            pattern,
            until=args.until,
            start_date=args.start,
            title=getattr(module, "__title__", None) or getattr(module, "__name__", "dir3"),
            services=services,
            overrides=overrides or None,
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
        explicit = "gcal" if (args.gcal or args.sync_gcal or args.gcal_clear) else None
        no_action = not (
            args.sync or args.clear or args.sync_gcal or args.gcal_clear or args.gcal
            or args.compile or args.nuke
        )
        if args.nuke and not args.yes:
            parser.error("--nuke loescht ALLE Events im Kalender (auch fremde) - nur mit --yes")
        do_clear = args.clear or args.gcal_clear or args.nuke
        do_sync = args.sync or args.sync_gcal or (args.gcal and not do_clear) or (
            no_action and not do_clear
        )
        if do_sync and do_clear:
            parser.error("nur --sync oder --clear (nicht beides)")
        show_plan = args.compile or args.gcal_dry_run
        if replaced:
            print(f"Ersetzt: {', '.join(sorted(replaced))}")
        icon_policy = config.icon_policy or DefaultIconPolicy()
        if show_plan:
            print(f"Standort: {location_text}")
            print(render_plan(plan, icon_policy=icon_policy))

        if do_sync or do_clear:
            provider_name, provider_settings = _resolve_provider(parser, config, explicit)
            if do_sync:
                base_policy = (
                    config.color_policy
                    if config.color_policy is not None
                    else PrayerColorPolicy()
                )
                if config.colors:
                    color_policy = DictColorPolicy(config.colors, fallback=base_policy)
                else:
                    color_policy = base_policy
                report = _sync_with_provider(
                    provider_name,
                    provider_settings,
                    plan,
                    timezone_name=location.timezone or "UTC",
                    dry_run=args.gcal_dry_run,
                    color_policy=color_policy,
                    icon_policy=icon_policy,
                )
                print(report)
            else:
                report = _clear_with_provider(
                    provider_name,
                    provider_settings,
                    dry_run=args.gcal_dry_run,
                    nuke=args.nuke,
                )
                print(report)
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        return _friendly_error(exc)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
