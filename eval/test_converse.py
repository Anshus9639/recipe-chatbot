"""Tests for the conversational layer: grounding guardrail, routing, and fallback.
Run from the repo root:  python eval/test_converse.py   (no API key needed; LLM calls are mocked)
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import gemini
from src.converse import ConversationalBot, _parse_json, grounding_ok
from src.router import Bot
from src.search import RecipeIndex

GROUNDED = ("1. **Creamy Penne Pasta**  `ar:nvQzTEX.J7/2LmKnF8KjsR6aCqNHGxO`  (score 0.627, 2 step(s))\n"
            "**Recipes matching:** 9,890\n**Percentage:** 9,890 / 122,938 usable recipes = 8.04%\n"
            "*Restriction checks are text-based; they are not a medical or allergen-safety guarantee.*")


def test_guardrail():
    assert grounding_ok(GROUNDED, GROUNDED)
    assert grounding_ok(GROUNDED, "Here you go, friend! " + GROUNDED)
    assert not grounding_ok(GROUNDED, GROUNDED.replace("ar:nvQzTEX.J7/2LmKnF8KjsR6aCqNHGxO", "ar:WRONG"))
    assert not grounding_ok(GROUNDED, GROUNDED.replace("8.04%", "about 8%"))
    assert not grounding_ok(GROUNDED, GROUNDED.replace("not a medical", "a reliable"))
    assert not grounding_ok(GROUNDED, "Sure! " + GROUNDED[:80])
    print("PASS guardrail: IDs, numbers, safety markers, truncation")


def test_parse_json():
    assert _parse_json('{"mode":"engine","query":"find pasta"}') == ("engine", "find pasta")
    assert _parse_json('```json\n{"mode":"talk","reply":"Hi!"}\n```') == ("talk", "Hi!")
    for bad in ('{"mode":"engine"}', '{"mode":"talk","reply":""}', 'not json'):
        try:
            _parse_json(bad)
            raise AssertionError(f"accepted bad intent: {bad}")
        except (ValueError, KeyError):
            pass
    print("PASS intent parsing: fences, validation")


def test_fallback_equivalence(ix):
    core, conv = Bot(ix), ConversationalBot(ix, key=None)
    for q in ["Find a penne pasta recipe", "I cannot have dairy",
              "How many recipes contain both garlic and onion?", "I have rice and tomatoes"]:
        assert conv.reply(q) == core.reply(q), q
        assert conv.last_mode == "fallback"
    print("PASS fallback: no key -> identical to rule-based Bot")


def test_routing(ix):
    with patch("src.converse.gemini.call") as call:
        bot = ConversationalBot(ix, key="fake")
        call.return_value = '{"mode":"talk","reply":"Hello! I can search recipes for you."}'
        assert bot.reply("hey there!") == "Hello! I can search recipes for you."
        assert bot.last_mode == "talk" and call.call_count == 1

        bot = ConversationalBot(ix, key="fake")
        call.reset_mock()
        call.side_effect = ['{"mode":"engine","query":"how many recipes contain both garlic and onion?"}',
                            "Sure thing! " + Bot(ix).reply("how many recipes contain both garlic and onion?")]
        out = bot.reply("yo how many recipes got garlic AND onion??")
        assert out.startswith("Sure thing!") and "9,890" in out and bot.last_mode == "engine"

        bot = ConversationalBot(ix, key="fake")
        call.reset_mock()
        grounded = Bot(ix).reply("find a penne pasta recipe")
        call.side_effect = ['{"mode":"engine","query":"find penne pasta"}',
                            "Here are some tasty pastas! (IDs and numbers dropped)"]
        assert bot.reply("find me pasta") == grounded   # guardrail rejects the rewrite

        bot = ConversationalBot(ix, key="fake")
        call.reset_mock()
        call.side_effect = gemini.GeminiError("api down")
        out = bot.reply("find a penne pasta recipe")
        assert "Conversational layer unavailable" in out and bot.last_mode == "fallback"
        assert "Creamy Penne Pasta" in out
    print("PASS routing: talk, engine+phrase, guardrail fallback, API-failure fallback")


if __name__ == "__main__":
    test_guardrail()
    test_parse_json()
    ix = RecipeIndex()
    test_fallback_equivalence(ix)
    test_routing(ix)
    print("\nALL CONVERSATIONAL-LAYER TESTS PASSED")