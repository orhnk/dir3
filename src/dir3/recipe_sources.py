"""Bulk acquisition of the open recipe datasets.

Three openly licensed sources cover recipes from all over the world:

=====================  =====================================================
``zenodo-culinary``    50,510 recipes worldwide (ODC-ODbL); all cuisines are
                       imported, with structured ingredient quantities,
                       servings and nutrition.
``turkish-recipes-175k``  174,975 Turkish recipes (Apache-2.0); quantities are
                       parsed from free-text lines, nutrition where available.
``unitools-recipes``   501 curated world recipes (CC BY-SA 4.0); structured
                       quantities and per-serving nutrition.
=====================  =====================================================

Only haram recipes (pork, alcohol, blood) are dropped.  The optional
``regions`` argument narrows an import to ``de``, ``tr`` or ``ar``; by default
every cuisine is accepted.

Downloads are cached under ``~/.cache/dir3/recipes/<source>/`` and only the
normalized recipes are written to the SQLite database.  Re-running is
idempotent: the ``(source, source_id)`` pair deduplicates automatically.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_CACHE_DIR
from .recipes import (
    Ingredient,
    Recipe,
    normalize_region,
    parse_amount,
    parse_grams,
    parse_ingredient_line,
    parse_kcal,
    parse_minutes,
    parse_servings,
    region_for_cuisines,
)

_RECIPE_CACHE = DEFAULT_CACHE_DIR / "recipes"


@dataclass(frozen=True, slots=True)
class RecipeSource:
    key: str
    name: str
    description: str
    license: str
    attribution: str
    homepage: str
    urls: tuple[str, ...]

    @property
    def filenames(self) -> tuple[str, ...]:
        return tuple(url.rsplit("/", 1)[-1] for url in self.urls)


SOURCES: dict[str, RecipeSource] = {
    "zenodo-culinary": RecipeSource(
        key="zenodo-culinary",
        name="Culinary Recipes Dataset",
        description="50.510 Rezepte weltweit; alle Kuechen, nur Haram wird "
        "beim Import entfernt.",
        license="ODC-ODbL 1.0",
        attribution="Barba & Canals, Culinary Recipes Dataset, "
        "DOI 10.5281/zenodo.15169428",
        homepage="https://zenodo.org/records/15169428",
        urls=("https://zenodo.org/api/records/15169428/files/dataset.csv/content",),
    ),
    "turkish-recipes-175k": RecipeSource(
        key="turkish-recipes-175k",
        name="Turkish Recipes 175K",
        description="174.975 tuerkische Rezepte mit Zutaten, Portionen und "
        "Naehrwerten (wo vorhanden).",
        license="Apache-2.0",
        attribution="Turkish Recipes 175K, Muhammed Locak, "
        "https://huggingface.co/datasets/mmkocak/turkish-recipes-175K",
        homepage="https://huggingface.co/datasets/mmkocak/turkish-recipes-175K",
        urls=(
            "https://huggingface.co/datasets/mmkocak/turkish-recipes-175K/"
            "resolve/main/data/train.jsonl",
            "https://huggingface.co/datasets/mmkocak/turkish-recipes-175K/"
            "resolve/main/data/validation.jsonl",
            "https://huggingface.co/datasets/mmkocak/turkish-recipes-175K/"
            "resolve/main/data/test.jsonl",
        ),
    ),
    "unitools-recipes": RecipeSource(
        key="unitools-recipes",
        name="UniTools World Recipes",
        description="501 kuratierte Weltrezepte mit strukturierten Mengen, "
        "Portionen und Naehrwerten je Portion; alle Laender.",
        license="CC BY-SA 4.0",
        attribution="UniTools - theunitools.com",
        homepage="https://theunitools.com/en/data",
        urls=("https://theunitools.com/data/unitools-recipes-v1.json",),
    ),
}


def _sha1(*parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts if part is not None)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _literal(value: object, default: object) -> object:
    """Parse the Python/JSON literals used by the CSV dataset."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    text = str(value).strip()
    if not text or text in ("{}", "[]"):
        return default
    for loader in (json.loads, ast.literal_eval):
        try:
            return loader(text)
        except (ValueError, SyntaxError):
            continue
    return default


def _localized(value: object) -> str:
    if isinstance(value, dict):
        for key in ("en", "de", "tr", "ar", "ru"):
            if value.get(key):
                return str(value[key])
        return next((str(item) for item in value.values() if item), "")
    return str(value) if value is not None else ""


def _nutrition(row: dict, key: str) -> float | None:
    nutrition = _literal(row.get("Nutrition"), {})
    if not isinstance(nutrition, dict):
        return None
    return parse_grams(nutrition.get(key))


def _zenodo_recipes(
    path: Path, regions: Iterable[str] | None = None
) -> Iterator[Recipe]:
    import csv

    allowed = None if regions is None else set(regions)
    with path.open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        for row in reader:
            cuisines = _literal(row.get("Cuisine"), [])
            if not isinstance(cuisines, list):
                continue
            region = region_for_cuisines(cuisines)
            if allowed is not None and region not in allowed:
                continue
            name = (row.get("Name") or "").strip()
            if not name:
                continue
            raw_ingredients = _literal(row.get("Ingredients"), [])
            if not isinstance(raw_ingredients, list):
                continue
            categories = _literal(row.get("Category"), [])
            if not isinstance(categories, list):
                categories = []
            instructions = _literal(row.get("Instructions"), [])
            if isinstance(instructions, str):
                instructions = [instructions]
            elif not isinstance(instructions, list):
                instructions = []
            servings = _literal(row.get("Servings"), None)
            prep = parse_minutes(row.get("Preparation Time")) or 0
            cook = parse_minutes(row.get("Cooking Time")) or 0
            url = (row.get("URL") or "").strip()
            yield Recipe(
                name=name,
                ingredients=tuple(
                    Ingredient.from_dict(item) for item in raw_ingredients
                ),
                servings=parse_servings(servings),
                calories=_nutrition(row, "Calories"),
                protein=_nutrition(row, "Protein"),
                fat=_nutrition(row, "Fat"),
                carbs=_nutrition(row, "Carbohydrates"),
                cuisine=", ".join(str(item) for item in cuisines),
                region=region,
                category=", ".join(str(item) for item in categories),
                tags=tuple(str(item) for item in categories),
                instructions=tuple(str(step) for step in instructions),
                minutes=(prep + cook) or None,
                source="zenodo-culinary",
                source_id=url or _sha1(name, row.get("Ingredients")),
                url=url,
                license="ODC-ODbL 1.0",
            )


def _turkish_recipes(
    path: Path, regions: Iterable[str] | None = None
) -> Iterator[Recipe]:
    if regions is not None and "tr" not in set(regions):
        return
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            data = json.loads(line)
            name = str(data.get("title") or "").strip()
            if not name:
                continue
            nutrition = data.get("nutrition") or {}
            if not isinstance(nutrition, dict):
                nutrition = {}
            ingredients = data.get("ingredients") or ()
            if isinstance(ingredients, str):
                ingredients = (ingredients,)
            instructions = data.get("instructions") or ()
            if isinstance(instructions, str):
                instructions = (instructions,)
            tags = data.get("tags") or ()
            if isinstance(tags, str):
                tags = (tags,)
            prep = parse_minutes(data.get("prep_time")) or 0
            cook = parse_minutes(data.get("cook_time")) or 0
            total = parse_minutes(data.get("total_time")) or 0
            if not prep and not cook and not total:
                minutes = None
            else:
                minutes = prep + cook or total
            yield Recipe(
                name=name,
                ingredients=tuple(
                    parse_ingredient_line(item) for item in ingredients
                ),
                servings=parse_servings(data.get("servings")),
                calories=parse_kcal(nutrition.get("calories")),
                protein=parse_grams(nutrition.get("Protein(g)")),
                fat=parse_grams(nutrition.get("Yağ(g)")),
                carbs=parse_grams(nutrition.get("Karbonhidrat(g)")),
                cuisine="Turkish",
                region="tr",
                category=str(data.get("category") or ""),
                tags=tuple(str(tag) for tag in tags),
                instructions=tuple(str(step) for step in instructions),
                minutes=minutes,
                source="turkish-recipes-175k",
                source_id=_sha1(name, data.get("raw_text") or data.get("ingredients")),
                url="",
                license="Apache-2.0",
            )


def _unitools_recipes(
    path: Path, regions: Iterable[str] | None = None
) -> Iterator[Recipe]:
    allowed = None if regions is None else set(regions)
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data.get("recipes") or ():
        country = str(item.get("country") or "")
        region = normalize_region(country)
        if allowed is not None and region not in allowed:
            continue
        name = _localized(item.get("name")) or str(item.get("nativeName") or "")
        if not name:
            continue
        nutrition = item.get("nutritionPerServing") or {}
        if not isinstance(nutrition, dict):
            nutrition = {}
        prep = parse_minutes(item.get("prepMinutes")) or 0
        cook = parse_minutes(item.get("cookMinutes")) or 0
        steps = item.get("steps") or ()
        ingredients = []
        for ingredient in item.get("ingredients") or ():
            if not isinstance(ingredient, dict):
                continue
            ingredients.append(
                Ingredient(
                    name=_localized(ingredient.get("name"))
                    or str(ingredient.get("id") or ""),
                    amount=parse_amount(ingredient.get("quantity")),
                    unit=str(ingredient.get("unit") or ""),
                    note=_localized(ingredient.get("note")),
                    scaling=str(ingredient.get("scaling") or "linear"),
                )
            )
        yield Recipe(
            name=name,
            ingredients=tuple(ingredients),
            servings=parse_servings(item.get("baseServings")),
            calories=parse_kcal(nutrition.get("calories")),
            protein=parse_grams(nutrition.get("protein")),
            fat=parse_grams(nutrition.get("fat")),
            carbs=parse_grams(nutrition.get("carbs")),
            cuisine=country,
            region=region,
            category=str(item.get("category") or ""),
            tags=tuple(str(diet) for diet in item.get("diets") or ()),
            instructions=tuple(
                _localized(step.get("text"))
                for step in steps
                if isinstance(step, dict)
            ),
            minutes=(prep + cook) or None,
            source="unitools-recipes",
            source_id=str(item.get("slug") or _sha1(name, country)),
            url=SOURCES["unitools-recipes"].homepage,
            license="CC BY-SA 4.0",
        )


def iter_source_recipes(
    key: str,
    paths: Iterable[str | Path],
    *,
    regions: Iterable[str] | None = None,
) -> Iterator[Recipe]:
    """Yield normalized recipes from the downloaded files of ``key``.

    By default every cuisine is accepted; pass ``regions=("de", "tr", "ar")``
    to keep only those three.  Haram recipes are filtered by
    :class:`~dir3.recipes.RecipeBook` during import, not here.
    """
    if key not in SOURCES:
        raise ValueError(f"unknown recipe source {key!r}")
    allowed = None if regions is None else tuple(regions)
    if key == "zenodo-culinary":
        for path in paths:
            yield from _zenodo_recipes(Path(path), allowed)
    elif key == "turkish-recipes-175k":
        for path in paths:
            yield from _turkish_recipes(Path(path), allowed)
    elif key == "unitools-recipes":
        for path in paths:
            yield from _unitools_recipes(Path(path), allowed)
    else:  # pragma: no cover - guarded above
        raise AssertionError(key)


def source_path(
    source: RecipeSource, filename: str, cache_dir: str | Path | None = None
) -> Path:
    root = Path(cache_dir).expanduser() if cache_dir else _RECIPE_CACHE
    return root / source.key / filename


def _download(url: str, target: Path, progress=None) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "dir3-recipes/0.1 (+https://github.com/)"}
    )
    part = target.with_suffix(target.suffix + ".part")
    downloaded = 0
    with urllib.request.urlopen(request, timeout=120) as response:
        total = int(response.headers.get("Content-Length") or 0)
        if progress:
            progress(target.name, 0, total)
        with part.open("wb") as stream:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                stream.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(target.name, downloaded, total)
    part.replace(target)
    return target


def download_source(
    key: str,
    *,
    cache_dir: str | Path | None = None,
    refresh: bool = False,
    progress=None,
) -> list[Path]:
    """Download (or reuse) all files of one source and return their paths."""
    if key not in SOURCES:
        raise ValueError(f"unknown recipe source {key!r}")
    source = SOURCES[key]
    paths: list[Path] = []
    for url, filename in zip(source.urls, source.filenames, strict=True):
        target = source_path(source, filename, cache_dir)
        if target.exists() and target.stat().st_size > 0 and not refresh:
            paths.append(target)
            continue
        paths.append(_download(url, target, progress=progress))
    return paths


def describe_sources() -> str:
    """Human-readable overview for ``dir3-recipes fetch --help``."""
    lines = []
    for source in SOURCES.values():
        lines.append(
            f"{source.key:24} {source.name} - {source.description} "
            f"[{source.license}]"
        )
    return "\n".join(lines)


def progress_printer(name: str, downloaded: int, total: int) -> None:
    """Default progress callback: one line per file, in-place updates."""
    if total:
        percent = downloaded * 100 // total
        print(
            f"\r  {name}: {percent:3d}% "
            f"({downloaded / 1_000_000:.1f}/{total / 1_000_000:.1f} MB)",
            end="",
            file=sys.stderr,
            flush=True,
        )
    else:
        print(
            f"\r  {name}: {downloaded / 1_000_000:.1f} MB",
            end="",
            file=sys.stderr,
            flush=True,
        )
    if downloaded == total:
        print(file=sys.stderr)
