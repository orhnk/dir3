"""Personal diet engine: daily targets, weekly meal plan and shopping list.

The engine is a recommendation helper, not medical advice.  It uses the
Mifflin-St Jeor formula for the basal metabolic rate, an activity factor and a
modest goal adjustment, then picks recipes from :class:`~dir3.recipes.RecipeBook`
that fit the per-meal calorie and macro budget.

Example::

    from dir3 import DietProfile, MealPlanSettings, RecipeBook, plan_meals

    profile = DietProfile(
        weight_kg=80, height_cm=180, age=30, sex="m",
        activity="moderate", goal="maintain",
        allergies=("lactose",), favorites=("mercimek",),
    )
    with RecipeBook.open() as book:
        plan = plan_meals(book, profile, MealPlanSettings(days=7, meals=("lunch", "dinner")))
        print(plan.text())
        print(plan.shopping_list(runs=2).text())

Allergies and conditions are keyword filters over the ingredient names.  The
data sets do not contain sodium or sugar columns, so hypertension and diabetes
rules are intentionally coarse.  Always check the result yourself.
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

from .core import Task, task
from .recipes import Recipe, RecipeBook
from .timeutils import time_from_minutes, to_minutes

#: Activity labels understood by :class:`DietProfile`.
ACTIVITY_LEVELS = {
    "sedentary": 1.2,
    "sitzend": 1.2,
    "light": 1.375,
    "leicht": 1.375,
    "moderate": 1.55,
    "moderat": 1.55,
    "active": 1.725,
    "aktiv": 1.725,
    "very active": 1.9,
    "sehr aktiv": 1.9,
}

#: Daily calorie adjustment per goal.
GOAL_ADJUSTMENTS = {
    "lose": -400.0,
    "abnehmen": -400.0,
    "maintain": 0.0,
    "halten": 0.0,
    "gain": 300.0,
    "zunehmen": 300.0,
}

#: Share of the daily calories per meal (normalized to the selected meals).
MEAL_SHARES = {"breakfast": 0.25, "lunch": 0.40, "dinner": 0.35, "snack": 0.10}

#: Ingredient keywords for common allergies/intolerances.  The lists cover
#: German, Turkish, English and Arabic names; matching is case-insensitive.
ALLERGEN_TERMS: dict[str, tuple[str, ...]] = {
    "gluten": (
        "weizen", "wheat", "mehl", "flour", "brot", "bread", "nudel", "pasta",
        "teigware", "couscous", "bulgur", "yufka", "pide", "lavash", "lavas",
        "ekmek", "makarna", "gerste", "barley", "roggen", "rye", "dinkel",
        "spelt", "semmel", "brioche", "grieß", "griess", "un", "unu",
        "galeta", "irmik", "şehriye", "sehriye", "erişte", "eriste",
    ),
    "lactose": (
        "milch", "milk", "süt", "sahne", "cream", "butter", "käse", "kaese",
        "cheese", "joghurt", "yogurt", "yoğurt", "ayran", "labneh", "feta",
        "mozzarella", "mozarella", "parmesan", "quark", "schmand",
        "crème fraîche", "creme fraiche", "peynir", "tereyağı", "tereyagi",
        "kaymak", "kefir", "krema", "لبن", "حليب", "جبن", "زبدة",
    ),
    "nuts": (
        "nuss", "nüsse", "nuss", "nut", "nuts", "mandel", "almond", "walnuss",
        "walnut", "haselnuss", "hazelnut", "pistazie", "pistachio", "cashew",
        "erdnuss", "peanut", "ceviz", "fıstık", "badem", "fındık", "findik",
        "لوز", "جوز", "فستق",
    ),
    "egg": (
        "ei", "eier", "eigelb", "eiweiß", "eiweiss", "egg", "eggs",
        "yumurta", "بيض",
    ),
    "soy": ("soja", "soy", "tofu", "edamame", "tamari", "صويا"),
    "shellfish": (
        "garnele", "garnelen", "shrimp", "prawn", "krabbe", "crab", "lobster",
        "hummer", "muschel", "shellfish", "karides", "قريدس", "جمبري",
    ),
    "fish": (
        "fisch", "fish", "lachs", "salmon", "thunfisch", "tuna", "sardine",
        "anchovy", "hamsi", "balık", "سمك", "تونة",
    ),
    "sesame": ("sesam", "sesame", "tahini", "tahin", "سمسم", "طحينة"),
}

#: Salt-heavy ingredient names; the datasets have no sodium column.
_SALT_TERMS = (
    "salz", "salt", "sodium", "sojasauce", "soy sauce", "bouillon",
    "brühe", "bruehe", "broth", "stock cube", "salzstange", "tuz", "sodyum",
)

#: Coarse disease rules.  These are keyword/limit heuristics, not treatment.
CONDITION_RULES: dict[str, dict[str, Any]] = {
    "diabetes": {"max_carbs_per_meal": 60.0},
    "zuckerkrankheit": {"max_carbs_per_meal": 60.0},
    "hypertension": {"avoid": _SALT_TERMS},
    "bluthochdruck": {"avoid": _SALT_TERMS},
    "celiac": {"allergens": ("gluten",)},
    "coeliac": {"allergens": ("gluten",)},
    "zöliakie": {"allergens": ("gluten",)},
    "lactose": {"allergens": ("lactose",)},
    "laktose": {"allergens": ("lactose",)},
}

#: Common names for an allergy that map to one keyword group.
_ALLERGEN_ALIASES = {
    "milk": "lactose",
    "milch": "lactose",
    "dairy": "lactose",
    "süt": "lactose",
    "sut": "lactose",
    "nut": "nuts",
    "nuss": "nuts",
    "peanut": "nuts",
    "erdnuss": "nuts",
    "zöliakie": "gluten",
    "zoeliakie": "gluten",
}


def _fold(value: object) -> str:
    return unicodedata.normalize("NFC", str(value)).casefold().strip()


def _as_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = re.split(r"[,;]", value)
    elif isinstance(value, Iterable):
        parts = value
    else:
        parts = (value,)
    seen: list[str] = []
    for part in parts:
        text = str(part).strip()
        if text and text.casefold() not in {item.casefold() for item in seen}:
            seen.append(text)
    return tuple(seen)


@dataclass(frozen=True, slots=True)
class DietProfile:
    """Body data, goal, allergies and food preferences of one person."""

    weight_kg: float
    height_cm: float
    age: int
    sex: str = "m"
    activity: float = 1.4
    goal: str = "maintain"
    allergies: tuple[str, ...] = ()
    avoid_ingredients: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    favorites: tuple[str, ...] = ()
    max_carbs_per_meal: float | None = None
    max_fat_per_meal: float | None = None

    def __post_init__(self) -> None:
        if self.weight_kg <= 0:
            raise ValueError("weight_kg must be positive")
        if self.height_cm <= 0:
            raise ValueError("height_cm must be positive")
        if self.age <= 0:
            raise ValueError("age must be positive")
        sex = _fold(self.sex)
        if sex in ("m", "male", "mann", "maennlich", "männlich"):
            sex = "m"
        elif sex in ("f", "female", "frau", "weiblich"):
            sex = "f"
        else:
            raise ValueError("sex must be 'm'/'male' or 'f'/'female'")
        object.__setattr__(self, "sex", sex)
        activity = self.activity
        if isinstance(activity, str):
            key = _fold(activity)
            if key not in ACTIVITY_LEVELS:
                raise ValueError(
                    f"unknown activity {activity!r}; use {', '.join(sorted(ACTIVITY_LEVELS))}"
                )
            activity = ACTIVITY_LEVELS[key]
        if not 1.0 <= float(activity) <= 2.5:
            raise ValueError("activity must be between 1.0 and 2.5")
        object.__setattr__(self, "activity", float(activity))
        goal = _fold(self.goal)
        if goal not in GOAL_ADJUSTMENTS:
            raise ValueError("goal must be lose, maintain or gain")
        goal = {"abnehmen": "lose", "zunehmen": "gain", "halten": "maintain"}.get(goal, goal)
        object.__setattr__(self, "goal", goal)
        for name in (
            "allergies", "avoid_ingredients", "conditions", "favorites"
        ):
            object.__setattr__(self, name, _as_tuple(getattr(self, name)))
        for name in ("max_carbs_per_meal", "max_fat_per_meal"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive or None")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DietProfile:
        return cls(
            weight_kg=float(data.get("weight_kg", data.get("weight"))),
            height_cm=float(data.get("height_cm", data.get("height"))),
            age=int(data["age"]),
            sex=str(data.get("sex", "m")),
            activity=data.get("activity", 1.4),
            goal=str(data.get("goal", "maintain")),
            allergies=data.get("allergies", ()),
            avoid_ingredients=data.get("avoid_ingredients", ()),
            conditions=data.get("conditions", ()),
            favorites=data.get("favorites", ()),
            max_carbs_per_meal=data.get("max_carbs_per_meal"),
            max_fat_per_meal=data.get("max_fat_per_meal"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "weight_kg": self.weight_kg,
            "height_cm": self.height_cm,
            "age": self.age,
            "sex": self.sex,
            "activity": self.activity,
            "goal": self.goal,
            "allergies": list(self.allergies),
            "avoid_ingredients": list(self.avoid_ingredients),
            "conditions": list(self.conditions),
            "favorites": list(self.favorites),
            "max_carbs_per_meal": self.max_carbs_per_meal,
            "max_fat_per_meal": self.max_fat_per_meal,
        }


@dataclass(frozen=True, slots=True)
class NutritionTarget:
    """Daily calorie and macro target for one person."""

    calories: float
    protein_g: float
    fat_g: float
    carbs_g: float

    def to_dict(self) -> dict[str, float]:
        return {
            "calories": round(self.calories, 1),
            "protein_g": round(self.protein_g, 1),
            "fat_g": round(self.fat_g, 1),
            "carbs_g": round(self.carbs_g, 1),
        }


def basal_metabolic_rate(profile: DietProfile) -> float:
    """Mifflin-St Jeor basal metabolic rate in kcal/day."""
    base = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * profile.age
    return base + 5 if profile.sex == "m" else base - 161


def daily_calorie_target(profile: DietProfile) -> float:
    """BMR times activity plus the goal adjustment."""
    return basal_metabolic_rate(profile) * profile.activity + GOAL_ADJUSTMENTS[profile.goal]


def nutrition_targets(profile: DietProfile) -> NutritionTarget:
    """Calories plus a simple protein/fat/carbohydrate split.

    Protein is 1.2 g/kg body weight (1.6 g/kg when gaining), fat is 30 % of
    the calories, carbohydrates fill the rest.  Diabetes lowers the carb
    target to 45 % of the calories.
    """
    calories = max(800.0, daily_calorie_target(profile))
    protein = profile.weight_kg * (1.6 if profile.goal == "gain" else 1.2)
    fat = calories * 0.30 / 9
    carb_share = 0.45 if _has_condition(profile, "diabetes") else 1.0
    carbs = max(0.0, (calories - protein * 4 - fat * 9) / 4)
    if carb_share < 1.0:
        carbs = min(carbs, calories * carb_share / 4)
    return NutritionTarget(calories, protein, fat, carbs)


def _has_condition(profile: DietProfile, name: str) -> bool:
    return any(name in _fold(condition) for condition in profile.conditions)


def _condition_rules(profile: DietProfile) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for condition in profile.conditions:
        key = _fold(condition)
        for name, rule in CONDITION_RULES.items():
            if name in key:
                rules.append(rule)
    return rules


def max_carbs_per_meal(profile: DietProfile) -> float | None:
    limits = [
        rule["max_carbs_per_meal"]
        for rule in _condition_rules(profile)
        if "max_carbs_per_meal" in rule
    ]
    if profile.max_carbs_per_meal is not None:
        limits.append(profile.max_carbs_per_meal)
    return min(limits) if limits else None


def _term_matches(term: str, text: str) -> bool:
    if len(term) <= 3:
        return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None
    return term in text


def avoid_terms(profile: DietProfile) -> tuple[str, ...]:
    """All ingredient keywords excluded by allergies, conditions and preferences."""
    terms: list[str] = []
    for allergy in profile.allergies:
        key = _fold(allergy)
        key = _ALLERGEN_ALIASES.get(key, key)
        matched = False
        for name, keywords in ALLERGEN_TERMS.items():
            if name in key or key in name:
                terms.extend(keywords)
                matched = True
        if not matched:
            terms.append(key)
    terms.extend(_fold(item) for item in profile.avoid_ingredients)
    for rule in _condition_rules(profile):
        terms.extend(_fold(item) for item in rule.get("avoid", ()))
        for name in rule.get("allergens", ()):
            terms.extend(ALLERGEN_TERMS.get(name, (name,)))
    unique: list[str] = []
    for term in terms:
        term = term.strip()
        if term and term not in unique:
            unique.append(term)
    return tuple(unique)


def recipe_allowed(
    recipe: Recipe,
    profile: DietProfile,
    *,
    max_calories: float | None = None,
) -> bool:
    """Whether ``recipe`` fits the profile's allergies, conditions and limits."""
    if recipe.calories is None:
        return False
    if max_calories is not None and recipe.calories > max_calories:
        return False
    blob = _fold(
        " ".join(
            [recipe.name, *(ingredient.name for ingredient in recipe.ingredients), *recipe.tags]
        )
    )
    if any(_term_matches(term, blob) for term in avoid_terms(profile)):
        return False
    carb_limit = max_carbs_per_meal(profile)
    if carb_limit is not None and recipe.carbs is not None and recipe.carbs > carb_limit:
        return False
    if (
        profile.max_fat_per_meal is not None
        and recipe.fat is not None
        and recipe.fat > profile.max_fat_per_meal
    ):
        return False
    return True


@dataclass(frozen=True, slots=True)
class MealPlanSettings:
    """How many days, which meals, for how many people and how to choose."""

    days: int = 7
    meals: tuple[str, ...] = ("lunch", "dinner")
    people: int = 1
    servings_per_person: float = 1.0
    mode: str = "mix"
    favorite_bonus: float = 0.35
    repeat_penalty: float = 2.0
    avoid_repeats_days: int = 3
    seed: int | None = None
    candidate_limit: int = 400

    def __post_init__(self) -> None:
        if self.days <= 0:
            raise ValueError("days must be positive")
        if self.people <= 0:
            raise ValueError("people must be positive")
        if self.servings_per_person <= 0:
            raise ValueError("servings_per_person must be positive")
        meals = self.meals
        if isinstance(meals, str):
            meals = tuple(part.strip() for part in meals.split(",") if part.strip())
        meals = tuple(_fold(meal) for meal in meals)
        if not meals:
            raise ValueError("meals must not be empty")
        object.__setattr__(self, "meals", meals)
        mode = _fold(self.mode)
        if mode not in ("balanced", "favorites", "mix"):
            raise ValueError("mode must be balanced, favorites or mix")
        object.__setattr__(self, "mode", mode)
        if self.avoid_repeats_days < 0:
            raise ValueError("avoid_repeats_days must not be negative")
        if self.candidate_limit <= 0:
            raise ValueError("candidate_limit must be positive")


@dataclass(frozen=True, slots=True)
class MealPlanEntry:
    """One selected recipe for one meal.

    ``calories`` is per person; ``servings`` is the total number of portions to
    cook (for the whole household).
    """

    date: date
    meal: str
    recipe: Recipe
    servings: float
    calories: float

    @property
    def portions(self) -> float:
        return self.servings


@dataclass(frozen=True, slots=True)
class MealPlan:
    profile: DietProfile
    targets: NutritionTarget
    entries: tuple[MealPlanEntry, ...]
    settings: MealPlanSettings

    def days(self) -> list[date]:
        return sorted({entry.date for entry in self.entries})

    def day_calories(self) -> dict[date, float]:
        totals: dict[date, float] = defaultdict(float)
        for entry in self.entries:
            totals[entry.date] += entry.calories
        return dict(totals)

    def text(self) -> str:
        lines = [
            f"Ziel: {self.targets.calories:.0f} kcal/Tag, "
            f"{self.targets.protein_g:.0f} g Protein, "
            f"{self.targets.fat_g:.0f} g Fett, {self.targets.carbs_g:.0f} g KH"
        ]
        for day in self.days():
            entries = [entry for entry in self.entries if entry.date == day]
            total = sum(entry.calories for entry in entries)
            lines.append("")
            lines.append(f"{day.strftime('%a %d.%m.%Y')} - {total:.0f} kcal")
            for entry in entries:
                suffix = " pro Person" if self.settings.people > 1 else ""
                portion = "Portion" if entry.servings == 1 else "Portionen"
                lines.append(
                    f"  {entry.meal:10} {entry.recipe.name} "
                    f"({entry.calories:.0f} kcal{suffix}, {entry.servings:g} {portion})"
                )
        return "\n".join(lines)

    def shopping_list(self, *, runs: int = 1) -> ShoppingList:
        return build_shopping_list(self.entries, runs=runs)


def _meal_shares(meals: Sequence[str]) -> dict[str, float]:
    raw = {meal: MEAL_SHARES.get(meal, 1.0) for meal in meals}
    total = sum(raw.values())
    return {meal: share / total for meal, share in raw.items()}


def _is_favorite(recipe: Recipe, favorites: Sequence[str]) -> bool:
    name = _fold(recipe.name)
    return any(_fold(favorite) in name for favorite in favorites)


def _macro_error(recipe: Recipe, targets: NutritionTarget, share: float) -> float:
    errors: list[float] = []
    for value, target in (
        (recipe.protein, targets.protein_g * share),
        (recipe.fat, targets.fat_g * share),
        (recipe.carbs, targets.carbs_g * share),
    ):
        if value is not None and target > 0:
            errors.append(abs(value - target) / target)
    return (sum(errors) / len(errors)) * 0.25 if errors else 0.0


def _candidates(
    book: RecipeBook,
    profile: DietProfile,
    target_calories: float,
    limit: int,
) -> list[Recipe]:
    for span in (0.30, 0.45, 0.65, 0.85):
        low = max(1.0, target_calories * (1 - span))
        high = target_calories * (1 + span)
        found = [
            recipe
            for recipe in book.iter_recipes(
                min_calories=low, max_calories=high, limit=limit
            )
            if recipe_allowed(recipe, profile)
        ]
        if found:
            return found
    return []


def _pick(
    candidates: Sequence[Recipe],
    profile: DietProfile,
    settings: MealPlanSettings,
    targets: NutritionTarget,
    share: float,
    meal_target: float,
    recent: dict[str, int],
    day_index: int,
    rng: random.Random,
) -> Recipe:
    favorites = [_fold(item) for item in profile.favorites]
    favorite_recipes = [
        recipe for recipe in candidates if _is_favorite(recipe, favorites)
    ]
    pool = (
        favorite_recipes
        if settings.mode == "favorites" and favorite_recipes
        else list(candidates)
    )

    def score(recipe: Recipe) -> float:
        calories = recipe.calories or 1.0
        penalty = abs(calories - meal_target) / meal_target
        penalty += _macro_error(recipe, targets, share)
        last = recent.get(recipe.name)
        if (
            settings.avoid_repeats_days
            and last is not None
            and day_index - last < settings.avoid_repeats_days
        ):
            penalty += settings.repeat_penalty
        if settings.mode == "mix" and _is_favorite(recipe, favorites):
            penalty -= settings.favorite_bonus
        if settings.mode == "favorites" and favorite_recipes and recipe not in favorite_recipes:
            penalty += 10.0
        return penalty + rng.random() * 0.01

    return min(pool, key=score)


def plan_meals(
    book: RecipeBook,
    profile: DietProfile,
    settings: MealPlanSettings | None = None,
    *,
    start_date: date | None = None,
) -> MealPlan:
    """Build a meal plan for ``settings.days`` days.

    Recipes need calories; recipes without nutrition are skipped.  Each meal
    gets one recipe per person; ``people`` only scales the shopping quantities,
    not the calorie target.  The selection is deterministic for a given
    ``seed``.
    """
    settings = settings or MealPlanSettings()
    targets = nutrition_targets(profile)
    shares = _meal_shares(settings.meals)
    start = start_date or date.today()
    rng = random.Random(settings.seed)
    recent: dict[str, int] = {}
    entries: list[MealPlanEntry] = []

    for day_index in range(settings.days):
        current = start + timedelta(days=day_index)
        for meal in settings.meals:
            share = shares[meal]
            meal_target = targets.calories * share / settings.servings_per_person
            candidates = _candidates(book, profile, meal_target, settings.candidate_limit)
            if not candidates:
                raise ValueError(
                    f"kein passendes Rezept fuer {meal} an {current.isoformat()} "
                    f"({meal_target:.0f} kcal)"
                )
            recipe = _pick(
                candidates,
                profile,
                settings,
                targets,
                share,
                meal_target,
                recent,
                day_index,
                rng,
            )
            entry_servings = settings.people * settings.servings_per_person
            entries.append(
                MealPlanEntry(
                    date=current,
                    meal=meal,
                    recipe=recipe,
                    servings=entry_servings,
                    calories=(recipe.calories or 0.0) * settings.servings_per_person,
                )
            )
            recent[recipe.name] = day_index
    return MealPlan(profile, targets, tuple(entries), settings)


# ---------------------------------------------------------------------------
# Shopping list
# ---------------------------------------------------------------------------

#: Unit conversions that are safe without a density table.  Everything else
#: (cups, spoons, pieces) stays in its own unit.
_UNIT_CONVERSIONS: dict[str, tuple[str, float]] = {
    "kg": ("g", 1000.0),
    "kilogramm": ("g", 1000.0),
    "kilo": ("g", 1000.0),
    "g": ("g", 1.0),
    "gr": ("g", 1.0),
    "gramm": ("g", 1.0),
    "gram": ("g", 1.0),
    "mg": ("g", 0.001),
    "l": ("ml", 1000.0),
    "lt": ("ml", 1000.0),
    "liter": ("ml", 1000.0),
    "litre": ("ml", 1000.0),
    "ml": ("ml", 1.0),
    "milliliter": ("ml", 1.0),
    "cl": ("ml", 10.0),
    "dl": ("ml", 100.0),
}


def _normalize_unit(unit: str) -> tuple[str, float]:
    text = unit.strip()
    key = _fold(text)
    if key in _UNIT_CONVERSIONS:
        return _UNIT_CONVERSIONS[key]
    return text, 1.0


def _normalize_name(name: str) -> str:
    text = _fold(name)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,;:-")


@dataclass(frozen=True, slots=True)
class ShoppingItem:
    """One aggregated shopping position."""

    name: str
    amount: float | None
    unit: str
    recipes: int = 1
    unknown: bool = False

    def text(self) -> str:
        if self.amount is None:
            quantity = "nach Bedarf"
        else:
            quantity = f"{_format_amount(self.amount)} {self.unit}".strip()
            if self.unknown:
                quantity += " + nach Bedarf"
        return f"{quantity} {self.name}".strip()


@dataclass(frozen=True, slots=True)
class ShoppingRun:
    index: int
    start: date
    end: date
    items: tuple[ShoppingItem, ...]

    @property
    def item_count(self) -> int:
        return len(self.items)

    def text(self) -> str:
        lines = [f"Einkauf {self.index + 1}: {self.start:%d.%m.} - {self.end:%d.%m.}"]
        lines.extend(f"  {item.text()}" for item in self.items)
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ShoppingList:
    runs: tuple[ShoppingRun, ...]

    @property
    def item_count(self) -> int:
        return sum(run.item_count for run in self.runs)

    def text(self) -> str:
        return "\n\n".join(run.text() for run in self.runs)


def _format_amount(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value))}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def build_shopping_list(entries: Sequence[MealPlanEntry], *, runs: int = 1) -> ShoppingList:
    """Aggregate the ingredients of ``entries`` into one or more shopping runs.

    ``runs`` splits the plan by day (two runs on a seven-day plan are four and
    three days).  Amounts are scaled from the recipe's servings to the planned
    portions; kg/g and l/ml are normalized.  Ingredient lines without an amount
    are kept as "nach Bedarf".
    """
    if runs <= 0:
        raise ValueError("runs must be positive")
    if not entries:
        return ShoppingList(())
    days = sorted({entry.date for entry in entries})
    run_count = max(1, min(int(runs), len(days)))
    buckets: list[dict[tuple[str, str], dict[str, Any]]] = [
        {} for _ in range(run_count)
    ]
    day_index = {day: index for index, day in enumerate(days)}
    for entry in entries:
        index = min(run_count - 1, day_index[entry.date] * run_count // len(days))
        bucket = buckets[index]
        factor = (
            entry.servings / entry.recipe.servings
            if entry.recipe.servings and entry.recipe.servings > 0
            else 1.0
        )
        for ingredient in entry.recipe.ingredients:
            name = _normalize_name(ingredient.name)
            if not name:
                continue
            unit, unit_factor = _normalize_unit(ingredient.unit)
            key = (name, unit)
            current = bucket.setdefault(
                key,
                {"amount": 0.0, "known": False, "unknown": False, "recipes": 0},
            )
            current["recipes"] += 1
            if ingredient.amount is None:
                current["unknown"] = True
            else:
                current["known"] = True
                current["amount"] += ingredient.amount * factor * unit_factor
    result: list[ShoppingRun] = []
    for index, bucket in enumerate(buckets):
        items = tuple(
            sorted(
                (
                    ShoppingItem(
                        name=name,
                        amount=payload["amount"] if payload["known"] else None,
                        unit=unit,
                        recipes=payload["recipes"],
                        unknown=payload["unknown"],
                    )
                    for (name, unit), payload in bucket.items()
                ),
                key=lambda item: item.name,
            )
        )
        run_days = [
            day
            for day in days
            if min(run_count - 1, day_index[day] * run_count // len(days)) == index
        ]
        if not run_days:
            continue
        result.append(
            ShoppingRun(index=index, start=run_days[0], end=run_days[-1], items=items)
        )
    return ShoppingList(tuple(result))


@dataclass(frozen=True, slots=True)
class ShoppingSettings:
    """How the shopping event length is derived from the item count."""

    base_minutes: int = 15
    minutes_per_item: float = 1.5
    max_minutes: int = 120
    name: str = "Einkaufen"
    flex: bool = False

    def __post_init__(self) -> None:
        if self.base_minutes < 0:
            raise ValueError("base_minutes must not be negative")
        if self.minutes_per_item < 0:
            raise ValueError("minutes_per_item must not be negative")
        if self.max_minutes <= 0:
            raise ValueError("max_minutes must be positive")
        if not self.name:
            raise ValueError("name must not be empty")

    def minutes_for(self, run: ShoppingRun) -> int:
        if not run.items:
            return 0
        return min(
            self.max_minutes,
            int(round(self.base_minutes + self.minutes_per_item * len(run.items))),
        )


def shopping_task(
    run: ShoppingRun,
    settings: ShoppingSettings | None = None,
    *,
    start: int | time | str,
) -> tuple[int, Task]:
    """Return ``(minute, task)`` for one shopping run.

    The duration grows with the number of items: ``base_minutes +
    minutes_per_item * item_count``, capped at ``max_minutes``.
    """
    settings = settings or ShoppingSettings()
    begin = start if isinstance(start, int) else to_minutes(start)
    minutes = settings.minutes_for(run)
    return begin, task(
        f"{settings.name} {run.index + 1} ({run.item_count} Artikel)",
        start=time_from_minutes(begin),
        duration=timedelta(minutes=minutes),
        flex=settings.flex,
    )
