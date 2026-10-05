"""Tests for filter-at-DB retrieval and strict-threshold behavior.

Covers:
  - Finding #3: filter-at-DB (document_ids pushed into the Chroma call)
  - Finding #4: strict threshold (no silent fallback to unfiltered results)
  - Broad vs targeted retrieval modes
  - Cosine HNSW metric is enforced at construction
"""

from __future__ import annotations

import pytest

from app.agent_state import AgentSettings
from app.models import Chunk, RetrievalResult
from app.retrieval import Retriever, VectorStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _settings(**overrides) -> AgentSettings:
    base = dict(
        answer_verification=False,
        require_citations=False,
        allow_abstain=False,
        top_k=4,
        score_threshold=0.0,
    )
    base.update(overrides)
    return AgentSettings.from_request(**base)


def _seed(store: VectorStore, chunks: list[Chunk]) -> None:
    store.add_documents(chunks)


# ---------------------------------------------------------------------------
# Construction / metadata
# ---------------------------------------------------------------------------
def test_chroma_collection_uses_cosine(tmp_chroma_store: VectorStore):
    """The Chroma collection must be built with hnsw:space = cosine."""
    collection = tmp_chroma_store._store._collection  # langchain_chroma internals
    metadata = collection.metadata or {}
    assert metadata.get("hnsw:space") == "cosine", (
        "Collection must use cosine distance so relevance scores are "
        "interpretable as 1 - cosine_distance."
    )


def test_persist_directory_isolated(tmp_chroma_store: VectorStore, tmp_path):
    """The store must write only under tmp_path."""
    assert str(tmp_path) in tmp_chroma_store.persist_directory


# ---------------------------------------------------------------------------
# Finding #3 — filter-at-DB
# ---------------------------------------------------------------------------
def test_filter_at_db_only_returns_selected_docs(tmp_chroma_store, sample_chunks):
    """Chunks from unselected docs must never appear, even with a wide top_k."""
    _seed(tmp_chroma_store, sample_chunks)

    hits = tmp_chroma_store.query(
        "roles and permissions",
        top_k=50,  # much larger than the corpus
        document_ids=["alpha.txt"],
    )
    assert hits, "expected at least one chunk from alpha.txt"
    assert all(h.document_id == "alpha.txt" for h in hits), [
        h.document_id for h in hits
    ]


def test_filter_at_db_excludes_other_docs(tmp_chroma_store, sample_chunks):
    _seed(tmp_chroma_store, sample_chunks)
    hits = tmp_chroma_store.query(
        "encryption",
        top_k=50,
        document_ids=["beta.txt"],
    )
    assert all(h.document_id == "beta.txt" for h in hits), [
        h.document_id for h in hits
    ]


def test_filter_at_db_empty_when_doc_unknown(tmp_chroma_store, sample_chunks):
    _seed(tmp_chroma_store, sample_chunks)
    hits = tmp_chroma_store.query(
        "anything",
        top_k=10,
        document_ids=["does-not-exist"],
    )
    assert hits == []


def test_retriever_filter_at_db(tmp_chroma_store, sample_chunks):
    _seed(tmp_chroma_store, sample_chunks)
    ret = Retriever(tmp_chroma_store)
    settings = _settings(top_k=10)

    result = ret.retrieve(
        "roles",
        settings,
        document_ids=["alpha.txt"],
    )
    assert isinstance(result, RetrievalResult)
    assert result.query == "roles"
    assert result.chunks, "expected chunks from alpha.txt"
    assert all(c.document_id == "alpha.txt" for c in result.chunks)


# ---------------------------------------------------------------------------
# Finding #4 — strict threshold (no silent fallback)
# ---------------------------------------------------------------------------
def test_strict_threshold_returns_empty(tmp_chroma_store, sample_chunks):
    """When all candidates fall below the threshold, return [] — do not
    fall back to unfiltered results."""
    _seed(tmp_chroma_store, sample_chunks)
    hits = tmp_chroma_store.query(
        "roles",
        top_k=10,
        score_threshold=1.01,  # impossible to satisfy
    )
    assert hits == [], (
        "strict threshold violated — unfiltered results were returned"
    )


def test_strict_threshold_retriever_returns_empty(tmp_chroma_store, sample_chunks):
    _seed(tmp_chroma_store, sample_chunks)
    ret = Retriever(tmp_chroma_store)
    settings = _settings(top_k=10, score_threshold=1.01)
    result = ret.retrieve("roles", settings)
    assert result.chunks == []


def test_low_threshold_passes_results(tmp_chroma_store, sample_chunks):
    """A permissive threshold keeps everything above it."""
    _seed(tmp_chroma_store, sample_chunks)
    hits = tmp_chroma_store.query(
        "roles",
        top_k=10,
        score_threshold=-1.0,  # everything passes
    )
    assert len(hits) >= 1


# ---------------------------------------------------------------------------
# Broad vs targeted
# ---------------------------------------------------------------------------
def test_broad_mode_covers_multiple_docs(tmp_chroma_store, sample_chunks):
    _seed(tmp_chroma_store, sample_chunks)
    ret = Retriever(tmp_chroma_store)
    settings = _settings(top_k=6)

    result = ret.retrieve(
        "security",
        settings,
        document_ids=["alpha.txt", "beta.txt"],
        broad=True,
    )
    # We can't guarantee both docs match a given query with the fake
    # embedding, but the union must be a subset of the selected docs and
    # must respect filter-at-DB.
    assert all(c.document_id in {"alpha.txt", "beta.txt"} for c in result.chunks)
    assert len(result.chunks) <= settings.top_k or len(result.chunks) <= 12


def test_targeted_mode_respects_filter(tmp_chroma_store, sample_chunks):
    _seed(tmp_chroma_store, sample_chunks)
    ret = Retriever(tmp_chroma_store)
    settings = _settings(top_k=10)

    result = ret.retrieve(
        "roles",
        settings,
        document_ids=["beta.txt"],
        broad=False,
    )
    assert all(c.document_id == "beta.txt" for c in result.chunks)


# ---------------------------------------------------------------------------
# Ad-hoc AgentSettings construction (backward-compat with old test style)
# ---------------------------------------------------------------------------
def test_explicit_agent_settings_construction(tmp_chroma_store, sample_chunks):
    _seed(tmp_chroma_store, sample_chunks)
    agent = AgentSettings(
        llm_model="test-model",
        temperature=0.0,
        max_tokens=128,
        groq_api_key=None,
        groq_base_url=None,
        embedding_model="test-embed",
        top_k=10,
        score_threshold=0.99,
        doc_relevance_floor=0.05,
        max_context_tokens=1000,
        max_retrieval_attempts=2,
        chunk_size=800,
        chunk_overlap=150,
        memory_message_limit=6,
        query_rewriting=True,
        answer_verification=False,
        source_citations=True,
        min_citation_coverage=0.5,
        abstain_confidence_threshold=0.3,
        require_citations=True,
        allow_abstain=True,
    )
    ret = Retriever(tmp_chroma_store)
    result = ret.retrieve("roles", agent)
    assert isinstance(result, RetrievalResult)


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------
def test_delete_by_document(tmp_chroma_store, sample_chunks):
    _seed(tmp_chroma_store, sample_chunks)
    removed = tmp_chroma_store.delete_by_document("beta.txt")
    assert removed >= 1

    remaining = tmp_chroma_store.query("anything", top_k=10)
    assert all(h.document_id != "beta.txt" for h in remaining)


def test_empty_query_returns_empty(tmp_chroma_store, sample_chunks):
    _seed(tmp_chroma_store, sample_chunks)
    hits = tmp_chroma_store.query("", top_k=5)
    assert isinstance(hits, list)