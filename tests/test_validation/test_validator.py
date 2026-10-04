import pytest

from recipe_planner.validation.validator import validate_ingredients, validate_recipes

# ---------------------------------------------------------------------------
# Fixtures / helpers
#
# These build a minimal, fully valid recipe and ingredient from scratch.
# Individual tests take a fresh copy and mutate just the one thing they're
# testing, so each test is only exercising the behaviour it claims to.
# ---------------------------------------------------------------------------


def valid_recipe() -> dict:
    return {
        "name": "Test Recipe",
        "description": "A recipe used for testing",
        "link": "https://example.com/recipe",
        "number_of_meals": 4,
        "can_freeze": True,
        "cooking_time": {
            "initial_cook": {"active_minutes": 30, "total_minutes": 45},
            "subsequent_occasions": {"active_minutes": 5, "total_minutes": 10},
        },
        "eat_at_work": True,
        "unhealthy": False,
        "tags": ["tasty"],
        "ingredients": [
            {"name": "onion", "quantity": 1, "unit": "whole"},
        ],
    }


def wrap_recipe(
    recipe: dict, recipe_id: str = "test_recipe", category: str = "main_dishes"
) -> dict:
    """Wrap a single recipe in the {category: {recipe_id: recipe}} shape
    that validate_recipes expects."""
    return {category: {recipe_id: recipe}}


def valid_ingredient() -> dict:
    return {
        "name": "onion",
        "canonical_unit": "whole",
        "purchase_options": [{"quantity": 1, "cost": 0.20}],
        "shelf_life_days": {"pantry": 30},
        "nutrition": {
            "per": 100,
            "unit": "g",
            "amount_per_canonical_unit": 150,
            "source": "Test Source",
            "calories": 40,
            "protein": 1.1,
            "carbohydrates": 9.3,
            "sugars": 4.2,
            "fat": 0.1,
            "saturated_fat": 0.0,
            "fibre": 1.7,
        },
    }


def wrap_ingredient(ingredient: dict, ingredient_id: str = "test_ingredient") -> dict:
    """Wrap a single ingredient in the {ingredient_id: ingredient} shape
    that validate_ingredients expects."""
    return {ingredient_id: ingredient}


def has_error_containing(errors: list, *fragments: str) -> bool:
    """True if at least one error message contains every given fragment.
    Used instead of exact string matching so tests don't break on minor
    wording changes, while still checking the error is actually about
    what the test expects."""
    return any(all(fragment in error for fragment in fragments) for error in errors)


# ---------------------------------------------------------------------------
# validate_recipes
# ---------------------------------------------------------------------------


class TestValidateRecipes:
    def test_valid_recipe_has_no_errors(self):
        errors = validate_recipes(wrap_recipe(valid_recipe()))
        assert errors == []

    @pytest.mark.parametrize(
        "field",
        [
            "name",
            "description",
            "link",
            "number_of_meals",
            "can_freeze",
            "cooking_time",
            "eat_at_work",
            "unhealthy",
            "tags",
            "ingredients",
        ],
    )
    def test_missing_required_field_is_reported(self, field):
        recipe = valid_recipe()
        del recipe[field]

        errors = validate_recipes(wrap_recipe(recipe))

        assert has_error_containing(errors, field, "missing required field")

    @pytest.mark.parametrize(
        "field, bad_value",
        [
            ("number_of_meals", "four"),
            ("can_freeze", "yes"),
            ("eat_at_work", 1),
            ("unhealthy", "no"),
            ("tags", "tasty"),  # should be a list, not a bare string
            ("ingredients", {"name": "onion"}),  # should be a list, not a dict
        ],
    )
    def test_field_with_wrong_type_is_reported(self, field, bad_value):
        recipe = valid_recipe()
        recipe[field] = bad_value

        errors = validate_recipes(wrap_recipe(recipe))

        assert has_error_containing(errors, field)

    def test_rejects_bool_where_int_expected(self):
        # bool is a subclass of int in Python, so this specifically checks
        # the check_type guard against a True/False slipping through.
        recipe = valid_recipe()
        recipe["number_of_meals"] = True

        errors = validate_recipes(wrap_recipe(recipe))

        assert has_error_containing(errors, "number_of_meals")

    def test_missing_nested_cooking_time_field_is_reported(self):
        recipe = valid_recipe()
        del recipe["cooking_time"]["initial_cook"]["active_minutes"]

        errors = validate_recipes(wrap_recipe(recipe))

        assert has_error_containing(
            errors, "cooking_time.initial_cook.active_minutes", "missing required field"
        )

    def test_non_positive_number_of_meals_is_reported(self):
        recipe = valid_recipe()
        recipe["number_of_meals"] = 0

        errors = validate_recipes(wrap_recipe(recipe))

        assert has_error_containing(errors, "number_of_meals", "positive")

    def test_ingredient_with_invalid_unit_is_reported(self):
        recipe = valid_recipe()
        recipe["ingredients"] = [{"name": "onion", "quantity": 1, "unit": "litre"}]

        errors = validate_recipes(wrap_recipe(recipe))

        assert has_error_containing(errors, "unit", "litre")

    def test_ingredient_with_non_positive_quantity_is_reported(self):
        recipe = valid_recipe()
        recipe["ingredients"] = [{"name": "onion", "quantity": -1, "unit": "whole"}]

        errors = validate_recipes(wrap_recipe(recipe))

        assert has_error_containing(errors, "quantity", "positive")

    def test_ingredient_missing_required_field_is_reported(self):
        recipe = valid_recipe()
        recipe["ingredients"] = [{"name": "onion", "unit": "whole"}]  # missing quantity

        errors = validate_recipes(wrap_recipe(recipe))

        assert has_error_containing(errors, "quantity", "missing required field")

    def test_malformed_recipe_entry_is_reported_not_crashed(self):
        # Simulates the real bug hit earlier: a mis-indented field leaving a
        # list where a recipe dict should be. Should be reported cleanly,
        # not raise an exception.
        recipe_dict = {"main_dishes": {"broken_recipe": ["not", "a", "dict"]}}

        errors = validate_recipes(recipe_dict)

        assert has_error_containing(errors, "broken_recipe", "expected a mapping")

    def test_side_dishes_referencing_existing_recipe_has_no_error(self):
        main = valid_recipe()
        main["side_dishes"] = ["side_recipe"]
        side = valid_recipe()

        recipe_dict = {
            "main_dishes": {"main_recipe": main},
            "sides": {"side_recipe": side},
        }

        errors = validate_recipes(recipe_dict)

        assert errors == []

    def test_side_dishes_referencing_missing_recipe_is_reported(self):
        main = valid_recipe()
        main["side_dishes"] = ["nonexistent_side"]

        errors = validate_recipes(wrap_recipe(main, recipe_id="main_recipe"))

        assert has_error_containing(errors, "side_dishes", "nonexistent_side")

    def test_side_dishes_with_wrong_type_is_reported(self):
        recipe = valid_recipe()
        recipe["side_dishes"] = "boiled_rice"  # should be a list

        errors = validate_recipes(wrap_recipe(recipe))

        assert has_error_containing(errors, "side_dishes")


# ---------------------------------------------------------------------------
# validate_ingredients
# ---------------------------------------------------------------------------


class TestValidateIngredients:
    def test_valid_ingredient_has_no_errors(self):
        errors = validate_ingredients(wrap_ingredient(valid_ingredient()))
        assert errors == []

    @pytest.mark.parametrize(
        "field",
        ["name", "canonical_unit", "purchase_options", "shelf_life_days", "nutrition"],
    )
    def test_missing_required_field_is_reported(self, field):
        ingredient = valid_ingredient()
        del ingredient[field]

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, field, "missing required field")

    def test_unknown_top_level_field_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["brand"] = "Tesco"  # not part of the schema

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "brand", "unrecognised")

    def test_invalid_canonical_unit_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["canonical_unit"] = "litre"

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "canonical_unit", "litre")

    def test_empty_purchase_options_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["purchase_options"] = []

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "purchase_options", "empty")

    def test_duplicate_purchase_option_quantity_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["purchase_options"] = [
            {"quantity": 1, "cost": 0.20},
            {"quantity": 1, "cost": 0.25},
        ]

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "purchase_options", "more than one")

    def test_purchase_option_missing_field_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["purchase_options"] = [{"quantity": 1}]  # missing cost

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "cost", "missing required field")

    def test_purchase_option_non_positive_cost_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["purchase_options"] = [{"quantity": 1, "cost": 0}]

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "cost", "positive")

    def test_shelf_life_disallowed_key_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["shelf_life_days"] = {"cupboard": 30}  # not fridge/freezer/pantry

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "cupboard", "unrecognised")

    def test_shelf_life_with_no_valid_keys_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["shelf_life_days"] = {}

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "shelf_life_days", "at least one")

    def test_nutrition_invalid_unit_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["nutrition"]["unit"] = "whole"  # must be g or ml, not canonical_unit's enum

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "nutrition.unit", "whole")

    def test_nutrition_missing_amount_per_canonical_unit_when_required(self):
        ingredient = valid_ingredient()  # canonical_unit "whole", nutrition unit "g"
        del ingredient["nutrition"]["amount_per_canonical_unit"]

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "amount_per_canonical_unit", "required")

    def test_nutrition_amount_per_canonical_unit_not_required_when_units_match(self):
        ingredient = valid_ingredient()
        ingredient["canonical_unit"] = "g"  # now matches nutrition.unit ("g")
        del ingredient["nutrition"]["amount_per_canonical_unit"]

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert errors == []

    def test_nutrition_unknown_field_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["nutrition"]["salt"] = 1.2  # not part of the schema

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "nutrition.salt", "unrecognised")

    def test_calorie_mismatch_beyond_tolerance_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["nutrition"]["calories"] = 500  # miles off from the actual macros

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "calories", "macros")

    def test_calorie_mismatch_within_tolerance_is_not_reported(self):
        # The valid_ingredient() fixture's macros (protein*4 + carbs*4 + fat*9)
        # come to ~42.5 against a stated 40 calories - within the 10% tolerance.
        errors = validate_ingredients(wrap_ingredient(valid_ingredient()))

        assert not has_error_containing(errors, "calories", "macros")

    def test_substitutes_with_self_reference_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["substitutes_with"] = ["test_ingredient"]  # same id as itself

        errors = validate_ingredients(wrap_ingredient(ingredient, ingredient_id="test_ingredient"))

        assert has_error_containing(errors, "substitutes_with", "itself")

    def test_substitutes_with_unknown_reference_is_reported(self):
        ingredient = valid_ingredient()
        ingredient["substitutes_with"] = ["nonexistent_ingredient"]

        errors = validate_ingredients(wrap_ingredient(ingredient))

        assert has_error_containing(errors, "substitutes_with", "nonexistent_ingredient")

    def test_substitutes_with_valid_reference_has_no_error(self):
        thigh = valid_ingredient()
        thigh["name"] = "chicken thigh fillets"
        thigh["canonical_unit"] = "g"
        del thigh["nutrition"]["amount_per_canonical_unit"]
        thigh["substitutes_with"] = ["chicken_breast_fillets"]

        breast = valid_ingredient()
        breast["name"] = "chicken breast fillets"
        breast["canonical_unit"] = "g"
        del breast["nutrition"]["amount_per_canonical_unit"]

        ingredient_dict = {
            "chicken_thigh_fillets": thigh,
            "chicken_breast_fillets": breast,
        }

        errors = validate_ingredients(ingredient_dict)

        assert not has_error_containing(errors, "substitutes_with")

    def test_duplicate_alias_across_ingredients_is_reported(self):
        first = valid_ingredient()
        first["aliases"] = ["spring onion"]

        second = valid_ingredient()
        second["name"] = "red onion"
        second["aliases"] = ["spring onion"]  # same alias as `first`

        ingredient_dict = {
            "onion": first,
            "red_onion": second,
        }

        errors = validate_ingredients(ingredient_dict)

        assert has_error_containing(errors, "spring onion", "onion", "red_onion")
