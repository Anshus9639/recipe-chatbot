"""Rich result presentation. Parses the engine's deterministic markdown into cards.

Every number shown here comes from the engine text or the loaded dataset; nothing
is invented. If parsing fails (e.g. the conversational layer rephrased the format),
the raw engine markdown is rendered unchanged so no information is ever lost.
"""
import re

import pandas as pd
import streamlit as st

SOURCE_NAMES = {"ar": "Allrecipes", "epi": "Epicurious", "fn": "Food.com"}

SEARCH_RE = re.compile(
    r"^(\d+)\.\s+\*\*(.+?)\*\*\s+`([^`]+)`\s+\(score ([0-9.]+), (\d+) step\(s\)\)\s*$", re.M)
MATCH_RE = re.compile(
    r"^(\d+)\.\s+\*\*(.+?)\*\*\s+`([^`]+)`\s+score ([0-9.]+), (.+)$", re.M)
RANK_RE = re.compile(
    r"^(\d+)\.\s+\*\*(.+?)\*\*\s+`([^`]+)`\s+\((\d+) step\(s\), (\d+) sentence\(s\)\)\s*$", re.M)
CAND_RE = re.compile(
    r"^(\d+)\.\s+\*\*(.+?)\*\*:\s*(STRONG|MODERATE|WEAK|NONE)( \+ CONFLICT)?"
    r"( \(already in this recipe\))?\s*$", re.M)
HAVE_RE = re.compile(r"\*\*Your ingredients \(normalized, staples excluded\):\*\*\s*(.+)")
COUNT_RE = re.compile(r"\*\*Recipes matching:\*\*\s*([\d,]+)")
PCT_RE = re.compile(r"\*\*Percentage:\*\*\s*([\d,]+)\s*/\s*([\d,]+)\s*usable recipes\s*=\s*([\d.]+)%")
COMMON_RE = re.compile(r"^(\d+)\.\s+([^:\n]+):\s*([\d,]+) recipes \(([\d.]+)%\)\s*$", re.M)
MEAN_RE = re.compile(r"mean ([\d.]+), median ([\d.]+)")
CHOSEN_RE = re.compile(r"^-\s+(.+?)\s*->\s*\*\*(.+?)\*\*:\s*confidence\s*\*\*(LOW|MODERATE|HIGH)([^*]*)\*\*", re.M)

GRADE_COLOR = {"STRONG": "green", "MODERATE": "yellow", "WEAK": "orange", "NONE": "gray"}


class _Fallback(Exception):
    pass


def _blocks(text, result_re):
    """Split engine text into header, per-result detail lines and tail."""
    header, results, tail = [], [], []
    for line in text.split("\n"):
        m = result_re.match(line)
        if m:
            results.append((m, []))
        elif results and re.match(r"^\s+-\s", line):
            results[-1][1].append(line.strip()[2:])
        elif results:
            tail.append(line)
        else:
            header.append(line)
    return "\n".join(header).strip(), results, "\n".join(tail).strip()


def _source_badge(rid):
    return SOURCE_NAMES.get(rid.split(":")[0], rid.split(":")[0])


def _recipe_expander(core, rid):
    if rid not in core.by_id.index:
        return
    row = core.by_id.loc[rid]
    with st.expander("Original ingredients & instructions", icon=":material/menu_book:"):
        st.markdown("**Ingredients**")
        st.markdown("\n".join(f"- {l}" for l in row["ingredients"]))
        st.markdown("**Instructions**")
        steps = [l.strip() for l in row["instructions"].split("\n") if l.strip()]
        st.markdown("\n".join(f"{i}. {l}" for i, l in enumerate(steps, 1)))


def _card_head(title, rid, badges):
    st.markdown(f"**{title}**")
    with st.container(horizontal=True):
        st.badge(_source_badge(rid), icon=":material/library_books:", color="violet")
        for text, color in badges:
            st.badge(text, color=color)
    st.html(f'<div class="ri-id">{rid}</div>')


def _search(content, core):
    header, results, tail = _blocks(content, SEARCH_RE)
    ids = [m.group(3) for m, _ in results]
    if not results or ids != list(core.last):
        raise _Fallback()
    st.markdown(header)
    for i, (m, details) in enumerate(results, 1):
        with st.container(key=f"rcard_s{i}", border=True):
            _card_head(m.group(2), m.group(3),
                       [(f"score {m.group(4)}", "blue"), (f"{m.group(5)} steps", "gray")])
            for d in details:
                st.caption(d)
            _recipe_expander(core, m.group(3))
    if tail:
        st.markdown(tail)


def _match(content, core):
    header, results, tail = _blocks(content, MATCH_RE)
    ids = [m.group(3) for m, _ in results]
    if not results or ids != list(core.last):
        raise _Fallback()
    have_m = HAVE_RE.search(header)
    n_have = len([x for x in have_m.group(1).split(",") if x.strip()]) if have_m else 0
    st.markdown(header)
    for i, (m, details) in enumerate(results, 1):
        matched = missing = unused = ""
        n_matched = 0
        why = ""
        for d in details:
            if d.startswith("matched ("):
                n_matched = int(re.match(r"matched \((\d+)\)", d).group(1))
                matched = d.split(":", 1)[1].strip()
            elif d.startswith("missing / extra required ("):
                missing = d.split(":", 1)[1].strip()
            elif d.startswith("your ingredients not used:"):
                unused = d.split(":", 1)[1].strip()
            elif d.startswith("why this rank:"):
                why = d.split(":", 1)[1].strip()
        with st.container(key=f"rcard_m{i}", border=True):
            _card_head(m.group(2), m.group(3),
                       [(f"score {m.group(4)}", "blue"), (m.group(5), "gray")])
            if n_have:
                cov = min(1.0, n_matched / n_have)
                st.progress(cov, text=f"Ingredient coverage: {n_matched}/{n_have} ({cov:.0%})")
            chips = [f":green-badge[{x.strip()}]" for x in matched.split(";") if x.strip()]
            if missing and not missing.startswith("none"):
                chips += [f":orange-badge[missing: {x.strip()}]" for x in missing.split(",") if x.strip()]
            if unused:
                chips += [f":gray-badge[unused: {x.strip()}]" for x in unused.split(",") if x.strip()]
            if chips:
                st.markdown(" ".join(chips))
            for d in details:
                if d.startswith("staples assumed available:"):
                    st.caption(d)
            if why:
                st.caption(f"Why this rank: {why}")
            _recipe_expander(core, m.group(3))
    if tail:
        st.markdown(tail)


def _adapt(content, core):
    parts = re.split(r"(?m)^###\s+", content)
    head, sections = parts[0], {}
    for p in parts[1:]:
        title, _, body = p.partition("\n")
        sections[title.strip()] = body.strip()
    chosen_key = "Chosen substitution"
    if chosen_key not in sections or "Updated ingredient list" not in sections \
            or "Revised instructions" not in sections:
        raise _Fallback()
    chosen = CHOSEN_RE.findall(sections[chosen_key])
    if not chosen:
        raise _Fallback()
    evidence = []
    for title, body in sections.items():
        if not title.startswith("Replacing "):
            continue
        cands = list(CAND_RE.finditer(body))
        if not cands:
            raise _Fallback()
        intro = body[:cands[0].start()].strip()
        blocks = []
        for j, cm in enumerate(cands):
            end = cands[j + 1].start() if j + 1 < len(cands) else len(body)
            detail = body[cm.end():end].strip()
            blocks.append((cm, detail))
        evidence.append((title, intro, blocks))

    st.markdown(head)
    for title, intro, blocks in evidence:
        st.markdown(f"**{title}**")
        if intro:
            st.markdown(intro)
        for j, (cm, detail) in enumerate(blocks):
            with st.container(key=f"rcard_e{j}", border=True):
                with st.container(horizontal=True):
                    st.markdown(f"**{cm.group(2)}**")
                    st.badge(cm.group(3), color=GRADE_COLOR[cm.group(3)])
                    if cm.group(4):
                        st.badge("CONFLICT", icon=":material/warning:", color="red")
                    if cm.group(5):
                        st.badge("already in recipe", color="gray")
                if detail:
                    st.markdown(detail)
    for old, new, level, rest in chosen:
        text = f"{old} → **{new}**: confidence **{level}{rest}**"
        if level == "HIGH":
            st.success(text, icon=":material/verified:")
        elif level == "MODERATE":
            st.info(text, icon=":material/info:")
        else:
            st.warning(text, icon=":material/warning:")
    for line in sections[chosen_key].split("\n"):
        if line.strip().startswith("**WARNING"):
            st.error(line.strip())
    order = ["Updated ingredient list", "Revised instructions"]
    order += [t for t in sections if t.startswith("Expected effects")]
    order += [t for t in sections if t.startswith("Verification")]
    for title in order:
        body = sections.get(title, "")
        with st.container(border=True):
            st.markdown(f"**{title}**")
            if title.startswith("Verification") and "STILL VIOLATED" in body:
                st.error("This adaptation still violates part of your request; see the checks below.")
            st.markdown(body)


def _stats(content, core, ix):
    count_m, pct_m = COUNT_RE.search(content), PCT_RE.search(content)
    common = COMMON_RE.findall(content)
    rank_header, rank_results, rank_tail = _blocks(content, RANK_RE)
    mean_m = MEAN_RE.search(content)
    if not (count_m or common or rank_results or mean_m):
        raise _Fallback()
    if count_m:
        n = int(count_m.group(1).replace(",", ""))
        cols = st.columns(2 if pct_m else 1)
        with cols[0]:
            st.metric("Recipes matching", f"{n:,}")
        if pct_m:
            with cols[1]:
                st.metric("Share of dataset", f"{pct_m.group(3)}%",
                          help=f"{pct_m.group(1)} / {pct_m.group(2)} usable recipes")
    if mean_m:
        c1, c2 = st.columns(2)
        c1.metric("Mean", mean_m.group(1))
        c2.metric("Median", mean_m.group(2))
    if common:
        df = pd.DataFrame({"ingredient": [c[1].strip() for c in common],
                           "recipes": [int(c[2].replace(",", "")) for c in common]})
        st.bar_chart(df, x="ingredient", y="recipes", horizontal=True, color="#B5D99A")
    if rank_results:
        ids = [m.group(3) for m, _ in rank_results]
        if ids == list(core.last):
            st.markdown(rank_header)
            for i, (m, _) in enumerate(rank_results, 1):
                with st.container(key=f"rcard_r{i}", border=True):
                    _card_head(m.group(2), m.group(3),
                               [(f"{m.group(4)} steps", "blue"), (f"{m.group(5)} sentences", "gray")])
                    _recipe_expander(core, m.group(3))
    # The full engine text stays visible: it carries filters, denominators and disclaimers.
    st.markdown(content)


def render_assistant(content, core, ix, latest=False):
    if not latest:
        st.markdown(content)
        return
    try:
        kind = core.last_kind
        if kind == "search" and core.last:
            _search(content, core)
        elif kind == "match" and core.last:
            _match(content, core)
        elif kind == "adapt":
            _adapt(content, core)
        elif kind == "stats":
            _stats(content, core, ix)
        else:
            st.markdown(content)
    except Exception:
        # The LLM layer may rephrase the engine format; raw markdown is the safe path.
        st.markdown(content)