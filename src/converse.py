"""Hybrid conversational layer: Gemini handles language, the deterministic Bot handles facts.

Pipeline per turn:
  1. Gemini translates the free-form message (+ history) into a canonical engine command,
     or answers small talk / asks a clarifying question directly (never dataset facts).
  2. The engine (src.router.Bot) computes the grounded answer.
  3. Gemini rephrases it naturally; a programmatic check verifies every recipe ID, number
     and safety marker survived. If anything is missing, the raw engine output is shown.
Any API/parse failure falls back to the rule-based router on the original text.
"""
import json
import re

from src import gemini
from src.router import Bot

UNDERSTAND_SYSTEM = """You are the language layer of a recipe assistant. A deterministic engine
answers all dataset questions; you only translate the user's message into a command it understands,
or handle small talk yourself. Respond with JSON only.

Two modes:
{"mode":"engine","query":"<canonical command>"}  for anything about recipes, ingredients, statistics or adaptations.
{"mode":"talk","reply":"<short friendly reply>"}  for greetings, thanks, questions about what you can do,
or when the request is too ambiguous and you need a clarifying question.

NEVER state recipe facts, counts, percentages, recipe IDs, nutrition or cooking times in talk mode.
Route nutrition/time questions to the engine anyway (it refuses them properly).

The engine understands commands like these (match this style):
- Search: "find penne pasta" | "find chicken with garlic and lemon juice, no eggs, at most 4 steps"
- Restrictions (apply to the active search/match): "I cannot have dairy" | "exclude peanuts" | "no eggs"
- Detail: "show 2" | "show ingredients of recipe 1" | "show instructions of recipe 2"
- Statistics: "how many recipes contain both garlic and onion? what percentage of the dataset is that?" |
  "what's the average and median ingredient count?" | "most common ingredients in tomato recipes" |
  "among recipes containing tomato, which five have the fewest instruction steps?"
- Pantry matching: "I have eggs, onions, tomatoes and rice, no peanuts, at most six steps, prefer fewest
  additional ingredients" | follow-ups: "exclude eggs too" | "I also have garlic" | "prefer fewer steps"
- Adaptation: "replace the cream in recipe 1 without dairy" | "take this banana bread recipe and remove eggs" |
  "use applesauce instead" | "make it dairy-free"
- Reset: "start over" | "clear restrictions"

Use the conversation history to resolve references ("make it dairy free" after a search means
"I cannot have dairy"). Preserve the user's ingredient names, numbers and constraints exactly;
do not add constraints they did not state. Fix typos and translate slang into plain ingredient names."""

PHRASE_SYSTEM = """Rewrite the assistant's answer to sound warm and natural, like a helpful friend who
happens to be a careful cook. You may add ONE short friendly opening sentence and smooth the phrasing.

Hard rules — the answer is grounded in a real dataset and must stay grounded:
- Preserve EVERY recipe ID (like ar:...), number, percentage, score and quantity exactly.
- Preserve all filter descriptions, evidence lines, matched/missing ingredient lists and calculations.
- Preserve every warning, refusal, disclaimer and safety note (e.g. about allergens, predictions,
  violations, unreliable step counts) — keep their meaning and strength.
- Keep the markdown structure (headings, lists). Never add facts, recipes, numbers or claims that
  are not in the original. Never drop sections. Do not invent nutrition, times or outcomes."""

ID_RE = re.compile(r"\b(?:ar|epi|fn):[^\s,;?)`*]+")
NUM_RE = re.compile(r"\d[\d,./]*")
MARKERS = ("VIOLATES", "NOT eligible", "No match", "not a medical", "PREDICTIONS", "WARNING",
           "NOT applied", "No reliable adaptation", "Not available in this dataset")


def _nums(text):
    return {n.replace(",", "").rstrip(".") for n in NUM_RE.findall(ID_RE.sub(" ", text))}


def grounding_ok(original, rewrite):
    """Every ID, number and safety marker in the engine output must survive the rewrite."""
    if len(rewrite) < 0.6 * len(original):
        return False
    if set(ID_RE.findall(original)) - set(ID_RE.findall(rewrite)):
        return False
    if _nums(original) - _nums(rewrite):
        return False
    low = rewrite.lower()
    return all(m.lower() in low for m in MARKERS if m.lower() in original.lower())


def _parse_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    obj = json.loads(text)
    if obj.get("mode") == "engine" and isinstance(obj.get("query"), str) and obj["query"].strip():
        return "engine", obj["query"].strip()
    if obj.get("mode") == "talk" and isinstance(obj.get("reply"), str) and obj["reply"].strip():
        return "talk", obj["reply"].strip()
    raise ValueError(f"unexpected intent shape: {obj!r:.120}")


class ConversationalBot:
    def __init__(self, ix, key=None):
        self.core = Bot(ix)
        self.key = key or gemini.get_api_key()
        self.history = []
        self.last_mode = None

    def _remember(self, user, assistant):
        self.history.append((user, assistant))
        self.history = self.history[-8:]

    def _understand(self, text):
        hist = "\n".join(f"user: {u}\nassistant: {a[:400]}" for u, a in self.history)
        prompt = (f"Conversation so far:\n{hist}\n\n" if hist else "") + f"User message: {text}"
        return _parse_json(gemini.call(prompt, system=UNDERSTAND_SYSTEM, json_mode=True, key=self.key))

    def reply(self, text):
        if not self.key:
            self.last_mode = "fallback"
            return self.core.reply(text)
        try:
            mode, payload = self._understand(text)
        except (gemini.GeminiError, ValueError, KeyError):
            self.last_mode = "fallback"
            out = self.core.reply(text)
            self._remember(text, out)
            return out + "\n\n*(Conversational layer unavailable — used rule-based parsing.)*"
        if mode == "talk":
            self.last_mode = "talk"
            self._remember(text, payload)
            return payload
        grounded = self.core.reply(payload)
        try:
            rewrite = gemini.call(f"Original answer:\n\n{grounded}", system=PHRASE_SYSTEM, key=self.key)
            final = rewrite if grounding_ok(grounded, rewrite) else grounded
        except gemini.GeminiError:
            final = grounded
        self.last_mode = "engine"
        self._remember(text, final)
        return final