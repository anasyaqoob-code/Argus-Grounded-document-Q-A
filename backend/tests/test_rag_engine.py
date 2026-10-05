"""End-to-end tests for AgenticRAGService.

Uses the ``built_engine`` fixture (from conftest.py), which:
  - patches ``ChatGroq`` with a FIFO fake (``mock_llm``)
  - installs a deterministic offline embedding function
  - builds a fresh Chroma index in tmp_path over ``txt_file``

Nothing here touches the live ``backend/app/data/`` or the network.
"""

from __future__ import annotations

import json

import pytest

from app.agent_state import AgentSettings, AgentStateName
from app.models import AgentResult, Chunk, RetrievalResult
from app.rag_engine import (
    AgenticRAGService,
    RunResult,
    embed_text,
    get_rag_engine,
    reset_rag_engine,
)
from app.verification import ABSTAIN_MESSAGE


# ===========================================================================
# Helpers — staged LLM responses
# ===========================================================================
def _decision_json(
    *,
    rewritten: str = "q",
    search: str = "q",
    fmt: str = "paragraph",
    broad: bool = False,
) -> str:
    return json.dumps(
        {
            "rewritten_question": rewritten,
            "needs_retrieval": True,
            "response_format": fmt,
            "search_query": search,
            "decision_summary": "ok",
            "is_broad_query": broad,
        }
    )


def _eval_json(sufficient: bool = True, reason: str = "ok") -> str:
    return json.dumps({"is_sufficient": sufficient, "summary": reason})


def _verify_json(passed: bool = True, reason: str = "ok") -> str:
    return json.dumps({"passed": passed, "summary": reason, "unsupported_claims": []})


def _stage_happy_path(mock_llm, answer: str = "RBAC assigns permissions by role [S1]."):
    """Push responses for one successful ask cycle.

    Order:
      1. _understand_and_decide
      2. _evaluate_context
      3. streamed answer tokens
      4. _verify_answer (LLM verifier)
    """
    mock_llm.push(
        _decision_json(search="RBAC", rewritten="What is RBAC?"),
        _eval_json(sufficient=True),
        answer,
        _verify_json(passed=True),
    )


# ===========================================================================
# build_index
# ===========================================================================
def test_build_index_returns_stats(built_engine):
    assert built_engine.retriever is not None
    assert built_engine.chunks, "index should contain chunks"
    assert all(isinstance(c, Chunk) for c in built_engine.chunks)
    assert built_engine.selected_doc_ids, "default selection = all docs"


def test_build_index_unsupported_file(monkeypatch):
    from tests.conftest import FakeUploadedFile

    engine = AgenticRAGService()
    bad = FakeUploadedFile("bad.docx", b"xxx")
    with pytest.raises(ValueError, match="Unsupported file type"):
        engine.build_index([bad])


# ===========================================================================
# retrieve — checks it delegates to Retriever and returns Chunks
# ===========================================================================
def test_retrieve_returns_chunks(built_engine):
    hits = built_engine.retrieve("RBAC roles")
    assert isinstance(hits, list)
    assert all(isinstance(c, Chunk) for c in hits)


def test_retrieve_no_index_raises():
    engine = AgenticRAGService()
    with pytest.raises(RuntimeError, match="not initialized"):
        engine.retrieve("anything")


# ===========================================================================
# ask — happy path
# ===========================================================================
def test_ask_happy_path(built_engine, mock_llm):
    _stage_happy_path(mock_llm, answer="RBAC assigns permissions by role [S1].")
    result = built_engine.ask("What is RBAC?")
    assert isinstance(result, AgentResult)
    assert result.answer
    assert result.insufficient_evidence is False
    assert any(s.state == AgentStateName.FINAL.value for s in result.activity)
    # At least one decision + evaluate + verify LLM call
    assert len(mock_llm.calls) >= 2


# ===========================================================================
# Fast-path gates — no LLM call
# ===========================================================================
def test_gate_greeting_skips_llm(built_engine, mock_llm):
    before = len(mock_llm.calls)
    result = built_engine.ask("hi")
    assert "document assistant" in result.answer.lower()
    assert len(mock_llm.calls) == before


def test_gate_capability_skips_llm(built_engine, mock_llm):
    before = len(mock_llm.calls)
    result = built_engine.ask("what can you do")
    assert "documents" in result.answer.lower()
    assert len(mock_llm.calls) == before


def test_gate_thanks_skips_llm(built_engine, mock_llm):
    before = len(mock_llm.calls)
    result = built_engine.ask("thanks")
    assert "welcome" in result.answer.lower()
    assert len(mock_llm.calls) == before


# ===========================================================================
# ask_stream — event protocol
# ===========================================================================
def test_ask_stream_yields_step_token_final(built_engine, mock_llm):
    _stage_happy_path(mock_llm)
    events = list(built_engine.ask_stream("What is RBAC?"))
    types = [e["type"] for e in events]
    assert "step" in types
    assert "token" in types
    assert "final" in types
    final = next(e for e in events if e["type"] == "final")
    assert "result" in final
    assert isinstance(final["result"], AgentResult)
    assert "citations" in final


# ===========================================================================
# Finding #2 — fail-closed verification
# ===========================================================================
def test_fail_closed_verify_abstains_on_last_attempt(built_engine, mock_llm):
    """The key regression test for finding #2.

    Verifier says passed=False on the final attempt, allow_abstain=True.
    The engine must replace the answer with ABSTAIN_MESSAGE.
    """
    # One attempt allowed → first verify IS the final attempt.
    built_engine.settings = AgentSettings.from_request(
        max_retrieval_attempts=1,
        answer_verification=True,
        allow_abstain=True,
        require_citations=False,
        source_citations=False,
    )
    mock_llm.push(
        _decision_json(search="RBAC", rewritten="What is RBAC?"),
        _eval_json(sufficient=True),
        "Unsupported guess [S1].",
        _verify_json(passed=False, reason="unsupported"),
    )

    result = built_engine.ask("What is RBAC?")
    assert result.answer == ABSTAIN_MESSAGE, (
        f"fail-closed violated — got: {result.answer!r}"
    )
    assert result.insufficient_evidence is True


def test_fail_closed_verify_disabled_returns_raw_answer(built_engine, mock_llm):
    """With allow_abstain=False, the raw answer is returned even when
    verification fails (explicit opt-out)."""
    built_engine.settings = AgentSettings.from_request(
        max_retrieval_attempts=1,
        answer_verification=True,
        allow_abstain=False,
        require_citations=False,
        source_citations=False,
    )
    mock_llm.push(
        _decision_json(search="RBAC", rewritten="What is RBAC?"),
        _eval_json(sufficient=True),
        "Raw unverified answer.",
        _verify_json(passed=False, reason="unsupported"),
    )
    result = built_engine.ask("What is RBAC?")
    assert result.answer != ABSTAIN_MESSAGE


# ===========================================================================
# Finding #4 — insufficient evidence path via strict threshold
# ===========================================================================
def test_insufficient_when_context_missing(built_engine, mock_llm):
    """EVALUATE says insufficient on all attempts → abstain."""
    built_engine.settings = AgentSettings.from_request(
        max_retrieval_attempts=1,
        allow_abstain=True,
        answer_verification=False,
    )
    mock_llm.push(
        _decision_json(search="completely unrelated", rewritten="What is quantum entanglement?"),
        _eval_json(sufficient=False, reason="no relevant context"),
    )
    result = built_engine.ask("What is quantum entanglement?")
    assert result.insufficient_evidence is True
    assert result.answer == ABSTAIN_MESSAGE


# ===========================================================================
# Overview fast-path
# ===========================================================================
def test_overview_fast_path_multi_doc(built_engine, mock_llm, comparison_txt, monkeypatch):
    """Adding a second doc triggers the overview fast-path for 'what is this pdf about'."""
    built_engine.build_index([comparison_txt])
    assert len(built_engine.selected_doc_ids) >= 2

    mock_llm.push(
        "Summary A.",
        "Summary B.",
    )
    result = built_engine.ask("what is this pdf about?")
    assert result.answer
    assert result.response_format == "paragraph"


# ===========================================================================
# stream / run adapters (FastAPI surface)
# ===========================================================================
def _fake_session():
    from app import storage

    sid = storage.create_session(title="test")
    return sid


def test_stream_adapter_yields_stream_event_envelope(built_engine, mock_llm):
    sid = _fake_session()
    _stage_happy_path(mock_llm)
    events = list(built_engine.stream("What is RBAC?", session_id=sid))
    assert events, "no events streamed"
    for ev in events:
        assert "type" in ev
        assert "data" in ev
        assert ev["type"] in {"step", "token", "final", "error"}
    final = next((e for e in events if e["type"] == "final"), None)
    assert final is not None
    assert "answer" in final["data"]
    assert "citations" in final["data"]


def test_run_adapter_returns_run_result(built_engine, mock_llm):
    sid = _fake_session()
    _stage_happy_path(mock_llm)
    result = built_engine.run("What is RBAC?", session_id=sid)
    assert isinstance(result, RunResult)
    assert result.answer
    for attr in ("answer", "citations", "abstained", "abstain_reason",
                 "session_id", "confidence", "metadata"):
        assert hasattr(result, attr), f"missing {attr}"
    assert result.session_id == sid


# ===========================================================================
# embed_text
# ===========================================================================
def test_embed_text_returns_vector():
    vec = embed_text("hello world")
    assert isinstance(vec, list)
    assert len(vec) > 0
    assert all(isinstance(x, float) for x in vec[:3])


# ===========================================================================
# Singleton
# ===========================================================================
def test_get_rag_engine_singleton(built_engine):
    reset_rag_engine()
    a = get_rag_engine()
    b = get_rag_engine()
    assert a is b
    reset_rag_engine()