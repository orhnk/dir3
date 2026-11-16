"""Normalizers for Zenodo, Turkish Recipes 175K and UniTools."""

import csv
import json

from dir3 import TARGET_REGIONS, RecipeBook, recipe_sources
from dir3.recipe_sources import (
    SOURCES,
    describe_sources,
    download_source,
    iter_source_recipes,
)


def _write_zenodo(path):
    fields = [
        "Name",
        "Author",
        "Date",
        "Rating Value",
        "Rating Count",
        "Preparation Time",
        "Cooking Time",
        "Category",
        "Cuisine",
        "Ingredients",
        "Ingredients_Raw",
        "Instructions",
        "Cooking Methods",
        "Implements",
        "Number of steps",
        "Servings",
        "Nutrition",
        "URL",
    ]
    rows = [
        {
            "Name": "Käsespätzle",
            "Cuisine": "['German']",
            "Category": "['Dinner']",
            "Ingredients": repr(
                [
                    {"ingredient": "Spätzle", "quantity": "500", "unit": "g", "misc": ""},
                    {"ingredient": "Käse", "quantity": "200", "unit": "g", "misc": "gerieben"},
                ]
            ),
            "Instructions": repr(["Kochen.", "Servieren."]),
            "Servings": repr(["4"]),
            "Nutrition": repr(
                {
                    "Calories": "600 kcal",
                    "Protein": "20 g",
                    "Fat": "25 g",
                    "Carbohydrates": "70 g",
                }
            ),
            "Preparation Time": "10",
            "Cooking Time": "20",
            "URL": "https://example.test/kasespaetzle",
        },
        {
            "Name": "Mercimek Çorbası",
            "Cuisine": "['Turkish']",
            "Ingredients": repr(
                [{"ingredient": "Linsen", "quantity": "250", "unit": "g", "misc": ""}]
            ),
            "Servings": repr(["4", "4 servings"]),
            "Nutrition": repr({"Calories": "180 kcal"}),
            "URL": "https://example.test/mercimek",
        },
        {
            "Name": "Pancakes",
            "Cuisine": "['American']",
            "Ingredients": repr(
                [{"ingredient": "Flour", "quantity": "200", "unit": "g", "misc": ""}]
            ),
            "URL": "https://example.test/pancakes",
        },
        {
            "Name": "Schweinebraten",
            "Cuisine": "['German']",
            "Ingredients": repr(
                [{"ingredient": "Schweinefleisch", "quantity": "1", "unit": "kg", "misc": ""}]
            ),
            "URL": "https://example.test/schweinebraten",
        },
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def test_zenodo_normalizer_filters_regions_and_keeps_nutrition(tmp_path):
    path = tmp_path / "culinary.csv"
    _write_zenodo(path)
    recipes = list(iter_source_recipes("zenodo-culinary", [path], regions=TARGET_REGIONS))
    assert [recipe.name for recipe in recipes] == [
        "Käsespätzle",
        "Mercimek Çorbası",
        "Schweinebraten",
    ]
    german = recipes[0]
    assert german.region == "de"
    assert german.servings == 4
    assert german.calories == 600
    assert german.protein == 20
    assert german.carbs == 70
    assert german.minutes == 30
    assert german.ingredients[0].amount == 500
    assert german.ingredients[0].unit == "g"
    assert german.source == "zenodo-culinary"
    assert german.source_id == "https://example.test/kasespaetzle"


def test_zenodo_default_import_keeps_all_cuisines_but_not_haram(tmp_path):
    path = tmp_path / "culinary.csv"
    _write_zenodo(path)
    with RecipeBook(tmp_path / "recipes.db") as book:
        stats = book.add_many(iter_source_recipes("zenodo-culinary", [path]))
        assert stats.imported == 3
        assert stats.haram == 1
        assert book.count() == 3
        assert book.recipes(query="Pancakes")[0].region == ""


def test_turkish_normalizer_parses_lines_and_nutrition(tmp_path):
    path = tmp_path / "turkish.jsonl"
    path.write_text(
        json.dumps(
            {
                "title": "Mercimek Çorbası",
                "ingredients": ["1 su bardağı mercimek", "2 yemek kaşığı zeytinyağı"],
                "instructions": ["Kochen."],
                "category": "Çorbalar",
                "tags": ["Vegan"],
                "servings": "4",
                "prep_time": "PT10M",
                "cook_time": "PT20M",
                "nutrition": {
                    "calories": "180",
                    "Protein(g)": "9",
                    "Yağ(g)": "6",
                    "Karbonhidrat(g)": "24",
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    recipe = list(iter_source_recipes("turkish-recipes-175k", [path]))[0]
    assert recipe.region == "tr"
    assert recipe.calories == 180
    assert recipe.protein == 9
    assert recipe.fat == 6
    assert recipe.carbs == 24
    assert recipe.minutes == 30
    assert recipe.ingredients[0].amount == 1
    assert recipe.ingredients[0].unit == "su bardağı"
    assert recipe.source == "turkish-recipes-175k"


def test_unitools_normalizer_filters_countries(tmp_path):
    path = tmp_path / "unitools.json"
    path.write_text(
        json.dumps(
            {
                "recipes": [
                    {
                        "slug": "kaesespaetzle",
                        "country": "DE",
                        "name": {"en": "Cheese Spätzle"},
                        "baseServings": 4,
                        "nutritionPerServing": {
                            "calories": 600,
                            "protein": 20,
                            "fat": 25,
                            "carbs": 70,
                        },
                        "ingredients": [
                            {
                                "name": {"en": "Spätzle"},
                                "quantity": 500,
                                "unit": "g",
                                "scaling": "linear",
                            }
                        ],
                        "steps": [{"text": {"en": "Cook."}, "minutes": 10}],
                    },
                    {
                        "slug": "mercimek",
                        "country": "TR",
                        "name": {"en": "Lentil Soup"},
                        "baseServings": 4,
                        "nutritionPerServing": {"calories": 180},
                        "ingredients": [],
                        "steps": [],
                    },
                    {
                        "slug": "koshari",
                        "country": "EG",
                        "name": {"en": "Koshari"},
                        "baseServings": 6,
                        "nutritionPerServing": {"calories": 450},
                        "ingredients": [],
                        "steps": [],
                    },
                    {
                        "slug": "pancakes",
                        "country": "US",
                        "name": {"en": "Pancakes"},
                        "baseServings": 4,
                        "ingredients": [],
                        "steps": [],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    recipes = list(
        iter_source_recipes("unitools-recipes", [path], regions=TARGET_REGIONS)
    )
    assert [recipe.name for recipe in recipes] == [
        "Cheese Spätzle",
        "Lentil Soup",
        "Koshari",
    ]
    assert [recipe.region for recipe in recipes] == ["de", "tr", "ar"]
    assert recipes[0].ingredients[0].amount == 500


def test_unitools_default_import_keeps_all_countries(tmp_path):
    path = tmp_path / "unitools.json"
    path.write_text(
        json.dumps(
            {
                "recipes": [
                    {
                        "slug": "pancakes",
                        "country": "US",
                        "name": {"en": "Pancakes"},
                        "baseServings": 4,
                        "ingredients": [],
                        "steps": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    recipes = list(iter_source_recipes("unitools-recipes", [path]))
    assert [recipe.name for recipe in recipes] == ["Pancakes"]
    assert recipes[0].region == ""
    assert recipes[0].cuisine == "US"


def test_download_source_uses_cache_and_refresh(tmp_path, monkeypatch):
    calls = []

    def fake_download(url, target, progress=None):
        calls.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
        return target

    monkeypatch.setattr(recipe_sources, "_download", fake_download)
    first = download_source("unitools-recipes", cache_dir=tmp_path)
    second = download_source("unitools-recipes", cache_dir=tmp_path)
    third = download_source("unitools-recipes", cache_dir=tmp_path, refresh=True)
    assert len(calls) == 2
    assert first == second == third
    assert first[0].exists()


def test_source_catalog_and_descriptions():
    assert set(SOURCES) == {
        "zenodo-culinary",
        "turkish-recipes-175k",
        "unitools-recipes",
    }
    text = describe_sources()
    assert "ODC-ODbL" in text
    assert "Apache-2.0" in text
    assert "CC BY-SA 4.0" in text
