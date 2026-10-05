"""Application settings loaded from environment variables.

Migrated from OpenAI → Groq + HuggingFace embeddings during the FastAPI
port. Old `openai_*` and `embedding_model` fields are retained as
deprecated aliases so nothing that still reads them breaks; the migrated
RAG engine reads the new Groq / HF fields exclusively.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global application settings (env / .env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # App
    # ------------------------------------------------------------------
    app_name: str = "Argus"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # ------------------------------------------------------------------
    # Frontend — used by password-reset email links and Google OAuth
    # redirect back into the SPA.
    # ------------------------------------------------------------------
    frontend_url: str = "http://localhost:5173"

    # ------------------------------------------------------------------
    # LLM — Groq (migrated from OpenAI)
    # ------------------------------------------------------------------
    groq_api_key: Optional[str] = None
    groq_base_url: Optional[str] = None
    groq_model: str = "openai/gpt-oss-120b"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048

    # Deprecated OpenAI aliases (kept for backward-compat with any code
    # that still reads them; the new engine does not).
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    llm_model: str = "gpt-4o-mini"

    # ------------------------------------------------------------------
    # Embeddings — HuggingFace (migrated from OpenAI)
    # ------------------------------------------------------------------
    huggingface_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # Deprecated alias
    embedding_model: str = "text-embedding-3-small"

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    top_k: int = 4
    score_threshold: float = 0.0
    doc_relevance_floor: float = 0.05
    max_context_tokens: int = 6000
    max_retrieval_attempts: int = 2

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------
    chunk_size: int = 800
    chunk_overlap: int = 150

    # ------------------------------------------------------------------
    # Session / memory
    # ------------------------------------------------------------------
    session_ttl_seconds: int = 3600 * 24
    memory_message_limit: int = 6

    # ------------------------------------------------------------------
    # Agent behaviour toggles
    # ------------------------------------------------------------------
    query_rewriting: bool = True
    answer_verification: bool = True
    source_citations: bool = True

    # ------------------------------------------------------------------
    # Verification / abstention
    #
    # min_citation_coverage: fraction of retrieved chunks the LLM must cite
    #   for VERIFY to pass. Small models often omit inline [Sn] markers even
    #   when they use the content, so this is 0 by default. Grounding is
    #   enforced by the token-overlap heuristic and the LLM verifier inside
    #   combine_verdicts.
    #
    # abstain_confidence_threshold: blended confidence floor below which
    #   the pipeline abstains. MiniLM cosine similarities on short chunks
    #   sit in 0.05–0.15 for relevant content, so a high threshold vetoes
    #   every answer. 0.15 catches only genuinely unsupported responses.
    # ------------------------------------------------------------------
    min_citation_coverage: float = 0.0
    abstain_confidence_threshold: float = 0.15

    # ------------------------------------------------------------------
    # Upload / validation
    # ------------------------------------------------------------------
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB
    max_pages_per_doc: int = 500
    max_files_per_batch: int = 10
    allowed_extensions: str = ".pdf,.txt,.md,.docx"

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    sqlite_path: str = "argus.db"
    chroma_path: str = "./chroma_data"

    @property
    def allowed_ext_set(self) -> set[str]:
        return {
            e.strip().lower()
            for e in self.allowed_extensions.split(",")
            if e.strip()
        }

    @property
    def groq_api_key_required(self) -> str:
        """Return the key or raise — used by the engine at construction time."""
        if not self.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is not set. Add it to your .env file."
            )
        return self.groq_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()