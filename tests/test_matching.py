from recipe_planner.matching import find_ingredient_match, flatten_recipes


class TestFlattenRecipes:
    def test_flattens_multiple_categories_into_one_mapping(self):
        recipe_dict = {
            "main_dishes": {"curry": {"name": "Curry"}},
            "sides": {"rice": {"name": "Rice"}},
        }

        result = flatten_recipes(recipe_dict)

        assert result == {
            "curry": {"name": "Curry"},
            "rice": {"name": "Rice"},
        }

    def test_empty_input_returns_empty_mapping(self):
        assert flatten_recipes({}) == {}

    def test_category_with_no_recipes_is_handled(self):
        recipe_dict = {"main_dishes": {}, "sides": {"rice": {"name": "Rice"}}}

        result = flatten_recipes(recipe_dict)

        assert result == {"rice": {"name": "Rice"}}

    def test_category_whose_value_is_not_a_mapping_is_skipped_not_crashed(self):
        # Reproduces the shape of the real thai_red_curry bug: a
        # mis-indented field leaves a list sitting where a category's
        # recipe mapping should be.
        recipe_dict = {
            "main_dishes": {"curry": {"name": "Curry"}},
            "side_dishes": ["boiled_rice"],
        }

        result = flatten_recipes(recipe_dict)

        assert result == {"curry": {"name": "Curry"}}

    def test_same_recipe_id_in_two_categories_keeps_the_later_one(self):
        # Documents current behaviour rather than asserting it's
        # necessarily desirable - flatten_recipes itself does no duplicate
        # detection, that's handled elsewhere (the raw-text scan in the
        # validator). This test exists so a future change to that
        # behaviour is a deliberate choice, not an accident.
        recipe_dict = {
            "main_dishes": {"shared_id": {"name": "First"}},
            "sides": {"shared_id": {"name": "Second"}},
        }

        result = flatten_recipes(recipe_dict)

        assert result == {"shared_id": {"name": "Second"}}


class TestFindIngredientMatch:
    def ingredient_dict(self):
        return {
            "onion": {
                "name": "onion",
                "aliases": ["spring onion", "brown onion"],
            },
            "chicken_thigh_fillets": {
                "name": "chicken thigh fillets",
                "aliases": ["chicken thighs"],
            },
        }

    def test_exact_key_match(self):
        result = find_ingredient_match("onion", self.ingredient_dict())
        assert result == ("exact", "onion")

    def test_name_field_match(self):
        result = find_ingredient_match("chicken thigh fillets", self.ingredient_dict())
        assert result == ("name_field", "chicken_thigh_fillets")

    def test_alias_match(self):
        result = find_ingredient_match("chicken thighs", self.ingredient_dict())
        assert result == ("alias", "chicken_thigh_fillets")

    def test_not_found(self):
        result = find_ingredient_match("garlic", self.ingredient_dict())
        assert result == ("not_found", None)

    def test_case_insensitive_key_match(self):
        result = find_ingredient_match("Onion", self.ingredient_dict())
        assert result == ("case_insensitive", "onion")

    def test_case_insensitive_name_field_match(self):
        result = find_ingredient_match("Chicken Thigh Fillets", self.ingredient_dict())
        assert result == ("case_insensitive", "chicken_thigh_fillets")

    def test_case_insensitive_alias_match(self):
        result = find_ingredient_match("Spring Onion", self.ingredient_dict())
        assert result == ("case_insensitive", "onion")

    def test_exact_match_takes_priority_over_case_insensitive(self):
        # "onion" is both an exact key match and would also match
        # case-insensitively - exact must win, since it's a better result.
        result = find_ingredient_match("onion", self.ingredient_dict())
        assert result[0] == "exact"

    def test_non_dict_ingredient_entry_is_skipped_not_crashed(self):
        ingredient_dict = {
            "broken_entry": ["not", "a", "mapping"],
            "onion": {"name": "onion", "aliases": []},
        }

        result = find_ingredient_match("onion", ingredient_dict)

        assert result == ("exact", "onion")

    def test_non_dict_ingredient_entry_does_not_break_not_found_case(self):
        ingredient_dict = {"broken_entry": ["not", "a", "mapping"]}

        result = find_ingredient_match("garlic", ingredient_dict)

        assert result == ("not_found", None)

    def test_non_string_alias_is_ignored_not_crashed(self):
        ingredient_dict = {
            "onion": {"name": "onion", "aliases": [None, 123, "spring onion"]},
        }

        result = find_ingredient_match("spring onion", ingredient_dict)

        assert result == ("alias", "onion")

    def test_missing_aliases_key_is_treated_as_no_aliases(self):
        ingredient_dict = {"onion": {"name": "onion"}}  # no "aliases" key at all

        result = find_ingredient_match("spring onion", ingredient_dict)

        assert result == ("not_found", None)

    def test_empty_ingredient_dict_returns_not_found(self):
        result = find_ingredient_match("anything", {})
        assert result == ("not_found", None)
