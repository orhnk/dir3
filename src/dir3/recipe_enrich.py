"""Fill missing recipe data from ingredient lines.

The open datasets do not provide calories for every recipe.  This module
estimates them from the ingredient quantities and a small local food table.
Estimates are approximate and are marked in the database
(``nutrition_estimated = 1``); they are not a replacement for a laboratory
analysis or a medical nutrition table.

It also fills missing servings with ``1`` (marked as estimated) and marks
ingredient lines without an amount as ``to_taste``, so the shopping list shows
"nach Bedarf" instead of pretending the amount is known.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .recipes import Recipe, RecipeBook

#: Turkish characters are folded to ASCII so aliases match every source.
_TRANSLIT = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
        "â": "a",
        "Â": "a",
        "î": "i",
        "Î": "i",
        "û": "u",
        "Û": "u",
    }
)


def _fold(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold().translate(_TRANSLIT)
    text = re.sub(r"[^\w\s%]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True, slots=True)
class FoodValue:
    """Nutrition per 100 g plus optional piece weight and density."""

    calories: float
    protein: float
    fat: float
    carbs: float
    piece_g: float | None = None
    density: float = 1.0


def _food(
    aliases: tuple[str, ...],
    calories: float,
    protein: float,
    fat: float,
    carbs: float,
    *,
    piece_g: float | None = None,
    density: float = 1.0,
) -> tuple[tuple[str, ...], FoodValue]:
    return (
        tuple(_fold(alias) for alias in aliases),
        FoodValue(calories, protein, fat, carbs, piece_g, density),
    )


#: Approximate values per 100 g.  The table covers the most frequent German,
#: Turkish, English and Arabic ingredient names in the bulk sources.
_FOODS = (
    _food(("tuz", "salz", "salt", "ملح"), 0, 0, 0, 0),
    _food(("su", "wasser", "water", "ماء"), 0, 0, 0, 0),
    _food(
        ("seker", "toz seker", "pudra sekeri", "zucker", "sugar", "سكر"),
        400,
        0,
        0,
        100,
        density=0.85,
    ),
    _food(("un", "unu", "mehl", "flour", "طحين", "دقيق"), 364, 10, 1, 76, density=0.53),
    _food(("sut", "milch", "milk", "حليب", "لبن"), 61, 3.2, 3.3, 4.8, density=1.03),
    _food(("yogurt", "yoghurt", "joghurt", "لبن رائب"), 61, 3.5, 3.3, 4.7, density=1.03),
    _food(("yumurta", "ei", "eier", "egg", "eggs", "بيض"), 155, 13, 11, 1.1, piece_g=50),
    _food(("yumurta sarisi", "eigelb", "egg yolk", "صفار البيض"), 322, 16, 27, 3.6, piece_g=17),
    _food(("yumurta aki", "eiweiss", "egg white", "بياض البيض"), 52, 11, 0.2, 0.7, piece_g=33),
    _food(
        (
            "sivi yag",
            "aycicek yagi",
            "zeytinyagi",
            "zeytinyag",
            "olive oil",
            "olivenol",
            "oil",
            "vegetable oil",
            "زيت",
        ),
        884,
        0,
        100,
        0,
        density=0.92,
    ),
    _food(("tereyagi", "tereyag", "butter", "زبدة"), 717, 0.9, 81, 0.1, piece_g=14, density=0.91),
    _food(("margarin", "margarine"), 717, 0.9, 81, 0.1, density=0.91),
    _food(("krema", "sahne", "cream", "قشطة"), 340, 2.8, 36, 2.8, density=1.0),
    _food(("krem santi", "schlagsahne pulver", "whipped cream powder"), 300, 3, 20, 28),
    _food(("kasar peyniri", "kasar", "kashkaval", "kaşar"), 350, 25, 27, 2),
    _food(("beyaz peynir", "feta", "white cheese", "جبن ابيض"), 264, 17, 21, 4),
    _food(("krem peynir", "cream cheese", "philadelphia"), 342, 6, 34, 4),
    _food(("labne", "labneh", "لبنة"), 250, 7, 22, 6),
    _food(("kiyma", "hackfleisch", "minced meat", "ground beef", "لحم مفروم"), 250, 26, 17, 0),
    _food(("tavuk gogsu", "huhnbrust", "chicken breast", "صدر دجاج"), 165, 31, 3.6, 0, piece_g=200),
    _food(("tavuk", "huhn", "chicken", "دجاج"), 165, 31, 3.6, 0, piece_g=150),
    _food(("dana eti", "sigir eti", "rindfleisch", "beef", "لحم بقري"), 250, 26, 17, 0),
    _food(("balik", "fisch", "fish", "سمك"), 130, 20, 5, 0, piece_g=150),
    _food(("pirinc", "reis", "rice", "أرز"), 365, 7, 0.7, 80, density=0.85),
    _food(("bulgur", "bulgur"), 342, 12, 1.3, 76, density=0.85),
    _food(("makarna", "nudel", "pasta", "معكرونة"), 371, 13, 1.5, 75),
    _food(("irmik", "griess", "semolina", "سميد"), 360, 12, 1, 73, density=0.8),
    _food(("nisasta", "starke", "starch", "نشا"), 381, 0.3, 0.1, 91, density=0.6),
    _food(("kakao", "cocoa", "كاكاو"), 228, 20, 14, 58, density=0.4),
    _food(("bal", "honig", "honey", "عسل"), 304, 0.3, 0, 82, density=1.4),
    _food(("tahin", "tahini", "طحينة"), 595, 17, 54, 21),
    _food(("ceviz", "walnuss", "walnut", "جوز"), 654, 15, 65, 14),
    _food(("findik", "haselnuss", "hazelnut", "بندق"), 628, 15, 61, 17),
    _food(("badem", "mandel", "almond", "لوز"), 579, 21, 50, 22),
    _food(("antep fistigi", "fistik", "pistazie", "pistachio", "فستق"), 560, 20, 45, 28),
    _food(("hindistan cevizi", "kokos", "coconut", "جوز الهند"), 354, 3, 33, 15),
    _food(("susam", "sesam", "sesame", "سمسم"), 573, 17, 50, 23),
    _food(("domates", "tomate", "tomato", "طماطم"), 18, 0.9, 0.2, 3.9, piece_g=120),
    _food(
        ("domates salcasi", "tomatenmark", "tomato paste", "معجون طماطم"),
        82,
        4,
        0.5,
        19,
        density=1.1,
    ),
    _food(
        ("biber salcasi", "paprika mark", "pepper paste", "معجون فلفل"), 80, 2, 0.5, 16, density=1.1
    ),
    _food(("patates", "kartoffel", "potato", "بطاطس"), 77, 2, 0.1, 17, piece_g=170),
    _food(("havuc", "karotte", "carrot", "جزر"), 41, 0.9, 0.2, 10, piece_g=80),
    _food(("sogan", "zwiebel", "onion", "بصل"), 40, 1.1, 0.1, 9, piece_g=110),
    _food(("sarimsak", "knoblauch", "garlic", "ثوم"), 149, 6, 0.5, 33, piece_g=3),
    _food(("limon", "zitrone", "lemon", "ليمون"), 29, 1.1, 0.3, 9, piece_g=100),
    _food(
        ("limon suyu", "limonun suyu", "zitronensaft", "lemon juice", "عصير ليمون"),
        22,
        0.4,
        0.2,
        6.9,
    ),
    _food(("karabiber", "pfeffer", "black pepper", "فلفل اسود"), 251, 10, 3, 64),
    _food(("pul biber", "pulbiber", "chiliflocken", "chili flakes", "فلفل احمر"), 282, 12, 14, 50),
    _food(("kekik", "thymian", "thyme", "زعتر"), 101, 6, 2, 24),
    _food(("kimyon", "kreuzkummel", "cumin", "كمون"), 375, 18, 22, 44),
    _food(("tarcin", "zimt", "cinnamon", "قرفة"), 247, 4, 1, 81),
    _food(("nane", "minze", "mint", "نعناع"), 70, 4, 0.7, 15),
    _food(("maydanoz", "petersilie", "parsley", "بقدونس"), 36, 3, 0.8, 6, piece_g=30),
    _food(("dereotu", "dill", "شبت"), 43, 3.5, 1.1, 7, piece_g=20),
    _food(("vanilya", "vanilin", "vanille", "vanilla", "فانيليا"), 288, 0.1, 0.1, 13),
    _food(
        ("kabartma tozu", "backpulver", "baking powder", "بيكنج باودر"), 53, 0, 0, 28, piece_g=10
    ),
    _food(("karbonat", "natron", "baking soda", "صودا الخبز"), 0, 0, 0, 0),
    _food(("yas maya", "frische hefe", "fresh yeast"), 105, 8, 0.5, 18, piece_g=42),
    _food(("maya", "hefe", "yeast", "خميرة"), 325, 40, 7, 41, piece_g=10),
    _food(
        ("yesil biber", "gruene paprika", "green pepper", "فلفل اخضر"),
        20,
        0.9,
        0.2,
        4.6,
        piece_g=120,
    ),
    _food(("kirmizi biber", "rote paprika", "red pepper", "فلفل احمر"), 31, 1, 0.3, 6, piece_g=120),
    _food(("kapya biber", "kapia", "kapya"), 31, 1, 0.3, 6, piece_g=150),
    _food(("patlican", "aubergine", "eggplant", "باذنجان"), 25, 1, 0.2, 6, piece_g=250),
    _food(("kabak", "zucchini", "courgette", "كوسا"), 17, 1.2, 0.3, 3.1, piece_g=200),
    _food(("salatalik", "gurke", "cucumber", "خيار"), 15, 0.7, 0.1, 3.6, piece_g=150),
    _food(("lahana", "kohl", "cabbage", "ملفوف"), 25, 1.3, 0.1, 6),
    _food(("ispanak", "spinat", "spinach", "سبانخ"), 23, 2.9, 0.4, 3.6),
    _food(("mantar", "pilz", "mushroom", "مشروم"), 22, 3.1, 0.3, 3.3),
    _food(("nohut", "kichererbse", "chickpea", "حمص"), 364, 19, 6, 61, density=0.85),
    _food(("mercimek", "linse", "lentil", "عدس"), 352, 25, 1, 63, density=0.85),
    _food(("fasulye", "bohne", "bean", "beans", "فاصوليا"), 333, 24, 1.2, 60),
    _food(("zeytin", "olive", "olives", "زيتون"), 115, 0.8, 11, 6, piece_g=4),
    _food(("kuru uzum", "rosine", "raisin", "زبيب"), 299, 3, 0.5, 79),
    _food(("hurma", "dattel", "date", "تمر"), 282, 2.5, 0.4, 75, piece_g=8),
    _food(("muz", "banane", "banana", "موز"), 89, 1.1, 0.3, 23, piece_g=120),
    _food(("elma", "apfel", "apple", "تفاح"), 52, 0.3, 0.2, 14, piece_g=180),
    _food(("portakal", "orange", "برتقال"), 47, 0.9, 0.1, 12, piece_g=150),
    _food(("cilek", "erdbeere", "strawberry", "فراولة"), 32, 0.7, 0.3, 8, piece_g=12),
    _food(("cikolata", "schokolade", "chocolate", "شوكولاتة"), 546, 5, 31, 61),
    _food(("mayonez", "mayonnaise", "مايونيز"), 680, 1, 75, 1),
    _food(("sirke", "essig", "vinegar", "خل"), 21, 0, 0, 0.9, density=1.0),
    _food(("nar eksisi", "granatapfelsirup", "pomegranate syrup", "دبس رمان"), 293, 0.4, 0, 73),
    _food(("ekmek", "brot", "bread", "خبز"), 265, 9, 3.2, 49, piece_g=30),
    _food(("yufka", "filo", "phyllo", "يوفكا"), 300, 9, 2, 60, piece_g=100),
    _food(("galeta unu", "semmelbrot", "breadcrumbs", "بقسماط"), 400, 12, 8, 72),
    _food(("kayisi", "aprikose", "apricot", "مشمش"), 48, 1.4, 0.4, 11, piece_g=35),
    _food(("seftali", "pfirsich", "peach", "خوخ"), 39, 0.9, 0.3, 10, piece_g=150),
    _food(("uzum", "traube", "grape", "عنب"), 69, 0.7, 0.2, 18),
    _food(("nar", "granatapfel", "pomegranate", "رمان"), 83, 1.7, 1.2, 19),
    _food(("pekmez", "melasse", "molasses", "دبس"), 293, 0, 0, 73),
    _food(("sut tozu", "milchpulver", "milk powder", "حليب بودرة"), 496, 26, 27, 38),
    _food(("salca", "tomatenmark", "tomato paste", "معجون"), 82, 4, 0.5, 19, density=1.1),
    _food(("biber", "paprika", "pepper", "فلفل"), 31, 1, 0.3, 6, piece_g=120),
    _food(("kori", "curry", "currypulver", "كاري"), 325, 14, 14, 56),
    _food(("has has", "hashas", "mohn", "poppy seed", "خشخاش"), 525, 18, 42, 28),
    _food(("visne suyu", "sauerkirschsaft", "sour cherry juice"), 50, 0.5, 0.1, 12),
    _food(("etimek", "zwieback", "rusk", "بقسماط"), 400, 10, 5, 78, piece_g=10),
    _food(
        ("milfoy", "blatterteig", "puff pastry", "عجينة", "عجين"),
        400,
        6,
        24,
        40,
        piece_g=250,
    ),
    _food(("kuru erik", "backpflaume", "dried plum", "برقوق مجفف"), 240, 2, 0.4, 64, piece_g=10),
    _food(("sucuk", "sujuk", "sucuk"), 450, 20, 40, 2),
    _food(
        ("kuru kayisi", "getrocknete aprikose", "dried apricot", "مشمش مجفف"),
        241,
        3.4,
        0.5,
        63,
        piece_g=8,
    ),
    _food(
        ("kuru incir", "getrocknete feige", "dried fig", "تين مجفف"), 249, 3.3, 0.9, 64, piece_g=20
    ),
    _food(("findik ezmesi", "haselnussmus", "hazelnut spread"), 550, 6, 34, 55),
    _food(
        ("fistik ezmesi", "erdnussbutter", "peanut butter", "زبدة الفول السوداني"), 588, 25, 50, 20
    ),
    _food(("tahin helvasi", "halva", "حلاوة طحينية"), 500, 12, 30, 45),
    _food(("biskuvi", "keks", "biscuit", "بسكويت"), 450, 7, 16, 70, piece_g=10),
    _food(("kraker", "cracker", "مقرمشات"), 450, 9, 15, 70, piece_g=5),
)

_FOOD_INDEX = sorted(
    ((alias, value) for aliases, value in _FOODS for alias in aliases),
    key=lambda pair: len(pair[0]),
    reverse=True,
)

_MASS_UNITS = {
    "g": 1.0,
    "gr": 1.0,
    "gram": 1.0,
    "gramm": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "kilogram": 1000.0,
    "kilogramm": 1000.0,
    "mg": 0.001,
}
_VOLUME_UNITS = {
    "ml": 1.0,
    "mililiter": 1.0,
    "milliliter": 1.0,
    "l": 1000.0,
    "liter": 1000.0,
    "litre": 1000.0,
    "cl": 10.0,
    "dl": 100.0,
}
_SPOON_UNITS = {
    "yemek kasigi": 15.0,
    "tablespoon": 15.0,
    "tbsp": 15.0,
    "el": 15.0,
    "tatli kasigi": 5.0,
    "teaspoon": 5.0,
    "tsp": 5.0,
    "tl": 5.0,
    "cay kasigi": 2.5,
    "yemek kasik": 15.0,
}
_CUP_UNITS = {
    "su bardagi": 200.0,
    "bardak": 200.0,
    "cay bardagi": 100.0,
    "cup": 240.0,
    "cups": 240.0,
    "tasse": 200.0,
    "kase": 200.0,
    "fincan": 60.0,
    "kahve fincani": 60.0,
}
_PIECE_UNITS = {
    "adet",
    "tane",
    "piece",
    "pieces",
    "stuck",
    "stueck",
    "st",
    "stk",
    "unit",
    "units",
    "paket",
    "kutu",
    "dose",
    "can",
    "demet",
    "bunch",
    "tutam",
    "pinch",
    "dilim",
    "slice",
    "yaprak",
    "dis",
    "clove",
    "handful",
    "avuc",
}


def lookup_food(name: str) -> FoodValue | None:
    """Find the longest matching food alias in an ingredient name."""
    text = _fold(name)
    for alias, value in _FOOD_INDEX:
        if len(alias) <= 3:
            if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text):
                return value
        elif alias in text:
            return value
    return None


def _unit_grams(amount: float, unit: str, food: FoodValue) -> float | None:
    key = _fold(unit)
    if key in _MASS_UNITS:
        return amount * _MASS_UNITS[key]
    if key in _VOLUME_UNITS:
        return amount * _VOLUME_UNITS[key] * food.density
    if key in _SPOON_UNITS:
        return amount * _SPOON_UNITS[key] * food.density
    if key in _CUP_UNITS:
        return amount * _CUP_UNITS[key] * food.density
    if key in _PIECE_UNITS:
        if food.piece_g is not None:
            return amount * food.piece_g
        return None
    if not key:
        if food.piece_g is not None and amount <= 12:
            return amount * food.piece_g
        if amount >= 50:
            return amount
    return None


@dataclass(frozen=True, slots=True)
class NutritionEstimate:
    """Estimated per-serving values and the ingredient coverage."""

    calories: float
    protein: float
    fat: float
    carbs: float
    coverage: float
    known: int
    total: int


def estimate_recipe(recipe: Recipe) -> NutritionEstimate | None:
    """Estimate per-serving nutrition from measurable ingredients.

    Returns ``None`` when too few ingredients have a known amount/unit or a
    plausible calorie value.  The caller decides how to store the estimate.
    """
    if recipe.calories is not None:
        return None
    servings = recipe.servings or 1.0
    if servings <= 0:
        return None
    total = 0
    known = 0
    calories = protein = fat = carbs = 0.0
    for ingredient in recipe.ingredients:
        total += 1
        if ingredient.amount is None or ingredient.amount <= 0:
            continue
        food = lookup_food(ingredient.name)
        if food is None:
            continue
        grams = _unit_grams(ingredient.amount, ingredient.unit, food)
        if grams is None or grams <= 0:
            continue
        known += 1
        factor = grams / 100.0
        calories += food.calories * factor
        protein += food.protein * factor
        fat += food.fat * factor
        carbs += food.carbs * factor
    if total == 0:
        return None
    if known < 2 and not (known == total and known == 1):
        return None
    coverage = known / total
    if coverage < 0.4:
        return None
    calories /= servings
    if not 5 <= calories <= 5000:
        return None
    return NutritionEstimate(
        calories=round(calories, 2),
        protein=round(protein / servings, 2),
        fat=round(fat / servings, 2),
        carbs=round(carbs / servings, 2),
        coverage=round(coverage, 3),
        known=known,
        total=total,
    )


@dataclass(slots=True)
class EnrichmentStats:
    """What one enrichment run changed."""

    scanned: int = 0
    nutrition_filled: int = 0
    nutrition_skipped: int = 0
    servings_filled: int = 0
    unmeasured_marked: int = 0
    batches: int = 0


def enrich_database(
    path: str | Path,
    *,
    limit: int | None = None,
    batch_size: int = 500,
) -> EnrichmentStats:
    """Estimate missing nutrition and mark estimated fields in ``path``."""
    stats = EnrichmentStats()
    with RecipeBook(path) as book:
        stats.servings_filled = book.fill_missing_servings()
        stats.unmeasured_marked = book.mark_unmeasured_ingredients()
        pending: list[tuple[Recipe, float, float, float, float]] = []
        for recipe in book.iter_missing_nutrition(limit=limit):
            stats.scanned += 1
            estimate = estimate_recipe(recipe)
            if estimate is None:
                stats.nutrition_skipped += 1
                continue
            pending.append(
                (
                    recipe,
                    estimate.calories,
                    estimate.protein,
                    estimate.fat,
                    estimate.carbs,
                )
            )
            if len(pending) >= batch_size:
                book.apply_nutrition(pending)
                stats.nutrition_filled += len(pending)
                stats.batches += 1
                pending.clear()
        if pending:
            book.apply_nutrition(pending)
            stats.nutrition_filled += len(pending)
            stats.batches += 1
    return stats
