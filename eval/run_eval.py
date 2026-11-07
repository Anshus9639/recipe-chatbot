"""Reproducible evaluation: scripted multi-turn conversations with programmatic checks.

Run from the repo root:  python eval/run_eval.py
Outputs: eval/transcripts.md (full conversations), eval/results.json (pass/fail per check).
Every statistical answer is re-verified with an independent computation, and every
returned recipe is re-checked against the hard constraints it claims to satisfy.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import restrictions as R
from src.router import Bot
from src.search import RecipeIndex

HERE = Path(__file__).resolve().parent
ID_RE = re.compile(r"\b(?:ar|epi|fn):[^\s,;?)`]+")


# ---- check helpers: each returns (ok, detail) --------------------------------
def has(text):
    return lambda bot, reply, ix: (text.lower() in reply.lower(), f"reply contains '{text}'")


def results_valid(bot, reply, ix):
    bad = [r for r in bot.last if r not in bot.by_id.index]
    return (bool(bot.last) and not bad, f"{len(bot.last)} result ID(s), all exist in dataset")


def no_violation(name):
    def check(bot, reply, ix):
        bad = {r: R.offending_lines(bot.by_id.loc[r]["ingredients"], name) for r in bot.last}
        bad = {r: v for r, v in bad.items() if v}
        return (not bad, f"restriction '{name}' re-checked on every result: {'OK' if not bad else bad}")
    return check


def steps_at_most(n):
    def check(bot, reply, ix):
        bad = [r for r in bot.last
               if not (bot.by_id.loc[r]["n_steps"] <= n and bot.by_id.loc[r]["steps_reliable"])]
        return (not bad, f"step limit {n} (reliable counts) re-checked on every result: {'OK' if not bad else bad}")
    return check


def cited_ids_exist(bot, reply, ix):
    ids = set(ID_RE.findall(reply))
    bad = [i for i in ids if i not in bot.by_id.index]
    return (bool(ids) and not bad, f"{len(ids)} cited recipe ID(s), unknown: {bad or 'none'}")


def garlic_onion_count(bot, reply, ix):
    n = sum(1 for ks in ix.df["ingredient_keys"] if "garlic" in ks and "onion" in ks)
    total = len(ix.df)
    pct = f"{100 * n / total:.2f}%"
    ok = f"{n:,}" in reply and pct in reply and f"{total:,}" in reply
    return (ok, f"independent Python loop: n={n:,}, denominator={total:,}, pct={pct}")


def tomato_rank_ids(bot, reply, ix):
    sub = ix.df[ix.df["ingredient_keys"].apply(lambda ks: "tomato" in ks) & ix.df["steps_reliable"]]
    want = list(sub.sort_values(["n_steps", "n_sentences", "id"]).head(5)["id"])
    return (bot.last == want, f"independent pandas re-rank: expected {want}, got {bot.last}")


def ingredient_mean(bot, reply, ix):
    a = ix.df["n_ingredients"]
    ok = f"{a.mean():.2f}" in reply and f"{a.median():.1f}" in reply
    return (ok, f"independent pandas: mean {a.mean():.2f}, median {a.median():.1f}")


CONVERSATIONS = [
    {"id": "C1", "task": 1, "name": "Search + restriction follow-up + detail", "turns": [
        ("Find a penne pasta recipe", [results_valid]),
        ("I cannot have dairy", [has("Refined the active search"), has("restrictions: dairy"),
                                 results_valid, no_violation("dairy"), has("evidence:")]),
        ("show 1", [has("Ingredients"), has("Instructions")]),
    ]},
    {"id": "C2", "task": 1, "name": "Aggregate statistic (count + percentage)", "turns": [
        ("How many recipes contain both garlic and onion? What percentage of the dataset is that?",
         [garlic_onion_count, has("Denominator"), has("Calculation")]),
    ]},
    {"id": "C3", "task": 1, "name": "Step-count ranking with IDs", "turns": [
        ("Among recipes containing tomato, which five have the fewest instruction steps?",
         [tomato_rank_ids, has("step = non-empty instruction line")]),
    ]},
    {"id": "C4", "task": 1, "name": "Average / median ingredient count", "turns": [
        ("What's the average and median ingredient count?", [ingredient_mean, has("Recipes analyzed")]),
    ]},
    {"id": "C5", "task": 1, "name": "Unsupported attribute refusal (nutrition)", "turns": [
        ("Find a penne pasta recipe", [results_valid]),
        ("How many calories are in result 1?", [has("Not available in this dataset"), has("won't estimate")]),
    ]},
    {"id": "C6", "task": 1, "name": "Unenforceable diet + unknown dish", "turns": [
        ("Show me gluten-free pasta", [has("was NOT applied")]),
        ("Find unicorn dust cake", [has("No matching recipe found")]),
    ]},
    {"id": "C7", "task": 2, "name": "Ingredient matching + exclusion follow-up (PDF example)", "turns": [
        ("I have eggs, onions, tomatoes, and rice. Suggest five recipes using as many of these as "
         "possible, with no peanuts and at most six instruction steps. Prefer recipes that need the "
         "fewest additional ingredients.",
         [results_valid, no_violation("peanut"), steps_at_most(6), has("why this rank"), has("missing / extra")]),
        ("Exclude eggs too", [has("Updated"), results_valid, no_violation("egg"),
                              no_violation("peanut"), steps_at_most(6)]),
        ("show 1", [has("Ingredients"), has("Instructions")]),
    ]},
    {"id": "C8", "task": 2, "name": "No-match cases (unknown ingredients / impossible limit)", "turns": [
        ("I have unicorn horn and moondust", [has("not an ingredient name in the dataset"),
                                              has("nothing was matched")]),
        ("I have rice and tomatoes, at most 0 steps", [has("No match found"), has("VIOLATES"),
                                                       has("NOT eligible")]),
    ]},
    {"id": "C9", "task": 3, "name": "Egg-free banana bread with local evidence + follow-ups", "turns": [
        ("Take this banana bread recipe and remove eggs. Use only ingredients that appear in the "
         "dataset. What replacements have evidence from related baked recipes, and how might the "
         "texture change?",
         [cited_ids_exist, has("Updated ingredient list"), has("Revised instructions"),
          has("Expected effects"), has("PREDICTIONS"), has("confidence")]),
        ("Use applesauce instead", [has("applesauce"), cited_ids_exist]),
        ("Also no dairy", [has("dairy"), has("Verification")]),
    ]},
    {"id": "C10", "task": 3, "name": "Substitution refusals (egg-structure dish / no rule)", "turns": [
        ("Take this quiche recipe and remove eggs", [has("Not adapted")]),
        ("start over", [has("reset")]),
        ("Find banana bread", [results_valid]),
        ("show 1", [has("Ingredients")]),
        ("Replace the flour in this recipe", [has("No reliable adaptation supported"),
                                              has("no substitution rules")]),
    ]},
    {"id": "C11", "task": 3, "name": "Preferred substitute violates a hard restriction", "turns": [
        ("Take this banana bread recipe and remove eggs using yogurt, without dairy",
         [has("was rejected"), has("violates your dairy")]),
    ]},
    {"id": "C12", "task": 1, "name": "Unreadable step limit is reported, not silently dropped", "turns": [
        ("Find pasta with at most about six or seven steps", [has("could not read it"),
                                                              has("NO step limit was applied")]),
    ]},
]


def main():
    ix = RecipeIndex()
    transcript = ["# Evaluation transcripts", "",
                  f"Generated by `eval/run_eval.py` on {len(ix.df):,} usable recipes.", ""]
    results, n_pass, n_fail = [], 0, 0
    for conv in CONVERSATIONS:
        bot = Bot(ix)
        transcript += [f"## {conv['id']} (Task {conv['task']}): {conv['name']}", ""]
        for turn, checks in conv["turns"]:
            reply = bot.reply(turn)
            transcript += [f"**User:** {turn}", "", reply, ""]
            for fn in checks:
                ok, detail = fn(bot, reply, ix)
                label = f"{conv['id']} | {turn[:60]} | {detail}"
                results.append({"conv": conv["id"], "turn": turn, "ok": bool(ok), "detail": detail})
                n_pass += ok
                n_fail += not ok
                print(("PASS " if ok else "FAIL ") + label)
        transcript.append("---\n")
    (HERE / "transcripts.md").write_text("\n".join(transcript), encoding="utf-8")
    (HERE / "results.json").write_text(json.dumps(
        {"pass": n_pass, "fail": n_fail, "checks": results}, indent=2), encoding="utf-8")
    print(f"\n{n_pass} passed, {n_fail} failed, {len(CONVERSATIONS)} conversations, "
          f"{sum(len(c['turns']) for c in CONVERSATIONS)} turns")
    print("Wrote eval/transcripts.md and eval/results.json")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())