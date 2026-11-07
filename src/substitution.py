"""Task 3: evidence-based ingredient substitution.
Local dataset evidence first. NO external search is used. Roles, candidate lists, amount ratios and
'expected effects' are hand-written general cooking knowledge and are labelled as such; whether a
substitute is SUPPORTED is decided only by evidence computed from the dataset."""
import re
from fractions import Fraction

import numpy as np

from src import restrictions as R
from src.normalize import normalize_ingredient, singular
from src.search import Filters, RecipeIndex

NEIGHBORS = 200     # size of the 'most similar recipes' window used for direct evidence
GRADES = {3: "STRONG", 2: "MODERATE", 1: "WEAK", 0: "NONE"}
CONF = {3: "HIGH (direct local evidence)",
        2: "MODERATE (limited direct or indirect evidence)",
        1: "LOW (weak or conflicting local evidence)"}
PASTA_WORDS = ("pasta", "penne", "spaghetti", "linguine", "fettuccine", "fettuccini", "macaroni",
               "rigatoni", "ziti", "farfalle", "lasagna", "noodle")
EGG_STRUCTURE = re.compile(r"quiche|custard|flan\b|frittata|omelet|souffle|meringue|scrambled|egg salad|"
                           r"deviled|hollandaise|mayonnaise|pudding|brulee|eggnog|french toast", re.I)

# ------------------------------------------------------------------ quantities
QTY_RE = re.compile(r"^\s*(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*(.*)$")
UNIT_RE = re.compile(r"^((?:\([^)]*\)\s*)?(?:cups?|tablespoons?|teaspoons?|tbsp|tsp|ounces?|oz|pounds?|"
                     r"lbs?|sticks?|cans?|packages?|containers?|cartons?|pints?|quarts?))\b\s*(.*)$", re.I)


def parse_qty(line):
    """'1 1/2 cups heavy cream' -> (1.5, 'cups', 'heavy cream'); '2 eggs' -> (2.0, '', 'eggs')."""
    m = QTY_RE.match(line)
    if not m:
        return None, "", line
    val = float(sum(Fraction(p) for p in m.group(1).split()))
    u = UNIT_RE.match(m.group(2))
    return (val, u.group(1), u.group(2)) if u else (val, "", m.group(2))


def fmt(x):
    f = Fraction(x).limit_denominator(8)
    w, r = divmod(f.numerator, f.denominator)
    if r == 0:
        return str(w)
    return (f"{w} " if w else "") + f"{r}/{f.denominator}"


def make_line(c, line):
    qty, unit, _ = parse_qty(line)
    if unit.lower().startswith("stick") and qty:
        qty, unit = qty * 0.5, "cup"
    if c.get("each"):
        n = qty or 1.0
        amt, u = c["each"]
        tail = c["tail"](n) if c.get("tail") else ""
        return f"{fmt(n * amt)} {u} {c['name']}{tail}"
    if qty is None:
        return f"{c['name']} (same amount as the original line; quantity could not be read)"
    return re.sub(r"\s+", " ", f"{fmt(qty * c['factor'])} {unit} {c['name']}").strip()


# ------------------------------------------------------------------ knowledge base (HYPOTHESES)
def _C(key, name, pat, factor=1.0, each=None, effect="", caution="", short=None, tail=None):
    return {"key": key, "name": name, "pat": re.compile(pat) if pat else None, "factor": factor,
            "each": each, "effect": effect, "caution": caution, "short": short or name, "tail": tail}


CREAM_SAFE = ("cream of tartar", "cream of coconut", "coconut cream", "ice cream", "cream cheese",
              "sour cream", "cream of mushroom soup", "cream of chicken soup", "cream of celery soup")

KB = {
    "egg": {
        "plain": lambda k: k == "egg", "spec": R.SPECS["egg"],
        "roles": "binding, moisture, structure/leavening",
        "instr": re.compile(r"\beggs?\b", re.I),
        "cands": [
            _C("applesauce", "applesauce", r"\bapplesauce\b", each=(0.25, "cup"),
               effect="adds moisture and mild sweetness; crumb likely denser and softer, with less rise"),
            _C("banana", "mashed ripe banana", r"\bbanana\b", each=(0.25, "cup"), short="mashed banana",
               effect="adds moisture, sweetness and banana flavor; denser texture"),
            _C("silken tofu", "silken tofu, blended smooth", r"\bsilken tofu\b", each=(0.25, "cup"),
               short="silken tofu", effect="neutral flavor; binds and moistens; slightly denser"),
            _C("pumpkin", "canned pumpkin puree", r"\bpumpkin\b(?! pie)", each=(0.25, "cup"),
               short="pumpkin puree", effect="adds moisture and color; slightly earthy flavor; denser"),
            _C("yogurt", "plain yogurt", r"\byogurt\b", each=(0.25, "cup"),
               effect="adds moisture and tang; tender crumb"),
            _C("flaxseed", "ground flaxseed", r"\bflax", each=(1, "tablespoon"), short="flaxseed mixture",
               tail=lambda n: f", mixed with {fmt(3 * n)} tablespoons water",
               effect="binds as a gel; slightly nutty, denser and more crumbly"),
        ]},
    "cream": {
        "plain": lambda k: k in {"cream", "heavy cream", "whipping cream", "heavy whipping cream", "light cream"},
        "spec": R.make_spec(("cream",), CREAM_SAFE),
        "roles": "fat/richness, moisture, sauce body (thickening)",
        "instr": re.compile(r"\b(?:heavy |whipping )?cream\b(?!\s+(?:cheese|of tartar))", re.I),
        "cands": [
            _C("coconut milk", "coconut milk", r"\bcoconut milk\b", effect="similar richness; coconut flavor; slightly thinner"),
            _C("coconut cream", "coconut cream", r"\bcoconut cream\b", effect="closest in richness; coconut flavor"),
            _C("silken tofu", "silken tofu, blended smooth", r"\bsilken tofu\b", short="silken tofu",
               effect="creamy body, neutral flavor; less fat"),
            _C("soy milk", "soy milk", r"\bsoy milk\b", effect="much thinner sauce; may need reducing"),
            _C("almond milk", "almond milk", r"\balmond milk\b", effect="much thinner sauce; mild nutty note"),
            _C("oat milk", "oat milk", r"\boat milk\b", effect="thinner sauce; slightly sweet"),
            _C("vegetable broth", "vegetable broth", r"\bvegetable (broth|stock)\b",
               effect="lighter, savory, no richness; needs thickening or reducing"),
            _C("evaporated milk", "evaporated milk", r"\bevaporated milk\b", effect="rich but dairy"),
            _C("half and half", "half and half", r"\bhalf and half\b", effect="slightly lighter than cream; dairy"),
            _C("milk", "milk", r"^(whole |skim |low fat )?milk$", effect="thin; dairy"),
        ]},
    "butter": {
        "plain": lambda k: k == "butter",
        "spec": R.make_spec(("butter",), R.RESTRICTIONS["dairy"]["safe"]),
        "roles": "fat, flavor, moisture, browning",
        "instr": re.compile(r"\bbutter\b(?!\s*(?:beans?|nut))", re.I),
        "cands": [
            _C("olive oil", "olive oil", r"\bolive oil\b", factor=0.75,
               effect="less flavor of butter, more moisture; softer, less flaky texture"),
            _C("vegetable oil", "vegetable oil", r"\bvegetable oil\b", factor=0.75,
               effect="neutral flavor; moist, softer texture"),
            _C("coconut oil", "coconut oil", r"\bcoconut oil\b", factor=1.0,
               effect="solid when cool like butter; mild coconut note"),
            _C("margarine", "margarine", r"\bmargarine\b", factor=1.0,
               effect="closest texture to butter",
               caution="margarine products often contain milk-derived ingredients; check the product label"),
            _C("shortening", "vegetable shortening", r"\bshortening\b", factor=1.0, short="shortening",
               effect="tender, less flavor"),
            _C("applesauce", "applesauce", r"\bapplesauce\b", factor=0.5,
               effect="reduces fat; denser, moister, less browning"),
        ]},
    "milk": {
        "plain": lambda k: k in {"milk", "whole milk", "skim milk", "low fat milk", "lowfat milk", "nonfat milk"},
        "spec": R.make_spec(("milk",), R.RESTRICTIONS["dairy"]["safe"]),
        "roles": "liquid/moisture, mild richness",
        "instr": re.compile(r"\bmilk\b", re.I),
        "cands": [
            _C("soy milk", "soy milk", r"\bsoy milk\b", effect="closest protein content; mild beany note"),
            _C("almond milk", "almond milk", r"\balmond milk\b", effect="thinner; mild nutty note"),
            _C("oat milk", "oat milk", r"\boat milk\b", effect="slightly sweet; creamy"),
            _C("rice milk", "rice milk", r"\brice milk\b", effect="thin and sweet"),
            _C("coconut milk", "coconut milk", r"\bcoconut milk\b", effect="richer; coconut flavor"),
            _C("water", "water", r"^water$", effect="less rich and less flavorful; thinner crumb/sauce"),
        ]},
    "cheese": {
        "plain": lambda k: (k.endswith("cheese") and k not in {"cream cheese", "cottage cheese"})
                           or k in {"parmesan", "romano", "mozzarella", "cheddar", "feta", "ricotta"},
        "spec": R.make_spec(("cheese", "parmesan", "mozzarella", "cheddar", "ricotta", "feta", "romano")),
        "roles": "flavor (salty/umami), topping, melt/binding",
        "instr": re.compile(r"\b(?:parmesan|romano|mozzarella|cheddar|cheese)\b", re.I),
        "cands": [
            {"key": None, "name": "(omit)", "omit": True, "pat": None, "short": "(omitted)",
             "effect": "less salty/savory depth; no melt or crust", "caution": ""},
        ]},
}
ALIASES = {"egg": "egg", "cream": "cream", "heavy cream": "cream", "whipping cream": "cream",
           "butter": "butter", "milk": "milk", "cheese": "cheese", "parmesan": "cheese",
           "parmesan cheese": "cheese"}


# ------------------------------------------------------------------ cached masks / context
def _cache(ix):
    return ix.__dict__.setdefault("_sub_cache", {})


def _pos(ix):
    c = _cache(ix)
    if "pos" not in c:
        c["pos"] = {rid: n for n, rid in enumerate(ix.df["id"])}
    return c["pos"]


def _cand_mask(ix, pat):
    c = _cache(ix)
    if pat.pattern not in c:
        c[pat.pattern] = ix.df["ingredient_keys"].apply(lambda ks: any(pat.search(k) for k in ks)).to_numpy()
    return c[pat.pattern]


def _context(ix, keys, title):
    """-> (long label, short label, mask, is_specific). Generic context gives much weaker indirect evidence."""
    if "flour" in keys and ("baking powder" in keys or "baking soda" in keys):
        return ("baked goods (flour + baking powder/soda)", "baked goods",
                ix._has_key("flour") & (ix._has_key("baking powder") | ix._has_key("baking soda")), True)
    t = title.lower()
    if any(w in k for k in keys for w in PASTA_WORDS) or any(w in t for w in PASTA_WORDS):
        c = _cache(ix)
        if "ctx_pasta" not in c:
            c["ctx_pasta"] = ix.df["ingredient_keys"].apply(
                lambda ks: any(w in k for k in ks for w in PASTA_WORDS)).to_numpy()
        return "pasta dishes (pasta word in title or ingredients)", "pasta dishes", c["ctx_pasta"], True
    return ("all recipes (no specific dish type detected)", "all recipes",
            np.ones(len(ix.df), dtype=bool), False)


def _line_with(row, pat):
    for l in row["ingredients"]:
        if any(pat.search(k) for k in normalize_ingredient(l)):
            return l
    return None


def _sentence_with(text, word):
    for s in re.split(r"(?<=[.!?])\s+|\n", text):
        if re.search(re.escape(word), s, re.I):
            return s.strip()[:170]
    return None


def _grade(nd, ni, specific):
    """Evidence grade. Indirect-only evidence from an unspecific dish type can never exceed WEAK."""
    if nd >= 3:
        return 3
    if nd >= 2 or (nd >= 1 and ni >= 10) or (specific and ni >= 25):
        return 2
    if nd >= 1 or ni >= 3:
        return 1
    return 0


# ------------------------------------------------------------------ evidence for one target
def _evaluate(ix, i, name, specs, H, prefer):
    kb = KB[name]
    row = ix.df.iloc[i]
    keys = row["ingredient_keys"]
    T = ix._violators(("tgt", name), kb["spec"])                 # recipes containing the target
    doc = (row["title"].lower() + " ") * 3 + " ".join(k for k in keys if not R.line_violates(k, kb["spec"]))
    sims = (ix.X @ ix.vec.transform([doc]).T).toarray().ravel()   # similarity WITHOUT the target
    sims[i] = -1.0
    top = np.argpartition(-sims, NEIGHBORS)[:NEIGHBORS]
    top = top[sims[top] > 0]
    nb = np.zeros(len(sims), dtype=bool)
    nb[top] = True
    ctx_long, ctx_short, ctx, specific = _context(ix, keys, row["title"])
    base = H & ~T                                               # compliant recipes lacking the target
    ev = {"context": ctx_long, "ctx": ctx_short, "n_nb": int(nb.sum()), "n_nb_free": int((nb & base).sum()),
          "recs": [], "rejected": [], "chosen": None, "prefer_note": None, "alternatives": [], "blocked": None}

    def top_ids(mask, k=3):
        idx = np.flatnonzero(mask)
        idx = idx[np.argsort(-sims[idx])][:k]
        return [ix.df["id"].iat[j] for j in idx], idx

    for c in kb["cands"]:
        if c.get("omit"):
            direct, ind = nb & base, ctx & base
            rec = {"c": c, "n_direct": int(direct.sum()), "n_ind": int(ind.sum()), "n_with": 0,
                   "rate": None, "conflict": False, "in_recipe": False, "example": None, "ind_ids": []}
            rec["direct_ids"], _ = top_ids(direct)
        else:
            M = _cand_mask(ix, c["pat"])
            if not M.any():
                ev["rejected"].append((c["name"], "no recipe in the dataset contains it")); continue
            viol = [lbl for lbl, s in specs if R.line_violates(c["name"], s)]
            if viol:
                ev["rejected"].append((c["name"], f"violates your {viol[0]}")); continue
            direct, ind = nb & base & M, ctx & base & M
            n_alone, n_with = int(ind.sum()), int((ctx & T & M).sum())
            rate = n_alone / (n_alone + n_with) if (n_alone + n_with) else None
            rec = {"c": c, "n_direct": int(direct.sum()), "n_ind": n_alone, "n_with": n_with, "rate": rate,
                   "conflict": rate is not None and rate < 0.5 and (n_alone + n_with) >= 5,
                   "in_recipe": any(c["pat"].search(k) for k in keys), "example": None}
            rec["direct_ids"], di = top_ids(direct)
            rec["ind_ids"], _ = top_ids(ind & ~nb)
            if len(di):
                r2 = ix.df.iloc[int(di[0])]
                rec["example"] = (r2["id"], _line_with(r2, c["pat"]),
                                  _sentence_with(r2["instructions"], c["key"].split()[0]))
        rec["grade"] = _grade(rec["n_direct"], rec["n_ind"], specific)
        rec["eff"] = rec["grade"] - (1 if rec["conflict"] else 0)   # conflict lowers confidence one level
        ev["recs"].append(rec)

    ev["recs"].sort(key=lambda r: (-r["eff"], r["conflict"], -r["n_direct"], -r["n_ind"]))
    usable = [r for r in ev["recs"] if r["eff"] >= 1 and not r["in_recipe"]]
    if prefer:
        p = prefer.lower()
        pick = next((r for r in ev["recs"] if p in r["c"]["name"].lower()), None)
        why = next((w for n, w in ev["rejected"] if p in n.lower()), None)
        if pick is None:
            ev["prefer_note"] = (f"Your preferred substitute '{prefer}' was rejected: {why}." if why
                                 else f"'{prefer}' is not a known candidate for this ingredient.")
        elif pick["in_recipe"]:
            ev["prefer_note"] = f"'{prefer}' is already an ingredient of this recipe, so it cannot be used as a swap."
            pick = None
        elif pick["eff"] < 1:
            ev["prefer_note"] = (f"Your preferred substitute '{prefer}' has too little local evidence "
                                 f"({GRADES[pick['grade']]}{' + CONFLICT' if pick['conflict'] else ''}), so it was not applied.")
            pick = None
        if pick is None:
            ev["alternatives"] = usable[:3]
    else:
        pick = usable[0] if usable else None

    if pick and name == "egg" and EGG_STRUCTURE.search(row["title"]) and pick["n_direct"] == 0:
        ev["blocked"] = (f"In '{row['title'].strip()}' eggs form the structure (they set the dish), and the dataset has no "
                         f"similar egg-free recipe. Evidence from unrelated dishes is not enough to adapt it reliably.")
        pick = None
        ev["alternatives"] = []
    ev["chosen"] = pick
    return ev


# ------------------------------------------------------------------ main entry
def _res(status, text, **kw):
    return {"status": status, "text": text, **kw}


def adapt(ix, recipe_id, target=None, restrictions=(), exclude=(), prefer=None):
    pos = _pos(ix)
    if recipe_id not in pos:
        return _res("unsupported", f"Recipe `{recipe_id}` was not found.")
    i = pos[recipe_id]
    row = ix.df.iloc[i]
    lines = list(row["ingredients"])
    specs = [(n, R.SPECS[n]) for n in restrictions] + \
            [(f"exclusion '{t}'", R.make_spec(tuple(normalize_ingredient(t) or [t.lower()]))) for t in exclude]
    H = ix.filter_mask(Filters(restrictions=tuple(restrictions), exclude=tuple(exclude)))
    line_keys = [normalize_ingredient(l) for l in lines]
    head = [f"**Recipe:** {row['title'].strip()} (`{row['id']}`)",
            f"**Request:** replace {target or 'every ingredient that violates your restrictions'}; "
            f"**hard restrictions:** {', '.join(n for n, _ in specs) or 'none'}"]

    assign, unsupported = {}, []
    if target:
        name = ALIASES.get(" ".join(singular(w) for w in target.lower().split()))
        if not name:
            return _res("unsupported", "\n".join(head) + f"\n\n**No reliable adaptation supported.** I have no "
                        f"substitution rules for '{target}' (supported: egg, cream, butter, milk, cheese), and "
                        f"inventing one would be ungrounded. The recipe is unchanged.")
        for j, ks in enumerate(line_keys):
            if any(KB[name]["plain"](k) for k in ks):
                assign[j] = name
        if not assign:
            rel = [l for l in lines if R.line_violates(l, KB[name]["spec"])]
            return _res("unsupported", "\n".join(head) + f"\n\n**No change made.** This recipe has no plain "
                        f"'{target}' line I can safely replace. Related lines: {rel or 'none'}.")
    else:
        if not specs:
            return _res("unsupported", "Tell me which ingredient to replace or which restriction to satisfy.")
        for j, l in enumerate(lines):
            if not any(R.line_violates(l, s) for _, s in specs):
                continue
            nm = next((n for n, kb in KB.items() if any(kb["plain"](k) for k in line_keys[j])), None)
            if nm:
                assign[j] = nm
            else:
                unsupported.append(l)
        if not assign and not unsupported:
            return _res("ok", "\n".join(head) + "\n\nThis recipe already passes your restrictions "
                        "(text-based check of its ingredient lines). No change needed.", new_ingredients=lines)

    evs = {n: _evaluate(ix, i, n, specs, H, prefer) for n in sorted(set(assign.values()))}
    out = list(head)
    for n, e in evs.items():
        kb = KB[n]
        out.append(f"\n### Replacing '{n}'")
        out.append(f"**Role(s) of {n} (general cooking knowledge, not derived from the dataset):** {kb['roles']}")
        out.append(f"**Dish type for indirect evidence:** {e['context']}")
        out.append(f"**Local evidence (dataset only; no external search used).** Window: the {e['n_nb']} most "
                   f"similar recipes; {e['n_nb_free']} of them satisfy your constraints and lack {n}.")
        for k, r in enumerate(e["recs"][:4], 1):
            c = r["c"]
            tag = GRADES[r["grade"]] + (" + CONFLICT" if r["conflict"] else "") + (" (already in this recipe)" if r["in_recipe"] else "")
            out.append(f"{k}. **{c['name']}**: {tag}")
            out.append(f"   - direct: {r['n_direct']} similar recipe(s) use it without {n}"
                       + (f" (e.g. {', '.join('`'+x+'`' for x in r['direct_ids'])})" if r["direct_ids"] else ""))
            if c.get("omit"):
                out.append(f"   - indirect: {r['n_ind']:,} {e['ctx']} lack {n}")
            else:
                rt = (f"; used WITHOUT {n} in {r['rate']:.0%} of the {r['n_ind'] + r['n_with']:,} {e['ctx']} that use it"
                      if r["rate"] is not None else "")
                out.append(f"   - indirect (different dishes, same type): {r['n_ind']:,} {e['ctx']} use it without {n}{rt}"
                           + (f" (e.g. {', '.join('`'+x+'`' for x in r['ind_ids'])})" if r["ind_ids"] else ""))
                if r["conflict"]:
                    out.append(f"   - CONFLICT: it usually appears together with {n}, so it may be an add-on, not a replacement.")
                if r["in_recipe"]:
                    out.append("   - NOTE: this recipe already contains it, so it is not offered as a swap.")
                if r["example"] and r["example"][1]:
                    ex = r["example"]
                    out.append(f"   - dataset example `{ex[0]}`: \"{ex[1]}\""
                               + (f"; method: \"{ex[2]}\"" if ex[2] else ""))
            if c.get("caution"):
                out.append(f"   - caution (external knowledge): {c['caution']}")
        if e["rejected"]:
            out.append("**Rejected candidates:** " + "; ".join(f"{a} ({b})" for a, b in e["rejected"]))
        if e["prefer_note"]:
            out.append(f"**Note:** {e['prefer_note']}")
        if e["blocked"]:
            out.append(f"**Not adapted:** {e['blocked']}")

    chosen = {n: e["chosen"] for n, e in evs.items() if e["chosen"]}
    if not chosen:
        msgs = []
        for e in evs.values():
            if e["blocked"]:
                msgs.append(e["blocked"])
            elif e["alternatives"]:
                msgs.append("You asked for a specific substitute, so I did not swap in a different one. "
                            "Best-supported permitted alternatives: "
                            + "; ".join(f"{r['c']['name']} ({GRADES[r['grade']]}{' + CONFLICT' if r['conflict'] else ''}, "
                                        f"{r['n_direct']} direct)" for r in e["alternatives"])
                            + ". Ask again without a preferred substitute to apply one.")
        out.append("\n**No reliable adaptation supported.** "
                   + (" ".join(msgs) or "The dataset gives no usable evidence for any permitted substitute, "
                                        "so I am not inventing one.") + " The recipe is unchanged.")
        return _res("unsupported", "\n".join(out), new_ingredients=lines)

    new_disp, final, replaced = [], [], 0
    for j, old in enumerate(lines):
        nm = assign.get(j)
        if nm in chosen:
            c = chosen[nm]["c"]
            replaced += 1
            if c.get("omit"):
                new_disp.append(f"~~{old}~~ (omitted)")
            else:
                nl = make_line(c, old)
                final.append(nl)
                new_disp.append(f"{nl}   <- replaces: {old}")
        else:
            final.append(old)
            new_disp.append(old)

    out.append("\n### Chosen substitution")
    confs = []
    for n, ch in chosen.items():
        cf = CONF[max(1, min(3, ch["eff"]))]
        confs.append(cf)
        out.append(f"- {n} -> **{ch['c']['name']}**: confidence **{cf}**")
    if any(c.startswith("LOW") for c in confs):
        out.append("**WARNING: evidence is weak or conflicting. Treat this adaptation as an experiment.**")
    out.append("\n### Updated ingredient list")
    out += [f"- {l}" for l in new_disp]
    out.append("*Amounts for substitutes follow general rule-of-thumb ratios (external knowledge, not verified by "
               "the dataset); see the dataset example lines above for amounts real recipes use.*")

    instr = [l.strip() for l in row["instructions"].split("\n") if l.strip()]
    out.append("\n### Revised instructions")
    n_changed = 0
    for k, ln in enumerate(instr, 1):
        new = ln
        for n, ch in chosen.items():
            c = ch["c"]
            if c.get("omit"):
                if KB[n]["instr"].search(new):
                    new = "[skip any use of the omitted ingredient] " + new
            else:
                new = KB[n]["instr"].sub(lambda m, c=c: f"[{c['short']} in place of {m.group(0)}]", new)
        if new != ln:
            n_changed += 1
            new = "[changed] " + new
        out.append(f"{k}. {new}")
    if n_changed == 0:
        out.append("*No instruction line mentions the replaced ingredient by name; add the substitute where the "
                   "original would have been combined.*")
    else:
        out.append("*Cues tied to the original ingredient (e.g. 'until set', 'beaten', baking time) may no longer "
                   "apply to the substitute; check wording where marked.*")

    out.append("\n### Expected effects (PREDICTIONS from general cooking knowledge, NOT verified outcomes)")
    for n, ch in chosen.items():
        out.append(f"- {ch['c']['name']} for {n}: {ch['c']['effect']}")

    out.append("\n### Verification (computed)")
    remaining = []
    for lbl, s in specs:
        bad = [l for l in final if R.line_violates(l, s)]
        remaining += bad
        out.append(f"- {lbl}: " + (f"STILL VIOLATED by {bad}" if bad else
                                   f"none of the {len(final)} ingredient lines match this rule (text-based)"))
    if unsupported:
        out.append(f"- Lines with no supported replacement rule (unchanged): {unsupported}")
    out.append("*This is a text-based check of ingredient lines. It is not a medical or allergen-safety claim; "
               "hidden sources (e.g. broth, chocolate chips, margarine) cannot be detected from recipe text.*")
    status = "ok" if (not remaining and not unsupported and replaced == len(assign)) else "partial"
    if status == "partial":
        out.append("**PARTIAL adaptation: the recipe still contains items that violate your request (see above).**")
    return _res(status, "\n".join(out), new_ingredients=final, chosen={n: c["c"]["name"] for n, c in chosen.items()},
                confidence=confs, remaining=remaining + unsupported)


if __name__ == "__main__":
    ix = RecipeIndex()

    def pick(query, include=()):
        res, _, _ = ix.search(Filters(query=query, include=include), top_k=1)
        return res["id"].iloc[0] if len(res) else None

    banana, pasta, quiche = pick("banana bread", ("egg",)), pick("pasta cream sauce", ("heavy cream",)), pick("quiche", ("egg",))
    cases = [
        ("1. Banana bread: remove eggs", banana, dict(target="egg", restrictions=("egg",))),
        ("2. Replace cream in a pasta recipe, no dairy", pasta, dict(target="cream", restrictions=("dairy",))),
        ("3. Make the whole pasta recipe dairy-free (no target given)", pasta, dict(restrictions=("dairy",))),
        ("4. Egg-structure dish: remove eggs from a quiche (expect refusal)", quiche, dict(target="egg", restrictions=("egg",))),
        ("5. Unsupported target (flour)", banana, dict(target="flour")),
        ("6. Preferred substitute violates a restriction (yogurt, no dairy)", banana,
         dict(target="egg", restrictions=("egg", "dairy"), prefer="yogurt")),
    ]
    for title, rid, kw in cases:
        print("\n" + "=" * 72 + f"\n>>> {title}\n")
        if rid is None:
            print("(no source recipe found for this case)")
            continue
        print(adapt(ix, rid, **kw)["text"])