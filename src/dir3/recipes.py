"""Offline recipe database with quantities, servings and nutrition.

dir3 collects openly licensed recipes from all over the world into one local
SQLite database, with a focus on German, Turkish and Arabic cuisine.  Every
recipe keeps its ingredient quantities and units, the number of servings and -
when the source provides them - calories, protein, fat and carbohydrates per
serving.  Only haram ingredients (pork, alcohol, blood) are removed on import,
and user recipes are checked before they are stored.

The database is intentionally independent of the planner: a ``@day`` can query
it, but collecting data works without compiling a plan.  Bulk acquisition lives
in :mod:`dir3.recipe_sources` and the ``dir3-recipes`` CLI.

Quick start::

    from dir3 import Ingredient, Recipe, RecipeBook

    book = RecipeBook.open()  # data/recipes.db or ~/.local/share/dir3/recipes.db
    book.add(
        Recipe(
            "Mercimek Çorbası",
            ingredients=(Ingredient("rote Linsen", 250, "g"),),
            servings=4,
            calories=180,
            region="tr",
        )
    )
    for recipe in book.recipes(region="tr", max_calories=400, limit=5):
        print(recipe.name, recipe.calories)
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path

from .config import DEFAULT_DATA_DIR

#: Project-local database, used when it exists.
PROJECT_RECIPE_DB = Path("data/recipes.db")


def _default_recipe_db() -> Path:
    """Prefer ``data/recipes.db`` in the current project, then the user dir."""
    local = PROJECT_RECIPE_DB.expanduser()
    return local if local.exists() else DEFAULT_DATA_DIR / "recipes.db"


#: Persistent database with all downloaded and user-provided recipes.
DEFAULT_RECIPE_DB = _default_recipe_db()

#: Optional shortcut for imports narrowed to German, Turkish and Arabic food.
TARGET_REGIONS = ("de", "tr", "ar")

#: ``region`` values understood by :func:`normalize_region`.
_REGION_TERMS = {
    "de": (
        "german",
        "deutsch",
        "austrian",
        "österreich",
        "swiss",
        "schweizer",
        "bavarian",
        "bayerisch",
        "swabian",
        "schwäbisch",
        "alsatian",
    ),
    "tr": ("turkish", "türkisch", "turkisch", "ottoman", "anatolian", "anadolu"),
    "ar": (
        "arabic",
        "arabisch",
        "middle eastern",
        "middle-east",
        "levantine",
        "lebanese",
        "syrian",
        "egyptian",
        "moroccan",
        "tunisian",
        "algerian",
        "libyan",
        "iraqi",
        "jordanian",
        "palestinian",
        "saudi",
        "emirati",
        "kuwaiti",
        "qatari",
        "omani",
        "yemeni",
        "sudanese",
        "gulf",
        "maghreb",
    ),
}

#: Country codes for the three target regions (used by UniTools).
_ARAB_COUNTRIES = frozenset(
    {
        "DZ",
        "BH",
        "KM",
        "DJ",
        "EG",
        "IQ",
        "JO",
        "KW",
        "LB",
        "LY",
        "MA",
        "MR",
        "OM",
        "PS",
        "QA",
        "SA",
        "SO",
        "SD",
        "SY",
        "TN",
        "AE",
        "YE",
    }
)
_COUNTRY_REGIONS = {"DE": "de", "AT": "de", "CH": "de", "TR": "tr"}
_COUNTRY_REGIONS.update({code: "ar" for code in _ARAB_COUNTRIES})


def normalize_region(value: object) -> str:
    """Map a cuisine/country label to ``de``, ``tr``, ``ar`` or ``""``.

    Accepts cuisine names ("Middle Eastern Inspired"), country names ("Egypt")
    and ISO country codes ("EG").  Unknown values return an empty string so
    callers can decide whether to keep the recipe.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value)).strip().casefold()
    if not text:
        return ""
    code = text.upper()
    if len(code) == 2 and code.isalpha():
        if code in _COUNTRY_REGIONS:
            return _COUNTRY_REGIONS[code]
    for region, terms in _REGION_TERMS.items():
        if any(term in text for term in terms):
            return region
    return ""


def region_for_cuisines(cuisines: Iterable[object]) -> str:
    """First target region found in a list of cuisine labels."""
    for cuisine in cuisines:
        region = normalize_region(cuisine)
        if region:
            return region
    return ""


# ---------------------------------------------------------------------------
# Haram filter
# ---------------------------------------------------------------------------

#: Explicitly forbidden food markers.  The lists deliberately cover German,
#: Turkish, English and Arabic ingredient names.  Ambiguous names (generic
#: "salami", "gelatine", vanilla extract) are *not* filtered automatically.
_HARAM_TERMS = {
    "Schweinefleisch": (
        "pork",
        "schwein",
        "schinken",
        "speck",
        "bacon",
        "ham",
        "prosciutto",
        "pancetta",
        "guanciale",
        "lard",
        "chorizo",
        "domuz",
        "خنزير",
    ),
    "Alkohol": (
        "wine",
        "rotwein",
        "weisswein",
        "wein",
        "beer",
        "bier",
        "ale",
        "rum",
        "whisky",
        "whiskey",
        "vodka",
        "gin",
        "liqueur",
        "likör",
        "brandy",
        "cognac",
        "schnaps",
        "mirin",
        "sake",
        "raki",
        "rakı",
        "arak",
        "şarap",
        "bira",
        "نبيذ",
        "خمر",
        "كحول",
        "بيرة",
    ),
    "Blut": ("blood", "blut", "blutwurst", "kan", "دم"),
}

#: German compounds where the forbidden word is part of a longer word.
_HARAM_PREFIXES = frozenset({"schwein", "schinken", "speck", "blut", "domuz", "pork"})


def _normalized(value: object) -> str:
    return unicodedata.normalize("NFC", str(value)).casefold()


def _term_matches(term: str, text: str) -> bool:
    if term in _HARAM_PREFIXES:
        return term in text
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def find_haram(*texts: object) -> str | None:
    """Return the reason a text is haram, or ``None``.

    ``texts`` may be a recipe name, ingredient names, instructions - they are
    joined and searched together.  This is a conservative helper, not a fatwa:
    it detects pork, alcohol and blood; unknown meat still needs a trusted
    source.
    """
    blob = _normalized(" ".join(str(text) for text in texts if text))
    if not blob:
        return None
    for reason, terms in _HARAM_TERMS.items():
        if any(_term_matches(term, blob) for term in terms):
            return reason
    return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_UNICODE_FRACTIONS = {
    "½": " 1/2 ",
    "¼": " 1/4 ",
    "¾": " 3/4 ",
    "⅓": " 1/3 ",
    "⅔": " 2/3 ",
    "⅛": " 1/8 ",
}
_WORD_NUMBERS = {
    "half": 0.5,
    "halbe": 0.5,
    "halber": 0.5,
    "halbes": 0.5,
    "yarım": 0.5,
    "yarim": 0.5,
    "ein": 1.0,
    "eine": 1.0,
    "einen": 1.0,
    "one": 1.0,
    "bir": 1.0,
    "two": 2.0,
    "iki": 2.0,
    "three": 3.0,
    "üç": 3.0,
    "uc": 3.0,
    "four": 4.0,
    "dört": 4.0,
    "dort": 4.0,
    "five": 5.0,
    "beş": 5.0,
    "bes": 5.0,
    "نصف": 0.5,
    "واحد": 1.0,
    "اثنان": 2.0,
}
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_MIXED_FRACTION_RE = re.compile(r"(\d+)\s+(\d+)\s*/\s*(\d+)")
_FRACTION_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)")


def normalize_digits(text: str) -> str:
    """Convert Arabic-Indic/Persian digits to ASCII digits."""
    return text.translate(_DIGITS)


def parse_amount(value: object) -> float | None:
    """Parse a quantity: ``"1,5"``, ``"1/2"``, ``"1 1/2"``, ``"½"``.

    Turkish/German/Arabic number words (``yarım``, ``halbe``, ``نصف``) are
    understood as well.  Ranges keep their lower bound (``"2-3"`` -> ``2``).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = normalize_digits(str(value)).strip().casefold()
    if not text:
        return None
    for char, replacement in _UNICODE_FRACTIONS.items():
        text = text.replace(char, replacement)
    text = text.replace(",", ".")
    mixed = _MIXED_FRACTION_RE.search(text)
    if mixed:
        whole, numerator, denominator = (float(part) for part in mixed.groups())
        if denominator:
            return whole + numerator / denominator
    fraction = _FRACTION_RE.search(text)
    if fraction:
        numerator, denominator = (float(part) for part in fraction.groups())
        if denominator:
            return numerator / denominator
    number = _NUMBER_RE.search(text)
    if number:
        return float(number.group().replace(",", "."))
    for word, number in _WORD_NUMBERS.items():
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text):
            return number
    return None


def _first_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    number = _NUMBER_RE.search(normalize_digits(str(value)).replace(",", "."))
    return float(number.group()) if number else None


def parse_servings(value: object) -> float | None:
    """Parse servings from ``"4"``, ``"4 kişilik"``, ``["16", ...]`` or ranges."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            servings = parse_servings(item)
            if servings is not None:
                return servings
        return None
    servings = _first_number(value)
    if servings is not None:
        return servings
    return parse_amount(value)


def parse_kcal(value: object) -> float | None:
    """Parse ``"283 kcal"`` / ``97`` / ``"1,5"`` into kcal."""
    return _first_number(value)


parse_grams = parse_kcal


def parse_minutes(value: object) -> int | None:
    """Parse ISO-8601 durations (``PT1H30M``), ``"30 dk"`` and plain numbers."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value) if value >= 0 else None
    text = normalize_digits(str(value)).strip()
    if not text:
        return None
    upper = text.upper()
    if upper.startswith("P"):
        hours = re.search(r"(\d+(?:[.,]\d+)?)\s*H", upper)
        minutes = re.search(r"(\d+(?:[.,]\d+)?)\s*M", upper)
        total = 0.0
        if hours:
            total += float(hours.group(1).replace(",", ".")) * 60
        if minutes:
            total += float(minutes.group(1).replace(",", "."))
        return int(total) if total or hours or minutes else None
    lowered = text.casefold()
    amount = _first_number(lowered)
    if amount is None:
        return None
    if any(unit in lowered for unit in ("saat", "stunde", "hour", "std")):
        return int(amount * 60)
    return int(amount)


_UNIT_ALIASES = (
    "yemek kaşığı",
    "yemek kasigi",
    "tatlı kaşığı",
    "tatli kasigi",
    "çay kaşığı",
    "cay kasigi",
    "su bardağı",
    "su bardagi",
    "çay bardağı",
    "cay bardagi",
    "esslöffel",
    "teelöffel",
    "tablespoons",
    "tablespoon",
    "teaspoons",
    "milliliter",
    "kilogramm",
    "packungen",
    "scheiben",
    "teaspoon",
    "handful",
    "ml",
    "cl",
    "dl",
    "kg",
    "mg",
    "tbsp",
    "tbs",
    "tsp",
    "el",
    "tl",
    "stk",
    "st",
    "pkg",
    "cup",
    "cups",
    "ounce",
    "ounces",
    "oz",
    "lb",
    "gramm",
    "gram",
    "pfund",
    "becher",
    "tasse",
    "tassen",
    "packung",
    "dose",
    "dosen",
    "stück",
    "stueck",
    "prise",
    "prisen",
    "bund",
    "zehe",
    "zehen",
    "scheibe",
    "clove",
    "cloves",
    "sprig",
    "sprigs",
    "pinch",
    "slice",
    "slices",
    "bunch",
    "piece",
    "pieces",
    "can",
    "adet",
    "tane",
    "paket",
    "kutu",
    "demet",
    "diş",
    "tutam",
    "avuç",
    "bardak",
    "kaşık",
    "ملاعق كبيرة",
    "ملعقة كبيرة",
    "ملاعق صغيرة",
    "ملعقة صغيرة",
    "أكواب",
    "كوب",
    "غرام",
    "جرام",
    "كيلوغرام",
    "كيلو",
    "ملليلتر",
    "مل",
    "لتر",
    "حبات",
    "حبة",
    "رشة",
    "ملعقة",
    "كأس",
    "liter",
    "litre",
    "gram",
    "g",
    "l",
)
_SORTED_UNITS = tuple(sorted(_UNIT_ALIASES, key=len, reverse=True))
_AMOUNT_HEAD = re.compile(
    r"^(?:ca\.?|etwa|about|approx\.?|~)?\s*"
    r"(\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?|[½¼¾⅓⅔⅛]|"
    r"yarım|yarim|half|einen|eine|ein|bir|one|نصف)"
    r"(?:\s*(?:-|–)\s*\d+(?:[.,]\d+)?)?\s*",
    re.IGNORECASE,
)


def _match_unit(rest: str) -> tuple[str, str]:
    lowered = rest.casefold()
    for alias in _SORTED_UNITS:
        if not lowered.startswith(alias):
            continue
        after = lowered[len(alias) : len(alias) + 1]
        if after and (after.isalnum() or after == "_"):
            continue
        unit = rest[: len(alias)].strip()
        name = rest[len(alias) :].lstrip(" .,:;-")
        return unit, name
    return "", rest


def parse_ingredient_line(line: object) -> Ingredient:
    """Split a free-text ingredient line into amount, unit and name.

    ``"2 yemek kaşığı zeytinyağı"`` -> 2 / ``yemek kaşığı`` / ``zeytinyağı``.
    Unparseable lines keep their complete text as the name; the original line
    is always stored in ``Ingredient.raw``.
    """
    raw = str(line).strip()
    text = normalize_digits(raw)
    text = re.sub(r"^[-*•·]\s*", "", text)
    amount = None
    rest = text
    match = _AMOUNT_HEAD.match(text)
    if match:
        amount = parse_amount(match.group(1))
        rest = text[match.end() :].strip()
    unit, name = _match_unit(rest)
    name = name.strip(" ,;-") or rest.strip(" ,;-") or raw
    return Ingredient(name=name, amount=amount, unit=unit, raw=raw)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ingredient:
    """One ingredient line with amount, unit and optional note."""

    name: str
    amount: float | None = None
    unit: str = ""
    note: str = ""
    raw: str = ""
    scaling: str = "linear"

    def scaled(self, factor: float) -> Ingredient:
        if self.amount is None:
            return self
        return replace(self, amount=self.amount * factor)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "amount": self.amount,
            "unit": self.unit,
            "note": self.note,
            "raw": self.raw,
            "scaling": self.scaling,
        }

    @classmethod
    def from_dict(cls, data: object) -> Ingredient:
        if isinstance(data, str):
            return parse_ingredient_line(data)
        if not isinstance(data, dict):
            return parse_ingredient_line(data)
        return cls(
            name=str(data.get("name") or data.get("ingredient") or ""),
            amount=parse_amount(data.get("amount", data.get("quantity"))),
            unit=str(data.get("unit") or ""),
            note=str(data.get("note") or data.get("misc") or ""),
            raw=str(data.get("raw") or ""),
            scaling=str(data.get("scaling") or "linear"),
        )


@dataclass(frozen=True, slots=True)
class Recipe:
    """A recipe with structured ingredients and per-serving nutrition."""

    name: str
    ingredients: tuple[Ingredient, ...] = ()
    servings: float | None = None
    calories: float | None = None
    protein: float | None = None
    fat: float | None = None
    carbs: float | None = None
    cuisine: str = ""
    region: str = ""
    category: str = ""
    tags: tuple[str, ...] = ()
    instructions: tuple[str, ...] = ()
    minutes: int | None = None
    source: str = "user"
    source_id: str = ""
    url: str = ""
    license: str = ""
    nutrition_estimated: bool = False
    servings_estimated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name).strip())
        ingredients = self.ingredients
        if isinstance(ingredients, str):
            ingredients = (ingredients,)
        object.__setattr__(
            self,
            "ingredients",
            tuple(
                item if isinstance(item, Ingredient) else Ingredient.from_dict(item)
                for item in ingredients
            ),
        )
        tags = self.tags if not isinstance(self.tags, str) else (self.tags,)
        instructions = (
            self.instructions
            if not isinstance(self.instructions, str)
            else (self.instructions,)
        )
        object.__setattr__(self, "tags", tuple(str(tag) for tag in tags))
        object.__setattr__(
            self, "instructions", tuple(str(step) for step in instructions)
        )
        region = normalize_region(self.region) or normalize_region(self.cuisine)
        object.__setattr__(self, "region", region)

    @property
    def haram_reason(self) -> str | None:
        return find_haram(
            self.name,
            *(ingredient.name for ingredient in self.ingredients),
            *self.instructions,
        )

    @property
    def is_haram(self) -> bool:
        return self.haram_reason is not None

    def scaled(self, servings: float) -> Recipe:
        """Return a copy scaled to ``servings`` (calories stay per serving)."""
        if self.servings is None or self.servings <= 0:
            raise ValueError(f"'{self.name}' has no servings to scale from")
        if servings <= 0:
            raise ValueError("servings must be positive")
        factor = servings / self.servings
        return replace(
            self,
            servings=float(servings),
            ingredients=tuple(item.scaled(factor) for item in self.ingredients),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ingredients": [item.to_dict() for item in self.ingredients],
            "servings": self.servings,
            "calories": self.calories,
            "protein": self.protein,
            "fat": self.fat,
            "carbs": self.carbs,
            "cuisine": self.cuisine,
            "region": self.region,
            "category": self.category,
            "tags": list(self.tags),
            "instructions": list(self.instructions),
            "minutes": self.minutes,
            "source": self.source,
            "source_id": self.source_id,
            "url": self.url,
            "license": self.license,
            "nutrition_estimated": self.nutrition_estimated,
            "servings_estimated": self.servings_estimated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Recipe:
        nutrition = data.get("nutrition") if isinstance(data.get("nutrition"), dict) else {}
        return cls(
            name=str(data.get("name") or data.get("title") or data.get("recipe_name") or ""),
            ingredients=tuple(
                Ingredient.from_dict(item)
                for item in data.get("ingredients") or ()
            ),
            servings=parse_servings(data.get("servings")),
            calories=parse_kcal(data.get("calories", nutrition.get("calories"))),
            protein=parse_grams(data.get("protein", nutrition.get("protein"))),
            fat=parse_grams(data.get("fat", nutrition.get("fat"))),
            carbs=parse_grams(
                data.get("carbs", data.get("carbohydrates", nutrition.get("carbs")))
            ),
            cuisine=str(data.get("cuisine") or ""),
            region=str(data.get("region") or ""),
            category=str(data.get("category") or ""),
            tags=tuple(data.get("tags") or ()),
            instructions=tuple(str(step) for step in data.get("instructions") or ()),
            minutes=parse_minutes(data.get("minutes")),
            source=str(data.get("source") or "user"),
            source_id=str(data.get("source_id") or ""),
            url=str(data.get("url") or ""),
            license=str(data.get("license") or ""),
            nutrition_estimated=bool(data.get("nutrition_estimated", False)),
            servings_estimated=bool(data.get("servings_estimated", False)),
        )


@dataclass(frozen=True, slots=True)
class ImportStats:
    """Result of a bulk import."""

    total: int = 0
    imported: int = 0
    duplicates: int = 0
    haram: int = 0
    invalid: int = 0

    def __str__(self) -> str:
        return (
            f"{self.imported} importiert, {self.haram} haram entfernt, "
            f"{self.duplicates} Duplikate, {self.invalid} ungueltig "
            f"(von {self.total})"
        )


class HaramIngredientError(ValueError):
    """Raised when a user recipe contains a detected haram ingredient."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    name TEXT NOT NULL,
    servings REAL,
    calories REAL,
    protein REAL,
    fat REAL,
    carbs REAL,
    minutes INTEGER,
    cuisine TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    instructions TEXT NOT NULL DEFAULT '[]',
    url TEXT NOT NULL DEFAULT '',
    license TEXT NOT NULL DEFAULT '',
    nutrition_estimated INTEGER NOT NULL DEFAULT 0,
    servings_estimated INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source, source_id)
);
CREATE TABLE IF NOT EXISTS ingredients (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    amount REAL,
    unit TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    raw TEXT NOT NULL DEFAULT '',
    scaling TEXT NOT NULL DEFAULT 'linear',
    PRIMARY KEY(recipe_id, position)
);
CREATE INDEX IF NOT EXISTS idx_recipes_region ON recipes(region);
CREATE INDEX IF NOT EXISTS idx_recipes_source ON recipes(source);
CREATE INDEX IF NOT EXISTS idx_recipes_calories ON recipes(calories);
CREATE INDEX IF NOT EXISTS idx_ingredients_name ON ingredients(name);
"""


def _default_source_id(recipe: Recipe) -> str:
    payload = json.dumps(
        {
            "name": recipe.name,
            "ingredients": [
                item.raw or f"{item.amount} {item.unit} {item.name}"
                for item in recipe.ingredients
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _recipe_from_row(row: sqlite3.Row, ingredients: Iterable[sqlite3.Row]) -> Recipe:
    return Recipe(
        name=row["name"],
        ingredients=tuple(
            Ingredient(
                name=item["name"],
                amount=item["amount"],
                unit=item["unit"],
                note=item["note"],
                raw=item["raw"],
                scaling=item["scaling"],
            )
            for item in ingredients
        ),
        servings=row["servings"],
        calories=row["calories"],
        protein=row["protein"],
        fat=row["fat"],
        carbs=row["carbs"],
        cuisine=row["cuisine"],
        region=row["region"],
        category=row["category"],
        tags=tuple(json.loads(row["tags"] or "[]")),
        instructions=tuple(json.loads(row["instructions"] or "[]")),
        minutes=row["minutes"],
        source=row["source"],
        source_id=row["source_id"],
        url=row["url"],
        license=row["license"],
        nutrition_estimated=bool(row["nutrition_estimated"]),
        servings_estimated=bool(row["servings_estimated"]),
    )


class RecipeBook:
    """SQLite-backed collection of recipes.

    The constructor creates the database (and its parent directory) when it
    does not exist yet.  Use ``with RecipeBook.open() as book:`` for automatic
    closing.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else DEFAULT_RECIPE_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the first database version."""
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(recipes)")
        }
        if "nutrition_estimated" not in columns:
            self._conn.execute(
                "ALTER TABLE recipes ADD COLUMN nutrition_estimated"
                " INTEGER NOT NULL DEFAULT 0"
            )
        if "servings_estimated" not in columns:
            self._conn.execute(
                "ALTER TABLE recipes ADD COLUMN servings_estimated"
                " INTEGER NOT NULL DEFAULT 0"
            )

    @classmethod
    def open(cls, path: str | Path | None = None) -> RecipeBook:
        return cls(path)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> RecipeBook:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- writing ---------------------------------------------------------

    def add(self, recipe: Recipe, *, replace: bool = False) -> bool:
        """Insert one recipe; return ``False`` for an existing duplicate.

        Raises :class:`HaramIngredientError` when pork, alcohol or blood is
        detected in the name, an ingredient or an instruction.
        """
        if not recipe.name:
            raise ValueError("recipe name must not be empty")
        reason = recipe.haram_reason
        if reason:
            raise HaramIngredientError(
                f"'{recipe.name}' enthaelt {reason} - haram-Rezepte werden nicht gespeichert"
            )
        with self._conn:
            outcome = self._insert(recipe, replace=replace)
        return outcome == "imported"

    def add_many(
        self,
        recipes: Iterable[Recipe],
        *,
        replace: bool = False,
    ) -> ImportStats:
        """Bulk import; haram and nameless recipes are dropped and counted.

        Recipes without ingredients are kept: the source data contains a few
        of them, and the instruction is to accept every non-haram recipe.
        """
        counts = {"total": 0, "imported": 0, "duplicates": 0, "haram": 0, "invalid": 0}
        with self._conn:
            for recipe in recipes:
                counts["total"] += 1
                if not recipe.name:
                    counts["invalid"] += 1
                    continue
                try:
                    outcome = self._insert(recipe, replace=replace)
                except (ValueError, TypeError):
                    counts["invalid"] += 1
                    continue
                if outcome == "duplicate":
                    counts["duplicates"] += 1
                else:
                    counts[outcome] += 1
        return ImportStats(**counts)

    def _insert(self, recipe: Recipe, *, replace: bool) -> str:
        reason = recipe.haram_reason
        if reason:
            return "haram"
        source = recipe.source or "user"
        source_id = recipe.source_id or _default_source_id(recipe)
        existing = self._conn.execute(
            "SELECT id FROM recipes WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        values = (
            source,
            source_id,
            recipe.name,
            recipe.servings,
            recipe.calories,
            recipe.protein,
            recipe.fat,
            recipe.carbs,
            recipe.minutes,
            recipe.cuisine,
            recipe.region,
            recipe.category,
            json.dumps(list(recipe.tags), ensure_ascii=False),
            json.dumps(list(recipe.instructions), ensure_ascii=False),
            recipe.url,
            recipe.license,
            int(recipe.nutrition_estimated),
            int(recipe.servings_estimated),
        )
        if existing is not None:
            if not replace:
                return "duplicate"
            recipe_id = existing["id"]
            self._conn.execute(
                "UPDATE recipes SET name = ?, servings = ?, calories = ?, protein = ?,"
                " fat = ?, carbs = ?, minutes = ?, cuisine = ?, region = ?,"
                " category = ?, tags = ?, instructions = ?, url = ?, license = ?,"
                " nutrition_estimated = ?, servings_estimated = ? WHERE id = ?",
                values[2:] + (recipe_id,),
            )
            self._conn.execute("DELETE FROM ingredients WHERE recipe_id = ?", (recipe_id,))
        else:
            cursor = self._conn.execute(
                "INSERT INTO recipes (source, source_id, name, servings, calories,"
                " protein, fat, carbs, minutes, cuisine, region, category, tags,"
                " instructions, url, license, nutrition_estimated, servings_estimated)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            recipe_id = cursor.lastrowid
        self._conn.executemany(
            "INSERT INTO ingredients (recipe_id, position, name, amount, unit, note,"
            " raw, scaling) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    recipe_id,
                    position,
                    item.name,
                    item.amount,
                    item.unit,
                    item.note,
                    item.raw,
                    item.scaling,
                )
                for position, item in enumerate(recipe.ingredients)
            ],
        )
        return "imported"

    def import_json(self, path: str | Path, *, replace: bool = False) -> ImportStats:
        """Import one recipe, a list, or ``{"recipes": [...]}`` from JSON."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and "recipes" in data:
            records = data["recipes"]
        elif isinstance(data, list):
            records = data
        else:
            records = [data]
        return self.add_many(
            (Recipe.from_dict(record) for record in records), replace=replace
        )

    def import_jsonl(self, path: str | Path, *, replace: bool = False) -> ImportStats:
        """Import one JSON recipe per line."""
        with Path(path).open(encoding="utf-8") as stream:
            recipes = (
                Recipe.from_dict(json.loads(line))
                for line in stream
                if line.strip()
            )
            return self.add_many(recipes, replace=replace)

    def clear(self, source: str | None = None) -> int:
        """Delete all recipes (or only one source); return the row count."""
        with self._conn:
            if source is None:
                self._conn.execute("DELETE FROM ingredients")
                deleted = self._conn.execute("DELETE FROM recipes").rowcount
            else:
                self._conn.execute(
                    "DELETE FROM ingredients WHERE recipe_id IN"
                    " (SELECT id FROM recipes WHERE source = ?)",
                    (source,),
                )
                deleted = self._conn.execute(
                    "DELETE FROM recipes WHERE source = ?", (source,)
                ).rowcount
        return deleted

    # -- reading ---------------------------------------------------------

    def _where(
        self,
        *,
        region: str | None = None,
        cuisine: str | None = None,
        source: str | None = None,
        query: str | None = None,
        ingredient: str | None = None,
        max_calories: float | None = None,
        min_calories: float | None = None,
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        if region:
            clauses.append("r.region = ?")
            params.append(normalize_region(region) or region)
        if cuisine:
            clauses.append("r.cuisine LIKE ?")
            params.append(f"%{cuisine}%")
        if source:
            clauses.append("r.source = ?")
            params.append(source)
        if query:
            clauses.append("r.name LIKE ?")
            params.append(f"%{query}%")
        if ingredient:
            clauses.append(
                "EXISTS (SELECT 1 FROM ingredients i"
                " WHERE i.recipe_id = r.id AND i.name LIKE ?)"
            )
            params.append(f"%{ingredient}%")
        if max_calories is not None:
            clauses.append("r.calories IS NOT NULL AND r.calories <= ?")
            params.append(float(max_calories))
        if min_calories is not None:
            clauses.append("r.calories IS NOT NULL AND r.calories >= ?")
            params.append(float(min_calories))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    def iter_recipes(
        self,
        *,
        region: str | None = None,
        cuisine: str | None = None,
        source: str | None = None,
        query: str | None = None,
        ingredient: str | None = None,
        max_calories: float | None = None,
        min_calories: float | None = None,
        halal: bool = True,
        limit: int | None = None,
    ) -> Iterator[Recipe]:
        """Iterate matching recipes; haram recipes are filtered by default."""
        where, params = self._where(
            region=region,
            cuisine=cuisine,
            source=source,
            query=query,
            ingredient=ingredient,
            max_calories=max_calories,
            min_calories=min_calories,
        )
        sql = f"SELECT r.* FROM recipes r{where} ORDER BY r.name, r.id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        for row in self._conn.execute(sql, params):
            ingredients = self._conn.execute(
                "SELECT name, amount, unit, note, raw, scaling FROM ingredients"
                " WHERE recipe_id = ? ORDER BY position",
                (row["id"],),
            )
            recipe = _recipe_from_row(row, ingredients)
            if halal and recipe.is_haram:
                continue
            yield recipe

    def recipes(self, **filters: object) -> list[Recipe]:
        """List form of :meth:`iter_recipes`."""
        return list(self.iter_recipes(**filters))

    def iter_missing_nutrition(self, *, limit: int | None = None) -> Iterator[Recipe]:
        """Iterate recipes without calories (for the enrichment pass)."""
        sql = "SELECT r.* FROM recipes r WHERE r.calories IS NULL ORDER BY r.id"
        params: list[object] = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        for row in self._conn.execute(sql, params):
            ingredients = self._conn.execute(
                "SELECT name, amount, unit, note, raw, scaling FROM ingredients"
                " WHERE recipe_id = ? ORDER BY position",
                (row["id"],),
            )
            yield _recipe_from_row(row, ingredients)

    def apply_nutrition(
        self,
        updates: Iterable[tuple[Recipe, float, float, float, float]],
    ) -> int:
        """Write estimated nutrition values; mark them as estimates."""
        rows = [
            (
                calories,
                protein,
                fat,
                carbs,
                recipe.source,
                recipe.source_id,
            )
            for recipe, calories, protein, fat, carbs in updates
        ]
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany(
                "UPDATE recipes SET calories = ?, protein = ?, fat = ?, carbs = ?,"
                " nutrition_estimated = 1 WHERE source = ? AND source_id = ?",
                rows,
            )
        return len(rows)

    def fill_missing_servings(self, servings: float = 1.0) -> int:
        """Give recipes without servings a documented default and mark it."""
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE recipes SET servings = ?, servings_estimated = 1"
                " WHERE servings IS NULL",
                (float(servings),),
            )
        return cursor.rowcount

    def mark_unmeasured_ingredients(self) -> int:
        """Mark ingredient lines without an amount as ``to_taste``."""
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE ingredients SET scaling = 'to_taste'"
                " WHERE amount IS NULL AND scaling <> 'to_taste'"
            )
        return cursor.rowcount

    def count(self, **filters: object) -> int:
        """Count matching recipes (the database is already haram-filtered)."""
        where, params = self._where(**filters)
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM recipes r{where}", params
        ).fetchone()
        return int(row[0])

    def stats(self) -> dict:
        """Summary counts by region, source and calorie coverage."""
        total = self._conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        with_calories = self._conn.execute(
            "SELECT COUNT(*) FROM recipes WHERE calories IS NOT NULL"
        ).fetchone()[0]
        estimated_nutrition = self._conn.execute(
            "SELECT COUNT(*) FROM recipes WHERE nutrition_estimated = 1"
        ).fetchone()[0]
        estimated_servings = self._conn.execute(
            "SELECT COUNT(*) FROM recipes WHERE servings_estimated = 1"
        ).fetchone()[0]
        missing_calories = total - with_calories
        missing_servings = self._conn.execute(
            "SELECT COUNT(*) FROM recipes WHERE servings IS NULL"
        ).fetchone()[0]
        regions = {
            row["region"] or "?": row["n"]
            for row in self._conn.execute(
                "SELECT region, COUNT(*) AS n FROM recipes GROUP BY region ORDER BY region"
            )
        }
        sources = {
            row["source"]: row["n"]
            for row in self._conn.execute(
                "SELECT source, COUNT(*) AS n FROM recipes GROUP BY source ORDER BY source"
            )
        }
        return {
            "total": total,
            "with_calories": with_calories,
            "missing_calories": missing_calories,
            "missing_servings": missing_servings,
            "estimated_nutrition": estimated_nutrition,
            "estimated_servings": estimated_servings,
            "regions": regions,
            "sources": sources,
            "path": str(self.path),
        }
