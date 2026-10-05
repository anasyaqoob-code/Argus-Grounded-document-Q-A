"""Tests for citation building, validation, and the [Sn] protocol."""

from app.citations import (
    build_citation_prompt_block,
    build_citations,
    citation_block_from_map,
    citations_from_referenced,
    parse_citation_ids,
    split_known_unknown,
    strip_citation_markers,
    validate_citations,
)
from app.models import Chunk
from app.schemas import Citation


# ---------------------------------------------------------------------------
# Original builders / validators
# ---------------------------------------------------------------------------
def test_build_citations(sample_chunks):
    cits = build_citations(sample_chunks, max_citations=2)
    assert len(cits) == 2
    assert cits[0].chunk_id == "c1"
    assert cits[0].quote
    assert cits[0].filename == "alpha.txt"


def test_validate_drops_unknown_chunk(sample_chunks):
    bad = Citation(
        document_id="d1",
        filename="alpha.txt",
        chunk_id="does-not-exist",
        quote="RBAC assigns permissions based on roles",
        score=0.9,
    )
    valid = validate_citations([bad], sample_chunks)
    assert valid == []


def test_validate_keeps_matching_quote(sample_chunks):
    # Use a substring that actually exists in sample_chunks["c1"].text
    good = Citation(
        document_id="alpha.txt",
        filename="alpha.txt",
        chunk_id="c1",
        quote="RBAC assigns permissions based on roles",
        score=0.9,
    )
    valid = validate_citations([good], sample_chunks)
    assert len(valid) == 1


def test_validate_drops_mismatched_document(sample_chunks):
    bad = Citation(
        document_id="wrong-doc",
        filename="alpha.txt",
        chunk_id="c1",
        quote="RBAC assigns permissions based on roles",
        score=0.9,
    )
    valid = validate_citations([bad], sample_chunks)
    assert valid == []


def test_validate_drops_fabricated_quote(sample_chunks):
    bad = Citation(
        document_id="alpha.txt",
        filename="alpha.txt",
        chunk_id="c1",
        quote="Completely fabricated statement about unicorns in Paris",
        score=0.9,
    )
    valid = validate_citations([bad], sample_chunks)
    assert valid == []


# ---------------------------------------------------------------------------
# [Sn] protocol — stable IDs in the prompt
# ---------------------------------------------------------------------------
def test_build_citation_prompt_block(sample_chunks):
    block, id_map = build_citation_prompt_block(sample_chunks)
    assert "[S1]" in block
    assert "[S2]" in block
    assert "[S3]" in block
    assert "alpha.txt" in block
    assert "beta.txt" in block
    assert set(id_map.keys()) == {"S1", "S2", "S3"}
    assert id_map["S1"].chunk_id == "c1"
    assert id_map["S3"].chunk_id == "c3"


def test_citation_block_from_map_round_trip(sample_chunks):
    _block, id_map = build_citation_prompt_block(sample_chunks)
    rebuilt = citation_block_from_map(id_map)
    for sid in id_map:
        assert f"[{sid}]" in rebuilt


# ---------------------------------------------------------------------------
# Parsing + partition
# ---------------------------------------------------------------------------
def test_parse_citation_ids_dedups_and_orders():
    answer = "Fact one [S1]. Fact two [S2]. Re-stating [S1]. Then [S3]."
    assert parse_citation_ids(answer) == ["S1", "S2", "S3"]


def test_parse_citation_ids_empty():
    assert parse_citation_ids("") == []
    assert parse_citation_ids("no markers here") == []


def test_split_known_unknown(sample_chunks):
    _, id_map = build_citation_prompt_block(sample_chunks)
    known, unknown = split_known_unknown(["S1", "S99", "S2", "S7"], id_map)
    assert known == ["S1", "S2"]
    assert unknown == ["S99", "S7"]


# ---------------------------------------------------------------------------
# Only cited chunks become citations
# ---------------------------------------------------------------------------
def test_citations_from_referenced_only_returns_cited(sample_chunks):
    _, id_map = build_citation_prompt_block(sample_chunks)
    cits = citations_from_referenced(sample_chunks, ["S1"], id_map)
    assert len(cits) == 1
    assert cits[0].chunk_id == "c1"


def test_citations_from_referenced_preserves_order(sample_chunks):
    _, id_map = build_citation_prompt_block(sample_chunks)
    cits = citations_from_referenced(sample_chunks, ["S3", "S1"], id_map)
    assert [c.chunk_id for c in cits] == ["c3", "c1"]


def test_citations_from_referenced_unknown_only(sample_chunks):
    _, id_map = build_citation_prompt_block(sample_chunks)
    cits = citations_from_referenced(sample_chunks, ["S99"], id_map)
    assert cits == []


def test_citations_from_referenced_falls_back_when_no_refs(sample_chunks):
    _, id_map = build_citation_prompt_block(sample_chunks)
    cits = citations_from_referenced(sample_chunks, [], id_map)
    # No refs → return the whole set (caller's choice)
    assert len(cits) == 3


# ---------------------------------------------------------------------------
# Display helper
# ---------------------------------------------------------------------------
def test_strip_citation_markers():
    text = "RBAC is role-based [S1]. ABAC is [S2]."
    stripped = strip_citation_markers(text)
    assert "[S1]" not in stripped
    assert "[S2]" not in stripped
    assert "RBAC is role-based" in stripped


def test_strip_citation_markers_empty():
    assert strip_citation_markers("") == ""
    assert strip_citation_markers("no markers") == "no markers"