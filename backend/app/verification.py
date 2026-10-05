"""Answer verification and abstention.

Finding #2 fix (fail-closed): the orchestrator must NOT return the
generated answer when verification fails on the last attempt. This module
exposes three signals that combine into one ``VerificationVerdict``:

  1. token-overlap heuristic   — cheap, no LLM call
  2. LLM-as-verifier           — optional, uses ``Settings.answer_verification``
  3. citation coverage         — % of retrieved chunks the answer cited

Any one of them can veto the answer. The orchestrator switches on
``verdict.passed`` and, when False and ``allow_abstain`` is set, replaces
the answer with ``ABSTAIN_MESSAGE``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .agent_state import AgentSettings
from .models import Chunk, VerificationResult


# ---------------------------------------------------------------------------
# Token-based heuristic  (preserved)
# ---------------------------------------------------------------------------
def _token_set(text: str) -> set[str]:
    return {t.lower() for t in text.split() if len(t) > 2}


def estimate_grounding(answer: str, chunks: list[Chunk]) -> tuple[float, list[str]]:
    """Rough grounding score: fraction of answer tokens that appear in
    retrieved context. Returns ``(coverage, list_of_low_support_phrases)``.
    """
    if not answer.strip() or not chunks:
        return 0.0, ["no evidence"]

    context = " ".join(c.text for c in chunks)
    ctx_tokens = _token_set(context)
    ans_tokens = _token_set(answer)
    if not ans_tokens:
        return 0.0, ["empty answer"]

    overlap = ans_tokens & ctx_tokens
    coverage = len(overlap) / len(ans_tokens)

    unsupported: list[str] = []
    for sent in answer.replace("!", ".").replace("?", ".").split("."):
        sent = sent.strip()
        if len(sent) < 20:
            continue
        st = _token_set(sent)
        if not st:
            continue
        sent_cov = len(st & ctx_tokens) / len(st)
        if sent_cov < 0.25:
            unsupported.append(sent[:120])

    return coverage, unsupported


def max_retrieval_score(chunks: list[Chunk]) -> float:
    if not chunks:
        return 0.0
    return max(c.score for c in chunks)


# ---------------------------------------------------------------------------
# Legacy heuristic-only verdict  (now populates the trainer-shape fields)
# ---------------------------------------------------------------------------
def verify_answer(
    answer: str,
    chunks: list[Chunk],
    agent: AgentSettings,
    *,
    force_abstain: bool = False,
) -> VerificationResult:
    """Decide whether to accept the answer or abstain (heuristic only).

    Populates the four optional fields on ``VerificationResult``
    (``is_grounded``, ``confidence``, ``abstain``, ``abstain_reason``)
    in addition to the required ones.
    """
    if force_abstain or not answer.strip():
        reason = "No answer generated or forced abstention"
        return VerificationResult(
            passed=False,
            summary=reason,
            unsupported_claims=[],
            is_grounded=False,
            confidence=0.0,
            abstain=True,
            abstain_reason=reason,
        )

    coverage, unsupported = estimate_grounding(answer, chunks)
    max_score = max_retrieval_score(chunks)
    confidence = 0.5 * max_score + 0.5 * coverage

    abstain = False
    reason: Optional[str] = None

    if agent.allow_abstain:
        if not chunks:
            abstain = True
            reason = "No relevant documents found"
        elif confidence < agent.abstain_confidence_threshold:
            abstain = True
            reason = (
                f"Low confidence ({confidence:.2f} < "
                f"{agent.abstain_confidence_threshold})"
            )
        elif agent.require_citations and coverage < agent.min_citation_coverage:
            abstain = True
            reason = (
                f"Insufficient citation coverage ({coverage:.2f} < "
                f"{agent.min_citation_coverage})"
            )
        elif len(unsupported) >= 3:
            abstain = True
            reason = "Multiple unsupported claims detected"

    is_grounded = not abstain and coverage >= agent.min_citation_coverage

    return VerificationResult(
        passed=not abstain,
        summary=reason or ("Grounded" if not abstain else ""),
        unsupported_claims=unsupported,
        is_grounded=is_grounded,
        confidence=confidence,
        abstain=abstain,
        abstain_reason=reason,
    )


# ---------------------------------------------------------------------------
# LLM verdict
# ---------------------------------------------------------------------------
@dataclass
class LLMVerdict:
    """Internal shape for the LLM verifier's JSON response."""

    passed: bool
    summary: str = ""
    unsupported_claims: list[str] = field(default_factory=list)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def _parse_json(text: str) -> dict[str, Any]:
    """Tolerant JSON extraction; returns {} on failure (never raises)."""
    if not text:
        return {}
    text = text.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            pass
    return {}


def verify_answer_llm(
    question: str,
    answer: str,
    chunks: list[Chunk],
    llm: Any,
    settings: AgentSettings,
    *,
    context_char_limit: int = 6000,
) -> LLMVerdict:
    """Ask the LLM to judge whether ``answer`` is supported by ``chunks``.

    Never raises — on any failure (network, malformed JSON, empty response)
    returns ``LLMVerdict(passed=False, ...)`` so the orchestrator fails
    closed.
    """
    if not answer.strip() or not chunks:
        return LLMVerdict(
            passed=False, summary="No answer or no context to verify against"
        )

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:
        return LLMVerdict(passed=False, summary="LLM verifier unavailable")

    context = "\n\n".join(
        f"[{i}] {c.filename} — page {c.page if c.page is not None else '?'}\n{c.text}"
        for i, c in enumerate(chunks, start=1)
    )
    if len(context) > context_char_limit:
        context = context[:context_char_limit].rstrip() + "…"

    system = (
        "You verify whether an assistant's answer is fully supported by the "
        "provided document context.\n"
        "Return ONLY valid JSON with these keys:\n"
        '  "passed": boolean — true only if every factual claim is supported\n'
        '  "summary": short reason (one sentence)\n'
        '  "unsupported_claims": array of the specific unsupported sentences\n'
        "Do not use outside knowledge. Judge only against the context."
    )
    human = (
        f"Question: {question}\n\n"
        f"Context:\n{context}\n\n"
        f"Answer to verify:\n{answer}"
    )

    try:
        response = llm.invoke(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )
        raw = getattr(response, "content", None) or str(response)
        if isinstance(raw, list):
            raw = " ".join(str(x) for x in raw)
        data = _parse_json(str(raw))
    except Exception as exc:
        return LLMVerdict(
            passed=False,
            summary=f"Verification call failed: {type(exc).__name__}",
            unsupported_claims=[],
        )

    claims = data.get("unsupported_claims") or []
    if not isinstance(claims, list):
        claims = []
    return LLMVerdict(
        passed=bool(data.get("passed", False)),
        summary=str(data.get("summary", "")).strip(),
        unsupported_claims=[str(c) for c in claims],
    )


# ---------------------------------------------------------------------------
# Combined verdict
# ---------------------------------------------------------------------------
@dataclass
class VerificationVerdict:
    """Single signal the pipeline uses to accept / reject / abstain."""

    passed: bool
    summary: str = ""
    unsupported_claims: list[str] = field(default_factory=list)
    coverage: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    unknown_citation_ids: list[str] = field(default_factory=list)


def combine_verdicts(
    *,
    question: str,
    answer: str,
    chunks: list[Chunk],
    settings: AgentSettings,
    llm: Any = None,
    citation_coverage: Optional[float] = None,
    unknown_citation_ids: Optional[list[str]] = None,
) -> VerificationVerdict:
    """Merge heuristic + LLM + citation signals into one verdict.

    Passing rules (all must hold for ``passed=True``):
      - heuristic token coverage >= ``settings.min_citation_coverage``
        (only when ``settings.require_citations``)
      - no unknown citation IDs
      - citation coverage >= ``settings.min_citation_coverage``
        (only when supplied and ``settings.require_citations``)
      - confidence >= ``settings.abstain_confidence_threshold``
        (only when ``settings.allow_abstain``)
      - LLM verdict passes, IF ``settings.answer_verification`` is on
        and an ``llm`` was provided
    """
    coverage, unsupported = estimate_grounding(answer, chunks)
    max_score = max_retrieval_score(chunks)
    confidence = 0.5 * max_score + 0.5 * coverage

    reasons: list[str] = []
    all_unsupported: list[str] = list(unsupported)
    unknown_ids = list(unknown_citation_ids or [])

    if settings.require_citations and coverage < settings.min_citation_coverage:
        reasons.append(
            f"token coverage {coverage:.2f} < {settings.min_citation_coverage}"
        )

    if unknown_ids:
        reasons.append(f"{len(unknown_ids)} unknown citation id(s)")

    if citation_coverage is not None and settings.require_citations:
        if citation_coverage < settings.min_citation_coverage:
            reasons.append(
                f"citation coverage {citation_coverage:.2f} < "
                f"{settings.min_citation_coverage}"
            )

    if settings.allow_abstain and confidence < settings.abstain_confidence_threshold:
        reasons.append(
            f"confidence {confidence:.2f} < {settings.abstain_confidence_threshold}"
        )

    llm_summary = ""
    if settings.answer_verification and llm is not None and not reasons:
        lv = verify_answer_llm(question, answer, chunks, llm, settings)
        llm_summary = lv.summary
        all_unsupported.extend(lv.unsupported_claims)
        if not lv.passed:
            reasons.append(f"LLM verifier rejected: {lv.summary or 'unsupported'}")

    passed = not reasons
    summary = "; ".join(reasons) if reasons else (llm_summary or "Verified")

    return VerificationVerdict(
        passed=passed,
        summary=summary,
        unsupported_claims=all_unsupported,
        coverage=coverage,
        confidence=confidence,
        reason=summary,
        unknown_citation_ids=unknown_ids,
    )


def verdict_to_result(v: VerificationVerdict) -> VerificationResult:
    """Adapt a ``VerificationVerdict`` to ``models.VerificationResult``."""
    return VerificationResult(
        passed=v.passed,
        summary=v.summary,
        unsupported_claims=v.unsupported_claims,
        is_grounded=v.passed,
        confidence=v.confidence,
        abstain=not v.passed and bool(v.unknown_citation_ids or True),
        abstain_reason=None if v.passed else v.summary,
    )


# ---------------------------------------------------------------------------
# Canonical abstention message
# ---------------------------------------------------------------------------
ABSTAIN_MESSAGE = (
    "I don't have enough grounded evidence in the provided documents "
    "to answer confidently. Please try rephrasing or upload more relevant material."
)


__all__ = [
    "estimate_grounding",
    "max_retrieval_score",
    "verify_answer",
    "verify_answer_llm",
    "LLMVerdict",
    "combine_verdicts",
    "VerificationVerdict",
    "verdict_to_result",
    "ABSTAIN_MESSAGE",
]