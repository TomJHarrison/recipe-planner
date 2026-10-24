# Recipe Planner

## Aim

My goal is to have a tool which means that, prior to doing my weekly food shop, I can give some information to an agent, such as:

- How many meals I need to cook for
- The ingredients I already have in the fridge that I want to use up
- What *sort* of week I want to have:
  - Are there any particular recipes I want to cook?
  - Do I want a cheaper week?
  - Do I want to be healthy?
- How much time I have, and whether there are any particular days on which I have very little time to cook

The agent would then return a meal plan for the week, with proposed meals on each day, along with an ingredient list. The plan should fit within whatever constraints I've given it, and should minimise wasted ingredients — I don't want to end up buying a pack of something for one recipe and throwing most of it away because nothing else that week uses it up.

## What this needs to get there

- A log of recipes to choose from, with enough information about each one (how long it takes, whether it freezes, whether I can eat it at work, how many meals it makes, etc.) to actually plan around.
- Information about the ingredients those recipes use — most importantly the quantities they're actually sold in, so the plan can account for real pack sizes rather than assuming I can buy exactly what a recipe calls for. Nutrition and cost are also captured, since they're a useful by-product - if I ask for a healthy or cheap week, the agent should be able to use this to prioritise accordingly.
- Some way of validating that a proposed meal plan actually fits what I asked for — total cooking time, how many meals it produces, how much gets left over, whether things can be frozen, and so on. The intention isn't for this to search every possible combination of recipes itself, but to check whatever plan is proposed and say what works and what doesn't, so a plan can be refined until it fits.

## Current status

- `data/recipes.yml` — one entry per recipe, including ingredients and quantities, cooking time, freezer/eat-at-work suitability, and portions.
- `data/ingredients.yml` — one entry per ingredient (in progress), with purchase options and prices, nutrition information, and shelf life under different storage conditions.
- `src/recipe_planner/validation/` — checks both files individually, and checks that they reconcile with each other (e.g. every ingredient used in a recipe actually exists in the ingredient database).
- `src/recipe_planner/data_extraction/` — a script to make populating the ingredient database faster: it looks up nutrition data automatically and prompts for everything else that can't be sourced that way.

See `TODO.md` for what's still missing before this can actually plan a week end to end.
