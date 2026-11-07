"""One-shot LLM baseline comparison (required by the assignment).

Sends dataset questions to Gemini WITHOUT retrieval or conversation context and
saves its answers next to the ground truth computed by our system, showing where
a plausible-sounding one-shot answer is wrong or ungrounded.

Setup:  set GEMINI_API_KEY (free key from https://aistudio.google.com/apikey)
        optionally GEMINI_MODEL (default: gemini-2.5-flash)
Run:    python eval/llm_baseline.py
Output: eval/llm_baseline.md
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import stats as S
from src.router import Bot
from src.search import Filters, RecipeIndex

HERE = Path(__file__).resolve().parent


def ask_llm(prompt):
    key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])


def main():
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey, then:\n"
              '  set GEMINI_API_KEY=your-key   (Windows cmd)\n'
              '  export GEMINI_API_KEY=your-key   (bash)\n'
              "and re-run: python eval/llm_baseline.py")
        return 1

    ix = RecipeIndex()
    bot = Bot(ix)
    q1 = "How many recipes contain both garlic and onion? What percentage of the dataset is that?"
    q2 = "Among recipes containing tomato, which five have the fewest instruction steps?"
    q3 = ("How many calories are in the recipe 'Creamy Penne Pasta' "
          "(ID ar:nvQzTEX.J7/2LmKnF8KjsR6aCqNHGxO) from this dataset?")
    preamble = ("You are a chatbot answering questions about the Recipe Box dataset "
                "(eightportions.com, ~125k recipes from Allrecipes, Epicurious, Food.com). "
                "Answer directly and specifically.\n\nQuestion: ")

    count = S.count(ix, Filters(include=("garlic", "onion")))
    rank = S.rank_steps(ix, Filters(include=("tomato",)), k=5)
    cases = [
        (q1, count["text"],
         "Exact computed count; an LLM without retrieval can only guess."),
        (q2, rank["text"] + "\n" + rank["table"].to_string(index=False),
         "Stable IDs and a defined step rule; an LLM cannot know dataset IDs."),
        (q3, bot.reply(q3),
         "Nutrition is NOT in the dataset. Correct behavior is refusal; a specific number is fabricated."),
    ]

    out = ["# One-shot LLM baseline vs. this system", "",
           f"Model: `{os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')}`, one-shot, no retrieval, "
           "no conversation context. Our system's answers are computed from the local dataset.", ""]
    for q, ours, note in cases:
        print("Asking LLM:", q)
        try:
            llm = ask_llm(preamble + q)
        except Exception as e:
            llm = f"[API error: {e}]"
        out += [f"## Question\n\n{q}", f"### One-shot LLM answer\n\n{llm}",
                f"### This system (grounded)\n\n{ours}", f"**Why this case matters:** {note}", "", "---", ""]
    (HERE / "llm_baseline.md").write_text("\n".join(out), encoding="utf-8")
    print("Wrote eval/llm_baseline.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())