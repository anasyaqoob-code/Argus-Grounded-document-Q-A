"""Per-request AgentSettings and the canonical agent state machine.

Finding #2 fix: global Settings must not be mutated by concurrent requests.
Each request builds an immutable AgentSettings snapshot from global defaults
plus optional query overrides.

This module is the single source of truth for:
  - ``AgentSettings``  — frozen per-request configuration
  - ``AgentStateName`` — the 10 states the pipeline traverses
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .config import Settings, get_settings


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
class AgentStateName(str, Enum):
    """Canonical state names for the deterministic 9-stage pipeline.

    ``REFINE`` is not part of the happy path — it only appears when EVALUATE
    decides the retrieved context is insufficient and a retry is warranted.
    """

    UNDERSTAND = "understand"
    DECIDE = "decide"
    PLAN = "plan"
    SEARCH = "search"
    OBSERVE = "observe"
    EVALUATE = "evaluate"
    REFINE = "refine"
    GENERATE = "generate"
    VERIFY = "verify"
    FINAL = "final"


# Backwards-compat alias for call sites that refer to it as ``AgentState``.
AgentState = AgentStateName


# ---------------------------------------------------------------------------
# Per-request settings
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AgentSettings:
    """Immutable per-request configuration for the agentic pipeline.

    Every field is set at construction; the engine treats this object as
    read-only. Do NOT add mutable defaults.
    """

    # ---- LLM (Groq) ----------------------------------------------------
    llm_model: str
    temperature: float
    max_tokens: int
    groq_api_key: Optional[str]
    groq_base_url: Optional[str]

    # ---- Embeddings (HuggingFace) --------------------------------------
    embedding_model: str

    # ---- Retrieval -----------------------------------------------------
    top_k: int
    score_threshold: float
    doc_relevance_floor: float
    max_context_tokens: int
    max_retrieval_attempts: int

    # ---- Chunking ------------------------------------------------------
    chunk_size: int
    chunk_overlap: int

    # ---- Memory --------------------------------------------------------
    memory_message_limit: int

    # ---- Agent behaviour toggles ---------------------------------------
    query_rewriting: bool
    answer_verification: bool
    source_citations: bool

    # ---- Verification / abstention -------------------------------------
    min_citation_coverage: float
    abstain_confidence_threshold: float
    require_citations: bool
    allow_abstain: bool

    # ---- Deprecated OpenAI aliases (kept for backward-compat) ----------
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def from_request(
        cls,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
        max_retrieval_attempts: Optional[int] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        memory_message_limit: Optional[int] = None,
        query_rewriting: Optional[bool] = None,
        answer_verification: Optional[bool] = None,
        source_citations: Optional[bool] = None,
        require_citations: Optional[bool] = None,
        allow_abstain: Optional[bool] = None,
        settings: Optional[Settings] = None,
    ) -> "AgentSettings":
        """Build an immutable snapshot from global Settings + overrides."""
        s = settings or get_settings()

        def pick(override, fallback):
            return override if override is not None else fallback

        return cls(
            # LLM
            llm_model=s.groq_model,
            temperature=pick(temperature, s.llm_temperature),
            max_tokens=pick(max_tokens, s.llm_max_tokens),
            groq_api_key=s.groq_api_key,
            groq_base_url=s.groq_base_url,
            # Embeddings
            embedding_model=s.huggingface_embedding_model,
            # Retrieval
            top_k=pick(top_k, s.top_k),
            score_threshold=pick(score_threshold, s.score_threshold),
            doc_relevance_floor=s.doc_relevance_floor,
            max_context_tokens=s.max_context_tokens,
            max_retrieval_attempts=pick(
                max_retrieval_attempts, s.max_retrieval_attempts
            ),
            # Chunking
            chunk_size=pick(chunk_size, s.chunk_size),
            chunk_overlap=pick(chunk_overlap, s.chunk_overlap),
            # Memory
            memory_message_limit=pick(
                memory_message_limit, s.memory_message_limit
            ),
            # Behaviour toggles
            query_rewriting=pick(query_rewriting, s.query_rewriting),
            answer_verification=pick(
                answer_verification, s.answer_verification
            ),
            source_citations=pick(source_citations, s.source_citations),
            # Verification / abstention
            min_citation_coverage=s.min_citation_coverage,
            abstain_confidence_threshold=s.abstain_confidence_threshold,
            # Fix: read from global Settings when present, else default True.
            # Previously these hardcoded to True, ignoring any config override.
            require_citations=pick(
                require_citations,
                getattr(s, "require_citations", True),
            ),
            allow_abstain=pick(
                allow_abstain,
                getattr(s, "allow_abstain", True),
            ),
            # Deprecated aliases
            openai_api_key=s.openai_api_key,
            openai_base_url=s.openai_base_url,
        )


__all__ = ["AgentStateName", "AgentState", "AgentSettings"]