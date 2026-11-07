"""Ingredient-line normalization.

Turns '2 (14.5 ounce) cans diced tomatoes, drained' into ['tomato'].

RULES (document these in the README):
 1. Lowercase; drop parentheses, quantities, fractions, punctuation.
 2. Drop units (cup, tsp, can...), prep words (chopped, diced...) and size/quality
    words (large, fresh...). Forms that change the product are KEPT:
    'ground beef' != 'beef', 'garlic powder' != 'garlic', 'peanut butter' != 'butter',
    'egg white' != 'egg'.
 3. Singularize each word (eggs -> egg, tomatoes -> tomato).
 4. 'A or B' keeps only the first option (limitation: loses the alternative).
 5. Comma segments: use the first segment that still has content
    ('skinless, boneless chicken breast' -> 'chicken breast').
 6. Section headings like 'For the sauce:' are skipped.
 7. 'salt and pepper' style lines are split into separate ingredients, but only
    when every part is in SPLIT_OK (so 'mac and cheese' is never split).
 8. A small synonym table merges names that are the same product for matching.
"""
import re

UNITS = {
    "teaspoon", "tsp", "tablespoon", "tbsp", "cup", "c", "ounce", "oz", "pound", "lb",
    "gram", "g", "kg", "ml", "l", "liter", "litre", "quart", "pint", "gallon", "pinch",
    "dash", "can", "package", "pkg", "jar", "bottle", "slice", "piece", "sprig", "bunch",
    "head", "stalk", "handful", "fluid", "fl", "box", "bag", "container", "carton",
    "envelope", "drop", "splash", "inch", "cube", "tin", "packet", "tub",
}
DESCRIPTORS = {
    "chopped", "minced", "diced", "sliced", "grated", "shredded", "crushed", "melted",
    "softened", "beaten", "peeled", "cored", "seeded", "cubed", "halved", "quartered",
    "drained", "rinsed", "thinly", "finely", "coarsely", "roughly", "freshly", "fresh",
    "large", "small", "medium", "big", "extra", "virgin", "boneless", "skinless", "ripe",
    "packed", "firmly", "heaping", "level", "pure", "unsalted", "salted", "divided",
    "optional", "more", "additional", "plus", "about", "approximately", "chilled",
    "temperature", "room", "condensed", "half", "lightly", "well", "taste",
    "a", "an", "the",
}
DROP = UNITS | DESCRIPTORS

KEEP_S = {"molasses", "grits", "swiss", "couscous", "asparagus", "hummus", "citrus",
          "lemongrass", "watercress", "cress", "bass"}
IRREGULAR = {"leaves": "leaf", "halves": "half", "loaves": "loaf", "knives": "knife"}

SYNONYMS = {
    "ground black pepper": "black pepper", "pepper": "black pepper",
    "peppercorn": "black pepper",
    "scallion": "green onion", "spring onion": "green onion",
    "white sugar": "sugar", "granulated sugar": "sugar",
    "confectioner sugar": "powdered sugar", "icing sugar": "powdered sugar",
    "kosher salt": "salt", "sea salt": "salt", "table salt": "salt", "coarse salt": "salt",
    "all purpose flour": "flour", "plain flour": "flour",
    "vanilla": "vanilla extract",
    "garbanzo bean": "chickpea", "aubergine": "eggplant", "courgette": "zucchini",
    "capsicum": "bell pepper",
        "unsweetened cocoa powder": "cocoa powder", "unsweetened cocoa": "cocoa powder",
    "cocoa": "cocoa powder",
    "ground cinnamon": "cinnamon", "ground nutmeg": "nutmeg",
    "ground pepper": "black pepper",
}
SPLIT_OK = {"salt", "black pepper", "garlic", "onion", "sugar", "cinnamon", "nutmeg",
            "butter", "flour", "oil"}

HEAD_NOUNS = {"juice", "oil", "broth", "stock", "vinegar", "cheese", "flour", "sauce"}

TRAIL_RE = re.compile(
    r"\b(?:to taste|for (?:garnish|serving|frying|dusting|greasing|decoration|"
    r"sprinkling|topping|the pan|brushing)|as needed|or more|if desired|divided)\b.*"
)
NUM_RANGE_RE = re.compile(r"[\d/.]+\s+(?:or|to)\s+[\d/.]+")
NON_ALPHA_RE = re.compile(r"[^a-z_ ]")
QTY_RE = re.compile(r"[\d¼½¾⅓⅔⅛⅜⅝⅞/.]+")
LEAD_TRAIL = {"of", "and", "or", "with"}


def singular(t):
    if t in IRREGULAR:
        return IRREGULAR[t]
    if t in KEEP_S or len(t) <= 3:
        return t
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("oes"):
        return t[:-2]
    if t.endswith(("ches", "shes", "xes", "sses")):
        return t[:-2]
    if t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def _canon(p):
    p = p.strip().replace("_", " ")
    return SYNONYMS.get(p, p)


def _clean_tokens(text):
    text = QTY_RE.sub(" ", text.replace("'", "").replace("-", " "))
    text = NON_ALPHA_RE.sub(" ", text)
    tokens = [singular(t) for t in text.split()]
    garlic = "garlic" in tokens
    buttery = any(t in ("butter", "margarine") for t in tokens)
    kept = []
    for t in tokens:
        if t in DROP:
            continue
        if t == "clove" and garlic:               # 'garlic cloves' -> garlic, 'ground cloves' stays
            continue
        if t == "stick" and buttery:              # 'butter stick' -> butter
            continue
        kept.append(t)
    while kept and kept[0] in LEAD_TRAIL:
        kept.pop(0)
    while kept and kept[-1] in LEAD_TRAIL:
        kept.pop()
    return kept


def _segment(seg):
    seg = NUM_RANGE_RE.sub(" ", seg)
    alts = re.split(r"\bor\b", seg)
    kept = []
    for alt in alts:                              # rule 4: first alternative WITH content
        kept = _clean_tokens(alt)
        if kept:
            break
    if not kept:
        return []
    if len(kept) == 1 and len(alts) > 1:          # 'tomato or vegetable juice' -> 'tomato juice'
        tail = _clean_tokens(alts[-1])
        if len(tail) > 1 and tail[-1] in HEAD_NOUNS and kept[-1] != tail[-1]:
            kept = kept + [tail[-1]]
    phrase = " ".join(kept)
    parts = [_canon(p) for p in re.split(r"\band\b", phrase) if p.strip()]
    if len(parts) > 1 and all(p in SPLIT_OK for p in parts):
        return list(dict.fromkeys(parts))
    return [_canon(phrase)]


def normalize_ingredient(line):
    """Return a list of normalized ingredient names for one ingredient line."""
    if not isinstance(line, str) or not line.strip():
        return []
    s = line.lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("half-and-half", "half_and_half").replace("half and half", "half_and_half")
    if s.strip().endswith(":"):                   # rule 6: section heading
        return []
    s = TRAIL_RE.sub("", s)
    for seg in s.split(","):                      # rule 5
        keys = _segment(seg)
        if keys:
            return keys
    return []


if __name__ == "__main__":
    CASES = {
        "1/2 teaspoon salt": ["salt"],
        "2 large eggs": ["egg"],
        "1 clove garlic, minced": ["garlic"],
        "3 cloves garlic": ["garlic"],
        "1/4 teaspoon ground cloves": ["ground clove"],
        "Salt and freshly ground black pepper": ["salt", "black pepper"],
        "salt and pepper to taste": ["salt", "black pepper"],
        "2 tablespoons olive oil": ["olive oil"],
        "1 cup white sugar": ["sugar"],
        "2 (14.5 ounce) cans diced tomatoes": ["tomato"],
        "1 cup half-and-half": ["half and half"],
        "For the sauce:": [],
        "1 cup butter or margarine": ["butter"],
        "3 scallions, sliced": ["green onion"],
        "1 teaspoon vanilla extract": ["vanilla extract"],
        "1/2 cup peanut butter": ["peanut butter"],
        "1 cup all-purpose flour": ["flour"],
        "1 lb ground beef": ["ground beef"],
        "Kosher salt": ["salt"],
        "4 skinless, boneless chicken breast halves": ["chicken breast"],
        "2 egg whites": ["egg white"],
        "1/3 cup chopped or minced garlic": ["garlic"],
        "1 (12 fluid ounce) can or bottle beer": ["beer"],
        "1 cup unsweetened cocoa powder": ["cocoa powder"],
        "1 teaspoon ground cinnamon": ["cinnamon"],
        "1 cup tomato or vegetable juice": ["tomato juice"],
        "1/2 cup olive or vegetable oil": ["olive oil"],
        "1 cup chicken or vegetable broth": ["chicken broth"],
        "1 teaspoon kosher salt and ground pepper": ["salt", "black pepper"],
    }
    bad = 0
    for line, want in CASES.items():
        got = normalize_ingredient(line)
        flag = "OK " if got == want else "BAD"
        bad += got != want
        print(f"{flag} {line!r:50} -> {got}" + ("" if got == want else f"   (wanted {want})"))
    print(f"\n{len(CASES) - bad}/{len(CASES)} passed")