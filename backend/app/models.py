"""Data models for the Agentic RAG system.

Agent-state and per-request settings live in ``app.agent_state`` — this
module is purely the domain dataclasses used by the engine, storage, and
retrieval layers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from langchain_core.documents import Document


# ---------------------------------------------------------------------------
# Response format — matches VALID_FORMATS in rag_engine.py
# ---------------------------------------------------------------------------
ResponseFormat = Literal[
    "paragraph",
    "table",
    "bullet_list",
    "numbered_list",
    "code",
]


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------
@dataclass
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


# ---------------------------------------------------------------------------
# Documents / indexing
# ---------------------------------------------------------------------------
@dataclass
class DocumentRecord:
    id: str
    name: str
    status: Literal["processing", "ready", "error"] = "processing"
    pages: int = 0
    chunks: int = 0
    error: str = ""
    file_hash: str = ""   # content hash for deduplication


# ---------------------------------------------------------------------------
# Agent decisions & activity
# ---------------------------------------------------------------------------
@dataclass
class AgentDecision:
    needs_retrieval: bool
    response_format: ResponseFormat
    search_query: str
    decision_summary: str
    rewritten_question: str
    is_broad_query: bool = False


@dataclass
class EvaluationResult:
    is_sufficient: bool
    summary: str


@dataclass
class VerificationResult:
    """Outcome of verifying a generated answer.

    Required fields (used by the pipeline):
        passed              — overall verdict
        summary             — one-line reason
        unsupported_claims  — list of specific unsupported sentences

    Optional fields (trainer shape — populated by ``verify_answer`` when
    available, defaulted otherwise):
        is_grounded         — heuristic pass signal
        confidence          — blended retrieval + token-overlap score
        abstain             — whether the caller should abstain
        abstain_reason      — human-readable reason when abstaining
    """

    passed: bool
    summary: str
    unsupported_claims: list[str] = field(default_factory=list)
    # Trainer-shape optional fields
    is_grounded: bool = False
    confidence: float = 0.0
    abstain: bool = False
    abstain_reason: Optional[str] = None


@dataclass
class ActivityStep:
    state: str
    status: Literal["running", "complete", "failed"] = "complete"
    summary: str = ""
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    answer: str
    sources: list[Document]
    activity: list[ActivityStep]
    response_format: ResponseFormat = "paragraph"
    insufficient_evidence: bool = False


# ---------------------------------------------------------------------------
# Retrieval primitives — consumed by retrieval.py, verification.py,
# citations.py. Field names must match the call sites in those modules.
# ---------------------------------------------------------------------------
@dataclass
class Chunk:
    """A single retrieved chunk with provenance and score.

    ``text`` (not ``page_content``) is the field name because
    verification.py's ``estimate_grounding`` and citations.py's
    ``_make_quote`` both read ``c.text``.
    """

    chunk_id: str
    document_id: str
    filename: str
    page: Optional[int]
    text: str
    score: float = 0.0


@dataclass
class RetrievalResult:
    """Bundle returned by VectorStore.query().

    ``chunks`` is the ordered list (highest score first); ``query`` is
    echoed back for logging / traces.
    """

    query: str
    chunks: list[Chunk] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.chunks


# ---------------------------------------------------------------------------
# Citation — engine-side (dataclass). The API-side Pydantic model with the
# same name lives in schemas.py; import sites are explicit.
# ---------------------------------------------------------------------------
@dataclass
class Citation:
    document_id: str
    filename: str
    page: Optional[int]
    chunk_id: str
    quote: str
    score: float = 0.0


__all__ = [
    "ResponseFormat",
    "ChatMessage",
    "DocumentRecord",
    "AgentDecision",
    "EvaluationResult",
    "VerificationResult",
    "ActivityStep",
    "AgentResult",
    "Chunk",
    "RetrievalResult",
    "Citation",
]