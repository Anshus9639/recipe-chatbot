"""Streamlit web UI for the recipe chatbot. Wraps the same Bot used by the CLI.

Run from the repo root:  streamlit run app.py
"""
import streamlit as st

from src import gemini
from src.converse import ConversationalBot
from src.router import Bot
from src.search import RecipeIndex

st.set_page_config(page_title="Recipe chatbot", page_icon=":material/restaurant:", layout="centered")
# No native option hides the connection-state chip; the in-chat status covers progress feedback.
st.html("<style>[data-testid='stStatusWidget'] { display: none; }</style>")


@st.cache_resource(show_spinner="Loading recipe index (first run builds the TF-IDF cache)...")
def load_index():
    return RecipeIndex()


ix = load_index()


def make_bot():
    key = gemini.get_api_key()
    if not key:
        try:
            key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            key = None
    return ConversationalBot(ix, key) if key else Bot(ix)


if "bot" not in st.session_state:
    st.session_state.bot = make_bot()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending" not in st.session_state:
    st.session_state.pending = None

EXAMPLES = [
    "Find a penne pasta recipe",
    "How many recipes contain both garlic and onion? What percentage of the dataset is that?",
    "I have eggs, onions, tomatoes and rice, no peanuts, at most six steps",
    "Take this banana bread recipe and remove eggs",
]
EXAMPLE_ICONS = [":material/search:", ":material/query_stats:", ":material/kitchen:", ":material/swap_horiz:"]

CARDS = [
    (":material/search:", "Search & statistics",
     "Find recipes by dish or ingredient; counts and rankings are computed over every usable recipe, never a sample.",
     EXAMPLES[0]),
    (":material/kitchen:", "Pantry matching",
     "Tell me what you have. Hard constraints are checked twice and never silently relaxed.",
     EXAMPLES[2]),
    (":material/swap_horiz:", "Evidence-based swaps",
     "Replace an ingredient with graded dataset evidence, cited recipe IDs and honest confidence.",
     EXAMPLES[3]),
]

FOLLOWUPS = {
    "search": ["I cannot have dairy", "at most 4 steps"],
    "match": ["prefer fewer steps", "exclude eggs too"],
    "adapt": ["use applesauce instead", "make it dairy-free"],
}


def core_bot():
    b = st.session_state.bot
    return b.core if isinstance(b, ConversationalBot) else b


def send(text):
    st.session_state.pending = text


def reset():
    st.session_state.bot = make_bot()
    st.session_state.messages = []
    st.session_state.pending = None


with st.sidebar:
    st.header("Session", icon=":material/tune:")
    if isinstance(st.session_state.bot, ConversationalBot):
        st.badge("Conversational mode", icon=":material/forum:", color="green")
        st.caption("Gemini phrases the answers; every fact is computed locally.")
    else:
        st.badge("Rule-based mode", icon=":material/rule:", color="orange")
        st.caption("The local engine answers directly; natural-language mode is off.")

    f = core_bot().f
    chips = []
    if f.query:
        chips.append(f":blue-badge[search: {f.query}]")
    chips += [f":green-badge[has {k}]" for k in f.include]
    chips += [f":red-badge[no {x}]" for x in f.exclude]
    chips += [f":orange-badge[{r}-free]" for r in f.restrictions]
    if f.max_steps is not None:
        chips.append(f":violet-badge[at most {f.max_steps} steps]")
    st.markdown("**Active filters**")
    st.markdown(" ".join(chips) if chips else ":gray-badge[none - all usable recipes]")
    if f.restrictions or f.exclude:
        st.button("Clear restrictions", icon=":material/filter_alt_off:", key="clear_restrictions",
                  on_click=send, args=("clear restrictions",), width="stretch")
    st.button("Start over", icon=":material/restart_alt:", key="restart", on_click=reset, width="stretch")

    st.markdown("**Try an example**")
    for i, ex in enumerate(EXAMPLES):
        st.button(f"{EXAMPLE_ICONS[i]} {ex}", key=f"ex_{i}", on_click=send, args=(ex,), width="stretch")

    with st.expander("How answers stay grounded", icon=":material/verified:"):
        st.markdown(
            "- Hard filters run before ranking, over all usable recipes.\n"
            "- Statistics are exact computations, not estimates.\n"
            "- Substitutions cite local recipe IDs and grade the evidence STRONG/MODERATE/WEAK.\n"
            "- The LLM only phrases answers; a guardrail rejects any rewrite that drops IDs, "
            "numbers or warnings, and the rule-based engine answers if the API fails.")
    with st.expander("Setup & diagnostics", icon=":material/code:"):
        st.markdown("Conversational mode: set `GEMINI_API_KEY` (environment variable or "
                    "`.streamlit/secrets.toml`) and restart the app.")
        if isinstance(st.session_state.bot, ConversationalBot):
            k = st.session_state.bot.key or ""
            st.caption(f"Key in use: {k[:6]}...{k[-4:]}")
    st.caption("[GitHub repo](https://github.com/Anshus9639/recipe-chatbot) · "
               "[Eval report](https://github.com/Anshus9639/recipe-chatbot/blob/master/eval/REPORT.md)")

st.title("Recipe chatbot", icon=":material/restaurant:")
st.caption("Grounded search, statistics, ingredient matching and evidence-based substitution "
           "over the Recipe Box dataset.")
with st.container(horizontal=True):
    st.badge(f"{len(ix.df):,} usable recipes", icon=":material/database:", color="blue")
    st.badge(f"{ix.df['source'].nunique()} sources", icon=":material/library_books:", color="violet")
    st.badge("Every fact computed locally", icon=":material/verified:", color="green")

for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"], avatar=":material/restaurant:" if msg["role"] == "assistant"
                         else ":material/person:"):
        st.markdown(msg["content"])
        if i == len(st.session_state.messages) - 1 and msg["role"] == "assistant":
            c = core_bot()
            if c.last:
                with st.container(horizontal=True):
                    for n in range(1, min(5, len(c.last)) + 1):
                        st.button(f"Show {n}", key=f"qa_show_{n}", icon=":material/visibility:",
                                  on_click=send, args=(f"show {n}",))
            follow = FOLLOWUPS.get(c.last_kind, [])
            if follow:
                with st.container(horizontal=True):
                    for j, chip in enumerate(follow):
                        st.button(chip, key=f"qa_follow_{j}", on_click=send, args=(chip,))

if st.session_state.pending:
    text = st.session_state.pending
    st.session_state.pending = None
    st.session_state.messages.append({"role": "user", "content": text})
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(text)
    with st.chat_message("assistant", avatar=":material/restaurant:"):
        with st.status(":shimmer[Cooking up a grounded answer...]", type="compact") as status:
            reply = st.session_state.bot.reply(text)
            status.update(label="Answer computed from the dataset", state="complete")
        st.markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()

if not st.session_state.messages:
    for j, (col, (icon, name, desc, ex)) in enumerate(zip(st.columns(3), CARDS)):
        with col:
            with st.container(border=True, height="stretch"):
                st.markdown(f"{icon} **{name}**")
                st.caption(desc)
                st.button("Try it", key=f"card_{j}", on_click=send, args=(ex,), width="stretch")
    st.caption("...or type anything below: searches, statistics, pantry matches, substitutions.")

if prompt := st.chat_input("Ask about recipes, ingredients, statistics or substitutions",
                           key="chat", submit_mode="disable"):
    st.session_state.pending = prompt
    st.rerun()