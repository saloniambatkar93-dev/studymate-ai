"""The AI agents: a BASELINE agent (no tools) and the STUDY agent (with the retrieval tool)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from strands import Agent
from strands.models import BedrockModel

from errors import friendly_aws_message
from tools import NotesIndex, RetrievalLog, create_search_tool

# Same default the Strands SDK uses. Confirm it is enabled for you in the Bedrock console,
# or set BEDROCK_MODEL_ID in .env to any model you have access to.
DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-6"

BASELINE_PROMPT = (
    "You are StudyMate AI, a friendly study assistant. You have NO tools and you CANNOT see, open "
    "or search any of the student's files or notes. If the student asks about their notes or "
    "documents, say clearly that you cannot access them, and offer a general-knowledge answer "
    "that is clearly labelled as general knowledge. Keep answers short and clear."
)

STUDY_PROMPT = """You are StudyMate AI, a friendly study assistant with ONE tool: search_study_notes, \
which searches the student's uploaded study notes and returns passages with document names and page numbers.

Rules:
1. For any question about the student's course material, call search_study_notes FIRST. If the first \
results are weak, search again with different keywords.
2. Base your answer ONLY on the passages the tool returned. After each key point, cite the source \
like (Source: file.pdf, p. 3). Use the exact file names and page numbers from the tool output.
3. If the tool returns NO_DOCUMENTS, NO_RELEVANT_PASSAGES or RETRIEVAL_ERROR, say so plainly. Never \
claim to have read notes you did not retrieve and never invent page numbers. You may offer a general-\
knowledge answer only if you label it clearly as NOT from the student's notes.
4. Write for a student: clear, accurate, and well organised."""

MODES = {
    "Explain simply": (
        "Explain this in simple language for a beginner. Use short paragraphs and, if the notes "
        "support it, one easy example or analogy."
    ),
    "Exam answer": (
        "Write a well-structured exam answer: a one-sentence definition, the key points as a "
        "numbered list, and a one-sentence conclusion. About 150-200 words."
    ),
    "Multiple-choice quiz": (
        "Create {n} multiple-choice questions (options A-D, one correct answer) based only on the "
        "notes. After all questions, add an 'Answer key' with the correct letter and a one-line "
        "explanation each."
    ),
    "Just answer": "Answer the question directly and concisely.",
}


class AgentCallError(Exception):
    """Raised with a friendly message when the AI model cannot be reached or fails."""


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


def build_user_prompt(question: str, mode: str, num_questions: int = 5) -> str:
    style = MODES.get(mode, MODES["Just answer"]).format(n=num_questions)
    return f"Style: {style}\n\nStudent request: {question.strip()}"


def explain_agent_error(exc: BaseException) -> str:
    aws = friendly_aws_message(exc)
    if aws:
        return aws
    name = type(exc).__name__
    if name == "ModelThrottledException":
        return "The AI model is busy (throttled). Wait a few seconds and try again."
    if name == "ContextWindowOverflowException":
        return "This conversation has become too long. Click 'Clear conversation' and ask again."
    if name == "MaxTokensReachedException":
        return "The answer was cut off because it was too long. Ask for something shorter."
    return f"The AI agent hit an unexpected problem ({name}): {str(exc)[:300]}"


def build_model() -> BedrockModel:
    try:
        return BedrockModel(
            model_id=os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
            region_name=os.getenv("AWS_REGION") or None,
            temperature=0.3,
            max_tokens=int(os.getenv("BEDROCK_MAX_TOKENS", "1500")),
        )
    except Exception as exc:
        raise AgentCallError(explain_agent_error(exc)) from exc


def build_baseline_agent() -> Agent:
    """The ORIGINAL agent: just the model, no tools. Used for the 'before' demo."""
    return Agent(model=build_model(), system_prompt=BASELINE_PROMPT, callback_handler=None)


@dataclass
class StudyAgent:
    agent: Agent
    log: RetrievalLog


def build_study_agent(index: NotesIndex) -> StudyAgent:
    """The IMPROVED agent: same model plus the search_study_notes tool."""
    log = RetrievalLog()
    tool_fn = create_search_tool(index, log)
    agent = Agent(model=build_model(), system_prompt=STUDY_PROMPT, tools=[tool_fn], callback_handler=None)
    return StudyAgent(agent=agent, log=log)


def ask_baseline(agent: Agent, question: str) -> str:
    try:
        return str(agent(question)).strip()
    except Exception as exc:
        raise AgentCallError(explain_agent_error(exc)) from exc


def ask_study(study: StudyAgent, question: str, mode: str = "Just answer", num_questions: int = 5) -> Answer:
    study.log.clear()
    try:
        result = study.agent(build_user_prompt(question, mode, num_questions))
    except Exception as exc:
        raise AgentCallError(explain_agent_error(exc)) from exc

    seen: set[tuple[str, int]] = set()
    sources: list[SourceRef] = []
    for hit in study.log.hits:  # only sources the tool REALLY returned
        key = (hit.chunk.doc, hit.chunk.page)
        if key not in seen:
            seen.add(key)
            snippet = hit.chunk.text if len(hit.chunk.text) <= 300 else hit.chunk.text[:297] + "..."
            sources.append(SourceRef(hit.chunk.doc, hit.chunk.page, snippet))
    return Answer(
        text=str(result).strip(),
        sources=sources,
        queries=list(study.log.queries),
        tool_used=bool(study.log.queries),
        passages_retrieved=len(study.log.hits),
    )
