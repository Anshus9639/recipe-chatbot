"""Streamlit web UI for the recipe chatbot. Wraps the same Bot used by the CLI.

Run from the repo root:  streamlit run app.py
"""
import streamlit as st

from src import gemini
from src.converse import ConversationalBot
from src.router import Bot
from src.search import RecipeIndex

st.set_page_config(page_title="Recipe chatbot", page_icon=":material/restaurant:", layout="centered")


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

EXAMPLES = [
    "Find a penne pasta recipe",
    "How many recipes contain both garlic and onion? What percentage of the dataset is that?",
    "I have eggs, onions, tomatoes and rice, no peanuts, at most six steps",
    "Take this banana bread recipe and remove eggs",
]


def send(text):
    st.session_state.messages.append({"role": "user", "content": text})
    st.session_state.messages.append({"role": "assistant", "content": st.session_state.bot.reply(text)})


with st.sidebar:
    st.header("Recipe chatbot")
    st.caption(f"{len(ix.df):,} usable recipes from the Recipe Box dataset. "
               "Every fact is retrieved or computed locally.")
    if isinstance(st.session_state.bot, ConversationalBot):
        st.success("Conversational mode: Gemini handles language; facts stay computed.",
                   icon=":material/forum:")
        k = st.session_state.bot.key or ""
        st.caption(f"API key in use: {k[:6]}...{k[-4:]}")
    else:
        st.info("Rule-based mode. Set GEMINI_API_KEY (env or .streamlit/secrets.toml) "
                "for natural conversation.", icon=":material/rule:")
    if st.button("Start over", icon=":material/restart_alt:", width="stretch"):
        st.session_state.bot = make_bot()
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.subheader("Try an example")
    for i, ex in enumerate(EXAMPLES):
        if st.button(ex, key=f"ex_{i}", width="stretch"):
            send(ex)
            st.rerun()
    st.divider()
    st.caption("Search, then add restrictions ('I cannot have dairy'), ask statistics, "
               "match your ingredients, or adapt a recipe ('replace the cream in recipe 1 "
               "without dairy'). Say 'show 2' for a result's full text.")

st.title("Recipe chatbot")
st.caption("Grounded search, statistics, ingredient matching and evidence-based substitution.")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar=":material/restaurant:" if msg["role"] == "assistant" else None):
        st.markdown(msg["content"])

if not st.session_state.messages:
    suggestions = st.empty()
    chosen = suggestions.pills("Try asking:", EXAMPLES, label_visibility="collapsed")
    if chosen:
        suggestions.empty()
        send(chosen)
        st.rerun()

if prompt := st.chat_input("Ask about recipes, ingredients, statistics or substitutions",
                           key="chat", submit_mode="disable"):
    send(prompt)
    st.rerun()