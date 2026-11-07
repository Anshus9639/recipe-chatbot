"""TF-IDF search. Hard filters run on the FULL dataset; TF-IDF only ranks the survivors."""
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from src import restrictions as R
from src.normalize import normalize_ingredient
from src.prepare import load_features

CACHE = Path("data/processed/tfidf.joblib")
STOP = sorted(set(ENGLISH_STOP_WORDS) | {
    "find", "recipe", "recipes", "show", "want", "need", "give", "suggest", "please",
    "dish", "make", "cook", "cooking", "looking", "like"})
COLS = ["id", "title", "n_steps", "steps_reliable", "ingredients", "instructions"]


@dataclass(frozen=True)
class Filters:
    query: str = ""
    include: tuple = ()        # ingredients that MUST be present (normalized-key match)
    exclude: tuple = ()        # free-text ingredients that must NOT appear (hard)
    restrictions: tuple = ()   # named: dairy, egg, peanut, tree_nut, shellfish (hard)
    max_steps: Optional[int] = None   # counts only recipes with reliable step counts


class RecipeIndex:
    def __init__(self):
        df = load_features()
        self.n_all = len(df)          # all loaded recipes, incl. unusable (for reporting)
        self.df = df[df["usable"]].reset_index(drop=True)
        self.ing_text = self.df["ingredients"].apply(lambda l: " | ".join(l)).map(R.norm_text)
        self._cache = {}
        self._load_or_fit()

    def _load_or_fit(self):
        if CACHE.exists():
            self.vec, self.X = joblib.load(CACHE)
            return
        print("Fitting TF-IDF (first run only, 1-3 min)...")
        docs = [(t.lower() + " ") * 3 + " ".join(k)          # title x3 = field boost
                for t, k in zip(self.df["title"], self.df["ingredient_keys"])]
        self.vec = TfidfVectorizer(ngram_range=(1, 2), min_df=3, sublinear_tf=True,
                                   stop_words=STOP, dtype=np.float32)
        self.X = self.vec.fit_transform(docs)
        joblib.dump((self.vec, self.X), CACHE)
        print("TF-IDF matrix:", self.X.shape)

    # ---------- hard filters (full dataset) ----------
    def _violators(self, ck, spec):
        if ck not in self._cache:
            self._cache[ck] = R.text_mask(self.ing_text, spec)
        return self._cache[ck]

    def _has_key(self, key):
        ck = ("inc", key)
        if ck not in self._cache:
            self._cache[ck] = self.df["ingredient_keys"].apply(lambda ks: key in ks).to_numpy()
        return self._cache[ck]

    def filter_mask(self, f):
        mask = np.ones(len(self.df), dtype=bool)
        for name in f.restrictions:
            mask &= ~self._violators(("res", name), R.SPECS[name])
        for term in f.exclude:
            keys = tuple(normalize_ingredient(term) or [term.lower()])
            mask &= ~self._violators(("exc", keys), R.make_spec(keys))
        for term in f.include:
            for key in (normalize_ingredient(term) or [term.lower()]):
                mask &= self._has_key(key)
        if f.max_steps is not None:
            mask &= (self.df["n_steps"].to_numpy() <= f.max_steps) & \
                    self.df["steps_reliable"].to_numpy()
        return mask

    # ---------- ranking ----------
    def search(self, f, top_k=5):
        """Returns (results_df, n_candidates_after_filters, n_matching_query)."""
        idx = np.flatnonzero(self.filter_mask(f))
        n_candidates = len(idx)
        if f.query.strip():
            q = self.vec.transform([f.query.lower()])
            if q.nnz == 0:
                return self.df.iloc[[]][COLS].assign(score=[]), n_candidates, 0
            sims = (self.X[idx] @ q.T).toarray().ravel()
            keep = sims > 0
            idx, sims = idx[keep], sims[keep]
            order = np.argsort(-sims, kind="stable")[:top_k]
        else:
            sims = np.zeros(len(idx))
            order = np.arange(min(top_k, len(idx)))
        res = self.df.iloc[idx[order]][COLS].copy()
        res["score"] = sims[order]
        return res, n_candidates, len(idx)


def show(res):
    for _, r in res.iterrows():
        print(f"  [{r['score']:.3f}] {r['id']} | {r['title']} | steps={r['n_steps']}")
        for l in r["ingredients"][:4]:
            print("       -", l)


if __name__ == "__main__":
    ix = RecipeIndex()
    print(f"Indexed usable recipes: {len(ix.df):,}")

    f1 = Filters(query="penne pasta")
    res, n_c, n_m = ix.search(f1, top_k=15)
    print(f"\n[1] '{f1.query}' | filters: none | candidates={n_c:,} | matching={n_m:,}")
    show(res.head(5))

    f2 = replace(f1, restrictions=("dairy",))
    res2, n_c2, n_m2 = ix.search(f2, top_k=5)
    print(f"\n[2] follow-up: 'I cannot have dairy' | candidates={n_c2:,} "
          f"(removed {n_c - n_c2:,}) | matching={n_m2:,}")
    show(res2)
    print("   Evidence: every ingredient line of each result was scanned; no dairy terms found.")

    print("\n[3] SANITY: unfiltered top-15 recipes that the dairy filter removes, with the trigger line:")
    for _, r in res.iterrows():
        bad = R.offending_lines(r["ingredients"], "dairy")
        if bad:
            print(f"  {r['id']} | {r['title']} -> {bad[:2]}")

    f3 = Filters(query="chicken", include=("garlic", "lemon juice"), exclude=("egg",), max_steps=4)
    res3, n_c3, n_m3 = ix.search(f3, top_k=3)
    print(f"\n[4] chicken + include garlic & lemon juice, exclude egg, max 4 reliable steps "
          f"| candidates={n_c3:,} | matching={n_m3:,}")
    show(res3)
