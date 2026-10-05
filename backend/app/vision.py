"""Groq Vision integration for image-based question extraction.

Single vision call extracts every question from an uploaded image along
with an optimized search query for each. The search queries are used to
build the retrieval pass downstream, so this endpoint is the only place
the image ever needs to be processed.

Design constraints:
  - Groq vision models rotate; the model ID is a module constant so it
    can be swapped without touching call sites.
  - Output is strict JSON so the parser never has to guess.
  - Failures return an empty list rather than raising — the endpoint
    decides how to surface "no questions found".
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Optional

from groq import Groq

logger = logging.getLogger("argus.vision")

# Groq's current vision-capable model. Qwen 3.8 27B accepts image input
# alongside text and is the only multimodal option on this key.
# Override via ARGUS_VISION_MODEL if Groq rotates the lineup.
VISION_MODEL = os.getenv(
    "ARGUS_VISION_MODEL",
    "qwen/qwen3.8-27b",
)

# Fallback: same model, retried once. Kept as a named constant so a
# future second vision model can be slotted in without touching call sites.
VISION_MODEL_FALLBACK = os.getenv(
    "ARGUS_VISION_MODEL_FALLBACK",
    "qwen/qwen3.8-27b",
)

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB hard cap

_EXTRACT_SYSTEM = """You read a single image and extract every distinct
question it contains. The image may be a screenshot, photograph, worksheet,
whiteboard, or excerpt from a larger document.

For each question:
  - "text": the question exactly as written (normalize whitespace only).
  - "search_query": a short keyword query (3-8 words) optimized for
    semantic search over a corpus of unrelated documents. Strip filler
    ("what does the document say about..."), keep the substance.

If the image contains no questions, return an empty array.

Return ONLY valid JSON in this exact shape:
{"questions": [{"text": "...", "search_query": "..."}]}

Do NOT wrap in markdown fences. Do NOT add commentary."""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def _parse_questions(raw: str) -> list[dict[str, str]]:
    """Tolerant JSON extraction from the vision model's response."""
    if not raw:
        return []
    text = raw.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []

    if not isinstance(data, dict):
        return []
    questions = data.get("questions")
    if not isinstance(questions, list):
        return []

    out: list[dict[str, str]] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        text_field = str(q.get("text", "")).strip()
        if not text_field:
            continue
        search_field = str(q.get("search_query", "")).strip() or text_field
        out.append({"text": text_field, "search_query": search_field})
    return out


def _call_vision(client: Groq, model: str, b64_image: str) -> str:
    """One vision call. Returns the raw response content.

    Qwen 3.8 supports a `reasoning_effort` parameter; keeping it low
    discourages the model from wrapping its JSON output in chain-of-
    thought prose. If the parameter is rejected by the SDK, the call
    is retried without it.
    """
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _EXTRACT_SYSTEM},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_image}",
                        },
                    },
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 1200,
    }

    try:
        response = client.chat.completions.create(
            **payload, reasoning_effort="low"
        )
    except TypeError:
        # SDK doesn't accept reasoning_effort — retry without it.
        response = client.chat.completions.create(**payload)

    msg = response.choices[0].message
    content = msg.content
    if isinstance(content, list):
        content = " ".join(str(part) for part in content)
    return str(content or "")


def extract_questions_from_image(
    image_bytes: bytes,
    *,
    api_key: Optional[str] = None,
) -> list[dict[str, str]]:
    """Extract questions + search queries from an image.

    Never raises on parse failure — returns [] instead. The caller
    decides whether that is an error or a valid "no questions" result.
    """
    if not image_bytes:
        return []
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit."
        )

    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY is not set.")

    client = Groq(api_key=key)
    b64 = base64.b64encode(image_bytes).decode("ascii")

    try:
        raw = _call_vision(client, VISION_MODEL, b64)
    except Exception as exc:
        logger.warning(
            "Vision call failed on %s: %s; trying fallback %s",
            VISION_MODEL,
            exc,
            VISION_MODEL_FALLBACK,
        )
        try:
            raw = _call_vision(client, VISION_MODEL_FALLBACK, b64)
        except Exception as exc2:
            logger.exception("Fallback vision model also failed: %s", exc2)
            return []

    questions = _parse_questions(raw)
    logger.info("Extracted %d question(s) from image", len(questions))
    return questions


__all__ = [
    "VISION_MODEL",
    "VISION_MODEL_FALLBACK",
    "MAX_IMAGE_BYTES",
    "extract_questions_from_image",
]