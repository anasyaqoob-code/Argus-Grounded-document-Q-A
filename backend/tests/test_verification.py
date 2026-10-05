"""Tests for abstention / verification."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agent_state import AgentSettings
from app.models import Chunk, VerificationResult
from app.verification import (
    ABSTAIN_MESSAGE,
    LLMVerdict,
    VerificationVerdict,
    combine_verdicts,
    estimate_grounding,
    max_retrieval_score,
    verdict_to_result,
    verify_answer,
    verify_answer_llm,
)


# ---------------------------------------------------------------------------
# Local agent_settings helper
# ---------------------------------------------------------------------------
def _agent_settings(**overrides) -> AgentSettings:
    base = dict(
        answer_verification=False,
        require_citations=True,
        allow_abstain=True,
        min_citation_coverage=0.5,
        abstain_confidence_threshold=0.3,
    )
    base.update(overrides)
    return AgentSettings.from_request(**base)


# ---------------------------------------------------------------------------
# estimate_grounding
# ---------------------------------------------------------------------------
def test_estimate_grounding_high_overlap():
    chunks = [
        Chunk(
            chunk_id="c1",
            document_id="d1",
            filename="f.txt",
            page=1,
            text="The capital of France is Paris and the Eiffel Tower is famous.",
            score=0.9,
        )
    ]
    answer = "The capital of France is Paris."
    cov, unsupported = estimate_grounding(answer, chunks)
    assert cov > 0.7
    assert unsupported == []


def test_estimate_grounding_no_chunks():
    cov, unsupported = estimate_grounding("Anything", [])
    assert cov == 0.0
    assert "no evidence" in unsupported


def test_estimate_grounding_empty_answer():
    chunks = [
        Chunk(chunk_id="c1", document_id="d1", filename="f.txt", page=1, text="x", score=0.5)
    ]
    cov, unsupported = estimate_grounding("", chunks)
    assert cov == 0.0
    assert unsupported


def test_max_retrieval_score():
    chunks = [
        Chunk(chunk_id="c1", document_id="d1", filename="f.txt", page=1, text="x", score=0.3),
        Chunk(chunk_id="c2", document_id="d1", filename="f.txt", page=1, text="y", score=0.9),
    ]
    assert max_retrieval_score(chunks) == 0.9
    assert max_retrieval_score([]) == 0.0


# ---------------------------------------------------------------------------
# verify_answer — heuristic-only path
# ---------------------------------------------------------------------------
def test_abstain_when_no_chunks():
    result = verify_answer("Some answer", [], _agent_settings())
    assert result.abstain is True
    assert result.abstain_reason is not None


def test_abstain_low_confidence():
    weak = [
        Chunk(
            chunk_id="c1", document_id="d1", filename="f.txt", page=1,
            text="unrelated weather data from 1990", score=0.05,
        )
    ]
    result = verify_answer(
        "Quantum entanglement enables instantaneous communication across galaxies.",
        weak,
        _agent_settings(),
    )
    assert result.abstain is True


def test_accept_when_grounded():
    chunks = [
        Chunk(
            chunk_id="c1", document_id="d1", filename="f.txt", page=1,
            text="The capital of France is Paris. It is known for the Eiffel Tower.",
            score=0.92,
        )
    ]
    answer = "The capital of France is Paris."
    result = verify_answer(answer, chunks, _agent_settings())
    assert result.abstain is False
    assert result.is_grounded is True
    assert result.confidence is not None and result.confidence > 0.5


def test_force_abstain():
    chunks = [
        Chunk(
            chunk_id="c1", document_id="d1", filename="f.txt", page=1,
            text="rich evidence about the topic at hand here", score=0.99,
        )
    ]
    result = verify_answer(
        "good answer with evidence", chunks, _agent_settings(), force_abstain=True
    )
    assert result.abstain is True


def test_allow_abstain_false():
    """With allow_abstain=False, verify_answer does not veto — the caller
    has opted out of abstention."""
    agent = _agent_settings(allow_abstain=False)
    result = verify_answer("I guess something", [], agent)
    assert result.abstain is False


def test_verify_answer_returns_extended_result():
    """Sanity: the extended VerificationResult carries all four extra fields."""
    chunks = [
        Chunk(
            chunk_id="c1", document_id="d1", filename="f.txt", page=1,
            text="The capital of France is Paris.", score=0.9,
        )
    ]
    r = verify_answer("The capital of France is Paris.", chunks, _agent_settings())
    assert isinstance(r, VerificationResult)
    # Required
    assert isinstance(r.passed, bool)
    assert isinstance(r.summary, str)
    assert isinstance(r.unsupported_claims, list)
    # Optional (trainer-shape)
    assert isinstance(r.is_grounded, bool)
    assert isinstance(r.confidence, float)
    assert isinstance(r.abstain, bool)
    assert r.abstain_reason is None or isinstance(r.abstain_reason, str)


# ---------------------------------------------------------------------------
# verify_answer_llm
# ---------------------------------------------------------------------------
class _FakeLLM:
    def __init__(self, content: str):
        self.content = content
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append(messages)
        m = MagicMock()
        m.content = self.content
        return m


def test_verify_answer_llm_good_json():
    llm = _FakeLLM('{"passed": true, "summary": "ok", "unsupported_claims": []}')
    chunks = [
        Chunk(chunk_id="c1", document_id="d1", filename="f.txt", page=1, text="hi", score=0.9)
    ]
    verdict = verify_answer_llm("q", "hi", chunks, llm, _agent_settings())
    assert verdict.passed is True
    assert verdict.summary == "ok"


def test_verify_answer_llm_fenced_json():
    llm = _FakeLLM('```json\n{"passed": true, "summary": "ok"}\n```')
    chunks = [
        Chunk(chunk_id="c1", document_id="d1", filename="f.txt", page=1, text="hi", score=0.9)
    ]
    verdict = verify_answer_llm("q", "hi", chunks, llm, _agent_settings())
    assert verdict.passed is True


def test_verify_answer_llm_malformed_fails_closed():
    llm = _FakeLLM("not json at all")
    chunks = [
        Chunk(chunk_id="c1", document_id="d1", filename="f.txt", page=1, text="hi", score=0.9)
    ]
    verdict = verify_answer_llm("q", "hi", chunks, llm, _agent_settings())
    assert verdict.passed is False


def test_verify_answer_llm_exception_fails_closed():
    class Boom:
        def invoke(self, messages):
            raise RuntimeError("network died")

    chunks = [
        Chunk(chunk_id="c1", document_id="d1", filename="f.txt", page=1, text="hi", score=0.9)
    ]
    verdict = verify_answer_llm("q", "hi", chunks, Boom(), _agent_settings())
    assert verdict.passed is False
    assert "Verification call failed" in verdict.summary


def test_verify_answer_llm_no_context():
    llm = _FakeLLM('{"passed": true, "summary": "ok"}')
    verdict = verify_answer_llm("q", "a", [], llm, _agent_settings())
    assert verdict.passed is False


# ---------------------------------------------------------------------------
# combine_verdicts — the pipeline's real decision path
# ---------------------------------------------------------------------------
def test_combine_verdicts_all_clear():
    chunks = [
        Chunk(
            chunk_id="c1", document_id="d1", filename="f.txt", page=1,
            text="The capital of France is Paris.", score=0.9,
        )
    ]
    settings = _agent_settings(require_citations=False, allow_abstain=False)
    v = combine_verdicts(
        question="Where?",
        answer="The capital of France is Paris.",
        chunks=chunks,
        settings=settings,
    )
    assert v.passed is True
    assert v.reason in ("", "Verified")


def test_combine_verdicts_unknown_citations_veto():
    chunks = [
        Chunk(
            chunk_id="c1", document_id="d1", filename="f.txt", page=1,
            text="The capital of France is Paris.", score=0.9,
        )
    ]
    settings = _agent_settings(require_citations=False, allow_abstain=False)
    v = combine_verdicts(
        question="Where?",
        answer="The capital of France is Paris [S99].",
        chunks=chunks,
        settings=settings,
        unknown_citation_ids=["S99"],
    )
    assert v.passed is False
    assert "unknown citation" in v.reason


def test_combine_verdicts_citation_coverage_veto():
    chunks = [
        Chunk(
            chunk_id="c1", document_id="d1", filename="f.txt", page=1,
            text="The capital of France is Paris.", score=0.9,
        )
    ]
    settings = _agent_settings(require_citations=True, allow_abstain=False)
    v = combine_verdicts(
        question="Where?",
        answer="The capital of France is Paris.",
        chunks=chunks,
        settings=settings,
        citation_coverage=0.1,
    )
    assert v.passed is False
    assert "citation coverage" in v.reason


def test_combine_verdicts_low_confidence_veto():
    chunks = [
        Chunk(
            chunk_id="c1", document_id="d1", filename="f.txt", page=1,
            text="unrelated weather data", score=0.02,
        )
    ]
    settings = _agent_settings(require_citations=False, allow_abstain=True)
    v = combine_verdicts(
        question="Where?",
        answer="Quantum entanglement enables instantaneous communication.",
        chunks=chunks,
        settings=settings,
    )
    assert v.passed is False
    assert "confidence" in v.reason


def test_combine_verdicts_llm_rejection_veto():
    chunks = [
        Chunk(
            chunk_id="c1", document_id="d1", filename="f.txt", page=1,
            text="The capital of France is Paris.", score=0.9,
        )
    ]
    settings = _agent_settings(require_citations=False, allow_abstain=False, answer_verification=True)
    llm = _FakeLLM('{"passed": false, "summary": "unsupported", "unsupported_claims": ["x"]}')
    v = combine_verdicts(
        question="Where?",
        answer="The capital of France is Paris.",
        chunks=chunks,
        settings=settings,
        llm=llm,
    )
    assert v.passed is False
    assert "LLM verifier rejected" in v.reason


def test_combine_verdicts_llm_pass():
    chunks = [
        Chunk(
            chunk_id="c1", document_id="d1", filename="f.txt", page=1,
            text="The capital of France is Paris.", score=0.9,
        )
    ]
    settings = _agent_settings(require_citations=False, allow_abstain=False, answer_verification=True)
    llm = _FakeLLM('{"passed": true, "summary": "supported", "unsupported_claims": []}')
    v = combine_verdicts(
        question="Where?",
        answer="The capital of France is Paris.",
        chunks=chunks,
        settings=settings,
        llm=llm,
    )
    assert v.passed is True


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
def test_verdict_to_result_roundtrip():
    chunks = [
        Chunk(
            chunk_id="c1", document_id="d1", filename="f.txt", page=1,
            text="The capital of France is Paris.", score=0.9,
        )
    ]
    settings = _agent_settings(require_citations=False, allow_abstain=False)
    v = combine_verdicts(
        question="Where?",
        answer="The capital of France is Paris.",
        chunks=chunks,
        settings=settings,
    )
    r = verdict_to_result(v)
    assert r.passed == v.passed
    assert r.confidence == v.confidence
    assert r.is_grounded == v.passed


# ---------------------------------------------------------------------------
# ABSTAIN_MESSAGE
# ---------------------------------------------------------------------------
def test_abstain_message_present():
    assert "grounded evidence" in ABSTAIN_MESSAGE