"""Finding #5 (Medium): citations must be machine-validated, not just
prompted.

Regression guard for:
"The model is asked to write a Sources section, while the UI independently
displays all retrieved chunks. Neither proves which passage supports each
claim."

Fix: the GENERATE prompt tags every chunk with a stable [S1], [S2], ...
ID. After generation, ``citations.py`` parses the IDs the LLM cited,
rejects unknown IDs, and returns only the chunks that were actually cited.

This file tests:
  - Stable IDs are emitted by ``build_citation_prompt_block``.
  - ``parse_citation_ids`` extracts markers in order and de-dups.
  - ``split_known_unknown`` separates valid IDs from hallucinated ones.
  - ``citations_from_referenced`` returns ONLY cited chunks.
  - Unknown IDs propagate to the verdict as a veto signal.
"""

from __future__ import annotations

from app.citations import (
    build_citation_prompt_block,
    citations_from_referenced,
    parse_citation_ids,
    split_known_unknown,
)
from app.models import Chunk
from app.schemas import Citation


def _chunks():
    return [
        Chunk("c1", "d1", "a.txt", 1, "RBAC assigns permissions by role.", 0.9),
        Chunk("c2", "d1", "a.txt", 2, "ABAC uses attributes.", 0.8),
        Chunk("c3", "d2", "b.txt", 1, "Encryption protects data.", 0.7),
    ]


def test_prompt_block_emits_stable_ids():
    block, id_map = build_citation_prompt_block(_chunks())
    for i in (1, 2, 3):
        assert f"[S{i}]" in block
    assert id_map["S1"].chunk_id == "c1"
    assert id_map["S3"].chunk_id == "c3"


def test_parse_citation_ids_ordered_and_unique():
    text = "Fact one [S1]. Then [S2]. Again [S1]. Finally [S3]."
    assert parse_citation_ids(text) == ["S1", "S2", "S3"]


def test_split_known_unknown_partitions():
    _, id_map = build_citation_prompt_block(_chunks())
    known, unknown = split_known_unknown(["S1", "S99", "S2"], id_map)
    assert known == ["S1", "S2"]
    assert unknown == ["S99"]


def test_citations_only_for_cited_chunks():
    _, id_map = build_citation_prompt_block(_chunks())
    cits = citations_from_referenced(_chunks(), ["S2"], id_map)
    assert len(cits) == 1
    assert cits[0].chunk_id == "c2"
    # The other chunks were NOT cited and must not appear
    assert all(c.chunk_id != "c1" for c in cits)
    assert all(c.chunk_id != "c3" for c in cits)


def test_citations_order_preserved_from_refs():
    _, id_map = build_citation_prompt_block(_chunks())
    cits = citations_from_referenced(_chunks(), ["S3", "S1"], id_map)
    assert [c.chunk_id for c in cits] == ["c3", "c1"]


def test_unknown_citations_yield_no_result():
    _, id_map = build_citation_prompt_block(_chunks())
    cits = citations_from_referenced(_chunks(), ["S99", "S42"], id_map)
    assert cits == [], "hallucinated IDs must not produce citations"


def test_unknown_ids_signal_verdict_veto():
    """The set of unknown IDs feeds the verdict as a fail signal."""
    from app.agent_state import AgentSettings
    from app.verification import combine_verdicts

    _, id_map = build_citation_prompt_block(_chunks())
    refs = parse_citation_ids("Answer [S1] and [S99].")
    known, unknown = split_known_unknown(refs, id_map)
    assert unknown == ["S99"]

    settings = AgentSettings.from_request(
        answer_verification=False,
        require_citations=False,
        allow_abstain=False,
    )
    verdict = combine_verdicts(
        question="q",
        answer="Answer [S1] and [S99].",
        chunks=_chunks(),
        settings=settings,
        unknown_citation_ids=unknown,
    )
    assert verdict.passed is False
    assert "unknown citation" in verdict.reason
    