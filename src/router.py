"""Rule-based router + session context. Task 1 (search, stats, detail) + Task 2 (matching). No LLM."""
import contextlib
import io
import re
import sys
from dataclasses import replace

from src import matcher as M
from src import restrictions as R
from src import stats as S
from src.normalize import normalize_ingredient, singular
from src.search import STOP, Filters, RecipeIndex
from src.subchat import SubMixin

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
NUM_ALT = "|".join(NUM_WORDS)

# named restriction words -> restriction names (see restrictions.py)
RESTRICTION_WORDS = {"dairy": ["dairy"], "lactose": ["dairy"], "egg": ["egg"],
                     "peanut": ["peanut"], "nut": ["peanut", "tree_nut"],
                     "tree nut": ["tree_nut"], "shellfish": ["shellfish"]}

UNSUPPORTED = re.compile(
    r"\b(calories?|nutrition\w*|protein|carbs?|carbohydrates?|sodium|cholesterol|vitamins?|"
    r"macros?|cook(?:ing)? time|prep(?:aration)? time|how long)\b")
UNSUPPORTED_DIETS = re.compile(r"\b(vegan|vegetarian|gluten|halal|kosher|keto|paleo|diabetic)\b")

SEG = r"[a-z' ,\-]+?"
END = (r"(?=[.?!;]|,\s*(?:which|what|how|show|find|list|give)|"
       r"\b(?:but|with|that|which|at most|no more|under|fewer|less|within|up to|please)\b|$)")
EXC_CUE_RE = re.compile(
    r"\b(?:without|no|exclude|excluding|avoid|avoiding|not containing|free of|"
    r"(?:can ?not|can't|cant|don't|do not) (?:have|eat)|allergic to|allergy to|"
    r"intolerant to|intolerance to)\s+(" + SEG + r")" + END)
FREE_RE = re.compile(r"\b([a-z]+)[- ]free\b")
ALLERGY_RE = re.compile(r"\b([a-z]+)\s+allerg(?:y|ies)\b")
INC_RE = re.compile(r"\b(?:containing|contains?|including|includes?|with|using)\s+(" + SEG + r")" + END)
STEPS_RE = re.compile(r"\b(at most|no more than|max(?:imum)?(?: of)?|within|up to|under|fewer than|"
                      r"less than)\s+(\d+|" + NUM_ALT + r")\s+(?:(?:instruction|cooking|recipe)\s+)?steps?\b")
ID_RE = re.compile(r"\b(?:ar|epi|fn):[^\s,;?)]+")
NUM_REF_RE = re.compile(
    r"(?:#|\b(?:recipe|number|no\.?|result|option)\s*)(\d+)\b|"
    r"\b(?:show|open|display|give me|see)\s+(?:me\s+)?(\d+)\b|"
    r"\b(first|second|third|fourth|fifth|last)\b")
DETAIL_WORD = re.compile(r"\b(show|display|full|ingredients?|instructions?|directions?|method|"
                         r"details?|read|open)\b")

# ---- Task 2 (matching) patterns
SEGQ = r"[a-z0-9' ,\-/]+?"
END_H = (r"(?=[.?!;]|,\s*(?:which|what|how|show|find|list|give|suggest|recommend|no|without|"
         r"exclude|at most|prefer|please)|\b(?:but|no|without|exclude|excluding|suggest|recommend|"
         r"find|show|give|at most|no more|prefer|please)\b|$)")
HAVE_RE = re.compile(r"\b(?:i have|i've got|i got|i only have|i also have|my ingredients (?:are|:)|"
                     r"what can i (?:make|cook) with)\s+(" + SEGQ + r")" + END_H)
ADD_RE = re.compile(r"^(?:please\s+)?(?:also\s+)?add\s+(" + SEGQ +
                    r")(?:\s+to (?:my|the) (?:list|ingredients|pantry))?[.!]?$")
FEW_MISSING_RE = re.compile(r"\b(?:fewest|fewer|least|minimum|minimal|few)\s+"
                            r"(?:additional|extra|missing|other|more)\s+ingredients?\b")
FEW_STEPS_RE = re.compile(r"\b(?:fewer|fewest|least|shorter|shortest|simplest|quickest)\s+"
                          r"(?:instruction\s+)?steps?\b")
K_RE = re.compile(r"\b(\d+|" + NUM_ALT + r")\s+(?:\w+\s+)?recipes?\b")

INTENT_WORDS = {"how", "many", "count", "number", "percentage", "percent", "average", "mean",
                "median", "common", "popular", "ingredient", "ingredients", "fewest", "least",
                "most", "longest", "shortest", "steps", "step", "instruction", "instructions",
                "dataset", "top", "per", "among", "list", "tell", "new", "search", "another",
                "different", "contain", "contains", "containing", "include", "including",
                "use", "using", "have", "has", "s", "t", "re", "ll", "d", "ve", "m", "total",
                "frequent", "frequently", "used", "calculate", "both"}
NOISE = set(STOP) | INTENT_WORDS | set(NUM_WORDS)

HELP = ("I can search recipes (e.g. 'find a penne pasta recipe'), add restrictions "
        "('I cannot have dairy'), answer dataset statistics ('how many recipes contain garlic "
        "and onion?'), match your ingredients ('I have eggs, onions and rice, at most 6 steps'), "
        "adapt a recipe ('replace the cream in recipe 2 without dairy') and show a result "
        "('show 2'). Say 'start over' to reset.")


def _num(x):
    return int(x) if x.isdigit() else NUM_WORDS[x]


def parse(t):
    out = {"restr": set(), "exclude": [], "include": [], "max_steps": None,
           "notices": [], "words": []}
    rest = t

    m = STEPS_RE.search(rest)                      # before exclusions: 'no more than 6 steps'
    if m:
        n = _num(m.group(2))
        out["max_steps"] = n - 1 if m.group(1) in ("under", "fewer than", "less than") else n
        rest = rest.replace(m.group(0), " ")
    elif re.search(r"\b(\d+|" + NUM_ALT + r")\s+(?:\w+\s+){0,2}steps?\b", t) \
            and re.search(r"\b(at most|no more than|max|maximum|within|up to|under|fewer than|less than)\b", t):
        out["notices"].append("A step limit seems to be in your message but I could not read it, "
                              "so NO step limit was applied. Try 'at most 6 steps'.")
        # drop the whole phrase so it is not misparsed as an ingredient or ranking
        rest = re.sub(r"\b(?:at most|no more than|max(?:imum)?(?: of)?|within|up to|under|"
                      r"fewer than|less than)\b(?:\s+\w+){0,4}?\s+steps?\b", " ", rest)

    def take(item):
        item = re.sub(r"\b(?:too|as well|also|please)\b", " ", item)
        item = re.sub(r"\s+", " ", item).strip(" -")
        if not item or UNSUPPORTED_DIETS.search(item):
            return
        key = " ".join(singular(w) for w in item.split())
        if key in RESTRICTION_WORDS:
            out["restr"].update(RESTRICTION_WORDS[key])
        else:
            out["exclude"].append(item)

    for m in list(EXC_CUE_RE.finditer(rest)):
        for item in re.split(r",|\band\b|\bor\b", m.group(1)):
            take(item)
        rest = rest.replace(m.group(0), " ")
    for rx in (FREE_RE, ALLERGY_RE):
        for m in list(rx.finditer(rest)):
            take(m.group(1))
            rest = rest.replace(m.group(0), " ")

    for w in sorted(set(UNSUPPORTED_DIETS.findall(t))):
        out["notices"].append(f"'{w}' is not a rule I can enforce (no ingredient list is defined "
                              f"for it), so it was NOT applied.")

    for m in list(INC_RE.finditer(rest)):
        for item in re.split(r",|\band\b", m.group(1)):
            item = re.sub(r"^(?:both of|both|all|any|some|of|the)\s+", "", item.strip())
            for k in (normalize_ingredient(item) if item else []):
                if k not in out["include"]:
                    out["include"].append(k)
        rest = rest.replace(m.group(0), " ")

    out["words"] = [w for w in re.findall(r"[a-z]+", rest) if w not in NOISE]
    return out


def stat_kind(t):
    t = re.sub(r"\bat most\b", " ", t)    # limit cue, not the ranking word 'most'
    avg = re.search(r"\b(average|mean|median)\b", t)
    if re.search(r"\b(fewest|least|shortest|simplest|lowest|most|longest|highest)\b", t) \
            and re.search(r"\b(steps?|instructions?)\b", t) and not avg:
        return "rank"
    if avg:
        return "step_avg" if re.search(r"\bsteps?\b", t) and "ingredient" not in t else "ingr_avg"
    if "ingredient" in t and re.search(r"\b(common|popular|frequent\w*|most used)\b", t):
        return "common"
    if re.search(r"\b(how many|count|number of|percentage|percent|what share|total)\b", t):
        return "count"
    return None


def _k(t, default):
    m = re.search(r"\btop\s+(\d+)", t) or re.search(r"\b(\d+)\s+(?:recipes|ingredients)\b", t)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(" + NUM_ALT + r")\b(?!\s+steps?)", t)
    return NUM_WORDS[m.group(1)] if m else default


def _prefs(t):
    t2 = STEPS_RE.sub(" ", t)
    return bool(FEW_MISSING_RE.search(t2)), bool(FEW_STEPS_RE.search(t2))


def _filters_line(f):
    q = f"search text '{f.query}'; " if f.query else ""
    return f"{q}{S.describe(f)}"


def _evidence(row, f):
    lines, ev = row["ingredients"], []
    for name in f.restrictions:
        bad = R.offending_lines(lines, name)
        ev.append(f"{name} check: scanned {len(lines)} ingredient lines, no {name} terms found"
                  if not bad else f"WARNING {name}: {bad[:2]}")
    for term in f.exclude:
        keys = tuple(normalize_ingredient(term) or [term.lower()])
        bad = R.offending_lines(lines, R.make_spec(keys))
        ev.append(f"excludes '{term}': not found in {len(lines)} lines" if not bad
                  else f"WARNING '{term}': {bad[:2]}")
    for term in f.include:
        for k in (normalize_ingredient(term) or [term.lower()]):
            hit = [l for l in lines if k in R.norm_text(l)]
            ev.append(f"has '{k}': \"{hit[0]}\"" if hit else f"has '{k}' (via normalized name)")
    return ev


class Bot(SubMixin):
    def __init__(self, ix):
        self.ix = ix
        self.by_id = ix.df.set_index("id", drop=False)
        self.f = Filters()          # session filters; restrictions/exclude are shared by search+match
        self.stat_f = None          # active STATS filters
        self.m = None               # active MATCH request state (dict)
        self.last_kind = None       # "search" | "stats" | "match"
        self.last = []  
        self.focus = None           # recipe ID most recently opened or adapted ("this recipe")
        self.sub = None             # active substitution request (dict)
        self._parse = parse            # ids shown in the last result list

    # ------------------------------------------------------------ main entry
    def reply(self, text):
        t = text.lower().replace("\u2019", "'").strip()
        if not t:
            return HELP
        if UNSUPPORTED.search(t):
            return ("**Not available in this dataset.** Recipes contain only a title, ingredient "
                    "lines and instruction text, so I can't report nutrition values or cooking "
                    "times, and I won't estimate them. I can still search by dish or ingredient, "
                    "count and rank recipes, match your ingredients, or show a recipe's "
                    "ingredients and instructions.")
        if re.search(r"\b(reset|start over|new session|clear (?:all|everything|filters|restrictions))\b", t):
            if "restriction" in t:
                self.f = replace(self.f, restrictions=(), exclude=())
                return "Restrictions and exclusions cleared. Search text and other filters are unchanged."
            self.f, self.stat_f, self.m = Filters(), None, None
            self.last_kind, self.last = None, []
            return "Session reset: all filters cleared."
        s = self._sub_route(text, t)
        if s:
            return s        
        d = self._detail(text, t)
        if d:
            return d
        if HAVE_RE.search(t):
            return self._match_new(t)
        if self.last_kind == "match" and self.m:
            r = self._match_followup(t)
            if r:
                return r
        p = parse(t)
        kind = stat_kind(STEPS_RE.sub(" ", t))   # 'at most 4 steps' is a limit, not a ranking
        return self._stats(kind, t, p) if kind else self._search(p)

    # ------------------------------------------------------------ helpers
    def _check_new_exclusions(self, terms):
        notes = []
        for term in terms:
            keys = tuple(normalize_ingredient(term) or [term.lower()])
            if not self.ix._violators(("exc", keys), R.make_spec(keys)).any():
                notes.append(f"No recipe in the dataset has an ingredient line matching "
                             f"'{term}', so that exclusion has no effect (check the spelling).")
        return notes

    def _bad_keys(self, keys):
        return [k for k in keys if not self.ix._has_key(k).any()]

    def _merge_constraints(self, p):
        self.f = replace(self.f,
                         restrictions=tuple(sorted(set(self.f.restrictions) | p["restr"])),
                         exclude=tuple(dict.fromkeys(self.f.exclude + tuple(p["exclude"]))))

    # ------------------------------------------------------------ detail view
    def _detail(self, orig, t):
        row = None
        m = ID_RE.search(orig)
        if m:
            rid = m.group(0)
            if rid not in self.by_id.index:
                return f"I could not find a recipe with ID `{rid}`."
            row = self.by_id.loc[rid]
        elif DETAIL_WORD.search(t):
            m = NUM_REF_RE.search(t)
            if not m:
                return None
            if not self.last:
                return "No results are on screen yet. Search for something first."
            tok = m.group(1) or m.group(2) or m.group(3)
            idx = len(self.last) if tok == "last" else (ORDINALS.get(tok) or int(tok))
            if not 1 <= idx <= len(self.last):
                return f"The last list had {len(self.last)} recipes; pick a number from 1 to {len(self.last)}."
            row = self.by_id.loc[self.last[idx - 1]]
        else:
            return None
        self.focus = row["id"]        
        want_ing = bool(re.search(r"ingredient", t))
        want_ins = bool(re.search(r"instruction|direction|method|\bsteps?\b", t))
        both = want_ing == want_ins
        out = [f"**{row['title']}**  (`{row['id']}`, source: {row['source']})"]
        if both or want_ing:
            note = " (website artifact 'ADVERTISEMENT' removed)" if row["source"] == "ar" else ""
            out.append(f"\n*Ingredients ({len(row['ingredients'])} lines){note}:*")
            out += [f"- {l}" for l in row["ingredients"]]
        if both or want_ins:
            lines = [l.strip() for l in row["instructions"].split("\n") if l.strip()]
            rel = "" if row["steps_reliable"] else " (single paragraph: step count not reliable)"
            out.append(f"\n*Instructions (original text, {len(lines)} line(s)){rel}:*")
            out += [f"{i}. {l}" for i, l in enumerate(lines, 1)]
        return "\n".join(out)

    # ------------------------------------------------------------ Task 2: matching
    def _match_new(self, t):
        m = HAVE_RE.search(t)
        rest = t.replace(m.group(0), " ")
        p = parse(rest)
        keys, qty = M.parse_have(m.group(1))
        also = bool(self.m) and bool(re.search(r"\b(also|plus)\b", t))
        if also:
            keys = tuple(dict.fromkeys(self.m["have"] + keys))
            qty = self.m["qty"] + qty
        if not keys:
            return f"I could not find ingredient names in '{m.group(1).strip()}'. Nothing was matched."
        fm, fs = _prefs(t)
        km = K_RE.search(t)
        k = max(1, min(10, _num(km.group(1)))) if km else (self.m["k"] if also else 5)
        carried = bool(self.f.restrictions or self.f.exclude) and not also
        self._merge_constraints(p)
        self.m = {"have": tuple(keys), "qty": tuple(qty), "k": k,
                  "max_steps": p["max_steps"] if p["max_steps"] is not None else (self.m["max_steps"] if also else None),
                  "few_missing": fm or (also and self.m["few_missing"]),
                  "few_steps": fs or (also and self.m["few_steps"])}
        self.last_kind = "match"
        notes = list(p["notices"]) + self._check_new_exclusions(p["exclude"])
        if carried:
            notes.append("Earlier restrictions/exclusions were carried over (see Hard constraints).")
        return self._render_match(notes)

    def _match_followup(self, t):
        m = ADD_RE.match(t)
        if m:
            keys, qty = M.parse_have(m.group(1))
            if not keys:
                return None
            self.m["have"] = tuple(dict.fromkeys(self.m["have"] + keys))
            self.m["qty"] = self.m["qty"] + qty
            return self._render_match([f"Added {', '.join(keys)} to your ingredients."])
        fm, fs = _prefs(t)
        t2 = FEW_STEPS_RE.sub(" ", FEW_MISSING_RE.sub(" ", t))
        t2 = re.sub(r"\bprefer\w*\b", " ", t2)
        p = parse(t2)
        if p["words"] or p["include"]:
            return None
        if stat_kind(STEPS_RE.sub(" ", t)) and not (fm or fs):
            return None
        if not (p["restr"] or p["exclude"] or p["max_steps"] is not None or fm or fs):
            return None
        self._merge_constraints(p)
        if p["max_steps"] is not None:
            self.m["max_steps"] = p["max_steps"]
        self.m["few_missing"] = self.m["few_missing"] or fm
        self.m["few_steps"] = self.m["few_steps"] or fs
        notes = list(p["notices"]) + self._check_new_exclusions(p["exclude"])
        return self._render_match(notes, head="Updated the ingredient-matching request.\n\n")

    def _render_match(self, notes, head=""):
        m = self.m
        req = M.MatchRequest(have=m["have"], quantities=m["qty"], restrictions=self.f.restrictions,
                             exclude=self.f.exclude, max_steps=m["max_steps"],
                             prefer_few_missing=m["few_missing"], prefer_few_steps=m["few_steps"],
                             k=m["k"])
        out = M.run(self.ix, req)
        with contextlib.redirect_stdout(io.StringIO()):
            M.check_hard(self.ix, out, req)             # raises AssertionError on any violation
        self.last = [r["id"] for r in out["results"]]
        text = head + M.format_output(out, req)
        if out["results"]:
            text += ("\n\n*Verification: every hard constraint was re-checked on each returned "
                     "recipe: OK. Say 'show 2' for result 2's full text.*")
        return text + "".join(f"\n\n*Note: {n}*" for n in notes)

    # ------------------------------------------------------------ search
    def _search(self, p):
        old, notes = self.f, list(p["notices"])
        restr = tuple(sorted(set(old.restrictions) | p["restr"]))
        exc = tuple(dict.fromkeys(old.exclude + tuple(p["exclude"])))
        notes += self._check_new_exclusions(p["exclude"])
        query = " ".join(p["words"])

        vocab = self.ix.vec.vocabulary_
        unknown = [w for w in query.split() if len(w) > 1 and w not in vocab]
        if unknown:
            return (f"**No matching recipe found.** The word(s) {unknown} do not appear in the recipe "
                    f"vocabulary (fewer than 3 recipes use them), so I did not search for the remaining "
                    f"words. Try a different dish or ingredient name.")

        constraints_only = not query and not p["include"]
        if constraints_only:
            if not (p["restr"] or p["exclude"] or p["max_steps"] is not None):
                return HELP
            if not (old.query or old.include):
                return "Tell me what to search for first (e.g. 'find a penne pasta recipe'), then add restrictions."
            f = replace(old, restrictions=restr, exclude=exc,
                        max_steps=p["max_steps"] if p["max_steps"] is not None else old.max_steps)
            head = "Refined the active search."
        else:
            bad = self._bad_keys(p["include"])
            if bad:
                return f"No recipe in the dataset contains the ingredient name(s) {bad}. Nothing was searched."
            f = Filters(query=query, include=tuple(p["include"]), exclude=exc,
                        restrictions=restr, max_steps=p["max_steps"])
            head = "New search."
            if old.restrictions or old.exclude:
                head += " Earlier restrictions/exclusions were carried over."
        self.f, self.last_kind = f, "search"
        res, n_c, n_m = self.ix.search(f, top_k=5)
        out = [f"{head}\n**Active filters:** {_filters_line(f)}",
               f"**Recipes passing the hard filters:** {n_c:,}; also matching the search text: {n_m:,}"]
        if not len(res):
            self.last = []
            out.append("\n**No matching recipe found.** I did not relax any constraint. You can say "
                       "'clear restrictions' or 'start over', or search for something else.")
        else:
            self.last = list(res["id"])
            out.append("")
            for i, (_, r) in enumerate(res.iterrows(), 1):
                out.append(f"{i}. **{r['title']}**  `{r['id']}`  (score {r['score']:.3f}, {r['n_steps']} step(s))")
                shown = r["ingredients"][:5]
                out.append("   - ingredients: " + "; ".join(shown)
                           + (f"; ... (+{len(r['ingredients']) - 5} more)" if len(r["ingredients"]) > 5 else ""))
                out += [f"   - evidence: {e}" for e in _evidence(r, f)]
            if f.restrictions or f.exclude:
                out.append("\n*Restriction checks are text-based on the ingredient lines; they are not a "
                           "medical or allergen-safety guarantee.*")
            out.append("*Say 'show 2' for the full ingredients and instructions of result 2.*")
        out += [f"\n*Note: {n}*" for n in notes]
        return "\n".join(out)

    # ------------------------------------------------------------ statistics
    def _stats(self, kind, t, p):
        notes = list(p["notices"])
        keys = list(p["include"])
        if p["words"]:                                    # leftover words must name an ingredient
            extra = normalize_ingredient(" ".join(p["words"])) or []
            if not extra:
                return f"I could not interpret '{' '.join(p['words'])}' as an ingredient. Nothing was computed."
            keys += [k for k in extra if k not in keys]
        bad = self._bad_keys(keys)
        if bad:
            return f"No recipe in the dataset contains the ingredient name(s) {bad}. Nothing was computed."
        notes += self._check_new_exclusions(p["exclude"])
        if keys:
            f = Filters(include=tuple(keys), exclude=tuple(p["exclude"]),
                        restrictions=tuple(sorted(p["restr"])), max_steps=p["max_steps"])
        else:
            base = self.stat_f if (self.last_kind == "stats" and self.stat_f) else self.f
            if base.query:
                notes.append(f"Your search text '{base.query}' only ranks search results; it is not a filter, "
                             f"so this statistic covers every recipe passing the filters above. For a specific "
                             f"ingredient, ask e.g. 'recipes containing {base.query.split()[0]}'.")
            f = replace(base, query="",
                        exclude=tuple(dict.fromkeys(base.exclude + tuple(p["exclude"]))),
                        restrictions=tuple(sorted(set(base.restrictions) | p["restr"])),
                        max_steps=p["max_steps"] if p["max_steps"] is not None else base.max_steps)
        self.stat_f, self.last_kind = f, "stats"

        if kind == "count":
            out = S.count(self.ix, f)["text"]
        elif kind == "ingr_avg":
            out = S.ingredient_counts(self.ix, f)["text"]
        elif kind == "common":
            out = S.common_ingredients(self.ix, f, top=_k(t, 10))["text"]
        elif kind == "step_avg":
            sub = S._subset(self.ix, f)
            rel = sub[sub["steps_reliable"]]
            if rel.empty:
                out = f"**Filters:** {S.describe(f)}\nNo recipes with reliable step counts."
            else:
                out = (f"**Filters:** {S.describe(f)}\n**Recipes in filtered set:** {len(sub):,}; used: "
                       f"{len(rel):,} (single-paragraph recipes excluded)\n"
                       f"**Steps per recipe:** mean {rel['n_steps'].mean():.2f}, median {rel['n_steps'].median():.1f}\n"
                       f"**Calculation:** pandas mean/median of n_steps (non-empty instruction lines).")
        else:  # rank
            fewest = not re.search(r"\b(most|longest|highest)\b", STEPS_RE.sub(" ", t))
            r = S.rank_steps(self.ix, f, k=_k(t, 5), fewest=fewest)
            out = r["text"] + "\n"
            self.last = list(r["table"]["id"])
            for i, (_, row) in enumerate(r["table"].iterrows(), 1):
                out += (f"\n{i}. **{row['title']}**  `{row['id']}`  "
                        f"({row['n_steps']} step(s), {row['n_sentences']} sentence(s))")
            out += "\n\n*Say 'show 2' for result 2's full text.*"
        return out + "".join(f"\n\n*Note: {n}*" for n in notes)


DEMO = [
    "Find a penne pasta recipe",
    "I cannot have dairy",
    "show 1",
    "How many recipes contain both garlic and onion? What percentage of the dataset is that?",
    "Among recipes containing tomato, which five have the fewest instruction steps?",
    "What's the average and median ingredient count?",
    "How many calories are in result 1?",
    "start over",
    "Find chicken with garlic and lemon juice, no eggs, at most 4 steps",
    "Find unicorn dust cake",
    "Show me gluten-free pasta",
]

DEMO_MATCH = [
    "I have eggs, onions, tomatoes, and rice. Suggest five recipes using as many of these as possible, "
    "with no peanuts and at most six instruction steps. Prefer recipes that need the fewest additional ingredients.",
    "Exclude eggs too",
    "show 1",
    "I also have garlic",
    "Prefer fewer steps",
    "start over",
    "I have unicorn horn and moondust",
    "I have rice and tomatoes, at most 0 steps",
    "How many recipes contain both garlic and onion?",
]

DEMO_SUB = [
    "Take this banana bread recipe and remove eggs. Use only ingredients that appear in the dataset. "
    "What replacements have evidence from related baked recipes, and how might the texture change?",
    "Use applesauce instead",
    "Also no dairy",
    "start over",
    "Find pasta recipes containing heavy cream",
    "Replace the cream in recipe 1 without dairy. Prefer examples from recipes already in the database.",
    "show 1",
    "Replace the flour in this recipe",
    "start over",
    "Take this quiche recipe and remove eggs",
]

if __name__ == "__main__":
    ix = RecipeIndex()
    if "--chat" in sys.argv:
        from src.converse import ConversationalBot
        bot = ConversationalBot(ix)
        if not bot.key:
            print("GEMINI_API_KEY not set - running in rule-based mode.")
    else:
        bot = Bot(ix)
    flags = {"--demo": DEMO, "--demo-match": DEMO_MATCH, "--demo-sub": DEMO_SUB}
    chosen = next((v for k, v in flags.items() if k in sys.argv), None)
    if chosen:
        for q in chosen:
            print("\n" + "=" * 70 + "\n>>> " + q + "\n")
            print(bot.reply(q))
    else:
        print("Recipe chatbot (type 'quit' to exit).")
        while True:
            q = input("\nyou> ").strip()
            if q.lower() in {"quit", "exit"}:
                break
            print("\n" + bot.reply(q))