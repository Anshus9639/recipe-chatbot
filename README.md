# Recipe Chatbot

A conversational chatbot over the [Recipe Box dataset](https://eightportions.com/datasets/Recipes/)
(~125k recipes from Allrecipes, Epicurious and Food.com). It searches recipes, computes
statistics programmatically, matches recipes to ingredients you have, and adapts recipes
with evidence-based ingredient substitutions. **No LLM is used at runtime** — every answer
is retrieved or computed from the local dataset, so nothing is fabricated.

## Setup and running

Requires Python 3.10+ and ~2 GB disk for the dataset and caches.

```bash
# 1. install dependencies (a virtualenv is recommended)
python -m venv .venv
.venv\Scripts\activate          # Windows (source .venv/bin/activate on Linux/macOS)
pip install -r requirements.txt

# 2. get the data: download the dataset from https://eightportions.com/datasets/Recipes/
#    and place these three files in data/raw/ :
#      recipes_raw_nosource_ar.json
#      recipes_raw_nosource_epi.json
#      recipes_raw_nosource_fn.json

# 3. run the chatbot (first run builds the parquet cache and TF-IDF index, 1-3 min)
python -m src.router
```

Example session:

```
you> Find a penne pasta recipe
you> I cannot have dairy                  <- refines the previous search
you> show 2                               <- full ingredients + instructions
you> How many recipes contain both garlic and onion? What percentage of the dataset is that?
you> I have eggs, onions, tomatoes and rice, no peanuts, at most six steps
you> Exclude eggs too                     <- updates the match
you> Replace the cream in recipe 1 without dairy
you> start over
```

Scripted demos: `python -m src.router --demo` (search/stats), `--demo-match` (matching),
`--demo-sub` (substitution).

## Evaluation

```bash
python eval/run_eval.py         # 12 conversations, 25 turns, 57 programmatic checks
python eval/llm_baseline.py     # one-shot LLM comparison (set GEMINI_API_KEY first)
```

See [eval/REPORT.md](eval/REPORT.md) for results, what failed during development and why,
and known limitations. Full transcripts are in [eval/transcripts.md](eval/transcripts.md).
Each module also has a self-test: `python -m src.normalize`, `python -m src.stats`,
`python -m src.matcher`, `python -m src.search`, `python -m src.substitution`.

## Architecture

```
data/raw/*.json ── loader.py ──> recipes.parquet ── prepare.py ──> recipes_features.parquet
                                                                        │
router.py (CLI + session context, rule-based intent parsing)             │
  ├── search.py        Task 1: TF-IDF ranking AFTER hard filters on the full dataset
  ├── stats.py         Task 1: pandas counts/averages/rankings over the full filtered set
  ├── matcher.py       Task 2: hard filters first, then explainable coverage scoring
  ├── subchat.py       Task 3: conversation glue for adaptation requests
  └── substitution.py  Task 3: local-evidence search, grading, updated list + instructions
 normalize.py / restrictions.py: shared ingredient normalization and restriction specs
```

### Design decisions

- **Retrieval.** Hard filters (include/exclude/restrictions/step limit) are boolean masks
  computed over **all 122,938 usable recipes**; TF-IDF (title boosted 3x + normalized
  ingredient keys, 1-2 grams) only *ranks* the survivors. Aggregates never use the top-k
  results — the population is defined by filters alone.
- **Stable IDs.** `{source}:{original key}` (e.g. `ar:nvQz...`). Original titles, ingredient
  lines and instructions are preserved; the only cleaning is removing the `ADVERTISEMENT`
  website artifact into a separate cleaned copy (`ingredients_raw` keeps the original).
- **Normalization** ([src/normalize.py](src/normalize.py)). Strip quantities/units/prep words,
  singularize, merge true synonyms (`scallion` → `green onion`). Product-changing forms are
  kept distinct: `ground beef` ≠ `beef`, `garlic powder` ≠ `garlic`, `egg white` ≠ `egg`.
  `butter or margarine` keeps the first option (documented limitation).
- **Ranking (matching).** `score = w_cov·coverage + w_comp·completeness (+ w_steps·step score)`,
  weights shown in every answer; preferences only shift weights. Ties: fewer missing
  ingredients, fewer steps, then ID. Matched/missing/extra ingredients and the arithmetic
  are printed for each result, and every hard constraint is re-verified after ranking.
- **Computation.** Counts, percentages, means, medians and rankings are pandas/Python
  operations with the filters, denominator and calculation rule stated in the answer.
  Step count = non-empty instruction lines; single-paragraph recipes are flagged unreliable
  and excluded from step-sensitive queries (with the excluded count reported).
- **Substitution evidence.** For a target ingredient, the system searches the 200 most
  similar recipes (similarity computed *without* the target) for compliant recipes using
  each candidate substitute (direct evidence), plus the same dish type dataset-wide
  (indirect evidence). Evidence is graded STRONG/MODERATE/WEAK, co-occurrence conflicts
  lower confidence, and supporting recipe IDs are cited. Candidate lists and effect
  predictions are hand-written cooking knowledge and explicitly labeled as external
  hypotheses — only the *support* is computed from data. The output includes an updated
  ingredient list, revised instructions and labeled predictions.
- **Uncertainty and refusal.** No nutrition/time estimates (not in the dataset). Diets
  without an ingredient definition (vegan, gluten-free) are reported as NOT applied.
  Unknown ingredients/dishes produce explicit no-match answers. Unsupported substitution
  targets and egg-structure dishes (quiche) are refused. Restriction checks are text-based
  and every such answer carries a not-medically-safe disclaimer.
- **External search.** Not used. The assignment allows it as a secondary source; the bot
  states uncertainty instead.
- **Why no LLM at runtime?** The three tasks are retrieval + computation + evidence
  aggregation. A deterministic pipeline makes every answer reproducible and auditable,
  which is what the assignment grades. The trade-off is a brittle rule-based parser;
  mitigations (explicit filter reporting, parse warnings, refusals) are described in
  [eval/REPORT.md](eval/REPORT.md).

## AI tools disclosure

AI coding assistance (Qoder Desktop) was used for pair-programming throughout: drafting
and reviewing modules, fixing parser bugs found by the eval, and writing the eval harness
and documentation. The architecture, scoring rules, normalization rules and evidence
grading were designed iteratively with the tool and are explained above and in code;
all behavior is verified by the reproducible eval suite.

## Repository layout

```
src/    chatbot modules (each has a runnable self-test)
eval/   run_eval.py, llm_baseline.py, REPORT.md, transcripts.md, results.json
data/   raw JSON + processed parquet (git-ignored; see setup)
```