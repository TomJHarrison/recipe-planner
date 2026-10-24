"""
ingredients.py

Finds every ingredient used across recipes.yml that doesn't yet exist in
ingredients.yml, orders them by how many recipes use them, and walks
through each one interactively - looking up nutrition via USDA FoodData
Central, then prompting for every other field the ingredient schema
needs (aliases, canonical_unit, purchase_options, shelf_life_days,
substitutes_with).

Each ingredient is written to the draft output file (data/nutrition_draft.yml)
the moment it's finished, so quitting early - deliberately (type 'q') or
via Ctrl+C - loses nothing already completed. Re-running the script skips
anything already in the draft file, same as it skips anything already in
ingredients.yml, so a partial run can always be resumed.

Usage:
    export USDA_API_KEY=your_key_here   # free, instant signup:
                                         # https://fdc.nal.usda.gov/api-key-signup.html
    uv run python -m recipe_planner.enrichment.nutrition_lookup

Nutrients are read by numeric nutrientId, not by name - FDC uses the same
name ("Energy") for two different nutrients (kcal and kJ), distinguished
only by id/unit, so matching by name alone is unreliable. The ID -> name
mapping below was confirmed by inspecting ~10-15 ingredients' worth of
results; extract_nutrients() still checks every food against it at
runtime and raises if a food ever disagrees, rather than silently trusting
the mapping forever.

The script will prompt for the amount per canonical unit when the ingredient
is not measured in grams. For example, garlic is measured as "whole". But the
nutrition data comes through in grams. Therefore we need to know the number
of grams per whole unit so we can calculate the nutritional information.
"""

import os
import sys
from collections import Counter
from dataclasses import dataclass

import requests
import yaml
from dotenv import load_dotenv

from recipe_planner.io import INGREDIENT_FILE, PROJECT_ROOT, RECIPE_FILE, load_yaml
from recipe_planner.matching import find_ingredient_match, flatten_recipes, slugify, unslugify

load_dotenv()
USDA_API_KEY = os.environ.get("USDA_API_KEY")

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
USDA_FOOD_URL = "https://api.nal.usda.gov/fdc/v1/food"

MAX_CANDIDATES_PER_SOURCE = 5
VALID_CANONICAL_UNITS = ["g", "ml", "tsp", "whole", "can", "bag"]
# USDA Foundation/SR Legacy nutrition is always reported per 100 g, so this is
# the unit written to nutrition.unit for every ingredient.
NUTRITION_UNIT = "g"
SHELF_LIFE_KEYS = ["fridge", "freezer", "pantry"]
NUTRITION_DRAFT_OUTPUT_PATH = PROJECT_ROOT / "data" / "nutrition_draft.yml"

# nutrientId -> (the macro field it feeds, the name FDC is expected to
# report it under). Confirmed by inspection; verified again at runtime by
# extract_nutrients() below.
NUTRIENT_ID_MAP = {
    1003: ("protein", "Protein"),
    1004: ("fat", "Total lipid (fat)"),
    1005: ("carbohydrates", "Carbohydrate, by difference"),
    1008: ("calories", "Energy"),
    1079: ("fibre", "Fiber, total dietary"),
    1258: ("saturated_fat", "Fatty acids, total saturated"),
    2000: ("sugars", "Total Sugars"),
}

DRAFT_HEADER = (
    "# Draft ingredient entries, ready to paste into ingredients.yml as-is.\n"
    "# Generated interactively by nutrition_lookup.py - every field below\n"
    "# was either pulled from a chosen USDA FoodData Central candidate or\n"
    "# entered directly by you at the prompts.\n\n"
)


@dataclass
class NutritionCandidate:
    source: str  # "USDA FoodData Central"
    description: str  # human-readable name, for picking the right one
    identifier: str  # FDC ID, kept for traceability
    calories: float = None
    protein: float = None
    carbohydrates: float = None
    sugars: float = None
    fat: float = None
    saturated_fat: float = None
    fibre: float = None

    def is_complete(self) -> bool:
        core_fields = [self.calories, self.protein, self.carbohydrates, self.fat]
        return all(value is not None for value in core_fields)


class UnexpectedNutrientNameError(Exception):
    """Raised when a nutrientId we rely on shows up under a name other
    than the one it's always been observed under - meaning the ID->name
    mapping can no longer be trusted blindly for this food."""


def extract_nutrients(food: dict) -> dict:
    """
    Build a {macro_field: value} dict (e.g. {"protein": 22.0, ...}) for one
    food, reading each macro by its nutrientId rather than its nutrientName.

    For every nutrientId we care about, if it's present in this food's
    foodNutrients list under a name other than the one recorded in
    NUTRIENT_ID_MAP, this raises immediately rather than silently
    extracting a value we can no longer be confident means what we think
    it means.

    A missing "value" key (seen in practice for at least one tomato entry)
    is treated the same as the nutrient being absent, rather than raising.
    """
    macros = dict.fromkeys(field for field, _ in NUTRIENT_ID_MAP.values())

    for nutrient in food.get("foodNutrients", []):
        nutrient_id = nutrient.get("nutrientId")
        if nutrient_id not in NUTRIENT_ID_MAP:
            continue

        field, expected_name = NUTRIENT_ID_MAP[nutrient_id]
        actual_name = nutrient.get("nutrientName")

        if actual_name != expected_name:
            raise UnexpectedNutrientNameError(
                f"nutrientId {nutrient_id} was expected to always be "
                f"'{expected_name}' but got '{actual_name}' in "
                f"\"{food.get('description')}\" (fdcId={food.get('fdcId')}). "
                "The nutrientId -> name mapping can no longer be trusted - "
                "stopping rather than silently extracting the wrong value."
            )

        macros[field] = nutrient.get("value", None)

    return macros


def search_usda(query: str) -> list[NutritionCandidate]:
    """Query USDA FoodData Central, restricted to Foundation/SR Legacy data
    (generic raw ingredients) rather than Branded/Survey data, since the
    former is far more reliable for the kind of unbranded ingredients most
    recipes call for."""
    if not USDA_API_KEY:
        return []

    params = {
        "api_key": USDA_API_KEY,
        "query": query,
        "pageSize": MAX_CANDIDATES_PER_SOURCE,
        "dataType": ["Foundation", "SR Legacy"],
    }
    response = requests.get(USDA_SEARCH_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    candidates = []
    for food in data.get("foods", []):
        macros = extract_nutrients(food)
        candidates.append(
            NutritionCandidate(
                source="USDA FoodData Central",
                description=food.get("description", ""),
                identifier=str(food.get("fdcId", "")),
                **macros,
            )
        )
    return candidates


def describe_portion(portion: dict) -> str:
    """Build a readable label for one USDA food portion, e.g. "1 clove".

    Foundation foods usually carry a portionDescription; SR Legacy foods
    usually carry only amount + modifier (and a measureUnit that is often the
    placeholder "undetermined"), so fall back to assembling a label."""
    description = portion.get("portionDescription")
    if description and description != "Quantity not specified":
        return description

    amount = portion.get("amount") or 1
    parts = [f"{amount:g}"]
    measure_unit = portion.get("measureUnit")
    measure_name = measure_unit.get("name") if isinstance(measure_unit, dict) else measure_unit
    if measure_name and measure_name != "undetermined":
        parts.append(str(measure_name))
    if portion.get("modifier"):
        parts.append(str(portion["modifier"]))
    return " ".join(parts)


def fetch_portions(fdc_id: str) -> list[tuple[str, float]]:
    """Fetch the household portions USDA records for one food and return
    (description, grams_in_one_unit) pairs, e.g. [("1 clove", 3.0)].

    The search endpoint returns an abridged record without portions, so this
    needs the single-food endpoint. gramWeight is divided by amount so every
    result is the weight of exactly one unit (USDA sometimes records e.g.
    "2 tbsp = 30 g"). Portions with no gramWeight are skipped. Returns an empty
    list if there's no API key or the food has no portions."""
    if not USDA_API_KEY:
        return []

    response = requests.get(
        f"{USDA_FOOD_URL}/{fdc_id}",
        params={"api_key": USDA_API_KEY},
        timeout=10,
    )
    response.raise_for_status()
    food = response.json()

    portions = []
    for portion in food.get("foodPortions") or []:
        gram_weight = portion.get("gramWeight")
        if not gram_weight:
            continue
        amount = portion.get("amount") or 1
        portions.append((describe_portion(portion), round(gram_weight / amount, 2)))
    return portions


def print_candidate(index: int, candidate: NutritionCandidate) -> None:
    print(f"  [{index}] {candidate.description}  (id={candidate.identifier})")
    if candidate.is_complete():
        print(
            f"      calories={candidate.calories}  protein={candidate.protein}  "
            f"carbs={candidate.carbohydrates}  sugars={candidate.sugars}  "
            f"fat={candidate.fat}  sat_fat={candidate.saturated_fat}  fibre={candidate.fibre}"
        )
    else:
        print("      (incomplete nutrient data - missing one or more core fields)")


def prompt_for_nutrition_choice(num_candidates: int) -> int | None:
    """Ask the user to pick a candidate by number, or skip nutrition for
    this ingredient. Returns the zero-based index chosen, or None if
    skipped."""
    while True:
        raw = input(f"  Pick [1-{num_candidates}], or 's' to skip nutrition: ").strip().lower()
        if raw == "s":
            return None
        if raw.isdigit() and 1 <= int(raw) <= num_candidates:
            return int(raw) - 1
        print("  Not a valid choice, try again.")


def lookup_nutrition(query: str) -> NutritionCandidate | None:
    """Search USDA for `query` and let the user pick a candidate, or skip.
    Skipping nutrition does NOT skip the rest of the ingredient - the
    caller still prompts for every other field."""
    candidates = search_usda(query)

    if not candidates:
        print("  No candidates found - nutrition will be left blank for manual entry.")
        return None

    for index, candidate in enumerate(candidates, start=1):
        print_candidate(index, candidate)

    choice = prompt_for_nutrition_choice(len(candidates))
    return candidates[choice] if choice is not None else None


# --- discovering what's missing -----------------------------------------


def load_draft_ids(path) -> set[str]:
    """Return the set of ingredient ids already written to the draft
    output file by a previous (possibly interrupted) run, so this run
    skips re-asking about them. Returns an empty set if the file doesn't
    exist yet, is empty, or fails to parse (e.g. was interrupted mid-write)."""
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError:
            return set()
    return set(data.keys()) if isinstance(data, dict) else set()


def find_missing_ingredients(recipe_dict: dict, ingredient_dict: dict) -> list[tuple[str, int]]:
    """
    Identify every distinct ingredient name used across all recipes that
    does not already resolve to an entry in ingredient_dict (by exact key,
    name, or alias - via find_ingredient_match, the same logic the
    cross-file validator uses) and that hasn't already been written to the
    draft output file in a previous run.

    Returns (name, occurrence_count) tuples sorted by occurrence_count
    descending, so the most-used missing ingredients are worked through
    first.
    """
    all_recipes = flatten_recipes(recipe_dict)
    name_counts = Counter()

    for recipe in all_recipes.values():
        if not isinstance(recipe, dict):
            continue
        for ingredient in recipe.get("ingredients", []) or []:
            if not isinstance(ingredient, dict):
                continue
            name = ingredient.get("name")
            if isinstance(name, str):
                name_counts[name] += 1

    missing = []
    for name, count in name_counts.items():
        match_type, _ = find_ingredient_match(name, ingredient_dict)
        if match_type != "not_found":
            continue
        missing.append((name, count))

    missing.sort(key=lambda item: item[1], reverse=True)
    return missing


# --- prompting for the non-nutrition fields -------------------------------


def prompt_for_aliases() -> list[str]:
    print("  Aliases (blank to finish):")
    aliases = []
    while True:
        value = input(f"    alias {len(aliases) + 1} (or blank to finish): ").strip()
        if not value:
            return aliases
        aliases.append(slugify(value))


def prompt_for_canonical_unit() -> str:
    options = " | ".join(VALID_CANONICAL_UNITS)
    while True:
        value = input(f"  canonical_unit [{options}]: ").strip().lower()
        if value in VALID_CANONICAL_UNITS:
            return value
        print(f"  Not a valid unit - must be one of: {options}")


def prompt_for_grams() -> float | None:
    """Prompt for a positive number of grams. Blank skips (returns None)."""
    while True:
        raw = input("    grams in one unit (blank to skip): ").strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            print("    Not a valid number, try again.")
            continue
        if value <= 0:
            print("    Must be greater than zero, try again.")
            continue
        return value


def prompt_for_amount_per_canonical_unit(
    candidate: NutritionCandidate | None, canonical_unit: str
) -> float | None:
    """Ask how many grams one canonical_unit weighs (or measures).

    Not needed, so returns None without prompting, when canonical_unit already
    matches NUTRITION_UNIT. Otherwise, if a USDA candidate was chosen, offers
    that food's recorded portions to pick from, with 'm' to type a value
    manually. With no candidate or no portions it goes straight to manual
    entry. A blank answer skips (returns None), which leaves a placeholder in
    the output for the validator to flag later."""
    if canonical_unit == NUTRITION_UNIT:
        return None

    print(f"  amount_per_canonical_unit - grams in one '{canonical_unit}':")

    portions = []
    if candidate is not None:
        try:
            portions = fetch_portions(candidate.identifier)
        except requests.RequestException as exc:
            print(f"    Could not fetch USDA portions ({exc}) - enter a value manually.")
        else:
            if not portions:
                print("    No USDA portions recorded for this food - enter a value manually.")

    if not portions:
        return prompt_for_grams()

    for index, (description, grams) in enumerate(portions, start=1):
        print(f"    [{index}] {description} = {grams:g} g")

    while True:
        raw = (
            input(f"    Pick [1-{len(portions)}], 'm' to enter grams manually, or blank to skip: ")
            .strip()
            .lower()
        )
        if not raw:
            return None
        if raw == "m":
            return prompt_for_grams()
        if raw.isdigit() and 1 <= int(raw) <= len(portions):
            return portions[int(raw) - 1][1]
        print("    Not a valid choice, try again.")


def prompt_for_is_staple() -> bool:
    """Ask whether this ingredient is a staple, i.e. always in stock and
    assumed available. Staples skip the purchase option and shelf life
    prompts. Anything other than 'y' means no."""
    answer = input("  Is this a staple (always in stock; skips price and shelf life)? [y/N]: ")
    return answer.strip().lower() == "y"


def prompt_for_float(prompt_text: str) -> float:
    while True:
        raw = input(prompt_text).strip()
        try:
            return float(raw)
        except ValueError:
            print("    Not a valid number, try again.")


def prompt_for_purchase_options() -> list[dict]:
    print("  Purchase options (at least one required):")
    options = []
    while True:
        quantity = prompt_for_float(f"    quantity for option {len(options) + 1}: ")
        cost = prompt_for_float(f"    cost for option {len(options) + 1}: ")
        options.append({"quantity": quantity, "cost": cost})
        another = input("    Add another purchase option? [y/N]: ").strip().lower()
        if another != "y":
            return options


def prompt_for_shelf_life() -> dict:
    while True:
        shelf_life = {}
        for key in SHELF_LIFE_KEYS:
            raw = input(f"  shelf_life_days.{key} (days, or blank to skip): ").strip()
            if not raw:
                continue
            try:
                shelf_life[key] = int(raw)
            except ValueError:
                print("  Not a valid whole number - treating as skipped.")
        if shelf_life:
            return shelf_life
        print("  At least one of fridge/freezer/pantry is required - please enter at least one.")


def prompt_for_substitutes() -> list[str]:
    print("  Substitutes with (yaml key, e.g. chicken_breast_fillets; blank to finish):")
    substitutes = []
    while True:
        value = input(f"    substitute {len(substitutes) + 1} (or blank to finish): ").strip()
        if not value:
            return substitutes
        substitutes.append(slugify(value))


# --- writing each completed ingredient immediately ------------------------


def append_ingredient_block(
    path,
    ingredient_id: str,
    name: str,
    candidate: NutritionCandidate | None,
    aliases: list[str],
    canonical_unit: str,
    purchase_options: list[dict],
    shelf_life: dict,
    substitutes: list[str],
    amount_per_canonical_unit: float | None = None,
    is_staple: bool = False,
) -> None:
    """Append one completed ingredient's YAML block to the draft output
    file and flush immediately, so a crash or a deliberate quit after this
    point loses nothing already written."""
    file_exists = os.path.exists(path)
    with open(path, "a") as f:
        if not file_exists:
            f.write(DRAFT_HEADER)

        f.write(f"{ingredient_id}:\n")
        f.write(f'  name: "{name}"\n')

        if aliases:
            f.write("  aliases:\n")
            for alias in aliases:
                f.write(f"  - {alias}\n")

        f.write(f"  canonical_unit: {canonical_unit}\n")

        if is_staple:
            f.write("  is_staple: true\n")

        if purchase_options:
            f.write("  purchase_options:\n")
            for option in purchase_options:
                f.write(f"  - quantity: {option['quantity']}\n")
                f.write(f"    cost: {option['cost']}\n")

        if shelf_life:
            f.write("  shelf_life_days:\n")
            for key in SHELF_LIFE_KEYS:
                if key in shelf_life:
                    f.write(f"    {key}: {shelf_life[key]}\n")

        f.write("  nutrition:\n")
        f.write("    per: 100\n")
        f.write(f"    unit: {NUTRITION_UNIT}\n")
        if canonical_unit != NUTRITION_UNIT:
            if amount_per_canonical_unit is not None:
                f.write(f"    amount_per_canonical_unit: {amount_per_canonical_unit}\n")
            else:
                f.write(
                    "    amount_per_canonical_unit:    "
                    "# required: how much one canonical_unit weighs/measures, in `unit` above\n"
                )
        if candidate is not None:
            f.write(
                f'    source: "{candidate.source}"  '
                f"# {candidate.description} (id={candidate.identifier})\n"
            )
            f.write(f"    calories: {candidate.calories}\n")
            f.write(f"    protein: {candidate.protein}\n")
            f.write(f"    carbohydrates: {candidate.carbohydrates}\n")
            f.write(f"    sugars: {candidate.sugars}\n")
            f.write(f"    fat: {candidate.fat}\n")
            f.write(f"    saturated_fat: {candidate.saturated_fat}\n")
            f.write(f"    fibre: {candidate.fibre}\n")
        else:
            f.write("    source:    # no candidate chosen - needs manual lookup\n")
            for field in [
                "calories",
                "protein",
                "carbohydrates",
                "sugars",
                "fat",
                "saturated_fat",
                "fibre",
            ]:
                f.write(f"    {field}:\n")

        if substitutes:
            f.write("  substitutes_with:\n")
            for substitute in substitutes:
                f.write(f"  - {substitute}\n")

        f.flush()


# --- orchestration -----------------------------------------------------


def main():
    if not USDA_API_KEY:
        print(
            "Warning: USDA_API_KEY is not set - USDA FoodData Central lookups will be "
            "skipped. Get a free key at https://fdc.nal.usda.gov/api-key-signup.html "
            "and set it in your .env file.\n",
            file=sys.stderr,
        )

    recipe_dict = load_yaml(RECIPE_FILE)
    ingredient_dict = load_yaml(INGREDIENT_FILE)
    if ingredient_dict is None:
        ingredient_dict = {}

    missing = find_missing_ingredients(recipe_dict, ingredient_dict)

    if not missing:
        print("No missing ingredients found - recipes.yml and ingredients.yml are already in sync.")
        return

    print(f"{len(missing)} ingredient(s) to process, ordered by how many recipes use them.")

    try:
        for index, (name, count) in enumerate(missing, start=1):
            ingredient_id = slugify(name)
            display_name = unslugify(name)

            print(f"\n{'=' * 70}")
            print(
                f'[{index}/{len(missing)}] "{display_name}"  '
                f"(appears in {count} recipe ingredient line(s))"
            )
            print(f"Will be saved as: {ingredient_id}")
            print("=" * 70)

            response = (
                input("Press Enter to continue, or 'q' to save progress and quit: ").strip().lower()
            )
            if response == "q":
                print(
                    f"\nStopped. {index - 1}/{len(missing)} "
                    f"completed and saved to {INGREDIENT_FILE}."
                )
                return

            candidate = lookup_nutrition(display_name)
            aliases = prompt_for_aliases()
            canonical_unit = prompt_for_canonical_unit()
            amount_per_canonical_unit = prompt_for_amount_per_canonical_unit(
                candidate, canonical_unit
            )
            is_staple = prompt_for_is_staple()
            purchase_options = None if is_staple else prompt_for_purchase_options()
            shelf_life = None if is_staple else prompt_for_shelf_life()
            substitutes = prompt_for_substitutes()

            append_ingredient_block(
                INGREDIENT_FILE,
                ingredient_id,
                display_name,
                candidate,
                aliases,
                canonical_unit,
                purchase_options,
                shelf_life,
                substitutes,
                amount_per_canonical_unit=amount_per_canonical_unit,
                is_staple=is_staple,
            )
            print(f"  Saved '{ingredient_id}' to {INGREDIENT_FILE}.")

    except KeyboardInterrupt:
        print(f"\n\nInterrupted. Progress already saved to {INGREDIENT_FILE} - rerun to resume.")
        return

    print(f"\nAll {len(missing)} ingredients processed. Draft saved to {INGREDIENT_FILE}.")


if __name__ == "__main__":
    main()
