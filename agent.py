"""StudyMate AI agents powered by Google Gemini."""

from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st
from strands import Agent
from strands.models.gemini import GeminiModel

from tools import NotesIndex, RetrievalLog, create_search_tool


DEFAULT_MODEL_ID = "gemini-3.8-flash"

BASELINE_PROMPT = """
You are StudyMate AI, a friendly study assistant.
You do not have access to the student's notes or files.
If asked about their notes, explain that you cannot access them.
You may provide a general-knowledge answer, clearly labelled as such.
Keep answers clear and concise.
"""

STUDY_PROMPT = """
You are StudyMate AI, a friendly study assistant with one custom tool:
search_study_notes.

Rules:
1. For questions about the student's course material, use
   search_study_notes FIRST.
2. Base answers about the notes ONLY on passages returned by the tool.
3. Cite sources using the exact document name and page number,
   for example (Source: notes.pdf, p. 3).
4. If no relevant passages are found, say so honestly.
   Never invent document names, page numbers, or note contents.
5. You may provide general knowledge only when clearly labelled
   as not coming from the student's notes.
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
        "Create {n} multiple-choice questions based only on the notes. "
        "Give four options (A-D) for each question. Include an answer "
        "key with a short explanation after all questions."
    ),
    "Just answer": (
        "Answer the question directly and concisely using the notes."
    ),
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
            params={
                "temperature": 0.3,
                "max_output_tokens": 1500,
            },
        )
    except AgentCallError:
        raise
    except Exception as exc:
        raise AgentCallError(
            f"Could not configure Gemini ({type(exc).__name__}): "
            f"{str(exc)[:250]}"
        ) from exc


def build_user_prompt(
    question: str,
    mode: str,
    num_questions: int = 5,
) -> str:
    style = MODES.get(mode, MODES["Just answer"]).format(
        n=num_questions
    )
    return f"Answer style: {style}\n\nStudent request: {question.strip()}"


def build_baseline_agent() -> Agent:
    """Create the baseline agent without the notes-search tool."""

    return Agent(
        model=build_model(),
        system_prompt=BASELINE_PROMPT,
        callback_handler=None,
    )


@dataclass
class StudyAgent:
    agent: Agent
    log: RetrievalLog


def build_study_agent(index: NotesIndex) -> StudyAgent:
    """Create the study agent with the custom notes-search tool."""

    log = RetrievalLog()
    tool_fn = create_search_tool(index, log)

    agent = Agent(
        model=build_model(),
        system_prompt=STUDY_PROMPT,
        tools=[tool_fn],
        callback_handler=None,
    )

    return StudyAgent(agent=agent, log=log)


def ask_baseline(agent: Agent, question: str) -> str:
    try:
        return str(agent(question)).strip()
    except Exception as exc:
        raise AgentCallError(
            f"Gemini request failed ({type(exc).__name__}): "
            f"{str(exc)[:250]}"
        ) from exc


def ask_study(
    study: StudyAgent,
    question: str,
    mode: str = "Just answer",
    num_questions: int = 5,
) -> Answer:
    study.log.clear()

    try:
        result = study.agent(
            build_user_prompt(question, mode, num_questions)
        )
    except AgentCallError:
        raise
    except Exception as exc:
        raise AgentCallError(
            f"Gemini request failed ({type(exc).__name__}): "
            f"{str(exc)[:250]}"
        ) from exc

    seen = set()
    sources = []

    for hit in study.log.hits:
        key = (hit.chunk.doc, hit.chunk.page)

        if key not in seen:
            seen.add(key)
            snippet = hit.chunk.text

            if len(snippet) > 300:
                snippet = snippet[:297] + "..."

            sources.append(
                SourceRef(
                    doc=hit.chunk.doc,
                    page=hit.chunk.page,
                    snippet=snippet,
                )
            )

    return Answer(
        text=str(result).strip(),
        sources=sources,
        queries=list(study.log.queries),
        tool_used=bool(study.log.queries),
        passages_retrieved=len(study.log.hits),
    )
