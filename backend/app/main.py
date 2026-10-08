"""FastAPI application and routes for Argus."""

from __future__ import annotations
from pathlib import Path as _Path
from dotenv import load_dotenv

# Anchor .env to backend/.env regardless of the CWD uvicorn is launched
# from. Without this, running `uvicorn app.main:app` from any directory
# other than backend/ leaves every env var unset — which surfaces as
# "Google OAuth is not configured" from /auth/google/start, and as a
# silent "RESEND_API_KEY not set" warning when sending reset emails.
_ENV_PATH = _Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Iterator, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

from . import __version__
from . import auth
from . import storage
from . import password_reset
from . import google_auth
from .agent_state import AgentSettings
from .config import get_settings
from .rag_engine import get_rag_engine
from .vision import extract_questions_from_image
from .voice import router as voice_router
from .schemas import (
    AnswerResponse,
    ChatMessageResponse,
    Citation as CitationSchema,
    DocumentInfo,
    DocumentStatus,
    ErrorResponse,
    HealthResponse,
    QueryRequest,
    SessionHistoryResponse,
    SessionInfo,
    SessionListResponse,
    StreamEvent,
    UploadResponse,
)
from .storage import DEFAULT_USER_ID, get_storage
from .validation import (
    ValidationError,
    check_saved_file_size,
    detect_encrypted_pdf,
    validate_batch_size,
    validate_extension,
    validate_page_count,
    validate_upload,
    validation_to_http,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("argus")

_settings = get_settings()
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
IMAGE_DIR = UPLOAD_DIR / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# Ensure the schema exists before the first request. The startup
# handler also calls this, but doing it here guarantees the users
# table exists even under --reload restarts.
try:
    storage.init_db()
except Exception:
    logger.exception("init_db at import failed")


# ---------------------------------------------------------------------------
# Auth request bodies
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title=_settings.app_name,
    version=__version__,
    docs_url="/docs",
)

# CORS with credentials requires a specific origin list — the wildcard
# "*" is incompatible with allow_credentials=True and will cause the
# browser to silently drop the Set-Cookie header.
#
# The two localhost origins are always allowed so local development
# works unchanged. FRONTEND_URL is added at import time if set, so
# the deployed frontend's origin (e.g. https://argus.up.railway.app)
# is also accepted without needing to edit this file per environment.
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

_frontend_url = (os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
if _frontend_url and _frontend_url not in CORS_ORIGINS:
    CORS_ORIGINS.append(_frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve persisted chat images. Mounted under the API prefix so the
# relative URLs stored in message metadata stay portable.
app.mount(
    f"{_settings.api_prefix}/images",
    StaticFiles(directory=str(IMAGE_DIR)),
    name="images",
)

# Voice input — POST /api/v1/transcribe
app.include_router(voice_router)

# Password reset — POST /api/v1/auth/forgot-password
#                  POST /api/v1/auth/reset-password
app.include_router(password_reset.router, prefix=_settings.api_prefix)

# Google OAuth — GET /api/v1/auth/google/start
#                GET /api/v1/auth/google/callback
app.include_router(google_auth.router, prefix=_settings.api_prefix)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
def current_user(request: Request) -> str:
    """Return the authenticated user id from the JWT cookie.

    Raises 401 if the cookie is missing, malformed, or expired. The
    DEFAULT_USER_ID fallback is intentionally gone — every route that
    depends on this function now requires a valid session.
    """
    token = request.cookies.get(auth.COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        return auth.decode_jwt(token)
    except auth.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def require_admin(user_id: str = Depends(current_user)) -> str:
    """Dependency for admin-only routes.

    Wraps ``current_user`` so a non-admin gets a 403 rather than a 401.
    The distinction matters: 401 means "you aren't logged in", 403 means
    "you're logged in, but not allowed here."
    """
    storage_mod = get_storage()
    if not storage_mod.is_admin(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _SavedFileAdapter:
    """Adapts an on-disk path into the shape ``load_uploaded_documents``
    expects: ``.name`` and ``.getvalue()``.
    """

    def __init__(self, path: Path, name: str):
        self._path = path
        self.name = name

    def getvalue(self) -> bytes:
        return self._path.read_bytes()


def _doc_status(value: str) -> DocumentStatus:
    try:
        return DocumentStatus(value)
    except ValueError:
        return DocumentStatus.pending


def _to_document_info(row) -> DocumentInfo:
    return DocumentInfo(
        document_id=row.document_id,
        filename=row.filename,
        status=_doc_status(row.status),
        page_count=row.page_count,
        chunk_count=row.chunk_count,
        created_at=None,
        error=row.error,
    )


def _resolve_document_filenames(
    document_ids: Optional[list[str]],
    user_id: str,
) -> Optional[list[str]]:
    """Translate incoming document UUIDs (from /documents) into the
    filenames the RAG engine indexes chunks under.
    """
    if not document_ids:
        return None

    storage_mod = get_storage()
    filenames: list[str] = []
    for doc_uuid in document_ids:
        row = storage_mod.get_document(doc_uuid, user_id=user_id)
        if row and row.filename and row.filename not in filenames:
            filenames.append(row.filename)

    return filenames or None


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
def _set_session_cookie(response: Response, user_id: str) -> None:
    """Attach the JWT as an HTTP-only cookie.

    Local development uses ``secure=False`` so the cookie works over
    plain HTTP on localhost. In production (Railway, behind HTTPS) we
    flip to ``secure=True`` so the browser refuses to send the cookie
    over plain HTTP. The switch is driven by the ``ENV`` variable —
    set ``ENV=production`` in Railway, leave it unset locally.
    """
    is_prod = (os.getenv("ENV") or "").strip().lower() == "production"
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=auth.create_jwt(user_id),
        httponly=True,
        samesite="none",
        secure=is_prod,
        max_age=auth.JWT_EXPIRE_DAYS * 24 * 3600,
        path="/",
    )


def _user_payload(user_id: str, email: str, is_admin: bool = False) -> dict:
    return {"user_id": user_id, "email": email, "is_admin": bool(is_admin)}


@app.post(f"{_settings.api_prefix}/auth/register")
def auth_register(
    body: RegisterRequest,
    response: Response,
) -> dict:
    """Create a new account. Also migrates any pre-auth 'anon' data."""
    storage_mod = get_storage()

    existing = storage_mod.get_user_by_email(body.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )

    password_hash = auth.hash_password(body.password)
    new_user_id = storage_mod.create_user(body.email, password_hash)
    if not new_user_id:
        # Race condition: another request created the same email in
        # the window between our check and the insert.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )

    # First registration migrates any pre-auth data into this account.
    try:
        storage_mod.migrate_anon_data_to_user(new_user_id)
    except Exception:
        logger.exception("Failed to migrate anon data on register")

    # Analytics — record the signup. Best-effort; never blocks auth.
    storage_mod.record_auth_event(new_user_id, "signup")

    _set_session_cookie(response, new_user_id)
    is_admin = storage_mod.is_admin(new_user_id)
    return _user_payload(new_user_id, body.email, is_admin)


@app.post(f"{_settings.api_prefix}/auth/login")
def auth_login(
    body: LoginRequest,
    response: Response,
) -> dict:
    """Verify credentials and set the session cookie."""
    storage_mod = get_storage()

    row = storage_mod.get_user_by_email(body.email)
    if not row or not auth.verify_password(
        body.password, row["password_hash"]
    ):
        # Same message for "no such user" and "wrong password" — do
        # not leak which one was wrong.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Analytics — record the login. Best-effort.
    storage_mod.record_auth_event(row["id"], "login")

    _set_session_cookie(response, row["id"])
    is_admin = storage_mod.is_admin(row["id"])
    return _user_payload(row["id"], row["email"], is_admin)


@app.post(f"{_settings.api_prefix}/auth/logout")
def auth_logout(
    response: Response,
    user_id: str = Depends(current_user),
) -> dict:
    """Clear the session cookie and record the logout event.

    Requires a valid session now — the previous version cleared the
    cookie unconditionally, which was harmless but left us blind to
    logout frequency in analytics.
    """
    storage_mod = get_storage()
    storage_mod.record_auth_event(user_id, "logout")
    response.delete_cookie(
        key=auth.COOKIE_NAME,
        path="/",
    )
    return {"ok": True}


@app.get(f"{_settings.api_prefix}/auth/me")
def auth_me(user_id: str = Depends(current_user)) -> dict:
    """Return the current user, or 401 if not logged in."""
    storage_mod = get_storage()
    row = storage_mod.get_user_by_id(user_id)
    if not row:
        # The cookie was valid, but the user row was deleted. Treat
        # this as unauthenticated.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account no longer exists",
        )
    is_admin = storage_mod.is_admin(user_id)
    return _user_payload(row["id"], row["email"], is_admin)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


# ---------------------------------------------------------------------------
# Upload + document registry
# ---------------------------------------------------------------------------
@app.post(
    f"{_settings.api_prefix}/upload",
    response_model=UploadResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Depends(current_user),
) -> UploadResponse:
    """Persist a single uploaded file, build its index entry, register it."""
    storage_mod = get_storage()
    engine = get_rag_engine()

    try:
        ext, _declared = validate_upload(file, settings=_settings)
    except ValidationError as e:
        raise validation_to_http(e) from e

    doc_id = uuid.uuid4().hex
    safe_name = Path(file.filename or "doc").name
    dest = UPLOAD_DIR / f"{doc_id}_{safe_name}"

    try:
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as exc:
        logger.exception("Upload write failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist upload: {exc}",
        ) from exc

    try:
        check_saved_file_size(dest, settings=_settings)
        raw = dest.read_bytes()
        if ext == ".pdf":
            detect_encrypted_pdf(raw, filename=safe_name)
    except ValidationError as e:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise validation_to_http(e) from e

    storage_mod.create_document(
        filename=safe_name,
        path=str(dest),
        document_id=doc_id,
        status="pending",
        user_id=user_id,
    )

    try:
        storage_mod.update_document(doc_id, status="indexing", user_id=user_id)

        saved = _SavedFileAdapter(dest, safe_name)
        stats = engine.build_index([saved])

        page_count = stats.get("pages_by_file", {}).get(safe_name, 0)
        chunk_count = stats.get("document_records", [])
        chunk_count = next(
            (rec.chunks for rec in chunk_count if rec.name == safe_name), 0
        )
        try:
            validate_page_count(page_count, settings=_settings)
        except ValidationError as e:
            storage_mod.update_document(
                doc_id, status="failed", error=e.message, user_id=user_id
            )
            raise validation_to_http(e) from e

        storage_mod.update_document(
            doc_id,
            status="ready",
            page_count=page_count,
            chunk_count=chunk_count,
            user_id=user_id,
        )
        status_out = DocumentStatus.ready
        msg = f"Indexed {chunk_count} chunks from {page_count} page(s)"
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Indexing failed")
        storage_mod.update_document(
            doc_id, status="failed", error=str(exc), user_id=user_id
        )
        status_out = DocumentStatus.failed
        msg = f"Indexing failed: {exc}"

    return UploadResponse(
        document_id=doc_id,
        filename=safe_name,
        status=status_out,
        message=msg,
    )


@app.post(
    f"{_settings.api_prefix}/upload/batch",
    response_model=list[UploadResponse],
)
async def upload_batch(
    files: list[UploadFile] = File(...),
    user_id: str = Depends(current_user),
) -> list[UploadResponse]:
    try:
        validate_batch_size(files, settings=_settings)
    except ValidationError as e:
        raise validation_to_http(e) from e

    out: list[UploadResponse] = []
    for f in files:
        out.append(await upload_document(file=f, user_id=user_id))
    return out


@app.get(
    f"{_settings.api_prefix}/documents",
    response_model=list[DocumentInfo],
)
def list_documents(user_id: str = Depends(current_user)) -> list[DocumentInfo]:
    storage_mod = get_storage()
    return [
        _to_document_info(d)
        for d in storage_mod.list_documents(user_id=user_id)
    ]


@app.get(
    f"{_settings.api_prefix}/documents/{{document_id}}",
    response_model=DocumentInfo,
    responses={404: {"model": ErrorResponse}},
)
def get_document(
    document_id: str,
    user_id: str = Depends(current_user),
) -> DocumentInfo:
    storage_mod = get_storage()
    row = storage_mod.get_document(document_id, user_id=user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_document_info(row)


@app.delete(
    f"{_settings.api_prefix}/documents/{{document_id}}",
    responses={404: {"model": ErrorResponse}},
)
def delete_document(
    document_id: str,
    purge_conversations: bool = Query(
        False,
        description=(
            "When true, also delete every conversation whose messages "
            "cited this document. Off by default to preserve chat history."
        ),
    ),
    user_id: str = Depends(current_user),
) -> dict:
    storage_mod = get_storage()
    engine = get_rag_engine()

    row = storage_mod.get_document(document_id, user_id=user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    deleted_sessions: list[str] = []
    if purge_conversations:
        try:
            deleted_sessions = storage_mod.sessions_referencing_document(
                row.filename, row.document_id, user_id=user_id
            )
        except Exception:
            logger.exception(
                "Failed to find sessions referencing document %s",
                row.document_id,
            )
            deleted_sessions = []

        for sid in deleted_sessions:
            try:
                storage_mod.delete_session(sid, user_id=user_id)
            except Exception:
                logger.exception("Failed to delete session %s", sid)

    # Existing document deletion path — unchanged.
    try:
        engine.delete_document(row.filename)
    except Exception:
        logger.exception("Engine delete_document failed (continuing)")

    if row.path:
        try:
            Path(row.path).unlink(missing_ok=True)
        except OSError:
            pass

    storage_mod.delete_document(document_id, user_id=user_id)

    return {
        "ok": True,
        "document_id": document_id,
        "deleted_sessions": deleted_sessions,
    }


# ---------------------------------------------------------------------------
# Query — non-streaming JSON
# ---------------------------------------------------------------------------
@app.post(
    f"{_settings.api_prefix}/query",
    response_model=AnswerResponse,
)
async def query(
    req: QueryRequest,
    user_id: str = Depends(current_user),
) -> AnswerResponse:
    storage_mod = get_storage()
    engine = get_rag_engine()

    session_id = storage_mod.get_or_create_session(
        req.session_id, user_id=user_id
    )

    agent = AgentSettings.from_request(
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        top_k=req.top_k,
        score_threshold=req.score_threshold,
        require_citations=req.require_citations,
        allow_abstain=req.allow_abstain,
    )

    engine_document_ids = _resolve_document_filenames(req.document_ids, user_id)

    result = engine.run(
        req.query,
        session_id=session_id,
        agent=agent,
        document_ids=engine_document_ids,
        user_id=user_id,
    )

    return AnswerResponse(
        answer=result.answer,
        citations=[
            CitationSchema(
                document_id=c.document_id,
                filename=c.filename,
                page=c.page,
                chunk_id=c.chunk_id,
                quote=c.quote,
                score=c.score,
            )
            for c in result.citations
        ],
        abstained=result.abstained,
        abstain_reason=result.abstain_reason,
        session_id=session_id,
        confidence=result.confidence,
        metadata=result.metadata,
    )


# ---------------------------------------------------------------------------
# Query — SSE streaming
# ---------------------------------------------------------------------------
def _sse(events: Iterator[dict]) -> Iterator[str]:
    """Serialize each event dict as an SSE `data:` line."""
    for ev in events:
        try:
            payload = json.dumps(ev, default=str)
        except Exception as exc:
            payload = json.dumps(
                {
                    "type": "error",
                    "data": {"detail": str(exc), "code": "serialize"},
                }
            )
        yield f"data: {payload}\n\n"
    yield "data: {\"type\": \"done\"}\n\n"


@app.post(f"{_settings.api_prefix}/query/stream")
async def query_stream(
    req: QueryRequest,
    user_id: str = Depends(current_user),
) -> StreamingResponse:
    storage_mod = get_storage()
    engine = get_rag_engine()

    session_id = storage_mod.get_or_create_session(
        req.session_id, user_id=user_id
    )

    agent = AgentSettings.from_request(
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        top_k=req.top_k,
        score_threshold=req.score_threshold,
        require_citations=req.require_citations,
        allow_abstain=req.allow_abstain,
    )

    engine_document_ids = _resolve_document_filenames(req.document_ids, user_id)

    events = engine.stream(
        req.query,
        session_id=session_id,
        agent=agent,
        document_ids=engine_document_ids,
        user_id=user_id,
    )
    return StreamingResponse(
        _sse(events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session_id,
        },
    )


# ---------------------------------------------------------------------------
# Query — image (vision-driven batch Q&A)
# ---------------------------------------------------------------------------
@app.post(f"{_settings.api_prefix}/query/image")
async def query_image(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    document_ids: Optional[str] = Form(None),
    user_id: str = Depends(current_user),
) -> StreamingResponse:
    """Image-based Q&A. Persists the image, extracts questions via Groq
    Vision, then answers each from the loaded documents. Streams SSE
    events and persists every answer so the batch survives a page reload.
    """
    engine = get_rag_engine()
    storage_mod = get_storage()

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file must be an image.",
        )

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image.")

    # Persist the image to disk before the vision call — if extraction
    # fails we still want the user's upload to be recoverable, and the
    # URL needs to exist by the time the frontend renders it.
    image_id = uuid.uuid4().hex
    image_path = IMAGE_DIR / f"img_{image_id}.jpg"
    try:
        image_path.write_bytes(image_bytes)
    except OSError as exc:
        logger.exception("Failed to persist image")
        raise HTTPException(
            status_code=500, detail=f"Failed to save image: {exc}"
        ) from exc

    image_url = f"{_settings.api_prefix}/images/img_{image_id}.jpg"

    try:
        questions = extract_questions_from_image(image_bytes)
    except ValueError as exc:
        # Clean up the orphaned file before surfacing the error.
        try:
            image_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail=str(exc))

    sid = storage_mod.get_or_create_session(session_id, user_id=user_id)

    # Capture the persisted message_id so the SSE `questions` event can
    # carry it. Without this, the frontend can't attach feedback to the
    # batch until the session is reloaded.
    image_message_id = 0
    try:
        image_message_id = storage_mod.add_message(
            sid,
            "user",
            f"[image] {len(questions)} question(s) extracted",
            metadata={
                "image_upload": True,
                "image_id": image_id,
                "image_url": image_url,
                "question_count": len(questions),
            },
            user_id=user_id,
        ) or 0
    except Exception:
        logger.exception("Failed to persist image message")

    doc_id_list = (
        [d for d in document_ids.split(",") if d] if document_ids else None
    )
    engine_document_ids = _resolve_document_filenames(doc_id_list, user_id)

    def event_stream() -> Iterator[str]:
        # Mirror every answer_done into storage as an assistant message
        # so the batch is reconstructable on session reload.
        for evt in engine.stream_batch(
            questions,
            sid,
            document_ids=engine_document_ids,
            user_id=user_id,
        ):
            # Mutate first — the payload is serialized *after* every
            # augmentation, otherwise the client never sees them.
            if evt["type"] == "questions":
                # Surface the URL and the persisted message id so the
                # client can render the image and wire feedback without
                # a second round-trip.
                evt.setdefault("data", {})
                evt["data"]["image_url"] = image_url
                evt["data"]["message_id"] = image_message_id

            if evt["type"] == "answer_done":
                data = evt.get("data") or {}
                # Skip persistence for unanswered questions — an empty
                # row with no content would render as a blank bubble on
                # reload and pushes the batch's citation pills out of
                # alignment. Not-covered answers are also skipped: the
                # question text itself is already persisted on the user
                # image message, so the batch reconstructs with a
                # "Not covered" placeholder without needing a row.
                answer_text = str(data.get("answer", "")).strip()
                if answer_text and not data.get("not_covered", False):
                    try:
                        qid = int(data.get("id", 0))
                        q_index = qid - 1
                        q_text = (
                            questions[q_index]["text"]
                            if 0 <= q_index < len(questions)
                            else ""
                        )
                        storage_mod.add_message(
                            sid,
                            "assistant",
                            answer_text,
                            metadata={
                                "image_answer": True,
                                "image_id": image_id,
                                "question_id": qid,
                                "question_text": q_text,
                                "citations": data.get("citations") or [],
                                "not_covered": False,
                            },
                            user_id=user_id,
                        )
                    except Exception:
                        logger.exception("Failed to persist image answer")

            try:
                payload = json.dumps(evt["data"], default=str)
            except Exception as exc:
                payload = json.dumps(
                    {"detail": str(exc), "code": "serialize"}
                )

            yield f"event: {evt['type']}\ndata: {payload}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-Id": sid,
        },
    )


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
@app.get(
    f"{_settings.api_prefix}/sessions",
    response_model=SessionListResponse,
)
def list_sessions(
    user_id: str = Depends(current_user),
) -> SessionListResponse:
    storage_mod = get_storage()
    rows = storage_mod.list_sessions(user_id=user_id)
    out = []
    for r in rows:
        try:
            from datetime import datetime

            created = datetime.fromtimestamp(r["created_at"])
            updated = datetime.fromtimestamp(r["updated_at"])
        except Exception:
            created = updated = None  # type: ignore[assignment]
        out.append(
            SessionInfo(
                session_id=r["id"],
                title=r["title"],
                created_at=created,
                updated_at=updated,
                message_count=len(
                    storage_mod.get_messages(r["id"], user_id=user_id)
                ),
            )
        )
    return SessionListResponse(sessions=out)


@app.get(
    f"{_settings.api_prefix}/sessions/{{session_id}}",
    response_model=SessionHistoryResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_session(
    session_id: str,
    user_id: str = Depends(current_user),
) -> SessionHistoryResponse:
    storage_mod = get_storage()
    sessions = {
        s["id"]: s for s in storage_mod.list_sessions(user_id=user_id)
    }
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    from datetime import datetime

    rows = storage_mod.get_messages(session_id, user_id=user_id)
    messages = [
        ChatMessageResponse(
            message_id=r["id"],
            role=r["role"],
            content=r["content"],
            created_at=datetime.fromtimestamp(r["created_at"]),
            metadata=r.get("metadata") or {},
        )
        for r in rows
    ]
    return SessionHistoryResponse(
        session_id=session_id,
        title=sessions[session_id]["title"],
        messages=messages,
    )


@app.patch(
    f"{_settings.api_prefix}/sessions/{{session_id}}",
    response_model=SessionInfo,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def rename_session(
    session_id: str,
    payload: dict,
    user_id: str = Depends(current_user),
) -> SessionInfo:
    storage_mod = get_storage()
    if not storage_mod.session_exists(session_id, user_id=user_id):
        raise HTTPException(status_code=404, detail="Session not found")

    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    title = title[:80]

    storage_mod.rename_session(session_id, title, user_id=user_id)

    from datetime import datetime

    sessions = {
        s["id"]: s for s in storage_mod.list_sessions(user_id=user_id)
    }
    row = sessions.get(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session vanished")

    try:
        created = datetime.fromtimestamp(row["created_at"])
        updated = datetime.fromtimestamp(row["updated_at"])
    except Exception:
        created = updated = None  # type: ignore[assignment]

    return SessionInfo(
        session_id=row["id"],
        title=row["title"],
        created_at=created,
        updated_at=updated,
        message_count=len(
            storage_mod.get_messages(session_id, user_id=user_id)
        ),
    )


@app.delete(
    f"{_settings.api_prefix}/sessions/{{session_id}}",
    responses={404: {"model": ErrorResponse}},
)
def delete_session(
    session_id: str,
    user_id: str = Depends(current_user),
) -> dict:
    storage_mod = get_storage()
    if not storage_mod.session_exists(session_id, user_id=user_id):
        raise HTTPException(status_code=404, detail="Session not found")

    # Collect image ids *before* deleting the rows that reference them.
    image_ids = storage_mod.session_image_ids(session_id, user_id=user_id)

    storage_mod.delete_session(session_id, user_id=user_id)

    for img_id in image_ids:
        try:
            (IMAGE_DIR / f"img_{img_id}.jpg").unlink(missing_ok=True)
        except OSError:
            logger.exception("Failed to unlink image %s", img_id)

    return {"ok": True, "session_id": session_id}


@app.get(f"{_settings.api_prefix}/sessions/{{session_id}}/export.md")
def export_session_md(
    session_id: str,
    user_id: str = Depends(current_user),
) -> PlainTextResponse:
    storage_mod = get_storage()
    md = storage_mod.export_session_markdown(session_id, user_id=user_id)
    if not md:
        raise HTTPException(status_code=404, detail="Session not found")
    return PlainTextResponse(md, media_type="text/markdown")


@app.get(f"{_settings.api_prefix}/sessions/{{session_id}}/export.pdf")
def export_session_pdf(
    session_id: str,
    user_id: str = Depends(current_user),
) -> Response:
    storage_mod = get_storage()
    blob = storage_mod.export_session_pdf(session_id, user_id=user_id)
    if not blob:
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(
        content=blob,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="argus_{session_id}.pdf"'
            )
        },
    )


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------
@app.post(
    f"{_settings.api_prefix}/feedback/{{message_id}}", status_code=204
)
def set_feedback(
    message_id: int,
    rating: str = Query(..., pattern="^(up|down)$"),
    user_id: str = Depends(current_user),
) -> Response:
    storage_mod = get_storage()
    storage_mod.set_feedback(message_id, rating, user_id=user_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Suggested questions
# ---------------------------------------------------------------------------
@app.post(f"{_settings.api_prefix}/suggest")
def suggest_questions(
    payload: dict,
    user_id: str = Depends(current_user),
) -> dict:
    engine = get_rag_engine()
    raw_ids = payload.get("document_ids")
    max_q = int(payload.get("max_questions", 4))

    if raw_ids:
        storage_mod = get_storage()
        translated: list[str] = []
        for ident in raw_ids:
            row = storage_mod.get_document(ident, user_id=user_id)
            if row:
                translated.append(row.filename)
            else:
                translated.append(ident)
        doc_names = translated or list(engine.document_records.keys())
    else:
        doc_names = list(engine.document_records.keys())

    if not doc_names:
        return {"questions": []}

    try:
        questions = engine.suggest_questions(doc_names, max_questions=max_q)
    except Exception as exc:
        logger.warning("suggest_questions failed: %s", exc)
        questions = []

    return {"questions": questions}


# ---------------------------------------------------------------------------
# Admin — analytics dashboard endpoints
# ---------------------------------------------------------------------------
@app.get(f"{_settings.api_prefix}/admin/stats/summary")
def admin_summary(
    days: int = Query(0, ge=0, le=3650),
    _: str = Depends(require_admin),
) -> dict:
    """Headline totals for the dashboard's summary cards.

    ``days=0`` means lifetime — every counter returns its all-time
    total. Any positive value scopes each count to rows created in the
    last N days. The range selector in the frontend sends 0 for "All"
    and 7/30/90 for the shorter windows.
    """
    storage_mod = get_storage()
    since = None if days == 0 else time.time() - (days * 86400)
    return {
        "total_users": storage_mod.count_users(since=since),
        "total_sessions": storage_mod.count_sessions_total(since=since),
        "total_messages": storage_mod.count_messages_total(since=since),
        "total_documents": storage_mod.count_documents_total(since=since),
    }


@app.get(f"{_settings.api_prefix}/admin/stats/timeseries")
def admin_timeseries(
    days: int = Query(30, ge=0, le=3650),
    _: str = Depends(require_admin),
) -> dict:
    """Per-day time series for signups, logins, and sessions created.

    ``days=0`` returns lifetime data — every day since the first event.
    """
    storage_mod = get_storage()
    return {
        "days": days,
        "signups": storage_mod.auth_events_by_day("signup", days=days),
        "logins": storage_mod.auth_events_by_day("login", days=days),
        "logouts": storage_mod.auth_events_by_day("logout", days=days),
        "sessions": storage_mod.sessions_by_day(days=days),
    }


@app.get(f"{_settings.api_prefix}/admin/stats/rag")
def admin_rag(
    days: int = Query(30, ge=0, le=3650),
    _: str = Depends(require_admin),
) -> dict:
    """Aggregate RAG evaluation metrics over the last N days.

    ``days=0`` returns lifetime metrics.
    """
    storage_mod = get_storage()
    return storage_mod.rag_metrics_aggregate(days=days)


@app.get(f"{_settings.api_prefix}/admin/stats/recent")
def admin_recent(
    limit: int = Query(50, ge=1, le=500),
    _: str = Depends(require_admin),
) -> dict:
    """Recent assistant turns with their eval metrics, for the table."""
    storage_mod = get_storage()
    return {"queries": storage_mod.recent_queries(limit=limit)}


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
def _on_startup() -> None:
    try:
        storage_mod = get_storage()
        storage_mod.init_db()
        storage_mod.delete_empty_sessions(
            max_age_seconds=300, user_id=None
        )
        storage_mod.purge_expired_password_resets()
    except Exception:
        logger.exception("startup init failed")


__all__ = ["app"]