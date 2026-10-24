import re


def slugify(name: str) -> str:
    """..."""  # keep the existing docstring
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    return slug.strip("_")


def unslugify(slug: str) -> str:
    """..."""  # keep the existing docstring
    return slug.replace("_", " ").strip()


def flatten_recipes(recipe_dict: dict) -> dict:
    """Flatten a {category: {recipe_id: recipe}} structure into a single
    {recipe_id: recipe} mapping, regardless of which category each recipe
    lives under."""
    all_recipes = {}
    for category, recipes in recipe_dict.items():
        if isinstance(recipes, dict):
            all_recipes.update(recipes)
    return all_recipes


def find_ingredient_match(name: str, ingredient_dict: dict):
    """
    Attempt to resolve a recipe ingredient name against the ingredient
    database. Returns a (match_type, ingredient_id) tuple:

      - "exact"            : name matches an ingredient's key exactly -
                              this is the only case that should pass silently
      - "alias"             : name matches one of an ingredient's aliases
      - "name_field"        : name matches an ingredient's human-readable
                              'name' field, rather than its key
      - "case_insensitive"  : name matches a key, alias, or name field, but
                              only once case is ignored
      - "not_found"         : no match of any kind was found

    ingredient_id is None when match_type is "not_found". Matching is
    case-sensitive except for the dedicated "case_insensitive" fallback,
    which exists purely so a near-miss can be reported with a helpful
    suggestion rather than a bare "not found".
    """
    if name in ingredient_dict:
        return "exact", name

    for ingredient_id, ingredient in ingredient_dict.items():
        if not isinstance(ingredient, dict):
            continue
        if ingredient.get("name") == name:
            return "name_field", ingredient_id
        if name in (ingredient.get("aliases") or []):
            return "alias", ingredient_id

    lowered = name.lower()
    for ingredient_id, ingredient in ingredient_dict.items():
        if ingredient_id.lower() == lowered:
            return "case_insensitive", ingredient_id
        if not isinstance(ingredient, dict):
            continue
        if (ingredient.get("name") or "").lower() == lowered:
            return "case_insensitive", ingredient_id
        for alias in ingredient.get("aliases") or []:
            if isinstance(alias, str) and alias.lower() == lowered:
                return "case_insensitive", ingredient_id

    return "not_found", None
