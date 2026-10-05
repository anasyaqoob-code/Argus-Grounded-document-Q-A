"""Tests for upload validation — size, type, pages, batch, encoding, PDF."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest

from app.config import Settings
from app.validation import (
    ValidationError,
    check_saved_file_size,
    detect_encrypted_pdf,
    ensure_readable_text,
    guard_pdf_open,
    validate_batch_size,
    validate_extension,
    validate_page_count,
    validate_upload,
    validation_to_http,
)


# ---------------------------------------------------------------------------
# Fake UploadFile — enough surface for the validators
# ---------------------------------------------------------------------------
class FakeUploadFile:
    def __init__(self, filename: str, content_length: Optional[int] = None):
        self.filename = filename
        self.headers = (
            {"content-length": str(content_length)}
            if content_length is not None
            else {}
        )
        self._content = b""


# ---------------------------------------------------------------------------
# Extension
# ---------------------------------------------------------------------------
def test_validate_extension_ok():
    assert validate_extension("report.PDF") == ".pdf"
    assert validate_extension("notes.txt") == ".txt"


def test_validate_extension_rejects():
    with pytest.raises(ValidationError) as ei:
        validate_extension("malware.exe")
    assert ei.value.code == "unsupported_type"


def test_validate_extension_no_suffix():
    with pytest.raises(ValidationError) as ei:
        validate_extension("noext")
    assert ei.value.code == "unsupported_type"


# ---------------------------------------------------------------------------
# Saved-file size
# ---------------------------------------------------------------------------
def test_check_saved_file_size_ok(tmp_path):
    p = tmp_path / "small.txt"
    p.write_text("hello")
    size = check_saved_file_size(p)
    assert size == 5


def test_check_saved_file_size_too_large(tmp_path):
    p = tmp_path / "big.bin"
    p.write_bytes(b"x" * 100)
    settings = Settings(max_upload_bytes=50)
    with pytest.raises(ValidationError) as ei:
        check_saved_file_size(p, settings=settings)
    assert ei.value.code == "file_too_large"
    assert not p.exists()  # cleaned up


def test_check_empty_file(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("")
    with pytest.raises(ValidationError) as ei:
        check_saved_file_size(p)
    assert ei.value.code == "empty_file"
    assert not p.exists()


# ---------------------------------------------------------------------------
# Page count
# ---------------------------------------------------------------------------
def test_page_count_limit():
    settings = Settings(max_pages_per_doc=10)
    validate_page_count(5, settings)
    with pytest.raises(ValidationError) as ei:
        validate_page_count(11, settings)
    assert ei.value.code == "too_many_pages"


def test_page_count_exact_limit_ok():
    settings = Settings(max_pages_per_doc=10)
    validate_page_count(10, settings)  # no raise


# ---------------------------------------------------------------------------
# Batch size
# ---------------------------------------------------------------------------
def test_batch_size_empty_rejected():
    with pytest.raises(ValidationError) as ei:
        validate_batch_size([])
    assert ei.value.code == "empty_batch"


def test_batch_size_ok():
    files = [FakeUploadFile(f"f{i}.txt") for i in range(3)]
    assert validate_batch_size(files) == 3


def test_batch_size_oversized_rejected():
    settings = Settings(max_files_per_batch=2)
    files = [FakeUploadFile(f"f{i}.txt") for i in range(5)]
    with pytest.raises(ValidationError) as ei:
        validate_batch_size(files, settings=settings)
    assert ei.value.code == "batch_too_large"


# ---------------------------------------------------------------------------
# Text decoding
# ---------------------------------------------------------------------------
def test_ensure_readable_text_utf8():
    assert ensure_readable_text(b"hello") == "hello"


def test_ensure_readable_text_utf8_bom():
    raw = "\ufeffhello".encode("utf-8")
    assert ensure_readable_text(raw) == "hello"


def test_ensure_readable_text_latin1_fallback():
    raw = "café".encode("latin-1")
    out = ensure_readable_text(raw)
    assert "caf" in out


def test_ensure_readable_text_rejects_whitespace_only():
    with pytest.raises(ValidationError) as ei:
        ensure_readable_text(b"   \n\t   ")
    assert ei.value.code == "empty_text"


# ---------------------------------------------------------------------------
# Encrypted PDF detection
# ---------------------------------------------------------------------------
def test_detect_encrypted_pdf_marker_present():
    fake = b"%PDF-1.4\nsome body\n/Encrypt 5 0 R\n%%EOF"
    with pytest.raises(ValidationError) as ei:
        detect_encrypted_pdf(fake, filename="secret.pdf")
    assert ei.value.code == "encrypted_pdf"


def test_detect_encrypted_pdf_clean():
    clean = b"%PDF-1.4\nsome body\n%%EOF"
    detect_encrypted_pdf(clean, filename="ok.pdf")  # no raise


# ---------------------------------------------------------------------------
# Guarded PDF open
# ---------------------------------------------------------------------------
def test_guard_pdf_open_success():
    called = {"n": 0}

    def factory():
        called["n"] += 1
        return "reader"

    assert guard_pdf_open(factory) == "reader"
    assert called["n"] == 1


def test_guard_pdf_open_encrypted():
    class FileNotDecryptedError(Exception):
        pass

    def factory():
        raise FileNotDecryptedError("password required")

    with pytest.raises(ValidationError) as ei:
        guard_pdf_open(factory)
    assert ei.value.code == "encrypted_pdf"


def test_guard_pdf_open_corrupt():
    class PdfReadError(Exception):
        pass

    def factory():
        raise PdfReadError("bad xref")

    with pytest.raises(ValidationError) as ei:
        guard_pdf_open(factory)
    assert ei.value.code == "corrupt_pdf"


def test_guard_pdf_open_unexpected():
    def factory():
        raise RuntimeError("weird")

    with pytest.raises(ValidationError) as ei:
        guard_pdf_open(factory)
    assert ei.value.code == "pdf_read_error"


# ---------------------------------------------------------------------------
# Composite validate_upload
# ---------------------------------------------------------------------------
def test_validate_upload_ok():
    f = FakeUploadFile("a.pdf", content_length=100)
    ext, declared = validate_upload(f)
    assert ext == ".pdf"
    assert declared == 100


def test_validate_upload_bad_extension():
    f = FakeUploadFile("a.exe")
    with pytest.raises(ValidationError) as ei:
        validate_upload(f)
    assert ei.value.code == "unsupported_type"


def test_validate_upload_too_large():
    f = FakeUploadFile("a.pdf", content_length=10**10)
    with pytest.raises(ValidationError) as ei:
        validate_upload(f)
    assert ei.value.code == "file_too_large"


# ---------------------------------------------------------------------------
# HTTP mapping
# ---------------------------------------------------------------------------
def test_validation_to_http():
    exc = ValidationError("bad", code="custom_code")
    http = validation_to_http(exc)
    assert http.status_code == 400
    assert http.detail["code"] == "custom_code"
    assert http.detail["message"] == "bad"