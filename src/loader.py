"""Load the three Recipe Box JSON files into one unified DataFrame."""
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

RAW_DIR = Path("data/raw")
OUT_PATH = Path("data/processed/recipes.parquet")

SOURCES = {
    "ar": "recipes_raw_nosource_ar.json",
    "epi": "recipes_raw_nosource_epi.json",
    "fn": "recipes_raw_nosource_fn.json",
}

AD_RE = re.compile(r"ADVERTISEMENT")
WS_RE = re.compile(r"\s+")


def clean_ingredient(s):
    """Remove the website artifact 'ADVERTISEMENT' and extra whitespace.
    The original string is always kept separately in ingredients_raw."""
    if not isinstance(s, str):
        return ""
    return WS_RE.sub(" ", AD_RE.sub(" ", s)).strip()


def load_source(src, filename):
    with open(RAW_DIR / filename, encoding="utf-8") as fh:
        data = json.load(fh)

    rows, skipped = [], 0
    for key, rec in data.items():
        # Empty shell records have none of the three content fields.
        if not isinstance(rec, dict) or not any(
            k in rec for k in ("title", "ingredients", "instructions")
        ):
            skipped += 1
            continue

        raw_ings = rec.get("ingredients") or []
        ings = [c for c in (clean_ingredient(i) for i in raw_ings) if c]
        title = rec.get("title") or ""
        instr = rec.get("instructions") or ""

        has_title = bool(title.strip())
        has_ing = len(ings) > 0
        has_instr = bool(instr.strip())

        rows.append({
            "id": f"{src}:{key}",          # stable ID
            "source": src,
            "key": key,                    # original dataset key
            "title": title,                # original, unmodified
            "ingredients_raw": list(raw_ings),   # original, unmodified
            "ingredients": ings,           # cleaned copy (ADVERTISEMENT removed)
            "instructions": instr,         # original, unmodified
            "picture_link": rec.get("picture_link"),
            "has_title": has_title,
            "has_ingredients": has_ing,
            "has_instructions": has_instr,
            "usable": has_title and has_ing and has_instr,
        })
    return pd.DataFrame(rows), len(data), skipped


def build():
    frames, total_raw, total_skipped = [], 0, 0
    for src, fname in SOURCES.items():
        df, n_raw, n_skip = load_source(src, fname)
        print(f"{src:>3}: raw entries={n_raw:,} | skipped empty={n_skip:,} | kept={len(df):,}")
        frames.append(df)
        total_raw += n_raw
        total_skipped += n_skip

    df = pd.concat(frames, ignore_index=True)
    assert df["id"].is_unique, "Duplicate IDs found!"
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"\nTOTAL raw entries={total_raw:,} | skipped={total_skipped:,} | kept={len(df):,}")
    print(f"Saved -> {OUT_PATH}")
    return df


def load_recipes():
    """Used by the rest of the app: fast path loads the parquet cache."""
    if OUT_PATH.exists():
        return pd.read_parquet(OUT_PATH)
    return build()


def summarize(df):
    print("\n" + "=" * 60)
    print("UNIFIED DATASET SUMMARY")
    print("IDs unique:", df["id"].is_unique)
    print("\nCounts per source (kept / has_title / has_ingredients / has_instructions / usable):")
    g = df.groupby("source")
    out = g.size().to_frame("kept").join(
        g[["has_title", "has_ingredients", "has_instructions", "usable"]].sum()
    )
    print(out)
    print("Usable total:", int(df["usable"].sum()), "of", len(df))

    dup_key = df["title"].str.strip().str.lower() + "||" + df["instructions"].str.strip()
    print("\nExact duplicate rows (same title + instructions):", int(dup_key.duplicated().sum()))

    print("\nMost common cleaned ingredient lines per source (look for junk):")
    for src, grp in df.groupby("source"):
        c = Counter(i for ings in grp["ingredients"] for i in ings)
        print(f"  {src}: {c.most_common(8)}")

    print("\nInstruction line structure (non-empty lines split on newline):")
    n_lines = df["instructions"].apply(lambda t: len([l for l in t.split("\n") if l.strip()]))
    has = df["has_instructions"]
    for src in SOURCES:
        s = n_lines[(df["source"] == src) & has]
        print(f"  {src}: median lines={s.median():.0f}, mean={s.mean():.2f}, "
              f"single-line share={(s == 1).mean():.1%}")


if __name__ == "__main__":
    data = build()
    summarize(data)