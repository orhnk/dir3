"""``dir3-recipes`` - collect and query the offline recipe database.

Commands::

    dir3-recipes fetch [--source all|zenodo-culinary|turkish-recipes-175k|unitools-recipes]
    dir3-recipes stats
    dir3-recipes search "mercimek" --region tr --max-calories 500
    dir3-recipes add my-recipes.json
    dir3-recipes enrich [--limit N]
    dir3-recipes diet --profile profile.json --days 7 --runs 2

The bulk import removes haram recipes (pork, alcohol, blood) and stores the
remaining recipes with ingredient quantities, servings and nutrition.  The
database lives in ``data/recipes.db`` when it exists, otherwise in
``~/.local/share/dir3/recipes.db`` (override with ``DIR3_DATA_DIR`` or
``--db``).  ``enrich`` estimates missing nutrition from the ingredient lines
and marks the result as an estimate.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .diet import DietProfile, MealPlanSettings, ShoppingSettings, plan_meals
from .recipe_enrich import enrich_database
from .recipe_sources import (
    SOURCES,
    describe_sources,
    download_source,
    iter_source_recipes,
    progress_printer,
)
from .recipes import DEFAULT_RECIPE_DB, RecipeBook

_SOURCE_CHOICES = (*SOURCES, "all")


def _book(args) -> RecipeBook:
    return RecipeBook(args.db)


def _cmd_fetch(args) -> int:
    keys = list(SOURCES) if args.source == "all" else [args.source]
    with _book(args) as book:
        for key in keys:
            source = SOURCES[key]
            print(
                f"[{key}] {source.name} - {source.license}",
                file=sys.stderr,
            )
            paths = download_source(
                key,
                cache_dir=args.cache_dir,
                refresh=args.refresh,
                progress=progress_printer,
            )
            stats = book.add_many(iter_source_recipes(key, paths))
            print(f"[{key}] {stats}", file=sys.stderr)
        print(json.dumps(book.stats(), ensure_ascii=False, indent=2))
    return 0


def _cmd_stats(args) -> int:
    with _book(args) as book:
        print(json.dumps(book.stats(), ensure_ascii=False, indent=2))
    return 0


def _cmd_search(args) -> int:
    with _book(args) as book:
        recipes = book.recipes(
            query=args.query,
            region=args.region,
            cuisine=args.cuisine,
            ingredient=args.ingredient,
            max_calories=args.max_calories,
            limit=args.limit,
        )
        if not recipes:
            print("keine Rezepte gefunden", file=sys.stderr)
            return 1
        for recipe in recipes:
            calories = (
                f"{recipe.calories:.0f} kcal" if recipe.calories is not None else "? kcal"
            )
            servings = (
                f"{recipe.servings:g} Portionen"
                if recipe.servings is not None
                else "? Portionen"
            )
            print(
                f"{recipe.name}  |  {recipe.region or '?'}  |  "
                f"{calories}  |  {servings}  |  {len(recipe.ingredients)} Zutaten"
            )
    return 0


def _cmd_diet(args) -> int:
    data = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("profile JSON must be an object")
    profile = DietProfile.from_dict(data)
    settings = MealPlanSettings(
        days=args.days,
        meals=args.meals,
        people=args.people,
        servings_per_person=args.servings,
        mode=args.mode,
        seed=args.seed,
    )
    with _book(args) as book:
        plan = plan_meals(book, profile, settings)
    print(plan.text())
    shopping = plan.shopping_list(runs=args.runs)
    if shopping.runs:
        print()
        print(shopping.text())
        shopping_settings = ShoppingSettings()
        print()
        print("Einkaufsdauer:")
        for run in shopping.runs:
            print(
                f"  Einkauf {run.index + 1}: {run.item_count} Artikel -> "
                f"{shopping_settings.minutes_for(run)} min"
            )
    return 0


def _cmd_enrich(args) -> int:
    stats = enrich_database(args.db, limit=args.limit, batch_size=args.batch_size)
    print(json.dumps(asdict(stats), ensure_ascii=False, indent=2))
    return 0


def _cmd_add(args) -> int:
    path = Path(args.path)
    with _book(args) as book:
        if path.suffix.casefold() in (".jsonl", ".ndjson"):
            stats = book.import_jsonl(path, replace=args.replace)
        else:
            stats = book.import_json(path, replace=args.replace)
        print(stats)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dir3-recipes",
        description="Offline-Rezeptdatenbank (deutsch, tuerkisch, arabisch).",
        epilog=describe_sources(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_db(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--db",
            type=Path,
            default=DEFAULT_RECIPE_DB,
            help=f"Datenbank (Standard: {DEFAULT_RECIPE_DB})",
        )

    fetch = sub.add_parser("fetch", help="Quellen bulk herunterladen und importieren")
    fetch.add_argument("--source", choices=_SOURCE_CHOICES, default="all")
    fetch.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Download-Cache (Standard: ~/.cache/dir3/recipes)",
    )
    fetch.add_argument(
        "--refresh",
        action="store_true",
        help="vorhandene Downloads verwerfen und neu laden",
    )
    add_db(fetch)
    fetch.set_defaults(func=_cmd_fetch)

    stats = sub.add_parser("stats", help="Anzahl Rezepte, Regionen und Kalorien")
    add_db(stats)
    stats.set_defaults(func=_cmd_stats)

    search = sub.add_parser("search", help="Rezepte suchen")
    search.add_argument("query", nargs="?", default=None, help="Name enthaelt ...")
    search.add_argument("--region", choices=("de", "tr", "ar"), default=None)
    search.add_argument("--cuisine", default=None, help="Kueche enthaelt ...")
    search.add_argument("--ingredient", default=None, help="Zutat enthaelt ...")
    search.add_argument("--max-calories", type=float, default=None)
    search.add_argument("--limit", type=int, default=20)
    add_db(search)
    search.set_defaults(func=_cmd_search)

    add = sub.add_parser("add", help="eigene Rezepte aus JSON/JSONL importieren")
    add.add_argument("path", help="JSON-Datei, JSON-Liste oder JSONL")
    add.add_argument("--replace", action="store_true", help="Duplikate aktualisieren")
    add_db(add)
    add.set_defaults(func=_cmd_add)

    enrich = sub.add_parser(
        "enrich",
        help="fehlende Naehrwerte schaetzen, Portionen und Zutaten markieren",
    )
    enrich.add_argument("--limit", type=int, default=None, help="nur N Rezepte pruefen")
    enrich.add_argument("--batch-size", type=int, default=500)
    add_db(enrich)
    enrich.set_defaults(func=_cmd_enrich)

    diet = sub.add_parser("diet", help="Wochenplan und Einkaufsliste aus einem Profil")
    diet.add_argument("--profile", type=Path, required=True, help="Profil als JSON-Datei")
    diet.add_argument("--days", type=int, default=7)
    diet.add_argument("--meals", default="lunch,dinner", help="kommagetrennt")
    diet.add_argument("--people", type=int, default=1)
    diet.add_argument("--servings", type=float, default=1.0, help="Portionen pro Person")
    diet.add_argument("--mode", choices=("balanced", "favorites", "mix"), default="mix")
    diet.add_argument("--runs", type=int, default=1, help="Einkaeufe pro Woche")
    diet.add_argument("--seed", type=int, default=None)
    add_db(diet)
    diet.set_defaults(func=_cmd_diet)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
