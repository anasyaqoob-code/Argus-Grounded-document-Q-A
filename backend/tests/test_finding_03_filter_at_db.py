"""Finding #3 (High): document filter must be applied INSIDE the vector
store query, not after retrieval.

Regression guard for:
"Selected-document retrieval is applied too late. The vector store
retrieves global top-k results and only then removes unselected
documents."

Fix: ``retrieval.VectorStore.query`` builds ``filter={"source": {"$in": [...]}}``
and passes it into Chroma. No post-filter on the returned list.

This file tests the multi-doc case: given 3 docs with overlapping content,
filtering to one doc must never return chunks from the others — even with
a top_k far larger than that doc's chunk count.
"""

from __future__ import annotations

from app.models import Chunk
from app.retrieval import Retriever, VectorStore


def _make_chunks() -> list[Chunk]:
    return [
        Chunk("a1", "doc_a", "a.txt", 1, "The RBAC model assigns permissions by role.", 0.0),
        Chunk("a2", "doc_a", "a.txt", 1, "RBAC is simpler than ABAC.", 0.0),
        Chunk("b1", "doc_b", "b.txt", 1, "The RBAC model assigns permissions by role.", 0.0),
        Chunk("b2", "doc_b", "b.txt", 1, "RBAC is often used in enterprise systems.", 0.0),
        Chunk("c1", "doc_c", "c.txt", 1, "Encryption protects data at rest.", 0.0),
    ]


def test_filter_at_db_returns_only_selected(tmp_chroma_store):
    tmp_chroma_store.add_documents(_make_chunks())

    hits = tmp_chroma_store.query(
        "RBAC permissions",
        top_k=20,
        document_ids=["doc_a"],
    )
    assert hits, "expected chunks from doc_a"
    assert all(h.document_id == "doc_a" for h in hits), [
        h.document_id for h in hits
    ]
    # Confirm doc_b's near-identical content was NOT returned even though
    # it matches the query semantically.
    assert not any(h.document_id == "doc_b" for h in hits)


def test_filter_at_db_overlapping_content(tmp_chroma_store):
    """Both doc_a and doc_b contain the same sentence; only the selected
    one may appear."""
    tmp_chroma_store.add_documents(_make_chunks())

    for target in ("doc_a", "doc_b", "doc_c"):
        hits = tmp_chroma_store.query(
            "RBAC permissions role",
            top_k=20,
            document_ids=[target],
        )
        assert all(h.document_id == target for h in hits), (
            f"filter leak: expected only {target}, got "
            f"{[h.document_id for h in hits]}"
        )


def test_filter_intersection_multiple_docs(tmp_chroma_store):
    tmp_chroma_store.add_documents(_make_chunks())

    hits = tmp_chroma_store.query(
        "RBAC",
        top_k=20,
        document_ids=["doc_a", "doc_c"],
    )
    allowed = {"doc_a", "doc_c"}
    assert all(h.document_id in allowed for h in hits), [
        h.document_id for h in hits
    ]


def test_retriever_filter_at_db(tmp_chroma_store):
    from app.agent_state import AgentSettings

    tmp_chroma_store.add_documents(_make_chunks())
    ret = Retriever(tmp_chroma_store)
    settings = AgentSettings.from_request(top_k=20)

    result = ret.retrieve(
        "RBAC",
        settings,
        document_ids=["doc_b"],
    )
    assert result.chunks
    assert all(c.document_id == "doc_b" for c in result.chunks)


def test_filter_at_db_empty_when_no_docs(tmp_chroma_store):
    tmp_chroma_store.add_documents(_make_chunks())
    hits = tmp_chroma_store.query(
        "anything",
        top_k=10,
        document_ids=["nonexistent_doc"],
    )
    assert hits == []
    