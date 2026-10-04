from recipe_planner import data_extraction
from recipe_planner.data_extraction.ingredients import (
    NutritionCandidate,
    UnexpectedNutrientNameError,
    append_ingredient_block,
    extract_nutrients,
    find_missing_ingredients,
    load_draft_ids,
    prompt_for_aliases,
    prompt_for_canonical_unit,
    prompt_for_float,
    prompt_for_nutrition_choice,
    prompt_for_purchase_options,
    prompt_for_shelf_life,
    prompt_for_substitutes,
    search_usda,
    slugify,
)


def mock_input(monkeypatch, responses):
    """Make builtins.input() return each value in `responses` in turn,
    one per call, regardless of the prompt text passed to it."""
    responses_iter = iter(responses)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses_iter))


def nutrient(nutrient_id, name, value):
    return {"nutrientId": nutrient_id, "nutrientName": name, "value": value}


def food_with_nutrients(nutrients, description="Test Food", fdc_id=1):
    return {"description": description, "fdcId": fdc_id, "foodNutrients": nutrients}


# ---------------------------------------------------------------------------
# NutritionCandidate
# ---------------------------------------------------------------------------


class TestNutritionCandidate:
    def test_is_complete_when_all_core_fields_present(self):
        candidate = NutritionCandidate(
            source="USDA",
            description="Garlic",
            identifier="169230",
            calories=149,
            protein=6.4,
            carbohydrates=33.1,
            fat=0.5,
        )
        assert candidate.is_complete() is True

    def test_is_not_complete_when_a_core_field_is_missing(self):
        candidate = NutritionCandidate(
            source="USDA",
            description="Tomato",
            identifier="1",
            calories=None,
            protein=1.0,
            carbohydrates=4.0,
            fat=0.2,
        )
        assert candidate.is_complete() is False

    def test_sugars_and_fibre_are_not_required_for_completeness(self):
        # Core fields are calories/protein/carbohydrates/fat only -
        # sugars/saturated_fat/fibre being None shouldn't count against it.
        candidate = NutritionCandidate(
            source="USDA",
            description="X",
            identifier="1",
            calories=1,
            protein=1,
            carbohydrates=1,
            fat=1,
            sugars=None,
            saturated_fat=None,
            fibre=None,
        )
        assert candidate.is_complete() is True


# ---------------------------------------------------------------------------
# extract_nutrients
# ---------------------------------------------------------------------------


class TestExtractNutrients:
    def test_extracts_all_macros_by_id(self):
        food = food_with_nutrients(
            [
                nutrient(1003, "Protein", 6.4),
                nutrient(1004, "Total lipid (fat)", 0.5),
                nutrient(1005, "Carbohydrate, by difference", 33.1),
                nutrient(1008, "Energy", 149),
                nutrient(1079, "Fiber, total dietary", 2.1),
                nutrient(1258, "Fatty acids, total saturated", 0.09),
                nutrient(2000, "Total Sugars", 1.0),
            ]
        )

        macros = extract_nutrients(food)

        assert macros == {
            "protein": 6.4,
            "fat": 0.5,
            "carbohydrates": 33.1,
            "calories": 149,
            "fibre": 2.1,
            "saturated_fat": 0.09,
            "sugars": 1.0,
        }

    def test_missing_nutrient_results_in_none_not_a_missing_key(self):
        food = food_with_nutrients([nutrient(1003, "Protein", 6.4)])

        macros = extract_nutrients(food)

        assert macros["protein"] == 6.4
        assert macros["calories"] is None
        assert "calories" in macros  # key present, just None - not absent entirely

    def test_missing_value_key_is_treated_as_none_not_crashed(self):
        food = food_with_nutrients(
            [{"nutrientId": 1008, "nutrientName": "Energy"}]
        )  # no "value" key

        macros = extract_nutrients(food)

        assert macros["calories"] is None

    def test_unrecognised_nutrient_id_is_ignored(self):
        food = food_with_nutrients(
            [
                nutrient(1003, "Protein", 6.4),
                nutrient(9999, "Some Other Nutrient", 42),
            ]
        )

        macros = extract_nutrients(food)

        assert macros["protein"] == 6.4
        assert "Some Other Nutrient" not in macros

    def test_raises_when_known_id_has_unexpected_name(self):
        # This is the exact kJ-vs-kcal class of problem the id-based
        # approach exists to catch: id 1008 showing up under any name
        # other than "Energy" means the mapping can no longer be trusted.
        food = food_with_nutrients([nutrient(1008, "Energy (kJ)", 623)])

        try:
            extract_nutrients(food)
            assert False, "expected UnexpectedNutrientNameError to be raised"
        except UnexpectedNutrientNameError as exc:
            assert "1008" in str(exc)
            assert "Energy (kJ)" in str(exc)

    def test_error_message_identifies_the_offending_food(self):
        food = food_with_nutrients(
            [nutrient(1003, "Not Protein", 1)], description="Mystery Food", fdc_id=42
        )

        try:
            extract_nutrients(food)
            assert False, "expected UnexpectedNutrientNameError to be raised"
        except UnexpectedNutrientNameError as exc:
            assert "Mystery Food" in str(exc)
            assert "42" in str(exc)

    def test_empty_food_nutrients_list_returns_all_none(self):
        food = food_with_nutrients([])

        macros = extract_nutrients(food)

        assert all(value is None for value in macros.values())


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_spaces_become_underscores(self):
        assert slugify("chicken stock cube") == "chicken_stock_cube"

    def test_mixed_case_is_lowered(self):
        assert slugify("Chicken Thigh Fillets") == "chicken_thigh_fillets"

    def test_punctuation_collapses_to_underscore(self):
        assert slugify("flour (plain / all purpose)") == "flour_plain_all_purpose"

    def test_leading_and_trailing_whitespace_is_stripped(self):
        assert slugify("  garlic  ") == "garlic"

    def test_no_leading_or_trailing_underscore(self):
        assert slugify("(optional) coriander") == "optional_coriander"

    def test_already_valid_slug_is_unchanged(self):
        assert slugify("onion") == "onion"


# ---------------------------------------------------------------------------
# load_draft_ids
# ---------------------------------------------------------------------------


class TestLoadDraftIds:
    def test_missing_file_returns_empty_set(self, tmp_path):
        path = tmp_path / "does_not_exist.yml"

        assert load_draft_ids(path) == set()

    def test_valid_file_returns_its_top_level_keys(self, tmp_path):
        path = tmp_path / "draft.yml"
        path.write_text("garlic:\n  name: garlic\nonion:\n  name: onion\n")

        assert load_draft_ids(path) == {"garlic", "onion"}

    def test_empty_file_returns_empty_set(self, tmp_path):
        path = tmp_path / "draft.yml"
        path.write_text("")

        assert load_draft_ids(path) == set()

    def test_invalid_yaml_returns_empty_set_not_crashed(self, tmp_path):
        # Simulates a draft file left mid-write by an interrupted run -
        # specifically a syntax-level break (unclosed bracket), not just
        # a semantically-wrong-but-parseable value.
        path = tmp_path / "draft.yml"
        path.write_text("garlic:\n  nutrition: [1, 2\n")  # unclosed [ - real syntax error

        assert load_draft_ids(path) == set()

    def test_non_mapping_top_level_returns_empty_set(self, tmp_path):
        path = tmp_path / "draft.yml"
        path.write_text("- just\n- a\n- list\n")

        assert load_draft_ids(path) == set()


# ---------------------------------------------------------------------------
# find_missing_ingredients
# ---------------------------------------------------------------------------


class TestFindMissingIngredients:
    def test_ingredient_already_in_database_is_excluded(self):
        recipe_dict = {"main_dishes": {"r1": {"ingredients": [{"name": "onion"}]}}}
        ingredient_dict = {"onion": {"name": "onion"}}

        result = find_missing_ingredients(recipe_dict, ingredient_dict)

        assert result == []

    def test_ingredient_matched_via_alias_is_excluded(self):
        recipe_dict = {"main_dishes": {"r1": {"ingredients": [{"name": "chicken thighs"}]}}}
        ingredient_dict = {
            "chicken_thigh_fillets": {
                "name": "chicken thigh fillets",
                "aliases": ["chicken thighs"],
            }
        }

        result = find_missing_ingredients(recipe_dict, ingredient_dict)

        assert result == []

    def test_missing_ingredient_is_returned_with_its_count(self):
        recipe_dict = {
            "main_dishes": {
                "r1": {"ingredients": [{"name": "garlic"}]},
                "r2": {"ingredients": [{"name": "garlic"}, {"name": "onion"}]},
            }
        }

        result = find_missing_ingredients(recipe_dict, {})

        assert dict(result) == {"garlic": 2, "onion": 1}

    def test_result_is_sorted_by_count_descending(self):
        recipe_dict = {
            "main_dishes": {
                "r1": {"ingredients": [{"name": "garlic"}, {"name": "onion"}]},
                "r2": {"ingredients": [{"name": "garlic"}]},
            }
        }

        result = find_missing_ingredients(recipe_dict, {})

        assert [name for name, _ in result] == ["garlic", "onion"]

    def test_non_dict_recipe_is_skipped_not_crashed(self):
        recipe_dict = {"main_dishes": {"broken": ["not", "a", "dict"]}}

        result = find_missing_ingredients(recipe_dict, {})

        assert result == []

    def test_non_dict_ingredient_entry_is_skipped_not_crashed(self):
        recipe_dict = {"main_dishes": {"r1": {"ingredients": ["not a dict"]}}}

        result = find_missing_ingredients(recipe_dict, {})

        assert result == []

    def test_no_ingredients_key_is_handled(self):
        recipe_dict = {"main_dishes": {"r1": {}}}

        result = find_missing_ingredients(recipe_dict, {})

        assert result == []


# ---------------------------------------------------------------------------
# append_ingredient_block
# ---------------------------------------------------------------------------


class TestAppendIngredientBlock:
    def test_writes_header_only_on_first_call(self, tmp_path):
        path = tmp_path / "draft.yml"

        append_ingredient_block(
            path,
            "onion",
            "onion",
            None,
            [],
            "whole",
            [{"quantity": 1, "cost": 0.2}],
            {"pantry": 30},
            [],
        )
        first_content = path.read_text()
        assert first_content.startswith("# Draft ingredient entries")

        append_ingredient_block(
            path,
            "garlic",
            "garlic",
            None,
            [],
            "whole",
            [{"quantity": 1, "cost": 0.3}],
            {"pantry": 60},
            [],
        )
        second_content = path.read_text()

        assert second_content.count("# Draft ingredient entries") == 1
        assert "onion:" in second_content
        assert "garlic:" in second_content

    def test_empty_aliases_are_omitted(self, tmp_path):
        path = tmp_path / "draft.yml"
        append_ingredient_block(
            path,
            "onion",
            "onion",
            None,
            [],
            "whole",
            [{"quantity": 1, "cost": 0.2}],
            {"pantry": 30},
            [],
        )

        assert "aliases:" not in path.read_text()

    def test_non_empty_aliases_are_written(self, tmp_path):
        path = tmp_path / "draft.yml"
        append_ingredient_block(
            path,
            "onion",
            "onion",
            None,
            ["spring onion"],
            "whole",
            [{"quantity": 1, "cost": 0.2}],
            {"pantry": 30},
            [],
        )

        content = path.read_text()
        assert "aliases:" in content
        assert "- spring onion" in content

    def test_amount_per_canonical_unit_placeholder_added_for_whole_unit(self, tmp_path):
        path = tmp_path / "draft.yml"
        append_ingredient_block(
            path,
            "onion",
            "onion",
            None,
            [],
            "whole",
            [{"quantity": 1, "cost": 0.2}],
            {"pantry": 30},
            [],
        )

        assert "amount_per_canonical_unit:" in path.read_text()

    def test_amount_per_canonical_unit_placeholder_omitted_for_g_unit(self, tmp_path):
        path = tmp_path / "draft.yml"
        append_ingredient_block(
            path,
            "flour",
            "flour",
            None,
            [],
            "g",
            [{"quantity": 1000, "cost": 1.0}],
            {"pantry": 365},
            [],
        )

        assert "amount_per_canonical_unit:" not in path.read_text()

    def test_candidate_none_writes_blank_nutrition_fields(self, tmp_path):
        path = tmp_path / "draft.yml"
        append_ingredient_block(
            path,
            "mystery",
            "mystery",
            None,
            [],
            "g",
            [{"quantity": 100, "cost": 1.0}],
            {"pantry": 30},
            [],
        )

        content = path.read_text()
        assert "needs manual lookup" in content
        assert "calories:\n" in content

    def test_candidate_fields_are_written_when_present(self, tmp_path):
        path = tmp_path / "draft.yml"
        candidate = NutritionCandidate(
            source="USDA FoodData Central",
            description="Garlic, raw",
            identifier="169230",
            calories=149,
            protein=6.4,
            carbohydrates=33.1,
            sugars=1.0,
            fat=0.5,
            saturated_fat=0.09,
            fibre=2.1,
        )
        append_ingredient_block(
            path,
            "garlic",
            "garlic",
            candidate,
            [],
            "whole",
            [{"quantity": 1, "cost": 0.2}],
            {"pantry": 30},
            [],
        )

        content = path.read_text()
        assert "calories: 149" in content
        assert "Garlic, raw (id=169230)" in content

    def test_only_provided_shelf_life_keys_are_written(self, tmp_path):
        path = tmp_path / "draft.yml"
        append_ingredient_block(
            path,
            "onion",
            "onion",
            None,
            [],
            "whole",
            [{"quantity": 1, "cost": 0.2}],
            {"pantry": 30},
            [],
        )

        content = path.read_text()
        assert "pantry: 30" in content
        assert "fridge:" not in content
        assert "freezer:" not in content

    def test_non_empty_substitutes_are_written(self, tmp_path):
        path = tmp_path / "draft.yml"
        append_ingredient_block(
            path,
            "chicken_thigh_fillets",
            "chicken thigh fillets",
            None,
            [],
            "g",
            [{"quantity": 1000, "cost": 7.0}],
            {"fridge": 3},
            ["chicken_breast_fillets"],
        )

        content = path.read_text()
        assert "substitutes_with:" in content
        assert "- chicken_breast_fillets" in content


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------


class TestPromptForAliases:
    def test_blank_immediately_returns_empty_list(self, monkeypatch):
        mock_input(monkeypatch, [""])
        assert prompt_for_aliases() == []

    def test_collects_entries_until_blank(self, monkeypatch):
        mock_input(monkeypatch, ["spring onion", "brown onion", ""])
        assert prompt_for_aliases() == ["spring onion", "brown onion"]


class TestPromptForCanonicalUnit:
    def test_valid_unit_is_accepted(self, monkeypatch):
        mock_input(monkeypatch, ["g"])
        assert prompt_for_canonical_unit() == "g"

    def test_uppercase_input_is_normalised(self, monkeypatch):
        mock_input(monkeypatch, ["G"])
        assert prompt_for_canonical_unit() == "g"

    def test_invalid_unit_reprompts(self, monkeypatch):
        mock_input(monkeypatch, ["litre", "ml"])
        assert prompt_for_canonical_unit() == "ml"


class TestPromptForFloat:
    def test_valid_number_is_parsed(self, monkeypatch):
        mock_input(monkeypatch, ["4.5"])
        assert prompt_for_float("quantity: ") == 4.5

    def test_invalid_input_reprompts(self, monkeypatch):
        mock_input(monkeypatch, ["abc", "2"])
        assert prompt_for_float("quantity: ") == 2.0


class TestPromptForPurchaseOptions:
    def test_single_option(self, monkeypatch):
        mock_input(monkeypatch, ["600", "4.50", "n"])
        assert prompt_for_purchase_options() == [{"quantity": 600.0, "cost": 4.50}]

    def test_multiple_options(self, monkeypatch):
        mock_input(monkeypatch, ["600", "4.50", "y", "1000", "7.00", "n"])
        assert prompt_for_purchase_options() == [
            {"quantity": 600.0, "cost": 4.50},
            {"quantity": 1000.0, "cost": 7.00},
        ]


class TestPromptForShelfLife:
    def test_single_value_is_accepted(self, monkeypatch):
        mock_input(monkeypatch, ["", "", "30"])  # fridge skip, freezer skip, pantry 30
        assert prompt_for_shelf_life() == {"pantry": 30}

    def test_all_three_values(self, monkeypatch):
        mock_input(monkeypatch, ["3", "270", "30"])
        assert prompt_for_shelf_life() == {"fridge": 3, "freezer": 270, "pantry": 30}

    def test_all_skipped_reloops_until_one_is_given(self, monkeypatch):
        # First pass: all three skipped - should re-loop rather than return {}
        mock_input(monkeypatch, ["", "", "", "", "", "30"])
        assert prompt_for_shelf_life() == {"pantry": 30}

    def test_invalid_number_is_treated_as_skipped(self, monkeypatch):
        mock_input(monkeypatch, ["abc", "", "30"])
        assert prompt_for_shelf_life() == {"pantry": 30}


class TestPromptForSubstitutes:
    def test_blank_immediately_returns_empty_list(self, monkeypatch):
        mock_input(monkeypatch, [""])
        assert prompt_for_substitutes() == []

    def test_collects_entries_until_blank(self, monkeypatch):
        mock_input(monkeypatch, ["chicken_breast_fillets", ""])
        assert prompt_for_substitutes() == ["chicken_breast_fillets"]


class TestPromptForNutritionChoice:
    def test_valid_choice_returns_zero_based_index(self, monkeypatch):
        mock_input(monkeypatch, ["2"])
        assert prompt_for_nutrition_choice(num_candidates=3) == 1

    def test_skip_returns_none(self, monkeypatch):
        mock_input(monkeypatch, ["s"])
        assert prompt_for_nutrition_choice(num_candidates=3) is None

    def test_out_of_range_reprompts(self, monkeypatch):
        mock_input(monkeypatch, ["5", "1"])
        assert prompt_for_nutrition_choice(num_candidates=3) == 0


# ---------------------------------------------------------------------------
# search_usda
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, json_data):
        self._json_data = json_data

    def raise_for_status(self):
        pass

    def json(self):
        return self._json_data


class TestSearchUsda:
    def test_returns_empty_list_when_no_api_key_set(self, monkeypatch):
        monkeypatch.setattr(data_extraction.ingredients, "USDA_API_KEY", None)
        assert search_usda("garlic raw") == []

    def test_parses_a_successful_response_into_candidates(self, monkeypatch):
        monkeypatch.setattr(data_extraction.ingredients, "USDA_API_KEY", "fake-key")

        fake_food = food_with_nutrients(
            [
                nutrient(1003, "Protein", 6.4),
                nutrient(1004, "Total lipid (fat)", 0.5),
                nutrient(1005, "Carbohydrate, by difference", 33.1),
                nutrient(1008, "Energy", 149),
            ],
            description="Garlic, raw",
            fdc_id=169230,
        )
        monkeypatch.setattr(
            data_extraction.ingredients.requests,
            "get",
            lambda *a, **kw: FakeResponse({"foods": [fake_food]}),
        )

        candidates = search_usda("garlic raw")

        assert len(candidates) == 1
        assert candidates[0].description == "Garlic, raw"
        assert candidates[0].identifier == "169230"
        assert candidates[0].calories == 149
        assert candidates[0].protein == 6.4

    def test_mismatched_nutrient_name_propagates_as_error(self, monkeypatch):
        monkeypatch.setattr(data_extraction.ingredients, "USDA_API_KEY", "fake-key")

        bad_food = food_with_nutrients([nutrient(1008, "Energy (kJ)", 623)])
        monkeypatch.setattr(
            data_extraction.ingredients.requests,
            "get",
            lambda *a, **kw: FakeResponse({"foods": [bad_food]}),
        )

        try:
            search_usda("garlic raw")
            assert False, "expected UnexpectedNutrientNameError to be raised"
        except UnexpectedNutrientNameError:
            pass
