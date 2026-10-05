"""Citation extraction and validation.

Finding #5 fix: the generation prompt now assigns stable ``[S1]``,
``[S2]``, … IDs to retrieved chunks. The LLM is instructed to reference
them inline. After generation, this module:

  1. parses the referenced IDs out of the answer,
  2. rejects any ID that does not map to a retrieved chunk,
  3. returns only the cited chunks (not the full retrieval set).

The original ``build_citations`` / ``validate_citations`` helpers are
preserved unchanged for callers that want the whole-set behavior.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .models import Chunk
from .schemas import Citation


# ---------------------------------------------------------------------------
# Stable citation IDs  →  [S1], [S2], …
# ---------------------------------------------------------------------------
# Canonical form is [S1]. The LLM sometimes emits variant forms like
# 【S1】 or 【S1+L1-L4】 (East-Asian full-width brackets with optional
# line ranges), likely from training-data conventions. Accept both so
# parsing and display work regardless of which form the model picks.
CITATION_ID_RE = re.compile(r"[\[【]S(\d+)(?:\+L\d+-L\d+)?[\]】]")


def _sid(n: int) -> str:
    """Canonical citation ID for the n-th chunk (1-indexed)."""
    return f"S{n}"


def build_citation_prompt_block(
    chunks: list[Chunk],
    *,
    max_chunks: int = 12,
    max_chars_per_chunk: int = 1200,
) -> tuple[str, dict[str, Chunk]]:
    """Return a prompt-ready block and the ID→chunk map.

    The block looks like::

        [S1] paper.pdf — page 3
        <chunk text, truncated to max_chars_per_chunk>

        [S2] paper.pdf — page 7
        <chunk text>

    The map returned is ``{"S1": <Chunk>, "S2": <Chunk>, ...}`` and must
    be passed to ``split_known_unknown`` / ``citations_from_referenced``
    after generation.
    """
    id_map: dict[str, Chunk] = {}
    parts: list[str] = []
    for i, c in enumerate(chunks[:max_chunks], start=1):
        sid = _sid(i)
        id_map[sid] = c
        page = c.page if c.page is not None else "?"
        text = c.text
        if len(text) > max_chars_per_chunk:
            text = text[:max_chars_per_chunk].rstrip() + "…"
        parts.append(f"[{sid}] {c.filename} — page {page}\n{text}")
    return "\n\n".join(parts), id_map


def citation_block_from_map(id_map: dict[str, Chunk]) -> str:
    """Reconstruct the prompt block from an existing ID→chunk map.

    Used after a REFINE loop when the caller keeps the original map but
    wants to re-emit the same block for a fresh generation attempt.
    """
    # Preserve insertion order (Python dicts are ordered).
    parts: list[str] = []
    for sid, c in id_map.items():
        page = c.page if c.page is not None else "?"
        parts.append(f"[{sid}] {c.filename} — page {page}\n{c.text}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Parse / partition
# ---------------------------------------------------------------------------
def parse_citation_ids(answer: str) -> list[str]:
    """Return every ``[Sn]`` (or ``【Sn】`` / ``【Sn+Ln-Ln】``) marker in
    ``answer`` in first-appearance order.

    Deduplicated: an ID referenced twice is listed once.
    """
    if not answer:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in CITATION_ID_RE.finditer(answer):
        sid = f"S{m.group(1)}"
        if sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def split_known_unknown(
    refs: list[str],
    id_map: dict[str, Chunk],
) -> tuple[list[str], list[str]]:
    """Split referenced IDs into those that map to a retrieved chunk and
    those that don't (i.e. hallucinated citations).

    Returns ``(known, unknown)`` preserving the order of ``refs``.
    """
    known: list[str] = []
    unknown: list[str] = []
    for r in refs:
        (known if r in id_map else unknown).append(r)
    return known, unknown


# ---------------------------------------------------------------------------
# Citations from referenced IDs only  (finding #5 user-visible fix)
# ---------------------------------------------------------------------------
def citations_from_referenced(
    chunks: list[Chunk],
    refs: list[str],
    id_map: dict[str, Chunk],
    *,
    max_citations: int = 8,
    min_quote_len: int = 40,
) -> list[Citation]:
    """Return Citation objects for the chunks the LLM actually cited.

    Only referenced IDs that resolve through ``id_map`` are kept, in the
    order the LLM first cited them. The resulting citations go through
    ``validate_citations`` for the quote-substring check.

    Falls back to ``build_citations(chunks)`` when ``refs`` is empty, so
    callers that skip the ``[Sn]`` protocol still get a usable result.
    """
    if not refs:
        return build_citations(chunks, max_citations=max_citations,
                               min_quote_len=min_quote_len)

    ordered_chunks: list[Chunk] = []
    seen: set[str] = set()
    for sid in refs:
        c = id_map.get(sid)
        if c is None or c.chunk_id in seen:
            continue
        seen.add(c.chunk_id)
        ordered_chunks.append(c)
        if len(ordered_chunks) >= max_citations:
            break

    if not ordered_chunks:
        return []

    # Reuse the existing builder — it produces Citation objects with
    # `_make_quote()`-derived quotes, then validate against the same
    # chunks to drop any quote that isn't in the source text.
    candidates = build_citations(
        ordered_chunks,
        max_citations=max_citations,
        min_quote_len=min_quote_len,
    )
    return validate_citations(candidates, ordered_chunks)


# ---------------------------------------------------------------------------
# Display helper
# ---------------------------------------------------------------------------
def strip_citation_markers(answer: str) -> str:
    """Remove [Sn] / 【Sn】 / 【Sn+Ln-Ln】 markers from ``answer`` for
    clean display.

    Collapses leftover double-spaces from removed inline markers.
    """
    if not answer:
        return answer
    cleaned = CITATION_ID_RE.sub("", answer)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


# ---------------------------------------------------------------------------
# Original helpers — preserved verbatim
# ---------------------------------------------------------------------------
def build_citations(
    chunks: list[Chunk],
    *,
    max_citations: int = 8,
    min_quote_len: int = 40,
) -> list[Citation]:
    """
    Turn top chunks into structured citations with short quotes.
    """
    citations: list[Citation] = []
    seen: set[str] = set()
    for c in chunks:
        if c.chunk_id in seen:
            continue
        seen.add(c.chunk_id)
        quote = _make_quote(c.text, min_quote_len)
        citations.append(
            Citation(
                document_id=c.document_id,
                filename=c.filename,
                page=c.page,
                chunk_id=c.chunk_id,
                quote=quote,
                score=round(c.score, 4),
            )
        )
        if len(citations) >= max_citations:
            break
    return citations


def _make_quote(text: str, min_len: int) -> str:
    text = " ".join(text.split())
    if len(text) <= min_len + 20:
        return text
    for sep in (". ", "? ", "! "):
        idx = text.find(sep)
        if min_len <= idx <= 200:
            return text[: idx + 1]
    return text[:180].rstrip() + "…"


def validate_citations(
    citations: list[Citation],
    chunks: list[Chunk],
) -> list[Citation]:
    """
    Drop citations that do not correspond to a retrieved chunk or whose
    quote is not found in the source text (case-insensitive substring).
    """
    by_id = {c.chunk_id: c for c in chunks}
    valid: list[Citation] = []
    for cit in citations:
        src = by_id.get(cit.chunk_id)
        if src is None:
            continue
        if cit.document_id != src.document_id:
            continue
        quote_norm = cit.quote.rstrip("…").strip().lower()
        if quote_norm and quote_norm not in src.text.lower():
            if not _fuzzy_in(quote_norm, src.text.lower()):
                continue
        valid.append(cit)
    return valid


def _fuzzy_in(needle: str, haystack: str, min_ratio: float = 0.7) -> bool:
    if not needle:
        return False
    if needle in haystack:
        return True
    n_tokens = needle.split()
    if len(n_tokens) < 3:
        return False
    h_tokens = set(haystack.split())
    overlap = sum(1 for t in n_tokens if t in h_tokens)
    return (overlap / len(n_tokens)) >= min_ratio


def citations_to_dicts(citations: list[Citation]) -> list[dict[str, Any]]:
    return [c.model_dump() for c in citations]


__all__ = [
    "CITATION_ID_RE",
    "build_citation_prompt_block",
    "citation_block_from_map",
    "parse_citation_ids",
    "split_known_unknown",
    "citations_from_referenced",
    "strip_citation_markers",
    "build_citations",
    "validate_citations",
    "citations_to_dicts",
]