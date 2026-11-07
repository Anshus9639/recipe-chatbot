"""Hard dietary restrictions, matched as whole words in the full ingredient lines.
TEXT-BASED ONLY: this is NOT a medical or allergen-safety guarantee (hidden dairy in
'chocolate chips', 'margarine', 'broth' etc. cannot be detected from recipe text)."""
import re

_HYPHEN = re.compile(r"[-\u2013]")
_WS = re.compile(r"\s+")


def norm_text(s):
    return _WS.sub(" ", _HYPHEN.sub(" ", str(s).lower())).strip()


RESTRICTIONS = {
    "dairy": {
        "terms": ["milk", "buttermilk", "butter", "cream", "half and half", "cheese",
                  "yogurt", "yoghurt", "ghee", "whey", "casein", "custard", "kefir",
                  "parmesan", "mozzarella", "cheddar", "ricotta", "mascarpone", "feta",
                  "gouda", "provolone", "brie", "gruyere", "romano", "paneer",
                  "creamer", "buttercream"],
        "safe": ["peanut butter", "almond butter", "cashew butter", "nut butter",
                 "cocoa butter", "shea butter", "apple butter", "butter bean",
                 "coconut milk", "almond milk", "soy milk", "oat milk", "rice milk",
                 "cashew milk", "hemp milk", "coconut cream", "cream of coconut",
                 "cream of tartar"],
    },
    "egg": {
        "terms": ["egg", "eggnog", "mayonnaise", "mayo", "meringue"],
        "safe": [],
    },
    "peanut": {
        "terms": ["peanut", "groundnut"],
        "safe": [],
    },
    "tree_nut": {
        "terms": ["almond", "walnut", "pecan", "cashew", "pistachio", "hazelnut",
                  "macadamia", "brazil nut", "pine nut", "nut", "nutella", "marzipan",
                  "praline"],
        "safe": [],
    },
    "shellfish": {
        "terms": ["shrimp", "prawn", "crab", "lobster", "crawfish", "crayfish", "clam",
                  "oyster", "mussel", "scallop", "shellfish", "squid", "calamari",
                  "octopus"],
        "safe": [],
    },
}


def _pattern(words):
    ws = sorted({norm_text(w) for w in words}, key=len, reverse=True)
    return r"\b(?:" + "|".join(re.escape(w) for w in ws) + r")(?:e?s)?\b"


def make_spec(terms, safe=()):
    """Spec = (main_regex_string, safe_regex_string_or_None)."""
    return (_pattern(terms), _pattern(safe) if safe else None)


SPECS = {n: make_spec(d["terms"], d["safe"]) for n, d in RESTRICTIONS.items()}


def line_violates(line, spec):
    main, safe = spec
    t = norm_text(line)
    if safe:
        t = re.sub(safe, " ", t)
    return re.search(main, t) is not None


def offending_lines(lines, name_or_spec):
    spec = SPECS[name_or_spec] if isinstance(name_or_spec, str) else name_or_spec
    return [l for l in lines if line_violates(l, spec)]


def text_mask(texts, spec):
    """texts: pandas Series of norm_text'd, joined ingredient lines -> numpy bool array."""
    main, safe = spec
    if safe:
        texts = texts.str.replace(safe, " ", regex=True)
    return texts.str.contains(main, regex=True).to_numpy()


if __name__ == "__main__":
    CASES = [
        ("dairy", "1 cup butter", True), ("dairy", "1/2 cup peanut butter", False),
        ("dairy", "1 cup coconut milk", False), ("dairy", "1 cup whole milk", True),
        ("dairy", "1 teaspoon cream of tartar", False), ("dairy", "1/2 cup half-and-half", True),
        ("dairy", "1 cup grated Parmesan cheese", True), ("dairy", "1 butternut squash", False),
        ("dairy", "1 cup almond milk", False), ("dairy", "1 can evaporated milk", True),
        ("dairy", "1 cup heavy cream", True), ("dairy", "2 tablespoons butter or margarine", True),
        ("egg", "2 large eggs", True), ("egg", "1 eggplant", False),
        ("tree_nut", "1/2 cup chopped pecans", True), ("shellfish", "1 lb shrimp, peeled", True),
        ("peanut", "1/4 cup peanut oil", True), ("peanut", "1/4 cup olive oil", False),
    ]
    bad = 0
    for name, line, want in CASES:
        got = line_violates(line, SPECS[name])
        bad += got != want
        print(("OK " if got == want else "BAD"), f"{name:9} {line!r:45} -> {got}")
    print(f"\n{len(CASES) - bad}/{len(CASES)} passed")