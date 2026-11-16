"""Diet engine: targets, filters, weekly plan and shopping list."""

import json
from datetime import date, time

import pytest

from dir3 import (
    DietProfile,
    Ingredient,
    MealPlanEntry,
    MealPlanSettings,
    Recipe,
    RecipeBook,
    ShoppingSettings,
    basal_metabolic_rate,
    build_shopping_list,
    daily_calorie_target,
    nutrition_targets,
    plan_meals,
    recipe_allowed,
    shopping_task,
)
from dir3.recipe_cli import main

PROFILE = DietProfile(80, 180, 30, sex="m", activity=1.4)


def _recipe(book: RecipeBook, name: str, calories: float, **kwargs) -> Recipe:
    ingredients = kwargs.pop(
        "ingredients",
        (Ingredient("Zutat", 100, "g"),),
    )
    recipe = Recipe(
        name,
        ingredients=ingredients,
        servings=kwargs.pop("servings", 4),
        calories=calories,
        **kwargs,
    )
    assert book.add(recipe)
    return recipe


def test_bmr_targets_and_goal_adjustment():
    assert basal_metabolic_rate(PROFILE) == pytest.approx(1780)
    assert daily_calorie_target(PROFILE) == pytest.approx(2492)
    lose = DietProfile(80, 180, 30, sex="m", activity=1.4, goal="lose")
    assert daily_calorie_target(lose) == pytest.approx(2092)
    targets = nutrition_targets(PROFILE)
    assert targets.calories == pytest.approx(2492)
    assert targets.protein_g == pytest.approx(96)
    assert targets.fat_g == pytest.approx(83.07, abs=0.01)
    assert targets.carbs_g > 0


def test_female_bmr_and_profile_aliases():
    female = DietProfile(60, 165, 30, sex="female", activity="moderate", goal="abnehmen")
    assert basal_metabolic_rate(female) == pytest.approx(1320.25)
    assert female.sex == "f"
    assert female.activity == pytest.approx(1.55)
    assert female.goal == "lose"
    with pytest.raises(ValueError):
        DietProfile(0, 180, 30)
    with pytest.raises(ValueError):
        DietProfile(80, 180, 30, sex="x")
    with pytest.raises(ValueError):
        DietProfile(80, 180, 30, activity=3)
    with pytest.raises(ValueError):
        DietProfile(80, 180, 30, goal="bulk")


def test_allergies_conditions_and_limits():
    milk = Recipe("Milchreis", (Ingredient("Milch", 500, "ml"),), calories=300)
    cheese = Recipe("Börek", (Ingredient("Beyaz peynir", 200, "g"),), calories=300)
    peanut = Recipe("Erdnuss-Sauce", (Ingredient("Erdnussmus", 2, "EL"),), calories=300)
    plain = Recipe("Linsen", (Ingredient("Linsen", 200, "g"),), calories=300)
    assert not recipe_allowed(milk, DietProfile(80, 180, 30, allergies=("lactose",)))
    assert not recipe_allowed(cheese, DietProfile(80, 180, 30, allergies=("lactose",)))
    assert not recipe_allowed(peanut, DietProfile(80, 180, 30, allergies=("nuts",)))
    assert recipe_allowed(plain, DietProfile(80, 180, 30, allergies=("lactose", "nuts")))
    assert not recipe_allowed(
        plain, DietProfile(80, 180, 30, avoid_ingredients=("linsen",))
    )
    diabetes = DietProfile(80, 180, 30, conditions=("diabetes",))
    assert not recipe_allowed(
        Recipe("Süß", (Ingredient("Zucker", 100, "g"),), calories=300, carbs=80),
        diabetes,
    )
    assert recipe_allowed(
        Recipe("Herzhaft", (Ingredient("Zucchini", 200, "g"),), calories=300, carbs=20),
        diabetes,
    )
    assert not recipe_allowed(Recipe("Ohne Werte", (Ingredient("Wasser"),)), PROFILE)


def test_meal_plan_is_deterministic_and_complete(tmp_path):
    with RecipeBook(tmp_path / "recipes.db") as book:
        for index, calories in enumerate((900, 1100, 1250, 1300, 1400, 1600)):
            _recipe(book, f"Gericht {index}", calories)
        settings = MealPlanSettings(
            days=3, meals=("lunch", "dinner"), people=2, servings_per_person=1, seed=11
        )
        plan = plan_meals(book, PROFILE, settings, start_date=date(2026, 1, 5))
        again = plan_meals(book, PROFILE, settings, start_date=date(2026, 1, 5))
        assert len(plan.entries) == 6
        assert [entry.recipe.name for entry in plan.entries] == [
            entry.recipe.name for entry in again.entries
        ]
        assert plan.days() == [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
        assert all(entry.servings == 2 for entry in plan.entries)
        assert all(entry.recipe.calories is not None for entry in plan.entries)
        assert "Ziel:" in plan.text()
        assert "Gericht" in plan.text()


def test_favorites_mode_prefers_favorite(tmp_path):
    with RecipeBook(tmp_path / "recipes.db") as book:
        _recipe(book, "Favorit Linsen", 1300)
        _recipe(book, "Anderes Gericht", 1300)
        profile = DietProfile(80, 180, 30, favorites=("Favorit",))
        settings = MealPlanSettings(
            days=2, meals=("lunch", "dinner"), mode="favorites", seed=3
        )
        plan = plan_meals(book, profile, settings, start_date=date(2026, 1, 5))
        assert all(entry.recipe.name == "Favorit Linsen" for entry in plan.entries)


def test_plan_without_candidates_raises(tmp_path):
    with RecipeBook(tmp_path / "recipes.db") as book:
        _recipe(book, "Zu leicht", 10)
        with pytest.raises(ValueError, match="kein passendes Rezept"):
            plan_meals(book, PROFILE, MealPlanSettings(days=1), start_date=date(2026, 1, 5))


def _entry(day: date, recipe: Recipe, servings: float) -> MealPlanEntry:
    return MealPlanEntry(
        date=day,
        meal="dinner",
        recipe=recipe,
        servings=servings,
        calories=(recipe.calories or 0) * servings / (recipe.servings or 1),
    )


def test_shopping_list_merges_scales_and_converts_units():
    first = Recipe(
        "Linsensuppe",
        (
            Ingredient("Linsen", 500, "g"),
            Ingredient("Tomaten", 1, "kg"),
            Ingredient("Öl", 2, "EL"),
            Ingredient("Salz"),
        ),
        servings=4,
        calories=300,
    )
    second = Recipe(
        "Linsen-Salat",
        (Ingredient("linsen", 250, "g"), Ingredient("Wasser", 1, "l")),
        servings=4,
        calories=200,
    )
    shopping = build_shopping_list(
        [
            _entry(date(2026, 1, 5), first, 8),
            _entry(date(2026, 1, 8), second, 4),
        ],
        runs=2,
    )
    assert len(shopping.runs) == 2
    first_run = {item.name: item for item in shopping.runs[0].items}
    assert first_run["linsen"].amount == pytest.approx(1000)
    assert first_run["tomaten"].amount == pytest.approx(2000)
    assert first_run["tomaten"].unit == "g"
    assert first_run["öl"].amount == pytest.approx(4)
    assert first_run["salz"].amount is None
    assert first_run["salz"].unknown is True
    second_run = {item.name: item for item in shopping.runs[1].items}
    assert second_run["linsen"].amount == pytest.approx(250)
    assert second_run["wasser"].unit == "ml"
    assert second_run["wasser"].amount == pytest.approx(1000)


def test_shopping_list_keeps_unknown_amount_next_to_known():
    recipe = Recipe(
        "Salz und Pfeffer",
        (Ingredient("Salz"), Ingredient("Salz", 5, "g")),
        servings=1,
        calories=10,
    )
    shopping = build_shopping_list([_entry(date(2026, 1, 5), recipe, 1)])
    items = shopping.runs[0].items
    known = next(item for item in items if item.unit == "g")
    unknown = next(item for item in items if not item.unit)
    assert known.amount == pytest.approx(5)
    assert known.unknown is False
    assert unknown.amount is None
    assert "nach Bedarf" in unknown.text()


def test_shopping_task_duration_depends_on_item_count():
    recipe = Recipe(
        "Viel",
        tuple(Ingredient(f"Zutat {index}", 1, "g") for index in range(10)),
        servings=1,
        calories=100,
    )
    shopping = build_shopping_list([_entry(date(2026, 1, 5), recipe, 1)])
    run = shopping.runs[0]
    minute, event = shopping_task(run, start=time(10, 0))
    assert minute == 10 * 60
    assert event.duration is not None
    assert event.duration.total_seconds() // 60 == 30
    capped = shopping_task(
        run,
        ShoppingSettings(base_minutes=15, minutes_per_item=10, max_minutes=60),
        start="10:00",
    )
    assert capped[1].duration is not None
    assert capped[1].duration.total_seconds() // 60 == 60


def test_diet_cli_prints_plan_and_shopping(tmp_path, capsys):
    db = tmp_path / "recipes.db"
    with RecipeBook(db) as book:
        _recipe(book, "Linsen Gericht", 1300)
        _recipe(book, "Reis Gericht", 1200)
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "weight_kg": 80,
                "height_cm": 180,
                "age": 30,
                "sex": "m",
                "activity": "moderate",
                "goal": "maintain",
            }
        ),
        encoding="utf-8",
    )
    outcome = main(
        [
            "diet",
            "--profile",
            str(profile),
            "--db",
            str(db),
            "--days",
            "2",
            "--runs",
            "2",
            "--seed",
            "5",
        ]
    )
    output = capsys.readouterr().out
    assert outcome == 0
    assert "Ziel:" in output
    assert "Einkauf 1" in output
    assert "Einkaufsdauer:" in output
