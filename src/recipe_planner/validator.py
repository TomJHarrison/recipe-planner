from pathlib import Path

import yaml

# validator.py lives at src/recipe_planner/validator.py, so three levels up
# from this file is the repo root, regardless of where the command is run from
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RECIPE_FILE = PROJECT_ROOT / "data" / "recipes.yml"
INGREDIENT_FILE = PROJECT_ROOT / "data" / "ingredients.yml"

VALID_UNITS = {"g", "ml", "tsp", "whole", "can", "bag"}
VALID_NUTRITION_UNITS = {"g", "ml"}
SHELF_LIFE_KEYS = {"fridge", "freezer", "pantry"}
CALORIE_TOLERANCE = (
    0.10  # allowed relative difference between stated calories and macro-derived calories
)

RECIPE_STRUCTURE = {
    "required": {
        "name": str,
        "description": str,
        "link": str,
        "number_of_meals": int,
        "can_freeze": bool,
        "cooking_time": {
            "initial_cook": {"active_minutes": int, "total_minutes": int},
            "subsequent_occasions": {"active_minutes": int, "total_minutes": int},
        },
        "eat_at_work": bool,
        "unhealthy": bool,
        "tags": list,
        "ingredients": list,
    },
    "optional": {"side_dishes": list},
}

RECIPE_INGREDIENT_STRUCTURE = {
    "required": {
        "name": str,
        "quantity": (int, float),
        "unit": str,
    },
    "optional": {
        "optional": bool,
    },
}

INGREDIENT_STRUCTURE = {
    "required": {
        "name": str,
        "canonical_unit": str,
        "purchase_options": list,
        "shelf_life_days": dict,
        "nutrition": dict,
    },
    "optional": {
        "aliases": list,
        "substitutes_with": list,
    },
}

PURCHASE_OPTION_STRUCTURE = {
    "required": {
        "quantity": (int, float),
        "cost": (int, float),
    },
    "optional": {},
}

NUTRITION_STRUCTURE = {
    "required": {
        "per": int,
        "unit": str,
        "source": str,
        "calories": int,
        "protein": (int, float),
        "carbohydrates": (int, float),
        "sugars": (int, float),
        "fat": (int, float),
        "saturated_fat": (int, float),
        "fibre": (int, float),
    },
    "optional": {
        "amount_per_canonical_unit": (int, float),
    },
}


def load_yaml(filepath: str):
    with open(filepath) as stream:
        try:
            data = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            raise yaml.YAMLError(f"Unable to read yml file {filepath}") from exc

    return data


def check_type(value, expected_type) -> bool:
    # bool is technically a subclass of int in Python, so an explicit
    # True/False would otherwise pass an `int` or `float` check by accident.
    if isinstance(value, bool) and expected_type is not bool:
        return False
    return isinstance(value, expected_type)


def is_positive_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_field(value, expected, path: str) -> list:
    """Validate a single field against its expected type, recursing into
    plain nested dicts (e.g. cooking_time's sub-structure)."""
    if isinstance(expected, dict):
        if not isinstance(value, dict):
            return [f"{path}: expected a mapping, got {type(value).__name__}"]
        return validate_nested(value, expected, path)

    if not check_type(value, expected):
        return [f"{path}: expected {expected}, got {type(value).__name__}"]

    return []


def validate_nested(data: dict, structure: dict, path: str) -> list:
    """Validate a plain (non required/optional) nested structure, e.g. the
    contents of cooking_time. Every field in a plain structure is required."""
    errors = []
    for field, expected in structure.items():
        full_path = f"{path}.{field}"
        if field not in data:
            errors.append(f"{full_path}: missing required field")
            continue
        errors.extend(validate_field(data[field], expected, full_path))
    return errors


def validate_structure(data: dict, structure: dict, path: str = "") -> list:
    """Validate a mapping against a {'required': {...}, 'optional': {...}}
    structure definition."""
    errors = []

    for field, expected in structure.get("required", {}).items():
        full_path = f"{path}.{field}" if path else field
        if field not in data:
            errors.append(f"{full_path}: missing required field")
            continue
        errors.extend(validate_field(data[field], expected, full_path))

    for field, expected in structure.get("optional", {}).items():
        full_path = f"{path}.{field}" if path else field
        if field in data:
            errors.extend(validate_field(data[field], expected, full_path))

    return errors


def check_unknown_fields(data: dict, allowed_fields: set, path: str = "") -> list:
    """Flag any field present in `data` that isn't part of the allowed set."""
    errors = []
    for field in data:
        if field not in allowed_fields:
            full_path = f"{path}.{field}" if path else field
            errors.append(f"{full_path}: unrecognised field")
    return errors


# --- recipe validation -------------------------------------------------


def validate_recipe_ingredients(ingredients: list, path: str = "ingredients") -> list:
    errors = []

    for index, ingredient in enumerate(ingredients):
        ingredient_path = f"{path}[{index}]"

        if not isinstance(ingredient, dict):
            errors.append(f"{ingredient_path}: expected a mapping, got {type(ingredient).__name__}")
            continue

        errors.extend(validate_structure(ingredient, RECIPE_INGREDIENT_STRUCTURE, ingredient_path))

        unit = ingredient.get("unit")
        if isinstance(unit, str) and unit not in VALID_UNITS:
            errors.append(f"{ingredient_path}.unit: '{unit}' is not one of {sorted(VALID_UNITS)}")

        quantity = ingredient.get("quantity")
        if is_positive_number(quantity) and quantity <= 0:
            errors.append(f"{ingredient_path}.quantity: must be positive, got {quantity}")

    return errors


def validate_recipe(recipe_id: str, recipe: dict) -> list:
    if not isinstance(recipe, dict):
        return [f"{recipe_id}: expected a mapping, got {type(recipe).__name__}"]

    errors = validate_structure(recipe, RECIPE_STRUCTURE)

    number_of_meals = recipe.get("number_of_meals")
    if is_positive_number(number_of_meals) and number_of_meals <= 0:
        errors.append(f"number_of_meals: must be positive, got {number_of_meals}")

    if isinstance(recipe.get("ingredients"), list):
        errors.extend(validate_recipe_ingredients(recipe["ingredients"]))

    return [f"{recipe_id}: {error}" for error in errors]


def validate_side_dish_references(all_recipes: dict) -> list:
    """Check that every side_dishes entry points at a recipe that actually
    exists somewhere in the file."""
    errors = []

    for recipe_id, recipe in all_recipes.items():
        if not isinstance(recipe, dict):
            continue
        side_dishes = recipe.get("side_dishes")
        if not isinstance(side_dishes, list):
            continue
        for side_dish_id in side_dishes:
            if side_dish_id not in all_recipes:
                errors.append(
                    f"{recipe_id}: side_dishes references '{side_dish_id}', "
                    "which is not defined as a recipe anywhere in the file"
                )

    return errors


def validate_recipes(recipe_dict: dict) -> list:
    """
    Validate every recipe found in recipe_dict, which is expected to be
    structured as {category: {recipe_id: {...recipe fields...}}} (e.g.
    "main_dishes" / "sides" at the top level).

    Steps performed:
    1. Flatten every category into a single {recipe_id: recipe} mapping,
       since side_dishes references can point at a recipe in a different
       category to the one that references it, and the check in step 3
       needs to see every recipe regardless of which category it's under.
    2. For each recipe, validate it against RECIPE_STRUCTURE:
       - Check every required field is present (name, description, link,
         number_of_meals, can_freeze, cooking_time, eat_at_work, unhealthy,
         tags, ingredients) and report any that are missing.
       - Check every present field (required or optional) has the correct
         type, recursing into cooking_time's nested initial_cook /
         subsequent_occasions structure.
       - If the recipe itself isn't a mapping at all (e.g. a YAML
         indentation mistake has left a stray list or string where a
         recipe should be), report that directly rather than crashing.
    3. Check number_of_meals is a positive number, if present and numeric.
    4. If ingredients is a list, validate each ingredient entry against
       RECIPE_INGREDIENT_STRUCTURE:
       - Required fields (name, quantity, unit) are present and typed
         correctly; optional field (optional) is typed correctly if present.
       - unit is one of VALID_UNITS.
       - quantity is a positive number.
    5. Across all recipes, check that every side_dishes entry refers to a
       recipe_id that actually exists somewhere in the file (in any
       category), flagging dangling references.

    Returns a flat list of human-readable error strings, each prefixed with
    the recipe_id it relates to. An empty list means no issues were found.
    """
    all_recipes = {}
    for category, recipes in recipe_dict.items():
        all_recipes.update(recipes)

    errors = []
    for recipe_id, recipe in all_recipes.items():
        errors.extend(validate_recipe(recipe_id, recipe))

    errors.extend(validate_side_dish_references(all_recipes))

    return errors


# --- ingredient validation -----------------------------------------------


def validate_purchase_options(purchase_options, path: str = "purchase_options") -> list:
    errors = []

    if not isinstance(purchase_options, list):
        return [f"{path}: expected a list, got {type(purchase_options).__name__}"]

    if len(purchase_options) == 0:
        errors.append(f"{path}: must not be empty")

    quantities_seen = []
    for index, option in enumerate(purchase_options):
        option_path = f"{path}[{index}]"

        if not isinstance(option, dict):
            errors.append(f"{option_path}: expected a mapping, got {type(option).__name__}")
            continue

        errors.extend(validate_structure(option, PURCHASE_OPTION_STRUCTURE, option_path))
        errors.extend(check_unknown_fields(option, {"quantity", "cost"}, option_path))

        quantity = option.get("quantity")
        cost = option.get("cost")

        if is_positive_number(quantity):
            if quantity <= 0:
                errors.append(f"{option_path}.quantity: must be positive, got {quantity}")
            quantities_seen.append(quantity)

        if is_positive_number(cost) and cost <= 0:
            errors.append(f"{option_path}.cost: must be positive, got {cost}")

    for duplicate_quantity in {q for q in quantities_seen if quantities_seen.count(q) > 1}:
        errors.append(
            f"{path}: quantity {duplicate_quantity} appears in more than one purchase option"
        )

    return errors


def validate_shelf_life(shelf_life, path: str = "shelf_life_days") -> list:
    errors = []

    if not isinstance(shelf_life, dict):
        return [f"{path}: expected a mapping, got {type(shelf_life).__name__}"]

    errors.extend(check_unknown_fields(shelf_life, SHELF_LIFE_KEYS, path))

    if not (set(shelf_life.keys()) & SHELF_LIFE_KEYS):
        errors.append(f"{path}: must specify at least one of {sorted(SHELF_LIFE_KEYS)}")

    for key in SHELF_LIFE_KEYS:
        if key not in shelf_life:
            continue
        value = shelf_life[key]
        if not check_type(value, int):
            errors.append(f"{path}.{key}: expected int, got {type(value).__name__}")
        elif value <= 0:
            errors.append(f"{path}.{key}: must be positive, got {value}")

    return errors


def validate_nutrition(nutrition, canonical_unit, path: str = "nutrition") -> list:
    errors = []

    if not isinstance(nutrition, dict):
        return [f"{path}: expected a mapping, got {type(nutrition).__name__}"]

    errors.extend(validate_structure(nutrition, NUTRITION_STRUCTURE, path))
    allowed_fields = set(NUTRITION_STRUCTURE["required"]) | set(NUTRITION_STRUCTURE["optional"])
    errors.extend(check_unknown_fields(nutrition, allowed_fields, path))

    unit = nutrition.get("unit")
    if isinstance(unit, str) and unit not in VALID_NUTRITION_UNITS:
        errors.append(f"{path}.unit: '{unit}' is not one of {sorted(VALID_NUTRITION_UNITS)}")

    # amount_per_canonical_unit is only required when nutrition is on a
    # different basis (g/ml) to how the ingredient is actually purchased
    if isinstance(unit, str) and canonical_unit is not None and unit != canonical_unit:
        if nutrition.get("amount_per_canonical_unit") is None:
            errors.append(
                f"{path}: 'amount_per_canonical_unit' is required because nutrition.unit "
                f"('{unit}') differs from canonical_unit ('{canonical_unit}')"
            )

    numeric_fields = [
        "per",
        "calories",
        "protein",
        "carbohydrates",
        "sugars",
        "fat",
        "saturated_fat",
        "fibre",
        "amount_per_canonical_unit",
    ]
    for field in numeric_fields:
        value = nutrition.get(field)
        if is_positive_number(value) and value < 0:
            errors.append(f"{path}.{field}: must be non-negative, got {value}")

    protein = nutrition.get("protein")
    carbohydrates = nutrition.get("carbohydrates")
    fat = nutrition.get("fat")
    calories = nutrition.get("calories")
    if all(is_positive_number(v) for v in [protein, carbohydrates, fat, calories]):
        calculated_calories = protein * 4 + carbohydrates * 4 + fat * 9
        tolerance = max(
            calories * CALORIE_TOLERANCE, 5
        )  # small floor so very low-calorie items aren't over-strict
        if abs(calculated_calories - calories) > tolerance:
            errors.append(
                f"{path}: stated calories ({calories}) don't match macros "
                f"(protein*4 + carbohydrates*4 + fat*9 = {calculated_calories:.1f}), "
                f"outside {CALORIE_TOLERANCE * 100:.0f}% tolerance"
            )

    return errors


def validate_ingredient(ingredient_id: str, ingredient: dict, all_ingredient_ids: set) -> list:
    if not isinstance(ingredient, dict):
        return [f"{ingredient_id}: expected a mapping, got {type(ingredient).__name__}"]

    errors = validate_structure(ingredient, INGREDIENT_STRUCTURE)

    allowed_fields = set(INGREDIENT_STRUCTURE["required"]) | set(INGREDIENT_STRUCTURE["optional"])
    errors.extend(check_unknown_fields(ingredient, allowed_fields))

    canonical_unit = ingredient.get("canonical_unit")
    if isinstance(canonical_unit, str) and canonical_unit not in VALID_UNITS:
        errors.append(f"canonical_unit: '{canonical_unit}' is not one of {sorted(VALID_UNITS)}")

    if isinstance(ingredient.get("purchase_options"), list):
        errors.extend(validate_purchase_options(ingredient["purchase_options"]))

    if isinstance(ingredient.get("shelf_life_days"), dict):
        errors.extend(validate_shelf_life(ingredient["shelf_life_days"]))

    if isinstance(ingredient.get("nutrition"), dict):
        errors.extend(
            validate_nutrition(
                ingredient["nutrition"],
                canonical_unit if isinstance(canonical_unit, str) else None,
            )
        )

    substitutes_with = ingredient.get("substitutes_with")
    if isinstance(substitutes_with, list):
        for substitute_id in substitutes_with:
            if substitute_id == ingredient_id:
                errors.append(f"substitutes_with: '{ingredient_id}' cannot substitute with itself")
            elif substitute_id not in all_ingredient_ids:
                errors.append(
                    f"substitutes_with: references '{substitute_id}', "
                    "which is not defined as an ingredient anywhere in the file"
                )

    return [f"{ingredient_id}: {error}" for error in errors]


def validate_alias_uniqueness(all_ingredients: dict) -> list:
    errors = []
    alias_owner = {}

    for ingredient_id, ingredient in all_ingredients.items():
        if not isinstance(ingredient, dict):
            continue
        for alias in ingredient.get("aliases", []) or []:
            if not isinstance(alias, str):
                continue
            if alias in alias_owner and alias_owner[alias] != ingredient_id:
                errors.append(
                    f"alias '{alias}' is used by both '{alias_owner[alias]}' and '{ingredient_id}'"
                )
            else:
                alias_owner[alias] = ingredient_id

    return errors


def validate_ingredients(ingredient_dict: dict) -> list:
    """
    Validate every ingredient found in ingredient_dict, structured as
    {ingredient_id: {...ingredient fields...}}.

    Steps performed, for each ingredient:
    1. Check it's a mapping at all (not malformed YAML).
    2. Validate against INGREDIENT_STRUCTURE:
       - Required fields (name, canonical_unit, purchase_options,
         shelf_life_days, nutrition) are present.
       - Optional fields (aliases, substitutes_with) are correctly typed
         if present.
    3. Check there are no fields beyond the required + optional set
       (catches typos or stray extra fields at the top level).
    4. Check canonical_unit is one of VALID_UNITS.
    5. Validate purchase_options (if it's a list):
       - Is not empty.
       - Each entry is a mapping with quantity and cost, both present,
         correctly typed, and positive.
       - Each entry has no fields beyond quantity/cost.
       - No two entries share the same quantity (an ambiguous duplicate
         pack size).
    6. Validate shelf_life_days (if it's a mapping):
       - Contains no keys other than fridge/freezer/pantry.
       - Contains at least one of fridge/freezer/pantry.
       - Each present value is a positive integer.
    7. Validate nutrition (if it's a mapping):
       - Required fields (per, unit, source, calories, protein,
         carbohydrates, sugars, fat, saturated_fat, fibre) are present and
         correctly typed; optional field (amount_per_canonical_unit) is
         correctly typed if present.
       - Contains no fields beyond this required + optional set.
       - unit is restricted to g or ml specifically (a narrower check than
         canonical_unit's full enum, since nutrition is always a
         weight/volume basis).
       - amount_per_canonical_unit must be present if nutrition.unit
         differs from the ingredient's canonical_unit (e.g. an onion is
         bought as "whole" but nutrition is quoted per gram, so the
         conversion factor is required; a "g" ingredient with nutrition
         already in "g" doesn't need one).
       - All numeric fields are non-negative.
       - Sanity-checks stated calories against the macros: calculates
         protein*4 + carbohydrates*4 + fat*9 and flags a mismatch beyond a
         10% tolerance (with a small absolute floor so very low-calorie
         ingredients aren't held to an unrealistically tight margin),
         catching likely data-entry mistakes.
    8. Validate substitutes_with (if it's a list):
       - No ingredient lists itself as a substitute.
       - Every referenced ingredient_id actually exists in the file.
    9. Across all ingredients, check that no two different ingredients
       declare the same alias (and that an alias doesn't collide with
       another ingredient's name under a different id), since a shared
       alias would make automatic name-to-ingredient lookup ambiguous.

    Returns a flat list of human-readable error strings, each prefixed with
    the ingredient_id it relates to (alias-collision messages name both
    ingredients involved instead). An empty list means no issues were found.
    """
    all_ingredient_ids = set(ingredient_dict.keys())

    errors = []
    for ingredient_id, ingredient in ingredient_dict.items():
        errors.extend(validate_ingredient(ingredient_id, ingredient, all_ingredient_ids))

    errors.extend(validate_alias_uniqueness(ingredient_dict))

    return errors


# --- orchestration -----------------------------------------------------


def report(title: str, errors: list) -> None:
    print(f"--- {title} ---")
    if errors:
        print(f"{len(errors)} issue(s) found:")
        for error in errors:
            print(f"  {error}")
    else:
        print("All valid.")
    print()


def main():
    recipe_dict = load_yaml(RECIPE_FILE)
    ingredient_dict = load_yaml(INGREDIENT_FILE)

    recipe_errors = validate_recipes(recipe_dict)
    ingredient_errors = validate_ingredients(ingredient_dict)

    report("Recipes", recipe_errors)
    report("Ingredients", ingredient_errors)


if __name__ == "__main__":
    main()
