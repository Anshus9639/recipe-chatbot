"""Visual shell: design-system injection, ambient background, sidebar and hero."""
from pathlib import Path

import streamlit as st

STATIC = Path(__file__).resolve().parent.parent / "static"

BACKGROUND = """
<div class="ri-bg" aria-hidden="true">
  <span class="ri-aurora a1"></span><span class="ri-aurora a2"></span><span class="ri-aurora a3"></span>
  <img class="ri-botanical b1" src="app/static/leaf.svg" alt="">
  <img class="ri-botanical b2" src="app/static/herb.svg" alt="">
  <img class="ri-botanical b3" src="app/static/spice.svg" alt="">
  <i class="ri-steam s1"></i><i class="ri-steam s2"></i><i class="ri-steam s3"></i>
  <b class="ri-particle p1"></b><b class="ri-particle p2"></b><b class="ri-particle p3"></b>
  <b class="ri-particle p4"></b><b class="ri-particle p5"></b>
</div>
"""

COUNTUP_JS = """
<script>
(() => {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fmt = (v, suffix) => v.toLocaleString('en-US') + suffix;
  const animate = el => {
    if (el.dataset.done) return;
    el.dataset.done = '1';
    const target = parseInt(el.dataset.countup, 10);
    const suffix = el.dataset.suffix || '';
    if (reduce) { el.textContent = fmt(target, suffix); return; }
    const t0 = performance.now();
    const step = t => {
      const p = Math.min(1, (t - t0) / 900);
      el.textContent = fmt(Math.round(target * (1 - Math.pow(1 - p, 3))), suffix);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    // rAF is paused in hidden tabs; guarantee the final value regardless.
    setTimeout(() => { el.textContent = fmt(target, suffix); }, 1200);
  };
  // The metric divs may mount after this script runs; poll briefly for them.
  let tries = 0;
  const scan = () => {
    const els = document.querySelectorAll('[data-countup]:not([data-done])');
    els.forEach(animate);
    if (els.length === 0 && ++tries < 20) setTimeout(scan, 150);
  };
  scan();
})();
</script>
"""

EXAMPLES = [
    "Find a penne pasta recipe",
    "How many recipes contain both garlic and onion? What percentage of the dataset is that?",
    "I have eggs, onions, tomatoes and rice, no peanuts, at most six steps",
    "Take this banana bread recipe and remove eggs",
]

CARDS = [
    ("search", "Explore recipes",
     "Search by dishes, ingredients and natural language. Statistics are computed over the full filtered dataset.",
     EXAMPLES[0]),
    ("kitchen", "Pantry matching",
     "Enter available ingredients and receive explainable recipe rankings with hard constraints checked twice.",
     EXAMPLES[2]),
    ("swap_horiz", "Intelligent substitutions",
     "Adapt existing recipes using local dataset evidence and transparent confidence levels.",
     EXAMPLES[3]),
    ("monitoring", "Recipe analytics",
     "Explore ingredient frequencies, recipe distributions and step rankings over real computed data.",
     EXAMPLES[1]),
]


@st.cache_data
def _css():
    return (STATIC / "style.css").read_text(encoding="utf-8")


def inject():
    st.html(f"<style>{_css()}</style>")
    st.html(BACKGROUND)


def sidebar(core, send, reset, archive, conversational=False, api_key=""):
    with st.sidebar:
        st.html('<div class="ri-brand"><img src="app/static/leaf.svg" alt="">Recipe Intelligence</div>')
        st.caption("Studio · grounded culinary intelligence")
        if conversational:
            st.badge("Conversational mode", icon=":material/forum:", color="green")
        else:
            st.badge("Rule-based mode", icon=":material/rule:", color="orange")
        st.button("New conversation", icon=":material/add_comment:", key="nav_new",
                  on_click=reset, width="stretch")
        nav = [("nav_search", "search", "Recipe search", EXAMPLES[0]),
               ("nav_stats", "stats", "Search statistics", EXAMPLES[1]),
               ("nav_match", "match", "Pantry matching", EXAMPLES[2]),
               ("nav_sub", "adapt", "Ingredient substitution", EXAMPLES[3])]
        for key, kind, label, ex in nav:
            st.button(label, icon=":material/arrow_forward:", key=key,
                      type="primary" if core.last_kind == kind else "secondary",
                      on_click=send, args=(ex,), width="stretch")

        f = core.f
        chips = [f":blue-badge[search: {f.query}]"] if f.query else []
        chips += [f":green-badge[has {k}]" for k in f.include]
        chips += [f":red-badge[no {x}]" for x in f.exclude]
        chips += [f":orange-badge[{r}-free]" for r in f.restrictions]
        if f.max_steps is not None:
            chips.append(f":violet-badge[at most {f.max_steps} steps]")
        st.markdown("**Active restrictions & filters**")
        st.markdown(" ".join(chips) if chips else ":gray-badge[none - all usable recipes]")
        if f.restrictions or f.exclude:
            st.button("Clear restrictions", icon=":material/filter_alt_off:", key="clear_restrictions",
                      on_click=send, args=("clear restrictions",), width="stretch")

        if archive:
            with st.expander("Recent conversations", icon=":material/history:"):
                for i, a in enumerate(archive):
                    st.caption(f"{a['title']} · {len(a['messages']) // 2} turn(s)")
                    st.button("Ask again", key=f"arch_{i}", icon=":material/replay:",
                              on_click=send, args=(a["messages"][0]["content"],))
        with st.expander("Example prompts", icon=":material/lightbulb:"):
            for i, ex in enumerate(EXAMPLES):
                st.button(ex, key=f"ex_{i}", on_click=send, args=(ex,), width="stretch")
        st.button("Start over", icon=":material/restart_alt:", key="restart",
                  on_click=reset, width="stretch")
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
            k = api_key
            if k:
                st.caption(f"Key in use: {k[:6]}...{k[-4:]}")
        st.caption("[GitHub repo](https://github.com/Anshus9639/recipe-chatbot) · "
                   "[Eval report](https://github.com/Anshus9639/recipe-chatbot/blob/master/eval/REPORT.md)")


def hero(n_recipes, n_sources, send):
    st.html('<div class="ri-eyebrow">Your personal culinary intelligence engine</div>')
    st.title("Discover. Match. Adapt.")
    st.caption(f"Explore {n_recipes:,} recipes using grounded retrieval, intelligent ingredient "
               "matching and evidence-based substitutions.")
    metrics = [(n_recipes, "usable recipes", ""), (n_sources, "recipe sources", ""),
               (100, "local computation for dataset facts", "%")]
    for col, (i, (value, label, suffix)) in zip(st.columns(3), enumerate(metrics)):
        with col:
            with st.container(key=f"metric_{i}"):
                st.html(f'<div class="ri-metric"><div class="v" data-countup="{value}" '
                        f'data-suffix="{suffix}">0</div><div class="l">{label}</div></div>')
    st.html(COUNTUP_JS, unsafe_allow_javascript=True)
    for row in (CARDS[:2], CARDS[2:]):
        for col, (j, (icon, name, desc, ex)) in zip(st.columns(2), enumerate(row, start=CARDS.index(row[0]))):
            with col:
                with st.container(key=f"card_{j}", border=True, height="stretch"):
                    st.markdown(f":material/{icon}: **{name}**")
                    st.caption(desc)
                    st.button("Try it", key=f"try_{j}", on_click=send, args=(ex,), width="stretch")
    st.caption("...or type anything below: searches, statistics, pantry matches, substitutions.")