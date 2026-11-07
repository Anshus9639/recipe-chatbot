import json
from pathlib import Path
from collections import Counter

RAW = Path("data/raw")
FILES = sorted(RAW.glob("*.json"))

def short(x, n=120):
    s = repr(x)
    return s if len(s) <= n else s[:n] + "..."

all_keys = {}

for f in FILES:
    print("=" * 70)
    print("FILE:", f.name)
    with open(f, encoding="utf-8") as fh:
        data = json.load(fh)

    print("Top-level type:", type(data).__name__, "| size:", len(data))
    all_keys[f.name] = set(data.keys()) if isinstance(data, dict) else set()

    items = list(data.items()) if isinstance(data, dict) else list(enumerate(data))
    k0, v0 = items[0]
    print("First key:", k0, "| key length:", len(str(k0)))
    print("Record fields:", list(v0.keys()))
    for field, val in v0.items():
        print(f"  {field}: {type(val).__name__} -> {short(val)}")

    # Field presence / emptiness / types across ALL records
    present, empty, types = Counter(), Counter(), {}
    n_ingr, n_lines = [], []
    adverts = 0
    for _, rec in items:
        for field, val in rec.items():
            present[field] += 1
            types.setdefault(field, Counter())[type(val).__name__] += 1
            if val in (None, "", []):
                empty[field] += 1
        ing = rec.get("ingredients")
        if isinstance(ing, list):
            n_ingr.append(len(ing))
            adverts += sum(1 for i in ing if isinstance(i, str) and "ADVERTISEMENT" in i)
        ins = rec.get("instructions")
        if isinstance(ins, str):
            n_lines.append(len([l for l in ins.split("\n") if l.strip()]))

    print("\nField report (present / empty / types):")
    for field in present:
        print(f"  {field}: present={present[field]}, empty_or_null={empty[field]}, types={dict(types[field])}")
    if n_ingr:
        print(f"Ingredients per recipe: min={min(n_ingr)}, max={max(n_ingr)}")
    if n_lines:
        print(f"Instruction lines per recipe: min={min(n_lines)}, max={max(n_lines)}")
    print("Ingredient strings containing 'ADVERTISEMENT':", adverts)

    titles = [r.get("title") for _, r in items]
    print("Distinct titles:", len(set(titles)), "of", len(titles))

print("=" * 70)
print("KEY OVERLAP BETWEEN FILES (matters for stable IDs):")
names = list(all_keys)
for i in range(len(names)):
    for j in range(i + 1, len(names)):
        print(f"  {names[i]} & {names[j]}: {len(all_keys[names[i]] & all_keys[names[j]])} shared keys")