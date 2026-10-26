"""StudyMate AI agents powered by Google Gemini."""

from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st
from strands import Agent
from strands.models.gemini import GeminiModel

from tools import NotesIndex, RetrievalLog, run_search


DEFAULT_MODEL_ID = "gemini-3.6-flash"

BASELINE_PROMPT = """
You are StudyMate AI, a friendly study assistant.
You do not have access to the student's notes or files.
Answer using general knowledge and keep answers clear and concise.
"""

STUDY_PROMPT = """
You are StudyMate AI, a friendly study assistant.
Answer the student's question using the supplied passages from their notes.

Rules:
1. Treat the supplied passages as the source of truth about the notes.
2. Cite sources using the exact document name and page number,
   for example (Source: notes.pdf, p. 3).
3. Never invent document names, page numbers, or note contents.
4. If the passages do not contain the answer, say so honestly.
5. You may add general knowledge only when clearly labelled as such.
6. Use simple, clear language.
"""

MODES = {
    "Explain simply": (
        "Explain the topic in simple language for a beginner. "
        "Use short paragraphs and one easy example if appropriate."
    ),
    "Exam answer": (
        "Write a structured exam answer with a definition, numbered "
        "key points, and a short conclusion. Aim for 150-200 words."
    ),
    "Multiple-choice quiz": (
        "Create {n} multiple-choice questions based only on the supplied "
        "notes. Give four options (A-D) for each question. Include an "
        "answer key with a short explanation after all questions."
    ),
    "Just answer": "Answer the question directly and concisely using the notes.",
}


class AgentCallError(Exception):
    """An understandable error raised when an AI request fails."""


@dataclass(frozen=True)
class SourceRef:
    doc: str
    page: int
    snippet: str


@dataclass
class Answer:
    text: str
    sources: list[SourceRef]
    queries: list[str]
    tool_used: bool
    passages_retrieved: int


def get_api_key() -> str:
    """Read the Gemini API key from environment variables or Streamlit Secrets."""
    key = os.getenv("GEMINI_API_KEY", "").strip()

    if not key:
        try:
            key = str(st.secrets.get("GEMINI_API_KEY", "")).strip()
        except Exception:
            key = ""

    if not key:
        raise AgentCallError(
            "Gemini API key not found. Add GEMINI_API_KEY to "
            "Streamlit Settings → Secrets."
        )

    return key


def build_model() -> GeminiModel:
    """Create a Gemini model without requiring AWS credentials."""
    try:
        return GeminiModel(
            client_args={"api_key": get_api_key()},
            model_id=os.getenv("GEMINI_MODEL_ID", DEFAULT_MODEL_ID),
           params={"temperature": 0.3, "max_output_tokens": 4096},
        )
    except AgentCallError:
        raise
    except Exception as exc:
        raise AgentCallError(
            f"Could not configure Gemini ({type(exc).__name__}): {str(exc)[:250]}"
        ) from exc


def build_user_prompt(
    question: str,
    mode: str,
    num_questions: int = 5,
    passages: str = "",
) -> str:
    style = MODES.get(mode, MODES["Just answer"]).format(n=num_questions)

    return (
        f"Answer style: {style}\n\n"
        f"Student question: {question.strip()}\n\n"
        "Retrieved passages from the student's notes:\n"
        f"{passages or 'No relevant passages were found.'}\n\n"
        "If no passages were found, do not pretend that you read the notes. "
        "Explain that the notes search did not find relevant information."
    )


def build_baseline_agent() -> Agent:
    """Create the baseline agent without access to notes."""
    return Agent(
        model=build_model(),
        system_prompt=BASELINE_PROMPT,
        callback_handler=None,
    )


@dataclass
class StudyAgent:
    agent: Agent
    log: RetrievalLog
    index: NotesIndex


def build_study_agent(index: NotesIndex) -> StudyAgent:
    """Create the study agent; retrieval is performed directly by ask_study."""
    return StudyAgent(agent=Agent(
        model=build_model(),
        system_prompt=STUDY_PROMPT,
        callback_handler=None,
    ), log=RetrievalLog(), index=index)


def ask_baseline(agent: Agent, question: str) -> str:
    try:
        return str(agent(question)).strip()
    except Exception as exc:
        raise AgentCallError(
            f"Gemini request failed ({type(exc).__name__}): {str(exc)[:250]}"
        ) from exc


def ask_study(
    study: StudyAgent,
    question: str,
    mode: str = "Just answer",
    num_questions: int = 5,
) -> Answer:
    study.log.clear()

    # Search notes directly before asking Gemini to answer.
    try:
        passages, hits = run_search(study.index, question, max_results=4)
    except Exception as exc:
        raise AgentCallError(
            f"Notes search failed ({type(exc).__name__}): {str(exc)[:200]}"
        ) from exc

    study.log.queries.append(question)
    study.log.hits.extend(hits)

    seen = set()
    sources = []

    for hit in hits:
        key = (hit.chunk.doc, hit.chunk.page)
        if key not in seen:
            seen.add(key)
            snippet = hit.chunk.text
            if len(snippet) > 300:
                snippet = snippet[:297] + "..."
            sources.append(SourceRef(hit.chunk.doc, hit.chunk.page, snippet))

    # Do not send a Gemini request when the notes search found no passages.
    if not hits:
        return Answer(
            text=(
                "I couldn't find relevant information in your uploaded notes "
                "for this question. Try using keywords from your notes, or "
                "check that the correct PDF has been uploaded.\n\n"
                "Search result: " + passages
            ),
            sources=[],
            queries=list(study.log.queries),
            tool_used=True,
            passages_retrieved=0,
        )

    prompt = build_user_prompt(question, mode, num_questions, passages)

    try:
        result = study.agent(prompt)
    except Exception as exc:
        raise AgentCallError(
            f"Gemini request failed ({type(exc).__name__}): {str(exc)[:250]}"
        ) from exc

    return Answer(
        text=str(result).strip(),
        sources=sources,
        queries=list(study.log.queries),
        tool_used=True,
        passages_retrieved=len(hits),
    )
