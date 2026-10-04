from pathlib import Path

import yaml

# This file lives at src/recipe_planner/io.py, so two levels up from here
# is the repo root, regardless of where the command is run from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RECIPE_FILE = PROJECT_ROOT / "data" / "recipes.yml"
INGREDIENT_FILE = PROJECT_ROOT / "data" / "ingredients.yml"


def load_yaml(filepath):
    with open(filepath) as stream:
        try:
            data = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            raise yaml.YAMLError(f"Unable to read yml file {filepath}") from exc

    return data
