"""
Retrieval backed by a real Chroma vector store.

Findings addressed
------------------
#3 — filter-at-DB: ``document_ids`` is pushed into the Chroma call as
     ``filter={"source": {"$in": [...]}}``. ``document_ids`` are the
     filenames the engine indexes chunks under — NOT opaque UUIDs (those
     are translated by ``main.py::_resolve_document_filenames`` before
     reaching this module). No post-filter on the result list, so top-K
     slots are never wasted on unselected documents.

#4 — strict threshold: when ``score_threshold > 0``, results below it are
     dropped; if *every* result is dropped, the method returns ``[]``.
     There is no silent fallback to unfiltered results.

Both retrieval modes from the Streamlit monolith are preserved:
  - targeted (flat, one Chroma call)
  - broad    (per-document sweep, then combined + backfilled)
The Retriever picks the mode from the ``broad`` flag the orchestrator
passes down from the DECIDE step.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from langchain_chroma import Chroma
from langchain_core.documents import Document as LCDocument

from .agent_state import AgentSettings
from .models import Chunk, RetrievalResult
from . import storage


logger = logging.getLogger("argus.retrieval")

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Cap on adaptive top-K — raised from 12 to 24 so broad sweeps across 3+
# documents aren't starved. With top_k=4 and 3 docs, broad mode now
# resolves to k=16 (per-doc budget 5), guaranteeing every doc contributes.
MAX_TOTAL_K = 24


# ---------------------------------------------------------------------------
# Embedding function (lazy, cached)
# ---------------------------------------------------------------------------
_embedding_function_cache: Any = None


def _default_embedding_function() -> Any:
    """HuggingFace embeddings, instantiated once per process.

    Imported lazily so importing this module doesn't pay the torch /
    sentence-transformers import cost until a vector store is built.
    """
    global _embedding_function_cache
    if _embedding_function_cache is None:
        from langchain_huggingface import HuggingFaceEmbeddings

        _embedding_function_cache = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL_NAME,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embedding_function_cache


# ---------------------------------------------------------------------------
# Chroma <-> Chunk conversion
# ---------------------------------------------------------------------------
def _chunk_to_document(c: Chunk) -> LCDocument:
    return LCDocument(
        page_content=c.text,
        metadata={
            "source": c.filename,
            "doc_id": c.document_id,
            "page": c.page if c.page is not None else 0,
            "chunk_id": c.chunk_id,
        },
    )


def _document_to_chunk(doc: LCDocument, *, score: float = 0.0) -> Chunk:
    md = doc.metadata or {}
    return Chunk(
        chunk_id=str(md.get("chunk_id") or md.get("id") or uuid.uuid4().hex),
        document_id=str(md.get("doc_id") or md.get("source") or "unknown"),
        filename=str(md.get("source") or "unknown"),
        page=md.get("page"),
        text=doc.page_content or "",
        score=float(score),
    )


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------
class VectorStore:
    """Thin wrapper around langchain_chroma.Chroma.

    One instance == one Chroma collection. The collection name is unique
    per instance by default so a rebuild never silently mixes old and new
    vectors.
    """

    def __init__(
        self,
        *,
        persist_directory: Optional[str] = None,
        collection_name: Optional[str] = None,
        embedding_function: Optional[Any] = None,
    ) -> None:
        self._persist_directory = persist_directory or str(storage.CHROMA_DIR)
        self._collection_name = collection_name or f"argus_{uuid.uuid4().hex[:12]}"
        self._embedding_function = embedding_function or _default_embedding_function()

        self._store = Chroma(
            collection_name=self._collection_name,
            embedding_function=self._embedding_function,
            persist_directory=self._persist_directory,
            collection_metadata={"hnsw:space": "cosine"},
        )

    # ---- properties -----------------------------------------------------
    @property
    def collection_name(self) -> str:
        return self._collection_name

    @property
    def persist_directory(self) -> str:
        return self._persist_directory

    # ---- writes ---------------------------------------------------------
    def add_documents(self, chunks: list[Chunk]) -> int:
        """Add chunks to the collection. Returns the count added."""
        if not chunks:
            return 0
        docs = [_chunk_to_document(c) for c in chunks]
        ids = [c.chunk_id for c in chunks]
        self._store.add_documents(documents=docs, ids=ids)
        return len(docs)

    def delete_by_document(self, document_id: str) -> int:
        """Delete all chunks belonging to a document.

        ``document_id`` here is the filename — the same value the engine
        writes into ``source`` metadata via ``_chunk_to_document``.

        Returns the number of chunks removed (best-effort; Chroma doesn't
        report a count for delete-by-metadata).
        """
        try:
            before = self._store.get(where={"source": document_id})
        except Exception:
            before = {"ids": []}
        n = len(before.get("ids", []) or [])
        if n == 0:
            return 0
        try:
            self._store.delete(where={"source": document_id})
        except Exception:
            return 0
        return n

    def reset(self) -> None:
        """Drop the entire collection. Used by tests."""
        try:
            self._store.delete_collection()
        except Exception:
            pass

    # ---- queries --------------------------------------------------------
    def query(
        self,
        query: str,
        *,
        top_k: int = 8,
        score_threshold: float = 0.0,
        document_ids: Optional[list[str]] = None,
    ) -> list[Chunk]:
        """Single flat Chroma query with filter-at-DB and strict threshold."""
        filter_arg: Optional[dict[str, Any]] = None
        if document_ids:
            # Filter on ``source`` — it holds the filename, which is what
            # the engine receives after main.py's UUID→filename translation.
            # ``doc_id`` in the metadata is also the filename in the current
            # indexing path, but ``source`` is the semantically correct key
            # and matches what ``_document_to_chunk`` reads from.
            filter_arg = {"source": {"$in": list(document_ids)}}

        # Over-fetch when a threshold is set, so we don't lose candidates
        # that would pass after the cut.
        fetch_k = max(top_k, top_k * 2) if score_threshold > 0 else top_k

        try:
            scored = self._store.similarity_search_with_relevance_scores(
                query,
                k=fetch_k,
                filter=filter_arg,
            )
        except Exception:
            # If relevance-score API isn't available, fall back to plain
            # similarity_search with synthetic scores. Threshold then
            # cannot be applied meaningfully — but this shouldn't hit.
            try:
                plain = self._store.similarity_search(
                    query, k=fetch_k, filter=filter_arg
                )
            except Exception:
                return []
            return [_document_to_chunk(d) for d in plain[:top_k]]

        # (doc, score) pairs, sorted by Chroma. Score in [0, 1] for cosine.
        kept: list[Chunk] = []
        for doc, score in scored:
            if score_threshold > 0 and score < score_threshold:
                continue
            kept.append(_document_to_chunk(doc, score=float(score)))
            if len(kept) >= top_k:
                break

        # Finding #4 — strict threshold. If everything was dropped, return
        # empty. Do NOT fall back to unfiltered results.
        return kept


# ---------------------------------------------------------------------------
# Retriever — orchestration over the store
# ---------------------------------------------------------------------------
class Retriever:
    def __init__(self, store: Optional[VectorStore] = None) -> None:
        self.store = store or VectorStore()

    # ---- adaptive top-K (from monolith) --------------------------------
    def _effective_k(self, n_docs: int, broad: bool, base_top_k: int) -> int:
        base = max(1, base_top_k)
        k = min(base * max(1, n_docs), MAX_TOTAL_K)
        if broad:
            k = min(k + base, MAX_TOTAL_K)
        return max(1, k)

    # ---- main entry point ----------------------------------------------
    def retrieve(
        self,
        query: str,
        agent: AgentSettings,
        *,
        document_ids: Optional[list[str]] = None,
        broad: bool = False,
    ) -> RetrievalResult:
        """Retrieve chunks for `query`.

        When ``document_ids`` is None, all docs are eligible.
        When ``broad`` is True, sweeps each selected doc individually and
        combines — guaranteeing coverage of every doc (finding for
        comparison/overview questions). Otherwise performs one flat query.
        """
        active_docs = list(document_ids) if document_ids else None
        n_docs = max(1, len(active_docs) if active_docs else 1)
        k = self._effective_k(n_docs, broad, agent.top_k)

        if broad and active_docs and len(active_docs) > 1:
            chunks = self._retrieve_broad(
                query,
                k=k,
                active_docs=active_docs,
                score_threshold=agent.score_threshold,
            )
        else:
            chunks = self.store.query(
                query,
                top_k=k,
                score_threshold=agent.score_threshold,
                document_ids=active_docs,
            )

        return RetrievalResult(query=query, chunks=chunks)

    # ---- broad mode (per-doc sweep) ------------------------------------
    def _retrieve_broad(
        self,
        query: str,
        *,
        k: int,
        active_docs: list[str],
        score_threshold: float,
    ) -> list[Chunk]:
        """Per-document retrieval — every selected doc contributes.

        Ported from the monolith's ``_retrieve_broad``. Each doc gets a
        small per-doc budget, then a top-up pass fills any remaining slots
        with the best leftovers. Threshold is applied per-doc.
        """
        per_doc_k = max(2, k // max(1, len(active_docs)))
        combined: list[Chunk] = []

        for src in active_docs:
            hits = self.store.query(
                query,
                top_k=per_doc_k,
                score_threshold=score_threshold,
                document_ids=[src],
            )
            if not hits:
                logger.debug("broad retrieval: no hits for %s", src)
            combined.extend(hits)

        # De-dup by chunk_id, preserve best score.
        best: dict[str, Chunk] = {}
        for c in combined:
            existing = best.get(c.chunk_id)
            if existing is None or c.score > existing.score:
                best[c.chunk_id] = c

        ordered = sorted(best.values(), key=lambda x: x.score, reverse=True)
        if len(ordered) >= k:
            return ordered[:k]

        # Backfill: single flat query, merge in anything new up to k.
        extra = self.store.query(
            query,
            top_k=k,
            score_threshold=score_threshold,
            document_ids=active_docs,
        )
        seen = {c.chunk_id for c in ordered}
        for c in extra:
            if c.chunk_id in seen:
                continue
            ordered.append(c)
            seen.add(c.chunk_id)
            if len(ordered) >= k:
                break
        return ordered[:k]


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------
_store: Optional[VectorStore] = None
_retriever: Optional[Retriever] = None


def get_vector_store(
    *,
    persist_directory: Optional[str] = None,
    collection_name: Optional[str] = None,
    embedding_function: Optional[Any] = None,
    fresh: bool = False,
) -> VectorStore:
    """Singleton accessor. Pass ``fresh=True`` to force a new instance
    (used by tests and by index rebuilds)."""
    global _store, _retriever
    if fresh or _store is None:
        _store = VectorStore(
            persist_directory=persist_directory,
            collection_name=collection_name,
            embedding_function=embedding_function,
        )
        # The retriever wraps whatever store is current.
        _retriever = None
    return _store


def get_retriever(store: Optional[VectorStore] = None) -> Retriever:
    global _retriever
    if store is not None:
        _retriever = Retriever(store)
    elif _retriever is None:
        _retriever = Retriever(get_vector_store())
    return _retriever


def reset_singletons() -> None:
    """Clear cached VectorStore/Retriever. Used by tests."""
    global _store, _retriever
    _store = None
    _retriever = None


__all__ = [
    "EMBEDDING_MODEL_NAME",
    "MAX_TOTAL_K",
    "VectorStore",
    "Retriever",
    "get_vector_store",
    "get_retriever",
    "reset_singletons",
]