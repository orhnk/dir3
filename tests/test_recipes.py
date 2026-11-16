"""Recipe model, parser, haram filter and SQLite RecipeBook."""

import json

import pytest

from dir3 import (
    HaramIngredientError,
    Ingredient,
    Recipe,
    RecipeBook,
    find_haram,
    normalize_region,
    parse_amount,
    parse_ingredient_line,
    parse_minutes,
    parse_servings,
)


def _book(tmp_path):
    return RecipeBook(tmp_path / "recipes.db")


def test_parse_amount_handles_fractions_words_and_ranges():
    assert parse_amount("1,5") == 1.5
    assert parse_amount("1 1/2") == 1.5
    assert parse_amount("½") == 0.5
    assert parse_amount("2-3") == 2.0
    assert parse_amount("yarım") == 0.5
    assert parse_amount("halbe") == 0.5
    assert parse_amount("نصف") == 0.5
    assert parse_amount(None) is None


def test_parse_servings_accepts_lists_and_text():
    assert parse_servings("4 kişilik") == 4
    assert parse_servings(["16", "1 cake"]) == 16
    assert parse_servings("8-10") == 8
    assert parse_servings(None) is None


def test_parse_minutes_accepts_iso_and_turkish_units():
    assert parse_minutes("PT1H30M") == 90
    assert parse_minutes("30 dk") == 30
    assert parse_minutes("1 saat") == 60
    assert parse_minutes("0dk") == 0


def test_parse_ingredient_line_multilingual_units():
    german = parse_ingredient_line("2 EL Olivenöl")
    assert (german.amount, german.unit, german.name) == (2.0, "EL", "Olivenöl")
    turkish = parse_ingredient_line("1 su bardağı yulaf")
    assert (turkish.amount, turkish.unit, turkish.name) == (1.0, "su bardağı", "yulaf")
    arabic = parse_ingredient_line("٢ كوب أرز")
    assert (arabic.amount, arabic.unit, arabic.name) == (2.0, "كوب", "أرز")
    assert parse_ingredient_line("200g Spaghetti").unit == "g"
    assert parse_ingredient_line("Salz und Pfeffer").name == "Salz und Pfeffer"


def test_haram_filter_detects_pork_alcohol_and_blood():
    assert find_haram("Schweinefleisch") == "Schweinefleisch"
    assert find_haram("Bacon Pasta") == "Schweinefleisch"
    assert find_haram("Weißwein") == "Alkohol"
    assert find_haram("نبيذ") == "Alkohol"
    assert find_haram("Blutwurst") == "Blut"
    assert find_haram("Mercimek Çorbası") is None
    # no false positives inside other words
    assert find_haram("graham crackers") is None
    assert find_haram("Weinblätter") is None
    assert find_haram("kanat") is None


def test_region_normalization():
    assert normalize_region("German Inspired") == "de"
    assert normalize_region("TR") == "tr"
    assert normalize_region("EG") == "ar"
    assert normalize_region("Middle Eastern Inspired") == "ar"
    assert normalize_region("Persian") == ""


def test_recipe_scales_ingredients_but_keeps_per_serving_calories():
    recipe = Recipe(
        "Suppe",
        ingredients=(Ingredient("Linsen", 250, "g"), Ingredient("Salz", None, "Prise")),
        servings=4,
        calories=180,
    )
    scaled = recipe.scaled(8)
    assert scaled.servings == 8
    assert scaled.ingredients[0].amount == 500
    assert scaled.ingredients[1].amount is None
    assert scaled.calories == 180


def test_recipe_book_add_duplicate_and_filters(tmp_path):
    with _book(tmp_path) as book:
        soup = Recipe(
            "Mercimek",
            ingredients=(Ingredient("Linsen", 250, "g"),),
            servings=4,
            calories=180,
            region="tr",
        )
        cake = Recipe(
            "Kuchen",
            ingredients=(Ingredient("Mehl", 300, "g"), Ingredient("Zucker", 100, "g")),
            calories=420,
            region="de",
        )
        assert book.add(soup) is True
        assert book.add(soup) is False
        assert book.add(cake) is True
        assert book.count() == 2
        assert [r.name for r in book.recipes(region="tr")] == ["Mercimek"]
        assert [r.name for r in book.recipes(max_calories=200)] == ["Mercimek"]
        assert [r.name for r in book.recipes(ingredient="Zucker")] == ["Kuchen"]
        assert [r.name for r in book.recipes(query="kuchen")] == ["Kuchen"]
        assert [r.name for r in book.recipes(limit=1)] == ["Kuchen"]
        assert book.stats()["with_calories"] == 2
        assert book.clear("user") == 2
        assert book.count() == 0


def test_recipe_book_rejects_and_skips_haram(tmp_path):
    with _book(tmp_path) as book:
        with pytest.raises(HaramIngredientError):
            book.add(
                Recipe("Bacon", ingredients=(Ingredient("bacon", 100, "g"),))
            )
        stats = book.add_many(
            [
                Recipe("Bacon", ingredients=(Ingredient("bacon", 100, "g"),)),
                Recipe("Reis", ingredients=(Ingredient("Reis", 200, "g"),)),
                Recipe("", ingredients=(Ingredient("Reis", 200, "g"),)),
            ]
        )
        assert (stats.imported, stats.haram, stats.invalid) == (1, 1, 1)
        assert book.count() == 1
        empty = book.add_many([Recipe("Nur ein Name")])
        assert (empty.imported, empty.invalid) == (1, 0)
        assert book.count() == 2


def test_recipe_book_import_json_and_jsonl(tmp_path):
    payload = {
        "name": "Mercimek",
        "servings": 4,
        "calories": "180 kcal",
        "region": "tr",
        "ingredients": ["1 su bardağı mercimek", {"name": "Salz", "amount": 1, "unit": "Prise"}],
        "instructions": ["Kochen."],
    }
    json_path = tmp_path / "recipes.json"
    json_path.write_text(json.dumps([payload]), encoding="utf-8")
    jsonl_path = tmp_path / "more.jsonl"
    jsonl_path.write_text(
        json.dumps({**payload, "name": "Mercimek 2"}) + "\n", encoding="utf-8"
    )
    with _book(tmp_path) as book:
        assert book.import_json(json_path).imported == 1
        assert book.import_jsonl(jsonl_path).imported == 1
        recipe = book.recipes(query="Mercimek 2")[0]
        assert recipe.ingredients[0].amount == 1
        assert recipe.ingredients[0].unit == "su bardağı"
        assert recipe.calories == 180
        assert recipe.region == "tr"
        assert recipe.instructions == ("Kochen.",)
