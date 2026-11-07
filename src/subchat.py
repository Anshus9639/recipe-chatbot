"""Chat glue for Task 3 (substitution), mixed into router.Bot.
Needs on self: ix, by_id, f, last, last_kind, focus, sub, _parse, _merge_constraints,
_check_new_exclusions."""
import re

from src import restrictions as R
from src import substitution as SB
from src.normalize import normalize_ingredient, singular
from src.search import STOP, Filters

ORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
ID_RE = re.compile(r"\b(?:ar|epi|fn):[^\s,;?)]+")
REMOVE_VERBS = r"(?:remove|omit|leave\s+out|take\s+out|get\s+rid\s+of|eliminate)"
STRONG_SUB = re.compile(r"\b(?:replace|substitut\w*|swap|adapt)\b")
WEAK_SUB = re.compile(r"\b" + REMOVE_VERBS + r"\b|\bmake\b.*\b[a-z]+[- ]free\b|"
                      r"\b[a-z]+[- ]free\s+(?:version|variant|adaptation)\b")
TARGET_RE = re.compile(
    r"\b(?:replace|substitut(?:e|ing)(?:\s+for)?|swap(?:\s+out)?|" + REMOVE_VERBS + r")\s+"
    r"(?:the\s+|all\s+|any\s+|my\s+)?([a-z][a-z ]*?)"
    r"(?=\s+(?:in|from|with|for|using|and|but|without|so|because|since|of)\b|[,.?!;]|$)")
PREFER_RE = re.compile(r"\b(?:with|using)\s+([a-z][a-z ]*?)"
                       r"(?=\s+(?:in|from|for|and|but|without|instead)\b|[,.?!;]|$)")
NUM_REF = re.compile(r"(?:#|\b(?:recipe|number|no\.?|result|option)\s*)(\d+)\b")
ORD_REF = re.compile(r"\b(first|second|third|fourth|fifth|last)\s+(?:one|recipe|result)\b")
THIS_REF = re.compile(r"\b(?:this|that|the)\s+(?:[a-z'-]+\s+){0,3}recipe\b|"
                      r"\b(?:this|that)\s+one\b|\bmake it\b|\bin it\b")
DISH_RE = re.compile(r"\b(?:this|that|the|a|my)\s+((?:[a-z'-]+\s+){1,3}?)recipe\b")
DISH2_RE = re.compile(r"\b(?:in|from)\s+(?:the\s+|my\s+|a\s+)?([a-z][a-z' -]*?)"
                      r"(?=\s+(?:with|without|using|and|but|so)\b|[,.?!;]|$)")
BAD_PREFER = {"something", "anything", "free", "only", "ingredient", "ingredients", "dataset",
              "database", "evidence", "recipe", "recipes", "dairy", "egg", "eggs"}
PRONOUNS = {"it", "this", "that", "them", "one"}


def _clean_prefer(s):
    s = re.sub(r"\b(?:too|also|as well|please|instead)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s or any(w in BAD_PREFER for w in s.split()):
        return None
    return s


class SubMixin:
    # ------------------------------------------------------------ routing
    def _sub_route(self, orig, t):
        if self.last_kind == "adapt" and self.sub:
            r = self._sub_followup(t)
            if r:
                return r
        if STRONG_SUB.search(t) or (WEAK_SUB.search(t) and self._explicit_ref(orig, t)):
            return self._sub_new(orig, t)
        return None

    @staticmethod
    def _explicit_ref(orig, t):
        return bool(ID_RE.search(orig) or NUM_REF.search(t) or ORD_REF.search(t) or THIS_REF.search(t))

    # ------------------------------------------------------------ new request
    def _sub_new(self, orig, t):
        p = self._parse(t)
        notes = list(p["notices"]) + self._check_new_exclusions(p["exclude"])
        tm = TARGET_RE.search(t)
        target = None
        if tm:
            target = re.sub(r"\s+", " ", re.sub(r"\b(?:too|also|as well|please)\b", " ", tm.group(1))).strip()
            if not target or target in PRONOUNS:
                target = None
        name = SB.ALIASES.get(" ".join(singular(w) for w in target.split())) if target else None
        removal = bool(tm) and bool(re.match(REMOVE_VERBS, tm.group(0)))
        extra = {"egg"} if (removal and name == "egg") else set()    # one-off, not stored in the session
        pm = PREFER_RE.search(t)
        prefer = _clean_prefer(pm.group(1)) if pm else None
        self._merge_constraints(p)                                   # stated restrictions persist
        restr = tuple(sorted(set(self.f.restrictions) | extra))
        rid, header = self._sub_resolve(orig, t, target, name, restr)
        if rid is None:
            return header
        self.sub = {"id": rid, "target": target, "prefer": prefer, "extra": extra}
        return self._sub_run(header, notes)

    # ------------------------------------------------------------ follow-ups
    def _sub_followup(self, t):
        s = self.sub
        m = re.match(r"^(?:please\s+)?(?:use|try|go with|what about|how about)\s+(.+?)"
                     r"(?:\s+instead)?\s*[.?!]?$", t)
        if m:
            pf = _clean_prefer(m.group(1))
            if pf:
                s["prefer"] = pf
                return self._sub_run("", [])
            return None
        p = self._parse(t)
        if (p["restr"] or p["exclude"]) and not p["words"] and not p["include"]:
            notes = list(p["notices"]) + self._check_new_exclusions(p["exclude"])
            self._merge_constraints(p)
            s["target"], s["prefer"] = None, None
            return self._sub_run("*Re-ran the adaptation for every ingredient line that violates your "
                                 "restrictions and has a supported rule.*\n\n", notes)
        return None

    # ------------------------------------------------------------ run
    def _sub_run(self, header="", notes=()):
        s = self.sub
        restr = tuple(sorted(set(self.f.restrictions) | s["extra"]))
        res = SB.adapt(self.ix, s["id"], target=s["target"], restrictions=restr,
                       exclude=self.f.exclude, prefer=s["prefer"])
        self.focus, self.last, self.last_kind = s["id"], [s["id"]], "adapt"
        text = header + res["text"]
        if res["status"] == "partial":
            text += ("\n\n*To satisfy every restriction, say e.g. 'make it dairy-free' (adapts every "
                     "violating line that has a supported rule).*")
        text += "\n\n*Say 'show 1' for the original recipe.*"
        return text + "".join(f"\n\n*Note: {n}*" for n in notes)

    # ------------------------------------------------------------ find the recipe
    def _sub_resolve(self, orig, t, target, name, restr):
        m = ID_RE.search(orig)
        if m:
            rid = m.group(0)
            if rid in self.by_id.index:
                return rid, ""
            return None, f"I could not find a recipe with ID `{rid}`."
        idx = None
        m = NUM_REF.search(t)
        if m:
            idx = int(m.group(1))
        else:
            m = ORD_REF.search(t)
            if m:
                idx = ORDS.get(m.group(1), len(self.last))
        if idx is not None:
            if not self.last:
                return None, "No results are on screen yet. Search for a recipe first, or give a recipe ID."
            if not 1 <= idx <= len(self.last):
                return None, f"The last list had {len(self.last)} recipe(s); pick a number from 1 to {len(self.last)}."
            return self.last[idx - 1], ""
        dish = self._sub_dish(t)
        if dish:
            return self._sub_by_title(dish, target, name, restr)
        if self.focus:
            return self.focus, ""
        return None, ("Which recipe? Say 'recipe 2' (after a search), paste its ID, or name it, "
                      "e.g. 'remove eggs from this banana bread recipe'.")

    @staticmethod
    def _sub_dish(t):
        m = DISH_RE.search(t)
        cand = m.group(1) if m else None
        if not cand:
            m = DISH2_RE.search(t)
            cand = m.group(1) if m else None
            if cand and (re.search(r"\b(?:recipe|result|option|number)\b", cand)
                         or re.match(r"(?:this|that|it)\b", cand)):
                cand = None
        words = [w for w in (cand or "").split() if w not in STOP and w not in {"original", "same", "new"}]
        return " ".join(words)

    def _sub_by_title(self, dish, target, name, restr):
        vocab = self.ix.vec.vocabulary_
        unknown = [w for w in dish.split() if len(w) > 1 and w not in vocab]
        if unknown:
            return None, (f"**No matching recipe found.** The word(s) {unknown} are not in the recipe "
                          f"vocabulary, so I could not locate '{dish}'.")
        specs = [R.SPECS[n] for n in restr] + \
                [R.make_spec(tuple(normalize_ingredient(x) or [x.lower()])) for x in self.f.exclude]
        res, _, _ = self.ix.search(Filters(query=dish), top_k=40)
        for _, r in res.iterrows():
            row = self.by_id.loc[r["id"]]
            lines = row["ingredients"]
            if name:
                ok = any(SB.KB[name]["plain"](k) for l in lines for k in normalize_ingredient(l))
                what = f"contains {name}"
            elif target:
                ok, what = True, "matches"
            else:
                ok = any(R.line_violates(l, s) for l in lines for s in specs)
                what = "violates your restrictions"
            if ok:
                return r["id"], (f"*Recipe chosen by title search for '{dish}': the best-ranked match that "
                                 f"{what}: **{row['title'].strip()}** (`{row['id']}`). If you meant another "
                                 f"recipe, give its ID.*\n\n")
        return None, f"None of the top matches for '{dish}' fit the request, so nothing was adapted."