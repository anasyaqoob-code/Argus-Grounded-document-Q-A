"""Finding #2 (High): verification must fail CLOSED on the last attempt.

Regression guard for the fail-open bug flagged in the assessment:
"if verification fails on the final attempt, answer remains populated
and is returned."

The fix is in ``rag_engine.ask_stream``: when VERIFY reports
``passed=False`` on the last attempt and ``settings.allow_abstain`` is
True, the answer is REPLACED with ``ABSTAIN_MESSAGE`` before FINAL.

This file tests the behavior through the full agent loop, using the
``built_engine`` fixture (offline LLM, offline embeddings).
"""

from __future__ import annotations

import json

import pytest

from app.agent_state import AgentSettings
from app.verification import ABSTAIN_MESSAGE


def _decision_json():
    return json.dumps({
        "rewritten_question": "What is RBAC?",
        "needs_retrieval": True,
        "response_format": "paragraph",
        "search_query": "RBAC",
        "decision_summary": "ok",
        "is_broad_query": False,
    })


def _eval_ok():
    return json.dumps({"is_sufficient": True, "summary": "ok"})


def _verify_fail():
    return json.dumps({"passed": False, "summary": "unsupported", "unsupported_claims": ["x"]})


def _verify_pass():
    return json.dumps({"passed": True, "summary": "ok", "unsupported_claims": []})


def test_fail_closed_on_single_attempt(built_engine, mock_llm):
    """With max_retrieval_attempts=1, the first VERIFY is the last attempt.
    A failing verify must produce an abstention, not the raw answer."""
    built_engine.settings = AgentSettings.from_request(
        max_retrieval_attempts=1,
        answer_verification=True,
        allow_abstain=True,
        require_citations=False,
        source_citations=False,
    )
    mock_llm.push(
        _decision_json(),
        _eval_ok(),
        "UNVERIFIED RAW ANSWER.",     # streamed generation
        _verify_fail(),               # LLM verifier rejects
    )

    result = built_engine.ask("What is RBAC?")
    assert result.answer != "UNVERIFIED RAW ANSWER.", (
        "FAIL-CLOSED VIOLATION: the unverified answer was returned."
    )
    assert result.answer == ABSTAIN_MESSAGE
    assert result.insufficient_evidence is True


def test_fail_closed_on_last_attempt_of_two(built_engine, mock_llm):
    """Two attempts, both fail verification. Second failure must abstain."""
    built_engine.settings = AgentSettings.from_request(
        max_retrieval_attempts=2,
        answer_verification=True,
        allow_abstain=True,
        require_citations=False,
        source_citations=False,
    )
    mock_llm.push(
        # attempt 1
        _decision_json(),
        _eval_ok(),
        "First attempt answer.",
        _verify_fail(),
        # REFINE happens between attempts; no LLM call for refine when
        # query_rewriting is on, it calls _refine_query:
        json.dumps({"search_query": "RBAC roles"}),
        # attempt 2 (last)
        json.dumps({
            "is_sufficient": True,
            "summary": "ok",
        }),  # _evaluate_context for attempt 2
        "Second attempt answer.",
        _verify_fail(),
    )
    result = built_engine.ask("What is RBAC?")
    assert result.answer == ABSTAIN_MESSAGE
    assert result.insufficient_evidence is True


def test_fail_closed_disabled_returns_raw(built_engine, mock_llm):
    """Explicit opt-out: allow_abstain=False returns the raw answer."""
    built_engine.settings = AgentSettings.from_request(
        max_retrieval_attempts=1,
        answer_verification=True,
        allow_abstain=False,
        require_citations=False,
        source_citations=False,
    )
    mock_llm.push(
        _decision_json(),
        _eval_ok(),
        "Raw answer returned because abstention is off.",
        _verify_fail(),
    )
    result = built_engine.ask("What is RBAC?")
    assert result.answer != ABSTAIN_MESSAGE
    assert "Raw answer" in result.answer


def test_happy_path_verifies_and_returns_answer(built_engine, mock_llm):
    """Sanity: when verification passes, the answer IS returned."""
    built_engine.settings = AgentSettings.from_request(
        max_retrieval_attempts=1,
        answer_verification=True,
        allow_abstain=True,
        require_citations=False,
        source_citations=False,
    )
    mock_llm.push(
        _decision_json(),
        _eval_ok(),
        "Verified correct answer.",
        _verify_pass(),
    )
    result = built_engine.ask("What is RBAC?")
    assert result.answer == "Verified correct answer."
    assert result.insufficient_evidence is False