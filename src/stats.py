"""Statistics computed with pandas over the FULL filtered set (never top-k results).
Stats ignore Filters.query: TF-IDF ranks results, it doesn't define a population.
The population is defined only by include / exclude / restrictions / max_steps."""
from collections import Counter

from src import restrictions as R
from src.normalize import normalize_ingredient
from src.search import Filters, RecipeIndex


def _keys(terms):
    out = []
    for t in terms:
        out.extend(normalize_ingredient(t) or [t.lower()])
    return out


def describe(f):
    parts = []
    if f.include:
        parts.append("contains " + " AND ".join(f"'{k}'" for k in _keys(f.include)))
    if f.exclude:
        parts.append("excludes " + ", ".join(f"'{t}'" for t in f.exclude))
    if f.restrictions:
        parts.append("restrictions: " + ", ".join(f.restrictions))
    if f.max_steps is not None:
        parts.append(f"at most {f.max_steps} steps (reliable-step recipes only)")
    return "; ".join(parts) or "none (all usable recipes)"


def _subset(ix, f):
    return ix.df[ix.filter_mask(f)]


def count(ix, f):
    n, total = len(_subset(ix, f)), len(ix.df)
    pct = 100 * n / total
    text = (
        f"**Filters:** {describe(f)}\n"
        f"**Recipes matching:** {n:,}\n"
        f"**Percentage:** {n:,} / {total:,} usable recipes = {pct:.2f}%\n"
        f"**Denominator:** {total:,} usable recipes (of {ix.n_all:,} loaded; "
        f"{ix.n_all - total:,} lack a title, ingredients or instructions).\n"
        f"**Calculation:** exact match on normalized ingredient names, so 'onion' does "
        f"not match 'red onion' or 'green onion'."
    )
    return {"n": n, "total": total, "pct": pct, "text": text}


def ingredient_counts(ix, f):
    sub = _subset(ix, f)
    if sub.empty:
        return {"n": 0, "text": f"**Filters:** {describe(f)}\nNo recipes match, so nothing to average."}
    a, b = sub["n_ingredients"], sub["n_unique_ingredients"]
    text = (
        f"**Filters:** {describe(f)}\n"
        f"**Recipes analyzed:** {len(sub):,}\n"
        f"**Ingredient lines per recipe:** mean {a.mean():.2f}, median {a.median():.1f}\n"
        f"**Distinct normalized ingredients per recipe:** mean {b.mean():.2f}, median {b.median():.1f}\n"
        f"**Calculation:** pandas mean/median over every recipe in the filtered set."
    )
    return {"n": len(sub), "text": text}


def common_ingredients(ix, f, top=10):
    sub = _subset(ix, f)
    n = len(sub)
    skip = set(_keys(f.include))      # don't list the ingredient the user filtered on
    c = Counter(k for ks in sub["ingredient_keys"] for k in ks if k not in skip)
    rows = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    lines = [f"{i}. {k}: {v:,} recipes ({100 * v / n:.1f}%)" for i, (k, v) in enumerate(rows, 1)]
    text = (
        f"**Filters:** {describe(f)}\n"
        f"**Recipes analyzed:** {n:,}\n"
        f"**Most common ingredients (normalized names; filter ingredients omitted):**\n"
        + "\n".join(lines)
        + "\n**Calculation:** count of recipes containing each normalized ingredient, "
          "over the full filtered set."
    )
    return {"n": n, "rows": rows, "text": text}


def rank_steps(ix, f, k=5, fewest=True):
    """Rank by n_steps (non-empty instruction lines). Only recipes with reliable step
    counts take part. Tie-break: n_sentences, then id, so results are reproducible."""
    sub = _subset(ix, f)
    rel = sub[sub["steps_reliable"]]
    asc = fewest
    rel = rel.sort_values(["n_steps", "n_sentences", "id"], ascending=[asc, asc, True])
    top = rel.head(k)
    if top.empty:
        return {"n": 0, "table": top, "text": f"**Filters:** {describe(f)}\nNo recipes with reliable step counts."}
    boundary = int(top["n_steps"].iloc[-1])
    n_tied = int((rel["n_steps"] == boundary).sum())
    text = (
        f"**Filters:** {describe(f)}\n"
        f"**Recipes in filtered set:** {len(sub):,}; ranked: {len(rel):,} "
        f"({len(sub) - len(rel):,} excluded as single-paragraph recipes whose steps can't be counted)\n"
        f"**Ranking:** {'fewest' if fewest else 'most'} steps; step = non-empty instruction line; "
        f"ties broken by sentence count, then ID.\n"
        f"**Note:** {n_tied:,} recipes are tied at {boundary} step(s), so the cut-off among them "
        f"is by the tie-break rule, not by a real difference."
    )
    return {"n": len(rel), "table": top[["id", "title", "n_steps", "n_sentences"]], "text": text}


if __name__ == "__main__":
    ix = RecipeIndex()
    print(f"usable={len(ix.df):,} loaded={ix.n_all:,}\n")

    print("--- Q1: recipes with garlic AND onion ---")
    q1 = count(ix, Filters(include=("garlic", "onion")))
    print(q1["text"])
    keys = _keys(("garlic", "onion"))
    manual = sum(1 for ks in ix.df["ingredient_keys"] if all(k in ks for k in keys))
    assert manual == q1["n"], (manual, q1["n"])
    print("cross-check with a plain Python loop: OK\n")

    print("--- Q2: 5 fewest steps among tomato recipes ---")
    q2 = rank_steps(ix, Filters(include=("tomato",)), k=5)
    print(q2["text"])
    print(q2["table"].to_string(index=False))
    sub = ix.df[ix.df["ingredient_keys"].apply(lambda ks: "tomato" in ks) & ix.df["steps_reliable"]]
    assert int(q2["table"]["n_steps"].min()) == int(sub["n_steps"].min())
    print("cross-check minimum steps: OK\n")

    print("--- Q3: ingredient counts, dairy-free chicken recipes ---")
    print(ingredient_counts(ix, Filters(include=("chicken",), restrictions=("dairy",)))["text"], "\n")

    print("--- Q4: common ingredients in tomato recipes ---")
    print(common_ingredients(ix, Filters(include=("tomato",)), top=8)["text"], "\n")

    print("--- Re-check of Step 6 test [4]: every filter condition on every match ---")
    f3 = Filters(query="chicken", include=("garlic", "lemon juice"), exclude=("egg",), max_steps=4)
    res, _, n_match = ix.search(f3, top_k=1000)
    full = ix.df.set_index("id")
    for rid in res["id"]:
        r = full.loc[rid]
        assert "garlic" in r["ingredient_keys"] and "lemon juice" in r["ingredient_keys"]
        assert not R.offending_lines(r["ingredients"], R.make_spec(("egg",)))
        assert r["n_steps"] <= 4 and r["steps_reliable"]
    print(f"all {len(res)} results satisfy include / exclude / max_steps: OK")