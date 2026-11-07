"""Add derived columns (normalized ingredient keys, step counts) to the unified data."""
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from src.loader import load_recipes
from src.normalize import normalize_ingredient

OUT_PATH = Path("data/processed/recipes_features.parquet")
SENT_RE = re.compile(r"(?<=[.!?])\s*(?=[A-Z])")


def count_steps(text):
    """PRIMARY step rule: number of non-empty lines."""
    return len([l for l in text.split("\n") if l.strip()])


def count_sentences(text):
    """DIAGNOSTIC only: rough sentence count (also splits glued 'sugar.Set')."""
    return len([s for s in SENT_RE.split(text) if s.strip()]) if text.strip() else 0


def build():
    df = load_recipes()
    empty_lines = []

    def keys_for(ings):
        out = set()
        for line in ings:
            k = normalize_ingredient(line)
            if not k:
                empty_lines.append(line)
            out.update(k)
        return sorted(out)

    df["ingredient_keys"] = df["ingredients"].apply(keys_for)
    df["n_ingredients"] = df["ingredients"].apply(len)               # cleaned lines
    df["n_unique_ingredients"] = df["ingredient_keys"].apply(len)    # distinct normalized names
    df["n_steps"] = df["instructions"].apply(count_steps)
    df["n_sentences"] = df["instructions"].apply(count_sentences)
        # Single-paragraph recipes can't be step-counted by lines; flag them.
    df["steps_reliable"] = ~((df["n_steps"] == 1) & (df["n_sentences"] >= 4))

    df.to_parquet(OUT_PATH, index=False)
    print(f"Saved -> {OUT_PATH}  ({len(df):,} rows)")
    return df, empty_lines


def load_features():
    """Used by the app. Parquet returns numpy arrays; convert list columns back to lists."""
    if not OUT_PATH.exists():
        return build()[0]
    df = pd.read_parquet(OUT_PATH)
    for col in ("ingredients_raw", "ingredients", "ingredient_keys"):
        df[col] = df[col].apply(list)
    return df


if __name__ == "__main__":
    df, empty_lines = build()
    u = df[df["usable"]]
    print("\n" + "=" * 60)
    print(f"Usable recipes: {len(u):,}")
    for col in ("n_ingredients", "n_unique_ingredients", "n_steps", "n_sentences"):
        print(f"{col:22} mean={u[col].mean():.2f}  median={u[col].median():.0f}  max={u[col].max()}")
    print("\nSteps (line rule) vs sentences: recipes where n_steps==1 but n_sentences>=4:",
          int(((u['n_steps'] == 1) & (u['n_sentences'] >= 4)).sum()))
    print("\nTop 25 normalized ingredients (usable recipes):")
    c = Counter(k for ks in u["ingredient_keys"] for k in ks)
    print(c.most_common(25))
    print(f"\nIngredient lines that produced NO key: {len(empty_lines):,}. Sample:")
    print(empty_lines[:12])
    print("\nRandom raw line -> keys (eyeball these):")
    samp = u.sample(8, random_state=0)
    for ings in samp["ingredients"]:
        for line in ings[:2]:
            print(f"  {line!r:55} -> {normalize_ingredient(line)}")
            print("\nsteps_reliable among usable:", int(u["steps_reliable"].sum()), "of", len(u))