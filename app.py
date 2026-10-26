"""StudyMate AI - Streamlit interface. Run with:  streamlit run app.py"""
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # reads .env if present (never commit that file)

from agent import (  # noqa: E402
    MODES, AgentCallError, ask_baseline, ask_study, build_baseline_agent, build_study_agent,
)
from storage import StorageError, get_store  # noqa: E402
from tools import NotesIndex, run_search  # noqa: E402

SAMPLE_DIR = Path(__file__).parent / "sample_docs"

st.set_page_config(page_title="StudyMate AI", page_icon="📚", layout="wide")
st.markdown(
    """
    <style>
    .hero {background: linear-gradient(120deg,#4f46e5,#06b6d4); color:white; padding:1.2rem 1.5rem;
           border-radius:14px; margin-bottom:1rem;}
    .hero h1 {margin:0; font-size:1.9rem; color:white;}
    .hero p {margin:.3rem 0 0 0; opacity:.95;}
    .chip {display:inline-block; padding:.15rem .6rem; margin:.15rem .25rem .15rem 0; border-radius:999px;
           background:rgba(79,70,229,.12); border:1px solid rgba(79,70,229,.35); font-size:.85rem;}
    </style>
    <div class="hero"><h1>📚 StudyMate AI</h1>
    <p>Ask questions about <b>your own</b> PDF notes. Answers show where they came from.</p></div>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- state
def init_state() -> None:
    ss = st.session_state
    if "store" not in ss:
        try:
            ss.store = get_store()
        except StorageError as exc:
            st.error(f"Storage setup problem: {exc}")
            st.stop()
        ss.index = NotesIndex(ss.store)
    ss.setdefault("history", [])
    ss.setdefault("notice", None)  # (level, message) shown after a rerun
    ss.setdefault("uploader_key", 0)
    ss.setdefault("study_agent", None)
    ss.setdefault("baseline_agent", None)


def refresh_library() -> str | None:
    try:
        st.session_state.index.refresh()
        return None
    except StorageError as exc:
        return str(exc)


def get_study_agent():
    if st.session_state.study_agent is None:
        st.session_state.study_agent = build_study_agent(st.session_state.index)
    return st.session_state.study_agent


def get_baseline_agent():
    if st.session_state.baseline_agent is None:
        st.session_state.baseline_agent = build_baseline_agent()
    return st.session_state.baseline_agent


# --------------------------------------------------------------------------- sidebar
def save_uploads(files) -> None:
    ss = st.session_state
    saved, problems = [], []
    with st.spinner("Saving and reading your files..."):
        for f in files:
            try:
                saved.append(ss.store.save_document(f.name, f.getvalue()))
            except StorageError as exc:
                problems.append(str(exc))
        err = refresh_library()
    if err:
        problems.append(err)
    for row in ss.index.summary():
        if row["name"] in saved and row["error"]:
            problems.append(row["error"])
    if saved and not problems:
        ss.notice = ("success", f"Saved {len(saved)} file(s): {', '.join(saved)}")
    elif saved:
        ss.notice = ("warning", f"Saved {len(saved)} file(s), but: " + " | ".join(problems))
    else:
        ss.notice = ("error", " | ".join(problems) or "Nothing was saved.")
    ss.uploader_key += 1


def load_samples() -> None:
    ss = st.session_state
    try:
        with st.spinner("Adding sample notes..."):
            for path in sorted(SAMPLE_DIR.glob("*.txt")):
                ss.store.save_document(path.name, path.read_bytes())
            err = refresh_library()
        ss.notice = ("error", err) if err else ("success", "Sample notes added.")
    except StorageError as exc:
        ss.notice = ("error", str(exc))


def render_sidebar() -> None:
    ss = st.session_state
    with st.sidebar:
        st.header("📂 Your notes")
        st.caption(f"Storage: {ss.store.description}")
        files = st.file_uploader(
            "Upload PDF notes", type=["pdf"], accept_multiple_files=True,
            key=f"uploader_{ss.uploader_key}", help="Text-based PDFs only (no scanned images). Max 15 MB each.",
        )
        if files and st.button("💾 Save to library", use_container_width=True, type="primary"):
            save_uploads(files)
            st.rerun()
        if st.button("🧪 Load sample notes", use_container_width=True,
                     help="Adds 3 short sample documents so you can try the app immediately."):
            load_samples()
            st.rerun()

        if ss.notice:
            level, message = ss.notice
            getattr(st, level)(message)
            ss.notice = None

        err = refresh_library()
        if err:
            st.error(err)
        rows = ss.index.summary()
        st.subheader("Library")
        if not rows:
            st.info("No documents yet. Upload a PDF or load the sample notes.")
        for row in rows:
            if row["error"]:
                st.warning(f"⚠️ {row['name']}: {row['error']}")
            else:
                st.write(f"📄 **{row['name']}**  \n{row['pages']} page(s) · {row['chunks']} searchable chunks")
        st.divider()
        st.caption(
            "🔑 The AI answers use Amazon Bedrock (needs AWS credentials, billed per use). "
            "Uploading and the 'Retrieval test' tab work without AWS in local mode."
        )


# --------------------------------------------------------------------------- tabs
def render_answer(entry: dict) -> None:
    if entry["error"]:
        st.error(entry["error"])
        return
    ans = entry["answer"]
    if not ans.tool_used:
        st.warning("⚠️ The agent did not search your notes for this answer, so it may not come from your documents.")
    elif ans.passages_retrieved == 0:
        st.warning("⚠️ The search found nothing relevant in your notes. Treat this answer with caution.")
    st.markdown(ans.text)
    if ans.sources:
        st.markdown("**📎 Sources retrieved from your notes**")
        st.markdown("".join(f"<span class='chip'>{s.doc} · p. {s.page}</span>" for s in ans.sources),
                    unsafe_allow_html=True)
        with st.expander("Show retrieved passages"):
            for s in ans.sources:
                st.markdown(f"**{s.doc}, page {s.page}**")
                st.caption(s.snippet)
    if ans.queries:
        st.caption("Search queries the agent used: " + " · ".join(f"`{q}`" for q in ans.queries))


def tab_ask() -> None:
    ss = st.session_state
    mode = st.radio("Answer style", list(MODES), horizontal=True)
    n_q = 5
    if mode == "Multiple-choice quiz":
        n_q = st.slider("Number of questions", 3, 10, 5)

    for entry in ss.history:
        with st.chat_message("user"):
            st.write(f"{entry['q']}  \n*({entry['mode']})*")
        with st.chat_message("assistant"):
            render_answer(entry)

    with st.form("ask_form", clear_on_submit=True):
        question = st.text_area("Your question or topic", placeholder="e.g. What are the two stages of photosynthesis?")
        col1, col2 = st.columns([3, 1])
        submitted = col1.form_submit_button("Ask StudyMate", type="primary", use_container_width=True)
        cleared = col2.form_submit_button("Clear conversation", use_container_width=True)

    if cleared:
        ss.history, ss.study_agent = [], None
        st.rerun()
    if submitted:
        if not question.strip():
            st.warning("Please type a question first.")
            return
        entry = {"q": question.strip(), "mode": mode, "answer": None, "error": None}
        try:
            with st.spinner("Searching your notes and thinking..."):
                entry["answer"] = ask_study(get_study_agent(), question, mode, n_q)
        except AgentCallError as exc:
            entry["error"] = str(exc)
        ss.history.append(entry)
        st.rerun()


def tab_compare() -> None:
    st.markdown(
        "### Before vs. after adding the tool\n"
        "Both agents use the **same AI model**. The only difference: the right-hand agent has the "
        "`search_study_notes` tool. Load the sample notes first, then ask something about them."
    )
    q = st.text_input("Question", value="According to my notes, where in the chloroplast does the Calvin cycle occur?")
    if st.button("▶ Run both agents", type="primary"):
        left, right = st.columns(2)
        with left:
            st.subheader("❌ Before: no tool")
            try:
                with st.spinner("Baseline agent thinking..."):
                    st.write(ask_baseline(get_baseline_agent(), q))
            except AgentCallError as exc:
                st.error(str(exc))
        with right:
            st.subheader("✅ After: with notes tool")
            try:
                with st.spinner("Searching notes and thinking..."):
                    ans = ask_study(build_study_agent(st.session_state.index), q, "Just answer")
                render_answer({"error": None, "answer": ans})
            except AgentCallError as exc:
                st.error(str(exc))


def tab_retrieval() -> None:
    st.markdown(
        "### Retrieval test (no AI, no AWS charges)\n"
        "This runs only the search that the agent's tool uses, so you can check that your PDFs "
        "were read correctly."
    )
    query = st.text_input("Search keywords", value="Calvin cycle stroma")
    top_k = st.slider("Results", 1, 8, 4)
    if st.button("🔎 Search"):
        text, hits = run_search(st.session_state.index, query, top_k)
        if not hits:
            st.warning(text)
        for h in hits:
            st.markdown(f"**{h.chunk.doc}, page {h.chunk.page}** · score {h.score:.2f}")
            st.caption(h.chunk.text)


init_state()
render_sidebar()
t1, t2, t3 = st.tabs(["💬 Ask StudyMate", "🔬 Before vs. After", "🔎 Retrieval test"])
with t1:
    tab_ask()
with t2:
    tab_compare()
with t3:
    tab_retrieval()
