"""Shared fixtures for pytest.

Provides:
  - A strict tmp-DB + tmp-Chroma isolation layer (autouse).
  - Fake LLM (``mock_llm``) that patches ``app.rag_engine.ChatGroq``.
  - Fake embedding function so retrieval tests run fully offline.
  - A fresh Chroma-backed ``VectorStore`` bound to ``tmp_path``.
  - A fully-built ``AgenticRAGService`` for engine smoke tests.
  - Sample ``Chunk`` data shared across verification/citation tests.

Every test runs in isolation: nothing touches ``backend/app/data/``.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("GROQ_API_KEY", "test-key")


# ===========================================================================
# Global isolation (autouse)
# ===========================================================================
@pytest.fixture(autouse=True)
def _isolate_storage_and_chroma(tmp_path, monkeypatch):
    """Redirect storage + rag_engine data dirs into tmp_path.

    Runs for EVERY test. Ensures the live app DB and Chroma index are
    never touched by the test suite.
    """
    from app import storage, rag_engine

    tmp_data = tmp_path
    tmp_db = tmp_path / "app.db"
    tmp_chroma = tmp_path / "chroma"
    tmp_chroma.mkdir(parents=True, exist_ok=True)
    tmp_meta = tmp_chroma / "index_meta.pkl"

    monkeypatch.setattr(storage, "DATA_DIR", tmp_data, raising=False)
    monkeypatch.setattr(storage, "DB_PATH", tmp_db, raising=False)
    monkeypatch.setattr(storage, "CHROMA_DIR", tmp_chroma, raising=False)
    storage.init_db()

    monkeypatch.setattr(rag_engine, "DATA_DIR", tmp_data, raising=False)
    monkeypatch.setattr(rag_engine, "CHROMA_DIR", tmp_chroma, raising=False)
    monkeypatch.setattr(rag_engine, "META_FILE", tmp_meta, raising=False)

    yield


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch):
    """Clear cached VectorStore / Retriever / RAG engine between tests.

    Prevents a store or engine from one test leaking into the next.
    """
    from app import retrieval, rag_engine

    retrieval.reset_singletons()
    rag_engine.reset_rag_engine()
    monkeypatch.setattr(
        retrieval, "_embedding_function_cache", None, raising=False
    )

    yield

    retrieval.reset_singletons()
    rag_engine.reset_rag_engine()


# ===========================================================================
# Fake uploaded file
# ===========================================================================
class FakeUploadedFile:
    def __init__(self, name: str, content: bytes):
        self.name = name
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


@pytest.fixture
def txt_file():
    return FakeUploadedFile(
        "sample.txt",
        (
            b"RBAC (Role-Based Access Control) assigns permissions based on roles. "
            b"ABAC (Attribute-Based Access Control) uses attributes and policies. "
            b"RBAC is simpler to manage; ABAC is more flexible for fine-grained control. "
            b"Encryption protects sensitive data at rest and in transit."
        ),
    )


@pytest.fixture
def comparison_txt():
    return FakeUploadedFile(
        "compare.txt",
        (
            b"CV workloads process images with CNNs and need high memory bandwidth. "
            b"LLM workloads process text with transformers and need large VRAM. "
            b"CV is latency-sensitive; LLM is throughput-sensitive."
        ),
    )


# ===========================================================================
# Sample chunks
# ===========================================================================
@pytest.fixture
def sample_chunks():
    """Three Chunks across two filenames. Used by verification + citation tests."""
    from app.models import Chunk

    return [
        Chunk(
            chunk_id="c1",
            document_id="alpha.txt",
            filename="alpha.txt",
            page=1,
            text=(
                "RBAC assigns permissions based on roles. "
                "It is simpler to manage than ABAC."
            ),
            score=0.92,
        ),
        Chunk(
            chunk_id="c2",
            document_id="alpha.txt",
            filename="alpha.txt",
            page=2,
            text=(
                "ABAC uses attributes and policies. "
                "It is more flexible for fine-grained control."
            ),
            score=0.81,
        ),
        Chunk(
            chunk_id="c3",
            document_id="beta.txt",
            filename="beta.txt",
            page=1,
            text=(
                "Encryption protects sensitive data at rest and in transit. "
                "It is orthogonal to access-control models."
            ),
            score=0.74,
        ),
    ]


# ===========================================================================
# Fake embedding function — deterministic, offline
# ===========================================================================
class _FakeEmbeddingFunction:
    """Deterministic 16-dim embedding from SHA-256 of the input text.

    Implements the subset of the langchain Embeddings interface that
    langchain_chroma.Chroma actually calls: ``embed_documents`` and
    ``embed_query``.
    """

    _DIM = 16

    @staticmethod
    def _vec(text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in h[: _FakeEmbeddingFunction._DIM]]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture
def fake_embedding_function():
    return _FakeEmbeddingFunction()


# ===========================================================================
# Tmp Chroma-backed VectorStore
# ===========================================================================
@pytest.fixture
def tmp_chroma_store(tmp_path, fake_embedding_function):
    """A VectorStore with an isolated Chroma collection in tmp_path."""
    from app.retrieval import VectorStore

    chroma_dir = tmp_path / "chroma_store"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    store = VectorStore(
        persist_directory=str(chroma_dir),
        embedding_function=fake_embedding_function,
    )
    yield store
    try:
        store.reset()
    except Exception:
        pass


# ===========================================================================
# Fake LLM
# ===========================================================================
@pytest.fixture
def mock_llm(monkeypatch):
    """Patch ChatGroq so no network calls occur.

    The fake consumes ``responses`` FIFO on each ``.invoke()`` / ``.stream()``
    call. Tests stage responses in the exact order the agent will call them.

    Directives honored:
      - ``bind_tools()`` raises — engine must never regress into native
        tool-calling. A failing test with this error means the engine broke
        the contract.
      - ``stream()`` and ``invoke()`` share the same response queue, so tests
        can interleave decision JSON with streamed answer text.
    """

    class FakeLLM:
        def __init__(self, *args, **kwargs):
            self.responses: list[str] = []
            self.calls: list = []

        def push(self, *responses: str) -> "FakeLLM":
            self.responses.extend(responses)
            return self

        def bind_tools(self, *args, **kwargs):
            raise AssertionError(
                "ChatGroq.bind_tools() was called. Argus must never use "
                "native tool-calling — the controller is a pure Python state "
                "machine."
            )

        def invoke(self, messages):
            self.calls.append(messages)
            if not self.responses:
                content = '{"is_sufficient": true, "summary": "ok", "passed": true}'
            else:
                content = self.responses.pop(0)
            m = MagicMock()
            m.content = content
            m.tool_calls = []
            return m

        def stream(self, messages):
            self.calls.append(messages)
            content = self.responses.pop(0) if self.responses else "streamed answer"
            parts = content.split(" ")
            for i, tok in enumerate(parts):
                suffix = " " if i < len(parts) - 1 else ""
                yield MagicMock(content=tok + suffix)

    fake = FakeLLM()

    from app import rag_engine

    monkeypatch.setattr(rag_engine, "ChatGroq", lambda *a, **k: fake)
    return fake


# ===========================================================================
# Fully-built engine (for engine smoke tests)
# ===========================================================================
@pytest.fixture
def built_engine(monkeypatch, tmp_path, fake_embedding_function, mock_llm, txt_file):
    """An AgenticRAGService with a built index over ``txt_file``.

    - ``ChatGroq`` is patched with ``mock_llm``.
    - Chroma writes to ``tmp_path / "chroma"``.
    - Embedding function is the fake (offline).

    Usage:
        engine = built_engine
        engine.ask("What is RBAC?")
    """
    from app import rag_engine, retrieval

    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(rag_engine, "CHROMA_DIR", chroma_dir, raising=False)
    monkeypatch.setattr(rag_engine, "META_FILE", chroma_dir / "index_meta.pkl", raising=False)

    # Replace VectorStore's default embedding function with the fake.
    import app.retrieval as _retrieval

    original_vs_init = _retrieval.VectorStore.__init__

    def patched_init(self, *, persist_directory=None, collection_name=None, embedding_function=None):
        original_vs_init(
            self,
            persist_directory=persist_directory,
            collection_name=collection_name,
            embedding_function=embedding_function or fake_embedding_function,
        )

    monkeypatch.setattr(_retrieval.VectorStore, "__init__", patched_init)

    # Replace the cached default embedding function so VectorStore
    # constructed without an explicit embedding_function still uses the fake.
    monkeypatch.setattr(_retrieval, "_default_embedding_function", lambda: fake_embedding_function, raising=False)
    monkeypatch.setattr(_retrieval, "_embedding_function_cache", fake_embedding_function, raising=False)

    retrieval.reset_singletons()
    rag_engine.reset_rag_engine()

    engine = rag_engine.AgenticRAGService()
    engine.build_index([txt_file])

    yield engine

    retrieval.reset_singletons()
    rag_engine.reset_rag_engine()


__all__ = [
    "FakeUploadedFile",
    "txt_file",
    "comparison_txt",
    "sample_chunks",
    "fake_embedding_function",
    "tmp_chroma_store",
    "mock_llm",
    "built_engine",
]