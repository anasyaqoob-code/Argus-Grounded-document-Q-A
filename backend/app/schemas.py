"""Pydantic request / response models for the API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class DocumentStatus(str, Enum):
    pending = "pending"
    indexing = "indexing"
    ready = "ready"
    failed = "failed"


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    status: DocumentStatus
    message: str = "Upload accepted"


class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    status: DocumentStatus
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    created_at: Optional[datetime] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Query / answer
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None
    document_ids: Optional[list[str]] = None
    top_k: Optional[int] = Field(None, ge=1, le=50)
    stream: bool = True
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=64, le=8192)
    score_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    require_citations: bool = True
    allow_abstain: bool = True

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query must not be empty")
        return v


class Citation(BaseModel):
    document_id: str
    filename: str
    page: Optional[int] = None
    chunk_id: str
    quote: str
    score: float


class AnswerResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    abstained: bool = False
    abstain_reason: Optional[str] = None
    session_id: str
    confidence: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Sessions / history
# ---------------------------------------------------------------------------
class ChatMessageResponse(BaseModel):
    message_id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionInfo(BaseModel):
    session_id: str
    title: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    message_count: int


class SessionListResponse(BaseModel):
    sessions: list[SessionInfo] = Field(default_factory=list)


class SessionHistoryResponse(BaseModel):
    session_id: str
    title: str
    messages: list[ChatMessageResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Streaming events
# ---------------------------------------------------------------------------
class StepEvent(BaseModel):
    state: str
    status: Literal["running", "complete", "failed"] = "complete"
    summary: str = ""
    duration_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenEvent(BaseModel):
    token: str
    delta: Optional[str] = None


class FinalEvent(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    abstained: bool = False
    session_id: Optional[str] = None
    response_format: str = "paragraph"
    insufficient_evidence: bool = False


class ErrorEvent(BaseModel):
    detail: str
    code: Optional[str] = None


class StreamEvent(BaseModel):
    type: Literal["step", "token", "final", "error"]
    data: Union[StepEvent, TokenEvent, FinalEvent, ErrorEvent]


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None


__all__ = [
    "DocumentStatus",
    "UploadResponse",
    "DocumentInfo",
    "QueryRequest",
    "Citation",
    "AnswerResponse",
    "ChatMessageResponse",
    "SessionInfo",
    "SessionListResponse",
    "SessionHistoryResponse",
    "StepEvent",
    "TokenEvent",
    "FinalEvent",
    "ErrorEvent",
    "StreamEvent",
    "HealthResponse",
    "ErrorResponse",
]