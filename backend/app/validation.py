"""Upload and input validation (size, type, page limits, encoding).

Covers finding #6 from the assessment:
  - size cap (already existed, preserved)
  - page cap (already existed, preserved)
  - batch-size cap (new)
  - UTF-8 decode with fallback (new)
  - encrypted PDF detection (new)
  - corrupted PDF detection via guarded PdfReader open (new)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO, Iterable

from fastapi import HTTPException, UploadFile, status

from .config import Settings, get_settings


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class ValidationError(Exception):
    def __init__(self, message: str, code: str = "validation_error"):
        self.message = message
        self.code = code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Extension / size / page
# ---------------------------------------------------------------------------
def validate_extension(filename: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    ext = Path(filename).suffix.lower()
    if not ext or ext not in settings.allowed_ext_set:
        allowed = ", ".join(sorted(settings.allowed_ext_set))
        raise ValidationError(
            f"Unsupported file type '{ext}'. Allowed: {allowed}",
            code="unsupported_type",
        )
    return ext


def validate_upload_size(file: UploadFile, settings: Settings | None = None) -> int:
    """Return size in bytes; raises if over limit.

    Prefers Content-Length. When absent, returns 0 and expects the caller
    to invoke ``check_saved_file_size`` after persisting to disk.
    """
    settings = settings or get_settings()
    size_header = file.headers.get("content-length")
    if size_header is not None:
        try:
            size = int(size_header)
        except ValueError:
            size = None
        else:
            if size > settings.max_upload_bytes:
                raise ValidationError(
                    f"File exceeds max size of {settings.max_upload_bytes} bytes",
                    code="file_too_large",
                )
            return size
    return 0


def check_saved_file_size(path: str | Path, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    size = os.path.getsize(path)
    if size > settings.max_upload_bytes:
        _safe_unlink(path)
        raise ValidationError(
            f"File exceeds max size of {settings.max_upload_bytes} bytes",
            code="file_too_large",
        )
    if size == 0:
        _safe_unlink(path)
        raise ValidationError("Empty file", code="empty_file")
    return size


def validate_page_count(page_count: int, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if page_count > settings.max_pages_per_doc:
        raise ValidationError(
            f"Document has {page_count} pages; max allowed is {settings.max_pages_per_doc}",
            code="too_many_pages",
        )


# ---------------------------------------------------------------------------
# Batch limit (new)
# ---------------------------------------------------------------------------
def validate_batch_size(
    files: Iterable[UploadFile],
    settings: Settings | None = None,
) -> int:
    """Return the file count after enforcing the per-request batch cap."""
    settings = settings or get_settings()
    max_batch = getattr(settings, "max_files_per_batch", 10)
    count = sum(1 for _ in files)
    if count == 0:
        raise ValidationError("No files in upload request", code="empty_batch")
    if count > max_batch:
        raise ValidationError(
            f"Too many files in one request ({count}); max is {max_batch}",
            code="batch_too_large",
        )
    return count


# ---------------------------------------------------------------------------
# Text decoding (new)
# ---------------------------------------------------------------------------
def ensure_readable_text(
    raw: bytes,
    *,
    filename: str = "",
    settings: Settings | None = None,
) -> str:
    """Decode bytes to text with a tolerant fallback chain.

    Tries UTF-8, then UTF-8 with BOM, then latin-1. Raises if the result
    is empty or whitespace-only. Never raises UnicodeDecodeError.
    """
    settings = settings or get_settings()

    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if text.strip():
            return text
        # decoded but empty/whitespace — keep trying weaker encodings,
        # but if latin-1 succeeds and text is still empty, it really is empty
        break

    # latin-1 never fails on bytes, so if we get here the content is empty
    raise ValidationError(
        f"File '{filename}' contains no readable text",
        code="empty_text",
    )


# ---------------------------------------------------------------------------
# PDF safety (new)
# ---------------------------------------------------------------------------
_ENCRYPT_MARKER = b"/Encrypt"


def detect_encrypted_pdf(
    raw: bytes,
    *,
    filename: str = "",
) -> None:
    """Coarse pre-check for password-protected PDFs.

    Looks for the /Encrypt marker in the trailer region. Cheap and does
    not require opening the PDF. False negatives are possible (marker not
    at the tail); ``guard_pdf_open`` is the authoritative gate.
    """
    tail = raw[-2048:] if len(raw) > 2048 else raw
    if _ENCRYPT_MARKER in tail:
        raise ValidationError(
            f"PDF '{filename}' appears to be password-protected",
            code="encrypted_pdf",
        )


def guard_pdf_open(reader_factory):
    """Wrap a callable that opens a PdfReader.

    Usage::

        reader = guard_pdf_open(lambda: PdfReader(io.BytesIO(raw)))

    Raises ``ValidationError`` for encrypted or corrupted PDFs instead of
    letting PyPDF-specific exceptions bubble up.
    """
    try:
        return reader_factory()
    except Exception as exc:  # pypdf raises a family of these
        name = type(exc).__name__
        if "Decrypt" in name or "Password" in name:
            raise ValidationError(
                "PDF is password-protected",
                code="encrypted_pdf",
            ) from exc
        if "PdfRead" in name or "PdfStream" in name or "EOF" in name:
            raise ValidationError(
                f"PDF is corrupted or malformed: {exc}",
                code="corrupt_pdf",
            ) from exc
        raise ValidationError(
            f"Failed to read PDF: {exc}",
            code="pdf_read_error",
        ) from exc


# ---------------------------------------------------------------------------
# Composite helper (new)
# ---------------------------------------------------------------------------
def validate_upload(
    file: UploadFile,
    settings: Settings | None = None,
) -> tuple[str, int]:
    """Run extension + header size check in one call.

    Returns ``(extension, declared_size)``. ``declared_size`` is 0 when
    Content-Length was absent; the caller then must invoke
    ``check_saved_file_size`` after persisting to disk.
    """
    settings = settings or get_settings()
    ext = validate_extension(file.filename or "", settings=settings)
    size = validate_upload_size(file, settings=settings)
    return ext, size


# ---------------------------------------------------------------------------
# HTTP mapping
# ---------------------------------------------------------------------------
def validation_to_http(exc: ValidationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "message": exc.message,
            "code": getattr(exc, "code", "validation_error"),
        },
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _safe_unlink(path: str | Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


__all__ = [
    "ValidationError",
    "validate_extension",
    "validate_upload_size",
    "check_saved_file_size",
    "validate_page_count",
    "validate_batch_size",
    "ensure_readable_text",
    "detect_encrypted_pdf",
    "guard_pdf_open",
    "validate_upload",
    "validation_to_http",
]