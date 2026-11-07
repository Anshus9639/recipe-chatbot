"""Task 2: ingredient-based recipe matching. Hard filters first, transparent score second."""
import re
from dataclasses import dataclass, replace

import numpy as np

from src import restrictions as R
from src.normalize import normalize_ingredient
from src.search import Filters, RecipeIndex

STAPLES = {"salt", "black pepper", "water"}     # assumed available; ignored in scoring
VARIANTS = {                                     # same product family; flagged as 'x ~ y'
    "rice": ["white rice", "brown rice", "long grain rice", "long grain white rice",
             "cooked rice", "basmati rice", "jasmine rice"],
    "onion": ["yellow onion", "white onion", "sweet onion"],
    "tomato": ["roma tomato", "plum tomato"],
    "chicken breast": ["chicken breast half"],
}


@dataclass(frozen=True)
class MatchRequest:
    have: tuple                      # normalized ingredient keys the user has
    quantities: tuple = ()           # original item strings that carried a quantity
    restrictions: tuple = ()         # HARD: named (dairy, egg, ...)
    exclude: tuple = ()              # HARD: free-text ingredients
    max_steps: int = None            # HARD (reliable-step recipes only)
    prefer_few_missing: bool = False  # PREFERENCE
    prefer_few_steps: bool = False    # PREFERENCE
    k: int = 5


def parse_have(text):
    """'2 eggs, 1 cup rice and onions' -> (keys, items_with_quantity)."""
    keys, qty = [], []
    for item in re.split(r",|;|&|\band\b", text.lower()):
        item = item.strip()
        if not item:
            continue
        if re.match(r"\d", item):
            qty.append(item)
        for k in normalize_ingredient(item):
            if k not in keys:
                keys.append(k)
    return tuple(keys), tuple(qty)


def weights(req):
    # Coverage always dominates ("use as many of my ingredients as possible");
    # completeness (few missing ingredients) is the secondary term.
    w_cov, w_comp, w_steps = 0.7, 0.3, 0.0
    if req.prefer_few_missing:
        w_cov, w_comp = 0.6, 0.4
    if req.prefer_few_steps:
        w_cov, w_comp, w_steps = w_cov * 0.8, w_comp * 0.8, 0.2
    return round(w_cov, 3), round(w_comp, 3), round(w_steps, 3)


def _cover(have):
    cover = {h: h for h in have}
    for h in have:
        for v in VARIANTS.get(h, ()):
            cover.setdefault(v, h)
    return cover


def _step_score(n, reliable):
    return (1 - (min(int(n), 10) - 1) / 9) if reliable else 0.0


def _line_for(lines, key):
    pat = re.compile(r"\b" + re.escape(R.norm_text(key)) + r"(?:e?s)?\b")
    for l in lines:
        if pat.search(R.norm_text(l)):
            return l if len(l) <= 70 else l[:67] + "..."
    return None


def _score_all(ix, idxs, cover, have, w):
    keys_col = ix.df["ingredient_keys"].to_numpy()
    steps = ix.df["n_steps"].to_numpy()
    rel = ix.df["steps_reliable"].to_numpy()
    ids = ix.df["id"].to_numpy()
    out = []
    for i in idxs:
        ks = keys_col[i]
        matched = {cover[r] for r in ks if r in cover}
        if not matched:
            continue
        ns = [r for r in ks if r not in STAPLES]
        n_miss = sum(1 for r in ns if r not in cover)
        comp = (len(ns) - n_miss) / len(ns) if ns else 1.0
        s = (w[0] * len(matched) / len(have) + w[1] * comp
             + w[2] * _step_score(steps[i], rel[i]))
        out.append((-round(s, 6), n_miss, int(steps[i]), ids[i], int(i)))
    out.sort()
    return out


def _describe(ix, i, cover, have, w):
    r = ix.df.iloc[i]
    ks, lines = r["ingredient_keys"], r["ingredients"]
    by_user = {}
    for k in ks:
        if k in cover:
            by_user.setdefault(cover[k], []).append(k)
    matched = []
    for h in have:
        for k in by_user.get(h, []):
            line = _line_for(lines, k)
            matched.append((h if k == h else f"{h} ~ {k}") + (f' ("{line}")' if line else ""))
    ns = [k for k in ks if k not in STAPLES]
    missing = [k for k in ns if k not in cover]
    comp_n, comp_d = len(ns) - len(missing), len(ns)
    comp = comp_n / comp_d if comp_d else 1.0
    cov = len(by_user) / len(have)
    st = _step_score(r["n_steps"], r["steps_reliable"])
    score = w[0] * cov + w[1] * comp + w[2] * st
    why = f"{w[0]}x coverage({len(by_user)}/{len(have)}) + {w[1]}x completeness({comp_n}/{comp_d})"
    if w[2]:
        why += f" + {w[2]}x step score({st:.2f})"
    return {
        "id": r["id"], "title": r["title"], "n_steps": int(r["n_steps"]),
        "steps_reliable": bool(r["steps_reliable"]), "score": score,
        "matched": matched, "unused": [h for h in have if h not in by_user],
        "missing": missing,
        "staples_missing": [k for k in ks if k in STAPLES and k not in cover],
        "why": f"{why} = {score:.3f}", "_i": i,
    }


def _violations(ix, i, req):
    r = ix.df.iloc[i]
    v = []
    for n in req.restrictions:
        bad = R.offending_lines(r["ingredients"], n)
        if bad:
            v.append(f"{n} restriction: \"{bad[0]}\"")
    for t in req.exclude:
        keys = tuple(normalize_ingredient(t) or [t.lower()])
        bad = R.offending_lines(r["ingredients"], R.make_spec(keys))
        if bad:
            v.append(f"excluded '{t}': \"{bad[0]}\"")
    if req.max_steps is not None and not (r["n_steps"] <= req.max_steps and r["steps_reliable"]):
        v.append(f"steps: {r['n_steps']} (limit {req.max_steps}"
                 + ("" if r["steps_reliable"] else ", step count unreliable") + ")")
    return v


def run(ix, req):
    out = {"results": [], "alternatives": [], "notes": [], "pool": 0, "candidates": 0,
           "have": [], "weights": weights(req)}
    notes = out["notes"]
    have = [h for h in req.have if h not in STAPLES]
    given_staples = [h for h in req.have if h in STAPLES]
    if given_staples:
        notes.append(f"Staples {given_staples} are assumed available and ignored in scoring.")
    if req.quantities:
        notes.append(f"Quantities were given ({'; '.join(req.quantities)}), but quantity sufficiency "
                     f"was NOT verified: recipe quantities are free text, so matching is name-level.")

    specs = [R.SPECS[n] for n in req.restrictions] + \
            [R.make_spec(tuple(normalize_ingredient(t) or [t.lower()])) for t in req.exclude]
    kept = []
    for h in have:                                 # your own constraint beats your own ingredient
        if any(R.line_violates(h, s) for s in specs):
            notes.append(f"Removed '{h}' from your ingredients: it conflicts with your hard "
                         f"restriction/exclusion.")
        else:
            kept.append(h)
    known = []
    for h in kept:
        if ix._has_key(h).any() or any(ix._has_key(v).any() for v in VARIANTS.get(h, ())):
            known.append(h)
        else:
            notes.append(f"'{h}' is not an ingredient name in the dataset, so it was skipped.")
    out["have"] = known
    if not known:
        notes.append("No usable ingredients remain, so nothing was matched.")
        return out

    w = out["weights"]
    cover = _cover(known)
    cand_any = np.zeros(len(ix.df), dtype=bool)
    for key in cover:
        cand_any |= ix._has_key(key)

    mask = ix.filter_mask(Filters(exclude=req.exclude, restrictions=req.restrictions,
                                  max_steps=req.max_steps))
    out["pool"] = int(mask.sum())
    scored = _score_all(ix, np.flatnonzero(mask & cand_any), cover, known, w)
    out["candidates"] = len(scored)
    out["results"] = [_describe(ix, s[4], cover, known, w) for s in scored[:req.k]]

    if not out["results"]:                         # separate, clearly marked alternatives
        alt = _score_all(ix, np.flatnonzero(cand_any), cover, known, w)[:30]
        for s in alt:
            d = _describe(ix, s[4], cover, known, w)
            d["violations"] = _violations(ix, s[4], req)
            if d["violations"]:
                out["alternatives"].append(d)
            if len(out["alternatives"]) == 3:
                break
    return out


def _steps_txt(d):
    return f"{d['n_steps']} step(s)" + ("" if d["steps_reliable"] else " (single paragraph: count unreliable)")


def format_output(out, req):
    w = out["weights"]
    L = [f"**Your ingredients (normalized, staples excluded):** {', '.join(out['have']) or 'none'}"]
    hard = []
    if req.restrictions:
        hard.append("restrictions: " + ", ".join(req.restrictions))
    if req.exclude:
        hard.append("excludes: " + ", ".join(req.exclude))
    if req.max_steps is not None:
        hard.append(f"at most {req.max_steps} steps (reliable-step recipes only)")
    L.append("**Hard constraints (never relaxed):** " + ("; ".join(hard) or "none"))
    prefs = [p for p, on in (("fewest missing ingredients", req.prefer_few_missing),
                             ("fewer steps", req.prefer_few_steps)) if on]
    L.append("**Preferences (affect ranking only):** " + (", ".join(prefs) or "none"))
    L.append(f"**Score** = {w[0]} x coverage + {w[1]} x completeness"
             + (f" + {w[2]} x step score" if w[2] else "")
             + ". coverage = share of your ingredients the recipe uses; completeness = share of the "
               "recipe's non-staple ingredients you already have; step score = 1 for 1 step down to 0 "
               "for 10+ (0 if unreliable). Ties: fewer missing, fewer steps, then ID.")
    if out["have"]:
        L.append(f"**Pool after hard filters:** {out['pool']:,} recipes; of those, "
                 f"{out['candidates']:,} use at least one of your ingredients.")
    if out["results"]:
        L.append("")
        for n, d in enumerate(out["results"], 1):
            L.append(f"{n}. **{d['title']}**  `{d['id']}`  score {d['score']:.3f}, {_steps_txt(d)}")
            L.append(f"   - matched ({len(d['matched'])}): " + "; ".join(d["matched"]))
            L.append(f"   - missing / extra required ({len(d['missing'])}): "
                     + (", ".join(d["missing"]) or "none: you have everything"))
            if d["unused"]:
                L.append(f"   - your ingredients not used: {', '.join(d['unused'])}")
            if d["staples_missing"]:
                L.append(f"   - staples assumed available: {', '.join(d['staples_missing'])}")
            L.append(f"   - why this rank: {d['why']}")
    else:
        L.append("\n**No match found.** No recipe satisfies all hard constraints and uses your ingredients.")
        if out["alternatives"]:
            L.append("\n**Closest alternatives that VIOLATE your constraints (NOT eligible, shown for reference only):**")
            for n, d in enumerate(out["alternatives"], 1):
                L.append(f"{n}. **{d['title']}**  `{d['id']}`  score {d['score']:.3f}, {_steps_txt(d)}")
                L.append(f"   - VIOLATES: " + "; ".join(d["violations"]))
                L.append(f"   - matched: " + "; ".join(d["matched"]))
    L += [f"\n*Note: {n}*" for n in out["notes"]]
    if req.restrictions or req.exclude:
        L.append("\n*Restriction checks are text-based on ingredient lines, not a medical or allergen-safety guarantee.*")
    return "\n".join(L)


def check_hard(ix, out, req):
    """Re-verify every hard constraint on every returned recipe (guards against silent violations)."""
    by_id = ix.df.set_index("id")
    for r in out["results"]:
        row = by_id.loc[r["id"]]
        for n in req.restrictions:
            assert not R.offending_lines(row["ingredients"], n), (r["id"], n)
        for t in req.exclude:
            keys = tuple(normalize_ingredient(t) or [t.lower()])
            assert not R.offending_lines(row["ingredients"], R.make_spec(keys)), (r["id"], t)
        if req.max_steps is not None:
            assert row["n_steps"] <= req.max_steps and row["steps_reliable"], r["id"]
    print(f"[check] hard constraints verified on {len(out['results'])} result(s): OK")


if __name__ == "__main__":
    ix = RecipeIndex()

    def show(title, req):
        print("\n" + "=" * 70 + f"\n>>> {title}\n")
        out = run(ix, req)
        print(format_output(out, req))
        check_hard(ix, out, req)
        return out

    have, qty = parse_have("eggs, onions, tomatoes, and rice")
    r1 = MatchRequest(have=have, restrictions=("peanut",), max_steps=6, prefer_few_missing=True)
    show("I have eggs, onions, tomatoes, rice. Five recipes, no peanuts, at most 6 steps, fewest extra ingredients", r1)

    r2 = replace(r1, restrictions=r1.restrictions + ("egg",))
    show("Follow-up: Exclude eggs too", r2)

    have, qty = parse_have("2 eggs, 1 cup rice, tomatoes")
    r3 = MatchRequest(have=have, quantities=qty, prefer_few_steps=True)
    show("With quantities and 'fewer steps' preference", r3)

    have, qty = parse_have("unicorn horn, moondust")
    show("NO-MATCH 1: ingredients not in the dataset", MatchRequest(have=have))

    have, qty = parse_have("rice, tomatoes")
    show("NO-MATCH 2: impossible hard constraint (at most 0 steps)", MatchRequest(have=have, max_steps=0))