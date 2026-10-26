import pytest

from storage import LocalStore, StorageError
from tests.pdf_factory import build_simple_pdf
from tools import (
    ExtractionError, NotesIndex, RetrievalLog, chunk_page, create_search_tool, extract_pages,
    run_search, tokenize,
)


# ---------- reading documents
def test_pdf_pages_keep_real_page_numbers():
    pdf = build_simple_pdf(["Page one about cells.", "", "Page three about atoms."])
    pages = extract_pages("notes.pdf", pdf)
    assert [n for n, _ in pages] == [1, 3]  # blank page 2 skipped, numbering preserved
    assert "atoms" in pages[1][1]


def test_corrupt_pdf_gives_friendly_error():
    with pytest.raises(ExtractionError):
        extract_pages("bad.pdf", b"%PDF-1.4 this is not really a pdf")


def test_pdf_without_text_is_rejected():
    with pytest.raises(ExtractionError, match="no selectable text"):
        extract_pages("scan.pdf", build_simple_pdf([""]))


def test_txt_page_markers():
    pages = extract_pages("a.txt", b"--- page 1 ---\nalpha\n--- page 2 ---\nbeta")
    assert [n for n, _ in pages] == [1, 2]


def test_unsupported_type():
    with pytest.raises(ExtractionError):
        extract_pages("a.docx", b"x")


# ---------- chunking and tokenizing
def test_long_page_is_split_into_chunks():
    text = " ".join(f"word{i}" for i in range(400))
    chunks = chunk_page("d.pdf", 2, text)
    assert len(chunks) >= 3
    assert all(len(c.text.split()) <= 140 and c.page == 2 for c in chunks)


def test_tokenize_drops_stopwords_and_plurals():
    assert tokenize("What are the Laws of Motion?") == ["law", "motion"]


# ---------- search quality on the sample notes
def test_search_finds_correct_document_and_page(sample_index):
    top = sample_index.search("Where does the Calvin cycle occur in the chloroplast?")[0]
    assert (top.chunk.doc, top.chunk.page) == ("biology_photosynthesis.txt", 2)

    top = sample_index.search("what is inertia")[0]
    assert (top.chunk.doc, top.chunk.page) == ("physics_newtons_laws.txt", 1)

    top = sample_index.search("spinning jenny inventor")[0]
    assert top.chunk.doc == "history_industrial_revolution.txt"


def test_search_unrelated_query_returns_nothing(sample_index):
    assert sample_index.search("quantum chromodynamics gluon") == []


def test_empty_query_returns_nothing(sample_index):
    assert sample_index.search("the of and") == []


# ---------- the tool output the AI sees
def test_run_search_formats_sources(sample_index):
    text, hits = run_search(sample_index, "photosynthesis equation glucose", 2)
    assert hits
    assert "Source: biology_photosynthesis.txt, page 1" in text


def test_run_search_no_documents(store):
    text, hits = run_search(NotesIndex(store), "anything")
    assert text.startswith("NO_DOCUMENTS") and hits == []


def test_run_search_no_match_does_not_invent(sample_index):
    text, hits = run_search(sample_index, "quantum chromodynamics")
    assert text.startswith("NO_RELEVANT_PASSAGES") and hits == []


def test_run_search_reports_storage_failure():
    class Broken:
        def list_documents(self):
            raise StorageError("AWS credentials were not found.")

    text, hits = run_search(NotesIndex(Broken()), "x")
    assert text.startswith("RETRIEVAL_ERROR") and "credentials" in text and hits == []


def test_run_search_handles_bad_max_results(sample_index):
    text, hits = run_search(sample_index, "inertia", max_results="abc")
    assert hits


# ---------- the real Strands tool object
def test_strands_tool_records_activity(sample_index):
    log = RetrievalLog()
    tool_fn = create_search_tool(sample_index, log)
    assert tool_fn.tool_name == "search_study_notes"
    spec = tool_fn.tool_spec
    assert "query" in spec["inputSchema"]["json"]["properties"]
    out = tool_fn("Newton second law force mass acceleration")  # decorated function stays callable
    assert "physics_newtons_laws.txt" in out
    assert log.queries and log.hits


# ---------- index behaviour with real PDFs
def test_index_reads_uploaded_pdf_and_detects_changes(tmp_path):
    store = LocalStore(tmp_path)
    store.save_document("bio.pdf", build_simple_pdf(["Mitochondria produce ATP.", "Ribosomes build proteins."]))
    index = NotesIndex(store)
    index.refresh()
    top = index.search("ribosomes proteins")[0]
    assert (top.chunk.doc, top.chunk.page) == ("bio.pdf", 2)

    store.save_document("bio.pdf", build_simple_pdf(["Lysosomes digest waste."]))
    index.refresh()
    assert index.search("lysosomes")[0].chunk.page == 1
    assert index.search("ribosomes") == []


def test_bad_pdf_is_reported_not_crashing(tmp_path):
    store = LocalStore(tmp_path)
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4 junk")
    index = NotesIndex(store)
    index.refresh()
    assert "broken.pdf" in index.errors
    assert index.document_names == []
