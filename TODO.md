# Meal Planner — Remaining Work

Current state: `recipes.yml`, `ingredients.yml` (in progress), a validator for
both files individually and cross-referenced, and an interactive script for
populating ingredient entries (nutrition automated, other fields prompted).

Goal: an agent that takes weekly constraints (meals needed, pantry stock,
desired "type" of week, time budget) and returns a validated weekly plan +
shopping list that minimises waste.

## Gaps to close

- [ ] **Pantry/stock schema** — a structure for "ingredients I already have"
  (`ingredient_id`, `quantity`, `unit`, `days_remaining` or `acquired_date`),
  separate from `recipes.yml`/`ingredients.yml`. Needed so the agent can
  prioritise using up what's on hand.

- [ ] **Weekly plan schema** — a structure for "which recipe on which day",
  e.g. `{day, meal_slot (lunch/dinner), recipe_id, side_dish_id, occasion
  (initial_cook/subsequent)}`. Needed before shelf-life checks, cost totals,
  or a plan validator can exist at all.

- [ ] **Shopping-list / pack-matching logic** — sum required ingredient
  quantities across a proposed week, match against `purchase_options`,
  decide which pack(s) to buy, compute leftovers. This is the "bin-packing"
  problem deferred earlier in the project — it's now the core blocker to
  "minimise wasted ingredients."
  - [ ] Decide the cost-vs-waste trade-off explicitly: when a cheaper
    pack creates more leftover, which wins by default?

- [ ] **Shelf-life-vs-cook-day check** — once the plan schema exists,
  validate that nothing bought at the start of the week is cooked after
  it's gone off. The original motivating problem for this whole project —
  still not implemented.

- [ ] **`amount_per_canonical_unit` gap** — not currently prompted for in
  the interactive ingredient script. Required for correct quantity/cost/
  nutrition math on any `whole`/`can`/`bag`/`tsp` ingredient. Either add it
  to the interactive flow or plan a dedicated pass to fill it in.

- [ ] **Price data refresh strategy** — no mechanism currently tracks
  staleness (unlike nutrition, which has a lookup script). Decide: is cost
  output a rough indicator, or does it need periodic re-collection?

- [ ] **Plan validator** — scores one proposed week (total cost, total
  active time, leftover ingredients, shelf-life violations, freezer
  feasibility) rather than searching all combinations. Pairs with an
  agent that proposes → validator checks → agent revises, same pattern as
  the recipe/ingredient validators.
  - Explicitly avoid brute-force enumeration of all recipe combinations —
    doesn't scale past a small recipe log (millions+ combinations even at
    ~50 recipes for a 5-recipe week).
  - Optional cheap pre-filter (e.g. by tag) is fine; full search is not.
