"""Voice input via Groq Whisper.

One endpoint: POST /api/v1/transcribe
Accepts an audio upload (webm/ogg/mp4/wav/mp3/m4a) and returns the
Whisper transcript. Uses the same GROQ_API_KEY as the rest of the
pipeline — no extra vendor, no extra secret.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status

logger = logging.getLogger("argus.voice")

router = APIRouter(prefix="/api/v1", tags=["voice"])

# Groq Whisper model. `whisper-large-v3-turbo` is fast and accurate.
WHISPER_MODEL = "whisper-large-v3-turbo"

# Hard cap on upload size (20 MB).
MAX_AUDIO_BYTES = 20 * 1024 * 1024

# Accepted container formats — MediaRecorder produces webm/opus on
# Chrome/Edge and mp4/m4a on Safari.
_ALLOWED_EXTENSIONS = {".webm", ".ogg", ".oga", ".mp3", ".mp4", ".m4a", ".wav"}


def _groq_client() -> Any:
    """Lazy-construct a Groq client. Raises HTTPException on failure."""
    try:
        from groq import Groq
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Voice feature unavailable — groq SDK not installed.",
        ) from exc

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Voice feature unavailable — GROQ_API_KEY is not set.",
        )
    return Groq(api_key=api_key)


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)) -> dict:
    """Accept an audio blob, return the Whisper transcript as JSON.

    Response: ``{"text": "...", "bytes": 1234}``
    """
    filename = (audio.filename or "audio.webm").lower()
    ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ".webm"
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported audio format {ext!r}. "
                f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            ),
        )

    try:
        content = await audio.read()
    except Exception as exc:
        logger.exception("Failed to read audio upload")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read uploaded audio: {exc}",
        ) from exc

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty audio file.",
        )

    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Audio too large ({len(content)} bytes). "
                f"Max is {MAX_AUDIO_BYTES} bytes."
            ),
        )

    client = _groq_client()

    try:
        result = client.audio.transcriptions.create(
            file=(filename, content),
            model=WHISPER_MODEL,
            response_format="text",
            language="en",
            temperature=0.0,
        )
    except Exception as exc:
        logger.exception("Whisper transcription failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Transcription service error: {type(exc).__name__}",
        ) from exc

    # The SDK returns a plain string when response_format="text".
    text = result if isinstance(result, str) else getattr(result, "text", "")

    return {
        "text": (text or "").strip(),
        "bytes": len(content),
    }


__all__ = ["router"]