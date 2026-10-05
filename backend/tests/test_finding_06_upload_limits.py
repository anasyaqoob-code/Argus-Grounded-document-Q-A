"""Finding #6 (Medium): upload safety — size, pages, batch, encoding, PDF.

Regression guard for:
"There are no explicit file-size, page-count, encrypted-PDF, encoding,
or batch limits."

Fix: ``validation.py`` exposes validate_extension, validate_upload,
check_saved_file_size, validate_page_count, validate_batch_size,
ensure_readable_text, detect_encrypted_pdf, guard_pdf_open.

This file exercises every one of those guard rails through the public
API.
"""

from __future__ import annotations

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
)


class _FakeUploadFile:
    def __init__(self, filename, content_length=None):
        self.filename = filename
        self.headers = (
            {"content-length": str(content_length)}
            if content_length is not None
            else {}
        )


# --- extension --------------------------------------------------------
def test_extension_pdf_ok():
    assert validate_extension("doc.PDF") == ".pdf"


def test_extension_rejects_executable():
    with pytest.raises(ValidationError) as ei:
        validate_extension("malware.exe")
    assert ei.value.code == "unsupported_type"


# --- size -------------------------------------------------------------
def test_size_rejects_oversize(tmp_path):
    p = tmp_path / "big.txt"
    p.write_bytes(b"x" * 200)
    with pytest.raises(ValidationError) as ei:
        check_saved_file_size(p, settings=Settings(max_upload_bytes=100))
    assert ei.value.code == "file_too_large"
    assert not p.exists()


def test_size_rejects_empty(tmp_path):
    p = tmp_path / "empty.txt"
    p.touch()
    with pytest.raises(ValidationError) as ei:
        check_saved_file_size(p)
    assert ei.value.code == "empty_file"


# --- page count -------------------------------------------------------
def test_page_count_enforced():
    settings = Settings(max_pages_per_doc=5)
    validate_page_count(5, settings)  # boundary OK
    with pytest.raises(ValidationError) as ei:
        validate_page_count(6, settings)
    assert ei.value.code == "too_many_pages"


# --- batch ------------------------------------------------------------
def test_batch_empty_rejected():
    with pytest.raises(ValidationError) as ei:
        validate_batch_size([])
    assert ei.value.code == "empty_batch"


def test_batch_too_large_rejected():
    settings = Settings(max_files_per_batch=2)
    files = [_FakeUploadFile(f"f{i}.txt") for i in range(5)]
    with pytest.raises(ValidationError) as ei:
        validate_batch_size(files, settings=settings)
    assert ei.value.code == "batch_too_large"


# --- encoding ---------------------------------------------------------
def test_encoding_utf8_ok():
    assert ensure_readable_text(b"hello") == "hello"


def test_encoding_latin1_fallback():
    raw = "café".encode("latin-1")
    assert "caf" in ensure_readable_text(raw)


def test_encoding_rejects_whitespace_only():
    with pytest.raises(ValidationError) as ei:
        ensure_readable_text(b"   \n\t  ")
    assert ei.value.code == "empty_text"


# --- encrypted PDF ----------------------------------------------------
def test_encrypted_pdf_detected():
    raw = b"%PDF-1.4\nbody\n/Encrypt 5 0 R\n%%EOF"
    with pytest.raises(ValidationError) as ei:
        detect_encrypted_pdf(raw, filename="secret.pdf")
    assert ei.value.code == "encrypted_pdf"


def test_clean_pdf_passes():
    raw = b"%PDF-1.4\nbody\n%%EOF"
    detect_encrypted_pdf(raw, filename="ok.pdf")  # no raise


def test_guarded_pdf_open_encrypted():
    class FileNotDecryptedError(Exception):
        pass

    with pytest.raises(ValidationError) as ei:
        guard_pdf_open(lambda: (_ for _ in ()).throw(FileNotDecryptedError()))
    assert ei.value.code == "encrypted_pdf"


def test_guarded_pdf_open_corrupt():
    class PdfReadError(Exception):
        pass

    with pytest.raises(ValidationError) as ei:
        guard_pdf_open(lambda: (_ for _ in ()).throw(PdfReadError()))
    assert ei.value.code == "corrupt_pdf"


# --- composite --------------------------------------------------------
def test_validate_upload_too_large_header():
    f = _FakeUploadFile("a.pdf", content_length=10**12)
    with pytest.raises(ValidationError) as ei:
        validate_upload(f)
    assert ei.value.code == "file_too_large"
    