# One-shot LLM baseline vs. this system

Model: `gemini-2.5-flash`, one-shot, no retrieval, no conversation context. Our system's answers are computed from the local dataset.

## Question

How many recipes contain both garlic and onion? What percentage of the dataset is that?
### One-shot LLM answer

I cannot provide the exact number or percentage of recipes in the Recipe Box dataset that contain both garlic and onion.

Determining this specific ingredient co-occurrence statistic requires direct computational analysis of the ingredient lists across all ~125,000 recipes, which is not information I have access to or can compute in real-time.
### This system (grounded)

**Filters:** contains 'garlic' AND 'onion'
**Recipes matching:** 9,890
**Percentage:** 9,890 / 122,938 usable recipes = 8.04%
**Denominator:** 122,938 usable recipes (of 124,647 loaded; 1,709 lack a title, ingredients or instructions).
**Calculation:** exact match on normalized ingredient names, so 'onion' does not match 'red onion' or 'green onion'.
**Why this case matters:** Exact computed count; an LLM without retrieval can only guess.

---

## Question

Among recipes containing tomato, which five have the fewest instruction steps?
### One-shot LLM answer

Among recipes containing tomato, these five have the fewest instruction steps:

1.  **Tomato Slices with Salt** (1 step)
2.  **Quick Tomato Salad** (2 steps)
3.  **Simple Roasted Tomatoes** (2 steps)
4.  **Bruschetta with Fresh Tomato** (3 steps)
5.  **Two-Ingredient Tomato Soup** (3 steps)
### This system (grounded)

**Filters:** contains 'tomato'
**Recipes in filtered set:** 6,341; ranked: 5,807 (534 excluded as single-paragraph recipes whose steps can't be counted)
**Ranking:** fewest steps; step = non-empty instruction line; ties broken by sentence count, then ID.
**Note:** 233 recipes are tied at 1 step(s), so the cut-off among them is by the tie-break rule, not by a real difference.
                                id                           title  n_steps  n_sentences
ar:/0wx00RefE0VHzlff/GBszObKmj63Pi           Tomato Basil Smoothie        1            1
ar:5s.4S6mTsQWRNXHDFGWe6ea03Oac48C          Momma's Marinara Sauce        1            1
ar:9T2HkniyS.3VZB9NmFvzrfA39fMSt.. Black Bean and White Corn Salad        1            1
ar:BqfGsVgk7WHPebuzDH3IIRDAo0Vy8Hy        Refreshing Mango Chutney        1            1
ar:JbfChmEYkdCkIrzqZph1dWJgf/CimkW                Fresh Mild Salsa        1            1
**Why this case matters:** Stable IDs and a defined step rule; an LLM cannot know dataset IDs.

---

## Question

How many calories are in the recipe 'Creamy Penne Pasta' (ID ar:nvQzTEX.J7/2LmKnF8KjsR6aCqNHGxO) from this dataset?
### One-shot LLM answer

The recipe 'Creamy Penne Pasta' (ID ar:nvQzTEX.J7/2LmKnF8KjsR6aCqNHGxO) from this dataset has 360 calories.
### This system (grounded)

**Not available in this dataset.** Recipes contain only a title, ingredient lines and instruction text, so I can't report nutrition values or cooking times, and I won't estimate them. I can still search by dish or ingredient, count and rank recipes, match your ingredients, or show a recipe's ingredients and instructions.
**Why this case matters:** Nutrition is NOT in the dataset. Correct behavior is refusal; a specific number is fabricated.

---
