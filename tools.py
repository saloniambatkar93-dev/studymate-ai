"""Document reading, search (retrieval) and the custom Strands tool.

How retrieval works (deliberately simple and honest):
  1. Read each document page by page (PDFs with selectable text; no OCR).
  2. Cut each page into small chunks (~140 words).
  3. Rank chunks against the question using BM25, a classic KEYWORD scoring method.
This is keyword search, not semantic/embedding search, so it works best when the question
shares words with the notes. It needs no paid AWS service.
"""
from __future__ import annotations

import io
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from strands import tool

from storage import StorageError

MAX_CHUNK_WORDS = 140
CHUNK_OVERLAP_WORDS = 20
MAX_RESULTS_LIMIT = 8

STOPWORDS = frozenset(
    """a about above after again all also am an and any are as at be because been before being
    below between both but by can could did do does doing down during each few for from further
    had has have having he her here hers him his how i if in into is it its just me more most my
    no nor not of off on once only or other our out over own same she should so some such than
    that the their them then there these they this those through to too under until up very was
    we were what when where which while who whom why will with would you your tell explain
    describe notes note please""".split()
)


class ExtractionError(Exception):
    """A document could not be read. The message is safe to show to the user."""


@dataclass(frozen=True)
class Chunk:
    doc: str
    page: int
    text: str


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


@dataclass
class RetrievalLog:
    """Records what the tool really did during one question (used for honest source display)."""

    queries: list[str] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)

    def clear(self) -> None:
        self.queries.clear()
        self.hits.clear()


# --------------------------------------------------------------------------- reading documents
_PAGE_MARKER = re.compile(r"^\s*---\s*page\s+(\d+)\s*---\s*$", re.IGNORECASE | re.MULTILINE)


def extract_pages(name: str, data: bytes) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] for pages that contain text."""
    lower = name.lower()
    if lower.endswith(".pdf"):
        pages = _extract_pdf(name, data)
    elif lower.endswith(".txt"):
        pages = _extract_txt(data)
    else:
        raise ExtractionError(f"'{name}': unsupported file type.")
    pages = [(n, t) for n, t in pages if t.strip()]
    if not pages:
        raise ExtractionError(
            f"'{name}' has no selectable text. It may be a scanned/image-only PDF "
            "(this app does not do OCR). Try a PDF exported from Word, Google Docs or similar."
        )
    return pages


def _extract_pdf(name: str, data: bytes) -> list[tuple[int, str]]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:
                ok = 0
            if not ok:
                raise ExtractionError(f"'{name}' is password-protected. Remove the password and upload again.")
        return [(i, page.extract_text() or "") for i, page in enumerate(reader.pages, start=1)]
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"'{name}' could not be read as a PDF ({type(exc).__name__}). The file may be damaged.") from exc


def _extract_txt(data: bytes) -> list[tuple[int, str]]:
    text = data.decode("utf-8", errors="replace")
    parts = _PAGE_MARKER.split(text)  # [before, "1", text1, "2", text2, ...]
    if len(parts) == 1:
        return [(1, text)]
    pages = [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    if parts[0].strip():
        pages.insert(0, (1, parts[0]))
    return pages


# --------------------------------------------------------------------------- chunking
def chunk_page(doc: str, page: int, text: str) -> list[Chunk]:
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        words = paragraph.split()
        if not words:
            continue
        if len(words) <= MAX_CHUNK_WORDS:
            pieces.append(" ".join(words))
            continue
        step = MAX_CHUNK_WORDS - CHUNK_OVERLAP_WORDS
        for start in range(0, len(words), step):
            window = words[start:start + MAX_CHUNK_WORDS]
            pieces.append(" ".join(window))
            if start + MAX_CHUNK_WORDS >= len(words):
                break
    # Merge neighbouring small pieces so chunks aren't tiny
    merged: list[str] = []
    for piece in pieces:
        if merged and len(merged[-1].split()) + len(piece.split()) <= MAX_CHUNK_WORDS:
            merged[-1] += " " + piece
        else:
            merged.append(piece)
    return [Chunk(doc, page, m) for m in merged]


# --------------------------------------------------------------------------- search index
def _normalise(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [_normalise(w) for w in words if len(w) > 1 and w not in STOPWORDS]


class NotesIndex:
    """Keeps a searchable index of every document in a store (re-reads only changed files)."""

    K1 = 1.5
    B = 0.75

    def __init__(self, store):
        self.store = store
        self._versions: dict[str, str] = {}
        self._chunks_by_doc: dict[str, list[Chunk]] = {}
        self._pages_by_doc: dict[str, int] = {}
        self.errors: dict[str, str] = {}
        self._chunks: list[Chunk] = []
        self._tfs: list[Counter] = []
        self._lengths: list[int] = []
        self._df: Counter = Counter()
        self._avg_len = 0.0

    def refresh(self) -> None:
        """Sync with the store. May raise StorageError (e.g. AWS problem)."""
        infos = self.store.list_documents()
        current = {d.name: d.version for d in infos}
        changed = False
        for name in list(self._versions):
            if name not in current:
                for d in (self._versions, self._chunks_by_doc, self._pages_by_doc, self.errors):
                    d.pop(name, None)
                changed = True
        for info in infos:
            if self._versions.get(info.name) == info.version:
                continue
            changed = True
            self._versions[info.name] = info.version
            self._chunks_by_doc.pop(info.name, None)
            self.errors.pop(info.name, None)
            try:
                pages = extract_pages(info.name, self.store.load_document(info.name))
            except ExtractionError as exc:
                self.errors[info.name] = str(exc)
                continue
            chunks = [c for n, t in pages for c in chunk_page(info.name, n, t)]
            self._chunks_by_doc[info.name] = chunks
            self._pages_by_doc[info.name] = len(pages)
        if changed:
            self._rebuild()

    def _rebuild(self) -> None:
        self._chunks = [c for name in sorted(self._chunks_by_doc) for c in self._chunks_by_doc[name]]
        self._tfs = [Counter(tokenize(c.text)) for c in self._chunks]
        self._lengths = [sum(tf.values()) for tf in self._tfs]
        self._df = Counter(term for tf in self._tfs for term in tf)
        self._avg_len = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0

    @property
    def document_names(self) -> list[str]:
        return sorted(self._chunks_by_doc)

    def summary(self) -> list[dict]:
        rows = [
            {"name": n, "pages": self._pages_by_doc[n], "chunks": len(self._chunks_by_doc[n]), "error": None}
            for n in self.document_names
        ]
        rows += [{"name": n, "pages": 0, "chunks": 0, "error": e} for n, e in sorted(self.errors.items())]
        return rows

    def search(self, query: str, top_k: int = 4) -> list[Hit]:
        terms = set(tokenize(query))
        if not terms or not self._chunks:
            return []
        n_docs = len(self._chunks)
        scored: list[Hit] = []
        for i, tf in enumerate(self._tfs):
            score = 0.0
            for term in terms:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                idf = math.log(1 + (n_docs - self._df[term] + 0.5) / (self._df[term] + 0.5))
                denom = freq + self.K1 * (1 - self.B + self.B * self._lengths[i] / (self._avg_len or 1))
                score += idf * freq * (self.K1 + 1) / denom
            if score > 0:
                scored.append(Hit(self._chunks[i], score))
        scored.sort(key=lambda h: h.score, reverse=True)
        if not scored:
            return []
        best = scored[0].score
        return [h for h in scored[:top_k] if h.score >= 0.2 * best]


# --------------------------------------------------------------------------- the agent tool
def run_search(index: NotesIndex, query: str, max_results: int = 4) -> tuple[str, list[Hit]]:
    """Search the notes. Returns (text_for_the_AI, hits). Never raises: problems become text."""
    try:
        max_results = max(1, min(int(max_results), MAX_RESULTS_LIMIT))
    except (TypeError, ValueError):
        max_results = 4
    try:
        index.refresh()
    except StorageError as exc:
        return (f"RETRIEVAL_ERROR: the notes could not be accessed. {exc} "
                "Tell the student this plainly. Do not pretend to have read any notes."), []
    if not index.document_names:
        return ("NO_DOCUMENTS: the student has not uploaded any readable study documents yet. "
                "Tell them to upload a PDF in the sidebar. Do not invent notes."), []
    hits = index.search(query, max_results)
    if not hits:
        return (f"NO_RELEVANT_PASSAGES: nothing in the uploaded notes matched '{query}'. "
                "Tell the student the notes don't seem to cover this, and suggest rephrasing. "
                "Do not invent notes."), []
    blocks = [f"[{i}] Source: {h.chunk.doc}, page {h.chunk.page}\n{h.chunk.text}" for i, h in enumerate(hits, 1)]
    return "Passages from the student's uploaded notes:\n\n" + "\n\n".join(blocks), hits


def create_search_tool(index: NotesIndex, log: RetrievalLog):
    """Build the Strands tool. `log` records real tool activity so the UI can show true sources."""

    @tool
    def search_study_notes(query: str, max_results: int = 4) -> str:
        """Search the student's uploaded study notes (PDFs) for passages relevant to a topic.

        Use this FIRST for any question about the student's course material. It returns the most
        relevant passages with the document name and page number. Use short keyword queries
        (for example "photosynthesis light reactions"). Call it again with different keywords
        if the first results are not enough.

        Args:
            query: Short keywords describing the topic to look up in the notes.
            max_results: How many passages to return (1 to 8). Default 4.
        """
        text, hits = run_search(index, query, max_results)
        log.queries.append(query)
        log.hits.extend(hits)
        return text

    return search_study_notes
