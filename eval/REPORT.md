# Evaluation report

## How to reproduce

```bash
python eval/run_eval.py        # 12 conversations, 25 turns, 57 programmatic checks
python eval/llm_baseline.py    # one-shot LLM comparison (needs GEMINI_API_KEY)
```

`run_eval.py` writes `eval/transcripts.md` (full conversations) and `eval/results.json`
(pass/fail per check). Checks are not just string matching: every statistical answer is
re-verified with an **independent computation** (a plain Python loop for the garlic+onion
count, an independent pandas re-rank for the step ranking), every returned recipe ID is
looked up in the dataset, and every hard constraint (dairy/egg/peanut exclusions, step
limits) is re-checked on the actual ingredient lines of each result.

## Results

**57 / 57 checks pass** (12 conversations, 25 user turns, 122,938 usable recipes).

| Conv | Task | Covers | Result |
|---|---|---|---|
| C1 | 1 | Search + "I cannot have dairy" follow-up refines the active search; evidence lines; detail view | PASS |
| C2 | 1 | Aggregate count + percentage with denominator, cross-checked by independent loop | PASS |
| C3 | 1 | Fewest-step ranking among tomato recipes; IDs match an independent re-rank | PASS |
| C4 | 1 | Mean/median ingredient count, cross-checked with pandas | PASS |
| C5 | 1 | Calories question → refusal (attribute not in dataset) | PASS |
| C6 | 1 | "gluten-free" → explicit notice that the diet was NOT applied; unknown dish → no fabrication | PASS |
| C7 | 2 | PDF example: pantry matching, no peanuts, ≤6 steps, fewest extra; "Exclude eggs too" updates results | PASS |
| C8 | 2 | No-match: unknown ingredients; impossible limit → alternatives clearly marked VIOLATES / NOT eligible | PASS |
| C9 | 3 | Egg-free banana bread: cited dataset IDs all exist, updated list + revised instructions, predictions labeled; "Use applesauce instead" and "Also no dairy" follow-ups | PASS |
| C10 | 3 | Refusals: quiche (eggs are structural, no local egg-free evidence) and flour (no substitution rule) | PASS |
| C11 | 3 | Weak/conflicting evidence: preferred substitute (yogurt) violates the dairy restriction → rejected, not silently swapped | PASS |
| C12 | 1 | Unreadable step limit ("at most about six or seven steps") → explicit warning, no silent drop | PASS |

## What worked

- **Hard filters on the full dataset, TF-IDF only for ranking.** Counts and percentages are
  computed over every recipe passing the filters, never over the top-k search results.
- **Session context.** Restrictions persist across turns and across tasks (search → match →
  substitution) until the user clears them; "Exclude eggs too" updates the active match.
- **Never relaxing hard constraints silently.** Matching re-verifies every returned recipe
  (`matcher.check_hard`); violating alternatives are shown only in a separate, labeled block.
- **Grounded refusal.** Nutrition/time questions, unenforceable diets (vegan, gluten-free),
  unknown ingredients, egg-structure dishes and unsupported substitution targets all produce
  explicit refusals instead of plausible-sounding answers.
- **Evidence grading for substitution.** Direct evidence (similar recipes using the substitute
  without the target) beats indirect evidence (same dish type); co-occurrence conflicts lower
  confidence; every claim cites real recipe IDs (all verified to exist by the eval).

## What failed, and why

- **C12 failed on the first eval run (2 checks).** The "unreadable step limit" warning was
  dead code: it was nested inside the branch where the limit had *already* parsed, so it
  could never fire. After moving it to an `else` branch, the eval exposed two more bugs in
  the same path: the leftover phrase "with at most about six or seven steps" was parsed as an
  ingredient inclusion (`at most six`), and `stat_kind` treated the "most" in "at most" as a
  ranking keyword. Fixed by removing the unreadable phrase from further parsing and ignoring
  "at most" in ranking detection. All 57 checks now pass. This is exactly the kind of silent
  misparse the assignment warns about, and it was caught by a scripted conversation, not by
  reading the code.

## Known limitations (honest failure modes)

- **Rule-based language understanding.** The router uses regex patterns, not an LLM. Phrasings
  outside the patterns are misrouted or partially understood. Mitigation: the bot reports the
  filters it actually applied, warns when it detects a limit it cannot read, and refuses
  inputs it cannot interpret instead of guessing.
- **Substitution knowledge base covers 5 ingredient families** (egg, cream, butter, milk,
  cheese). Any other target is explicitly refused ("no substitution rules for 'flour'"),
  which the assignment allows: refusing unsupported answers beats fabricating them.
- **Restriction checks are text-based.** "dairy-free" means no dairy term appears in the
  ingredient lines; hidden sources (e.g. milk solids in margarine, broth composition) cannot
  be detected. Every such answer carries a not-medically-safe disclaimer.
- **Quantities are name-level only.** The matcher accepts quantities but states that
  sufficiency was NOT verified, because dataset quantities are free text.
- **Normalization loses information.** "butter or margarine" keeps only the first option;
  "onion" does not match "red onion" (deliberate: they are different products). Both rules are
  stated in the answers they affect.
- **Step counts** = non-empty instruction lines. Single-paragraph recipes with ≥4 sentences
  are flagged unreliable and excluded from step-limited queries and rankings, and the counts
  of excluded recipes are reported.

## One-shot LLM comparison

`eval/llm_baseline.py` sends three questions to Gemini one-shot (no retrieval, no context)
and saves its answers beside our computed answers in `eval/llm_baseline.md`:

1. **Garlic + onion count/percentage** — the exact answer is 9,890 / 122,938 = 8.04%.
   An LLM without retrieval can only produce a plausible-sounding guess.
2. **Five tomato recipes with fewest steps** — requires stable dataset IDs and a defined
   step-counting rule; a one-shot LLM cannot know the IDs and typically invents titles.
3. **Calories of a specific recipe** — nutrition is not in the dataset. Any specific number
   is fabricated; the correct behavior (which our system shows) is refusal.

**Status: executed** with `gemini-2.5-flash` (one-shot, no retrieval). Full output:
[`eval/llm_baseline.md`](llm_baseline.md). Verified findings:

1. **Garlic + onion count** — the LLM declined, saying it cannot compute dataset statistics.
   Our system returns the exact computed answer (9,890 / 122,938 = 8.04%) with the denominator
   and normalization rule stated.
2. **Five tomato recipes with fewest steps** — the LLM **fabricated a ranked list**: we checked
   all five titles against the dataset and **4 of 5 do not exist at all** ("Tomato Slices with
   Salt", "Simple Roasted Tomatoes", "Bruschetta with Fresh Tomato", "Two-Ingredient Tomato
   Soup"). The one real title ("Quick Tomato Salad", `fn:oJNprjaC7EYgQPmwnFdHcj0kcvRNiUS`) has
   1 step, not the claimed 2, its step count is flagged unreliable (single paragraph), and it
   does not contain the normalized ingredient `tomato`, so it is not even eligible for this
   ranking. None of the five real answers (which our system returns with stable IDs) appear in
   the LLM's list. This is the assignment's required case of a plausible-sounding but wrong
   and ungrounded one-shot answer.
3. **Calories of a specific recipe** — the LLM asserted "**360 calories**" for a recipe whose
   record contains no nutrition data whatsoever: a pure fabrication. Our system refuses and
   states exactly what is missing.