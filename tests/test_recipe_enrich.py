"""Ingredient-based nutrition estimation and database enrichment."""

import json

from dir3 import (
    Ingredient,
    Recipe,
    RecipeBook,
    enrich_database,
    estimate_recipe,
)
from dir3.recipe_cli import main


def test_estimate_recipe_from_common_ingredients():
    recipe = Recipe(
        "Menemen",
        ingredients=(
            Ingredient("yumurta", 2, "adet"),
            Ingredient("domates", 1, "adet"),
            Ingredient("zeytinyağı", 1, "yemek kaşığı"),
            Ingredient("tuz", 1, "çay kaşığı"),
        ),
        servings=2,
    )
    estimate = estimate_recipe(recipe)
    assert estimate is not None
    assert 120 <= estimate.calories <= 190
    assert estimate.protein > 5
    assert estimate.total == 4
    assert estimate.known == 4


def test_estimate_requires_enough_measured_ingredients():
    unknown = Recipe(
        "Rätsel",
        ingredients=(Ingredient("xyz", 100, "g"), Ingredient("abc", 2, "adet")),
        servings=2,
    )
    assert estimate_recipe(unknown) is None
    partly = Recipe(
        "Halb bekannt",
        ingredients=(
            Ingredient("un", 100, "g"),
            Ingredient("xyz", 100, "g"),
            Ingredient("abc", 1, "adet"),
        ),
        servings=2,
    )
    assert estimate_recipe(partly) is None


def test_enrichment_fills_nutrition_servings_and_marks_unmeasured(tmp_path):
    db = tmp_path / "recipes.db"
    with RecipeBook(db) as book:
        book.add(
            Recipe(
                "Menemen",
                ingredients=(
                    Ingredient("yumurta", 2, "adet"),
                    Ingredient("domates", 1, "adet"),
                    Ingredient("zeytinyağı", 1, "yemek kaşığı"),
                    Ingredient("tuz", None, "Prise"),
                ),
                servings=2,
            )
        )
        book.add(Recipe("Nur Salz", ingredients=(Ingredient("Salz"),)))

    stats = enrich_database(db)
    assert stats.scanned == 2
    assert stats.nutrition_filled == 1
    assert stats.servings_filled == 1
    assert stats.unmeasured_marked >= 2

    with RecipeBook(db) as book:
        menemen = book.recipes(query="Menemen")[0]
        assert menemen.calories is not None
        assert menemen.protein is not None
        assert menemen.nutrition_estimated is True
        assert menemen.servings == 2
        assert menemen.servings_estimated is False
        assert menemen.ingredients[-1].scaling == "to_taste"
        salt = book.recipes(query="Nur Salz")[0]
        assert salt.servings == 1
        assert salt.servings_estimated is True
        assert salt.calories is None
        report = book.stats()
        assert report["estimated_nutrition"] == 1
        assert report["estimated_servings"] == 1


def test_enrich_cli_reports_json(tmp_path, capsys):
    db = tmp_path / "recipes.db"
    with RecipeBook(db) as book:
        book.add(
            Recipe(
                "Suppe",
                ingredients=(Ingredient("mercimek", 200, "g"), Ingredient("su", 1, "l")),
                servings=4,
            )
        )
    outcome = main(["enrich", "--db", str(db), "--limit", "1"])
    assert outcome == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scanned"] == 1
    assert payload["nutrition_filled"] == 1
