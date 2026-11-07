"""Recipe Intelligence Studio — Streamlit UI over the existing deterministic Bot.

Run from the repo root:  streamlit run app.py
All facts come from Bot.reply(); the frontend only presents them.
"""
import streamlit as st

from src import gemini
from src.converse import ConversationalBot
from src.router import Bot
from src.search import RecipeIndex
from ui import present, shell

st.set_page_config(page_title="Recipe Intelligence Studio", page_icon=":material/restaurant:",
                   layout="centered")
shell.inject()

FOLLOWUPS = {
    "search": ["I cannot have dairy", "at most 4 steps"],
    "match": ["prefer fewer steps", "exclude eggs too"],
    "adapt": ["use applesauce instead", "make it dairy-free"],
}


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


def core_bot():
    b = st.session_state.bot
    return b.core if isinstance(b, ConversationalBot) else b


if "bot" not in st.session_state:
    st.session_state.bot = make_bot()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending" not in st.session_state:
    st.session_state.pending = None
if "archive" not in st.session_state:
    st.session_state.archive = []


def send(text):
    st.session_state.pending = text


def reset():
    msgs = st.session_state.messages
    if msgs:
        title = next((m["content"] for m in msgs if m["role"] == "user"), "Conversation")
        st.session_state.archive = ([{"title": title[:48], "messages": msgs}]
                                    + st.session_state.archive)[:5]
    st.session_state.bot = make_bot()
    st.session_state.messages = []
    st.session_state.pending = None


core = core_bot()
bot = st.session_state.bot
shell.sidebar(core, send, reset, st.session_state.archive,
              conversational=isinstance(bot, ConversationalBot),
              api_key=getattr(bot, "key", "") or "")

if not st.session_state.messages and not st.session_state.pending:
    shell.hero(len(ix.df), ix.df["source"].nunique(), send)

for i, msg in enumerate(st.session_state.messages):
    latest = i == len(st.session_state.messages) - 1 and msg["role"] == "assistant"
    with st.chat_message(msg["role"], avatar=":material/restaurant:" if msg["role"] == "assistant"
                         else ":material/person:"):
        present.render_assistant(msg["content"], core, ix, latest=latest)
        if latest:
            if core.last:
                with st.container(horizontal=True):
                    for n in range(1, min(5, len(core.last)) + 1):
                        st.button(f"Show {n}", key=f"qa_show_{n}", icon=":material/visibility:",
                                  on_click=send, args=(f"show {n}",))
            follow = FOLLOWUPS.get(core.last_kind, [])
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
        with st.container(key="msg_new"):
            with st.container(key="cooking"):
                with st.status(":shimmer[Cooking up a grounded answer...]", type="compact") as status:
                    reply = st.session_state.bot.reply(text)
                    status.update(label="Answer computed from the dataset", state="complete")
            present.render_assistant(reply, core, ix, latest=True)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()

if prompt := st.chat_input("Ask about recipes, ingredients, statistics or substitutions",
                           key="chat", submit_mode="disable"):
    st.session_state.pending = prompt
    st.rerun()
